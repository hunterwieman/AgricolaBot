"""Museum Caretaker (occupation, E100; Ephipparius Expansion; players 1+).

Card text: "At the start of each work phase, if you have at least 1 wood,
1 clay, 1 reed, 1 stone, 1 grain, and 1 vegetable in your supply, you get
1 bonus point."
Category: Points Provider. No printed VPs.

TIMING — "at the start of each work phase" is the preparation ladder's
``start_of_work`` window (ruling 54, 2026-07-14), the ladder's last rung:
post-replenishment, the very instant the work phase opens, shared with
Freemason / Cob / Trout Pool.

DUAL REGISTRATION (user ruling 2026-07-14) — the Education Bonus shape, one
card on both firing kinds of one event:

- **The auto** ("you get" — mandatory, choice-free) banks the point whenever
  the six-goods criterion holds. It registers with ``order=10`` so it fires
  AFTER the window's other automatic effects (Freemason's 2 clay/stone land
  first — the explicit ordering mechanism, not import-order accident).
- **The trigger** exists for goods granted by same-window TRIGGERS: if the
  criterion was false when the autos ran but a same-window trigger grant then
  completes it, the player may fire Museum Caretaker on the same window frame
  and still collect. It never causes a frame push by itself: at window-open the
  criterion either held (the auto already banked and latched — trigger
  ineligible) or didn't (trigger ineligible too), so the trigger only surfaces
  on frames other cards' triggers opened. NOTE: with today's catalog the
  positive case is structurally unreachable — Cob (the only implemented
  `start_of_work` trigger) requires ≥1 clay itself, grants only clay + food
  toward the criterion, and CONSUMES grain, so it can never flip the criterion
  from false to true. The trigger half is live machinery awaiting a
  criterion-good-granting `start_of_work` trigger card; its dynamics are
  pinned by test_card_museum_caretaker.py via a mid-frame grant stand-in.

MAX 1 POINT PER ROUND — both paths latch ``used_this_round`` (cleared at the
next round's entry, the ladder's ``__collect__`` sentinel) and both gate on it,
so auto + trigger can never double-bank within a round.

THE POINTS — banked in the per-card CardStore counter, read at end-game by a
``register_scoring`` term (the Swimming Class banked-VP idiom); the bank
accumulates across rounds.

Card-game only (ownership-gated registries), so the Family trace and the C++
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_auto
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "museum_caretaker"


def _criterion(state: GameState, idx: int) -> bool:
    """≥1 each of wood, clay, reed, stone, grain, and vegetable in supply."""
    r = state.players[idx].resources
    return (r.wood >= 1 and r.clay >= 1 and r.reed >= 1
            and r.stone >= 1 and r.grain >= 1 and r.veg >= 1)


def _bank(state: GameState, idx: int) -> GameState:
    """+1 banked point, latched once-per-round."""
    p = state.players[idx]
    p = fast_replace(
        p,
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
        used_this_round=p.used_this_round | {CARD_ID},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _auto_eligible(state: GameState, idx: int) -> bool:
    return (CARD_ID not in state.players[idx].used_this_round
            and _criterion(state, idx))


def _trigger_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and CARD_ID not in state.players[idx].used_this_round
            and _criterion(state, idx))


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# The auto fires LAST among the window's autos (order=10): it must read the
# combined result of its same-instant peers (Freemason's clay/stone).
register_auto("start_of_work", CARD_ID, _auto_eligible, _bank, order=10)
# The trigger catches criterion-completing goods granted by same-window
# triggers (Cob); the shared used_this_round latch caps the round at 1 point.
register("start_of_work", CARD_ID, _trigger_eligible, _bank)
register_scoring(CARD_ID, _score)
