#!/usr/bin/env python
"""High-effort verification sweep over every card carrying a GEOMETRY code
(L-GEOMBOARD / L-GEOMFARM / L-CARDFIELD) — the shared-bias blind spot that
agreement-based flagging can't catch. Parses the current doc for the work-list.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.getcwd())
import gen_classify as G  # noqa: E402

SP = os.environ["SP"]
GEOM = {"L-GEOMBOARD", "L-GEOMFARM", "L-CARDFIELD"}
DOC = "CARD_IMPLEMENTATION_PROGRESS.md"

# Parse the doc's per-card entries: header, text line, code line.
cards, cur = [], None
hdr = re.compile(r"^- (?:✅|🚫|⬜) \*\*([A-E]\d+) (.+?)\*\*")
for ln in open(DOC):
    m = hdr.match(ln)
    if m:
        cur = {"id": m.group(1), "name": m.group(2)}
        continue
    if cur and ln.startswith("  - _"):
        cur["text"] = ln.strip()[3:].rstrip("_").lstrip("_")
    elif cur and ln.startswith("  - `"):
        codes = re.search(r"`([^`]*)`", ln).group(1).split()
        cur["codes"] = codes
        cards.append(cur)
        cur = None

wl = [c for c in cards if set(c["codes"]) & GEOM]
print(f"cards carrying a geometry code: {len(wl)}")

INSTR = """

=== GEOMETRY-CODE VERIFICATION TASK ===
Each card below currently carries one or more of L-GEOMBOARD, L-GEOMFARM, L-CARDFIELD. These three codes are frequently OVER-applied. For EACH card, return the CORRECT final code set, scrutinizing whether each geometry code is truly warranted by the STRICT tests:

- L-GEOMBOARD — ONLY action-board POSITION / ORDER / ADJACENCY: specific round-space NUMBERS or bands, "the space above/below X", "the most recently revealed card", "an action space adjacent to another". NOT warranted for: using / hooking / reading a specific NAMED space (Forest, Fishing, a Quarry, Grove, Lessons, etc.) or its good-count / occupancy; nor for scheduling goods/pieces onto FUTURE round spaces (that is E-SCHED, not geometry).
- L-GEOMFARM — ONLY orthogonal ADJACENCY / SHAPE between farm tiles (a room next to both a field and a pasture; a 2x2 of fields; cells adjacent to the house). NOT warranted for merely COUNTING pastures/fields/spaces, a per-pasture capacity or restriction, or "how many X you have".
- L-CARDFIELD — ONLY when the card ITSELF is a field you sow/harvest on. NOT warranted for a card that merely reads or affects your existing field TILES' contents ("veg in your fields", "each grain field", place a crop into a field).

Remove any geometry code that fails its test; keep it if it genuinely applies; leave the card's OTHER codes as-is unless clearly wrong. Return the full corrected `codes`, a one-line `reason` naming which geometry code(s) you kept or removed and why, and `low_confidence` only if genuinely ambiguous. Each card shows its current `codes`. Use only codes from the taxonomy above.
"""

schema = {"type": "object", "additionalProperties": False, "properties": {
    "cards": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "id": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"}, "low_confidence": {"type": "boolean"}},
        "required": ["id", "codes", "reason", "low_confidence"]}}}, "required": ["cards"]}
BS = 9
batches = [wl[i:i + BS] for i in range(0, len(wl), BS)]
out = f"{SP}/scratchpad/geom_review.js"
js = (
    "export const meta = {\n"
    "  name: 'verify-geometry-codes',\n"
    "  description: 'High-effort check of every card tagged with a geometry code',\n"
    "  phases: [{ title: 'Verify', detail: 'one high-effort agent per batch' }],\n"
    "}\n\n"
    "const PROMPT = " + json.dumps(G.TAXONOMY + INSTR) + ";\n"
    "const BATCHES = " + json.dumps(batches) + ";\n"
    "const SCHEMA = " + json.dumps(schema) + ";\n\n"
    "log('Verifying ' + BATCHES.length + ' geometry-code batches (high effort)');\n"
    "const results = await parallel(BATCHES.map((b, i) => () =>\n"
    "  agent(PROMPT + '\\n\\n=== CARDS TO VERIFY ===\\n' + JSON.stringify(b, null, 1),\n"
    "    { label: 'geom-' + (i + 1), phase: 'Verify', schema: SCHEMA, effort: 'high' })\n"
    "));\n"
    "const cards = results.filter(Boolean).flatMap(r => (r && r.cards) ? r.cards : []);\n"
    "log('Verified ' + cards.length + ' cards');\n"
    "return { cards };\n"
)
open(out, "w").write(js)
print(f"wrote {out}: {len(wl)} cards, {len(batches)} batches (size {BS})")
