"""Tests for Angler (occupation, A95).

Card text: "Each time after you use the \"Fishing\" Accumulation space while
there are at most 2 food on that space, you get a \"Major or Minor Improvement\"
action."

Classification: the condition is the PRE-TAKE food count on Fishing (0/1/2
qualifies; 3+ does not); Fishing sweeps its whole pile at the take, so the food
that was on the space == the host frame's `taken.food` (Refactor A). The grant is
an OPTIONAL after_action_space trigger on the fishing host that reads
`taken.food <= 2` and pushes a PendingMajorMinorImprovement (the Merchant
composite-push idiom), gated on the composite having a legal child right now.
"""
import agricola.cards.angler  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=("angler",) + tuple(f"o{i}" for i in range(20)),
    minors=("corn_scoop",) + tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id="angler")


def _angler_offered(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == "angler"
               for a in legal_actions(state))


def _state(*, seed=5, occ=("angler",), hand_occ=(), minors=(), res=None, food_on_fishing=1):
    """Card-mode state: current player owns `occ` / holds `minors` in hand with
    resources `res`; the fishing space holds `food_on_fishing` food and is free.
    Opponent's hand is emptied so it can never play (keeps flows deterministic)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "fishing"),
                      workers=(0, 0), accumulated_amount=food_on_fishing)
    cs = fast_replace(cs, board=with_space(cs.board, "fishing", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     hand_occupations=frozenset(hand_occ),
                     hand_minors=frozenset(minors),
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _use_fishing(state):
    """Drive the hosted Fishing lifecycle up to the after window (take included)."""
    state = step(state, PlaceWorker(space="fishing"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())               # the take: food to player, space zeroed
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "angler" in OCCUPATIONS
    # No before_action_space auto anymore — the after-window trigger reads taken.food.
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "angler" not in before_ids
    trig = next(e for e in TRIGGERS.get("after_action_space", ())
                if e.card_id == "angler")
    assert not trig.mandatory                            # a granted action is optional
    assert "angler" in OWN_ACTION_HOOK_CARDS["fishing"]  # atomic space is hosted


# ---------------------------------------------------------------------------
# The condition band: pre-take count 0/1/2 offers, 3+ does not
# ---------------------------------------------------------------------------

def test_offered_at_one_food():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=1)
    cs = _use_fishing(cs)
    assert cs.players[cp].resources.food == 1            # the take happened
    assert _angler_offered(cs)


def test_offered_at_two_food():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=2)
    cs = _use_fishing(cs)
    assert cs.players[cp].resources.food == 2
    assert _angler_offered(cs)


def test_offered_at_zero_food():
    # Unreachable in real play (Fishing refills every round) but "at most 2"
    # covers it harmlessly.
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=0)
    cs = _use_fishing(cs)
    assert _angler_offered(cs)


def test_not_offered_at_three_food():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=3)
    cs = _use_fishing(cs)
    assert cs.players[cp].resources.food == 3            # the take still happened
    assert not _angler_offered(cs)


# ---------------------------------------------------------------------------
# POSITIVE: fire -> build a major end-to-end through the granted composite
# ---------------------------------------------------------------------------

def test_fire_build_major_end_to_end():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=2)
    cs = _use_fishing(cs)

    assert _angler_offered(cs)
    cs = step(cs, _FIRE)                     # granted composite pushed
    top = cs.pending_stack[-1]
    assert type(top).PENDING_ID == "major_minor_improvement"
    assert top.initiated_by_id == "card:angler"

    from tests.test_utils import sole_build_major
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())                    # pop build-major -> composite flips
    cs = step(cs, Stop())                    # pop the granted composite

    # Back at the fishing host's after phase: latched once per use.
    assert not _angler_offered(cs)
    cs = step(cs, Stop())                    # pop the fishing host; turn ends

    assert cs.board.major_improvement_owners[0] == cp
    assert cs.players[cp].resources.clay == 0
    assert cs.players[cp].resources.food == 2


# ---------------------------------------------------------------------------
# POSITIVE: fire -> play a minor through the granted composite
# ---------------------------------------------------------------------------

def test_fire_play_minor_end_to_end():
    cs, cp = _state(minors=("corn_scoop",), res=Resources(wood=1), food_on_fishing=1)
    cs = _use_fishing(cs)

    assert _angler_offered(cs)
    cs = step(cs, _FIRE)

    from tests.test_utils import sole_play_minor
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "corn_scoop"))     # pays the 1 wood
    cs = step(cs, Stop())                    # pop play-minor -> composite flips
    cs = step(cs, Stop())                    # pop the granted composite
    cs = step(cs, Stop())                    # pop the fishing host

    assert "corn_scoop" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0


# ---------------------------------------------------------------------------
# Eligibility: nothing buildable or playable -> not offered (no dead host)
# ---------------------------------------------------------------------------

def test_not_offered_when_nothing_buildable_or_playable():
    # 2 food on the space qualifies, but no resources and no hand minor ->
    # the granted composite would have no legal child.
    cs, cp = _state(res=Resources(), food_on_fishing=2)
    cs = _use_fishing(cs)
    assert not _angler_offered(cs)


# ---------------------------------------------------------------------------
# Optionality: declinable (Stop without firing)
# ---------------------------------------------------------------------------

def test_declinable():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=1)
    cs = _use_fishing(cs)

    assert _angler_offered(cs)
    assert any(isinstance(a, Stop) for a in legal_actions(cs))
    cs = step(cs, Stop())                    # decline: pop the host instead

    assert all(f.PENDING_ID != "major_minor_improvement" for f in cs.pending_stack)
    assert cs.board.major_improvement_owners[0] is None
    assert cs.players[cp].resources.clay == 2            # nothing was spent
    assert cs.players[cp].resources.food == 1            # the take still happened


# ---------------------------------------------------------------------------
# The condition is per-use — each use reads its own taken.food, nothing leaks
# ---------------------------------------------------------------------------

def test_condition_is_per_use_no_leak():
    # First use at 3 food: not offered (this use's taken.food == 3 > 2).
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=3)
    cs = _use_fishing(cs)
    assert not _angler_offered(cs)
    cs = step(cs, Stop())                    # end the turn

    # Later use at 2 food: this use's OWN taken.food == 2 -> offered. There is no
    # cross-use state to leak (each use reads its own `taken`, not a stored snapshot).
    sp = fast_replace(get_space(cs.board, "fishing"),
                      workers=(0, 0), accumulated_amount=2)
    cs = fast_replace(cs, board=with_space(cs.board, "fishing", sp),
                      current_player=cp)
    cs = _use_fishing(cs)
    assert _angler_offered(cs)


# ---------------------------------------------------------------------------
# Opponent's Fishing use -> nothing (own-action hook, atomic for the opponent)
# ---------------------------------------------------------------------------

def test_opponent_use_is_atomic_and_grants_nothing():
    cs, cp = _state(res=Resources(clay=2), food_on_fishing=1)
    cs = fast_replace(cs, current_player=1 - cp)         # the non-owner acts
    out = step(cs, PlaceWorker(space="fishing"))
    # No host frame for the non-owner -> atomic fast path, no window anywhere.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[1 - cp].resources.food == cs.players[1 - cp].resources.food + 1


# ---------------------------------------------------------------------------
# Hand-only is inert
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    cs, cp = _state(occ=(), hand_occ=("angler",), res=Resources(clay=2),
                    food_on_fishing=1)
    out = step(cs, PlaceWorker(space="fishing"))
    # A hand card cannot fire: the space stays atomic, no host frame, no offer.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[cp].resources.food == 1
