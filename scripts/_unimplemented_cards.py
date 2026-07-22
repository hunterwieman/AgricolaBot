"""Shared core for the unimplemented-card listers (minors + occupations).

A card counts as *unimplemented* when its slug is absent from the live card registry
(no card module has registered it), and *not decided against* when the catalog JSON does
not mark it `wontfix`. Everything else — including cards merely *deferred* pending a
rules/infrastructure decision — is listed, because deferred is not the same as rejected.

Both `list_unimplemented_minors.py` and `list_unimplemented_occupations.py` are thin CLIs
over this module; the terminal / markdown / HTML rendering lives here once. The HTML page
grows a "Players" filter row automatically whenever the rows carry a `players` field (they
do for occupations, not for minors).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "agricola" / "cards" / "data"

# Catalog card_category -> the CSS/short key used for colour-coding in the HTML output.
CAT_KEY = {
    "Food Provider": "food",
    "Crop Provider": "crop",
    "Building Resource Provider": "build",
    "Livestock Provider": "stock",
    "Farm Planner": "plan",
    "Actions Booster": "action",
    "Points Provider": "points",
    "Goods Provider": "goods",
}


def card_slug(name: str) -> str:
    """Mirror of play_web._card_slug — slug(json_name) == card_id for implemented cards.
    Apostrophes are dropped (Shepherd's Crook -> shepherds_crook); other non-alnum runs
    collapse to a single '_'."""
    bare = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_")


def implemented_slugs(registry_name: str) -> set[str]:
    """The set of card_ids actually registered (built) in the live catalog.

    registry_name is 'MINORS' or 'OCCUPATIONS' in agricola.cards.specs.
    """
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    import agricola.cards  # noqa: F401  (runs every card module's register_* calls)
    from agricola.cards import specs
    return set(getattr(specs, registry_name))


def _row_id_candidates(row: dict) -> tuple[str, str]:
    """The registry ids a catalog row could be implemented under.

    Usually a card's id is just slug(name). But when a name is ambiguous — two
    printings of the same name, like the B8 and C54 minors both named "Market Stall" —
    the implementation disambiguates with a `slug_<deck><number>` id (e.g.
    `market_stall_c54`). Checking only the base slug would then miss the card and
    falsely report it unimplemented, so we accept either form."""
    base = card_slug(row["name"])
    return base, f"{base}_{row['deck'].lower()}{row['number']}"


def _is_implemented(row: dict, impl: set[str]) -> bool:
    return any(cand in impl for cand in _row_id_candidates(row))


def unimplemented(json_filename: str, registry_name: str) -> list[dict]:
    """Catalog rows that are neither implemented (in the registry) nor marked wontfix,
    sorted by (deck, number). Each row keeps the raw catalog fields."""
    catalog = json.loads((_DATA_DIR / json_filename).read_text())
    impl = implemented_slugs(registry_name)
    rows = [
        r for r in catalog
        if r.get("status") != "wontfix" and not _is_implemented(r, impl)
    ]
    rows.sort(key=lambda r: (r["deck"], r["number"]))
    return rows


# --------------------------------------------------------------------------- outputs


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def print_terminal(rows: list[dict]) -> None:
    by_deck: dict[str, list[dict]] = {}
    for r in rows:
        by_deck.setdefault(r["deck"], []).append(r)
    for deck in sorted(by_deck):
        group = by_deck[deck]
        print(f"\n=== Deck {deck}  ({len(group)} cards) " + "=" * 30)
        for r in group:
            players = f"  ·  {r['players']}" if r.get("players") else ""
            print(f"\n  [{r['deck']}{r['number']}] {r['name']}  ·  {r.get('card_category', '')}{players}")
            for line in _wrap(r["text"], 92):
                print(f"      {line}")
    print()


def markdown(rows: list[dict], noun: str) -> str:
    by_deck: dict[str, list[dict]] = {}
    for r in rows:
        by_deck.setdefault(r["deck"], []).append(r)
    out = [
        f"# {noun} not yet implemented",
        "",
        f"{len(rows)} cards — unimplemented (absent from the live registry) and not marked "
        "`wontfix`. Deferred cards are included.",
    ]
    for deck in sorted(by_deck):
        group = by_deck[deck]
        out += ["", f"## Deck {deck}  ({len(group)} cards)", ""]
        for r in group:
            players = f" · {r['players']}" if r.get("players") else ""
            out.append(f"**{r['deck']}{r['number']}. {r['name']}** — _{r.get('card_category', '')}{players}_")
            out.append(f"  {r['text']}")
            out.append("")
    return "\n".join(out)


def html(rows: list[dict], noun: str) -> str:
    payload = json.dumps(
        [
            {
                "deck": r["deck"], "number": r["number"], "name": r["name"],
                "category": r.get("card_category", ""), "text": r["text"],
                "players": r.get("players", ""),
            }
            for r in rows
        ],
        ensure_ascii=False,
    )
    return (
        _HTML_TEMPLATE
        .replace("__PAYLOAD__", payload)
        .replace("__CATKEY__", json.dumps(CAT_KEY))
        .replace("__TOTAL__", str(len(rows)))
        .replace("__NOUN__", noun)
        .replace("__NOUN_LC__", noun.lower())
    )


def run(*, json_filename: str, registry_name: str, noun: str) -> None:
    """Shared CLI entry point for both listers. `noun` is the human label (e.g.
    'Minor Improvements' / 'Occupations') used in headings and titles."""
    ap = argparse.ArgumentParser(
        description=f"List unimplemented {noun.lower()} (not in the {registry_name} "
        "registry, not marked wontfix).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--deck", help="restrict to one deck letter (A–E)")
    ap.add_argument("--category", help="restrict to one card_category (e.g. 'Food Provider')")
    ap.add_argument("--players", help="restrict to one player-count band (e.g. '3+'); occupations only")
    ap.add_argument("--count", action="store_true", help="print only the tallies, no card list")
    ap.add_argument("--markdown", metavar="PATH", help="write the list as markdown to PATH")
    ap.add_argument("--html", metavar="PATH", help="write the filterable web page to PATH")
    args = ap.parse_args()

    rows = unimplemented(json_filename, registry_name)
    if args.deck:
        rows = [r for r in rows if r["deck"].upper() == args.deck.upper()]
    if args.category:
        rows = [r for r in rows if r.get("card_category", "").lower() == args.category.lower()]
    if args.players:
        rows = [r for r in rows if r.get("players", "") == args.players]

    if args.markdown:
        Path(args.markdown).write_text(markdown(rows, noun))
        print(f"wrote {len(rows)} cards to {args.markdown}")
    if args.html:
        Path(args.html).write_text(html(rows, noun))
        print(f"wrote {len(rows)} cards to {args.html}")
    if (args.markdown or args.html) and not args.count:
        return

    if not args.count:
        print_terminal(rows)

    by_deck = Counter(r["deck"] for r in rows)
    by_cat = Counter(r.get("card_category", "") for r in rows)
    print(f"Total unimplemented (not wontfix): {len(rows)}")
    print("  by deck:     " + "  ".join(f"{d}:{n}" for d, n in sorted(by_deck.items())))
    print("  by category: " + "  ".join(f"{c}:{n}" for c, n in sorted(by_cat.items(), key=lambda x: -x[1])))
    if any(r.get("players") for r in rows):
        by_pl = Counter(r.get("players", "") for r in rows)
        print("  by players:  " + "  ".join(f"{p}:{n}" for p, n in sorted(by_pl.items())))


# The self-contained filterable page. CSP-safe (no external assets). The "Players" filter
# row builds itself only when the data carries a players field, so the same template serves
# minors (no players) and occupations (players).
_HTML_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unimplemented __NOUN__ — AgricolaBot</title>
<style>
:root{--bg:#efe7d6;--panel:#f7f1e3;--card:#fffdf6;--ink:#2e271d;--muted:#7a6f5c;
 --line:#ddd0b4;--accent:#8f2d24;--accent-soft:#c76a4a;--food:#c9791f;--crop:#5c7a35;
 --build:#7b6a55;--stock:#a05a3c;--plan:#3f6d70;--action:#8f2d24;--points:#6a4d86;--goods:#b8912b;
 --shadow:0 1px 2px rgba(60,45,20,.10),0 3px 12px rgba(60,45,20,.06);}
@media (prefers-color-scheme:dark){:root{--bg:#1b1712;--panel:#241f18;--card:#2b2419;--ink:#ece2cf;
 --muted:#a3947a;--line:#3d3427;--accent:#d3705f;--accent-soft:#e08f6f;--food:#e0a24e;--crop:#94b063;
 --build:#b4a284;--stock:#cf8460;--plan:#6fa6a8;--action:#d3705f;--points:#b193d0;--goods:#dcb84e;
 --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.3);}}
:root[data-theme="light"]{--bg:#efe7d6;--panel:#f7f1e3;--card:#fffdf6;--ink:#2e271d;--muted:#7a6f5c;
 --line:#ddd0b4;--accent:#8f2d24;--accent-soft:#c76a4a;--food:#c9791f;--crop:#5c7a35;--build:#7b6a55;
 --stock:#a05a3c;--plan:#3f6d70;--action:#8f2d24;--points:#6a4d86;--goods:#b8912b;
 --shadow:0 1px 2px rgba(60,45,20,.10),0 3px 12px rgba(60,45,20,.06);}
:root[data-theme="dark"]{--bg:#1b1712;--panel:#241f18;--card:#2b2419;--ink:#ece2cf;--muted:#a3947a;
 --line:#3d3427;--accent:#d3705f;--accent-soft:#e08f6f;--food:#e0a24e;--crop:#94b063;--build:#b4a284;
 --stock:#cf8460;--plan:#6fa6a8;--action:#d3705f;--points:#b193d0;--goods:#dcb84e;
 --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.3);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 80px}
.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-family:Georgia,"Iowan Old Style",serif;font-weight:700;font-size:30px;line-height:1.15;margin:6px 0 8px;text-wrap:balance}
.lede{color:var(--muted);max-width:60ch;margin:0}.lede b{color:var(--ink);font-variant-numeric:tabular-nums}
.controls{position:sticky;top:0;z-index:5;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:22px 0 26px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:12px}
.search{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.search input{border:0;background:transparent;color:var(--ink);font-size:15px;width:100%;outline:none}
.search svg{flex:0 0 auto;opacity:.5}
.chips{display:flex;flex-wrap:wrap;gap:7px;align-items:center}
.chips.hide{display:none}
.chips .lbl{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-right:2px;min-width:62px}
.chip{font-size:12.5px;padding:5px 11px;border-radius:20px;border:1px solid var(--line);background:var(--card);color:var(--muted);cursor:pointer;user-select:none;font-variant-numeric:tabular-nums;transition:all .12s;font-family:inherit}
.chip:hover{border-color:var(--accent-soft);color:var(--ink)}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.chip.cat[aria-pressed="true"]{background:var(--c);border-color:var(--c);color:#fff}
.chip .n{opacity:.65;margin-left:5px;font-size:11px}.chip[aria-pressed="true"] .n{opacity:.85}
.deckgroup{margin-bottom:34px}
.deckgroup h2{font-family:Georgia,serif;font-size:19px;margin:0 0 4px;display:flex;align-items:baseline;gap:10px;border-bottom:2px solid var(--line);padding-bottom:8px}
.deckgroup h2 .cnt{font-size:13px;color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--c);border-radius:9px;padding:13px 15px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:7px}
.card .row1{display:flex;align-items:center;gap:9px}
.badge{font-family:Georgia,serif;font-size:12px;font-weight:700;color:#fff;background:var(--c);padding:2px 7px;border-radius:5px;flex:0 0 auto;font-variant-numeric:tabular-nums}
.pill{font-size:10.5px;font-weight:600;color:var(--muted);border:1px solid var(--line);border-radius:20px;padding:1px 7px;flex:0 0 auto;font-variant-numeric:tabular-nums}
.card .name{font-weight:650;font-size:15.5px;line-height:1.2}
.card .cat{margin-left:auto;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--c);font-weight:600;white-space:nowrap}
.card .text{color:var(--muted);font-size:13.5px;line-height:1.48}
mark{background:var(--accent-soft);color:#fff;border-radius:2px;padding:0 1px}
.empty{color:var(--muted);text-align:center;padding:60px 0;font-size:16px}
.count-row{display:flex;align-items:center;gap:10px;margin:-8px 0 20px}
.count-line{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.addall{margin-left:auto;font-family:inherit;font-size:12px;padding:5px 11px;border-radius:20px;border:1px solid var(--line);background:var(--card);color:var(--muted);cursor:pointer;white-space:nowrap}
.addall:hover{border-color:var(--accent-soft);color:var(--ink)}
.selbtn{flex:0 0 auto;width:22px;height:22px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--muted);cursor:pointer;font-size:15px;line-height:1;display:flex;align-items:center;justify-content:center;font-family:inherit;transition:all .12s}
.selbtn:hover{border-color:var(--accent-soft);color:var(--accent)}
.selbtn[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),var(--shadow)}
#tray{position:fixed;right:18px;bottom:18px;width:304px;max-width:calc(100vw - 36px);background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.28);z-index:20;display:flex;flex-direction:column;max-height:min(70vh,540px)}
.tray-head{display:flex;align-items:center;gap:9px;padding:12px 14px;cursor:pointer;user-select:none}
.tray-head h3{margin:0;font-family:Georgia,serif;font-size:15px;font-weight:700}
.tray-head .c{background:var(--accent);color:#fff;font-size:12px;font-weight:700;border-radius:20px;padding:1px 8px;font-variant-numeric:tabular-nums}
.tray-head .caret{margin-left:auto;color:var(--muted);font-size:12px;transition:transform .2s}
#tray.collapsed{max-height:none}
#tray.collapsed .caret{transform:rotate(180deg)}
#tray.collapsed .tray-body{display:none}
.tray-body{display:flex;flex-direction:column;min-height:0;border-top:1px solid var(--line)}
#trayList{overflow-y:auto;padding:8px;display:flex;flex-direction:column;gap:5px}
.tray-item{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:7px;padding:5px 8px;font-size:13px}
.ti-badge{font-family:Georgia,serif;font-size:11px;font-weight:700;color:#fff;background:var(--c);padding:1px 6px;border-radius:4px;flex:0 0 auto;font-variant-numeric:tabular-nums}
.ti-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ti-x{border:0;background:transparent;color:var(--muted);cursor:pointer;font-size:14px;padding:2px 4px;border-radius:4px}
.ti-x:hover{color:#fff;background:var(--accent)}
.tray-empty{color:var(--muted);font-size:12.5px;padding:18px 14px;text-align:center;line-height:1.5}
.tray-foot{display:flex;gap:8px;padding:10px;border-top:1px solid var(--line)}
.tray-foot button{flex:1;font-family:inherit;font-size:12.5px;padding:7px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.tray-foot button:hover{border-color:var(--accent-soft)}
.tray-foot .clear:hover{color:#fff;background:var(--accent);border-color:var(--accent)}
footer{margin-top:40px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:16px}
</style></head><body><div class="wrap">
<header><div class="eyebrow">AgricolaBot · Card catalog</div>
<h1>__NOUN__ not yet implemented</h1>
<p class="lede">Every __NOUN_LC__ not in the live registry and not marked <i>won't-fix</i>. <b>__TOTAL__</b> cards across decks A–E.</p></header>
<div class="controls">
 <div class="search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
 <input id="q" type="text" placeholder="Search name or card text…" autocomplete="off"></div>
 <div class="chips" id="deckChips"><span class="lbl">Deck</span></div>
 <div class="chips" id="catChips"><span class="lbl">Category</span></div>
 <div class="chips hide" id="playerChips"><span class="lbl">Players</span></div></div>
<div class="count-row"><span class="count-line" id="countLine"></span><button class="addall" id="addAll">＋ Add all shown</button></div><div id="list"></div>
<footer>Generated by the unimplemented-card lister · reflects the registry at generation time · your selection is saved in this browser</footer></div>
<aside id="tray"><div class="tray-head" id="trayHead"><h3>To implement</h3><span class="c" id="trayCount">0</span><span class="caret">▾</span></div>
<div class="tray-body"><div id="trayList"></div>
<div class="tray-foot"><button id="copyBtn">Copy list</button><button class="clear" id="clearBtn">Clear</button></div></div></aside>
<script>
const DATA=__PAYLOAD__,CATKEY=__CATKEY__;
const STORE="agri-implement-__NOUN_LC__";
const state={q:"",deck:new Set(),cat:new Set(),players:new Set()};
const byId={};DATA.forEach(d=>{byId[d.deck+d.number]=d;});
let selected=new Set();
try{const s=JSON.parse(localStorage.getItem(STORE));if(Array.isArray(s))selected=new Set(s.filter(id=>byId[id]));}catch(e){}
function save(){try{localStorage.setItem(STORE,JSON.stringify([...selected]));}catch(e){}}
function catClass(c){return CATKEY[c]||"goods";}
function toggle(set,val,el){if(set.has(val)){set.delete(val);el.setAttribute('aria-pressed','false');}
 else{set.add(val);el.setAttribute('aria-pressed','true');}}
function addChips(container,values,set,opts){
 values.forEach(v=>{const n=DATA.filter(opts.match(v)).length,el=document.createElement('button');
  el.className='chip'+(opts.cat?' cat':'');el.setAttribute('aria-pressed','false');
  if(opts.cat)el.style.setProperty('--c',`var(--${catClass(v)})`);
  el.innerHTML=`${opts.label(v)}<span class="n">${n}</span>`;
  el.onclick=()=>{toggle(set,v,el);render();};container.appendChild(el);});}
function buildChips(){
 const decks=[...new Set(DATA.map(d=>d.deck))].sort();
 addChips(document.getElementById('deckChips'),decks,state.deck,{match:v=>d=>d.deck===v,label:v=>`Deck ${v}`});
 const cats=[...new Set(DATA.map(d=>d.category))].sort();
 addChips(document.getElementById('catChips'),cats,state.cat,{cat:true,match:v=>d=>d.category===v,label:v=>v});
 const players=[...new Set(DATA.map(d=>d.players).filter(Boolean))].sort();
 if(players.length){const pc=document.getElementById('playerChips');pc.classList.remove('hide');
  addChips(pc,players,state.players,{match:v=>d=>d.players===v,label:v=>`${v} players`});}}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function hl(s,q){s=esc(s);if(!q)return s;try{return s.replace(new RegExp('('+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<mark>$1</mark>');}catch(e){return s;}}
function filtered(){
 const q=state.q.trim().toLowerCase();
 return DATA.filter(d=>{
  if(state.deck.size&&!state.deck.has(d.deck))return false;
  if(state.cat.size&&!state.cat.has(d.category))return false;
  if(state.players.size&&!state.players.has(d.players))return false;
  if(q&&!(d.name.toLowerCase().includes(q)||d.text.toLowerCase().includes(q)))return false;
  return true;});}
function render(){
 const rows=filtered(),list=document.getElementById('list');
 document.getElementById('countLine').textContent=`Showing ${rows.length} of ${DATA.length} cards`+(state.q.trim()?` matching “${state.q.trim()}”`:'');
 if(!rows.length){list.innerHTML='<div class="empty">No cards match these filters.</div>';return;}
 const byDeck={};rows.forEach(r=>{(byDeck[r.deck]=byDeck[r.deck]||[]).push(r);});
 let out='';
 Object.keys(byDeck).sort().forEach(dk=>{const g=byDeck[dk];
  out+=`<section class="deckgroup"><h2>Deck ${dk} <span class="cnt">${g.length} card${g.length>1?'s':''}</span></h2><div class="grid">`;
  g.forEach(r=>{const cc=catClass(r.category),id=r.deck+r.number,on=selected.has(id);
   const pill=r.players?`<span class="pill">${r.players}</span>`:'';
   out+=`<article class="card${on?' sel':''}" style="--c:var(--${cc})"><div class="row1"><button class="selbtn" data-id="${id}" aria-pressed="${on}" title="Add to implement list">${on?'✓':'＋'}</button><span class="badge">${r.deck}${r.number}</span>${pill}<span class="name">${hl(r.name,state.q.trim())}</span><span class="cat">${r.category}</span></div><div class="text">${hl(r.text,state.q.trim())}</div></article>`;});
  out+='</div></section>';});
 list.innerHTML=out;}
function sortedSel(){return [...selected].map(id=>byId[id]).filter(Boolean)
 .sort((a,b)=>a.deck<b.deck?-1:a.deck>b.deck?1:a.number-b.number);}
function renderTray(){
 document.getElementById('trayCount').textContent=selected.size;
 const t=document.getElementById('trayList');
 if(!selected.size){t.innerHTML='<div class="tray-empty">No cards selected yet.<br>Click ＋ on a card to add it.</div>';return;}
 t.innerHTML=sortedSel().map(c=>`<div class="tray-item"><span class="ti-badge" style="--c:var(--${catClass(c.category)})">${c.deck}${c.number}</span><span class="ti-name">${esc(c.name)}</span><button class="ti-x" data-id="${c.deck}${c.number}" title="Remove">✕</button></div>`).join('');}
function setSel(id,on){if(on)selected.add(id);else selected.delete(id);save();
 const btn=document.querySelector(`.selbtn[data-id="${id}"]`);
 if(btn){btn.setAttribute('aria-pressed',on);btn.textContent=on?'✓':'＋';btn.closest('.card').classList.toggle('sel',on);}
 renderTray();}
document.getElementById('list').addEventListener('click',e=>{const b=e.target.closest('.selbtn');
 if(b)setSel(b.dataset.id,!selected.has(b.dataset.id));});
document.getElementById('trayList').addEventListener('click',e=>{const x=e.target.closest('.ti-x');
 if(x)setSel(x.dataset.id,false);});
document.getElementById('addAll').addEventListener('click',()=>{filtered().forEach(d=>selected.add(d.deck+d.number));save();render();renderTray();});
document.getElementById('clearBtn').addEventListener('click',()=>{if(!selected.size||confirm('Clear all '+selected.size+' selected cards?')){selected.clear();save();render();renderTray();}});
document.getElementById('copyBtn').addEventListener('click',e=>{const cards=sortedSel();
 const txt=cards.map(c=>`${c.deck}${c.number}. ${c.name}`).join('\n');
 navigator.clipboard.writeText(txt).then(()=>{const btn=e.target;const o=btn.textContent;btn.textContent=`Copied ${cards.length}!`;setTimeout(()=>btn.textContent=o,1400);}).catch(()=>{});});
document.getElementById('trayHead').addEventListener('click',()=>document.getElementById('tray').classList.toggle('collapsed'));
document.getElementById('q').addEventListener('input',e=>{state.q=e.target.value;render();});
buildChips();render();renderTray();
</script></body></html>"""
