"""Tests for Young Farmer (occupation, D112; Dulcinaria Expansion).

Card text (verbatim): "Each time you use the "Major Improvement" action space,
you also get 1 grain and, afterward, you can take a "Sow" action."

Shape: two halves on the Major Improvement space's Delegating host
(PendingSubActionSpace — non-atomic, always hosted, NO action-space hook):
- +1 grain: a mandatory choice-free AUTOMATIC effect on `before_action_space`
  ("each time you use" = before), fired at the host push — so it lands on ANY
  use of the space, the build-a-major branch and the play-a-minor branch alike.
- the Sow: printed "afterward" -> an OPTIONAL trigger on `after_action_space`
  (user confirmation 2026-07-14: the sow is optional), surfacing only once the
  space's whole work resolved (ruling 60's deferred after-flip), gated on the
  engine's own sow predicate (`_can_sow`: crop in supply AND an empty field),
  pushing the full uncapped PendingSow. Declining = the host's Stop without
  firing; once per use via the host's triggers_resolved.
"""
import agricola.cards.young_farmer   # noqa: F401  (registers the card)
import agricola.cards.market_stall   # noqa: F401  (a real 1-grain minor for the play-minor branch)

from agricola.actions import (
    ChooseSubAction,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingMajorMinorImprovement,
    PendingSow,
    PendingSubActionSpace,
)
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import add_resources, with_fields, with_resources, with_space
from tests.test_utils import sole_build_major, sole_play_minor

CARD_ID = "young_farmer"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    """A cards-mode round-1 WORK state, P0 to move, the Major Improvement space
    revealed (it is a Stage-1 card space)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    cs = with_space(cs, "major_improvement", revealed=True, workers=(0, 0))
    return cs, 0


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _hand_occ(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_occupations=p.hand_occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _hand_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_minors=p.hand_minors | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _place(state):
    """Place the acting player at Major Improvement; the Delegating host is
    pushed in its before-phase (where the +1 grain auto has already fired)."""
    state = step(state, PlaceWorker(space="major_improvement"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.space_id == "major_improvement"
    assert top.phase == "before"
    return state


def _build_fireplace_to_after(state):
    """From the host's before-phase, drive the build-a-major branch (Fireplace,
    major_idx 0, 2 clay) all the way to the host's after-phase."""
    state = step(state, ChooseSubAction(name="improvement"))
    assert isinstance(state.pending_stack[-1], PendingMajorMinorImprovement)
    state = step(state, ChooseSubAction(name="build_major"))
    state = step(state, sole_build_major(state, 0))       # build Fireplace
    state = step(state, Stop())    # pop PendingBuildMajor after-phase -> MMI flips
    assert isinstance(state.pending_stack[-1], PendingMajorMinorImprovement)
    assert state.pending_stack[-1].phase == "after"
    state = step(state, Stop())    # pop MMI -> the space host auto-advances
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.space_id == "major_improvement"
    assert top.phase == "after"
    return state


def _grain_on_field(state, idx):
    """Total grain sown on board fields."""
    return sum(cell.grain for row in state.players[idx].farmyard.grid for cell in row
               if cell.cell_type == CellType.FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_young_farmer_registered():
    assert CARD_ID in OCCUPATIONS
    # The +1 grain is an AUTOMATIC effect on before_action_space (subset check).
    before_autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert CARD_ID in before_autos
    # The Sow grant is an OPTIONAL trigger on after_action_space (subset check).
    after_trigs = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in after_trigs
    # It is NOT registered as a trigger on the before window (the sow is "afterward").
    before_trigs = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID not in before_trigs
    # No action-space hook — major_improvement is non-atomic and always hosted.
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("major_improvement", set())


# ---------------------------------------------------------------------------
# The +1 grain — both branches of the space
# ---------------------------------------------------------------------------

def test_grain_granted_on_build_major_branch():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, clay=2)            # Fireplace's cost; zero grain
    s = _place(s)
    # The grain lands at the host push, before any branch choice.
    assert s.players[cp].resources.grain == 1
    s = _build_fireplace_to_after(s)
    assert s.players[cp].resources.grain == 1    # still held at the after-phase
    assert s.board.major_improvement_owners[0] == cp


def test_grain_granted_on_play_minor_branch():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = _hand_minor(s, cp, "market_stall")
    s = with_resources(s, cp)                    # ZERO grain — the grant funds the cost
    s = _place(s)
    assert s.players[cp].resources.grain == 1
    s = step(s, ChooseSubAction(name="improvement"))
    s = step(s, ChooseSubAction(name="play_minor"))
    s = step(s, sole_play_minor(s, "market_stall"))   # pays its 1-grain cost
    p = s.players[cp]
    assert p.resources.grain == 0                # the granted grain paid the minor
    assert p.resources.veg == 1                  # Market Stall's on-play exchange
    assert "market_stall" not in p.hand_minors   # played (then passed — traveling)


def test_no_grain_at_an_unrelated_space():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp)
    s = step(s, PlaceWorker(space="farmland"))   # hosted non-atomic, wrong space
    assert s.players[cp].resources.grain == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_opponent_use_pays_nothing():
    s, cp = _card_state()
    s = _own_occ(s, 0, CARD_ID)                  # P0 owns the card...
    s = fast_replace(s, current_player=1)        # ...but P1 uses the space
    s = with_resources(s, 1, clay=2)
    g0, g1 = (s.players[i].resources.grain for i in range(2))
    s = _place(s)
    assert s.players[0].resources.grain == g0    # the owner gets nothing
    assert s.players[1].resources.grain == g1    # the visitor gets nothing
    s = _build_fireplace_to_after(s)
    # The Sow trigger is not offered either (P1 does not own the card).
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_hand_only_is_inert():
    s, cp = _card_state()
    s = _hand_occ(s, cp, CARD_ID)                # in hand, never played
    s = with_fields(s, cp, [(0, 2)])
    s = with_resources(s, cp, clay=2, grain=1)   # sow would be possible if owned
    s = _place(s)
    assert s.players[cp].resources.grain == 1    # no grant
    s = _build_fireplace_to_after(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# The Sow grant — offered in the after-phase, only when sowable
# ---------------------------------------------------------------------------

def test_sow_offered_after_and_sows_for_real():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_fields(s, cp, [(0, 2)])             # one empty field
    s = with_resources(s, cp, clay=2)            # the granted grain is the only crop
    s = _place(s)
    # Not offered in the before-phase (the sow is "afterward").
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _build_fireplace_to_after(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert CommitSow(grain=1, veg=0) in legal_actions(s)
    s = step(s, CommitSow(grain=1, veg=0))       # sow the granted grain
    p = s.players[cp]
    assert p.resources.grain == 0                # the grain left the supply...
    assert _grain_on_field(s, cp) == 3           # ...onto the field (3 per sown field)
    # The sow frame flips to its after-phase; Stop pops it back to the host.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSow) and top.phase == "after"
    s = step(s, Stop())
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.phase == "after"
    s = step(s, Stop())                          # Stop ends the turn
    assert not any(isinstance(f, PendingSow) for f in s.pending_stack)


def test_sow_not_offered_without_a_crop():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_fields(s, cp, [(0, 2)])             # an empty field exists...
    s = with_resources(s, cp, clay=2)
    s = _place(s)
    s = _build_fireplace_to_after(s)
    # ...but strip every crop (the granted grain included): no dead-end fire.
    s = with_resources(s, cp, grain=0, veg=0)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    # Positive control: a crop back in supply restores the offer.
    s = add_resources(s, cp, veg=1)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_sow_not_offered_without_an_empty_field():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, clay=2)            # no fields at all
    s = _place(s)
    s = _build_fireplace_to_after(s)
    assert s.players[cp].resources.grain == 1    # crop in supply, nowhere to sow
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality — declining = Stop without firing
# ---------------------------------------------------------------------------

def test_sow_is_declinable():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_fields(s, cp, [(0, 2)])
    s = with_resources(s, cp, clay=2)
    s = _place(s)
    s = _build_fireplace_to_after(s)
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                          # decline by ending the turn
    p = s.players[cp]
    assert p.resources.grain == 1                # nothing sown
    assert _grain_on_field(s, cp) == 0
    assert not any(isinstance(f, PendingSow) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Scoping — once per use of the space
# ---------------------------------------------------------------------------

def test_sow_fires_once_per_use():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_fields(s, cp, [(0, 2)])
    s = with_resources(s, cp, clay=2)
    s = _place(s)
    s = _build_fireplace_to_after(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitSow(grain=1, veg=0))
    s = step(s, Stop())                          # pop the sow frame's after-phase
    # Back at the host's after-phase: make a second sow POSSIBLE again...
    s = add_resources(s, cp, grain=1)
    s = with_fields(s, cp, [(0, 3)])             # a fresh empty field
    top = s.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.phase == "after"
    # ...yet the trigger is spent for this use (the host's triggers_resolved).
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
