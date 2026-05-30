"""Evaluate a trained NN value function against the 8-config ensemble.

For each opponent in `tuned_configs/DATA_GEN_ENSEMBLE.md`, plays
`--n-games` total — half with NN as P0 and half with NN as P1 — to
control for the starting-player asymmetry. Reports per-matchup
W-D-L + avg NN-margin and an aggregate at the end.

NN and opponents both use `restricted_legal_actions` (matches the
training-pipeline convention used to generate the data the NN was
trained on).

CLI:
    python scripts/eval_nn_vs_ensemble.py \\
        --checkpoint nn_models/<run-id>/best \\
        --n-games 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (  # noqa: E402
    CONFIG_V1_T2,
    HeuristicConfig,
    HeuristicConfigV3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    restricted_legal_actions,
)
from agricola.agents.nn.agent import NNAgent  # noqa: E402
from agricola.agents.nn.model import NormalizedValueModel  # noqa: E402
from scripts.play_match import play_match  # noqa: E402


# DATA_GEN_ENSEMBLE.md order — same configs used to generate training data
ENSEMBLE: list[tuple[str, str]] = [
    ("t2", "v1"),
    ("tuned_configs/alphas_gen_7.json", "v3"),
    ("tuned_configs/alphas_gen_1.json", "v3"),
    ("tuned_configs/panel_wood_r1.json", "v3"),
    ("tuned_configs/panel_gen16.json", "v3"),
    ("tuned_configs/panel_gen47_wood020.json", "v3"),
    ("tuned_configs/panel_gen_25.json", "v3"),
    ("tuned_configs/panel_gen47.json", "v3"),
]


def _load_config(spec: str, arch: str):
    if spec == "t2":
        return CONFIG_V1_T2
    path = ROOT / spec
    with path.open("r") as f:
        data = json.load(f)
    cfg_dict = data["best_config"]
    return HeuristicConfigV3(**cfg_dict) if arch == "v3" else HeuristicConfig(**cfg_dict)


def _opp_factory(spec: str, arch: str):
    cfg = _load_config(spec, arch)
    cls = HubrisHeuristicV1 if arch == "v1" else HubrisHeuristicV3

    def factory(seed: int):
        return cls(
            seed=seed, temperature=0.0, lookahead="turn",
            config=cfg, legal_actions_fn=restricted_legal_actions,
        )
    return factory


def _nn_factory(model: NormalizedValueModel, differential: bool):
    def factory(seed: int):
        return NNAgent(
            model, differential=differential, seed=seed,
            lookahead="turn", legal_actions_fn=restricted_legal_actions,
        )
    return factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", type=Path, required=True,
                        help="Path prefix to the trained model (the .pt / .meta.json pair)")
    parser.add_argument("--n-games", type=int, default=100,
                        help="Total games per opponent (split 50/50 P0/P1)")
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--differential", action="store_true", default=True,
                        help="Use the D inference wrapper (default ON)")
    parser.add_argument("--no-differential", action="store_false",
                        dest="differential")
    args = parser.parse_args()

    print(f"Loading NN from {args.checkpoint}...")
    model = NormalizedValueModel.load(args.checkpoint)
    nn_fac = _nn_factory(model, args.differential)
    print(f"Differential wrapper: {'ON' if args.differential else 'OFF'}")
    print()

    n_half = args.n_games // 2
    seeds_p0 = list(range(args.base_seed, args.base_seed + n_half))
    seeds_p1 = list(range(args.base_seed + n_half,
                            args.base_seed + 2 * n_half))

    print(f"Running NN vs {len(ENSEMBLE)} opponents, "
           f"{2 * n_half} games each ({n_half} as P0, {n_half} as P1).")
    print(f"NN+heuristic both with lookahead='turn', restricted_legal_actions ON.")
    print()
    print(f"{'opponent':<32} | {'NN-P0 (W-D-L  margin)':>22} | "
          f"{'NN-P1 (W-D-L  margin)':>22} | "
          f"{'total (W-D-L  margin)':>22} | time(s)")
    print("-" * 132)

    overall_wins = 0
    overall_draws = 0
    overall_losses = 0
    overall_margin_sum = 0.0
    t_start = time.perf_counter()

    for spec, arch in ENSEMBLE:
        opp_fac = _opp_factory(spec, arch)
        t_op = time.perf_counter()

        # NN as P0
        r0 = play_match(nn_fac, opp_fac, seeds_p0)
        nn_w0, nn_l0, d0 = r0.p0_wins, r0.p1_wins, r0.draws
        m0 = r0.avg_margin

        # NN as P1 (swap factories; negate avg_margin so it's NN's margin)
        r1 = play_match(opp_fac, nn_fac, seeds_p1)
        nn_w1, nn_l1, d1 = r1.p1_wins, r1.p0_wins, r1.draws
        m1 = -r1.avg_margin

        tot_w = nn_w0 + nn_w1
        tot_l = nn_l0 + nn_l1
        tot_d = d0 + d1
        tot_margin = (m0 + m1) / 2.0
        t_op_elapsed = time.perf_counter() - t_op

        overall_wins += tot_w
        overall_losses += tot_l
        overall_draws += tot_d
        overall_margin_sum += tot_margin

        spec_short = spec.replace("tuned_configs/", "").replace(".json", "")
        print(
            f"{spec_short:<32} | "
            f"{nn_w0:>2}-{d0:>2}-{nn_l0:>2}  {m0:+6.2f}    | "
            f"{nn_w1:>2}-{d1:>2}-{nn_l1:>2}  {m1:+6.2f}    | "
            f"{tot_w:>3}-{tot_d:>2}-{tot_l:>3}  {tot_margin:+6.2f}    | "
            f"{t_op_elapsed:>6.1f}",
            flush=True,
        )

    total_games = overall_wins + overall_draws + overall_losses
    total_elapsed = time.perf_counter() - t_start
    print()
    print(
        f"Aggregate: {overall_wins}-{overall_draws}-{overall_losses} "
        f"({overall_wins / total_games * 100:.1f}% win rate)  "
        f"avg margin: {overall_margin_sum / len(ENSEMBLE):+.2f}  "
        f"({total_games} games, {total_elapsed:.0f}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
