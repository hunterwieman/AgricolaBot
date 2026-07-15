"""Bellfounder (occupation, D107; Consul Dirigens Expansion; Food Provider; 1+).

Card text (verbatim): "In the returning home phase of each round, if you have
at least 1 clay, you can use this card to discard all of your clay and get
your choice of 3 food or 1 bonus point."

WHAT THE CARD DOES — in the returning home phase of EVERY round (harvest
rounds included — the text says "each round", with no Silage-style
non-harvest carve-out), if the owner holds any clay they may (once) discard
ALL of it — however much — for a flat 3 food OR a flat 1 bonus point: the
payout does not scale with the clay discarded.

TIMING — the printed anchor names the phase, so the effect rides the
round-end ladder's ``returning_home`` window (user ruling 49, 2026-07-12:
"in the returning home phase" is a distinct rung of the round-end ladder;
``agricola/cards/round_end.py``, position 3). That rung fires PRE-reset —
the live board is its event data — which is harmless here: Bellfounder
reads nothing off the board.

THE CHOICE — surfaced WIDE as an optional play-variant TRIGGER (user
decision 2026-07-14: two trigger variants, not a nested choice frame): one
``FireTrigger(card_id, variant=...)`` per payout, ``"food"`` (+3 food) and
``"point"`` (+1 bonus point). Both discard all the player's clay.

THE BONUS POINT is BANKED — it is a history fact (how often the owner chose
the point payout), not derivable from the end-game board — so each
``"point"`` fire increments a counter in the per-card ``CardStore`` and the
end-game scoring term reads the bank back (the Big Country banked-VP idiom).

ONCE PER ROUND ("you can use this card" once per phase) comes free from the
window frame's ``triggers_resolved`` (one ``returning_home`` window per
round, a fresh frame each round); DECLINING is the frame's ``Proceed`` (no
SkipTrigger, the standard shape). "At least 1 clay" is the eligibility gate.

Card-game only (ownership-gated card registries; CardStore state is
card-only and default-skipped): the Family game is byte-identical and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "bellfounder"

_VARIANTS = ("food", "point")


def _variants(state: GameState, idx: int) -> list:
    """Both payouts whenever the card can fire at all ("at least 1 clay");
    neither payout has any further precondition."""
    if state.players[idx].resources.clay < 1:
        return []
    return list(_VARIANTS)


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"If you have at least 1 clay." Ownership is the window machinery's
    gate; once-per-round is the frame's `triggers_resolved`."""
    return state.players[idx].resources.clay >= 1


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """One fire: discard ALL the player's clay (however much), then the
    chosen payout — "food" grants a flat 3 food, "point" banks 1 bonus point
    in the CardStore (read back by the end-game scoring term)."""
    p = state.players[idx]
    resources = p.resources - Resources(clay=p.resources.clay)
    if variant == "food":
        p = fast_replace(p, resources=resources + Resources(food=3))
    else:
        assert variant == "point", f"bellfounder: unknown variant {variant!r}"
        p = fast_replace(
            p,
            resources=resources,
            card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
        )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _score(state: GameState, idx: int) -> int:
    # The banked bonus points (1 per round the "point" payout was chosen).
    return state.players[idx].card_state.get(CARD_ID, 0)


def _action_label(variant: str) -> str | None:
    """Web-UI label (mechanical, terse): "food" -> "discard all clay → 3
    food"; "point" -> "discard all clay → 1 bonus point"."""
    if variant == "food":
        return "discard all clay → 3 food"
    if variant == "point":
        return "discard all clay → 1 bonus point"
    return None


# No on-play effect — the card is purely its round-end trigger + scoring term.
register_occupation(CARD_ID, lambda state, idx: state)

# The optional once-per-round discard on the round-end ladder's
# returning_home window (ruling 49), variant-expanded: "food" | "point"
# (user decision 2026-07-14: the payout choice is surfaced wide).
register("returning_home", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_action_labeler(CARD_ID, _action_label)

# End-game: the banked bonus points (the Big Country banked-VP idiom).
register_scoring(CARD_ID, _score)
