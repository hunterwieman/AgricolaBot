"""Tests for Feed Pellets (minor improvement, D84; Dulcinaria Expansion).

Card text: "When you play this card, you immediately get 1 sheep. In the
feeding phase of each harvest, you can exchange exactly 1 vegetable for 1
animal of a type you already have." No cost, no prerequisite, no printed VPs.

Coverage:
- registration: the minor spec (free, no prereq, on_play set) + THREE
  HarvestConversionSpec entries (sheep/boar/cattle), each 1 veg -> 0 food +
  a grant-1-animal side effect, no variants.
- on play: 1 sheep via the standard decision-free grant — fits the free house
  pet slot on the start farm (no frame); with a pre-existing house pet the
  keep-or-cook PendingAccommodate surfaces and resolves (real play-minor flow).
- at a real HARVEST_FEED frame (driven from Phase.HARVEST_FIELD so the walk's
  once-per-harvest budget reset runs): the exchange is offered only for types
  the player already has; firing debits 1 veg and grants the animal (no frame
  with pasture room; PendingAccommodate ON TOP of the feed frame without room,
  returning to the feed frame when resolved — the driver-verified composition);
  once per feeding phase TOTAL (sibling suppression + no re-offer); the gained
  animal is cookable toward the same feeding (Fireplace rates); negative cases
  (no veg / no animals / unowned); a fresh use next harvest.
"""
import agricola.cards.feed_pellets  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import (
    CommitAccommodate,
    CommitConvert,
    CommitHarvestConversion,
)
from agricola.cards.feed_pellets import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingAccommodate,
    PendingHarvestFeed,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import (
    with_animals,
    with_majors,
    with_minors,
    with_pending_stack,
    with_phase,
    with_resources,
)
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_pasture_1x1(state, player_idx, row=0, col=0):
    """Add a 1x1 pasture enclosed at (row, col) — capacity 2, so a granted
    second animal of a held type has room (plus the house pet slot)."""
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    new_pastures = compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v)
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid, horizontal_fences=new_h,
        vertical_fences=new_v, pastures=new_pastures))


def _feed_state(*, veg=0, food=10, sheep=0, boar=0, cattle=0,
                owned=True, pasture=False, fireplace=False):
    """Drive from Phase.HARVEST_FIELD into P0's HARVEST_FEED frame (the walk
    must ENTER the harvest itself so the once-per-harvest conversion budget
    reset runs). P1 is food-rich so only P0's frame is interesting; P0 is the
    starting player, so their feed frame is on top."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    if pasture:
        state = _set_pasture_1x1(state, 0)
    if fireplace:
        state = with_majors(state, owner_by_idx={0: 0})  # P0 gets a Fireplace
    state = with_resources(state, 0, veg=veg, food=food)
    state = with_resources(state, 1, food=99)
    if sheep or boar or cattle:
        state = with_animals(state, 0, sheep=sheep, boar=boar, cattle=cattle)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed) and top.player_idx == 0
    return state


def _offered(state):
    """The feed_pellets_* conversion ids currently offered, sorted."""
    return sorted(
        a.conversion_id for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion)
        and a.conversion_id.startswith(CARD_ID))


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    # Printed cost: none. Prerequisite: none. VPs: none. Not passing.
    assert spec.cost == Cost()
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.passing_left is False
    assert prereq_met(spec, setup(0), 0)
    assert prereq_met(spec, setup(0), 1)
    # Three conversion entries, one per animal type — 1 veg in, 0 food out,
    # an animal-granting side effect, no variants.
    for t in ("sheep", "boar", "cattle"):
        cid = f"{CARD_ID}_{t}"
        assert cid in HARVEST_CONVERSIONS
        cspec = HARVEST_CONVERSIONS[cid]
        assert cspec.input_cost == Resources(veg=1)
        assert cspec.food_out == 0
        assert cspec.side_effect_fn is not None
        assert cspec.variants_fn is None


# --- On play: 1 sheep -------------------------------------------------------

def test_on_play_grants_one_sheep_and_flags():
    s = setup(0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].animals.sheep == s.players[0].animals.sheep + 1
    # The standard decision-free grant: flagged for the accommodation barrier.
    assert out.players[0].animals_need_accommodation is True
    # Opponent untouched.
    assert out.players[1] == s.players[1]


def test_on_play_real_flow_sheep_fits_house_pet():
    """Play via the real play-minor flow on a fresh farm: the sheep takes the
    free house pet slot, so no keep-or-cook frame surfaces."""
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _edit_player(cs, cp, hand_minors=frozenset({CARD_ID}))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))

    out = step(cs, sole_play_minor(cs, CARD_ID))

    assert out.players[cp].animals.sheep == 1
    assert CARD_ID in out.players[cp].minor_improvements   # kept, not traveling
    assert out.players[cp].animals_need_accommodation is False  # barrier ran
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


def test_on_play_over_capacity_surfaces_keep_or_cook():
    """With a pre-existing house pet (1 boar, no pastures), the granted sheep
    is a second animal for one flexible slot: the keep-or-cook frame surfaces,
    and resolving it keeps the chosen animal."""
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = with_animals(cs, cp, boar=1)   # occupies the house pet slot
    cs = _edit_player(cs, cp, hand_minors=frozenset({CARD_ID}))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))

    out = step(cs, sole_play_minor(cs, CARD_ID))

    top = out.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == cp
    acts = legal_actions(out)
    assert acts and all(isinstance(a, CommitAccommodate) for a in acts)
    # Keep the sheep; the boar is released (no cooking improvement -> 0 food).
    keep_sheep = next(a for a in acts if a.sheep == 1 and a.boar == 0)
    out = step(out, keep_sheep)
    assert out.players[cp].animals == Animals(sheep=1)
    assert not any(isinstance(f, PendingAccommodate) for f in out.pending_stack)


# --- The feed-phase exchange: offering --------------------------------------

def test_offered_only_for_types_already_held():
    """'an animal of a type you already have' — only owned types' entries."""
    assert _offered(_feed_state(veg=1, sheep=1)) == ["feed_pellets_sheep"]
    assert _offered(_feed_state(veg=1, sheep=1, boar=1)) == [
        "feed_pellets_boar", "feed_pellets_sheep"]
    assert _offered(_feed_state(veg=1, cattle=1)) == ["feed_pellets_cattle"]


def test_not_offered_without_veg():
    assert _offered(_feed_state(veg=0, sheep=1)) == []


def test_not_offered_with_no_animals():
    assert _offered(_feed_state(veg=1)) == []


def test_not_offered_when_unowned():
    assert _offered(_feed_state(veg=1, sheep=1, owned=False)) == []


# --- Firing: debit + grant --------------------------------------------------

def test_fire_debits_veg_and_grants_animal_with_room():
    """With pasture room the granted sheep just fits: no accommodate frame,
    back at the feed frame."""
    state = _feed_state(veg=1, sheep=1, pasture=True)
    state = step(state, CommitHarvestConversion(conversion_id="feed_pellets_sheep"))

    p = state.players[0]
    assert p.resources.veg == 0
    assert p.animals.sheep == 2
    assert p.resources.food == 10          # food_out == 0: no food from the fire
    assert "feed_pellets_sheep" in p.harvest_conversions_used
    assert p.animals_need_accommodation is False
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed) and top.player_idx == 0


def test_fire_without_room_stacks_accommodate_on_feed_frame():
    """No pasture: the held sheep is the house pet, so the granted second sheep
    doesn't fit — PendingAccommodate surfaces ON TOP of the feed frame, and
    resolving it returns to the feed frame (the driver-verified composition)."""
    state = _feed_state(veg=1, sheep=1)
    state = step(state, CommitHarvestConversion(conversion_id="feed_pellets_sheep"))

    top = state.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    below = state.pending_stack[-2]
    assert isinstance(below, PendingHarvestFeed) and below.player_idx == 0

    acts = legal_actions(state)
    assert acts and all(isinstance(a, CommitAccommodate) for a in acts)
    keep = max(acts, key=lambda a: a.sheep)     # keep as many sheep as housable
    state = step(state, keep)
    assert state.players[0].animals.sheep == 1  # 1 housable (house pet slot)
    # Back at the feed frame; the feed is still completable.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed) and top.player_idx == 0
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))


def test_gained_animal_cookable_toward_same_feeding():
    """The granted animal is in the player's supply when the final payment
    frontier is enumerated, so it can be cooked toward THIS feeding: 0 food,
    need 4, Fireplace (sheep -> 2 food) — after the exchange, consuming both
    sheep covers the feeding with no begging."""
    state = _feed_state(veg=1, food=0, sheep=1, pasture=True, fireplace=True)
    state = step(state, CommitHarvestConversion(conversion_id="feed_pellets_sheep"))

    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed) and top.player_idx == 0
    converts = [a for a in legal_actions(state) if isinstance(a, CommitConvert)]
    both_sheep = next(a for a in converts if a.sheep == 2)   # the gained one too
    state = step(state, both_sheep)
    p = state.players[0]
    assert p.animals.sheep == 0
    assert p.begging_markers == 0          # 2 sheep x 2 food == the 4-food need
    assert p.resources.food == 0           # nothing left over


# --- Once per feeding phase TOTAL --------------------------------------------

def test_once_per_feeding_total_sibling_suppression():
    """'exchange exactly 1 vegetable for 1 animal' is once per feeding phase
    TOTAL: firing one type suppresses all three entries for the rest of the
    harvest, even with veg left and both types still held."""
    state = _feed_state(veg=2, sheep=1, boar=1, pasture=True)
    assert _offered(state) == ["feed_pellets_boar", "feed_pellets_sheep"]

    state = step(state, CommitHarvestConversion(conversion_id="feed_pellets_boar"))
    p = state.players[0]
    assert p.animals.boar == 2 and p.animals.sheep == 1
    assert p.resources.veg == 1            # veg remains, but the use is spent
    assert _offered(state) == []           # no siblings, no re-offer


def test_optional_decline_leaves_everything_untouched():
    """Declining is implicit: committing the feed without firing spends no veg
    and records no use."""
    state = _feed_state(veg=1, sheep=1)
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.veg == 1
    assert p.animals.sheep == 1
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)


def test_next_harvest_offers_again():
    """The once-per-feeding budget resets at the next harvest's start: after
    firing in one harvest, a fresh harvest offers the exchange again."""
    state = _feed_state(veg=2, sheep=1, pasture=True)
    state = step(state, CommitHarvestConversion(conversion_id="feed_pellets_sheep"))
    assert _offered(state) == []           # spent for this harvest

    # Enter the next harvest: the walk's fresh-start reset clears the budget.
    state = with_pending_stack(state, ())
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed) and top.player_idx == 0
    assert _offered(state) == ["feed_pellets_sheep"]
