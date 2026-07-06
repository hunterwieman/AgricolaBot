"""Feed Pellets (minor improvement, D84; Dulcinaria Expansion; Livestock Provider).

Card text: "When you play this card, you immediately get 1 sheep. In the feeding
phase of each harvest, you can exchange exactly 1 vegetable for 1 animal of a
type you already have."
Cost: none. Prerequisite: none. VPs: none. Not passing.

Two effects:

1. ON PLAY — "you immediately get 1 sheep": the standard decision-free on-play
   animal grant (user ruling 2026-07-06: the same on-play grant wording as
   Shepherd's Crook / Young Animal Market): `helpers.grant_animals` adds the
   sheep and flags the player, and the engine's accommodation barrier
   (engine._reconcile_accommodation, run at every decision boundary) either
   finds it room (house pet slot / pasture) or surfaces the keep-or-cook
   PendingAccommodate before the next decision.

2. IN THE FEEDING PHASE — "you can exchange exactly 1 vegetable for 1 animal of
   a type you already have": a recurring, optional, in-feeding conversion
   during HARVEST_FEED — the HarvestConversionSpec seam (Beer Keg is the
   multi-entry precedent). The which-animal choice is encoded as THREE registry
   entries (feed_pellets_sheep / feed_pellets_boar / feed_pellets_cattle),
   each:

   - input_cost 1 veg, food_out 0 (the exchange yields an animal, not food;
     the 1-veg affordability gate is the feed enumerator's `_can_afford`);
   - is_owned_fn: owns the card AND holds >= 1 of that type ("a type you
     already have", re-checked live at every enumeration) AND no
     feed_pellets_* sibling has fired yet this harvest — "exchange exactly 1
     vegetable for 1 animal" is ONCE per feeding phase TOTAL, not once per
     animal type (user ruling 2026-07-06), enforced with Beer Keg's
     cross-variant guard over `harvest_conversions_used` (which the harvest
     walk resets at each harvest's start, so every harvest gets a fresh use);
   - side_effect_fn: grant 1 animal of the type via `helpers.grant_animals` —
     the standard decision-free-grant flow (user ruling 2026-07-06: a
     mid-feeding gain that doesn't fit the farm puts PendingAccommodate ON TOP
     of the feed frame, and resolving it returns to the feed frame — the
     driver-verified composition).

   The gained animal sits in `player.animals` when the final CommitConvert
   frontier is enumerated (the feed enumerator recomputes from live state on
   every call), so it IS cookable toward this same feeding (user ruling
   2026-07-06) — automatic; the tests assert it.

Declining is implicit (commit CommitConvert without firing), per the
harvest-conversion seam's standard optionality. No variants_fn: each entry is
an ordinary single-commit conversion.

Card-only state (ownership-gated registry entries; grant_animals' flag) is
untouched in the Family game, so it stays byte-identical and the C++ gates are
unaffected. See harvest_conversions.py, beer_keg.py, shepherds_crook.py, and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.helpers import grant_animals
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "feed_pellets"

_TYPES = ("sheep", "boar", "cattle")


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately get 1 sheep (decision-free grant; the accommodation
    barrier reconciles at the next decision boundary)."""
    return grant_animals(state, idx, Animals(sheep=1))


def _make_is_owned(animal_type: str):
    """Return is_owned_fn for the feed_pellets_<animal_type> entry.

    Offered iff the player owns Feed Pellets AND holds >= 1 of `animal_type`
    ("an animal of a type you already have") AND no feed_pellets_* sibling has
    fired yet this harvest (once per feeding phase TOTAL — user ruling
    2026-07-06; the Beer Keg cross-variant guard over
    harvest_conversions_used).
    """
    def fn(state: GameState, idx: int) -> bool:
        p = state.players[idx]
        if CARD_ID not in p.minor_improvements:
            return False
        if getattr(p.animals, animal_type) < 1:
            return False
        # Once per feeding phase across all three sibling entries.
        return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)
    return fn


def _make_grant(animal_type: str):
    """Return side_effect_fn: grant 1 `animal_type` via grant_animals (add +
    flag; the barrier surfaces keep-or-cook on top of the feed frame if it
    doesn't fit)."""
    def fn(state: GameState, idx: int) -> GameState:
        return grant_animals(state, idx, Animals(**{animal_type: 1}))
    return fn


register_minor(CARD_ID, on_play=_on_play)

for _t in _TYPES:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_t}",
        input_cost=Resources(veg=1),
        food_out=0,
        is_owned_fn=_make_is_owned(_t),
        side_effect_fn=_make_grant(_t),
    ))
