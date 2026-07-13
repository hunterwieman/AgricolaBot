"""Tests for Hauberg (minor improvement, B41; Bubulcus Expansion).

Card text: "Alternate placing 2 wood and 1 wild boar on the next 4 round spaces.
You decide what to start with. At the start of these rounds, you get the goods."
Cost: 3 Food. Prereq: 3 Occupations.

The start-with-which choice surfaces WIDE via `register_play_minor_variant`
("wood_first" / "boar_first", both zero-surcharge — the 3-food cost is the
ordinary base cost). Wood rides on future_resources, boar on future_rewards
(collected + accommodated at round start).
"""
import json
from pathlib import Path

import agricola.cards.hauberg  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_resources, with_round

CARD_ID = "hauberg"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Hauberg")


def _at_play_minor_frame(round_number=1, occupations=frozenset({"o0", "o1", "o2"}),
                         food=3):
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}),
                     occupations=occupations)
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_round(state, round_number)
    state = with_resources(state, cp, food=food)
    state = with_pending_stack(
        state, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def _wood(p):
    return [r.wood for r in p.future_resources]


def _boar(p):
    return [fr.animals.boar for fr in p.future_rewards]


# ---------------------------------------------------------------------------
# Registration & prereq
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "3 Food"
    assert _ROW["prerequisites"] == "3 Occupations"
    assert _ROW["text"] == (
        "Alternate placing 2 wood and 1 wild boar on the next 4 round spaces. "
        "You decide what to start with. At the start of these rounds, you get "
        "the goods.")
    import agricola.cards.hauberg as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=3))
    assert spec.min_occupations == 3
    assert CARD_ID in PLAY_MINOR_VARIANTS


def test_prereq_three_occupations():
    spec = MINORS[CARD_ID]
    ok, cp = _at_play_minor_frame(occupations=frozenset({"o0", "o1", "o2"}))
    assert prereq_met(spec, ok, cp)
    bad, cp = _at_play_minor_frame(occupations=frozenset({"o0", "o1"}))
    assert not prereq_met(spec, bad, cp)
    assert CARD_ID not in playable_minors(bad, cp)


def test_both_orderings_offered_wide():
    state, _cp = _at_play_minor_frame()
    assert {a.variant for a in _plays(state)} == {"wood_first", "boar_first"}


# ---------------------------------------------------------------------------
# Scheduling: the two alternations (round 1 -> spaces R+1..R+4 = rounds 2..5)
# ---------------------------------------------------------------------------

def test_wood_first_alternation():
    state, cp = _at_play_minor_frame(round_number=1)
    (wf,) = [a for a in _plays(state) if a.variant == "wood_first"]
    out = step(state, wf)
    p = out.players[cp]
    assert p.resources.food == 0             # 3-food base cost paid
    assert _wood(p)[1] == 2 and _wood(p)[3] == 2      # wood on rounds 2, 4
    assert _wood(p)[2] == 0 and _wood(p)[4] == 0
    assert _boar(p)[2] == 1 and _boar(p)[4] == 1      # boar on rounds 3, 5
    assert _boar(p)[1] == 0 and _boar(p)[3] == 0


def test_boar_first_alternation():
    state, cp = _at_play_minor_frame(round_number=1)
    (bf,) = [a for a in _plays(state) if a.variant == "boar_first"]
    out = step(state, bf)
    p = out.players[cp]
    assert _boar(p)[1] == 1 and _boar(p)[3] == 1      # boar on rounds 2, 4
    assert _wood(p)[2] == 2 and _wood(p)[4] == 2      # wood on rounds 3, 5
    assert _wood(p)[1] == 0 and _boar(p)[2] == 0


def test_clamps_past_round_14():
    """Played round 12: spaces are rounds 13,14,15,16 — only 13,14 land."""
    state, cp = _at_play_minor_frame(round_number=12)
    (wf,) = [a for a in _plays(state) if a.variant == "wood_first"]
    out = step(state, wf)
    p = out.players[cp]
    assert _wood(p)[12] == 2         # round 13 gets wood (start)
    assert _boar(p)[13] == 1         # round 14 gets boar
    assert sum(_wood(p)) == 2        # rounds 15,16 dropped
    assert sum(_boar(p)) == 1
