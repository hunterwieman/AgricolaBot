"""Tests for the NN model + normalization wrapper (`agricola/agents/nn/model.py`).

Coverage:
- `ConfigurableMLP` output shape contract (default + multi-dim + empty hidden)
- Activation / norm choices supported, bad arg raises
- Determinism given a seed
- Config-dict roundtrip (reconstruct from constructor kwargs)
- Param count sanity for the design-default architecture
- `NormalizedValueModel` forward normalizes inputs, predict_margin denormalizes
- Encoding-version mismatch raises at construction AND at load
- Save/load roundtrip preserves predictions exactly
- Normalization buffers preserved across save/load
- `extras` metadata persists in sidecar
- `.to(device)` moves buffers along with weights
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn

from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import (
    NET_REGISTRY,
    ConfigurableMLP,
    EncodingVersionMismatch,
    NormalizedValueModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stats(
    input_dim: int = ENCODED_DIM, target_std: float = 10.0,
) -> NormStats:
    """A non-trivial NormStats (non-zero mean, non-unit std)
    distinguishes a working normalization buffer from a broken one."""
    return NormStats(
        input_mean=np.arange(input_dim, dtype=np.float32),
        input_std=np.full(input_dim, 2.0, dtype=np.float32),
        target_std=float(target_std),
        encoding_version=ENCODING_VERSION,
    )


# ---------------------------------------------------------------------------
# ConfigurableMLP — output shape
# ---------------------------------------------------------------------------


def test_mlp_default_output_shape_squeezed():
    """Default output_dim=1 squeezes the trailing dim → (batch,)."""
    mlp = ConfigurableMLP(input_dim=170, hidden_dims=[32, 32])
    y = mlp(torch.randn(8, 170))
    assert y.shape == (8,)


def test_mlp_output_dim_multi_keeps_shape():
    """output_dim > 1 keeps (batch, output_dim) — usable as a
    sub-encoder for a future Siamese model (FIRST_NN.md §7.1)."""
    mlp = ConfigurableMLP(input_dim=170, hidden_dims=[32], output_dim=64)
    y = mlp(torch.randn(8, 170))
    assert y.shape == (8, 64)


def test_mlp_empty_hidden_dims_collapses_to_linear():
    """No hidden layers → just `Linear(input_dim, output_dim)`."""
    mlp = ConfigurableMLP(input_dim=10, hidden_dims=[], output_dim=3)
    y = mlp(torch.randn(4, 10))
    assert y.shape == (4, 3)


# ---------------------------------------------------------------------------
# ConfigurableMLP — config / activations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("activation", ["gelu", "silu", "relu", "tanh"])
def test_mlp_supported_activations(activation):
    mlp = ConfigurableMLP(input_dim=10, hidden_dims=[16], activation=activation)
    y = mlp(torch.randn(2, 10))
    assert y.shape == (2,)


def test_mlp_bad_activation_raises():
    with pytest.raises(ValueError):
        ConfigurableMLP(input_dim=10, hidden_dims=[16], activation="nope")


def test_mlp_bad_norm_raises():
    with pytest.raises(ValueError):
        ConfigurableMLP(input_dim=10, hidden_dims=[16], norm="bogus")


@pytest.mark.parametrize("bad_dropout", [-0.1, 1.0, 1.5])
def test_mlp_bad_dropout_raises(bad_dropout):
    with pytest.raises(ValueError):
        ConfigurableMLP(input_dim=10, hidden_dims=[16], dropout=bad_dropout)


def test_mlp_bad_head_raises():
    with pytest.raises(ValueError):
        ConfigurableMLP(input_dim=10, hidden_dims=[16], head="softmax")


@pytest.mark.parametrize("head,lo,hi", [
    ("tanh", -1.0, 1.0),
    ("sigmoid", 0.0, 1.0),
])
def test_mlp_head_bounds_output(head, lo, hi):
    """tanh/sigmoid heads bound the output to (-1,1) / (0,1). The linear
    default is unbounded (covered elsewhere)."""
    torch.manual_seed(0)
    mlp = ConfigurableMLP(input_dim=10, hidden_dims=[16], head=head)
    # Large-magnitude inputs would blow past the bounds without the head.
    x = torch.randn(64, 10) * 50.0
    out = mlp(x)
    assert out.min().item() >= lo
    assert out.max().item() <= hi


def test_mlp_head_in_config_dict_and_roundtrips():
    """The head is persisted in config_dict so save/load reconstructs it."""
    mlp = ConfigurableMLP(input_dim=10, hidden_dims=[8], head="sigmoid")
    assert mlp.config_dict()["head"] == "sigmoid"
    clone = ConfigurableMLP(**mlp.config_dict())
    assert clone.head == "sigmoid"


def test_mlp_head_defaults_linear():
    """Omitting head (e.g. loading a pre-P2 checkpoint config) → linear."""
    cfg = {"input_dim": 10, "hidden_dims": [8]}  # no 'head' key
    mlp = ConfigurableMLP(**cfg)
    assert mlp.head == "linear"


def test_mlp_norm_none_uses_identity():
    """norm='none' → identity (skip normalization). Useful for bare
    linear stacks (e.g., classifier heads)."""
    mlp = ConfigurableMLP(input_dim=10, hidden_dims=[8], norm="none")
    # No LayerNorm modules in the architecture.
    has_layernorm = any(isinstance(m, nn.LayerNorm) for m in mlp.modules())
    assert not has_layernorm


def test_mlp_deterministic_given_seed():
    torch.manual_seed(42)
    a = ConfigurableMLP(input_dim=10, hidden_dims=[16])
    torch.manual_seed(42)
    b = ConfigurableMLP(input_dim=10, hidden_dims=[16])
    x = torch.randn(2, 10)
    assert torch.equal(a(x), b(x))


def test_mlp_config_dict_recreates_same_architecture():
    """config_dict() captures enough info to reconstruct an architecturally
    identical module (param count + forward shape)."""
    mlp = ConfigurableMLP(
        input_dim=170, hidden_dims=[256, 128],
        output_dim=1, activation="silu", norm="layer", dropout=0.1,
    )
    config = mlp.config_dict()
    reconstructed = ConfigurableMLP(**config)
    assert reconstructed.param_count() == mlp.param_count()
    # Forward-shape compatible.
    x = torch.randn(2, 170)
    assert reconstructed(x).shape == mlp(x).shape


def test_mlp_default_design_param_count_in_expected_range():
    """The agreed default config is [256, 256] / GELU / LayerNorm /
    dropout 0.0 / no residual / output 1. Sanity-check the param count
    sits in the ballpark we said it would (~200k)."""
    mlp = ConfigurableMLP(
        input_dim=170, hidden_dims=[256, 256],
        activation="gelu", norm="layer", dropout=0.0,
    )
    # Rough breakdown:
    #   Linear(170, 256): 170*256+256 = 43,776
    #   LayerNorm(256):                     512
    #   Linear(256, 256): 256*256+256 = 65,792
    #   LayerNorm(256):                     512
    #   Linear(256, 1):   256*1+1   =      257
    #   Total: ~110,849
    n = mlp.param_count()
    assert 100_000 < n < 150_000, f"Default architecture has {n} parameters"


# ---------------------------------------------------------------------------
# NormalizedValueModel — forward + predict_margin
# ---------------------------------------------------------------------------


class _SpyNet(nn.Module):
    """A net that records its received input. Used to verify the
    NormalizedValueModel passes a NORMALIZED tensor to its inner net."""

    def __init__(self, input_dim: int):
        super().__init__()
        self.input_dim = input_dim
        self.linear = nn.Linear(input_dim, 1)
        self.last_input: torch.Tensor | None = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        self.last_input = x.detach().clone()
        return self.linear(x).squeeze(-1)

    def config_dict(self) -> dict:
        return {"input_dim": self.input_dim}


def test_forward_normalizes_input_passed_to_net():
    """When x equals input_mean, the inner net should see all zeros
    (since (mean − mean) / std = 0). Strong correctness check that the
    normalization buffer is wired in."""
    stats = NormStats(
        input_mean=np.full(4, 5.0, dtype=np.float32),
        input_std=np.full(4, 2.0, dtype=np.float32),
        target_std=1.0,
        encoding_version=ENCODING_VERSION,
    )
    spy = _SpyNet(input_dim=4)
    model = NormalizedValueModel(spy, stats)
    x = torch.tensor([[5.0, 5.0, 5.0, 5.0]])  # equals mean
    _ = model(x)
    assert spy.last_input is not None
    assert torch.allclose(spy.last_input, torch.zeros(1, 4))


def test_forward_normalizes_with_correct_scale():
    """Non-mean input gets scaled by 1/std after centering."""
    stats = NormStats(
        input_mean=np.zeros(3, dtype=np.float32),
        input_std=np.array([1.0, 2.0, 4.0], dtype=np.float32),
        target_std=1.0,
        encoding_version=ENCODING_VERSION,
    )
    spy = _SpyNet(input_dim=3)
    model = NormalizedValueModel(spy, stats)
    x = torch.tensor([[4.0, 4.0, 4.0]])
    _ = model(x)
    # After normalization: [4/1, 4/2, 4/4] = [4.0, 2.0, 1.0]
    assert torch.allclose(spy.last_input, torch.tensor([[4.0, 2.0, 1.0]]))


def test_predict_margin_denormalizes_by_target_std():
    """predict_margin == forward * target_std."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=10.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    x = torch.randn(3, ENCODED_DIM)
    forward_out = model(x)
    margin_out = model.predict_margin(x)
    assert torch.allclose(margin_out, forward_out * 10.0)


# ---------------------------------------------------------------------------
# NormalizedValueModel — encoding-version safety
# ---------------------------------------------------------------------------


def test_construction_with_stale_encoding_version_raises():
    """Construction-time hard-fail prevents a wrapper from being built
    around stats from an older encoder schema."""
    stale = NormStats(
        input_mean=np.zeros(ENCODED_DIM, dtype=np.float32),
        input_std=np.ones(ENCODED_DIM, dtype=np.float32),
        target_std=1.0,
        encoding_version=ENCODING_VERSION + 1,
    )
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    with pytest.raises(EncodingVersionMismatch):
        NormalizedValueModel(mlp, stale)


# ---------------------------------------------------------------------------
# NormalizedValueModel — save / load
# ---------------------------------------------------------------------------


def test_save_load_roundtrip_preserves_predictions(tmp_path: Path):
    """End-to-end: same input → same predict_margin output before and
    after save/load. The strongest correctness test for persistence."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=5.0)
    mlp = ConfigurableMLP(
        input_dim=ENCODED_DIM, hidden_dims=[16, 16],
        activation="silu", norm="layer", dropout=0.0,
    )
    model = NormalizedValueModel(mlp, stats)
    x = torch.randn(4, ENCODED_DIM)
    before = model.predict_margin(x).detach().clone()

    save_path = tmp_path / "checkpoint"
    model.save(save_path)
    loaded = NormalizedValueModel.load(save_path)
    after = loaded.predict_margin(x)
    assert torch.equal(before, after)


def test_save_load_preserves_normalization_buffers(tmp_path: Path):
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=3.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    save_path = tmp_path / "checkpoint"
    model.save(save_path)
    loaded = NormalizedValueModel.load(save_path)
    assert torch.equal(loaded.input_mean, model.input_mean)
    assert torch.equal(loaded.input_std, model.input_std)
    assert loaded.target_std.item() == pytest.approx(3.0)


def test_value_scale_defaults_one_and_persists(tmp_path: Path):
    """value_scale defaults to 1.0, survives save/load via the meta
    sidecar, and does NOT affect predict_margin (MCTS-only knob)."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=1.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    assert model.value_scale == 1.0  # default

    x = torch.randn(4, ENCODED_DIM)
    before = model.predict_margin(x).detach().clone()
    model.value_scale = 7.5  # set post-hoc, as training does
    after = model.predict_margin(x)
    assert torch.equal(before, after), "value_scale must not affect predict_margin"

    save_path = tmp_path / "checkpoint"
    model.save(save_path)
    loaded = NormalizedValueModel.load(save_path)
    assert loaded.value_scale == pytest.approx(7.5)


def test_load_pre_p2_checkpoint_defaults_value_scale(tmp_path: Path):
    """A meta sidecar without a value_scale key (pre-P2 checkpoint) loads
    with value_scale defaulting to 1.0 — no MCTS normalization, correct."""
    import json
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=1.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    save_path = tmp_path / "checkpoint"
    model.save(save_path)
    # Strip value_scale from the sidecar to simulate a pre-P2 checkpoint.
    meta_path = save_path.with_suffix(".meta.json")
    meta = json.load(meta_path.open())
    del meta["value_scale"]
    json.dump(meta, meta_path.open("w"))
    loaded = NormalizedValueModel.load(save_path)
    assert loaded.value_scale == 1.0


def test_measure_leaf_value_scale_computes_differential_std():
    """measure_leaf_value_scale returns the std of pred[0::2]-pred[1::2]."""
    from agricola.agents.nn.model import measure_leaf_value_scale
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=10.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    x = torch.randn(40, ENCODED_DIM)  # 20 paired states
    s = measure_leaf_value_scale(model, x)
    # Reproduce by hand.
    with torch.no_grad():
        pred = model.predict_margin(x)
        expect = float((pred[0::2] - pred[1::2]).std().item())
    assert s == pytest.approx(expect, rel=1e-5)
    assert s > 0


def test_load_with_stale_encoding_version_raises(tmp_path: Path):
    """Tamper with the sidecar to simulate encoder-schema drift; load
    must hard-fail rather than silently producing wrong inferences."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=1.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    save_path = tmp_path / "checkpoint"
    model.save(save_path)

    meta_path = save_path.with_suffix(".meta.json")
    with meta_path.open("r") as f:
        meta = json.load(f)
    meta["encoding_version"] = ENCODING_VERSION + 1
    with meta_path.open("w") as f:
        json.dump(meta, f)

    with pytest.raises(EncodingVersionMismatch):
        NormalizedValueModel.load(save_path)


def test_save_extras_persisted_in_sidecar(tmp_path: Path):
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=1.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats)
    save_path = tmp_path / "checkpoint"
    model.save(save_path, extras={"git_sha": "abc123", "run_id": "test"})

    with save_path.with_suffix(".meta.json").open("r") as f:
        meta = json.load(f)
    assert meta["extras"] == {"git_sha": "abc123", "run_id": "test"}


# ---------------------------------------------------------------------------
# Device move + eval mode
# ---------------------------------------------------------------------------


def test_to_device_moves_buffers():
    """`.to(device)` should move the normalization buffers along with
    the weights. CPU is the only universally-available device for
    testing in CI."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=2.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    model = NormalizedValueModel(mlp, stats).to("cpu")
    assert model.input_mean.device.type == "cpu"
    assert model.input_std.device.type == "cpu"
    assert model.target_std.device.type == "cpu"
    # Forward still works.
    y = model.predict_margin(torch.randn(2, ENCODED_DIM))
    assert y.shape == (2,)


def test_inference_in_eval_mode_no_grad():
    """Inference idiom: eval mode + no_grad context. With LayerNorm +
    dropout=0, there's no train/eval discrepancy, but we still verify
    the idiom works end-to-end (catches accidental train-only ops)."""
    stats = _make_stats(input_dim=ENCODED_DIM, target_std=1.0)
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16], dropout=0.0)
    model = NormalizedValueModel(mlp, stats)
    model.eval()
    with torch.no_grad():
        y = model.predict_margin(torch.randn(1, ENCODED_DIM))
    assert y.shape == (1,)
    assert not y.requires_grad


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_net_registry_includes_configurable_mlp():
    """The default architecture must be in the registry for save/load."""
    assert "ConfigurableMLP" in NET_REGISTRY
    assert NET_REGISTRY["ConfigurableMLP"] is ConfigurableMLP
