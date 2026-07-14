"""Sugar Baker (occupation, D101; Consul Dirigens Expansion; players 1+).

Card text: "Each time after you use the 'Grain Utilization' action space, you
can buy 1 bonus point for 1 food. Place the food on the action space (for the
next visitor)."
Clarification: "If this card is played by using the 'Grain Utilization' space
(e.g. with Freshman A097,) you may not immediately use this card."
Category: Points Provider. No printed VPs.

TWO HALVES:

1. **The purchase** — an explicit "after you use" → an OPTIONAL trigger on the
   ``after_action_space`` event, filtered to ``space_id == "grain_utilization"``
   (the coarse-event idiom; Grain Utilization is non-atomic, so its host frame
   always exists — no hook registration). Firing pays 1 food (through the
   shared food-payment path, the Plow Driver / Curator idiom — raise-only
   ``PendingFoodPayment`` when short, resume registered under this card id),
   banks 1 bonus point in the per-card CardStore counter (``register_scoring``
   reads it back), and records the paid food as OWED TO THE NEXT VISITOR.
   Once per use via the host frame's ``triggers_resolved``.

2. **The deposited food** — "place the food on the action space (for the next
   visitor)". Representation (user ruling 2026-07-14, option (b)): the food is
   NOT written onto the space's ``accumulated_amount`` (Grain Utilization is
   not an accumulation space and its resolver never grants deposits); it rides
   the owner's CardStore under a second key (``sugar_baker_owed``), and a
   ``before_action_space`` AUTOMATIC effect with ``any_player=True`` (the Milk
   Jug opponent-hook shape) grants it to the NEXT player who uses Grain
   Utilization — either player, the owner included — and clears the debt. The
   rules outcome is identical to food physically on the space; the pile can
   never exceed 1 food, because any next visit collects the deposit in its
   before-phase, before the after-phase could deposit again.

   NOTE the any_player routing: the auto's ``idx`` is the OWNER (whose
   CardStore holds the debt); the recipient is the VISITOR — the host frame's
   ``player_idx``.

FRESHMAN (A097, unimplemented): per the printed clarification, a Sugar Baker
played by using Grain Utilization itself may not fire on that same use. No
implemented route plays an occupation via Grain Utilization, so no gate exists
today; when Freshman lands, this trigger's eligibility must exclude the very
host under which the card was just played.

Card-game only (ownership-gated registries), so the Family trace and the C++
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register, register_auto
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "sugar_baker"
_OWED_KEY = "sugar_baker_owed"     # CardStore key for the food owed to the next visitor
_FOOD_COST = 1


# --- half 1: the after-use purchase (optional trigger) ----------------------

def _pay_and_bank(state: GameState, idx: int) -> GameState:
    """Debit 1 food, bank 1 bonus point, and place the food on the space (as
    the owed-to-next-visitor debt). Reached directly (food on hand) and as the
    post-food-payment resume."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=_FOOD_COST),
        card_state=(p.card_state
                    .set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1)
                    .set(_OWED_KEY, _FOOD_COST)),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _buy_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """At the Grain Utilization host's after-phase (the event key scopes the
    phase; the space filter is ours), with the 1 food payable — directly or by
    liquidating convertible goods."""
    if CARD_ID in triggers_resolved:
        return False
    if state.pending_stack[-1].space_id != "grain_utilization":
        return False
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _buy_apply(state: GameState, idx: int) -> GameState:
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_bank(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


# --- half 2: the deposited food goes to the next visitor (any-player auto) --

def _grant_eligible(state: GameState, owner: int) -> bool:
    """The active use is Grain Utilization and this owner has a deposit owed."""
    return (state.pending_stack[-1].space_id == "grain_utilization"
            and state.players[owner].card_state.get(_OWED_KEY, 0) > 0)


def _grant_apply(state: GameState, owner: int) -> GameState:
    """Hand the deposit to the VISITOR (the host frame's player_idx — possibly
    the owner themself) and clear the owner's debt."""
    visitor = state.pending_stack[-1].player_idx
    owed = state.players[owner].card_state.get(_OWED_KEY, 0)
    players = list(state.players)
    players[owner] = fast_replace(
        players[owner], card_state=players[owner].card_state.remove(_OWED_KEY))
    players[visitor] = fast_replace(
        players[visitor],
        resources=players[visitor].resources + Resources(food=owed))
    return fast_replace(state, players=tuple(players))


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_action_space", CARD_ID, _buy_eligible, _buy_apply)
register_food_payment_resume(CARD_ID, _pay_and_bank)
register_auto("before_action_space", CARD_ID, _grant_eligible, _grant_apply,
              any_player=True)
register_scoring(CARD_ID, _score)
