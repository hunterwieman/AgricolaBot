"""Master Renovator (occupation, deck E #87; Ephipparius Expansion; 1+ players).

Card text (verbatim): "At the end of the work phases of rounds 7 and 9, you
can take a "Renovation" action without placing a person and pay 1 building
resource of your choice less."
Category: Farm Planner. No printed VPs.

USER RULING (2026-07-14): "at the end of the work phases" = the round-end
ladder's ``end_of_work`` rung (position 0 — still during the work phase,
running once every worker is placed; machinery in
CARD_ENGINE_IMPLEMENTATION.md §5c).

TWO PIECES:

- **the grant** — an OPTIONAL trigger ("you can") on the round-end ladder's
  ``end_of_work`` window, eligible only when ``round_number`` names round 7
  or 9 (at the ladder, ``round_number`` still names the round just
  completing). Firing pushes a standard ``PendingRenovate`` carrying this
  card's provenance — "without placing a person" comes free from the window
  (no worker is involved), and the renovate then resolves exactly like a
  space renovate: the frame's enumerator offers one ``CommitRenovate`` per
  (legal target × effective payment). Declining is the window's ``Proceed``
  (no SkipTrigger — the standard optional-trigger shape). Once per window
  visit comes from the frame's ``triggers_resolved``; rounds 7 and 9 are
  separate rounds with separate window frames, so the card fires in each.

- **the discount** — "pay 1 building resource of your choice less" is a
  payment-time CHOICE, so it is a cost CONVERSION (not a reduction, which is
  choice-free): the generator returns the unchanged cost plus one variant
  per nonzero building-resource component (wood/clay/stone/reed) with that
  component reduced by 1 — the payment frontier surfaces each choice as its
  own payment. It is scoped to THIS card's grant via ``CostCtx.granted_by``
  (the seam landed in commit 700d16a: the ``PendingRenovate`` enumerator
  threads the frame's ``initiated_by_id`` into the cost context, ``None``
  for every space-initiated renovate) — a House Redevelopment / Farm
  Redevelopment renovate is never discounted.

ELIGIBILITY mirrors ``legality._can_renovate`` — a legal target exists
(house not stone; Mantlepiece's permanent renovation ban respected) — but
resolves affordability through the GRANT-scoped ctx
(``_renovate_ctx(p, t, granted_by="card:master_renovator")``), so the
discount itself can make the renovate affordable (a player 1 resource short
of the printed cost is still offered the grant). Never a dead-end offer.

Card-game only (ownership-gated registries; no CardStore): the Family game
is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _legal_renovate_targets, _renovate_ctx, can_pay
from agricola.pending import PendingRenovate, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "master_renovator"
_PROVENANCE = f"card:{CARD_ID}"
_ROUNDS = (7, 9)
_BUILDING_RESOURCES = ("wood", "clay", "stone", "reed")


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"...of rounds 7 and 9" + the player can actually renovate NOW.

    Mirrors ``legality._can_renovate`` (a legal target exists; Mantlepiece's
    permanent ban respected) with one difference: affordability is resolved
    through the grant-scoped ctx (``granted_by=_PROVENANCE``), so a renovate
    only the discount makes payable still qualifies. Once-per-window is the
    frame's ``triggers_resolved`` (handled by the machinery); ownership is
    the window machinery's gate."""
    if state.round_number not in _ROUNDS:
        return False
    p = state.players[idx]
    if "mantlepiece" in p.minor_improvements:   # renovation permanently forbidden
        return False
    return any(
        can_pay(state, idx, _renovate_ctx(p, t, granted_by=_PROVENANCE))
        for t in _legal_renovate_targets(state, p)
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Push the granted renovate. "Without placing a person" is inherent —
    the window trigger involves no worker. The frame's provenance is what
    the enumerator threads into ``CostCtx.granted_by``, scoping the
    discount below to exactly this grant."""
    return push(state, PendingRenovate(
        player_idx=idx, initiated_by_id=_PROVENANCE))


def _expand(state: GameState, idx: int, ctx, cost: Resources) -> list[Resources]:
    """"...pay 1 building resource of your choice less": the unchanged cost
    plus one variant per nonzero building-resource component with that
    component reduced by 1 — each choice its own payment. Scoped to this
    card's own grant via ``ctx.granted_by``; every other renovate (spaces,
    other cards' grants) passes through unchanged. Components are checked
    >= 1, so no variant ever goes negative."""
    out = [cost]
    if ctx.granted_by != _PROVENANCE:
        return out
    for field in _BUILDING_RESOURCES:
        if getattr(cost, field) >= 1:
            out.append(cost - Resources(**{field: 1}))
    return out


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register("end_of_work", CARD_ID, _eligible, _apply)
register_conversion("renovate", CARD_ID, _expand)
