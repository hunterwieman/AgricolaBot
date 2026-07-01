"""Tests for Wooden Whey Bucket (minor improvement, D16; Dulcinaria Expansion).

Card text: "Each time before you use the "Sheep Market"/"Cattle Market" accumulation
space, you can build exactly 1 stable for 1 wood/at no cost." (0 VP, cost 1 wood + 1 food.)

The paired slashes are a per-space correspondence: Sheep Market -> stable for 1 WOOD,
Cattle Market -> stable at NO COST. It is an OPTIONAL `before_action_space` FireTrigger on
the non-atomic Sheep/Cattle Market host whose apply_fn pushes a 1-stable PendingBuildStables
at that space's cost. Declinable (a stable consumes a cell), once-per-use, owner-gated, and
gated on the per-space cost being affordable + a buildable cell.
"""
import agricola.cards.wooden_whey_bucket  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitAccommodate,
    CommitBuildStable,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import _can_build_stable, legal_actions
from agricola.pending import (
    PendingBuildStables,
    PendingCattleMarket,
    PendingSheepMarket,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import get_space, with_space

from tests.factories import with_current_player, with_resources, with_space as _with_space_factory

CARD_ID = "wooden_whey_bucket"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _market_state(space_id, *, accumulated=1, owner=0, wood=5):
    """`owner` is active; `space_id` market is revealed + stocked; `owner` owns the card
    and has `wood` wood (enough to pay the sheep-market stable's 1-wood cost)."""
    state = setup(seed=0)
    state = with_current_player(state, owner)
    state = _with_space_factory(state, space_id, revealed=True,
                                accumulated_amount=accumulated)
    state = with_resources(state, owner, wood=wood)
    state = _own_minor(state, owner)
    return state


def _drive_accommodate(state):
    """Take the market's animals (keep maximum), then pop the market host frame."""
    keep = max(
        (a for a in legal_actions(state) if isinstance(a, CommitAccommodate)),
        key=lambda a: (getattr(a, "sheep", 0) + getattr(a, "cattle", 0)),
    )
    state = step(state, keep)
    top = state.pending_stack[-1]
    if isinstance(top, (PendingSheepMarket, PendingCattleMarket)):
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    assert CARD_ID in CARDS
    assert any(e.card_id == CARD_ID for e in TRIGGERS["before_action_space"])
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1, food=1)
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Per-space cost mapping: Sheep Market -> 1 wood, Cattle Market -> free
# ---------------------------------------------------------------------------

def test_sheep_market_grant_costs_one_wood():
    s = _market_state("sheep_market", wood=5)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la

    s = step(s, FireTrigger(card_id=CARD_ID))
    bs = s.pending_stack[-1]
    assert isinstance(bs, PendingBuildStables)
    assert bs.cost == Resources(wood=1) and bs.max_builds == 1
    assert bs.initiated_by_id == f"card:{CARD_ID}"

    wood_before = s.players[0].resources.wood
    s = step(s, CommitBuildStable(row=0, col=2))
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert s.players[0].resources.wood == wood_before - 1   # paid 1 wood


def test_cattle_market_grant_is_free():
    s = _market_state("cattle_market", wood=0)   # no wood — must still be offered
    s = step(s, PlaceWorker(space="cattle_market"))
    assert isinstance(s.pending_stack[-1], PendingCattleMarket)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    s = step(s, FireTrigger(card_id=CARD_ID))
    bs = s.pending_stack[-1]
    assert isinstance(bs, PendingBuildStables)
    assert bs.cost == Resources() and bs.max_builds == 1

    s = step(s, CommitBuildStable(row=0, col=2))
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert s.players[0].resources.wood == 0   # paid nothing


# ---------------------------------------------------------------------------
# Full flow: build the stable, then take the market animals afterwards
# ---------------------------------------------------------------------------

def test_full_flow_stable_then_animals():
    s = _market_state("cattle_market", accumulated=1, wood=0)
    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitBuildStable(row=0, col=2))
    s = step(s, Proceed())   # flip PendingBuildStables to after-phase
    s = step(s, Stop())      # pop the build host -> back to the market frame

    # The grant is spent (once per use): only the market's own accommodation remains.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _drive_accommodate(s)
    assert not s.pending_stack
    assert s.players[0].animals.cattle == 1
    # The stable persists on the board.
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE


# ---------------------------------------------------------------------------
# Once-per-use scoping: the grant fires at most once per market use
# ---------------------------------------------------------------------------

def test_once_per_use():
    s = _market_state("cattle_market", wood=0)
    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitBuildStable(row=0, col=2))
    s = step(s, Proceed())
    s = step(s, Stop())
    # After firing once, it is not offered again on this same use.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality: the grant can be declined
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _market_state("cattle_market", accumulated=1, wood=0)
    s = step(s, PlaceWorker(space="cattle_market"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Decline by going straight to the market's accommodation.
    s = _drive_accommodate(s)
    assert not s.pending_stack
    # No stable was built.
    assert all(c.cell_type != CellType.STABLE
               for row in s.players[0].farmyard.grid for c in row)
    assert s.players[0].animals.cattle == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_to_non_owner():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _with_space_factory(s, "cattle_market", revealed=True, accumulated_amount=1)
    # P1 owns the card; P0 (active) does not.
    s = _own_minor(s, 1)
    s = step(s, PlaceWorker(space="cattle_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_on_non_market_space():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _with_space_factory(s, "sheep_market", revealed=True, accumulated_amount=2)
    s = _own_minor(s, 0)
    # Use a DIFFERENT, non-market space (pig_market is also animal but not in SPACES).
    s = _with_space_factory(s, "pig_market", revealed=True, accumulated_amount=1)
    s = step(s, PlaceWorker(space="pig_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_when_sheep_grant_unaffordable():
    # Owner has 0 wood, so the Sheep-Market grant (1 wood) is unaffordable -> not offered.
    s = _market_state("sheep_market", wood=0)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert not _can_build_stable(s, s.players[0], Resources(wood=1))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_when_no_buildable_cell():
    # Fill every empty cell so no stable cell remains -> the grant is not offered even
    # at the free Cattle Market.
    s = _market_state("cattle_market", wood=5)
    g = s.players[0].farmyard.grid
    new_rows = tuple(
        tuple(
            fast_replace(g[r][c], cell_type=CellType.FIELD)
            if g[r][c].cell_type == CellType.EMPTY else g[r][c]
            for c in range(5)
        )
        for r in range(3)
    )
    fy = fast_replace(s.players[0].farmyard, grid=new_rows)
    p = fast_replace(s.players[0], farmyard=fy)
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    assert not _can_build_stable(s, s.players[0], Resources())

    s = step(s, PlaceWorker(space="cattle_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
