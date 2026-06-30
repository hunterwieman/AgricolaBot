"""Tests for Woodcraft (minor improvement, C58; Corbarius Expansion).

Card text: "Each time you use a wood accumulation space, if immediately
afterward you have at most 5 wood in your supply, you get 1 food."
Prerequisite: 1 Occupation. No spendable cost, no printed VPs, not passing.

Shape: a MANDATORY, choice-free `after_action_space` automatic effect on the
atomic-hosted Forest (the only wood accumulation space on the 2-player board).
The atomic Forest host runs its +3 wood pickup on Proceed FIRST, then flips to
the after-phase where the auto fires — so the "at most 5 wood" threshold reads
the POST-pickup supply. There is no FireTrigger: the food is granted on the
Proceed step itself (declining is not possible — it is income, not a
conversion). The prereq is 1 Occupation (`min_occupations=1`).
"""
from __future__ import annotations

import agricola.cards.woodcraft  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, OCCUPATIONS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "woodcraft"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _with_n_occupations(state, idx, n):
    p = state.players[idx]
    occs = frozenset(f"occ{i}" for i in range(n))
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=occs) if i == idx else state.players[i]
        for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_woodcraft_registered():
    assert CARD_ID in MINORS
    assert CARD_ID not in OCCUPATIONS                  # it is a minor, not an occupation
    # Mandatory automatic after_action_space effect (NOT a declinable trigger).
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert CARD_ID in auto_ids
    trig_ids = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID not in trig_ids                     # not a FireTrigger
    # Hosts the atomic Forest space.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())
    # Rides after_action_space, not before.
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID not in before_ids


def test_spec_no_cost_no_vps_min_one_occupation():
    spec = MINORS[CARD_ID]
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 1                   # prereq: 1 Occupation
    # No spendable cost (empty Cost()).
    assert spec.cost == Cost()


def test_prereq_requires_one_occupation():
    s, cp = _card_state()
    spec = MINORS[CARD_ID]
    # 0 occupations → prereq not met.
    s0 = _with_n_occupations(s, cp, 0)
    assert prereq_met(spec, s0, cp) is False
    # 1 occupation → prereq met.
    s1 = _with_n_occupations(s, cp, 1)
    assert prereq_met(spec, s1, cp) is True


def test_on_play_is_noop():
    s, cp = _card_state()
    after = MINORS[CARD_ID].on_play(s, 0)
    assert after == s


# ---------------------------------------------------------------------------
# Hosting: Forest is atomic but hosted once the card is owned
# ---------------------------------------------------------------------------

def test_forest_hosted_when_owned():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = step(s, PlaceWorker(space="forest"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    # No optional trigger surfaces (mandatory auto) → only Proceed is legal.
    assert legal_actions(s) == [Proceed()]


def test_forest_atomic_when_not_owned():
    # Without the card, Forest is NOT hosted (atomic fast path): no food bonus.
    s, cp = _card_state()
    s = with_resources(s, cp, wood=0, food=0)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                          # resolved atomically
    assert s.players[cp].resources.wood == 3            # +3 pickup, no host
    assert s.players[cp].resources.food == 0            # no woodcraft food


# ---------------------------------------------------------------------------
# The effect via the real engine flow — threshold read POST-pickup (+3 wood)
# ---------------------------------------------------------------------------

def test_grants_food_when_at_most_five_after_pickup():
    # 0 wood + 3 pickup = 3 <= 5 → +1 food.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=0, food=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())                              # +3 wood, flip to after, fire auto
    assert s.pending_stack[-1].phase == "after"
    assert s.players[cp].resources.wood == 3            # post-pickup
    assert s.players[cp].resources.food == 1            # woodcraft granted 1 food
    s = step(s, Stop())
    assert s.pending_stack == ()


def test_boundary_exactly_five_after_pickup_grants():
    # 2 wood + 3 pickup = 5 <= 5 → +1 food (the boundary, "at most 5").
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=2, food=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[cp].resources.wood == 5            # exactly 5
    assert s.players[cp].resources.food == 1            # granted


def test_boundary_six_after_pickup_does_not_grant():
    # 3 wood + 3 pickup = 6 > 5 → no food (just over the threshold).
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=3, food=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[cp].resources.wood == 6            # post-pickup, over threshold
    assert s.players[cp].resources.food == 0            # NOT granted
    s = step(s, Stop())
    assert s.pending_stack == ()


def test_abundant_wood_no_food():
    # 10 wood + 3 pickup = 13 > 5 → no food.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10, food=0)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[cp].resources.wood == 13
    assert s.players[cp].resources.food == 0


# ---------------------------------------------------------------------------
# Scoping — fires each time the wood space is used (no once-per-game/round cap)
# ---------------------------------------------------------------------------

def test_fires_again_on_a_later_forest_use():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=0, food=0)

    # First use.
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[cp].resources.food == 1
    s = step(s, Stop())
    assert s.pending_stack == ()

    # Re-arm: reset the player's wood to 0 (keep the 1 food from the first use),
    # clear Forest's worker, and take that player's turn again.
    s = with_resources(s, cp, wood=0, food=1)
    forest = fast_replace(get_space(s.board, "forest"), workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "forest", forest))
    s = fast_replace(s, current_player=cp)

    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    assert s.players[cp].resources.food == 2            # fired a second time
    s = step(s, Stop())
    assert s.pending_stack == ()


# ---------------------------------------------------------------------------
# Wrong space — a non-wood accumulation space does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit is an accumulation space, but CLAY not wood — Woodcraft is not
    # hooked on it, so the space stays atomic (no host) and no food is granted.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=0, food=0)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not s.pending_stack                          # resolved atomically
    assert s.players[cp].resources.food == 0            # no woodcraft food
