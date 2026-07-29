"""Confidant (occupation, B93; Bubulcus Expansion; players 1+).

Card text (verbatim): "Place 1 food from your supply on each of the next 2, 3, or 4
round spaces. At the start of these rounds, you get the food back and your choice of a
\"sow\" or \"Build Fences\" action."
Clarification (verbatim): "For example, if played in Round 9, you must place 1 food on
each of Rounds 10-11, 10-12, or 10-13."
No cost, no prerequisite, no printed VPs. Played via Lessons.

GOVERNING RULING 74 (2026-07-21, CARD_DEFERRED_PLANS.md; the earlier C5 defer is
superseded — user: "seems straightforward"). The user's ruling was the hold release
itself; the build shape recorded beside it — "play-occupation variants N in {2,3,4}
(gated food >= N, debiting N food) + schedule_resources (the food back) +
schedule_effect (the per-round grant), resolved at the round_space_collection window as
a variant trigger ['sow', 'build_fences'] (named actions — full-width frames), window
Proceed = decline" — was the IMPLEMENTER's build record, not ruling text; in particular
the "(gated food >= N)" parenthetical was never a user ruling (an earlier docstring
misattributed it as one) and is superseded by the 2026-07-27 ruling below. Driver
detail (verbatim): "the granted sow / build-fences are the NAMED actions, so the pushed
frames carry their action flags True (full sow: PendingSow with max_fields=0; fences:
PendingBuildFences with build_fences_action=True)."

Four composed mechanisms, every one an existing seam:

1. THE N-CHOICE AT PLAY — `register_play_occupation_variant` (exemplars roof_ballaster.py
   / baker.py). One play route per distinct placement COUNT c, each declaring a food
   SURCHARGE of c. The placed food leaves supply at play: the executor folds the surcharge
   into the debited play cost (FOOD_PAYMENT_DESIGN.md §8), so `_on_play` never re-debits
   it. USER RULING (2026-07-27): asked whether a player may use the at-any-time cooking
   conversions to afford a bigger placement count N, the user ruled "Yes, obviously they
   may." (This supersedes the shipped raw `food >= c` pre-filter, whose docstring had
   justified itself as blocking a "backdoor grain->food conversion" — under ruling 82 that
   gate deleted rules-legal plays.) So `_variants` offers every positive count for the
   round, and affordability is the play-occupation enumerator's standard, liquidation-aware
   per-(variant, payment) gate — `_payable(payment + surcharge)`, exactly the
   stable_sergeant / roof_ballaster shape; when the combined debit's food exceeds food on
   hand, the executor's shortfall guard raises it via a `PendingFoodPayment` re-run at
   debit time.

2. THE FOOD COMES BACK — `schedule_resources` (exemplar pond_hut.py). 1 food onto each of
   the c scheduled round spaces (`future_resources`), auto-collected at each round's start.
   Debit c food at play (mechanism 1's surcharge); schedule c returns over the SAME c
   rounds — same rounds, same count.

3. THE PER-ROUND GRANT — `schedule_effect` (exemplar handplow.py). Unions CARD_ID into
   each of those c rounds' `future_rewards[slot].effect_card_ids`, which gates mechanism 4
   on exactly those rounds (the Handplow schedule gate).

4. THE ROUND-START CHOICE — a `round_space_collection` window trigger (handplow.py's
   window) PLUS `register_play_variant_trigger` for the ['sow', 'build_fences'] routes
   (exemplars cottager.py / scholar.py). At the round_space_collection window (the instant
   the round-space goods land — user ruling 2026-07-14), the owner is offered one
   FireTrigger per currently-legal route (variant-expanded by `_expand_variant_triggers`),
   with the window's Proceed as the decline. Firing pushes the NAMED action: a full
   `PendingSow` (`max_fields=0` — the generic uncapped "Sow" action, slurry.py) or the
   literal `PendingBuildFences` (`build_fences_action=True`). Eligibility gates each route
   on it being doable NOW (`_can_sow` / `_any_legal_pasture_commit` — never a dead-end)
   AND CARD_ID being scheduled on THIS round; firing consumes the slot (like Handplow), and
   the window frame's `triggers_resolved` gives once-per-round.

NEAR-END READING — FLAGGED for the user, awaiting a ruling. RULES.md general rule: "On the
next x round spaces. If fewer than x rounds remain, place only on the remaining spaces."
So in round R, variant N covers rounds R+1 .. min(R+N, 14) — placing on min(N, 14-R)
spaces, the surcharge kept consistent at that many food, and variants that collapse to
identical placements near the end are DEDUPED (round 11 -> {2,3}; round 12 -> {2}; round
13 -> {1}; round 14 -> {0}). OPEN QUESTION, implemented on my lean and NOT a settled
ruling: does the printed "2, 3, or 4" (a minimum of 2) FORBID playing Confidant when fewer
than 2 round spaces remain (round 13 with 1 left, round 14 with 0 left), or does the
general "place on remaining" rule let you play it on 1/0 spaces? This code ALLOWS it
(caps placement at what remains), because RULES.md's general rule governs and no "minimum
required to play" is printed. Awaiting the user's ruling.

PLAYABILITY — played-and-wasted, never gated (user ruling 2026-07-21). Confidant prints no
"you may not play if you cannot place" prerequisite, so it follows the general occupation
rule: it is ALWAYS playable (base occupation cost permitting), and its mandatory placement
simply WASTES when it can't be carried out (the `place_0` variant). This is the Prophet /
Basket Weaver category; the contrast is Established Person, whose printed "You may not play
this card if you cannot renovate" DOES gate playability. So `_variants` always returns at
least one route, and Confidant is never excluded from `playable_occupations`.

The `place_0` waste variant is what makes this correct with NO engine change: because
`_variants` is never empty, the occupation-play routes (Lessons / Scholar / a granted play)
push a non-empty `PendingPlayOccupation` off the ordinary base-cost gate alone. (An earlier
follow-up added a committability guard to `agricola/legality.py` to gate playability on the
placement being affordable; it was REVERTED, user 2026-07-21 — playability is base cost plus
any printed prerequisite, and an effect *wastes* rather than gates, so the guard conflated
the two. A future gated card — Established Person's "you may not play if you cannot renovate"
— wants a real occupation-prerequisite mechanism, not a committability check.)
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect, schedule_resources
from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.legality import (
    _any_legal_pasture_commit,
    _can_sow,
    _payable,
    _play_occupation_ctx,
    effective_payments,
)
from agricola.pending import (
    PendingBuildFences,
    PendingPlayOccupation,
    PendingSow,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "confidant"


# ---------------------------------------------------------------------------
# 1 + 2 + 3: the N-choice at play, and the two schedules it sets
# ---------------------------------------------------------------------------

def _placement_counts(round_number: int) -> list[int]:
    """The DISTINCT numbers of round spaces Confidant can place on, played in
    `round_number`. Variant N in {2,3,4} covers rounds R+1 .. min(R+N, 14) — i.e.
    min(N, 14-R) spaces (RULES.md: "if fewer than x rounds remain, place only on the
    remaining spaces"). Near the end the N's that collapse to the same count are ONE
    variant (round 11 -> [2,3]; round 12 -> [2]; round 13 -> [1]; round 14 -> [0]).
    The near-end reading is FLAGGED (module docstring): counts 0/1 are ALLOWED here."""
    remaining = 14 - round_number
    return sorted({min(n, remaining) for n in (2, 3, 4)})


def _any_positive_pair_payable(state: GameState, idx: int, c_min: int) -> bool:
    """Would the play-occupation enumerator offer at least one (positive-count,
    payment) pair right now? Mirrors its gate — liquidation-aware `_payable` on
    payment + surcharge over the base-cost payment frontier — for the SMALLEST
    positive count (payability is monotone in the count, so if the smallest
    fails on every payment, every count does). The base cost lives on the
    `PendingPlayOccupation` host, on top of the stack at every call site this
    card reaches (the enumerator, the executor's debit and its post-raise
    re-run — Confidant registers no pair gate, so the bundle-filter path that
    calls variants under a food frame never runs for it); if no such host is
    in sight, fall back to surcharge-only payability (base treated as free —
    the permissive direction, matching a free first occupation)."""
    p = state.players[idx]
    top = state.pending_stack[-1] if state.pending_stack else None
    if isinstance(top, PendingPlayOccupation) and top.player_idx == idx:
        payments = effective_payments(state, idx, _play_occupation_ctx(top.cost))
        return any(_payable(state, idx, p, pm + Resources(food=c_min))
                   for pm in payments)
    return _payable(state, idx, p, Resources(food=c_min))


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """One play route per distinct positive placement count c for the round (1 food per
    space over the rounds-capped, deduped counts), each declaring a food SURCHARGE of c.
    No food pre-filter here (USER RULING 2026-07-27: the at-any-time cooking conversions
    may fund a bigger count — "Yes, obviously they may"): affordability of base payment +
    surcharge is the play-occupation enumerator's standard, liquidation-aware
    per-(variant, payment) gate, and a food shortfall raises through the executor's
    `PendingFoodPayment` re-run at debit time (the stable_sergeant shape).

    The WASTE `place_0` route (user ruling 2026-07-21: played-and-wasted, never gated —
    Confidant prints no "you may not play if you cannot place" prerequisite, the Prophet /
    Basket Weaver category) is offered exactly when NO positive count would survive the
    enumerator's pair gate (`_any_positive_pair_payable` — too few rounds remain, round
    14, or even the smallest count atop the base payment cannot be covered by supply plus
    conversions): with every positive pair unpayable the waste-play is the rules-legal
    remainder and must stay offerable (ruling 82), while offering place_0 alongside a
    payable positive count would let the player dodge the mandatory placement. Hence
    there is always at least one variant, the mandatory placement is never dodgeable,
    and it is never a playability gate."""
    counts = [c for c in _placement_counts(state.round_number) if c > 0]
    if counts and _any_positive_pair_payable(state, idx, min(counts)):
        return [(f"place_{c}", Resources(food=c)) for c in counts]
    return [("place_0", Resources())]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Schedule the food's RETURN (`schedule_resources`, 1 food per round) and the
    per-round GRANT (`schedule_effect`) over the next c round spaces. The c-food SURCHARGE
    is debited by the play executor (folded into the play cost, FOOD_PAYMENT_DESIGN.md §8),
    NOT here. For c == 0 (round 14) the ranges are empty — nothing scheduled."""
    if variant is None:                      # defensive: a variant is always chosen for this card
        return state
    c = int(variant.split("_")[1])
    R = state.round_number
    rounds = range(R + 1, R + c + 1)         # the next c round spaces (all <= 14 by construction)
    state = schedule_resources(state, idx, rounds, Resources(food=1))
    return schedule_effect(state, idx, rounds, CARD_ID)


# ---------------------------------------------------------------------------
# 4: the per-round "sow" / "Build Fences" choice at the round_space_collection window
# ---------------------------------------------------------------------------

def _scheduled_slot(p, round_number: int):
    """The `future_rewards` slot index for `round_number` if it carries Confidant's grant,
    else None (the Handplow schedule gate)."""
    slot = round_number - 1
    fr = p.future_rewards
    if 0 <= slot < len(fr) and CARD_ID in fr[slot].effect_card_ids:
        return slot
    return None


def _legal_routes(state: GameState, idx: int) -> list[str]:
    """The subset of ('sow', 'build_fences') doable RIGHT NOW — never offer a route whose
    pushed frame would have no legal commit (a dead frame). Sow: an empty field + a crop in
    supply, or a card-field sow (`_can_sow`). Build Fences: at least one legal pasture
    commit — wood + geometry (`_any_legal_pasture_commit`). Order per ruling 74."""
    p = state.players[idx]
    routes: list[str] = []
    if _can_sow(state, p):
        routes.append("sow")
    if _any_legal_pasture_commit(state, p):
        routes.append("build_fences")
    return routes


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the round-start choice iff Confidant is scheduled on THIS round (the slot
    gate) AND at least one route is legal now. Ownership + once-per-round (the window
    frame's `triggers_resolved`) are enforced by the enumerator, not here (mirrors
    Handplow)."""
    p = state.players[idx]
    return (_scheduled_slot(p, state.round_number) is not None
            and bool(_legal_routes(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Consume this round's grant (like Handplow — so it fires at most once), then push
    the chosen NAMED action: a full `PendingSow` (`max_fields=0`) or the literal
    `PendingBuildFences` (`build_fences_action=True`). The window's Proceed is the decline
    (this apply runs only when a route was fired)."""
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    if variant == "sow":
        return push(state, PendingSow(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}", max_fields=0))
    return push(state, PendingBuildFences(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", build_fences_action=True))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
# "At the start of these rounds ... your choice of a 'sow' or 'Build Fences' action" — the
# round_space_collection window (round-space schedule grants resolve at COLLECTION time,
# user ruling 2026-07-14), with the two routes as play-variant FireTriggers.
register("round_space_collection", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_routes)
