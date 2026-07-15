"""Tests for Field Caretaker (occupation, B141; Bubulcus Expansion; players 3+).

Card text: "When you play this card, you can immediately exchange 0/1/3 clay for
1/2/3 grain. This card is a field."

Two pieces: a card-field registration (counts as 1 field, sowable grain/veg) and
a tiered play-variant exchange (0/1/3 clay -> 1/2/3 grain, with a decline).
"""
import agricola.cards.field_caretaker  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import CommitPlayOccupation
from agricola.cards.card_fields import (
    CARD_FIELDS, card_field_count, can_sow_card_fields,
)
from agricola.cards.field_caretaker import CARD_ID
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, res=Resources()):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}),
                     occupations=frozenset(), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=cp, initiated_by_id="space:lessons", cost=Resources()),))
    return cs, cp


def _variants_offered(cs):
    return sorted(a.variant for a in legal_actions(cs)
                  if isinstance(a, CommitPlayOccupation) and a.card_id == CARD_ID)


def _commit(cs, variant):
    return next(a for a in legal_actions(cs)
               if isinstance(a, CommitPlayOccupation)
               and a.card_id == CARD_ID and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration — occupation, play-variant, AND card-field
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_OCCUPATION_VARIANTS
    assert CARD_ID in CARD_FIELDS
    spec = CARD_FIELDS[CARD_ID]
    assert spec.stacks == 1
    assert spec.sow_amounts == (("grain", 3), ("veg", 2))   # a general field


# ---------------------------------------------------------------------------
# The tiered exchange variants (gated by clay affordability)
# ---------------------------------------------------------------------------

def test_all_tiers_offered_with_enough_clay():
    cs, _cp = _state(res=Resources(clay=3))
    assert _variants_offered(cs) == ["1", "2", "3", "decline"]


def test_expensive_tiers_gated_by_clay():
    cs, _cp = _state(res=Resources(clay=1))   # affords tier "2" (1 clay), not "3" (3 clay)
    assert _variants_offered(cs) == ["1", "2", "decline"]
    cs, _cp = _state(res=Resources())          # no clay: only the free tier + decline
    assert _variants_offered(cs) == ["1", "decline"]


# ---------------------------------------------------------------------------
# The exchange itself
# ---------------------------------------------------------------------------

def test_free_tier_grants_one_grain():
    cs, cp = _state(res=Resources(clay=0))
    out = step(cs, _commit(cs, "1"))
    p = out.players[cp]
    assert p.resources.grain == 1 and p.resources.clay == 0
    assert CARD_ID in p.occupations


def test_middle_tier_pays_one_clay_for_two_grain():
    cs, cp = _state(res=Resources(clay=2))
    out = step(cs, _commit(cs, "2"))
    p = out.players[cp]
    assert p.resources.grain == 2
    assert p.resources.clay == 1               # 2 - 1 surcharge


def test_top_tier_pays_three_clay_for_three_grain():
    cs, cp = _state(res=Resources(clay=3))
    out = step(cs, _commit(cs, "3"))
    p = out.players[cp]
    assert p.resources.grain == 3
    assert p.resources.clay == 0               # 3 - 3 surcharge


def test_decline_grants_no_grain():
    cs, cp = _state(res=Resources(clay=3))
    out = step(cs, _commit(cs, "decline"))
    p = out.players[cp]
    assert p.resources.grain == 0 and p.resources.clay == 3
    assert CARD_ID in p.occupations


# ---------------------------------------------------------------------------
# The card is a field
# ---------------------------------------------------------------------------

def test_played_card_counts_as_a_field_and_is_sowable():
    cs, cp = _state(res=Resources(clay=0, grain=1))
    out = step(cs, _commit(cs, "decline"))
    p = out.players[cp]
    assert card_field_count(p) == 1            # counts as exactly one field
    # The exchange grain (or supply grain) can be sown onto the empty card-field.
    assert can_sow_card_fields(p)
