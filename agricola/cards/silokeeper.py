"""Silokeeper (occupation, Bubulcus B112; players 1+).

Card text (verbatim): "Each time you use the action space card that has been
revealed right before the most recent harvest, you also get 1 grain."

Clarification (Unofficial Compendium): "The action space card is Round 4, 7, 9,
11, or 13."

Reading the timing precisely. Harvests occur at the END of rounds 4, 7, 9, 11, 13,
14. The card "revealed right before the most recent harvest" is the stage card
turned up at the start of that harvest's round — i.e. the space whose
``ActionSpaceState.revealed_round`` equals the most-recent-COMPLETED harvest round.
Because a round's harvest happens after its work phase, during round R's work the
most recent completed harvest is the largest harvest round STRICTLY LESS THAN R.
So the single target space's ``revealed_round`` is:

    max({4, 7, 9, 11, 13} that are < round_number)     (None in rounds 1–4)

which is always one of 4/7/9/11/13 exactly as the clarification states, and never
14 — round 14's harvest is the game's last, with no work phase after it, so its
card is never "the most recent harvest's card" during play. The target advances as
the game progresses: the round-4 card is the target in rounds 5–7, the round-7 card
in rounds 8–9, the round-9 card in rounds 10–11, the round-11 card in rounds 12–13,
and the round-13 card in round 14.

Timing / kind: "Each time you use …" with a flat, mandatory +1 grain that is
independent of the space's own output → an automatic effect (``register_auto`` on
the ``before_action_space`` window, per the standing trigger-timing ruling — the
Wood Cutter idiom). Eligibility compares the used space's ``revealed_round`` to the
current target.

Hook set: the target may be an ATOMIC space, so ``register_action_space_hook`` must
host those. The atomic stage cards that can land on a harvest reveal round are
Western Quarry (round 7), Vegetable Seeds (round 9), Eastern Quarry (round 11) and
Urgent Wish for Children (round 13); the round-4 candidates and the other
harvest-round candidates (House Redevelopment, Basic Wish, Pig Market, Cattle
Market, Cultivation) are already-hosted non-atomic spaces needing no hook. Played
via Lessons; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "silokeeper"

# The rounds whose stage card is revealed "right before" a harvest (rounds 4, 7,
# 9, 11, 13 end with a harvest; round 14's final harvest has no work phase after
# it, so its card is never a target — matching the clarification's omission of 14).
_HARVEST_REVEAL_ROUNDS = (4, 7, 9, 11, 13)

# The ATOMIC stage cards that can occupy a harvest reveal round (7/9/11/13); the
# round-4 candidates and the other candidates are already-hosted non-atomic spaces.
_HOOK_SPACES = frozenset({
    "western_quarry",            # can be the round-7 card
    "vegetable_seeds",           # can be the round-9 card
    "eastern_quarry",            # can be the round-11 card
    "urgent_wish_for_children",  # can be the round-13 card
})


def _target_reveal_round(round_number: int) -> int | None:
    """The ``revealed_round`` of the card revealed right before the most recent
    COMPLETED harvest: the largest harvest reveal round strictly below the current
    round (None in rounds 1–4, before any harvest has completed)."""
    past = [h for h in _HARVEST_REVEAL_ROUNDS if h < round_number]
    return max(past) if past else None


def _eligible(state: GameState, idx: int) -> bool:
    target = _target_reveal_round(state.round_number)
    if target is None:
        return False
    space_id = state.pending_stack[-1].space_id
    return get_space(state.board, space_id).revealed_round == target


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _HOOK_SPACES)
