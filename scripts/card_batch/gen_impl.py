import json, glob, os, sys
SP=sys.argv[1]; DECK=sys.argv[2]; TIER=sys.argv[3]  # TIER='1','2', or 'all'
TR=SP+"/triage_cde"
import sys as _s; _s.path.insert(0,"scripts")
from card_text import card_slug
NAMES={}
for fn in ["agricola/cards/data/revised_occupations.json","agricola/cards/data/revised_minor_improvements.json"]:
    for c in json.load(open(fn)):
        NAMES[card_slug(c["name"])]=c["name"]
cards=[]
for f in sorted(glob.glob(TR+f"/{DECK}_*.json")):
    s=json.load(open(f))
    if s.get("decision")!="implement": continue
    if TIER!="all" and str(s.get("tier"))!=TIER: continue
    cid=s.get("card_id")
    cards.append({"name": NAMES.get(cid,cid), "card_id": cid, "spec": os.path.basename(f)})
CHEAT="\n".join([
"MACHINERY CHEAT-SHEET (verified 2026-06-30; trust over CLAUDE.md which is stale on cards).",
"- register_occupation(card_id,on_play); register_minor(card_id,*,cost=Cost(),cost_fn=None,min_occupations=0,max_occupations=None,prereq=None,passing_left=False,vps=0,on_play). 'X in supply'=PREREQ not cost. register_scoring(card_id,fn(s,i)->int).",
"- register_auto(event,card_id,eligible(s,i)->bool,apply(s,i)->s,*,any_player=False)=MANDATORY choiceless. register(event,...,eligible(s,i,triggers_resolved)->bool,...,*,mandatory=False)=OPTIONAL declinable. register_action_space_hook(card_id,{spaces}) hosts ATOMIC (forest,fishing,grain_seeds,vegetable_seeds,clay_pit,reed_bank,western_quarry,eastern_quarry,day_laborer,meeting_place); non-atomic already hosted. harvest cards: register/_auto on the printed instant's harvest-window id + register_harvest_window_hook (the harvest_field seam is DELETED). round-entry cards: register/_auto on the preparation-ladder window id (before_round/round_space_collection/start_of_round/replenishment/before_work/start_of_work — CARD_ENGINE_IMPLEMENTATION.md 5d; NO hook registration, hosting is eligibility-driven). register_conditional one-shot latch. register_occupancy_override. harvest_conversions.register_harvest_conversion (side_effect_fn supports food->VP). schedules.schedule_resources/schedule_effect/schedule_animals. CardStore p.card_state.get/set.",
"- 'each time you use [space]'=before_action_space unless text says 'after'/'immediately after'. after-autos fire at Proceed/commit flip (once per action). granted sub-actions OPTIONAL (register) unless 'you must'; gate on legal+affordable. pasture not a CellType: helpers.enclosed_cells/farmyard.pastures. majors on state.board.major_improvement_owners. occupancy via get_space(board,sid).workers!=(0,0). FIREPLACE=(0,1) HEARTH=(2,3) ClayOven5 StoneOven6 Joinery7 Pottery8 Basketmaker9. To grant an animal at a market, BUMP the market pending's `gained` (routes through accommodation) — NEVER add p.animals directly.",
"DEFER (return status 'deferred_by_implementer') when it needs new shared infra OR has a '/' alternative cost / play-variant (a minor 'pay A/B -> get X/Y' is UNSUPPORTED), an immediate un-accommodated animal grant, an at-any-time/standalone conversion, or end-of-turn/return-home/after-harvest timing. PREFER deferring to guessing.",
])
IMPL={"type":"object","additionalProperties":False,"required":["card_id","status","import_line","note"],
 "properties":{"card_id":{"type":"string"},"status":{"type":"string","enum":["pass","fail","deferred_by_implementer"]},
  "import_line":{"type":"string","description":"the `from agricola.cards import <id>  # noqa: F401` line, or '' if not pass"},
  "note":{"type":"string","description":"ONE short line: a deviation/concern/defer-reason, or 'ok'"}}}
VER={"type":"object","additionalProperties":False,"required":["card_id","verdict","issues"],
 "properties":{"card_id":{"type":"string"},"verdict":{"type":"string","enum":["correct","suspect","wrong","skipped"]},
  "issues":{"type":"string","description":"ONE short line: the bug/risk, or 'none'"}}}
J=json.dumps; NL=J("\n\n")
js=[]
js.append("export const meta = { name: 'card-impl-"+DECK+TIER+"', description: 'Implement deck-"+DECK+" tier-"+TIER+" cards from on-disk specs + adversarial verify', phases:[{title:'Implement'},{title:'Verify'}] }")
js.append("const CHEAT="+J(CHEAT)+"; const IMPL_SCHEMA="+J(IMPL)+"; const VERIFY_SCHEMA="+J(VER)+"; const TR="+J(TR)+"; const CARDS="+J(cards)+";")
js.append("""
phase('Implement')
const items = await pipeline(CARDS,
  (c) => agent(
    CHEAT+"""+NL+"""+
    'IMPLEMENT ONE Agricola card (2-player card game). A prior triage wrote a spec JSON. CARD: '+c.name+' (card_id '+c.card_id+').'+"""+NL+"""+
    'STEPS: (1) Read the spec at '+TR+'/'+c.spec+' (plan/ordering_note/template are your guide). (2) Run: ~/miniconda3/bin/python scripts/card_text.py \"'+c.name+'\"  — read VERBATIM text + errata + clarifications; the impl MUST match the text (follow text over spec, note deviations). Watch a \"/\" in the cost or reward = an OR/play-variant -> return status deferred_by_implementer (UNSUPPORTED). If it does not cleanly fit existing machinery, return deferred_by_implementer with the reason in note — do NOT write wrong code. You have NO authority to shift a timing or narrow a mechanism because the difference seems harmless: a deviation you can justify is STILL a defer (an owner audit found a concrete problem behind every past \"harmless\" deviation). Never write a docstring calling a deviation accepted/neutral/established — any deviation requires a dated user ruling, which you do not have. (3) Read the template + 1-2 neighbors; verify any mechanism exists. (4) WRITE agricola/cards/'+c.card_id+'.py (docstring quoting verbatim text + register_* calls). Do NOT edit __init__.py or shared files. (5) WRITE tests/test_card_'+c.card_id+'.py, FIRST line: import agricola.cards.'+c.card_id+'  # noqa: F401 — cover registration, the real-flow effect, eligibility boundaries, optionality, scoping; mirror an existing test_card_*.py. (6) RUN: ~/miniconda3/bin/python -m pytest tests/test_card_'+c.card_id+'.py -q  until green. RETURN ONLY the JSON object (4 fields, no markdown, no prose).',
    { label:'i:'+c.card_id, phase:'Implement', schema:IMPL_SCHEMA, agentType:'general-purpose' }),
  (impl,c) => {
    if (!impl || impl.status!=='pass') return { impl, verify:{card_id:c.card_id, verdict:'skipped', issues: impl?('status='+impl.status+' '+(impl.note||'')):'null'} }
    return agent(
      'ADVERSARIALLY VERIFY one freshly-implemented Agricola card vs its EXACT text. Be skeptical. CARD: '+c.name+' card_id: '+c.card_id+'.'+"""+NL+"""+
      'NOTE: the card is intentionally NOT in agricola/cards/__init__.py yet (wired centrally later) — do NOT flag that. Focus on RULES correctness.'+"""+NL+"""+
      'STEPS: (1) ~/miniconda3/bin/python scripts/card_text.py \"'+c.name+'\" — verbatim text+errata+clarifications. (2) Read agricola/cards/'+c.card_id+'.py + tests/test_card_'+c.card_id+'.py. (3) FIDELITY FIRST: ANY timing or mechanism delta vs the printed text is a finding, regardless of any justification in the module — a docstring claiming an \"accepted approximation\" / \"behaviorally neutral\" shift WITHOUT a dated user ruling is itself a bug (self-ratification; report verdict=wrong). Then check: timing (each-time-you-use=before unless text says after), optionality (you-may=declinable register; mandatory=register_auto), exact thresholds/counts (== vs >=, banded vs cumulative), majors via board.major_improvement_owners, animal grants via helpers.grant_animals (or market gained-bump), never raw p.animals arithmetic, NO \"/\" reward/play-variant treated as pay-both, and what real-game path the TEST does NOT cover (tautology check). RETURN ONLY the JSON object (3 fields). verdict wrong/suspect must put the precise bug/risk in issues.',
      { label:'v:'+c.card_id, phase:'Verify', schema:VERIFY_SCHEMA, agentType:'general-purpose' }).then(v=>({impl,verify:v}))
  })
const ok=items.filter(Boolean), impls=ok.map(x=>x.impl).filter(Boolean)
const passed=impls.filter(i=>i.status==='pass'), failed=impls.filter(i=>i.status==='fail'), deferred=impls.filter(i=>i.status==='deferred_by_implementer')
const flagged=ok.filter(x=>x.verify && (x.verify.verdict==='suspect'||x.verify.verdict==='wrong'))
log('"""+DECK+TIER+""" impl: '+passed.length+' passed, '+failed.length+' failed, '+deferred.length+' deferred; '+flagged.length+' flagged')
return { counts:{total:CARDS.length,passed:passed.length,failed:failed.length,deferred:deferred.length,flagged:flagged.length},
  import_lines:passed.map(i=>i.import_line), passed:passed.map(i=>({card_id:i.card_id,note:i.note})),
  failed:failed.map(i=>({card_id:i.card_id,note:i.note})), deferred:deferred.map(i=>({card_id:i.card_id,note:i.note})),
  flags:flagged.map(x=>({card_id:x.verify.card_id,verdict:x.verify.verdict,issues:x.verify.issues})) }
""")
out=SP+f"/card-impl-{DECK}{TIER}.js"
open(out,"w").write("\n".join(js))
print(f"wrote {out} | {len(cards)} cards | backtick:", "`" in open(out).read())
