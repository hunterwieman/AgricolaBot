"""Tests for Child's Toy (minor improvement, E30; Ephipparius Expansion).

Card text: "During the feeding phase of each harvest, your newborns require 2
food (instead of 1)."

A feeding-requirement fold (`register_feeding_requirement`): the base
requirement 2*people_total − newborns already charges 1 food per newborn, so
the fold adds +newborns, making each of the owner's newborns cost exactly 2.
The fold is consulted only at harvest feeding (`helpers.feeding_requirement`
— the feed-frame enumerator's food_owed and the CommitConvert feed executor),
matching the printed "during the feeding phase of each harvest". Cost is the
alternative ("/") pair 1 Wood / 1 Clay; prerequisite "Exactly 2 Adults" is a
custom play-time predicate (adults = people_total − newborns). Tests drive the
real harvest walk end-to-end (begging under the raised need), pin the feed
frontier off the raised requirement, and exercise both payment alternatives at
a real PendingPlayMinor frame.
"""
import json
import pathlib

import agricola.cards.childs_toy  # noqa: F401  -- registers the card

from agricola.cards.childs_toy import CARD_ID
from agricola.cards.harvest_windows import FEEDING_REQUIREMENT_FOLDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import feeding_requirement
from agricola.legality import legal_actions
from agricola.actions import CommitConvert, CommitPlayMinor
from agricola.pending import PendingHarvestFeed, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

from tests.factories import (
    with_pending_stack,
    with_people,
    with_phase,
    with_resources,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(seed=0):
    state, _env = setup_env(seed, card_pool=_POOL)
    p0 = fast_replace(state.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(state.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(state, players=(p0, p1))


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state; both players start with `food` food and no
    other convertible goods (fresh setup: no grain/veg/animals)."""
    state = with_phase(_base_state(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in _HARVEST_PHASES:
        state = step(state, pick(legal_actions(state)))
    return state


def _walk_to_feed_frame(state, idx):
    """Drive the harvest walk until player `idx`'s PendingHarvestFeed is on top
    (its conversion not yet committed)."""
    state = _advance_until_decision(state)
    while state.phase in _HARVEST_PHASES:
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestFeed) and top.player_idx == idx
                and not top.conversion_done):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("never reached the feed frame")


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the card data this implementation was written against."""
    path = (pathlib.Path(__file__).resolve().parents[1]
            / "agricola" / "cards" / "data" / "revised_minor_improvements.json")
    rows = json.loads(path.read_text())
    row = next(r for r in rows if r["deck"] == "E" and r["number"] == 30)
    assert row["name"] == "Child's Toy"
    assert row["cost"] == "1 Wood/1 Clay"
    assert row["vps"] == 2
    assert row["prerequisites"] == "Exactly 2 Adults"
    assert row["passing_left"] is None
    assert row["text"] == ("During the feeding phase of each harvest, your "
                           "newborns require 2 food (instead of 1).")


def test_registered_spec():
    spec = MINORS[CARD_ID]
    # "1 Wood/1 Clay" is an ALTERNATIVE ("/") cost: printed 1-wood in `cost`,
    # the 1-clay alternative in `alt_costs` — pay ONE, not both.
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.alt_costs == (Cost(resources=Resources(clay=1)),)
    assert spec.vps == 2
    assert spec.passing_left is False
    assert spec.prereq is not None                    # "Exactly 2 Adults"
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert CARD_ID in FEEDING_REQUIREMENT_FOLDS


# ---------------------------------------------------------------------------
# The requirement fold (unit level, through helpers.feeding_requirement)
# ---------------------------------------------------------------------------

def test_requirement_raised_for_owner_with_newborn():
    state = _base_state()
    state = with_people(state, 0, total=3, home=3, newborns=1)
    assert feeding_requirement(state, 0) == 2 * 3 - 1     # base: newborn costs 1
    owned = _own_minor(state, 0)
    assert feeding_requirement(owned, 0) == 2 * 3         # newborn costs 2


def test_requirement_unchanged_without_newborns():
    state = _base_state()                                  # 2 adults, no newborns
    owned = _own_minor(state, 0)
    assert feeding_requirement(owned, 0) == feeding_requirement(state, 0) == 4


def test_opponent_requirement_unaffected():
    state = _base_state()
    state = with_people(state, 1, total=3, home=3, newborns=1)
    owned = _own_minor(state, 0)                           # player 0 owns the card
    assert feeding_requirement(owned, 1) == 2 * 3 - 1      # player 1 keeps the discount


# ---------------------------------------------------------------------------
# End-to-end: a real harvest walk with a newborn
# ---------------------------------------------------------------------------

def test_owner_begs_under_raised_need():
    """Owner with 1 newborn (3 people) holds exactly the BASE need (5 food) but
    not the raised need (6): feeding ends with 1 begging marker and 0 food."""
    state = _harvest_state(food=10)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_resources(state, 0, food=5)               # no grain/veg/animals
    state = _own_minor(state, 0)
    state = _run_harvest(state)
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 1
    assert state.players[1].begging_markers == 0


def test_negative_control_no_card_no_begging():
    """Same harvest without the card: 5 food covers the base need of 5 exactly."""
    state = _harvest_state(food=10)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_resources(state, 0, food=5)
    state = _run_harvest(state)
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 0


def test_no_newborn_harvest_unchanged():
    """Owner with no newborns: the card changes nothing (need stays 2/adult)."""
    state = _harvest_state(food=10)
    state = with_resources(state, 0, food=4)               # 2 adults need 4
    state = _own_minor(state, 0)
    state = _run_harvest(state)
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 0


def test_opponent_newborn_unaffected_end_to_end():
    """Player 1 (non-owner) has the newborn: their discount survives — 5 food
    feeds 3 people (one newborn) cleanly while player 0 owns the card."""
    state = _harvest_state(food=10)
    state = with_resources(state, 0, food=4)
    state = with_people(state, 1, total=3, home=3, newborns=1)
    state = with_resources(state, 1, food=5)
    state = _own_minor(state, 0)
    state = _run_harvest(state)
    assert state.players[1].resources.food == 0
    assert state.players[1].begging_markers == 0


# ---------------------------------------------------------------------------
# The feed frontier reflects the raised requirement
# ---------------------------------------------------------------------------

def test_feed_frontier_computed_off_raised_need():
    """Owner at the feed frame with 5 food + 1 grain and a newborn: need is 6,
    so food_owed is 1 and the frontier offers BOTH covering the shortfall with
    the grain (no begging) and keeping the grain (beg 1). Without the card the
    5 food covers the need outright and only the trivial convert is offered."""
    base = _harvest_state(food=10)
    base = with_people(base, 0, total=3, home=3, newborns=1)
    base = with_resources(base, 0, food=5, grain=1)

    owned = _walk_to_feed_frame(_own_minor(base, 0), 0)
    assert feeding_requirement(owned, 0) == 6
    converts = sorted(
        (a.grain for a in legal_actions(owned) if isinstance(a, CommitConvert)))
    assert converts == [0, 1]           # keep-grain-and-beg XOR pay-with-grain

    plain = _walk_to_feed_frame(base, 0)
    assert feeding_requirement(plain, 0) == 5
    converts = [a for a in legal_actions(plain) if isinstance(a, CommitConvert)]
    assert len(converts) == 1 and converts[0].grain == 0   # nothing owed


def test_paying_the_raised_need_with_grain_avoids_begging():
    """Committing the grain conversion at the raised need feeds fully."""
    state = _harvest_state(food=10)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_resources(state, 0, food=5, grain=1)
    state = _own_minor(state, 0)
    state = _walk_to_feed_frame(state, 0)
    pay = next(a for a in legal_actions(state)
               if isinstance(a, CommitConvert) and a.grain == 1)
    state = step(state, pay)
    p = state.players[0]
    assert p.resources.food == 0 and p.resources.grain == 0
    assert p.begging_markers == 0


# ---------------------------------------------------------------------------
# Prerequisite "Exactly 2 Adults" (adults = people_total − newborns)
# ---------------------------------------------------------------------------

def test_prereq_boundaries():
    state = _base_state()
    spec = MINORS[CARD_ID]
    # 2 adults (fresh setup) -> met.
    assert prereq_met(spec, state, 0)
    # 3 adults -> not met.
    assert not prereq_met(spec, with_people(state, 0, total=3, home=3), 0)
    # 1 adult (2 people, 1 newborn) -> not met.
    assert not prereq_met(spec, with_people(state, 0, total=2, newborns=1), 0)
    # 3 people but 1 newborn = 2 ADULTS -> met (newborns are not adults).
    assert prereq_met(spec, with_people(state, 0, total=3, home=3, newborns=1), 0)


# ---------------------------------------------------------------------------
# Playing the card: the two payment alternatives at a real play-minor frame
# ---------------------------------------------------------------------------

def _at_play_minor_frame(res):
    """A CARDS state at a PendingPlayMinor with the card in the current
    player's hand and `res` resources on hand. Returns (state, current_player)."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}), resources=res)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _minor_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def test_both_alternatives_offered_when_both_affordable():
    state, _cp = _at_play_minor_frame(Resources(wood=1, clay=1))
    payments = sorted((c.payment.wood, c.payment.clay) for c in _minor_commits(state))
    assert payments == [(0, 1), (1, 0)]   # a 1-clay option and a 1-wood option


def test_pay_via_wood_debits_only_wood():
    state, cp = _at_play_minor_frame(Resources(wood=1, clay=1))
    wood_commit = next(c for c in _minor_commits(state) if c.payment.wood == 1)
    out = step(state, wood_commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.wood == 0          # wood spent
    assert p.resources.clay == 1          # clay untouched


def test_pay_via_clay_debits_only_clay():
    state, cp = _at_play_minor_frame(Resources(wood=1, clay=1))
    clay_commit = next(c for c in _minor_commits(state) if c.payment.clay == 1)
    out = step(state, clay_commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.clay == 0          # clay spent
    assert p.resources.wood == 1          # wood untouched


def test_only_affordable_alternative_offered():
    state, _cp = _at_play_minor_frame(Resources(wood=1))
    commits = _minor_commits(state)
    assert len(commits) == 1 and commits[0].payment.wood == 1
    state, _cp = _at_play_minor_frame(Resources(clay=1))
    commits = _minor_commits(state)
    assert len(commits) == 1 and commits[0].payment.clay == 1


def test_prereq_blocks_play_at_the_frame():
    """The legality path enforces the prerequisite: 3 adults -> not offered."""
    state, cp = _at_play_minor_frame(Resources(wood=1, clay=1))
    state = with_people(state, cp, total=3, home=3)
    assert _minor_commits(state) == []


def test_prereq_newborn_excluded_at_the_frame():
    """3 people with 1 newborn = exactly 2 adults -> playable."""
    state, cp = _at_play_minor_frame(Resources(wood=1, clay=1))
    state = with_people(state, cp, total=3, home=3, newborns=1)
    assert len(_minor_commits(state)) == 2
