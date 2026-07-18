"""Pole Barns (minor E1, Ephipparius; traveling): "You can immediately build up to 3
stables at no cost. (You must pay the cost of this card though.)" Cost 2 wood, prereq
"15 Fences Built".

The optional grant surfaces WIDE via the minor play-variant seam: "skip" (always) + "build"
(only when a free stable is placeable now). "build" pushes the reusable multi-shot
`PendingBuildStables` primitive with `cost=Resources()`, `max_builds=3`, and — per the
2026-07-17 user ruling — `build_stables_action=False` (a CARD EFFECT, not the literal Build
Stables action). The 2-wood card cost is paid by the normal play-minor path; the stables are
free. Passing: the card travels to the opponent's hand.
"""
import agricola.cards.pole_barns  # noqa: F401  (registers the card)

from agricola.actions import CommitBuildStable, CommitPlayMinor, Proceed, Stop
from agricola.cards.pole_barns import CARD_ID, FRAME_ID
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import fences_built, stables_in_supply
from agricola.legality import legal_actions
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import PendingBuildStables, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_n_fences(state, idx, n):
    """Place exactly `n` fence pieces on player `idx`'s farmyard (horizontal edges first,
    row-major, then vertical), recomputing the pasture cache so the Farmyard stays
    self-consistent. Only the COUNT matters for the prereq; the layout is irrelevant."""
    p = state.players[idx]
    h = [[False] * 5 for _ in range(4)]   # shape (4, 5)
    v = [[False] * 6 for _ in range(3)]   # shape (3, 6)
    slots = [("h", r, c) for r in range(4) for c in range(5)] + \
            [("v", r, c) for r in range(3) for c in range(6)]
    for kind, r, c in slots[:n]:
        (h if kind == "h" else v)[r][c] = True
    hf = tuple(tuple(row) for row in h)
    vf = tuple(tuple(row) for row in v)
    fy = fast_replace(
        p.farmyard, horizontal_fences=hf, vertical_fences=vf,
        pastures=compute_pastures_from_arrays(p.farmyard.grid, hf, vf))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_grid(state, idx, cells, cell_type):
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = fast_replace(grid[r][c], cell_type=cell_type)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _empty_cells(state, idx):
    g = state.players[idx].farmyard.grid
    return [(r, c) for r in range(3) for c in range(5)
            if g[r][c].cell_type == CellType.EMPTY]


def _at_play_minor_frame(*, wood=2, n_fences=15):
    """A CARDS state at a PendingPlayMinor with Pole Barns in the current player's hand,
    `wood` wood, and `n_fences` fence pieces built (default: prereq satisfied)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    state = _set_n_fences(state, cp, n_fences)
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     resources=Resources(wood=wood))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_pending_stack(state, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _variants_offered(state):
    return sorted(a.variant for a in legal_actions(state)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)


def _commit(state, variant):
    return next(a for a in legal_actions(state)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in PLAY_MINOR_VARIANTS


def test_registration_static_facts():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))   # 2 Wood
    assert spec.passing_left is True                         # traveling minor
    assert spec.vps == 0
    assert spec.min_occupations == 0 and spec.max_occupations is None


# ---------------------------------------------------------------------------
# Prereq boundary: 14 built -> unplayable, 15 -> playable
# ---------------------------------------------------------------------------

def test_prereq_unplayable_at_14_fences():
    state, cp = _at_play_minor_frame(n_fences=14)
    assert fences_built(state.players[cp].farmyard) == 14
    assert not prereq_met(MINORS[CARD_ID], state, cp)
    # And so the card is not offered as a play at all.
    assert not _variants_offered(state)


def test_prereq_playable_at_15_fences():
    state, cp = _at_play_minor_frame(n_fences=15)
    assert fences_built(state.players[cp].farmyard) == 15
    assert prereq_met(MINORS[CARD_ID], state, cp)
    assert _variants_offered(state)   # offered


# ---------------------------------------------------------------------------
# The wide variants
# ---------------------------------------------------------------------------

def test_both_variants_offered_when_a_stable_is_placeable():
    # Fresh farm (empty cells + 4 stables in supply) + 15 fences: build & skip both offered.
    state, _cp = _at_play_minor_frame()
    assert _variants_offered(state) == ["build", "skip"]


def test_build_variant_absent_when_no_empty_cell():
    # Fill every empty cell with FIELD -> no legal stable cell -> only "skip".
    state, cp = _at_play_minor_frame()
    state = _set_grid(state, cp, _empty_cells(state, cp), CellType.FIELD)
    assert _variants_offered(state) == ["skip"]


def test_build_variant_absent_when_no_stable_in_supply():
    # Build 4 stables (exhaust the supply of 4); empty cells remain elsewhere, so the only
    # thing missing is a stable in supply -> only "skip".
    state, cp = _at_play_minor_frame()
    state = _set_grid(state, cp, [(0, 4), (1, 4), (2, 4), (0, 3)], CellType.STABLE)
    assert stables_in_supply(state.players[cp]) == 0
    assert _variants_offered(state) == ["skip"]


# ---------------------------------------------------------------------------
# The pushed frame (build_stables_action=False, free, up-to-3)
# ---------------------------------------------------------------------------

def test_build_pushes_free_up_to_3_card_effect_frame():
    state, cp = _at_play_minor_frame()
    out = MINORS[CARD_ID].on_play(state, cp, "build")
    top = out.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.player_idx == cp
    assert top.initiated_by_id == FRAME_ID
    assert top.cost == Resources()               # free stables
    assert top.max_builds == 3                   # up to 3
    assert top.num_built == 0
    assert top.build_stables_action is False     # a CARD EFFECT, not the literal action


def test_skip_is_a_noop():
    state, cp = _at_play_minor_frame()
    out = MINORS[CARD_ID].on_play(state, cp, "skip")
    assert out is state


# ---------------------------------------------------------------------------
# Real flow: play, then build 3 free; the card passes to the opponent
# ---------------------------------------------------------------------------

def test_realflow_build_three_free_and_passes():
    state, cp = _at_play_minor_frame(wood=2)
    before_wood = state.players[cp].resources.wood
    out = step(state, _commit(state, "build"))
    # The card immediately travels to the opponent's hand (passing).
    assert CARD_ID in out.players[1 - cp].hand_minors
    assert CARD_ID not in out.players[cp].hand_minors
    assert isinstance(out.pending_stack[-1], PendingBuildStables)
    # Build three stables, one commit at a time (free).
    for _ in range(3):
        commit = next(a for a in legal_actions(out) if isinstance(a, CommitBuildStable))
        out = step(out, commit)
    top = out.pending_stack[-1]
    assert top.num_built == 3
    # Cap saturated: no more cell commits, only Proceed.
    nxt = legal_actions(out)
    assert not any(isinstance(a, CommitBuildStable) for a in nxt)
    assert any(isinstance(a, Proceed) for a in nxt)
    out = step(out, Proceed())   # flip to after-phase
    out = step(out, Stop())      # pop the build host
    p = out.players[cp]
    from agricola.helpers import stables_built
    assert stables_built(p.farmyard) == 3
    # Only the 2-wood card cost was spent; the stables were free.
    assert p.resources.wood == before_wood - 2
    assert all(not isinstance(f, PendingBuildStables) for f in out.pending_stack)


def test_realflow_build_one_then_proceed():
    state, cp = _at_play_minor_frame(wood=2)
    before_wood = state.players[cp].resources.wood
    out = step(state, _commit(state, "build"))
    commit = next(a for a in legal_actions(out) if isinstance(a, CommitBuildStable))
    out = step(out, commit)
    top = out.pending_stack[-1]
    assert top.num_built == 1
    # After 1 build (of max 3): more cell commits AND Proceed both legal.
    nxt = legal_actions(out)
    assert any(isinstance(a, CommitBuildStable) for a in nxt)
    assert any(isinstance(a, Proceed) for a in nxt)
    out = step(out, Proceed())   # stop early at 1
    out = step(out, Stop())
    p = out.players[cp]
    from agricola.helpers import stables_built
    assert stables_built(p.farmyard) == 1
    assert p.resources.wood == before_wood - 2   # only the card cost
    assert all(not isinstance(f, PendingBuildStables) for f in out.pending_stack)


def test_realflow_skip_builds_nothing_and_passes():
    state, cp = _at_play_minor_frame(wood=2)
    before_wood = state.players[cp].resources.wood
    from agricola.helpers import stables_built
    before_stables = stables_built(state.players[cp].farmyard)
    out = step(state, _commit(state, "skip"))
    p = out.players[cp]
    assert stables_built(p.farmyard) == before_stables   # nothing built
    assert p.resources.wood == before_wood - 2           # card cost still paid
    assert CARD_ID in out.players[1 - cp].hand_minors     # traveled
    assert all(not isinstance(f, PendingBuildStables) for f in out.pending_stack)
