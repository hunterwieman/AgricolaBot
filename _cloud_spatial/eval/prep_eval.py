#!/usr/bin/env python
"""Prep a fair C++ MCTS match: a256-spatial vs champion (joint_a256_300k).

Both joint models' value_scale + outcome_scale are re-measured on ONE common
state set (identical states), so neither leaf is mis-calibrated. Exports the
spatial model and writes a champion export copy, both with the common-set scales.
"""
import json, pickle, random
from pathlib import Path
import numpy as np
import torch

from agricola.agents.nn.schema import load_game_records
from agricola.agents.nn.model import load_value_evaluator
from agricola.agents.nn.encoder import (
    encode_for_inference, encode_for_inference_spatial, encode_for_inference_candidate)

ENC = {"": encode_for_inference, "v2": encode_for_inference,
       "cand_spatial_v1": encode_for_inference_spatial,
       "cand_feat178_v1": encode_for_inference_candidate}

ROOT = Path("/Users/hunterwieman/Desktop/Agricola/AgricolaBot")
PKL_DIR = Path("/tmp/enc_measure/shard/games")
N_STATES = 6000
SEED = 42

# --- 1. common state set (sample from local gen300k pickles) ------------------
states = []
for pkl in sorted(PKL_DIR.glob("worker_*.pkl")):
    for g in load_game_records(pkl):
        for snap in g.decisions:
            states.append(snap.state)
random.seed(SEED)
common = random.sample(states, min(N_STATES, len(states)))
print(f"common set: {len(common)} states (from {len(states)} total)", flush=True)

# --- 2. measure value_scale + outcome_scale for a model on the common set -----
def measure(model):
    enc = ENC[str(getattr(model, "encoding_tag", "") or "")]
    X = np.stack([enc(s, 0) for s in common]).astype(np.float32)
    x = torch.from_numpy(X)
    model.eval()
    with torch.no_grad():
        m = model.predict_margin(x).cpu().numpy()
        try:
            o = model.predict_outcome(x).cpu().numpy(); osc = float(o.std())
        except Exception as e:
            print(f"  (no predict_outcome: {e})"); osc = 1.0
    return float(m.std()), osc

champ = load_value_evaluator(str(ROOT / "nn_models" / "best"))
spat  = load_value_evaluator(str(ROOT / "_cloud_spatial/eval/spatial_a256/best"))
cv, co = measure(champ); sv, so = measure(spat)
print(f"CHAMPION  common-set: value_scale={cv:.4f}  outcome_scale={co:.4f}  (stored 3.298/0.549)", flush=True)
print(f"SPATIAL   common-set: value_scale={sv:.4f}  outcome_scale={so:.4f}", flush=True)
json.dump({"champ": [cv, co], "spatial": [sv, so]},
          open(ROOT / "_cloud_spatial/eval/scales.json", "w"), indent=2)
print("scales -> _cloud_spatial/eval/scales.json", flush=True)
