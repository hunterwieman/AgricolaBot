#!/usr/bin/env python
"""Prep the b512-spatial vs B_wide match — same fair setup as the a256 eval.

Both 512->512->256 joint models' value_scale + outcome_scale are re-measured on
the SAME common 6k state set (seed 42, identical to the a256 prep), then both are
C++-exported and their manifests patched. Only the encoder differs (b512 spatial /
B_wide v2), so the match isolates the encoder.
"""
import json, random, subprocess, sys
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
EVAL = ROOT / "_cloud_spatial/eval"
PKL_DIR = Path("/tmp/enc_measure/shard/games")

# --- common state set (seed 42 → identical to the a256 prep) -------------------
states = []
for pkl in sorted(PKL_DIR.glob("worker_*.pkl")):
    for g in load_game_records(pkl):
        for snap in g.decisions:
            states.append(snap.state)
random.seed(42)
common = random.sample(states, min(6000, len(states)))
print(f"common set: {len(common)} states", flush=True)

def measure(model):
    enc = ENC[str(getattr(model, "encoding_tag", "") or "")]
    x = torch.from_numpy(np.stack([enc(s, 0) for s in common]).astype(np.float32))
    model.eval()
    with torch.no_grad():
        v = float(model.predict_margin(x).cpu().numpy().std())
        try: o = float(model.predict_outcome(x).cpu().numpy().std())
        except Exception: o = 1.0
    return v, o

jobs = [  # (label, ckpt_dir, export_dir)
    ("b512_spatial", EVAL / "b512_spatial/best", EVAL / "cpp_export_b512_spatial"),
    ("b_wide",       EVAL / "b_wide/best",       EVAL / "cpp_export_b_wide"),
]
for label, ckpt, outdir in jobs:
    model = load_value_evaluator(str(ckpt))
    vs, os_ = measure(model)
    print(f"{label}: value_scale={vs:.4f} outcome_scale={os_:.4f}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/nn/export_weights.py"),
                    "--value-ckpt", str(ckpt) + ".pt", "--out-dir", str(outdir)],
                   check=True)
    mf = outdir / "weights_manifest.json"
    m = json.loads(mf.read_text())
    m["value_scale"] = vs; m.setdefault("value", {})["value_scale"] = vs
    m["outcome_scale"] = os_; m.setdefault("outcome", {})["outcome_scale"] = os_
    mf.write_text(json.dumps(m, indent=2))
    print(f"  patched {mf.name}: vs={vs:.4f} os={os_:.4f}", flush=True)
print("prep_eval_b512: done", flush=True)
