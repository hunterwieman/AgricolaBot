"""Beaver Colony (minor improvement, E33; Ephipparius Expansion; no cost; prereq
1 Fenced Stable; printed 1 VP).

Card text: "From now on, one of your pastures with stable cannot hold animals. Each time
you get reed from an action space, you get 1 bonus point."

Two clauses:

1. A standing capacity RESTRICTION scoped to pastures WITH a stable: one such pasture must
   stay empty. Registered as an "empty-pasture" card whose qualifying predicate is
   `pasture.num_stables >= 1`, so `extract_slots` reserves (drops) the smallest-capacity
   pasture-with-stable from the accommodation capacity list. If the player has NO
   pasture-with-stable (e.g. after an Overhaul-style raze), the restriction is vacuous and
   imposes no reduction (user ruling 2026-07-13); when the player also owns Herbal Garden,
   ONE empty pasture-with-stable satisfies both (the sharing ruling — handled by the fold).
   `_on_play` flags the accommodation barrier so the engine evicts if the animals no longer
   fit under the reduction (the Milking Place idiom).

2. "Each time you get reed from an action space, you get 1 bonus point." In the 2-player
   game the Reed Bank is the ONLY action space that yields reed, so this is an
   `after_action_space` automatic effect on the `reed_bank` host (flat +1 per use, banked
   in CardStore): keying on the reed actually TAKEN (Refactor A), it reads the host frame's
   `taken.reed` stamped across the take. Reed Bank is atomic-hosted only when hooked, so
   `register_action_space_hook` hosts it when this card is owned. Eligibility reads
   `taken.reed >= 1`, so a (defensively) empty Reed Bank sweeps 0 and grants nothing.

The banked reed points are scored by a term reading CardStore; the printed 1 VP rides
`MinorSpec.vps`. Card-only state (the CardStore int) is empty in the Family game ->
byte-identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_empty_pasture
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "beaver_colony"
REED_SPACES = frozenset({"reed_bank"})


def _prereq(state: GameState, idx: int) -> bool:
    """At least one fenced stable — a stable inside a pasture (a HAVE-check at play time)."""
    return any(p.num_stables >= 1 for p in state.players[idx].farmyard.pastures)


def _on_play(state: GameState, idx: int) -> GameState:
    """One pasture-with-stable must now be empty: flag the accommodation barrier so the
    engine re-checks the fit and evicts if the animals no longer fit."""
    p = state.players[idx]
    if p.animals != Animals():   # Animals has no __bool__ — compare, don't truth-test
        p = fast_replace(p, animals_need_accommodation=True)
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _reed_eligible(state: GameState, idx: int) -> bool:
    """Fires after using Reed Bank when reed was actually taken (auto eligibility
    signature is (state, owner_idx)). The `space_id in REED_SPACES` check pins to the
    reed_bank host — atomic, so it carries a `taken` (a non-atomic frame never matches
    the pin, so `taken` is always present here)."""
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in REED_SPACES:
        return False
    return top.taken.reed >= 1


def _reed_apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, prereq=_prereq, vps=1, on_play=_on_play)
register_empty_pasture(CARD_ID, lambda pasture: pasture.num_stables >= 1)
register_auto("after_action_space", CARD_ID, _reed_eligible, _reed_apply)
register_action_space_hook(CARD_ID, REED_SPACES)
register_scoring(CARD_ID, _score)
