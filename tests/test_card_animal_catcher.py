"""Tests for Animal Catcher (C168) — an occupation: each time you use the Day Laborer
action space, instead of 2 food you CAN get 3 different animals from the general supply;
if you do, you pay 1 food each remaining harvest (per swap).

An optional `before_action_space` FireTrigger on the atomic Day Laborer host (hooked via
register_action_space_hook). Firing has two INDEPENDENT halves plus a latch:
(1) suppress Day Laborer's +2 food — the space grants nothing, so `taken.food == 0` and
"got food from a space" reactors (Kindling Gatherer) do NOT fire; (2) grant 1 sheep +
1 boar + 1 cattle from the general supply (via the accommodation barrier); (3) bump a
CardStore tax counter the feeding fold reads (+1 food per remaining harvest, per swap).
Declinable — Proceed runs the normal +2 food.
"""
import agricola.cards.animal_catcher  # noqa: F401  (registers the card)
import agricola.cards.kindling_gatherer  # noqa: F401  (property-1 interaction)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, should_host_space
from agricola.engine import step
from agricola.helpers import feeding_requirement
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env

CARD_ID = "animal_catcher"
_FT = FireTrigger(card_id=CARD_ID)
_POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                 minors=tuple(f"m{i}" for i in range(20)))


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx, *occ):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | set(occ)) if i == idx
        else state.players[i] for i in range(2)))


def _give_capacity(state, idx):
    """Three 1-cell pastures → capacity to house 1 sheep + 1 boar + 1 cattle (one per
    pasture), so the swap's grant fits without a barrier prompt."""
    fy = state.players[idx].farmyard
    pastures = tuple(Pasture(cells=frozenset({(0, c)}), num_stables=0, capacity=2)
                     for c in range(3))
    p = fast_replace(state.players[idx], farmyard=fast_replace(fy, pastures=pastures))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _swap_flow(state):
    """place on Day Laborer → fire the swap → Proceed (suppressed) → Stop."""
    state = step(state, PlaceWorker(space="day_laborer"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert _FT in legal_actions(state)
    state = step(state, _FT)                        # barrier houses the 3 animals inline
    assert Proceed() in legal_actions(state) and _FT not in legal_actions(state)
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def test_registration_and_hosting():
    assert CARD_ID in OCCUPATIONS
    s = _card_state()
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s          # no on-play effect
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["day_laborer"]  # atomic space hooked
    s = _own(s, 0, CARD_ID)
    assert should_host_space(s, "day_laborer", 0)
    assert not should_host_space(s, "day_laborer", 1)       # opponent doesn't own it


def test_swap_suppresses_food_and_grants_animals():
    s = _give_capacity(_own(_card_state(), 0, CARD_ID), 0)
    food0 = s.players[0].resources.food
    a0 = s.players[0].animals
    out = _swap_flow(s)
    # (1) Suppression: NO +2 food.
    assert out.players[0].resources.food == food0
    # (2) The alternate reward: 3 different animals.
    assert out.players[0].animals.sheep == a0.sheep + 1
    assert out.players[0].animals.boar == a0.boar + 1
    assert out.players[0].animals.cattle == a0.cattle + 1
    # (3) Tax latched.
    assert out.players[0].card_state.get(CARD_ID, 0) == 1


def test_decline_takes_two_food_no_tax():
    s = _own(_card_state(), 0, CARD_ID)
    food0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    assert _FT in legal_actions(s)
    s = step(s, Proceed())                          # decline → normal Day Laborer
    s = step(s, Stop())
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].animals.sheep == 0
    assert s.players[0].card_state.get(CARD_ID, 0) == 0   # no tax when declined


def test_swap_neutralizes_kindling_gatherer():
    """Property 1: taking the swap makes taken.food == 0, so Kindling Gatherer (owned)
    does NOT fire its +1 wood — with zero special-casing in either card."""
    s = _give_capacity(_own(_card_state(), 0, CARD_ID, "kindling_gatherer"), 0)
    wood0 = s.players[0].resources.wood
    out = _swap_flow(s)
    assert out.players[0].resources.wood == wood0   # no +1 wood: no food was taken


def test_decline_lets_kindling_fire():
    """The mirror: declining leaves the +2 food (taken.food == 2), so Kindling Gatherer
    fires +1 wood — confirming the suppression, not the hook, is what silences it."""
    s = _own(_card_state(), 0, CARD_ID, "kindling_gatherer")
    food0 = s.players[0].resources.food
    wood0 = s.players[0].resources.wood
    s = step(s, PlaceWorker(space="day_laborer"))
    s = step(s, Proceed())
    s = step(s, Stop())
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].resources.wood == wood0 + 1   # kindling fired on the 2 food


def test_feeding_tax_after_one_swap():
    base = feeding_requirement(_own(_card_state(), 0, CARD_ID), 0)   # owned, counter 0
    out = _swap_flow(_give_capacity(_own(_card_state(), 0, CARD_ID), 0))
    assert feeding_requirement(out, 0) == base + 1


def test_feeding_tax_stacks_per_swap():
    """Two swaps → +2 food per remaining harvest (the live-counter fold)."""
    s = _own(_card_state(), 0, CARD_ID)
    base = feeding_requirement(s, 0)
    p = s.players[0]
    s2 = fast_replace(s, players=tuple(
        fast_replace(p, card_state=p.card_state.set(CARD_ID, 2)) if i == 0
        else s.players[i] for i in range(2)))
    assert feeding_requirement(s2, 0) == base + 2
