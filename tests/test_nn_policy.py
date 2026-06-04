"""Tests for the placement-policy slice (POLICY_HEAD.md).

Coverage:
- Extraction: placement-only, single-perspective, target index, the
  mask-contains-target invariant (also exercises wrapper-invariance — records
  are made under unrestricted legality, masks built under restricted).
- By-game split determinism.
- AWR weights: clipped, positive, β reported; val/test stay unweighted.
- Model: shape, masked softmax (illegal→0, sums to 1, no NaN), all-False guard,
  input normalization, persistence round-trip, ENCODING_VERSION rejection.
- `policy_prior`: distribution over exactly the legal placements; NO_PRIOR at
  terminal / sub-action states.
- End-to-end `train_policy` smoke (loss_weight="none") on a tmp run dir.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn

from agricola.actions import PlaceWorker
from agricola.agents.base import RandomAgent, decider_of
from agricola.agents.nn import GameRecord, play_recording_game
from agricola.agents.nn.dataset import NormStats, _seed_split
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION, encode_state
from agricola.agents.nn.model import (
    ConfigurableMLP,
    EncodingVersionMismatch,
    NormalizedValueModel,
)
from agricola.agents.nn.policy import NO_PRIOR, policy_prior
from agricola.agents.nn.policy_dataset import (
    NUM_SPACES,
    PolicyNormStats,
    _decision_rows,
    build_policy_datasets_from_games,
)
from agricola.agents.nn.policy_heads import (
    CHOOSE_SUBACTION_HEAD,
    COMMIT_BUILD_MAJOR_HEAD,
    HEADS,
    PLACEMENT_HEAD,
    STOP_LABEL,
)
from agricola.agents.nn.policy_model import NormalizedPolicyModel
from agricola.agents.nn.policy_training import train_policy
from agricola.constants import SPACE_IDS, SPACE_INDEX, Phase
from agricola.legality import legal_actions
from agricola.setup import setup_env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _record_one_game(seed: int) -> GameRecord:
    initial, env = setup_env(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        dealer=env.resolve,
        game_idx=seed,
        seed=seed,
        p0_config_path="random",
        p1_config_path="random",
        p0_temperature=0.0,
        p1_temperature=0.0,
        legal_actions_fn=legal_actions,
    )


@pytest.fixture(scope="module")
def small_games() -> list[GameRecord]:
    """12 random games — enough for the 80/10/10 seed-hash split to populate
    every bucket, and to contain placement + sub-action + terminal states."""
    return [_record_one_game(seed) for seed in range(12)]


def _tiny_policy_model(head=PLACEMENT_HEAD, seed: int = 0) -> NormalizedPolicyModel:
    torch.manual_seed(seed)
    net = ConfigurableMLP(ENCODED_DIM, [16], head.num_classes, head="linear")
    stats = PolicyNormStats(
        input_mean=np.zeros(ENCODED_DIM, np.float32),
        input_std=np.ones(ENCODED_DIM, np.float32),
        encoding_version=ENCODING_VERSION,
    )
    m = NormalizedPolicyModel(net, stats)
    m.head_name = head.name
    return m


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extraction_placement_only_and_mask_invariant(small_games):
    n_rows = 0
    n_placement_snaps = 0
    for g in small_games:
        n_placement_snaps += sum(
            isinstance(s.chosen_action, PlaceWorker) for s in g.decisions
        )
    for seed, x, target, mask, R, won in _decision_rows(small_games, PLACEMENT_HEAD):
        n_rows += 1
        assert x.shape == (ENCODED_DIM,)
        assert 0 <= target < NUM_SPACES
        assert mask.shape == (NUM_SPACES,)
        assert mask[target], "chosen space must be in its own legal mask"
        assert mask.sum() >= 2, "recorded placement decisions are non-singleton"
        assert won in (1.0, 0.0, -1.0)
    # One row per placement snapshot — nothing else, nothing dropped.
    assert n_rows == n_placement_snaps > 0


def test_extraction_is_single_perspective(small_games):
    # The encoded x must be the DECIDER's perspective, not the opponent's.
    for g in small_games:
        for snap in g.decisions:
            if not isinstance(snap.chosen_action, PlaceWorker):
                continue
            d = snap.decider_idx
            x_decider = encode_state(snap.state, d).astype(np.float32)
            x_other = encode_state(snap.state, 1 - d).astype(np.float32)
            # find the matching extracted row
            rows = [r for r in _decision_rows([g], PLACEMENT_HEAD) if r[2] == SPACE_INDEX[snap.chosen_action.space]]
            assert any(np.array_equal(r[1], x_decider) for r in rows)
            # perspectives differ on a real (asymmetric) state
            assert not np.array_equal(x_decider, x_other)
            return  # one is enough
    pytest.skip("no placement snapshot found")


def test_non_placement_snapshots_skipped():
    # A hand-built record whose only decision is a non-PlaceWorker action
    # contributes zero policy rows.
    from agricola.actions import ChooseSubAction
    initial, env = setup_env(seed=3)
    g = _record_one_game(3)
    fake = GameRecord(
        data_version=g.data_version, game_idx=999, seed=999,
        p0_config_path="x", p1_config_path="x",
        p0_temperature=0.0, p1_temperature=0.0,
        p0_final_score=10, p1_final_score=8, winner=0,
        terminal_state=g.terminal_state,
        decisions=tuple(
            s for s in g.decisions if not isinstance(s.chosen_action, PlaceWorker)
        )[:1],
    )
    if not fake.decisions:
        pytest.skip("no non-placement snapshot available")
    assert list(_decision_rows([fake], PLACEMENT_HEAD)) == []


def test_seed_split_deterministic_and_partitions(small_games):
    # Same seed → same split bucket, always.
    for g in small_games:
        a = _seed_split(g.seed, 0, 0.8, 0.1)
        b = _seed_split(g.seed, 0, 0.8, 0.1)
        assert a == b and a in (0, 1, 2)
    train, val, test, stats, info = build_policy_datasets_from_games(
        small_games, loss_weight="none", verbose=False,
    )
    total = sum(isinstance(s.chosen_action, PlaceWorker)
                for g in small_games for s in g.decisions)
    assert len(train) + len(val) + len(test) == total


# ---------------------------------------------------------------------------
# AWR weights
# ---------------------------------------------------------------------------


def test_awr_weights_clipped_and_unweighted_eval(small_games, tmp_path):
    # Tiny value model as the AWR baseline.
    vnet = ConfigurableMLP(ENCODED_DIM, [8], 1, head="linear")
    vstats = NormStats(np.zeros(ENCODED_DIM, np.float32),
                       np.ones(ENCODED_DIM, np.float32), 14.0, ENCODING_VERSION)
    NormalizedValueModel(vnet, vstats).save(tmp_path / "vmodel")

    train, val, test, stats, info = build_policy_datasets_from_games(
        small_games, loss_weight="awr", value_ckpt=tmp_path / "vmodel",
        awr_clip=6.0, store_dtype="float32", verbose=False,
    )
    w = train._weight.numpy()
    assert (w >= 0).all() and (w <= 6.0 + 1e-6).all()
    assert info["awr_beta"] is not None and info["awr_beta"] > 0
    # val/test are always unweighted.
    assert np.allclose(val._weight.numpy(), 1.0)
    assert np.allclose(test._weight.numpy(), 1.0)


def test_none_weights_are_ones(small_games):
    train, *_ = build_policy_datasets_from_games(
        small_games, loss_weight="none", verbose=False,
    )
    assert np.allclose(train._weight.numpy(), 1.0)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_forward_shape_and_masked_softmax():
    model = _tiny_policy_model()
    x = torch.randn(4, ENCODED_DIM)
    assert model.forward(x).shape == (4, NUM_SPACES)

    mask = torch.zeros(4, NUM_SPACES, dtype=torch.bool)
    mask[:, [0, 2, 5]] = True
    probs = model.policy_probs(x, mask)
    assert probs.shape == (4, NUM_SPACES)
    assert torch.allclose(probs.sum(dim=-1), torch.ones(4), atol=1e-5)
    illegal = ~mask
    assert torch.all(probs[illegal] == 0.0)
    assert not torch.isnan(probs).any()


def test_model_all_false_mask_no_nan():
    model = _tiny_policy_model()
    x = torch.randn(2, ENCODED_DIM)
    mask = torch.zeros(2, NUM_SPACES, dtype=torch.bool)  # pathological all-illegal
    probs = model.policy_probs(x, mask)
    assert not torch.isnan(probs).any()
    assert torch.allclose(probs.sum(dim=-1), torch.ones(2), atol=1e-5)


def test_model_applies_input_normalization():
    captured = {}

    class _Spy(nn.Module):
        def forward(self, x):
            captured["x"] = x.detach().clone()
            return torch.zeros(x.shape[0], NUM_SPACES)

    stats = PolicyNormStats(
        input_mean=np.full(ENCODED_DIM, 3.0, np.float32),
        input_std=np.full(ENCODED_DIM, 2.0, np.float32),
        encoding_version=ENCODING_VERSION,
    )
    model = NormalizedPolicyModel(_Spy(), stats)
    x = torch.full((1, ENCODED_DIM), 3.0)  # == input_mean → net sees zeros
    model.forward(x)
    assert torch.allclose(captured["x"], torch.zeros(1, ENCODED_DIM), atol=1e-6)


def test_model_save_load_roundtrip(tmp_path):
    model = _tiny_policy_model(seed=1)
    x = torch.randn(3, ENCODED_DIM)
    mask = torch.ones(3, NUM_SPACES, dtype=torch.bool)
    before = model.predict_logits(x, mask)
    model.save(tmp_path / "pol", extras={"note": "test"})
    loaded = NormalizedPolicyModel.load(tmp_path / "pol")
    after = loaded.predict_logits(x, mask)
    assert torch.allclose(before, after, atol=1e-6)
    meta = json.loads((tmp_path / "pol.meta.json").read_text())
    assert meta["model_kind"] == "policy"
    assert meta["extras"]["note"] == "test"


def test_model_encoding_version_mismatch(tmp_path):
    model = _tiny_policy_model()
    model.save(tmp_path / "pol")
    meta_path = tmp_path / "pol.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["encoding_version"] = ENCODING_VERSION + 99
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(EncodingVersionMismatch):
        NormalizedPolicyModel.load(tmp_path / "pol")


def test_construct_with_stale_stats_raises():
    net = ConfigurableMLP(ENCODED_DIM, [8], NUM_SPACES, head="linear")
    stale = PolicyNormStats(
        input_mean=np.zeros(ENCODED_DIM, np.float32),
        input_std=np.ones(ENCODED_DIM, np.float32),
        encoding_version=ENCODING_VERSION + 99,
    )
    with pytest.raises(EncodingVersionMismatch):
        NormalizedPolicyModel(net, stale)


# ---------------------------------------------------------------------------
# policy_prior
# ---------------------------------------------------------------------------


def test_policy_prior_distribution_over_legal_placements():
    model = _tiny_policy_model()
    state, _ = setup_env(seed=7)  # round-1 WORK → empty stack → placement
    prior = policy_prior(state, model)
    assert prior is not NO_PRIOR
    assert len(prior) >= 2
    assert all(isinstance(a, PlaceWorker) for a in prior)
    assert abs(sum(prior.values()) - 1.0) < 1e-5
    # keys are exactly the legal placements
    from tests.test_utils import filter_implemented
    from agricola.agents.restricted import restricted_legal_actions
    legal = {a for a in filter_implemented(restricted_legal_actions(state))
             if isinstance(a, PlaceWorker)}
    assert set(prior) == legal


def test_policy_prior_no_prior_on_terminal_and_subaction(small_games):
    model = _tiny_policy_model()
    # Terminal state.
    assert policy_prior(small_games[0].terminal_state, model) is NO_PRIOR
    # A sub-action (non-empty pending stack) snapshot.
    found = False
    for g in small_games:
        for snap in g.decisions:
            if snap.state.pending_stack:
                assert policy_prior(snap.state, model) is NO_PRIOR
                found = True
                break
        if found:
            break
    assert found, "expected at least one sub-action (pending-stack) snapshot"


# ---------------------------------------------------------------------------
# End-to-end training smoke
# ---------------------------------------------------------------------------


def test_train_policy_smoke(small_games, tmp_path):
    # Write the fixture games to a tmp run dir (build reads pickles, not metadata).
    run_dir = tmp_path / "run"
    (run_dir / "games").mkdir(parents=True)
    with (run_dir / "games" / "worker_00.pkl").open("wb") as f:
        pickle.dump(small_games, f)

    out_dir = tmp_path / "out"
    log, best = train_policy(
        run_dir, out_dir, loss_weight="none", hidden_dims=[16, 16],
        max_epochs=3, early_stop_patience=99, batch_size=64, verbose=False,
    )
    assert len(log) == 3
    for name in ("config.json", "policy_norm_stats.json", "train_log.jsonl",
                 "best.pt", "best.meta.json", "test_metrics.json"):
        assert (out_dir / name).exists(), name
    # Best checkpoint loads and runs.
    model = NormalizedPolicyModel.load(best)
    x = torch.randn(2, ENCODED_DIM)
    mask = torch.ones(2, NUM_SPACES, dtype=torch.bool)
    assert model.policy_probs(x, mask).shape == (2, NUM_SPACES)
    # Log entries carry the policy metrics.
    e = log[0]
    for k in ("train_ce", "val_ce", "val_top1", "val_top3"):
        assert k in e
    tm = json.loads((out_dir / "test_metrics.json").read_text())
    assert "test" in tm and "top1" in tm["test"]


# ---------------------------------------------------------------------------
# ChooseSubAction head (the second decision-type head)
# ---------------------------------------------------------------------------


def test_choose_subaction_target_mapping_and_alias():
    from agricola.actions import ChooseSubAction, Stop
    h = CHOOSE_SUBACTION_HEAD
    assert h.num_classes == 8
    assert h.target_index(Stop()) == h.vocab.index(STOP_LABEL)
    # build_stable alias merges into build_stables
    bs = h.vocab.index("build_stables")
    assert h.target_index(ChooseSubAction(name="build_stable")) == bs
    assert h.target_index(ChooseSubAction(name="build_stables")) == bs
    assert h.target_index(ChooseSubAction(name="plow")) == h.vocab.index("plow")
    # actions this head doesn't own
    assert h.target_index(PlaceWorker(space="forest")) is None


def test_choose_subaction_extraction(small_games):
    """Parent-pending decisions extract with width-8 masks; mask contains the
    chosen class. Random games hit side_job / grain_utilization, so > 0."""
    rows = list(_decision_rows(small_games, CHOOSE_SUBACTION_HEAD))
    assert len(rows) > 0
    for seed, x, target, mask, R, won in rows:
        assert x.shape == (ENCODED_DIM,)
        assert mask.shape == (CHOOSE_SUBACTION_HEAD.num_classes,)
        assert 0 <= target < CHOOSE_SUBACTION_HEAD.num_classes
        assert mask[target]


def test_choose_subaction_owns_disjoint_from_placement(small_games):
    # No snapshot is owned by both heads (typed decision points).
    for g in small_games:
        for snap in g.decisions:
            s = snap.state
            assert not (PLACEMENT_HEAD.owns(s) and CHOOSE_SUBACTION_HEAD.owns(s))


def test_policy_prior_choose_subaction(small_games):
    model = _tiny_policy_model(CHOOSE_SUBACTION_HEAD)
    found = False
    for g in small_games:
        for snap in g.decisions:
            if CHOOSE_SUBACTION_HEAD.owns(snap.state):
                prior = policy_prior(snap.state, model)  # head auto-from model
                assert prior is not NO_PRIOR
                assert abs(sum(prior.values()) - 1.0) < 1e-5
                found = True
                break
        if found:
            break
    assert found, "expected a parent-pending decision in the fixture games"


# ---------------------------------------------------------------------------
# CommitBuildMajor head (the third decision-type head)
# ---------------------------------------------------------------------------


def test_commit_build_major_vocab_and_target():
    from agricola.actions import CommitBuildMajor
    h = COMMIT_BUILD_MAJOR_HEAD
    assert h.num_classes == 14  # 8 non-hearth majors + 2 hearths × 3 variants
    assert h.target_index(CommitBuildMajor(major_idx=5, return_fireplace_idx=None)) == h.vocab.index("m5")
    assert h.target_index(CommitBuildMajor(major_idx=2, return_fireplace_idx=None)) == h.vocab.index("m2")
    assert h.target_index(CommitBuildMajor(major_idx=2, return_fireplace_idx=0)) == h.vocab.index("m2_rf0")
    assert h.target_index(CommitBuildMajor(major_idx=3, return_fireplace_idx=1)) == h.vocab.index("m3_rf1")
    assert h.target_index(PlaceWorker(space="forest")) is None


def test_commit_build_major_extraction_invariants(small_games):
    # Random games may or may not contain major-buy decisions; any that exist
    # must satisfy the head's invariants (width-14 mask containing the target).
    for seed, x, target, mask, R, won in _decision_rows(small_games, COMMIT_BUILD_MAJOR_HEAD):
        assert mask.shape == (COMMIT_BUILD_MAJOR_HEAD.num_classes,)
        assert 0 <= target < COMMIT_BUILD_MAJOR_HEAD.num_classes
        assert mask[target]


def test_all_heads_ownership_disjoint(small_games):
    # The three registered heads own disjoint decision points (typed by the
    # pending-stack top) — no snapshot is claimed by more than one.
    heads = list(HEADS.values())
    for g in small_games:
        for snap in g.decisions:
            owners = [h.name for h in heads if h.owns(snap.state)]
            assert len(owners) <= 1, (owners, snap.state.phase)
