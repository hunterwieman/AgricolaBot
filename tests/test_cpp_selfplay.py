"""Stage 4 gate (CPP_ENGINE_PLAN.md §8): the C++ setup + reveal dealer + the
random self-play trace driver.

The C++ binary plays a full Family game with its OWN RNG and emits an
``agricola-cpp-trace-v1`` JSON envelope. The *trace* (not a NumPy seed) is the
source of truth (§2.1), so the gate asserts:

1. **Setup validity** — every C++ trace's ``initial_state`` is a round-1 WORK
   state Python could also produce (the round-1 WORK GameState is fully
   determined by SP × round-1 card, so there are only a handful of distinct
   dumps across all seeds).
2. **Replay clean + valid record** — each trace replays through the *Python*
   engine via ``replay_trace`` with no drift and yields a terminal
   ``GameRecord``.
3. **Reveals legal** — every ``RevealCard`` in the trace is among the legal
   reveal candidates at its state, and ``round_card_order`` is a valid
   within-stage permutation (each stage's cards appear exactly once, in the
   right stage block).
4. **Dataset invariants** — the produced ``GameRecord`` passes the
   ``validate_dataset`` invariants (chosen_action legal, decider_idx, terminal
   phase, stored-vs-recomputed scores).
5. **SP balance** — over many seeds both starting players occur.
6. **Non-vacuity** — games reach terminal and include harvest + reveals + some
   non-empty pending decisions.

Skips cleanly if the cpp module isn't built (see cpp/README.md).
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from agricola.agents.base import decider_of
from agricola.agents.nn.schema import DATA_VERSION
from agricola.agents.nn.trace_replay import (
    TRACE_SCHEMA,
    action_from_params,
    replay_trace,
)
from agricola.canonical import dumps, from_canonical
from agricola.constants import STAGE_CARDS, Phase, stage_of_round
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup_env

# scripts/ is not a package; load the validator's per-record checker by path.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scripts.nn.validate_dataset import check_record  # noqa: E402

_BUILD_DIR = _ROOT / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp",
    reason="cpp module not built — see cpp/README.md (cmake -S cpp -B cpp/build ...)",
)

_HARVEST_PHASES = {Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cpp_trace(seed: int) -> dict:
    return json.loads(agricola_cpp.random_selfplay_trace(seed))


def _python_initial_dumps(n_seeds: int = 300) -> set[str]:
    """The set of distinct round-1 WORK state dumps Python produces over seeds."""
    return {dumps(setup_env(seed)[0]) for seed in range(n_seeds)}


def _canonicalize_initial(trace: dict) -> str:
    """Re-dump the trace's initial_state through the Python serializer so it is
    comparable to ``dumps(setup_env(seed)[0])`` (the envelope embeds the parsed
    canonical object, not its string form)."""
    return dumps(from_canonical(trace["initial_state"]))


# ---------------------------------------------------------------------------
# 1. Setup validity
# ---------------------------------------------------------------------------

def test_initial_state_is_python_reachable():
    python_initials = _python_initial_dumps(300)
    # The round-1 WORK state is fully determined by SP (2 values) × the round-1
    # card (one of the 4 stage-1 cards) = at most 8 distinct dumps.
    assert len(python_initials) <= 8
    for seed in range(120):
        trace = _cpp_trace(seed)
        assert trace["schema"] == TRACE_SCHEMA
        assert trace["seed"] == seed
        got = _canonicalize_initial(trace)
        assert got in python_initials, (
            f"seed={seed}: C++ initial_state not a Python-reachable round-1 "
            f"WORK state"
        )


def test_sp_balance():
    """Both starting players occur over many seeds (not all one seat)."""
    sps = set()
    for seed in range(60):
        trace = _cpp_trace(seed)
        init = from_canonical(trace["initial_state"])
        sps.add(init.starting_player)
    assert sps == {0, 1}, f"only saw starting_player(s) {sps} over 60 seeds"


# ---------------------------------------------------------------------------
# 2. Replay clean + valid GameRecord + 4. dataset invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(40))
def test_replay_clean_and_record_valid(seed):
    trace = _cpp_trace(seed)
    rec = replay_trace(trace)  # raises on any drift / non-terminal
    assert rec.terminal_state.phase == Phase.BEFORE_SCORING
    assert rec.data_version == DATA_VERSION
    assert len(rec.decisions) > 0

    failures = check_record(rec)
    assert not failures, "validate_dataset invariants failed:\n" + "\n".join(
        str(f) for f in failures
    )


# ---------------------------------------------------------------------------
# 3. Reveals legal + round_card_order is a valid within-stage permutation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_reveals_legal_and_order_valid(seed):
    trace = _cpp_trace(seed)
    state = from_canonical(trace["initial_state"])

    revealed_in_order: list[str] = []
    for i, entry in enumerate(trace["actions"]):
        action = action_from_params(entry["type"], entry["params"])
        if entry["type"] == "RevealCard":
            # decider must be nature (None) at a reveal.
            assert decider_of(state) is None, (
                f"seed={seed} action {i}: RevealCard at non-nature state"
            )
            legal = legal_actions(state)
            assert action in legal, (
                f"seed={seed} action {i}: RevealCard({action.card!r}) not a "
                f"legal candidate at round={state.round_number}"
            )
            revealed_in_order.append(action.card)
        state = step(state, action)

    # The round-1 reveal is consumed inside setup (not in the trace), so the
    # trace's reveals are rounds 2..14. Prepend the round-1 card recovered from
    # the initial state's single revealed stage card to reconstruct the full
    # 14-length order, then verify the within-stage permutation property.
    init = from_canonical(trace["initial_state"])
    revealed_at_start = [
        sid for sid in _stage_card_ids()
        if init.board.action_spaces[_space_idx(sid)].revealed
    ]
    assert len(revealed_at_start) == 1, (
        f"seed={seed}: expected exactly 1 revealed stage card at round-1 WORK, "
        f"got {revealed_at_start}"
    )
    full_order = revealed_at_start + revealed_in_order
    assert len(full_order) == 14, (
        f"seed={seed}: reconstructed order has {len(full_order)} cards"
    )
    _assert_within_stage_permutation(full_order, seed)


def _stage_card_ids() -> list[str]:
    out: list[str] = []
    for stage in sorted(STAGE_CARDS):
        out.extend(STAGE_CARDS[stage])
    return out


def _space_idx(space_id: str) -> int:
    from agricola.constants import SPACE_INDEX
    return SPACE_INDEX[space_id]


def _assert_within_stage_permutation(order: list[str], seed: int):
    """order[i] is round i+1's card. Each stage's cards must appear exactly
    once, contiguously, within that stage's round block."""
    pos = 0
    for stage in sorted(STAGE_CARDS):
        block = order[pos:pos + len(STAGE_CARDS[stage])]
        pos += len(STAGE_CARDS[stage])
        assert sorted(block) == sorted(STAGE_CARDS[stage]), (
            f"seed={seed}: stage {stage} block {block} is not a permutation of "
            f"{STAGE_CARDS[stage]}"
        )
        # Every card in the block belongs to this stage (round -> stage check).
        for round_offset, card in enumerate(block):
            rnd = order.index(card) + 1
            assert stage_of_round(rnd) == stage


# ---------------------------------------------------------------------------
# 6. Non-vacuity
# ---------------------------------------------------------------------------

def test_non_vacuity():
    """Replayed games reach terminal and exercise harvest, reveals, and some
    multi-action pending decisions."""
    saw_harvest = False
    saw_reveal = False
    saw_pending_decision = False

    for seed in range(15):
        trace = _cpp_trace(seed)
        # The game must be long enough to be a real game.
        assert len(trace["actions"]) > 50, f"seed={seed}: suspiciously short game"
        state = from_canonical(trace["initial_state"])
        for entry in trace["actions"]:
            if entry["phase"] in {p.name for p in _HARVEST_PHASES}:
                saw_harvest = True
            if entry["type"] == "RevealCard":
                saw_reveal = True
            # A decision taken while a non-reveal pending frame is on the stack
            # (a genuine mid-turn sub-action choice, not just nature's reveal).
            if state.pending_stack and entry["type"] != "RevealCard":
                saw_pending_decision = True
            action = action_from_params(entry["type"], entry["params"])
            state = step(state, action)
        assert state.phase == Phase.BEFORE_SCORING

    assert saw_harvest, "no harvest phase observed across games"
    assert saw_reveal, "no RevealCard observed across games"
    assert saw_pending_decision, "no mid-turn pending decision observed"
