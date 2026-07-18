"""Tests for Recycled Brick (minor improvement, D77; Dulcinaria Expansion).

Card text: "Each time any player (including you) renovates to stone, you get 1 clay
for each newly renovated room."
Cost: 1 Food. Prerequisite: 3 Occupations. 0 VPs.

An `any_player=True` AUTOMATIC effect on the `after_renovate` event: it fires for its
OWNER whenever EITHER player renovates to stone (owner routing lives in
apply_auto_effects). "renovates to stone" is an OUTCOME read — the after phase is
correct because a renovate's target is only knowable post-application (the Roughcaster
precedent); at `after_renovate` the RENOVATOR's `house_material` reads STONE exactly
when the renovation targeted stone (clay->stone, or Conservator's wood->stone — its
target IS stone, so it counts). The RENOVATOR is the top frame's (`PendingRenovate`)
`player_idx`; the BENEFICIARY is the auto's `owner_idx`. All rooms renovate at once, so
"newly renovated room" = every room of the renovator's house → 1 clay per room granted
to the owner.

Each test drives the REAL House Redevelopment renovate flow (the roughcaster hook
pattern), so the firing-point wiring is exercised end-to-end. The load-bearing cases
are the OPPONENT renovate (any_player routing) and the Conservator wood->stone renovate
(target IS stone → counts).
"""
from __future__ import annotations

import agricola.cards.recycled_brick  # noqa: F401  (registers the card)
import agricola.cards.conservator     # noqa: F401  (wood->stone renovate target)

from agricola.actions import (
    ChooseSubAction,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from agricola.legality import legal_actions
from tests.factories import with_grid, with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "recycled_brick"

_POOL = CardPool(
    occupations=("conservator",) + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _card_state(cp=0, seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=cp)
    # Drop both hands so nothing but the test's grants is in play.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _add_room(state, idx, r, c):
    """Add a third ROOM cell so the renovator's house has 3 rooms."""
    return with_grid(state, idx, {(r, c): Cell(cell_type=CellType.ROOM)})


def _renovate_to(target):
    """A `run_actions` thunk selecting the unique legal `CommitRenovate` whose
    `to_material` is `target` (needed when Conservator makes two targets legal)."""
    def _pick(state):
        opts = [a for a in legal_actions(state)
                if isinstance(a, CommitRenovate) and a.to_material == target]
        assert len(opts) == 1, f"expected one CommitRenovate to {target}, got {opts!r}"
        return opts[0]
    return _pick


def _drive_renovate(state, commit):
    """Drive the real House Redevelopment renovate flow to a turn-complete state.
    `commit` is the CommitRenovate (or a run_actions thunk producing one). The
    renovating player is `state.current_player`."""
    return run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        commit,      # applies the renovate
        Stop(),      # pop PendingRenovate after-phase (after_renovate fired here)
        Proceed(),   # flip the host (house_redevelopment) to its after-phase
        Stop(),      # pop the host -> turn complete
    ])


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))   # cost: 1 food
    assert spec.min_occupations == 3                        # prerequisite: 3 occupations
    assert spec.vps == 0
    entries = AUTO_EFFECTS.get("after_renovate", ())
    assert any(e.card_id == CARD_ID and e.any_player for e in entries)
    # Mandatory choice-free auto → not a declinable trigger.
    from agricola.cards.triggers import TRIGGERS
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


# --- Owner renovates to stone -----------------------------------------------

def test_owner_clay_to_stone_gains_clay_per_room():
    # Clay house, default 2 rooms → renovate to stone costs 2 stone + 1 reed. Owner
    # gets 1 clay per room = 2 clay (fires exactly once).
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, stone=2, reed=1)   # renovate cost; clay marker 0
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0)
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.clay == 2       # exactly 1 per room, once


def test_scales_with_room_count():
    # 3 rooms → renovate to stone costs 3 stone + 1 reed → owner gets 3 clay.
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = _add_room(cs, 0, 0, 0)                    # third room at (0,0)
    cs = with_resources(cs, 0, stone=3, reed=1)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0)
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.clay == 3       # 1 per room, 3 rooms


def test_conservator_wood_to_stone_counts():
    # Conservator makes wood->stone legal; the TARGET is stone → the payout applies.
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, stone=2, reed=1)   # 2-room wood->stone: 2 stone + 1 reed
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0)
    cs = _own_occ(cs, 0, "conservator")
    cs = _drive_renovate(cs, _renovate_to(HouseMaterial.STONE))
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.clay == 2       # target is stone → counts


# --- Opponent renovates (the any_player routing) -----------------------------

def test_opponent_renovate_to_stone_owner_gains():
    """THE load-bearing any_player case: player 1 renovates clay->stone, and the
    OWNER (player 0) — not the renovator — gets the clay, scaled by the RENOVATOR's
    room count."""
    cs = _card_state(cp=1)                          # player 1 renovates
    cs = with_house(cs, 1, HouseMaterial.CLAY)
    cs = with_resources(cs, 1, stone=2, reed=1)     # renovator pays; its clay stays 0
    cs = with_resources(cs, 0, clay=5)              # owner's clay marker
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0)                           # OWNER is player 0
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[1].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.clay == 5 + 2     # owner gained (renovator's 2 rooms)
    assert cs.players[1].resources.clay == 0         # renovator (non-owner) did not


# --- Non-firing cases --------------------------------------------------------

def test_wood_to_clay_pays_nothing():
    # A wood->clay renovate ends in a CLAY house → not "to stone" → no clay.
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, clay=2, reed=1)      # wood->clay: 2 clay + 1 reed
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0)
    clay0 = cs.players[0].resources.clay
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    # Only the leftover clay after paying the 2-clay cost remains — no bonus granted.
    assert cs.players[0].resources.clay == clay0 - 2


def test_unowned_gains_nothing():
    # A player who has NOT played Recycled Brick gets no clay on a clay->stone renovate.
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, stone=2, reed=1)     # NOT owning the card
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.clay == 0         # not owned → nothing
