"""Tests for Maintenance Premium (minor improvement, B55; Bubulcus Expansion).

Card text: "Place 3 food on this card. Each time you use a wood accumulation space,
you get 1 food from this card. Each time you renovate restock this card to 3 food."
Prerequisite: 2 Occupations. No printed cost. No VPs. Not passing.

Shape: a food-bearing card with a CardStore reservoir (keyed "maintenance_premium").
on_play seeds it at 3. A mandatory `before_action_space` auto on the Forest pays the
owner 1 food per wood-space use while the reservoir holds food; a mandatory
`after_renovate` auto restocks it to 3. Both are choice-free automatic effects, so
no FireTrigger is ever surfaced — the forest test drives the real placement flow and
the renovate test drives the real House Redevelopment flow.
"""
from __future__ import annotations

import agricola.cards.maintenance_premium  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "maintenance_premium"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
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


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _seed_reservoir(state, idx, value):
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, value))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reservoir(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _use_forest(state):
    """Place P0 at the (permanent, revealed) Forest and run the host to completion, so
    the host frame's before_action_space autos have fired. Returns the turn-complete
    (empty-stack) state.

    With the card owned the Forest is HOSTED (a PendingActionSpace), so the placement's
    before_action_space autos fire at the push; Proceed runs the +3 wood pickup and
    flips the host to its after-phase, and Stop pops it."""
    state = step(state, PlaceWorker(space="forest"))
    if not state.pending_stack:
        return state                       # unhosted (card unowned) → atomic fast path
    state = step(state, Proceed())         # +3 wood pickup, flip host to after-phase
    return step(state, Stop())             # pop the host → turn complete


def _renovate_setup(material, *, idx=0, **resources):
    """A card-mode state with house_redevelopment revealed and the given house."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()             # no printed cost
    assert spec.min_occupations == 2       # prereq: 2 occupations
    assert spec.max_occupations is None
    assert spec.vps == 0
    assert not spec.passing_left
    # Mandatory autos on the two events + the Forest host index.
    before = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    after = {e.card_id for e in AUTO_EFFECTS.get("after_renovate", [])}
    assert CARD_ID in before
    assert CARD_ID in after
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())


# ---------------------------------------------------------------------------
# on_play: places 3 food on the card
# ---------------------------------------------------------------------------

def test_on_play_seeds_three_food():
    cs = _card_state()
    food0 = cs.players[0].resources.food
    assert _reservoir(cs, 0) == 0          # not yet on the card
    cs = MINORS[CARD_ID].on_play(cs, 0)
    assert _reservoir(cs, 0) == 3          # 3 food on the card
    assert cs.players[0].resources.food == food0   # not in the player's supply


# ---------------------------------------------------------------------------
# Forest payout: +1 food from the card per wood-space use
# ---------------------------------------------------------------------------

def test_forest_pays_one_food_from_card():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 3)
    food0 = cs.players[0].resources.food
    wood0 = cs.players[0].resources.wood
    cs = _use_forest(cs)
    assert not cs.pending_stack                       # turn complete
    assert cs.players[0].resources.food == food0 + 1  # +1 food from the card
    assert cs.players[0].resources.wood == wood0 + 3  # Forest's own +3 wood, intact
    assert _reservoir(cs, 0) == 2                      # reservoir drained by 1


def test_forest_is_hosted_when_owned():
    # Owning the card pushes a PendingActionSpace host on the Forest (so the auto can
    # fire), instead of the atomic fast path.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 3)
    cs = step(cs, PlaceWorker(space="forest"))
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert cs.pending_stack[-1].phase == "before"


def test_reservoir_drains_one_per_use():
    # A forest use draws the reservoir down by exactly 1 (3->2, 2->1, 1->0), each on a
    # fresh single-turn state (a worker is consumed per use, so successive uses on one
    # game would change player). The last legal payout is at 1; the next subsection
    # covers the empty case.
    for start, expected in ((3, 2), (2, 1), (1, 0)):
        cs = _card_state()
        cs = _own_minor(cs, 0, CARD_ID)
        cs = _seed_reservoir(cs, 0, start)
        food0 = cs.players[0].resources.food
        cs = _use_forest(cs)
        assert cs.players[0].resources.food == food0 + 1
        assert _reservoir(cs, 0) == expected


def test_empty_reservoir_pays_nothing():
    # With the reservoir already at 0, the Forest is still hosted (the owner holds the
    # card) but the auto's eligibility is false (card_state == 0), so no food is paid.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 0)
    food0 = cs.players[0].resources.food
    cs = _use_forest(cs)
    assert cs.players[0].resources.food == food0
    assert _reservoir(cs, 0) == 0


# ---------------------------------------------------------------------------
# Eligibility boundaries: unowned, wrong space
# ---------------------------------------------------------------------------

def test_unowned_does_not_pay_and_not_hosted():
    cs = _card_state()
    cs = _seed_reservoir(cs, 0, 3)          # food on a card the player hasn't played
    food0 = cs.players[0].resources.food
    cs = step(cs, PlaceWorker(space="forest"))
    assert not cs.pending_stack             # atomic fast path (not hosted)
    assert cs.players[0].resources.food == food0   # no payout


def test_non_wood_space_does_not_pay():
    # Clay Pit is an accumulation space but NOT wood — the card is not hooked on it,
    # so it stays atomic and the reservoir is untouched.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 3)
    cs = with_space(cs, "clay_pit", revealed=True)
    food0 = cs.players[0].resources.food
    cs = step(cs, PlaceWorker(space="clay_pit"))
    assert not cs.pending_stack             # not hosted for this card
    assert cs.players[0].resources.food == food0
    assert _reservoir(cs, 0) == 3           # untouched


# ---------------------------------------------------------------------------
# Renovate: restock to 3 (every renovate type, regardless of remaining)
# ---------------------------------------------------------------------------

def test_renovate_restocks_to_three():
    # Wood->clay renovate costs 2 clay + 1 reed. Start with a partly-drained reservoir.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 1)
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,        # applies the renovate; after_renovate auto restocks
        Stop(),               # pop PendingRenovate after-phase
        Proceed(),            # flip the host to its after-phase
        Stop(),               # pop the host
    ])
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert _reservoir(cs, 0) == 3            # restocked to 3 (was 1)


def test_renovate_restocks_to_three_not_topup():
    # A restock-TO-3, not a +3 top-up: a reservoir at 2 becomes 3, not 5.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 2)
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(), Proceed(), Stop(),
    ])
    assert _reservoir(cs, 0) == 3            # 2 -> 3, not 2 + 3


def test_clay_to_stone_renovate_also_restocks():
    # "Each time you renovate" covers clay->stone too (not just wood->clay).
    # Clay->stone renovate costs 1 stone + 1 reed per room (2 rooms by default).
    cs = _renovate_setup(HouseMaterial.CLAY, stone=2, reed=2)
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 0)          # fully drained
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(), Proceed(), Stop(),
    ])
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert _reservoir(cs, 0) == 3           # drained 0 -> restocked to 3


# ---------------------------------------------------------------------------
# Scoping: the reservoir is per-player (the opponent's card is not touched)
# ---------------------------------------------------------------------------

def test_reservoir_is_per_player():
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _own_minor(cs, 1, CARD_ID)
    cs = _seed_reservoir(cs, 0, 3)
    cs = _seed_reservoir(cs, 1, 3)
    cs = _use_forest(cs)                     # P0 uses the Forest
    assert _reservoir(cs, 0) == 2            # P0's reservoir drained
    assert _reservoir(cs, 1) == 3            # P1's untouched (own-action auto)


# ---------------------------------------------------------------------------
# Restock then re-drain: the full lifecycle through the real flow
# ---------------------------------------------------------------------------

def test_drained_then_renovate_restocks_via_real_flow():
    # A renovate restocks a fully-drained reservoir back to 3 (the real flow), so the
    # card is live again for the next wood-space use. Driven on one renovate turn; the
    # subsequent-payout half is covered by the forest tests above (a forest use draws 1
    # from a 3-stocked reservoir), kept on a separate state to avoid crossing turns.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    cs = _own_minor(cs, 0, CARD_ID)
    cs = _seed_reservoir(cs, 0, 0)          # already drained → an empty card
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(), Proceed(), Stop(),
    ])
    assert cs.pending_stack == ()
    assert _reservoir(cs, 0) == 3           # restocked from empty
