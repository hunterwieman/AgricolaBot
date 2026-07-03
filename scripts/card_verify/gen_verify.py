#!/usr/bin/env python
"""Generate the implemented-card audit workflow (.js) + a sidecar batches JSON.

For every IMPLEMENTED card (slug registered in MINORS/OCCUPATIONS, with the known
Market Stall B8/C54 name-collision fix), builds an audit work item: verbatim text
(+errata/clarifications), printed facts, the classification tags + note from
CARD_IMPLEMENTATION_PROGRESS.md, the card-module file(s), and the test files that
mention the slug. Tiers cards into trivial (Opus low, bigger batches) vs complex
(Opus medium, smaller batches), grouped by mechanic family so siblings are audited
together. The verifier instructions (VERIFIER_PROMPT.md, same dir) are inlined once.

Usage (repo root):
  ~/miniconda3/bin/python scripts/card_verify/gen_verify.py
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "card_classify"))
os.chdir(ROOT)
from gen_classify import load  # noqa: E402  (registry-live implemented flag + text assembly)

IMPL_FIX = {"C54": False}  # Market Stall name collision: B8 is the implemented one

# Tags that alone make a card "trivial" (Opus low). Anything else -> "complex" (Opus medium).
TRIVIAL_TAGS = {"ONPLAY", "PASSIVE", "E-GOODS", "E-SCORE", "E-SCORECMP", "E-SCOREGRP",
                "E-SCOREOPT", "E-PASSING", "NONE"}

# Mechanic-family assignment: first matching rule wins (order matters).
FAMILY_RULES = [
    ("costmod", {"E-COSTMOD", "E-FREEFENCE", "E-ALTCOST", "E-PIECECOST"}),
    ("harvest", {"S-HFEED", "S-HFIELD", "S-AFTERFEED", "S-HSTART", "S-HBREED", "E-BREEDMOD"}),
    ("sched", {"E-SCHED", "E-SCHEDANIMAL"}),
    ("start_of_round", {"S-SOR"}),
    ("latch", {"LATCH"}),
    ("space_hook", {"S-SPACE"}),
    ("sub_hook", {"S-SUB", "S-MAJMIN", "S-PLAY", "S-OBTAIN"}),
    ("animals_capacity", {"E-ANIMALS", "E-CAPGROW", "E-CAPNEW", "E-CAPNEG"}),
    ("people", {"E-GROWTH", "E-PEOPLE", "E-EXTRAPLACE", "E-WORKERMANIP", "E-NOPLACE"}),
]


def doc_tags():
    """id -> (codes, note) parsed from CARD_IMPLEMENTATION_PROGRESS.md."""
    out, cid = {}, None
    hdr = re.compile(r"^- (?:✅|🚫|⬜) \*\*([A-E]\d+) ")
    for ln in open(os.path.join(ROOT, "CARD_IMPLEMENTATION_PROGRESS.md")):
        m = hdr.match(ln)
        if m:
            cid = m.group(1)
            continue
        if cid and ln.startswith("  - `"):
            m2 = re.match(r"  - `([^`]*)`(?: — (.*))?", ln.rstrip("\n"))
            out[cid] = (m2.group(1).split(), (m2.group(2) or "").strip())
            cid = None
    return out


def build_file_index():
    """quoted-slug -> files, for card modules and tests."""
    def scan(pattern):
        idx = {}
        for path in sorted(glob.glob(pattern)):
            if "__pycache__" in path or path.endswith("__init__.py"):
                continue
            src = open(path, encoding="utf-8").read()
            idx[os.path.relpath(path, ROOT)] = src
        return idx
    return scan(os.path.join(ROOT, "agricola", "cards", "*.py")), \
        scan(os.path.join(ROOT, "tests", "*.py"))


def files_mentioning(slug, index):
    # match the slug as a whole token: quoted ("rammed_clay"), imported
    # (cards.rammed_clay), or used as an identifier stem (rammed_clay_setup)
    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(slug) + r"(?![A-Za-z0-9])")
    return [p for p, src in index.items() if pat.search(src)]


def family_of(tags):
    ts = set(tags)
    if ts <= TRIVIAL_TAGS:
        return "trivial"
    for name, marks in FAMILY_RULES:
        if ts & marks:
            return name
    return "misc"


def main():
    tags = doc_tags()
    card_files, test_files = build_file_index()

    items = []
    for kind in ("minor", "occupation"):
        for c in load(kind):
            implemented = IMPL_FIX.get(c["id"], c["implemented"])
            if not implemented or c.get("status") == "wontfix":
                continue
            codes, note = tags.get(c["id"], ([], ""))
            mods = files_mentioning(c["slug"], card_files)
            expected = os.path.join("agricola", "cards", c["slug"] + ".py")
            if expected in mods:  # put the card's own module first
                mods = [expected] + [m for m in mods if m != expected]
            items.append({
                "id": c["id"], "name": c["name"], "slug": c["slug"], "kind": kind,
                "players": c.get("players"), "cost": c.get("cost"), "prereq": c.get("prereq"),
                "vps": c.get("vps", 0), "passing": c["passing"], "text": c["text"],
                "tags": codes, "tag_note": note,
                "module_files": mods,
                "test_files": files_mentioning(c["slug"], test_files),
                "family": family_of(codes),
            })

    # group by family, then batch: trivial -> 8 @ low, everything else -> 4 @ medium
    by_family = {}
    for it in items:
        by_family.setdefault(it["family"], []).append(it)
    batches = []
    for fam in sorted(by_family):
        group = sorted(by_family[fam], key=lambda x: (x["kind"], x["id"]))
        size, effort = (8, "low") if fam == "trivial" else (4, "medium")
        for i in range(0, len(group), size):
            chunk = group[i:i + size]
            batches.append({
                "label": f"{fam}-{i // size + 1}",
                "effort": effort,
                "cards": [{k: v for k, v in it.items() if k != "family"} for it in chunk],
            })

    prompt = open(os.path.join(HERE, "VERIFIER_PROMPT.md"), encoding="utf-8").read()
    preamble = (
        "You run from the REPO ROOT — read the listed files with the Read tool using the "
        "relative paths given per card (`module_files` — the card's own module first — and "
        "`test_files`; also check the card's import line in agricola/cards/__init__.py). "
        "Occupations have NO printed cost/VP/prereq/passing — their play cost is the standard "
        "Lessons food ramp, not card-specific.\n\n"
    )

    schema = {"type": "object", "additionalProperties": False, "properties": {
        "cards": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "verdict": {"type": "string", "enum": ["correct", "incorrect", "uncertain"]},
                "clause_audit": {"type": "array", "items": {"type": "object",
                    "additionalProperties": False, "properties": {
                        "clause": {"type": "string"}, "where": {"type": "string"},
                        "ok": {"type": "boolean"}},
                    "required": ["clause", "where", "ok"]}},
                "discrepancies": {"type": "array", "items": {"type": "object",
                    "additionalProperties": False, "properties": {
                        "clause": {"type": "string"}, "expected": {"type": "string"},
                        "actual": {"type": "string"}, "evidence": {"type": "string"},
                        "severity": {"type": "string", "enum": ["bug", "minor", "cosmetic"]}},
                    "required": ["clause", "expected", "actual", "evidence", "severity"]}},
                "tag_errors": {"type": "array", "items": {"type": "string"}},
                "untested_clauses": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"}},
            "required": ["id", "verdict", "clause_audit", "discrepancies", "tag_errors",
                         "untested_clauses", "note"]}}},
        "required": ["cards"]}

    out = os.path.join(HERE, "verify_impl.js")
    js = ("export const meta = {\n  name: 'verify-implemented-cards',\n"
          "  description: 'Audit every implemented card against its verbatim rules text',\n"
          "  phases: [{ title: 'Audit', detail: 'one agent per mechanic-family batch' }],\n}\n\n"
          "const PROMPT = " + json.dumps(preamble + prompt) + ";\n"
          "const BATCHES = " + json.dumps(batches) + ";\n"
          "const SCHEMA = " + json.dumps(schema) + ";\n\n"
          "log('Auditing ' + BATCHES.length + ' batches');\n"
          "const results = await parallel(BATCHES.map((b) => () =>\n"
          "  agent(PROMPT + '\\n\\n=== CARDS TO AUDIT ===\\n' + JSON.stringify(b.cards, null, 1),\n"
          "    { label: b.label, phase: 'Audit', schema: SCHEMA, effort: b.effort, model: 'opus' })\n"
          "));\n"
          "const cards = results.filter(Boolean).flatMap(r => (r && r.cards) ? r.cards : []);\n"
          "log('Audited ' + cards.length + ' cards');\nreturn { cards };\n")
    open(out, "w").write(js)
    with open(out + ".batches.json", "w") as f:
        json.dump(batches, f, indent=1)

    n_triv = sum(len(b["cards"]) for b in batches if b["effort"] == "low")
    print(f"wrote {out}: {len(items)} cards, {len(batches)} batches "
          f"({n_triv} trivial @ low, {len(items) - n_triv} complex @ medium)")
    for fam in sorted(by_family):
        print(f"  {fam:16s} {len(by_family[fam]):3d} cards")


if __name__ == "__main__":
    main()
