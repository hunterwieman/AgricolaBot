import agricola.cards.home_brewer  # noqa: F401
# Tests for Home Brewer (occupation, C #110; Consul Dirigens Expansion).
#
# Card text (verbatim): "After the field phase of each harvest, you can use this
# card to turn exactly 1 grain into your choice of 3 food or 1 bonus point."
# Occupation. No cost / prereq. VPs: 0. Not passing.
#
# TIMING: harvest window #7 `after_field_phase` (user ruling 2026-07-03) — an
# optional play-variant trigger surfaced on the per-player PendingHarvestWindow
# host AFTER that player's crop take and BEFORE feeding. Two variants: "food"
# (1 grain -> 3 food) and "vp" (1 grain -> 1 banked bonus point). Once per
# harvest (the frame's triggers_resolved). Banked points read by the scoring
# term at end-game.
#
# Drivers mirror tests/test_harvest_windows.py: walk to the after_field_phase
# PendingHarvestWindow for the owner, then fire / decline around it.

import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.home_brewer import CARD_ID, WINDOW_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _own_occ(state, player_idx, card_id):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {card_id})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, grain=0, food=0, owned=True, owner=0) -> GameState:
    """A HARVEST_FIELD-phase state with `owner` (optionally) owning Home Brewer,
    given grain/food, the other player well-fed. No fields are sown, so the crop
    take is a no-op and the player's grain stays exactly `grain` when the
    after_field_phase window opens."""
    state = setup(seed=0)
    state = fast_replace(state, starting_player=owner)
    if owned:
        state = _own_occ(state, owner, CARD_ID)
    state = with_resources(state, owner, food=food, grain=grain)
    state = with_resources(state, 1 - owner, food=99)
    return with_phase(state, Phase.HARVEST_FIELD)


def _walk_to_window(state, *, window_id=WINDOW_ID, owner=0):
    """Drive the harvest walk (auto-applying singletons) until the top frame is a
    PendingHarvestWindow for `window_id`/`owner`, or the harvest ends. Returns the
    state at that frame (or the post-harvest state if it never appears)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id and top.player_idx == owner):
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _brewer_actions(state):
    """Sorted Home Brewer FireTrigger variants currently legal."""
    return sorted(
        a.variant for a in legal_actions(state)
        if isinstance(a, FireTrigger) and a.card_id == CARD_ID
    )


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _score_fn():
    """The registered scoring callable for Home Brewer (SCORING_TERMS is a list of
    (card_id, fn) tuples, not a dict)."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # A play-variant trigger on window #7 (not the feeding/HARVEST_CONVERSIONS seam).
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert WINDOW_ID == "after_field_phase"
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_no_longer_registered_as_harvest_conversion():
    """The legacy HARVEST_CONVERSIONS registration is removed — the card now lives
    on the after_field_phase window, not the feeding seam."""
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    assert f"{CARD_ID}_food" not in HARVEST_CONVERSIONS
    assert f"{CARD_ID}_vp" not in HARVEST_CONVERSIONS


def test_on_play_is_noop():
    """The occupation's on-play does nothing (effect is the recurring window trigger)."""
    state = setup(seed=0)
    out = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert out is state


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """Both variants offered at after_field_phase iff the player owns Home Brewer."""
    owned = _walk_to_window(_harvest_state(grain=1, food=0, owned=True))
    top = owned.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == WINDOW_ID
    assert _brewer_actions(owned) == ["food", "vp"]

    # Unowned: the window frame never appears (no eligible trigger), harvest ends.
    unowned = _walk_to_window(_harvest_state(grain=1, food=0, owned=False))
    assert not (unowned.pending_stack
                and isinstance(unowned.pending_stack[-1], PendingHarvestWindow))


def test_offered_only_when_grain_affordable():
    """Both variants need 1 grain; with 0 grain no window frame is pushed."""
    with_grain = _walk_to_window(_harvest_state(grain=1, food=0))
    assert _brewer_actions(with_grain) == ["food", "vp"]

    # 0 grain -> not eligible -> no after_field_phase frame at all.
    no_grain = _walk_to_window(_harvest_state(grain=0, food=0))
    assert not (no_grain.pending_stack
                and isinstance(no_grain.pending_stack[-1], PendingHarvestWindow))


# --- Real-flow effect -------------------------------------------------------

def test_fire_food_variant_spends_grain_adds_three_food():
    """Fire the "food" variant: spend 1 grain, gain 3 food, bank 0 points."""
    state = _walk_to_window(_harvest_state(grain=2, food=0))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))

    p = state.players[0]
    assert p.resources.grain == 1             # 2 - 1 spent
    assert p.resources.food == 3              # +3 food
    assert p.card_state.get(CARD_ID, 0) == 0  # no banked point


def test_fire_vp_variant_spends_grain_banks_one_point_no_food():
    """Fire the "vp" variant: spend 1 grain, gain 0 food, bank 1 bonus point."""
    state = _walk_to_window(_harvest_state(grain=2, food=0))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="vp"))

    p = state.players[0]
    assert p.resources.grain == 1             # 2 - 1 spent
    assert p.resources.food == 0              # vp variant gives no food
    assert p.card_state.get(CARD_ID, 0) == 1  # 1 banked point


# --- Once-per-harvest: choosing ONE output spends the use --------------------

def test_once_per_harvest_choice_food():
    """After firing one variant, no Home Brewer variant is offered again this
    window (a single use, choosing the output — not two independent fires)."""
    state = _walk_to_window(_harvest_state(grain=5, food=0))
    assert _brewer_actions(state) == ["food", "vp"]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))
    # Even though 4 grain remains, the card is spent for this harvest.
    assert _brewer_actions(state) == []
    # Only Proceed remains at the host.
    assert legal_actions(state) == [Proceed()]


def test_vp_variant_also_spends_the_use():
    """Firing the "vp" output likewise spends the once-per-harvest use."""
    state = _walk_to_window(_harvest_state(grain=5, food=0))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="vp"))
    assert _brewer_actions(state) == []


# --- Timing: the trigger is NOT offered during feeding ----------------------

def test_not_offered_during_feeding():
    """Declining at after_field_phase, the card is NOT re-offered in the feeding
    phase (it lives on window #7, before feeding — not the feeding seam)."""
    # Plenty of food so feeding never converts the grain (isolating the timing).
    state = _walk_to_window(_harvest_state(grain=2, food=10))
    # Decline the after_field_phase offer.
    state = step(state, Proceed())
    # Drive the rest of the harvest; Home Brewer is never offered again.
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        assert _brewer_actions(state) == []
        state = step(state, legal_actions(state)[0])
    # Declined: grain/points untouched.
    p = state.players[0]
    assert p.resources.grain == 2
    assert p.card_state.get(CARD_ID, 0) == 0


# --- Scoping: a fresh harvest re-enables the card ---------------------------

def test_fresh_harvest_reenables_card():
    """A new harvest opens a fresh after_field_phase frame, and the bank carries
    forward across harvests."""
    state = _walk_to_window(_harvest_state(grain=2, food=0))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="vp"))
    assert state.players[0].card_state.get(CARD_ID, 0) == 1

    # Simulate the next harvest: fresh HARVEST_FIELD state carrying the bank forward.
    banked = state.players[0].card_state.get(CARD_ID, 0)
    fresh = _harvest_state(grain=2, food=0)
    p = fresh.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, banked))
    fresh = dataclasses.replace(
        fresh, players=tuple(p if i == 0 else fresh.players[i] for i in range(2)))
    fresh = _walk_to_window(fresh)

    assert _brewer_actions(fresh) == ["food", "vp"]
    # Bank carries forward across harvests.
    assert fresh.players[0].card_state.get(CARD_ID, 0) == 1


# --- Optionality: declining leaves everything untouched ---------------------

def test_optional_decline_via_proceed():
    """The trigger is optional — Proceed at the host leaves grain/food/points
    untouched and the harvest completes."""
    state = _walk_to_window(_harvest_state(grain=2, food=10))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert p.resources.grain == 2
    assert p.card_state.get(CARD_ID, 0) == 0


def test_declining_via_full_harvest_run():
    """Running the whole harvest picking Proceed never fires Home Brewer."""
    state = _harvest_state(grain=2, food=10)

    def pick(acts):
        proceeds = [a for a in acts if isinstance(a, Proceed)]
        return proceeds[0] if proceeds else acts[0]

    state = _run_harvest(state, pick)
    p = state.players[0]
    assert p.resources.grain == 2
    assert p.card_state.get(CARD_ID, 0) == 0


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    # No bank -> 0.
    assert score_fn(state, 0) == 0
    # Bank 3 points across harvests.
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 3))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    assert score_fn(state, 0) == 3
    # Opponent (no bank) scores 0.
    assert score_fn(state, 1) == 0
