"""Tests for Mining Hammer (minor improvement, B16):

    "When you play this card, you immediately get 1 food. Each time you renovate,
     you can also build a stable without paying wood."

Two shapes: an on-play one-shot +1 food, and an OPTIONAL `before_renovate` trigger
that grants a FREE stable (pushes the PendingBuildStables primitive at zero cost,
capped at 1 build).

The grant is a FLAT one — a free stable whose legality depends only on an empty
farmyard cell and a stable in supply, neither of which the renovate produces or
changes. The text is a bare "each time you renovate" with no reference to the
renovate's target or outcome, so per the ruling in CARD_AUTHORING_GUIDE.md
("Each time you [do X]" fires BEFORE X unless the text says "after") it hooks the
PendingRenovate BEFORE-phase — offered alongside the CommitRenovate options, before
the renovate commits. No stranding is possible: the free stable consumes a farmyard
cell + a stable from supply, while the renovate consumes only building resources
(clay/reed or stone/reed) — disjoint sets. Each test drives the real renovate flow
through House Redevelopment so the firing point is exercised end-to-end.
"""
import agricola.cards.mining_hammer  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    CommitRenovate,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.constants import CellType, HouseMaterial
from agricola.helpers import stables_in_supply
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("mining_hammer",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    from tests.factories import with_current_player
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


def _at_before_phase(cs):
    """Drive to the PendingRenovate BEFORE-phase (after ChooseSubAction, before commit)."""
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    return cs


# ---------------------------------------------------------------------------
# Registration + on-play +1 food
# ---------------------------------------------------------------------------

def test_mining_hammer_registered():
    assert "mining_hammer" in MINORS
    assert MINORS["mining_hammer"].cost == Cost(resources=Resources(wood=1))


def test_mining_hammer_on_play_food():
    # Play the minor via House Redevelopment's minor-play slot; +1 food on play.
    cs = _card_state()
    cs = with_resources(cs, 0, wood=1, food=0)  # afford the 1-wood cost
    cs = _own_minor(cs, 0, "mining_hammer")  # give ownership so no double-count
    p = cs.players[0]
    # Call the on-play effect directly (the registered hook) to isolate the +1 food.
    from agricola.cards.mining_hammer import _on_play
    food0 = p.resources.food
    cs2 = _on_play(cs, 0)
    assert cs2.players[0].resources.food == food0 + 1


# ---------------------------------------------------------------------------
# Timing: the free-stable trigger is offered in the BEFORE-phase
# ---------------------------------------------------------------------------

def test_mining_hammer_offered_in_before_phase():
    # Wood->clay renovate costs 2 clay + 1 reed.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    cs = _at_before_phase(cs)
    # We are at the PendingRenovate BEFORE-phase: the frame has not committed yet.
    assert type(cs.pending_stack[-1]).__name__ == "PendingRenovate"
    assert cs.pending_stack[-1].phase == "before"
    legal = legal_actions(cs)
    # The optional free-stable trigger is surfaced BEFORE the renovate commits,
    # alongside the CommitRenovate option(s) — not after them in an after-phase.
    assert FireTrigger(card_id="mining_hammer") in legal
    assert any(isinstance(a, CommitRenovate) for a in legal)


# ---------------------------------------------------------------------------
# Firing: a free stable is pushed as a primitive; renovate still commits after
# ---------------------------------------------------------------------------

def test_mining_hammer_fires_free_stable():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1, wood=0)
    cs = _own_minor(cs, 0, "mining_hammer")
    supply0 = stables_in_supply(cs.players[0])
    wood0 = cs.players[0].resources.wood
    cs = _at_before_phase(cs)
    assert FireTrigger(card_id="mining_hammer") in legal_actions(cs)
    # Fire the grant -> pushes the PendingBuildStables primitive (free cost).
    cs = step(cs, FireTrigger(card_id="mining_hammer"))
    assert type(cs.pending_stack[-1]).__name__ == "PendingBuildStables"
    # Build the free stable at some legal cell.
    stable_commit = next(
        a for a in legal_actions(cs) if isinstance(a, CommitBuildStable)
    )
    cs = step(cs, stable_commit)
    # No wood was paid for the stable (the whole point of the card).
    assert cs.players[0].resources.wood == wood0
    # One stable left the supply (i.e. one was built).
    assert stables_in_supply(cs.players[0]) == supply0 - 1
    # The granted stable build is a multi-shot host (capped at 1): Proceed flips it to
    # its after-phase, Stop pops it back to the renovate before-phase.
    cs = run_actions(cs, [Proceed(), Stop()])
    # Back at the PendingRenovate before-phase; the mandatory renovate is still forced.
    assert type(cs.pending_stack[-1]).__name__ == "PendingRenovate"
    assert any(isinstance(a, CommitRenovate) for a in legal_actions(cs))
    # Commit the renovate itself, then finish the turn.
    cs = step(cs, sole_renovate(cs))   # flips PendingRenovate to its after-phase
    cs = run_actions(cs, [Stop(), Proceed(), Stop()])
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY


# ---------------------------------------------------------------------------
# Optionality: declinable by just committing the renovate without firing
# ---------------------------------------------------------------------------

def test_mining_hammer_decline():
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    supply0 = stables_in_supply(cs.players[0])
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,   # commit the renovate without firing (declined)
        Stop(),      # pop PendingRenovate after-phase
        Proceed(),   # flip the host to its after-phase
        Stop(),      # pop the host
    ])
    assert cs.pending_stack == ()
    assert stables_in_supply(cs.players[0]) == supply0   # no free stable built
    assert cs.players[0].house_material == HouseMaterial.CLAY


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_mining_hammer_not_offered_when_unowned():
    # A player who has not played Mining Hammer never sees the trigger.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _at_before_phase(cs)
    assert FireTrigger(card_id="mining_hammer") not in legal_actions(cs)


def test_mining_hammer_not_offered_without_stable_slot():
    # Fill every non-house farmyard cell so no legal stable cell remains ->
    # the grant would dead-end, so eligibility gates it off. The mandatory
    # renovate is still offered (it needs no farmyard cell).
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    p = cs.players[0]
    grid = p.farmyard.grid
    new_rows = []
    for r in range(len(grid)):
        new_row = []
        for c in range(len(grid[r])):
            cell = grid[r][c]
            if cell.cell_type == CellType.EMPTY:
                cell = fast_replace(cell, cell_type=CellType.FIELD)
            new_row.append(cell)
        new_rows.append(tuple(new_row))
    fy = fast_replace(p.farmyard, grid=tuple(new_rows))
    p = fast_replace(p, farmyard=fy)
    cs = fast_replace(cs, players=tuple(
        p if i == 0 else cs.players[i] for i in range(2)))
    cs = _at_before_phase(cs)
    legal = legal_actions(cs)
    assert FireTrigger(card_id="mining_hammer") not in legal
    assert any(isinstance(a, CommitRenovate) for a in legal)


def test_mining_hammer_once_per_renovate():
    # After firing once (building the free stable), the trigger is stamped in
    # triggers_resolved -> not offered again within the same renovate action.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, "mining_hammer")
    cs = _at_before_phase(cs)
    cs = step(cs, FireTrigger(card_id="mining_hammer"))
    stable_commit = next(
        a for a in legal_actions(cs) if isinstance(a, CommitBuildStable)
    )
    cs = step(cs, stable_commit)
    cs = run_actions(cs, [Proceed(), Stop()])  # pop the multi-shot stable host
    # Back at the renovate before-phase; the grant is spent for this renovate.
    assert type(cs.pending_stack[-1]).__name__ == "PendingRenovate"
    assert FireTrigger(card_id="mining_hammer") not in legal_actions(cs)
