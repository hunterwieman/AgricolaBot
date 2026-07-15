"""Tests for Whale Oil (minor improvement, E51; Ephipparius Expansion).

Card text: "Each time you use "Fishing", place 1 food from the general supply on
this card. Each time before you play an occupation, you get food equal to the
amount on this card."
Cost 1 wood; no prereq; no printed VPs.

Two halves, driven through real engine flows:
  FISHING USE — a before_action_space auto on `fishing`, driven through the
    hosted-space lifecycle: +1 food onto the card each use (stacking).
  PLAY-OCCUPATION PAYOUT — a mandatory before_play_occupation auto (the Bookshelf
    template) granting food equal to the card's stored amount WITHOUT consuming
    it (a growing multiplier), plus the occupation-food-source that lets the
    affordability gate see that food. Covers registration, the payout amount +
    card-not-consumed, firing on each play, the affordability gate, and scoping.
"""
import agricola.cards.whale_oil  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "whale_oil"

# Real registered occupations (committing one runs OCCUPATIONS[cid].on_play); the
# fillers only pad the pool to the deal requirement.
_OCCS = ("priest", "stable_architect", "consultant", "childless", "soldier") \
    + tuple(f"o{i}" for i in range(20))
_POOL = CardPool(occupations=_OCCS, minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))


def _held(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


# --------------------------------------------------------------------------- fishing flow

def _fishing_state(seed=5, *, held=0, food_on_fishing=1, owner_seat=None):
    """Owner (default the active seat) holds Whale Oil with `held` food; the
    Fishing space is stocked + free."""
    s, _env = setup_env(seed, card_pool=_POOL)
    cp = s.current_player
    idx = cp if owner_seat is None else owner_seat
    p = fast_replace(
        s.players[idx],
        minor_improvements=s.players[idx].minor_improvements | {CARD_ID},
        card_state=s.players[idx].card_state.set(CARD_ID, held),
    )
    s = fast_replace(s, players=tuple(p if i == idx else s.players[i] for i in range(2)),
                     current_player=cp)
    sp = fast_replace(get_space(s.board, "fishing"), accumulated_amount=food_on_fishing)
    s = fast_replace(s, board=with_space(s.board, "fishing", sp))
    return s, idx


def _use_fishing(state):
    """Hosted Fishing lifecycle for an automatic-only owner: place, Proceed, Stop."""
    state = step(state, PlaceWorker(space="fishing"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# --------------------------------------------------------------------------- occupation flow

def _occ_state(*, owned_occ=(), hand=("childless",), owned_minors=(CARD_ID,),
               held=None, food=0):
    """Active seat owns `owned_minors` (Whale Oil at `held` food) and `owned_occ`
    played occupations, with `hand` occupations in hand and `food` on hand."""
    s, _env = setup_env(5, card_pool=_POOL)
    cp = s.current_player
    p = fast_replace(
        s.players[cp],
        occupations=frozenset(owned_occ),
        minor_improvements=frozenset(owned_minors),
        hand_occupations=frozenset(hand),
        resources=Resources(food=food),
    )
    if held is not None and CARD_ID in owned_minors:
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    return s, cp


def _to_play_occupation(s):
    s = step(s, PlaceWorker(space="lessons"))
    s = step(s, ChooseSubAction(name="play_occupation"))
    return s


def _spaces(s):
    return {a.space for a in legal_placements(s)}


# --------------------------------------------------------------------------- registration

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert CARD_ID in OCCUPATION_FOOD_SOURCES
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("before_action_space", ()))
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("before_play_occupation", ()))
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["fishing"]


# --------------------------------------------------------------------------- fishing use

def test_fishing_places_one_food_on_card():
    s, idx = _fishing_state(held=0)
    out = _use_fishing(s)
    assert _held(out, idx) == 1


def test_fishing_stacks_on_card():
    s, idx = _fishing_state(held=1)
    out = _use_fishing(s)
    assert _held(out, idx) == 2


def test_fishing_not_hosted_for_non_owner():
    # P1 owns Whale Oil; P0 uses fishing -> not hosted (own-use hook).
    s, idx = _fishing_state(held=3, owner_seat=1)
    assert idx == 1
    assert not should_host_space(s, "fishing", 0)


# --------------------------------------------------------------------------- occupation payout

def test_payout_equals_card_amount_and_card_kept():
    # Hold 2 on the card; play a FREE first occupation -> gain exactly 2 food,
    # card stays 2 (not consumed).
    s, cp = _occ_state(owned_occ=(), hand=("childless",), held=2, food=0)
    s = _to_play_occupation(s)
    assert s.players[cp].resources.food == 2      # +2 from the card, before the cost
    assert _held(s, cp) == 2                       # card NOT consumed
    s = step(s, CommitPlayOccupation(card_id="childless"))
    assert s.players[cp].resources.food == 2      # first play free -> stays 2
    assert _held(s, cp) == 2


def test_payout_tracks_a_larger_amount():
    s, cp = _occ_state(owned_occ=(), hand=("childless",), held=3, food=0)
    s = _to_play_occupation(s)
    assert s.players[cp].resources.food == 3      # payout == amount on the card
    assert _held(s, cp) == 3


def test_payout_fires_on_each_play():
    # Two occupation plays each grant the card amount (the card is a growing
    # multiplier, unchanged between plays). Mirrors bookshelf's per-play test:
    # the second play is stacked (step does not verify legality).
    s, cp = _occ_state(owned_occ=("priest", "stable_architect", "consultant"),
                       hand=("childless", "soldier"), held=2, food=0)
    s = _to_play_occupation(s)
    assert s.players[cp].resources.food == 2      # +2 payout
    s = step(s, CommitPlayOccupation(card_id="childless"))
    assert s.players[cp].resources.food == 1      # 2 - 1 (cost, 3 occ already played)
    s = _to_play_occupation(s)                     # a second, independent play
    assert s.players[cp].resources.food == 3      # 1 + 2 payout again
    assert _held(s, cp) == 2                        # still not consumed


def test_no_payout_when_card_empty():
    # Card empty -> the payout auto does not fire (no FireTrigger either).
    s, cp = _occ_state(owned_occ=(), hand=("childless",), held=0, food=0)
    s = _to_play_occupation(s)
    assert s.players[cp].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_payout_does_not_fire_for_non_owner():
    # Acting seat does NOT own Whale Oil -> no payout (0 occupations -> free play).
    s, cp = _occ_state(owned_occ=(), hand=("childless",), owned_minors=(), food=0)
    s = _to_play_occupation(s)
    assert s.players[cp].resources.food == 0


# --------------------------------------------------------------------------- affordability gate

def test_occupation_source_reports_stored_amount():
    src = OCCUPATION_FOOD_SOURCES[CARD_ID]
    s, idx = _fishing_state(held=3)
    assert src(s, idx) == (3, Resources())
    s0, idx0 = _fishing_state(held=0)
    assert src(s0, idx0) is None                   # nothing to offer -> None


def test_lessons_offered_only_via_whale_oil_food():
    # 0 food, no liquidation fuel, 3 occupations played -> next play costs 1 food,
    # payable ONLY via Whale Oil's stored food. Lessons offered iff the card holds
    # enough (>= the 1-food cost); an empty card does not qualify.
    s, _ = _occ_state(owned_occ=("priest", "stable_architect", "consultant"),
                      held=2, food=0)
    assert "lessons" in _spaces(s)
    s_empty, _ = _occ_state(owned_occ=("priest", "stable_architect", "consultant"),
                            held=0, food=0)
    assert "lessons" not in _spaces(s_empty)
    s_unowned, _ = _occ_state(owned_occ=("priest", "stable_architect", "consultant"),
                              owned_minors=(), food=0)
    assert "lessons" not in _spaces(s_unowned)
