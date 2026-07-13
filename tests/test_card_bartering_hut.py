"""Tests for Bartering Hut (minor E9, traveling): "Up to two times: Immediately
spend any 2/3/4 building resources for 1 sheep/wild boar/cattle from the
general supply." Free.

On-play pushes a PendingCardChoice over "decline" + every affordable
(animal, wood, clay, reed, stone) composition; a purchase re-pushes the choice
while a use and an affordable purchase remain. Animals route through
grant_animals + the UNFILTERED accommodation barrier (no accommodation clause
on this card — user-confirmed 2026-07-13).
"""
import agricola.cards.bartering_hut  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, CommitCardChoice, CommitPlayMinor
from agricola.cards.bartering_hut import _options
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARD_CHOICE_RESOLVERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingCardChoice, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack

CARD_ID = "bartering_hut"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _at_play_minor_frame(res, *, animals=Animals()):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     resources=res, animals=animals)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp,
                                 initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _play(state):
    (commit,) = [a for a in legal_actions(state)
                 if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    return step(state, commit)


def _choose(state, option):
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    idx = top.options.index(option)
    return step(state, CommitCardChoice(index=idx))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.passing_left is True
    assert spec.vps == 0
    assert CARD_ID in CARD_CHOICE_RESOLVERS


# ---------------------------------------------------------------------------
# The option menu: affordable compositions only
# ---------------------------------------------------------------------------

def test_options_respect_holdings():
    state, cp = _at_play_minor_frame(Resources(wood=2, clay=1))
    opts = _options(state, cp)
    assert opts[0] == "decline"
    # sheep (2): ww / wc; boar (3): wwc; cattle (4): unaffordable.
    assert set(opts[1:]) == {
        ("sheep", 2, 0, 0, 0),
        ("sheep", 1, 1, 0, 0),
        ("boar", 2, 1, 0, 0),
    }


def test_rich_holdings_offer_all_tiers():
    state, cp = _at_play_minor_frame(Resources(wood=4, clay=4, reed=4, stone=4))
    opts = _options(state, cp)
    # 1 decline + 10 sheep + 20 boar + 35 cattle compositions = 66.
    assert len(opts) == 66


def test_no_affordable_purchase_no_frame():
    state, cp = _at_play_minor_frame(Resources(wood=1))
    out = _play(state)
    assert not any(isinstance(f, PendingCardChoice) for f in out.pending_stack)
    assert CARD_ID in out.players[1 - cp].hand_minors    # still traveled


# ---------------------------------------------------------------------------
# The purchase flow
# ---------------------------------------------------------------------------

def test_two_purchases_then_stop():
    state, cp = _at_play_minor_frame(Resources(wood=4))
    s = _play(state)
    assert isinstance(s.pending_stack[-1], PendingCardChoice)
    s = _choose(s, ("sheep", 2, 0, 0, 0))
    # First purchase: sheep granted (fits the pet slot), second choice offered
    # with options recomputed on the post-debit 2 wood.
    assert s.players[cp].animals.sheep == 1
    assert s.players[cp].resources.wood == 2
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert ("sheep", 2, 0, 0, 0) in top.options
    assert not any(o[0] == "boar" for o in top.options if o != "decline")
    s = _choose(s, ("sheep", 2, 0, 0, 0))
    # Second purchase ends the effect — no third frame even if resources remained.
    assert s.players[cp].animals.sheep == 2 or any(
        isinstance(f, PendingAccommodate) for f in s.pending_stack)
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)


def test_single_purchase_exhausting_resources_stops():
    state, cp = _at_play_minor_frame(Resources(wood=4))
    s = _play(state)
    s = _choose(s, ("cattle", 4, 0, 0, 0))
    assert s.players[cp].animals.cattle == 1
    assert s.players[cp].resources.wood == 0
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)


def test_decline_first_forfeits_second():
    state, cp = _at_play_minor_frame(Resources(wood=4))
    s = _play(state)
    s = _choose(s, "decline")
    p = s.players[cp]
    assert p.animals == Animals()
    assert p.resources.wood == 4
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)


def test_mixed_composition_debits_each_resource():
    state, cp = _at_play_minor_frame(Resources(wood=1, clay=1, reed=1, stone=1))
    s = _play(state)
    s = _choose(s, ("cattle", 1, 1, 1, 1))
    p = s.players[cp]
    assert p.animals.cattle == 1
    assert (p.resources.wood, p.resources.clay,
            p.resources.reed, p.resources.stone) == (0, 0, 0, 0)


def test_overflow_interleaves_barrier_between_purchases():
    # A pet boar holds the only slot; buying a sheep overflows -> the barrier's
    # unfiltered keep-which frame lands ON TOP of the second choice frame.
    state, cp = _at_play_minor_frame(Resources(wood=4), animals=Animals(boar=1))
    s = _play(state)
    s = _choose(s, ("sheep", 2, 0, 0, 0))
    assert isinstance(s.pending_stack[-1], PendingAccommodate)
    assert isinstance(s.pending_stack[-2], PendingCardChoice)
    options = [a for a in legal_actions(s) if isinstance(a, CommitAccommodate)]
    # UNFILTERED: keeping the boar by releasing the just-bought sheep is legal.
    assert any(a.boar == 1 and a.sheep == 0 for a in options)
    keep_boar = next(a for a in options if a.boar == 1 and a.sheep == 0)
    s = step(s, keep_boar)
    # Back at the second purchase choice.
    assert isinstance(s.pending_stack[-1], PendingCardChoice)
    s = _choose(s, "decline")
    assert not any(isinstance(f, PendingCardChoice) for f in s.pending_stack)
