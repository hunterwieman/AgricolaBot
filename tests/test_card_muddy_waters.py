"""Tests for Muddy Waters (minor improvement, E41; Ephipparius Expansion).

Card text: "Alternate placing 1 food and 1 clay on each remaining even-numbered
round space, starting with food. At the start of these rounds, you get the
respective good."
Free. Prereq: 5 Cards in Play. VPs: 1.

Deferred goods on the REMAINING even round spaces (2,4,...,14 strictly after the
current round), food/clay alternating from food, all on future_resources. Prereq
= >= 5 of the player's own played occupations + minors (majors excluded). Tests
the schedule at several points, the "remaining" clamp, and the prereq boundary.
"""
import json
from pathlib import Path

import agricola.cards.muddy_waters  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_round

CARD_ID = "muddy_waters"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Muddy Waters")


def _state(round_number=1, occupations=frozenset(), minors=frozenset()):
    state, _env = setup_env(5, card_pool=_POOL)
    state = with_round(state, round_number)
    p = fast_replace(state.players[0], occupations=occupations,
                     minor_improvements=minors)
    return fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))


def _food(p):
    return [r.food for r in p.future_resources]


def _clay(p):
    return [r.clay for r in p.future_resources]


# ---------------------------------------------------------------------------
# Registration & prereq
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] is None            # free
    assert _ROW["prerequisites"] == "5 Cards in Play"
    assert _ROW["vps"] == 1
    assert _ROW["text"] == (
        "Alternate placing 1 food and 1 clay on each remaining even-numbered "
        "round space, starting with food. At the start of these rounds, you get "
        "the respective good.")
    import agricola.cards.muddy_waters as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    assert MINORS[CARD_ID].cost == Cost()
    assert MINORS[CARD_ID].vps == 1


def test_prereq_five_own_cards():
    spec = MINORS[CARD_ID]
    # 4 cards (2 occ + 2 minors): not enough.
    four = _state(occupations=frozenset({"o0", "o1"}), minors=frozenset({"m0", "m1"}))
    assert not prereq_met(spec, four, 0)
    # 5 cards (3 occ + 2 minors): enough — occupations AND minors both count.
    five = _state(occupations=frozenset({"o0", "o1", "o2"}), minors=frozenset({"m0", "m1"}))
    assert prereq_met(spec, five, 0)


# ---------------------------------------------------------------------------
# Scheduling on the remaining even round spaces
# ---------------------------------------------------------------------------

def test_schedule_from_round_1():
    state = _state(round_number=1)
    out = MINORS[CARD_ID].on_play(state, 0)
    p = out.players[0]
    # Remaining evens 2,4,6,8,10,12,14 -> food,clay,food,clay,food,clay,food.
    assert [i for i, f in enumerate(_food(p)) if f] == [1, 5, 9, 13]   # rounds 2,6,10,14
    assert [i for i, c in enumerate(_clay(p)) if c] == [3, 7, 11]      # rounds 4,8,12
    assert all(f in (0, 1) for f in _food(p))
    assert all(c in (0, 1) for c in _clay(p))


def test_schedule_midgame_clamps_to_remaining():
    """Played during round 5: only even spaces strictly after 5 remain (6..14),
    still starting with food."""
    state = _state(round_number=5)
    out = MINORS[CARD_ID].on_play(state, 0)
    p = out.players[0]
    assert [i for i, f in enumerate(_food(p)) if f] == [5, 9, 13]      # rounds 6,10,14
    assert [i for i, c in enumerate(_clay(p)) if c] == [7, 11]         # rounds 8,12


def test_schedule_late_game_single_space():
    """Played during round 13: only round 14 remains -> a single food."""
    state = _state(round_number=13)
    out = MINORS[CARD_ID].on_play(state, 0)
    p = out.players[0]
    assert [i for i, f in enumerate(_food(p)) if f] == [13]            # round 14
    assert sum(_clay(p)) == 0


# ---------------------------------------------------------------------------
# Real play end-to-end
# ---------------------------------------------------------------------------

def test_real_play_lands_and_scores():
    state = _state(round_number=1,
                   occupations=frozenset({"o0", "o1", "o2", "o3", "o4"}))   # 5 cards
    cp = 0
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    state = fast_replace(state, players=tuple(p if i == cp else state.players[i] for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    assert CARD_ID in playable_minors(state, cp)
    (commit,) = [a for a in legal_actions(state)
                 if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    out = step(state, commit)
    p = out.players[cp]
    assert CARD_ID in p.minor_improvements
    assert _food(p)[1] == 1 and _clay(p)[3] == 1     # rounds 2 (food), 4 (clay)


def test_not_playable_below_five_cards():
    state = _state(round_number=1, occupations=frozenset({"o0", "o1", "o2", "o3"}))  # 4
    cp = 0
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    state = fast_replace(state, players=tuple(p if i == cp else state.players[i] for i in range(2)))
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    assert CARD_ID not in playable_minors(state, cp)
