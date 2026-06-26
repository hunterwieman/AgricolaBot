"""Hook-firing coverage for every commit-terminated sub-action leaf frame
(SUBACTION_HOOK_REFACTOR.md).

The sub-action hook refactor gave every commit-terminated sub-action a
before/after host lifecycle: its Commit pivots the frame to ``phase="after"`` (no
auto-pop), firing the frame's ``after_<id>`` automatic effects (e.g. after_sow,
after_renovate) at the flip; the before-phase surfaces any ``before_<id>``
card triggers as ``FireTrigger`` options, and the after-phase surfaces any
``after_<id>`` triggers + ``Stop``.

This is the sub-action-leaf analogue of ``tests/test_space_host_hooks.py`` (which
covered the action-space *host* frames). The eight leaf frames are:

  Family-reachable: PendingSow / PendingBakeBread / PendingPlow /
                    PendingRenovate / PendingBuildMajor
  Card-only:        PendingFamilyGrowth / PendingPlayOccupation / PendingPlayMinor

For each, three "should-work" dimensions are asserted:
  (1) the after-automatic effect fires at the commit-flip,
  (2) a before-trigger is surfaced as a FireTrigger in the before-phase,
  (3) an after-trigger is surfaced as a FireTrigger in the after-phase.

A fourth dimension — a before-*automatic* effect — is DEFERRED by design
(SUBACTION_HOOK_REFACTOR §4d: before-autos are NOT fired at the sub-action push).
``test_before_auto_is_deferred_not_fired_at_push`` pins that current behavior so
the deferral is a known/tested limitation, not a silent gap.

The synthetic effects/triggers use the test-scoped ``register_auto`` / ``register``
+ try/finally cleanup pattern from ``tests/test_space_host_hooks.py`` and
``tests/test_subaction_hook_lifecycle.py``.
"""
import contextlib

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    CommitFamilyGrowth,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBakeBread,
    PendingBuildMajor,
    PendingFamilyGrowth,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingPlow,
    PendingRenovate,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space

from tests.factories import add_resources, with_current_player, with_majors, with_resources


# A generous card pool so card-only frames have hand cards to play. The o*/m*
# ids are unregistered (never offered); the registered ones are added explicitly.
_POOL = CardPool(
    occupations=("consultant",) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)

_HOOK_CARD = "_test_subaction_hook"


# ---------------------------------------------------------------------------
# Test-scoped registration helpers (auto-effect + trigger), with cleanup.
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _registered_auto(event: str):
    """Register a synthetic automatic effect on `event` that bumps the owner's
    stone by 1 each time it fires, then clean it up."""
    from agricola.cards.triggers import AUTO_EFFECTS, register_auto

    def _elig(state, idx):
        return True

    def _apply(state, idx):
        return fast_replace(
            state,
            players=tuple(
                fast_replace(q, resources=q.resources + Resources(stone=1))
                if i == idx else q
                for i, q in enumerate(state.players)
            ),
        )

    register_auto(event, _HOOK_CARD, _elig, _apply)
    try:
        yield
    finally:
        AUTO_EFFECTS[event] = [
            e for e in AUTO_EFFECTS.get(event, []) if e.card_id != _HOOK_CARD
        ]


@contextlib.contextmanager
def _registered_trigger(event: str):
    """Register a synthetic OPTIONAL trigger on `event` (a no-op apply; we only
    assert it is SURFACED as a FireTrigger), then clean it up."""
    from agricola.cards.triggers import CARDS, TRIGGERS, register

    def _elig(state, idx, triggers_resolved):
        return _HOOK_CARD not in triggers_resolved

    def _apply(state, idx):
        return state

    register(event, _HOOK_CARD, _elig, _apply)
    try:
        yield
    finally:
        TRIGGERS[event] = [e for e in TRIGGERS.get(event, []) if e.card_id != _HOOK_CARD]
        CARDS.pop(_HOOK_CARD, None)


def _grant_minor(state, idx):
    """Grant the synthetic hook card to player `idx` as a played minor so `_owns`
    (occupations | minor_improvements) sees it for both autos and triggers."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {_HOOK_CARD})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Per-frame builders + drivers. Each `_build_<frame>` returns (state, cp) with
# the player owning the hook card and positioned so the named sub-action is
# reachable in one ChooseSubAction. `_to_before` drives to the sub-action's
# before-phase (frame on top, phase=="before"); `_commit` is the commit that
# flips it to the after-phase.
# ---------------------------------------------------------------------------

def _reveal(cs, space_id):
    sp = fast_replace(get_space(cs.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(cs, board=with_space(cs.board, space_id, sp))


# --- PendingSow (Grain Utilization) ---------------------------------------

def _build_sow():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = _grant_minor(state, 0)
    # one empty field to sow into
    p = state.players[0]
    grid = [list(row) for row in p.farmyard.grid]
    grid[0][2] = Cell(cell_type=CellType.FIELD)
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid)))
    state = fast_replace(state, players=(p, state.players[1]))
    return state, 0


def _to_before_sow(state):
    state = step(state, PlaceWorker(space="grain_utilization"))
    return step(state, ChooseSubAction(name="sow"))


def _commit_sow(state):
    return step(state, CommitSow(grain=1, veg=0))


# --- PendingBakeBread (Grain Utilization) ---------------------------------

def _build_bake():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace -> bake legal
    state = _grant_minor(state, 0)
    return state, 0


def _to_before_bake(state):
    state = step(state, PlaceWorker(space="grain_utilization"))
    return step(state, ChooseSubAction(name="bake_bread"))


def _commit_bake(state):
    return step(state, CommitBake(grain=1))


# --- PendingPlow (Farmland, a Delegating space host) ----------------------

def _build_plow():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = _grant_minor(state, 0)
    return state, 0


def _to_before_plow(state):
    state = step(state, PlaceWorker(space="farmland"))
    return step(state, ChooseSubAction(name="plow"))


def _commit_plow(state):
    plow = next(a for a in legal_actions(state) if isinstance(a, CommitPlow))
    return step(state, plow)


# --- PendingRenovate (House Redevelopment) --------------------------------

def _build_renovate():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Wood house, 2 starting rooms -> renovate costs 2 clay + 1 reed.
    state = with_resources(state, 0, clay=2, reed=1)
    state = _grant_minor(state, 0)
    return state, 0


def _to_before_renovate(state):
    state = step(state, PlaceWorker(space="house_redevelopment"))
    return step(state, ChooseSubAction(name="renovate"))


def _commit_renovate(state):
    return step(state, CommitRenovate())


# --- PendingBuildMajor (Major Improvement) --------------------------------

def _build_major():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, clay=2)  # affords a Fireplace (idx 0)
    state = _grant_minor(state, 0)
    return state, 0


def _to_before_major(state):
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))  # push the composite
    return step(state, ChooseSubAction(name="build_major"))   # push PendingBuildMajor


def _commit_major(state):
    # A non-oven major (Fireplace, idx 0) so the frame is on top in its
    # after-phase (no oven wrapper interposed).
    return step(state, CommitBuildMajor(major_idx=0, return_fireplace_idx=None))


# --- Card-only frames -----------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    cs = _grant_minor(cs, cp)
    return cs, cp


# --- PendingPlayOccupation (Lessons) --------------------------------------

def _build_play_occupation():
    cs, cp = _card_state()
    cs = _reveal(cs, "lessons")
    p = cs.players[cp]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"consultant"})
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _to_before_play_occupation(state):
    state = step(state, PlaceWorker(space="lessons"))
    return step(state, ChooseSubAction(name="play_occupation"))


def _commit_play_occupation(state):
    return step(state, CommitPlayOccupation(card_id="consultant"))


# --- PendingPlayMinor (Major/Minor Improvement) ---------------------------

def _build_play_minor():
    cs, cp = _card_state()
    cs = _reveal(cs, "major_improvement")
    p = cs.players[cp]
    # market_stall costs 1 grain; only that minor in hand so it's the play.
    p = fast_replace(p, hand_minors=frozenset({"market_stall"}),
                     resources=fast_replace(p.resources, grain=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _to_before_play_minor(state):
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))  # push the composite
    return step(state, ChooseSubAction(name="play_minor"))    # push PendingPlayMinor


def _commit_play_minor(state):
    return step(state, CommitPlayMinor(card_id="market_stall"))


# ---------------------------------------------------------------------------
# The frame roster: (id, frame_class, before_event_id, builder, to_before, commit).
# `before_event_id` is the `<id>` the frame's before_/after_ events use.
# ---------------------------------------------------------------------------

_FRAMES = [
    ("sow", PendingSow, "sow", _build_sow, _to_before_sow, _commit_sow),
    ("bake_bread", PendingBakeBread, "bake_bread", _build_bake, _to_before_bake, _commit_bake),
    ("plow", PendingPlow, "plow", _build_plow, _to_before_plow, _commit_plow),
    ("renovate", PendingRenovate, "renovate", _build_renovate, _to_before_renovate, _commit_renovate),
    ("build_major", PendingBuildMajor, "build_major", _build_major, _to_before_major, _commit_major),
    ("family_growth", PendingFamilyGrowth, "family_growth",
     None, None, None),  # family_growth has a bespoke driver below
    ("play_occupation", PendingPlayOccupation, "play_occupation",
     _build_play_occupation, _to_before_play_occupation, _commit_play_occupation),
    ("play_minor", PendingPlayMinor, "play_minor",
     _build_play_minor, _to_before_play_minor, _commit_play_minor),
]


# family_growth is reachable only through Basic Wish for Children (a Proceed-host
# parent), so its build/to_before/commit don't fit the uniform space->choose
# shape. Wire it in explicitly.

def _build_family_growth():
    cs, cp = _card_state()
    cs = _reveal(cs, "basic_wish_for_children")
    from tests.factories import with_grid
    # people_total < num_rooms: add a 3rd room so family growth is legal.
    cs = with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})
    return cs, cp


def _to_before_family_growth(state):
    state = step(state, PlaceWorker(space="basic_wish_for_children"))
    return step(state, ChooseSubAction(name="family_growth"))


def _commit_family_growth(state):
    return step(state, CommitFamilyGrowth())


_DRIVERS = {
    "family_growth": (_build_family_growth, _to_before_family_growth, _commit_family_growth),
}


def _resolve_driver(name, builder, to_before, commit):
    if name in _DRIVERS:
        return _DRIVERS[name]
    return builder, to_before, commit


_FRAME_IDS = [row[0] for row in _FRAMES]


def _row(name):
    return next(r for r in _FRAMES if r[0] == name)


# ---------------------------------------------------------------------------
# (1) The after-automatic effect fires at the commit-flip.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _FRAME_IDS)
def test_after_auto_fires_at_commit_flip(name):
    """For every sub-action leaf frame, an after_<id> automatic effect fires when
    the frame pivots to its after-phase (at the Commit), before the trailing Stop —
    so the bump has landed while the frame is still on the stack in phase=='after'."""
    _name, frame_cls, eid, builder, to_before, commit = _row(name)
    builder, to_before, commit = _resolve_driver(name, builder, to_before, commit)
    with _registered_auto(f"after_{eid}"):
        state, cp = builder()
        state = to_before(state)
        pre = state.players[cp].resources.stone
        state = commit(state)
        top = state.pending_stack[-1]
        assert isinstance(top, frame_cls) and top.phase == "after", (
            f"{name}: frame not on top in after-phase after commit (top={top!r})"
        )
        assert state.players[cp].resources.stone == pre + 1, (
            f"{name}: after_{eid} automatic effect did not fire at the commit-flip"
        )


# ---------------------------------------------------------------------------
# (2) A before-trigger is surfaced as a FireTrigger in the before-phase.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _FRAME_IDS)
def test_before_trigger_surfaced_in_before_phase(name):
    """For every sub-action leaf frame, an owned/eligible before_<id> OPTIONAL
    trigger is surfaced as a FireTrigger among the before-phase legal actions
    (mirroring Potter on before_bake_bread)."""
    _name, frame_cls, eid, builder, to_before, commit = _row(name)
    builder, to_before, commit = _resolve_driver(name, builder, to_before, commit)
    with _registered_trigger(f"before_{eid}"):
        state, cp = builder()
        state = to_before(state)
        top = state.pending_stack[-1]
        assert isinstance(top, frame_cls) and top.phase == "before"
        assert FireTrigger(card_id=_HOOK_CARD) in legal_actions(state), (
            f"{name}: before_{eid} trigger not surfaced in the before-phase"
        )


# ---------------------------------------------------------------------------
# (3) An after-trigger is surfaced as a FireTrigger in the after-phase.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _FRAME_IDS)
def test_after_trigger_surfaced_in_after_phase(name):
    """For every sub-action leaf frame, an owned/eligible after_<id> OPTIONAL
    trigger is surfaced as a FireTrigger in the after-phase (alongside Stop)."""
    _name, frame_cls, eid, builder, to_before, commit = _row(name)
    builder, to_before, commit = _resolve_driver(name, builder, to_before, commit)
    with _registered_trigger(f"after_{eid}"):
        state, cp = builder()
        state = to_before(state)
        state = commit(state)
        top = state.pending_stack[-1]
        assert isinstance(top, frame_cls) and top.phase == "after"
        legal = legal_actions(state)
        assert FireTrigger(card_id=_HOOK_CARD) in legal, (
            f"{name}: after_{eid} trigger not surfaced in the after-phase"
        )
        assert Stop() in legal, f"{name}: Stop not offered in the after-phase"


# ---------------------------------------------------------------------------
# (4) before-automatic effects are DEFERRED by design (SUBACTION_HOOK_REFACTOR
# §4d) — NOT fired at the sub-action push. This pins the current deferred
# behavior so the deferral is a known/tested limitation, not a silent gap. Do
# NOT "fix" this into firing without the §4d maintainer decision.
# ---------------------------------------------------------------------------

def test_before_auto_is_deferred_not_fired_at_push():
    """A before_<id> AUTOMATIC effect registered on a sub-action does NOT fire when
    the sub-action frame is pushed (its before-phase begins) — the §4d deferral.

    Contrast with the after-auto, which fires at the commit-flip
    (test_after_auto_fires_at_commit_flip), and with the action-space *host*
    before-auto, which DOES fire at push (test_space_host_hooks.py). Sub-action
    before-autos are deliberately not wired; this test documents that."""
    with _registered_auto("before_sow"):
        state, cp = _build_sow()
        pre = state.players[cp].resources.stone
        state = _to_before_sow(state)        # pushes PendingSow (before-phase)
        top = state.pending_stack[-1]
        assert isinstance(top, PendingSow) and top.phase == "before"
        assert state.players[cp].resources.stone == pre, (
            "before_sow automatic effect fired at the sub-action push — the §4d "
            "before-auto deferral has changed (see SUBACTION_HOOK_REFACTOR §4d)"
        )
