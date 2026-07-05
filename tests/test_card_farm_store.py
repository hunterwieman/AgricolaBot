"""Tests for Farm Store (minor improvement, C41; Consul Dirigens Expansion).

Card text (verbatim, from agricola/cards/data/revised_minor_improvements.json):
"After the feeding phase of each harvest, you can exchange exactly 1 food for 2
different building resources of your choice or 1 vegetable."
Cost: 2 Wood, 2 Clay. VPs: 0 (printed blank). No prereq. Not passing.

Implemented as an OPTIONAL PLAY-VARIANT TRIGGER on harvest window #11
``after_feeding`` (the ladder window that resolves after the feeding phase's
payment frames; design of record HARVEST_WINDOWS_DESIGN.md §1 row 11 names this
card). Seven output variants (the six distinct building-resource pairs over
{wood, clay, reed, stone} + the single-veg option); firing one spends exactly 1
food and grants that output, once per harvest (the frame's ``triggers_resolved``).

These tests drive REAL harvests through the walk (mirroring
tests/test_harvest_windows.py's EOH-trigger tests), reaching the per-player
``PendingHarvestWindow`` for ``after_feeding``.
"""
import agricola.cards.farm_store  # noqa: F401  (import triggers registration)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.farm_store import CARD_ID, WINDOW_ID, _OUTPUTS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_minors, with_phase, with_resources, with_sown_fields


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def _harvest_state(seed=0, food=10, owner=0, sp=0) -> GameState:
    """A HARVEST_FIELD-phase state where `owner` holds Farm Store and both players
    have `food` food (so feeding is painless). SP is `sp`."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=sp)
    state = with_minors(state, owner, frozenset({CARD_ID}))
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _walk_to_after_feeding(state, owner=0):
    """Advance the harvest until `owner`'s after_feeding PendingHarvestWindow is
    on top, always taking the first legal action for any other decision. Returns
    the state paused at that frame (or the terminal state if it never appears)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == WINDOW_ID and top.player_idx == owner):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _fire_triggers(acts):
    return sorted(a.variant for a in acts
                  if isinstance(a, FireTrigger) and a.card_id == CARD_ID)


_EXPECTED_VARIANTS = sorted(_OUTPUTS)


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON)
# ---------------------------------------------------------------------------

def test_registration_spec_matches_json():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=2, clay=2)
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None
    assert spec.min_occupations == 0 and spec.max_occupations is None


def test_registered_as_after_feeding_trigger():
    """Optional trigger (declinable) on window #11, with a play-variant enumerator
    — NOT an automatic effect (the text is "you can")."""
    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID == "after_feeding"
    assert entry.mandatory is False
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


def test_seven_distinct_building_pairs_plus_veg():
    """"2 DIFFERENT building resources" -> six distinct unordered pairs over
    {wood, clay, reed, stone}; plus the single-veg option = seven variants."""
    assert len(_OUTPUTS) == 7
    building = {"wood", "clay", "reed", "stone"}
    pairs = set()
    for tag, out in _OUTPUTS.items():
        nonzero = [n for n in building if getattr(out, n) > 0]
        if tag == "veg":
            assert out == Resources(veg=1)
            continue
        # Exactly two DISTINCT building resources, one unit each, nothing else.
        assert len(nonzero) == 2
        assert all(getattr(out, n) == 1 for n in nonzero)
        assert out.veg == 0 and out.grain == 0 and out.food == 0
        pairs.add(frozenset(nonzero))
    # Six distinct pairs = C(4, 2).
    assert len(pairs) == 6


# ---------------------------------------------------------------------------
# Offering at the after_feeding window
# ---------------------------------------------------------------------------

def test_all_seven_variants_offered_when_owned_and_food():
    state = _walk_to_after_feeding(_harvest_state(food=10, owner=0), owner=0)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "after_feeding" and top.player_idx == 0
    acts = legal_actions(state)
    assert _fire_triggers(acts) == _EXPECTED_VARIANTS
    assert Proceed() in acts                    # declinable ("you can")


def test_not_offered_to_non_owner():
    """The opponent (who does not own Farm Store) never sees the exchange: no
    after_feeding PendingHarvestWindow for player 1, so the walk runs to term."""
    state = _harvest_state(food=10, owner=0)
    end = _walk_to_after_feeding(state, owner=1)   # ask for player 1's frame
    assert end.phase == Phase.PREPARATION          # never appeared


# ---------------------------------------------------------------------------
# Firing: building pairs and the veg variant
# ---------------------------------------------------------------------------

def test_fire_building_pair_spends_food_grants_two_resources():
    state = _walk_to_after_feeding(_harvest_state(food=10, owner=0), owner=0)
    before = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID, variant="wood_stone"))
    r = state.players[0].resources
    assert r.food == before.food - 1
    assert r.wood == before.wood + 1
    assert r.stone == before.stone + 1
    assert r.clay == before.clay and r.reed == before.reed  # the other pair untouched
    assert r.veg == before.veg


def test_fire_veg_variant_spends_food_grants_vegetable():
    state = _walk_to_after_feeding(_harvest_state(food=10, owner=0), owner=0)
    before = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID, variant="veg"))
    r = state.players[0].resources
    assert r.food == before.food - 1
    assert r.veg == before.veg + 1
    # No building resource on the veg variant.
    assert (r.wood, r.clay, r.reed, r.stone) == (
        before.wood, before.clay, before.reed, before.stone)


# ---------------------------------------------------------------------------
# Once per harvest: firing one variant spends the card for this harvest
# ---------------------------------------------------------------------------

def test_once_per_harvest_choice():
    """A single exchange per harvest, choosing the output — not seven fires.
    After firing, only Proceed remains even with food to spare."""
    state = _walk_to_after_feeding(_harvest_state(food=10, owner=0), owner=0)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="clay_reed"))
    acts = legal_actions(state)
    assert _fire_triggers(acts) == []            # the card is spent this harvest
    assert legal_actions(state) == [Proceed()]


# ---------------------------------------------------------------------------
# Affordability: exactly 1 food needed
# ---------------------------------------------------------------------------

def test_not_offered_without_a_spare_food():
    """The exchange needs >= 1 food to spare AFTER feeding. At default setup each
    player has 2 adults (feeding cost 4 food). With exactly 4 food, feeding leaves
    0 spare, so the after_feeding trigger is never eligible and its window frame is
    never even pushed (the eligibility gate `owns_window_card` + `_eligible` is
    False) — the harvest runs to completion with no exchange offered. With 5 food,
    1 survives and the exchange IS offered (the positive contrast)."""
    # Exactly enough to feed (4) -> 0 spare -> never offered.
    end = _walk_to_after_feeding(_harvest_state(food=4, owner=0), owner=0)
    assert end.phase == Phase.PREPARATION           # frame never appeared
    assert end.players[0].resources.food == 0       # feeding consumed it all

    # One to spare (5) -> offered.
    state = _walk_to_after_feeding(_harvest_state(food=5, owner=0), owner=0)
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert state.players[0].resources.food == 1
    assert _fire_triggers(legal_actions(state)) == _EXPECTED_VARIANTS


# ---------------------------------------------------------------------------
# Optionality: declining grants nothing
# ---------------------------------------------------------------------------

def test_decline_via_proceed_grants_nothing():
    state = _walk_to_after_feeding(_harvest_state(food=10, owner=0), owner=0)
    before = state.players[0].resources
    state = step(state, Proceed())
    r = state.players[0].resources
    # No goods gained; food unchanged by the (declined) exchange.
    assert r == before


# ---------------------------------------------------------------------------
# Timing: fires AFTER feeding resolves, not during the field phase or feeding
# ---------------------------------------------------------------------------

def test_fires_only_at_after_feeding_and_after_payment_resolves():
    """Pin the timing. The exchange is offered ONLY at the after_feeding window
    frame, and ONLY once the feeding-payment frames (PendingHarvestFeed) have
    fully resolved — never during the field phase (HARVEST_FIELD) and never while
    a feeding-payment decision is still live on the stack.

    (The coarse ``state.phase`` enum still reads HARVEST_FEED at the after_feeding
    window — it only flips to HARVEST_BREED at the breeding sentinel, ladder #13 —
    so the load-bearing timing signal is the window position + the absence of any
    PendingHarvestFeed frame, not the phase enum; see engine._advance_harvest.)"""
    state = with_sown_fields(_harvest_state(food=10, owner=0), 0,
                             grain_fields=((0, 1), (0, 2)))
    state = _advance_until_decision(state)
    saw_frame = False
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        stack = state.pending_stack
        top = stack[-1] if stack else None
        variants = _fire_triggers(legal_actions(state))
        if variants:
            # Whenever the exchange is offered it must be at the after_feeding
            # frame, never during the field phase, and never while any feeding
            # payment is still pending.
            assert isinstance(top, PendingHarvestWindow)
            assert top.window_id == "after_feeding"
            assert state.phase != Phase.HARVEST_FIELD
            assert not any(isinstance(f, PendingHarvestFeed) for f in stack)
            saw_frame = True
        state = step(state, legal_actions(state)[0])
    assert saw_frame                              # the exchange WAS offered once


def test_effect_reads_post_payment_food():
    """The exchange spends food that survived the feeding payment. With just enough
    food to feed and one to spare, exactly the 1 spare food funds the exchange —
    proving the effect runs on the post-payment state, not before feeding."""
    # 2 people * 2 food = 4 needed; give 5 so exactly 1 survives feeding.
    state = _harvest_state(food=5, owner=0)
    state = _walk_to_after_feeding(state, owner=0)
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    # Post-feeding food is the surplus above the feeding cost.
    surplus = state.players[0].resources.food
    assert surplus >= 1                            # the spare food is available
    state = step(state, FireTrigger(card_id=CARD_ID, variant="reed_stone"))
    assert state.players[0].resources.food == surplus - 1


# ---------------------------------------------------------------------------
# On-play: no immediate effect (the card's whole effect is the recurring exchange)
# ---------------------------------------------------------------------------

def test_on_play_is_a_noop():
    """Farm Store has no on-play clause (its spec on_play is the default no-op):
    playing it grants nothing immediately; the effect is the recurring exchange."""
    state = setup(0)
    before = state.players[0].resources
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources == before
