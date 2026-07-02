#!/usr/bin/env python
"""Generate a HIGH-EFFORT adjudication workflow over the flagged (⚠/🔶) cards.

Each card shows both classification passes' tags; a high-effort reviewer decides
the correct final codes using the tightened taxonomy + adjudication conventions.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.getcwd())
import gen_classify as G  # noqa: E402

SP = os.environ["SP"]
NORM = {"COST-GAME": "CAP-GAME", "T-DURING": "S-HFEED", "L-OCCUP": "L-OCCUPY",
        "E-MANDCHOICE": "F-MANDCHOICE", "E-CARDSPACE-LIKE": "L-CARDSPACE",
        "ALTCOST-NONE": "E-ALTCOST", "CAP-NEW": "E-CAPNEW"}
REVIEW_IGNORE = set("""A-OWN A-OPP T-BEFORE T-AFTER E-GOODS ONPLAY F-AUTO F-TRIG S-OBTAIN LATCH
 E-WORKERMANIP E-CROPMANIP E-BREEDMOD EXOTIC S-HSTART E-EXTRAPLACE L-GEOMFARM L-GEOMBOARD
 E-SCOREOPT E-SCORE S-BEFORESCORE CAP-TURN CAP-ROUND CAP-HARVEST""".split())
PATCH_MIN = set("A45 A48 B23 C18 C22 C23 C32 C49 C84 D25 D37 E3 E4 E5 E14 E58 E68 E73 E80 E84".split())
PATCH_OCC = set("A162 B146 C108 C125 D97 D103 D110 D129 D155 D157 E155".split())


def norm(cs):
    return set(NORM.get(x, NORM.get(x.upper(), x)) for x in cs)


def worklist(curfile, cmpfile, cardsfile, patch):
    meta = {c["id"]: c for c in json.load(open(cardsfile))}
    cur = {c["id"]: c for c in json.load(open(curfile))["result"]["cards"] if c["id"] in meta}
    cmp = {c["id"]: norm(c["codes"]) for c in json.load(open(cmpfile))["result"]["cards"] if c["id"] in meta}
    out = []
    for i, c in cur.items():
        if i in patch:
            continue
        cur_codes = norm(c["codes"])
        unclear = bool(c.get("unclear"))
        if not (unclear or ((cur_codes ^ cmp.get(i, set())) - REVIEW_IGNORE)):
            continue
        m = meta[i]
        out.append({"id": i, "name": m["name"], "players": m.get("players"),
                    "cost": m.get("cost"), "prereq": m.get("prereq"), "text": m["text"],
                    "pass1": sorted(cmp.get(i, set())), "pass2": sorted(cur_codes)})
    return out


CONV = """

=== ADJUDICATION TASK ===
Two independent classification passes tagged each card below and DISAGREED. Using the taxonomy above and these conventions, decide the CORRECT final code set for each card. READ THE CARD TEXT and reason it out — do not just copy one pass. Return the final `codes`, a one-line `reason`, and `low_confidence` (true ONLY if the card genuinely cannot be settled from its text — a real ambiguity or a mechanic no code captures).

CONVENTIONS (use these to settle disagreements):
1. A-OWN is the DEFAULT actor for any own-turn HOOK — always include A-OWN (use A-OPP only when the trigger is ANOTHER player's action). Never omit the actor on a HOOK.
2. L-GEOMBOARD is ONLY for action-board POSITION/ORDER/ADJACENCY (specific round-space numbers/bands, "the space above/below X", "the most recently revealed card"). Placing or SCHEDULING goods/pieces onto FUTURE round spaces is E-SCHED, NOT L-GEOMBOARD.
3. A passive end-game scoring RULE ("during scoring, 1 point per X") is E-SCORE and NEVER carries HOOK / S-BEFORESCORE / F-AUTO. BUT a bonus point earned THROUGH an action ("on a Bake Bread action, pay 1 grain for 1 bonus point") legitimately combines HOOK + E-SCORE — that is correct, not an error.
4. Only use codes from the taxonomy. If a real mechanic is missing, set low_confidence and name it in `reason`.

Each card shows `pass1` and `pass2` (the two passes' tag sets) — treat them as suggestions to adjudicate, not answers.
"""


def main():
    wl = (worklist(f"{SP}/tasks/wr3mwb7wu.output", f"{SP}/tasks/wg6nk25er.output",
                   f"{SP}/scratchpad/classify_minors_v3.js.cards.json", PATCH_MIN)
          + worklist(f"{SP}/tasks/wigfr99vs.output", f"{SP}/tasks/wyw52oxjy.output",
                     f"{SP}/scratchpad/classify_occupations_v2.js.cards.json", PATCH_OCC))
    BS = 8
    batches = [wl[i:i + BS] for i in range(0, len(wl), BS)]
    prompt_head = G.TAXONOMY + CONV
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "cards": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "id": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"}, "low_confidence": {"type": "boolean"}},
            "required": ["id", "codes", "reason", "low_confidence"]}}}, "required": ["cards"]}
    out = f"{SP}/scratchpad/review_flagged.js"
    js = (
        "export const meta = {\n"
        "  name: 'adjudicate-flagged-cards',\n"
        "  description: 'High-effort review of the classification-disagreement cards',\n"
        "  phases: [{ title: 'Adjudicate', detail: 'one high-effort agent per batch' }],\n"
        "}\n\n"
        "const PROMPT = " + json.dumps(prompt_head) + ";\n"
        "const BATCHES = " + json.dumps(batches) + ";\n"
        "const SCHEMA = " + json.dumps(schema) + ";\n\n"
        "log('Adjudicating ' + BATCHES.length + ' batches (high effort)');\n"
        "const results = await parallel(BATCHES.map((b, i) => () =>\n"
        "  agent(PROMPT + '\\n\\n=== CARDS TO ADJUDICATE ===\\n' + JSON.stringify(b, null, 1),\n"
        "    { label: 'adj-' + (i + 1), phase: 'Adjudicate', schema: SCHEMA, effort: 'high' })\n"
        "));\n"
        "const cards = results.filter(Boolean).flatMap(r => (r && r.cards) ? r.cards : []);\n"
        "log('Adjudicated ' + cards.length + ' cards');\n"
        "return { cards };\n"
    )
    open(out, "w").write(js)
    json.dump(wl, open(out + ".worklist.json", "w"), indent=1)
    print(f"wrote {out}: {len(wl)} flagged cards, {len(batches)} batches (size {BS})")


if __name__ == "__main__":
    main()
