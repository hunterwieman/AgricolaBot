#!/usr/bin/env python
"""Rebuild the per-card triage spec files from the committed consolidated JSON.

The card-batch triage wrote one spec JSON per card to an ephemeral scratchpad dir
(`<scratchpad>/triage_cde/<DECK>_<num>.json`); `gen_impl.py` and the implement agents
read those. The consolidated, COMMITTED copy is `card_triage_cde_specs.json` (a list of
the same specs, each carrying its original filename in `_file`). If the scratchpad is
gone (new session / cleared /private/tmp), run this to recreate the per-card files in a
durable dir, then point `gen_impl.py` at it.

Usage:
    python scripts/card_batch/reconstruct_specs.py [scratchpad_dir]
        scratchpad_dir defaults to ./card_batch_work
    -> writes the per-card specs into <scratchpad_dir>/triage_cde/<DECK>_<num>.json
       (the exact layout gen_impl.py expects), so you can then run:
           python scripts/card_batch/gen_impl.py <scratchpad_dir> <DECK> <TIER|all>
"""
import json
import os
import sys

src = "card_triage_cde_specs.json"
scratch = sys.argv[1] if len(sys.argv) > 1 else "card_batch_work"
target = os.path.join(scratch, "triage_cde")
os.makedirs(target, exist_ok=True)
specs = json.load(open(src))
n = 0
for s in specs:
    fn = s.get("_file")
    if not fn:
        continue
    json.dump(s, open(os.path.join(target, fn), "w"))
    n += 1
print(f"reconstructed {n} per-card spec files into {target}/")
print(f"now run: python scripts/card_batch/gen_impl.py {scratch} <DECK> <TIER|all>")
