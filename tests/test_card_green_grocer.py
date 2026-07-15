import agricola.cards.green_grocer  # noqa: F401  (registers the card)

"""Tests for Green Grocer (occupation, Corbarius C103): "At the start of each
round, you can make exactly one of the following exchanges: 1 Cattle → 1
Vegetable; 1 Vegetable → 1 Cattle; 2 Sheep → 1 Vegetable; 1 Vegetable → 2
Sheep; 2 Food → 1 Grain; 1 Grain → 2 Food"

User decision (2026-07-14): surfaced WIDE — one FireTrigger variant per
affordable exchange on the preparation ladder's `start_of_round` window
(Scholar's play-variant shape). Animal gains route through
`helpers.grant_animals` (accommodation barrier); spends are direct.
"""
from agricola.actions import FireTrigger, CommitAccommodate, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingHarvestWindow, push
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_animals, with_resources

CARD_ID = "green_grocer"

ALL_VARIANTS = ("cattle_to_veg", "veg_to_cattle", "sheep2_to_veg",
                "veg_to_sheep2", "food2_to_grain", "grain_to_food2")


# ---------------------------------------------------------------------------
# Helpers (mirroring tests/test_cards_category7.py)
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _host(state, idx):
    """A WORK state with a start_of_round window choice host for `idx` on top
    (the synthetic-frame idiom: popping the frame ends the turn)."""
    return push(fast_replace(state, phase=Phase.WORK),
                PendingHarvestWindow(window_id="start_of_round", player_idx=idx))


def _offered_variants(state):
    return [a.variant for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    entries = {e.card_id: e for e in TRIGGERS.get("start_of_round", [])}
    assert CARD_ID in entries                      # subset check, never exact-set
    assert entries[CARD_ID].mandatory is False     # optional ("you can")
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# ---------------------------------------------------------------------------
# Each exchange moves exactly the printed amounts (synthetic host drive)
# ---------------------------------------------------------------------------

def test_cattle_to_veg():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0)               # no goods
    s = with_animals(s, 0, cattle=1)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="cattle_to_veg"))
    p = s.players[0]
    assert p.animals.cattle == 0
    assert p.resources.veg == 1


def test_veg_to_cattle():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, veg=1)
    s = with_animals(s, 0)                 # empty farm: 1 cattle fits as pet
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="veg_to_cattle"))
    p = s.players[0]
    assert p.resources.veg == 0
    assert p.animals.cattle == 1
    # It fits (house pet), so the barrier surfaces no keep-which choice.
    assert not any(isinstance(f, PendingAccommodate) for f in s.pending_stack)


def test_sheep2_to_veg():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0)
    s = with_animals(s, 0, sheep=2)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="sheep2_to_veg"))
    p = s.players[0]
    assert p.animals.sheep == 0
    assert p.resources.veg == 1


def test_veg_to_sheep2_overflow_surfaces_accommodation_barrier():
    # A fresh farm houses at most 1 animal (the house pet): the 2 granted sheep
    # cannot both fit, so grant_animals + the barrier must surface the
    # keep-which choice rather than silently inflating the count.
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, veg=1)
    s = with_animals(s, 0)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="veg_to_sheep2"))
    p = s.players[0]
    assert p.resources.veg == 0
    assert p.animals.sheep == 2            # transient over-capacity, pre-barrier
    assert isinstance(s.pending_stack[-1], PendingAccommodate)
    options = [a for a in legal_actions(s) if isinstance(a, CommitAccommodate)]
    assert options
    # Every offered keep-config fits the fresh farm (≤ 1 house pet).
    for a in options:
        assert a.sheep + a.boar + a.cattle <= 1


def test_food2_to_grain():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, food=2)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="food2_to_grain"))
    p = s.players[0]
    assert p.resources.food == 0
    assert p.resources.grain == 1


def test_grain_to_food2():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, grain=1)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_to_food2"))
    p = s.players[0]
    assert p.resources.grain == 0
    assert p.resources.food == 2


def test_opponent_unaffected():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, grain=1)
    before = s.players[1]
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_to_food2"))
    assert s.players[1].resources == before.resources
    assert s.players[1].animals == before.animals


# ---------------------------------------------------------------------------
# Only affordable variants offered
# ---------------------------------------------------------------------------

def test_only_affordable_variants_offered():
    # 1 veg, 1 grain, 0 food, no animals: exactly the veg routes + grain→food.
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, veg=1, grain=1)
    s = with_animals(s, 0)
    s = _host(s, 0)
    assert _offered_variants(s) == ["veg_to_cattle", "veg_to_sheep2",
                                    "grain_to_food2"]
    assert Proceed() in legal_actions(s)   # declinable


def test_all_six_offered_when_all_affordable():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, veg=1, grain=1, food=2)
    s = with_animals(s, 0, sheep=2, cattle=1)
    s = _host(s, 0)
    assert _offered_variants(s) == list(ALL_VARIANTS)


def test_not_offered_when_nothing_affordable():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, food=1)       # 1 food affords no exchange
    s = with_animals(s, 0, sheep=1)        # 1 sheep affords none either
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


def test_not_offered_when_not_owned():
    # Card in HAND only (not played) → the trigger must not surface.
    s = setup(0)
    p = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = with_resources(s, 0, grain=1)
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Optionality & "exactly one" per round
# ---------------------------------------------------------------------------

def test_declinable_via_proceed():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, grain=1)
    s = _host(s, 0)
    before = s.players[0].resources
    s = step(s, Proceed())                 # decline: no exchange happened
    assert s.players[0].resources == before
    assert s.pending_stack == ()
    assert CARD_ID not in s.players[0].used_this_round


def test_exactly_one_exchange_per_round():
    # After one fire, no second exchange is offered this round (even though
    # another exchange is still affordable).
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, grain=1, food=2)
    s = _host(s, 0)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_to_food2"))
    assert CARD_ID in s.players[0].used_this_round     # latched
    assert _offered_variants(s) == []                  # host visit: fired
    assert legal_actions(s) == [Proceed()]
    # A second host visit in the SAME round (fresh frame) is still latched out.
    s2 = step(s, Proceed())
    s2 = _host(s2, 0)
    assert legal_actions(s2) == [Proceed()]


# ---------------------------------------------------------------------------
# The REAL preparation ladder: window appears, fire resolves, next round again
# ---------------------------------------------------------------------------

def test_fires_on_real_start_of_round_window_and_reoffers_next_round():
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, grain=1)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    out = _complete_preparation(s)
    # The ladder paused at the start_of_round choice host for the owner.
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round"
    assert top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID, variant="grain_to_food2") in legal_actions(out)

    out = step(out, FireTrigger(card_id=CARD_ID, variant="grain_to_food2"))
    p = out.players[0]
    assert p.resources.grain == 0
    assert p.resources.food == 2
    assert CARD_ID in p.used_this_round
    out = step(out, Proceed())
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()

    # Next round: used_this_round clears at round entry, so the exchange is
    # offered again (2 food now affords food2_to_grain).
    nxt = fast_replace(out, phase=Phase.PREPARATION,
                       round_number=out.round_number + 1)
    nxt = _complete_preparation(nxt)
    top = nxt.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round"
    assert FireTrigger(card_id=CARD_ID, variant="food2_to_grain") in legal_actions(nxt)


def test_hand_only_inert_on_real_preparation():
    # Card in hand (never played): the ladder makes no frame and no exchange.
    s = setup(0)
    p = fast_replace(s.players[0], hand_occupations=frozenset({CARD_ID}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = with_resources(s, 0, grain=1)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    out = _complete_preparation(s)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.players[0].resources.grain == 1     # untouched
