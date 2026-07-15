import agricola.cards.chief_forester  # noqa: F401

"""Tests for Chief Forester (occupation, A115) — the granted 1-field "Sow" action
on a wood accumulation space.

Card text: "Each time you use a wood accumulation space, you also get a "Sow"
action for exactly 1 field."

An OPTIONAL `before_action_space` trigger on the (hooked, atomic) `forest` host
whose apply pushes `PendingSow(max_fields=1)` — the Assistant Tiller shape with
PendingPlow swapped for PendingSow. The host's Proceed is the decline; eligibility
gates on `_can_sow` so it never dead-ends; the sow is capped at one field.
"""
import pytest

from agricola.actions import CommitSow, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup_env
from agricola.state import get_space
from tests.factories import with_fields, with_resources

_FIRE = FireTrigger(card_id="chief_forester")


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _ready(idx=0, *, fields=((0, 0),), grain=1):
    """Own Chief Forester with `fields` plowed empty + `grain` in supply, ready to
    place at `idx`."""
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=idx)
    s = _own(s, idx, "chief_forester")
    s = with_fields(s, idx, list(fields))
    s = with_resources(s, idx, grain=grain)
    return s


def _sow_commit(state):
    return next(a for a in legal_actions(state)
               if isinstance(a, CommitSow) and a.grain == 1)


# ---------------------------------------------------------------------------
# Registration + hooking
# ---------------------------------------------------------------------------

def test_registered_and_hooks_forest_only():
    assert "chief_forester" in OCCUPATIONS
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert "chief_forester" in bas
    s = _ready()
    assert should_host_space(s, "forest", 0)
    # Not the other building accumulation spaces (clay/reed/stone).
    assert not should_host_space(s, "clay_pit", 0)
    assert not should_host_space(s, "reed_bank", 0)
    assert not should_host_space(s, "western_quarry", 0)


# ---------------------------------------------------------------------------
# The grant: fire -> sow one field -> Forest still pays its wood
# ---------------------------------------------------------------------------

def test_sow_offered_at_forest_and_commits_one_field():
    s = _ready()
    s = step(s, PlaceWorker(space="forest"))
    la = legal_actions(s)
    assert _FIRE in la            # the optional sow grant
    assert Proceed() in la        # decline path (host's Proceed)

    s = step(s, _FIRE)
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.pending_stack[-1].max_fields == 1

    s = step(s, _sow_commit(s))   # sow 1 grain into the one empty field
    s = step(s, Stop())           # pop PendingSow's after-phase
    # The field now holds sown grain (3 per Agricola sow), grain supply spent.
    grid = s.players[0].farmyard.grid
    assert grid[0][0].grain == 3
    assert s.players[0].resources.grain == 0

    # Forest's own effect still resolves: Proceed takes the accumulated wood.
    accumulated = get_space(s.board, "forest").accumulated.wood
    s = step(s, Proceed())
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].resources.wood == accumulated


# ---------------------------------------------------------------------------
# Optionality — decline via Proceed leaves the field unsown, wood still taken
# ---------------------------------------------------------------------------

def test_decline_via_proceed_leaves_field_unsown():
    s = _ready()
    accumulated = get_space(s.board, "forest").accumulated.wood
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())        # decline the sow
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].farmyard.grid[0][0].grain == 0   # not sown
    assert s.players[0].resources.grain == 1             # grain untouched
    assert s.players[0].resources.wood == accumulated    # wood still collected


# ---------------------------------------------------------------------------
# Eligibility boundary — no sow possible -> the trigger is not offered
# ---------------------------------------------------------------------------

def test_no_grant_when_no_field_to_sow():
    # Own the card + grain, but NO plowed field -> _can_sow is False -> only Proceed.
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=0)
    s = _own(s, 0, "chief_forester")
    s = with_resources(s, 0, grain=2)
    s = step(s, PlaceWorker(space="forest"))
    assert legal_actions(s) == [Proceed()]


def test_no_grant_when_no_seed():
    # A plowed field but zero grain/veg -> nothing to sow -> only Proceed.
    s = _ready(grain=0)
    s = step(s, PlaceWorker(space="forest"))
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# "for exactly 1 field" — the sow is capped at one field
# ---------------------------------------------------------------------------

def test_capped_at_one_field():
    # Two empty fields + two grain: an uncapped sow could fill both; max_fields=1
    # forbids any commit that sows into 2 fields (grain+veg == 2).
    s = _ready(fields=((0, 0), (0, 1)), grain=2)
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, _FIRE)
    commits = [a for a in legal_actions(s) if isinstance(a, CommitSow)]
    assert commits                                   # a 1-field sow is available
    assert all(a.grain + a.veg <= 1 for a in commits)  # never a 2-field sow


# ---------------------------------------------------------------------------
# Once per use of the space
# ---------------------------------------------------------------------------

def test_only_once_per_forest_use():
    s = _ready()
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, _FIRE)
    s = step(s, _sow_commit(s))
    s = step(s, Stop())           # pop PendingSow -> back at the forest host
    la = legal_actions(s)
    assert _FIRE not in la         # triggers_resolved blocks a second sow
    assert Proceed() in la


# ---------------------------------------------------------------------------
# Not offered elsewhere / hand-only inert
# ---------------------------------------------------------------------------

def test_hand_only_card_is_inert():
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=0)
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations
                     | frozenset({"chief_forester"}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = with_fields(s, 0, [(0, 0)])
    s = with_resources(s, 0, grain=1)
    assert not should_host_space(s, "forest", 0)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
