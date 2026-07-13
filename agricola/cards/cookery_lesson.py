"""Cookery Lesson (minor improvement, B29; Bubulcus Expansion; cost 2 Food).

Card text: "Each time you use a 'Lesson' action space and a cooking improvement on the same
turn, you get 1 bonus point." (Clarification: cooking improvements have the bowl icon — the
Fireplace and Cooking Hearth.)

The reward is 1 point per Lessons-placement turn on which the player ALSO uses a cooking
improvement (cooks an animal). Two facts make this subtle:

1. **"Uses a cooking improvement" = an actual COOK, not an animal-count change.** An animal
   spent as a card's cost, discarded, or exchanged is NOT a cook and must not count (a real
   count-diff would false-positive on those). So the point is driven off the engine's actual
   animal→food cook sites via `resolution.note_animal_cook` -> this card's reaction
   (`register_animal_cook_reaction`), which fires at exactly the moment an animal is cooked.

2. **The cook can happen at several moments on a Lessons turn**, and no single "after Lessons"
   hook covers them all — paying the occupation's food cost cooks BEFORE the Lessons host
   flips, while an on-play-grant overflow cooks AFTER it (during accommodation). So the reward
   is not tied to the Lessons after-phase; instead it is granted AT THE COOK, gated on a
   Lessons host being on the stack (the "used a Lessons space this turn" signal, present
   throughout a Lessons resolution) and not-yet-scored this turn. `used_this_turn` (cleared at
   every turn boundary) enforces the "1 point max per Lessons placement" cap.

For the case where the player has no other reason to cook, an OPTIONAL explicit cook is
offered as play-variant triggers on the Lessons after-phase — "cook 1 sheep/boar/cattle via
your Fireplace/Cooking Hearth" (offered only with such an improvement — animal rates > 0 — and
the animal, and only while unscored). Firing one cooks the animal and grants the point.

Card-only state (the CardStore int + the used_this_turn markers) is empty in the Family game
-> byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_animal_cook_reaction,
    register_play_variant_trigger,
)
from agricola.helpers import cooking_rates
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "cookery_lesson"
_LESSONS = frozenset({"lessons"})
_SCORED = "cookery_lesson_scored"          # once-per-Lessons-turn cap (used_this_turn)
_ANIMAL = {"sheep": Animals(sheep=1), "boar": Animals(boar=1), "cattle": Animals(cattle=1)}


def _in_lessons(state: GameState) -> bool:
    """True while a Lessons action-space host is anywhere on the stack — i.e. we are inside a
    Lessons placement's resolution (the "used a Lessons space this turn" signal)."""
    return any(getattr(f, "space_id", None) in _LESSONS for f in state.pending_stack)


def _award(state: GameState, idx: int) -> GameState:
    """Bank 1 point for this Lessons turn, at most once (the `_SCORED` marker)."""
    p = state.players[idx]
    if _SCORED in p.used_this_turn:
        return state
    p = fast_replace(
        p,
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
        used_this_turn=p.used_this_turn | {_SCORED},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _react(state: GameState, idx: int) -> GameState:
    """Fired whenever the owner cooks an animal (via `note_animal_cook`): grant the point if
    the cook happened during a Lessons placement this turn."""
    return _award(state, idx) if _in_lessons(state) else state


# --- The optional explicit cook (play-variant triggers on the Lessons after-phase) ---------

def _cook_variants(state: GameState, idx: int) -> list[str]:
    """The animals the owner can cook via a cooking improvement: an animal rate > 0 means a
    Fireplace/Cooking Hearth is owned (animals cannot be cooked without one), and the animal
    is on hand."""
    p = state.players[idx]
    sR, bR, cR, _vR = cooking_rates(state, idx)
    variants: list[str] = []
    if sR > 0 and p.animals.sheep >= 1:
        variants.append("sheep")
    if bR > 0 and p.animals.boar >= 1:
        variants.append("boar")
    if cR > 0 and p.animals.cattle >= 1:
        variants.append("cattle")
    return variants


def _cook_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in _LESSONS:
        return False
    if _SCORED in state.players[idx].used_this_turn:   # already earned this turn
        return False
    return bool(_cook_variants(state, idx))


def _cook_apply(state: GameState, idx: int, variant: str) -> GameState:
    p = state.players[idx]
    sR, bR, cR, _vR = cooking_rates(state, idx)
    rate = {"sheep": sR, "boar": bR, "cattle": cR}[variant]
    p = fast_replace(
        p,
        animals=p.animals - _ANIMAL[variant],
        resources=p.resources + Resources(food=rate),
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return _award(state, idx)


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))
register_animal_cook_reaction(CARD_ID, _react)
register("after_action_space", CARD_ID, _cook_eligible, _cook_apply)
register_play_variant_trigger(CARD_ID, _cook_variants)
register_scoring(CARD_ID, _score)
