import agricola.cards.shelter  # noqa: F401  (registers the card)

"""Shelter (minor A1, Artifex; traveling): "You can immediately build a stable at no
cost, but only if you place it in a pasture covering exactly 1 farmyard space." No cost,
no prereq.

The optional grant surfaces WIDE via the minor play-variant seam (user ruling 2026-07-20):
"decline" (always) + "build" (only when a QUALIFYING cell exists — the single cell of a
pasture covering exactly 1 space that has no stable — AND a stable is in supply). "build"
pushes the reusable `PendingBuildStables` primitive with `cost=Resources()`, `max_builds=1`,
and `allowed_cells=<qualifying cells>`; the enumerator intersects those with the legal stable
cells, so the free stable can land ONLY in a 1-cell pasture. Passing: the card travels to the
opponent's hand.
"""
from agricola.actions import CommitBuildStable, CommitPlayMinor, Proceed, Stop
from agricola.cards.shelter import CARD_ID, FRAME_ID, _qualifying_cells
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import stables_built, stables_in_supply
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

def _replace_player(state, idx, new_player):
    return fast_replace(state, players=tuple(
        new_player if i == idx else state.players[i] for i in range(2)))


def _one_cell_edges(r, c):
    """Fence edges (as index-pairs into the h/v arrays) that fully enclose cell (r,c)
    as its own 1-cell pasture: top h[r][c], bottom h[r+1][c], left v[r][c], right v[r][c+1]."""
    h = {(r, c), (r + 1, c)}
    v = {(r, c), (r, c + 1)}
    return h, v


def _two_cell_edges(r, c):
    """Fence edges enclosing the horizontal pair (r,c)+(r,c+1) as ONE 2-cell pasture
    (the shared edge v[r][c+1] is left open, so the two cells connect)."""
    h = {(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)}
    v = {(r, c), (r, c + 2)}
    return h, v


def _fence(state, idx, h_set, v_set):
    """Set the given horizontal/vertical fence edges on player `idx`'s farmyard and
    recompute the pasture cache (caller-discipline: fence mutations must pass `pastures`)."""
    p = state.players[idx]
    h = [list(row) for row in p.farmyard.horizontal_fences]
    v = [list(row) for row in p.farmyard.vertical_fences]
    for (r, c) in h_set:
        h[r][c] = True
    for (r, c) in v_set:
        v[r][c] = True
    hf = tuple(tuple(row) for row in h)
    vf = tuple(tuple(row) for row in v)
    fy = fast_replace(p.farmyard, horizontal_fences=hf, vertical_fences=vf,
                      pastures=compute_pastures_from_arrays(p.farmyard.grid, hf, vf))
    return _replace_player(state, idx, fast_replace(p, farmyard=fy))


def _set_grid(state, idx, cells, cell_type):
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = fast_replace(grid[r][c], cell_type=cell_type)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return _replace_player(state, idx, fast_replace(p, farmyard=fy))


def _at_play_minor_frame(*, wood=5):
    """A CARDS state at a PendingPlayMinor with Shelter the ONLY card in the current
    player's hand and `wood` wood on hand (to prove none is spent). Fresh farm: no
    pastures, so no qualifying cell yet."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
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


def _pasture_with(state, idx, cell):
    return next(P for P in state.players[idx].farmyard.pastures if cell in P.cells)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in PLAY_MINOR_VARIANTS


def test_registration_static_facts():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                 # no cost
    assert spec.prereq is None                 # no prereq
    assert spec.passing_left is True           # traveling minor
    assert spec.vps == 0
    assert spec.min_occupations == 0 and spec.max_occupations is None
    # No prereq -> always meets it.
    state, cp = _at_play_minor_frame()
    assert prereq_met(spec, state, cp)


# ---------------------------------------------------------------------------
# The wide variants — "build" gated on a qualifying 1-cell pasture + a stable in supply
# ---------------------------------------------------------------------------

def test_no_pastures_offers_decline_only():
    state, _cp = _at_play_minor_frame()   # fresh farm, no pastures
    assert _variants_offered(state) == ["decline"]


def test_one_cell_pasture_offers_build():
    state, cp = _at_play_minor_frame()
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    # Sanity: exactly one 1-cell pasture, at (0,4), no stable.
    assert _qualifying_cells(state.players[cp]) == ((0, 4),)
    assert _variants_offered(state) == ["build", "decline"]


def test_two_cell_pasture_cells_not_offered():
    # A pasture covering 2 spaces does not qualify -> only "decline".
    state, cp = _at_play_minor_frame()
    h, v = _two_cell_edges(0, 0)
    state = _fence(state, cp, h, v)
    P = _pasture_with(state, cp, (0, 0))
    assert len(P.cells) == 2                       # it really is a 2-cell pasture
    assert _qualifying_cells(state.players[cp]) == ()
    assert _variants_offered(state) == ["decline"]


def test_one_cell_pasture_with_stable_not_offered():
    # Enclose (0,4) as a 1-cell pasture, then put a stable in it -> num_stables==1 ->
    # the pasture already contains a stable, so it no longer qualifies.
    state, cp = _at_play_minor_frame()
    h, v = _one_cell_edges(0, 4)
    state = _set_grid(state, cp, [(0, 4)], CellType.STABLE)
    state = _fence(state, cp, h, v)
    P = _pasture_with(state, cp, (0, 4))
    assert len(P.cells) == 1 and P.num_stables == 1
    assert _qualifying_cells(state.players[cp]) == ()
    assert _variants_offered(state) == ["decline"]


def test_no_stable_in_supply_offers_decline_only():
    # A qualifying 1-cell pasture exists, but all 4 stables are placed elsewhere (supply
    # exhausted) -> "build" is withheld.
    state, cp = _at_play_minor_frame()
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    state = _set_grid(state, cp, [(0, 1), (0, 2), (0, 3), (1, 4)], CellType.STABLE)
    assert stables_in_supply(state.players[cp]) == 0
    assert _qualifying_cells(state.players[cp]) == ((0, 4),)   # still qualifies geometrically
    assert _variants_offered(state) == ["decline"]


# ---------------------------------------------------------------------------
# The pushed frame — free, exactly one, restricted to the qualifying cell(s)
# ---------------------------------------------------------------------------

def test_build_pushes_free_single_cell_restricted_frame():
    state, cp = _at_play_minor_frame()
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    out = MINORS[CARD_ID].on_play(state, cp, "build")
    top = out.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.player_idx == cp
    assert top.initiated_by_id == FRAME_ID
    assert top.cost == Resources()               # free stable
    assert top.max_builds == 1                    # exactly one
    assert top.num_built == 0
    assert top.allowed_cells == ((0, 4),)         # only the 1-cell pasture's cell
    # NOTE: `build_stables_action` is intentionally NOT asserted here — the given ruling's
    # constructor omitted it (defaults True). Whether Shelter, like Pole Barns / Stable /
    # Stallwright (all card-effect stable builds), should carry build_stables_action=False
    # is an open question flagged to the user, not settled by this test.


def test_decline_is_a_noop():
    state, cp = _at_play_minor_frame()
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    out = MINORS[CARD_ID].on_play(state, cp, "decline")
    assert out is state


# ---------------------------------------------------------------------------
# allowed_cells actually restricts placement — only the 1-cell pasture cell is offered,
# even though other empty cells exist on the farm.
# ---------------------------------------------------------------------------

def test_build_only_offers_the_qualifying_cell():
    state, cp = _at_play_minor_frame()
    # One qualifying 1-cell pasture at (0,4) AND a non-qualifying 2-cell pasture at (0,0),
    # with plenty of other empty cells around.
    h1, v1 = _one_cell_edges(0, 4)
    h2, v2 = _two_cell_edges(0, 0)
    state = _fence(state, cp, h1 | h2, v1 | v2)
    assert _qualifying_cells(state.players[cp]) == ((0, 4),)
    out = step(state, _commit(state, "build"))
    assert isinstance(out.pending_stack[-1], PendingBuildStables)
    build_cells = [(a.row, a.col) for a in legal_actions(out)
                   if isinstance(a, CommitBuildStable)]
    assert build_cells == [(0, 4)]               # ONLY the 1-cell pasture's cell


# ---------------------------------------------------------------------------
# Real flow — play "build", place the free stable, it lands in the pasture and doubles its
# capacity; the card travels; nothing is debited.
# ---------------------------------------------------------------------------

def test_realflow_build_free_stable_doubles_capacity_and_passes():
    state, cp = _at_play_minor_frame(wood=5)
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    before_res = state.players[cp].resources
    before_cap = _pasture_with(state, cp, (0, 4)).capacity
    assert before_cap == 2                        # 2 * 1 cell * 2**0 stables

    out = step(state, _commit(state, "build"))
    # Passing: the card immediately travels to the opponent's hand.
    assert CARD_ID in out.players[1 - cp].hand_minors
    assert CARD_ID not in out.players[cp].hand_minors
    assert isinstance(out.pending_stack[-1], PendingBuildStables)

    commit = next(a for a in legal_actions(out) if isinstance(a, CommitBuildStable))
    assert (commit.row, commit.col) == (0, 4)
    out = step(out, commit)
    top = out.pending_stack[-1]
    assert top.num_built == 1
    # max_builds==1: cap saturated -> no more cell commits, only Proceed.
    nxt = legal_actions(out)
    assert not any(isinstance(a, CommitBuildStable) for a in nxt)
    assert any(isinstance(a, Proceed) for a in nxt)
    out = step(out, Proceed())   # flip to after-phase
    out = step(out, Stop())      # pop the build host

    p = out.players[cp]
    assert stables_built(p.farmyard) == 1
    assert p.farmyard.grid[0][4].cell_type == CellType.STABLE
    # Free build AND no card cost -> resources are entirely unchanged.
    assert p.resources == before_res
    # The stable inside the 1-cell pasture doubles its capacity (2 -> 4).
    assert _pasture_with(out, cp, (0, 4)).capacity == before_cap * 2
    assert all(not isinstance(f, PendingBuildStables) for f in out.pending_stack)


def test_realflow_decline_builds_nothing_and_passes():
    state, cp = _at_play_minor_frame(wood=5)
    h, v = _one_cell_edges(0, 4)
    state = _fence(state, cp, h, v)
    before_res = state.players[cp].resources
    before_stables = stables_built(state.players[cp].farmyard)
    out = step(state, _commit(state, "decline"))
    p = out.players[cp]
    assert stables_built(p.farmyard) == before_stables   # nothing built
    assert p.resources == before_res                     # nothing spent
    assert CARD_ID in out.players[1 - cp].hand_minors     # traveled
    assert all(not isinstance(f, PendingBuildStables) for f in out.pending_stack)
