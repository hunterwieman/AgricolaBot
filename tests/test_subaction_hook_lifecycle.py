"""Lifecycle tests for the uniform sub-action host refactor
(SUBACTION_HOOK_REFACTOR.md): every commit-terminated sub-action is now a
before/after host — its Commit pivots the frame to ``phase="after"`` (no
auto-pop), the after-phase enumerator offers any after-triggers + ``Stop``, and
that trailing ``Stop`` pops the frame. After-automatic effects fire at the
commit-flip (the after-window opens), before the after-triggers are surfaced.

Covers the four cases the refactor's §8 calls out: a single-commit sub-action
(Grain Utilization bake), the ``PendingBuildMajor`` / free-oven two-deep nesting,
a minor played at the Major/Minor Improvement space (a sub-action host nested
under a parent space host), and an after-automatic effect firing at the flip.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    CommitPlayMinor,
    CommitSow,
    PlaceWorker,
    Stop,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBakeBread,
    PendingBuildMajor,
    PendingClayOven,
    PendingGrainUtilization,
    PendingMajorMinorImprovement,
    PendingPlayMinor,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

from tests.factories import with_current_player, with_majors, with_resources


# ---------------------------------------------------------------------------
# Single-commit sub-action: Grain Utilization bake
# ---------------------------------------------------------------------------

def test_grain_util_bake_before_commit_after_stop_lifecycle():
    """place -> choose bake -> before-phase -> CommitBake -> after-phase [Stop]
    -> Stop -> parent -> Stop. Explicit assertions at every boundary."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace -> bake legal
    pre_food = state.players[0].resources.food

    state = step(state, PlaceWorker(space="grain_utilization"))
    state = step(state, ChooseSubAction(name="bake_bread"))

    # before-phase: the commit is offered (and would-be before_bake_bread triggers).
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread) and top.phase == "before"
    assert CommitBake(grain=1) in legal_actions(state)

    # CommitBake pivots to the after-phase (no pop); the bake has applied.
    state = step(state, CommitBake(grain=1))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread) and top.phase == "after"
    assert state.players[0].resources.food == pre_food + 2
    assert legal_actions(state) == [Stop()]            # after-phase: only Stop

    # Stop pops PendingBakeBread -> back at the parent (still on the stack).
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingGrainUtilization)
    assert legal_actions(state) == [Stop()]

    # Stop pops the parent -> turn ends.
    state = step(state, Stop())
    assert state.pending_stack == ()


# ---------------------------------------------------------------------------
# PendingBuildMajor / free-oven: two-deep nesting (the free bake is itself a
# now-after-phase PendingBakeBread)
# ---------------------------------------------------------------------------

def test_build_major_clay_oven_free_bake_nested_lifecycle():
    """Clay Oven purchase pivots PendingBuildMajor to its after-phase BEFORE
    pushing the oven wrapper, so the wrapper's free bake (itself a flip+Stop
    PendingBakeBread) pops back to an already-"after" host."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, clay=3, stone=1, grain=1)
    pre_food = state.players[0].resources.food

    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="build_major"))
    state = step(state, CommitBuildMajor(major_idx=5, return_fireplace_idx=None))

    # PendingBuildMajor already flipped to after; the oven wrapper is on top.
    assert isinstance(state.pending_stack[-1], PendingClayOven)
    bm = state.pending_stack[-2]
    assert isinstance(bm, PendingBuildMajor) and bm.phase == "after"
    assert legal_actions(state) != [Stop()]            # the free bake is still offered

    # Take the free bake: it runs its own before -> commit -> after lifecycle.
    state = step(state, ChooseSubAction(name="bake_bread"))
    state = step(state, CommitBake(grain=1))
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    assert state.pending_stack[-1].phase == "after"
    assert state.players[0].resources.food == pre_food + 5   # Clay Oven: 5 food/grain

    # Unwind: bake after-phase -> oven wrapper -> build-major after -> parent.
    state = step(state, Stop())                        # pop PendingBakeBread
    assert isinstance(state.pending_stack[-1], PendingClayOven)
    state = step(state, Stop())                        # pop PendingClayOven
    assert isinstance(state.pending_stack[-1], PendingBuildMajor)
    state = step(state, Stop())                        # pop PendingBuildMajor
    assert isinstance(state.pending_stack[-1], PendingMajorMinorImprovement)
    state = step(state, Stop())                        # pop the parent
    assert state.pending_stack == ()
    assert state.board.major_improvement_owners[5] == 0


# ---------------------------------------------------------------------------
# Nested host: a minor played at the Major/Minor Improvement space — the
# PendingPlayMinor sub-action host runs its before/after/Stop lifecycle nested
# under the parent space host, which then runs its own Stop.
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _improvement_state(*, minors, res):
    cs, _env = setup_env(5, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "major_improvement"), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=minors, resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def test_minor_at_improvement_space_nested_host_lifecycle():
    """Play market_stall (cost 1 grain, +1 veg, then passes) via Major/Minor
    Improvement. PendingPlayMinor flips to after and Stops back to the parent,
    which then Stops — two nested host lifecycles."""
    cs, cp = _improvement_state(minors=frozenset({"market_stall"}), res=Resources(grain=1))
    pre_veg = cs.players[cp].resources.veg

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    # before-phase of the nested PendingPlayMinor: the commit is offered.
    assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
    assert cs.pending_stack[-1].phase == "before"
    assert CommitPlayMinor(card_id="market_stall") in legal_actions(cs)

    cs = step(cs, CommitPlayMinor(card_id="market_stall"))
    # Nested host pivoted to after-phase (no pop); the minor's effect applied.
    assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
    assert cs.pending_stack[-1].phase == "after"
    assert cs.players[cp].resources.veg == pre_veg + 1
    assert legal_actions(cs) == [Stop()]

    # Stop pops PendingPlayMinor -> back at the parent space host.
    cs = step(cs, Stop())
    assert isinstance(cs.pending_stack[-1], PendingMajorMinorImprovement)
    assert cs.pending_stack[-1].minor_chosen is True
    assert legal_actions(cs) == [Stop()]

    # Stop pops the parent -> turn ends.
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# After-automatic effect fires at the commit-flip (the after-window opens),
# not at the trailing Stop. Exercised with a test-scoped registration (no card
# module added — mechanism only).
# ---------------------------------------------------------------------------

def test_after_auto_fires_at_the_commit_flip():
    """A test-registered after_sow automatic effect fires when PendingSow
    pivots to its after-phase (at CommitSow), before the trailing Stop."""
    from agricola.cards.triggers import AUTO_EFFECTS, register_auto

    card_id = "_test_after_sow_wood"

    def _elig(state, idx):
        return True

    def _apply(state, idx):
        p = state.players[idx]
        return fast_replace(
            state,
            players=tuple(
                fast_replace(p, resources=p.resources + Resources(wood=5))
                if i == idx else state.players[i]
                for i in range(2)
            ),
        )

    register_auto("after_sow", card_id, _elig, _apply)
    try:
        state = setup(seed=0)
        state = with_current_player(state, 0)
        state = with_resources(state, 0, grain=1)
        # The owner must hold the card for the auto to fire (apply_auto_effects
        # ownership-checks via _owns over occupations/minors).
        p = fast_replace(state.players[0],
                         occupations=state.players[0].occupations | {card_id})
        # Give the player one empty field to sow into.
        from agricola.constants import CellType
        from agricola.state import Cell
        grid = [list(row) for row in p.farmyard.grid]
        grid[0][2] = Cell(cell_type=CellType.FIELD)
        p = fast_replace(p, farmyard=fast_replace(p.farmyard,
                                                  grid=tuple(tuple(r) for r in grid)))
        state = fast_replace(state, players=(p, state.players[1]))
        pre_wood = state.players[0].resources.wood

        state = step(state, PlaceWorker(space="grain_utilization"))
        state = step(state, ChooseSubAction(name="sow"))
        state = step(state, CommitSow(grain=1, veg=0))

        # The auto fired AT the flip — wood is already +5 while PendingSow is
        # still on the stack in its after-phase (before any Stop).
        assert isinstance(state.pending_stack[-1], PendingSow)
        assert state.pending_stack[-1].phase == "after"
        assert state.players[0].resources.wood == pre_wood + 5
    finally:
        AUTO_EFFECTS["after_sow"] = [
            e for e in AUTO_EFFECTS.get("after_sow", []) if e.card_id != card_id
        ]
