"""`after_feeding` must not read as being inside the feeding phase.

`Phase.HARVEST_FEED` is a **band** label: the walk stamps it across the whole FEED
band, `start_of_feeding` -> `feeding` -> `after_feeding`. Three cards read it as a
**phase** label to scope themselves to their printed "in the feeding phase"
timing -- Schnapps Distiller (C109), Schnapps Distillery (C59) and Studio (C55)
all gate `is_owned_fn` on `state.phase is Phase.HARVEST_FEED`.

At the `after_feeding` rung those guards are one rung too wide, which re-opens the
food-laundering line Farm Store's printed "After the feeding phase" wording exists
to forbid (CARD_AUTHORING_GUIDE.md sec 2, "'After the feeding phase' is NOT
'during feeding' -- a conversion must not feed itself"):

    Farm Store            1 food      -> 1 vegetable   (printed: after the feeding phase)
    Schnapps Distiller    1 vegetable -> 5 food        (printed: in the feeding phase)

Both fire at the same rung, so 1 food becomes 5 -- +4 per harvest. The user's
ruling 85 companion rule is explicit that a raise-frame bundle may fire a
converter only inside that converter's OWN printed window ("Schnapps Distillery:
feeding phase only"); the band label is what breaks it.

The fix is a distinct `Phase` member for the `after_feeding` rung, mirroring the
tail members `END_OF_HARVEST` / `AFTER_HARVEST` (added for exactly this defect
class: labelling the post-span tail `HARVEST_BREED` "was misleading state").

Both tests below are expected to FAIL until that lands.
"""
import dataclasses

import agricola.cards.basket_carrier  # noqa: F401  (import triggers registration)
import agricola.cards.farm_store  # noqa: F401
import agricola.cards.schnapps_distiller  # noqa: F401
import agricola.cards.schnapps_distillery  # noqa: F401
import agricola.cards.studio  # noqa: F401

from agricola.actions import CommitConvert, FireTrigger
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.constants import GameMode, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow, PendingReveal
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import with_minors, with_phase, with_resources

WINDOW_ID = "after_feeding"
FARM_STORE = "farm_store"
BASKET_CARRIER = "basket_carrier"
SCHNAPPS = "schnapps_distiller"

# The three cards whose printed text says "in the feeding phase" and which scope
# themselves on the band label.
PHASE_GATED_CONVERSIONS = ("schnapps_distiller", "schnapps_distillery",
                           "studio_wood", "studio_clay", "studio_stone")


def _with_occupations(state, idx, card_ids):
    p = state.players[idx]
    p = dataclasses.replace(p, occupations=p.occupations | set(card_ids))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _state(owner=0, food=5):
    """A HARVEST_FIELD state where `owner` holds Farm Store, Basket Carrier and
    Schnapps Distiller, and both players hold `food` food.

    Deliberately NO cooking improvement: with base rates of 0 a vegetable is
    worthless as fuel, so the only route from a vegetable to food is Schnapps.
    That is what makes test B a clean probe of the phase gate.

    5 food covers the 4-food feeding requirement (2 adults) and leaves exactly 1
    -- enough for Farm Store's 1-food exchange, short of Basket Carrier's 2-food
    fee, which is what forces the raise frame.
    """
    state = with_phase(setup(0), Phase.HARVEST_FIELD)
    # Cards mode is required, not cosmetic: the walk's honest-phase branches are
    # gated on GameMode.CARDS (the Family walk keeps its byte-identical sequence
    # for the C++ twin), so a Family-mode state could never observe the fix.
    state = fast_replace(state, starting_player=owner, mode=GameMode.CARDS)
    state = with_minors(state, owner, frozenset({FARM_STORE}))
    state = _with_occupations(state, owner, (BASKET_CARRIER, SCHNAPPS))
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _drive_to_after_feeding(state, owner=0, limit=400):
    """Walk the harvest until `owner`'s `after_feeding` window frame is on top.

    Two rules, both load-bearing:

    * **Never fire a trigger on the way in.** Basket Carrier is a free-span
      carrier, so it is offered at every in-span surface -- the FIELD
      during-window (`PendingFieldPhase`) and the simple windows alike. Taking it
      early spends both the 2 food and its shared once-per-harvest budget before
      the rung under test.
    * **Take `CommitConvert` at a payment frame**, so the feeding resolves rather
      than routing through a conversion.

    Frame-driven, never phase-driven: once the fix lands this rung no longer
    carries `Phase.HARVEST_FEED`, so a phase-gated loop would walk past it. For
    the same reason the bail-out is frame-shaped -- reaching a reveal or an empty
    stack means the harvest ended without the window, and wandering into a later
    harvest would let the test pass on a state it never set up.
    """
    state = _advance_until_decision(state)
    for _ in range(limit):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == WINDOW_ID and top.player_idx == owner):
            return state
        if top is None or isinstance(top, PendingReveal):
            raise AssertionError(
                f"harvest ended without player {owner}'s {WINDOW_ID} window "
                f"(reached {type(top).__name__})")
        acts = legal_actions(state)
        if not acts:
            break
        pool = [a for a in acts if not isinstance(a, FireTrigger)] or acts
        pick = pool[0]
        if isinstance(top, PendingHarvestFeed):
            converts = [a for a in pool if isinstance(a, CommitConvert)]
            if converts:
                pick = converts[0]
        state = step(state, pick)
    raise AssertionError(f"never reached player {owner}'s {WINDOW_ID} window")


# ---------------------------------------------------------------------------
# A. The direct probe: the feeding-phase converters are off at after_feeding
# ---------------------------------------------------------------------------

def test_feeding_phase_converters_are_disabled_at_after_feeding():
    """A converter printed "in the feeding phase" must not be owned-and-usable at
    the `after_feeding` rung -- that rung is after the feeding phase by its own
    name, and by the printed text of the two cards that occupy it."""
    state = _drive_to_after_feeding(_state())
    for conversion_id in PHASE_GATED_CONVERSIONS:
        spec = HARVEST_CONVERSIONS[conversion_id]
        assert not spec.is_owned_fn(state, 0), (
            f"{conversion_id} is still enabled at {WINDOW_ID} "
            f"(phase={state.phase.name}) -- its printed timing is the feeding "
            f"phase, which has ended by this rung")


# ---------------------------------------------------------------------------
# B. The end-to-end line: Farm Store's vegetable must not become food
# ---------------------------------------------------------------------------

def test_farm_store_vegetable_cannot_fund_a_same_rung_fee():
    """Fire Farm Store for a vegetable, then check Basket Carrier's 2-food fee is
    NOT raisable from it.

    With no cooking improvement the vegetable has no base conversion, so Basket
    Carrier's liquidation-aware gate can only clear if Schnapps is (wrongly)
    still enabled. Its absence from the legal set is therefore exactly the
    assertion that the laundering line is closed.
    """
    state = _drive_to_after_feeding(_state())
    p = state.players[0]
    assert p.resources.food == 1, "setup should leave exactly 1 food after feeding"
    assert p.resources.veg == 0

    veg_fire = [a for a in legal_actions(state)
                if isinstance(a, FireTrigger)
                and a.card_id == FARM_STORE and a.variant == "veg"]
    assert veg_fire, "Farm Store's vegetable variant should be offered here"
    state = step(state, veg_fire[0])

    p = state.players[0]
    assert (p.resources.food, p.resources.veg) == (0, 1)

    basket = [a for a in legal_actions(state)
              if isinstance(a, FireTrigger) and a.card_id == BASKET_CARRIER]
    assert not basket, (
        "Basket Carrier's 2-food fee was raisable at after_feeding from the "
        "vegetable Farm Store just produced -- the feeding-phase converters are "
        "still enabled one rung too late (1 food -> 1 veg -> 5 food)")
