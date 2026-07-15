"""Food Distributor (occupation, C155; Corbarius Expansion; players 4+).

Card text (verbatim): "When you play this card, you immediately get 1 grain and,
at the start of this returning home phase, an amount of food equal to the number
of occupied action space cards."
Clarification: "Action space cards = Round 1-14 action spaces."
No cost / prerequisite / passing / printed VPs.

TWO HALVES:

1. **On play** — "you immediately get 1 grain" is the standard on-play instant
   (Consultant's "immediately get" idiom) → an ``on_play`` that adds 1 grain. It
   also records the round of play in the per-card ``CardStore`` (II.7) so half 2
   can recognise "this returning home phase".

2. **"At the start of this returning home phase, food = occupied action space
   cards"** — a ONE-SHOT for the returning-home phase of the round the card was
   played in. The anchor "at the start of ... returning home phase" is the
   round-end ladder's ``start_of_returning_home`` window (round_end.py position 2,
   ruling 49) — PRE-reset, so the still-placed board is the event data. "you get"
   is mandatory and choice-free → an automatic effect (``register_auto``).

   ONE-SHOT via the CardStore latch, not a recurring window: the auto fires only
   when the stored play-round equals ``round_number`` (the round-end ladder runs
   with ``round_number`` naming the round being completed, the same value on_play
   stored during that round's work phase). Applying clears the stored key, so it
   can never fire in a later round. "occupied action space cards" is the count of
   the 14 Round-1–14 stage spaces (the clarification excludes the permanent
   spaces) that hold a worker of EITHER player (``sum(workers) > 0``); an
   unrevealed stage space holds no worker, so it contributes 0 naturally.

Card-game only (ownership-gated registry; CardStore is default-skipped): the
Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import PERMANENT_ACTION_SPACES, SPACE_IDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "food_distributor"

# The 14 "Round 1-14 action spaces" — the stage cards, i.e. every action space
# that is not a permanent one (the clarification's scope).
_STAGE_SPACES = tuple(s for s in SPACE_IDS if s not in set(PERMANENT_ACTION_SPACES))


def _on_play(state: GameState, idx: int) -> GameState:
    """+1 grain immediately, and stamp the play round so the returning-home
    one-shot recognises "this returning home phase"."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(grain=1),
        card_state=p.card_state.set(CARD_ID, state.round_number),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _occupied_stage_spaces(state: GameState) -> int:
    return sum(1 for sid in _STAGE_SPACES
               if sum(get_space(state.board, sid).workers) > 0)


def _eligible(state: GameState, idx: int) -> bool:
    # Fire only in the returning-home phase of the round the card was played in.
    return state.players[idx].card_state.get(CARD_ID) == state.round_number


def _apply(state: GameState, idx: int) -> GameState:
    food = _occupied_stage_spaces(state)
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=food),
        card_state=p.card_state.remove(CARD_ID),   # spent: never fires again
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("start_of_returning_home", CARD_ID, _eligible, _apply)
