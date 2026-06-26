"""Tests for the Category-8 deferred-goods cards (CARD_IMPLEMENTATION_PLAN.md §II.5):
the cards that place goods / an effect on FUTURE round spaces, collected at the start
of each scheduled round.

Two carriers:
- **Goods / food** ride on the Family-reachable `future_resources` (the Well's tuple).
  Wall Builder, Pond Hut, Strawberry Patch, Large Greenhouse, Sack Cart, Thick Forest,
  Herring Pot all schedule there.
- **A round-start effect** rides on the card-only `future_rewards` (FutureReward).
  Handplow schedules its deferred plow there.

(Manservant + Clay Hut Builder, also Category 8 but gated on the one-shot conditional
latch, are covered in tests/test_cards_one_shot_latch.py.)

Each card is exercised at the entry point that actually fires it: `on_play` for the
play-time minors, `apply_auto_effects` for Wall Builder's after-build-rooms hook, a
real `fishing` placement for Herring Pot's before-action-space hook, and the
registered round-start effect for Handplow.
"""
from __future__ import annotations

from agricola.actions import FireTrigger, PlaceWorker, Proceed
from agricola.cards.specs import MINORS, OCCUPATIONS, prereq_met
from agricola.cards.triggers import TRIGGERS, apply_auto_effects
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_plow, legal_actions
from agricola.pending import PendingPlow, PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env
from agricola.state import Cell, FutureReward, GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_occ_count(state, idx, n):
    """Give player `idx` exactly `n` placeholder occupations (for count prereqs)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(f"_occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_veg_fields(state, idx, n):
    """Make player `idx` have `n` FIELD cells sown with vegetables (veg>0)."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    placed = 0
    for r in range(3):
        for c in range(5):
            if placed >= n:
                break
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD, veg=1)
                placed += 1
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fill_grid_fields(state, idx):
    """Fill every non-room cell with FIELD so no plowable (empty) cell remains."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _run_turn(state):
    steps = 0
    while state.pending_stack and steps < 20:
        state = step(state, legal_actions(state)[0])
        steps += 1
    return state


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


def _clay(state, idx):
    return [r.clay for r in state.players[idx].future_resources]


def _grain(state, idx):
    return [r.grain for r in state.players[idx].future_resources]


def _wood(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


def _veg(state, idx):
    return [r.veg for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_category8_cards_registered():
    for cid in ("pond_hut", "strawberry_patch", "large_greenhouse", "sack_cart",
                "thick_forest", "herring_pot", "handplow"):
        assert cid in MINORS
    for cid in ("wall_builder", "manservant", "clay_hut_builder"):
        assert cid in OCCUPATIONS
    assert MINORS["pond_hut"].cost == Cost(resources=Resources(wood=1))
    assert MINORS["pond_hut"].vps == 1
    assert MINORS["strawberry_patch"].vps == 2
    assert MINORS["thick_forest"].cost == Cost()   # "5 Clay in Your Supply" is a prereq
    assert MINORS["herring_pot"].cost == Cost(resources=Resources(clay=1))
    assert MINORS["handplow"].cost == Cost(resources=Resources(wood=1))
    # Handplow's deferred plow is an OPTIONAL start_of_round trigger (not a forced auto).
    assert "handplow" in {e.card_id for e in TRIGGERS.get("start_of_round", [])}


# ---------------------------------------------------------------------------
# Wall Builder — +1 food on the next 4 round spaces, each time you build >=1 room
# ---------------------------------------------------------------------------

def test_wall_builder_schedules_next_4():
    s = _own_occ(setup(0), 0, "wall_builder")   # round 1
    out = apply_auto_effects(s, "after_build_rooms", 0)
    f = _food(out, 0)
    assert f[0] == 0                       # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == f[4] == 1  # rounds 2..5
    assert f[5] == 0                       # round 6 not scheduled


def test_wall_builder_unowned_noop():
    s = setup(0)
    out = apply_auto_effects(s, "after_build_rooms", 0)
    assert out is s   # AUTO_EFFECTS non-empty but unowned → returns unchanged state


# ---------------------------------------------------------------------------
# Pond Hut / Strawberry Patch — +1 food on the next 3 round spaces (on play)
# ---------------------------------------------------------------------------

def test_pond_hut_on_play_schedules_next_3():
    s = setup(0)
    out = MINORS["pond_hut"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0
    assert f[1] == f[2] == f[3] == 1   # rounds 2,3,4
    assert f[4] == 0


def test_pond_hut_prereq_exactly_two_occupations():
    s = setup(0)
    assert not prereq_met(MINORS["pond_hut"], _give_occ_count(s, 0, 1), 0)
    assert prereq_met(MINORS["pond_hut"], _give_occ_count(s, 0, 2), 0)
    assert not prereq_met(MINORS["pond_hut"], _give_occ_count(s, 0, 3), 0)  # exactly 2


def test_strawberry_patch_on_play_and_prereq():
    s = setup(0)
    out = MINORS["strawberry_patch"].on_play(s, 0)
    f = _food(out, 0)
    assert f[1] == f[2] == f[3] == 1 and f[0] == 0
    # Prereq: 2 vegetable fields.
    assert not prereq_met(MINORS["strawberry_patch"], _set_veg_fields(s, 0, 1), 0)
    assert prereq_met(MINORS["strawberry_patch"], _set_veg_fields(s, 0, 2), 0)


# ---------------------------------------------------------------------------
# Large Greenhouse — +1 veg on rounds R+4, R+7, R+9
# ---------------------------------------------------------------------------

def test_large_greenhouse_on_play():
    s = setup(0)   # R=1 → rounds 5, 8, 10
    out = MINORS["large_greenhouse"].on_play(s, 0)
    v = _veg(out, 0)
    assert v[4] == 1 and v[7] == 1 and v[9] == 1
    assert sum(v) == 3


def test_large_greenhouse_clamps_past_14():
    from agricola.setup import setup as _setup
    s = fast_replace(_setup(0), round_number=10)   # R+7=17, R+9=19 dropped; R+4=14 kept
    out = MINORS["large_greenhouse"].on_play(s, 0)
    v = _veg(out, 0)
    assert v[13] == 1            # round 14
    assert sum(v) == 1          # the other two fall past round 14


# ---------------------------------------------------------------------------
# Sack Cart — +1 grain on the REMAINING absolute rounds {5,8,11,14}
# ---------------------------------------------------------------------------

def test_sack_cart_all_remaining_at_round_1():
    s = setup(0)
    out = MINORS["sack_cart"].on_play(s, 0)
    g = _grain(out, 0)
    for rnd in (5, 8, 11, 14):
        assert g[rnd - 1] == 1
    assert sum(g) == 4


def test_sack_cart_drops_already_entered_rounds():
    s = fast_replace(setup(0), round_number=6)   # rounds 5 already gone → {8,11,14}
    out = MINORS["sack_cart"].on_play(s, 0)
    g = _grain(out, 0)
    assert g[4] == 0                 # round 5 dropped
    assert g[7] == g[10] == g[13] == 1
    assert sum(g) == 3


# ---------------------------------------------------------------------------
# Thick Forest — +1 wood on each remaining EVEN round; prereq hold >=5 clay
# ---------------------------------------------------------------------------

def test_thick_forest_on_play_even_rounds():
    s = setup(0)   # R=1 → even rounds 2,4,6,8,10,12,14
    out = MINORS["thick_forest"].on_play(s, 0)
    w = _wood(out, 0)
    for slot in range(14):
        rnd = slot + 1
        assert w[slot] == (1 if (rnd > 1 and rnd % 2 == 0) else 0)


def test_thick_forest_prereq_five_clay_not_spent():
    s = setup(0)
    p = fast_replace(s.players[0], resources=Resources(clay=4))
    s4 = fast_replace(s, players=(p, s.players[1]))
    assert not prereq_met(MINORS["thick_forest"], s4, 0)
    p = fast_replace(s.players[0], resources=Resources(clay=5))
    s5 = fast_replace(s, players=(p, s.players[1]))
    assert prereq_met(MINORS["thick_forest"], s5, 0)
    # The clay is a have-check, not a debit: on_play leaves the supply untouched.
    out = MINORS["thick_forest"].on_play(s5, 0)
    assert out.players[0].resources.clay == 5


# ---------------------------------------------------------------------------
# Herring Pot — before_action_space hook on Fishing (end-to-end placement)
# ---------------------------------------------------------------------------

def test_herring_pot_schedules_on_fishing_use():
    s, _env = setup_env(0)
    ap = s.current_player
    s = _own_minor(s, ap, "herring_pot")
    before = _food(s, ap)
    s = step(s, PlaceWorker(space="fishing"))
    s = _run_turn(s)
    f = _food(s, ap)
    R = 1
    # Rounds R+1..R+3 each gain 1 food; the rest unchanged.
    assert f[R] == before[R] + 1
    assert f[R + 1] == before[R + 1] + 1
    assert f[R + 2] == before[R + 2] + 1
    assert f[R + 3] == before[R + 3]


# ---------------------------------------------------------------------------
# Handplow — schedules a deferred plow effect on round R+5
# ---------------------------------------------------------------------------

def test_handplow_on_play_schedules_effect():
    s = setup(0)   # R=1 → effect on round 6 (slot 5)
    out = MINORS["handplow"].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert "handplow" in fr[5].effect_card_ids
    assert sum(1 for r in fr if r) == 1   # only that one slot populated
    # Goods carrier is untouched (Handplow is an effect, not goods).
    assert all(r.food == 0 for r in out.players[0].future_resources)


def _prep_with_handplow_scheduled(idx=0, prev_round=1):
    """A PREPARATION state where player `idx` owns Handplow with its plow scheduled
    for the round `_complete_preparation` is about to enter (prev_round+1)."""
    state = setup(0)
    entered = prev_round + 1
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered - 1] = FutureReward(effect_card_ids=frozenset({"handplow"}))
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {"handplow"},
                     future_rewards=tuple(rewards))
    state = fast_replace(state,
                         players=tuple(p if i == idx else state.players[i] for i in range(2)),
                         round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


def test_handplow_offers_optional_plow_at_round_start():
    # The scheduled round is entered → a PendingPreparation host surfaces the plow as
    # an OPTIONAL FireTrigger alongside Proceed (the decline). Firing pushes the plow
    # and consumes the grant.
    s, entered = _prep_with_handplow_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPreparation) and top.player_idx == 0
    la = legal_actions(s)
    assert FireTrigger(card_id="handplow") in la
    assert Proceed() in la                       # optional → declinable
    s2 = step(s, FireTrigger(card_id="handplow"))
    assert isinstance(s2.pending_stack[-1], PendingPlow)
    assert "handplow" not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_handplow_can_be_declined():
    # Proceed declines the plow — no PendingPlow is pushed and the host resolves.
    s, _ = _prep_with_handplow_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s = step(s, Proceed())
    assert all(not isinstance(f, PendingPlow) for f in s.pending_stack)


def test_handplow_not_offered_when_unplowable():
    # Scheduled but the farm has no plowable cell → the host appears (the schedule
    # drives hosting) but Handplow is not eligible, so only Proceed is offered.
    s, _ = _prep_with_handplow_scheduled(idx=0, prev_round=1)
    s = _fill_grid_fields(s, 0)
    assert not _can_plow(s.players[0])
    s = _complete_preparation(s)
    assert legal_actions(s) == [Proceed()]


def test_handplow_owner_not_hosted_on_unscheduled_round():
    # Owning Handplow does NOT host a preparation frame on rounds its plow isn't due
    # (hosting is gated on the schedule, not card ownership).
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {"handplow"})
    state = fast_replace(state, players=(p, state.players[1]),
                         round_number=3, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()   # no host pushed
