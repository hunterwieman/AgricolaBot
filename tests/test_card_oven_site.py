import agricola.cards.oven_site  # noqa: F401
import agricola.cards.stonecutter  # noqa: F401  (a real build_major −1 stone reduction)

"""Tests for Oven Site (minor improvement, A27) — the on-play optional grant to build a
Clay Oven or Stone Oven for a flat 1 clay + 1 stone, plus 2 wood unconditionally.

Card text: "When you play this card, you get 2 wood and you can immediately build the
'Clay Oven' or 'Stone Oven' major improvement. Either way, it only costs you 1 clay
and 1 stone." Prerequisite: "Both Fireplace and Cooking Hearth". No cost, kept.

The grant is the generic `PendingGrantedSubAction` wrapper (subactions=("build_major",),
major_allowed=(5, 6)); choosing pushes a BARE `PendingBuildMajor` (not the composite
"Major or Minor Improvement" action). The 1c+1s price is a grant-scoped whole-cost
`register_formula` on build_major, so other reductions stack on top (user ruling
2026-07-20). Tests push a `PendingPlayMinor` host directly (the established factory
pattern) with `oven_site` in hand and the prereq majors owned.
"""
from agricola.actions import (ChooseSubAction, CommitBake, CommitBuildMajor,
                              CommitPlayMinor, Stop)
from agricola.cards.cost_mods import FORMULA_MODS
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (PendingBuildMajor, PendingClayOven,
                              PendingGrantedSubAction, PendingPlayMinor)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack
from tests.test_utils import sole_play_minor

_BUILD_MAJOR = ChooseSubAction(name="build_major")

CLAY_OVEN, STONE_OVEN = 5, 6

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("oven_site",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, res=None):
    """A 2-player card-mode state with `oven_site` in the active player's hand (opponent
    hand cleared) and the given resources. Majors are set per-test after cp is known."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_minors": frozenset({"oven_site"})}
    if res is not None:
        changes["resources"] = res
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _own_occ(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _play_oven_site(res, *, extra_owned_majors=None, occ=None):
    """Own the prereq (Fireplace 0 + Cooking Hearth 2), hold `res`, own `occ` (optional),
    then play `oven_site` through a PendingPlayMinor host. Returns the state at the
    granted-build wrapper (or wherever play left the stack) + the active player index."""
    cs, cp = _card_state(res=res)
    majors = {0: cp, 2: cp}
    if extra_owned_majors:
        majors.update({m: cp for m in extra_owned_majors})
    cs = with_majors(cs, owner_by_idx=majors)
    if occ is not None:
        cs = _own_occ(cs, cp, occ)
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "oven_site"))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_oven_site_registered():
    assert "oven_site" in MINORS
    spec = MINORS["oven_site"]
    assert spec.cost == Cost()               # no cost
    assert spec.passing_left is False        # kept, not traveling
    assert spec.vps == 0
    assert spec.prereq is not None
    # The 1c+1s price is a build_major whole-cost formula.
    assert "oven_site" in {c for c, _a, _f in FORMULA_MODS["build_major"]}


# ---------------------------------------------------------------------------
# Prerequisite: "Both Fireplace and Cooking Hearth"
# ---------------------------------------------------------------------------

def test_prereq_requires_both_fireplace_and_cooking_hearth():
    spec = MINORS["oven_site"]
    cs, cp = _card_state()
    # Neither → not met.
    assert not prereq_met(spec, cs, cp)
    # Fireplace only → not met.
    assert not prereq_met(spec, with_majors(cs, owner_by_idx={0: cp}), cp)
    # Cooking Hearth only → not met.
    assert not prereq_met(spec, with_majors(cs, owner_by_idx={2: cp}), cp)
    # Both → met.
    assert prereq_met(spec, with_majors(cs, owner_by_idx={0: cp, 2: cp}), cp)
    # The other pair members count too (Fireplace idx 1, Cooking Hearth idx 3).
    assert prereq_met(spec, with_majors(cs, owner_by_idx={1: cp, 3: cp}), cp)
    # Opponent owning the pair does not satisfy MY prereq.
    assert not prereq_met(spec, with_majors(cs, owner_by_idx={0: 1 - cp, 2: cp}), cp)


# ---------------------------------------------------------------------------
# +2 wood is unconditional; the grant wrapper is pushed
# ---------------------------------------------------------------------------

def test_grants_2_wood_and_pushes_the_build_wrapper():
    # Start with 0 wood; after play it must be exactly +2, regardless of the build.
    cs, cp = _play_oven_site(Resources(clay=1, stone=1))
    assert cs.players[cp].resources.wood == 2
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("build_major",)
    assert top.major_allowed == (CLAY_OVEN, STONE_OVEN)
    assert top.initiated_by_id == "card:oven_site"
    la = legal_actions(cs)
    assert _BUILD_MAJOR in la     # take the build
    assert Stop() in la           # decline path


def test_2_wood_granted_even_when_declining():
    cs, cp = _play_oven_site(Resources(clay=1, stone=1))
    assert cs.players[cp].resources.wood == 2
    cs = step(cs, Stop())         # decline the build grant
    # Declining does not claw back the wood, and no oven was built.
    assert cs.players[cp].resources.wood == 2
    assert cs.board.major_improvement_owners[CLAY_OVEN] is None
    assert cs.board.major_improvement_owners[STONE_OVEN] is None
    # Clay/stone untouched (no build was paid for).
    assert cs.players[cp].resources.clay == 1
    assert cs.players[cp].resources.stone == 1


# ---------------------------------------------------------------------------
# The grant offers only the two ovens, as a BARE build (not the composite action)
# ---------------------------------------------------------------------------

def test_grant_offers_only_the_two_ovens_bare():
    cs, cp = _play_oven_site(Resources(clay=3, stone=3))
    cs = step(cs, _BUILD_MAJOR)
    top = cs.pending_stack[-1]
    # A BARE PendingBuildMajor (Oven Site's own build), NOT the composite
    # "Major or Minor Improvement" action → no play-minor branch, and repeat cards
    # (Merchant / Small Trader) cannot fire off it.
    assert isinstance(top, PendingBuildMajor)
    assert top.allowed_majors == (CLAY_OVEN, STONE_OVEN)
    assert top.initiated_by_id == "card:oven_site"
    la = legal_actions(cs)
    assert not any(isinstance(a, CommitPlayMinor) for a in la)
    majors_offered = {a.major_idx for a in la if isinstance(a, CommitBuildMajor)}
    assert majors_offered == {CLAY_OVEN, STONE_OVEN}


# ---------------------------------------------------------------------------
# The offered payment is exactly 1 clay + 1 stone (printed costs Pareto-dominated)
# ---------------------------------------------------------------------------

def test_payment_is_exactly_one_clay_one_stone():
    cs, cp = _play_oven_site(Resources(clay=3, stone=3))
    cs = step(cs, _BUILD_MAJOR)
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitBuildMajor)]
    assert {c.major_idx for c in commits} == {CLAY_OVEN, STONE_OVEN}
    # Each oven surfaces exactly one payment: the discounted 1 clay + 1 stone.
    for c in commits:
        assert c.payment == Resources(clay=1, stone=1), (c.major_idx, c.payment)
    payments = {c.payment for c in commits}
    # The printed costs (Clay Oven 3c+1s, Stone Oven 1c+3s) are Pareto-dominated, never offered.
    assert Resources(clay=3, stone=1) not in payments
    assert Resources(clay=1, stone=3) not in payments


# ---------------------------------------------------------------------------
# No dead-end: unaffordable / both-owned → the wrapper offers only Stop
# ---------------------------------------------------------------------------

def test_no_build_grant_when_unaffordable():
    # Prereq met + card played, but no clay/stone → 1c+1s unaffordable → only Stop.
    cs, cp = _play_oven_site(Resources())     # no clay, no stone
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert legal_actions(cs) == [Stop()]      # no dead-end build offered


def test_no_build_grant_when_both_ovens_owned():
    # Both ovens already owned → no buildable major on the menu → only Stop.
    cs, cp = _play_oven_site(Resources(clay=5, stone=5),
                             extra_owned_majors=(CLAY_OVEN, STONE_OVEN))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert legal_actions(cs) == [Stop()]


# ---------------------------------------------------------------------------
# Building through the grant fires the oven's free Bake Bread (a real major build)
# ---------------------------------------------------------------------------

def test_building_clay_oven_fires_free_bake():
    cs, cp = _play_oven_site(Resources(clay=1, stone=1, grain=1))
    cs = step(cs, _BUILD_MAJOR)
    commit = next(a for a in legal_actions(cs)
                  if isinstance(a, CommitBuildMajor) and a.major_idx == CLAY_OVEN)
    assert commit.payment == Resources(clay=1, stone=1)
    food0 = cs.players[cp].resources.food
    cs = step(cs, commit)
    # Oven owned; the discounted price was debited.
    assert cs.board.major_improvement_owners[CLAY_OVEN] == cp
    assert cs.players[cp].resources.clay == 0
    assert cs.players[cp].resources.stone == 0
    # The oven's free-bake wrapper is up (a real major build → free bake fires).
    assert isinstance(cs.pending_stack[-1], PendingClayOven)
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    cs = step(cs, CommitBake(grain=1))        # Clay Oven: 1 grain -> 5 food
    assert cs.players[cp].resources.food == food0 + 5
    assert cs.players[cp].resources.grain == 0
    # Drive the nested walk to completion cleanly.
    cs = step(cs, Stop())                      # pop PendingBakeBread's after-phase
    cs = step(cs, Stop())                      # pop the oven wrapper; deferred flip fires
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor) and top.phase == "after"
    cs = step(cs, Stop())                      # pop PendingBuildMajor
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.chosen == frozenset({"build_major"})
    assert legal_actions(cs) == [Stop()]       # build taken once → only Stop
    cs = step(cs, Stop())                      # pop the wrapper
    cs = step(cs, Stop())                      # pop the play-minor host
    assert not any(isinstance(f, (PendingGrantedSubAction, PendingPlayMinor,
                                  PendingBuildMajor)) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Decline via Stop leaves ownership + resources unchanged
# ---------------------------------------------------------------------------

def test_decline_build_via_stop():
    cs, cp = _play_oven_site(Resources(clay=1, stone=1))
    owners0 = cs.board.major_improvement_owners
    cs = step(cs, Stop())                       # decline the build grant (pop wrapper)
    assert cs.board.major_improvement_owners == owners0
    assert cs.players[cp].resources.clay == 1
    assert cs.players[cp].resources.stone == 1
    cs = step(cs, Stop())                       # pop the play-minor host
    assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# A cost reduction STACKS on the 1c+1s discount (the pipeline-formula ruling)
# ---------------------------------------------------------------------------

def test_discount_is_scoped_to_the_grant_not_permanent():
    # Owning Oven Site does NOT permanently cheapen ovens: a NORMAL Major Improvement
    # build (granted_by is None) pays the printed cost, because the formula gates on
    # ctx.granted_by == "card:oven_site".
    cs, cp = _card_state(res=Resources(clay=3, stone=3))
    p = fast_replace(cs.players[cp], minor_improvements=frozenset({"oven_site"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(cs, (PendingBuildMajor(
        player_idx=cp, initiated_by_id="space:major_improvement"),))
    commits = [a for a in legal_actions(cs)
               if isinstance(a, CommitBuildMajor) and a.major_idx == CLAY_OVEN]
    payments = {c.payment for c in commits}
    assert Resources(clay=3, stone=1) in payments   # printed Clay Oven cost
    assert Resources(clay=1, stone=1) not in payments  # the grant-only discount


def test_cost_reduction_stacks_on_the_discount():
    # Stonecutter reduces every build_major by 1 stone. Stacked on Oven Site's
    # 1 clay + 1 stone, an oven costs just 1 clay (stone floored to 0) — user ruling
    # 2026-07-20: reductions fold onto the grant-scoped formula through the chokepoint.
    cs, cp = _play_oven_site(Resources(clay=1), occ="stonecutter")   # 1 clay, 0 stone
    cs = step(cs, _BUILD_MAJOR)
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitBuildMajor)]
    assert commits, "an oven must be buildable at the stacked price"
    for c in commits:
        assert c.payment == Resources(clay=1), (c.major_idx, c.payment)
    # Affordable with only 1 clay: build the Clay Oven, paying 1 clay + 0 stone.
    commit = next(c for c in commits if c.major_idx == CLAY_OVEN)
    cs = step(cs, commit)
    assert cs.board.major_improvement_owners[CLAY_OVEN] == cp
    assert cs.players[cp].resources.clay == 0
    assert cs.players[cp].resources.stone == 0
