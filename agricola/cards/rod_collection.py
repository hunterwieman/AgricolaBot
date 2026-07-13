"""Rod Collection (minor improvement, E38; Ephipparius Expansion; printed 1 VP;
prereq 3 Occupations).

Card text: "Each time you use 'Fishing', you can place up to 2 wood on this card,
irretrievably. During scoring, each such wood is worth 1 bonus point, except the 1st,
4th, 7th, and 10th."

Two parts:

1. A per-use OPTIONAL grant on the Fishing space. "Each time you use 'Fishing'" carries
   no "after" qualifier, so per the trigger-timing ruling it is a `before_action_space`
   trigger on the `fishing` host; Fishing is an atomic accumulation space, so
   `register_action_space_hook` is needed to host the before-phase. "You can place up to
   2 wood" is optional and a CHOICE of amount (0/1/2), so it is a COLLAPSED play-variant
   trigger (the Cottager shape): the enumerator offers `FireTrigger("rod_collection",
   variant="1")` (when >= 1 wood) and `variant="2"` (when >= 2 wood); declining is the
   host's Proceed (take the Fishing action, place no wood). The host's `triggers_resolved`
   makes it fire at most once per Fishing use, so the variant carries the whole 0..2
   choice in one fire. The wood is spent from the player's supply and banked as a running
   count in the card's CardStore ("irretrievably" = removed from play, not to the general
   supply).

2. A scoring term over the banked wood W: each wood is worth 1 point EXCEPT the 1st, 4th,
   7th, and 10th piece — read literally as exactly those four ordinal positions. So
   points = W - |{1,4,7,10} ∩ [1..W]| (e.g. W=1 -> 0, W=2 -> 1, W=3 -> 2, W=4 -> 2,
   W=7 -> 4). The printed 1 VP rides `MinorSpec.vps` separately.

Card-only state (the CardStore int) is empty in the Family game -> byte-identical, C++
gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "rod_collection"
SPACES = frozenset({"fishing"})
_EXCLUDED = (1, 4, 7, 10)   # ordinal wood positions that score no point


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The wood amounts placeable this Fishing use: '1' when >= 1 wood, '2' when >= 2.
    Both offered when affordable — placing the 1st vs 2nd wood can differ in value under
    the scoring formula, so the choice is the player's."""
    wood = state.players[idx].resources.wood
    variants: list[str] = []
    if wood >= 1:
        variants.append("1")
    if wood >= 2:
        variants.append("2")
    return variants


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each time you use Fishing" -> before_action_space on the fishing host; offered
    # only while there is wood to place (the host's triggers_resolved handles once-per-use).
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    n = int(variant)
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=n),   # spent irretrievably
        card_state=p.card_state.set(CARD_ID, banked + n),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    w = state.players[idx].card_state.get(CARD_ID, 0)
    excluded = sum(1 for k in _EXCLUDED if k <= w)
    return w - excluded


register_minor(CARD_ID, min_occupations=3, vps=1)
register("before_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)
register_scoring(CARD_ID, _score)
