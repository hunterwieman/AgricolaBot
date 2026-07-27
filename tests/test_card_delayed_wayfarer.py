"""Tests for Delayed Wayfarer (occupation, E125).

Card text (verbatim): "When you play this card, you immediately get 1 building resource
of your choice and, once all people have been placed this round, you can place a person
from your supply."

The last buildable supply-loaner card. Rulings (2026-07-26): the loaner clause is
ONE-SHOT (the round the card is played only), its instant is the shared
all-players-placed boundary (every player's workers, not just the owner's — contrast
Telegram), and the granted placement happens INSIDE the work phase, before the
`end_of_work` rung — pinned here via Iron Hoe, whose "occupy both 'Grain Seeds' and
'Vegetable Seeds'" condition the bonus worker can complete.
"""
import agricola.cards  # noqa: F401  -- registers the card (and everything else)

from agricola.actions import CommitCardChoice, PlaceWorker, FireTrigger
from agricola.cards.delayed_wayfarer import (
    CARD_ID,
    DECLINE,
    TAKE,
    _OFFER_OPTIONS,
    _RESOURCE_OPTIONS,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.turn_offers import TURN_START_OFFERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_people, with_round, with_space

_POOL = CardPool(
    occupations=(CARD_ID, "iron_hoe_dummy") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_TAKE_IDX = _OFFER_OPTIONS.index(TAKE)
_DECLINE_IDX = _OFFER_OPTIONS.index(DECLINE)


def _p0(state):
    return state.players[0]


def _offer_up(state) -> bool:
    return (bool(state.pending_stack)
            and isinstance(state.pending_stack[-1], PendingCardChoice)
            and state.pending_stack[-1].initiated_by_id == f"card:{CARD_ID}")


def _base(*, seed=11):
    s, _env = setup_env(seed, card_pool=_POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    p1 = fast_replace(s.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    return fast_replace(s, players=(p0, p1))


def _owning(state, *, played_round, own_home=0, opp_home=0, supply=1, total=3,
            extra_occupations=frozenset()):
    """P0 owns Delayed Wayfarer, played in `played_round` (CardStore record)."""
    p = state.players[0]
    p = fast_replace(p,
                     occupations=p.occupations | {CARD_ID} | extra_occupations,
                     card_state=p.card_state.set(CARD_ID, played_round))
    state = fast_replace(state, players=(p, state.players[1]))
    state = with_people(state, 0, total=total, home=own_home, supply=supply)
    return with_people(state, 1, total=2, home=opp_home)


def _at_boundary(*, played_round=4, **kw):
    """Round `played_round`, every worker placed — the all-players-placed boundary."""
    s = with_round(_base(), played_round)
    return _advance_until_decision(_owning(s, played_round=played_round, **kw))


# ---------------------------------------------------------------------------
# Registration + the on-play resource choice
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in TURN_START_OFFERS


def test_on_play_offers_the_four_building_resources_and_records_the_round():
    s = with_round(_base(), 3)
    s = OCCUPATIONS[CARD_ID].on_play(s, 0)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == _RESOURCE_OPTIONS
    assert _p0(s).card_state.get(CARD_ID) == 3
    for i, kind in enumerate(_RESOURCE_OPTIONS):
        before = getattr(_p0(s).resources, kind)
        out = step(s, CommitCardChoice(index=i))
        assert getattr(_p0(out).resources, kind) == before + 1
        assert not out.pending_stack or not isinstance(
            out.pending_stack[-1], PendingCardChoice)


# ---------------------------------------------------------------------------
# The offer: the shared all-players-placed boundary, one-shot
# ---------------------------------------------------------------------------

def test_offer_surfaces_once_all_players_have_placed():
    s = _at_boundary(played_round=4)
    assert _offer_up(s)
    assert legal_actions(s) == [CommitCardChoice(index=_TAKE_IDX),
                                CommitCardChoice(index=_DECLINE_IDX)]
    assert s.phase is Phase.WORK and s.round_number == 4   # the phase waited


def test_not_offered_while_the_opponent_still_has_workers():
    """The instant is EVERY player's workers placed — the owner being done is not
    enough (that is Telegram's instant, not this card's)."""
    s = _at_boundary(played_round=4, opp_home=1)
    assert not _offer_up(s)


def test_not_offered_in_a_later_round():
    """One-shot: 'this round' is the round the card was played."""
    s = _at_boundary(played_round=3)          # played round 3, boundary reached round 3?
    assert _offer_up(s)                       # ...its own round: offered
    s2 = with_round(_base(), 5)
    s2 = _advance_until_decision(_owning(s2, played_round=3))
    assert not _offer_up(s2)                  # a later round: never again


def test_not_offered_without_a_supply_meeple():
    s = _at_boundary(played_round=4, supply=0, total=5)
    assert not _offer_up(s)


# ---------------------------------------------------------------------------
# Taking and declining
# ---------------------------------------------------------------------------

def test_declining_ends_the_work_phase():
    s = step(_at_boundary(played_round=4), CommitCardChoice(index=_DECLINE_IDX))
    p = _p0(s)
    assert p.temp_workers_active == 0
    assert CARD_ID in p.used_this_round or s.round_number != 4   # latched (or round over)
    assert s.round_number != 4 or s.phase is not Phase.WORK


def test_taking_grants_exactly_one_extra_placement_inside_the_work_phase():
    """Round 5 (no harvest); the loaner is placed on FARMLAND — a hosted space — so
    the counter can be read mid-turn, before the placement (the round's last action)
    lets the reset zero it."""
    s = step(_at_boundary(played_round=5), CommitCardChoice(index=_TAKE_IDX))
    p = _p0(s)
    assert (p.workers_in_supply, p.people_home, p.temp_workers_active) == (0, 1, 1)
    assert p.people_total == 3                    # never a family member
    assert s.current_player == 0                  # the turn is the owner's
    assert s.phase is Phase.WORK and s.round_number == 5
    ordinal_before = placements_this_round(p)     # 3: the faked family placements
    s = step(s, PlaceWorker(space="farmland"))
    assert s.pending_stack                        # the plow host is up: mid-turn
    assert placements_this_round(_p0(s)) == ordinal_before + 1   # the loaner MINTS
    # Finish the turn; the offer is spent, so the round now runs out.
    while s.round_number == 5:
        acts = legal_actions(s)
        assert acts
        s = step(s, acts[0])
    p = _p0(s)
    assert p.temp_workers_active == 0             # returned at the reset
    assert p.workers_in_supply == 1               # ...to SUPPLY
    assert p.people_total + p.workers_in_supply == 4   # meeple conservation (3 + 1)


def test_offer_is_not_repeated_after_being_answered():
    for idx in (_TAKE_IDX, _DECLINE_IDX):
        s = step(_at_boundary(played_round=4), CommitCardChoice(index=idx))
        assert not _offer_up(s)


# ---------------------------------------------------------------------------
# The ruling pin: the loaner is visible to the end_of_work readers (Iron Hoe)
# ---------------------------------------------------------------------------

def test_loaner_completes_iron_hoe_pair_before_end_of_work():
    """Iron Hoe: "At the end of each work phase, if you occupy both the 'Grain Seeds'
    and 'Vegetable Seeds' action spaces, you can plow 1 field." Ruled 2026-07-26: the
    Wayfarer's bonus worker exists for the end_of_work readers — here it completes
    Iron Hoe's pair, so the end-of-work trigger must be offered."""
    s = with_round(_base(), 8)                       # vegetable_seeds is stage 3
    s = with_space(s, "vegetable_seeds", revealed=True)
    s = _owning(s, played_round=8, own_home=2, opp_home=0, total=2, supply=3,
                extra_occupations=frozenset({"iron_hoe"}))
    # Iron Hoe is a MINOR in the data; inject it where its module expects it.
    p = s.players[0]
    p = fast_replace(p, occupations=p.occupations - {"iron_hoe"},
                     minor_improvements=p.minor_improvements | {"iron_hoe"})
    s = fast_replace(s, players=(p, s.players[1]))
    s = _advance_until_decision(s)

    s = step(s, PlaceWorker(space="grain_seeds"))    # worker 1 of 2
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    s = step(s, PlaceWorker(space="forest"))         # worker 2 of 2 -> all placed
    while s.pending_stack and not _offer_up(s):
        s = step(s, legal_actions(s)[0])
    assert _offer_up(s)
    s = step(s, CommitCardChoice(index=_TAKE_IDX))   # take the loaner
    s = step(s, PlaceWorker(space="vegetable_seeds"))   # ...completing the pair
    while s.pending_stack and s.phase is Phase.WORK and not any(
            isinstance(a, FireTrigger) and a.card_id == "iron_hoe"
            for a in legal_actions(s)):
        s = step(s, legal_actions(s)[0])
    assert any(isinstance(a, FireTrigger) and a.card_id == "iron_hoe"
               for a in legal_actions(s)), \
        "the loaner's placement must be visible to Iron Hoe's end_of_work check"
