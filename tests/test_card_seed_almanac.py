import agricola.cards.seed_almanac  # noqa: F401
"""Seed Almanac (E18): an optional `after_play_minor` trigger — pay 1 food to plow
1 field each time AFTER you play a (different) minor while owning this card.

The tests drive the real engine flow (place at the Major Improvement space, choose
the play-minor branch, commit a real minor play), then exercise Seed Almanac's
after-window trigger:
  - registration (minor spec + trigger event + food-payment resume);
  - the food-on-hand path (1 food debited, PendingPlow pushed, plow a cell);
  - the OWN-play exclusion ("after this one" — its own play never offers it);
  - the two dead-end gates (no plowable cell; 0 food + nothing liquidatable);
  - the liquidation path (0 food + 1 grain -> PendingFoodPayment -> resume plows);
  - decline via the host's Stop;
  - once per play host.

A test-scoped no-op costless minor (`_TEST_MINOR`) is the "other minor" that fires
the trigger, so the played card grants nothing that could pollute the food/plow
gates. seed_almanac itself is used for the own-play-exclusion test.
"""
from contextlib import contextmanager

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS
from agricola.cards.triggers import CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_fields, with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "seed_almanac"
_TEST_MINOR = "test_seed_almanac_filler"   # costless no-op — the "other minor"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id=CARD_ID)


@contextmanager
def _filler_minor():
    """A test-scoped costless no-op minor to play as the trigger-firing "other
    minor" (grants nothing, so it never perturbs the food/plow gates)."""
    from agricola.cards.specs import register_minor
    register_minor(_TEST_MINOR, cost=Cost())
    try:
        yield
    finally:
        MINORS.pop(_TEST_MINOR, None)


def _replace_player(state, idx, p):
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, cid):
    return _replace_player(state, idx, fast_replace(
        state.players[idx], minor_improvements=state.players[idx].minor_improvements | {cid}))


def _hand_minor(state, idx, cid):
    return _replace_player(state, idx, fast_replace(
        state.players[idx], hand_minors=state.players[idx].hand_minors | {cid}))


def _set_occupations(state, idx, ids):
    return _replace_player(state, idx, fast_replace(
        state.players[idx], occupations=frozenset(ids)))


def _reveal(state, sid):
    sp = fast_replace(get_space(state.board, sid), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, sid, sp))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type.name == "FIELD")


def _drive_play(state, idx, cid):
    """Place at the Major Improvement space and play `cid` via its play-minor branch,
    landing the play-minor host in its after-phase (`after_play_minor` fired)."""
    state = _reveal(state, "major_improvement")
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="play_minor"))
    return step(state, sole_play_minor(state, cid))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_with_cost_and_prereq():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.min_occupations == 4
    assert spec.vps == 0


def test_registered_as_optional_after_play_minor_trigger():
    entry = CARDS[CARD_ID]
    assert entry.event == "after_play_minor"
    assert entry.mandatory is False
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# ---------------------------------------------------------------------------
# The food-on-hand path: pay 1 food, plow 1 field
# ---------------------------------------------------------------------------

def test_pays_one_food_and_plows():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        cs = with_resources(cs, cp, food=2)
        fields0 = _num_fields(cs, cp)
        cs = _drive_play(cs, cp, _TEST_MINOR)

        # After the other minor's play, Seed Almanac is offered (optional: Stop too).
        acts = legal_actions(cs)
        assert _FIRE in acts and Stop() in acts

        cs = step(cs, _FIRE)
        # 1 food debited immediately; a plow is pushed (food was on hand).
        assert cs.players[cp].resources.food == 1
        assert isinstance(cs.pending_stack[-1], PendingPlow)

        cs = step(cs, next(a for a in legal_actions(cs) if isinstance(a, CommitPlow)))
        assert _num_fields(cs, cp) == fields0 + 1


# ---------------------------------------------------------------------------
# "after this one": its OWN play never offers the trigger
# ---------------------------------------------------------------------------

def test_own_play_does_not_offer_trigger():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    # Playable prereq: 4 occupations + 1 reed cost; plenty of food + a plowable cell
    # so the ONLY reason it isn't offered is the own-play exclusion.
    cs = _set_occupations(cs, cp, [f"occ{i}" for i in range(4)])
    cs = with_resources(cs, cp, reed=1, food=3)
    cs = _hand_minor(cs, cp, CARD_ID)
    cs = _drive_play(cs, cp, CARD_ID)

    # Seed Almanac is now owned (its play added it to the tableau) and the host frame
    # is stamped played_card_id == seed_almanac -> the trigger must NOT be offered.
    assert cs.pending_stack[-1].played_card_id == CARD_ID
    acts = legal_actions(cs)
    assert _FIRE not in acts
    assert Stop() in acts


# ---------------------------------------------------------------------------
# Dead-end gates: never offer when the plow or the food is impossible
# ---------------------------------------------------------------------------

def test_not_offered_with_no_plowable_cell():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        cs = with_resources(cs, cp, food=2)
        # Fill every cell with a FIELD: no EMPTY cell remains, so no plow target.
        cs = with_fields(cs, cp, [(r, c) for r in range(3) for c in range(5)])
        cs = _drive_play(cs, cp, _TEST_MINOR)

        acts = legal_actions(cs)
        assert _FIRE not in acts
        assert Stop() in acts


def test_not_offered_with_no_food_and_nothing_liquidatable():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        # 0 food, 0 grain/veg, 0 animals (no cooking improvement) -> 1 food unpayable.
        cs = with_resources(cs, cp)   # all zero
        cs = _drive_play(cs, cp, _TEST_MINOR)

        acts = legal_actions(cs)
        assert _FIRE not in acts
        assert Stop() in acts


# ---------------------------------------------------------------------------
# Liquidation path: 0 food + 1 grain -> PendingFoodPayment -> resume plows
# ---------------------------------------------------------------------------

def test_liquidation_pays_one_food_then_plows():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        cs = with_resources(cs, cp, grain=1)   # 0 food, 1 convertible grain
        fields0 = _num_fields(cs, cp)
        cs = _drive_play(cs, cp, _TEST_MINOR)

        # Liquidatable -> the trigger is offered even with 0 food on hand.
        assert _FIRE in legal_actions(cs)
        cs = step(cs, _FIRE)

        # Food short: a raise-only PendingFoodPayment for this card is pushed.
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingFoodPayment)
        assert top.food_needed == 1 and top.resume_kind == CARD_ID
        opts = legal_actions(cs)
        assert opts and all(isinstance(a, CommitFoodPayment) for a in opts)

        # Convert the grain: food raised (1) then debited (1) -> 0; grain spent; plow pushed.
        want = CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)
        cs = step(cs, next(a for a in opts if a == want))
        assert cs.players[cp].resources.food == 0
        assert cs.players[cp].resources.grain == 0
        assert isinstance(cs.pending_stack[-1], PendingPlow)

        cs = step(cs, next(a for a in legal_actions(cs) if isinstance(a, CommitPlow)))
        assert _num_fields(cs, cp) == fields0 + 1


# ---------------------------------------------------------------------------
# Decline (the host's Stop) and once-per-play
# ---------------------------------------------------------------------------

def test_can_be_declined_via_stop():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        cs = with_resources(cs, cp, food=2)
        fields0 = _num_fields(cs, cp)
        cs = _drive_play(cs, cp, _TEST_MINOR)

        assert _FIRE in legal_actions(cs)
        cs = step(cs, Stop())   # decline: no food spent, no field plowed
        assert cs.players[cp].resources.food == 2
        assert _num_fields(cs, cp) == fields0
        assert not any(isinstance(f, PendingPlayMinor) for f in cs.pending_stack)


def test_fires_at_most_once_per_play():
    with _filler_minor():
        cs, _env = setup_env(0, card_pool=_POOL)
        cp = cs.current_player
        cs = _own_minor(cs, cp, CARD_ID)
        cs = _hand_minor(cs, cp, _TEST_MINOR)
        cs = with_resources(cs, cp, food=3)   # enough for a second fire, were one offered
        cs = _drive_play(cs, cp, _TEST_MINOR)

        cs = step(cs, _FIRE)
        cs = step(cs, next(a for a in legal_actions(cs) if isinstance(a, CommitPlow)))
        cs = step(cs, Stop())   # pop the (now-complete) plow frame back to the host
        # Back at the play-minor host's after-phase: the trigger is spent (triggers_resolved).
        assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
        acts = legal_actions(cs)
        assert _FIRE not in acts
        assert Stop() in acts
