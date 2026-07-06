"""Uncaring Parents (occupation, E99; Ephipparius Expansion; players 1+).

Card text (verbatim): "At the end of each harvest, if you live in a stone
house, you get 1 bonus point."

Category: Points Provider. No on-play effect — the card is a recurring,
choice-free point stream: at the end of every harvest whose moment finds the
owner living in a stone house, the owner earns 1 bonus point. Occupations carry
no play cost / prerequisite / printed VPs in the card data.

Timing — "at the end of each harvest" → harvest window #16, ``end_of_harvest``
(the same window as Winter Caretaker's buy). Under the post-breeding-timeline
ruling (2026-07-03, ``CARD_DEFERRED_PLANS.md`` → Harvest-window redesign
rulings), "at the end of each harvest" is the last moment INSIDE the harvest —
after the breeding phase and after-breeding effects, strictly before the
after-harvest window (which is outside the harvest). The effect is MANDATORY
and choice-free ("you get", no "you can"), so it is an automatic effect
(``register_auto`` on the ``end_of_harvest`` window event), fired mechanically
by the harvest walk (``_process_simple_window``) per owner, starting player
first — never surfaced as a decision.

Eligibility — "if you live in a stone house": the player's house material is
stone (``PlayerState.house_material == HouseMaterial.STONE``; all rooms share
one material — the same read scoring.py and Half-Timbered House use). The
condition is evaluated at each firing, so a player who renovates to stone
mid-game earns the point at every LATER harvest's end (and one who somehow
fired earlier keeps points already earned — the point, once received, is not
conditional on staying stone). House material can only change in the WORK
phase (renovation), never mid-harvest, so the read moment inside the harvest
is unambiguous.

The point cannot be granted immediately (there is no immediate-VP mechanism),
so each fire increments a per-card ``CardStore`` counter — 1 per harvest, up
to 6 across the game's six harvests — and the scoring term reads the count
back at end-game (the Elephantgrass Plant / Big Country banked-bonus-point
idiom). The points are earned during play, not printed keep-VPs, and the card
carries no "you can only use one card ..." exclusivity clause, so it is a
plain ``register_scoring`` term, not a scoring-group member.

A harvest-skipping player (Layabout, when it lands) never reaches the window:
skip guards suppress simple windows generically (``window_skipped`` runs
before the window's autos), so no card-side handling is needed.

Card-only machinery throughout (occupation registry, harvest-window auto,
CardStore, scoring term): the Family game never owns the card, so it stays
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import HouseMaterial
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "uncaring_parents"


def _eligible(state: GameState, idx: int) -> bool:
    """"If you live in a stone house" — read at the end_of_harvest moment.

    Ownership is gated by ``apply_auto_effects`` itself (the auto only fires
    for a player who has PLAYED the card), so only the printed condition
    lives here.
    """
    return state.players[idx].house_material == HouseMaterial.STONE


def _bank(state: GameState, idx: int) -> GameState:
    """Bank 1 bonus point (the CardStore counter; scored at end-game)."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect

# The recurring end-of-harvest point: a mandatory, choice-free AUTO on window
# #16 (the last in-harvest moment — post-breeding-timeline ruling 2026-07-03).
register_auto("end_of_harvest", CARD_ID, _eligible, _bank)
register_harvest_window_hook(CARD_ID, "end_of_harvest")

register_scoring(CARD_ID, _score)
