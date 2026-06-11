"""Tests for the shared-trunk value+policy model (`shared_model.py`).

Covers: forward shapes for every head type, the value contract
(`predict_margin`), save/load round-trip parity, architecture agnosticism
(arbitrary trunk/embedding/head dims reconstruct), and the pointer-head
candidate-normalization path.
"""
from __future__ import annotations

import numpy as np
import torch

from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.shared_model import SharedTrunkModel

FIXED_SPECS = {name: h.num_classes for name, h in HEADS.items()}
POINTER_SPECS = {name: h.candidate_dim for name, h in POINTER_HEADS.items()}


def _stats() -> NormStats:
    return NormStats(
        input_mean=np.zeros(ENCODED_DIM, np.float32),
        input_std=np.ones(ENCODED_DIM, np.float32),
        target_std=12.0,
        encoding_version=ENCODING_VERSION,
    )


def _model(**over) -> SharedTrunkModel:
    kw = dict(
        fixed_head_specs=FIXED_SPECS, pointer_head_specs=POINTER_SPECS,
        norm_stats=_stats(), trunk_hidden_dims=[64, 64], embedding_dim=32,
        pointer_head_dims=[16],
    )
    kw.update(over)
    return SharedTrunkModel(**kw)


def test_embedding_and_head_forward_shapes():
    m = _model().eval()
    B = 5
    x = torch.randn(B, ENCODED_DIM)
    emb = m.embed(x)
    assert emb.shape == (B, 32)
    # value head
    assert m.value_from_embedding(emb).shape == (B,)
    assert m.predict_margin(x).shape == (B,)
    # every fixed head
    for name, K in FIXED_SPECS.items():
        assert m.fixed_logits_from_embedding(emb, name).shape == (B, K)
    # pointer heads: M candidate rows, each carrying its state's embedding
    for name, dim in POINTER_SPECS.items():
        M = 7
        emb_rows = m.embed(torch.randn(M, ENCODED_DIM))
        cand = torch.randn(M, dim)
        assert m.pointer_scores_from_embedding(name, emb_rows, cand).shape == (M,)


def test_predict_margin_uses_target_std():
    # predict_margin = normalized_value * target_std (the inference contract).
    m = _model().eval()
    x = torch.randn(4, ENCODED_DIM)
    with torch.no_grad():
        norm_v = m.value_from_embedding(m.embed(x))
        assert torch.allclose(m.predict_margin(x), norm_v * 12.0, atol=1e-6)


def test_save_load_roundtrip_parity(tmp_path):
    m = _model().eval()
    # perturb a pointer head's candidate norm so it's non-identity and must persist
    m.set_pointer_cand_norm("harvest_feed",
                            mean=np.arange(POINTER_SPECS["harvest_feed"], dtype=np.float32),
                            std=np.full(POINTER_SPECS["harvest_feed"], 2.0, np.float32))
    m.value_scale = 7.5
    x = torch.randn(6, ENCODED_DIM)
    with torch.no_grad():
        v0 = m.predict_margin(x)
        emb = m.embed(x)
        plogits0 = m.fixed_logits_from_embedding(emb, "placement")
        cand = torch.randn(6, POINTER_SPECS["harvest_feed"])
        ps0 = m.pointer_scores_from_embedding("harvest_feed", emb, cand)

    m.save(tmp_path / "shared")
    m2 = SharedTrunkModel.load(tmp_path / "shared").eval()
    assert m2.config_dict() == m.config_dict()
    assert m2.value_scale == 7.5
    with torch.no_grad():
        assert torch.allclose(m2.predict_margin(x), v0, atol=1e-6)
        emb2 = m2.embed(x)
        assert torch.allclose(m2.fixed_logits_from_embedding(emb2, "placement"),
                              plogits0, atol=1e-6)
        assert torch.allclose(
            m2.pointer_scores_from_embedding("harvest_feed", emb2, cand), ps0, atol=1e-6)


def test_architecture_agnostic_shapes():
    # Arbitrary trunk/embedding/head dims all construct and reconstruct.
    m = _model(trunk_hidden_dims=[128, 96, 48], embedding_dim=24,
               value_head_dims=[16], fixed_head_dims=[20], pointer_head_dims=[12, 8])
    x = torch.randn(3, ENCODED_DIM)
    assert m.embed(x).shape == (3, 24)
    assert m.param_count() > 0
    cfg = m.config_dict()
    assert cfg["trunk_hidden_dims"] == [128, 96, 48] and cfg["embedding_dim"] == 24


def test_pointer_cand_norm_affects_output():
    m = _model().eval()
    M, dim = 4, POINTER_SPECS["animal_frontier"]
    emb = m.embed(torch.randn(M, ENCODED_DIM))
    cand = torch.randn(M, dim)
    with torch.no_grad():
        before = m.pointer_scores_from_embedding("animal_frontier", emb, cand)
        m.set_pointer_cand_norm("animal_frontier",
                                mean=np.full(dim, 5.0, np.float32),
                                std=np.full(dim, 3.0, np.float32))
        after = m.pointer_scores_from_embedding("animal_frontier", emb, cand)
    assert not torch.allclose(before, after)
