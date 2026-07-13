"""Tests for Upholstery (minor E31): each improvement built/played after it, you may
place 1 reed on the card for 1 bonus point, capped at your room count."""
import agricola.cards.upholstery  # noqa: F401  (registers the card)
import agricola.cards.dwelling_plan  # noqa: F401  (a second minor to play "after")

from agricola.actions import FireTrigger
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.cards.upholstery import CARD_ID, _apply, _eligible, _on_play
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState

from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("upholstery", "dwelling_plan") + tuple(f"m{i}" for i in range(20)),
)


def _p_state(*, reed=1, banked=0, latch=False) -> GameState:
    """A default (2-room) state where player 0's reed / banked-count / same-turn latch
    are set, for unit-testing eligibility (the cap is 2 rooms)."""
    state = setup(seed=0)
    p = state.players[0]
    changes = {
        "resources": Resources(reed=reed),
        "card_state": p.card_state.set(CARD_ID, banked),
    }
    if latch:
        changes["used_this_turn"] = frozenset({CARD_ID})
    p = fast_replace(p, **changes)
    return fast_replace(state, players=(p, state.players[1]))


def _card_state(seed=5, *, hand=frozenset(), tableau=frozenset(), res=None):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_minors": hand, "minor_improvements": tableau}
    if res is not None:
        changes["resources"] = res
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources()   # no cost
    assert spec.vps == 0                          # points come from banked reed
    # Optional trigger on BOTH after-improvement events (no single event covers both).
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("after_play_minor", ()))
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("after_build_major", ()))
    assert CARDS[CARD_ID].mandatory is False
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- Unit: eligibility / apply / latch / scoring ----------------------------

def test_eligibility_boundaries():
    assert _eligible(_p_state(reed=1, banked=0), 0, frozenset()) is True
    assert _eligible(_p_state(reed=0, banked=0), 0, frozenset()) is False   # no reed
    assert _eligible(_p_state(reed=1, banked=1), 0, frozenset()) is True    # under the 2-room cap
    assert _eligible(_p_state(reed=1, banked=2), 0, frozenset()) is False   # at the cap (2 rooms)
    assert _eligible(_p_state(reed=1, banked=0, latch=True), 0, frozenset()) is False  # played this turn


def test_apply_spends_reed_and_banks_point():
    s = _apply(_p_state(reed=2, banked=1), 0)
    assert s.players[0].resources.reed == 1
    assert s.players[0].card_state.get(CARD_ID, 0) == 2


def test_on_play_latches_turn():
    s = _on_play(setup(seed=0), 0)
    assert CARD_ID in s.players[0].used_this_turn


def test_scoring_reads_bank():
    score = _score_fn()
    assert score(_p_state(banked=0), 0) == 0
    assert score(_p_state(banked=3), 0) == 3


# --- Integration: self-exclusion + fires on a later play --------------------

def test_self_play_does_not_offer_trigger():
    # Playing Upholstery itself must NOT offer the reed placement, even with reed + rooms.
    cs, cp = _card_state(hand=frozenset({CARD_ID}), res=Resources(reed=2))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID in cs.players[cp].used_this_turn                    # latched by on_play
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)
    assert cs.players[cp].card_state.get(CARD_ID, 0) == 0              # nothing banked


def test_fires_on_a_later_minor_play():
    # Upholstery already in the tableau (latch clear = a later turn). Play a different
    # minor; Upholstery's trigger is offered and banks a point for one reed.
    cs, cp = _card_state(
        hand=frozenset({"dwelling_plan"}),
        tableau=frozenset({CARD_ID}),
        res=Resources(food=1, reed=1),   # food plays dwelling_plan; reed feeds the fire
    )
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "dwelling_plan"))
    # dwelling_plan's own renovate is unaffordable (no clay) -> only Upholstery offered.
    assert FireTrigger(card_id=CARD_ID) in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert cs.players[cp].resources.reed == 0
    assert cs.players[cp].card_state.get(CARD_ID, 0) == 1
