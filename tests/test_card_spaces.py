"""Tests for the played-card-as-action-space machinery (user ruling 74,
2026-07-21 — `agricola/cards/card_spaces.py`; consumers: Collector C104,
Tree Inspector D116).

Covers the machinery contracts:
- placement offered only to the OWNER ("for you only"), and only when usable;
- `people_home` accounting exactly like a board placement;
- occupancy (the on-card worker marker) blocks a second same-round use;
- the return-home reset clears the marker (placeable again next round);
- player alternation and the round's all-placed detection are unaffected;
- a card-space use is a real action-space host: the every-space hook cards'
  triggers fire on it (`space_id = "card:<id>"` — the ruling's "card spaces
  count as action spaces for other cards' hooks");
- the Henpecked Husband return works when the first person sits on a card
  space (the card-space branch of its board read);
- the Family game is BYTE-UNCHANGED: full random Family games reproduce the
  pre-change state+wire fingerprints exactly.
"""
import agricola.cards.collector  # noqa: F401  -- registers the card (not in cards/__init__ yet)
import agricola.cards.tree_inspector  # noqa: F401  -- registers the card (not in cards/__init__ yet)
import agricola.cards.work_certificate  # noqa: F401  -- the every-space hook exemplar
import agricola.cards.henpecked_husband  # noqa: F401  -- the card-space return branch

import hashlib
import json

import numpy as np

from agricola import canonical
from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.card_spaces import (
    CARD_ACTION_SPACES,
    card_space_occupied,
    card_space_worker_count,
)
from agricola.constants import GameMode, HouseMaterial, Phase
from agricola.engine import step
from agricola.agents.nn.trace_replay import action_to_params
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingReveal
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_current_player, with_house, with_resources, with_space
from tests.test_utils import filter_implemented, run_actions

_POOL = CardPool(
    occupations=("collector", "tree_inspector", "henpecked_husband")
    + tuple(f"o{i}" for i in range(20)),
    minors=("work_certificate",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _stock_tree_inspector(state, idx, wood):
    p = state.players[idx]
    return _edit_player(state, idx, card_state=p.card_state.set("tree_inspector", wood))


def _card_placements(actions, card_id):
    sid = f"card:{card_id}"
    return [a for a in actions if isinstance(a, PlaceWorker) and a.space == sid]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_both_cards_registered_as_card_spaces():
    assert "collector" in CARD_ACTION_SPACES
    assert "tree_inspector" in CARD_ACTION_SPACES


# ---------------------------------------------------------------------------
# Placement surfacing: owner-only, only when usable
# ---------------------------------------------------------------------------

def test_placement_offered_only_to_owner():
    cs = _own_occ(_card_state(), 0, "tree_inspector")
    cs = _stock_tree_inspector(cs, 0, 2)
    # Owner (P0) sees the placement.
    assert _card_placements(legal_actions(cs), "tree_inspector") == [
        PlaceWorker(space="card:tree_inspector")]
    # The opponent (P1) never does — "for you only".
    cs1 = with_current_player(cs, 1)
    assert _card_placements(legal_actions(cs1), "tree_inspector") == []


def test_unplayed_card_not_placeable():
    # In hand (or not dealt at all) is not OWNED — no placement.
    cs = _stock_tree_inspector(_card_state(), 0, 2)
    assert _card_placements(legal_actions(cs), "tree_inspector") == []


def test_not_placeable_when_placeable_fn_empty():
    # Tree Inspector holds no wood -> the empty-accumulation-space prune.
    cs = _own_occ(_card_state(), 0, "tree_inspector")
    assert _card_placements(legal_actions(cs), "tree_inspector") == []


# ---------------------------------------------------------------------------
# The placement itself: people_home accounting + the host lifecycle
# ---------------------------------------------------------------------------

def test_placement_decrements_people_home_and_hosts():
    cs = _own_occ(_card_state(), 0, "tree_inspector")
    cs = _stock_tree_inspector(cs, 0, 2)
    home_before = cs.players[0].people_home
    cs = step(cs, PlaceWorker(space="card:tree_inspector"))
    # people_home accounting exactly like a board placement.
    assert cs.players[0].people_home == home_before - 1
    # The on-card worker marker records occupancy.
    assert card_space_worker_count(cs.players[0], "tree_inspector") == 1
    # Hosted with the generic action-space lifecycle, space_id = "card:<id>".
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingActionSpace)
    assert top.space_id == "card:tree_inspector"
    assert top.phase == "before"
    # No trigger owned -> the singleton Proceed, then the after-window's Stop.
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())
    assert cs.pending_stack[-1].phase == "after"
    assert legal_actions(cs) == [Stop()]


# ---------------------------------------------------------------------------
# Occupancy: a second same-round use is blocked; alternation unaffected
# ---------------------------------------------------------------------------

def test_occupied_blocks_second_use_and_alternation_runs():
    cs = _own_occ(_card_state(), 0, "collector")
    first = _card_placements(legal_actions(cs), "collector")[0]
    cs = run_actions(cs, [first, Proceed(), Stop()])
    # The turn ended -> alternation rotated to P1 (people_home keyed).
    assert cs.current_player == 1
    assert card_space_occupied(cs.players[0], "collector")
    # P1 places somewhere; back to P0: the occupied card space is not offered.
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])
    assert cs.current_player == 0
    assert _card_placements(legal_actions(cs), "collector") == []


# ---------------------------------------------------------------------------
# The return-home reset clears the marker; next round it is placeable again
# ---------------------------------------------------------------------------

def test_reset_full_round_loop():
    cs = _own_occ(_card_state(), 0, "collector")
    # Round 1, P0 worker 1: Collector.
    cs = run_actions(cs, [
        _card_placements(legal_actions(cs), "collector")[0], Proceed(), Stop()])
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])   # P1 worker 1
    cs = run_actions(cs, [PlaceWorker(space="forest")])        # P0 worker 2 (atomic)
    cs = run_actions(cs, [PlaceWorker(space="fishing")])       # P1 worker 2
    # All workers placed -> round end -> the reveal pause for round 2.
    assert isinstance(cs.pending_stack[-1], PendingReveal)
    assert cs.phase is Phase.PREPARATION
    # The reset ran: everyone is home, and the on-card marker is cleared.
    assert cs.players[0].people_home == cs.players[0].people_total
    assert not card_space_occupied(cs.players[0], "collector")
    # Complete the reveal; round 2 begins and Collector is placeable again —
    # now at its 2nd-use width, C(10,7) = 120.
    reveal = [a for a in legal_actions(cs)][0]
    cs = step(cs, reveal)
    assert cs.phase is Phase.WORK and cs.round_number == 2
    cs = with_current_player(cs, 0)
    assert len(_card_placements(legal_actions(cs), "collector")) == 120


# ---------------------------------------------------------------------------
# The hook ruling: an every-space hook card fires on a card-space use
# ---------------------------------------------------------------------------

def test_every_space_hook_card_fires_on_card_space_use():
    """Work Certificate ("each time after you use an action space, you can take
    1 building resource from a stocked accumulation space") must fire in the
    after-window of a CARD-space use — card spaces count as action spaces for
    other cards' hooks (ruling 74)."""
    cs = _own_occ(_card_state(), 0, "tree_inspector")
    cs = _own_minor(cs, 0, "work_certificate")
    cs = _stock_tree_inspector(cs, 0, 1)
    cs = with_space(cs, "forest", revealed=True, accumulated=Resources(wood=4))
    cs = step(cs, PlaceWorker(space="card:tree_inspector"))
    cs = step(cs, Proceed())
    after = legal_actions(cs)
    assert cs.pending_stack[-1].phase == "after"
    assert FireTrigger(card_id="work_certificate", variant="forest:wood") in after
    # Firing works off the card-space host exactly as off a board host.
    cs = step(cs, FireTrigger(card_id="work_certificate", variant="forest:wood"))
    assert cs.players[0].resources.wood == 1 + 1   # the sweep (1) + the take (1)


# ---------------------------------------------------------------------------
# Henpecked Husband: the first person on a CARD space is returnable
# ---------------------------------------------------------------------------

def test_henpecked_return_from_card_space():
    cs = _own_occ(_card_state(), 0, "collector")
    cs = _own_occ(cs, 0, "henpecked_husband")
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, wood=5, reed=2)
    # P0's 1st placement: Collector — the record stamps ("card:collector").
    cs = run_actions(cs, [
        _card_placements(legal_actions(cs), "collector")[0], Proceed(), Stop()])
    assert cs.players[0].card_state.get("henpecked_husband") == (1, "card:collector")
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])   # P1
    # P0's 2nd placement: a named Build Rooms action -> the mandatory return
    # fires at the after-flip; the on-card worker comes home.
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),
    ])
    assert cs.players[0].people_home == 1
    assert not card_space_occupied(cs.players[0], "collector")
    cs = run_actions(cs, [Stop(), Proceed(), Stop()])          # end the build turn
    cs = run_actions(cs, [PlaceWorker(space="fishing")])       # P1
    # The vacated card space is OPEN again (occupancy is solely worker
    # presence — the Tea Time ruling) at its 2nd-use width.
    assert cs.current_player == 0
    assert len(_card_placements(legal_actions(cs), "collector")) == 120


# ---------------------------------------------------------------------------
# Family byte-identity: the pre-change fingerprints reproduce exactly
# ---------------------------------------------------------------------------

def _family_fingerprint(setup_seed, agent_seed, max_steps=400):
    """SHA-256 over every step's canonical state JSON + the sorted wire
    encodings (type name + action_to_params) of its legal actions — the exact
    contracts the C++ differential gates consume."""
    state = setup(seed=setup_seed)
    rng = np.random.default_rng(agent_seed)
    h = hashlib.sha256()
    steps = 0
    while state.phase != Phase.BEFORE_SCORING and steps < max_steps:
        acts = filter_implemented(legal_actions(state))
        h.update(canonical.dumps(state).encode())
        wire = sorted(
            json.dumps([type(a).__name__, action_to_params(a)], sort_keys=True)
            for a in acts)
        h.update(json.dumps(wire).encode())
        state = step(state, acts[int(rng.integers(len(acts)))])
        steps += 1
    h.update(canonical.dumps(state).encode())
    return steps, h.hexdigest()


def test_family_game_byte_identical_to_pre_change():
    """Two full random Family games; the digests were captured on the
    pre-change engine (2026-07-21, before the card-space machinery landed),
    so a match proves the Family state JSON, the legal-action set, and the
    wire encoding are all byte-unchanged."""
    assert _family_fingerprint(7, 11) == (
        210, "7717f31b891e1c1f12435927c82f182f3025fc6bf5a300cbef450a1f1fc483f7")
    assert _family_fingerprint(3, 5) == (
        199, "1a5b0f45af4d4a64032e93e8caaa0ee0854a604ecd039b4c4afedb05f9f74af8")


def test_family_placement_actions_carry_default_picks():
    """A Family placement never sets `picks`; the wire encoding omits it."""
    state = setup(seed=0)
    for a in legal_actions(state):
        assert isinstance(a, PlaceWorker)
        assert a.picks is None
        assert "picks" not in action_to_params(a)


def test_canonical_roundtrip_mid_card_space_turn():
    """A CARDS state paused mid-card-space-turn (the host frame carrying a
    non-None `picks`) serializes, round-trips, and re-serializes identically —
    the canonical contract for the new frame field."""
    cs = _own_occ(_card_state(), 0, "collector")
    picks = ("wood", "clay", "reed", "stone", "grain", "veg")
    mid = step(cs, PlaceWorker(space="card:collector", picks=picks))
    assert mid.pending_stack[-1].picks == picks
    s = canonical.dumps(mid)
    assert '"picks"' in s                       # non-default -> emitted
    rt = canonical.loads(s)
    assert rt == mid and hash(rt) == hash(mid) and canonical.dumps(rt) == s
    # The wire encoding carries the payload and re-tuples it on the way back.
    from agricola.agents.nn.trace_replay import action_from_params
    a = PlaceWorker(space="card:collector", picks=picks)
    params = action_to_params(a)
    assert params["picks"] == picks
    assert action_from_params("PlaceWorker", json.loads(json.dumps(params))) == a
