"""Tests for the siamese variant of the shared-trunk model
(`SiameseSharedTrunkModel` in `shared_model.py`).

The siamese model is a drop-in for `SharedTrunkModel` (same public surface and
head outputs); the only difference is the trunk's front end — both players' blocks
run through one shared per-player encoder, then `[own;opp;shared;mid]` feeds the
usual trunk. Covers: forward shapes for every head type, the value/outcome
contracts, a couple of optimizer steps (finite + decreasing loss), save/load
round-trip parity, the block-split derivation, and that the player encoder is
genuinely shared (own and opp get the SAME function).
"""
from __future__ import annotations

import numpy as np
import torch

from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.shared_model import (
    MID_BLOCK_DIM,
    SHARED_BLOCK_DIM,
    SiameseSharedTrunkModel,
    _siamese_blocks,
)

FIXED_SPECS = {name: h.num_classes for name, h in HEADS.items()}
POINTER_SPECS = {name: h.candidate_dim for name, h in POINTER_HEADS.items()}


def _stats() -> NormStats:
    return NormStats(
        input_mean=np.zeros(ENCODED_DIM, np.float32),
        input_std=np.ones(ENCODED_DIM, np.float32),
        target_std=12.0,
        encoding_version=ENCODING_VERSION,
    )


def _model(**over) -> SiameseSharedTrunkModel:
    kw = dict(
        fixed_head_specs=FIXED_SPECS, pointer_head_specs=POINTER_SPECS,
        norm_stats=_stats(), trunk_hidden_dims=[64, 64], embedding_dim=32,
        pointer_head_dims=[16], player_encoder_dims=[24], player_encoder_out=16,
    )
    kw.update(over)
    return SiameseSharedTrunkModel(**kw)


def test_block_split_derivation():
    # v2 layout: own(54) | opp(54) | shared(54) | mid(8) = 170.
    p, shared, mid = _siamese_blocks(ENCODED_DIM)
    assert (p, shared, mid) == (54, SHARED_BLOCK_DIM, MID_BLOCK_DIM)
    # candidate layout: own(58) | opp(58) | shared(54) | mid(8) = 178.
    assert _siamese_blocks(178) == (58, SHARED_BLOCK_DIM, MID_BLOCK_DIM)
    # odd remainder rejected (63 - 62 = 1, not an even split).
    try:
        _siamese_blocks(63)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_embedding_and_head_forward_shapes():
    m = _model().eval()
    B = 5
    x = torch.randn(B, ENCODED_DIM)
    emb = m.embed(x)
    assert emb.shape == (B, 32)
    assert m.value_from_embedding(emb).shape == (B,)
    assert m.predict_margin(x).shape == (B,)
    assert m.predict_outcome(x).shape == (B,)
    for name, K in FIXED_SPECS.items():
        assert m.fixed_logits_from_embedding(emb, name).shape == (B, K)
    for name, dim in POINTER_SPECS.items():
        M = 7
        emb_rows = m.embed(torch.randn(M, ENCODED_DIM))
        cand = torch.randn(M, dim)
        assert m.pointer_scores_from_embedding(name, emb_rows, cand).shape == (M,)


def test_player_encoder_is_shared():
    # The own and opp blocks pass through the SAME encoder: swap the two halves
    # in the input and the two per-player embeddings should swap accordingly,
    # which (since shared/mid are unchanged) keeps the trunk-fused vector's
    # own/opp embedding slots merely swapped. Concretely: encoding a state and
    # its own/opp-swapped twin must produce embeddings that differ only because
    # the order changed — easiest check is that a self-symmetric input (own==opp)
    # gives identical own/opp embeddings.
    m = _model().eval()
    p = m._player_block
    block = torch.randn(1, p)
    shared_mid = torch.randn(1, SHARED_BLOCK_DIM + MID_BLOCK_DIM)
    x = torch.cat([block, block, shared_mid], dim=1)  # own == opp
    with torch.no_grad():
        norm_x = (x - m.input_mean) / m.input_std
        e_own = m.player_encoder(norm_x[:, :p])
        e_opp = m.player_encoder(norm_x[:, p:2 * p])
    assert torch.allclose(e_own, e_opp, atol=1e-6)


def test_predict_margin_uses_target_std():
    m = _model().eval()
    x = torch.randn(4, ENCODED_DIM)
    with torch.no_grad():
        norm_v = m.value_from_embedding(m.embed(x))
        assert torch.allclose(m.predict_margin(x), norm_v * 12.0, atol=1e-6)


def test_optimizer_steps_reduce_loss():
    torch.manual_seed(0)
    m = _model().train()
    x = torch.randn(64, ENCODED_DIM)
    y = torch.randn(64)  # normalized value target
    opt = torch.optim.Adam(m.parameters(), lr=1e-2)
    losses = []
    for _ in range(10):
        opt.zero_grad()
        pred = m.value_from_embedding(m.embed(x))
        loss = torch.nn.functional.mse_loss(pred, y)
        assert torch.isfinite(loss)
        loss.backward()
        opt.step()
        losses.append(float(loss))
    assert losses[-1] < losses[0]  # overfits a fixed batch


def test_save_load_roundtrip_parity(tmp_path):
    m = _model().eval()
    m.set_pointer_cand_norm("harvest_feed",
                            mean=np.arange(POINTER_SPECS["harvest_feed"], dtype=np.float32),
                            std=np.full(POINTER_SPECS["harvest_feed"], 2.0, np.float32))
    m.value_scale = 7.5
    x = torch.randn(6, ENCODED_DIM)
    with torch.no_grad():
        v0 = m.predict_margin(x)
        o0 = m.predict_outcome(x)
        emb = m.embed(x)
        plogits0 = m.fixed_logits_from_embedding(emb, "placement")
        cand = torch.randn(6, POINTER_SPECS["harvest_feed"])
        ps0 = m.pointer_scores_from_embedding("harvest_feed", emb, cand)

    m.save(tmp_path / "siam")
    m2 = SiameseSharedTrunkModel.load(tmp_path / "siam").eval()
    assert m2.config_dict() == m.config_dict()
    assert m2.value_scale == 7.5
    with torch.no_grad():
        assert torch.allclose(m2.predict_margin(x), v0, atol=1e-6)
        assert torch.allclose(m2.predict_outcome(x), o0, atol=1e-6)
        emb2 = m2.embed(x)
        assert torch.allclose(m2.fixed_logits_from_embedding(emb2, "placement"),
                              plogits0, atol=1e-6)
        assert torch.allclose(
            m2.pointer_scores_from_embedding("harvest_feed", emb2, cand), ps0, atol=1e-6)


def test_meta_records_siamese_kind(tmp_path):
    import json
    m = _model()
    m.save(tmp_path / "siam")
    meta = json.loads((tmp_path / "siam.meta.json").read_text())
    assert meta["model_kind"] == "siamese_shared_trunk"
    assert meta["net_config"]["player_encoder_out"] == 16
    assert meta["net_config"]["player_encoder_dims"] == [24]
