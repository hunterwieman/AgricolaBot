"""Tests for Skillful Renovator (occupation, C119; Consul Dirigens Expansion).

Card text: "When you play this card, you immediately get 1 wood and 1 clay. Each
time after you renovate, you get a number of wood equal to the number of people
you placed that round."
Clarifications: "If you renovate with your 3rd placed person of a round, this card
triggers a payout of 3 wood. Newborns are not placed."

Shape: an occupation with two mandatory, choice-free clauses → an on-play effect
(+1 wood, +1 clay) and an `after_renovate` automatic effect that pays wood equal
to the people placed this round, computed `people_total - newborns - people_home`.
Both are choice-free, so no FireTrigger is surfaced — the renovate tests drive the
real House Redevelopment flow.
"""
from __future__ import annotations

import agricola.cards.skillful_renovator  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_people, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "skillful_renovator"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


def _do_renovate(state):
    """Drive the real House Redevelopment renovate flow to a turn-complete state.

    PlaceWorker decrements people_home BEFORE the renovate frame, so the placed
    count seen by the after_renovate auto already includes this worker.
    """
    return run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,        # applies the renovate
        Stop(),               # pop PendingRenovate after-phase
        Proceed(),            # flip the house_redevelopment host to its after-phase
                              #   → fires after_renovate (the card's payout)
        Stop(),               # pop the host → turn complete
    ])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    after = {e.card_id for e in AUTO_EFFECTS.get("after_renovate", [])}
    assert CARD_ID in after
    # Mandatory auto (no FireTrigger), so it is NOT in the declinable TRIGGERS list.
    from agricola.cards.triggers import TRIGGERS
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


# ---------------------------------------------------------------------------
# on_play: +1 wood, +1 clay
# ---------------------------------------------------------------------------

def test_on_play_grants_wood_and_clay():
    cs = _card_state()
    wood0 = cs.players[0].resources.wood
    clay0 = cs.players[0].resources.clay
    cs = OCCUPATIONS[CARD_ID].on_play(cs, 0)
    assert cs.players[0].resources.wood == wood0 + 1
    assert cs.players[0].resources.clay == clay0 + 1


def test_on_play_only_affects_owner():
    cs = _card_state()
    wood1 = cs.players[1].resources.wood
    clay1 = cs.players[1].resources.clay
    cs = OCCUPATIONS[CARD_ID].on_play(cs, 0)
    assert cs.players[1].resources.wood == wood1   # opponent untouched
    assert cs.players[1].resources.clay == clay1


# ---------------------------------------------------------------------------
# after_renovate: +wood equal to people placed this round (real flow)
# ---------------------------------------------------------------------------

def test_renovate_pays_one_wood_with_one_placed():
    # Default start: people_total=2, people_home=2. The renovate placement is the
    # 1st placed person → placed = 2 - 0 - 1 = 1 → +1 wood.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own(cs, 0, CARD_ID)
    wood0 = cs.players[0].resources.wood
    cs = _do_renovate(cs)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY
    # +1 wood from the card; the renovate itself spends only clay+reed, not wood.
    assert cs.players[0].resources.wood == wood0 + 1


def test_renovate_with_third_placed_person_pays_three_wood():
    # The clarification's worked example: renovating with the 3rd placed person of
    # the round pays 3 wood. Set up two people already placed this round
    # (people_total=3, people_home=1); the renovate placement is the 3rd
    # (people_home → 0) → placed = 3 - 0 - 0 = 3 → +3 wood.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = with_people(cs, 0, total=3, home=1, newborns=0)
    cs = _own(cs, 0, CARD_ID)
    wood0 = cs.players[0].resources.wood
    cs = _do_renovate(cs)
    assert cs.players[0].resources.wood == wood0 + 3


def test_newborns_are_not_counted_as_placed():
    # "Newborns are not placed." A newborn inflates people_total but must be
    # subtracted. people_total=3 with 1 newborn, people_home=1 → after the renovate
    # placement (home → 0): placed = 3 - 1 - 0 = 2 → +2 wood (NOT 3).
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = with_people(cs, 0, total=3, home=1, newborns=1)
    cs = _own(cs, 0, CARD_ID)
    wood0 = cs.players[0].resources.wood
    cs = _do_renovate(cs)
    assert cs.players[0].resources.wood == wood0 + 2


def test_clay_to_stone_renovate_also_pays():
    # "Each time after you renovate" covers clay->stone too, not just wood->clay.
    # Clay->stone costs 1 stone + 1 reed per room (2 rooms by default).
    cs = _renovate_setup(HouseMaterial.CLAY, stone=2, reed=2)
    cs = _own(cs, 0, CARD_ID)
    wood0 = cs.players[0].resources.wood
    cs = _do_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.wood == wood0 + 1   # 1 placed → +1 wood


# ---------------------------------------------------------------------------
# Eligibility / scoping boundaries
# ---------------------------------------------------------------------------

def test_unowned_does_not_pay():
    # A player who has NOT played the card gets no renovate payout.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)  # card not owned
    wood0 = cs.players[0].resources.wood
    cs = _do_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert cs.players[0].resources.wood == wood0             # no payout


def test_payout_is_per_player():
    # P0 owns the card and renovates; P1 owns it too but does not renovate, so P1's
    # wood is untouched (the auto is own-action, fired for the acting player only).
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own(cs, 0, CARD_ID)
    cs = _own(cs, 1, CARD_ID)
    wood1 = cs.players[1].resources.wood
    cs = _do_renovate(cs)
    assert cs.players[1].resources.wood == wood1             # opponent untouched
