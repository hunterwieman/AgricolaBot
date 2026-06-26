"""Tests for the Category-5 cards (build / renovate / bake / play-card hooks):
Roughcaster, Junk Room, Mining Hammer, Bread Paddle, Dutch Windmill.

These ride the after-hooks the SUBACTION_HOOK / SPACE_HOST refactors expose
(`after_renovate`, `after_build_rooms`, `after_bake_bread`,
`after_play_occupation`) plus the coarse `after_build_improvement` event fired by
both `_execute_build_major` and `_execute_play_minor`. Two kinds:

- automatic income (`register_auto`) — Roughcaster (+3 food), Junk Room (+1 food),
  Dutch Windmill (+3 food, post-harvest gate); fired directly at the hook.
- granted sub-action (`register` trigger) — Mining Hammer (a free stable on
  renovate), Bread Paddle (a Bake Bread after playing an occupation); surfaced as
  an optional FireTrigger.

Each test drives the real engine flow that fires the hook (no direct frame pokes
where a real flow exists), so the firing-point wiring is exercised end-to-end.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    CommitBuildRoom,
    CommitBuildStable,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitRenovate,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread, PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_house,
    with_majors,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=("roughcaster", "consultant") + tuple(f"o{i}" for i in range(20)),
    minors=("junk_room", "mining_hammer", "bread_paddle", "dutch_windmill")
    + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so deterministic plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_stables(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.STABLE)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_category5_cards_registered():
    assert "roughcaster" in OCCUPATIONS
    for cid in ("junk_room", "mining_hammer", "bread_paddle", "dutch_windmill"):
        assert cid in MINORS
    assert MINORS["dutch_windmill"].vps == 2
    # The other four are 0-VP (no vps field).
    for cid in ("junk_room", "mining_hammer", "bread_paddle"):
        assert MINORS[cid].vps == 0


# ---------------------------------------------------------------------------
# Roughcaster — +3 food on clay-room build and on clay->stone renovate
# ---------------------------------------------------------------------------

def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


def test_roughcaster_food_on_clay_to_stone_renovate():
    # Clay house, 2 rooms -> renovate to stone costs 2 stone + 1 reed.
    cs = _renovate_setup(HouseMaterial.CLAY, stone=2, reed=1)
    cs = _own_occ(cs, 0, "roughcaster")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),      # pop PendingRenovate's after-phase (after_renovate fired here)
        Proceed(),   # flip the parent to its after-phase
        Stop(),      # pop the parent
    ])
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.food == food0 + 3   # Roughcaster fired


def test_roughcaster_no_food_on_wood_to_clay_renovate():
    # Wood->clay renovate: not a clay->stone, so Roughcaster does NOT fire.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_occ(cs, 0, "roughcaster")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert cs.players[0].resources.food == food0     # no fire


def test_roughcaster_food_on_clay_room_build():
    # Build a room in a CLAY house via Farm Expansion -> a clay room -> +3 food
    # fired once at the build-rooms session-ending Stop.
    cs = _card_state()
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, clay=5, reed=2)   # clay-house room costs 5 clay + 2 reed
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_occ(cs, 0, "roughcaster")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Stop(),       # pop PendingBuildRooms (after_build_rooms fired here)
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0 + 3   # Roughcaster fired ONCE


def test_roughcaster_no_food_on_wood_room_build():
    # A wood-house room is not a clay room -> no fire.
    cs = _card_state()
    cs = with_resources(cs, 0, wood=5, reed=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_occ(cs, 0, "roughcaster")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].resources.food == food0   # no fire


# ---------------------------------------------------------------------------
# Junk Room — +1 food after building any improvement (incl. itself)
# ---------------------------------------------------------------------------

def test_junk_room_food_on_major_build():
    # Already-owned Junk Room; build a major improvement -> +1 food.
    cs = _card_state()
    cs = with_resources(cs, 0, clay=2)   # Fireplace (major_idx 0): 2 clay
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "junk_room")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=0, return_fireplace_idx=None),
        Stop(),   # pop PendingBuildMajor after-phase
        Stop(),   # pop PendingMajorMinorImprovement after-phase
        Stop(),   # pop PendingSubActionSpace
    ])
    assert cs.board.major_improvement_owners[0] == 0
    assert cs.players[0].resources.food == food0 + 1   # Junk Room fired on the major


def test_junk_room_fires_on_its_own_play():
    # "including this one": playing Junk Room itself fires after_build_improvement,
    # and it owns the card by then -> +1 food on its own play.
    cs = _card_state()
    cs = with_resources(cs, 0, wood=1, clay=1)   # Junk Room cost: 1 wood + 1 clay
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _give_hand_minor(cs, 0, "junk_room")
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="play_minor"),
        CommitPlayMinor(card_id="junk_room"),
        Stop(),   # pop PendingPlayMinor after-phase
        Stop(),   # pop PendingMajorMinorImprovement after-phase
        Stop(),   # pop PendingSubActionSpace
    ])
    assert "junk_room" in cs.players[0].minor_improvements
    # Paid 1 wood + 1 clay; gained +1 food from its own after_build_improvement.
    assert cs.players[0].resources.food == food0 + 1


# ---------------------------------------------------------------------------
# Mining Hammer — a free stable granted on renovate (optional trigger)
# ---------------------------------------------------------------------------

def test_mining_hammer_grants_free_stable_on_renovate():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    stables0 = _num_stables(cs, 0)
    wood0 = cs.players[0].resources.wood
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, CommitRenovate())   # flips PendingRenovate to its after-phase
    # The renovate after-hook surfaces the Mining Hammer grant at PendingRenovate's
    # after-phase (alongside Stop).
    la = legal_actions(cs)
    assert FireTrigger(card_id="mining_hammer") in la
    cs = step(cs, FireTrigger(card_id="mining_hammer"))
    assert isinstance(cs.pending_stack[-1], PendingBuildStables)
    builds = [a for a in legal_actions(cs) if isinstance(a, CommitBuildStable)]
    cs = step(cs, builds[0])
    assert _num_stables(cs, 0) == stables0 + 1
    assert cs.players[0].resources.wood == wood0   # FREE: no wood paid for the stable


def test_mining_hammer_decline_grant():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    stables0 = _num_stables(cs, 0)
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),      # decline the grant + pop PendingRenovate after-phase
        Proceed(),   # flip the host (house_redevelopment) to its after-phase
        Stop(),      # pop the host (skip the optional improvement step)
    ])
    assert cs.pending_stack == ()
    assert _num_stables(cs, 0) == stables0   # declined -> no stable built


def test_mining_hammer_not_offered_when_no_stable_buildable():
    # Fill every empty cell with fields (not a legal stable target) so no stable
    # can be placed -> the grant's eligibility (_can_build_stable) is False -> not
    # offered, only Stop remains at the renovate after-phase.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    overrides = {}
    grid = cs.players[0].farmyard.grid
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                overrides[(r, c)] = Cell(cell_type=CellType.FIELD)
    cs = with_grid(cs, 0, overrides)
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, CommitRenovate())
    assert FireTrigger(card_id="mining_hammer") not in legal_actions(cs)
    assert legal_actions(cs) == [Stop()]


# ---------------------------------------------------------------------------
# Bread Paddle — a Bake Bread granted after playing an occupation
# ---------------------------------------------------------------------------

def test_bread_paddle_grants_bake_after_occupation():
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})   # Fireplace: 1 grain -> 2 food on bake
    cs = with_resources(cs, 0, grain=2)
    cs = with_space(cs, "lessons", revealed=True)
    cs = _own_minor(cs, 0, "bread_paddle")
    cs = _give_hand_occ(cs, 0, "consultant")
    food0 = cs.players[0].resources.food
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    # The play-occupation after-hook surfaced the Bread Paddle grant.
    assert FireTrigger(card_id="bread_paddle") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="bread_paddle"))
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    cs = step(cs, CommitBake(grain=1))   # Fireplace: 1 grain -> 2 food
    assert cs.players[0].resources.food == food0 + 2
    assert cs.players[0].resources.grain == 1


def test_bread_paddle_not_offered_without_usable_bake():
    # Owns Bread Paddle + a baker but no grain -> _can_bake_bread False -> no grant.
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = with_resources(cs, 0, grain=0)
    cs = with_space(cs, "lessons", revealed=True)
    cs = _own_minor(cs, 0, "bread_paddle")
    cs = _give_hand_occ(cs, 0, "consultant")
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    assert FireTrigger(card_id="bread_paddle") not in legal_actions(cs)


# ---------------------------------------------------------------------------
# Dutch Windmill — +3 food on a bake in a post-harvest round
# ---------------------------------------------------------------------------

def _bake_via_grain_util(cs, *, grain):
    """Drive a Bake Bread via Grain Utilization (sow skipped, bake one)."""
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = with_resources(cs, 0, grain=grain)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    cs = step(cs, CommitBake(grain=1))   # Fireplace: 1 grain -> 2 food
    return cs


def test_dutch_windmill_food_in_post_harvest_round():
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})   # Fireplace
    cs = _own_minor(cs, 0, "dutch_windmill")
    cs = fast_replace(cs, round_number=5)        # round immediately after harvest (4)
    cs = _bake_via_grain_util(cs, grain=1)
    # 1 grain -> 2 food from the Fireplace bake + 3 food from Dutch Windmill.
    assert cs.players[0].resources.food == 5


def test_dutch_windmill_no_food_in_non_post_harvest_round():
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "dutch_windmill")
    cs = fast_replace(cs, round_number=6)        # NOT a post-harvest round
    cs = _bake_via_grain_util(cs, grain=1)
    # Only the bake's 2 food; no Windmill bonus.
    assert cs.players[0].resources.food == 2


def test_dutch_windmill_round_gate_exact():
    # Direct check of the gate set: bake in each round, compare food delta.
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "dutch_windmill")
    for rnd, fires in [(5, True), (6, False), (8, True), (9, False),
                       (10, True), (12, True), (14, True), (13, False)]:
        base = fast_replace(cs, round_number=rnd)
        after = _bake_via_grain_util(base, grain=1)
        expected = 2 + (3 if fires else 0)
        assert after.players[0].resources.food == expected, f"round {rnd}"
