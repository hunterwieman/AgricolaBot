"""The craft majors' harvest-span window surfaces (ruling 74, 2026-07-21).

NOT a card — machinery registrations. The three built-in craft major
improvements are once-per-harvest resource→food converters (Joinery, major 7:
1 wood → 2 food; Pottery, major 8: 1 clay → 2 food; Basketmaker's Workshop,
major 9: 1 reed → 3 food), and their `HarvestConversionSpec` rows in
`harvest_conversions.py` already give each two surfaces: the FEED offering
(`CommitHarvestConversion`) and, via `frontier_fire`, any harvest-time
`PendingFoodPayment` frontier. This module adds the third surface family the
span pattern prescribes — the free-span WINDOW triggers, through
``end_of_harvest`` and the breed frame's pre-commit stretch:

> **Ruling 74 (user, 2026-07-21, CARD_DEFERRED_PLANS.md):** "General pattern
> (user): every resource→food conversion printed without a specific harvest
> phase — Joinery / Pottery / Basketmaker's included — follows the span
> pattern. The `end_of_harvest` offering is unconditional but
> **Cards-mode-only** (user approved the lean; Family keeps its FEED-only
> surface, lossless there since nothing can change between the feed offering
> and end_of_harvest in Family)."

So every eligibility here gates on ``state.mode is GameMode.CARDS``: in the
Family game the crafts keep exactly their FEED-only surface (plus the
frontier), no window frame is ever hosted for them, and the Family trace —
and the C++ differential contract — are untouched.

**Ownership.** Craft-major "ownership" is the board's owner array
(``state.board.major_improvement_owners[idx]``), not a tableau card, so these
registrations ride the ruling-74 ownership-predicate override: each entry
passes the spec's own ``is_owned_fn`` through ``register_free_span_trigger``
(→ ``TriggerEntry.is_owned_fn``), which BOTH surfacing gates — the trigger
enumerator in `legality.py` and ``engine._has_window_trigger`` — consult in
place of the tableau ``_owns``.

**Registry keys.** Each entry registers under a pseudo-id
(``"craft_span_joinery"`` / ``"craft_span_pottery"`` /
``"craft_span_basketmaker"``) — a key that can never collide with a card id.
The pseudo-id is safe everywhere a trigger's card_id flows: the surfacing
gates read the entry's own ``is_owned_fn``; ``_apply_fire_trigger`` dispatches
through ``CARDS[card_id]`` and stamps the id into the host frame's
``triggers_resolved`` (plain strings); no spec is registered under it, so it
is never dealt, played, scored, or counted; and the web UI renders an unknown
FireTrigger id via ``play_web._card_info``'s title-case fallback (no crash).

**The budget.** A window fire performs THE SAME exchange the feed surface
performs and consumes THE SAME once-per-harvest budget: the built-in
conversion ids ``"joinery"`` / ``"pottery"`` / ``"basketmaker"`` in
``PlayerState.harvest_conversions_used`` — the ids the feed executor
(`_execute_harvest_conversion`) and the frontier fire
(`_execute_food_payment`, via `available_span_converters`) mark and check. A
feed or frontier fire therefore withholds the window offer for the rest of
that harvest, and vice versa; the next harvest's fresh FIELD entry resets it.
The exchange amounts are READ from the registered spec (input_cost /
food_out), never duplicated, so the three surfaces cannot drift apart.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.constants import GameMode
from agricola.cost import RESOURCE_FIELDS
from agricola.replace import fast_replace
from agricola.resources import Resources

# (pseudo registry key, built-in conversion id / shared budget id)
CRAFT_SPAN_IDS: tuple[tuple[str, str], ...] = (
    ("craft_span_joinery",     "joinery"),
    ("craft_span_pottery",     "pottery"),
    ("craft_span_basketmaker", "basketmaker"),
)


def _register_craft_span(pseudo_id: str, conversion_id: str) -> None:
    """Register one craft major's free-span window triggers, reading the
    exchange (input, food out, owner predicate) from its conversion spec so
    the window surface can never drift from the feed surface."""
    spec = HARVEST_CONVERSIONS[conversion_id]
    # The built-in craft rows are pure single-good -> food exchanges; a rider
    # or variant appearing here would mean the window fire below no longer
    # mirrors the feed fire — fail loud at import rather than diverge.
    assert spec.side_effect_fn is None and spec.variants_fn is None, conversion_id

    def _eligible(state, idx, triggers_resolved) -> bool:
        """Cards mode only (ruling 74: Family keeps its FEED-only surface,
        lossless there since nothing can change between the feed offering and
        end_of_harvest in Family), owner of the major, the shared
        once-per-harvest budget unused, and the input good on hand."""
        if state.mode is not GameMode.CARDS:
            return False
        if not spec.is_owned_fn(state, idx):
            return False
        p = state.players[idx]
        if conversion_id in p.harvest_conversions_used:
            return False
        return all(getattr(p.resources, f) >= getattr(spec.input_cost, f)
                   for f in RESOURCE_FIELDS)

    def _apply(state, idx):
        """Fire the exchange exactly as the feed surface does — debit the
        spec's input, add its food_out, mark the SHARED budget id (the window
        machinery carries no cost layer or budget bookkeeping of its own)."""
        p = state.players[idx]
        p = fast_replace(
            p,
            resources=p.resources - spec.input_cost
            + Resources(food=spec.food_out),
            harvest_conversions_used=(
                p.harvest_conversions_used | {conversion_id}),
        )
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))

    register_free_span_trigger(pseudo_id, _eligible, _apply,
                               is_owned_fn=spec.is_owned_fn)


for _pseudo_id, _conversion_id in CRAFT_SPAN_IDS:
    _register_craft_span(_pseudo_id, _conversion_id)
