"""Tests for Beaver Colony (minor E33): 1 VP, prereq 1 fenced stable, a "one
pasture-with-stable must be empty" restriction (capacity fold in
test_cards_empty_pasture.py), and a +1 bonus point each time you take reed from an
action space (Reed Bank)."""
import agricola.cards.beaver_colony  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.beaver_colony import CARD_ID, _on_play
from agricola.cards.capacity_mods import EMPTY_PASTURE_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env

from scripts.profile_states import STATES
from tests.factories import with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *card_ids):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost.resources == Resources()             # no cost
    assert any(cid == CARD_ID for cid, _ in EMPTY_PASTURE_CARDS)
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("after_action_space", ()))
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["reed_bank"]
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_prereq_requires_a_fenced_stable():
    s = setup(0)                          # no pastures/stables
    assert prereq_met(MINORS[CARD_ID], s, 0) is False
    s2 = STATES["mid_round_6_basic"]()    # has a pasture-with-stable
    assert prereq_met(MINORS[CARD_ID], s2, 0) is True


# --- Eviction on play -------------------------------------------------------

def test_on_play_flags_accommodation_when_animals_present():
    state = STATES["mid_round_6_basic"]()
    p = fast_replace(state.players[0], animals=Animals(sheep=2))
    state = fast_replace(state, players=(p, state.players[1]))
    out = _on_play(state, 0)
    assert out.players[0].animals_need_accommodation is True


# --- The reed-scoring trigger -----------------------------------------------

def test_reed_bank_use_banks_a_point():
    s = _own(_card_state(), 0, CARD_ID)
    s = fast_replace(s, current_player=0)
    s = with_space(s, "reed_bank", accumulated=Resources(reed=2))
    assert s.players[0].card_state.get(CARD_ID, 0) == 0
    s = step(s, PlaceWorker(space="reed_bank"))
    # The after_action_space auto fires only after the take — nothing banked yet.
    assert s.players[0].card_state.get(CARD_ID, 0) == 0
    s = step(s, Proceed())                                # take the reed → +1 point
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    s = step(s, Stop())
    assert s.players[0].card_state.get(CARD_ID, 0) == 1   # not double-counted
    assert s.players[0].resources.reed == 2               # the reed was taken


def test_no_point_on_a_non_reed_space():
    s = _own(_card_state(), 0, CARD_ID)
    s = fast_replace(s, current_player=0)
    s = step(s, PlaceWorker(space="forest"))              # wood, not reed
    assert s.players[0].card_state.get(CARD_ID, 0) == 0


def test_unowned_player_banks_nothing():
    s = _own(_card_state(), 1, CARD_ID)                   # player 1 owns it
    s = fast_replace(s, current_player=0)                 # player 0 acts
    s = with_space(s, "reed_bank", accumulated=Resources(reed=1))
    s = step(s, PlaceWorker(space="reed_bank"))
    assert s.players[1].card_state.get(CARD_ID, 0) == 0   # only fires on the owner's own use


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    import dataclasses
    score = _score_fn()
    state = setup(0)
    assert score(state, 0) == 0
    p = dataclasses.replace(state.players[0],
                            card_state=state.players[0].card_state.set(CARD_ID, 4))
    state = dataclasses.replace(state, players=(p, state.players[1]))
    assert score(state, 0) == 4
