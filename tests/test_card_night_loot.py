"""Tests for Night Loot (minor improvement, E5; Ephipparius Expansion; traveling).

Card text (verbatim): "Immediately remove exactly 2 different building resources
from accumulation spaces and place them in your supply." Cost: 2 Food. PASSING.

User rulings (2026-07-17): the take is MANDATORY (a choice of WHICH two, no
decline — so NO skip variant); the card is NOT playable unless >= 2 distinct
types among {wood, clay, reed, stone} each have >= 1 unit on a REVEALED
accumulation space (a `prereq`, never a dead-end / partial take). Surfaced WIDE
via the minor play-variant seam: one CommitPlayMinor per legal pick, encoded
"typeA@spaceA+typeB@spaceB" (stone offers both quarries when both hold stone).
"""
import agricola.cards.night_loot  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitPlayMinor, Stop
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_pending_stack, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("night_loot",) + tuple(f"m{i}" for i in range(20)),
)

# Board presets (space -> factory kwargs). The default round-1 card board has
# forest=3 wood, clay_pit=1 clay, reed_bank=1 reed (all revealed), and both
# quarries unrevealed with 0 stone.
_ONLY_WOOD_CLAY = {"reed_bank": {"accumulated": Resources()}}  # strip reed -> {wood, clay}
_ONLY_WOOD = {  # strip clay + reed, quarries already empty -> {wood} only
    "clay_pit": {"accumulated": Resources()},
    "reed_bank": {"accumulated": Resources()},
}
_WOOD_AND_STONE_BOTH_QUARRIES = {  # {wood, stone}, stone on BOTH quarries
    "clay_pit": {"accumulated": Resources()},
    "reed_bank": {"accumulated": Resources()},
    "western_quarry": {"revealed": True, "accumulated": Resources(stone=1)},
    "eastern_quarry": {"revealed": True, "accumulated": Resources(stone=1)},
}


def _state(seed=5, *, hand=frozenset({"night_loot"}), res=Resources(food=2), board=None):
    """A 2-player card state with the current player's hand/resources set and,
    optionally, the accumulation board overridden."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=hand, resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    for sid, kwargs in (board or {}).items():
        cs = with_space(cs, sid, **kwargs)
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


def _commits(cs):
    return [a for a in legal_actions(cs)
            if isinstance(a, CommitPlayMinor) and a.card_id == "night_loot"]


def _variants(cs):
    return sorted(c.variant for c in _commits(cs))


def _commit(cs, variant):
    return next(a for a in _commits(cs) if a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "night_loot" in MINORS
    spec = MINORS["night_loot"]
    assert spec.cost.resources == Resources(food=2)   # 2 Food
    assert spec.cost.animals == Animals()             # no animal cost
    assert spec.passing_left is True                  # traveling minor
    assert spec.vps == 0
    assert spec.prereq is not None                    # the >=2-types prereq
    assert "night_loot" in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# Prerequisite: >= 2 different building-resource TYPES available on the board
# ---------------------------------------------------------------------------

def test_prereq_true_on_default_board():
    # Default: wood(forest) + clay(clay_pit) + reed(reed_bank) = 3 types.
    cs, cp = _state()
    assert prereq_met(MINORS["night_loot"], cs, cp)


def test_prereq_false_with_only_one_type():
    cs, cp = _state(board=_ONLY_WOOD)   # only wood remains
    assert not prereq_met(MINORS["night_loot"], cs, cp)


def test_prereq_ignores_unrevealed_quarry_stone():
    # Put stone on a quarry but leave it UNREVEALED; strip clay + reed so only
    # wood is revealed. The hidden stone must not count -> < 2 types -> False.
    board = {
        "clay_pit": {"accumulated": Resources()},
        "reed_bank": {"accumulated": Resources()},
        "western_quarry": {"revealed": False, "accumulated": Resources(stone=1)},
    }
    cs, cp = _state(board=board)
    assert not prereq_met(MINORS["night_loot"], cs, cp)


def test_playable_gates_on_prereq():
    # Card in hand + 2 food + >= 2 types -> playable.
    cs, cp = _state()
    assert "night_loot" in playable_minors(cs, cp)
    # < 2 types -> not playable even holding the card and the food.
    cs, cp = _state(board=_ONLY_WOOD)
    assert "night_loot" not in playable_minors(cs, cp)


# ---------------------------------------------------------------------------
# Variant enumeration
# ---------------------------------------------------------------------------

def test_variants_wood_clay_from_named_spaces():
    # Only wood + clay available -> the single pick names both source spaces.
    cs, cp = _state(board=_ONLY_WOOD_CLAY)
    cs = _push_minor(cs, cp)
    assert _variants(cs) == ["wood@forest+clay@clay_pit"]


def test_variants_default_board_three_pairs():
    # wood + clay + reed -> C(3,2) = 3 single-source pairs, canonical order.
    cs, cp = _state()
    cs = _push_minor(cs, cp)
    assert _variants(cs) == [
        "clay@clay_pit+reed@reed_bank",
        "wood@forest+clay@clay_pit",
        "wood@forest+reed@reed_bank",
    ]


def test_stone_pair_offers_both_quarry_sources():
    # {wood, stone} with stone on BOTH quarries -> the wood+stone pick is offered
    # once per quarry (both sources surfaced).
    cs, cp = _state(board=_WOOD_AND_STONE_BOTH_QUARRIES)
    cs = _push_minor(cs, cp)
    assert _variants(cs) == [
        "wood@forest+stone@eastern_quarry",
        "wood@forest+stone@western_quarry",
    ]


def test_no_skip_variant_effect_is_mandatory():
    # Every offered variant takes exactly two typed resources (two "type@space"
    # tokens); there is no decline/skip/None variant.
    cs, cp = _state()
    cs = _push_minor(cs, cp)
    commits = _commits(cs)
    assert commits  # the card is offered
    for c in commits:
        assert c.variant is not None and "+" in c.variant
        tokens = c.variant.split("+")
        assert len(tokens) == 2
        assert all("@" in t for t in tokens)
        # No surcharge: the take is from the board, so payment is just the 2 food.
        assert c.payment == Resources(food=2)


# ---------------------------------------------------------------------------
# Firing: decrement the named spaces, credit the supply, charge 2 food
# ---------------------------------------------------------------------------

def test_firing_wood_clay_decrements_spaces_and_credits_supply():
    cs, cp = _state(res=Resources(food=2), board=_ONLY_WOOD_CLAY)
    assert get_space(cs.board, "forest").accumulated.wood == 3
    assert get_space(cs.board, "clay_pit").accumulated.clay == 1
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "wood@forest+clay@clay_pit"))
    # Board: one unit removed from each named space.
    assert get_space(cs.board, "forest").accumulated.wood == 2
    assert get_space(cs.board, "clay_pit").accumulated.clay == 0
    # Supply: +1 wood, +1 clay; the 2-food cost was charged.
    p = cs.players[cp]
    assert p.resources.wood == 1
    assert p.resources.clay == 1
    assert p.resources.food == 0
    # Back at the host's after-phase, ready to end the turn.
    assert [type(f).__name__ for f in cs.pending_stack] == ["PendingPlayMinor"]
    assert legal_actions(cs) == [Stop()]


def test_firing_takes_from_the_named_quarry_only():
    # Two quarries both hold stone; taking stone@western must leave eastern full.
    cs, cp = _state(res=Resources(food=2), board=_WOOD_AND_STONE_BOTH_QUARRIES)
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "wood@forest+stone@western_quarry"))
    assert get_space(cs.board, "western_quarry").accumulated.stone == 0  # taken
    assert get_space(cs.board, "eastern_quarry").accumulated.stone == 1  # untouched
    assert get_space(cs.board, "forest").accumulated.wood == 2
    p = cs.players[cp]
    assert p.resources.wood == 1 and p.resources.stone == 1 and p.resources.food == 0


# ---------------------------------------------------------------------------
# Passing (traveling minor)
# ---------------------------------------------------------------------------

def test_passes_to_opponent_and_is_not_kept():
    cs, cp = _state(board=_ONLY_WOOD_CLAY)
    opp = 1 - cp
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "wood@forest+clay@clay_pit"))
    p = cs.players[cp]
    assert "night_loot" not in p.minor_improvements   # passing -> not kept
    assert "night_loot" not in p.hand_minors          # left the hand
    assert "night_loot" in cs.players[opp].hand_minors  # circulated to opponent
    # The take still resolved for the player who played it.
    assert p.resources.wood == 1 and p.resources.clay == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
