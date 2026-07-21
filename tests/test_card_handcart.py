import agricola.cards.handcart  # noqa: F401  (registers the card)

"""Tests for Handcart (minor improvement, B81; Bubulcus Expansion).

Card text: "Before each work phase, you can take 1 building resource from at
most one wood/clay/reed/stone accumulation space containing at least 6/5/4/4
building resources of the same type."

An OPTIONAL play-variant trigger on the preparation ladder's `before_work`
window (ruling 54, 2026-07-14; the C3-cluster mechanism approval + the
threshold/take semantics ruling of 2026-07-20: the same-type count that
qualifies a space may be ANY building-resource type — not just the space's
native one — and once a space qualifies, ANY building resource present on it
is takeable). Covers: registration/spec; the eligibility-driven window hosting
(no qualifying space → no frame at all); threshold boundaries per family
(same-type count — a mixed pile whose no single type reaches the number does
NOT qualify); a foreign type reaching the number DOES qualify, with every
present type takeable (including the mixed take: qualify via stone, take
wood); the debit/credit arithmetic; the structural "at most one" (one take per
window even with two qualifying quarries); decline via Proceed; the
post-refill sequencing (`before_work` runs AFTER `__replenish__`, so
just-refilled goods count) driven across a REAL round boundary with the
RevealCard nature step; unowned/hand-only inertness; and the 1-wood play cost
paid through the real play-minor flow.
"""
from agricola.actions import ChooseSubAction, FireTrigger, PlaceWorker, Proceed
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space
from tests.factories import with_resources, with_space
from tests.test_utils import sole_play_minor

CARD_ID = "handcart"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx=0):
    """Give `idx` the PLAYED card (tableau, not hand)."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _enter_round(state, *, from_round=1):
    """Set round_number=from_round and run the real `_complete_preparation`
    round boundary into round from_round+1 (the whole prep ladder: collection,
    the `__replenish__` refill, then the before_work window — where a window
    frame pauses the walk if Handcart is eligible)."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _acc(state, space_id) -> Resources:
    return get_space(state.board, space_id).accumulated


def _fires(state):
    return [a for a in legal_actions(state) if isinstance(a, FireTrigger)]


def _at_before_work(state) -> bool:
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.window_id == "before_work"


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_registered_minor_spec():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))   # "1 Wood"
    assert spec.vps == 0
    assert spec.passing_left is False
    # No prerequisite: any state satisfies it.
    assert prereq_met(spec, setup(0), 0)


def test_registered_on_before_work_window():
    # "Before each work phase" -> the before_work window; an OPTIONAL
    # play-variant trigger (one FireTrigger per (space, type)), not an auto.
    entries = [e for e in TRIGGERS.get("before_work", ()) if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].mandatory is False
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("before_work", ())}
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


# ---------------------------------------------------------------------------
# Eligibility-driven hosting: no qualifying space -> no frame at all
# ---------------------------------------------------------------------------

def test_no_qualifying_space_no_frame():
    s = _own(setup(0))
    # Empty the Forest so the refill leaves it at 3 (< 6). Clay Pit refills to
    # 2 (< 5), Reed Bank to 2 (< 4), the quarries are unrevealed (0 < 4).
    s = with_space(s, "forest", accumulated=Resources())
    before = s.players[0].resources
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()          # no window frame was ever pushed
    assert out.phase is Phase.WORK
    assert out.round_number == 2
    assert out.players[0].resources == before


# ---------------------------------------------------------------------------
# Wood threshold boundary: post-refill 5 vs 6
# ---------------------------------------------------------------------------

def test_wood_threshold_five_does_not_qualify():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources(wood=2))  # +3 refill -> 5
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert _acc(out, "forest") == Resources(wood=5)


def test_wood_threshold_six_qualifies_and_fires():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources(wood=3))  # +3 refill -> 6
    wood_before = s.players[0].resources.wood
    out = _enter_round(s, from_round=1)
    assert _at_before_work(out)
    assert out.pending_stack[-1].player_idx == 0
    # Only wood is present on the Forest, so wood is the one takeable type.
    assert _fires(out) == [FireTrigger(card_id=CARD_ID, variant="forest:wood")]
    assert Proceed() in legal_actions(out)
    # Fire: 1 wood moves from the Forest's stock to the owner's supply.
    out = step(out, FireTrigger(card_id=CARD_ID, variant="forest:wood"))
    assert _acc(out, "forest") == Resources(wood=5)
    assert out.players[0].resources.wood == wood_before + 1
    # The trigger is consumed for this window: only Proceed remains.
    assert legal_actions(out) == [Proceed()]
    out = step(out, Proceed())
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.round_number == 2


# ---------------------------------------------------------------------------
# Stone family (threshold 4): boundary + each quarry judged independently
# ---------------------------------------------------------------------------

def test_stone_threshold_three_does_not_qualify():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources())            # 3 < 6
    s = with_space(s, "western_quarry", revealed=True,
                   accumulated=Resources(stone=2))                  # +1 refill -> 3
    out = _enter_round(s, from_round=7)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert _acc(out, "western_quarry") == Resources(stone=3)


def test_stone_threshold_four_qualifies_and_fires():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources())            # 3 < 6
    s = with_space(s, "western_quarry", revealed=True,
                   accumulated=Resources(stone=3))                  # +1 refill -> 4
    stone_before = s.players[0].resources.stone
    out = _enter_round(s, from_round=7)
    assert _at_before_work(out)
    assert _fires(out) == [
        FireTrigger(card_id=CARD_ID, variant="western_quarry:stone")]
    out = step(out, FireTrigger(card_id=CARD_ID, variant="western_quarry:stone"))
    assert _acc(out, "western_quarry") == Resources(stone=3)
    assert out.players[0].resources.stone == stone_before + 1
    out = step(out, Proceed())
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Clay family (threshold 5) boundary
# ---------------------------------------------------------------------------

def test_clay_threshold_boundary():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources())            # 3 < 6
    s = with_space(s, "clay_pit", accumulated=Resources(clay=3))    # +1 refill -> 4 < 5
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()
    s = with_space(s, "clay_pit", accumulated=Resources(clay=4))    # +1 refill -> 5
    out = _enter_round(s, from_round=1)
    assert _at_before_work(out)
    assert _fires(out) == [FireTrigger(card_id=CARD_ID, variant="clay_pit:clay")]
    out = step(out, FireTrigger(card_id=CARD_ID, variant="clay_pit:clay"))
    assert _acc(out, "clay_pit") == Resources(clay=4)
    assert out.players[0].resources.clay == 1


# ---------------------------------------------------------------------------
# Same-type counting (2026-07-20 ruling): a mixed pile with no single type at
# the number does NOT qualify; a foreign type at the number DOES, and every
# present type is takeable
# ---------------------------------------------------------------------------

def test_mixed_pile_no_single_type_at_threshold_no_frame():
    s = _own(setup(0))
    # Direct board edit simulating a card's deposit (Nail Basket's stone placed
    # on the Forest): post-refill the space holds 5 wood + 3 stone = 8 goods,
    # but NO single type reaches the Forest's number of 6 -> no window frame.
    s = with_space(s, "forest", accumulated=Resources(wood=2, stone=3))
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert _acc(out, "forest") == Resources(wood=5, stone=3)


def test_foreign_type_at_threshold_qualifies_and_all_present_types_takeable():
    s = _own(setup(0))
    # Direct board edit simulating card deposits: 6 stone sit on the Forest
    # (a wood space, number 6). Post-refill the pile is 3 wood + 6 stone: the
    # STONE count reaches 6, so the space qualifies — and BOTH present types
    # are takeable variants (the take is not limited to the qualifying type).
    s = with_space(s, "forest", accumulated=Resources(stone=6))     # +3 wood refill
    res_before = s.players[0].resources
    out = _enter_round(s, from_round=1)
    assert _at_before_work(out)
    assert _acc(out, "forest") == Resources(wood=3, stone=6)
    assert _fires(out) == [
        FireTrigger(card_id=CARD_ID, variant="forest:wood"),
        FireTrigger(card_id=CARD_ID, variant="forest:stone"),
    ]
    # Take the stone (the type that met the number).
    out = step(out, FireTrigger(card_id=CARD_ID, variant="forest:stone"))
    assert _acc(out, "forest") == Resources(wood=3, stone=5)        # wood untouched
    assert out.players[0].resources - res_before == Resources(stone=1)
    assert legal_actions(out) == [Proceed()]


def test_mixed_take_qualify_via_stone_take_wood():
    s = _own(setup(0))
    # Qualify via type A (6 stone on the Forest), take type B (a wood): the
    # 2026-07-20 ruling's "can take any resource from the space".
    s = with_space(s, "forest", accumulated=Resources(stone=6))     # +3 wood refill
    res_before = s.players[0].resources
    out = _enter_round(s, from_round=1)
    assert _at_before_work(out)
    out = step(out, FireTrigger(card_id=CARD_ID, variant="forest:wood"))
    assert _acc(out, "forest") == Resources(wood=2, stone=6)        # stone untouched
    assert out.players[0].resources - res_before == Resources(wood=1)
    out = step(out, Proceed())
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# "At most one" space: one take per window even with two qualifying quarries
# ---------------------------------------------------------------------------

def test_at_most_one_space_per_window():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources())            # 3 < 6
    s = with_space(s, "western_quarry", revealed=True,
                   accumulated=Resources(stone=3))                  # -> 4
    s = with_space(s, "eastern_quarry", revealed=True,
                   accumulated=Resources(stone=3))                  # -> 4
    out = _enter_round(s, from_round=7)
    assert _at_before_work(out)
    assert _fires(out) == [
        FireTrigger(card_id=CARD_ID, variant="western_quarry:stone"),
        FireTrigger(card_id=CARD_ID, variant="eastern_quarry:stone"),
    ]
    out = step(out, FireTrigger(card_id=CARD_ID, variant="western_quarry:stone"))
    # The eastern quarry still qualifies (4 stone), but the trigger is consumed
    # for this window — one take total, no second fire, only Proceed.
    assert _acc(out, "eastern_quarry") == Resources(stone=4)
    assert legal_actions(out) == [Proceed()]
    assert out.players[0].resources.stone == 1                  # exactly one taken
    out = step(out, Proceed())
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK
    assert out.round_number == 8


# ---------------------------------------------------------------------------
# Decline via Proceed
# ---------------------------------------------------------------------------

def test_decline_via_proceed():
    s = _own(setup(0))
    s = with_space(s, "forest", accumulated=Resources(wood=3))      # -> 6, qualifies
    res_before = s.players[0].resources
    out = _enter_round(s, from_round=1)
    assert _at_before_work(out)
    out = step(out, Proceed())                                      # decline the take
    assert out.players[0].resources == res_before                   # nothing gained
    assert _acc(out, "forest") == Resources(wood=6)                 # nothing debited
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Ownership gating: unowned / hand-only -> inert
# ---------------------------------------------------------------------------

def test_unowned_inert():
    s = setup(0)                                                    # nobody owns it
    s = with_space(s, "forest", accumulated=Resources(wood=3))      # -> 6 qualifies
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


def test_hand_only_inert():
    # In hand but not played: a hand card cannot fire.
    s = setup(0)
    p = fast_replace(s.players[0], hand_minors=frozenset({CARD_ID}))
    s = fast_replace(s, players=(p,) + s.players[1:])
    s = with_space(s, "forest", accumulated=Resources(wood=3))      # -> 6 qualifies
    out = _enter_round(s, from_round=1)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Play cost: the 1 wood is debited through the real play-minor flow
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_play_cost_debits_one_wood():
    cs, _env = setup_env(0, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    from agricola.state import with_space as board_with_space
    cs = fast_replace(cs, board=board_with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=1)                             # exactly the cost
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors
    assert cs.players[cp].resources.wood == 0                       # 1 wood paid


# ---------------------------------------------------------------------------
# Sequencing: before_work runs AFTER the refill, across a REAL round boundary
# ---------------------------------------------------------------------------

def test_post_refill_goods_count_across_real_round_boundary():
    """Drive a real game (steps + RevealCard nature steps) from round 1 into
    the round-2 preparation, steering every placement away from the Forest so
    its setup stock of 3 wood is never taken. Pre-refill the Forest holds only
    3 wood (< 6, would never host the window); `__replenish__` lifts it to 6,
    and the before_work window — which runs AFTER the refill — sees 6 and
    hosts the take. This is the ladder-order consequence under test."""
    from agricola.agents.base import decider_of

    s, env = setup_env(0)
    s = _own(s, 0)
    assert _acc(s, "forest") == Resources(wood=3)   # the round-1 setup stock

    steps = 0
    while steps < 500 and not _at_before_work(s):
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))             # the RevealCard nature step
        else:
            la = legal_actions(s)
            choices = [a for a in la
                       if not (isinstance(a, PlaceWorker) and a.space == "forest")]
            assert choices, "steering away from the Forest emptied the action set"
            s = step(s, choices[0])
        steps += 1
    assert _at_before_work(s), "before_work window never hosted Handcart"
    # The walk paused during round 2's preparation, post-refill: 3 + 3 = 6.
    assert s.round_number == 2
    assert _acc(s, "forest") == Resources(wood=6)
    wood_before = s.players[0].resources.wood
    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest:wood"))
    assert _acc(s, "forest") == Resources(wood=5)
    assert s.players[0].resources.wood == wood_before + 1
    s = step(s, Proceed())
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert s.round_number == 2
