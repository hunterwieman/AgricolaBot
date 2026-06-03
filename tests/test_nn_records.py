"""Smoke tests for the NN data-record schema in `agricola/agents/nn.py`.

Covers:
- DecisionSnapshot / GameRecord construction with a real GameState.
- Pickle roundtrip preserves all fields.
- DATA_VERSION mismatch is detected hard-fail at load time
  (the protocol's whole point — silent skipping would defeat it).
- ENCODING_VERSION and DATA_VERSION are exposed as module constants.
"""

from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path

import pytest

from agricola.actions import PlaceWorker
from agricola.agents.base import RandomAgent, decider_of
from agricola.agents.nn import (
    DATA_VERSION,
    ENCODING_VERSION,
    DataVersionMismatch,
    DecisionSnapshot,
    GameRecord,
    compute_winner,
    load_game_records,
    play_recording_game,
)
from agricola.constants import Phase
from agricola.legality import legal_actions
from agricola.setup import setup, setup_env
from tests.test_utils import filter_implemented


def _make_minimal_record(*, game_idx: int = 0, seed: int = 0,
                          data_version: int = DATA_VERSION) -> GameRecord:
    """Build a tiny but real GameRecord: one snapshot from setup(seed)
    using the first legal action, plus a synthetic terminal state.
    Used as the test fixture.

    The terminal state is fabricated by phase-flipping the setup state
    via `dataclasses.replace` — not engine-realistic, but a valid
    `GameState` with `phase=BEFORE_SCORING` for schema-roundtrip purposes.
    Tests that need a *real* terminal state should play a game; this
    fixture is intentionally cheap for schema-only smoke testing.
    """
    state = setup(seed=seed)
    actions = legal_actions(state)
    assert len(actions) > 0, "Setup state must have at least one legal action."
    chosen = actions[0]
    snapshot = DecisionSnapshot(
        state=state,
        chosen_action=chosen,
        decider_idx=decider_of(state),
    )
    fake_terminal = replace(state, phase=Phase.BEFORE_SCORING)
    return GameRecord(
        data_version=data_version,
        game_idx=game_idx,
        seed=seed,
        p0_config_path="v1_t2",
        p1_config_path="tuned_configs/v3_best.json",
        p0_temperature=0.5,
        p1_temperature=0.8,
        p0_final_score=42,
        p1_final_score=38,
        winner=0,                  # P0 wins this fixture game
        terminal_state=fake_terminal,
        decisions=(snapshot,),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_module_exposes_version_constants():
    """The two version constants must be importable module-level ints.
    They're load-bearing for the schema-versioning protocol — any
    refactor that moves or renames them is a breaking change."""
    assert isinstance(DATA_VERSION, int) and DATA_VERSION >= 1
    assert isinstance(ENCODING_VERSION, int) and ENCODING_VERSION >= 1


def test_construct_record_smoke():
    """Building a GameRecord with a real GameState round-trips through
    construction without error."""
    rec = _make_minimal_record()
    assert rec.data_version == DATA_VERSION
    assert rec.game_idx == 0
    assert rec.seed == 0
    assert len(rec.decisions) == 1
    snap = rec.decisions[0]
    assert isinstance(snap.chosen_action, PlaceWorker)
    assert snap.decider_idx in (0, 1)


def test_record_frozen():
    """Records and snapshots are frozen — mutating fields should raise.
    Matches the project-wide frozen-dataclass discipline."""
    rec = _make_minimal_record()
    with pytest.raises((AttributeError, Exception)):
        rec.game_idx = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Pickle roundtrip
# ---------------------------------------------------------------------------


def test_pickle_roundtrip_preserves_fields(tmp_path: Path):
    """Pickle/unpickle preserves every field, including the nested
    GameState. This is the operation the data-generation pipeline
    depends on — if it doesn't work, the whole pipeline is broken."""
    rec = _make_minimal_record(game_idx=7, seed=42)
    path = tmp_path / "test_worker.pkl"

    with path.open("wb") as f:
        pickle.dump([rec], f)

    loaded = load_game_records(path)
    assert len(loaded) == 1
    got = loaded[0]

    assert got.data_version == rec.data_version
    assert got.game_idx == rec.game_idx
    assert got.seed == rec.seed
    assert got.p0_config_path == rec.p0_config_path
    assert got.p1_config_path == rec.p1_config_path
    assert got.p0_temperature == rec.p0_temperature
    assert got.p1_temperature == rec.p1_temperature
    assert got.p0_final_score == rec.p0_final_score
    assert got.p1_final_score == rec.p1_final_score
    assert got.winner == rec.winner
    assert got.terminal_state == rec.terminal_state
    assert got.terminal_state.phase == Phase.BEFORE_SCORING
    assert len(got.decisions) == 1

    got_snap = got.decisions[0]
    orig_snap = rec.decisions[0]
    assert got_snap.decider_idx == orig_snap.decider_idx
    assert got_snap.chosen_action == orig_snap.chosen_action
    # GameState equality: same hash + same content (frozen dataclasses with
    # canonical-tuple BoardState — see CHANGES.md Change 8).
    assert hash(got_snap.state) == hash(orig_snap.state)
    assert got_snap.state == orig_snap.state


# ---------------------------------------------------------------------------
# DATA_VERSION mismatch detection (the protocol's load-bearing part)
# ---------------------------------------------------------------------------


def test_version_mismatch_raises_hard(tmp_path: Path):
    """A record with a stale data_version triggers DataVersionMismatch at
    load. This is the entire point of DATA_VERSION — silent fallthrough
    on mismatch would defeat the protocol. See FIRST_NN.md §10.4."""
    stale = _make_minimal_record(data_version=DATA_VERSION - 1)
    path = tmp_path / "stale_worker.pkl"
    with path.open("wb") as f:
        pickle.dump([stale], f)

    with pytest.raises(DataVersionMismatch) as excinfo:
        load_game_records(path)

    # Error message must name the version gap so the caller can fix it.
    msg = str(excinfo.value)
    assert str(DATA_VERSION) in msg
    assert str(DATA_VERSION - 1) in msg


def test_non_gamerecord_entry_raises(tmp_path: Path):
    """A pickle that doesn't contain GameRecords raises TypeError —
    catches the "I pickled the wrong thing" class of bug."""
    path = tmp_path / "wrong_type.pkl"
    with path.open("wb") as f:
        pickle.dump([{"not": "a record"}], f)

    with pytest.raises(TypeError):
        load_game_records(path)


def test_empty_pickle_returns_empty(tmp_path: Path):
    """An empty list of records is valid (just a worker that produced
    nothing yet)."""
    path = tmp_path / "empty.pkl"
    with path.open("wb") as f:
        pickle.dump([], f)

    loaded = load_game_records(path)
    assert loaded == []


# ---------------------------------------------------------------------------
# compute_winner
# ---------------------------------------------------------------------------


def test_compute_winner_score_difference():
    """Score margin is the primary criterion; tiebreaker is ignored
    when scores differ."""
    assert compute_winner(p0_score=42, p1_score=38, p0_tiebreaker=0, p1_tiebreaker=99) == 0
    assert compute_winner(p0_score=38, p1_score=42, p0_tiebreaker=99, p1_tiebreaker=0) == 1


def test_compute_winner_tiebreaker_resolves_score_tie():
    """When scores are equal, the tiebreaker decides."""
    assert compute_winner(p0_score=40, p1_score=40, p0_tiebreaker=5, p1_tiebreaker=3) == 0
    assert compute_winner(p0_score=40, p1_score=40, p0_tiebreaker=3, p1_tiebreaker=5) == 1


def test_compute_winner_true_tie_returns_none():
    """Equal scores AND equal tiebreakers → no winner."""
    assert compute_winner(p0_score=40, p1_score=40, p0_tiebreaker=3, p1_tiebreaker=3) is None


# ---------------------------------------------------------------------------
# play_recording_game
# ---------------------------------------------------------------------------


def _play_one_random_game(seed: int = 42) -> GameRecord:
    """Convenience: full RandomAgent vs RandomAgent game with the
    recording driver. Used by multiple tests below."""
    initial, env = setup_env(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        dealer=env.resolve,
        game_idx=0,
        seed=seed,
        p0_config_path="random",
        p1_config_path="random",
        p0_temperature=0.0,  # Metadata only; RandomAgent has no temperature concept.
        p1_temperature=0.0,
        legal_actions_fn=legal_actions,  # RandomAgent's default is unrestricted.
    )


def test_recording_game_returns_complete_record():
    """A full RandomAgent-vs-RandomAgent game produces a GameRecord
    with all fields populated and the terminal state at BEFORE_SCORING."""
    rec = _play_one_random_game(seed=42)

    # Metadata propagated correctly.
    assert rec.data_version == DATA_VERSION
    assert rec.game_idx == 0
    assert rec.seed == 42
    assert rec.p0_config_path == "random"
    assert rec.p1_config_path == "random"

    # Terminal state at game end.
    assert rec.terminal_state.phase == Phase.BEFORE_SCORING

    # At least one real decision should have been recorded.
    assert len(rec.decisions) > 0


def test_recording_game_snapshots_are_non_singleton(seed: int = 42):
    """Every recorded snapshot's state had >1 legal action — the
    snapshot semantics rule. Validates that singleton states were
    correctly skipped during recording."""
    rec = _play_one_random_game(seed=seed)

    for i, snap in enumerate(rec.decisions):
        actions = filter_implemented(legal_actions(snap.state))
        assert len(actions) > 1, (
            f"Snapshot {i} has only {len(actions)} legal actions — "
            f"singleton states should not be recorded. State phase: "
            f"{snap.state.phase}, decider: {snap.decider_idx}."
        )
        assert snap.chosen_action in actions, (
            f"Snapshot {i}: chosen_action {snap.chosen_action} not in "
            f"legal actions {actions}."
        )


def test_recording_game_decider_idx_matches_state():
    """Each snapshot's decider_idx equals `decider_of(snapshot.state)`."""
    rec = _play_one_random_game(seed=42)
    for snap in rec.decisions:
        assert snap.decider_idx == decider_of(snap.state)


def test_recording_game_winner_consistent_with_scores():
    """If the final-score margin is non-zero, the winner is determined
    by the higher score. If margin is zero, winner is determined by
    tiebreaker (we don't recompute it here — just sanity-check the
    rule when scores differ)."""
    rec = _play_one_random_game(seed=42)
    if rec.p0_final_score > rec.p1_final_score:
        assert rec.winner == 0
    elif rec.p1_final_score > rec.p0_final_score:
        assert rec.winner == 1
    else:
        # Score tie: winner could be 0, 1, or None depending on tiebreaker.
        # All values are valid; just check it's one of them.
        assert rec.winner in (0, 1, None)


def test_recording_game_is_deterministic():
    """Same seed → same record. This is the determinism invariant the
    whole data-generation pipeline relies on for reproducibility and
    resume-on-existing behavior. If this ever fails, the resume logic
    in step 4 is also broken."""
    rec_a = _play_one_random_game(seed=42)
    rec_b = _play_one_random_game(seed=42)

    assert rec_a.p0_final_score == rec_b.p0_final_score
    assert rec_a.p1_final_score == rec_b.p1_final_score
    assert rec_a.winner == rec_b.winner
    assert len(rec_a.decisions) == len(rec_b.decisions)
    # Hash-based comparison is sufficient since GameState is hashable
    # and a difference in any field would change the hash.
    assert hash(rec_a.terminal_state) == hash(rec_b.terminal_state)
    for snap_a, snap_b in zip(rec_a.decisions, rec_b.decisions):
        assert hash(snap_a.state) == hash(snap_b.state)
        assert snap_a.chosen_action == snap_b.chosen_action
        assert snap_a.decider_idx == snap_b.decider_idx


def test_recording_game_pickles_after_recording(tmp_path: Path):
    """A freshly recorded game can be pickled and reloaded via
    `load_game_records`. End-to-end check that the recording driver's
    output is compatible with the storage protocol."""
    rec = _play_one_random_game(seed=42)
    path = tmp_path / "recorded.pkl"
    with path.open("wb") as f:
        pickle.dump([rec], f)

    loaded = load_game_records(path)
    assert len(loaded) == 1
    assert loaded[0].p0_final_score == rec.p0_final_score
    assert loaded[0].p1_final_score == rec.p1_final_score
    assert len(loaded[0].decisions) == len(rec.decisions)
