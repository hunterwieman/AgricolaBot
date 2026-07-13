"""Ox Skull (minor improvement, E37; Ephipparius Expansion; no cost; prereq 1 Cattle).

Card text: "When you play this card, you immediately get 1 food. During scoring, if you have
no cattle, you get 3 bonus points."

Three parts:

1. `on_play` gains 1 food (a flat "immediately" — at play time; user-confirmed 2026-07-13).
2. Prerequisite: >= 1 cattle at play (a HAVE-check). So you play it while holding cattle, then
   aim to end with none.
3. A scoring term worth 3 iff you have no cattle at game end.

Because reaching 0 cattle is what pays, a player holding exactly 1 cattle at end-game is
better off DISCARDING it (cattle category −1 but Ox Skull +3, net +1 — 1 cattle scores +1),
yet that could be wrong if another card rewards cattle, so it must be the player's CHOICE.
Ox Skull therefore registers a BEFORE-SCORING decision (`register_before_scoring`): at the
BEFORE_SCORING boundary, if the owner has exactly 1 cattle, the engine offers keep-vs-discard
via the standard `PendingCardChoice` frame; the resolver applies it and pops. The offer is
made only at exactly 1 cattle — the sole case where discarding can help Ox Skull (with 0 it's
moot; with >= 2, discarding to 0 is a wash or worse) — keeping the action set minimal.

Card-only: no state persists (the discard mutates animals directly, the offer latches
`fired_once` at push). Family byte-identical.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_before_scoring, register_card_choice_resolver
from agricola.pending import pop
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "ox_skull"


def _prereq(state: GameState, idx: int) -> bool:
    """At least 1 cattle at play (a HAVE-check)."""
    return state.players[idx].animals.cattle >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return 3 if state.players[idx].animals.cattle == 0 else 0


def _before_scoring_options(state: GameState, idx: int):
    """Offer keep/discard only at exactly 1 cattle — the sole case where discarding the cow
    (to reach 0 cattle for +3) can strictly help Ox Skull."""
    return ("keep", "discard") if state.players[idx].animals.cattle == 1 else ()


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    if chosen == "discard":
        p = state.players[idx]
        p = fast_replace(p, animals=p.animals - Animals(cattle=1))
        state = fast_replace(
            state, players=tuple(p if i == idx else state.players[i] for i in range(2))
        )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_minor(CARD_ID, prereq=_prereq, on_play=_on_play)
register_scoring(CARD_ID, _score)
register_before_scoring(CARD_ID, _before_scoring_options)
register_card_choice_resolver(CARD_ID, _resolve)
