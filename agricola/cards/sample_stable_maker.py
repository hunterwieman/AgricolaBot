"""Sample Stable Maker (occupation, Dulcinaria Expansion; deck D #102; players 1+).

Card text (verbatim): "At the start of each returning home phase, you can
return a built stable to your supply to get 1 wood, 1 grain, 1 food, and a
\"Minor Improvement\" action."

TIMING — the printed anchor "at the start of each returning home phase" is a
named rung of the round-end timing ladder (user ruling 49, 2026-07-12;
``agricola/cards/round_end.py``, whose own docstring assigns this card to the
``start_of_returning_home`` window — position 2, BEFORE the phase's live-board
``returning_home`` rung and the ``__reset__`` bookkeeping). The window id is an
event string like any other; this is its first registrant.

THE CHOICE — "you can" makes the whole package one OPTIONAL trigger on the
window's frame. WHICH built stable is returned matters (an unfenced stable
frees its cell and drops its flexible 1-animal slot; a fenced stable halves
its pasture's capacity), so the trigger is variant-expanded: one
``FireTrigger(card_id, variant="<r>,<c>")`` per built-stable grid cell,
row-major. Eligibility is simply >= 1 built stable (the goods are
unconditional once a stable is returned).

ONE FIRE does, in order:

1. **Return the stable** — the cell reverts to EMPTY (its fences, if any, are
   untouched). The supply count is DERIVED (``helpers.stables_in_supply``), so
   it rises automatically; ``helpers.stables_built`` drops by one.
2. **Capacity guard** — removing a stable can SHRINK housing (an unfenced
   stable's flexible slot disappears; a fenced stable halves its pasture),
   possibly leaving the current animals over capacity with no inherent
   reconciliation. The owner's ``animals_need_accommodation`` flag is set
   unconditionally (the Milking Place idiom for capacity reductions —
   ``milking_place.py``): the engine's accommodation barrier re-checks the fit
   at the very next decision boundary, surfacing the keep-which choice
   (``PendingAccommodate``) only when the animals no longer fit, and clearing
   the flag cheaply otherwise.
3. **The goods** — +1 wood, +1 grain, +1 food.
4. **The "Minor Improvement" action** — a granted sub-action, so OPTIONAL
   (CARD_AUTHORING_GUIDE: only "you must" is mandatory) and paying the minor's
   own cost, exactly like Meeting Place's optional minor. IF the owner has a
   currently playable hand minor — evaluated on the post-goods state, since
   the freshly granted wood/grain/food may be what makes a minor affordable —
   the generic optional-grant wrapper is pushed
   (``PendingGrantedSubAction(subactions=("play_minor",))``, the Dwelling Plan
   idiom): it offers ``ChooseSubAction("play_minor")`` or ``Stop`` (= decline
   the minor while keeping everything else). With no playable minor the push
   is skipped — the goods still land (never offer a dead-end).

ONCE PER ROUND comes free from the window frame's ``triggers_resolved`` (one
``start_of_returning_home`` window per round, a fresh frame each round);
DECLINING the whole package is the frame's ``Proceed``. Ownership is the
window machinery's gate, so a hand-only copy is inert and the opponent is
never offered anything.

Card-game only (ownership-gated card registries; no on-play effect, no
CardStore): the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import CellType
from agricola.helpers import stables_built
from agricola.pasture import compute_pastures_from_arrays
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "sample_stable_maker"
FRAME_ID = "card:sample_stable_maker"   # the granted minor play's provenance


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"Return a built stable" needs a built stable; nothing else gates the
    fire (the goods are unconditional, the minor rider is skipped when dead).
    Once-per-round is the window frame's `triggers_resolved`."""
    return stables_built(state.players[idx].farmyard) >= 1


def _variants(state: GameState, idx: int) -> list:
    """One "<r>,<c>" variant per built-stable grid cell, row-major. Per-cell
    because WHICH stable is returned matters: a fenced stable halves its
    pasture's capacity, an unfenced one frees its cell and flexible slot."""
    grid = state.players[idx].farmyard.grid
    return [f"{r},{c}" for r in range(3) for c in range(5)
            if grid[r][c].cell_type is CellType.STABLE]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """One fire: return the chosen stable (cell -> EMPTY), flag the
    accommodation barrier (the removal can shrink housing — Milking Place
    idiom), grant 1 wood + 1 grain + 1 food, then — if a hand minor is
    playable on the post-goods state — push the optional play-minor wrapper
    (the Dwelling Plan idiom; Stop declines the minor alone)."""
    # local imports: card modules can't import legality/pending at module load
    # (load-order), matching the Beneficiary idiom.
    from agricola.legality import playable_minors
    from agricola.pending import PendingGrantedSubAction, push

    r_s, c_s = variant.split(",")
    r, c = int(r_s), int(c_s)

    p = state.players[idx]
    assert p.farmyard.grid[r][c].cell_type is CellType.STABLE, (
        f"sample_stable_maker: no built stable at ({r}, {c}) "
        f"(variant {variant!r})")
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.EMPTY)
            if (rr, cc) == (r, c) else cell
            for cc, cell in enumerate(row))
        for rr, row in enumerate(p.farmyard.grid))
    # Recompute the pasture cache from the new grid: Pasture objects cache
    # their stable count / capacity, so a stable edit must refresh them —
    # the engine's own build-stable resolver does exactly this.
    farmyard = fast_replace(
        p.farmyard, grid=grid,
        pastures=compute_pastures_from_arrays(
            grid, p.farmyard.horizontal_fences, p.farmyard.vertical_fences))
    p = fast_replace(
        p,
        farmyard=farmyard,
        resources=p.resources + Resources(wood=1, grain=1, food=1),
        animals_need_accommodation=True,
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))

    # The optional "Minor Improvement" action rider — gated on a hand minor
    # being playable RIGHT NOW (post-goods), so the wrapper is never a
    # dead-end; skipped entirely otherwise (the goods above still landed).
    if playable_minors(state, idx):
        state = push(state, PendingGrantedSubAction(
            player_idx=idx, initiated_by_id=FRAME_ID,
            subactions=("play_minor",), minor_is_action=True))
    return state


def _action_label(variant: str) -> str | None:
    """Web-UI label (mechanical, terse): "0,3" -> "Return stable (row 1,
    col 4) → 1 wood, 1 grain, 1 food (+ minor)". 1-based for the human."""
    parts = variant.split(",")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    r, c = int(parts[0]), int(parts[1])
    return (f"Return stable (row {r + 1}, col {c + 1}) "
            f"→ 1 wood, 1 grain, 1 food (+ minor)")


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect

# The optional once-per-round return on the round-end ladder's
# start_of_returning_home window (ruling 49), one variant per built stable.
register("start_of_returning_home", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_action_labeler(CARD_ID, _action_label)
