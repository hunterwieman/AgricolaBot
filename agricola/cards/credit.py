"""Credit (minor improvement, A54; Artifex Expansion; no cost).

Card text: "When you play this card, you immediately get 5 food. At the end of
each round that does not end with a harvest, you must pay 1 food, or else take
a begging marker."
Cost: none (free). Prerequisite: "At Most 3 Occupations" (max_occupations=3).
Printed VPs: 0. Kept (not passing). Category: Food Provider.

Two pieces:

- **the on-play grant** — "you immediately get 5 food" is a mandatory pure-goods
  gain at play time: `on_play` credits +5 food, no choice, no frame.

- **the recurring debt** — "at the end of each round" is the round-end ladder's
  `end_of_round` rung (ruling 49, 2026-07-12: the returning-home phase is the
  round's LAST phase and "the end of the round" is a DISTINCT, LATER instant —
  the ladder's last window, after the return-home reset; ruling 49 names Credit
  A54 as a member of this "at the end of each round" family).

THE DEBT'S THREE CASES (USER RULING 2026-07-27, verbatim: "with 0 food, the
player should be given both options: raise-and-pay and beg. With 1+ food, they
must pay.") — the "or else" is a real payment choice only when the at-any-time
conversions could still cover the food (ruling 82: a plain food-on-hand gate
makes rules-legal moves unplayable; an earlier build auto-begged any 0-food
owner, deleting the raise-and-pay line):

1. **food >= 1** — mandatory and choice-free: pay 1 food. An automatic effect
   (`register_auto`; ruling 21, 2026-07-05: a mandatory choice-free tier is an
   AUTO, never a forced offer).
2. **food == 0 and a conversion could raise 1 food** (`_liquidatable_to`) —
   mandatory WITH a choice: the two options are raise-and-pay and
   take-the-begging-marker. The established mandatory-with-choice ladder shape
   (Childless on `start_of_round`): a `mandatory`-tagged trigger — the window
   host's Proceed is gated off until it fires — whose apply pushes a
   `PendingCardChoice(("pay", "beg"))`; the registered resolver applies the
   pick. "pay" pushes a raise-only `PendingFoodPayment` whose registered
   resume debits the 1 food (raise-then-debit, banking any overshoot); "beg"
   adds the marker and cooks nothing.
3. **food == 0 and nothing liquidatable** — mandatory and choice-free: take a
   begging marker. The same AUTO as case 1 (its apply pays when food >= 1,
   begs otherwise).

The auto and the trigger are MUTUALLY EXCLUSIVE per owner per round-end, and
the exclusion must survive the window walk's fire order (autos fire first,
then trigger eligibility is read on the post-auto state): an owner at 1 food +
1 grain pays via the auto and lands on exactly the state — 0 food, grain in
supply — that case 2 matches. So whichever surface collects the debt latches
`used_this_round` (cleared at the next round's entry, i.e. after this window)
and the trigger requires the latch unset: one debt per round-end.

THE TRIGGER'S GATE IS "DEBT UNCOLLECTED", NOT A SNAPSHOT OF CASE 2. The window
is free-ordered and other `end_of_round` effects can move food mid-window
(Baking Course's bake turns a grain into food after the auto pass already
declined to fire). A gate frozen to "food == 0 and raisable" would then read
False on the changed state and unlock the host's Proceed with the debt never
collected — a rules leak — or, flipped the other way (a trigger fired after
the goods were spent elsewhere), the beg path must still be takeable. So the
mandatory trigger stays eligible until the debt is collected (non-harvest
round + latch unset — begging is always possible, so the debt is always
collectible), and the OPTIONS are built from the state at fire time: 0 food
with a raisable conversion → the ruled two-way ("pay", "beg"); food >= 1 →
("pay",) alone (the ruling's "With 1+ food, they must pay" — a singleton
choice frame, auto-resolved by singleton-skip); 0 food and nothing raisable →
("beg",) alone. At the window's own entry the auto has already collected the
two choice-free cases and latched, so the trigger only ever SURFACES in the
ruled 0-food-raisable state; the singleton options exist solely for
mid-window flips, where the auto pass is over and this trigger is the debt's
only remaining collector.

- **the condition** — "that does not end with a harvest" is the bearer's OWN
  eligibility clause on BOTH surfaces, not a ladder concern (ruling 49: the
  condition suppresses its bearer on harvest rounds; the ladder itself runs
  unconditioned on every round). `state.round_number not in HARVEST_ROUNDS`
  (rounds 4/7/9/11/13/14 end with a harvest → no payment those rounds,
  including round 14).
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import (
    register,
    register_auto,
    register_card_choice_resolver,
)
from agricola.constants import HARVEST_ROUNDS
from agricola.legality import _liquidatable_to
from agricola.pending import PendingCardChoice, PendingFoodPayment, pop, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "credit"

_GRANT = 5  # the on-play food grant


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you immediately get 5 food." """
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=_GRANT))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _non_harvest_round(state: GameState) -> bool:
    """"...each round that does not end with a harvest" — the bearer's own
    condition (ruling 49): suppressed on the harvest rounds 4/7/9/11/13/14."""
    return state.round_number not in HARVEST_ROUNDS


def _can_raise_one(state: GameState, idx: int) -> bool:
    """Could the at-any-time conversions cover the 1-food debt right now?"""
    return _liquidatable_to(state, idx, state.players[idx], Resources(food=1))


# --- Cases 1 + 3: the choice-free AUTO (pay with food on hand / forced beg) ---

def _eligible_auto(state: GameState, idx: int) -> bool:
    """The choice-free cases only: with food on hand the payment is forced
    (USER RULING 2026-07-27: "With 1+ food, they must pay"), and with nothing
    liquidatable the marker is forced. The 0-food-but-raisable case is the
    mandatory-with-choice trigger's (below), never this auto's."""
    if not _non_harvest_round(state):
        return False
    p = state.players[idx]
    return p.resources.food >= 1 or not _can_raise_one(state, idx)


def _apply_auto(state: GameState, idx: int) -> GameState:
    """Pay 1 food when food >= 1, otherwise take 1 begging marker — and latch
    `used_this_round` so the choice trigger (whose eligibility is read on the
    POST-auto state) can never collect the same round's debt twice: paying
    down to 0 food with a crop still in supply is exactly the state the
    trigger's own gate matches."""
    p = state.players[idx]
    if p.resources.food >= 1:
        p = fast_replace(p, resources=p.resources + Resources(food=-1))
    else:
        p = fast_replace(p, begging_markers=p.begging_markers + 1)
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Case 2: 0 food + raisable — the mandatory-with-choice trigger ------------

def _eligible_choice(state: GameState, idx: int, triggers_resolved) -> bool:
    """USER RULING 2026-07-27: "with 0 food, the player should be given both
    options: raise-and-pay and beg." The gate is "this round's debt is still
    uncollected" (non-harvest round + the `used_this_round` latch unset), NOT
    a snapshot of the 0-food-raisable state: the window is free-ordered, so
    food moved by another end_of_round effect must neither unlock Proceed
    with the debt outstanding nor strand the beg path (module docstring). At
    the window's entry the auto has already collected — and latched — both
    choice-free cases, so the trigger only surfaces at 0 food + raisable."""
    p = state.players[idx]
    return _non_harvest_round(state) and CARD_ID not in p.used_this_round


def _apply_choice(state: GameState, idx: int) -> GameState:
    """The mandatory fire (the host's Proceed is gated until it happens):
    surface the pick, the Childless shape, options from the state AT FIRE
    TIME — ("pay", "beg") in the ruled 0-food-raisable state; a singleton
    forced route when a mid-window food change left only one legal line
    (food >= 1 → must pay; nothing raisable → must beg)."""
    p = state.players[idx]
    if p.resources.food >= 1:
        options = ("pay",)                    # "With 1+ food, they must pay."
    elif _can_raise_one(state, idx):
        options = ("pay", "beg")              # the ruled two-way choice
    else:
        options = ("beg",)                    # nothing to pay with
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", options=options))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    """Apply the pick, latch the round's debt as collected, and pop the choice
    frame (the resolver owns it).

    "pay": debit directly when the food is on hand, else push the raise-only
    PendingFoodPayment — its registered resume (`_pay`) debits the 1 food from
    the raised supply. "beg": one begging marker, nothing cooked."""
    state = pop(state)   # the PendingCardChoice; the window host is top again
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    if chosen == "pay":
        if state.players[idx].resources.food >= 1:
            return _pay(state, idx)
        return push(state, PendingFoodPayment(
            player_idx=idx, food_needed=1, resume_kind=CARD_ID,
            reserved=Cost(),
        ))
    p = state.players[idx]
    p = fast_replace(p, begging_markers=p.begging_markers + 1)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _pay(state: GameState, idx: int) -> GameState:
    """Debit the 1 food — the post-food-payment resume (the raise-only frame
    leaves the raised food in supply for this to debit, banking overshoot)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=-1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    max_occupations=3,          # "At Most 3 Occupations" prerequisite
    on_play=_on_play,
)
# Cases 1 + 3 — mandatory, choice-free (ruling 21): an AUTO on the ladder rung.
register_auto("end_of_round", CARD_ID, _eligible_auto, _apply_auto)
# Case 2 — mandatory WITH choice (USER RULING 2026-07-27): the Childless shape.
register("end_of_round", CARD_ID, _eligible_choice, _apply_choice, mandatory=True)
register_card_choice_resolver(CARD_ID, _resolve)
register_food_payment_resume(CARD_ID, _pay)
