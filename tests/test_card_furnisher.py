import agricola.cards.furnisher  # noqa: F401  (registers the card — not wired into cards/__init__.py)
"""Tests for Furnisher (occupation, deck D #96; Consul Dirigens Expansion).

Card text: "When you play this card, you immediately get 2 wood. After each new
room you build, you can build or play 1 improvement for 1 wood less."
Clarification: "The improvement does not need to cost any wood."

User ruling 74 (2026-07-21, CARD_DEFERRED_PLANS.md): triggers on EVERY room
build (any `after_build_rooms`, regardless of `build_rooms_action` — a granted
single-room build counts, N=1); the grants resolve WITHOUT interruption (one
optional trigger; firing opens up to N consecutive improvement plays via the
`PendingGrantedSubAction` use-budget wrapper, N = rooms built that action);
build-major / play-minor are the card's OWN effect (bare frames, never the
named actions); -1 wood via `granted_by`-scoped reductions on both kinds; the
improvement need not cost wood (printed clarification).
"""
import agricola.cards.cottager  # noqa: F401  (the non-named-action rooms addition)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildMajor,
    CommitBuildRoom,
    CommitPlayMinor,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import (
    PendingBuildMajor,
    PendingBuildRooms,
    PendingFarmExpansion,
    PendingGrantedSubAction,
    PendingMajorMinorImprovement,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

from tests.factories import with_current_player, with_resources

CARD_ID = "furnisher"
GRANTED_BY = f"card:{CARD_ID}"

# Major idx 7 = Joinery (2 wood + 2 stone) — the wood-cost major for the
# exact-debit assertions. Real implemented minors used from hand:
#   manger      — 2 wood, no prereq, inert on play (scoring-only)
#   beer_stall  — 1 wood, no prereq (the "playable only via the -1" case)
#   lumber_mill — 2 stone, 0 wood (the printed wood-free clarification)
JOINERY = 7

# Dummy pools — the tests inject ownership/hands directly; the pool only feeds
# the CARDS-mode hand deal (unregistered ids, so the dealt hands are inert).
_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers (the bed_maker/family_friendly_home test idioms, CARDS mode)
# ---------------------------------------------------------------------------

def _replace_player(state, idx, p):
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, occupations=p.occupations | {card_id}))


def _hand_minor(state, idx, card_id):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, hand_minors=p.hand_minors | {card_id}))


def _base_state(*, wood, reed, stone=0, hand=()):
    """CARDS-mode round-1 WORK state; P0 active with Furnisher played,
    resources exactly (wood, reed, stone), the given real minors in hand."""
    state, _env = setup_env(seed=0, card_pool=_POOL)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=wood, reed=reed, stone=stone)
    state = _own_occupation(state, 0)
    for cid in hand:
        state = _hand_minor(state, 0, cid)
    return state


def _enter_build_rooms(state):
    """Drive the real Farm Expansion flow to the Build Rooms host push."""
    state = step(state, PlaceWorker(space="farm_expansion"))
    assert isinstance(state.pending_stack[-1], PendingFarmExpansion)
    state = step(state, ChooseSubAction(name="build_rooms"))
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    return state


def _commit_any_room(state):
    build = next(a for a in legal_actions(state) if isinstance(a, CommitBuildRoom))
    return step(state, build)


def _to_after_window(state, rooms):
    """Build `rooms` rooms, then Proceed — opening the after-window."""
    for _ in range(rooms):
        state = _commit_any_room(state)
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms) and top.phase == "after"
    assert top.num_built == rooms
    return state


def _walk_out(state):
    """Exit every open frame (Proceed/Stop) until the turn ends."""
    while state.pending_stack:
        la = legal_actions(state)
        if Stop() in la:
            state = step(state, Stop())
        elif Proceed() in la:
            state = step(state, Proceed())
        else:
            raise AssertionError(f"cannot exit frame: {la}")
    return state


# ---------------------------------------------------------------------------
# Registration (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # On-play: exactly +2 wood, nothing else.
    state, _env = setup_env(seed=0, card_pool=_POOL)
    before = state.players[0].resources
    after_state = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after_state.players[0].resources == before + Resources(wood=2)
    assert after_state.players[1] == state.players[1]
    # An optional (never mandatory) trigger on after_build_rooms (ruling 74) —
    # and NOT on the before-window, and not an automatic effect.
    assert CARD_ID in CARDS
    assert CARDS[CARD_ID].mandatory is False
    assert any(e.card_id == CARD_ID for e in TRIGGERS["after_build_rooms"])
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_build_rooms", ()))
    for event, entries in AUTO_EFFECTS.items():
        assert not any(e.card_id == CARD_ID for e in entries), event
    # The -1 wood registers on BOTH improvement kinds (ruling 74).
    assert any(cid == CARD_ID for cid, _ in REDUCTIONS["build_major"])
    assert any(cid == CARD_ID for cid, _ in REDUCTIONS["play_minor"])


# ---------------------------------------------------------------------------
# The real flow: 2 rooms -> fire -> 2 uses (major at -1, minor at -1) -> Stop
# ---------------------------------------------------------------------------

def test_full_flow_two_rooms_two_uses():
    # 2 rooms (10 wood + 4 reed) + Joinery granted (1 wood + 2 stone) +
    # manger granted (1 wood): wood 12, reed 4, stone 2 — exact.
    s = _base_state(wood=12, reed=4, stone=2, hand=("manger",))
    s = _enter_build_rooms(s)
    # Not offered in the before-window nor between room commits.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _commit_any_room(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _commit_any_room(s)
    s = step(s, Proceed())                 # the work-complete flip
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.initiated_by_id == GRANTED_BY
    assert top.subactions == ("build_major", "play_minor")
    assert top.max_uses == 2 and top.uses_done == 0
    assert top.minor_is_action is False and top.major_allowed is None
    la = legal_actions(s)
    assert ChooseSubAction(name="build_major") in la
    assert ChooseSubAction(name="play_minor") in la
    assert Stop() in la

    # Use 1: build Joinery at -1 wood (1 wood + 2 stone, NOT the full 2+2).
    s = step(s, ChooseSubAction(name="build_major"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.initiated_by_id == GRANTED_BY and top.allowed_majors is None
    assert s.pending_stack[-2].uses_done == 1
    la = legal_actions(s)
    reduced = CommitBuildMajor(major_idx=JOINERY, payment=Resources(wood=1, stone=2))
    full = CommitBuildMajor(major_idx=JOINERY, payment=Resources(wood=2, stone=2))
    assert reduced in la and full not in la
    wood_before, stone_before = s.players[0].resources.wood, s.players[0].resources.stone
    s = step(s, reduced)
    assert s.players[0].resources.wood == wood_before - 1      # exact: 2 - 1
    assert s.players[0].resources.stone == stone_before - 2
    assert s.board.major_improvement_owners[JOINERY] == 0
    s = step(s, Stop())                    # pop the build-major after-phase
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.uses_done == 1

    # Use 2: play manger (2 wood) at -1 wood.
    s = step(s, ChooseSubAction(name="play_minor"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor)
    assert top.initiated_by_id == GRANTED_BY
    assert top.minor_improvement_action is False   # NOT the named action
    assert s.pending_stack[-2].uses_done == 2
    la = legal_actions(s)
    reduced_minor = CommitPlayMinor(card_id="manger", payment=Resources(wood=1))
    full_minor = CommitPlayMinor(card_id="manger", payment=Resources(wood=2))
    assert reduced_minor in la and full_minor not in la
    wood_before = s.players[0].resources.wood
    s = step(s, reduced_minor)
    assert s.players[0].resources.wood == wood_before - 1      # exact: 2 - 1
    assert "manger" in s.players[0].minor_improvements
    s = step(s, Stop())                    # pop the play-minor after-phase

    # Uses exhausted: only Stop remains at the wrapper.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.uses_done == 2 == top.max_uses
    assert legal_actions(s) == [Stop()]
    s = step(s, Stop())                    # pop the wrapper
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms) and top.phase == "after"
    # Latched: done for this action.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)                       # turn ends normally
    assert s.players[0].resources.wood == 0
    assert s.players[0].resources.stone == 0


# ---------------------------------------------------------------------------
# Early Stop after 1 of 2 uses
# ---------------------------------------------------------------------------

def test_early_stop_after_one_use():
    s = _base_state(wood=12, reed=4, stone=2, hand=("manger",))
    s = _enter_build_rooms(s)
    s = _to_after_window(s, rooms=2)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, ChooseSubAction(name="play_minor"))
    s = step(s, CommitPlayMinor(card_id="manger", payment=Resources(wood=1)))
    s = step(s, Stop())                    # pop the play-minor after-phase
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.uses_done == 1 < top.max_uses
    # A second use is still on offer (Joinery affordable: 1 wood + 2 stone) —
    # but Stop ends early.
    la = legal_actions(s)
    assert ChooseSubAction(name="build_major") in la and Stop() in la
    s = step(s, Stop())
    assert isinstance(s.pending_stack[-1], PendingBuildRooms)
    s = _walk_out(s)
    assert "manger" in s.players[0].minor_improvements
    assert all(o is None for o in s.board.major_improvement_owners)
    assert s.players[0].resources.stone == 2   # untouched


# ---------------------------------------------------------------------------
# Decline entirely: Stop without firing — no wrapper, nothing debited
# ---------------------------------------------------------------------------

def test_decline_entirely():
    s = _base_state(wood=12, reed=4, stone=2, hand=("manger",))
    s = _enter_build_rooms(s)
    s = _to_after_window(s, rooms=2)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, Stop())                    # decline: exit without firing
    assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack)
    s = _walk_out(s)
    p = s.players[0]
    assert p.resources.wood == 2 and p.resources.stone == 2
    assert "manger" in p.hand_minors and "manger" not in p.minor_improvements
    assert all(o is None for o in s.board.major_improvement_owners)


# ---------------------------------------------------------------------------
# Every room build (ruling 74): Cottager's granted single room -> N = 1
# ---------------------------------------------------------------------------

def test_granted_single_room_build_n1():
    # Cottager's room costs the normal 5 wood + 2 reed; beer_stall (1 wood)
    # is then playable ONLY via the -1 (wood is 0 after the build).
    s = _base_state(wood=5, reed=2, hand=("beer_stall",))
    s = _own_occupation(s, 0, "cottager")
    s = step(s, PlaceWorker(space="day_laborer"))
    fire_room = FireTrigger(card_id="cottager", variant="room")
    assert fire_room in legal_actions(s)
    s = step(s, fire_room)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    assert top.build_rooms_action is False     # NOT the named action
    s = _commit_any_room(s)
    s = step(s, Proceed())
    # The every-room-build ruling: the granted build qualifies, N = 1.
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.max_uses == 1
    s = step(s, ChooseSubAction(name="play_minor"))
    s = step(s, CommitPlayMinor(card_id="beer_stall", payment=Resources()))
    s = step(s, Stop())                    # pop the play-minor after-phase
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert legal_actions(s) == [Stop()]    # the single use is spent
    s = _walk_out(s)
    assert "beer_stall" in s.players[0].minor_improvements


# ---------------------------------------------------------------------------
# Grant-scoped: a normal Major Improvement space build pays FULL price
# ---------------------------------------------------------------------------

def test_discount_is_grant_scoped():
    s = _base_state(wood=2, reed=0, stone=2)
    s = step(s, PlaceWorker(space="major_improvement"))
    s = step(s, ChooseSubAction(name="improvement"))
    assert isinstance(s.pending_stack[-1], PendingMajorMinorImprovement)
    s = step(s, ChooseSubAction(name="build_major"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.initiated_by_id != GRANTED_BY
    la = legal_actions(s)
    full = CommitBuildMajor(major_idx=JOINERY, payment=Resources(wood=2, stone=2))
    reduced = CommitBuildMajor(major_idx=JOINERY, payment=Resources(wood=1, stone=2))
    assert full in la and reduced not in la
    s = step(s, full)
    assert s.players[0].resources.wood == 0    # full 2 wood debited
    assert s.players[0].resources.stone == 0
    assert s.board.major_improvement_owners[JOINERY] == 0


# ---------------------------------------------------------------------------
# The printed clarification: a wood-free improvement plays through the grant
# ---------------------------------------------------------------------------

def test_zero_wood_minor_playable_through_grant():
    # lumber_mill costs 2 stone, 0 wood. After the 1-room build (5 wood +
    # 2 reed) everything but the 2 stone is gone, so no major is buildable —
    # the trigger's eligibility rides on the wood-free minor alone.
    s = _base_state(wood=5, reed=2, stone=2, hand=("lumber_mill",))
    s = _enter_build_rooms(s)
    s = _to_after_window(s, rooms=1)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    la = legal_actions(s)
    assert ChooseSubAction(name="play_minor") in la
    assert ChooseSubAction(name="build_major") not in la
    s = step(s, ChooseSubAction(name="play_minor"))
    s = step(s, CommitPlayMinor(card_id="lumber_mill", payment=Resources(stone=2)))
    p = s.players[0]
    assert "lumber_mill" in p.minor_improvements
    assert p.resources.stone == 0 and p.resources.wood == 0


# ---------------------------------------------------------------------------
# The -1 wood end-to-end: a 1-wood minor at 0 wood plays through the grant
# ---------------------------------------------------------------------------

def test_one_wood_minor_at_zero_wood_through_grant():
    # beer_stall costs 1 wood; the room build leaves wood at exactly 0. It is
    # unplayable at normal pricing, playable under the grant's -1 (to 0 wood).
    s = _base_state(wood=5, reed=2, hand=("beer_stall",))
    s = _enter_build_rooms(s)
    s = _to_after_window(s, rooms=1)
    assert s.players[0].resources.wood == 0
    assert playable_minors(s, 0) == []
    assert playable_minors(s, 0, granted_by=GRANTED_BY) == ["beer_stall"]
    # Eligibility reads the granted pricing: the trigger IS offered.
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    la = legal_actions(s)
    assert ChooseSubAction(name="play_minor") in la
    assert ChooseSubAction(name="build_major") not in la
    s = step(s, ChooseSubAction(name="play_minor"))
    commit = CommitPlayMinor(card_id="beer_stall", payment=Resources())
    assert commit in legal_actions(s)
    s = step(s, commit)
    assert "beer_stall" in s.players[0].minor_improvements
    assert s.players[0].resources.wood == 0    # debited 0 wood
    s = _walk_out(s)


# ---------------------------------------------------------------------------
# Dead-end guard: nothing takeable under the granted pricing -> not offered
# ---------------------------------------------------------------------------

def test_dead_end_trigger_not_offered():
    # Exactly the 2 rooms' price: afterwards every resource is 0, the dealt
    # hand minors are unregistered dummies (never playable), and no major is
    # payable even at -1 wood.
    s = _base_state(wood=10, reed=4)
    s = _enter_build_rooms(s)
    s = _to_after_window(s, rooms=2)
    p = s.players[0]
    assert p.resources.wood == 0 and p.resources.clay == 0
    assert p.resources.stone == 0 and p.resources.reed == 0
    assert playable_minors(s, 0, granted_by=GRANTED_BY) == []
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)
