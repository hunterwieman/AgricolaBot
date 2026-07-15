"""Asparagus Knife (minor improvement, A58; Artifex Expansion; Food Provider).

Card text (verbatim): "In the returning home phase of rounds 8, 10, and 12, you
can take 1 vegetable from exactly 1 vegetable field. You can immediately exchange
it for 3 food and 1 bonus point."

Cost: 1 Wood. Printed VPs: 0 — the bonus points are BANKED via a scoring term (a
per-card CardStore counter read back at end-game), not printed VPs. Not passing.

WHAT THE CARD DOES — in the returning home phase of rounds 8, 10, and 12, the
owner may (once per round) take 1 vegetable from a vegetable field, and MAY
immediately exchange that vegetable for 3 food + 1 bonus point.

USER RULING (2026-07-15) — the take and the exchange are surfaced as TWO options
of one optional play-variant trigger, plus the window's Proceed = decline:

- ``"convert"`` — take 1 veg from a veg field AND immediately exchange it: +3
  food and +1 banked bonus point (the veg is consumed by the exchange, not added
  to supply). "Immediately" here means the exchange is part of the SAME option
  (not a separate later instant).
- ``"take_only"`` — take 1 veg from a veg field to supply, no exchange (+1 veg).

The vegetable may be taken from ANY vegetable field — no field choice is offered
(the ruling: keep it simple). The take is from GRID vegetable field tiles only:
the first row-major FIELD cell holding veg (see CARD-FIELD NOTE below).

TIMING — the printed anchor names the phase, so the effect rides the round-end
ladder's ``returning_home`` window (the same rung Silage uses; ruling 49,
2026-07-12). Rounds 8, 10, and 12 are all NON-harvest rounds
(``HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}``), so that window fires normally in
each of them. Eligibility is ``state.round_number in {8, 10, 12}`` AND the owner
holds a grid FIELD cell with veg >= 1.

ONCE PER ROUND comes free from the window frame's ``triggers_resolved`` (one
``returning_home`` window per round, a fresh frame each round); DECLINING is the
frame's ``Proceed`` (no SkipTrigger — the standard shape).

THE BANKED POINTS — there is no immediate-VP mechanism, so a "convert" fire
increments a per-card CardStore counter (banked across rounds 8/10/12, up to +3),
and the scoring term reads the count back at end-game. This mirrors Beer Keg's
banked-point pattern.

CARD-FIELD NOTE (a deliberately NARROWER reading than Silage) — rulings 45/46
hold a card-field (Beanfield etc.) counts as "a field", and Silage treats
veg-bearing card-fields as valid removal sources (each with its own variant +
``remove_card_crop``, because removals there can fire card reactions). Per the
user's "take from ANY veg field, keep it simple" (2026-07-15), this card takes
from GRID vegetable field TILES ONLY. Whether card-field veg sources should be
included later is left to the user.

Card-only state (the CardStore int) is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md and
silage.py / beer_keg.py.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "asparagus_knife"

# The returning-home phases of these rounds (all non-harvest) offer the effect.
_ROUNDS = frozenset({8, 10, 12})


def _has_veg_field(state: GameState, idx: int) -> bool:
    """True iff the player holds at least one grid FIELD cell with veg >= 1."""
    return any(
        cell.cell_type is CellType.FIELD and cell.veg >= 1
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _take_one_veg(state: GameState, idx: int) -> GameState:
    """Remove 1 veg from the first row-major grid FIELD holding veg (any veg
    field — no field choice; ruling 2026-07-15). Eligibility guarantees such a
    field exists, so the fallback return is unreachable."""
    p = state.players[idx]
    for r, row in enumerate(p.farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type is CellType.FIELD and cell.veg >= 1:
                grid = tuple(
                    tuple(
                        fast_replace(cl, veg=cl.veg - 1) if (rr, cc) == (r, c) else cl
                        for cc, cl in enumerate(rw))
                    for rr, rw in enumerate(p.farmyard.grid))
                p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid))
                return fast_replace(
                    state,
                    players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return state  # unreachable — eligibility guarantees a veg field


def _variants(state: GameState, idx: int) -> list:
    """The two options — "convert" (take + exchange for 3 food + 1 bonus point)
    and "take_only" (take 1 veg to supply) — both requiring a veg field (the
    eligibility guarantee; guarded here too so the enumeration is self-consistent
    if the call convention ever changes)."""
    if not _has_veg_field(state, idx):
        return []
    return ["convert", "take_only"]


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Rounds 8/10/12's returning home phase (all non-harvest — the window fires)
    AND the player holds a veg field. Ownership is the window machinery's gate;
    once-per-round is the frame's ``triggers_resolved``."""
    return state.round_number in _ROUNDS and _has_veg_field(state, idx)


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """One fire: take 1 veg from a veg field, then apply the chosen option —
    "convert" exchanges it for +3 food and banks +1 bonus point (the veg is
    consumed, not added to supply); "take_only" adds the veg to supply."""
    state = _take_one_veg(state, idx)
    p = state.players[idx]
    if variant == "convert":
        p = fast_replace(
            p,
            resources=p.resources + Resources(food=3),
            card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1))
    elif variant == "take_only":
        p = fast_replace(p, resources=p.resources + Resources(veg=1))
    else:
        raise AssertionError(f"asparagus_knife: unknown variant {variant!r}")
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across rounds 8/10/12 (0..3)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


def _action_label(variant: str) -> str | None:
    """Web-UI label (terse, mechanical)."""
    if variant == "convert":
        return "Take 1 veg → 3 food + 1 bonus point"
    if variant == "take_only":
        return "Take 1 veg (to supply)"
    return None


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), vps=0)

# The optional once-per-round take/exchange on the round-end ladder's
# returning_home window (ruling 49), variant-expanded into convert / take_only.
register("returning_home", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_scoring(CARD_ID, _score)
register_action_labeler(CARD_ID, _action_label)
