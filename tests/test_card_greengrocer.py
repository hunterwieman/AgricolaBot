"""Tests for Greengrocer (occupation, B142).

Card text: "Each time you use the 'Grain Seeds' action space, you also get 1 vegetable."

A Category-3 automatic-income hook on Grain Seeds: +1 veg in the before-window each time
the owner uses the space. Driven end-to-end through the hosted-atomic lifecycle.
"""
import agricola.cards.greengrocer  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space

_POOL = CardPool(
    occupations=("greengrocer",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *occupations):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _play_hosted_space(state, space_id):
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def test_registration():
    assert "greengrocer" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "greengrocer" in auto_ids
    assert "greengrocer" in OWN_ACTION_HOOK_CARDS["grain_seeds"]


def test_grain_seeds_gives_one_vegetable():
    s = fast_replace(_own(_card_state(), 0, "greengrocer"), current_player=0)
    before_veg = s.players[0].resources.veg
    before_grain = s.players[0].resources.grain
    out = _play_hosted_space(s, "grain_seeds")
    assert out.players[0].resources.veg == before_veg + 1          # Greengrocer
    assert out.players[0].resources.grain == before_grain + 1      # the space's 1 grain


def test_does_not_fire_on_other_spaces():
    # Greengrocer only hooks grain_seeds; using Forest stays atomic -> no veg.
    s = fast_replace(_own(_card_state(), 0, "greengrocer"), current_player=0)
    before_veg = s.players[0].resources.veg
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.veg == before_veg


def test_not_owned_is_atomic_no_veg():
    s = fast_replace(_card_state(), current_player=0)
    before_veg = s.players[0].resources.veg
    out = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.veg == before_veg
    assert out.players[0].resources.grain == s.players[0].resources.grain + 1
