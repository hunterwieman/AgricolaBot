"""Upholstery (minor improvement, E31; Ephipparius Expansion; no cost, no printed VP).

Card text: "Each time you build or play an improvement after this one, you can place 1
reed on this card, irretrievably, to get 1 bonus point, up to the number of rooms in
your house."

An OPTIONAL, per-improvement reed->point conversion, banked on the card:

- "build or play an improvement" spans both majors and minors. The coarse
  `after_build_improvement` event is auto-only (it cannot host optional triggers), and no
  single event covers both kinds, so this registers the SAME optional trigger on BOTH
  `after_play_minor` and `after_build_major`. Each fires in the host's after-phase; the
  host's `triggers_resolved` gives "each time" (once per improvement).
- "after this one" excludes the very play that plays Upholstery (and, per the general rule
  "a newly-played card's 'each time' trigger only fires on later turns", the whole play
  turn). The after-phase ownership trick that auto-excludes before-phase cards (Paper
  Maker) does NOT apply here — Upholstery is already in the tableau when its own
  after_play_minor fires — so `on_play` sets a same-turn latch (`CARD_ID` in
  `used_this_turn`, which the engine clears at every turn boundary), and eligibility
  suppresses the trigger while the latch is set. on_play runs after the after-autos but
  before the enumerator surfaces after-triggers, so the latch is visible in time.
- "place 1 reed ... irretrievably, to get 1 bonus point" — the reed is spent from the
  player's own supply (never the general supply) and a running count is banked in the
  card's CardStore; the scoring term returns that count (= bonus points).
- "up to the number of rooms in your house" — a running cap: eligibility requires
  banked < current room count. Rooms can grow over the game, so the cap grows with them.

Card-only state (the CardStore int + the used_this_turn latch) is empty in the Family
game -> byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState, PlayerState

CARD_ID = "upholstery"


def _room_count(p: PlayerState) -> int:
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _on_play(state: GameState, idx: int) -> GameState:
    # Latch the play turn so the trigger cannot fire on the play that played Upholstery
    # (nor anything else this turn) — "after this one" / "only on later turns".
    p = state.players[idx]
    p = fast_replace(p, used_this_turn=p.used_this_turn | {CARD_ID})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    if CARD_ID in p.used_this_turn:            # played this turn -> excluded
        return False
    if p.resources.reed < 1:                   # a reed from the player's own supply
        return False
    return p.card_state.get(CARD_ID, 0) < _room_count(p)   # cap = number of rooms


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources - Resources(reed=1),          # spent irretrievably
        card_state=p.card_state.set(CARD_ID, banked + 1),   # bank 1 bonus point
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, on_play=_on_play)
register("after_play_minor", CARD_ID, _eligible, _apply)
register("after_build_major", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
