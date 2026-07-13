"""Tests for Rod Collection (minor E38): place up to 2 wood on the card each time you
use Fishing; score each wood except the 1st/4th/7th/10th."""
import agricola.cards.rod_collection  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.rod_collection import CARD_ID
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own_with_wood(idx=0, wood=2):
    s = _card_state()
    p = fast_replace(
        s.players[idx],
        minor_improvements=s.players[idx].minor_improvements | {CARD_ID},
        resources=Resources(wood=wood),
    )
    s = fast_replace(s, players=tuple(p if i == idx else s.players[i] for i in range(2)))
    return fast_replace(s, current_player=idx)


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _fire_variants(state):
    return sorted(
        a.variant for a in legal_actions(state)
        if isinstance(a, FireTrigger) and a.card_id == CARD_ID
    )


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.min_occupations == 3
    assert spec.vps == 1
    assert spec.cost.resources == Resources()
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("before_action_space", ()))
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["fishing"]
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_prereq_three_occupations():
    state = setup(seed=0)
    spec = MINORS[CARD_ID]
    assert prereq_met(spec, state, 0) is False    # 0 occupations
    p = fast_replace(state.players[0], occupations=frozenset({"a", "b", "c"}))
    state = fast_replace(state, players=(p, state.players[1]))
    assert prereq_met(spec, state, 0) is True


# --- Scoring formula --------------------------------------------------------

def test_scoring_formula_excludes_1_4_7_10():
    score = _score_fn()
    state = setup(seed=0)

    def with_bank(w):
        p = dataclasses.replace(state.players[0],
                                card_state=state.players[0].card_state.set(CARD_ID, w))
        return dataclasses.replace(state, players=(p, state.players[1]))

    expected = {0: 0, 1: 0, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 10: 6, 11: 7}
    for w, pts in expected.items():
        assert score(with_bank(w), 0) == pts, w


# --- Real-flow effect -------------------------------------------------------

def test_offers_both_variants_and_places_two_wood():
    s = _own_with_wood(wood=2)
    s = step(s, PlaceWorker(space="fishing"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert _fire_variants(s) == ["1", "2"]
    assert Proceed() in legal_actions(s)

    s = step(s, FireTrigger(card_id=CARD_ID, variant="2"))
    assert s.players[0].resources.wood == 0                 # 2 spent
    assert s.players[0].card_state.get(CARD_ID, 0) == 2     # 2 banked


def test_place_one_wood_variant():
    s = _own_with_wood(wood=2)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="1"))
    assert s.players[0].resources.wood == 1                 # 1 spent
    assert s.players[0].card_state.get(CARD_ID, 0) == 1


def test_only_one_variant_when_one_wood():
    s = _own_with_wood(wood=1)
    s = step(s, PlaceWorker(space="fishing"))
    assert _fire_variants(s) == ["1"]


def test_no_variant_when_no_wood():
    s = _own_with_wood(wood=0)
    s = step(s, PlaceWorker(space="fishing"))
    assert _fire_variants(s) == []          # nothing to place
    assert Proceed() in legal_actions(s)    # can still take Fishing


def test_once_per_use_then_take_fishing():
    s = _own_with_wood(wood=2)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="1"))
    # After firing, the trigger is spent for this use (host triggers_resolved).
    assert _fire_variants(s) == []
    s = step(s, Proceed())                  # take the Fishing action
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].card_state.get(CARD_ID, 0) == 1


def test_decline_places_no_wood():
    s = _own_with_wood(wood=2)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, Proceed())                  # decline the placement, take Fishing
    s = step(s, Stop())
    assert s.players[0].resources.wood == 2               # untouched
    assert s.players[0].card_state.get(CARD_ID, 0) == 0
