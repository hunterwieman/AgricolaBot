import agricola.cards.cottar  # noqa: F401
"""Cottar (E122): a mandatory wood-or-clay choice after each improvement
(user ruling 2026-07-15: the improvement's ordinary after window)."""
from agricola.actions import (
    ChooseSubAction,
    CommitCardChoice,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_build_major, sole_play_minor

CARD_ID = "cottar"

_POOL = CardPool(
    occupations=(CARD_ID, "consultant") + tuple(f"o{i}" for i in range(18)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal(state, sid):
    sp = fast_replace(get_space(state.board, sid), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, sid, sp))


def _hand_minor(state, idx, cid):
    p = fast_replace(state.players[idx],
                     hand_minors=state.players[idx].hand_minors | {cid})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_registered_mandatory_on_both_events():
    assert CARD_ID in OCCUPATIONS
    assert CARDS[CARD_ID].mandatory


def _drive_minor_play(cs, cp):
    cs = with_resources(cs, cp, grain=1)      # Market Stall's 1-grain cost
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    return step(cs, sole_play_minor(cs, "market_stall"))


def test_minor_play_forces_the_choice_then_pays():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _own(_reveal(cs, "major_improvement"), cp)
    cs = _hand_minor(cs, cp, "market_stall")
    cs = _drive_minor_play(cs, cp)

    # The after-window withholds Stop: only Cottar's fire is legal.
    acts = legal_actions(cs)
    assert Stop() not in acts
    assert FireTrigger(card_id=CARD_ID) in acts
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert isinstance(cs.pending_stack[-1], PendingCardChoice)
    wood0 = cs.players[cp].resources.wood
    cs = step(cs, CommitCardChoice(index=0))
    assert cs.players[cp].resources.wood == wood0 + 1
    # Choice resolved: the host's Stop is legal again.
    assert Stop() in legal_actions(cs)


def test_clay_option():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _own(_reveal(cs, "major_improvement"), cp)
    cs = _hand_minor(cs, cp, "market_stall")
    cs = _drive_minor_play(cs, cp)
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    clay0 = cs.players[cp].resources.clay
    cs = step(cs, CommitCardChoice(index=1))
    assert cs.players[cp].resources.clay == clay0 + 1


def test_major_build_forces_the_choice():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _own(_reveal(cs, "major_improvement"), cp)
    cs = with_resources(cs, cp, clay=2)          # Fireplace (idx 0) costs 2 clay
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))

    acts = legal_actions(cs)
    assert Stop() not in acts and FireTrigger(card_id=CARD_ID) in acts
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    wood0 = cs.players[cp].resources.wood
    cs = step(cs, CommitCardChoice(index=0))
    assert cs.players[cp].resources.wood == wood0 + 1
    assert Stop() in legal_actions(cs)


def test_own_occupation_play_does_not_fire():
    # An occupation is not an improvement: playing one (at Lessons) never
    # withholds Stop nor offers Cottar.
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _own(cs, cp)
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"consultant"}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    from agricola.actions import CommitPlayOccupation
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    acts = legal_actions(cs)
    assert Stop() in acts
    assert FireTrigger(card_id=CARD_ID) not in acts


def test_opponent_improvement_pays_nothing():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    cs = _own(_reveal(cs, "major_improvement"), opp)   # the OPPONENT owns Cottar
    cs = _hand_minor(cs, cp, "market_stall")
    cs = _drive_minor_play(cs, cp)
    # The acting player doesn't own Cottar: Stop is free, no trigger.
    acts = legal_actions(cs)
    assert Stop() in acts
    assert FireTrigger(card_id=CARD_ID) not in acts


def test_hand_only_inert():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    cs = _reveal(cs, "major_improvement")
    p = fast_replace(cs.players[cp],
                     hand_occupations=cs.players[cp].hand_occupations | {CARD_ID})
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    cs = _hand_minor(cs, cp, "market_stall")
    cs = _drive_minor_play(cs, cp)
    assert Stop() in legal_actions(cs)
