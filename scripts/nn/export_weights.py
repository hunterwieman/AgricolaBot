"""Export the value net + 9 policy heads to a raw-float32 weight format for the
hand-rolled C++ MLP (CPP_ENGINE_PLAN.md §6) — the libtorch-free replacement for
``export_torchscript.py``.

Why a custom format instead of TorchScript: the C++ NN forward is now a
hand-rolled MLP (plain matmul / LayerNorm / GELU) — no libtorch dispatcher
overhead, no libtorch dependency. This script dumps each model's parameters
losslessly (raw little-endian float32 binary blobs) plus a JSON manifest that
fully describes how to reconstruct the forward pass on the C++ side.

Format (written under ``nn_models/cpp_export/``):

- ``<model>.bin`` — one raw float32 blob per model, holding every layer tensor
  back-to-back in the order they appear in the manifest's ``layers`` list,
  followed by ``input_mean`` then ``input_std`` (and, value only, ``target_std``).
  Little-endian float32; no header, no padding. Lossless (the .pt is float32
  too, so this round-trips bit-exactly).
- ``weights_manifest.json`` — per model: ``file``, ``input_dim``, the ordered
  ``layers`` (each ``{"kind": "linear", "out": O, "in": I}`` with W[O,I] then
  b[O], or ``{"kind": "layernorm", "dim": D, "eps": 1e-5}`` with gamma[D] then
  beta[D]), plus ``input_mean`` / ``input_std`` lengths, ``num_classes``
  (fixed heads), ``candidate_dim`` (pointer heads), and ``value_scale`` /
  ``target_std`` (value). Also top-level ``encoding_version`` / ``encoded_dim``.

The blob layout per model is exactly:

    [layer0 tensor(s)] [layer1 tensor(s)] ... [input_mean] [input_std] (... [target_std])

The C++ ``Mlp`` reads the manifest, then mmaps/reads the blob sequentially in
that order. Because the manifest lists every tensor's shape, the reader needs no
key strings — it just consumes ``out*in + out`` floats per Linear, ``2*dim`` per
LayerNorm, then ``input_dim`` for mean, ``input_dim`` for std.

The inner network is a ``ConfigurableMLP``:
``[Linear -> LayerNorm -> GELU -> Dropout] x N -> Linear(out) -> Identity``.
We walk ``model.net`` (the ``nn.Sequential``) in order and emit a manifest entry
for each ``nn.Linear`` / ``nn.LayerNorm`` (GELU / Dropout / Identity carry no
parameters and are implicit in the C++ forward: every hidden block is
``gelu(layernorm(linear(x)))`` and the final layer is a bare ``linear``).

Run (from repo root):

    ~/miniconda3/bin/python scripts/nn/export_weights.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch import nn  # noqa: E402

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402
from agricola.agents.nn.policy import _load_head_model  # noqa: E402
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS  # noqa: E402
from scripts.nn.build_combined_policy import UNWEIGHTED_SET  # noqa: E402

OUT_DIR = ROOT / "nn_models" / "cpp_export"
VALUE_CKPT = ROOT / "nn_models" / "best"  # best.pt + best.meta.json

LAYERNORM_EPS = 1e-5  # torch.nn.LayerNorm default; matched in C++.


def _f32(t: torch.Tensor) -> np.ndarray:
    """A contiguous float32 numpy view of a (detached, CPU) tensor."""
    return t.detach().cpu().contiguous().numpy().astype(np.float32, copy=False)


def _walk_layers(net: nn.Module):
    """Yield (kind, module) for each parameterized layer of an MLP `net`, in
    forward order. GELU/Dropout/Identity carry no parameters and are skipped —
    the C++ forward applies GELU after every hidden LayerNorm by construction."""
    # ConfigurableMLP wraps its layers in `self.net = nn.Sequential(...)`.
    seq = net.net if isinstance(net, nn.Module) and hasattr(net, "net") else net
    for m in seq:
        if isinstance(m, nn.Linear):
            yield ("linear", m)
        elif isinstance(m, nn.LayerNorm):
            yield ("layernorm", m)
        elif isinstance(m, (nn.GELU, nn.Dropout, nn.Identity)):
            continue
        else:
            raise ValueError(
                f"export_weights: unexpected layer {type(m).__name__} in net; "
                f"the hand-rolled C++ MLP only handles Linear/LayerNorm/GELU/"
                f"Dropout/Identity. Update mlp.cpp + this exporter together."
            )


def _verify_gelu(net: nn.Module) -> None:
    """Confirm GELU is the EXACT erf form (not the tanh approximation) — the C++
    side uses std::erf, so a tanh-approx GELU here would silently diverge."""
    seq = net.net if hasattr(net, "net") else net
    for m in seq:
        if isinstance(m, nn.GELU):
            approx = getattr(m, "approximate", "none")
            if approx not in ("none", None):
                raise ValueError(
                    f"export_weights: GELU.approximate={approx!r}; the C++ MLP "
                    f"implements the exact erf form only. Re-train or extend "
                    f"mlp.cpp for the tanh approximation."
                )


def _export_model(
    inner_net: nn.Module,
    input_mean: torch.Tensor,
    input_std: torch.Tensor,
    *,
    file_stem: str,
    extra_tail: list[tuple[str, np.ndarray]] | None = None,
) -> dict:
    """Write `<file_stem>.bin` and return its manifest entry.

    Blob layout: each layer's tensors (Linear: W then b; LayerNorm: gamma then
    beta) in forward order, then input_mean, input_std, then any `extra_tail`
    arrays (value: target_std). All raw little-endian float32, concatenated.
    """
    _verify_gelu(inner_net)

    layers: list[dict] = []
    blob_parts: list[np.ndarray] = []
    for kind, m in _walk_layers(inner_net):
        if kind == "linear":
            w = _f32(m.weight)  # [out, in]
            b = _f32(m.bias)    # [out]
            out_dim, in_dim = w.shape
            assert b.shape == (out_dim,)
            layers.append({"kind": "linear", "out": int(out_dim), "in": int(in_dim)})
            blob_parts.append(w.reshape(-1))  # row-major [out, in]
            blob_parts.append(b.reshape(-1))
        else:  # layernorm
            g = _f32(m.weight)  # gamma [dim]
            be = _f32(m.bias)   # beta  [dim]
            dim = g.shape[0]
            assert be.shape == (dim,)
            layers.append({"kind": "layernorm", "dim": int(dim), "eps": LAYERNORM_EPS})
            blob_parts.append(g.reshape(-1))
            blob_parts.append(be.reshape(-1))

    im = _f32(input_mean).reshape(-1)
    isd = _f32(input_std).reshape(-1)
    assert im.shape == isd.shape, (im.shape, isd.shape)
    blob_parts.append(im)
    blob_parts.append(isd)

    tail_meta: dict = {}
    if extra_tail:
        for name, arr in extra_tail:
            a = arr.astype(np.float32, copy=False).reshape(-1)
            blob_parts.append(a)
            tail_meta[name] = int(a.shape[0])

    blob = np.concatenate(blob_parts).astype("<f4", copy=False)  # little-endian f32
    fname = f"{file_stem}.bin"
    (OUT_DIR / fname).write_bytes(blob.tobytes())

    entry: dict = {
        "file": fname,
        "input_dim": int(im.shape[0]),
        "layers": layers,
        "input_mean_len": int(im.shape[0]),
        "input_std_len": int(isd.shape[0]),
        "blob_floats": int(blob.shape[0]),
    }
    entry.update(tail_meta)
    return entry


# Fixed filename per head (the C++ loader maps head name -> file via manifest).
_FIXED_STEMS = {
    "placement": "placement",
    "choose_subaction": "choose_subaction",
    "commit_build_major": "commit_build_major",
    "commit_sow": "commit_sow",
    "commit_bake": "commit_bake",
    "fencing": "fencing",
    "build_stop": "build_stop",
}
_POINTER_STEMS = {
    "animal_frontier": "animal_frontier",
    "harvest_feed": "harvest_feed",
}


def _is_shared_trunk(ckpt: Path) -> bool:
    """True if `ckpt` is a SharedTrunkModel checkpoint (meta model_kind)."""
    try:
        meta = json.loads(Path(ckpt).with_suffix(".meta.json").read_text())
        return meta.get("model_kind") == "shared_trunk"
    except Exception:
        return False


def _export_joint(ckpt: Path) -> int:
    """Export a SharedTrunkModel to the `shared_trunk` manifest format: ONE trunk
    blob (real 170-input norm → embedding), a standalone embed_norm LayerNorm, and
    head blobs that take the embedding with IDENTITY input-norm (pointer heads bake
    the candidate-norm into the cand slice). The C++ joint path runs the trunk once
    and feeds every head off the cached embedding (one forward per node)."""
    from agricola.agents.nn.shared_model import SharedTrunkModel

    model = SharedTrunkModel.load(str(ckpt))
    model.eval()
    E = int(model.embedding_dim)
    ident_m, ident_s = torch.zeros(E), torch.ones(E)

    manifest: dict = {
        "encoding_version": ENCODING_VERSION,
        "encoded_dim": ENCODED_DIM,
        "format": "shared_trunk_v1",
        "embedding_dim": E,
        "layernorm_eps": LAYERNORM_EPS,
        "fixed_heads": {},
        "pointer_heads": {},
    }

    # Trunk: real 170-input norm + trunk layers → RAW embedding (pre embed_norm).
    manifest["trunk"] = _export_model(
        model.trunk, model.input_mean, model.input_std, file_stem="trunk")

    # embed_norm: standalone LayerNorm applied to the trunk output (NO GELU).
    if isinstance(model.embed_norm, torch.nn.LayerNorm):
        en = model.embed_norm
        blob = np.concatenate(
            [_f32(en.weight).reshape(-1), _f32(en.bias).reshape(-1)]).astype("<f4")
        (OUT_DIR / "embed_norm.bin").write_bytes(blob.tobytes())
        manifest["embed_norm"] = {"file": "embed_norm.bin", "dim": E,
                                  "eps": LAYERNORM_EPS}
    else:
        manifest["embed_norm"] = None

    # Value head: identity input-norm + Linear(E→1) + target_std (denorm).
    manifest["value"] = _export_model(
        model.value_head, ident_m, ident_s, file_stem="value",
        extra_tail=[("target_std", _f32(model.target_std).reshape(-1))])
    manifest["value"]["value_scale"] = float(getattr(model, "value_scale", 1.0))

    # Fixed heads: identity input-norm + Linear(E→K), keyed by head name.
    for name, head in model.fixed_heads.items():
        manifest["fixed_heads"][name] = _export_model(
            head, ident_m, ident_s, file_stem=f"fixed_{name}")

    # Pointer heads: input [E ; cand_dim] — identity over E, the head's fitted
    # cand_mean/std over the cand slice (so the C++ normalizes only the candidate).
    for name, head in model.pointer_heads.items():
        cm = getattr(model, f"cand_mean__{name}").detach().cpu()
        cs = getattr(model, f"cand_std__{name}").detach().cpu()
        in_mean = torch.cat([ident_m, cm])
        in_std = torch.cat([ident_s, cs])
        entry = _export_model(head, in_mean, in_std, file_stem=f"pointer_{name}")
        entry["candidate_dim"] = int(cm.shape[0])
        manifest["pointer_heads"][name] = entry

    with (OUT_DIR / "weights_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nOK — wrote shared-trunk export (trunk + value + "
          f"{len(manifest['fixed_heads'])} fixed + {len(manifest['pointer_heads'])} "
          f"pointer heads) to {OUT_DIR}")
    return 0


def main() -> int:
    import argparse
    global OUT_DIR, VALUE_CKPT
    ap = argparse.ArgumentParser(description=__doc__ or "export NN weights for C++")
    ap.add_argument("--value-ckpt", type=str, default=None,
                    help="value-net checkpoint base path (default nn_models/best). "
                         "Exported alongside the unweighted policy heads, so each "
                         "export dir is a complete {value + 9 heads} bundle.")
    ap.add_argument("--out-dir", type=str, default=None,
                    help="output dir for the blob bundle (default nn_models/cpp_export).")
    args = ap.parse_args()
    if args.value_ckpt:
        VALUE_CKPT = Path(args.value_ckpt)
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Route a SharedTrunkModel checkpoint to the shared-trunk export format.
    if _is_shared_trunk(VALUE_CKPT):
        return _export_joint(VALUE_CKPT)
    manifest: dict = {
        "encoding_version": ENCODING_VERSION,
        "encoded_dim": ENCODED_DIM,
        "format": "raw_f32_v1",
        "layernorm_eps": LAYERNORM_EPS,
        "value": {},
        "fixed_heads": {},
        "pointer_heads": {},
    }
    written: list[str] = []

    # --- value -------------------------------------------------------------
    value = NormalizedValueModel.load(str(VALUE_CKPT))
    value.eval()
    target_std = _f32(value.target_std).reshape(-1)  # scalar buffer -> [1]
    entry = _export_model(
        value.net,
        value.input_mean,
        value.input_std,
        file_stem="value",
        extra_tail=[("target_std", target_std)],
    )
    entry["value_scale"] = float(value.value_scale)
    manifest["value"] = entry
    written.append(str(OUT_DIR / entry["file"]))
    print(
        f"wrote {OUT_DIR / entry['file']}  (value, {len(entry['layers'])} layers, "
        f"target_std={float(target_std[0]):.6f}, value_scale={value.value_scale:.6f})"
    )

    # --- the 9 policy heads (unweighted set) -------------------------------
    for ckpt in UNWEIGHTED_SET:
        model = _load_head_model(ckpt)
        model.eval()
        name = model.head_name
        if name in HEADS:
            head = HEADS[name]
            stem = _FIXED_STEMS[name]
            entry = _export_model(
                model.net, model.input_mean, model.input_std, file_stem=stem
            )
            entry["num_classes"] = int(head.num_classes)
            manifest["fixed_heads"][name] = entry
            written.append(str(OUT_DIR / entry["file"]))
            print(
                f"wrote {OUT_DIR / entry['file']}  (fixed head '{name}', "
                f"{head.num_classes} classes, {len(entry['layers'])} layers)"
            )
        elif name in POINTER_HEADS:
            head = POINTER_HEADS[name]
            stem = _POINTER_STEMS[name]
            cdim = int(head.candidate_dim)
            entry = _export_model(
                model.net, model.input_mean, model.input_std, file_stem=stem
            )
            entry["candidate_dim"] = cdim
            # input_dim spans state + candidate (ENCODED_DIM + candidate_dim).
            assert entry["input_dim"] == ENCODED_DIM + cdim, (
                entry["input_dim"], ENCODED_DIM, cdim,
            )
            manifest["pointer_heads"][name] = entry
            written.append(str(OUT_DIR / entry["file"]))
            print(
                f"wrote {OUT_DIR / entry['file']}  (pointer head '{name}', "
                f"candidate_dim={cdim}, {len(entry['layers'])} layers)"
            )
        else:
            raise ValueError(
                f"checkpoint {ckpt} has unknown head_name {name!r}; "
                f"expected one of {sorted(HEADS) + sorted(POINTER_HEADS)}"
            )

    # --- manifest ----------------------------------------------------------
    mpath = OUT_DIR / "weights_manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2))
    written.append(str(mpath))
    print(f"wrote {mpath}")

    expected_bins = (
        ["value.bin"]
        + [f"{s}.bin" for s in _FIXED_STEMS.values()]
        + [f"{s}.bin" for s in _POINTER_STEMS.values()]
        + ["weights_manifest.json"]
    )
    missing = [e for e in expected_bins if not (OUT_DIR / e).exists()]
    if missing:
        print(f"ERROR: missing exports: {missing}", file=sys.stderr)
        return 1
    print(f"\nOK — wrote {len(written)} files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
