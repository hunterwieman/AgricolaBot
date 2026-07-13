"""Tests for Vegetable Slicer (minor improvement, A41; Artifex Expansion).

Card text: "Each time you upgrade a Fireplace to a Cooking Hearth, you immediately
get 2 wood and 1 vegetable (not retroactively)."

"Upgrade a Fireplace to a Cooking Hearth" = building a Cooking Hearth by RETURNING
a Fireplace (not paying clay). The engine fires a dedicated
`upgrade_to_cooking_hearth` event in the return-Fireplace branch of
`_execute_build_major`; this card is a `register_auto` on it (+2 wood + 1 veg).
Tests drive the REAL Major Improvement build flow and check the fire fires only on
the upgrade route, only for the owner, and never on a clay-paid Cooking Hearth.
"""
import json
from pathlib import Path

import agricola.cards.vegetable_slicer  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.resources import Cost, Resources
from tests.factories import with_current_player, with_majors, with_minors, with_resources, with_space
from tests.test_utils import build_major, run_actions
from agricola.setup import setup

CARD_ID = "vegetable_slicer"

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Vegetable Slicer")


def _setup(*, resources=None, owner_by_idx=None, own_card=True):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    if resources:
        state = with_resources(state, 0, **resources)
    if owner_by_idx:
        state = with_majors(state, owner_by_idx=owner_by_idx)
    if own_card:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_space(state, "major_improvement", revealed=True)
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "1 Wood"
    assert _ROW["text"] == (
        "Each time you upgrade a Fireplace to a Cooking Hearth, you immediately "
        "get 2 wood and 1 vegetable (not retroactively).")
    import agricola.cards.vegetable_slicer as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("upgrade_to_cooking_hearth", [])}


# ---------------------------------------------------------------------------
# The upgrade route fires; the clay route does not
# ---------------------------------------------------------------------------

def _build_cooking_hearth(state, *, return_fp=None):
    steps = [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(2, return_fp) if return_fp is not None else build_major(2),
        Stop(), Stop(), Stop(),
    ]
    return run_actions(state, steps)


def test_upgrade_via_return_fireplace_grants_wood_and_veg():
    state = _setup(owner_by_idx={0: 0})     # owns Fireplace idx 0
    before = state.players[0].resources
    out = _build_cooking_hearth(state, return_fp=0)
    assert out.board.major_improvement_owners[2] == 0    # Cooking Hearth built
    assert out.board.major_improvement_owners[0] is None  # Fireplace returned
    assert out.players[0].resources.wood == before.wood + 2
    assert out.players[0].resources.veg == before.veg + 1


def test_clay_paid_cooking_hearth_does_not_fire():
    """A Cooking Hearth built from CLAY is not an 'upgrade' — no reward."""
    state = _setup(resources={"clay": 4})
    before = state.players[0].resources
    out = _build_cooking_hearth(state)       # clay route
    assert out.board.major_improvement_owners[2] == 0
    assert out.players[0].resources.wood == before.wood   # no wood granted
    assert out.players[0].resources.veg == before.veg     # no veg granted


def test_unowned_upgrade_is_a_noop():
    """Without the card, the upgrade event grants nothing."""
    state = _setup(owner_by_idx={0: 0}, own_card=False)
    before = state.players[0].resources
    out = _build_cooking_hearth(state, return_fp=0)
    assert out.players[0].resources.wood == before.wood
    assert out.players[0].resources.veg == before.veg


def test_no_immediate_on_play_effect():
    """'not retroactively' — the card has no on_play grant, so playing it (even
    while already holding a Cooking Hearth) never grants goods on its own; the
    reward only ever comes from the upgrade EVENT."""
    state = _setup(owner_by_idx={2: 0})      # already owns a Cooking Hearth
    assert MINORS[CARD_ID].on_play(state, 0) is state   # default no-op on_play
