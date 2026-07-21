import agricola.cards.stone_company  # noqa: F401  (registers the card)
import agricola.cards.forest_stone  # noqa: F401  (a stone-alt-cost minor for the play-minor branch)

"""Tests for Stone Company (minor improvement, A23; Artifex Expansion).

Card text: "Immediately after each time you use a \"Quarry\" accumulation
space, you get a \"Major or Minor Improvement\" action during which you must
spend at least 1 stone." Cost 2 Clay + 1 Reed; 1 VP; no prerequisite.

Classification (user ruling 2026-07-21): an OPTIONAL after_action_space trigger
on the two quarry hosts (western_quarry / eastern_quarry — atomic accumulation
spaces, so the card hooks them); firing pushes the NAMED composite
PendingMajorMinorImprovement with min_spend=Resources(stone=1), which the
choose-handler threads onto the child build-major / play-minor frames so only
payments spending >= 1 stone are offered (the Cooking-Hearth Fireplace-return
route never qualifies). Eligibility fires only when something is buildable /
playable UNDER the constraint (no dead host).
"""
from agricola.actions import (ChooseSubAction, CommitBuildMajor, FireTrigger,
                              PlaceWorker, Proceed, Stop)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.cost import ReturnImprovement
from agricola.engine import step
from agricola.legality import (_can_afford_any_major_improvement, legal_actions,
                               playable_minors)
from agricola.pending import (PendingActionSpace, PendingBuildMajor,
                              PendingClayOven, PendingMajorMinorImprovement)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_majors
from tests.test_utils import sole_build_major, sole_play_minor

CARD_ID = "stone_company"
QUARRIES = ("western_quarry", "eastern_quarry")
CLAY_OVEN = 5   # 3 clay + 1 stone — the cheapest stone-spending major
MIN_SPEND = Resources(stone=1)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "corn_scoop", "forest_stone") + tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id=CARD_ID)


def _offered(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state))


def _state(*, seed=5, res=None, hand=(), occ=(), stone=1, quarry="western_quarry",
           played=True):
    """Card-mode state: the active player has played Stone Company (or holds it in
    hand when played=False), holds `hand` minors / owns `occ` occupations with
    resources `res`; `quarry` is revealed, free, and stocked with `stone` stone.
    Opponent's hand is emptied so it can never play (keeps flows deterministic)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, quarry),
                      revealed=True, workers=(0, 0),
                      accumulated=Resources(stone=stone))
    cs = fast_replace(cs, board=with_space(cs.board, quarry, sp))
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(
        p,
        minor_improvements=(p.minor_improvements | {CARD_ID} if played
                            else p.minor_improvements),
        hand_minors=frozenset(hand) | (frozenset() if played else {CARD_ID}),
        occupations=p.occupations | set(occ),
        resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _use_quarry(state, quarry="western_quarry"):
    """Drive the hosted quarry lifecycle up to the after window (take included)."""
    state = step(state, PlaceWorker(space=quarry))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())               # the take: stone to player, space zeroed
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=2, reed=1))
    assert spec.vps == 1
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.passing_left is False
    trig = next(e for e in TRIGGERS.get("after_action_space", ())
                if e.card_id == CARD_ID)
    assert not trig.mandatory                    # a granted action is optional
    for sid in QUARRIES:                         # atomic spaces are hosted
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[sid]


# ---------------------------------------------------------------------------
# POSITIVE: fire -> build a stone-costing major end-to-end through the
# constrained composite; the latch makes it once per use
# ---------------------------------------------------------------------------

def test_fire_build_stone_major_end_to_end():
    # 3 clay on hand + the 1 stone taken from the quarry pays the Clay Oven
    # (3 clay + 1 stone), a payment spending >= 1 stone.
    cs, cp = _state(res=Resources(clay=3), stone=1)
    cs = _use_quarry(cs)
    assert cs.players[cp].resources.stone == 1   # the take happened

    assert _offered(cs)
    cs = step(cs, _FIRE)                         # granted composite pushed
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement)
    assert top.initiated_by_id == "card:stone_company"
    assert top.min_spend == MIN_SPEND

    cs = step(cs, ChooseSubAction(name="build_major"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.min_spend == MIN_SPEND            # constraint threaded to the child

    # Only the Clay Oven qualifies: the Fireplaces (2c/3c) spend no stone, and
    # every other stone-costing major needs more stone/clay than we hold.
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitBuildMajor)]
    assert {c.major_idx for c in commits} == {CLAY_OVEN}
    for c in commits:                            # every offer spends >= 1 stone
        assert not isinstance(c.payment, ReturnImprovement)
        assert c.payment.stone >= 1

    cs = step(cs, sole_build_major(cs, CLAY_OVEN))
    assert isinstance(cs.pending_stack[-1], PendingClayOven)
    cs = step(cs, Stop())                        # decline the oven's free bake
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor) and top.phase == "after"
    cs = step(cs, Stop())                        # pop build-major -> composite flips
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    cs = step(cs, Stop())                        # pop the granted composite

    # Back at the quarry host's after phase: latched once per use.
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert not _offered(cs)
    cs = step(cs, Stop())                        # pop the quarry host; turn ends

    assert cs.board.major_improvement_owners[CLAY_OVEN] == cp
    assert cs.players[cp].resources.clay == 0
    assert cs.players[cp].resources.stone == 0   # 1 taken, 1 spent


# ---------------------------------------------------------------------------
# POSITIVE: the play-minor branch — a minor payable with >= 1 stone qualifies
# ---------------------------------------------------------------------------

def test_fire_play_stone_costing_minor_end_to_end():
    # Forest Stone's alternative cost is 1 stone (prereq: 1 occupation). With no
    # clay, no major qualifies — eligibility comes from the minor branch alone.
    cs, cp = _state(hand=("forest_stone",), occ=("o0",), stone=1)
    cs = _use_quarry(cs)
    assert cs.players[cp].resources.stone == 1

    assert _offered(cs)
    cs = step(cs, _FIRE)
    cs = step(cs, ChooseSubAction(name="play_minor"))
    commit = sole_play_minor(cs, "forest_stone")
    assert commit.payment == Resources(stone=1)  # the qualifying (only) payment
    cs = step(cs, commit)
    cs = step(cs, Stop())                        # pop play-minor -> composite flips
    cs = step(cs, Stop())                        # pop the granted composite
    cs = step(cs, Stop())                        # pop the quarry host

    assert "forest_stone" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.stone == 0   # 1 taken, 1 spent


# ---------------------------------------------------------------------------
# NON-QUALIFYING: affordable improvements that spend no stone don't count
# ---------------------------------------------------------------------------

def test_not_offered_when_no_payment_spends_stone():
    # 2 clay affords a Fireplace — but that payment spends no stone, and with
    # only the 1 taken stone nothing stone-costing is affordable.
    cs, cp = _state(res=Resources(clay=2), stone=1)
    cs = _use_quarry(cs)
    assert cs.players[cp].resources.stone == 1   # the take still happened
    p = cs.players[cp]
    # Unconstrained the Fireplace IS affordable — the min-spend filter, not
    # poverty, is what blocks the grant.
    assert _can_afford_any_major_improvement(cs, p)
    assert not _can_afford_any_major_improvement(cs, p, min_spend=MIN_SPEND)
    assert not _offered(cs)


def test_stoneless_minor_does_not_qualify():
    # Corn Scoop (1 wood) is playable unconstrained, but its payment spends no
    # stone -> the minor branch is empty under the constraint -> not offered.
    cs, cp = _state(res=Resources(wood=1), hand=("corn_scoop",), stone=1)
    cs = _use_quarry(cs)
    assert playable_minors(cs, cp, composite_only_ok=True) == ["corn_scoop"]
    assert playable_minors(cs, cp, composite_only_ok=True,
                           min_spend=MIN_SPEND) == []
    assert not _offered(cs)


# ---------------------------------------------------------------------------
# The Cooking-Hearth Fireplace-return route never satisfies the constraint
# ---------------------------------------------------------------------------

def test_fireplace_return_route_does_not_qualify():
    # Owning a Fireplace makes a Cooking Hearth affordable unconstrained (the
    # return route) — but returning a Fireplace spends no stone, so under the
    # constraint nothing qualifies and the trigger is not offered at all.
    cs, cp = _state(res=Resources(), stone=1)
    cs = with_majors(cs, owner_by_idx={0: cp})   # own the cheap Fireplace
    cs = _use_quarry(cs)
    p = cs.players[cp]
    assert _can_afford_any_major_improvement(cs, p)               # via the return route
    assert not _can_afford_any_major_improvement(cs, p, min_spend=MIN_SPEND)
    assert not _offered(cs)


def test_fireplace_return_route_not_among_the_offers():
    # With 4 clay + the taken stone the trigger IS offered (Clay Oven qualifies),
    # but the Cooking Hearths never appear: 4-clay and return-a-Fireplace both
    # spend no stone.
    cs, cp = _state(res=Resources(clay=4), stone=1)
    cs = with_majors(cs, owner_by_idx={0: cp})
    cs = _use_quarry(cs)
    assert _offered(cs)
    cs = step(cs, _FIRE)
    cs = step(cs, ChooseSubAction(name="build_major"))
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitBuildMajor)]
    assert {c.major_idx for c in commits} == {CLAY_OVEN}
    assert not any(c.major_idx in (2, 3) for c in commits)        # no Cooking Hearth
    assert not any(isinstance(c.payment, ReturnImprovement) for c in commits)


# ---------------------------------------------------------------------------
# Optionality: declinable (Stop without firing); the latch is per use
# ---------------------------------------------------------------------------

def test_declinable_and_fresh_next_use():
    cs, cp = _state(res=Resources(clay=3), stone=1)
    cs = _use_quarry(cs)
    assert _offered(cs)
    assert any(isinstance(a, Stop) for a in legal_actions(cs))
    cs = step(cs, Stop())                        # decline: pop the host instead
    assert all(not isinstance(f, PendingMajorMinorImprovement)
               for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == 3    # nothing was spent
    assert cs.players[cp].resources.stone == 1   # the take still happened

    # A LATER use is a fresh grant (the latch lives on the per-use host frame).
    sp = fast_replace(get_space(cs.board, "western_quarry"),
                      workers=(0, 0), accumulated=Resources(stone=1))
    cs = fast_replace(cs, board=with_space(cs.board, "western_quarry", sp),
                      current_player=cp)
    cs = _use_quarry(cs)
    assert _offered(cs)


# ---------------------------------------------------------------------------
# Both quarries trigger
# ---------------------------------------------------------------------------

def test_eastern_quarry_also_grants():
    cs, cp = _state(res=Resources(clay=3), stone=1, quarry="eastern_quarry")
    cs = _use_quarry(cs, quarry="eastern_quarry")
    assert cs.players[cp].resources.stone == 1
    assert _offered(cs)


# ---------------------------------------------------------------------------
# Scoping: opponent's quarry use is atomic; a hand-only card is inert
# ---------------------------------------------------------------------------

def test_opponent_use_is_atomic_and_grants_nothing():
    cs, cp = _state(res=Resources(clay=3), stone=1)
    cs = fast_replace(cs, current_player=1 - cp)         # the non-owner acts
    out = step(cs, PlaceWorker(space="western_quarry"))
    # No host frame for the non-owner -> atomic fast path, no window anywhere.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[1 - cp].resources.stone == 1


def test_hand_only_is_inert():
    cs, cp = _state(res=Resources(clay=3), stone=1, played=False)
    out = step(cs, PlaceWorker(space="western_quarry"))
    # A hand card cannot fire: the space stays atomic, no host frame, no offer.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[cp].resources.stone == 1
