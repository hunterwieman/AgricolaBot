"""Fern Seeds (minor improvement, D8; Dulcinaria Expansion; traveling).

Card text (verbatim): "You get 2 food and 1 grain, which you must sow immediately."

No cost, no printed VPs. Prerequisite (printed): "1 Empty and 2 Planted Fields".
A TRAVELING (passing) card — after its on-play effect it is passed to the opponent
rather than kept in the tableau.

Category 2 (on-play one-shot) that COMPOSES A PRIMITIVE on play. on_play grants
2 food + 1 grain, then pushes the shared PendingSow primitive
(``initiated_by_id="card:fern_seeds"``) so the granted grain runs through the
normal CommitSow path. Two constraints pin the pushed sow:

- **max_fields=1** — exactly one field is sown (the single granted grain).
- **required_crop="grain"** (the new seam; user ruling 2026-07-20) — the sow may
  plant ONLY grain: ``_enumerate_pending_sow`` excludes every commit sowing veg
  and every card-field bundle touching a non-grain good, so no vegetable commit is
  offered even when the player holds vegetables, and no wood/stone card-sow is
  offered.

``crops_only`` is left False (the default): user ruling 2026-07-20 permits the
granted grain to be sown onto a grain-capable CARD field (e.g. Artichoke Field),
so the required-crop filter admits grain card-sows.

The sow is MANDATORY ("you must sow immediately", not "you may"): PendingSow's
before-phase offers a CommitSow per legal target and NO Stop, so the grain cannot
be declined. Sequencing mirrors Shifting Cultivation: PendingPlayMinor is a
commit-terminated host under the DEFERRED after-flip (user ruling 2026-07-14) —
``_execute_play_minor`` marks the host's work applied (and, being a traveling
card, has already passed it to the opponent) before running on_play, so the
PendingSow lands on top of the still-before-phase host; when the sow commits and
pops, the host flips (firing any after_play_minor autos only then) and its
after-phase Stop pops it cleanly.

THE PREREQUISITE + THE NO-DEAD-END GUARD.

"1 Empty and 2 Planted Fields" reads as an at-least (RULES.md: prerequisites are
"at least"), and "Fields" is the umbrella term, so CARD fields count too (ruling
45, 2026-07-12 — a card-field is one field for field-count readers): an owned
card-field holding nothing is an empty field, one holding a crop/goods is a
planted field. So the printed prereq is: (empty board fields + unplanted
card-fields) >= 1 AND (planted board fields + planted card-fields) >= 2.

The printed prereq alone can be satisfied while the forced grain sow has no legal
target: the only empty field might be a VEG-ONLY card field (e.g. Beanfield) with
no grain-sowable empty field anywhere, so pushing a mandatory required_crop="grain"
sow would leave an empty legal-action set. Because the engine must never offer a
dead-end (CARD_AUTHORING_GUIDE.md — "always gate a grant on whether it's actually
doable"), the registered prereq ALSO requires that a grain-sowable empty field
exists right now — an empty board field, or an empty card-field whose sow whitelist
includes grain. (The +1 grain the card grants guarantees the SUPPLY side of the
sow, so the guard only concerns the existence of a grain-accepting empty field.)
This extra conjunct is the engine's never-offer-a-dead-end gate; it is surfaced in
the implementation report for user visibility rather than treated as a settled
reading of the printed text.

Card-only: the pushed PendingSow's ``required_crop`` / ``max_fields`` default to
Family-constant values (None / 0), so the Family game is byte-identical and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.pending import PendingSow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "fern_seeds"


def _empty_board_field_exists(p) -> bool:
    grid = p.farmyard.grid
    return any(
        grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
        for r in range(3) for c in range(5)
    )


def _grain_sowable_empty_field_exists(p) -> bool:
    """A field that can right now receive a grain sow: an empty board FIELD cell,
    or an owned card-field with an empty stack whose sow whitelist includes grain
    (user ruling 2026-07-20 — the granted grain may be sown onto a grain-capable
    card field). Supply is not consulted: the card grants the grain, so a sowable
    field is the only thing the mandatory sow can dead-end on."""
    if _empty_board_field_exists(p):
        return True
    from agricola.cards.card_fields import (   # local import: load-order safe
        CARD_FIELDS, EMPTY_STACK, card_field_stacks, owned_card_fields,
    )
    for cid in owned_card_fields(p):
        if any(s == EMPTY_STACK for s in card_field_stacks(p, cid)) and any(
                good == "grain" for good, _amt in CARD_FIELDS[cid].sow_amounts):
            return True
    return False


def _prereq(state: GameState, idx: int) -> bool:
    """Printed "1 Empty and 2 Planted Fields" (at-least; card-fields count,
    ruling 45) PLUS the no-dead-end guard (a grain-sowable empty field must
    exist for the mandatory grain sow — user ruling 2026-07-20)."""
    from agricola.cards.card_fields import (   # local import: load-order safe
        planted_card_field_count, unplanted_card_field_count,
    )
    p = state.players[idx]
    grid = p.farmyard.grid
    empty_board = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0 and grid[r][c].veg == 0
    )
    planted_board = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and (grid[r][c].grain > 0 or grid[r][c].veg > 0)
    )
    empty_fields = empty_board + unplanted_card_field_count(p)
    planted_fields = planted_board + planted_card_field_count(p)
    return (
        empty_fields >= 1
        and planted_fields >= 2
        and _grain_sowable_empty_field_exists(p)
    )


def _on_play(state: GameState, idx: int) -> GameState:
    """Grant 2 food + 1 grain, then push a mandatory grain sow of exactly 1
    field. The `_prereq` guard guarantees the pushed sow always has a legal
    target, so it never dead-ends."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2, grain=1))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingSow(
        player_idx=idx, initiated_by_id="card:fern_seeds",
        max_fields=1, required_crop="grain"))


register_minor(
    CARD_ID,
    cost=Cost(),
    passing_left=True,
    vps=0,
    prereq=_prereq,
    on_play=_on_play,
)
