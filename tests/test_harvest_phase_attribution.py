"""Phase attribution of the harvest walk's outer windows (Cards mode).

User-approved design (2026-07-27, following ruling 85's harvest boundary): the
CARDS-mode harvest walk gives the four OUTER windows honest Phase values —
``PRE_HARVEST`` over the two lead windows (``immediately_before_harvest``,
``start_of_harvest``), ``END_OF_HARVEST`` at the ``end_of_harvest`` window and
``AFTER_HARVEST`` at ``after_harvest`` (ruling 85 put the tail outside the
harvest span, so labeling those states HARVEST_BREED was misleading), while the
three phase BANDS keep HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED exactly as
before (through ``after_breeding``). The FAMILY walk is gated out entirely: its
phase sequence — entry HARVEST_FIELD through the lead windows and FIELD band,
HARVEST_BREED through the tail — is byte-identical to the pre-change engine,
load-bearing for the C++ twin and the NN encoder (neither knows the new
members).

Three test groups:

1. **Cards-walk attribution** — drive one real Cards harvest whose owned cards
   pause the walk in every segment, and pin the phase each paused state
   carries: Autumn Mother's lead-window frame under PRE_HARVEST, Food
   Merchant's occasion host (at the take) under HARVEST_FIELD (the flip-back
   after the lead-in), the FEED/BREED frames under their band phases, Winter
   Caretaker's frame under END_OF_HARVEST, Value Assets' frame under
   AFTER_HARVEST.
2. **Family byte-identity** — a full random Family game never produces the new
   values, and a Family-mode walk with a hand-given tail card (the shape most
   card unit tests drive) still pauses at end_of_harvest under HARVEST_BREED.
3. **Unit-level tail reads** — `in_conversion_span` / `post_breed_floors`
   answer out-of-span / lapsed at the Cards tail shapes purely from the phase,
   the stored cursor AND the cursor-None probe shape alike (the walk's
   eligibility probes run with the cursor cleared — the probe answering
   correctly is what kills the Proceed-only-frame residue, pinned end-to-end
   in test_card_winter_caretaker.py).
"""
from __future__ import annotations

import dataclasses

import numpy as np

import agricola.cards.autumn_mother    # noqa: F401  (register the cards)
import agricola.cards.food_merchant    # noqa: F401
import agricola.cards.value_assets     # noqa: F401
import agricola.cards.winter_caretaker # noqa: F401

from agricola.actions import (
    CommitBreed,
    CommitConvert,
    CommitFieldTake,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_windows import (
    in_conversion_span,
    post_breed_floors,
    sentinel_position,
)
from agricola.constants import CellType, GameMode, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHarvestOccasion,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import (
    with_grid,
    with_majors,
    with_phase,
    with_resources,
    with_sown_fields,
)

NEW_PHASES = {Phase.PRE_HARVEST, Phase.END_OF_HARVEST, Phase.AFTER_HARVEST}
BAND_PHASES = {Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED}
ALL_HARVEST_PHASES = BAND_PHASES | NEW_PHASES

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, *, occupations=(), minors=()):
    p = state.players[idx]
    p = dataclasses.replace(
        p,
        occupations=p.occupations | set(occupations),
        minor_improvements=p.minor_improvements | set(minors),
    )
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _neutral_action(state):
    """Advance the walk WITHOUT firing any card or converter surface: the
    mechanical commits first, then Proceed/Stop, never a FireTrigger or a
    CommitHarvestConversion (the test_card_plow_builder walker)."""
    actions = legal_actions(state)
    for kind in (CommitFieldTake, CommitConvert, CommitBreed):
        for a in actions:
            if isinstance(a, kind):
                return a
    for a in actions:
        if isinstance(a, (Proceed, Stop)):
            return a
    for a in actions:
        if not isinstance(a, (FireTrigger, CommitHarvestConversion)):
            return a
    raise AssertionError(f"no neutral action among {actions}")


# ---------------------------------------------------------------------------
# 1. Cards-walk attribution
# ---------------------------------------------------------------------------

def _cards_state_pausing_everywhere():
    """A CARDS-mode HARVEST_FIELD-phase state whose walk pauses in every
    segment for P0: Autumn Mother (lead window #1; needs a free room + a
    payable 3 food), Food Merchant (an occasion host at the take; needs
    harvested grain + a payable buy), Winter Caretaker (end_of_harvest;
    payable 2 food), Value Assets (after_harvest minor; payable 1 food).
    P0 is food-rich so every fee is directly payable; P1 is food-rich so its
    frames resolve trivially."""
    cs, _env = setup_env(5, card_pool=_POOL)
    assert cs.mode is GameMode.CARDS
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), harvest_cursor=None)
    cs = _own(cs, 0,
              occupations=("autumn_mother", "food_merchant", "winter_caretaker"),
              minors=("value_assets",))
    # Autumn Mother's condition: a worker in supply (setup leaves both home)
    # and people_total < rooms -> give P0 a third room.
    cs = with_grid(cs, 0, {(0, 4): Cell(cell_type=CellType.ROOM)})
    # Food Merchant's condition: grain harvested at the take.
    cs = with_sown_fields(cs, 0, grain_fields=((0, 1),))
    cs = with_resources(cs, 0, food=20)
    cs = with_resources(cs, 1, food=99)
    return cs


def test_cards_walk_phase_attribution():
    """One Cards harvest, neutral-stepped: every paused state carries the
    honest phase of its walk segment, and the walk completes into
    PREPARATION."""
    state = _cards_state_pausing_everywhere()
    pauses = []          # (frame kind, window id or None, player_idx, phase)
    state = _advance_until_decision(state)
    for _ in range(300):
        if state.phase not in ALL_HARVEST_PHASES:
            break
        top = state.pending_stack[-1]
        if isinstance(top, PendingHarvestWindow):
            pauses.append(("window", top.window_id, top.player_idx, state.phase))
        elif isinstance(top, PendingHarvestOccasion):
            pauses.append(("occasion", None, top.player_idx, state.phase))
        elif isinstance(top, PendingHarvestFeed):
            pauses.append(("feed", None, top.player_idx, state.phase))
        elif isinstance(top, PendingHarvestBreed):
            pauses.append(("breed", None, top.player_idx, state.phase))
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")

    # The lead window: Autumn Mother's frame pauses under PRE_HARVEST.
    assert ("window", "immediately_before_harvest", 0, Phase.PRE_HARVEST) in pauses
    # The FIELD band re-stamps HARVEST_FIELD after the PRE_HARVEST lead-in:
    # Food Merchant's occasion host (pushed at P0's take) pauses under it.
    assert ("occasion", None, 0, Phase.HARVEST_FIELD) in pauses
    # The FEED and BREED bands keep their phases (both players' frames).
    for idx in (0, 1):
        assert ("feed", None, idx, Phase.HARVEST_FEED) in pauses
        assert ("breed", None, idx, Phase.HARVEST_BREED) in pauses
    # The tail: Winter Caretaker's end_of_harvest frame under END_OF_HARVEST,
    # Value Assets' after_harvest frame under AFTER_HARVEST.
    assert ("window", "end_of_harvest", 0, Phase.END_OF_HARVEST) in pauses
    assert ("window", "after_harvest", 0, Phase.AFTER_HARVEST) in pauses
    # No pause ever carried a mismatched segment phase: every window pause's
    # phase is a function of its window id.
    expected = {
        "immediately_before_harvest": Phase.PRE_HARVEST,
        "start_of_harvest": Phase.PRE_HARVEST,
        "end_of_harvest": Phase.END_OF_HARVEST,
        "after_harvest": Phase.AFTER_HARVEST,
    }
    for kind, window_id, _idx, phase in pauses:
        if kind == "window" and window_id in expected:
            assert phase is expected[window_id], (window_id, phase)
    # The harvest completed normally.
    assert state.phase is Phase.PREPARATION
    assert state.harvest_cursor is None


def test_cards_outer_pauses_resume_the_walk():
    """A paused outer-window frame's pop re-enters the walk (the
    _advance_until_decision dispatch covers the new phases): stepping Proceed
    at the END_OF_HARVEST pause reaches the AFTER_HARVEST pause, then
    PREPARATION — no stall, no assertion."""
    state = _cards_state_pausing_everywhere()
    state = _advance_until_decision(state)
    seen = []
    for _ in range(300):
        if state.phase not in ALL_HARVEST_PHASES:
            break
        top = state.pending_stack[-1]
        if isinstance(top, PendingHarvestWindow):
            seen.append((top.window_id, state.phase))
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert ("end_of_harvest", Phase.END_OF_HARVEST) in seen
    assert ("after_harvest", Phase.AFTER_HARVEST) in seen
    # end_of_harvest resolved BEFORE after_harvest (the ladder order).
    assert (seen.index(("end_of_harvest", Phase.END_OF_HARVEST))
            < seen.index(("after_harvest", Phase.AFTER_HARVEST)))
    assert state.phase is Phase.PREPARATION


# ---------------------------------------------------------------------------
# 2. Family byte-identity
# ---------------------------------------------------------------------------

def test_family_full_game_never_produces_new_phases():
    """A full random Family game (every decision state observed) never carries
    PRE_HARVEST / END_OF_HARVEST / AFTER_HARVEST — the honest outer phases are
    CARDS-walk-only, so the Family phase sequence the C++ twin and the encoder
    were built against is unchanged."""
    for seed in (3, 11):
        state = setup(seed=seed)
        rng = np.random.default_rng(seed)
        assert state.mode is GameMode.FAMILY
        steps = 0
        while state.phase != Phase.BEFORE_SCORING:
            assert state.phase not in NEW_PHASES, (seed, steps, state.phase)
            actions = legal_actions(state)
            state = step(state, actions[int(rng.integers(len(actions)))])
            steps += 1
        assert state.phase not in NEW_PHASES


def test_family_walk_with_tail_card_still_pauses_under_harvest_breed():
    """The gating, from the other side: a FAMILY-mode state with a hand-given
    tail card (the shape most card unit tests drive) still hosts its
    end_of_harvest frame under Phase.HARVEST_BREED — the honest tail phases
    are stamped only when state.mode is CARDS."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = _own(state, 0, occupations=("winter_caretaker",))
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=99)

    state = _advance_until_decision(state)
    for _ in range(300):
        if state.phase not in ALL_HARVEST_PHASES:
            raise AssertionError("walk ended without an end_of_harvest pause")
        assert state.phase not in NEW_PHASES        # Family: never
        top = state.pending_stack[-1]
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "end_of_harvest"):
            assert state.phase is Phase.HARVEST_BREED
            assert state.harvest_cursor == (
                sentinel_position("end_of_harvest", None) + 1)
            return
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


# ---------------------------------------------------------------------------
# 3. Unit-level tail reads (the probe shape included)
# ---------------------------------------------------------------------------

def _cards_tail_state(phase, cursor):
    """A minimal CARDS-mode state at a tail shape: P0 owns the Joinery (a span
    converter input on hand) and 3 sheep, so an in-span answer would surface
    the converter and a bound answer would floor the sheep."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), phase=phase,
        harvest_cursor=cursor)
    cs = with_majors(cs, owner_by_idx={7: 0})
    cs = with_resources(cs, 0, wood=1)
    p = cs.players[0]
    p = dataclasses.replace(p, animals=dataclasses.replace(p.animals, sheep=3))
    return dataclasses.replace(cs, players=(p, cs.players[1]))


def test_span_and_floors_at_cards_tail_phases():
    """At the Cards tail shapes the phase read alone answers: out of span and
    floors lapsed — for the stored-cursor pause shape AND the cursor-None
    probe shape (the walk's eligibility probes run with the cursor cleared;
    the probe answering correctly is the residue fix)."""
    eoh_pos = sentinel_position("end_of_harvest", None)
    ah_pos = sentinel_position("after_harvest", None)
    for phase, stored in ((Phase.END_OF_HARVEST, eoh_pos + 1),
                          (Phase.AFTER_HARVEST, ah_pos + 1)):
        for cursor in (stored, None):
            s = _cards_tail_state(phase, cursor)
            assert not in_conversion_span(s, 0), (phase, cursor)
            assert post_breed_floors(s, 0) == (0, 0, 0), (phase, cursor)


def test_span_and_floors_at_cards_lead_phase():
    """PRE_HARVEST (the lead windows) is pre-span and unfloored — at the
    stored-cursor pause shape (a window-#1 frame stores cursor 1) and the
    cursor-None probe shape alike."""
    for cursor in (1, None):
        s = _cards_tail_state(Phase.PRE_HARVEST, cursor)
        assert not in_conversion_span(s, 0), cursor
        assert post_breed_floors(s, 0) == (0, 0, 0), cursor
