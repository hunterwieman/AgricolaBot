"""Tests for Patch Caregiver (occupation, B113; Bubulcus; players 1+).

Card text (verbatim): "When you play this card, you can choose to buy 1 grain
for 1 food, or 1 vegetable for 3 food. This card is a field."

Covers:
- registration facts (occupation registry, play-variant registry, the
  CARD_FIELDS row: 1 stack, unrestricted grain/veg);
- the WIDE on-play buy (ruling 17, 2026-07-05): the bare "decline" play, the
  "buy_grain" variant (food -1, grain +1), the "buy_veg" variant (food -3,
  veg +1), and the affordability gate (a buy is NOT offered when its food
  surcharge is not coverable);
- the card as a field after it is in play: sowing onto it through
  `legal_actions` + `step` at a PendingSow frame (grain plants 3; a veg sow
  is also offered), the field-phase take harvesting 1 from it;
- the ruling-45 (2026-07-12) field-count contribution: scoring counts the
  card as 1 field even though it is an OCCUPATION (`owned_card_fields` reads
  both tableau sets).
"""
from __future__ import annotations

import agricola.cards.patch_caregiver  # noqa: F401  (registers at import)

from agricola.actions import CommitPlayOccupation, CommitSow
from agricola.cards.card_fields import CARD_FIELDS, card_field_stacks
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayOccupation, PendingSow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_pending_stack, with_resources, with_sown_fields

CARD = "patch_caregiver"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD})


def _play_state(seed=0, *, food=3):
    """A state with Patch Caregiver in hand at a PendingPlayOccupation host
    (zero base play cost — the first Lessons occupation), `food` on hand and
    nothing liquidatable (no grain/veg/animals at setup)."""
    state = setup(seed)
    cp = state.current_player
    state = _edit_player(state, cp, hand_occupations=frozenset({CARD}))
    state = with_resources(state, cp, food=food)
    frame = PendingPlayOccupation(player_idx=cp,
                                  initiated_by_id="space:lessons",
                                  cost=Resources())
    return with_pending_stack(state, [frame]), cp


def _plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayOccupation) and a.card_id == CARD]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD in OCCUPATIONS
    assert CARD in PLAY_OCCUPATION_VARIANTS
    spec = CARD_FIELDS[CARD]
    assert spec.stacks == 1
    assert spec.sow_amounts == (("grain", 3), ("veg", 2))


# ---------------------------------------------------------------------------
# The wide on-play buy (ruling 17)
# ---------------------------------------------------------------------------

def test_all_three_variants_offered_with_three_food():
    state, _cp = _play_state(food=3)
    assert sorted(a.variant for a in _plays(state)) == [
        "buy_grain", "buy_veg", "decline"]


def test_decline_plays_bare():
    state, cp = _play_state(food=3)
    state = step(state, CommitPlayOccupation(card_id=CARD, variant="decline"))
    p = state.players[cp]
    assert CARD in p.occupations and CARD not in p.hand_occupations
    assert (p.resources.food, p.resources.grain, p.resources.veg) == (3, 0, 0)


def test_buy_grain_variant():
    state, cp = _play_state(food=3)
    state = step(state, CommitPlayOccupation(card_id=CARD, variant="buy_grain"))
    p = state.players[cp]
    assert CARD in p.occupations
    assert (p.resources.food, p.resources.grain, p.resources.veg) == (2, 1, 0)


def test_buy_veg_variant():
    state, cp = _play_state(food=3)
    state = step(state, CommitPlayOccupation(card_id=CARD, variant="buy_veg"))
    p = state.players[cp]
    assert CARD in p.occupations
    assert (p.resources.food, p.resources.grain, p.resources.veg) == (0, 0, 1)


def test_buys_withheld_without_the_food():
    # 0 food, nothing liquidatable -> only the bare play.
    state, _cp = _play_state(food=0)
    assert [a.variant for a in _plays(state)] == ["decline"]
    # 2 food -> buy_grain payable, buy_veg (3 food) not.
    state, _cp = _play_state(food=2)
    assert sorted(a.variant for a in _plays(state)) == ["buy_grain", "decline"]


# ---------------------------------------------------------------------------
# The card as a field (rulings 45/47) — sow, then the field-phase take
# ---------------------------------------------------------------------------

def test_sow_and_take_on_the_card():
    state = setup(7)
    state = _own_occupation(state, 0)              # an OCCUPATION card-field
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    la = legal_actions(state)
    grain_sow = CommitSow(grain=0, veg=0, card_sows=((CARD, "grain"),))
    # Unrestricted: both crops offered.
    assert grain_sow in la
    assert CommitSow(grain=0, veg=0, card_sows=((CARD, "veg"),)) in la
    state = step(state, grain_sow)
    p = state.players[0]
    assert card_field_stacks(p, CARD) == ((3, 0, 0, 0),)
    assert p.resources.grain == 0                  # spent from supply
    # The field-phase take harvests 1 from the card.
    nxt, occasion = field_take(state, 0)
    entries = [e for e in occasion.entries if e.source == f"card:{CARD}"]
    assert len(entries) == 1
    assert (entries[0].crop, entries[0].amount, entries[0].emptied) == (
        "grain", 1, False)
    assert card_field_stacks(nxt.players[0], CARD) == ((2, 0, 0, 0),)
    assert nxt.players[0].resources.grain == 1


def test_unowned_card_offers_no_sow():
    state = setup(7)
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_pending_stack(
        state, [PendingSow(player_idx=0, initiated_by_id="test")])
    assert all(
        all(cid != CARD for cid, _g in a.card_sows)
        for a in legal_actions(state) if isinstance(a, CommitSow))


# ---------------------------------------------------------------------------
# Ruling 45 — the field-count contribution (an occupation counted as a field)
# ---------------------------------------------------------------------------

def test_scoring_counts_the_occupation_as_one_field():
    state = with_sown_fields(setup(7), 0, grain_fields=[(2, 0)])
    _, base_bd = score(state, 0)
    assert base_bd.field_tiles == -1               # 1 field
    _, bd = score(_own_occupation(state, 0), 0)
    assert bd.field_tiles == 1                     # 2 fields: board + card
