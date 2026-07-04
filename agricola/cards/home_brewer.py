"""Home Brewer (occupation, C #110; Consul Dirigens Expansion; Food Provider).

Card text (verbatim): "After the field phase of each harvest, you can use this
card to turn exactly 1 grain into your choice of 3 food or 1 bonus point."
Occupation. Players 1+. VPs: 0. No cost / prerequisite. Not passing.

TIMING — window #7 `after_field_phase` (user ruling 2026-07-03: Home Brewer
belongs on window #7 `after_field_phase`; HARVEST_WINDOWS_DESIGN.md §1 ladder,
CARD_DEFERRED_PLANS.md "Harvest-window redesign — user rulings"). The printed
"after the field phase of each harvest" maps to the ladder's `after_field_phase`
window, which resolves after that player's crop take and BEFORE the feeding
phase — it is NOT the feeding seam. (Previously this rode HARVEST_CONVERSIONS,
the feeding seam, under an audited equivalence reading; that registration is
removed.)

Ordering (ruling 3, 2026-07-03): `after_field_phase` sits inside the per-player
FIELD segment — the starting player's whole FIELD segment (including their #7)
resolves before the other player's segment begins, so the two players' #7 frames
never coexist.

ONCE PER HARVEST — "turn exactly 1 grain … each harvest" is a single use per
harvest: exactly one grain, exactly one output. This is expressed by the
per-player `PendingHarvestWindow` frame's `triggers_resolved` (once-per-window is
automatic — firing the trigger marks it resolved, so it cannot fire twice in the
same window), NOT by any manual bookkeeping.

THE CHOICE — "your choice of 3 food or 1 bonus point" is a choice of OUTPUT (the
input is always exactly 1 grain). It is modeled as a play-variant optional
trigger (mirroring stable_manure.py's variant mechanism): two variants —

  - "food": 1 grain -> 3 food (the Food-Provider density).
  - "vp":   1 grain -> 1 bonus point (banked; no immediate-VP mechanism exists).

The trigger surfaces as one `FireTrigger(card_id, variant)` per variant at the
`after_field_phase` host; the player fires exactly one (or `Proceed` declines).

The bonus point cannot be granted immediately, so the "vp" variant banks +1 in a
per-card CardStore counter (carried across all six harvests) and the scoring term
reads it back at end-game. Card-only state (the CardStore int) is empty in the
Family game, so it stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "home_brewer"
WINDOW_ID = "after_field_phase"


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Usable iff the player has at least 1 grain to spend (ownership and the
    once-per-window guard are enforced by the host enumerator via `_owns` and the
    frame's `triggers_resolved`; firing marks the card resolved for this window)."""
    return state.players[idx].resources.grain >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """The two output choices, offered only when 1 grain is affordable. The
    input is always exactly 1 grain, so both variants share the same eligibility;
    `_eligible` already gates on grain, but re-check here so the enumerator never
    surfaces an unaffordable variant."""
    if state.players[idx].resources.grain < 1:
        return []
    return ["food", "vp"]


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Spend exactly 1 grain; either gain 3 food ("food") or bank 1 bonus point
    ("vp")."""
    p = state.players[idx]
    resources = p.resources - Resources(grain=1)
    card_state = p.card_state
    if variant == "food":
        resources = resources + Resources(food=3)
    elif variant == "vp":
        card_state = card_state.set(CARD_ID, card_state.get(CARD_ID, 0) + 1)
    else:  # pragma: no cover - defensive
        raise AssertionError(f"unknown home_brewer variant {variant!r}")
    p = fast_replace(p, resources=resources, card_state=card_state)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Bonus points banked across all harvests via the "vp" variant."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Pure recurring-window occupation: played via Lessons, on-play is a no-op (the
# effect is the recurring after-field-phase conversion only).
register_occupation(CARD_ID, lambda state, idx: state)

# Optional play-variant trigger on window #7 (after_field_phase); one grain,
# one output, once per harvest (the frame's triggers_resolved gives once-per-window).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)

register_scoring(CARD_ID, _score)
