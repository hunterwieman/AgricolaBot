#!/usr/bin/env python
"""Reconcile the two places a "won't-fix" decision is recorded, and report any drift.

A card being ruled won't-fix is tracked in two independent spots:

  1. The catalog JSON (`agricola/cards/data/revised_*.json`), via `"status": "wontfix"`.
     This is the field the unimplemented-card listers read, so it decides what shows up
     on the reference pages.
  2. The progress ledger (`CARD_IMPLEMENTATION_PROGRESS.md`), via a `🚫` marker on the
     card's entry. This is the human-facing record of what was decided and why.

Nothing links the two, so a decision recorded in one can silently miss the other:
  * 🚫 in the ledger but not `wontfix` in the JSON  → the card is falsely listed as
    "not yet implemented" on the reference pages.
  * `wontfix` in the JSON but no 🚫 in the ledger    → the ledger is a stale record.

This script surfaces both directions for minors and occupations. It only reports; it
changes nothing. Exit code is 0 when the two sources agree, 1 when any drift is found
(so it can gate a commit hook if you ever want that).

    python scripts/reconcile_wontfix.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "agricola" / "cards" / "data"
_LEDGER = _ROOT / "CARD_IMPLEMENTATION_PROGRESS.md"

# Which JSON backs each ledger Part, in file order. The `# Part — <name>` headers split
# the ledger; every 🚫 entry between two headers belongs to that Part's catalog.
_PARTS = [
    ("Minors", "revised_minor_improvements.json"),
    ("Occupations", "revised_occupations.json"),
]

_PART_RE = re.compile(r"^#\s*Part\s*[—-]\s*(\w+)", re.IGNORECASE)
_ENTRY_RE = re.compile(r"^\s*-\s*🚫\s*\*\*([A-E])(\d+)\s+(.+?)\*\*")


def _ledger_wontfix() -> dict[str, dict[str, str]]:
    """Map part-name -> {"<DECK><NUM>": name} for every 🚫-marked ledger entry."""
    out: dict[str, dict[str, str]] = {name: {} for name, _ in _PARTS}
    current: str | None = None
    for line in _LEDGER.read_text().splitlines():
        mp = _PART_RE.match(line)
        if mp:
            # normalise to one of our known part names (Minors / Occupations)
            hit = next((n for n, _ in _PARTS if n.lower() == mp.group(1).lower()), None)
            current = hit
            continue
        me = _ENTRY_RE.match(line)
        if me and current:
            out[current][f"{me.group(1)}{me.group(2)}"] = me.group(3).strip()
    return out


def _json_rows(filename: str) -> dict[str, dict]:
    """Map '<DECK><NUM>' -> catalog row for one JSON file."""
    rows = json.loads((_DATA_DIR / filename).read_text())
    return {f"{r['deck']}{r['number']}": r for r in rows}


def main() -> None:
    ledger = _ledger_wontfix()
    any_drift = False

    for part_name, filename in _PARTS:
        rows = _json_rows(filename)
        json_wf = {cid for cid, r in rows.items() if r.get("status") == "wontfix"}
        ledger_wf = set(ledger[part_name])

        missing_in_json = sorted(ledger_wf - json_wf)   # 🚫 in ledger, not wontfix in JSON
        missing_in_ledger = sorted(json_wf - ledger_wf)  # wontfix in JSON, no 🚫 in ledger
        # name mismatches for ids both sides agree are wontfix (parse/typo guard)
        name_mismatch = [
            cid for cid in sorted(ledger_wf & json_wf)
            if cid in rows and rows[cid]["name"].strip() != ledger[part_name][cid]
        ]

        print(f"\n=== {part_name} ===")
        print(f"  ledger 🚫: {len(ledger_wf)}   |   JSON wontfix: {len(json_wf)}")

        if not missing_in_json and not missing_in_ledger and not name_mismatch:
            print("  ✓ in sync")
            continue
        any_drift = True

        if missing_in_json:
            print("  ⚠ ruled 🚫 in the ledger but NOT wontfix in the catalog JSON")
            print("    (these are falsely listed as 'not yet implemented'):")
            for cid in missing_in_json:
                nm = ledger[part_name][cid]
                st = rows[cid].get("status", "<no such catalog row>") if cid in rows else "<no such catalog row>"
                print(f"      {cid}  {nm}   (JSON status: {st})")

        if missing_in_ledger:
            print("  ⚠ wontfix in the catalog JSON but NO 🚫 in the ledger (stale ledger):")
            for cid in missing_in_ledger:
                print(f"      {cid}  {rows[cid]['name']}")

        if name_mismatch:
            print("  ⚠ name mismatch between ledger and JSON for the same id (check parse/typo):")
            for cid in name_mismatch:
                print(f"      {cid}  ledger={ledger[part_name][cid]!r}  json={rows[cid]['name']!r}")

    print()
    if any_drift:
        print("Drift found — the two won't-fix records disagree (see above).")
        sys.exit(1)
    print("All won't-fix records agree across the ledger and the catalog JSON.")


if __name__ == "__main__":
    main()
