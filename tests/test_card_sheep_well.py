"""Tests for Sheep Well (minor improvement, D45; Consul Dirigens Expansion).

Card text: "Place 1 food on each of the next round spaces, up to the number of
sheep you have. At the start of these rounds, you get the food."
Cost: 2 Stone. No prerequisite. VPs: 2. Not passing.

Category-8 deferred-goods card (mirrors tests/test_card_trellises.py): the whole
effect runs at play (on_play), scheduling +1 food onto rounds R+1..R+N where
N = the player's current sheep count. Collection rides on `future_resources`, paid
out at the start of each scheduled round by `_complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.sheep_well  # noqa: F401  (registers the card; not in __init__)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Phase
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_sheep(state, idx, n):
    """Give player `idx` exactly `n` sheep (bare animal count; no accommodation
    check — we only care about the on_play cap source)."""
    p = state.players[idx]
    p = fast_replace(p, animals=fast_replace(p.animals, sheep=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_sheep_well_registered():
    assert "sheep_well" in MINORS
    spec = MINORS["sheep_well"]
    assert spec.cost == Cost(resources=Resources(stone=2))
    assert spec.vps == 2
    assert spec.passing_left is False
    # Pure on-play minor — no trigger/hook machinery.
    for entries in TRIGGERS.values():
        assert "sheep_well" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# on_play scheduling — N sheep → +1 food on the next N round spaces
# ---------------------------------------------------------------------------

def test_on_play_schedules_next_n_round_spaces():
    s = _set_sheep(setup(0), 0, 3)     # R=1, 3 sheep → rounds 2,3,4
    assert s.players[0].animals.sheep == 3
    out = MINORS["sheep_well"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0                   # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == 1   # rounds 2,3,4
    assert f[4] == 0                   # round 5 not scheduled
    assert sum(f) == 3


def test_on_play_cap_is_sheep_count():
    # 5 sheep → 5 scheduled rounds.
    s = _set_sheep(setup(0), 0, 5)     # R=1 → rounds 2..6
    out = MINORS["sheep_well"].on_play(s, 0)
    f = _food(out, 0)
    assert [f[i] for i in range(1, 6)] == [1, 1, 1, 1, 1]
    assert sum(f) == 5


def test_on_play_zero_sheep_schedules_nothing():
    s = setup(0)
    assert s.players[0].animals.sheep == 0
    out = MINORS["sheep_well"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_count_ignores_other_animals():
    # Boar/cattle don't count — only sheep are the cap.
    s = setup(0)
    p = s.players[0]
    p = fast_replace(p, animals=Animals(sheep=2, boar=3, cattle=4))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    out = MINORS["sheep_well"].on_play(s, 0)
    f = _food(out, 0)
    assert f[1] == 1 and f[2] == 1     # rounds 2,3 only (2 sheep)
    assert sum(f) == 2


def test_on_play_clamps_past_round_14():
    # Round 12 with 5 sheep → rounds 13,14 scheduled; 15,16,17 dropped by the
    # 1..14 slot clamp (the "up to ... remaining round spaces" cap, for free).
    s = _set_sheep(fast_replace(setup(0), round_number=12), 0, 5)
    out = MINORS["sheep_well"].on_play(s, 0)
    f = _food(out, 0)
    assert f[12] == 1 and f[13] == 1   # rounds 13, 14
    assert sum(f) == 2                  # only 2 remaining rounds, not 5


def test_on_play_starts_after_current_round_midgame():
    # Mid-game (R=7): scheduling starts at R+1=8, never re-credits the current round.
    s = _set_sheep(fast_replace(setup(0), round_number=7), 0, 2)
    out = MINORS["sheep_well"].on_play(s, 0)
    f = _food(out, 0)
    assert f[6] == 0                    # round 7 (current) untouched
    assert f[7] == 1 and f[8] == 1      # rounds 8, 9
    assert sum(f) == 2


# ---------------------------------------------------------------------------
# End-to-end: play the minor at a real PendingPlayMinor, then collect at round start
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("sheep_well",) + tuple(f"m{i}" for i in range(20)),
)


def test_play_minor_flow_and_round_start_collection():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    # Give the player the card in hand, the stone to pay, and 2 sheep.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"sheep_well"}),
                     resources=Resources(stone=2),
                     animals=Animals(sheep=2))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))

    # Drive a real PendingPlayMinor and commit the card.
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "sheep_well"))

    # Card left the hand; cost paid; food scheduled on rounds 2 and 3 (R=1, 2 sheep).
    pl = cs.players[cp]
    assert "sheep_well" in pl.minor_improvements
    assert "sheep_well" not in pl.hand_minors
    assert pl.resources.stone == 0
    f = _food(cs, cp)
    assert f[1] == 1 and f[2] == 1 and f[0] == 0 and f[3] == 0

    # Collection at the start of round 2: _complete_preparation pays out the slot.
    food_before = cs.players[cp].resources.food
    prep = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    prep = _complete_preparation(prep)
    while prep.pending_stack:                       # resolve the reveal nature step
        prep = step(prep, legal_actions(prep)[0])
    assert prep.round_number == 2
    assert prep.players[cp].resources.food == food_before + 1
