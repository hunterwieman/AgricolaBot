#!/usr/bin/env python
"""Fable adjudication over every card where the existing doc label and the Fable
cold label disagree (excluding hand-ruled/patched cards, which stay authoritative)."""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import gen_classify as G  # noqa: E402

NORM = {"COST-GAME": "CAP-GAME", "T-DURING": "S-HFEED", "L-OCCUP": "L-OCCUPY", "E-MANDCHOICE": "F-MANDCHOICE",
        "E-CARDSPACE-LIKE": "L-CARDSPACE", "ALTCOST-NONE": "E-ALTCOST", "CAP-NEW": "E-CAPNEW"}
def nz(cs): return set(NORM.get(x, NORM.get(x.upper(), x)) for x in cs)
EXCLUDE = set("A45 A48 B23 C18 C22 C23 C32 C49 C84 D25 D37 E3 E4 E5 E14 E58 E68 E73 E80 E84".split()) \
    | set("A162 B146 C108 C125 D97 D103 D110 D129 D155 D157 E155".split()) \
    | set("A138 D134 B24 B70 D140 D119 A63 D22 D20 D144 E16 E70 B149".split())

meta = {c["id"]: c for c in (G.load("minor") + G.load("occupation"))}
# existing doc tags
doc = {}; cid = None; hdr = re.compile(r"^- (?:✅|🚫|⬜) \*\*([A-E]\d+) ")
for ln in open(os.path.join(ROOT, "CARD_IMPLEMENTATION_PROGRESS.md")):
    m = hdr.match(ln)
    if m: cid = m.group(1); continue
    if cid and ln.startswith("  - `"):
        doc[cid] = nz(re.search(r"`([^`]*)`", ln).group(1).split()); cid = None
# fable cold labels
fab = {}
for f in ["fable_minors.json", "fable_occ.json"]:
    for c in json.load(open(os.path.join(DATA, f)))["result"]["cards"]:
        fab[c["id"]] = nz(c["codes"])

wl = []
for i in meta:
    if i in EXCLUDE or i not in fab or i not in doc:
        continue
    if fab[i] != doc[i]:
        wl.append({"id": i, "name": meta[i]["name"], "players": meta[i].get("players"),
                   "cost": meta[i].get("cost"), "prereq": meta[i].get("prereq"), "text": meta[i]["text"],
                   "labelA_existing": sorted(doc[i]), "labelB_fable": sorted(fab[i])})
print(f"disagreements to adjudicate: {len(wl)} (excluded {len(EXCLUDE)} hand-ruled/patched)")

CONV = """

=== ADJUDICATION TASK ===
Two labelers tagged each card and DISAGREED: `labelA_existing` (a prior multi-pass pipeline) and `labelB_fable` (a fresh pass). Using the taxonomy + rulings above, READ THE CARD TEXT and decide the CORRECT final code set for each card — do not just pick a side. Return the final `codes`, a one-line `reason`, and `low_confidence` (true only if genuinely unsettleable). Use only taxonomy codes.
"""
schema = {"type": "object", "additionalProperties": False, "properties": {
    "cards": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "id": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"}, "low_confidence": {"type": "boolean"}},
        "required": ["id", "codes", "reason", "low_confidence"]}}}, "required": ["cards"]}
BS = 8
batches = [wl[i:i + BS] for i in range(0, len(wl), BS)]
out = os.path.join(HERE, "fable_adj.js")
js = ("export const meta = {\n  name: 'fable-adjudicate-disagreements',\n"
      "  description: 'Fable adjudication of existing-vs-Fable label disagreements',\n"
      "  phases: [{ title: 'Adjudicate' }],\n}\n\n"
      "const PROMPT = " + json.dumps(G.TAXONOMY + CONV) + ";\n"
      "const BATCHES = " + json.dumps(batches) + ";\n"
      "const SCHEMA = " + json.dumps(schema) + ";\n\n"
      "log('Fable-adjudicating ' + BATCHES.length + ' batches');\n"
      "const results = await parallel(BATCHES.map((b, i) => () =>\n"
      "  agent(PROMPT + '\\n\\n=== CARDS TO ADJUDICATE ===\\n' + JSON.stringify(b, null, 1),\n"
      "    { label: 'fadj-' + (i + 1), phase: 'Adjudicate', schema: SCHEMA, effort: 'high', model: 'fable' })\n"
      "));\n"
      "const cards = results.filter(Boolean).flatMap(r => (r && r.cards) ? r.cards : []);\n"
      "log('Adjudicated ' + cards.length + ' cards');\nreturn { cards };\n")
open(out, "w").write(js)
print(f"wrote {out}: {len(wl)} cards, {len(batches)} batches (size {BS})")
