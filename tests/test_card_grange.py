"""Tests for Grange (minor improvement, B37; Bubulcus Expansion).

Card text: "When you play this card, you immediately get 1 food."
Prerequisite: 6 Field Tiles and All Animal Types. Printed VPs: 3. No cost.

Covers: registration; the +1 food via a real play-minor engine flow (kept in
tableau, not passing); the prereq eligibility boundary (6 fields + one of each
animal — fires when met, blocked when fields < 6 or an animal type missing);
and that the 3 printed VPs ride on the spec (auto-scored, no register_scoring).
"""
import agricola.cards.grange  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_animals, with_fields
from tests.test_utils import sole_play_minor
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("grange",) + tuple(f"m{i}" for i in range(20)),
)

# Six field cells (>= 6 needed for the prereq).
_SIX_FIELDS = ((0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 0))
_FIVE_FIELDS = _SIX_FIELDS[:5]


def _state(*, fields=_SIX_FIELDS, animals=None, in_hand=True, seed=5):
    """Set up a game state with `grange` in the current player's hand, the given
    field cells plowed, and the given animals (one of each by default)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    hand = frozenset({"grange"}) if in_hand else frozenset()
    p = fast_replace(cs.players[cp], hand_minors=hand)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if fields:
        cs = with_fields(cs, cp, fields)
    if animals is None:
        animals = Animals(sheep=1, boar=1, cattle=1)
    cs = with_animals(cs, cp, sheep=animals.sheep, boar=animals.boar,
                      cattle=animals.cattle)
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_grange_registered():
    assert "grange" in MINORS
    spec = MINORS["grange"]
    assert spec.vps == 3
    assert spec.passing_left is False
    assert spec.cost.resources == Resources() and spec.cost.animals == Animals()  # no cost
    # On-play one-shot, not a trigger card.
    assert "grange" not in CARDS


# ---------------------------------------------------------------------------
# Prerequisite eligibility boundary
# ---------------------------------------------------------------------------

def test_prereq_met_when_six_fields_and_all_animals():
    cs, cp = _state()
    assert prereq_met(MINORS["grange"], cs, cp) is True
    assert "grange" in playable_minors(cs, cp)


def test_prereq_blocked_with_five_fields():
    cs, cp = _state(fields=_FIVE_FIELDS)
    assert prereq_met(MINORS["grange"], cs, cp) is False
    assert "grange" not in playable_minors(cs, cp)


def test_prereq_blocked_when_an_animal_type_missing():
    # 6 fields but no cattle.
    cs, cp = _state(animals=Animals(sheep=1, boar=1, cattle=0))
    assert prereq_met(MINORS["grange"], cs, cp) is False
    assert "grange" not in playable_minors(cs, cp)


def test_prereq_blocked_when_no_fields():
    cs, cp = _state(fields=())
    assert prereq_met(MINORS["grange"], cs, cp) is False


# ---------------------------------------------------------------------------
# On-play effect via a real engine play-minor flow
# ---------------------------------------------------------------------------

def test_play_grange_gains_one_food_and_kept():
    cs, cp = _state()
    food_before = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    # The prereq is met, so the play is offered.
    assert legal_actions(cs) == [sole_play_minor(cs, "grange")]
    cs = step(cs, sole_play_minor(cs, "grange"))
    p = cs.players[cp]
    assert p.resources.food == food_before + 1        # immediate +1 food
    assert "grange" in p.minor_improvements            # non-passing -> kept
    assert "grange" not in p.hand_minors               # left my hand
    assert "grange" not in cs.players[1 - cp].hand_minors  # not circulated


def test_printed_vps_scored_from_spec():
    from agricola.scoring import score

    cs, cp = _state()
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "grange"))
    # The +3 must come from the spec's vps (card_points), scored automatically
    # — no register_scoring term, so no double-count.
    _total, breakdown = score(cs, cp)
    assert breakdown.card_points == 3


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
