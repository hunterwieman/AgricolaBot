"""Tests for Drinking Trough (minor improvement A12): the per-pasture +2 capacity bonus,
exercised through `extract_slots` / `can_accommodate` / `pasture_capacity_bonus`, plus
registration and Family byte-identity (no card owned -> no bonus).

The cross-LEVEL equivalence of the +2 (non-canonical) capacities through the optimized
frontier caches lives in tests/test_frontier_opt.py (the red-team item).
"""
from agricola.cards.capacity_mods import PASTURE_CAPACITY_MODS, pasture_capacity_bonus
from agricola.cards.specs import MINORS
from agricola.helpers import can_accommodate, extract_slots
from agricola.replace import fast_replace
from agricola.setup import setup

from scripts.profile_states import STATES


def _own_minor(state, pidx, card_id):
    p = state.players[pidx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == pidx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "drinking_trough" in MINORS
    assert MINORS["drinking_trough"].cost.resources.clay == 1
    assert any(cid == "drinking_trough" for cid, _fn in PASTURE_CAPACITY_MODS)


# ---------------------------------------------------------------------------
# The capacity bonus
# ---------------------------------------------------------------------------

def test_bonus_zero_by_default():
    s = setup(0)
    assert pasture_capacity_bonus(s.players[0]) == 0


def test_bonus_two_when_owned():
    s = setup(0)
    s = _own_minor(s, 0, "drinking_trough")
    assert pasture_capacity_bonus(s.players[0]) == 2


def test_each_pasture_gets_plus_two():
    # mid_round_6_basic: player 0 has two pastures (1x1 + 1 stable -> cap 4; 2x1 -> cap 4).
    state = STATES["mid_round_6_basic"]()
    base_caps, base_flex = extract_slots(state.players[0])
    state2 = _own_minor(state, 0, "drinking_trough")
    caps, flex = extract_slots(state2.players[0])
    assert flex == base_flex                         # house/stable slots unchanged
    assert sorted(caps) == sorted(c + 2 for c in base_caps)
    # The other (non-owner) player is unaffected.
    assert extract_slots(state2.players[1]) == extract_slots(state.players[1])


def test_bonus_is_flat_not_doubled_by_stable():
    # The 1x1-with-stable pasture has base capacity 4 (2*1*2^1). Drinking Trough makes it 6
    # (4 + 2), NOT 8 (no extra doubling) and NOT (2*1+2)*2 = 8 either.
    state = STATES["mid_round_6_basic"]()
    state = _own_minor(state, 0, "drinking_trough")
    caps, _flex = extract_slots(state.players[0])
    assert 6 in caps          # the stabled pasture: 4 -> 6
    assert 8 not in caps


def test_capacity_lets_player_keep_more_animals():
    # A single 1x1 pasture (cap 2) + the default house pet (1 flexible). Without the card it
    # holds at most 3 of one type (2 in pasture + 1 pet); with the card the pasture holds 4.
    s = setup(0)
    grid = s.players[0].farmyard.grid
    # build a 1x1 pasture at (0,0) by fencing all four edges (reuse the profile helper).
    from scripts.profile_states import _add_pasture
    s = _add_pasture(s, 0, [(0, 0)])           # 1x1, 0 stables -> capacity 2
    caps0, flex0 = extract_slots(s.players[0])
    assert caps0 == [2]
    assert can_accommodate(caps0, flex0, 3, 0, 0)       # 2 in pasture + 1 pet
    assert not can_accommodate(caps0, flex0, 4, 0, 0)

    s2 = _own_minor(s, 0, "drinking_trough")
    caps1, flex1 = extract_slots(s2.players[0])
    assert caps1 == [4]                                  # 2 -> 4
    assert can_accommodate(caps1, flex1, 5, 0, 0)        # 4 in pasture + 1 pet
    assert not can_accommodate(caps1, flex1, 6, 0, 0)
