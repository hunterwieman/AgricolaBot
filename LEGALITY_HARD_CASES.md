# Legality hard cases — the mechanisms that break state-read legality

> **Problem catalog only (2026-07-09). No solutions here.** This document describes what
> makes legality checks difficult in the card game — the mechanisms, worked card
> interactions, and the complete card lists per mechanism — as decision input for a design
> the user is making. Sources: three full-catalog censuses in this directory
> (`CENSUS_AT_ANY_TIME.md`, `CENSUS_REACTIVE_TRIGGERS.md`, `CENSUS_COST_IMPOSITION.md`)
> plus code reads of `agricola/legality.py` and implemented card modules. Card text is
> verbatim-checkable via `python scripts/card_text.py <slug>`. Implemented = the module
> `agricola/cards/<slug>.py` exists.
> `PLACEMENT_REACHABILITY_DESIGN.md` contains earlier solution sketches; those are **on
> hold** and are not the plan of record.

## 0. The baseline being broken

Today a placement is legal iff its per-space predicate holds on the **current state**
(`legal_placements` → `FAMILY_GAME_LEGALITY` / `CARD_GAME_LEGALITY`). Several predicates
are resource-gated — Fencing needs an affordable pasture commit, both renovation spaces
need `_can_renovate`, Grain Utilization needs a sowable seed — **grain or veg** — with an
empty field, or a bake source (`_can_sow or _can_bake_bread`), card-mode Lessons
needs a *payable* occupation, the improvement spaces need an affordable build/play.
Sub-action choices inside a turn are gated the same way (`_can_renovate` at
ChooseSubAction time, the play-occupation enumerator withholding unpayable commits).
Costs resolve through chokepoints (`effective_payments` / `can_pay` — formulas,
reductions, conversions) and food through the liquidation-aware `_payable`.

All of this rests on two assumptions:

- **(A1) What you hold now is what you can spend when the bill arrives.**
- **(A2) Non-resource preconditions (house material, room/field/stable counts, empty
  cells, hand contents) are stable between the decision and the work.**

Every mechanism below breaks A1 or A2. They also **compose**: most real difficulty comes
from pairs and triples, so each section carries a worked interaction.

---

## M1 — Income attached to using a space (before-window grants)

**What it is.** "Each time (before) you use [space], you get X." The goods arrive after
the placement decision but before the space's mandatory work — so the placement-time
predicate under-counts what the player will hold at pay time. Breaks A1 in the
*under-offering* direction: legal placements are denied.

**Worked interaction (grant × cost-modifier).** Round 8; House Redevelopment sits on the
round-5 slot; the round-8 card was just revealed, so Sweep's target ("the card left of
the most recently placed") is House Redevelopment. Player: 3-room wood house, 1 wood,
1 reed, 0 clay, owns **Sweep** and **Frame Builder**. Renovation costs 3 clay + 1 reed;
Frame Builder's conversion makes (1 clay + 1 wood + 1 reed) a second way to pay. At 0
clay the predicate says illegal — but placing fires Sweep (+2 clay) first, and 2 clay +
1 wood + 1 reed pays via Frame Builder's variant. Note the composition: the grant is only
sufficient *because* a cost card changes what the goods must be.

**Second worked interaction (grant × seed gate, no cost card needed).** Grain
Utilization is a stage-1 card, so it can be the most recent reveal. A player with an empty
field but **no grain, no veg, and no bake source** who owns **Outrider** ("each time
before you use the most recently revealed card, you get 1 grain") is denied placement by
`_legal_grain_utilization` (`_can_sow or _can_bake_bread`) — `_can_sow` needs grain-or-veg
in supply — even though Outrider's grain arrives before the mandatory sow/bake and would
enable the sow.

**Sub-action-level variant.** The same mismatch exists one level down, and the codebase
contains both a handled and an unhandled member (verified 2026-07-09):

- **The Lessons-payment family is systematically handled** (verified 2026-07-09): every
  implemented card that injects or substitutes occupation-payment food inside the play
  window — **Paper Maker** (wood→food), **Bookshelf** (+3 food), **Tasting** (grain→4
  food), **Forest School** (each food payable in wood) — registers into
  `OCCUPATION_FOOD_SOURCES`, and `_payable_occupation` (legality.py:488–515) simulates
  firing each owned source before declaring an occupation unaffordable. This seam is the
  engine's one existing systematic gate-awareness mechanism for pre-work income. (Future
  members needing the same wiring: patron, whale_oil — the latter pays out *card-held*
  food before occupation plays, so it is also M8's shape. The bake side has its own
  gate-awareness precedent: hand_truck and potter_ceramics both registered
  `_can_bake_bread` extensions.)
- **Thresher** (implemented) sells 1 grain for 1 food "immediately before" Grain
  Utilization / Farmland / Cultivation — and is NOT counted anywhere: no sow/seed
  analog of that seam exists, so the placement gates are blind to the buy.
  **Confirmed live under-offer** (§13).

**Cards whose grant can precede a costed obligation (the legality-relevant set):**

| Slug | Deck# | Impl? | Grant | Which gates it can flip (user-verified 2026-07-09; systematic matrix pending) |
|---|---|---|---|---|
| brook | B56 | no | +1 food, four spaces above Fishing | the round-1 slot can BE the Major/Minor Improvement space (food pays food-cost minors and, via wood_expert, majors — M1b) or Grain Utilization (food buys the seed via Thresher) |
| master_workman | A126 | no | +1 wood/clay/reed/stone by slot, on slots 1–4 | slots 1–4 hold the stage-1 cards: the improvement space takes any of the four resources natively; Fencing takes slot-1 wood natively and slot-2 clay via rammed_clay; Grain Utilization takes slot-2 clay via potter_ceramics; the Sheep Market slot is inert |
| knapper | A124 | no | +1 stone on slots 5–7 (= stage 2) | stage 2 includes House Redevelopment (stone renovation) |
| sweep | B120 | no | +2 clay on the left-of-most-recent card | targets = slots 1–6 and 8–12: House Redevelopment (clay renovation), Major/Minor Improvement (clay pays improvements directly), **Fencing** (clay pays fences with Rammed Clay), **Grain Utilization** (clay → grain → bake with Potter Ceramics) |
| silokeeper | B112 | no | +1 grain on the last-harvest-round card | slot 4 can be Grain Utilization (seed); **renovation spaces + Fencing via Millwright** (grain replaces building resources) |
| outrider | C160 | no | +1 grain on most-recent card | 4+; same gates as Silokeeper — Grain Utilization directly, renovation/Fencing via Millwright |
| pioneer | E105 | no | +1 resource of choice +1 food on most-recent card | every resource-gated space; also M2 |
| legworker | C117 | no | +1 wood using a space adjacent to your person | Fencing directly; **renovation via Frame Builder / Brushwood Collector** (wood replaces clay/stone/reed) |
| bean_counter | D158 | no | food banked per slot-1–8 use; pays out at 3 | 4+; slots 1–8 include the Major/Minor Improvement space — food-cost minors and majors/minors via wood_expert (M1b) — **and Grain Utilization via Thresher** (payout food buys the seed; whether the payout lands in time for Thresher's "immediately before" buy is an open user ruling — see §14); only the boundary-crossing payout (banked 2 → 3 mid-window) is legality-relevant, later-turn food is ordinary supply |
| bookshelf | D49 | **yes** | +3 food before an occupation play | sub-action level: the occupation's own cost — **handled** at the gate via the occupation-food-source simulation (verified 2026-07-09) |
| patron | D152 | no | +2 food before later occupation plays | 4+; Bookshelf's shape — would need the same gate wiring when built |
| tasting | B63 | **yes** | 1 grain → 4 food, before paying the occupation cost (Lessons) | **handled** — occupation-food-source seam (verified 2026-07-09) |
| paper_maker | B109 | **yes** | pay 1 wood → 1 food per occupation, immediately before each occupation play | **handled** — the seam's original member |
| stock_protector | B94 | no | +2 wood, explicitly before using Fencing | Fencing natively; the card's *other* clause (extra person placement) sits in the temporary-worker defer family — the income clause is an M1 row regardless |
| hammer_crusher | D14 | no | +2 clay +1 reed immediately before renovating to stone, plus a Build Rooms grant | single-handedly covers both halves of the renovation gate (reed + material) on either renovation space |
| wood_workshop | B75 | **yes** | +1 wood before playing or building ANY improvement | official clarification: *"you are able to pay for the improvement with just the wood given by this card"* — yet no gate counts it (§13 #6, **confirmed under-offer**) — text verified 2026-07-09 |
| wood_barterer | D119 | no | before using a space with a Build Fences or Build Rooms action: choose +2 wood OR up to 2 wood → 1 reed each | Fencing (wood), Farm Expansion (wood/reed), renovation-space fences; clarification: literal action spaces only, never card-granted actions. An *optional* pre-work grant — legality counts it existentially per the 2026-07-09 ruling — text verified 2026-07-09 |
| forest_campaigner | C158 | no | +1 food before placing ANY person, when ≥8 wood sits on accumulation spaces | 4+; the only *universal* pre-placement income found — its food reaches every food-relevant gate (Lessons, food-cost minors, wood_expert majors, Thresher seed-buys) whenever the wood condition holds — text verified 2026-07-09 |
| field_merchant | B103 | no | on declining a Minor/Major Improvement action: 1 food/vegetable instead | official clarification: *"you can place onto the Major Improvement space just to decline it"* — i.e. the card makes the improvement-space placement **legal with nothing affordable** (declining becomes a legal use). A gate change by clarification, not income — text verified 2026-07-09 |
| young_farmer | D112 | no | +1 grain on using the improvement space, plus an *afterward* Sow action | marginal for legality (the grain matters only for a grain-cost card-mode minor; the Sow grant is post-work) — text verified 2026-07-09 |
| vegetable_vendor | E141 | no | at the improvement space: +1 veg; at Vegetable Seeds: a granted Major-or-Minor Improvement action | 3+; the veg half is marginal (veg-cost minors); the Vegetable Seeds half is a route grant on an ungated space, no placement-legality role — text verified 2026-07-09 (an earlier ingestion halved this card) |

**Completeness note (updated 2026-07-09):** the ordinary "each time you use [space]"
hook family — excluded from the earlier censuses — has now been swept for before-window
income on the gated spaces; it contributed tasting, paper_maker, stock_protector,
hammer_crusher, young_farmer, and vegetable_vendor above. The sweep also re-nominated
wholesaler and new_market on a stage-assignment error (it placed gated stage cards on
round slots 8–11; stage bands are fixed, and the slots-8–11 spaces are all ungated) —
their no-legality-role verdict stands.

**Grants with no identified placement-legality role (income only — user assessment
2026-07-09):** wholesaler (B137), new_market (D55, implemented), pig_stalker (D165). Their
spaces (Vegetable Seeds, the animal markets, Eastern Quarry) are gated on availability /
accumulation only, never on the placer's resources — so the grant can never be the thing
that flips legality. The only way these become relevant is a future tax pricing those
spaces, and the cost-imposition census found none. (chairman (D139) was listed here
earlier and is fully irrelevant — see M9.)

The gate lists above are user-verified instances; the systematic derivation is the
**good → gate matrix** in M1b below, compiled from the live cost-modifier registries.

---

## M1b — The good → gate matrix

Compiled 2026-07-09 from the cost-modifier registrations in the implemented card modules
plus a catalog sweep for unimplemented cost-substitution cards. Rows = a good a grant
could deliver; columns = the resource-gated placements. "native" = the printed costs
already take this good; "via <card> (impl)" = an implemented conversion card makes it
usable; "(unimpl)" = the conversion exists in the catalog but is not implemented — the
cell activates only if that card is ever built (it does NOT mean the interaction is
wrong). The seven resource-gated placements: Fencing, the two renovation spaces
(House/Farm Redevelopment share `_can_renovate`), Grain Utilization, Cultivation (its sow
leg — the plow leg is free, so goods matter only when no plowable cell exists), the
Major/Minor Improvement space, **Farm Expansion** (`_can_build_room or _can_build_stable`
— legality.py:817), and card-mode Lessons.

| Good | Fencing | Renovations | Grain Util. | Cultivation (sow) | Major/Minor Impr. | Farm Expansion | Lessons |
|---|---|---|---|---|---|---|---|
| **wood** | native | via frame_builder (impl) — 1 wood covers 2 clay or 2 stone · via brushwood_collector (unimpl) — 1 wood covers the reed | — | — | native (wood-cost majors/minors) | native (rooms, stables) | via **forest_school (impl)** — each food of an occupation cost payable in wood (gate-aware through the food-source seam) |
| **clay** | via rammed_clay (impl) — clay for wood, 1:1, unlimited | native | via potter_ceramics (impl) — 1 clay → 1 grain before a bake; also unlocks the bake gate at 0 grain | — | native | native for clay-house rooms (+ clay_plasterer/clay_supports formulas, impl) · via feed_fence (unimpl) — clay pays the wood for exactly 1 stable per Build-Stables action | — |
| **stone** | — | native | — | — | native | native for stone-house rooms | — |
| **reed** | — | native (1 reed) | — | — | native (reed-cost improvements) | native (rooms' 2 reed) | — |
| **grain** | via millwright (impl) — grain replaces ≤2 building resources per action | via millwright (impl) | native (seed + bake fuel) | native | — (millwright does NOT cover build_major / play_minor) | via millwright (impl) — rooms and stables | via **tasting (impl)** — 1 grain → 4 food before paying the occupation cost (gate-aware) |
| **veg** | — | — | native (sow) | native | veg-cost minors | — | — |
| **food** | — | — | via **thresher (impl)** — buy 1 grain for 1 food "immediately before" using the space (its Farmland leg gates nothing — plowing is free) | via thresher (impl) — same buy, feeding the sow leg | via **wood_expert (impl)** — 1 food covers up to 2 wood on ANY major or minor · the 59 food-cost minors · bottles' per-person cost_fn | — | native (occupation cost) |

Three families multiply every row without adding a good:

- **Threshold-lowerers** — reductions (implemented: bricklayer, lumber_mill,
  master_bricklayer, roof_ladder, straw_thatched_roof; unimplemented: stonecutter,
  chimney_sweep, rock_beater, carpenters_apprentice, house_artist, furnisher, blueprint)
  and whole-cost formulas (implemented: carpenter, carpenters_parlor, clay_plasterer,
  clay_supports, wooden_hut_extender; unimplemented: oven_site, basket_weaver,
  braid_maker): gates flip with *fewer* granted goods.
- **Free-fence sources** (briar_hedge, ash_trees, hedge_keeper, field_fences — all
  implemented): flip Fencing with zero goods; already inside `_any_legal_pasture_commit`.
- **Future wideners** (unimplemented, would add cells): site_manager (food → one of
  each resource on its granted major build), wood_barterer (wood → reed before
  room/fence actions), **working_gloves** (any 1 building resource in place of ≤2 food
  of an occupation cost — puts every resource row into the Lessons column),
  **art_teacher** (3+; food sitting ON the Traveling Players space pays occupation
  costs — board-goods as payment, M8's shape), the M5 at-any-time converters, and the
  M8 Grocer family (food → arbitrary goods — would put food in almost every cell).
- **Route expanders** (unimplemented family; member texts **not yet individually
  verified** except where noted — the extraction-only re-run re-quoted the family and
  its spot-checked quotes ran 6/6 accurate, full diff pending): cards that let a MAJOR
  be built through a Minor-Improvement action — blueprint, carpenters_yard,
  craftsmanship_promoter, plow_builder, braid_maker, elder_baker, ambition (and
  wooden_shed, the reverse: a minor playable only via a Major action), plus
  vegetable_vendor's Vegetable-Seeds half (verified). witches_dance_floor was in this
  family and is **banned** (user ruling 2026-07-09; `status: wontfix` in the data — a
  field/occupation/Fireplace chimera playable only via a Minor action). These don't add
  goods-cells; they widen *which plays satisfy the improvement gate* and multiply the
  improvement column's reach. **Official precedent that route substitution changes a
  placement gate:** freshman (A97, status wontfix/banned) carries the clarification
  *"You may use the Grain Utilization space while being unable to Sow or Bake Bread,
  as this card substitutes the Bake Bread action"* — the publisher's own ruling that a
  granted substitute action legalizes an otherwise-illegal placement (text verified
  2026-07-09). **Second official instance, on an unbanned card:** agrarian_fences (B26,
  unimplemented) — a Build Fences action instead of one of Grain Utilization's two — is
  clarified *"You can take a 'Build Fences' action in this way without the ability to
  sow or bake"*: the substitution legalizes the space outright (text verified
  2026-07-09). Related, ruling-dependent: small_potters_oven (C60, unimplemented) builds
  a Clay/Stone Oven "each time before you get a Bake Bread action" — whether that can
  bootstrap the bake gate (build the baker to legalize the bake) needs a ruling.
- **Precondition wideners** (unimplemented): love_for_agriculture (B72) lets 1–2-cell
  pastures *count as fields* for sowing — the Grain Utilization / Cultivation gates'
  "empty field" half becomes satisfiable by pasture geometry, a state-equivalence
  rather than a goods-cell (text verified 2026-07-09). The card-field family
  (wood_field D75, rock_garden E80 — cards that ARE fields for wood/stone) raises a
  §14 rules question about whether sowing wood/stone satisfies sow-gated placements.

Two hygiene flags from the registry sweep — **both verified 2026-07-09**: (a)
frame_builder's and bricklayer's "non-renovate clauses are inert" docstrings are
**stale**: all three paths (build_room / build_major / play_minor) route through the
`action_kind`-keyed chokepoint, and end-to-end tests prove the discounts/conversions
apply (`test_cost_modifiers.py:241/:252`, `test_cards_cost_cards.py:161/:182/:267`); the
stale artifacts are the two module docstrings (frame_builder.py:13–16,
bricklayer.py:11–15) and `test_cost_modifiers.py`'s line-4 header ("no engine wiring
yet"). (b) `register_baking_spec_extension` (legality.py:183) is **dead by design**:
zero production registrants (one test-only call); built for future non-major
baking-source cards; `winnowing_fan` only *reads* `baking_specs_for_player`, and
existing non-major bake cards ride the bake primitive instead.

---

## M2 — The grant's content is a player choice

**What it is.** A mandatory grant whose *content* the player picks (Pioneer: "you get 1
building resource of your choice and 1 food"). Legality becomes existential over the
choice — and after placement, the choice itself can strand the mandatory work if picked
badly. Breaks A1 twice: at the placement gate (is there *some* choice that works?) and at
the choice gate (which options leave the work completable?).

**Worked interaction.** Pioneer owner, 0 wood, places on Fencing when Fencing is the most
recent card. The placement is completable only via choosing wood; choosing clay leaves
the mandatory ≥1-pasture build unaffordable. Two grant-choice cards on one host compound
this: each card's viable options depend on what the *other* still-unfired grant will add.

**Worked interactions with conversion cards (the choice set widens/shifts with the
tableau, 2026-07-09):**

- **Pioneer × Rammed Clay on Fencing.** Same 0-wood player, now owning Rammed Clay (clay
  pays fences 1:1). The enabling choices are {wood, clay}, not {wood} — both the
  pre-placement check ("does some choice complete the work?") and the post-placement
  option filter must know the conversion, or clay is wrongly withheld (and with it, the
  strictly better line of banking the rarer good).
- **Pioneer × Frame Builder on House Redevelopment.** Player holds 1 reed, 0 clay, 0
  wood, 2 rooms (renovation base: 2 clay + 1 reed). Choosing clay gives 1 clay — short.
  Choosing **wood** completes it: Frame Builder's variant replaces the 2 clay with 1
  wood, so (1 wood + 1 reed) pays. Without Frame Builder, wood is never a renovation
  currency; with it, wood is the *only* enabling choice here. Which options survive is a
  function of the whole tableau, not the printed cost.
- Pioneer's food rider composes independently: at the improvement space, the +1 food
  feeds wood_expert / food-cost minors (M1b's food row) on top of whichever resource is
  chosen.

**Cards:** pioneer (E105) is the only placement-tied member. Struck from earlier drafts
(2026-07-09): tax_collector (E126) — its choice-income arrives at round start and is
ordinary supply before any placement, so it can never be the thing a gate is blind to;
cottar (E122) — its income lands after paying an improvement cost, i.e. after the host's
only costed mandatory work. patroness (E163) matters only in the multi-occupation
composition documented in M3.

---

## M3 — Optional spending inside a host whose mandatory work has a cost
### (the Writing Desk pattern)

**What it is.** An optional trigger that spends shared resources while the host still owes
mandatory costed work. Firing can make the obligation unpayable. Breaks A1 in the
*over-offering* direction: an offered action leads to a stuck state (the engine's
"non-terminal ⇒ non-empty legal actions" invariant is violated — a hard dead state, not a
bad position).

**Confirmed live instance.** **Writing Desk** (implemented): "each time you use Lessons,
you can play 1 additional occupation for an occupation cost of 2 food." Its guard checks
≥2 playable hand occupations and the 2 food being payable **now** — never the mandatory
Lessons ramp (1 food, given the card's own 2-occupation prerequisite) on the post-spend
state. With exactly 2 food and nothing liquidatable: fire → play the grant occupation →
0 food → the mandatory play is unpayable and undeclinable → empty action set.

**Worked interaction (spending × cost-modifier — printed-cost blindness).** Which goods
the mandatory work "needs" is not the printed cost once conversions exist. **Bucksaw**
(implemented; "each time you renovate, you can also pay 1 wood…") spends wood — a good
renovation never prints. But with **Frame Builder**, (…+ 1 wood + …) is a real renovate
payment variant; if Bucksaw's trigger fires in the before-window of a renovate that was
only payable via that variant, the 1-wood spend strands it. Whether Bucksaw's timing is
before or after is unaudited (§13).

**Worked interaction (income arriving mid-host rescues the mandatory work —
user-identified 2026-07-09).** The post-fire completability question is existential over
income that arrives *between* the spend and the mandatory work, not just over current
holdings. **Patroness × Paper Maker × Writing Desk** on Lessons: fire Writing Desk (2
food) and play the grant occupation → **Patroness** ("after each occupation after this
one, 1 building resource of your choice") pays out — choose wood → the mandatory Lessons
play costs 1 food the player no longer has, but **Paper Maker** ("immediately before
playing each occupation, pay 1 wood total → 1 food per occupation in front of you")
converts that wood into enough food. Writing Desk's fire was completable only through an
after-play grant feeding a pre-play converter. Any repaired guard that checks
affordability on the immediate post-spend holdings alone calls this legal line dead.

**Where the pattern can occur — hosts with costed mandatory work today:** Lessons
(occupation ramp), the Major/Minor Improvement space (the composite's mandatory child is
a costed build-or-play), House Redevelopment and Farm Redevelopment (renovate), Fencing
(wood/fence pieces), Grain Utilization (a seed — grain **or** veg — for the sow leg, or
grain for the bake leg, of the mandatory sow-or-bake), and **Farm Expansion** (mandatory
at least one of room/stable, both costed — `_can_build_room or _can_build_stable`,
legality.py:817; omitted from this list until 2026-07-09).
Farmland/Cultivation's plow and the take-spaces are free today — see M4 for the card that
changes that.

**Cards (spending options on those hosts):**

| Slug | Deck# | Impl? | Spend | Host | Status |
|---|---|---|---|---|---|
| writing_desk | D28 | **yes** | 2 food | Lessons | guard hole confirmed (§13) |
| bucksaw | A37 | **yes** | 1 wood | renovate hosts | timing + guard unaudited (§13) |
| loppers | A34 | **yes** | 1 wood + 1 fence piece | Fencing | timing + guard unaudited (§13); the fence *piece* is also a shared resource |
| upholstery | E31 | no | 1 reed | improvement hosts | the spend competes only with the improvement's own (post-modifier) cost, which can include reed (Basketmaker's Workshop 2 reed + 2 stone; reed-cost minors) |
| contraband | E54 | no | +1 printed-cost resource | improvement hosts | user sketch 2026-07-09: implementable as wide payment variants — each building-resource-costed improvement gains a dearer +1-resource option yielding 3 food; open note: whether that 3 food may compose with wood_expert inside the same payment |
| beer_stein | C61 | **yes** | 1 grain | bake (Grain Util.) | guard (≥2 grain + baker) is exact **under the implemented pool only** — see the cycle note below |
| baking_sheet | A30 | **yes** | 1 grain | bake | same status as beer_stein |

*The same-window boundary, corrected (2026-07-09, user counterexample).* A spending
trigger whose refills share its decision window can survive on a simple count guard
**only while every refill is independent of the spend's own proceeds** — then any
blocked line is reachable refill-first (Potter Ceramics before Beer Stein at 1 grain +
1 clay). A conversion **cycle through the spend's output** defeats the reordering:
with Beer Stein + Clay Carrier + Potter Ceramics, a 1-grain player legally bakes via
grain → 2 food → 2 clay → 1 grain — and that chain's input IS the spend's output, so
the spend must come first and the ≥2-grain guard hides a legal line. No implemented
same-window food→…→grain path exists today (Clay Carrier is unimplemented M5), so the
guards are exact *contingently*. The general statement: **the moment at-any-time
converters exist, every M3 spending guard inherits M5's reachability problem** — "does
a legal completion remain after the spend?" stops being a count and becomes a closure
question over the post-spend state.

(Any future trigger with a cost, registered on a costed-mandatory host, joins this table.)

---

## M4 — Imposed costs: taxes on otherwise-free actions

**What it is.** A card that makes a free action cost something — for the owner or an
opponent. Two legality effects: an *added precondition* (the actor must be able to pay
the tax), and a *domain expansion* for M3 (a previously-free mandatory work item becomes
costed, so spending triggers on its host can now strand it). Census:
`CENSUS_COST_IMPOSITION.md` — **8 cards, none implemented.**

- **dwelling_mound (C37)** — the owner pays 1 food per new field tile, "must be able to
  pay before placing." The moment it exists, plowing has a price: `_can_plow`, every
  plow-grant eligibility, and Farmland/Cultivation join M3's host list. Plow currently
  has no cost concept anywhere in the engine.
- **fishing_net (C51) / forest_guardian (B138)** — an opponent must pre-pay the owner 1
  food (to use Fishing / to take ≥5 wood from a wood space). Placement legality acquires
  a payability precondition **and** a player-to-player transfer; Fishing Net adds an
  ordering rule (the space's own food may not fund the toll).
- **chapel (A39) / forest_inn (B42) / alchemists_lab (E81)** — tolls on card-created
  shared spaces (that whole space family is separately unbuilt).
- **credit (A54) / animal_catcher (C168)** — recurring upkeep with a begging/penalty
  fallback; irrelevant to legality (user 2026-07-09). Listed in the census only.

---

## M5 — At-any-time conversions over the resource pool

**What it is.** 14 of the 31 at-any-time cards convert holdings at player-chosen moments
(census: `CENSUS_AT_ANY_TIME.md`; none implemented). Affordability stops being "does the
current vector cover the cost" and becomes "is some *reachable* vector via conversions
sufficient." Breaks A1 for every resource-gated check simultaneously.

**Worked interactions.** **hard_porcelain** (2/3/4 clay → 1/2/3 stone) makes a
stone-renovation reachable for a clay-rich player the predicate calls illegal.
**clay_carrier + large_pottery** form a net-positive cycle (2 food → 2 clay → 4 food),
bounded only by Clay Carrier's once-per-round latch — reachability computations must
consume real per-card bounds, not assume convergence.

**Cards:** kettle B32, hard_porcelain B80, clay_firer D162, large_pottery D60,
basketmakers_wife C139, emissary D124, sheep_walker B104, clay_carrier D122,
oriental_fireplace A60, earth_oven D59, boar_spear E53, crudit C57 (food half),
seed_trader D114, grocer A102 (pile — see M8). (reed_seller D159: ruled out of scope
2026-07-06.)

---

## M6 — At-any-time board/farmyard mutations

**What it is.** At-any-time cards that change the farm or board — stables, rooms, house
material, fields, crops. Breaks A2: any precondition read from the farm (house material
prerequisites, room-gated growth, empty-field checks, field counts) can be changed by the
player between any two decisions. None implemented.

**Worked interaction.** **trowel** (renovate to stone at any time) flips every
"stone house" prerequisite and gate mid-turn: whether a minor with a stone-house
prerequisite is playable at an improvement space depends on whether the player *could*
first fire Trowel — including paying for it, which can itself involve M5 conversions.

**Cards:** stable_cleaner C94, trowel D13, stone_house_reconstruction E13, mason C87,
master_builder D87, piggy_bank E27, roll_over_plow C18, changeover D71, clearing_spade
A71, sower C115 (Sow half), muddy_puddles B83 (animals), stable_yard C50 (animal swap),
pen_builder E86 (capacity).

---

## M7 — Automatic payouts reacting to state changes, however caused

**What it is.** Cards that pay out whenever a state change happens, regardless of what
caused it (census: `CENSUS_REACTIVE_TRIGGERS.md`, 153 cards, 47 implemented; the
affordability-feeding subset matters here). Alone, each is an ordinary effect. Combined
with anything from M1/M2/M6 that mutates state, they make the *value* of a move
non-local: what a stable-build yields depends on which reactors are in play, and reactor
income can fund further moves.

**Worked interaction (the three-card chain, user-constructed 2026-07-09).** A
before-window food grant + **stable_cleaner** + **potters_yard**: place on House
Redevelopment with 0 clay → grant food → Stable Cleaner builds a stable mid-turn (1 wood
+ 1 food) → the cell turns used → Potter's Yard pays 1 clay → the mandatory renovation is
payable. Three mechanisms (M1 × M6 × M7), each blind to the others by construction.

**Second interaction, one card from being live.** **barrow_pusher** (implemented: +1
clay +1 food per new field tile, any source) × **roll_over_plow** (unimplemented,
at-any-time plow): the day Roll-Over Plow lands, plowing at will yields clay+food through
a card that already exists.

**Affordability-feeding reactor list (payload funds builds/plays or mutates the farm;
implemented members bolded):** potters_yard A40, farmstead C48, **barrow_pusher A105**,
cultivator D104, mountain_plowman E164, **rocky_terrain C80**, field_spade E79,
brick_hammer D80, recycled_brick D77, renovation_preparer D123, vegetable_slicer A41,
**junk_room A55**, **skillful_renovator C119**, **roughcaster A110**, pasture_master
B168, master_huntsman E165, **stablehand D89**, **mining_hammer B16**, stable_milker
D166, breeder_buyer A167, saddler E128, **wall_builder A111** (scheduled), stable_tree
A74 / farmyard_manure A43 (scheduled, on-turn only), blackberry_farmer E108 (scheduled),
interior_decorator D111 (scheduled), **cubbyhole E52** (feeding-time), feed_fence C56,
brushwood-family cost-mods excluded (see §11).

---

## M8 — Goods held on cards participating in affordability

**What it is.** Purchasable/pullable goods that live on a card rather than in the supply
(depleting piles, banked stores). Affordability becomes a reachability question over
interleaved pulls and spends, where the engine's usual Pareto-dominance pruning is
unsound (`CARD_SYSTEM_DESIGN.md` §15 — the Grocer analysis, with a worked 7-step
fixture). Distinct from M5 because the *source* is stateful and depletes.

**Cards:** grocer A102 (8-good pile, official clarification: buy any amount at once),
seed_trader D114 (2 grain + 2 veg), muddy_puddles B83 (5-good pile, ordered),
material_hub C81 (2 of each resource, drips on any player's big takes), forest_stone B48
(food shuttle), bonehead D118 (6 wood, drips per hand-card play), sower C115 (reed per
major built), piggy_bank E27 (food bank → free major), wolf E103 (pile-match),
resource_hoarder E123 (a fixed resource pile spendable at build time toward rooms /
improvements / renovations), art_teacher B155 (food on the Traveling Players *board
space* pays occupation costs — board-held rather than card-held, same reachability
shape), firewood C75 (wood banked each returning-home, moved to supply *before building
a Fireplace/Hearth/oven* — card-held goods in a pre-work window; text verified
2026-07-09), whale_oil E51 (card-held food paid out before occupation plays). Of these
only interim_storage-style *timed* releases are implemented; none of the
player-controlled-pull members are.

### M8b — Food as universal currency (the Grocer collapse)

The day Grocer lands, food stops being one column of the good→gate matrix and becomes a
bounded form of *every* resource: its pile is (wood, grain, reed, stone, vegetable,
clay, reed, vegetable) at 1 food per good, any amount at once — per-game caps of ≤1
wood, ≤1 grain, ≤2 reed, ≤1 stone, ≤2 veg, ≤1 clay, in pile order. (Which end of the
printed sequence is the top is not stated in the data — the physical card's stacking
diagram decides; a rules detail to pin before implementation. Seed Trader and Muddy
Puddles are smaller analogues for crops and animals/food.)

Two consequences, kept distinct because only one of them is a per-card problem:

- **Every food-generating card composes with Grocer** — and since animals and crops cook
  into food, that is *most of the catalog*: a 2026-07-09 sweep counts **~336 of 840
  cards** yielding food/crops/animals to their owner (split ≈220 supply-window —
  ordinary closure input — ≈48 scheduled to future rounds, ≈57 harvest-phase, ~10
  pre-work at a gated space, the M1 rows). **Sizing color only**: the counts are
  keyword-heuristic and come from a census run that made verified errors elsewhere;
  treat as order-of-magnitude, not inventory.
  Food sitting in supply is an ordinary input to whatever affordability computation
  exists; it creates no per-card legality issue. The composition burden lands on the
  M5/M8 reachability computation (the fan-out from any food-holding state gets wide,
  capped by pile state), not on the generator cards individually.
- **The M1 rows sharpen**: for pre-work food grants (Brook, Bean Counter, Pioneer's
  rider, Bookshelf/Patron), Grocer would add cells to their gate lists — food arriving
  inside the decision-to-work window becomes proto-wood/clay/stone/reed at those same
  instants, capped by the pile.

---

## M9 — Cross-owner income: an opponent's card funds the actor

**What it is.** A card owned by one player that pays the *acting* player around their
action, making player A's legality depend on player B's tableau. **No current member
affects legality.** The one candidate found, **chairman (D139, 3+)** — pre-action food to
the acting opponent at the Meeting Place — is irrelevant: per the rules, the Meeting Place
is always legal when unoccupied (user ruling 2026-07-09), so its pre-work income can never
be the thing that flips a gate. (kelp_gatherer pays the actor during the take — post-work;
fishing_net is the inverse, the actor *pays* the opponent — M4.) Retained as a shape to
re-check if a future cross-owner card pays the actor before a *resource-gated* action.

---

## M10 — Enumerator-side gap: mandatory triggers don't gate work on every host kind

**What it is.** Not a card mechanism — an engine fact that becomes load-bearing the
moment a mandatory-with-choice trigger lands on the wrong host kind. A mandatory
before-trigger must resolve before the host's work, but only the **atomic host** enforces
this (`legality.py:2431` withholds Proceed). The delegating host appends its mandatory
child unconditionally (`legality.py:1858`), the Proceed-hosts (e.g. Cultivation,
`legality.py:1884`) and the animal markets gate nothing — so taking the work would
silently decline a mandatory trigger. Today's two mandatory cards (Seasonal Worker → Day
Laborer, atomic; Childless → start-of-round host) happen to sit on gated frames; Pioneer
(M2) is the first card that can reach ungated ones — its "most recent card" ranges over
every host kind.

---

## §11 — Amplifiers (not problems alone; they widen every mechanism above)

These are correctly implemented today and make legality *harder to reason about* only in
combination: **cost modifiers** (formulas/reductions/conversions — which goods matter is
not the printed cost; see M3's Bucksaw example), **food liquidation** (`_payable`'s
cooking closure — every food figure above is really "food + cookable"), **free-fence
sources** (fence affordability isn't wood-count), **occupation food sources**
(paper_maker — the one existing single-source pre-simulation in `_payable_occupation`),
**renovate-target extensions** (conservator — more targets, more costs to check).

## §12 — Explicit non-problems (scope fence)

- **After-window grants** (water_worker's "each time after…") — income lands after the
  work is paid; never a legality input for that action.
- **Scheduled income** (well, pond_hut, salter, whisky_distiller, potters_market…) —
  arrives at future round starts; never in time for the current decision.
- **VP-only reactives** (beaver_colony, champion_breeder, swimming_class, hook_knife…).
- **Capacity passives** (bunk_beds, reader, pen_builder's capacity half) — affect
  accommodation frontiers, which already recompute from state.
- **Upkeep with a penalty fallback** (credit, animal_catcher) — never blocks an action.

## §13 — Suspected or confirmed live defects surfaced by this catalog

1. **writing_desk guard hole — confirmed by code read** (module guard checks the 2-food
   spend and hand count, never the post-spend mandatory ramp): reachable dead state.
2. **Mandatory-gate gap on non-atomic hosts — confirmed by code read** (M10; latent
   until a mandatory trigger lands there).
3. **bookshelf × Lessons placement gate — RESOLVED, not a defect** (verified
   2026-07-09): Bookshelf registers into `OCCUPATION_FOOD_SOURCES`, and
   `_payable_occupation` simulates owned sources at the gate; a dedicated test pins the
   0-food case. Kept here so the suspicion isn't re-raised.
4. **bucksaw / loppers timing + guards — unaudited** (M3): before-window spends on
   costed-mandatory hosts; after-window would be safe.
5. **thresher × Grain Utilization / Cultivation placement gates — CONFIRMED live
   under-offer** (verified 2026-07-09): thresher registers only a `before_action_space`
   trigger; `_legal_grain_utilization` = `_can_sow or _can_bake_bread` and
   `_legal_cultivation` = `_can_plow or _can_sow`, where `_can_sow` is a pure state read
   (grain-or-veg ≥ 1) with **no extension registry** (the only eligibility-extension
   seam in the area is bake-specific). Trace: owns thresher, 1 food, 0 seeds, empty
   field, no baker → both predicates False → the spaces are never offered, though the
   rules allow buy-then-sow. Telling detail: thresher's own test pre-seeds 1 grain + 2
   food "so the placement is legal now" — the enablement case is untested because the
   gate cannot produce it.
6. **wood_workshop × the improvement gates — CONFIRMED live under-offer** (verified
   2026-07-09): the card is implemented as `register_auto("before_build_major")` +
   `register_auto("before_play_minor")` — the +1 wood lands at the leaf-frame push —
   and **its official clarification states the wood may pay for the improvement
   itself** (*"You are able to pay for the improvement with just the wood given by this
   card"*). But no placement or branch-choice gate counts it: `_legal_major_improvement`
   / the card-mode major-or-minor predicate / `playable_minors` all read pre-grant
   state, and no improvement-side income seam exists (the food-source seam is
   occupation-only). A 0-wood player whose only playable improvement is short exactly
   the granted wood is wrongly denied. Unlike thresher, the clarification removes all
   rules ambiguity about intent.
7. **seed_pellets / drill_harrow × the sow gates — suspected under-offers, contingent
   on a §14 rules ruling** (both implemented, verified 2026-07-09): seed_pellets is a
   `before_sow` auto (+1 grain); drill_harrow a `before_sow` trigger (pay 3 food →
   plow). At 0 seeds (or seeds but no empty field), `_can_sow` fails, the sow branch is
   never offered, and the before-sow effect is unreachable — circular. Whether the
   rules let these *initiate* a sow that current state can't support is the §14
   question; the codebase's own bake-side precedent (hand_truck's `_can_bake_bread`
   extension lets its pre-bake grain open the bake gate) suggests yes, but that is a
   ruling, not an inference I can make.

## §14 — Open rules questions raised by this catalog

- **Bean Counter's payout vs Thresher's buy (2026-07-09).** Thresher's exchange is
  printed "**immediately before** each time you use…"; Bean Counter's banking is a bare
  "each time you use…" (= the before-window under the standing timing ruling). If Bean
  Counter's third food lands at the same space use, does it arrive in time to fund
  Thresher's buy? Per the standing instruction, every "immediately" gets its own
  per-instance user ruling — this one decides whether the composition in the
  bean_counter row is real.
- **Forbid vs fizzle** (from M3, 2026-07-09): when an optional choice makes a host's
  still-pending mandatory action impossible — is that choice illegal to offer, or does
  the impossible obligation lapse ("do as much as you can")? Shapes every stranding
  guard.
- **Does sowing wood/stone satisfy a sow gate?** (from M1b's card-field family,
  2026-07-09): wood_field / rock_garden are fields sowable only with wood/stone ("sow
  and harvest … as you would grain/vegetables"). If a player's only sowable target is
  such a card and their only "seed" is wood/stone, is a Grain Utilization / Cultivation
  placement legal on the strength of a wood-sow? Decides whether wood/stone enter those
  matrix columns when the card-field family lands.
- **Can a before-sow effect initiate a sow that current state can't support?** (from
  §13 #7, 2026-07-09): seed_pellets' +1 grain fires "before you take a Sow action" —
  may a 0-seed player with an empty field start the sow on the strength of it?
  drill_harrow's pay-3-food plow fires before the sow — may a player with seeds but no
  empty field start the sow counting on the plow to create the field? The bake side has
  in-codebase precedent (hand_truck opens the bake gate via an extension) and
  wood_workshop / agrarian_fences have official clarifications answering "yes" for
  their gates — but each instance needs its own ruling.
