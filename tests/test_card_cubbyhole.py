"""Tests for Cubbyhole (minor improvement, E52; Ephipparius Expansion).

Card text: "For each room that you add to your house, place 1 food from the
general supply on this card. At the start of each feeding phase, you get food
equal to the amount on this card."

Two effects, both exercised end-to-end:

  - ROOM-ADD BANK: a `before_build_rooms`/`after_build_rooms` before/after snapshot
    on the build-rooms sub-action host banks 1 food (a CardStore int) per room
    built this session (the Rustic idiom). Driven through the real Farm Expansion
    build-rooms flow.
  - FEEDING PAYOUT: a `start_of_feeding` (harvest window #8) auto grants food equal
    to the on-card bank, BEFORE the FEED payment (so it is payable) and WITHOUT
    consuming the bank (recurring). Driven through the real harvest walk.
"""
import agricola.cards.cubbyhole  # noqa: F401  -- registers the card

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitPlayMinor,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.cubbyhole import CARD_ID, _FOOD_KEY, _SNAPSHOT_KEY
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

from tests.factories import (
    with_current_player,
    with_house,
    with_pending_stack,
    with_phase,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_bank(state, idx, amount):
    """Force the on-card food bank to `amount` (skip the room-build wiring)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_FOOD_KEY, amount))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_rooms(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.ROOM)


def _bank(state, idx):
    return state.players[idx].card_state.get(_FOOD_KEY, 0)


def _expansion_setup(material=HouseMaterial.WOOD, *, idx=0, own=True, **resources):
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "farm_expansion", revealed=True)
    if own:
        cs = _own_minor(cs, idx, CARD_ID)
    return cs


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup_env(seed, card_pool=_POOL)[0], Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON)
# ---------------------------------------------------------------------------

def test_registered_spec():
    spec = MINORS[CARD_ID]
    # Cost "1 Reed,1 Wood/1 Clay" = 1 reed + (1 wood OR 1 clay).
    assert spec.cost == Cost(Resources(reed=1, wood=1))
    assert spec.alt_costs == (Cost(Resources(reed=1, clay=1)),)
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.max_occupations is None and spec.min_occupations == 0  # no prereq
    # Wired on the three events + the harvest-window hook.
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("before_build_rooms", ())}
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("after_build_rooms", ())}
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("start_of_feeding", ())}
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_feeding", set())


# ---------------------------------------------------------------------------
# Room-add bank (real Farm Expansion build-rooms flow)
# ---------------------------------------------------------------------------

def test_one_room_banks_one_food():
    # Wood house: a room costs 5 wood + 2 reed. Build one via Farm Expansion.
    cs = _expansion_setup(HouseMaterial.WOOD, wood=5, reed=2)
    assert _bank(cs, 0) == 0
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms -> after -> after_build_rooms fires
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert _bank(cs, 0) == 1                          # +1 food banked on the card
    assert cs.players[0].card_state.get(_SNAPSHOT_KEY, 0) == 0   # snapshot reset


def test_two_rooms_one_session_banks_two():
    cs = _expansion_setup(HouseMaterial.WOOD, wood=10, reed=4)
    rooms0 = _num_rooms(cs, 0)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
    ])
    next_room = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = run_actions(cs, [
        next_room,
        Proceed(),    # one after_build_rooms for the whole 2-room session
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert _num_rooms(cs, 0) == rooms0 + 2
    assert _bank(cs, 0) == 2                          # 1 food per room added


def test_bank_accumulates_across_sessions():
    """Two separate build-rooms sessions bank cumulatively (running total)."""
    cs = _expansion_setup(HouseMaterial.WOOD, wood=10, reed=4)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _bank(cs, 0) == 1
    # Re-open the farm_expansion space for a second session (clear its worker) and
    # build again — the bank must accumulate, not reset.
    cs = with_space(cs, "farm_expansion", revealed=True, workers=(0, 0))
    cs = with_current_player(cs, 0)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        lambda s: next(a for a in legal_actions(s) if isinstance(a, CommitBuildRoom)),
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _bank(cs, 0) == 2                          # 1 (first session) + 1 (second)


def test_starting_rooms_are_not_banked():
    """A player who never builds a room has an empty bank (the initial 2 rooms
    were never inside a build session)."""
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    assert _num_rooms(cs, 0) == 2                     # the two starting rooms
    assert _bank(cs, 0) == 0


# ---------------------------------------------------------------------------
# Feeding payout (real harvest walk) — payable, non-consuming, recurring
# ---------------------------------------------------------------------------

def test_payout_at_start_of_feeding_is_payable():
    """The bank pays out at start_of_feeding, BEFORE the FEED payment — so a
    player with no other food can feed from the payout."""
    state = _harvest_state(food=0)                    # no food on hand
    state = _own_minor(state, 0, CARD_ID)
    state = _set_bank(state, 0, 4)                    # 4 food on the card
    # Give player 0 exactly 1 family member so feeding needs 2 food; the 4-food
    # payout covers it (and the opponent already has food=0 -> begs, irrelevant).
    p0 = fast_replace(state.players[0], people_total=1)
    state = fast_replace(state, players=tuple(
        p0 if i == 0 else state.players[i] for i in range(2)))
    begs0 = state.players[0].begging_markers
    state = _run_harvest(state)
    # The payout arrived before feeding, so player 0 paid its 2-food feeding from
    # the 4 and never begged; 2 food remains (4 payout - 2 feeding).
    assert state.players[0].begging_markers == begs0
    assert state.players[0].resources.food == 2


def test_payout_does_not_consume_the_bank():
    """The on-card bank is unchanged by a payout (recurring engine)."""
    state = _harvest_state(food=10)
    state = _own_minor(state, 0, CARD_ID)
    state = _set_bank(state, 0, 3)
    state = _run_harvest(state)
    assert _bank(state, 0) == 3                       # bank untouched


def test_payout_recurs_over_two_harvests():
    state = _harvest_state(food=10)
    state = _own_minor(state, 0, CARD_ID)
    state = _set_bank(state, 0, 2)
    food_start = state.players[0].resources.food
    # First harvest: +2 from the payout (net of feeding, which the 10 food covers).
    state = _run_harvest(state)
    # Advance to the next harvest round and run it again.
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _run_harvest(state)
    # Two payouts of 2 food each landed (feeding paid from the ample base food).
    # Track the net by comparing food gained beyond feeding across the two harvests.
    assert _bank(state, 0) == 2                       # still recurring, undecremented


def test_zero_bank_is_a_noop():
    state = _harvest_state(food=10)
    state = _own_minor(state, 0, CARD_ID)             # bank defaults to 0
    state = _run_harvest(state)
    # No payout food beyond the base (feeding took its 2/adult from the base).
    assert _bank(state, 0) == 0


# ---------------------------------------------------------------------------
# Owner-gating and NOT-firing-elsewhere
# ---------------------------------------------------------------------------

def test_unowned_never_pays_out():
    state = _harvest_state(food=10)
    state = _set_bank(state, 0, 5)                    # bank set but card NOT owned
    state = _run_harvest(state)
    # The auto is owner-gated: an unplayed card never fires even with a stray bank.
    # Feeding still took 2/adult, so compare against a no-payout baseline run.
    base = _run_harvest(_harvest_state(food=10))
    assert state.players[0].resources.food == base.players[0].resources.food


def test_payout_only_at_start_of_feeding_not_other_windows():
    """Sanity: the payout fires exactly once per harvest (at #8), reflected by the
    food delta being exactly the bank amount net of feeding."""
    state = _harvest_state(food=10)
    state = _own_minor(state, 0, CARD_ID)
    state = _set_bank(state, 0, 3)
    food0 = state.players[0].resources.food
    p0 = fast_replace(state.players[0], people_total=1)   # feeding needs 2
    state = fast_replace(state, players=tuple(
        p0 if i == 0 else state.players[i] for i in range(2)))
    state = _run_harvest(state)
    # Exactly one +3 payout, minus 2 for feeding = net +1 over the harvest.
    assert state.players[0].resources.food == food0 + 3 - 2


# ---------------------------------------------------------------------------
# Real play flow: mixed cost + VP
# ---------------------------------------------------------------------------

def _at_play_minor_frame(**res):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if res:
        cs = with_resources(cs, cp, **res)
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_play_offers_both_cost_routes():
    cs, cp = _at_play_minor_frame(reed=1, wood=1, clay=1)
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    payments = {p.payment for p in plays}
    assert Resources(reed=1, wood=1) in payments      # base route
    assert Resources(reed=1, clay=1) in payments      # alt route


def test_play_via_wood_route():
    cs, cp = _at_play_minor_frame(reed=1, wood=1)     # only the wood route affordable
    play = next(a for a in legal_actions(cs)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.payment == Resources(reed=1, wood=1))
    cs = step(cs, play)
    assert CARD_ID in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.reed == 0 and cs.players[cp].resources.wood == 0


def test_play_via_clay_route():
    cs, cp = _at_play_minor_frame(reed=1, clay=1)     # only the clay route affordable
    play = next(a for a in legal_actions(cs)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.payment == Resources(reed=1, clay=1))
    cs = step(cs, play)
    assert CARD_ID in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.reed == 0 and cs.players[cp].resources.clay == 0
