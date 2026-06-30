"""Clay Puncher (occupation, A121): +1 clay when played, and +1 clay each time
AFTER you use a Lessons action space or the Clay Pit accumulation space.

Card text: "When you play this card and each time after you use a 'Lessons'
action space or the 'Clay Pit' accumulation space, you get 1 clay."
Clarification: "Gives 1+1=2 clay when played on Lessons."
"""
import agricola.cards.clay_puncher  # noqa: F401  (registers the card)
import agricola.cards.stable_architect  # noqa: F401  (a registered no-op-on-play occupation)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space

_POOL = CardPool(
    occupations=("clay_puncher", "stable_architect") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, occupations=frozenset(), hand=frozenset({"clay_puncher"})):
    """A card-mode round-1 WORK state with the current player's hand/tableau set
    deterministically so plays are reproducible."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=hand, occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_clay_puncher_registered():
    assert "clay_puncher" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert "clay_puncher" in auto_ids
    # Clay Pit is atomic → it must be explicitly hosted. Lessons is NOT hooked
    # (it self-hosts as a PendingSubActionSpace).
    assert "clay_puncher" in OWN_ACTION_HOOK_CARDS["clay_pit"]
    assert "clay_puncher" not in OWN_ACTION_HOOK_CARDS.get("lessons", set())


# ---------------------------------------------------------------------------
# After Clay Pit (atomic → hosted) → +1 clay
# ---------------------------------------------------------------------------

def test_after_clay_pit_grants_one_clay():
    cs, cp = _card_state(occupations=frozenset({"clay_puncher"}), hand=frozenset())
    cs = fast_replace(cs, current_player=cp)
    accumulated = get_space(cs.board, "clay_pit").accumulated.clay
    before = cs.players[cp].resources.clay

    cs = step(cs, PlaceWorker(space="clay_pit"))
    # Owned hook card → the atomic space is hosted by a PendingActionSpace.
    assert isinstance(cs.pending_stack[-1], PendingActionSpace)
    assert cs.pending_stack[-1].phase == "before"
    # No optional trigger surfaces (the grant is an automatic after-effect).
    assert legal_actions(cs) == [Proceed()]
    cs = step(cs, Proceed())            # run Clay Pit, flip to after, fire the auto
    assert cs.pending_stack[-1].phase == "after"
    # +1 came at the after-phase flip; the accumulated clay came from Proceed.
    assert cs.players[cp].resources.clay == before + accumulated + 1
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# On play (+1) AND after the same Lessons use (+1) = 2 clay total
# ---------------------------------------------------------------------------

def test_played_on_lessons_grants_two_clay():
    cs, cp = _card_state()
    before = cs.players[cp].resources.clay

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="clay_puncher"))
    # On-play grant already applied (card now owned); +1 so far.
    assert cs.players[cp].resources.clay == before + 1
    assert "clay_puncher" in cs.players[cp].occupations

    cs = step(cs, Stop())   # pop PendingPlayOccupation's after-phase
    # Popping the occupation child auto-advances the Lessons host to its
    # after-phase, firing after_action_space → +1 more = 2 total.
    assert cs.players[cp].resources.clay == before + 2
    cs = step(cs, Stop())   # pop the Lessons host frame
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# After Lessons use when the card is already owned (a SECOND Lessons use)
# ---------------------------------------------------------------------------

def test_after_lessons_use_grants_one_clay_when_already_owned():
    # Owns clay_puncher already; plays a DIFFERENT occupation via Lessons.
    cs, cp = _card_state(occupations=frozenset({"clay_puncher"}),
                         hand=frozenset({"stable_architect"}))
    cs = fast_replace(cs, current_player=cp)
    before = cs.players[cp].resources.clay

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="stable_architect"))
    # stable_architect has no on-play effect; clay unchanged until the host's after-phase.
    assert cs.players[cp].resources.clay == before
    cs = step(cs, Stop())   # pop the occupation child → Lessons host flips to after
    assert cs.players[cp].resources.clay == before + 1   # after_action_space fired
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


# ---------------------------------------------------------------------------
# Eligibility boundary: does NOT fire on an unrelated space
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Owns clay_puncher; uses Forest (not Lessons / Clay Pit). Forest is atomic
    # and clay_puncher does not hook it, so it stays on the atomic fast path and
    # grants no clay.
    cs, cp = _card_state(occupations=frozenset({"clay_puncher"}), hand=frozenset())
    cs = fast_replace(cs, current_player=cp)
    before_clay = cs.players[cp].resources.clay
    assert "clay_puncher" not in OWN_ACTION_HOOK_CARDS.get("forest", set())

    cs = step(cs, PlaceWorker(space="forest"))
    # No host frame pushed → atomic fast path, turn already advanced.
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_clay   # no +1 clay


def test_opponents_clay_puncher_does_not_fire_on_my_clay_pit():
    # Only the ACTING player's owned hook fires (any_player=False default).
    cs, cp = _card_state(hand=frozenset())
    opp = 1 - cp
    op = fast_replace(cs.players[opp], occupations=frozenset({"clay_puncher"}))
    cs = fast_replace(cs, players=tuple(op if i == opp else cs.players[i] for i in range(2)),
                      current_player=cp)
    # cp does NOT own clay_puncher → Clay Pit is not hosted for cp's use.
    accumulated = get_space(cs.board, "clay_pit").accumulated.clay
    before_cp = cs.players[cp].resources.clay
    before_opp = cs.players[opp].resources.clay

    cs = step(cs, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in cs.pending_stack)
    assert cs.players[cp].resources.clay == before_cp + accumulated   # only accumulated
    assert cs.players[opp].resources.clay == before_opp               # opponent: no +1
