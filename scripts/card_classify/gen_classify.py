#!/usr/bin/env python
"""Generate a card-classification workflow (.js) + a sidecar cards JSON.

Reads the minor/occupation catalog, computes implementation status from the live
registry (deck-aware collision flag), batches the cards with verbatim text, and
emits a self-contained Workflow script that fans out one classifier agent per
batch. The taxonomy/rubric is inlined once (amortized across the batch).

Usage:
  python scratchpad/gen_classify.py --type minor --batch-size 14 \
      --out scratchpad/classify_minors.js
"""
from __future__ import annotations
import argparse, json, os, sys
from collections import Counter

sys.path.insert(0, os.getcwd())
import agricola.cards  # noqa: F401  (populate registries)
from agricola.cards.specs import MINORS, OCCUPATIONS
from scripts.card_text import card_slug

TAXONOMY = r"""You classify Agricola CARDS (occupations or minor improvements) by the game MECHANICS/FEATURES each one uses, so an engine team can track what still needs building. A card almost always uses SEVERAL mechanics at once — tag EVERY code that applies. Classify ONLY from the card's printed text plus its errata/clarifications (which OVERRIDE the text). Never invent effects the text does not state.

For each card return: `id` (exactly as given), `codes` (all applicable codes below), `unclear` (true ONLY if you genuinely cannot assign codes — ambiguous timing/optionality/mechanic; then explain in `note`), `new_category` (if the card uses a mechanic NO code below captures, put a short `NAME: definition` here — else ""), and a one-line `note` (brief reasoning, or the ambiguity).

Tag >=1 ACTIVATION; the HOOK sub-codes ONLY if you tagged HOOK; >=1 EFFECT; and any SCOPE/LEGALITY/STATE that apply.

ACTIVATION — how the effect turns on:
- ONPLAY: an effect happens once, when the card is played.
- HOOK: the card fires in response to a game event (a trigger). If used, ALSO tag the 4 HOOK dimensions.
- ATWILL: the player may use the effect at a time of their own choosing (deferrable). "At any time, you can...", or "Once per round, you can..." (also add CAP-ROUND).
- PASSIVE: an always-on continuous rule change, no firing ("your pastures can hold 2 more animals"; "every improvement costs 1 wood less").
- LATCH: the effect fires ONCE, the first moment a persistent STANDING CONDITION becomes true — a house-material state or a played-card/animal/resource COUNT ("Once you live in a stone house...", "Once you no longer live in wood...", "As soon as you have 6 occupations..."), then never again. Pair with ST-LATCH (and usually CAP-GAME). NOT for "the first time you take action X" (e.g. "on your first renovation") — that is an ACTION trigger: HOOK on that sub-action + CAP-GAME, never LATCH.

HOOK dimensions (only if HOOK):
  Timing: T-BEFORE (fires before the triggering action's effect; the DEFAULT for "each time you use [space]" and "before you..."); T-AFTER ("immediately after...", "after you...", "at the end of...").
  Seam: S-SPACE (using an action space); S-SUB (a primitive sub-action: sow/bake/plow/renovate/build room/stable/fence/family-growth/play-a-card); S-MAJMIN (taking the Major-or-Minor-Improvement action); S-PLAY (a card being played); S-OBTAIN (you OBTAIN/gain a good -- it enters your supply, from ANY source); S-SOR (start of each round); S-HSTART (start of a harvest, before its field phase); S-HFIELD (harvest field phase); S-HFEED (during the feeding phase); S-AFTERFEED (after the feeding phase is finished); S-HBREED (breeding phase / gaining newborns); S-ROUNDEND (returning-home / end of round); S-TURNEND (end of a turn or work phase); S-BEFORESCORE (just before scoring); S-REVEAL (a card/space being revealed).
  Firing: F-AUTO (mandatory, no choice: "you get..."); F-TRIG (optional: "you can/may..."; ALL granted sub-actions/actions are optional -> F-TRIG); F-MANDCHOICE (mandatory but you must choose: "you get 1 grain OR 1 vegetable", no decline).
  Actor: A-OWN (fires on YOUR action); A-OPP (fires on ANOTHER player's action: "each time another player...").

SCOPE cap (add if limited per period): CAP-TURN, CAP-ROUND, CAP-HARVEST, CAP-GAME (once ever / "only once"). Use CAP-* only to cap the frequency of an ATWILL option ("Once per round, you can..." -> ATWILL + CAP-ROUND). A HOOK that fires "each round/harvest/turn" BY ITS NATURE already implies once-per-occurrence and does NOT get a CAP tag.

EFFECT — what it does (tag all that apply):
- E-GOODS: gain goods/food/crops immediately.
- E-SCHED: place goods/food on FUTURE round spaces (collected at the start of those rounds).
- E-SCHEDANIMAL: place ANIMALS on future round spaces.
- E-ANIMALS: the card provides animals to the player (ANY amount, ANY timing) -- flag it because the animals must be accommodated on the farm.
- E-GRANTSUB: grants a primitive sub-action (plow, bake bread, build a room/stable/fence, renovate, family growth).
- E-GRANTACT: grants a whole action (a full "Build Fences/Rooms/Stables" action, or another action space's action).
- E-NOPLACE: lets you take an action WITHOUT placing a person.
- E-SUBSTITUTE: replaces one action with another ("instead of X, you can do Y").
- E-COSTMOD: changes what a build/renovation/improvement COSTS (cheaper, a replacement cost formula, or substituting one resource for another when paying).
- E-FREEFENCE: makes some fences free / provides free fence pieces.
- E-FOODCOST: an effect that costs FOOD (payable by converting crops/animals).
- E-ALTCOST: the card's own printed PLAY-cost is a choice ("3 Wood / 2 Clay" = pay one OR the other for the SAME effect).
- E-PLAYVARIANT: playing the card forks the cost AND/OR the reward together ("1 Grain/1 Reed -> 1 veg/4 wood").
- E-PIECECOST: a cost paid with a game PIECE from supply (a stable or fence), not a resource.
- E-PASSING: a traveling/passing minor -- after you play it and resolve it, you PASS the card to another player instead of keeping it.
- E-CONVERT: converts/exchanges one good for another at a rate.
- E-CAPGROW: raises the capacity of an EXISTING animal slot (pastures, the house pet, per-room).
- E-CAPNEW: creates a NEW holder/slot (the card itself holds animals; or a room/stable holds a person).
- E-CAPNEG: removes/overrides capacity ("you can no longer hold animals in your house").
- E-SCORE: an end-game BONUS-point rule written in the card TEXT ("During scoring, you get 1 bonus point for each..."). NOT the plain printed VP circle. Scoring is COMPUTED at game end, it is NOT a fired event -> do NOT also tag HOOK / S-BEFORESCORE / F-AUTO for a scoring rule.
- E-SCOREOPT: an end-game score needing a real OPTIMIZATION over arrangements (assign animals to pastures to maximize the bonus). A plain threshold / coverage / count score ("pastures cover >=6 spaces"; "1 pt per major improvement") is ordinary E-SCORE, NOT E-SCOREOPT.
- E-SCORECMP: a comparative score depending on BOTH players ("each player with the most rooms...").
- E-SCOREGRP: a mutually-exclusive scoring card ("you can only use one card to get bonus points for your stone house").
- E-TAKEBACK: reclaims/removes a benefit previously granted or promised (e.g. wood still promised on round spaces).
- E-RETURNCOMP: returns/discards a placed component (a built stable, an improvement) for a benefit.
- E-OPPTRANSFER: moves goods TO or FROM another player (a toll they pay you; a gift you give them).
- E-BAKESPEC: adds or changes a baking improvement or bake-bread conversion rate.
- E-GROWTH: a Family Growth (gaining a person). Note in `note` if "even without room" or "without placing a person".
- E-PEOPLE: temporary workers, changing person capacity, or newborn classification (NOT a plain extra placement -> E-EXTRAPLACE).
- E-EXTRAPLACE: place an ADDITIONAL worker / take a second placement in a phase (beyond the normal one-per-turn).
- E-WORKERMANIP: manipulate an ALREADY-PLACED worker -- return it home to reuse this phase, move it, or use two spaces with one person. NOT gaining people (E-PEOPLE) and NOT family growth (E-GROWTH). Usually needs ST-PLACELOG.
- E-CROPMANIP: manipulate crops ON fields or the field-harvest RULE -- move/remove planted crops, discard a field's crops as a cost, or change how many goods a field yields in the field phase. NOT gaining loose crops (E-GOODS) and NOT normal sow/harvest.
- E-BREEDMOD: change the BREEDING rules -- breed OUTSIDE the harvest breeding phase, or relax the "need 2 of a type" requirement. NOT merely gaining animals (E-ANIMALS).

LEGALITY / STRUCTURE:
- L-OCCUPY: lets you use an OCCUPIED action space.
- L-EXT: extends legality/eligibility (a new renovation target; considering a space unoccupied; changing what currency a cost is paid in).
- L-CARDSPACE: the card is itself an action space.
- L-CARDFIELD: the card ITSELF is a field you sow/harvest ON. NOT: a card that stores a POOL of field TILES you plow onto your farm (that is ST-STACK); NOT a card that merely reads/affects your existing field tiles' contents ("veg in your fields", "each grain field").
- L-GEOMFARM: depends on ORTHOGONAL ADJACENCY / SHAPE between farm tiles (a room next to both a field and a pasture; a 2x2 of fields; cells adjacent to your house). ONLY adjacency/shape — merely COUNTING or referencing pastures/fields/spaces (or a per-pasture capacity/restriction) is NOT L-GEOMFARM.
- L-GEOMBOARD: depends on the GAME-VARIABLE arrangement of action-space cards on the main board -- their reveal/placement ORDER ("the most recently revealed card", "the card left of the most recently placed") OR ADJACENCY between action spaces ("the space above/below X", "Fishing and its orthogonally adjacent spaces", "a space adjacent to another occupied space"). NOT warranted for: specific round-space NUMBERS or bands ("round spaces 8-11", "1/2/3/4") or round TIMING ("a round following a harvest") -- these are FIXED every game and are NOT geometry; nor for scheduling goods/pieces onto future round spaces (that is E-SCHED); nor for reading a NAMED space's good-count/occupancy.
- L-HIDDEN: depends on the hidden identity/order of unrevealed round-space cards.
- L-RANDOM: involves randomness during play (dice, coin flips, a random draw).

STATE the card must keep:
- ST-STORE: a small per-card number/flag (a snapshot, a uses-left counter).
- ST-LATCH: a one-time effect that fires the first moment a standing condition (usually house material) becomes true.
- ST-THRESHOLD: a one-time effect that fires when a resource/animal COUNT reaches a threshold.
- ST-COUNTER: a running count accumulated over a phase/game.
- ST-STACK: a stack/pile of goods kept ON the card, consumed over time.
- ST-PLACELOG: needs to know WHICH space a specific worker was placed on.
- ST-PROV: needs the provenance/payload of an event (which resource paid a cost; which card was just played; a value snapshotted before a space was zeroed).

EXOTIC: a genuine ONE-OFF mechanic that fits NO other code and is not worth its own category. Tag EXOTIC + the nearest applicable codes + describe it in `note`.

NONE: the card needs NO mechanic beyond immediate plain goods/crops/food (even conditional on a plain state read) and/or a plain printed VP. Tag it alongside ONPLAY+E-GOODS for trivially-implementable cards.

KEY RULINGS (apply exactly):
- A-OWN is the DEFAULT actor on any own-turn HOOK -- ALWAYS include it (use A-OPP instead only when the trigger is ANOTHER player's action; use BOTH if it fires on any player's action).
- A passive end-game scoring RULE (E-SCORE -- "during scoring, 1 point per X") is computed at scoring and NEVER carries HOOK / S-BEFORESCORE / F-AUTO. A bonus point earned THROUGH an action ("on a Bake Bread action, pay 1 grain for 1 bonus point") MAY legitimately combine HOOK + E-SCORE.
- E-FOODCOST is for effects that COST food (payable by converting crops/animals). An effect that PRODUCES food is NOT E-FOODCOST.
- A hook keyed on OBTAINING a good ("each time you obtain/gain [good]") -> S-OBTAIN (not S-SPACE).
- A one-shot that fires when a standing condition FIRST becomes true -> ACTIVATION LATCH + ST-LATCH (not HOOK).
- A play restriction COMPUTABLE from state ("only if more rounds left than unused spaces"; "not once any player has 5+ cards") is just a prerequisite/condition -- do NOT invent a mechanic for it; if the card otherwise only scores a plain VP or gains plain goods, tag NONE.
- "Each time you use [an action space]" fires BEFORE the space's action -> T-BEFORE. Only "immediately after"/"at the end of" -> T-AFTER.
- Every granted sub-action or action is OPTIONAL -> F-TRIG (unless the text says "you must").
- "Once per round, you can..." = ATWILL + CAP-ROUND. "At any time..." = ATWILL. A standalone conversion/buy/build with no stated trigger event = ATWILL. "...without placing a person" with no trigger = ATWILL + E-NOPLACE.
- A prerequisite (top-left, e.g. "2 Occupations", "Clay House", "3 Grain Fields") is a HAVE-check to PLAY the card. It is NOT a cost and NOT a mechanic -- do NOT tag anything for it.
- A cost paid in ordinary resources/food/animals is normal and needs no code -- only flag E-ALTCOST (A/B), E-PIECECOST (stable/fence), or E-FOODCOST (food that may need conversion).
- The plain printed VP circle is automatic and is NOT E-SCORE. E-SCORE is only for a bonus-point RULE in the card's text.
- codes MUST come from the list above. If a mechanic is missing, describe it in `new_category`; never invent a new code inside `codes`.
"""


def load(kind):
    path = f"agricola/cards/data/revised_{'minor_improvements' if kind=='minor' else 'occupations'}.json"
    cards = json.load(open(path))
    reg = MINORS if kind == "minor" else OCCUPATIONS
    names = Counter(c["name"] for c in cards)
    out = []
    for c in cards:
        slug = card_slug(c["name"])
        text = c.get("text", "") or ""
        if c.get("errata"):
            text += f"  [ERRATA: {c['errata']}]"
        if c.get("clarifications"):
            text += f"  [CLARIFICATION: {c['clarifications']}]"
        out.append({
            "id": f"{c['deck']}{c['number']}",
            "deck": c["deck"], "number": c["number"], "name": c["name"],
            "cost": c.get("cost"), "prereq": c.get("prerequisites"),
            "passing": bool(c.get("passing_left")), "vps": c.get("vps", 0),
            "text": text,
            "slug": slug, "implemented": slug in reg,
            "status": c.get("status"), "players": c.get("players"),
            "name_dup": names[c["name"]] > 1,
        })
    return out


OCC_NOTE = ("\n\nNOTE — these are OCCUPATION cards: they have NO printed cost / VP / prerequisite / "
            "passing flag (ignore those fields); the effect and any conditions live entirely in the "
            "text. Occupations are NEVER passing (never tag E-PASSING). An occupation's play cost is a "
            "standard food ramp, not card-specific (do NOT tag E-FOODCOST/E-ALTCOST for it).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["minor", "occupation"], default="minor")
    ap.add_argument("--batch-size", type=int, default=14)
    ap.add_argument("--limit", type=int, default=0, help="first N cards (0=all)")
    ap.add_argument("--model", default=None, help="agent model override (e.g. fable)")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cards = load(a.type)
    if a.limit:
        cards = cards[:a.limit]
    # agent payload: only the classification-relevant fields (no impl status)
    slim = [{"id": c["id"], "name": c["name"], "cost": c["cost"],
             "prereq": c["prereq"], "passing": c["passing"], "text": c["text"]}
            for c in cards]
    batches = [slim[i:i + a.batch_size] for i in range(0, len(slim), a.batch_size)]

    js = (
        "export const meta = {\n"
        "  name: 'classify-cards',\n"
        "  description: 'Tag each Agricola card with the mechanics/features it uses',\n"
        "  phases: [{ title: 'Classify', detail: 'one agent per batch' }],\n"
        "}\n\n"
        "const TAXONOMY = " + json.dumps(TAXONOMY + (OCC_NOTE if a.type == "occupation" else "")) + ";\n"
        "const BATCHES = " + json.dumps(batches) + ";\n"
        "const SCHEMA = " + json.dumps({
            "type": "object", "additionalProperties": False,
            "properties": {"cards": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "properties": {
                    "id": {"type": "string"},
                    "codes": {"type": "array", "items": {"type": "string"}},
                    "unclear": {"type": "boolean"},
                    "new_category": {"type": "string"},
                    "note": {"type": "string"}},
                "required": ["id", "codes", "unclear", "new_category", "note"]}}},
            "required": ["cards"]}) + ";\n\n"
        "log('Classifying ' + BATCHES.length + ' batches');\n"
        "const results = await parallel(BATCHES.map((b, i) => () =>\n"
        "  agent(\n"
        "    TAXONOMY + '\\n\\n=== CARDS TO CLASSIFY (one entry per card, use the id shown) ===\\n' + JSON.stringify(b, null, 1),\n"
        "    { label: 'cards-' + (i + 1), phase: 'Classify', schema: SCHEMA, effort: '" + a.effort + "'" + (", model: '" + a.model + "'" if a.model else "") + " }\n"
        "  )\n"
        "));\n"
        "const cards = results.filter(Boolean).flatMap(r => (r && r.cards) ? r.cards : []);\n"
        "log('Collected ' + cards.length + ' classified cards');\n"
        "return { cards };\n"
    )
    with open(a.out, "w") as f:
        f.write(js)
    with open(a.out + ".cards.json", "w") as f:
        json.dump(cards, f, indent=1)
    print(f"wrote {a.out} : {len(cards)} cards, {len(batches)} batches (size {a.batch_size})")
    print(f"implemented: {sum(c['implemented'] for c in cards)} / {len(cards)}"
          f"   name-dup(ambiguous impl): {sum(c['name_dup'] for c in cards)}")


if __name__ == "__main__":
    main()
