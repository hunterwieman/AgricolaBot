"""Monkey-patch dataclasses.replace to count (class, changed-field-set) tuples.

Runs Workload B (random play from the wealthy prefab, 10 seeds) and prints
the most-frequent (class, fields) call sites, so we can see which dataclass
mutations actually dominate.

Read-only on agricola/ — only patches the stdlib dataclasses module for
the duration of this script.
"""
from __future__ import annotations

import dataclasses
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---- Monkey-patch BEFORE importing anything that uses replace
_orig_dc_replace = dataclasses.replace
_counts: Counter = Counter()


def _counting_dc_replace(obj, /, **changes):
    key = (type(obj).__name__, tuple(sorted(changes.keys())))
    _counts[key] += 1
    return _orig_dc_replace(obj, **changes)


dataclasses.replace = _counting_dc_replace

# Also instrument fast_replace so post-migration call sites are captured
import agricola.replace as _replace_mod  # noqa: E402

_orig_fast_replace = _replace_mod.fast_replace


def _counting_fast_replace(obj, /, **changes):
    key = (type(obj).__name__, tuple(sorted(changes.keys())))
    _counts[key] += 1
    return _orig_fast_replace(obj, **changes)


_replace_mod.fast_replace = _counting_fast_replace

# ---- Now import & run
from agricola.setup import setup  # noqa: E402

from tests.test_utils import random_agent_play  # noqa: E402

from scripts.profile_states import STATES  # noqa: E402


def main():
    total_actions = 0
    for seed in range(10):
        s = STATES["early_round_3_wealthy"]()
        _terminal, trace = random_agent_play(s, seed=seed)
        total_actions += len(trace)

    print(f"Workload B: {total_actions} actions across 10 seeds\n")
    grand_total = sum(_counts.values())
    print(f"dataclasses.replace total calls: {grand_total}\n")

    # Aggregate by class
    by_class: Counter = Counter()
    for (cls, fields), n in _counts.items():
        by_class[cls] += n
    print("By class (total calls):")
    for cls, n in by_class.most_common():
        pct = 100 * n / grand_total
        print(f"  {cls:<22} {n:>8}  ({pct:.1f}%)")
    print()

    # Show top (class, fields) shapes
    print("Top 20 (class, fields-changed) shapes:")
    print(f"  {'count':>8}  {'pct':>5}  class.fields")
    for (cls, fields), n in _counts.most_common(20):
        pct = 100 * n / grand_total
        field_str = ",".join(fields)
        print(f"  {n:>8}  {pct:>4.1f}%  {cls}.{{{field_str}}}")


if __name__ == "__main__":
    main()
