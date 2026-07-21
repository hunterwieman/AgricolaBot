"""Work Certificate (minor A82): "Each time after you use an action space, you can
take 1 building resource from a building resource accumulation space with at least
4 building resources on it." Clarification: "Can be immediately triggered."
No cost, no VPs; prerequisite "3 Occupations".

An OPTIONAL `after_action_space` play-variant trigger hooked over EVERY space id
(so every own placement is hosted while the card is owned); one variant per legal
(source space, building-resource type) pair, e.g. "forest:wood". The threshold is
a TYPELESS total (>= 4 building resources in any mix); firing debits the space's
accumulated stock and credits the owner. Mechanism approved by user ruling
2026-07-20 (deferred-plans cluster C3).
"""
import agricola.cards.work_certificate  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.work_certificate import CARD_ID
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_resources, with_space
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, forest=Resources(wood=3), clay_pit=Resources(clay=1),
           own=True, current_player=0):
    """A CARDS-mode state, `current_player` to move, Forest/Clay Pit stocks set
    explicitly, that player (by default) owning Work Certificate."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player)     # zero everything
    state = with_space(state, "forest", revealed=True, accumulated=forest)
    state = with_space(state, "clay_pit", revealed=True, accumulated=clay_pit)
    if own:
        state = _own(state, current_player, CARD_ID)
    return state


def _wc_variants(opts):
    """The Work Certificate variants surfaced among legal actions."""
    return {a.variant for a in opts
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID}


def _use_grain_seeds(state):
    """Drive a full atomic-space use (hosted, since Work Certificate hooks every
    space) up to its after window: place on Grain Seeds, Proceed (take the grain)."""
    state = step(state, PlaceWorker(space="grain_seeds"))
    assert [type(a).__name__ for a in legal_actions(state)] == ["Proceed"]
    state = step(state, Proceed())
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.triggers import (
        OWN_ACTION_HOOK_CARDS,
        PLAY_VARIANT_TRIGGERS,
        TRIGGERS,
    )
    from agricola.constants import SPACE_IDS
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                 # no cost
    assert spec.vps == 0                       # no VPs
    assert spec.min_occupations == 3           # prereq "3 Occupations"
    assert not spec.passing_left
    # optional trigger on the AFTER window of an action space
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    # hooked over EVERY canonical space id (own-use)
    for space_id in SPACE_IDS:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())


# ---------------------------------------------------------------------------
# Threshold boundary: 3 total -> not offered; 4 total -> offered
# ---------------------------------------------------------------------------

def test_three_on_space_not_offered():
    # Forest holds 3 wood (< 4); Clay Pit 1 clay; nothing else qualifies.
    s = _state(forest=Resources(wood=3))
    s = _use_grain_seeds(s)
    opts = legal_actions(s)
    assert _wc_variants(opts) == set()
    assert any(isinstance(a, Stop) for a in opts)


def test_four_on_space_offered_and_arithmetic():
    # Forest holds exactly 4 wood -> the take is offered; firing moves 1 wood
    # space -> player (space -1, player +1).
    s = _state(forest=Resources(wood=4))
    s = _use_grain_seeds(s)
    opts = legal_actions(s)
    assert _wc_variants(opts) == {"forest:wood"}
    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest:wood"))
    assert s.players[0].resources.wood == 1
    assert get_space(s.board, "forest").accumulated == Resources(wood=3)
    # once per use: not re-offered on the same host; Stop ends the turn.
    assert _wc_variants(legal_actions(s)) == set()
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Mixed stock: typeless threshold, one variant per type present, foreign take
# ---------------------------------------------------------------------------

def test_mixed_stock_offers_each_type_and_foreign_take_works():
    # Clay Pit seeded with a MIXED stock via a direct board edit (a card deposit
    # — e.g. Nail Basket's stone — can put foreign types on a space): 2 clay +
    # 1 wood + 1 stone = 4 building resources in total, so it qualifies even
    # though no single type reaches 4 (the printed threshold is typeless).
    s = _state(forest=Resources(wood=3),
               clay_pit=Resources(clay=2, wood=1, stone=1))
    s = _use_grain_seeds(s)
    # one variant per building-resource type PRESENT on the qualifying space
    assert _wc_variants(legal_actions(s)) == {
        "clay_pit:wood", "clay_pit:clay", "clay_pit:stone"}
    # taking the FOREIGN type (stone off the clay space) works
    s = step(s, FireTrigger(card_id=CARD_ID, variant="clay_pit:stone"))
    assert s.players[0].resources.stone == 1
    assert get_space(s.board, "clay_pit").accumulated == Resources(clay=2, wood=1)


def test_two_qualifying_spaces_offer_both():
    s = _state(forest=Resources(wood=5), clay_pit=Resources(clay=4))
    s = _use_grain_seeds(s)
    assert _wc_variants(legal_actions(s)) == {"forest:wood", "clay_pit:clay"}


# ---------------------------------------------------------------------------
# Optionality: decline via Stop costs nothing
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    s = _state(forest=Resources(wood=6))
    s = _use_grain_seeds(s)
    assert _wc_variants(legal_actions(s)) == {"forest:wood"}
    s = step(s, Stop())                        # decline: the host's after-phase Stop
    assert s.players[0].resources.wood == 0    # nothing taken
    assert get_space(s.board, "forest").accumulated == Resources(wood=6)
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Own use only; hand card is inert
# ---------------------------------------------------------------------------

def test_opponent_use_not_hosted_and_offers_nothing():
    # "you use" is own-use only: P0 owns the card, P1's placement stays atomic.
    from agricola.cards.triggers import should_host_space
    s = _state(forest=Resources(wood=6), own=False, current_player=1)
    s = _own(s, 0, CARD_ID)                    # the OWNER is P0; P1 is acting
    assert should_host_space(s, "grain_seeds", 0) is True
    assert should_host_space(s, "grain_seeds", 1) is False
    s = step(s, PlaceWorker(space="grain_seeds"))   # atomic: no host, no trigger
    assert s.players[1].resources.grain == 1
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


def test_hand_card_does_not_host_or_fire():
    from agricola.cards.triggers import should_host_space
    s = _state(forest=Resources(wood=6), own=False)
    p = s.players[0]
    s = fast_replace(s, players=(fast_replace(
        p, hand_minors=frozenset({CARD_ID})), s.players[1]))
    assert should_host_space(s, "grain_seeds", 0) is False
    s = step(s, PlaceWorker(space="grain_seeds"))   # atomic: no host, no trigger
    assert s.players[0].resources.grain == 1
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Prerequisite: "3 Occupations" (a HAVE-check)
# ---------------------------------------------------------------------------

def test_prereq_three_occupations():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=frozenset({"o1", "o2"}))
    cs2 = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    assert not prereq_met(MINORS[CARD_ID], cs2, cp)
    assert CARD_ID not in playable_minors(cs2, cp)
    p3 = fast_replace(p, occupations=frozenset({"o1", "o2", "o3"}))
    cs3 = fast_replace(cs, players=tuple(
        p3 if i == cp else cs.players[i] for i in range(2)))
    assert prereq_met(MINORS[CARD_ID], cs3, cp)
    assert CARD_ID in playable_minors(cs3, cp)     # free cost -> always affordable


# ---------------------------------------------------------------------------
# "Can be immediately triggered": the placement that PLAYS the card fires it
# ---------------------------------------------------------------------------

def test_immediately_triggered_on_the_playing_placement():
    # Play Work Certificate at the Major Improvement space's play-minor branch;
    # the SAME placement's after_action_space window then offers the take.
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    cs = with_space(cs, "forest", revealed=True, accumulated=Resources(wood=6))
    cs = with_resources(cs, cp)                    # zero resources (card is free)
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=frozenset({"o1", "o2", "o3"}))  # meet the prereq
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    assert CARD_ID in cs.players[cp].minor_improvements   # played THIS use
    cs = step(cs, Stop())              # pop the play-minor host's after window
    cs = step(cs, Stop())              # pop the composite improvement host
    # Back at the space host's after window: the just-played card fires NOW.
    opts = legal_actions(cs)
    assert _wc_variants(opts) == {"forest:wood"}
    cs = step(cs, FireTrigger(card_id=CARD_ID, variant="forest:wood"))
    assert cs.players[cp].resources.wood == 1
    assert get_space(cs.board, "forest").accumulated == Resources(wood=5)
    cs = step(cs, Stop())              # pop the space host -> turn over
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
