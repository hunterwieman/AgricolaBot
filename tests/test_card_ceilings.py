"""Tests for Ceilings (minor improvement, B76; Bubulcus Expansion; cost 1 clay,
prereq 1 occupation).

Card text: "Place 1 wood on the next 5 round spaces. At the start of these rounds,
you get the wood. Remove the wood promised by this card from future round spaces
the next time you renovate."

Two clauses, tested here:
- on_play schedules 1 wood onto rounds R+1..R+5 of `future_resources` and records the
  seeded slot indices in the per-card CardStore (fewer than 5 when < 5 rounds remain).
- the MANDATORY `after_renovate` auto removes exactly 1 wood from each recorded slot
  that is STILL UNCOLLECTED (`slot >= round_number`), keeps wood already collected,
  and clears the record (once-only latch — a second renovate does nothing). Wood other
  schedulers placed on the same slots survives (subtract-exactly-1, never clamped).

The renovate flow is driven end-to-end through the House Redevelopment space (the
roughcaster idiom), so the real `after_renovate` firing point is exercised.
"""
from __future__ import annotations

import agricola.cards.ceilings  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS, apply_auto_effects
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space as state_with_space
from tests.factories import add_resources, with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_play_minor, sole_renovate

CARD_ID = "ceilings"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wood(state: GameState, idx: int):
    return [r.wood for r in state.players[idx].future_resources]


def _record(state: GameState, idx: int):
    return state.players[idx].card_state.get(CARD_ID, ())


def _with_occupations(state: GameState, idx: int, occ):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occ))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state: GameState, idx: int, card_id: str) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _drive_renovate(state, commit):
    """Drive the real House Redevelopment renovate flow to a turn-complete state
    (the roughcaster idiom). `commit` is the CommitRenovate (or a thunk producing one)."""
    return run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        commit,       # applies the renovate
        Stop(),       # pop PendingRenovate after-phase (after_renovate fired here)
        Proceed(),    # flip the host (house_redevelopment) to its after-phase
        Stop(),       # pop the host → turn complete
    ])


def _renovate_ready(state: GameState, idx: int = 0, material=HouseMaterial.CLAY):
    """A card-mode state with `idx`'s house set to `material` (default clay, 2 rooms →
    renovate to stone costs 2 stone + 1 reed), the House Redevelopment space revealed,
    and materials to pay the renovate."""
    state = with_house(state, idx, material)
    state = with_resources(state, idx, stone=2, reed=1)
    state = with_space(state, "house_redevelopment", revealed=True)
    return state


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_ceilings_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=1))
    assert spec.min_occupations == 1     # "1 Occupation" prerequisite
    assert spec.vps == 0
    assert spec.passing_left is False
    # The removal clause is a MANDATORY auto → in after_renovate, not the declinable list.
    ids = {e.card_id for e in AUTO_EFFECTS.get("after_renovate", [])}
    assert CARD_ID in ids
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


def test_ceilings_prereq_requires_one_occupation():
    spec = MINORS[CARD_ID]
    s = setup(0)
    assert not prereq_met(spec, s, 0)                       # 0 occupations → fails
    s1 = _with_occupations(s, 0, ("oa",))
    assert prereq_met(spec, s1, 0)                          # exactly 1 → met
    s2 = _with_occupations(s, 0, ("oa", "ob"))
    assert prereq_met(spec, s2, 0)                          # 2 → still met (>= bound)


# ---------------------------------------------------------------------------
# on_play: schedule + record
# ---------------------------------------------------------------------------

def test_ceilings_on_play_seeds_5_slots_and_records():
    s = setup(0)   # R = 1 → next 5 rounds are 2..6 (slots 1..5)
    out = MINORS[CARD_ID].on_play(s, 0)
    wood = _wood(out, 0)
    for rnd in (2, 3, 4, 5, 6):
        assert wood[rnd - 1] == 1
    assert sum(wood) == 5
    # Current + past round spaces untouched.
    assert wood[0] == 0
    for rnd in (7, 8, 9, 10, 11, 12, 13, 14):
        assert wood[rnd - 1] == 0
    # Record holds exactly the seeded slots, sorted.
    assert _record(out, 0) == (1, 2, 3, 4, 5)
    # Only the owner is scheduled/recorded.
    assert sum(_wood(out, 1)) == 0
    assert _record(out, 1) == ()


def test_ceilings_on_play_fewer_when_few_rounds_remain():
    # R = 12 → next 5 rounds would be 13..17, but 15/16/17 are out of the game.
    # Only rounds 13, 14 (slots 12, 13) are seeded and recorded.
    s = fast_replace(setup(0), round_number=12)
    out = MINORS[CARD_ID].on_play(s, 0)
    wood = _wood(out, 0)
    assert wood[12] == 1 and wood[13] == 1
    assert sum(wood) == 2
    assert _record(out, 0) == (12, 13)


def test_ceilings_on_play_last_round_seeds_nothing():
    # R = 14 → rounds 15..19 all out of game; nothing placed, nothing recorded.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sum(_wood(out, 0)) == 0
    assert _record(out, 0) == ()


def test_ceilings_schedule_is_additive():
    # on_play adds onto pre-existing promises (schedule_resources is additive).
    s = setup(0)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[3] = fr[3] + Resources(wood=2)   # round 4 already has 2 wood promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr)), s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _wood(out, 0)[3] == 3        # 2 pre-existing + 1 from Ceilings


# ---------------------------------------------------------------------------
# Collection at round start (the schedule half works end-to-end)
# ---------------------------------------------------------------------------

def test_ceilings_collected_at_scheduled_round_start():
    s = MINORS[CARD_ID].on_play(setup(0), 0)   # seeds rounds 2..6
    wood_before = s.players[0].resources.wood
    # Sit in PREPARATION on round 1; completing it enters round 2 (a scheduled round).
    s = fast_replace(s, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.wood == wood_before + 1
    assert out.players[0].future_resources[1].wood == 0   # consumed slot cleared


# ---------------------------------------------------------------------------
# Removal on renovate
# ---------------------------------------------------------------------------

def test_ceilings_renovate_before_collection_removes_all():
    # Play at round 1 (seeds slots 1..5), renovate in round 1 before any collection →
    # every seeded slot is still uncollected, so all 5 wood are removed; record cleared.
    cs = _card_state()                             # round_number == 1
    cs = _own_minor(cs, 0, CARD_ID)
    cs = MINORS[CARD_ID].on_play(cs, 0)
    assert _record(cs, 0) == (1, 2, 3, 4, 5)
    cs = _renovate_ready(cs, 0, HouseMaterial.CLAY)
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert sum(_wood(cs, 0)) == 0                   # all promised wood removed
    assert _record(cs, 0) == ()                     # latch cleared


def test_ceilings_renovate_after_some_collection_keeps_collected_wood():
    # Play at round 1 (seeds slots 1..5 = rounds 2..6), then simulate collecting
    # rounds 2 and 3 (slots 1, 2 → wood moved into supply, slots zeroed, round_number=3).
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = MINORS[CARD_ID].on_play(cs, 0)
    p = cs.players[0]
    fr = list(p.future_resources)
    collected = fr[1].wood + fr[2].wood            # == 2 (1 each)
    fr[1] = fr[1] - Resources(wood=fr[1].wood)     # zero slot 1 (round 2 collected)
    fr[2] = fr[2] - Resources(wood=fr[2].wood)     # zero slot 2 (round 3 collected)
    cs = fast_replace(cs, round_number=3,
                      players=(fast_replace(p, future_resources=tuple(fr)), cs.players[1]))
    # Renovate materials, then ADD the collected wood already sitting in supply.
    cs = _renovate_ready(cs, 0, HouseMaterial.CLAY)   # sets stone=2, reed=1 (wood=0)
    cs = add_resources(cs, 0, wood=collected)
    supply_before = cs.players[0].resources.wood      # == collected (2)

    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.STONE
    wood = _wood(cs, 0)
    # Uncollected slots (3, 4, 5 = rounds 4, 5, 6) had their 1 wood removed.
    assert wood[3] == 0 and wood[4] == 0 and wood[5] == 0
    assert sum(wood) == 0
    # Collected wood (already in supply) is untouched by the renovate (which spends no wood).
    assert cs.players[0].resources.wood == supply_before
    assert _record(cs, 0) == ()                        # latch cleared


def test_ceilings_second_renovate_does_nothing():
    # After the first renovate clears the record, the after_renovate auto is a no-op for
    # Ceilings. The first renovate is driven end-to-end; the second is exercised through
    # the real firing dispatch (apply_auto_effects — exactly what the engine calls at the
    # after_renovate boundary), avoiding a fiddly full board reset for a second placement.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = MINORS[CARD_ID].on_play(cs, 0)
    cs = _renovate_ready(cs, 0, HouseMaterial.CLAY)
    cs = _drive_renovate(cs, sole_renovate)          # clay -> stone; record cleared
    assert _record(cs, 0) == ()
    # Fresh wood promised on a future slot (as if another schedule card ran later).
    p = cs.players[0]
    fr = list(p.future_resources)
    fr[7] = fr[7] + Resources(wood=1)                # round 8 now has 1 wood
    cs = fast_replace(cs, players=(fast_replace(p, future_resources=tuple(fr)), cs.players[1]))
    wood_before = list(_wood(cs, 0))
    # A second renovate would fire this event again — but the latch is spent, so nothing moves.
    out = apply_auto_effects(cs, "after_renovate", 0)
    assert _wood(out, 0) == wood_before              # unchanged — latch already spent
    assert _record(out, 0) == ()


def test_ceilings_removal_keeps_other_scheduler_wood():
    # Another scheduler placed 2 extra wood on one of Ceilings' slots. Renovate before
    # collection removes EXACTLY the 1 wood Ceilings added there — the other 2 survive.
    cs = _card_state()
    cs = _own_minor(cs, 0, CARD_ID)
    cs = MINORS[CARD_ID].on_play(cs, 0)              # slots 1..5 each have 1 wood
    p = cs.players[0]
    fr = list(p.future_resources)
    fr[3] = fr[3] + Resources(wood=2)               # slot 3 (round 4) now has 1 + 2 = 3
    cs = fast_replace(cs, players=(fast_replace(p, future_resources=tuple(fr)), cs.players[1]))
    cs = _renovate_ready(cs, 0, HouseMaterial.CLAY)
    cs = _drive_renovate(cs, sole_renovate)
    wood = _wood(cs, 0)
    assert wood[3] == 2                              # 3 - 1 = 2 (other scheduler survives)
    # All other Ceilings slots dropped to 0.
    for s in (1, 2, 4, 5):
        assert wood[s] == 0
    assert _record(cs, 0) == ()


def test_ceilings_unowned_renovate_does_nothing():
    # A player who never played Ceilings (no record, not owned) renovating → no effect,
    # even if future_resources happens to hold wood on those slots.
    cs = _card_state()
    p = cs.players[0]
    fr = list(p.future_resources)
    fr[1] = fr[1] + Resources(wood=1)               # stray wood, but Ceilings not owned
    cs = fast_replace(cs, players=(fast_replace(p, future_resources=tuple(fr)), cs.players[1]))
    cs = _renovate_ready(cs, 0, HouseMaterial.CLAY)
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert _wood(cs, 0)[1] == 1                      # untouched — card not owned


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=state_with_space(state.board, "major_improvement", sp))


def test_ceilings_played_via_engine_schedules_and_records():
    # Drive the actual play-minor flow through the Major Improvement space in CARDS mode.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, clay=1)                       # afford the 1-clay cost
    cs = _with_occupations(cs, cp, ("oa",))                   # satisfy the 1-occupation prereq
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    clay_before = cs.players[cp].resources.clay

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    assert CARD_ID in cs.players[cp].minor_improvements
    wood = _wood(cs, cp)
    for rnd in (2, 3, 4, 5, 6):
        assert wood[rnd - 1] == 1
    assert sum(wood) == 5
    assert _record(cs, cp) == (1, 2, 3, 4, 5)
    assert cs.players[cp].resources.clay == clay_before - 1   # cost paid
