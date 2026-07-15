"""Tests for Seed Seller (occupation, D141).

Card text: "When you play this card, you immediately get 1 grain. Each time you use the
'Grain Seeds' action space, you get 1 additional grain."

- on-play: +1 grain (exercised via the registered on_play).
- a Category-3 automatic-income hook on Grain Seeds: +1 grain in the before-window each
  time the owner uses the space, driven end-to-end through the hosted-atomic lifecycle.
"""
import agricola.cards.seed_seller  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("seed_seller",) + tuple(f"o{i}" for i in range(20)),
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
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def test_registration():
    assert "seed_seller" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "seed_seller" in auto_ids
    assert "seed_seller" in OWN_ACTION_HOOK_CARDS["grain_seeds"]


def test_on_play_gives_one_grain():
    s = fast_replace(_card_state(), current_player=0)
    before = s.players[0].resources.grain
    out = OCCUPATIONS["seed_seller"].on_play(s, 0)
    assert out.players[0].resources.grain == before + 1


def test_grain_seeds_gives_one_additional_grain():
    s = fast_replace(_own(_card_state(), 0, "seed_seller"), current_player=0)
    before = s.players[0].resources.grain
    out = _play_hosted_space(s, "grain_seeds")
    # +1 (the space) + 1 (Seed Seller's before-window auto).
    assert out.players[0].resources.grain == before + 1 + 1


def test_not_owned_is_atomic_single_grain():
    s = fast_replace(_card_state(), current_player=0)
    before = s.players[0].resources.grain
    out = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.grain == before + 1
