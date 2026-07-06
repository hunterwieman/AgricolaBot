#!/usr/bin/env python
"""Compile classification workflow results (minors + occupations) into one progress .md."""
import json, os, sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "CARD_IMPLEMENTATION_PROGRESS.md")

CANON = set("""ONPLAY HOOK ATWILL PASSIVE LATCH T-BEFORE T-AFTER S-SPACE S-SUB S-MAJMIN S-PLAY S-OBTAIN S-SOR S-HSTART S-HFIELD S-HFEED S-AFTERFEED S-HBREED S-ROUNDEND S-TURNEND S-BEFORESCORE S-REVEAL F-AUTO F-TRIG F-MANDCHOICE A-OWN A-OPP CAP-TURN CAP-ROUND CAP-HARVEST CAP-GAME E-GOODS E-SCHED E-SCHEDANIMAL E-SEEDSPACE E-ANIMALS E-GRANTSUB E-GRANTACT E-NOPLACE E-SUBSTITUTE E-COSTMOD E-FREEFENCE E-FOODCOST E-ALTCOST E-PLAYVARIANT E-PIECECOST E-PASSING E-CONVERT E-CAPGROW E-CAPNEW E-CAPNEG E-SCORE E-SCOREOPT E-SCORECMP E-SCOREGRP E-TAKEBACK E-RETURNCOMP E-OPPTRANSFER E-BAKESPEC E-GROWTH E-PEOPLE E-EXTRAPLACE E-WORKERMANIP E-CROPMANIP E-BREEDMOD L-OCCUPY L-EXT L-CARDSPACE L-CARDFIELD L-GEOMFARM L-GEOMBOARD L-HIDDEN L-RANDOM ST-STORE ST-LATCH ST-THRESHOLD ST-COUNTER ST-STACK ST-PLACELOG ST-PROV EXOTIC NONE REVISIT""".split())

NORMALIZE = {"COST-GAME": "CAP-GAME", "T-DURING": "S-HFEED",
             "L-OCCUP": "L-OCCUPY", "E-MANDCHOICE": "F-MANDCHOICE", "E-CARDSPACE-LIKE": "L-CARDSPACE",
             "ALTCOST-NONE": "E-ALTCOST", "CAP-NEW": "E-CAPNEW"}
# C54 "Market Stall" shares B8's name-slug; it is implemented under the
# distinct card_id `market_stall_c54` (2026-07-05), which the slug-based
# implemented-check can't see — force True. Same for the C71 "Slurry
# Spreader" minor (card_id `slurry_spreader_c71`; the A-deck occupation of
# the same name owns the plain slug).
IMPL_FIX = {"C54": True, "C71": True}
# Codes too noisy/low-stakes to flag a review on (actor, timing, minor-goods, on-play, firing).
REVIEW_IGNORE = {"A-OWN", "A-OPP", "T-BEFORE", "T-AFTER", "E-GOODS", "ONPLAY", "F-AUTO", "F-TRIG",
                 "S-OBTAIN", "LATCH", "E-WORKERMANIP", "E-CROPMANIP", "E-BREEDMOD", "EXOTIC",
                 "S-HSTART", "E-EXTRAPLACE",
                 # codes whose definitions were tightened between the compared passes:
                 "L-GEOMFARM", "L-GEOMBOARD", "E-SCOREOPT", "E-SCORE", "S-BEFORESCORE",
                 "CAP-TURN", "CAP-ROUND", "CAP-HARVEST"}

PATCH_MIN = {
    "A45": (["LATCH", "ST-LATCH", "E-SCHED", "CAP-GAME"], "House-material latch: on leaving a wooden house, schedule 1 food x6 rounds."),
    "A48": (["HOOK", "T-AFTER", "S-OBTAIN", "F-TRIG", "A-OWN", "E-CONVERT"], "BANNED. On obtaining wood: wood->3 food (mandatory at 7+)."),
    "B23": (["ONPLAY", "EXOTIC", "L-CARDSPACE", "L-HIDDEN"], "Reserve the round-14 action-space card as an owner-private space."),
    "C18": (["ATWILL", "E-CROPMANIP", "E-GRANTSUB"], "Discard one field's crops (>=3 planted) to plow 1 field."),
    "C22": (["ONPLAY", "E-WORKERMANIP", "E-EXTRAPLACE", "ST-PLACELOG"], "Move your first-placed worker (+newborn) to the card, then place another."),
    "C23": (["PASSIVE", "E-WORKERMANIP", "L-GEOMBOARD"], "Use Day Laborer + adjacent Lessons with one person, in order."),
    "C32": (["ONPLAY", "NONE"], "Plain 3 VP; play-restricted once any player has 5+ cards (computable condition)."),
    "C49": (["HOOK", "T-AFTER", "S-HFEED", "F-TRIG", "A-OWN", "E-CONVERT", "CAP-HARVEST"], "During feeding: per empty unfenced stable, grain->5 food."),
    "C84": (["HOOK", "S-ROUNDEND", "F-TRIG", "A-OWN", "E-BREEDMOD", "E-ANIMALS", "CAP-ROUND"], "Non-harvest round: pay 1 grain to breed 1 type off-phase."),
    "D25": (["ONPLAY", "EXOTIC", "L-CARDFIELD", "E-BAKESPEC"], "BANNED (user ruling 2026-07-03) — never implement. Multi-entity: counts as field / occupation / minor / Fireplace major."),
    "D37": (["ONPLAY", "NONE"], "Plain 2 VP; play-restricted by rounds-left vs unused-spaces (computable condition)."),
    "E3": (["ONPLAY", "E-WORKERMANIP", "E-PASSING", "ST-PLACELOG"], "Return your worker on Grain Utilization to reuse it this round."),
    "E4": (["ONPLAY", "E-CROPMANIP", "E-GOODS", "E-PASSING"], "Remove all grain from one field; +2 wood per grain removed."),
    "E5": (["ONPLAY", "EXOTIC", "E-GOODS", "E-PASSING"], "Strip 2 different building resources off board accumulation spaces."),
    "E14": (["ATWILL", "E-GRANTACT", "E-NOPLACE"], "When all others have more people: Build Rooms without placing (computable condition)."),
    "E58": (["HOOK", "T-BEFORE", "S-HFIELD", "F-TRIG", "A-OWN", "EXOTIC", "E-GOODS"], "At harvest start: skip field+breeding phases for 1 food."),
    "E68": (["L-CARDFIELD", "E-GOODS"], "Card-field that grows WOOD; +1 veg when its last wood is harvested."),
    "E73": (["HOOK", "T-AFTER", "S-HFIELD", "F-TRIG", "A-OWN", "E-CROPMANIP"], "Field phase: harvest ALL crops from one chosen field at once."),
    "E80": (["L-CARDFIELD"], "Card-field that grows STONE (plant-as-3, counts as 1)."),
    "E84": (["PASSIVE", "E-BREEDMOD", "E-CAPNEW"], "Breed sheep with only 1; the card holds 1 sheep."),
}
PATCH_OCC = {
    "A162": (["EXOTIC", "L-GEOMBOARD", "E-GOODS"], "Conditional 'gap' action space between Forest & Clay Pit when both occupied."),
    "B146": (["HOOK", "T-BEFORE", "S-SPACE", "F-TRIG", "A-OWN", "E-GOODS", "EXOTIC"], "Discard 1 hand card for +1 building resource (E-HANDCOST candidate, not adopted)."),
    "C108": (["ONPLAY", "EXOTIC"], "Mandatory: skip the next entire harvest, including feeding (phase-skip)."),
    "C125": (["HOOK", "S-SOR", "F-TRIG", "A-OWN", "E-EXTRAPLACE"], "Before each work phase, place an extra person on a not-owned-resource accumulation space."),
    "D97": (["ONPLAY", "HOOK", "S-HSTART", "F-TRIG", "A-OWN", "E-GRANTACT", "EXOTIC"], "BANNED (user ruling 2026-07-03) — never implement. On play take 1 begging marker; start of each harvest, play 1 occupation free."),
    "D103": (["HOOK", "T-AFTER", "S-SPACE", "F-TRIG", "A-OWN", "E-EXTRAPLACE", "E-FOODCOST", "E-GOODS"], "Fishing/Reed Bank: pay 1 food -> extra placement + choose 3 stone or grain+veg."),
    "D110": (["HOOK", "T-BEFORE", "S-SPACE", "F-AUTO", "A-OWN", "E-GOODS"], "+2 food on Reed Bank/Clay Pit/Grove, which one gated by Fishing's food (1/2/3+)."),
    "D129": (["HOOK", "S-HSTART", "F-TRIG", "A-OWN", "E-GRANTACT", "E-NOPLACE", "CAP-HARVEST"], "Each harvest w/ >=5 wood: discard down to 5 wood to Build Stables/Wood Rooms."),
    "D155": (["HOOK", "S-HFEED", "F-TRIG", "A-OWN", "E-CONVERT", "CAP-HARVEST"], "Each harvest: 1 wood -> 1 food + 1 grain (craft conversion)."),
    "D157": (["HOOK", "A-OPP", "F-AUTO", "ST-THRESHOLD", "E-GOODS", "CAP-GAME", "E-SCORE", "E-SCORECMP"], "Opponent hits 5 people -> +8 food once; +3 VP if only you have 5."),
    "E155": (["ONPLAY", "E-GOODS", "E-ANIMALS", "EXOTIC"], "On-play goods + 2 boar; locks your family growth until R11 unless all others grew."),
}

LEGEND = [
    ("Activation", "ONPLAY · HOOK · ATWILL(any time) · PASSIVE(always-on) · LATCH(fires once when a condition first becomes true)"),
    ("Hook timing", "T-BEFORE · T-AFTER"),
    ("Hook seam", "S-SPACE · S-SUB · S-MAJMIN · S-PLAY · S-OBTAIN(gain a good) · S-SOR(round start) · S-HSTART(harvest start) · S-HFIELD/S-HFEED/S-AFTERFEED/S-HBREED · S-ROUNDEND · S-TURNEND · S-BEFORESCORE · S-REVEAL"),
    ("Hook firing/actor", "F-AUTO · F-TRIG(optional) · F-MANDCHOICE · A-OWN · A-OPP(opponent's action)"),
    ("Scope cap", "CAP-TURN · CAP-ROUND · CAP-HARVEST · CAP-GAME"),
    ("Effect", "E-GOODS · E-SCHED · E-SCHEDANIMAL · E-ANIMALS · E-GRANTSUB · E-GRANTACT · E-NOPLACE · E-SUBSTITUTE · E-COSTMOD · E-FREEFENCE · E-FOODCOST · E-ALTCOST · E-PLAYVARIANT · E-PIECECOST · E-PASSING · E-CONVERT · E-CAPGROW/E-CAPNEW/E-CAPNEG · E-SCORE/E-SCOREOPT/E-SCORECMP/E-SCOREGRP · E-TAKEBACK · E-RETURNCOMP · E-OPPTRANSFER · E-BAKESPEC · E-GROWTH · E-PEOPLE · E-EXTRAPLACE(extra worker) · E-WORKERMANIP(move/reuse a placed worker) · E-CROPMANIP(crops on fields) · E-BREEDMOD"),
    ("Legality/struct", "L-OCCUPY · L-EXT · L-CARDSPACE · L-CARDFIELD · L-GEOMFARM · L-GEOMBOARD · L-HIDDEN · L-RANDOM"),
    ("State", "ST-STORE · ST-LATCH · ST-THRESHOLD · ST-COUNTER · ST-STACK · ST-PLACELOG · ST-PROV"),
    ("Other", "EXOTIC(one-off) · NONE(no special mechanic)"),
]


# High-effort adjudication of the flagged (disagreement) cards — overrides the cold-pass tags.
ADJUDICATED = {c["id"]: c for c in json.load(open(os.path.join(DATA, "adjudicated.json")))["result"]["cards"]}

# User rulings on the 7 residual low-confidence cards (highest precedence).
RESIDUAL_FIX = {
    "A138": (["A-OWN", "E-GOODS", "F-TRIG", "HOOK", "S-SPACE", "T-BEFORE"],
             "Each time YOU use Fishing (own use only, per text): pay 1 wood -> food per person + reed. No food is spent, so E-FOODCOST dropped."),
    "D134": (["A-OWN", "A-OPP", "E-SCORE", "E-WORKERMANIP", "F-AUTO", "HOOK", "S-SPACE", "T-AFTER"],
             "Fires on ANY player's Fishing use (user ruling): owner gets 1 bonus point and must skip their next placement."),
    "B24": (["ONPLAY", "PASSIVE", "E-EXTRAPLACE"],
            "Place two people back-to-back if one uses an animal market; extra placement. A named-space reference is NOT board geometry (L-GEOMBOARD dropped)."),
    "B70": (["HOOK", "S-SOR", "F-TRIG", "A-OWN", "E-CONVERT", "E-FOODCOST", "E-GOODS"],
            "At the start of harvest-ending rounds, optionally buy crops with food -- a TIMED start-of-round option (not ATWILL)."),
    "D140": (["HOOK", "T-BEFORE", "S-SPACE", "F-AUTO", "A-OWN", "E-GOODS", "ST-PROV"],
             "Each time you take >=4 building resources or animals from an accumulation space, +1 food. Hook only (spurious ONPLAY dropped)."),
    "D119": (["HOOK", "T-BEFORE", "S-SPACE", "F-TRIG", "A-OWN", "E-GOODS", "E-CONVERT"],
             "Before using a Build-Fences/Rooms space, OPTIONALLY get 2 wood or exchange up to 2 wood for reed ('you can' -> F-TRIG, not mandatory)."),
    # Geometry rulings (user, 2026): L-GEOMBOARD = adjacency/reveal-order of action cards, NOT round timing/scheduling.
    "A63": (["HOOK", "T-AFTER", "S-SUB", "F-AUTO", "A-OWN", "E-GOODS"],
            "'Round immediately following a harvest' is round TIMING (fixed every game), not board layout -> L-GEOMBOARD removed."),
    "D22": (["ONPLAY", "E-SCHED", "E-EXTRAPLACE"],
            "Schedules an extra person onto a count-derived round space -- scheduling + extra placement, not board geometry -> L-GEOMBOARD removed."),
    "D20": (["HOOK", "T-BEFORE", "S-SPACE", "F-TRIG", "A-OWN", "E-GRANTSUB", "ST-STACK"],
            "Card holds a POOL of 2 field tiles you plow onto your farm (ST-STACK); the card is not itself a sown/harvested field -> L-CARDFIELD removed."),
    "D144": (["HOOK", "T-AFTER", "S-SPACE", "F-AUTO", "A-OWN", "E-GOODS", "L-GEOMBOARD"],
             "Fishing + its 3 orthogonally ADJACENT action spaces = board adjacency = geometry (user ruling) -> L-GEOMBOARD restored."),
    "E16": (["PASSIVE", "E-FREEFENCE", "L-GEOMFARM"],
            "Free fences on the farmyard-board EDGE = farmyard geometry (L-GEOMFARM), confirmed."),
    "E70": (["L-CARDFIELD", "HOOK", "T-AFTER", "S-SUB", "F-TRIG", "A-OWN", "E-CROPMANIP"],
            "'This card is a field' -> L-CARDFIELD (a card-STRUCTURE tag, not geometry); crop-swap on it is E-CROPMANIP."),
    "B149": (["ONPLAY", "E-PIECECOST", "E-RETURNCOMP", "E-GRANTSUB", "E-FREEFENCE", "E-COSTMOD"],
             "Build a 2-space pasture from 3 returned stables -- ordinary fencing, no geometry code needed (confirmed)."),
    "A85": (["PASSIVE", "E-CAPNEW", "E-PEOPLE", "L-GEOMFARM"],
            "A clay/stone room adjacent to both a field and a pasture holds an extra person -> new person-holder (E-CAPNEW, its taxonomy exemplar) + person-capacity change (E-PEOPLE); farm-tile adjacency = L-GEOMFARM (user ruling; E-CAPGROW is animal-slot-only)."),
    # Occupied-space-placement trio (A25/A130/C150), settled by the user (2026-07): relaxations of the
    # "can't place on an occupied space" rule, exercised WHEN YOU PLACE A WORKER (a standing option, PASSIVE),
    # NOT deferrable at-will actions -> ATWILL dropped.
    "A25": (["PASSIVE", "CAP-ROUND", "L-OCCUPY", "E-EXTRAPLACE", "ST-STORE", "ST-PLACELOG"],
            "Bassinet: once per work phase, place a(nother) person on the marked first-non-accumulating space if only 1 person is there -- a standing relaxation of the occupied-space rule at placement time (PASSIVE, not ATWILL, per user ruling), granting an extra placement onto an occupied space."),
    "A130": (["PASSIVE", "CAP-ROUND", "L-OCCUPY", "E-GRANTACT", "ST-PLACELOG"],
             "Mummy's Boy: once per round, place your 3rd+ person on your 2nd person's space and use it again -- relaxes the occupied-space rule at placement time (PASSIVE, not ATWILL, per user ruling); reusing that space's action = E-GRANTACT."),
    "C150": (["PASSIVE", "L-OCCUPY", "E-GRANTACT", "ST-PLACELOG"],
             "Parrot Breeder: pay 1 grain to use the space your right-hand neighbor just used -- relaxes the occupied-space rule at placement time (PASSIVE, not ATWILL, per user ruling); grain is an ordinary cost (no E-CONVERT/E-GOODS)."),
    "A39": (["HOOK", "T-BEFORE", "S-SPACE", "F-AUTO", "A-OWN", "A-OPP", "L-CARDSPACE", "E-SCORE", "E-OPPTRANSFER", "ST-COUNTER"],
            "Chapel: card is an action space; user gets 3 VP (accrued -> ST-COUNTER), opponents pay you 1 grain first (E-OPPTRANSFER). Confirmed by user."),
    "A102": (["ONPLAY", "ATWILL", "ST-STACK", "E-CONVERT", "E-FOODCOST", "E-GOODS"],
             "Grocer: on-play pile on the card (ST-STACK); at any time buy the top good for 1 food (ATWILL, food-for-good exchange). Confirmed by user. (On the deferred hard-set.)"),
    "C130": (["HOOK", "T-BEFORE", "S-SPACE", "F-TRIG", "A-OWN", "E-SEEDSPACE", "E-EXTRAPLACE"],
             "Outskirts Director: seed 2 reed onto the OTHER accumulation space (E-SEEDSPACE, a named mechanic per user) then place another person (E-EXTRAPLACE)."),
    "C93": (["HOOK", "T-BEFORE", "S-SPACE", "F-TRIG", "A-OWN", "E-SEEDSPACE", "E-EXTRAPLACE"],
            "Inner Districts Director: seed 1 stone onto the OTHER accumulation space (E-SEEDSPACE, same mechanic as C130) then place another person. EXOTIC replaced by the named code."),
    "D91": (["ONPLAY", "E-SCHED", "HOOK", "T-BEFORE", "S-SOR", "F-TRIG", "A-OWN", "E-GRANTSUB", "E-FOODCOST"],
            "Plowman: schedule field tiles onto rounds +4/+7/+10 (E-SCHED); at the START of those rounds optionally plow for 1 food -> T-BEFORE (user ruling)."),
    "E91": (["PASSIVE", "L-EXT", "HOOK", "S-HFEED", "T-BEFORE", "F-TRIG", "A-OWN", "E-GRANTSUB", "E-FOODCOST"],
            "Plow Builder: Joinery buildable via Minor Improvement (PASSIVE+L-EXT); using Joinery during harvest is a feeding-phase conversion -> S-HFEED (user ruling), pay 1 food to plow."),
}
# Accepted as-is (their adjudicated tags stand; clear the low-confidence flag).
RESIDUAL_OK = {"B87", "C100", "D51"}

# Geometry-code verification sweep — corrected tags for the 80 cards carrying a geometry code.
GEOM_FIX = {c["id"]: c for c in json.load(open(os.path.join(DATA, "geom_fixed.json")))["result"]["cards"]}
# User ruling: round-space NUMBER/band references are fixed every game -> NOT L-GEOMBOARD. Strip it.
GROUP_C_STRIP = {"D55", "A124", "A126", "D158", "B137", "D23", "B129"}
# Cross-model Fable adjudication of existing-vs-Fable disagreements (inert until the output exists).
_fadj = os.path.join(DATA, "fable_adj.json")
FABLE_ADJ = {c["id"]: c for c in json.load(open(_fadj))["result"]["cards"]} if os.path.exists(_fadj) else {}


def _norm_codes(codes):
    return list(dict.fromkeys(NORMALIZE.get(x, NORMALIZE.get(x.upper(), x)) for x in codes))


def build_part(kind, resultfile, cardsfile, patch, compare_file=None):
    meta = {c["id"]: c for c in json.load(open(cardsfile))}
    res = json.load(open(resultfile))["result"]["cards"]
    tag, resid, unclear = {}, Counter(), []
    for c in res:
        if c["id"] not in meta:
            continue
        codes = [NORMALIZE.get(x, NORMALIZE.get(x.upper(), x)) for x in c["codes"]]
        note, unc, reviewed, low = c.get("note", ""), c.get("unclear", False), False, False
        if c["id"] in RESIDUAL_FIX:  # user ruling / manual fix — highest precedence
            codes, note = RESIDUAL_FIX[c["id"]]
            unc, reviewed = False, True
        elif c["id"] in patch:  # hand-verified
            codes, note = patch[c["id"]]
            unc = False
        elif c["id"] in FABLE_ADJ:  # cross-model Fable adjudication of a disagreement
            fa = FABLE_ADJ[c["id"]]
            codes, note = fa["codes"], fa.get("reason", "")
            unc, reviewed, low = False, True, bool(fa.get("low_confidence"))
        elif c["id"] in GEOM_FIX:  # geometry-code verification sweep
            g = GEOM_FIX[c["id"]]
            codes, note = g["codes"], g.get("reason", "")
            unc, reviewed, low = False, True, bool(g.get("low_confidence"))
        elif c["id"] in ADJUDICATED:  # high-effort review settled the disagreement
            a = ADJUDICATED[c["id"]]
            codes, note = a["codes"], a.get("reason", "")
            unc, reviewed = False, True
            low = bool(a.get("low_confidence")) and c["id"] not in RESIDUAL_OK
        else:
            nc = c.get("new_category", "").strip()
            if nc:  # unadopted proposal -> flag as EXOTIC + keep the description
                codes = codes + ["EXOTIC"]
                note = (note + " | " if note else "") + "candidate mechanic: " + nc
        codes = _norm_codes(codes)
        if c["id"] in GROUP_C_STRIP:
            codes = [x for x in codes if x != "L-GEOMBOARD"]
        tag[c["id"]] = {"codes": codes, "unclear": unc, "note": note, "reviewed": reviewed, "low": low}
        if unc:
            unclear.append(c["id"])
        resid.update(x for x in codes if x not in CANON)

    def status_of(i):
        if meta[i].get("status") == "wontfix":
            return "wontfix"
        return "impl" if IMPL_FIX.get(i, meta[i]["implemented"]) else "todo"

    def is_residual(i):  # 🔶 — still low-confidence after review (or unclear & not reviewed)
        t = tag.get(i, {})
        return bool(t.get("low")) or (t.get("unclear") and not t.get("reviewed"))

    def is_revisit(i):  # ⚠ — classification understood but genuinely unsettled; think harder before implementing
        return "REVISIT" in tag.get(i, {}).get("codes", [])

    n_impl = sum(1 for i in meta if status_of(i) == "impl")
    n_ban = sum(1 for i in meta if status_of(i) == "wontfix")
    n_rev = sum(1 for i in meta if i in tag and tag[i].get("reviewed"))
    residual = [i for i in meta if is_residual(i)]
    revisit = [i for i in meta if is_revisit(i)]
    L = []
    W = L.append
    W(f"# Part — {kind.title()}s\n")
    W(f"**{len(meta)} {kind}s** — ✅ {n_impl} implemented · 🚫 {n_ban} won't-fix/banned · "
      f"⬜ {len(meta)-n_impl-n_ban} not yet · ⚖ {n_rev} high-effort adjudicated · 🔶 {len(residual)} residual (low-confidence) · "
      f"⚠ {len(revisit)} revisit (unsettled — think harder before implementing).\n")
    if residual:
        W("### Residual — low-confidence, worth a human look\n")
        for i in sorted(residual, key=lambda z: (meta[z]["deck"], meta[z]["number"])):
            W(f"- **{i} {meta[i]['name']}** — _{meta[i]['text']}_ — `{' '.join(tag[i]['codes'])}` — {tag[i]['note']}")
        W("")
    if revisit:
        W("### ⚠ Revisit — classification unsettled, re-derive the codes before implementing\n")
        for i in sorted(revisit, key=lambda z: (meta[z]["deck"], meta[z]["number"])):
            W(f"- **{i} {meta[i]['name']}** — _{meta[i]['text']}_ — `{' '.join(tag[i]['codes'])}` — {tag[i]['note']}")
        W("")
    by_deck = defaultdict(list)
    for i in meta:
        by_deck[meta[i]["deck"]].append(i)
    for deck in sorted(by_deck):
        W(f"### Deck {deck}\n")
        for i in sorted(by_deck[deck], key=lambda z: meta[z]["number"]):
            m = meta[i]
            t = tag.get(i, {"codes": ["(MISSING)"], "note": "", "unclear": False})
            box = {"impl": "✅", "wontfix": "🚫", "todo": "⬜"}[status_of(i)]
            flag = (" 🔶" if is_residual(i) else "") + (" ⚠" if is_revisit(i) else "")
            pcs = f" · [{m['players']}]" if m.get("players") else ""
            cost = f" · cost: {m['cost']}" if m.get("cost") else ""
            pre = f" · prereq: {m['prereq']}" if m.get("prereq") else ""
            pas = " · passing" if m.get("passing") else ""
            W(f"- {box} **{i} {m['name']}**{pcs}{flag}{cost}{pre}{pas}")
            W(f"  - _{m['text']}_")
            W(f"  - `{' '.join(t['codes'])}`" + (f" — {t['note']}" if t["note"] else ""))
        W("")
    W("### Index — cards per code\n")
    idx = defaultdict(list)
    for i, t in tag.items():
        for x in t["codes"]:
            idx[x].append(i)
    for x in sorted(idx):
        ids = sorted(idx[x], key=lambda z: (meta[z]["deck"], meta[z]["number"]))
        W(f"- `{x}` ({len(ids)}): {', '.join(ids)}")
    W("")
    return L, resid, (len(meta), n_impl, n_ban, n_rev), residual


H = ["# Card Implementation Progress\n",
     "_Pipeline: each card was tagged by two independent classification passes against the mechanics taxonomy; the ~290 cards where the passes disagreed on a gating code were then settled by a high-effort adjudication review. A handful of cards are hand-verified. Each entry: player-count (occupations), cost/prereq, verbatim text, and the mechanic codes it uses._\n",
     "_Markers: ✅ implemented (slug registered in `agricola/cards`) · 🚫 won't-fix/banned · ⬜ not yet · ⚖ adjudicated (a high-effort reviewer settled a two-pass disagreement) · 🔶 residual (still low-confidence after review, or unresolved — worth a human look) · ⚠ revisit (classification understood but genuinely unsettled — re-derive the codes before implementing; carries a `REVISIT` tag). Per-card tags are a strong map, not a formal spec._\n",
     "## Legend\n"]
for k, v in LEGEND:
    H.append(f"- **{k}:** {v}")
H.append("")

parts, resids, stats, residuals = [], Counter(), {}, {}
for kind, rf, cf, patch, cmp in [
    ("minor", os.path.join(DATA, "minors_cold.json"), os.path.join(DATA, "minors_cards.json"), PATCH_MIN, os.path.join(DATA, "minors_prev.json")),
    ("occupation", os.path.join(DATA, "occ_cold.json"), os.path.join(DATA, "occ_cards.json"), PATCH_OCC, os.path.join(DATA, "occ_prev.json")),
]:
    lines, resid, st, residual = build_part(kind, rf, cf, patch, cmp)
    parts += lines
    resids.update(resid)
    stats[kind] = st
    residuals[kind] = residual

open(OUT, "w").write("\n".join(H + parts) + "\n")
print(f"wrote {OUT}")
for kind, (n, imp, ban, nrev) in stats.items():
    print(f"  {kind}: {n} | impl {imp} | banned {ban} | todo {n-imp-ban} | adjudicated {nrev} | residual {len(residuals[kind])}")
print("residual unknown codes:", dict(resids))
