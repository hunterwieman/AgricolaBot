"""Tests for Shed Builder (occupation, E-deck #114; Ephipparius Expansion).

Card text: "When you build your 1st and 2nd stable, you get 1 grain. When you
build your 3rd and 4th stable, you get 1 vegetable. (This does not apply to
stables you have already built.)"

The card is an `after_build_stables` automatic payout keyed to each built
stable's LIFETIME ordinal (1st/2nd -> 1 grain each; 3rd/4th -> 1 vegetable
each), computed once per Build Stables ACTION at the after boundary. Tests
drive the REAL Farm Expansion build-stables flow (CARD_AUTHORING_GUIDE §5) and
pin:

  - single first stable -> +1 grain;
  - stables #1-#3 in ONE action -> +2 grain +1 veg, paid in one payout at the
    Proceed flip (nothing mid-action);
  - all four in one action -> +2 grain +2 veg;
  - the parenthetical: a player who already had 2 stables BEFORE playing the
    card builds one -> +1 veg (their lifetime 3rd), never grain;
  - opponent builds pay the owner nothing; a hand-only card is inert;
  - a card-GRANTED build (a free `PendingBuildStables` pushed by a card)
    flows through the same after event and pays too.
"""
import agricola.cards.shed_builder  # noqa: F401  -- registers the card

from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.shed_builder import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.legality import legal_actions
from agricola.pending import PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_pending_stack,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_occ(state, idx, card_id=CARD_ID):
    """Give player `idx` the occupation (played via Lessons in real play)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _expansion_setup(*, idx=0, own=True, **resources):
    cs = _card_state()
    cs = with_current_player(cs, idx)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "farm_expansion", revealed=True)
    if own:
        cs = _own_occ(cs, idx)
    return cs


def _next_stable(state):
    return next(a for a in legal_actions(state)
                if isinstance(a, CommitBuildStable))


def _grain(state, idx=0):
    return state.players[idx].resources.grain


def _veg(state, idx=0):
    return state.players[idx].resources.veg


def _num_stables(state, idx=0):
    grid = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if grid[r][c].cell_type == CellType.STABLE)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert callable(OCCUPATIONS[CARD_ID].on_play)
    # Wired as an automatic effect on the build-stables after boundary.
    assert CARD_ID in {e.card_id
                       for e in AUTO_EFFECTS.get("after_build_stables", ())}


def test_on_play_is_noop():
    state = _expansion_setup(wood=2)
    before = state.players[0]
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0] == before   # no resources / state change


# ---------------------------------------------------------------------------
# The payout — real Farm Expansion build-stables flow
# ---------------------------------------------------------------------------

def test_first_stable_pays_one_grain():
    cs = _expansion_setup(wood=2)
    assert _num_stables(cs) == 0
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(),   # flip PendingBuildStables -> after -> the payout fires
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert _num_stables(cs) == 1
    assert _grain(cs) == 1
    assert _veg(cs) == 0


def test_stables_one_through_three_in_one_action():
    """Building stables #1-#3 in ONE action pays 2 grain + 1 veg, in one
    payout at the Proceed flip — nothing is paid between piece-commits."""
    cs = _expansion_setup(wood=6)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        _next_stable,
        _next_stable,
    ])
    # All three committed; the action hasn't flipped yet -> no payout yet.
    assert _num_stables(cs) == 3
    assert _grain(cs) == 0 and _veg(cs) == 0
    cs = run_actions(cs, [Proceed(), Stop(), Proceed(), Stop()])
    assert _grain(cs) == 2   # ordinals 1 and 2
    assert _veg(cs) == 1     # ordinal 3


def test_all_four_in_one_action():
    cs = _expansion_setup(wood=8)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, _next_stable, _next_stable, _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _num_stables(cs) == 4
    assert _grain(cs) == 2   # ordinals 1, 2
    assert _veg(cs) == 2     # ordinals 3, 4


def test_fourth_stable_alone_pays_one_veg():
    """Three stables pre-built (as if from earlier actions): the next build is
    the lifetime 4th -> +1 veg, no grain."""
    cs = _expansion_setup(wood=2)
    cs = with_grid(cs, 0, {(2, 2): Cell(cell_type=CellType.STABLE),
                           (2, 3): Cell(cell_type=CellType.STABLE),
                           (2, 4): Cell(cell_type=CellType.STABLE)})
    cs = _own_occ(cs, 0)   # idempotent; ensure ownership survives the edits
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _num_stables(cs) == 4
    assert _grain(cs) == 0
    assert _veg(cs) == 1


# ---------------------------------------------------------------------------
# The parenthetical — pre-card stables consumed their ordinals
# ---------------------------------------------------------------------------

def test_pre_existing_stables_consume_ordinals():
    """A player who already built 2 stables BEFORE playing the card builds
    one more: it is their lifetime 3rd -> +1 veg, NEVER grain (the 1st/2nd
    ordinals were consumed by the pre-card stables)."""
    cs = _expansion_setup(wood=2)
    cs = with_grid(cs, 0, {(2, 3): Cell(cell_type=CellType.STABLE),
                           (2, 4): Cell(cell_type=CellType.STABLE)})
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _num_stables(cs) == 3
    assert _grain(cs) == 0
    assert _veg(cs) == 1


# ---------------------------------------------------------------------------
# Ownership boundaries
# ---------------------------------------------------------------------------

def test_opponent_builds_pay_nothing():
    """Player 0 owns the card; player 1 builds a stable -> nobody is paid."""
    cs = _card_state()
    cs = _own_occ(cs, 0)
    cs = with_current_player(cs, 1)
    cs = with_resources(cs, 1, wood=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _num_stables(cs, 1) == 1
    assert _grain(cs, 0) == 0 and _veg(cs, 0) == 0
    assert _grain(cs, 1) == 0 and _veg(cs, 1) == 0


def test_hand_only_is_inert():
    """The card sitting in hand (not played) pays nothing."""
    cs = _expansion_setup(wood=2, own=False)
    p0 = cs.players[0]
    p0 = fast_replace(p0, hand_occupations=p0.hand_occupations | {CARD_ID})
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _num_stables(cs) == 1
    assert _grain(cs) == 0 and _veg(cs) == 0


# ---------------------------------------------------------------------------
# Source-agnostic — a card-granted stable build pays too
# ---------------------------------------------------------------------------

def test_card_granted_build_pays():
    """A free PendingBuildStables pushed by a card effect (e.g. Stablehand's
    free stable) flips through the same after_build_stables event -> pays."""
    cs = _card_state()
    cs = _own_occ(cs, 0)
    cs = with_resources(cs, 0)   # no resources at all: the grant is free
    cs = with_pending_stack(cs, [PendingBuildStables(
        player_idx=0, initiated_by_id="card:test",
        cost=Resources(), max_builds=1,
    )])
    cs = run_actions(cs, [_next_stable])
    # Multi-shot host: no payout until the explicit Proceed flips it to after.
    assert _num_stables(cs) == 1
    assert _grain(cs) == 0
    cs = run_actions(cs, [Proceed()])   # flip -> after_build_stables fires
    assert _grain(cs) == 1
    assert _veg(cs) == 0
