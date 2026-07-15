"""Tests for Forest Stone (minor improvement, B48; Bubulcus Expansion).

Card text: "Place 2 food on this card. Each time you use a wood accumulation
space, move 1 of these food to your supply. Each time you use a stone
accumulation space, add 2 food to this card."
Cost 2 Wood / 1 Stone (alternative); prereq 1 Occupation; 1 VP.

The three parts are driven through real engine flows:
  ON PLAY — 2 food seeded, driven through the real PendingPlayMinor ->
    CommitPlayMinor flow (each printed alternative cost paid).
  WOOD USE — a before_action_space auto on the wood accumulation space
    (`forest`), driven through the hosted-space lifecycle (place / Proceed /
    Stop): moves 1 food from card to supply, gated on the card holding food.
  STONE USE — a before_action_space auto on the quarries, +2 to the card.
Plus registration and scoping (the host is not pushed for a non-owner's use).
"""
import agricola.cards.forest_stone  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "forest_stone"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, held=None):
    """Own Forest Stone at seat idx, optionally seeding `held` food on the card."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    if held is not None:
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _held(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _play_hosted_space(state, space_id):
    """Drive the automatic-only hosted lifecycle: place, Proceed, Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def _stock_quarry(state, quarry):
    """Reveal + stock a Stage-2/4 quarry so it can host a placement."""
    sp = get_space(state.board, quarry)
    return fast_replace(
        state,
        board=with_space(
            state.board, quarry,
            fast_replace(sp, revealed=True, accumulated=Resources(stone=1)),
        ),
    )


# --------------------------------------------------------------------------- registration

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.alt_costs == (Cost(resources=Resources(stone=1)),)
    assert spec.min_occupations == 1
    assert spec.vps == 1
    assert spec.passing_left is False
    # Two before_action_space autos under this card id (wood drip + stone fill).
    n_autos = sum(1 for e in AUTO_EFFECTS.get("before_action_space", ())
                  if e.card_id == CARD_ID)
    assert n_autos == 2
    # Hosts the wood space and both quarries.
    for sid in ("forest", "western_quarry", "eastern_quarry"):
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[sid]


def test_hosting_decision():
    s = _own(_state(), 0)
    for sid in ("forest", "western_quarry", "eastern_quarry"):
        assert should_host_space(s, sid, 0)
    # Not a hooked space, and not when unowned.
    assert not should_host_space(s, "clay_pit", 0)
    assert not should_host_space(_state(), "forest", 0)


# --------------------------------------------------------------------------- on_play (real flow)

def _play_minor_with(resources):
    """Play Forest Stone through the real PendingPlayMinor flow with `resources`
    on hand and one played occupation (prereq). Returns the post-play state + seat."""
    cs = _state()
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_minors=frozenset({CARD_ID}),
        occupations=cs.players[cp].occupations | {"dummy_occ"},
        resources=resources,
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    return cs, cp


def test_play_seeds_two_food_paying_wood():
    cs, cp = _play_minor_with(Resources(wood=2))
    p = cs.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.wood == 0          # paid the 2-wood alternative
    assert _held(cs, cp) == 2             # on_play placed 2 food on the card


def test_play_pays_stone_alternative():
    cs, cp = _play_minor_with(Resources(stone=1))
    p = cs.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.stone == 0         # paid the 1-stone alternative
    assert _held(cs, cp) == 2


def test_prereq_requires_one_occupation():
    cs = _state()
    cp = cs.current_player
    p0 = fast_replace(cs.players[cp], occupations=frozenset())
    s0 = fast_replace(cs, players=tuple(p0 if i == cp else cs.players[i] for i in range(2)))
    assert not prereq_met(MINORS[CARD_ID], s0, cp)          # 0 occupations -> blocked
    p1 = fast_replace(cs.players[cp], occupations=frozenset({"dummy_occ"}))
    s1 = fast_replace(cs, players=tuple(p1 if i == cp else cs.players[i] for i in range(2)))
    assert prereq_met(MINORS[CARD_ID], s1, cp)              # 1 occupation -> met


# --------------------------------------------------------------------------- wood-space drip

def test_wood_space_moves_one_food_from_card():
    s = fast_replace(_own(_state(), 0, held=2), current_player=0)
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")
    assert _held(out, 0) == 1                              # 2 -> 1 on the card
    assert out.players[0].resources.food == before + 1    # +1 to supply


def test_wood_space_drains_last_food():
    s = fast_replace(_own(_state(), 0, held=1), current_player=0)
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")
    assert _held(out, 0) == 0
    assert out.players[0].resources.food == before + 1


def test_wood_space_noop_when_card_empty():
    s = fast_replace(_own(_state(), 0, held=0), current_player=0)
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")               # still hosted (owned)
    assert _held(out, 0) == 0
    assert out.players[0].resources.food == before      # nothing to move


# --------------------------------------------------------------------------- stone-space fill

def test_western_quarry_adds_two_to_card():
    s = fast_replace(_own(_state(), 0, held=0), current_player=0)
    s = _stock_quarry(s, "western_quarry")
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "western_quarry")
    assert _held(out, 0) == 2                            # +2 on the card
    assert out.players[0].resources.food == before      # player food untouched


def test_eastern_quarry_adds_two_to_card():
    s = fast_replace(_own(_state(), 0, held=3), current_player=0)
    s = _stock_quarry(s, "eastern_quarry")
    out = _play_hosted_space(s, "eastern_quarry")
    assert _held(out, 0) == 5                            # 3 + 2


# --------------------------------------------------------------------------- scoping

def test_does_not_host_or_fire_for_non_owner():
    # P1 owns the card; P0 uses forest -> host not pushed, P1's card untouched.
    s = fast_replace(_own(_state(), 1, held=2), current_player=0)
    assert not should_host_space(s, "forest", 0)
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert _held(out, 1) == 2
