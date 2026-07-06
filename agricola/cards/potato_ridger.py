"""Potato Ridger (minor improvement, A59; Artifex Expansion; Food Provider).

Card text (verbatim): "Each time after you harvest 1+ vegetables, if you then have
3+ vegetables in your supply, you can turn exactly 1 vegetable into 6 food. With
4+ vegetables, you must do so."
Official clarification (verbatim): "'Harvest' is equivalent to the field phase, or
any literal effect of a card saying 'Harvest a [crop/vegetable].'"
Cost: 1 Wood. No prerequisite. VPs: 0. Kept (not passing).

What the card does in game terms: whenever a harvesting event delivers the owner
at least one vegetable, their vegetable supply is checked — holding 4 or more,
they immediately exchange exactly one vegetable for 6 food (no choice about it);
holding exactly 3, they may choose to make that exchange. At most one exchange
per harvesting event.

TWO-TIER mapping (user ruling 2026-07-05: "with 4+ vegetables, you must do so"
is an AUTOMATIC effect — mandatory and choice-free, fired with NO player input,
never a forced singleton offer; this aligns with the engine's standing
classification that a mandatory, choice-free card effect is an automatic
effect, not a trigger):

- **The MUST tier** (occasion harvested 1+ veg AND post-income supply >= 4) is a
  per-occasion AUTO (``register_harvest_occasion_auto``): it fires mechanically
  right after the occasion applies — no frame, no decision step, no FireTrigger
  ever surfaces for it.
- **The CAN tier** ("if you then have 3+ vegetables … you can") is a
  per-occasion OPTIONAL trigger (``register_harvest_occasion_trigger``): the
  ``PendingHarvestOccasion`` host offers FireTrigger, and Proceed declines. Its
  eligibility is written as printed — supply >= 3 — with the 4+ case carved off
  by the auto plus the seam's same-occasion exclusivity (next paragraph), so in
  practice the offer appears only at exactly 3.

SAME-OCCASION EXCLUSIVITY ("turn EXACTLY 1 vegetable" — one exchange per
occasion): when the auto fires at 4+, the supply lands back on 3+, which would
re-qualify the optional tier for the very same occasion. The seam prevents that
double-react: ``apply_harvest_occasion_autos`` reports which autos fired, the
host frame carries them as ``autos_fired``, and both the host-push check and
the trigger enumerator exclude a card whose automatic tier already reacted to
this occasion (``register_harvest_occasion_trigger``'s adapted eligibility).
So 4 veg -> the auto fires -> 3 veg -> NO optional offer for that same
occasion; a later occasion checks afresh (the exclusion is per-occasion, never
sticky). The optional tier's own once-per-occasion rides the host's
``triggers_resolved``.

Both tiers are UNSCOPED (ruling 12, 2026-07-04 — the harvest-verb lexicon —
plus this card's own clarification, which equates "harvest" with the
field-phase effect *or* a literal card "Harvest" wording): eligibility gates on
the OCCASION alone, never on ``state.phase`` and never on ``occasion.source``.
A real harvest's field-phase take fires them, and so does a card-played field
phase (Bumper Crop's mid-WORK ``source="card:bumper_crop"`` occasion) or a
card-granted extra harvest emitting its own occasion.

Counting doctrine (HARVEST_HANDOFF.md, the counting lexicon): "you harvest 1+
vegetables" sums the vegetable UNITS the occasion took (the manifest's veg
entries' ``amount``); "if you then have 3+ vegetables in your supply" reads the
player's supply AFTER the occasion's income landed — guaranteed by the seam,
which fires occasion effects post-income. A 4+ supply with NO vegetable
harvested this occasion forces nothing ("each time AFTER YOU HARVEST 1+
vegetables" is the entry condition for both tiers).

Ownership is checked by the seam at auto-fire, host-push, and enumeration time
(registrations are global), so the eligibility fns here are pure occasion +
supply.

Card-only registries throughout (occasion autos/triggers never fire in the
Family game), so the Family game stays byte-identical and the C++ gates are
untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_occasion_auto,
    register_harvest_occasion_trigger,
)
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "potato_ridger"


def _veg_harvested(occasion) -> int:
    """Vegetable UNITS this occasion took (sum of its veg entries' amounts)."""
    return sum(e.amount for e in occasion.entries if e.crop == "veg")


def _must_eligible(state: GameState, idx: int, occasion) -> bool:
    """The MUST tier: the occasion harvested 1+ vegetables AND the player then
    holds 4+ in supply (post-income) — the exchange fires automatically (user
    ruling 2026-07-05: no player input)."""
    return (_veg_harvested(occasion) >= 1
            and state.players[idx].resources.veg >= 4)


def _can_eligible(state: GameState, idx: int, occasion) -> bool:
    """The CAN tier, as printed: the occasion harvested 1+ vegetables AND the
    player then holds 3+ in supply. The 4+ case never reaches this offer: the
    auto fires first and the seam's ``autos_fired`` exclusion keeps this card's
    optional tier out of the same occasion — in practice the offer appears
    only at exactly 3."""
    return (_veg_harvested(occasion) >= 1
            and state.players[idx].resources.veg >= 3)


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """Turn exactly 1 vegetable into 6 food (shared by both tiers)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=-1, food=6))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(Resources(wood=1)))  # no on-play effect
register_harvest_occasion_auto(CARD_ID, _must_eligible, _apply)
register_harvest_occasion_trigger(CARD_ID, _can_eligible, _apply)
