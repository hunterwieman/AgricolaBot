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
- End-to-end `train_policy` smoke (loss_weight="unweighted") on a tmp run dir.
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
from agricola.agents.nn.policy import (
    NO_PRIOR,
    make_policy_fn,
    pointer_prior,
    policy_prior,
)
from agricola.agents.nn.policy_pointer_dataset import PointerNormStats
from agricola.agents.nn.policy_pointer_model import NormalizedPointerModel
from agricola.agents.nn.policy_dataset import (
    NUM_SPACES,
    PolicyNormStats,
    _decision_rows,
    _pi_vector,
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
    for seed, x, target, mask, R, won, pi in _decision_rows(small_games, PLACEMENT_HEAD):
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


# ---------------------------------------------------------------------------
# Soft-π targets (cross-entropy against the MCTS visit distribution)
# ---------------------------------------------------------------------------


def test_pi_vector_soft_normalizes_and_guards():
    # Soft target = normalized visit counts over the head's legal classes.
    from agricola.agents.nn.schema import DecisionSnapshot
    state, _ = setup_env(seed=7)
    placements = [a for a in legal_actions(state) if isinstance(a, PlaceWorker)]
    a0, a1 = placements[0], placements[1]
    i0, i1 = PLACEMENT_HEAD.target_index(a0), PLACEMENT_HEAD.target_index(a1)
    mask = PLACEMENT_HEAD.legal_mask(state, legal_actions)
    snap = DecisionSnapshot(state=state, chosen_action=a1, decider_idx=decider_of(state),
                            visit_distribution={a0: 30, a1: 10}, root_value=0.0)
    pi = _pi_vector(PLACEMENT_HEAD, snap, i1, mask, soft_targets=True)
    assert abs(pi[i0] - 0.75) < 1e-6 and abs(pi[i1] - 0.25) < 1e-6
    assert abs(float(pi.sum()) - 1.0) < 1e-6
    # soft_targets=False → one-hot on the played class even with a visit dist.
    hard = _pi_vector(PLACEMENT_HEAD, snap, i1, mask, soft_targets=False)
    assert hard[i1] == 1.0 and float(hard.sum()) == 1.0
    # No visit dist (legacy data) → one-hot fallback.
    snap_legacy = DecisionSnapshot(state=state, chosen_action=a1,
                                   decider_idx=decider_of(state))
    legacy = _pi_vector(PLACEMENT_HEAD, snap_legacy, i1, mask, soft_targets=True)
    assert legacy[i1] == 1.0
    # Mass on a class illegal under the training mask → loud failure (the
    # masked-softmax CE would otherwise NaN). Simulates a legality mismatch.
    bad_mask = mask.copy()
    bad_mask[i0] = False
    with pytest.raises(ValueError, match="illegal under the training legality"):
        _pi_vector(PLACEMENT_HEAD, snap, i1, bad_mask, soft_targets=True)


def test_pi_vector_build_stop_collapses_visit_counts():
    # build_stop is 2-way (__build__ / __stop__); every CommitBuildRoom cell
    # collapses into __build__, so soft-π sums their visits.
    from agricola.actions import CommitBuildRoom, Stop
    from agricola.agents.nn.policy_heads import BUILD_STOP_HEAD
    from agricola.agents.nn.schema import DecisionSnapshot
    state, _ = setup_env(seed=0)
    bi = BUILD_STOP_HEAD.target_index(CommitBuildRoom(row=0, col=0))
    si = BUILD_STOP_HEAD.target_index(Stop())
    vd = {CommitBuildRoom(row=0, col=0): 5,
          CommitBuildRoom(row=0, col=1): 15,
          Stop(): 20}
    snap = DecisionSnapshot(state=state, chosen_action=Stop(), decider_idx=0,
                            visit_distribution=vd, root_value=0.0)
    pi = _pi_vector(BUILD_STOP_HEAD, snap, si, np.array([True, True]),
                    soft_targets=True)
    assert abs(pi[bi] - 0.5) < 1e-6      # (5+15)/40 collapsed into __build__
    assert abs(pi[si] - 0.5) < 1e-6      # 20/40


def test_soft_pi_train_epoch_runs_on_nononehot_targets():
    # End-to-end: a dataset carrying genuine (non-one-hot) π trains a finite CE.
    from torch.utils.data import DataLoader

    from agricola.agents.nn.policy_training import train_one_epoch_policy
    from agricola.agents.nn.schema import DecisionSnapshot
    state, _ = setup_env(seed=7)
    placements = [a for a in legal_actions(state) if isinstance(a, PlaceWorker)]
    a0, a1 = placements[0], placements[1]
    g = _record_one_game(7)               # for a real terminal_state
    snap = DecisionSnapshot(state=state, chosen_action=a0, decider_idx=decider_of(state),
                            visit_distribution={a0: 30, a1: 10}, root_value=0.0)
    recs = [
        GameRecord(data_version=g.data_version, game_idx=s, seed=s,
                   p0_config_path="x", p1_config_path="x",
                   p0_temperature=0.0, p1_temperature=0.0,
                   p0_final_score=20, p1_final_score=18, winner=0,
                   terminal_state=g.terminal_state, decisions=(snap, snap))
        for s in range(8)                 # varied seeds → populated split buckets
    ]
    train, *_ = build_policy_datasets_from_games(
        recs, loss_weight="unweighted", legal_actions_fn=legal_actions,
        store_dtype="float32", verbose=False)
    # The stored target really is the soft distribution, not a one-hot.
    assert train._pi.max(dim=1).values.max().item() < 0.99
    model = _tiny_policy_model(PLACEMENT_HEAD)
    opt = torch.optim.SGD(model.parameters(), lr=0.01)
    loader = DataLoader(train, batch_size=4)
    ce = train_one_epoch_policy(model, loader, opt, torch.device("cpu"))
    assert np.isfinite(ce) and ce > 0


def test_seed_split_deterministic_and_partitions(small_games):
    # Same seed → same split bucket, always.
    for g in small_games:
        a = _seed_split(g.seed, 0, 0.8, 0.1)
        b = _seed_split(g.seed, 0, 0.8, 0.1)
        assert a == b and a in (0, 1, 2)
    train, val, test, stats, info = build_policy_datasets_from_games(
        small_games, loss_weight="unweighted", verbose=False,
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


def test_awr_rejects_non_margin_value_ckpt(small_games, tmp_path):
    # A non-margin value baseline (here a tanh/outcome head) must be rejected:
    # predict_margin is bounded there, so AWR's advantage A = R - V would mix
    # units (R is the score margin in points) and silently degenerate.
    vnet = ConfigurableMLP(ENCODED_DIM, [8], 1, head="tanh")
    vstats = NormStats(np.zeros(ENCODED_DIM, np.float32),
                       np.ones(ENCODED_DIM, np.float32), 1.0, ENCODING_VERSION)
    NormalizedValueModel(vnet, vstats).save(tmp_path / "vmodel_outcome")

    with pytest.raises(ValueError, match="margin-mode"):
        build_policy_datasets_from_games(
            small_games, loss_weight="awr", value_ckpt=tmp_path / "vmodel_outcome",
            awr_clip=6.0, store_dtype="float32", verbose=False,
        )


def test_unweighted_weights_are_ones(small_games):
    train, *_ = build_policy_datasets_from_games(
        small_games, loss_weight="unweighted", verbose=False,
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
        run_dir, out_dir, loss_weight="unweighted", hidden_dims=[16, 16],
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
    for seed, x, target, mask, R, won, pi in rows:
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
    from agricola.cost import ReturnImprovement
    from agricola.resources import Resources
    h = COMMIT_BUILD_MAJOR_HEAD
    assert h.num_classes == 14  # 8 non-hearth majors + 2 hearths × 3 variants
    # The label is derived from the wide commit's `payment`: a Resources payment is the
    # standard "m{idx}" class; a ReturnImprovement(fp) is the "m{idx}_rf{fp}" class.
    std = Resources(clay=4)
    assert h.target_index(CommitBuildMajor(major_idx=5, payment=std)) == h.vocab.index("m5")
    assert h.target_index(CommitBuildMajor(major_idx=2, payment=std)) == h.vocab.index("m2")
    assert h.target_index(CommitBuildMajor(
        major_idx=2, payment=ReturnImprovement(0))) == h.vocab.index("m2_rf0")
    assert h.target_index(CommitBuildMajor(
        major_idx=3, payment=ReturnImprovement(1))) == h.vocab.index("m3_rf1")
    assert h.target_index(PlaceWorker(space="forest")) is None


def test_commit_build_major_extraction_invariants(small_games):
    # Random games may or may not contain major-buy decisions; any that exist
    # must satisfy the head's invariants (width-14 mask containing the target).
    for seed, x, target, mask, R, won, pi in _decision_rows(small_games, COMMIT_BUILD_MAJOR_HEAD):
        assert mask.shape == (COMMIT_BUILD_MAJOR_HEAD.num_classes,)
        assert 0 <= target < COMMIT_BUILD_MAJOR_HEAD.num_classes
        assert mask[target]


def test_all_heads_ownership_disjoint(small_games):
    # The registered heads own disjoint decision points (typed by the
    # pending-stack top) — no snapshot is claimed by more than one.
    heads = list(HEADS.values())
    for g in small_games:
        for snap in g.decisions:
            owners = [h.name for h in heads if h.owns(snap.state)]
            assert len(owners) <= 1, (owners, snap.state.phase)


# ---------------------------------------------------------------------------
# CommitSow + CommitBake fixed heads
# ---------------------------------------------------------------------------


def test_commit_sow_head_vocab_and_target():
    from agricola.actions import CommitSow
    from agricola.agents.nn.policy_heads import COMMIT_SOW_HEAD as H
    assert H.num_classes == 104                       # Σ_{s=1}^{13}(s+1)
    assert H.target_index(CommitSow(grain=1, veg=0)) == H.vocab.index("g1v0")
    assert H.target_index(CommitSow(grain=2, veg=1)) == H.vocab.index("g2v1")
    assert H.target_index(CommitSow(grain=0, veg=0)) is None    # sum 0 excluded
    assert H.target_index(CommitSow(grain=10, veg=4)) is None   # sum 14 > 13
    assert H.target_index(PlaceWorker(space="forest")) is None


def test_commit_bake_head_vocab_and_target():
    from agricola.actions import CommitBake
    from agricola.agents.nn.policy_heads import COMMIT_BAKE_HEAD as H
    assert H.num_classes == 6
    assert H.target_index(CommitBake(grain=1)) == H.vocab.index("n1")
    assert H.target_index(CommitBake(grain=6)) == H.vocab.index("n6")
    assert H.target_index(CommitBake(grain=7)) is None          # > max 6
    assert H.target_index(PlaceWorker(space="forest")) is None


def test_commit_sow_bake_owns_and_legal_mask():
    from agricola.actions import CommitSow
    from agricola.agents.nn.policy_heads import COMMIT_BAKE_HEAD, COMMIT_SOW_HEAD
    from agricola.legality import legal_actions as full
    from agricola.pending import PendingBakeBread, PendingSow
    from tests.factories import (
        with_current_player, with_fields, with_pending_stack, with_resources,
    )

    # PendingSow with grain+veg in supply and empty fields → a real sow choice.
    s = setup_env(seed=0)[0]
    s = with_current_player(s, 0)
    s = with_resources(s, 0, grain=2, veg=1)
    s = with_fields(s, 0, [(0, 1), (0, 2), (0, 3)])   # empty plowed fields to sow on
    s = with_pending_stack(s, [PendingSow(player_idx=0, initiated_by_id="space:cultivation")])
    assert COMMIT_SOW_HEAD.owns(s)
    assert not COMMIT_BAKE_HEAD.owns(s)
    mask = COMMIT_SOW_HEAD.legal_mask(s)
    legal_sow = [a for a in full(s) if isinstance(a, CommitSow)]
    if legal_sow:                                      # mask marks exactly the legal in-vocab sows
        assert mask.sum() == len({(a.grain, a.veg) for a in legal_sow})

    # PendingBakeBread is owned by the bake head, not the sow head.
    s2 = with_pending_stack(setup_env(seed=0)[0],
                            [PendingBakeBread(player_idx=0, initiated_by_id="space:grain_utilization")])
    assert COMMIT_BAKE_HEAD.owns(s2)
    assert not COMMIT_SOW_HEAD.owns(s2)


def test_commit_sow_bake_extraction_invariants(small_games):
    # Random games may or may not contain sow/bake decisions; any that exist
    # satisfy the head invariants (target in its own legal mask).
    from agricola.agents.nn.policy_heads import COMMIT_BAKE_HEAD, COMMIT_SOW_HEAD
    from agricola.agents.nn.policy_dataset import _decision_rows
    for head in (COMMIT_SOW_HEAD, COMMIT_BAKE_HEAD):
        for seed, x, target, mask, R, won, pi in _decision_rows(small_games, head):
            assert mask.shape == (head.num_classes,)
            assert 0 <= target < head.num_classes
            assert mask[target]


# ---------------------------------------------------------------------------
# Fencing head — 109 RESTRICTED shapes + Stop (110), full legality
# ---------------------------------------------------------------------------


def test_fencing_head_vocab_and_target():
    from agricola.actions import CommitBuildPasture, Stop
    from agricola.agents.nn.policy_heads import (
        FENCING_HEAD as H, STOP_LABEL, _FENCE_SHAPES,
    )
    assert H.num_classes == 110                        # 109 shapes + Stop
    assert len(_FENCE_SHAPES) == 109
    assert H.target_index(CommitBuildPasture(cells=_FENCE_SHAPES[0])) == H.vocab.index("p0")
    assert H.target_index(Stop()) == H.vocab.index(STOP_LABEL)
    # a cell-set not in the RESTRICTED universe → not a class
    assert H.target_index(CommitBuildPasture(cells=frozenset({(0, 0), (2, 4)}))) is None
    assert H.target_index(PlaceWorker(space="forest")) is None


def test_fencing_head_owns_and_full_legality_mask():
    from agricola.actions import CommitBuildPasture
    from agricola.agents.nn.policy_heads import FENCING_HEAD as H
    from agricola.agents.restricted import restricted_legal_actions
    from agricola.legality import legal_actions as full
    from agricola.pending import PendingBuildFences
    from tests.factories import with_current_player, with_pending_stack, with_resources
    s = setup_env(seed=0)[0]
    s = with_current_player(s, 0)
    s = with_resources(s, 0, wood=10)
    s = with_pending_stack(s, [PendingBuildFences(
        player_idx=0, initiated_by_id="space:fencing",
        pastures_built=0, fences_built=0, subdivision_started=False)])
    assert H.owns(s)
    # full-legality mask = every farm-legal RESTRICTED shape (all in vocab → no drift)
    legal_shapes = {a.cells for a in full(s) if isinstance(a, CommitBuildPasture)}
    assert all(c in {fs for fs in _fence_shapes()} for c in legal_shapes)
    mask_full = H.legal_mask(s, full)
    assert mask_full.sum() == len(legal_shapes) >= 2
    # full legality considers at least as many shapes as the restricted wrapper
    assert mask_full.sum() >= H.legal_mask(s, restricted_legal_actions).sum()


def _fence_shapes():
    from agricola.agents.nn.policy_heads import _FENCE_SHAPES
    return _FENCE_SHAPES


# ---------------------------------------------------------------------------
# build_stop head — learned P(stop) at multi-shot Build Rooms / Build Stables
# ---------------------------------------------------------------------------


def _build_stop_state(num_built=1):
    from agricola.pending import PendingBuildStables
    from agricola.resources import Resources
    from tests.factories import with_current_player, with_pending_stack, with_resources
    s = setup_env(seed=0)[0]
    s = with_current_player(s, 0)
    s = with_resources(s, 0, wood=10)
    return with_pending_stack(s, [PendingBuildStables(
        player_idx=0, initiated_by_id="farm_expansion",
        cost=Resources(wood=2), max_builds=None, num_built=num_built)])


def test_build_stop_head_vocab_target_owns():
    from agricola.actions import CommitBuildRoom, CommitBuildStable, Stop
    from agricola.agents.nn.policy_heads import BUILD_LABEL, BUILD_STOP_HEAD as H, STOP_LABEL
    assert H.num_classes == 2
    assert H.target_index(Stop()) == H.vocab.index(STOP_LABEL)
    assert H.target_index(CommitBuildStable(row=0, col=4)) == H.vocab.index(BUILD_LABEL)
    assert H.target_index(CommitBuildRoom(row=0, col=0)) == H.vocab.index(BUILD_LABEL)
    assert H.target_index(PlaceWorker(space="forest")) is None
    assert H.owns(_build_stop_state(num_built=1))        # Stop legal ⟺ num_built≥1
    assert not H.owns(_build_stop_state(num_built=0))     # first build: no Stop


def test_make_policy_fn_build_stop_split():
    # With a build_stop model: {one cell-priority build cell: P(build), <stop>: P(stop)}.
    # Post the build-host refactor the before-phase "stop" action is Proceed (relabeled
    # to Stop for the head), so accept either.
    from agricola.actions import CommitBuildStable, Proceed, Stop
    from agricola.agents.nn.policy_heads import BUILD_STOP_HEAD
    s = _build_stop_state(num_built=1)
    pri = make_policy_fn([_tiny_policy_model(BUILD_STOP_HEAD)])(s, _full_legal(s))
    builds = [a for a in pri if isinstance(a, CommitBuildStable)]
    stops = [a for a in pri if isinstance(a, (Stop, Proceed))]
    assert len(builds) == 1 and len(stops) == 1           # cell-priority collapses build
    assert abs(sum(pri.values()) - 1.0) < 1e-5


def test_make_policy_fn_build_stop_absent_falls_back_to_uniform():
    # No build_stop model → the crude cell-priority fallback (<stop> + one cell, 50/50).
    from agricola.actions import CommitBuildStable, Proceed, Stop
    s = _build_stop_state(num_built=1)
    pri = make_policy_fn([])(s, _full_legal(s))
    assert any(isinstance(a, (Stop, Proceed)) for a in pri)
    assert any(isinstance(a, CommitBuildStable) for a in pri)
    vals = list(pri.values())
    assert all(abs(v - vals[0]) < 1e-9 for v in vals)     # uniform fallback


def test_build_stop_extraction_invariants(small_games):
    from agricola.agents.nn.policy_dataset import _decision_rows
    from agricola.agents.nn.policy_heads import BUILD_STOP_HEAD
    for seed, x, target, mask, R, won, pi in _decision_rows(small_games, BUILD_STOP_HEAD):
        assert mask.shape == (2,)
        assert 0 <= target < 2
        assert mask[target]


# ---------------------------------------------------------------------------
# make_policy_fn — the multi-head combiner PUCT consumes
#
# Design (POLICY_HEAD.md): the policy works over the FULL legal set. Per decision
# type — a learned head → its distribution over full legal; a cell commit
# (plow / build-stable / build-room) → uniform over the cell-priority-filtered set
# ONLY (no room cap); anything else → uniform over full legal.
# ---------------------------------------------------------------------------


def _full_legal(state):
    from agricola.legality import legal_actions as full
    from tests.test_utils import filter_implemented
    return filter_implemented(full(state))


def _plow_state():
    """A PendingPlow decision with several legal plow cells (player 0)."""
    from agricola.pending import PendingPlow
    from tests.factories import with_current_player, with_pending_stack
    state, _ = setup_env(seed=0)
    state = with_current_player(state, 0)
    return with_pending_stack(state, [
        PendingPlow(player_idx=0, initiated_by_id="space:farmland"),
    ])


def _room_cap_build_rooms_state():
    """A PendingBuildRooms decision while already at MAX_TOTAL_ROOMS — the case
    where `restricted_legal_actions` drops every CommitBuildRoom (room cap)."""
    from agricola.agents.restricted import MAX_TOTAL_ROOMS, ROOM_PRIORITY
    from agricola.constants import CellType
    from agricola.pending import PendingBuildRooms
    from agricola.resources import Resources
    from agricola.state import Cell
    from tests.factories import (
        with_current_player, with_grid, with_pending_stack, with_resources,
    )
    state, _ = setup_env(seed=0)
    state = with_current_player(state, 0)
    extra = list(ROOM_PRIORITY)[: MAX_TOTAL_ROOMS - 2]
    state = with_grid(state, 0, {c: Cell(cell_type=CellType.ROOM) for c in extra})
    state = with_resources(state, 0, wood=10, reed=4, clay=10, stone=10)
    return with_pending_stack(state, [
        PendingBuildRooms(
            player_idx=0, initiated_by_id="farm_expansion",
            max_builds=None, num_built=1,
        ),
    ])


def test_make_policy_fn_placement_head_over_full_legal():
    # The placement head distributes over the FULL legal placement set (placement
    # is wrapper-invariant, so "full" and "restricted" coincide here anyway).
    model = _tiny_policy_model(PLACEMENT_HEAD)
    pf = make_policy_fn([model])
    state, _ = setup_env(seed=7)
    pri = pf(state, _full_legal(state))
    legal_pw = {a for a in _full_legal(state) if isinstance(a, PlaceWorker)}
    assert set(pri) == legal_pw
    assert abs(sum(pri.values()) - 1.0) < 1e-5


def test_make_policy_fn_cell_commit_uniform_over_cell_priority():
    # CommitPlow has no encoder signal → uniform over the cell-priority-filtered
    # set: the many legal plow cells collapse to the one priority cell.
    from agricola.actions import CommitPlow
    from agricola.agents.restricted import PLOW_PRIORITY, _filter_cell_priority
    state = _plow_state()
    legal = _full_legal(state)
    pri = make_policy_fn([])(state, legal)
    assert set(pri) == set(_filter_cell_priority(list(legal), PLOW_PRIORITY, CommitPlow))
    assert sum(isinstance(a, CommitPlow) for a in legal) >= 2  # prune had something to do
    plow_keys = [a for a in pri if isinstance(a, CommitPlow)]
    assert len(plow_keys) == 1
    assert (plow_keys[0].row, plow_keys[0].col) == PLOW_PRIORITY[0]
    vals = list(pri.values())
    assert all(abs(v - vals[0]) < 1e-12 for v in vals)
    assert abs(sum(vals) - 1.0) < 1e-5


def test_make_policy_fn_cell_commit_does_not_apply_room_cap():
    # The cell path applies ONLY cell-priority, NOT the room cap: at MAX rooms,
    # restricted_legal_actions drops every CommitBuildRoom, but the policy keeps one.
    from agricola.actions import CommitBuildRoom
    from agricola.agents.restricted import restricted_legal_actions
    state = _room_cap_build_rooms_state()
    restricted_rooms = [a for a in restricted_legal_actions(state)
                        if isinstance(a, CommitBuildRoom)]
    assert restricted_rooms == []                       # cap drops them
    pri = make_policy_fn([])(state, _full_legal(state))
    room_keys = [a for a in pri if isinstance(a, CommitBuildRoom)]
    assert len(room_keys) >= 1                           # ... but the policy keeps one


def test_make_policy_fn_unhandled_decision_uniform_over_full_legal(small_games):
    # A pending decision with no head and not a cell commit → uniform over the
    # FULL legal set (no narrowing at all).
    from agricola.agents.nn.policy import _CELL_PRIORITY_SPECS
    pf = make_policy_fn([])
    for g in small_games:
        for snap in g.decisions:
            s = snap.state
            if not s.pending_stack:
                continue
            if type(s.pending_stack[-1]) in _CELL_PRIORITY_SPECS:
                continue  # cell commits covered above
            legal = _full_legal(s)
            pri = pf(s, legal)
            assert set(pri) == set(legal)
            vals = list(pri.values())
            assert all(abs(v - vals[0]) < 1e-12 for v in vals)
            assert abs(sum(vals) - 1.0) < 1e-5
            return
    pytest.skip("no non-cell pending snapshot in fixture games")


def test_make_policy_fn_dispatches_across_decision_types(small_games):
    # Placement + choose_subaction heads loaded: the combiner routes by stack top.
    pm = _tiny_policy_model(PLACEMENT_HEAD, seed=1)
    cm = _tiny_policy_model(CHOOSE_SUBACTION_HEAD, seed=2)
    pf = make_policy_fn([pm, cm])

    s0, _ = setup_env(seed=7)
    pri0 = pf(s0, _full_legal(s0))
    assert pri0 and all(isinstance(a, PlaceWorker) for a in pri0)
    assert abs(sum(pri0.values()) - 1.0) < 1e-5

    for g in small_games:
        for snap in g.decisions:
            if CHOOSE_SUBACTION_HEAD.owns(snap.state):
                s = snap.state
                pri = pf(s, _full_legal(s))
                assert pri and all(not isinstance(a, PlaceWorker) for a in pri)
                assert abs(sum(pri.values()) - 1.0) < 1e-5
                return
    pytest.skip("no choose_subaction snapshot in fixture games")


def test_make_policy_fn_falls_back_to_full_legal_when_head_absent(small_games):
    # Only the placement head is loaded; at a choose_subaction state (no head, not
    # a cell commit) the combiner gives uniform over the FULL legal set — no
    # restriction (e.g. build_rooms is not dropped).
    pf = make_policy_fn([_tiny_policy_model(PLACEMENT_HEAD)])
    for g in small_games:
        for snap in g.decisions:
            if CHOOSE_SUBACTION_HEAD.owns(snap.state):
                s = snap.state
                legal = _full_legal(s)
                pri = pf(s, legal)
                assert set(pri) == set(legal)
                vals = list(pri.values())
                assert all(abs(v - vals[0]) < 1e-12 for v in vals)
                assert abs(sum(vals) - 1.0) < 1e-5
                return
    pytest.skip("no choose_subaction snapshot in fixture games")


def test_make_policy_fn_rejects_unlabelled_model():
    net = ConfigurableMLP(ENCODED_DIM, [8], PLACEMENT_HEAD.num_classes, head="linear")
    stats = PolicyNormStats(
        input_mean=np.zeros(ENCODED_DIM, np.float32),
        input_std=np.ones(ENCODED_DIM, np.float32),
        encoding_version=ENCODING_VERSION,
    )
    unlabelled = NormalizedPolicyModel(net, stats)  # no head_name set
    with pytest.raises(ValueError):
        make_policy_fn([unlabelled])


# ---------------------------------------------------------------------------
# Pointer head — animal_frontier (CommitBreed + CommitAccommodate)
#
# Score-the-legal-set head over a variable-cardinality Pareto frontier. The
# candidate set + order must match the engine's enumerator (so chosen ∈ legal),
# and each candidate's features are (sheep_kept, boar_kept, cattle_kept,
# food_gained) — kept counts = raw commit fields, food from the frontier helper.
# ---------------------------------------------------------------------------


def _set_pasture_1x1(state, player_idx, row=0, col=0):
    """Add a 1x1 fenced pasture at (row, col). Mirrors test_harvest_breed."""
    import dataclasses
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard
    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    fy = Farmyard(grid=p.farmyard.grid, horizontal_fences=new_h,
                  vertical_fences=new_v,
                  pastures=compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v))
    players = list(state.players)
    players[player_idx] = dataclasses.replace(p, farmyard=fy)
    return dataclasses.replace(state, players=tuple(players))


def _breed_state_two_types():
    """HARVEST_BREED, P0 on top: 2 sheep + 2 boar + Fireplace + two 1x1 pastures
    → a 2-point breeding frontier {(3,2,0), (2,3,0)} (only one newborn fits the
    house-pet slot)."""
    import dataclasses
    from agricola.constants import Phase
    from agricola.engine import _initiate_harvest_breed
    from agricola.setup import setup
    from tests.factories import with_animals, with_majors, with_phase
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace
    state = with_animals(state, 0, sheep=2, boar=2)
    state = _set_pasture_1x1(state, 0, 0, 0)
    state = _set_pasture_1x1(state, 0, 0, 2)
    state = with_phase(state, Phase.HARVEST_BREED)
    return _initiate_harvest_breed(state)


def _sheep_market_state():
    """PendingSheepMarket(gained=4), P0 has 2 boar + Fireplace + one 1x1 pasture
    → a multi-point accommodate frontier with non-zero food (excess → cooked)."""
    from agricola.pending import PendingSheepMarket
    from agricola.setup import setup
    from tests.factories import with_animals, with_current_player, with_majors, with_pending_stack
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace → cooking rates > 0
    state = with_animals(state, 0, boar=2)           # existing type → real tradeoff
    state = _set_pasture_1x1(state, 0, 0, 0)
    return with_pending_stack(state, [
        PendingSheepMarket(player_idx=0, initiated_by_id="sheep_market", gained=4),
    ])


def test_animal_frontier_owns():
    import dataclasses
    from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD as H
    s_breed = _breed_state_two_types()
    assert H.owns(s_breed)                              # harvest breed, not chosen
    assert H.owns(_sheep_market_state())               # animal market
    s_place, _ = setup_env(seed=7)
    assert not H.owns(s_place)                          # placement
    # breed_chosen=True → only Stop remains → not a frontier decision
    top = s_breed.pending_stack[-1]
    s_done = dataclasses.replace(
        s_breed,
        pending_stack=s_breed.pending_stack[:-1]
        + (dataclasses.replace(top, breed_chosen=True),),
    )
    assert not H.owns(s_done)


def test_animal_frontier_breed_candidates_match_legality():
    from agricola.actions import CommitBreed
    from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD as H
    from agricola.legality import legal_actions as full
    s = _breed_state_two_types()
    legal_breed = [a for a in full(s) if isinstance(a, CommitBreed)]
    assert len(legal_breed) >= 2
    assert H.candidates(s) == legal_breed              # same set AND order
    feats = H.candidate_features(s)
    assert feats.shape == (len(legal_breed), 4)
    for a, row in zip(legal_breed, feats):             # kept counts = raw fields
        assert (row[0], row[1], row[2]) == (a.sheep, a.boar, a.cattle)


def test_animal_frontier_breed_food_matches_helper():
    from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD as H
    from agricola.helpers import breeding_food_gained, cooking_rates
    from agricola.resources import Animals
    s = _breed_state_two_types()
    pidx = s.pending_stack[-1].player_idx
    pre = s.players[pidx].animals
    rates3 = cooking_rates(s, pidx)[:3]
    for a, row in H.enumerate_candidates(s):
        post = Animals(sheep=a.sheep, boar=a.boar, cattle=a.cattle)
        assert row[3] == breeding_food_gained(pre, post, rates3)


def test_animal_frontier_target_position():
    from agricola.actions import PlaceWorker
    from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD as H
    s = _breed_state_two_types()
    cands = H.candidates(s)
    assert H.target_position(s, cands[0]) == 0
    assert H.target_position(s, cands[-1]) == len(cands) - 1
    assert H.target_position(s, PlaceWorker(space="forest")) is None


def test_animal_frontier_accommodate_matches_legality_and_food():
    from agricola.actions import CommitAccommodate
    from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD as H
    from agricola.helpers import cooking_rates, pareto_frontier
    from agricola.legality import legal_actions as full
    from agricola.resources import Animals
    s = _sheep_market_state()
    legal_acc = [a for a in full(s) if isinstance(a, CommitAccommodate)]
    assert H.candidates(s) == legal_acc
    top = s.pending_stack[-1]
    rates3 = cooking_rates(s, top.player_idx)[:3]
    food_by_cfg = {
        (c.sheep, c.boar, c.cattle): f
        for c, f in pareto_frontier(s.players[top.player_idx],
                                    Animals(sheep=top.gained), rates3)
    }
    foods = [row[3] for _, row in H.enumerate_candidates(s)]
    assert any(f > 0 for f in foods)                   # food slot is exercised
    for a, row in H.enumerate_candidates(s):
        assert row[3] == food_by_cfg[(a.sheep, a.boar, a.cattle)]


# ---------------------------------------------------------------------------
# Pointer head — torch layer (segment dataset/collate, scorer, prior, dispatch)
# ---------------------------------------------------------------------------

from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD  # noqa: E402


def _tiny_pointer_model(head=ANIMAL_FRONTIER_HEAD, seed=0):
    torch.manual_seed(seed)
    net = ConfigurableMLP(ENCODED_DIM + head.candidate_dim, [16], 1, head="linear")
    stats = PointerNormStats(
        input_mean=np.zeros(ENCODED_DIM + head.candidate_dim, np.float32),
        input_std=np.ones(ENCODED_DIM + head.candidate_dim, np.float32),
        candidate_dim=head.candidate_dim,
        encoding_version=ENCODING_VERSION,
    )
    m = NormalizedPointerModel(net, stats)
    m.head_name = head.name
    return m


def _fake_breed_games(n):
    """n GameRecords (distinct seeds), each one breed snapshot from the 2-point
    frontier, cycling the chosen candidate."""
    from agricola.agents.nn import DATA_VERSION
    from agricola.agents.nn.schema import DecisionSnapshot, GameRecord
    s = _breed_state_two_types()
    cands = ANIMAL_FRONTIER_HEAD.candidates(s)
    d = s.pending_stack[-1].player_idx
    games = []
    for seed in range(n):
        snap = DecisionSnapshot(state=s, chosen_action=cands[seed % len(cands)],
                                decider_idx=d)
        games.append(GameRecord(
            data_version=DATA_VERSION, game_idx=seed, seed=seed,
            p0_config_path="x", p1_config_path="x",
            p0_temperature=0.0, p1_temperature=0.0,
            p0_final_score=10, p1_final_score=5, winner=0,
            terminal_state=s, decisions=(snap,)))
    return games


def test_segment_log_softmax_matches_per_segment():
    import torch.nn.functional as F
    from agricola.agents.nn.policy_pointer_model import segment_log_softmax
    scores = torch.tensor([1.0, 3.0, 2.0, 0.0, 5.0])
    seg = torch.tensor([0, 0, 1, 1, 1])
    lp = segment_log_softmax(scores, seg, 2)
    assert torch.allclose(lp[:2], F.log_softmax(scores[:2], dim=0), atol=1e-6)
    assert torch.allclose(lp[2:], F.log_softmax(scores[2:], dim=0), atol=1e-6)
    p = lp.exp()
    assert abs(p[:2].sum().item() - 1.0) < 1e-6
    assert abs(p[2:].sum().item() - 1.0) < 1e-6


def test_pointer_model_candidate_probs_sum_to_one():
    m = _tiny_pointer_model()
    probs = m.candidate_probs(torch.randn(ENCODED_DIM), torch.randn(5, 4))
    assert probs.shape == (5,)
    assert (probs >= 0).all()
    assert abs(probs.sum().item() - 1.0) < 1e-5


def test_pointer_model_flat_matches_per_state():
    # The flattened (segment) scorer path must agree with the single-state path.
    m = _tiny_pointer_model()
    s0, s1 = torch.randn(ENCODED_DIM), torch.randn(ENCODED_DIM)
    c0, c1 = torch.randn(2, 4), torch.randn(3, 4)
    flat = m.score_flat(torch.stack([s0, s1]), torch.cat([c0, c1]),
                        torch.tensor([0, 0, 1, 1, 1]))
    assert torch.allclose(flat[:2], m.score_candidates(s0, c0), atol=1e-5)
    assert torch.allclose(flat[2:], m.score_candidates(s1, c1), atol=1e-5)


def test_pointer_model_save_load_roundtrip(tmp_path):
    m = _tiny_pointer_model(seed=1)
    state, cand = torch.randn(ENCODED_DIM), torch.randn(4, 4)
    before = m.candidate_probs(state, cand)
    m.save(tmp_path / "ptr")
    loaded = NormalizedPointerModel.load(tmp_path / "ptr")
    assert torch.allclose(before, loaded.candidate_probs(state, cand), atol=1e-6)
    meta = json.loads((tmp_path / "ptr.meta.json").read_text())
    assert meta["model_kind"] == "policy_pointer"
    assert meta["head"] == "animal_frontier"
    assert meta["candidate_dim"] == 4


def test_pointer_model_encoding_version_mismatch(tmp_path):
    m = _tiny_pointer_model()
    m.save(tmp_path / "ptr")
    meta_path = tmp_path / "ptr.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["encoding_version"] = ENCODING_VERSION + 99
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(EncodingVersionMismatch):
        NormalizedPointerModel.load(tmp_path / "ptr")


def test_pointer_extraction_rows():
    from agricola.agents.nn.policy_pointer_dataset import _pointer_rows
    rows = list(_pointer_rows(_fake_breed_games(3), ANIMAL_FRONTIER_HEAD))
    assert len(rows) == 3
    for seed, state_enc, cand, pos, R, won, pi in rows:
        assert state_enc.shape == (ENCODED_DIM,)
        assert cand.shape == (cand.shape[0], ANIMAL_FRONTIER_HEAD.candidate_dim)
        assert cand.shape[0] >= 2
        assert 0 <= pos < cand.shape[0]
        assert won in (1.0, 0.0, -1.0)


def test_pointer_extraction_raises_on_drift():
    from agricola.actions import CommitBreed
    from agricola.agents.nn import DATA_VERSION
    from agricola.agents.nn.policy_pointer_dataset import _pointer_rows
    from agricola.agents.nn.schema import DecisionSnapshot, GameRecord
    s = _breed_state_two_types()
    bogus = CommitBreed(sheep=99, boar=99, cattle=99)   # not on the frontier
    g = GameRecord(
        data_version=DATA_VERSION, game_idx=0, seed=0,
        p0_config_path="x", p1_config_path="x",
        p0_temperature=0.0, p1_temperature=0.0,
        p0_final_score=1, p1_final_score=0, winner=0,
        terminal_state=s,
        decisions=(DecisionSnapshot(state=s, chosen_action=bogus,
                                    decider_idx=s.pending_stack[-1].player_idx),))
    with pytest.raises(ValueError):
        list(_pointer_rows([g], ANIMAL_FRONTIER_HEAD))


def test_pointer_collate_segments_and_chosen_flat():
    from agricola.agents.nn.policy_pointer_dataset import pointer_collate
    # Each item: (state, cand[K,4], pi[K], chosen_pos, weight) — matches the
    # updated AgricolaPointerDataset.__getitem__ layout.
    batch = [
        (torch.zeros(ENCODED_DIM), torch.zeros(2, 4),
         torch.tensor([0.0, 1.0]), 1, torch.tensor(1.0)),
        (torch.ones(ENCODED_DIM), torch.ones(3, 4),
         torch.tensor([1.0, 0.0, 0.0]), 0, torch.tensor(2.0)),
    ]
    state, cand, seg, chosen_flat, weight, pi_flat = pointer_collate(batch)
    assert state.shape == (2, ENCODED_DIM)
    assert cand.shape == (5, 4)
    assert seg.tolist() == [0, 0, 1, 1, 1]
    assert chosen_flat.tolist() == [1, 2]      # snap0 pos1→flat1; snap1 pos0→flat2
    assert weight.tolist() == [1.0, 2.0]
    assert pi_flat.tolist() == [0.0, 1.0, 1.0, 0.0, 0.0]   # per-segment one-hot


def test_build_pointer_datasets_from_games_and_segment_ce():
    from agricola.agents.nn.policy_pointer_dataset import (
        build_pointer_datasets_from_games, pointer_collate)
    from agricola.agents.nn.policy_pointer_model import segment_log_softmax
    train, val, test, stats, info = build_pointer_datasets_from_games(
        _fake_breed_games(12), loss_weight="unweighted", verbose=False)
    assert stats.input_dim == ENCODED_DIM + ANIMAL_FRONTIER_HEAD.candidate_dim
    assert stats.candidate_dim == ANIMAL_FRONTIER_HEAD.candidate_dim
    assert len(train) >= 1 and info["loss_weight"] == "unweighted"
    # Full forward → segment-CE is finite over the train batch.
    state, cand, seg, chosen_flat, weight, pi_flat = pointer_collate(
        [train[i] for i in range(len(train))])
    lp = segment_log_softmax(_tiny_pointer_model().score_flat(state, cand, seg),
                             seg, state.shape[0])
    assert torch.isfinite(-lp[chosen_flat]).all()


def test_build_pointer_datasets_awr(tmp_path):
    from agricola.agents.nn.policy_pointer_dataset import build_pointer_datasets_from_games
    vnet = ConfigurableMLP(ENCODED_DIM, [8], 1, head="linear")
    vstats = NormStats(np.zeros(ENCODED_DIM, np.float32),
                       np.ones(ENCODED_DIM, np.float32), 14.0, ENCODING_VERSION)
    NormalizedValueModel(vnet, vstats).save(tmp_path / "vmodel")
    _, _, _, _, info = build_pointer_datasets_from_games(
        _fake_breed_games(12), loss_weight="awr", value_ckpt=tmp_path / "vmodel",
        awr_clip=6.0, verbose=False)
    assert info["loss_weight"] == "awr" and info["awr_beta"] is not None


def test_pointer_prior_distribution_over_frontier():
    m = _tiny_pointer_model()
    s = _breed_state_two_types()
    pri = pointer_prior(s, m)
    assert pri is not NO_PRIOR
    assert set(pri) == set(ANIMAL_FRONTIER_HEAD.candidates(s))
    assert abs(sum(pri.values()) - 1.0) < 1e-5


def test_pointer_prior_no_prior_off_decision(small_games):
    m = _tiny_pointer_model()
    s_place, _ = setup_env(seed=7)
    assert pointer_prior(s_place, m) is NO_PRIOR                     # placement
    assert pointer_prior(small_games[0].terminal_state, m) is NO_PRIOR  # terminal


def test_make_policy_fn_routes_to_pointer_head():
    from agricola.actions import CommitBreed
    pf = make_policy_fn([_tiny_policy_model(PLACEMENT_HEAD),
                         _tiny_pointer_model(ANIMAL_FRONTIER_HEAD)])
    s = _breed_state_two_types()
    pri = pf(s, _full_legal(s))
    assert set(pri) == set(ANIMAL_FRONTIER_HEAD.candidates(s))
    assert all(isinstance(a, CommitBreed) for a in pri)
    assert abs(sum(pri.values()) - 1.0) < 1e-5
    # placement still routes to the placement head
    s0, _ = setup_env(seed=7)
    assert all(isinstance(a, PlaceWorker) for a in pf(s0, _full_legal(s0)))


# ---- harvest_feed pointer head (heterogeneous toggle + convert candidates) ----

from agricola.agents.nn.policy_heads import HARVEST_FEED_HEAD  # noqa: E402


def _harvest_feed_state():
    """PendingHarvestFeed (P0 on top): owns Joinery + 1 wood (a craft toggle) and
    grain=3 with food_owed=4 (a multi-point CommitConvert frontier with begging)."""
    import dataclasses
    from agricola.constants import Phase
    from agricola.engine import _initiate_harvest_feed
    from agricola.setup import setup
    from tests.factories import with_majors, with_phase, with_resources
    s = setup(seed=0)
    s = dataclasses.replace(s, starting_player=0)
    s = with_majors(s, owner_by_idx={7: 0})            # Joinery (major 7)
    s = with_resources(s, 0, food=0, wood=1, grain=3)
    s = with_resources(s, 1, food=99)
    s = with_phase(s, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(s)


def test_harvest_feed_owns():
    import dataclasses
    s = _harvest_feed_state()
    assert HARVEST_FEED_HEAD.owns(s)
    top = s.pending_stack[-1]
    s_done = dataclasses.replace(
        s, pending_stack=s.pending_stack[:-1]
        + (dataclasses.replace(top, conversion_done=True),))
    assert not HARVEST_FEED_HEAD.owns(s_done)          # only Stop left
    s_place, _ = setup_env(seed=7)
    assert not HARVEST_FEED_HEAD.owns(s_place)


def test_harvest_feed_candidates_match_legality_both_kinds():
    from agricola.actions import CommitConvert, CommitHarvestConversion
    from agricola.legality import legal_actions as full
    s = _harvest_feed_state()
    legal_feed = [a for a in full(s)
                  if isinstance(a, (CommitConvert, CommitHarvestConversion))]
    assert HARVEST_FEED_HEAD.candidates(s) == legal_feed
    assert any(isinstance(a, CommitHarvestConversion) for a in legal_feed)
    assert any(isinstance(a, CommitConvert) for a in legal_feed)
    assert HARVEST_FEED_HEAD.candidate_features(s).shape == (len(legal_feed), 10)


def test_harvest_feed_featurizer_tags_and_begging():
    from agricola.actions import CommitConvert, CommitHarvestConversion
    from agricola.agents.nn.policy_heads import _CRAFT_INDEX
    from agricola.helpers import cooking_rates, harvest_feed_frontier
    s = _harvest_feed_state()
    pidx = s.pending_stack[-1].player_idx
    p = s.players[pidx]
    rates = cooking_rates(s, pidx)
    food_owed = max(0, 2 * p.people_total - p.newborns - p.resources.food)
    g0, v0 = p.resources.grain, p.resources.veg
    s0, b0, c0 = p.animals.sheep, p.animals.boar, p.animals.cattle
    beg = {(g0 - gr, v0 - vr, s0 - sr, b0 - br, c0 - cr): bg
           for ((gr, vr, sr, br, cr), bg) in harvest_feed_frontier(p, food_owed, rates)}
    saw_beg = False
    for a, row in HARVEST_FEED_HEAD.enumerate_candidates(s):
        if isinstance(a, CommitHarvestConversion):
            assert row[0] == 1.0
            assert row[1 + _CRAFT_INDEX[a.conversion_id]] == 1.0
            assert row[4:9].sum() == 0 and row[9] == 0     # toggle: no consumed/begging
        else:
            assert row[0] == 0.0
            assert tuple(row[4:9]) == (a.grain, a.veg, a.sheep, a.boar, a.cattle)
            assert row[9] == beg[(a.grain, a.veg, a.sheep, a.boar, a.cattle)]
            saw_beg = saw_beg or row[9] > 0
    assert saw_beg, "expected at least one convert option to incur begging"


def test_harvest_feed_build_prior_and_routing():
    from agricola.agents.nn import DATA_VERSION
    from agricola.agents.nn.policy import NO_PRIOR, make_policy_fn, pointer_prior
    from agricola.agents.nn.policy_pointer_dataset import build_pointer_datasets_from_games
    from agricola.agents.nn.schema import DecisionSnapshot, GameRecord
    s = _harvest_feed_state()
    cands = HARVEST_FEED_HEAD.candidates(s)
    d = s.pending_stack[-1].player_idx
    games = [GameRecord(
        data_version=DATA_VERSION, game_idx=i, seed=i,
        p0_config_path="x", p1_config_path="x", p0_temperature=0.0, p1_temperature=0.0,
        p0_final_score=10, p1_final_score=5, winner=0, terminal_state=s,
        decisions=(DecisionSnapshot(state=s, chosen_action=cands[i % len(cands)],
                                    decider_idx=d),)) for i in range(12)]
    train, *_rest, stats, info = build_pointer_datasets_from_games(
        games, head=HARVEST_FEED_HEAD, loss_weight="unweighted", verbose=False)
    assert stats.candidate_dim == 10 and len(train) >= 1
    m = _tiny_pointer_model(HARVEST_FEED_HEAD)
    pri = pointer_prior(s, m)
    assert pri is not NO_PRIOR and set(pri) == set(cands)
    assert abs(sum(pri.values()) - 1.0) < 1e-5
    pri2 = make_policy_fn([m])(s, _full_legal(s))      # routes feed → harvest_feed head
    assert set(pri2) == set(cands)


def test_load_policy_fn_mixed_checkpoints(tmp_path):
    # load_policy_fn auto-detects fixed vs pointer checkpoints and assembles one
    # combined policy_fn that dispatches correctly.
    from agricola.agents.nn.policy import load_policy_fn
    _tiny_policy_model(CHOOSE_SUBACTION_HEAD).save(tmp_path / "cs")
    _tiny_pointer_model(ANIMAL_FRONTIER_HEAD).save(tmp_path / "af")
    pf = load_policy_fn([tmp_path / "cs", tmp_path / "af"])
    s = _breed_state_two_types()                     # a pointer-head decision
    assert set(pf(s, _full_legal(s))) == set(ANIMAL_FRONTIER_HEAD.candidates(s))


def test_train_pointer_smoke(tmp_path):
    from agricola.agents.nn.policy_pointer_training import train_pointer
    run_dir = tmp_path / "run"
    (run_dir / "games").mkdir(parents=True)
    with (run_dir / "games" / "worker_00.pkl").open("wb") as f:
        pickle.dump(_fake_breed_games(20), f)

    out_dir = tmp_path / "out"
    log, best = train_pointer(
        run_dir, out_dir, loss_weight="unweighted", hidden_dims=[16, 16],
        max_epochs=3, early_stop_patience=99, batch_size=8, verbose=False,
    )
    assert len(log) == 3
    for name in ("config.json", "pointer_norm_stats.json", "train_log.jsonl",
                 "best.pt", "best.meta.json", "test_metrics.json"):
        assert (out_dir / name).exists(), name
    # Best checkpoint loads and scores candidates.
    model = NormalizedPointerModel.load(best)
    probs = model.candidate_probs(torch.randn(ENCODED_DIM), torch.randn(3, 4))
    assert probs.shape == (3,) and abs(probs.sum().item() - 1.0) < 1e-5
    for k in ("train_ce", "val_ce", "val_top1", "val_top3"):
        assert k in log[0]
    tm = json.loads((out_dir / "test_metrics.json").read_text())
    assert "test" in tm and "top1" in tm["test"]
