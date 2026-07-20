"""Tests for Forest School (minor improvement A28): two clauses.

  CLAUSE 1 — the LEGALITY RELAXATION (occupancy override) on Lessons: the owner may place on
    Lessons even when one opponent already occupies it; with boundaries (no ownership, owner
    already holds it, non-lessons spaces, 2+ other players).

  CLAUSE 2 — replace the occupation's food cost with wood, PER FOOD, as a play_occupation
    COST CONVERSION (rulings 65 + 67): the ways to pay surface as payment-carrying
    CommitPlayOccupations from the `effective_payments` frontier — one per (k wood,
    need−k food) point — never as triggers. Covers: registration (a CONVERSIONS entry; no
    trigger, no food source); the wood payment (Lessons); the affordability gate; the
    free-play legacy shape (the free first Lessons play AND a granted free play — the Seed
    Researcher shape); the frontier capped at the cost's food; the `paid_cost` stamp; and
    the 2-food granted route (Writing Desk): the full-wood payment, the MIXED 1-wood +
    1-food payment, and the automatic pruning of an unpayable partial (the old stranding
    filter, now structural).

  Plus registration / cost / vps and Family byte-identity (no card -> occupied lessons illegal).
"""
import agricola.cards.forest_school  # noqa: F401
import agricola.cards.writing_desk  # noqa: F401

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.cost_mods import CONVERSIONS
from agricola.cards.forest_school import CARD_ID, _occupancy_override
from agricola.cards.specs import MINORS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import TRIGGERS
from agricola.pending import PendingPlayOccupation, push
from agricola.engine import step
from agricola.legality import (
    OCCUPANCY_OVERRIDE_EXTENSIONS,
    legal_actions,
    legal_placements,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

import tests.factories as f

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost.resources.wood == 1
    assert spec.cost.resources.clay == 1
    # Ruling 67: the substitution is a play_occupation COST CONVERSION — not a
    # trigger and not an occupation food source (both old registrations are gone).
    assert any(cid == CARD_ID
               for _o, cid, _fn, _rec in CONVERSIONS.get("play_occupation", ()))
    assert CARD_ID not in OCCUPATION_FOOD_SOURCES
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_play_occupation", []))
    assert _occupancy_override in OCCUPANCY_OVERRIDE_EXTENSIONS


# ===========================================================================
# CLAUSE 1 — Lessons occupancy override
# ===========================================================================

def _lessons_state(seed=5, *, owner=None):
    """CARDS-mode state with Lessons revealed, p0 to move, and a playable (free first) occupation
    in p0's hand so `_legal_lessons_cards`' own affordability gate is satisfied — isolating the
    occupancy override. `owner=0` -> p0 owns Forest School. (Lessons is a CARDS-only space —
    illegal in the Family game — so this must be card mode.)"""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, "lessons", revealed=True)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset({"consultant"}),
                      resources=Resources(food=5))
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    if owner is not None:
        cs = f.with_minors(cs, owner, frozenset({CARD_ID}))
    return cs


def _set_workers(cs, w):
    return f.with_space(cs, "lessons", workers=w)


def _lessons_placeable(cs):
    return PlaceWorker(space="lessons") in legal_placements(cs)


def test_owner_may_use_lessons_occupied_by_opponent():
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 1))   # opponent (p1) holds Lessons
    assert _lessons_placeable(cs)


def test_not_offered_without_ownership():
    cs = _lessons_state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert not _lessons_placeable(cs)


def test_not_offered_when_owner_already_holds_lessons():
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (1, 0))   # owner (p0) is the sole occupant
    assert not _lessons_placeable(cs)


def test_override_does_not_apply_to_non_lessons_spaces():
    cs = _lessons_state(owner=0)
    cs = f.with_space(cs, "forest", revealed=True, workers=(0, 1))
    assert PlaceWorker(space="forest") not in legal_placements(cs)


def test_two_other_players_blocks_override():
    # 4-player shape: 2+ OTHER players holding the space -> override declines (== 1 only).
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 1))
    cs3 = f.with_space(cs, "lessons", workers=(0, 1, 1))
    assert _occupancy_override(cs3, "lessons") is False
    assert _occupancy_override(cs, "lessons") is True


def test_unoccupied_lessons_uses_normal_legality():
    # The override is irrelevant when the space is unoccupied; normal legality applies. With a
    # playable, affordable occupation in hand (set by the helper) and Lessons free, it is placeable.
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 0))
    assert _lessons_placeable(cs)


# ===========================================================================
# CLAUSE 2 — replace the occupation's food cost with wood
# ===========================================================================

def _play_state(*, owned=(CARD_ID,), occupations=(), hand=("consultant",), food=0, wood=0):
    """p0 owns the listed minors + has the listed occupations already in front of them, with the
    given hand and resources. (`occupations` non-empty makes the next play cost 1 food.)"""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        minor_improvements=frozenset(owned),
        occupations=frozenset(occupations),
        hand_occupations=frozenset(hand),
        resources=Resources(food=food, wood=wood),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(cs):
    return {a.space for a in legal_placements(cs)}


def _to_play_occupation(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs


def test_substitution_pays_in_wood():
    # 0 food, 1 wood, own Forest School, play a 2nd occupation (cost 1 food). The food
    # payment is unaffordable, so the frontier is exactly the wood substitution — ONE
    # payment-carrying commit (ruling 67: no trigger step, no legacy commit).
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=1)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="consultant") not in la   # food payment unaffordable
    wood_pay = CommitPlayOccupation(card_id="consultant", payment=Resources(wood=1))
    assert wood_pay in la

    cs = step(cs, wood_pay)
    p = cs.players[cp]
    assert "consultant" in p.occupations
    assert p.resources.wood == 0          # the occupation was paid in wood
    assert p.resources.food == 0
    assert p.resources.clay == 3          # consultant's on-play ran
    # The host stamped the actual payment (the "food paid" ground truth — ruling 67).
    assert cs.pending_stack[-1].paid_cost == Resources(wood=1)


def test_lessons_offered_only_via_forest_school():
    # 0 food, 0 liquidation fuel, 1 wood, own Forest School: the 2nd occupation's 1-food cost is
    # payable only by firing the substitution first — Lessons must be offered (the gate consults
    # the food source). Without the wood it must NOT be offered.
    cs, _ = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=1)
    assert "lessons" in _spaces(cs)
    cs_nowood, _ = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=0)
    assert "lessons" not in _spaces(cs_nowood)


def test_not_offered_for_free_first_occupation():
    # The free first occupation costs 0 food: nothing to replace, so the substitution is NOT
    # offered (no pointless 0-wood -> 0-food no-op).
    cs, _cp = _play_state(occupations=(), hand=("consultant",), food=0, wood=2)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    # Free play: the frontier is the singleton empty cost -> the legacy commit shape,
    # and no wood-substitution payments exist (nothing to replace).
    assert CommitPlayOccupation(card_id="consultant") in la
    assert not any(getattr(a, "payment", None) for a in la)


def test_substitution_optional_when_food_on_hand():
    # With food on hand BOTH ways to pay surface as payment-carrying commits — the food
    # payment and the wood substitution, Pareto-incomparable. Paying food leaves the
    # wood untouched (declining is picking the food payment; no trigger, no extra ply).
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=5, wood=2)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    food_pay = CommitPlayOccupation(card_id="consultant", payment=Resources(food=1))
    wood_pay = CommitPlayOccupation(card_id="consultant", payment=Resources(wood=1))
    assert food_pay in la
    assert wood_pay in la
    assert CommitPlayOccupation(card_id="consultant") not in la   # no legacy shape here
    cs = step(cs, food_pay)                                       # decline: pay food
    p = cs.players[cp]
    assert p.resources.food == 4          # 5 - 1, paid in food
    assert p.resources.wood == 2          # untouched


def test_frontier_capped_at_the_costs_food():
    # A 1-food cost never yields a payment beyond 1 wood, whatever the wood pile — the
    # conversion replaces AT MOST cost.food (and an over-replacement would be dominated
    # and pruned regardless).
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=3)
    cs = _to_play_occupation(cs)
    pays = {a.payment for a in legal_actions(cs)
            if isinstance(a, CommitPlayOccupation)}
    assert pays == {Resources(wood=1)}
    cs = step(cs, CommitPlayOccupation(card_id="consultant", payment=Resources(wood=1)))
    assert cs.players[cp].resources.wood == 2   # only one wood spent


def test_conversion_expands_per_food():
    # The conversion emits the unchanged cost + one variant per replacement count k,
    # UNFILTERED (the expand1 contract — the chokepoint's affordability filter and
    # Pareto prune decide what actually surfaces).
    from agricola.cards.forest_school import _expand
    cs, _cp = _play_state()
    assert _expand(cs, cs.current_player, None, Resources(food=2)) == [
        Resources(food=2), Resources(food=1, wood=1), Resources(wood=2)]
    assert _expand(cs, cs.current_player, None, Resources()) == [Resources()]


# ===========================================================================
# Granted routes — the price is the FRAME's cost (ruling 65 regressions)
# ===========================================================================

def _writing_desk_grant(*, food, wood):
    """p0 owns Forest School + Writing Desk (one occupation already in front, so the
    mandatory Lessons play costs 1 food), places on Lessons, and fires Writing Desk's
    grant. Returns the state paused on the granted 2-food PendingPlayOccupation."""
    cs, cp = _play_state(owned=(CARD_ID, "writing_desk"), occupations=("priest",),
                         hand=("consultant", "stable_architect"), food=food, wood=wood)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, FireTrigger(card_id="writing_desk"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=2)
    return cs, cp


def test_granted_two_food_play_full_wood_and_mixed_menu():
    # Writing Desk's granted play costs 2 food (the FRAME's price — ruling 65). With
    # 1 food + 2 wood the frontier holds BOTH substitutions — the mixed (1 wood +
    # 1 food) and the full-wood (2 wood) payments, Pareto-incomparable — while the
    # pure 2-food payment is unaffordable. Pay all-wood, complete the whole turn.
    cs, cp = _writing_desk_grant(food=1, wood=2)
    la = legal_actions(cs)
    mixed = CommitPlayOccupation(card_id="consultant",
                                 payment=Resources(wood=1, food=1))
    all_wood = CommitPlayOccupation(card_id="consultant", payment=Resources(wood=2))
    assert mixed in la
    assert all_wood in la
    assert not any(isinstance(a, CommitPlayOccupation)
                   and a.payment == Resources(food=2) for a in la)   # 1 food < 2

    cs = step(cs, all_wood)                                       # the 2-food cost, in wood
    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.food == 1
    assert cs.pending_stack[-1].paid_cost == Resources(wood=2)
    cs = step(cs, Stop())                                         # pop the granted play

    # The mandatory Lessons play completes normally with the remaining 1 food (its
    # frontier is the food payment alone — no wood left — so the legacy shape).
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="stable_architect"))
    p = cs.players[cp]
    assert {"consultant", "stable_architect"} <= p.occupations
    assert p.resources.food == 0


def test_granted_two_food_play_mixed_payment():
    # The MIXED payment (ruling 65): replace only 1 of the 2 food — pay 1 wood + 1 food.
    # With exactly 1 wood + 1 food it is the ONLY way to pay.
    cs, cp = _writing_desk_grant(food=1, wood=1)
    mixed = CommitPlayOccupation(card_id="consultant",
                                 payment=Resources(wood=1, food=1))
    assert mixed in legal_actions(cs)
    cs = step(cs, mixed)
    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.food == 0                                  # paid 1 wood + 1 food
    assert cs.pending_stack[-1].paid_cost == Resources(wood=1, food=1)


def test_granted_two_food_play_prunes_unpayable_partial():
    # With 0 food, the mixed (1 wood + 1 food) payment is unaffordable and drops out of
    # the frontier automatically — the old stranding filter, now structural; only the
    # full-wood payment surfaces. (The turn is deliberately left mid-Lessons: the
    # post-grant state is not under test.)
    cs, _cp = _writing_desk_grant(food=0, wood=2)
    pays = {a.payment for a in legal_actions(cs)
            if isinstance(a, CommitPlayOccupation) and a.card_id == "consultant"}
    assert pays == {Resources(wood=2)}


def test_granted_free_play_offers_no_substitution():
    # A granted play at NO occupation cost (Seed Researcher's shape) has nothing to
    # replace: the frontier is the singleton empty cost -> the legacy commit shape with
    # no substitution payments. (Direct frame push: the real Seed Researcher flow spans
    # the round-end ladder; what the conversion reads is the frame's cost.)
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=3)
    cs = push(cs, PendingPlayOccupation(
        player_idx=cp, initiated_by_id="card:seed_researcher", cost=Resources()))
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="consultant") in la       # free, committable
    assert not any(getattr(a, "payment", None) for a in la)


def test_gate_covers_multi_food_cost_via_wood():
    # The affordability gate simulates the swap against the ROUTE'S cost (the 3-arg seam):
    # 2 wood + 0 food reaches a 2-food play; 1 wood does not (1 raised food < 2, nothing
    # else liquidatable).
    from agricola.legality import _payable_occupation
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=2)
    assert _payable_occupation(cs, cp, cs.players[cp], Resources(food=2))
    cs1, cp1 = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=1)
    assert not _payable_occupation(cs1, cp1, cs1.players[cp1], Resources(food=2))
