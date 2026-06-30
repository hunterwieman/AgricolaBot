"""Tests for Cowherd (C147) — an occupation that grants 1 ADDITIONAL cattle each
time you use the Cattle Market accumulation space.

The +1 is staged on the PendingCattleMarket's `gained` field (an int, bumped via
replace_top in the `before_action_space` before-phase), NOT added directly to the
player — so the extra cattle flows through the SAME accommodation/overflow frontier
as the market's own cattle. Owner-gated ("you"); fires even when the space is empty
(gained 0 -> 1).
"""
import agricola.cards.cowherd  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingCattleMarket
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import (
    with_animals,
    with_current_player,
    with_majors,
    with_space,
)


def _give_capacity(state, player_idx, cells):
    """Give the player a single pasture over `cells` (capacity 2 per cell), so the
    accommodation frontier can KEEP the gained cattle instead of overflowing them."""
    fy = state.players[player_idx].farmyard
    pasture = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    fy = fast_replace(fy, pastures=(pasture,))
    p = fast_replace(state.players[player_idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == player_idx else state.players[i] for i in range(2)))


def _give_cowherd(state, player_idx):
    p = state.players[player_idx]
    p = fast_replace(p, occupations=p.occupations | {"cowherd"})
    return fast_replace(state, players=tuple(
        p if i == player_idx else state.players[i] for i in range(2)))


def _cattle_market_state(*, accumulated, owner=0, owner_cattle=0):
    """`owner` is active; Cattle Market is revealed + stocked with `accumulated`
    cattle; `owner` owns Cowherd and optionally some pre-existing cattle."""
    state = setup(seed=0)
    state = with_current_player(state, owner)
    state = with_space(state, "cattle_market", revealed=True,
                       accumulated_amount=accumulated)
    if owner_cattle:
        state = with_animals(state, owner, cattle=owner_cattle)
    state = _give_cowherd(state, owner)
    return state


def _commit_keep_all(state):
    """Drive CommitAccommodate keeping the maximum cattle, then any trailing Stop."""
    keep = max(
        (a for a in legal_actions(state) if isinstance(a, CommitAccommodate)),
        key=lambda a: a.cattle,
    )
    state = step(state, keep)
    if state.pending_stack and isinstance(state.pending_stack[-1], PendingCattleMarket):
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "cowherd" in OCCUPATIONS
    spec = OCCUPATIONS["cowherd"]
    # No on-play effect: applying it is identity.
    s = setup(seed=0)
    assert spec.on_play(s, 0) is s


# ---------------------------------------------------------------------------
# Bumps the staged `gained` in the before-phase (before accommodation), NOT the
# player directly.
# ---------------------------------------------------------------------------

def test_bumps_gained_in_before_phase():
    state = _cattle_market_state(accumulated=1)
    c0 = state.players[0].animals.cattle  # 0

    state = step(state, PlaceWorker(space="cattle_market"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCattleMarket)
    # Market stocked 1 cattle; Cowherd bumped it to 2 — staged, not on the player yet.
    assert top.gained == 2
    assert state.players[0].animals.cattle == c0  # not yet accommodated


def test_extra_cattle_flows_through_accommodation():
    """With pasture capacity to keep them, the full flow nets the player +2 cattle
    (1 from the space + 1 from Cowherd) — the extra cattle went through the SAME
    accommodation frontier as the market's own."""
    state = _cattle_market_state(accumulated=1)
    state = _give_capacity(state, 0, [(0, 0), (0, 1)])   # capacity 4
    state = step(state, PlaceWorker(space="cattle_market"))
    state = _commit_keep_all(state)
    assert state.players[0].animals.cattle == 2


def test_extra_cattle_overflows_to_food_without_capacity():
    """A fresh farmyard caps kept cattle at 1 (the house pet-cell). The gained=2 from
    space+Cowherd still entered the SAME accommodation frontier — so the overflow
    cattle converts to food (Fireplace cattle rate 3), which is exactly the +1 cattle
    Cowherd staged. Without Cowherd the market alone (1 cattle) fits with no overflow."""
    # Baseline: market alone (1 cattle), no Cowherd -> kept 1, no overflow.
    base = setup(seed=0)
    base = with_current_player(base, 0)
    base = with_majors(base, owner_by_idx={0: 0})       # Fireplace -> cattle rate 3
    base = with_space(base, "cattle_market", revealed=True, accumulated_amount=1)
    base_food = base.players[0].resources.food
    base = step(base, PlaceWorker(space="cattle_market"))
    base = _commit_keep_all(base)
    assert base.players[0].animals.cattle == 1
    assert base.players[0].resources.food == base_food  # nothing overflowed

    # With Cowherd: gained=2, capacity 1 -> keep 1, overflow the 1 Cowherd cattle to
    # food at rate 3.
    state = _cattle_market_state(accumulated=1)
    state = with_majors(state, owner_by_idx={0: 0})     # Fireplace -> cattle rate 3
    start_food = state.players[0].resources.food
    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.pending_stack[-1].gained == 2
    state = _commit_keep_all(state)
    assert state.players[0].animals.cattle == 1
    assert state.players[0].resources.food == start_food + 3   # the +1 cattle -> 3 food


def test_fires_even_when_space_empty():
    """Cattle Market with 0 cattle still yields 1 (0 -> 1 via Cowherd)."""
    state = _cattle_market_state(accumulated=0)
    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.pending_stack[-1].gained == 1
    state = _commit_keep_all(state)
    assert state.players[0].animals.cattle == 1


def test_stacks_on_existing_cattle():
    """Pre-existing cattle plus the market's + Cowherd's all coexist (capacity
    permitting): 1 pre-existing + 2 stocked + 1 Cowherd = 4, all kept in a
    capacity-4 pasture."""
    state = _cattle_market_state(accumulated=2, owner_cattle=1)
    state = _give_capacity(state, 0, [(0, 0), (0, 1)])   # capacity 4
    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.pending_stack[-1].gained == 3  # 2 stocked + 1 Cowherd
    state = _commit_keep_all(state)
    assert state.players[0].animals.cattle == 4   # 1 existing + 3 gained


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_no_fire_on_non_cattle_market_space():
    """A different animal market (sheep) does not trigger Cowherd."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, "sheep_market", revealed=True, accumulated_amount=2)
    state = _give_cowherd(state, 0)
    state = step(state, PlaceWorker(space="sheep_market"))
    # Only the market's own 2 sheep are staged; gained untouched by Cowherd.
    assert state.pending_stack[-1].gained == 2
    assert state.players[0].animals.sheep == 0  # still staged, not yet accommodated


def test_no_fire_on_non_market_space():
    """A non-market space (forest) never triggers Cowherd."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, "forest", revealed=True, accumulated_amount=3)
    state = _give_cowherd(state, 0)
    w0 = state.players[0].resources.wood
    state = step(state, PlaceWorker(space="forest"))
    # Forest is atomic + unhooked by Cowherd; the wood resolves normally, no error.
    assert state.players[0].resources.wood == w0 + 3


# ---------------------------------------------------------------------------
# Owner-gating: the effect is "you", not "any player".
# ---------------------------------------------------------------------------

def test_does_not_fire_for_non_owner():
    """P1 owns Cowherd; P0 (active, no Cowherd) uses Cattle Market. The staged
    `gained` must NOT be bumped — the effect is owner-gated."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, "cattle_market", revealed=True, accumulated_amount=1)
    state = _give_cowherd(state, 1)

    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.pending_stack[-1].gained == 1  # only the market's own cattle


def test_fires_for_owner_regardless_of_seat():
    """When P1 (the active player) both acts and owns Cowherd, it fires for P1."""
    state = _cattle_market_state(accumulated=1, owner=1)
    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.pending_stack[-1].gained == 2
