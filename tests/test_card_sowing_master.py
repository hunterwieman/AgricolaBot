import agricola.cards.sowing_master  # noqa: F401  (registers the card)

"""Tests for Sowing Master (occupation, D109; Dulcinaria Expansion).

Card text: "When you play this card, you immediately get 1 wood. Each time
after you use an action space with the \"Sow\" action, you get 2 food."

USER RULING (2026-07-14): the recurring grant is equivalent to "each time
after you use the Grain Utilization or Cultivation action spaces" — it fires
on ANY use of either space, whether or not the Sow sub-action was actually
taken (the space merely has to offer it). The bake-only test below pins that
reading. The +2 food is a mandatory automatic effect on `after_action_space`
(explicit "after" in the text), firing at the host's Proceed flip; both spaces
are non-atomic Proceed-hosts, so there is no action-space hook.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitPlayOccupation,
    CommitSow,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingCultivation, PendingGrainUtilization
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_fields, with_majors, with_resources, with_space

CARD_ID = "sowing_master"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5, *, occupations=frozenset(), hand=frozenset({CARD_ID})):
    """A cards-mode round-1 WORK state with the current player's hand/tableau
    set deterministically so plays are reproducible."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=hand, occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _owner_state(seed=5):
    """Cards-mode state where the current player already OWNS Sowing Master."""
    return _card_state(seed, occupations=frozenset({CARD_ID}), hand=frozenset())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # The recurring grant is an AUTOMATIC effect on after_action_space
    # (explicit "after" in the text), owner-gated.
    autos = [e for e in AUTO_EFFECTS.get("after_action_space", ()) if e.card_id == CARD_ID]
    assert len(autos) == 1
    assert autos[0].any_player is False
    # Not on the before window (the text says "after").
    before_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID not in before_ids
    # Both spaces are non-atomic Proceed-hosts: NO action-space hook.
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("grain_utilization", set())
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("cultivation", set())


# ---------------------------------------------------------------------------
# On-play grant: +1 wood (one-time)
# ---------------------------------------------------------------------------

def test_on_play_grants_one_wood():
    cs, cp = _card_state()
    before_wood = cs.players[cp].resources.wood

    # Play via Lessons (an occupation-play entry point).
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))

    assert CARD_ID in cs.players[cp].occupations
    assert cs.players[cp].resources.wood == before_wood + 1

    cs = step(cs, Stop())   # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())   # pop the Lessons host frame
    assert cs.pending_stack == ()
    # One-time: no further wood (and Lessons is not a sow space -> no food).
    assert cs.players[cp].resources.wood == before_wood + 1


# ---------------------------------------------------------------------------
# The ruled pin: +2 food after a Grain Utilization use where the player
# ONLY BAKED (no sow) — the space merely offers the Sow action.
# ---------------------------------------------------------------------------

def test_grain_utilization_bake_only_grants_two_food():
    cs, cp = _owner_state()
    cs = with_resources(cs, cp, grain=1)
    cs = with_majors(cs, owner_by_idx={0: cp})   # a Fireplace, so baking is legal

    cs = step(cs, PlaceWorker(space="grain_utilization"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization) and top.phase == "before"

    cs = step(cs, ChooseSubAction(name="bake_bread"))
    cs = step(cs, CommitBake(grain=1))
    cs = step(cs, Stop())                        # pop the bake leaf, back at the host
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization)
    assert top.bake_chosen and not top.sow_chosen   # NO sow taken
    assert Proceed() in legal_actions(cs)

    food_before_flip = cs.players[cp].resources.food
    cs = step(cs, Proceed())                     # the use is done -> after-phase
    assert cs.pending_stack[-1].phase == "after"
    # Fires at the Proceed flip: exactly +2 food, even though nothing was sown.
    assert cs.players[cp].resources.food == food_before_flip + 2

    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# +2 food after a Cultivation use (a Stage-5 round space; revealed for the test)
# ---------------------------------------------------------------------------

def test_cultivation_use_grants_two_food():
    cs, cp = _owner_state()
    cs = with_resources(cs, cp, grain=1)
    cs = with_fields(cs, cp, [(0, 2)])           # an empty field to sow into
    cs = with_space(cs, "cultivation", revealed=True)

    cs = step(cs, PlaceWorker(space="cultivation"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingCultivation) and top.phase == "before"

    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    cs = step(cs, Stop())                        # pop the sow leaf, back at the host
    assert isinstance(cs.pending_stack[-1], PendingCultivation)
    assert Proceed() in legal_actions(cs)

    food_before_flip = cs.players[cp].resources.food
    cs = step(cs, Proceed())
    assert cs.pending_stack[-1].phase == "after"
    assert cs.players[cp].resources.food == food_before_flip + 2

    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# Timing: nothing lands BEFORE the Proceed flip (verified inside the flows
# above via food_before_flip; here, the before-phase and mid-sub-action states)
# ---------------------------------------------------------------------------

def test_no_food_before_the_after_flip():
    cs, cp = _owner_state()
    cs = with_resources(cs, cp, grain=1)
    cs = with_fields(cs, cp, [(0, 2)])
    food0 = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="grain_utilization"))
    assert cs.players[cp].resources.food == food0     # nothing at the push
    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    assert cs.players[cp].resources.food == food0     # nothing at the commit
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == food0     # nothing back at the host
    cs = step(cs, Proceed())
    assert cs.players[cp].resources.food == food0 + 2  # lands at the flip
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# Eligibility boundary: does NOT fire on other spaces
# ---------------------------------------------------------------------------

def test_does_not_fire_on_other_spaces():
    # Farmland is also a hosted space that flips through after_action_space,
    # but it carries no Sow action -> no food.
    cs, cp = _owner_state()
    food0 = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="farmland"))
    cs = step(cs, ChooseSubAction(name="plow"))
    from agricola.actions import CommitPlow
    cs = step(cs, CommitPlow(row=0, col=2))
    cs = step(cs, Stop())    # pop the plow leaf's after-phase
    cs = step(cs, Stop())    # pop the Farmland host
    assert cs.pending_stack == ()
    assert cs.players[cp].resources.food == food0


# ---------------------------------------------------------------------------
# Owner-gated: an opponent's use of a sow space pays the owner nothing
# ---------------------------------------------------------------------------

def test_opponent_use_pays_nothing():
    cs, cp = _card_state(hand=frozenset())
    opp = 1 - cp
    # The OPPONENT owns Sowing Master; the current player uses Grain Utilization.
    op = fast_replace(cs.players[opp], occupations=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(op if i == opp else cs.players[i] for i in range(2)))
    cs = with_resources(cs, cp, grain=1)
    cs = with_fields(cs, cp, [(0, 2)])
    cp_food = cs.players[cp].resources.food
    opp_food = cs.players[opp].resources.food

    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    cs = step(cs, Stop())
    cs = step(cs, Proceed())
    assert cs.pending_stack[-1].phase == "after"
    cs = step(cs, Stop())
    assert cs.pending_stack == ()

    assert cs.players[cp].resources.food == cp_food      # the acting non-owner: nothing
    assert cs.players[opp].resources.food == opp_food    # the non-acting owner: nothing


# ---------------------------------------------------------------------------
# Hand-only is inert: an unplayed Sowing Master grants nothing
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    cs, cp = _card_state()   # in hand, NOT played
    assert CARD_ID in cs.players[cp].hand_occupations
    assert CARD_ID not in cs.players[cp].occupations
    cs = with_resources(cs, cp, grain=1)
    cs = with_fields(cs, cp, [(0, 2)])
    wood0 = cs.players[cp].resources.wood
    food0 = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    cs = step(cs, Stop())
    cs = step(cs, Proceed())
    cs = step(cs, Stop())
    assert cs.pending_stack == ()

    assert cs.players[cp].resources.wood == wood0    # no on-play wood either
    assert cs.players[cp].resources.food == food0    # no after-use food


# ---------------------------------------------------------------------------
# Scoping: EACH use fires — two separate uses grant twice
# ---------------------------------------------------------------------------

def test_each_use_fires_again():
    cs, cp = _owner_state()
    cs = with_resources(cs, cp, grain=2)
    cs = with_fields(cs, cp, [(0, 2), (0, 3)])
    cs = with_space(cs, "cultivation", revealed=True)
    food0 = cs.players[cp].resources.food

    # Use 1: Grain Utilization (sow).
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    cs = step(cs, Stop())
    cs = step(cs, Proceed())
    cs = step(cs, Stop())
    assert cs.players[cp].resources.food == food0 + 2

    # Use 2 (a later turn of the same player): Cultivation (sow).
    cs = fast_replace(cs, current_player=cp)
    cs = step(cs, PlaceWorker(space="cultivation"))
    cs = step(cs, ChooseSubAction(name="sow"))
    cs = step(cs, CommitSow(grain=1, veg=0))
    cs = step(cs, Stop())
    cs = step(cs, Proceed())
    cs = step(cs, Stop())
    assert cs.pending_stack == ()
    assert cs.players[cp].resources.food == food0 + 4
