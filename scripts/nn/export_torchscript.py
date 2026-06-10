"""Export the value net + 9 policy heads to TorchScript for the C++ engine.

The C++ side (Stage 5, CPP_ENGINE_PLAN.md §6) loads these `.ts` files via
libtorch and does NO normalization itself — every model is traced with all
input/output normalization baked into the graph (the .ts contract):

- **value** -> ``value.ts``: ``forward(x: float32[170]) -> float32 scalar`` =
  ``predict_margin`` (input-norm + net + x target_std). Input is the RAW
  (unnormalized) 170-feature encoding.
- **7 fixed heads** -> ``<head>.ts``: ``forward(x: float32[170]) ->
  float32[num_classes]`` = raw logits (input-norm + net; NO mask, NO softmax).
  The C++ side applies the legal mask (illegal -> -inf) + softmax.
- **2 pointer heads** -> ``<head>.ts``: ``forward(rows: float32[K, 170+D]) ->
  float32[K]`` = per-candidate raw scores (norm over the FULL [state;cand] row
  baked in). The C++ side softmaxes over K. Traced with an example batch so the
  leading dim is dynamic.

All models are ``.eval()`` before tracing (dropout OFF — leaving it on makes the
priors nondeterministic). Output: ``nn_models/cpp_export/*.ts`` + a
``manifest.json`` (head -> file, candidate_dim, num_classes, encoding_version)
for a C++-side sanity / version check.

The trace approach mirrors ``scripts/proto_jit_trace.py`` (already verified
numerically exact for these models). We trace the *wrapper* (with normalization),
not just the inner ``net``, so the C++ side never reimplements the norm math.

Run (from repo root):

    ~/miniconda3/bin/python scripts/nn/export_torchscript.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
from torch import nn  # noqa: E402

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402
from agricola.agents.nn.policy import _load_head_model  # noqa: E402
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS  # noqa: E402
from scripts.nn.build_combined_policy import UNWEIGHTED_SET  # noqa: E402

OUT_DIR = ROOT / "nn_models" / "cpp_export"
VALUE_CKPT = ROOT / "nn_models" / "best"  # best.pt + best.meta.json


# ---------------------------------------------------------------------------
# Trace wrappers — each bakes its model's normalization into the graph so the
# .ts forward consumes RAW features and emits the contracted output.
# ---------------------------------------------------------------------------


class _ValueTrace(nn.Module):
    """forward(x: [N,170]) -> [N] = predict_margin (input-norm + net + xtarget_std)."""

    def __init__(self, model: NormalizedValueModel):
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model.predict_margin(x)


class _FixedHeadTrace(nn.Module):
    """forward(x: [N,170]) -> [N,C] = raw logits (input-norm + net; NO mask/softmax)."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # NormalizedPolicyModel.forward already normalizes + runs the net,
        # returning raw logits. No mask, no softmax (C++ does both).
        return self.model.forward(x)


class _PointerHeadTrace(nn.Module):
    """forward(rows: [K, 170+D]) -> [K] = per-candidate raw scores.

    The pointer model normalizes the FULL [state;cand] row (input_mean/std span
    both parts) then scores each row to a scalar. ``_score_rows`` does exactly
    this. C++ builds the [K, 170+D] rows (state broadcast + candidate features)
    and softmaxes over K.
    """

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, rows: torch.Tensor) -> torch.Tensor:
        return self.model._score_rows(rows)


# Fixed filename per head (the C++ loader expects these exact names).
_FIXED_FILES = {
    "placement": "placement.ts",
    "choose_subaction": "choose_subaction.ts",
    "commit_build_major": "commit_build_major.ts",
    "commit_sow": "commit_sow.ts",
    "commit_bake": "commit_bake.ts",
    "fencing": "fencing.ts",
    "build_stop": "build_stop.ts",
}
_POINTER_FILES = {
    "animal_frontier": "animal_frontier.ts",
    "harvest_feed": "harvest_feed.ts",
}


def _save_traced(wrapper: nn.Module, example: torch.Tensor, path: Path) -> None:
    wrapper.eval()
    with torch.no_grad():
        traced = torch.jit.trace(wrapper, example)
    traced.save(str(path))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "encoding_version": ENCODING_VERSION,
        "encoded_dim": ENCODED_DIM,
        "value": {"file": "value.ts"},
        "fixed_heads": {},
        "pointer_heads": {},
    }
    written: list[str] = []

    # --- value -------------------------------------------------------------
    value = NormalizedValueModel.load(str(VALUE_CKPT))
    value.eval()
    vfile = OUT_DIR / "value.ts"
    _save_traced(_ValueTrace(value), torch.randn(2, ENCODED_DIM), vfile)
    manifest["value"]["value_scale"] = float(value.value_scale)
    written.append(str(vfile))
    print(f"wrote {vfile}  (value, value_scale={value.value_scale:.6f})")

    # --- the 9 policy heads (unweighted set) -------------------------------
    for ckpt in UNWEIGHTED_SET:
        model = _load_head_model(ckpt)
        model.eval()
        name = model.head_name
        if name in HEADS:
            head = HEADS[name]
            fname = _FIXED_FILES[name]
            path = OUT_DIR / fname
            _save_traced(_FixedHeadTrace(model), torch.randn(2, ENCODED_DIM), path)
            manifest["fixed_heads"][name] = {
                "file": fname,
                "num_classes": int(head.num_classes),
            }
            written.append(str(path))
            print(f"wrote {path}  (fixed head '{name}', {head.num_classes} classes)")
        elif name in POINTER_HEADS:
            head = POINTER_HEADS[name]
            fname = _POINTER_FILES[name]
            path = OUT_DIR / fname
            cdim = int(head.candidate_dim)
            example = torch.randn(3, ENCODED_DIM + cdim)
            _save_traced(_PointerHeadTrace(model), example, path)
            manifest["pointer_heads"][name] = {
                "file": fname,
                "candidate_dim": cdim,
            }
            written.append(str(path))
            print(f"wrote {path}  (pointer head '{name}', candidate_dim={cdim})")
        else:
            raise ValueError(
                f"checkpoint {ckpt} has unknown head_name {name!r}; "
                f"expected one of {sorted(HEADS) + sorted(POINTER_HEADS)}"
            )

    # --- manifest ----------------------------------------------------------
    mpath = OUT_DIR / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2))
    written.append(str(mpath))
    print(f"wrote {mpath}")

    # Sanity: all 10 .ts + manifest present.
    expected = (
        ["value.ts"]
        + list(_FIXED_FILES.values())
        + list(_POINTER_FILES.values())
        + ["manifest.json"]
    )
    missing = [e for e in expected if not (OUT_DIR / e).exists()]
    if missing:
        print(f"ERROR: missing exports: {missing}", file=sys.stderr)
        return 1
    print(f"\nOK — wrote {len(written)} files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
