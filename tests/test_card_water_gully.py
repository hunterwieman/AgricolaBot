"""Tests for Water Gully (minor improvement, E42; Ephipparius Expansion).

Card text: "Place 1 cattle, 1 grain, and 1 cattle on the next 3 round spaces (in
that order). At the start of these rounds, you get the respective good."
Cost: 1 Stone. Prereq: the "Well" Major Improvement.

Deferred goods: cattle on future_rewards (R+1, R+3), grain on future_resources
(R+2). Prereq = owning the Well (major idx 4). Tests the schedule, the prereq
gate, and a real end-to-end play.
"""
import json
from pathlib import Path

import agricola.cards.water_gully  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_pending_stack, with_resources, with_round

CARD_ID = "water_gully"
_WELL = 4

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Water Gully")


def _state(seed=5, round_number=1, well_owner=None):
    state, _env = setup_env(seed, card_pool=_POOL)
    state = with_round(state, round_number)
    if well_owner is not None:
        state = with_majors(state, owner_by_idx={_WELL: well_owner})
    return state


def _at_play_minor_frame(round_number=1):
    state = _state(round_number=round_number, well_owner=None)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_majors(state, owner_by_idx={_WELL: cp})     # owns the Well
    state = with_resources(state, cp, stone=1)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


# ---------------------------------------------------------------------------
# Registration & prereq
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "1 Stone"
    assert _ROW["prerequisites"] == "“Well” Major Improvement"
    assert _ROW["text"] == (
        "Place 1 cattle, 1 grain, and 1 cattle on the next 3 round spaces (in "
        "that order). At the start of these rounds, you get the respective good.")
    import agricola.cards.water_gully as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(stone=1))


def test_prereq_requires_the_well():
    spec = MINORS[CARD_ID]
    no_well = _state(well_owner=None)
    assert not prereq_met(spec, no_well, 0)
    with_well = _state(well_owner=0)
    assert prereq_met(spec, with_well, 0)
    # The opponent's Well does not satisfy player 0's prereq.
    opp_well = _state(well_owner=1)
    assert not prereq_met(spec, opp_well, 0)


# ---------------------------------------------------------------------------
# Scheduling (round 1 -> spaces rounds 2,3,4)
# ---------------------------------------------------------------------------

def test_on_play_schedules_cattle_grain_cattle():
    state = _state(round_number=1, well_owner=0)
    out = MINORS[CARD_ID].on_play(state, 0)
    fr = out.players[0].future_rewards
    fres = out.players[0].future_resources
    assert fr[1].animals.cattle == 1        # round 2: cattle
    assert fres[2].grain == 1               # round 3: grain
    assert fr[3].animals.cattle == 1        # round 4: cattle
    assert sum(r.animals.cattle for r in fr) == 2
    assert sum(r.grain for r in fres) == 1


def test_real_play_lands_the_schedule():
    state, cp = _at_play_minor_frame()
    (commit,) = [a for a in legal_actions(state)
                 if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    out = step(state, commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.stone == 0                   # cost paid
    assert p.future_rewards[1].animals.cattle == 1
    assert p.future_resources[2].grain == 1
    assert p.future_rewards[3].animals.cattle == 1


def test_not_offered_without_the_well():
    state, cp = _at_play_minor_frame()
    # Strip the Well: the card is no longer playable.
    state = with_majors(state, owner_by_idx={_WELL: 1 - cp})
    assert CARD_ID not in playable_minors(state, cp)
