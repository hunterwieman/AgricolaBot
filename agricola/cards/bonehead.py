"""Bonehead (occupation, deck D #118; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, immediately place 6 wood on it. Immediately
after each time you play a card from your hand, including this one, you get
1 wood from this card."

USER RULINGS (2026-07-14):

1. "Immediately after" = the ordinary after-window seam (same answer as Merchant
   — no distinct earlier instant). So each own play of a card from hand fires a
   payout via ``after_play_occupation`` / ``after_play_minor`` automatic effects.
2. Ruling 60 (the deferred after-flip, already built in the engine): "the wood
   from a play arrives only after the played card's FULL effect (everything its
   on_play pushed) has resolved — it can never fund that card's own effect."
   Bonehead just registers ordinary after-autos; the engine provides the
   ordering (pinned in tests/test_card_bonehead.py).
3. "Including this one": the self-payout at Bonehead's own play is handled
   INSIDE on_play — "approved as the same instant: on_play sets the store to 6
   and immediately takes 1 (net: 5 on the card, +1 wood to supply)."

MECHANICS. The wood pile lives in the per-card CardStore
(``p.card_state.get("bonehead", 0)``). on_play is one synchronous shot per
ruling 3: store <- 6, then the self-payout (store <- 5, +1 wood). The two
after-play autos (own plays only — the registries' default own-action routing)
pay 1 wood while the pile lasts: eligibility = store > 0; apply = store -1,
+1 wood. When the pile empties nothing more happens (the eligibility gate).

The self-play guard: because ruling 3 places the self-payout inside on_play, the
after_play_occupation auto must NOT fire again at Bonehead's own play's deferred
flip — under ruling 60's ordering, on_play has already run by then, so the store
is 5 (non-empty) at that instant and an unguarded auto would pay a second wood.
The auto therefore excludes the self-play by reading the play host's
``played_card_id`` stamp (the Clutterer idiom): ``played_card_id != CARD_ID``.

A TRAVELING (passing) minor counts — it was played from hand; the pass-on
doesn't matter (the after_play_minor auto fires at the play host's flip
regardless of where the card went). Opponent plays never fire: own-action autos
run only for the acting player, and the registry's ownership gate additionally
requires Bonehead in that player's tableau — a Bonehead still in HAND is inert
(no store, no payouts).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "bonehead"


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int) -> GameState:
    """Place 6 wood on the card, then the self-payout ("including this one") —
    one synchronous shot per ruling 3: net 5 on the card, +1 wood to supply."""
    p = state.players[idx]
    p = fast_replace(
        p,
        card_state=p.card_state.set(CARD_ID, 5),
        resources=p.resources + Resources(wood=1),
    )
    return _update_player(state, idx, p)


def _eligible(state: GameState, idx: int) -> bool:
    """Wood remains on the card, and the just-played card is not Bonehead itself
    (its own payout already happened inside on_play — ruling 3; without this
    guard the deferred flip would pay a second wood for the self-play)."""
    if state.players[idx].card_state.get(CARD_ID, 0) <= 0:
        return False
    played = getattr(state.pending_stack[-1], "played_card_id", None) \
        if state.pending_stack else None
    return played != CARD_ID


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    pile = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        card_state=p.card_state.set(CARD_ID, pile - 1),
        resources=p.resources + Resources(wood=1),
    )
    return _update_player(state, idx, p)


register_occupation(CARD_ID, _on_play)
register_auto("after_play_occupation", CARD_ID, _eligible, _apply)
register_auto("after_play_minor", CARD_ID, _eligible, _apply)
