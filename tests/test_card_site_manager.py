import agricola.cards.site_manager  # noqa: F401

"""Tests for Site Manager (occupation, deck D #95) — the on-play optional grant to
build one major improvement, with a grant-scoped payment substitution.

Card text (verbatim): "When you play this card, immediately build a major improvement.
When paying its cost, you can replace up to 1 building resource of each type with
1 food each."

User ruling 2026-07-21 (ruling 74): the build is OPTIONAL despite the imperative
wording — the `PendingGrantedSubAction` wrapper (subactions=("build_major",)) with
Stop as the decline. Choosing pushes a BARE `PendingBuildMajor` (never the composite
"Major or Minor Improvement" action), full menu (major_allowed=None). The
substitution is a `register_conversion("build_major", ...)` gated on
`ctx.granted_by == "card:site_manager"`, so it prices exactly this grant's build.

The real flow is exercised end-to-end: a real Lessons placement in CARDS mode plays
the card (first occupation — free), the wrapper appears, and the granted build is
committed with a substituted payment.
"""
from agricola.actions import (ChooseSubAction, CommitBuildMajor, CommitPlayMinor,
                              CommitPlayOccupation, PlaceWorker, Stop)
from agricola.cards.cost_mods import CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (PendingBuildMajor, PendingGrantedSubAction,
                              PendingPlayOccupation, PendingSubActionSpace)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

_BUILD_MAJOR = ChooseSubAction(name="build_major")

FIREPLACE = 0      # printed cost 2 clay
WELL = 4           # printed cost 3 stone + 1 wood

_POOL = CardPool(
    occupations=("site_manager",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, res=None):
    """A 2-player card-mode round-1 WORK state with `site_manager` in the active
    player's hand (opponent hand cleared) and the given resources."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_occupations": frozenset({"site_manager"})}
    if res is not None:
        changes["resources"] = res
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_occupations=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _play_site_manager(res):
    """The REAL flow: place a worker on Lessons (CARDS mode), choose play_occupation,
    commit Site Manager (first occupation — free). Returns the state at the on-play
    wrapper + the active player index."""
    cs, cp = _card_state(res=res)
    cs = step(cs, PlaceWorker(space="lessons"))
    choose = next(a for a in legal_actions(cs)
                  if isinstance(a, ChooseSubAction) and a.name == "play_occupation")
    cs = step(cs, choose)
    commit = next(a for a in legal_actions(cs)
                  if isinstance(a, CommitPlayOccupation)
                  and a.card_id == "site_manager")
    cs = step(cs, commit)
    return cs, cp


def _well_payments(cs):
    """The offered payment set for the Well among the current CommitBuildMajor actions."""
    return {a.payment for a in legal_actions(cs)
            if isinstance(a, CommitBuildMajor) and a.major_idx == WELL}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_site_manager_registered():
    assert "site_manager" in OCCUPATIONS
    # The substitution is a build_major conversion — and ONLY build_major.
    assert "site_manager" in {cid for _o, cid, _f, _r in CONVERSIONS["build_major"]}
    for kind, rows in CONVERSIONS.items():
        if kind != "build_major":
            assert "site_manager" not in {cid for _o, cid, _f, _r in rows}


# ---------------------------------------------------------------------------
# The real flow: Lessons play → the optional build wrapper (ruling 74)
# ---------------------------------------------------------------------------

def test_play_pushes_optional_build_wrapper():
    cs, cp = _play_site_manager(Resources(wood=1, stone=3, food=2))
    assert "site_manager" in cs.players[cp].occupations
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.subactions == ("build_major",)
    assert top.initiated_by_id == "card:site_manager"
    assert top.major_allowed is None          # full menu — no restriction
    la = legal_actions(cs)
    assert _BUILD_MAJOR in la                 # take the build
    assert Stop() in la                       # decline (ruling 74: OPTIONAL)


def test_grant_is_bare_build_major_full_menu():
    # Plenty of everything → every unbuilt major must be on offer (no menu
    # restriction), through a BARE PendingBuildMajor (not the composite action).
    cs, cp = _play_site_manager(Resources(wood=9, clay=9, reed=9, stone=9, food=9))
    cs = step(cs, _BUILD_MAJOR)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.allowed_majors is None
    assert top.initiated_by_id == "card:site_manager"
    la = legal_actions(cs)
    # Bare build: no play-minor branch (the composite's tell).
    assert not any(isinstance(a, CommitPlayMinor) for a in la)
    majors_offered = {a.major_idx for a in la if isinstance(a, CommitBuildMajor)}
    assert majors_offered == set(range(10))


# ---------------------------------------------------------------------------
# The substitution: exact variant set, and the up-to-1-per-type cap
# ---------------------------------------------------------------------------

def test_well_substitution_variants_exact():
    # Well = 3 stone + 1 wood: each present type (stone, wood) may have UP TO 1 unit
    # replaced by 1 food → exactly the 4 subset variants, all Pareto-incomparable.
    cs, cp = _play_site_manager(Resources(wood=1, stone=3, food=2))
    cs = step(cs, _BUILD_MAJOR)
    payments = _well_payments(cs)
    assert payments == {
        Resources(wood=1, stone=3),           # unchanged printed cost
        Resources(wood=1, stone=2, food=1),   # 1 stone -> 1 food
        Resources(stone=3, food=1),           # 1 wood  -> 1 food
        Resources(stone=2, food=2),           # both
    }
    # The cap: never 2 units of one type replaced.
    assert Resources(wood=1, stone=1, food=2) not in payments
    assert Resources(stone=1, food=3) not in payments


def test_cap_on_a_single_type_cost():
    # Fireplace = 2 clay: only 1 of the 2 clay may become food — never both.
    cs, cp = _play_site_manager(Resources(clay=2, food=2))
    cs = step(cs, _BUILD_MAJOR)
    payments = {a.payment for a in legal_actions(cs)
                if isinstance(a, CommitBuildMajor) and a.major_idx == FIREPLACE}
    assert payments == {Resources(clay=2), Resources(clay=1, food=1)}
    assert Resources(food=2) not in payments


# ---------------------------------------------------------------------------
# Committing a substituted payment: the exact debit, end-to-end walk-out
# ---------------------------------------------------------------------------

def test_substituted_payment_exact_debit():
    # Only 2 stone: the printed Well cost (3s+1w) is UNAFFORDABLE — the substitution
    # is what makes the Well buildable, and the wrapper's eligibility gate must
    # already see that grant-scoped pricing (build offered at the wrapper).
    cs, cp = _play_site_manager(Resources(wood=1, stone=2, food=2))
    assert _BUILD_MAJOR in legal_actions(cs)
    cs = step(cs, _BUILD_MAJOR)
    payments = _well_payments(cs)
    assert Resources(wood=1, stone=3) not in payments      # unaffordable printed cost
    commit = next(a for a in legal_actions(cs)
                  if isinstance(a, CommitBuildMajor) and a.major_idx == WELL
                  and a.payment == Resources(wood=1, stone=2, food=1))
    cs = step(cs, commit)
    # Well owned; the substituted payment debited EXACTLY: -1 wood, -2 stone, -1 food.
    assert cs.board.major_improvement_owners[WELL] == cp
    assert cs.players[cp].resources.wood == 0
    assert cs.players[cp].resources.stone == 0
    assert cs.players[cp].resources.food == 1
    # Walk the nested frames out cleanly.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor) and top.phase == "after"
    cs = step(cs, Stop())                     # pop PendingBuildMajor
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert top.chosen == frozenset({"build_major"})
    assert legal_actions(cs) == [Stop()]      # build taken once → only Stop
    cs = step(cs, Stop())                     # pop the wrapper
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation) and top.phase == "after"
    cs = step(cs, Stop())                     # pop the play-occupation host
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    cs = step(cs, Stop())                     # pop the Lessons host
    assert not any(isinstance(f, (PendingGrantedSubAction, PendingBuildMajor,
                                  PendingPlayOccupation)) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# The substitution is scoped to THIS grant (a normal build gets none)
# ---------------------------------------------------------------------------

def test_no_substitution_on_a_normal_major_build():
    # Owning Site Manager does NOT change a normal Major Improvement action's
    # pricing: granted_by is None there, so the conversion returns the cost
    # unchanged and only the printed Well payment surfaces.
    cs, cp = _card_state(res=Resources(wood=1, stone=3, food=2))
    p = fast_replace(cs.players[cp], hand_occupations=frozenset(),
                     occupations=frozenset({"site_manager"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i]
                                        for i in range(2)))
    cs = with_pending_stack(cs, (PendingBuildMajor(
        player_idx=cp, initiated_by_id="space:major_improvement"),))
    payments = _well_payments(cs)
    assert payments == {Resources(wood=1, stone=3)}
    assert Resources(wood=1, stone=2, food=1) not in payments
    assert Resources(stone=3, food=1) not in payments


# ---------------------------------------------------------------------------
# Decline path: the wrapper's Stop, no build, nothing debited
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    cs, cp = _play_site_manager(Resources(wood=1, stone=3, food=2))
    owners0 = cs.board.major_improvement_owners
    cs = step(cs, Stop())                     # decline the build grant (ruling 74)
    assert cs.board.major_improvement_owners == owners0
    assert cs.players[cp].resources == Resources(wood=1, stone=3, food=2)
    assert "site_manager" in cs.players[cp].occupations   # the play itself stands
    cs = step(cs, Stop())                     # pop the play-occupation host
    cs = step(cs, Stop())                     # pop the Lessons host
    assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Dead-end guard: nothing affordable under the granted pricing → only Stop
# ---------------------------------------------------------------------------

def test_no_dead_end_when_nothing_affordable():
    # Zero resources: no major is payable even with the substitution (every major
    # still needs >=1 building resource after up-to-1-per-type replacement), so the
    # wrapper (pushed unconditionally — the oven_site pattern) offers only Stop.
    cs, cp = _play_site_manager(Resources())
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction)
    assert legal_actions(cs) == [Stop()]
