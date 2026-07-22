import agricola.cards.miller  # noqa: F401  (first: registers the card under test)
import agricola.cards.field_watchman  # noqa: F401  (an acting-player before-trigger on
#                                       Grain Seeds, for the ordering test)

"""Tests for Miller (occupation, deck E #95, players 1+).

Card text (verbatim): "You can immediately build a baking improvement by paying its
cost. Each time another player uses the "Grain Seeds" action space, you can take a
"Bake Bread" action."

Under ruling 74 (2026-07-21):
- Clause 1 (on-play, optional, NORMAL cost): a `PendingGrantedSubAction` wrapper with
  `subactions=("build_major", "play_minor")`, the major menu restricted to the baking
  majors (0, 1, 2, 3, 5, 6) via `major_allowed`, the minor menu restricted to the
  baking-spec identity seam's hand minors (Iron Oven / Simple Oven / Baking Course
  today) via `minor_allowed` -> `PendingPlayMinor.allowed_cards`, and ONE USE TOTAL
  ("build A baking improvement", singular) via the use-budget shape `max_uses=1` —
  a baking major OR a baking minor, never one of each.
- Clause 2: an any_player `before_action_space` auto on the hooked (atomic) Grain
  Seeds space that pushes the OWNER's optional bake wrapper on top of the acting
  player's host — the decider rule routes the bake decision to the owner DURING the
  opponent's turn, resolving before all of the acting player's before-action
  triggers; the wrapper's Stop declines. "Another player" never includes you.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    CommitPlayMinor,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import BAKING_SPEC_EXTENSION_CARD_IDS, legal_actions
from agricola.pending import (
    PendingActionSpace,
    PendingBakeBread,
    PendingBuildMajor,
    PendingClayOven,
    PendingGrantedSubAction,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors
from tests.test_utils import sole_play_minor

CARD_ID = "miller"
BAKING_MENU = (0, 1, 2, 3, 5, 6)     # Fireplaces, Cooking Hearths, Clay + Stone Oven
CLAY_OVEN = 5
WELL = 4

_POOL = CardPool(
    occupations=(CARD_ID, "field_watchman") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(cur=0):
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=cur)


def _own_occ(state, idx, card_id=CARD_ID):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_res(state, idx, **kw):
    p = fast_replace(state.players[idx], resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _run_turn(s, cap=40):
    steps = 0
    while s.pending_stack and steps < cap:
        s = step(s, legal_actions(s)[0])
        steps += 1
    assert steps < cap, "turn did not terminate"
    return s


def _clause2_state(*, owner=1, acting=0, owner_grain=1, fireplace=True):
    """Card-mode state: `owner` has PLAYED Miller (plus a Fireplace + grain by
    default, so the bake is doable), `acting` is the current player."""
    s = _card_state(cur=acting)
    s = _own_occ(s, owner)
    if fireplace:
        s = with_majors(s, owner_by_idx={0: owner})
    s = _set_res(s, owner, grain=owner_grain)
    return s


def _play_miller_via_lessons(res: Resources, hand_minors=None):
    """Real clause-1 flow: hold `res` (and optionally a chosen minor hand), place
    on Lessons, play Miller. Returns the state at whatever Miller's on_play left
    on top, plus the player index."""
    s = _card_state(cur=0)
    changes = {"hand_occupations": frozenset({CARD_ID}), "resources": res}
    if hand_minors is not None:
        changes["hand_minors"] = frozenset(hand_minors)
    p = fast_replace(s.players[0], **changes)
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = step(s, PlaceWorker(space="lessons"))
    s = step(s, ChooseSubAction(name="play_occupation"))
    commit = next(a for a in legal_actions(s)
                  if isinstance(a, CommitPlayOccupation) and a.card_id == CARD_ID)
    return step(s, commit), 0


def _back_to_miller_wrapper(s, cap=6):
    """Unwind [Stop]-only after-phases / empty inner wrappers until Miller's own
    grant wrapper is back on top."""
    for _ in range(cap):
        top = s.pending_stack[-1]
        if (isinstance(top, PendingGrantedSubAction)
                and top.initiated_by_id == "card:miller"):
            return s
        la = legal_actions(s)
        assert la == [Stop()], f"unexpected actions while unwinding: {la!r}"
        s = step(s, Stop())
    raise AssertionError("never returned to the Miller wrapper")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_miller_registered():
    assert CARD_ID in OCCUPATIONS
    entry = next(e for e in AUTO_EFFECTS.get("before_action_space", ())
                 if e.card_id == CARD_ID)
    assert entry.any_player          # fires on the OPPONENT's Grain Seeds use
    # Grain Seeds is atomic: the any-player hook must claim the host, on either
    # player's turn (never the own-action index — "another player", not you).
    assert CARD_ID in ANY_PLAYER_HOOK_CARDS.get("grain_seeds", set())
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("grain_seeds", set())


def test_owner_makes_grain_seeds_hosted_on_either_turn():
    s = _clause2_state(owner=1, acting=0)
    assert should_host_space(s, "grain_seeds", 0)   # opponent's turn
    assert should_host_space(s, "grain_seeds", 1)   # own turn (host, but no fire)


# ---------------------------------------------------------------------------
# Clause 1 — on-play optional build of a baking improvement (build_major half)
# ---------------------------------------------------------------------------

def test_on_play_pushes_menu_restricted_build_wrapper():
    s, cp = _play_miller_via_lessons(Resources(food=2, clay=3, stone=1, grain=1))
    assert CARD_ID in s.players[cp].occupations
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.player_idx == cp
    assert top.initiated_by_id == "card:miller"
    assert top.subactions == ("build_major", "play_minor")
    assert top.major_allowed == BAKING_MENU
    # The minor menu is the baking-spec identity seam, derived at push time.
    assert top.minor_allowed == tuple(sorted(BAKING_SPEC_EXTENSION_CARD_IDS))
    assert {"iron_oven", "simple_oven", "baking_course"} <= set(top.minor_allowed)
    assert not top.minor_is_action
    assert top.max_uses == 1                  # ONE use total, not one per category
    la = legal_actions(s)
    assert ChooseSubAction(name="build_major") in la
    # The dealt hand holds only unregistered fillers -> no menu minor playable.
    assert ChooseSubAction(name="play_minor") not in la
    assert Stop() in la


def test_build_clay_oven_at_printed_cost_with_free_bake():
    s, cp = _play_miller_via_lessons(Resources(food=2, clay=3, stone=1, grain=1))
    s = step(s, ChooseSubAction(name="build_major"))
    top = s.pending_stack[-1]
    # A BARE PendingBuildMajor (the card's OWN effect, never the composite).
    assert isinstance(top, PendingBuildMajor)
    assert top.allowed_majors == BAKING_MENU
    assert top.initiated_by_id == "card:miller"

    commit = next(a for a in legal_actions(s)
                  if isinstance(a, CommitBuildMajor) and a.major_idx == CLAY_OVEN)
    # "By paying its cost": the printed Clay Oven price, no discount.
    assert commit.payment == Resources(clay=3, stone=1)
    food0 = s.players[cp].resources.food
    s = step(s, commit)
    assert s.board.major_improvement_owners[CLAY_OVEN] == cp
    assert s.players[cp].resources.clay == 0
    assert s.players[cp].resources.stone == 0
    # A real major build → the oven's free bake-on-purchase fires as normal.
    assert isinstance(s.pending_stack[-1], PendingClayOven)
    s = step(s, ChooseSubAction(name="bake_bread"))
    s = step(s, CommitBake(grain=1))          # Clay Oven: 1 grain -> 5 food
    assert s.players[cp].resources.food == food0 + 5
    assert s.players[cp].resources.grain == 0
    s = _run_turn(s)                          # unwind: bake/oven/build/play/lessons
    assert not s.pending_stack


def test_non_menu_majors_never_offered():
    # Rich in everything: Well (3s+1w) and Joinery/Pottery/Basketmaker's are all
    # affordable, but only the baking majors may be offered.
    s, _cp = _play_miller_via_lessons(
        Resources(food=2, clay=5, stone=3, wood=2, reed=2))
    s = step(s, ChooseSubAction(name="build_major"))
    offered = {a.major_idx for a in legal_actions(s)
               if isinstance(a, CommitBuildMajor)}
    assert offered                            # something on the menu is buildable
    assert offered <= set(BAKING_MENU)
    assert WELL not in offered
    assert not offered & {7, 8, 9}


def test_clause1_grant_is_declinable():
    s, cp = _play_miller_via_lessons(Resources(food=2, clay=3, stone=1))
    clay0 = s.players[cp].resources.clay
    owners0 = s.board.major_improvement_owners
    s = step(s, Stop())                       # decline the optional build
    assert s.board.major_improvement_owners == owners0
    assert s.players[cp].resources.clay == clay0
    assert CARD_ID in s.players[cp].occupations
    s = _run_turn(s)
    assert not s.pending_stack


def test_clause1_no_dead_end_when_unaffordable():
    # No clay/stone at all -> no menu major payable (and no menu minor in hand)
    # -> the wrapper offers only Stop.
    s, _cp = _play_miller_via_lessons(Resources(food=2))
    assert isinstance(s.pending_stack[-1], PendingGrantedSubAction)
    assert legal_actions(s) == [Stop()]


def test_minor_menu_offers_only_baking_hand_minors():
    # Hand: iron_oven (a baking minor, 3 stone) + corn_scoop (a playable NON-baking
    # minor, 1 wood). Only iron_oven may be offered through the grant.
    s, cp = _play_miller_via_lessons(
        Resources(food=2, stone=3, wood=1, grain=1),
        hand_minors=("iron_oven", "corn_scoop"))
    wrapper = s.pending_stack[-1]
    assert isinstance(wrapper, PendingGrantedSubAction)
    la = legal_actions(s)
    assert ChooseSubAction(name="play_minor") in la     # iron_oven is playable
    s = step(s, ChooseSubAction(name="play_minor"))
    child = s.pending_stack[-1]
    assert isinstance(child, PendingPlayMinor)
    assert child.initiated_by_id == "card:miller"
    assert child.allowed_cards == wrapper.minor_allowed
    assert not child.minor_improvement_action           # the card's OWN effect
    commits = [a for a in legal_actions(s) if isinstance(a, CommitPlayMinor)]
    # corn_scoop is playable in general but NOT a baking improvement -> filtered.
    assert {c.card_id for c in commits} == {"iron_oven"}

    # Play it at the printed cost (3 stone) — a real minor play: iron_oven's own
    # on-play free-bake wrapper fires as normal, at its 1-grain -> 6-food rate.
    s = step(s, sole_play_minor(s, "iron_oven"))
    assert "iron_oven" in s.players[cp].minor_improvements
    assert s.players[cp].resources.stone == 0
    oven_wrap = s.pending_stack[-1]
    assert isinstance(oven_wrap, PendingGrantedSubAction)
    assert oven_wrap.initiated_by_id == "card:iron_oven"
    food0 = s.players[cp].resources.food
    s = step(s, ChooseSubAction(name="bake_bread"))
    s = step(s, CommitBake(grain=1))
    assert s.players[cp].resources.food == food0 + 6
    s = step(s, Stop())                       # pop the bake's after-phase
    s = _back_to_miller_wrapper(s)
    assert s.pending_stack[-1].uses_done == 1
    s = step(s, Stop())                       # decline nothing further remains
    s = _run_turn(s)
    assert not s.pending_stack


def test_one_use_total_not_one_of_each():
    # "Build A baking improvement" (singular): the grant is ONE use across both
    # categories (max_uses=1), never a major AND a minor.
    # Direction A — play the baking minor first: the still-affordable menu major
    # (Fireplace 0, 2 clay) must no longer be offered.
    s, _cp = _play_miller_via_lessons(
        Resources(food=2, clay=2, stone=3),
        hand_minors=("iron_oven",))
    la = legal_actions(s)
    assert ChooseSubAction(name="build_major") in la
    assert ChooseSubAction(name="play_minor") in la
    s = step(s, ChooseSubAction(name="play_minor"))
    s = step(s, sole_play_minor(s, "iron_oven"))        # no grain -> bake wrapper is inert
    s = _back_to_miller_wrapper(s)
    assert s.pending_stack[-1].uses_done == 1
    assert legal_actions(s) == [Stop()]                 # clay untouched, yet no build

    # Direction B — build the major first: the still-playable menu minor
    # (iron_oven, 3 stone) must no longer be offered.
    s, _cp = _play_miller_via_lessons(
        Resources(food=2, clay=2, stone=3),
        hand_minors=("iron_oven",))
    s = step(s, ChooseSubAction(name="build_major"))
    commit = next(a for a in legal_actions(s)
                  if isinstance(a, CommitBuildMajor) and a.major_idx == 0)
    assert commit.payment == Resources(clay=2)          # printed Fireplace cost
    s = step(s, commit)
    s = _back_to_miller_wrapper(s)
    assert s.pending_stack[-1].uses_done == 1
    assert legal_actions(s) == [Stop()]                 # stone untouched, yet no play


# ---------------------------------------------------------------------------
# Clause 2 — the opponent's Grain Seeds use grants the owner a bake (out of turn)
# ---------------------------------------------------------------------------

def test_opponent_grain_seeds_owner_bakes_out_of_turn():
    s = _clause2_state(owner=1, acting=0, owner_grain=1)
    acting_grain0 = s.players[0].resources.grain
    acting_food0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="grain_seeds"))

    # The owner's wrapper surfaces ON TOP of the acting player's host, which is
    # still in its before-phase with the space's take not yet applied.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.player_idx == 1
    assert top.initiated_by_id == "card:miller"
    assert top.subactions == ("bake_bread",)
    host = s.pending_stack[0]
    assert isinstance(host, PendingActionSpace)
    assert host.space_id == "grain_seeds" and host.player_idx == 0
    assert host.phase == "before"
    assert s.players[0].resources.grain == acting_grain0    # take not applied yet

    # The decider rule routes the decision to the OWNER during the opponent's turn.
    la = legal_actions(s)
    assert len(la) == 2
    assert ChooseSubAction(name="bake_bread") in la
    assert Stop() in la

    # The owner bakes at THEIR OWN rates (Fireplace: grain -> 2 food).
    s = step(s, ChooseSubAction(name="bake_bread"))
    bake = s.pending_stack[-1]
    assert isinstance(bake, PendingBakeBread)
    assert bake.player_idx == 1
    assert bake.initiated_by_id == "card:miller"
    s = step(s, CommitBake(grain=1))
    assert s.players[1].resources.grain == 0
    assert s.players[1].resources.food == 2
    s = step(s, Stop())                       # pop the bake's after-phase
    assert legal_actions(s) == [Stop()]       # bake taken -> only the wrapper's exit
    s = step(s, Stop())                       # pop the wrapper

    # The opponent's Grain Seeds take now completes normally.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())
    assert s.players[0].resources.grain == acting_grain0 + 1
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.current_player == 1              # the turn passed as normal
    assert s.players[0].resources.food == acting_food0   # the acting player got no bake


def test_clause2_decline_path():
    s = _clause2_state(owner=1, acting=0, owner_grain=1)
    acting_grain0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert isinstance(s.pending_stack[-1], PendingGrantedSubAction)
    s = step(s, Stop())                       # the owner declines the bake
    assert s.players[1].resources.grain == 1  # nothing spent
    assert s.players[1].resources.food == 0
    s = step(s, Proceed())
    assert s.players[0].resources.grain == acting_grain0 + 1
    s = step(s, Stop())
    assert not s.pending_stack


def test_owner_decision_resolves_before_acting_players_before_triggers():
    # The acting player owns Field Watchman (an optional before_action_space
    # trigger on Grain Seeds). Ruling 74: the OWNER's bake resolves before ALL of
    # the acting player's before-action triggers — the wrapper sits on top at the
    # host push, so the host's enumerator (which surfaces the acting player's
    # FireTriggers) cannot run until the owner's decision fully resolves.
    s = _clause2_state(owner=1, acting=0, owner_grain=1)
    s = _own_occ(s, 0, "field_watchman")
    s = step(s, PlaceWorker(space="grain_seeds"))

    assert isinstance(s.pending_stack[-1], PendingGrantedSubAction)   # owner decides
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) for a in la)   # no acting-player trigger yet
    assert s.pending_stack[0].phase == "before"              # host take not yet run

    # Resolve the owner's bake completely...
    s = step(s, ChooseSubAction(name="bake_bread"))
    s = step(s, CommitBake(grain=1))
    s = step(s, Stop())
    s = step(s, Stop())
    # ...and only NOW does the host surface the acting player's before-trigger.
    la = legal_actions(s)
    assert FireTrigger(card_id="field_watchman") in la
    assert Proceed() in la


def test_own_grain_seeds_use_fires_nothing():
    # "Another player" never includes you: the owner's own use pushes the host
    # (the hook is ownership-keyed) but Miller must not fire.
    s = _clause2_state(owner=0, acting=0, owner_grain=1)
    grain0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)   # no wrapper pushed
    assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack)
    s = _run_turn(s)
    assert s.players[0].resources.grain == grain0 + 1   # the space's own +1 only
    assert s.players[0].resources.food == 0             # no bake happened


def test_no_bake_capability_nothing_surfaces():
    # (a) A baker but no grain.
    s = _clause2_state(owner=1, acting=0, owner_grain=0)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack)
    s = _run_turn(s)
    assert s.players[1].resources.food == 0

    # (b) Grain but no baking improvement.
    s = _clause2_state(owner=1, acting=0, owner_grain=1, fireplace=False)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack)
    s = _run_turn(s)
    assert s.players[1].resources.food == 0
    assert s.players[1].resources.grain == 1            # nothing consumed


def test_auto_fires_once_per_hosting():
    # One Grain Seeds use -> exactly one wrapper, never re-pushed later in the turn.
    s = _clause2_state(owner=1, acting=0, owner_grain=2)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert sum(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack) == 1
    s = step(s, ChooseSubAction(name="bake_bread"))
    s = step(s, CommitBake(grain=1))
    s = step(s, Stop())                       # pop the bake's after-phase
    s = step(s, Stop())                       # pop the wrapper
    # From here to the end of the turn no second wrapper may appear (the
    # before-auto seam runs exactly once, at the host push).
    steps = 0
    while s.pending_stack and steps < 40:
        assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack), \
            "a second wrapper appeared after the first resolved"
        s = step(s, legal_actions(s)[0])
        steps += 1
    assert not s.pending_stack
    assert s.players[1].resources.food == 2             # exactly one bake's payout
    assert s.players[1].resources.grain == 1
