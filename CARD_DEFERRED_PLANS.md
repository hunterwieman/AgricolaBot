# Deferred-Card Design Plans (Artifex / Bubulcus + rescued base cards)

_Written 2026-06-30 (overnight autonomous session). The companion to `CARD_BATCH_TRIAGE.md`
(the 67 implemented this session) — this doc covers everything **deferred**, clustered by the
single mechanism/decision that blocks each cluster, with a concrete build proposal, effort/risk,
and the questions only you can answer. Goal: a fast morning decision surface — approve a group
and I build every card in it._

The clusters are ordered **cheapest-and-highest-yield first**. Group A items are small, well-scoped
engine additions that each unblock multiple cards and keep the Family game byte-identical. Group B
needs more design care. Group C is the deliberate engine boundaries (a real design decision). The
long tail of genuinely-blocked cards (geometry, new shared spaces, return-home hooks, randomness,
temp extra workers, hidden round-space identity, card-as-animal-holder, per-card goods stacks) is
summarized at the end — those need substantial new subsystems and are correctly deferred.

> Convention reminder (verified this session): a card-only field added to `PlayerState`/a pending
> must default to a Family-game value and be added to the manual `__hash__` + `canonical._DEFAULT_SKIP_FIELDS`,
> so the Family game stays byte-identical and the C++ gates stay green. Every Group-A/B plan respects this.

---

## RESOLVED (2026-07-27, same day) — Archway × "the last action space you use"

**User ruling (verbatim): "after_work is during the work phase so yes. A fired Steam
Machine forecloses Archway's move (and an Archway move onto an accumulation space
re-opens Steam Machine), just like Straw Hat."** Engine form: Archway's relocation
branch consults `last_use_committed` exactly as Straw Hat's does (set → move
suppressed; unset → Steam Machine's own after_action_space trigger surfaces at an
accumulation destination naturally). The implementer's no-interaction lean below is
superseded. Original question, kept for the reasoning record:

Steam Machine's condition quantifies over uses "each work phase". Archway D51's relocation
("Immediately before the returning home phase, they can use an unoccupied action space with
the person from this card") sits on the `after_work` rung — after `end_of_work`, whose
rung-mate is Informant B117's "After each work phase...". If that instant is AFTER the work
phase, an Archway use neither counts toward "the last action space you use" nor is foreclosed
by a fired Steam Machine — they simply don't interact (the implementer's lean). If the user
instead rules the work phase extends until returning home begins, Archway's use-branch joins
the `last_use_committed` consumers exactly like Straw Hat's move (which IS in scope:
`end_of_work` is ruled *during* the work phase, so a committed last use forecloses Straw
Hat's move-and-take-that-action branch and forces its "get 1 food" branch — user, 2026-07-27).
Also joining the latch when built: **Adoptive Parents A92** (a payable newborn activation is
an optional future placement living outside `people_home`) and **Market Master E131** (the
catalog's only other own-last-placement instant — its fire SETS the latch too). All three
builds are pinned executably by `tests/test_last_use_commitment_tripwire.py` (the Large
Pottery pattern): each test fails at the card's registration and carries its contract.

Two refinements found 2026-07-27 while flagging Market Master:

1. **The same-window sibling rule.** Traveling Players is an accumulation space, so Market
   Master and Steam Machine can both legitimately fire in the SAME after-window — both
   conditions ride the same last placement, and nothing makes them exclusive. Steam
   Machine's current eligibility read (`not last_use_committed`) is blind and would wrongly
   block whichever sibling fires second; correct today (nothing else sets the latch), it
   must be scoped to OTHER-window commitments when Market Master lands (e.g. latch set AND
   no latch-setting card in this frame's `triggers_resolved`).
2. **Sheep Inspector joined the foreclosure set (fixed same day).** Its return shares the
   last placement's after-window; post-commitment, a returned home worker would HAVE to be
   re-placed (placements are mandatory), falsifying the committed last use — so its
   eligibility now consults the latch. The reverse order (return first, then no bake) was
   already correct via `people_home`. Both orders pinned in `tests/test_card_steam_machine.py`.

## Ruling 85 (2026-07-27) — the harvest tail: the cooking floor lapses at end_of_harvest; the last-chance conversion offer

(User, restated from their words.) The post-breed cooking prohibition (ruling 39's floor) **stops
applying at the "at the end of the harvest" moment** — equivalently, the breed phase ends just
before it (a new phase holding the end_of_harvest + after_harvest moments is acceptable if the
representation needs one) — so Winter Caretaker CAN cook a just-bred animal to pay for its
vegetable. And the player's standalone choice to activate each of their available harvest
conversions gets its **final home at the last conversion opportunity of the breed phase,
immediately before end_of_harvest**; the converters are closed after it. This supersedes the
2026-07-03 annotation that end_of_harvest is itself "the last chance for in-harvest conversions"
(the last chance moves one step earlier; the floor lapses there instead). **BUILT
(2026-07-27), same day.** As landed: `post_breed_floors` and `in_conversion_span` lapse/close
on the harvest walk's cursor at end_of_harvest — NOT a new Phase member (the enum is shared
with Family and the C++ twin; the tail windows deliberately keep running under the breed
phase's Phase value, and a Family harvest's cursor never reaches the new branches). **Corrected same day** (the
first build split the surfaces produce-vs-spend, keeping end_of_harvest for the food-spending
buys under ruling 36's old phrasing; the user: "No. All these cards refer to the harvest. My
ruling is about what counts as part of the harvest and what doesn't"): `FREE_SPAN_EVENTS`
itself now ends at `after_breeding` for EVERY span carrier — the converters (craft majors'
span exchanges, Braid Maker's reed clause, Paintbrush both routes, Stone Carver) AND the
food-spending buys (Basket Carrier, Furniture Carpenter, Plow Builder's standalone fee).
Ruling 36's "field phase through end-of-harvest" phrasing is superseded by this harvest
boundary; the tail windows belong only to cards whose printed text names a tail instant
(Winter Caretaker at end_of_harvest; Value Assets / Elephantgrass Plant at after_harvest).
Companion rule, stated by the user the same day: a raise frame may fire an unused converter
only when the current instant lies inside THAT converter's own printed window (Schnapps
Distillery: feeding phase only) — already realized per-card via ownership-predicate phase
guards (the Studio/ruling-77 pattern); the whole-harvest converters need no guard because the
span envelope IS their window. Standing instruction recorded with it: prior rulings are not
infallible — where one breaks the plain reading of card text without explicit justification,
bring it to the user.
Winter Caretaker's converter-route pin is rewritten to the ruled play (standalone-fire the
Joinery at after_breeding, then buy at end_of_harvest — where a just-bred animal is now also
cookable). Known cosmetic residue (verified, no rules impact): the walk's eligibility probes
run cursor-cleared, so a player whose ONLY payment route was a now-closed converter can still
receive a Proceed-only tail-window frame — a singleton agents auto-skip; no legal move is
deleted and nothing offered is unexecutable. Fixing it means threading the walk position
through `engine.py`'s probe — deliberately not done.

## Ruling 84 (2026-07-27) — the food-payment classification pass: every implemented food price rides the raise shape

1. **The sweep + the fix wave.** All 572 implemented card texts were read for food-as-a-price
   (a four-agent semantic sweep, cross-checked by a keyword list, a code-idiom grep, and the
   ruling-82 survey), and the 72-module union audited against ruling 82 with every defect verdict
   driver-verified. Result: **22 plain-gate defects, all rebuilt on the raise shape the same
   day** — acquirer, basket_carrier, credit, cube_cutter, dung_collector, excavator, farm_store,
   food_merchant, forest_trader, furniture_carpenter, green_grocer, haydryer, merchant,
   new_purchase, plow_builder (standalone fire only), stone_importer, supply_boat, thresher,
   treegardener, truffle_slicer, value_assets, winter_caretaker. **10 condition reads confirmed
   fine** (docstring-noted): angler, case_builder, forest_stone, furniture_maker,
   kindling_gatherer, maintenance_premium, portmonger, small_animal_breeder, social_benefits,
   tree_cutter. 39 modules already correct. Ruling 82's recorded "17-module survey" is
   **superseded**: small_animal_breeder was a mis-sort (its gate reads food, never charges it),
   and eight defect members were missing from it (new_purchase, excavator, cube_cutter,
   food_merchant, truffle_slicer, merchant, forest_trader, supply_boat).
2. **Credit A54** (user, verbatim): "with 0 food, the player should be given both options:
   raise-and-pay and beg. With 1+ food, they must pay." Built as the three-tier end_of_round
   shape: auto-pay / mandatory-with-choice (`PendingCardChoice(("pay", "beg"))`, the Childless
   idiom) / auto-beg.
3. **Confidant B93** (user): asked whether a player may cook mid-play to afford a bigger
   placement count N — "Yes, obviously they may." The raw `food >= N` pre-gate is removed; the
   counts ride the liquidation-aware play-variant surcharge machinery (the Stable Sergeant
   shape). The old docstring's "(gated food >= N)" citation was the build record's own text,
   not ruling text — re-attributed.
4. **Ruling 37's scope, clarified by the user**: it governs the food-RAISING machinery only —
   rider-output buys stay out of the conversion frontier ("never a row of the CommitConvert
   Pareto frontier") — and says nothing about how such a buy's own fee is paid. Furniture
   Carpenter's and Basket Carrier's span-surface fees are therefore ordinary ruling-82 fees;
   their FEED-seam offers stay on-hand-gated, harmless because the span surface preserves every
   legal line.
5. **The eligibility gate is harvest-aware** (engine, `legality._liquidatable_to`): inside a
   harvest instant it now delegates to the same frontier the raise frame enumerates (in-span
   converters + ruling-39 floors), closing a gate↔frontier gap no pre-wave card had reached.
6. **Flagged, implementer's lean stands unless ruled otherwise**: Truffle Slicer's "if you have
   at least 1 wild boar" is a fire-time read, so a raise bundle may legally cook the qualifying
   boar (the condition held when the effect was invoked).

## Ruling 86 (2026-07-27) — card action spaces: tolls, occupancy, and the destination universe

The Stage-3 rulings for the card-created action-space family (Chapel A39, Forest Inn
B42, Alchemists Lab E81, Forest Owner C162, Archway D51 — "for all"; Collector C104,
Pioneering Spirit D23, Hardworking Man D127, Elder Baker E161, Forest Tallyman A162 —
"for you only"; Tree Inspector D116 — the accumulation variant):

1. **Toll gating.** "If another player uses it, they must first pay you 1 grain/food"
   gates the non-owner's placement entirely — "if they cannot pay it is not legal"
   (user, verbatim) — and is paid at placement time, before the action resolves.
2. **Food tolls take the raise shape** (ruling 82: cooking mid-payment is a legal
   route), and the toll — including raised food — lands with the OWNER: the engine's
   first player-to-player payment (everything else burns to the general supply).
3. **For-all occupancy is standard occupancy**: one worker total per round, either
   player's — "unless a different card allows a player to place their worker on an
   occupied space (e.g. brotherly love)" (user), i.e. the occupancy-exemption
   machinery composes with card spaces exactly as with board spaces.
4. **Forest Inn's placement gate is carryability**: the action IS the exchange, so
   any placer (owner included) needs 5+ wood to place at all; a non-owner needs the
   toll besides.
5. **Card spaces join the relocation/jump destination universe**: "Straw Hat,
   Archway, and others should allow the jumping worker to move to one of these
   action spaces as well as the normal action spaces on the board" (user, verbatim).
   Scope note: the shipped jump cards are all named-space pairs (Swagman's pair,
   Job Contract's pair, Full Peasant's, Large-Scale Farmer's), so the live members
   are the generic-destination movers — Straw Hat now, Archway when built.
6. **The toll × before-window ordering — RULED 2026-07-27 (superseding this item's
   original deferral; see item 8).** The survey below stands as the member record.
   Original boundary note: The user's question: a generic before-`action_space` effect
   granting food could interact with a food toll, and the order (toll first vs grant
   first) would decide placement legality at the margin. Surveyed both directions
   (2026-07-27): **no implemented or catalog card fires a goods-granting
   before-window effect on a card space's use.** Every generic-scope before-granter
   is keyed to BOARD features — round-slot spaces (New Market D55, Wholesaler B137,
   Bean Counter D158, Knapper A124, Master Workman A126), named spaces (the whole
   implemented before_action_space roster), an action the toll spaces lack (Wood
   Barterer D119 — fences/rooms), board adjacency (Legworker C117), or ordinal ×
   board category (Catcher A107, Building Expert A163); Sowing Master D109 is
   after-window. So the toll gate reads the pre-use state today, and the first card
   that grants goods in a card-space use's before window re-opens the ordering as a
   rules question (it is the improvement-layer enabling-grant question — Wood
   Workshop B75 vs the affordability gates — at the action-space layer).

7. **Toll receipts ARE "obtaining" for the payee's reactors** (user, 2026-07-27:
   "yes"): the owner receiving a toll obtains that good — Chapel's grain toll fires
   the owner's Hayloft-Barn-class grain reactors, a food toll the food reactors — so
   the toll transfer must route through the standard goods-gain chokepoint, never a
   silent field bump.
8. **The toll is owed PER USE, however the worker arrives** (user: "yes" — pierced
   placements, Bassinet/Mummy's-Boy extras, and Straw Hat / Archway relocations all
   pay), **and the toll fires BEFORE the before-action-space benefits** (user: "the
   benefits from mattock, Work Certificate, etc. are not able to help pay the
   toll"). Consequence, in the user's words: "the legality check for the non-owners
   is a can afford payment AND the legality check for the owner" — toll
   affordability is read on the PRE-use state (liquidation-aware for food tolls per
   item 2; plain have-it for grain), conjoined with the space's own action-legality
   predicate. Fishing Net C51's printed clarifications independently pin the same
   model on its board-space toll ("Others must have 1 food before using"; proceeds
   may not pay the owner).

9. **Fishing Net's board-space toll shares the card-space toll model** (user,
   2026-07-27): "I want the Fishing Net toll to be similar to the other tolls (like
   alchemist's lab) in that it is before the before action space autos and
   triggers" — the toll is paid at the arrival, BEFORE the space's before-window
   fires, gates the non-owner's placement/arrival when unpayable (its printed
   clarifications agree: "Others must have 1 food before using"; proceeds may not
   pay), and is owed per use however the worker arrives (a jump onto Fishing pays).

**Appendix (2026-07-27) — the read-everything interaction survey.** After the keyword
sweep provably missed the reaction class (the user's Kindling Gatherer catch), two
agents read all 840 catalog texts against the five for-all spaces (read counts audited
420+420; exclusion lists reviewed; spot-checks verified verbatim). The surface:

- **Yield-reactors** (the `taken`-delta stamp / obtain events / after-windows):
  Kindling Gatherer E118 (Forest Inn's exchange food + Archway's food) composes
  as-written — its after-window eligibility reads the host's `taken.food`, which the
  card-space Proceed path stamps. **Beaver Colony E33 and Mattock E77 do NOT** —
  both are implemented against static named-board-space sets (reed_bank /
  quarries), an encoding that was exact while the board held the only reed/stone
  sources; Alchemists Lab's dynamic yield needs each to grow a content-based leg
  (the `taken`-delta shape) AT THE LAB'S BUILD, or they under-fire. Also: Syrup Tap
  E47, Wolf E103, Claypipe A53, Material Hub C81, Hayloft Barn B21, Agricultural
  Labourer C120, Work Certificate A82, Steam Machine C25, Child Ombudsman D92
  (check each's encoding at the relevant build); Shaving Horse A48 is wontfix.
- **Occupancy/arrival interactions** (the pierce-and-extra-placement family reaching
  card spaces): Lazy Sowman A94, Bassinet A25 (its printed clarification names a card
  space as a valid target), Brotherly Love D24, Mummy's Boy A130 [3+], Little Peasant
  B151 [4+] (blanket "not considered occupied for you"), Spin Doctor D151 [4+],
  Parrot Breeder C150 [4+], Rock Beater E150 [4+] ("providing stone and…" —
  definitional question at its build); Basket Chair C22, Sheep Inspector D93,
  Henpecked Husband D94, Godly Spouse D150 move/return workers OFF card spaces.
- **Settled by existing rulings, no new question**: a vacated card space RE-OPENS
  (the Tea Time ruling — occupancy is solely worker presence — which
  `return_card_space_worker` already implements); a Straw-Hat/Archway-mediated use
  IS a use and fires the destination's hooks (rulings 81/83); "round spaces N–M"
  wordings are board slots and never card spaces.
- **Toll-model siblings** (design inputs for the toll seam — build it SPACE-GENERIC):
  Fishing Net C51 puts the identical "must first pay you" toll on a BOARD space, with
  printed clarifications pinning the model — "Others must have 1 food before using"
  (the toll gates the use) and "Food from the 'Fishing' action space may not be used
  to pay the card owner" (no paying from proceeds); Forest Guardian B138 is the same
  transfer on 5+-wood accumulation takes; Chairman D139 a Meeting-Place-only payout.
- **Machinery-family siblings found**: Final Scenario B23 (a round card becomes an
  OWNER-ONLY card-hosted space until placed on the board) and Studio Boat C39 (in
  1–3p games — clarification confirmed — the card IS a for-all ACCUMULATION card
  space), so accumulation-ness and reachability are PER-SPEC properties, never
  assumptions about card spaces as a class.

**Open questions from the survey (need the user before/at the relevant builds):**
(a) Do TOLL RECEIPTS count as "obtaining/getting" a good for the payee's reactors
(Hayloft Barn's grain from a Chapel toll; Wolf; Agricultural Labourer; Kindling
Gatherer / Syrup Tap on food/wood tolls)? One adjudication covers the family.
(b) Is the toll owed PER USE however the worker arrives — pierced placements (Lazy
Sowman, Little Peasant, Brotherly Love, Bassinet, Mummy's Boy, Parrot Breeder) and
relocations (Straw Hat / Archway moving onto another player's toll space) — or only
on ordinary placements? (c) Per-card definitionals deferred to each build: Rock
Beater's "providing", Wares Salesman E144's "a card that lets them turn building
resources into food" (× Forest Inn), Pioneer E105's "the most recent action space
card", Legworker C117's adjacency (undefined for card spaces), Material Hub's
"takes" vs exchange proceeds.

## Ruling 83 (2026-07-27) — Straw Hat: the unconditional food branch, inherited jump readings, the Steam Machine commitment both ways

Settles **Straw Hat E10** ("At the end of the work phases of rounds 3 and 6, you can move
your person from the 'Farmland' action space to an unoccupied action space and take that
action, or get 1 food.") — the first end-of-work relocation — and banks the Archway
confirmations ahead of its build:

1. **The 1-food branch is UNCONDITIONAL.** Offered at the end of work of rounds 3 and 6
   with or without a person on Farmland; only the relocation branch needs the person.
2. **The relocation inherits the jump-family destination readings** (ruling 81)
   wholesale: "unoccupied" is a strict occupancy READ at the fire time
   (`legality.space_occupied` — a worker or a "considered occupied" marker blocks; an
   occupancy-exemption card never un-occupies); the destination's own action must be
   legal per the same per-space placement predicate a normal placement uses; the
   destination resolves as a FULL use (its card windows fire); and the moved person
   keeps its number and the move counts as "placing" for place-triggered readers
   without minting (ruling 79 items 3/4).
3. **Steam Machine cuts both ways** (user, verbatim): "If steam machine has already
   fired, then straw hat's re-location is no longer available, and the player must
   choose the 1 food option. If steam machine has not yet fired, straw hat has the
   option to fire it if they go on an accumulation space." Engine form: the shared
   last-use-commitment latch (`PlayerState.last_use_committed`) — a set latch
   suppresses the relocation variants (the food stays); an unset latch needs no Straw
   Hat code, because Steam Machine's own `after_action_space` eligibility
   (accumulation space + `people_home == 0` + latch unset + can bake) holds naturally
   at the relocated destination.
4. **Archway confirmations, recorded for its build** (blocked on the card-action-space
   infrastructure; the sibling shapes to design against are Chapel A39, Forest Inn B42,
   Pioneering Spirit D23, Alchemists Lab E81, Collector C104, Forest Owner C162,
   Hardworking Man D127, Elder Baker E161): the parked person's relocation is optional
   — declined, or destination-less, the person simply goes home at the reset; "an
   action space for all" means normal occupancy, either player may place there; and
   the relocation right belongs to the player who used the space, not the card's
   owner. (Archway × Steam Machine is the open question above.)

Engine form — **the standing-worker ledger is BUILT** (the ruling-79 "relocation batch"
deferral): `PlayerState.standing_workers` holds (minted number, location) pairs —
appended at the three placement chokepoints, location-rewritten by
`worker_moves._move_board_worker` (a relocation preserves the number), dropped at
`worker_moves.notify_worker_returned` (a return anonymizes), cleared at the
returning-home reset. The use-instant ordinal readers (Catcher, Wheel Plow, Plow Hero,
Fir Cutter) migrated from the mint counter to `helpers.acting_placement_number` — the
acting worker's standing number at the nearest space frame: equal to the counter at
every ordinary placement and at the same-worker jump, the moved worker's preserved
(possibly lower) number at a relocated use. **Skillful Renovator deliberately stays on
the counter**: its printed effect reads "a number of wood equal to the number of people
you placed that round" — a COUNT, not the acting person's ordinal.

## Ruling 82 (2026-07-26) — NEVER make a rules-legal move unplayable; the food-payment preserve seam

1. **An implementation must never make a rules-legal move unplayable** (now
   CARD_AUTHORING_GUIDE.md §0.4, a hard rule). The canonical violation: a "pay N food"
   cost gated on food-on-hand — in Agricola the at-any-time conversions are legal
   payment routes, so the plain gate deletes options. The user: "this is never
   acceptable." Consequences executed same day: **Junior Artist B152 UN-IMPLEMENTED**
   (module + tests archived; built on the plain gate; re-implementation on the preserve
   seam awaits the user's go-ahead); **Canal Boatman** and **Sheep Inspector** corrected
   to the raise shape (Sheep Inspector's cost sheep RESERVED from cooking; its dynamic
   target stashed in CardStore across the raise); a 17-module survey of remaining
   `food >= N` gates recorded for a classification pass (each is either a payable COST —
   defect — or a read CONDITION — fine).
2. **The preserve seam** (the ruling-75 pair-gate generalized):
   `register_food_payment_preserve(resume_kind, fn)` + `legality.raisable_food_preserving`
   + the frame-side `_filter_preserve_check_bundles` over the shared
   `_apply_liquidation_bundle` simulation. A fee whose destination has its own goods
   requirement is offered iff SOME bundle preserves the destination, and the frame
   offers exactly those bundles. Full Peasant (jump INTO Grain Utilization) and
   Large-Scale Farmer (INTO the Major/Minor Improvement space; its fee is debited
   inside the check, since food-costing minors exist) are the consumers; LSF's earlier
   all-bundles-must-pass form was itself a legal-move deletion and was corrected.
3. **One-direction sufficiency** (user, confirmed with the sharpened reason): the
   reverse jumps (INTO Fencing / INTO Farm Expansion) need no preserve check TODAY
   because work-phase liquidation consumes only crops/animals while those destinations
   cost wood/reed + pieces — disjoint pools. **The invariant is pinned by an executable
   tripwire**, `tests/test_liquidation_disjointness.py`, which MUST fail when **Large
   Pottery D60** ("At any time: Clay → 2 Food") or any anytime building-resource
   converter lands — its ledger entry carries the matching ⚠ REVISIT.
4. **Job Contract's marker extends to occupancy-READING cards** (the user's answer to
   ruling 81.3's flagged question): "considered occupied" activates Turnip Farmer and
   its kin exactly as a worker would. `legality.space_occupied` is now THE definition
   of board-space occupancy for reading cards (Turnip Farmer / Pub Owner / Bohemian
   swept onto it; Iron Hoe's "if YOU occupy" is per-player occupancy, a different
   quantity the marker does not currently attribute to — boundary-commented in place).

## Ruling 81 (2026-07-26) — the same-worker jump mechanism, Job Contract's bookkeeping, Child Ombudsman's instant

1. **The jump is an after-window trigger that nests the destination's space frame.** For
   the same-worker second-use cards (Swagman A129, Full Peasant B130, Large-Scale Farmer
   B150, Junior Artist B152, Job Contract C23): the jump is fired as a trigger in the
   SOURCE space's `after_action_space` window — so it may be taken before other
   after-window triggers; firing pushes the DESTINATION's action-space frame onto the
   stack; the destination resolves completely (its host, sub-decisions, and its own card
   events); the walk then returns to the source's after-window for any remaining
   triggers. The user endorses this not merely as how the code would work but as **the
   most faithful implementation of the cards**.
2. **Full Peasant's "while the other is unoccupied" is checked at that trigger time**
   (the after-window of the first space's use).
3. **Job Contract: legality sees two occupied spaces; physically there is ONE worker.**
   After the chained use, both Day Laborer and Lessons are treated as occupied for
   placement legality (per the printed "Afterward, both spaces are considered occupied";
   physically: the person stands on Lessons, a marker on Day Laborer). If a return effect
   (e.g. Sheep Inspector) returns that person home, BOTH spaces become unoccupied. The
   both-occupied bookkeeping must not double-credit a person at the returning-home reset —
   carry the accounting on `PlayerState` or on Job Contract's CardStore.
4. **Child Ombudsman (D92) fires at `after_action_space`** ("at the end of each person
   action") and can fire multiple times per TURN when a turn contains multiple person
   actions (e.g. Job Contract's chained Day Laborer → Lessons). It is NOT a member of the
   jump family — nothing moves; it is a granted no-space Family Growth (the Stork's Nest
   shape at a different instant); it entered the family lists as a sweep artifact of its
   "with that person" phrasing.

## Ruling 79 (2026-07-26) — the placement-ordinal interpretation ("PHYSICAL")

Settles what "the Nth person you place" / "your Nth person" means for the ordinal-reading
cards (Wheel Plow, Plow Hero, Catcher, Fir Cutter, Henpecked Husband, Skillful Renovator,
and the unbuilt Building Expert / Market Master / Godly Spouse / Midwife / Second Spouse
family), chosen after a five-way stress test against the return cards (Tea Time, Sheep
Inspector) and the future relocation family (Straw Hat, Archway, Job Contract, the 3+
"same person uses a second space" cards):

1. **Each act of placing a worker from home or from the meeple supply mints the round's
   next number** — your first placement is 1, the second 2, and so on. The ordinal a card
   reads is the acting placement's minted number.
2. **Returning home anonymizes.** A worker sent home mid-round (Tea Time, Sheep Inspector,
   Henpecked Husband's return) loses its number; placing it again is a NEW act and mints a
   fresh number. A card referring to a voided number's person (Henpecked Husband's "return
   the first person you placed") finds nothing and does nothing.
3. **An on-board relocation preserves.** A worker moved between spaces without going home
   (Straw Hat, Archway, Job Contract) keeps its number — the physical token is continuously
   observable, so its identity survives.
4. **A relocation counts as "placing a person"** for cards triggered on placing (Catcher's
   "each time you place your Nth person…"), even though it mints no number — the cleanest
   reading of the cards as written, accepted even where awkward or unintended. One number
   can therefore be "placed" twice (unreachable with Straw Hat/Archway, whose sources are
   never reward spaces; reachable via the 3+ relocation family).
5. **Numbers may exceed 5** (a re-placement after a return at full family is act 6+;
   off-table for the tiered cards, harmless). **Newborns never mint** — "Newborns are not
   placed" (Skillful Renovator's clarification); a newborn's wish-space marker, and any
   no-space growth, is not a placement act.
6. Loaner placements mint normally (they place through the ordinary pipeline; the earlier
   loaner-advances-the-ordinal ruling of 2026-07-24 falls out automatically).

Engine form: a card-only per-player counter `placements_this_round`, ticked at the
placement chokepoints in Cards mode only, reset at the returning-home reset; the shared
helper reads it. The old derived expression `(people_total − newborns) − people_home +
temp_workers_active` is retired (it silently mis-read every return scenario — it computed
"workers currently deployed", an interpretation nobody chose).

The standing-worker number map deferred here is **BUILT** (ruling 83, 2026-07-27 —
`PlayerState.standing_workers`, maintained at the placement/move/return/reset
chokepoints; the use-instant ordinal readers migrated to
`helpers.acting_placement_number`). Unblocked but NOT yet migrated: the standing-number
readers (Second Spouse, Midwife, Mummy's Boy — all 3+/4+), and Henpecked Husband's
migration from its stored-space record to find-the-worker (its "unless it is on the
Meeting Place" exemption then reads the worker's location at fire time; Job Contract,
all-counts, is the 2p-dealt card that makes that migration matter).

## Ruling 80 (2026-07-26, refined same day) — "even if" removes an obstacle; the unit is the person-GROUP

Card text of the form "you can use [space] **even if** X" strikes X from the list of
factors making that use illegal; it does **not** make the use legal outright. Every other
obstacle still applies.

**The refinement (same day): on a Wish space, the obstacle-unit is the placed person AND
ITS ASSOCIATED NEWBORN, as one group.** Not obvious from the rules, but the only
interpretation under which these cards make sense — every completed wish use leaves
parent+newborn on the space, so a per-MEEPLE reading would kill the override in the
ordinary case it exists for. Sleeping Corner's text reads as "…even if it is occupied by
one other player's person **(and the associated newborn)**"; the other cards carry the
analogous silent clarification. *(An earlier same-day per-meeple statement of the
corollary — "illegal at 2+ placed workers" — was superseded by this refinement before any
of it shipped; "2+ people" in Sleeping Corner's printed clarification counts GROUPS.)*

- **Sleeping Corner / Sheep Rug**: the override pierces exactly ONE other player's
  person-group (parent+newborn included); a second GROUP — another player's separate
  placement, the 3+/4p shape — still blocks.
- **Second Spouse** ("…even if it is occupied by the first person another player
  placed", clarified "not if any second, third, etc. people occupy it"): same — the
  newborn is not a "second person"; a second group is.
- **Forest School is a DIFFERENT shape** ("you can consider the 'Lessons' action spaces
  not occupied" — no person qualifier): occupancy is voided WHOLESALE. Ruled same day:
  any number of workers is looked through, **the owner's own earlier worker included** —
  the owner may use Lessons twice in a round, and "you could go on a lessons space with
  many people already on it".

Implementation notes (user directives, same date): the occupancy-override predicates must
generalize to 4 players — count workers and owners generically, never assume "the
opponent" is a single seat. On a wish space, groups == players-with-workers (each player
places there at most once), so the group count needs no per-worker identity.

## Ruling 74 (2026-07-21) — the 24-occupation triage batch

A triage of 24 unimplemented occupations (Bed Maker → Braid Maker) was walked with the user;
this entry is the rulings-of-record for the implementing waves. Every item below marked
**(user)** is a dated user ruling quotable verbatim in module docstrings; items marked
**(plan, flagged)** are driver readings the user saw in the plan but did not individually
rule — each is also flagged in its module docstring.

**Implementing now — per-card rulings:**

- **Bed Maker (A93)** — an **`after_build_rooms` trigger** (user; overrides the bare-"each
  time"-fires-before default: the growth is intended to use the just-built rooms, since
  "Family Growth with Room Only" requires rooms > people; the room-gate reads post-build
  state). Growth via `PendingFamilyGrowth(place_on_space=False)` (the standing card-granted-
  growth ruling); newborn feeds the standard 1 food. Once per action (printed clarification:
  exactly 1 growth regardless of rooms built) via the host's `triggers_resolved`. Fires on any
  rooms addition, flag-irrelevant **(plan, flagged** — by analogy to Furnisher's every-room
  ruling below; "add rooms to your house" is not the named-action wording**)**.
- **Site Manager (D95)** — the on-play major build is **OPTIONAL** (user: "let's not make it
  mandatory"). Shape: `PendingGrantedSubAction` wrapper (build_major category), bare
  `PendingBuildMajor` — never the composite. The ≤1-per-type→1-food-each substitution is a
  `register_conversion("build_major", …)` gated on `granted_by == "card:site_manager"` (the
  Oven Site grant-scoped-pricing pattern).
- **Sheep Inspector (D93)** — "after you complete a person action" = the **`after_action_space`
  window** (user). **Newborns do not count** as "another person you placed" (user). Once per
  work phase = `used_this_round`. Return semantics mirror Tea Time (person home, space OPEN).
- **Henpecked Husband (D94)** — an **`after_build_rooms` AUTO** (mandatory). Gate: a **named**
  Build Rooms action (`build_rooms_action == True`) taken on the turn initiated by the owner's
  **second placement** this round. Card-granted named actions riding that turn are **included**
  (user, on House Artist A149 × Traveling Players); personless builds (Wood Saw E14's "without
  placing a person") are **excluded via an explicit exclusion list** of personless-build card
  ids (user) — the list is EMPTY today; **any future personless-build card must add its id**
  (breadcrumb: this entry + the module docstring). Room-effect builds (flag False — the
  Cottager shape) never count. The first placement's space is recorded per-round in CardStore
  (an every-space hook); no return if that space is Meeting Place (printed).
- **Furnisher (D96)** — triggers on **every room build**, not just named Build Rooms actions
  (user). The grants resolve **without interruption** (user): one trigger; firing opens up to
  N consecutive improvement plays (N = rooms built that action; build-major or play-minor,
  each −1 wood via `granted_by`-scoped reductions), then the card is done for that action.
  The improvement need not cost wood (printed clarification). Needs the multi-use counter on
  `PendingGrantedSubAction`.
- **Livestock Feeder (C86)** — capacity = `register_flexible_slots` over the grain count.
  Eviction is **structural, not per-seam** (user approved): a volatile-capacity ownership
  check at the accommodation barrier, optimized by a CardStore **grain watermark** — refreshed
  at every owner decision boundary, `can_accommodate` run only when grain dropped since the
  last boundary, written only when changed (user: "I trust you will think carefully about how
  and when to update this watermark").
- **Stable Master (C89)** — on-play optional build-1-stable-for-1-wood; clause 2 converts ONE
  unfenced stable's 1-cap flexible slot into a **3-cap single-type bin** — a strict upgrade,
  so no player choice **(plan, flagged**; needs the extract_slots flexible→bin transformation;
  check the Shepherd's Whistle arrangement interplay at build**)**.
- **Confidant (B93)** — **IMPLEMENTED 2026-07-21** (C5 hold released, user: "seems
  straightforward"). Built as: play-occupation variants N ∈ {2,3,4} (gated food ≥ N, debiting
  N food) + `schedule_resources` (the food back) + `schedule_effect` (the per-round grant),
  resolved at the `round_space_collection` window as a variant trigger ["sow", "build_fences"]
  (named actions — full-width frames), window Proceed = decline. Two follow-ups: (a) it is the
  first play-variant occupation that can be UNPLAYABLE (mandatory placement, no decline
  variant), which motivated a general engine fix — `playable_occupations` drops a variant
  occupation with no legal variant, and `_any_occupation_committable` (mirroring the
  play-occupation enumerator's per-(variant, payment) filter over base + surcharge) gates
  Lessons / Scholar / a granted play, so a route never strands an empty `PendingPlayOccupation`;
  (b) OPEN near-end rules question — played with fewer than 2 round spaces remaining (round 13:
  1 left; round 14: 0), does the printed "2, 3, or 4" minimum forbid the play, or does
  RULES.md's general "place only on the remaining spaces" allow it on 1/0 spaces? Implemented on
  the general-rule lean (allow, capping at what remains, deduping collapsed variants);
  **awaiting the user's ruling.**
- **Dung Collector (E90)** — fires **only on harvest breeding outcomes** (`BreedingOutcome`,
  ≥2 newborns placed — the Champion Breeder read). Pig Breeder (A165) + Pure Breeder (D167)
  end-of-round-12 breeds are **sequential and distinct** (user) — 1 newborn each, never
  triggering. Caveat (record in module): any future card breeding 2+ newborns outside
  `_execute_breed` must emit the payload or this card and Champion Breeder under-fire. A forum
  query on the simultaneity question is outstanding; revisit if it rules simultaneous.
- **Canal Boatman (D103)** — implemented as an **`after_action_space` trigger** (user-
  authorized deviation from the before-default: "slightly incorrect, but easier to
  implement"). **Multiple workers** may be parked on the card in one round (user) — each
  qualifying Fishing/Reed Bank use is a fresh trigger. Sheep Inspector **can** return the
  on-card worker (user). Needs the on-card-worker bookkeeping (shared with the card-space
  machinery).
- **Miller (E95)** — the buildable menu is **baking majors + baking minors in hand** (user:
  Baking Course + the ovens + Oriental Fireplace when implemented). The owner's granted bake
  on the opponent's Grain Seeds use resolves **before all of the acting player's
  before-action triggers** (user). Mechanism (user-approved): an `any_player` before-auto
  pushing `PendingGrantedSubAction(player_idx=owner, subactions=("bake_bread",))` on top of
  the just-pushed host — the out-of-turn decision rides the decider rule.
- **Field Merchant (B103)** — corrected reading (user): declining a **"Minor Improvement"
  action** → 1 food; declining a **"Major or Minor Improvement" action** → 1 vegetable.
  Detection keys on the NAMED actions wherever they occur — spaces and declinable card grants
  (Sample Stable Maker, Angler); **Equipper is excluded** per its printed clarification
  ("This effect is not a 'Minor Improvement' action") (user). Exiting an improvement action
  you **could not use counts as declining** (user) — Meeting Place with no playable minor
  pays, and placing on the Major Improvement space with nothing affordable must be legal
  (ownership-gated placement extension + a decline route on the composite host).
- **Braid Maker (E109)** — **un-deferred**. The 1-reed-1-stone Basketmaker's cost applies to
  major builds too (user) — a formula — and at "Minor Improvement" actions via the approved
  `register_minor_action_major_build` seam. The reed→2-food exchange is a **harvest-span
  conversion** (user): available in any harvest-time `PendingFoodPayment`, at feeding, and at
  a final `end_of_harvest` offering. **General pattern (user):** every resource→food
  conversion printed without a specific harvest phase — **Joinery / Pottery / Basketmaker's
  included** — follows the span pattern. The `end_of_harvest` offering is **unconditional but
  Cards-mode-only** (user approved the lean; Family keeps its FEED-only surface, lossless
  there since nothing can change between the feed offering and end_of_harvest in Family).
- **Plow Builder (E91)** — clause 1 rides the same minor-action-major-build seam as Braid
  Maker; clause 2 (reacting to a Joinery use during the harvest with a pay-1-food plow)
  returns to the user as a concrete proposal during the span-machinery wave.
- **Collector (C104) / Tree Inspector (D116)** — **card-as-action-space approved**; card
  spaces **count as action spaces for other cards' hooks** (user: both texts literally say
  "action space"). Collector surfaces **wide at PlaceWorker** (user) via a picks payload —
  the goods menu is the 10 good types (food included), so the maxima are C(10,6)=210 /
  C(10,7)=120 / C(10,8)=45 / C(10,9)=10, none Pareto-comparable. Tree Inspector accumulates
  +1 wood at the prep refill — the quarry-reveal discard (`reveal` window) precedes the
  refill on the preparation ladder, matching the user's stated ordering.
- **Motivator (E93)** — its own session; `design_docs/cards/TEMP_WORKER_DESIGN.md` is the
  jump-start doc (loaner semantics + the `workers_in_supply` borrow ruled 2026-07-21; five
  open questions in its §10).

**Still deferred, with today's context:** Agricultural Labourer (C120) and Wolf (E103) — the
any-source "obtain" event family (decide as a family with the reactive-trigger design);
Child Ombudsman (D92) — end-of-turn; Pen Builder (E86) — at-any-time; Wood Barterer (D119) —
placement-legality anticipation (reachability, ON HOLD); Master Tanner (E85) — feed-phase
cook reactions against the no-FEED-triggers boundary.

**Ruling 75 (2026-07-21) — the user's answers to the seven ruling-74 follow-ups:**

1. **The stranding pair-gate:** the overlooked fact is that Stable Master's build is
   OPTIONAL — no mandatory build can strand. The ruled shape: a wide display of
   (payment × build/no-build) pairs — the build variant is offered only with payments
   that leave the build doable; the decline variant with every payment.
2. **`build_stables_action` flags:** Groom, Stable Planner, and Stablehand are all
   wrong — switch all three to False.
3. **The span family:** Stone Carver joins the harvest span, and the craft majors join
   (done); ALL of these are additionally payable-from during any harvest-time
   `PendingFoodPayment`/`CommitConvert`. A catalog sweep for every other card granting a
   conversion available throughout the harvest is commissioned.
4. **Partial multi-use named-action declines:** investigate whether any card grants
   multiple declinable named actions at once (user skeptical one exists). The real
   scenario of interest: multiple CARDS granting named improvement actions at the same
   trigger moment — a Proceed implicitly declining both should pay income for BOTH, if
   that situation is constructible at all (to be investigated).
5. **Work Certificate × Tree Inspector:** a Work Certificate owner CAN take 1 wood from
   a 4+-stack Tree Inspector card space — regardless of which player played Tree
   Inspector.
6. **Web labels for the craft-span triggers:** make the cosmetic fix.
7. **Plow Builder:** no Joinery upgrades exist today. The ruled design: a FUSED trigger
   — perform the Joinery conversion AND the pay-1-food plow as one fired action —
   available throughout the harvest (every span window), so the player can take the
   plow early; it shares the Joinery's once-per-harvest budget with the plain surfaces.
   (Confirmed premise: the free-span converter family already exists — Basket Carrier,
   Paintbrush, Furniture Carpenter, now Braid Maker + the craft majors.)

**Ruling 76 (2026-07-21) — the post-investigation answers:**

1. **Studio (C55):** its 3 conversions are offered at the same time the craft majors'
   conversions are offered, and additionally any `PendingFoodPayment` frame resolved
   DURING the feeding phase can and should offer Studio's conversions. (Driver reading,
   stated for confirmation: Studio stays feeding-phase-scoped per its printed text —
   the feed offering it already has, plus feeding-phase payment-frontier participation;
   it does NOT gain span windows outside the feeding phase.) Action-shaping guidance
   (user, verbatim): "At the moment Studio's rates are less than or equal to the rates
   offered by all other conversion cards …, so a strategy of greedily converting with
   the restricted cards (meaning the cards that offer conversions for only one
   resource type) before converting with studio preserves optionality. Concretely this
   means that a player who chooses to convert a wood to food should use the joinery
   over the studio if they have both and both are available."
2. **Unfired granting triggers ARE declines** (user: "yes it does"): declining-to-fire
   a trigger that would grant a named improvement action counts as declining the
   action for decline income — including when the trigger was withheld as unaffordable
   (the can't-use-counts-as-declining ruling extends to grants). Requires the
   grant-condition-held-but-unfired seam at host exits; fired-then-declined stays on
   the existing frame seams (no double pay). Stone Company stays excluded
   (non-declinable). NOTE the Merchant consequence flagged to the user: every taken
   improvement action with Merchant + Field Merchant in play pays for the declined
   repeat.
3. **Plow Builder (E91) revised:** the plow effect does not need to follow the Joinery
   use immediately — it is available at any later point in the harvest. Offer the
   standalone pay-1-food-plow trigger throughout the harvest iff the Joinery has been
   used this harvest (the `"joinery"` budget-used boolean), once per harvest; the fused
   use-Joinery-and-plow trigger is kept as well.

**Ruling 78 (2026-07-21) — the greedy-pass scope pullback + Field Merchant follow-ups:**

1. **Beer Tap's frontier participation is an OPEN, UNRESOLVED problem — NOT a settled
   feed-seam-only decision.** The ruling-77 greedy pass over-scoped it into the frontier
   as three grouped tiers; that was reverted so the greedy pass ships only the ARCHITECTURE
   (crop-input widening) + **Schnapps Distiller / Distillery** (clean single-tier fixed
   fires). But the interim feed-seam-only state **leaves a real rules gap**: Beer Tap is
   usable in the feeding phase, so a card cost raised mid-feeding (reachable via Plow
   Builder × Rocky Terrain) SHOULD be payable through it and currently is not.
   **The hard part — why the frontier can't just offer it:** the once-per-harvest budget
   is NOT a Pareto dimension of the frontier (only goods-remaining are; `fired` is a
   tie-break, not a dim). Beer Tap converts GRAIN — the same good base cooking uses — at a
   better-than-base rate, so firing a tier strictly dominates base-cooking in the grain
   dimension and the frontier PRUNES "don't fire, save the budget." For a fixed single-tier
   converter (Schnapps: always 1 veg → 5 food) that forced fire is harmless — early vs late
   is value-neutral. For Beer Tap's SUPER-LINEAR multi-tier pricing (1.5/2/2.25 food per
   grain), the forced fire commits the once-per-harvest budget at the SMALLEST tier covering
   the current small cost, foreclosing a bigger-tier use at the later feeding payment — a
   strategically-valid option the frontier silently removes. (Studio / the craft majors have
   a BENIGN version: they convert building resources base cooking ignores, so firing is a
   goods tradeoff — incomparable, both surface — never a forced fire; worth confirming that
   holds.) **Neither interim option is correct:** feed-seam-only under-offers (denies a legal
   option); the 3-tier frontier over-forces (prunes save-for-later). The correct handling
   (make the budget a Pareto dim? only offer the tier matching held grain? offer it but
   protect the save-for-later config? a different converter shape for super-linear cards?) is
   a genuine design question — DEFERRED until the user and driver are sure, tracked here as
   open, not closed. **Consequence (user, 2026-07-21): Beer Tap is UN-DEALT until this is
   solved.** Because the frontier gap makes a legal in-feeding use unavailable, the card is
   incomplete, and an incomplete card is not dealt (CARD_AUTHORING_GUIDE.md §0.2). Its
   `__init__.py` wiring is removed (the module + test stay in place, validating the feed-seam
   code); re-wire it once the frontier participation lands.
2. **Beer Stall is NOT a gap** (correction of a driver mischaracterization): C49 is already
   implemented elegantly (ruling 30, 2026-07-06) as a joint Pareto frontier over (animals
   kept, k stables emptied for conversions) via the k-stable doctored-farm technique,
   one-commit resolution. It stays feed-seam-only by its own design, not for lack of a
   frontier surface. No action.
3. **Field Merchant pays even with no minors in hand** (user lean, 2026-07-21): "I lean
   towards granting Field Merchant income even when the player has no minors in hand." This
   extends the ruling-74 "could not use counts as declining" rule (already live at Meeting
   Place / Basic Wish) to the GRANTED named-minor cases that currently pay nothing when
   unusable — **SSM fired-but-no-playable-minor**, **Task Artisan's on-play grant** (and its
   reveal grant) with no playable minor. A granted named minor-improvement action that the
   owner cannot use (no playable minor) pays the decline income, exactly as declining an
   unusable Meeting Place minor does. (A LEAN — implement, revisitable.)
4. **Harvest Festival Planning × Field Merchant — RESOLVED (user, 2026-07-21).** HFP (C72)
   pushes the composite `PendingMajorMinorImprovement` on-play (field phase, then the
   Major-or-Minor action). Two paths, both now paying Field Merchant its vegetable on a
   decline: (a) when the composite IS pushed (a legal child exists), a decline-income owner is
   offered the composite's `decline_improvement` route and declining pays — via the composite's
   own seam; (b) **when HFP has NO legal child it pushes nothing, and `_take_then_grant` now
   pays the "major_or_minor" decline income DIRECTLY** (the user ruled the could-not-use
   principle, ruling 78 item 3, extends to HFP's played-but-unusable COMPOSITE, not just
   granted minor actions). The two branches are mutually exclusive (child ⟹ frame, no-child ⟹
   direct pay), so neither double-pays; HFP stays OFF the named-action-grant seam (its composite
   is on-play resolution, not a trigger). One-line fix in `harvest_festival_planning.py`.

**Ruling 77 (2026-07-21) — the greedy-conversion principle + two corrections:**

1. **The greedy conversion principle (user, the governing statement):** "The broad point
   is that we should convert goods to food greedily. For each good type, convert at the
   highest rate until you hit the max conversions count. Then convert at the next
   highest rate until you hit a limit, and so on. This is particularly relevant in the
   harvest, but not exclusively. For example, it is how we calculate bake bread income.
   So if we have Schnapps Distiller and are converting N>1 veggies to food during the
   feeding phase, we should use Schnapps Distiller for the first veggie and our smaller
   rate for the remaining N-1." Consequence: the feeding-phase crop-input food
   converters (Schnapps Distiller C109, Schnapps Distillery C59, the grain/beer
   converter family) join feeding-phase `PendingFoodPayment` frames at their premium
   rates — the Studio pattern (phase-gated frontier participation; single-input cards
   need no frontier_group; the tiering falls out of the Pareto enumeration + each
   card's own budget). Combined-good combos (Veggie Lover's grain+veg pair) explicitly
   deferred: "We don't need to worry about combined good combos like veggie lover yet."
2. **Studio reading CONFIRMED** (user): "offered at the same time the craft majors'
   conversions are offered" = the feed offering plus feeding-phase payment frames —
   exactly the driver reading recorded at ruling 76 item 1.
3. **Merchant CORRECTION** (user — supersedes the ruling-76 Merchant note): "Merchant
   requires the player to pay 1 food and then take the relevant action. I don't think
   declining this bundle counts as declining the action." Merchant is REMOVED from the
   named-action-grant decline-income seam (both kinds); declining its pay-and-take
   repeat bundle pays nothing. (The interim implementation had registered it on a
   consequence the driver flagged but the user had not accepted — corrected.)

**Open questions surfaced DURING the ruling-74 implementation (answered above as
ruling 75; kept for the record):**

1. **The (variant × payment) stranding pair-gate.** A wide play-occupation variant's gate
   runs at enumeration, but the occupation cost is debited before the variant's on_play
   pushes its frame — so Working Gloves paying the cost with the exact wood a chosen
   Stable Master build-variant needs reaches a `PendingBuildStables` with no legal action
   (a hard dead state; Baker has the sibling gap via food-shortfall liquidation consuming
   its grain). Proposed fix: an optional per-variant post-payment predicate on the variant
   registries, consulted per (variant, payment) pair by the enumerator.
2. **`build_stables_action` flag inconsistency.** Groom, Stable Planner, and Stablehand
   leave the flag default-True on granted builds, against the §9.6 name-the-action
   contract (Stable Master's grant sets False per the contract). Latent — nothing reads
   the flag on those paths yet — but worth a sweep + per-card adjudication.
3. **Stone Carver and the span pattern.** Under the ruling-74 general pattern ("every
   resource→food conversion printed without a specific harvest phase follows the span"),
   Stone Carver has feed + payment-frontier surfaces but no span-window triggers — same
   classification as Braid Maker's clause 1. Needs a user-confirmed sweep of the
   converter cluster.
4. **Partially-used multi-use named-action grants.** The decline-income seam treats a
   `max_uses > 0` named-action wrapper as declined only when wholly untaken; whether a
   partially-used one "declines" its remaining uses at Stop is unsettled (no such card
   exists — Furnisher's wrapper is flag-False).
5. **Card spaces × source-scanning cards.** Does Tree Inspector's "1 Wood accumulation
   space" qualify as a Work Certificate take-source (its scan is board-only today)?
   Sheep Inspector's return-target scan was extended to card-parked workers per the
   explicit Canal Boatman ruling; Work Certificate awaits its own ruling.
6. **Web UI labels for the craft-span triggers.** The pseudo-id FireTriggers render via
   play_web's title-case fallback ("Craft Span Joinery"); a proper label needs a
   synthetic `_CARD_META` row (play_web.py owned by a parallel session at the time).
7. **Plow Builder (E91) clause 2 — the concrete proposal.** "If you use the Joinery (or
   an upgrade thereof) during the harvest, you can pay 1 food to plow 1 field": now that
   craft conversions fire on every span surface, the natural seam is a
   `register_conversion_reaction(card_id, conversion_id_prefix, react_fn)` fired at the
   three places a harvest conversion executes (the feed commit, the payment-frontier
   bundle, the span-window fire), offering the optional pay-and-plow right after the
   reacting conversion resolves. Clause 1 (the Joinery at a named Minor Improvement
   action) is already expressible via `register_minor_action_major_build`. The card
   stays deferred-whole until this seam is approved.

---

## Food-provider batch — deferred members (2026-07-15)

The 2026-07-15 food-provider batch (§1) implemented 20 minors and deferred three:

- **Oriental Fireplace (A60, minor)** and **Earth Oven (D59, minor)** — both ARE cooking
  improvements as minors: *"At any time: Vegetable / Sheep / (Wild boar) / Cattle → food; 'Bake
  Bread' action: Grain → food."* **Deferred into the cooking-modifier cluster** (ruling 42 — the
  Gypsy's Crock / Cooking Hearth Extension class): `helpers.cooking_rates` was hardcoded off the
  major-owner array with **no card-injection seam** *(no longer true as of 2026-07-21 — ruling 72
  built the additive-bonus fold, `cooking_mods.register_cooking_rate_bonus`, for Fatstock
  Stretcher; these two cards need the stronger improvement-INJECTION shape — a card that IS a
  cooking improvement contributing base rates — which remains undesigned)*. Two extra
  wrinkles for that design pass: the printed **cost is "return a Fireplace/Cooking Hearth"** (a
  non-resource `play_minor` route — `register_base_route` could carry it, but no minor uses that
  today) and the **"counts as 1 minor OR 1 major, whichever is convenient"** dual-classification.
  The bake-only half is a trivial `register_baking_spec_extension` once the cooking-rate seam lands.

- **Farmstead (C48, minor)** — *"After each turn in which you make at least one unused farmyard
  space used, you get 1 food."* **Deferred: end-of-turn timing** — the deliberately-unbuilt boundary
  (CARD_ENGINE_IMPLEMENTATION.md §8; the Firewood Collector case). "After each turn" needs a true
  post-turn anchor that does not exist yet (the action-space pop lands one window too early once
  at-any-time effects arrive). A per-sub-action approximation (autos on after_plow / after_build_* /
  after_build_fences with a once-per-turn latch) fires on the same turns but is an *approximation* of
  the end-of-turn semantics, so it stays deferred pending the end-of-turn / at-any-time design.

---

## Deck-B/E scoring-and-timing batch — deferred/held members (2026-07-13)

The batch that implemented Heirloom, Nave, Land Register, Misanthropy, Rod Collection, Upholstery,
Herbal Garden, Beaver Colony, Hook Knife, Ox Skull, and Cookery Lesson (§1) left three cards out:

- **Muck Rake (D29, minor)** — *"During scoring, you get 1 bonus point for exactly 1 unfenced stable
  holding exactly 1 sheep. The same applies to wild boar and cattle, if held in different unfenced
  stables."* **Deferred: the first scoring-time ANIMAL-ARRANGEMENT card.** No existing scoring term
  depends on how animals are arranged among pastures/stables (animals aren't location-tracked), and
  scoring it correctly needs a multi-slot arrangement-feasibility search (dedicate up to 3 distinct
  standalone stables to a lone sheep/boar/cattle while housing all other animals) — the doctored-
  player + `can_accommodate` technique (`shepherds_whistle`/`mineral_feeder`) extended to reserve
  several capacity-1 slots. Buildable, but it is also the card that would first trigger the
  arrangement-sharing ruling (§6, CARD_AUTHORING_GUIDE §2) if paired with a future scoring-arrangement
  card. Removed from this session at the user's direction; revisit as a deliberate scoring-arrangement
  task.
- **Breed Registry (D36, minor)** — *"During scoring, if you gained at most 2 sheep from sources
  other than breeding during the game and have not turned any sheep into food, you get 3 bonus
  points."* **Postponed (user-agreed 2026-07-13): needs game-long, all-players, gross provenance
  tracking that PREDATES the card's play.** Two per-player fields tracked from turn 1 — sheep
  obtained from non-breeding sources (GROSS, not net: discard/exchange diverges gross from net
  without cooking) and whether a sheep was ever cooked — instrumented at ~8–10 non-centralized
  sites (sheep market, breeding-exclusion, `grant_animals`, on-play direct adds, exchanges; and the
  four scattered cook sites), gated to card-mode for Family byte-identity. Real correctness risk
  (a missed site ships silently wrong). Best done deliberately, ideally alongside sibling
  "gained X from source Y" provenance cards so the instrumentation is built once.
- **Writing Chamber (C31, minor)** — *"During scoring, you get a number of bonus points equal to the
  total of negative points you have, to a maximum of 7 bonus points."* **NOT TO BE IMPLEMENTED**
  (explicit user directive 2026-07-13). Not a defer awaiting infrastructure — deliberately excluded;
  do not implement it in a future batch.

---

## RESOLVED (marked 2026-07-27): the three mis-timed harvest cards were all re-timed

A 2026-07-02 fidelity audit found three implemented harvest cards whose printed timing was not
the feeding phase but which were built as FEED-seam conversions, with self-ratifying docstring
justifications the user never approved. This section long said "awaiting the user's disposition"
/ "no faithful hook exists yet" — **stale on both counts** once the harvest-window ladder landed;
all three now sit on their printed instants (code-verified 2026-07-27 during the ruling-84 pass):

- **cube_cutter** — the `field_phase` during-window (printed "In the field phase"); its
  1-wood + 1-food price now also rides the ruling-82 raise shape with the wood reserved from
  liquidation.
- **winter_caretaker** — the `end_of_harvest` window (printed "At the end of each harvest");
  its 2-food buy now rides the raise shape (ruling 84), and ruling 85 governs what is cookable
  there.
- **elephantgrass_plant** — its printed after-harvest instant (the module docstring carries the
  mis-timing history).

No allowlist residue: `tests/test_card_fidelity_lint.py`'s ALLOWLIST is verified empty
(2026-07-27). One gap the ruling-84 pass exposed: the lint's phrase patterns never caught
Truffle Slicer's "Tier-2 simplification" or Confidant's "deliberately NOT
liquidation-raisable" — tightening them with the ruling-84 phrases is queued hygiene.

**Mechanics for whichever session executes** (all card-only — Family byte-identity and the C++
gates are untouched): each card's entry in the `ALLOWLIST` of
`tests/test_card_fidelity_lint.py` MUST be removed as part of its resolution (the lint then
enforces the outcome); on a re-time, verify once-per-harvest scoping survives the registry move;
on a re-defer, update `CARD_IMPLEMENTATION_PROGRESS.md` and CARD_ENGINE_IMPLEMENTATION.md §1's
census; run the full suite. Read CARD_AUTHORING_GUIDE.md §0.1 before starting — the fidelity
rule, including its subagent clause, governs this work.

---

## Harvest-window redesign — user rulings settled so far (2026-07-03)

> **The full design lives in `design_docs/cards/HARVEST_WINDOWS_DESIGN.md`**
> (the 18-window ladder, the during-field-phase model with the take-occasion manifest, the
> FEED/BREED seams, the one-batch migration list for implemented cards — including the three
> mis-timed cards from the priority section above — and the open questions awaiting the
> user). **Build status (2026-07-04): stages 1–2 are IMPLEMENTED** — the ladder walk, the
> per-player FIELD band (ruling 3), the take-occasion manifest (`PendingFieldPhase` +
> `CommitFieldTake` + the occasion registries) are live; the design doc's §12 carries the
> as-built map, and the delegated migration batch (§7 there) is the next step. The rulings
> below are recorded in both places; this list is the quick reference.

Context: a design-in-progress to split the harvest into explicit, ordered timing windows
(immediately-before-harvest → start-of-harvest → before-field-phase → start-of-field-phase →
during-field-phase → end-of-field-phase → after-field-phase → the feeding/breeding analogues).
Within the during-field-phase window, optional card triggers and the mandatory crop take may
resolve in any player-chosen order (the take behaves like a mandatory trigger gating the
window's exit; take-*modifying* effects become ineligible once the take fires). Rulings the
user made during this design — cite these, dated, in the docstrings of the cards they govern:

1. **A skipped phase has no boundaries.** A player who skips the field phase (Lunchtime Beer
   E58) fires NO before-/start-/during-/end-/after-field-phase effects that harvest. (Definite.)
2. ~~Layabout's harvest skip does NOT suppress harvest-boundary effects~~ **SUPERSEDED
   2026-07-05 by ruling 14**: Layabout cancels before- AND after-harvest trigger effects —
   the whole ladder, outer boundaries included — following the official online
   implementation. (The user dislikes this reading but rules to follow the official
   game; the original ruling here had gone the other way and was itself marked
   contested.)
3. **Player interleaving within a harvest window: whole-phase-per-player, starting player
   first** (the BoardGameArena convention), adopted **provisionally**. The user dislikes it —
   the printed rules imply no fixed order, and a fixed order advantages the later-deciding
   player — but it is the simplest start and matches the existing per-player harvest frames.
   Revisit if it proves distortive.
4. **Bumper Crop (E25) / Harvest Festival Planning (C72) trigger the field-phase *effect*
   (the crop take), not the field phase itself** — no field-phase-keyed card effects fire
   during them (per the user; C72's clarification "this is not a harvest" is the same idea one
   level up). They may be hard-coded through a shared take function; a Pending frame becomes
   necessary only if optional crops-off-field triggers must surface inside them.

5. **The field-phase take is a singular event.** Harvesting all crops from all fields is one
   game event; effects that scale per-field or per-crop (Slurry Spreader's per-last-crop food,
   Barley Mill's per-grain-field food) scale over that one event's contents and all arrive at
   once — there is no per-field sequence of moments inside the take. Each *card-granted*
   harvest firing (Scythe, Stable Manure, a card-field effect) is its own separate occasion.
6. **"Each time you obtain at least 1 X" counts OCCASIONS; "for each X you obtain/harvest"
   counts UNITS** — both read the same event. Hayloft Barn's clarification ("harvesting 2+
   grain at once only counts as obtaining once") is occasion-counting for that card's "each
   time" wording, NOT a general rule that batches away quantities: obtaining 2 grain at once
   is one *time* but still 2 *grain* (Agricultural Labourer's per-grain clay scales by 2).
   Beware over-generalizing any single card's clarification into event semantics — and beware
   the converse too: some card wordings are just imprecise, so don't infer deep event
   structure from one card's phrasing without checking siblings.
7. **Witches' Dance Floor (D25) and Begging Student (D97) are BANNED — never implement**
   (user rulings 2026-07-03; both marked 🚫 in `CARD_IMPLEMENTATION_PROGRESS.md`, like
   Shaving Horse A48). Begging Student's ban also moots the registration-liveness question
   (HARVEST_WINDOWS_DESIGN.md §11) unless another mid-harvest card-play member appears.
8. **Anytime-in-harvest triggers** ("each harvest, you can…", incl. the Joinery / Pottery /
   Basketmaker built-ins — full analysis in HARVEST_WINDOWS_DESIGN.md §10): good→food
   converters surface ONLY inside the feed payment and in-harvest food raises (the user's
   own optionality-constrained proposal); pure-VP food buys surface ONLY at a single late
   anchor after breeding (**approved 2026-07-03**; Furniture Carpenter migrates off its
   FEED-only seam accordingly); buys generating **goods** that can become food (Basket
   Carrier, Ebonist) are offered **throughout the harvest, not selectively** (ruled
   2026-07-03).
9. **Grain Sieve / Barley Mill fire ONCE, off the take occasion** (ruled 2026-07-03): their
   bonuses read "the specifics of what happened in" the main field-phase crop take — not a
   window-wide aggregate over card-granted extra harvests. And **Home Brewer re-homes to
   the after-field-phase window** (ruled 2026-07-03), off `HARVEST_CONVERSIONS`.
10. **The post-breeding timeline** (ruled 2026-07-03): breeding phase → after-the-breeding-
   phase (Feedyard — INSIDE the harvest; its food can fund the last-chance conversions, and
   it dies with a skipped breeding) → the last chance for in-harvest conversions (the
   anytime span's end; end-of-harvest cards live here) → after the harvest (Value Assets,
   Elephantgrass Plant — outside). Details + the designated (Feedyard, Winter Caretaker)
   regression pair: HARVEST_WINDOWS_DESIGN.md §10.
11. **All field-phase harvesting is ONE simultaneous event — every during-phase harvesting
   card folds into the take** (ruled 2026-07-05, supersedes ruling 9's Scythe-Worker-vs-
   Stable-Manure contrast): the only event in a harvest in which a player harvests goods
   from fields is the field phase's main event; card extras (Stable Manure, Scythe Worker,
   Scythe E73's widening, Grain Thief's replacement) are taken AT THE SAME TIME as that
   event, part of the same occasion — never a separate, sequenced harvesting event. A
   two-agent full-catalog sweep (2026-07-05) found zero counterevidence: no in-harvest
   field-harvesting outside the field phase, no sequential wording anywhere, and two
   official clarifications in support (Potato Ridger A59: "'Harvest' is equivalent to the
   field phase, or any literal effect of a card saying 'Harvest a [crop]'"; Hayloft Barn
   B21: "Harvesting 2+ grain at once only counts as obtaining once"). Consequence, ruled
   explicitly: **Grain Sieve treats Stable Manure's extras exactly as Scythe Worker's** —
   both are in the take occasion and count toward "at least 2 grain." Implementation:
   Stable Manure reworks from its wave-A free-order/own-occasion form onto the take
   fold-in seam; a during-the-field-phase separate occasion no longer exists
   (`emit_harvest_occasion` remains for genuinely separate events — a Bumper-Crop-played
   field phase, future literal "Harvest a crop" effects).
12. **The harvest-verb lexicon** (ruled 2026-07-05): "harvest" as an EVENT is a real
   harvest's field phase (Harvest Festival Planning's "this is not a harvest" scopes the
   event sense). "Harvest" as a VERB means taking crops off fields into the player's
   supply via the FIELD-PHASE EFFECT — wherever that effect runs, so crops taken by a
   card-played field phase (Bumper Crop) ARE harvested in the verb sense — or via a card
   effect literally worded "Harvest a [crop]" (Potato Ridger's clarification, the
   definition). Crop-off-field movements worded otherwise are not harvests: "remove"
   (Crop Rotation Field E70) is the wider any-departure verb — the E68/E69 ("harvest the
   last") vs E70 ("remove the last") same-family contrast is the key evidence — and
   Changeover's "discard" removes the crop FROM PLAY, not to the supply, so it is a
   different movement entirely (not evidence about the harvest verb either way).
   Reactor scoping follows each card's own printed frame: "…in the field phase OF A/EACH
   HARVEST" (Crack Weeder, Potato Harvester, Slurry Spreader — confirmed field-phase-
   restricted, correcting a sweep-agent mis-filing — Grain Sieve, Barley Mill, Lynchet,
   Artichoke Field) fires only in real harvests' field phases; unscoped harvest-verb
   reactors (Food Merchant, Field Cultivator, Melon Patch, Cherry Orchard) fire on any
   verb-sense harvest, a played field phase included; E70's "remove" fires on any crop
   departure from that card.
13. **A card-granted newborn is fed 1 food** (ratified 2026-07-05): a Family Growth
   granted at the immediately-before-harvest / start-of-harvest windows (Autumn Mother,
   Bed in the Grain Field) produces a standard newborn — 1 food at that harvest's
   feeding, exactly like a same-round Wish-space newborn. The engine's uniform newborn
   rule stands as-is.
14. **Layabout cancels ALL harvest-relative effects for the skipping player** (ruled
   2026-07-05, supersedes ruling 2): before-harvest and after-harvest triggers included —
   windows #1 through #18 are all suppressed, plus the feeding and breeding frames.
   This follows the official online implementation; the user dislikes the reading but
   rules to match it. Also resolves the design doc's open question #2 (window #1 does
   NOT fire for a Layabout player). Cite this ruling, dated, in Layabout's docstring
   when built.
15. **Cubbyhole's payout is NON-consuming** (ratified 2026-07-05): the on-card food
   bank pays out at every feeding phase and is never depleted — the literal reading
   of "you get food equal to the amount on this card" (no removal clause).
16. **Shepherd's Whistle's condition is capacity-theoretic** (ruled 2026-07-05;
   dominance rule AMENDED same day): "at least 1 unfenced stable without an
   animal" — since animals are not location-tracked, a stable is free iff the
   player's animals can be accommodated with one unfenced stable removed from
   capacity. No unfenced stable: ineligible. A stable free by that test: the
   sheep is granted automatically. Otherwise the player may CHOOSE to free one:
   the options are the Pareto keep-sets under the reduced capacity, each plus
   the granted sheep (reachability is TESTED this way, never inferred from the
   ending — a 3-type holding can fit full capacity while its sheep-decremented
   form fails the reduced capacity). **The frontier is over animal counts PLUS
   a received-vs-declined dimension, where received dominates declined iff the
   player has a sheep-conversion opportunity** (a cook-a-sheep-and-replace-it
   option then beats declining — the food is non-deferrable because the card
   replaces the cooked animal, so the usual food-exclusion premise fails; with
   no conversion the same option is identical to declining and is pruned).
   Food generated is computed per option but is never a frontier dimension
   (the standing convention — among received options, animals-only dominance
   is exact: food differences equal the deferred cook-value of the animal
   difference).
17. **Baker's on-play decline is WIDE** (ruled 2026-07-05): a "when you play this
   card, you CAN take a [sub-action]" grant is offered as PLAY-VARIANTS of the
   play action itself — "play Baker and bake" vs "play Baker and decline the
   bake" are two distinct CommitPlayOccupation choices (the existing
   PLAY_OCCUPATION_VARIANTS mechanism, Roof Ballaster's pay-or-not shape). The
   user rejected the alternative (an after-play trigger with Stop to decline)
   because it would let the granted bake interleave with OTHER after-play
   triggers in player-chosen order, which "when you play this card" does not
   license. Once the bake variant is chosen, the pushed PendingBakeBread is
   committed (the variant choice was the decline moment). When no bake is
   usable at play time, the plain variant-less play is offered alone.
18. **"Immediately after each harvest" = "after each harvest"** (ruled
   2026-07-05): the two phrasings name the SAME instant — the user called the
   wording distinction "confusing and unnecessary". The ladder's two separate
   after-harvest windows were merged into one (`after_harvest`); Elephantgrass
   Plant (printed "immediately after") and Value Assets (printed "after",
   unimplemented) both live there. **This does NOT generalize automatically:**
   the user's standing instruction is that EVERY occurrence of "immediately" in
   a card text gets its own user ruling — sometimes it means the same as the
   phrase without it, sometimes not. Never encode an "immediately" timing
   distinction (or collapse one) unilaterally. The first flagged instance —
   Social Benefits vs Farm Store — was ruled the same day (ruling 19).
19. **"Immediately after the feeding phase" = "after the feeding phase", Social
   Benefits first** (ruled 2026-07-05): the feeding pair also collapses into
   one window (`after_feeding`), with Social Benefits ("if you have no food
   left, you get 1 wood and 1 clay") resolving BEFORE Farm Store's optional
   1-food exchange. No new machinery: Social Benefits is an automatic effect
   and Farm Store an optional trigger, and the standing within-window ordering
   (automatic effects before optional triggers) already delivers exactly that
   order — the user ruled the ordering should ride that convention rather than
   a separate window. Consequence: a player ending feeding with exactly 1 food
   cannot spend it at Farm Store and then collect the "no food left" grant
   (pinned by test_social_benefits_resolves_before_farm_store).
20. **In-breeding-phase card effects fire BEFORE the CommitBreed decision,
   not after** (ruled 2026-07-05, for Stone Importer's priced stone buy):
   the breed frame hosts pre-commit triggers (event "breeding") only while
   the breeding choice is still open; once CommitBreed resolves, the frame
   offers only the outcome-reactive grants (event "breeding_outcome" —
   Fodder Planter / Slurry Spreader C71's sows, which need to know the
   newborns) and Stop, all still inside the breeding phase. No separate
   window — the frame's own two stretches carry both.
21. **A mandatory, choice-free card effect fires automatically, never as a
   forced offer** (ruled 2026-07-05, for Potato Ridger's "with 4+ vegetables,
   you must do so"): the player gives no input — the effect is an automatic
   consequence, not a singleton FireTrigger the player must click. This
   aligns the harvest-occasion seam with the engine's standing firing
   classification (mandatory + choiceless = automatic effect). Consequence
   for two-tier cards: the occasion host records which per-occasion autos
   fired (`PendingHarvestOccasion.autos_fired`), and a card whose automatic
   tier reacted is excluded from offering its optional tier on the SAME
   occasion (Potato Ridger harvesting into 4 veg: the auto exchange drops
   supply to 3, and the optional at-3 offer must not then appear — "exactly
   1 vegetable" is once per occasion).
22. **A Grain-Thief-replaced field is NOT harvested** (ruled 2026-07-06,
   ratifying the 2026-07-05 implementer reading of "leave the grain on the
   field and take 1 grain from the general supply INSTEAD"): the field is
   untouched by the take and emits NO manifest entry — invisible to Grain
   Sieve's "at least 2 grain", Lynchet's harvested-tile count, and Food
   Merchant's per-grain buys; it cannot donate an "additional" good to Stable
   Manure, and Scythe Worker takes no additional grain from it. The
   replacement's supply grain is likewise not harvested (never in the
   manifest).

23. **Eternal Rye Cultivation's tiers are exclusive** (ruled 2026-07-06, with
   the printed errata's "or"): after each harvest, exactly 2 grain in supply →
   1 food; 3+ grain → 1 grain INSTEAD; never both.
24. **On-play optional choices on MINORS surface wide** (ruled 2026-07-06, for
   Facades Carving's food-for-points exchange — extending ruling 17's
   occupation pattern): one play option per route, via the new
   `PLAY_MINOR_VARIANTS`/`register_play_minor_variant` seam; the surcharge
   folds into the commit's payment (cost modifiers never see it), the benefit
   rides a variant-aware on_play.
25. **Field Cultivator counts field TILES and its takes arrive together**
   (ruled 2026-07-06): "each time you harvest a field tile" counts occasion
   entries (amounts ignored); harvesting k tiles in one take grants up to k
   pile-takes at once, top-down, each optional; unscoped (fires on
   card-played field phases too, per ruling 12).
26. **Earthenware Potter's "after the final harvest" is the after_harvest
   window at round 14** (ruled 2026-07-06 — the same instant Value Assets
   uses, run by the walk immediately before scoring), **and the player freely
   chooses how many people to pay 1 clay for.**
27. **Feed Pellets** (ruled 2026-07-06): the mid-feeding animal gain rides the
   standard decision-free-grant flow (accommodate or keep-or-cook via the
   barrier, which composes mid-FEED); the gained animal is cookable toward
   the same feeding; "exchange exactly 1 vegetable for 1 animal" is once per
   feeding phase TOTAL.
28. **Craft Brewery surfaces wide, encoded by field height** (ruled
   2026-07-06): one conversion option per grain-count group present ("take
   from a field holding X grain") — same-height fields are interchangeable,
   the canonical pick is scan-order — via the new
   `HarvestConversionSpec.variants_fn` seam. The field grain's removal is NOT
   a harvest (no occasion; ruling 12's lexicon).
29. **Mineral Feeder — LANDED 2026-07-06** (ruled the same day): "at least 1
   sheep in a pasture" means at least one sheep actually housed in a pasture
   (not all sheep) under SOME legal arrangement — tested by the user's
   per-pasture construction (dedicate pasture j to sheep, MAX-FILL it, test
   the remainder against the rest of the farm; exact, not a heuristic) — and
   the player may COOK animals to make such an arrangement possible (the
   Shepherd's Whistle case-B analog). The case-B frontier is over
   **(animals, grain)** — the user's framing: declining sits at (current, 0),
   each option at (kept, 1) — so options and the decline never dominate each
   other and animals-only Pareto among options is exact. Cooking a SHEEP can
   itself enable the arrangement (the user's Stockyard counterexample) and
   the enumeration handles it with no special-casing. Same-instant caution
   recorded in CARD_AUTHORING_GUIDE.md §2: two arrangement-conditioned cards
   on ONE instant need a joint-satisfiability test, never independent ones.
30. **Beer Stall — build plan RULED 2026-07-06 (supersedes the same-day
   defer)**: the user's design — a Pareto frontier over **animal counts PER
   grain-conversions-TAKEN k** (taken, not offered: different k values never
   dominate each other — more food, less grain, both excluded dimensions),
   with the k exchanges BUNDLED INTO each option alongside the
   cooking/rearrangement (which dissolves the cook-first sequencing problem
   that forced the original defer — nothing is sequenced through the feeding
   flow). An option = (kept animals, k) where the kept animals fit with k
   unfenced stables left empty (the k-stable generalization of Shepherd's
   Whistle's doctored blank) and k <= grain supply; firing cooks the
   released animals, pays k grain, grants 5k food. Proceed = (current
   animals, 0 conversions). Surfaces as a variant-bearing feeding conversion
   (the Craft Brewery seam); once per feeding via harvest_conversions_used.
   Not yet built — ready on the user's go.

31. **Uncaring Parents does not interact with the stone-house-bonus
   exclusivity clause** (ruled 2026-07-06): Half-Timbered House / Luxurious
   Hostel's "you can only use one card to get bonus points for your stone
   house" does NOT reach it — the user's reasoning (offered with a hedge):
   the house is not providing the points, it only provides a condition that
   lets the card give its per-harvest points. Uncaring Parents scores as a
   plain unrestricted term, stacking with those cards.
32. **A card-field is NOT a "field tile"** (ruled 2026-07-06 — the user:
   "very important to keep in mind"): when card-fields (Beanfield et al.)
   land, their harvest-manifest entries (source "card:<id>") do not count
   for any per-TILE reader. Field Cultivator already encodes this (its tile
   count filters to "cell:" entries, with a pinned test); Lynchet excludes
   them structurally (board adjacency). Every future per-tile card must
   filter the same way.
33. **The Lynchet interchangeability gap is KNOWN and deliberately deferred**
   (user decision 2026-07-06): same-height fields are treated as
   interchangeable by the group-encoded choices (Stable Manure / Scythe /
   Grain Thief / Craft Brewery) and by sowing's canonical cell fill, even
   though Lynchet's house-adjacency reading can distinguish them (a Lynchet
   owner is occasionally denied the better of two "identical" picks — e.g.
   which field Grain Thief replaces). The agreed eventual shape is a
   CONDITIONAL adjacency-aware group key (split groups by house-adjacency
   only when the acting player owns an adjacency-reading card), but the user
   chose to ignore the problem for now rather than widen the decision space.
   Nothing mis-scores; this is a knowingly-accepted approximation, on record
   so future sessions treat it as a decision, not an oversight.

31. *(31-33 recorded above with the wave that landed them.)*
34. **The anytime-converter class-1 build direction** (decided 2026-07-06):
   the user's generalized conversion frontier — the mid-harvest food-raise
   frame (`PendingFoodPayment`) extends its Pareto space from crops + animals
   to crops + animals + CAPPED building-resource conversions (Joinery up to
   1 wood, Stone Carver 1 stone, …), each source live only within its span
   (instant-scoped, derived from phase/cursor) and budgeted once per harvest
   via `harvest_conversions_used`, shared with the feeding crafts. **The
   FEEDING phase is NOT folded into this frontier** — its surface stays as
   is (individual craft fires before the payment commit), because (a) at
   that frame the two shapes are outcome-equivalent, (b) folding changes the
   Family feed action shape and so breaks the no-card AI + requires the C++
   re-port — the user's judgment: hard to reverse once done, easy to add
   later if minds change — and (c) folding would silently prejudge whether
   feeding conversions are distinct orderable events (see the Gypsy's Crock
   note below). REVISITABLE by design.
35. **Gypsy's Crock (C53) is PARKED pending dedicated design** (user,
   2026-07-06): its activation reads how conversion/bake instants are
   grouped ("at the same time" — the Oriental Fireplace clarification), i.e.
   the event-granularity of feeding conversions, a rules-and-machinery
   question the user wants thought through carefully before any
   implementation. Do not implement casually; do not let its needs leak into
   the converter build.

36. **The anytime food→resources / food→points buys are FREE-SPAN** (ruled
   2026-07-06): available throughout the harvest span (field phase through
   end-of-harvest), NOT anchored to the last in-harvest moment. This DROPS
   the previously-approved late-anchor approach (its dominance argument
   fell to the Social Benefits counterexample: buying before the
   post-feeding "no food left" check can be strictly profitable).
   Consequence: Furniture Carpenter migrates off its FEED-only seam to
   free-span when the converter cluster builds; Paintbrush's VP option and
   Stone Sculptor's buy are free-span. Revisitable ("we can change this
   later if we want").
37. **The frontier boundary rule CONFIRMED** (2026-07-06): the generalized
   conversion frontier (ruling 34) integrates PURE goods→food converters
   only; any card whose output carries a rider — goods (Ebonist, Basket
   Carrier) or points (Stone Sculptor, Paintbrush's VP option) — surfaces
   as a standalone free-span trigger instead. Revisitable.
38. **Lumber Virtuoso is available throughout the harvest** (ruled
   2026-07-06, resolving its ask-at-build timing question): free-span, not
   start-of-harvest-only (the official implementation's narrowing is not
   followed here). [3+] — a design input until 4p.
39. **Post-breed cooking protection** (ruled 2026-07-06, the user's catch):
   after the breed action has resolved, the PARENTS and the OFFSPRING of a
   type that bred may not be cooked for the rest of that harvest — only
   non-parents. The user's implementation sketch: a per-type cooking FLOOR
   on post-breed in-harvest conversions — a type may not be cooked from
   (min_parents + 1) or above down below (min_parents + 1), i.e. below 3,
   or below 2 for sheep with Dolly's Mother in play. This becomes LIVE
   exactly when the converter cluster lands (today nothing cooks animals
   after breeding — the feed payment precedes breeding and the breed
   commit's own bundled cooking happens AT the commit); the generalized
   raise frame and any post-breed cooking surface must apply the floor.
   EDGE RESOLVED (2026-07-06): the user KEPT the shorthand — the floor
   reads CURRENT counts at cook time (a type at >= 3 may not be cooked
   below 3; >= 2 not below 2 for sheep with Dolly's Mother) and, crucially,
   is STATELESS: no breed-record is needed at all — the user's own
   observation ("how would a player end at 3+ without
   [CORRECTION 2026-07-13, user-driven: this record originally claimed the
   shorthand "slightly over-protects the capacity-blocked corner (parents
   whose newborn never fit)". That is WRONG — at count 2 the floor (3) does
   not bind and both animals stay cookable, and under the official
   only-if-room rule a capacity-blocked pair never bred and is correctly
   unprotected, so the floor is EXACT there. The real over-protection
   corners are: (a) a breeding-SKIPPED player (Layabout) holding 3+ — the
   stateless floor cannot tell they never bred; (b) the currently
   unreachable class of post-breed non-breed animal gains reaching 3+.
   Neither has an explicit user ruling yet.]
   breeding?") exposed that the record was only required under the stricter
   parents-and-offspring reading.

40. **Whole-phase-per-player banding extends to FEED and BREED; the outer
   harvest moments stay shared** (ruled 2026-07-06, extending ruling 3): the
   virtual walk gains a FEED band (start_of_feeding → the payment →
   after_feeding) and a BREED band (start_of_breeding → the breeding →
   after_breeding), each resolved wholly by one player before the other
   begins (starting player first), exactly like the existing FIELD band —
   the payment/breeding frames push one player per band pass instead of
   pairwise. The four OUTER moments — immediately-before-harvest,
   start-of-harvest, end-of-harvest, after-harvest — are SEPARATE from the
   three phase bands and keep their own windows, resolving
   both-players-per-moment as today. No frame or card changes; a walk-order
   engine change (full suite + C++ gates on landing).
41. **Field Cultivator becomes AUTOMATIC-take-the-maximum** (ruled
   2026-07-06): the per-occasion pile take is no longer a choice — the owner
   takes min(tiles harvested, pile remaining) goods automatically, the
   Scythe Worker mandatory-max precedent (document the simplification in
   the module; if a card ever makes holding building resources a liability
   or partial takes meaningful, restore the choice — the trigger form is in
   git history).
42. **Cooking Hearth Extension (C62) is DEFERRED alongside Gypsy's Crock**
   (user, 2026-07-12): it is pulled OUT of the converter-cluster build
   (ruling 34's queue had slotted it there as a `cooking_rates` doubler).
   Both cards modify how cooking itself works, and the user wants to decide
   how cooking-modifier cards are implemented as one dedicated design pass
   (the ruling-35 class) rather than piecemeal. Do not implement until that
   decision is made.
43. **Lettuce Patch (C70) "immediately" placement** (ruled 2026-07-12 — a
   per-instance "immediately" ruling under the ruling-18 standing
   instruction): "you can immediately turn each vegetable you harvested from
   this card into 4 food" is an optional trigger offered at the take
   occasion, ALONGSIDE the other optional triggers that fire on the field
   phase's harvesting action (the PendingHarvestOccasion stretch — Food
   Merchant's home). "Immediately" does not jump the queue ahead of them.
44. **Crop Rotation Field (E70) "immediately sow"** (ruled 2026-07-12):
   the granted opposite-crop sow on itself surfaces at the SAME trigger
   location as Lettuce Patch's convert — the removal-occasion optional
   stretch. Normal sow semantics (costs the supply crop), targets only this
   card, declinable ("you can"). Its firing condition stays the wider
   "remove" verb (any last-crop departure, the E-deck lexicon) — when a
   future non-take remover (e.g. Game Provider) empties the card, the sow
   is offered at THAT removal's instant.
45. **"Field tile" vs "field" — the lexicon** (ruled 2026-07-12, extending
   ruling 32): "field TILES" means the plowed fields on the farmyard grid;
   "field" is the BROADER category and includes card-fields. So a card-field
   counts for field-count readers — the Fields scoring category and any
   "you need N fields" requirement — while per-TILE readers still exclude it
   (ruling 32 unchanged).
46. **Per-FIELD harvest modifiers reach card-fields** (ruled 2026-07-12):
   Scythe Worker's per-grain-field extra, Stable Manure's donors, Grain
   Thief's replace targets — a card-field holding the qualifying crop is
   eligible. The take-modifier fold-fns must scan card-fields alongside the
   grid cells when the card-fields wave lands.
47. **Wood Field (D75) / Rock Garden (E80) stack semantics** (ruled
   2026-07-12): "as though it were 2/3 fields" = 2/3 independently-sowable
   STACKS (each sown separately, grain-like 3 wood / veg-like 2 stone per
   sow); the field-phase take harvests 1 from EACH non-empty stack; "but it
   is considered 1 field" scopes only the field-count readers of ruling 45
   (each card counts as exactly 1 field there).
48. **The sow-grant lexicon + the capped-sow accounting** (ruled 2026-07-12,
   from the full-catalog sow survey; the official clarification pair
   adjudicates it): a GENERIC "Sow" grant — even limited ("for exactly 1
   field": Chief Forester A115, Furrows D3, Changeover D71) — may target
   wood/stone card-fields (Chief Forester's clarification: "You may sow 2
   wood onto the Wood Field D075"); a CROPS-EXPLICIT grant ("sow crops" /
   "1 crop": Fodder Planter D115, Apiary E23) may NOT (Fodder Planter's
   clarification: "You may not plant onto Wood Field D075 this way") —
   crop-growing card-fields remain legal targets for both. Cap accounting:
   a card-field consumes exactly ONE field-unit of any capped sow's budget
   regardless of stacks, and that one unit may fill ANY subset of its empty
   stacks ("You may plant 2 wood at once with 1 trigger" — the "may"
   implies 1 is also fine). Within a normal uncapped sow, stacks are sown
   independently (Plant Fertilizer C8's clarification treats them as
   independent piles). Encoding: `PendingSow.crops_only` flag set by
   crops-explicit granters; default False (generic) — Family-inert, so
   canonical default-skip. Side note for future sow-modifier cards: the
   catalog's good-vs-crop wording is deliberate (Skimmer Plow / Cow Patty /
   Wild Greens say "good"; Tinsmith Master is clarified to grain/veg only).

49. **The round-end timing ladder** (ruled 2026-07-12): the returning-home
   phase is the round's LAST phase (preparation, work, returning home), and
   the "end of the round" is a DISTINCT, LATER instant — the returning-home
   seam fires BEFORE the end-of-round seam. The rungs, in order:
   `end_of_work` (the work phase's end, still DURING the work phase —
   Straw Hat E10 / Iron Hoe E20 / Apiary E23 / Sundial E26 / Piggy Bank E27 /
   Master Renovator E87 name this instant directly; Archway's placement here
   was REVISED to the after_work rung by ruling 50), then
   `start_of_returning_home` (before the phase — Turnip Farmer, Minstrel,
   Bohemian, Food Distributor, Sample Stable Maker), then `returning_home`
   (the phase itself — the "in the returning home phase" family, Silage
   included: its printed anchor plainly names the phase), then
   `after_returning_home` ("immediately after each returning home phase" —
   Steam Plow D18 — is CONCURRENT with it, a per-instance "immediately"
   merge), then `end_of_round` (Baking Course D64, Credit A54, Lifting
   Machine A70, Sculpture Course B53 — the "at the end of each round"
   family). The "that does not end with a harvest" condition suppresses its
   bearer on harvest rounds; UNCONDITIONED returning-home cards fire
   normally on harvest rounds, in the returning-home phase that precedes
   the harvest — the returning-home phase is DISTINCT from the harvest.
   (Perennial Rye C84's anchorless "Each round that does not end with a
   harvest" placement: proposed end_of_round with its condition-family
   siblings, NOT yet confirmed by the user.)

50. **The after_work rung + the ambiguity-defer category** (ruled
   2026-07-12): a separate `after_work` hook sits AFTER the `end_of_work`
   hooks and before `start_of_returning_home` — its members are Informant
   B117 ("After each work phase...") and Archway D51 ("Immediately before
   the returning home phase..." — revising ruling 49's initial
   end-of-work placement; the user: "this inconsistent wording is
   annoying"). The full round-end ladder is therefore: end_of_work →
   after_work → start_of_returning_home → returning_home (fired BEFORE
   `_resolve_return_home` resets placements, so the live board is the event
   data — the user's Swimming Class design, generalized) →
   after_returning_home → end_of_round → (the harvest, on harvest rounds,
   or the next round's preparation). **Perennial Rye C84 is DEFERRED FOR
   AMBIGUITY** (its anchorless "Each round that does not end with a
   harvest" confused the user too) — the first member of the new
   ambiguity-defer category below, distinct from the power bans. Out of
   scope for this arc (confirmed): Delayed Wayfarer E125 (extends the work
   loop's termination), Steam Machine C25 / Market Master E131 (own-last-
   placement instants, not the shared boundary).

51. **Baking Course D64 supplies a GLOBAL baking rate** (ruled 2026-07-12):
   its second sentence ("'Bake Bread' action: Grain → 2 Food") is the card
   supplying an UNLIMITED grain→2-food conversion rate during ALL Bake
   Bread actions, "just like the fireplace does" — a standing baking source
   (the BAKING_SPEC_EXTENSIONS seam), NOT a rate scoped to the bake the
   card's first sentence grants. The grant itself is an optional
   end_of_round bake (non-harvest rounds, ruling 49's rung).

52. **Dolly's Mother does NOT reach Silage's mid-round breed** (ruled
   2026-07-12): Silage's pair threshold is a FLAT 2 for every type — Dolly's
   Mother's printed scope is "during the breeding phase of a harvest", which
   Silage's returning-home breed is not, so the `sheep_min_parents` seam
   deliberately does not apply there (it keeps reading through everywhere
   its printed scope covers).
53. **Heresy Teacher A113 is UN-IMPLEMENTED and moved to the ambiguity
   defers** (user, 2026-07-12): the sole producer of mixed grain+veg fields
   ("Place the vegetable below the grain") made every per-field interaction
   ruling too complicated and unclear (the Scythe-E73 "all the crops" gap,
   the crop-count group keys, the card-field mixed stacks). Its module +
   tests are archived under `archive/deferred_cards/` (never deleted). The
   card's own text is clear — the deferral is about its interaction surface.
   CONSEQUENCE: mixed grain+veg fields are now UNREACHABLE (grid and card
   stacks alike), so the flagged mixed-field wrinkles are moot until it (or
   another mixer) returns; the machinery keeps supporting mixture (the
   card-field 4-tuple stacks, the take's grain-precedence) — that generality
   stays correct and tested at the seam level.

Also settled in this design thread: C++ byte-identity is **not** a constraint on this
redesign — design the Python harvest machinery on its merits and re-port to `cpp/` if a
Family-shape change falls out (the user explicitly deprioritized gate-preservation here in
favor of the best card-engine design). And per the CLAUDE.md Phase-3 directive added
2026-07-03: **4-player is an eventual goal — [3+]/[4] cards are design inputs** for this
machinery (e.g. Old Miser's per-person feeding discount, Game Provider's immediately-before
field-crop discard, Champion Breeder's newborns-placed count), even though they aren't dealt
at 2 players.

54. **The preparation ladder** (ruled 2026-07-14; order REVISED by the user the
   same day). The start of the round IS the start of the preparation phase
   (the pre-ladder engine's single `start_of_round` event — fired at the END
   of preparation, after the WORK flip, conflating "start of each round" with
   "start of each work phase" — was wrong on both counts). The ruled order,
   each an explicitly DISTINCT instant: **before the round → round card
   revealed → round-space goods collected → start_of_round → replenishment →
   before the work phase → start of the work phase.** (The first draft
   collected before the reveal; the user corrected it — reveal first — which
   also restored the pre-ladder Family order, so the C++ twin needed no
   change in the end.) Built as the third timing ladder
   (`agricola/cards/preparation.py`, `engine._advance_preparation` —
   CARD_ENGINE_IMPLEMENTATION.md §5d); re-tagged by printed text:
   Freemason / Cob / Trout Pool → `start_of_work`, Nest Site →
   `replenishment`, Pavior ("at the END of each preparation phase") →
   `before_work`, Small Animal Breeder / Civic Facade ("BEFORE the start of
   each round") → the new `before_round` rung — the ladder's first instant,
   pre-reveal and pre-collection, so Small Animal Breeder's food threshold
   deliberately does NOT count this round's round-space income, and "the
   current round number" there is `round_number + 1` (pre-increment).
   RESOLVED same day: the round-space schedule grants ("at the start of
   these rounds, you can plow the field [on the round space]" — Handplow,
   Plowman, Chain Float, Grassland Harrow, Small Greenhouse, Stable Planner,
   Tree Farm Joiner) resolve at COLLECTION time — the
   `round_space_collection` window, post-reveal but before `start_of_round`
   — not the `start_of_round` rung. No rung question remains open.

55. **Museum Caretaker fires as auto AND trigger at `start_of_work`** (ruled
   2026-07-14): the mandatory "you get" is an automatic effect ordered AFTER
   the window's other autos (the `register_auto(order=)` mechanism — Freemason
   first), PLUS a trigger so same-window TRIGGER grants that newly complete
   the six-goods criterion still yield the point; hard cap 1 point per round
   (`used_this_round` latch shared by both paths). Implementation note (not
   part of the ruling): with today's catalog the trigger half has no live
   firing partner — Cob, the only implemented `start_of_work` trigger,
   requires ≥1 clay itself and cannot flip the criterion — the user confirmed
   2026-07-14 that this is fine; the machinery awaits a criterion-good-
   granting `start_of_work` trigger card.

56. **Sugar Baker's deposited food is a CardStore debt, not board state**
   (ruled 2026-07-14, option (b) of the two representations offered): the food
   owed to Grain Utilization's next visitor rides the owner's CardStore and is
   granted by an any_player `before_action_space` auto — rules-identical to
   food physically on the space (the space maxes at 1 food: any next visit
   collects in its before-phase), with no Grain Utilization machinery change.

57. **Clutterer counts passed-away travelers** (ruled 2026-07-14): "each card
   played after this one" includes a qualifying traveling minor (Wood Pile)
   the owner played and passed on — so the count accrues AT PLAY TIME (the
   `played_card_id` stamp on the play hosts), never as a scoring-time
   tableau diff.

58. **Blighter's "complete stage left to play" = 6 − stage_of_round(current
   round)** (ruled 2026-07-14): the in-progress stage is not complete (stage-2
   play banks 4; round 14 banks 0); and its "may not play any more
   occupations" is the occupation-play blocker consulted at the
   `playable_occupations` chokepoint (one gate, every route).

59. **Prodigy** (ruled 2026-07-14): "improvement" = majors AND minors; "your
   1st occupation" = literally the first occupation played all game, by any
   route; the per-improvement point count freezes at play (the banked-VP
   idiom), per the printed parenthetical.

60. **The deferred after-flip** (ruled 2026-07-14): an "after you [do X]" card
   effect fires after X's FULL effect — everything the effect pushed included
   — never in the gap between X's commit and X's own effect resolving. The
   motivating case: Bonehead's "immediately after each time you play a card
   from your hand, you get 1 wood from this card" must NOT hand over the wood
   in time to fund the played card's own effect (Established Person's granted
   fences). Built as the user's own design: commit executors set an
   `effect_initiated` work-complete signal on their host instead of flipping
   it inline, and `_advance_until_decision` flips the host (firing the
   after-autos, plus the coarse `after_build_improvement` for the two
   improvement hosts) once the host is back on top — i.e. after every frame
   the effect pushed (an on_play's primitive, an oven's free-bake wrapper) has
   resolved. Two corollaries the user approved in the same discussion: the
   **accommodation barrier resolves BEFORE the deferred flip** (a keep-which-
   animals choice raised by the effect is part of the effect settling, so the
   after-autos wait for it too), and the mechanism applies **uniformly to
   every commit-terminated host** (play occupation/minor, sow, bake, plow,
   renovate, build major, family growth, the three animal markets) — one flip
   rule shared with the Delegating hosts' `subaction_complete`. This is a
   Family-visible change (the ovens' free bake is the Family-reachable pushed
   child), re-ported to `cpp/` in the same change with all 139 differential
   gates green. Machinery reference: CARD_ENGINE_IMPLEMENTATION.md §2;
   ordering pins: `tests/test_deferred_after_flip.py`.

61. **The 2026-07-14 card-batch rulings** (all user-ruled in the batch's design
   discussion; each is quoted in its card module's docstring):
   - **Fish Farmer D110**: the use-bonus reading — using Reed Bank / Clay Pit /
     Forest while Fishing holds exactly 1 / exactly 2 / 3+ food pays +2 food
     from the CARD (general supply); no food ever sits on those spaces. The
     misprint "Grove" is corrected to "Forest" in the data file's text (the
     card's own errata), per the user's instruction that our displayed text
     say Forest.
   - **Kindling Gatherer E118**: only food the SPACE itself yields counts —
     card-provided food (Fish Farmer, Brook) never triggers it. Implemented as
     the fixed space list day_laborer + fishing (2p), with the one
     user-anticipated exception hard-coded: a Sugar Baker deposit on Grain
     Utilization IS food on a space, so collecting it pays the wood (the
     order=-1 before-auto reads the deposit before Sugar Baker's collection
     clears it). Traveling Players joins the list at 4 players.
   - **Sowing Master D109**: "an action space with the 'Sow' action" ≡ Grain
     Utilization or Cultivation today (the +2 food fires whether or not the
     player sowed); the equivalence breaks if a future card creates a new
     sow-bearing space — revisit the space list then.
   - **Informant B117**: "after each work phase" = the round-end ladder's
     `after_work` rung (the two wordings name one instant for this card).
   - **Merchant C96**: House Redevelopment's optional improvement step COUNTS
     ("the action is distinct from the action space"); "immediately after" is
     the ordinary after seam on the composite host; "a second time" forbids
     chaining off its own granted action (provenance-gated). OPEN LEAN parked
     for the user: a Merchant-granted second take does NOT fire Small Trader's
     space bonus (provenance ≠ the space) — matches Small Trader's own
     clarification, not explicitly ruled.
   - **Bonehead D118**: "immediately after each time you play a card" is the
     ordinary after seam; "including this one" is paid inside its own on_play
     (net 5 wood on the card, +1 to supply — the same instant), with a
     played_card_id guard so the generic after-auto (which under ruling 60 now
     runs post-on_play) cannot double-pay the self-play.
   - **Optionality confirmations**: Little Stick Knitter's growth, Young
     Farmer's sow, and Stallwright's stable are OPTIONS (triggers), and
     Stallwright additionally requires stable pieces in supply.
   - **Wide vs deep**: Green Grocer / Forest Trader / Bellfounder / Emergency
     Seller surface WIDE (variant triggers / play-variants; Emergency Seller's
     full multiset enumeration — worst case 126 — explicitly approved);
     Beneficiary is DEEP (play the card → an occ/minor/proceed parent → the
     chosen type's cards → the remaining type or proceed → end), built by
     generalizing `PendingGrantedSubAction` to a category set + `occ_cost`.
   - **Master Renovator E87**: "at the end of the work phases" = the round-end
     ladder's `end_of_work` rung; the discount is a renovate cost conversion
     scoped by the new `CostCtx.granted_by` provenance (seam 700d16a).
   - **Field Doctor E92**: "surrounded by 4 field tiles" = ALL surrounding
     cells of the 2-room house, orthogonal AND diagonal, on-board, are field
     tiles (the starting domino has exactly 4 such cells); the data-file text
     is corrected to "Wish for Children" per the card's clarification.

62. **Empty animal markets stay ILLEGAL to place on** (2026-07-14, prompted by
   Fir Cutter's empty-market question; briefly ruled legal, REVERSED by the
   user the same day — the `accumulated_amount > 0` gates stay in both
   engines). The state is unreachable in real play anyway (every revealed
   accumulation space refills each preparation, and a use occupies the space
   for the round), so nothing observable hinges on it today; if a future card
   makes empty+available reachable, re-raise the question. Fir Cutter's
   "empty market still pays" unit test exercises the host flow on a
   constructed state via `step` (which doesn't verify legality), so it
   documents the card's behavior without contradicting the gate.

63. **The 2026-07-15 follow-up-batch rulings** (each quoted in its card module):
   - **Cottar E122**: "immediately after paying its cost" is implemented as the
     improvement's ordinary AFTER window (after the improvement, its effect
     included) — the official online implementation's instant, chosen by the
     user for consistency despite the printed wording naming the payment
     moment. Landing it also gave the play-minor and build-major hosts the
     mandatory-Stop gate their after-phases lacked (the atomic-host pattern;
     Family-inert — the gate is a no-op with no mandatory registrant).
   - **Moral Crusader B106**: "immediately before the start of each round"
     names the SAME instant as the preparation ladder's `before_round` window.
   - **Tinsmith Master B115**: the per-field "+1 crop, you can" is MEANINGFULLY
     DECLINABLE — the sow commit carries per-crop-type boost counts (how many
     sown grain/veg fields take the +1), never an always-max simplification.
   - **`ActionSpaceState.revealed_round`** (user decision): every space records
     the round whose preparation revealed it (permanents 0; deliberately
     redundant with `revealed` to avoid reworking its consumers) — built for
     the reveal-order family (Task Artisan now; Master Workman, Sweep,
     Outrider/Pioneer later). Task Artisan rides the preparation ladder's
     `reveal` window with `revealed_round == round_number` as "appeared this
     round".
   - **Furniture Maker × Forest School — RULED (user, 2026-07-15)**:
     wood-substituted occupation food does NOT count as "food paid as
     occupation cost" (the player paid wood, not food), so Furniture Maker
     grants nothing for a Forest-School-substituted play. Built as a card-only
     guard (no engine change): Furniture Maker subtracts the substitution when
     `"forest_school"` is in the host's `triggers_resolved`. Exact for today's
     catalog because Forest School substitutes the WHOLE printed food cost in
     one fire; a future PARTIAL food-substitution card would need the
     substituted amount tracked. Pinned by
     `test_forest_school_substituted_food_pays_no_wood`.
   - **Emergent interaction noted (falls out of shared machinery, not coded)**:
     an Angler-granted improvement action can be Merchant-doubled — the
     granted composite fires the ordinary after window and Merchant's no-chain
     guard only blocks its own provenance; textually consistent since the
     grant IS "a Major or Minor Improvement action".

64. **The "Major or Minor Improvement" action vs the "Minor Improvement"
   action vs the action *space*** (ruled 2026-07-15 — the recurring
   confusion, now documented explicitly in RULES.md's Primitive Sub-Actions
   ⚠️ callout + CARD_ENGINE_IMPLEMENTATION.md §6). There are two DISTINCT
   primitive sub-actions: the **"Major or Minor Improvement" action** (build a
   major OR play a minor — offered by the Major Improvement space, House
   Redevelopment, and card grants; engine: `PendingMajorMinorImprovement` /
   `after_major_minor_improvement`) and the **"Minor Improvement" action**
   (play a minor only — offered by Meeting Place, Basic Wish for Children, and
   card grants; engine: a bare `PendingPlayMinor` / `after_play_minor`). Card
   text keys off the ACTION (the primitive), never the space. Consequences
   this ruling corrected:
   - **Small Trader** ("+3 food each time you take a 'Major or Minor
     Improvement' action to play an improvement from your hand") keys off the
     'Major or Minor Improvement' action — so it fires on House Redevelopment
     and card grants (Angler; a Merchant repeat), NOT only the Major
     Improvement space; and never on Meeting Place / Basic Wish (those are the
     'Minor Improvement' action). Its prior `initiated_by_id ==
     "space:major_improvement"` gate was an un-ratified narrow reading, removed
     — the `after_major_minor_improvement` event already scopes to the
     composite, so the gate is just `minor_chosen`. Still minors only
     ("from your hand").
   - **Merchant** ("after a 'Major or Minor Improvement' OR 'Minor
     Improvement' action, pay 1 food to take the action a second time") was
     incomplete — it only handled the composite. Now it fires on BOTH action
     types with a TYPE-MATCHED repeat (composite → a second composite; bare
     minor → a second bare minor), and — user-confirmed 2026-07-15 — chains off
     **card-granted** bare minors too (Beneficiary / Task Artisan / Sample
     Stable Maker), by symmetry with Angler firing it on the composite side.
     Guards: no self-chain (`card:merchant`), and the bare-minor clause
     excludes the composite's own child minor (`major_minor_improvement`,
     handled by the composite clause). MACHINERY NOTE surfaced: a card firing
     on two events shares ONE frame-dispatched `apply_fn` (fire dispatch is
     id-keyed via `CARDS`); per-event eligibility is safe (the enumerator reads
     event-keyed `TRIGGERS`).

65. **Forest School replaces the occupation's food cost PER FOOD, priced by the
   route** (2026-07-17; a live-defect find during the tier triage — the card was
   implemented, not deferred, so this is a fix ruling). Two halves:
   - **"Each food that an occupation costs" is a per-unit license**: the player
     may replace any subset — k wood → k food, k ≤ min(food cost, wood held) —
     so MIXED payments are legal (1 wood + 1 food on Writing Desk's 2-food
     granted play). Rebuilt as a play-variant trigger (one FireTrigger per k),
     each k guarded so the play stays payable AFTER the swap (the play host has
     no decline — the standing stranding rule; the same guard filters a k below
     the shortfall).
   - **The price is the frame's `PendingPlayOccupation.cost`**, never re-derived
     from the Lessons ramp. The original implementation computed
     `occupation_cost(len(occupations))` — right on Lessons (identical by
     construction) and coincidentally on Scholar (owning Scholar forces the ramp
     to 1, its flat price), wrong on every differently-priced granted route: a
     phantom 1-wood → 1-food swap on Seed Researcher's FREE play, a mis-sized
     swap on Writing Desk's 2-food play, and an under-recognizing affordability
     gate (2 wood + 0 food could not reach Writing Desk's grant).
   MACHINERY (both Family-inert): `OCCUPATION_FOOD_SOURCES` sources now receive
   the route's actual cost — `source_fn(state, idx, cost)`, all five registrants
   migrated (only Forest School reads it) — and the play-occupation enumerator
   expands variant triggers (`_expand_variant_triggers`, the same
   no-op-when-unregistered wrapper the atomic and delegating hosts use).

66. **The 2026-07-17 tier-1 batch rulings** (each quoted in its card module; the
   batch: Heart of Stone C21, Seed Almanac E18, Recycled Brick D77, Nail Basket
   E15, Profiteering E82, Double-Turn Plow A20, Furrows D3, Pole Barns E1,
   Lumber Pile E76, Thunderbolt E4, Night Loot E5 — 11 minors, all on existing
   seams, no engine change):
   - **"Immediately" adds nothing in this batch** (the standing per-instance
     check, ruled for all seven occurrences at once): the six on-play uses
     (Pole Barns, Furrows, Thunderbolt, Night Loot, Lumber Pile, Double-Turn
     Plow) are the ordinary on-play instant, and Heart of Stone's is the reveal
     window's instant. Triggers on the same instant fire in any player-chosen
     order.
   - **Pole Barns builds stables as a CARD EFFECT, not a "Build Stables"
     action** — the pushed frame carries `build_stables_action=False`, so an
     action-keyed card never fires on it (a verb-keyed "each time you build a
     stable" card still does). Contrast Nail Basket, whose grant IS the literal
     named "Build Fences" action (`build_fences_action=True`).
   - **Double-Turn Plow may stop after 1 field** (the multi-shot plow's
     Proceed-at-≥1; never forced to the second plow).
   - **Thunderbolt enumerates board fields BY GRAIN COUNT** (equal-count board
     fields are interchangeable — the fungible-board-field convention; the
     executor strikes the deterministic lowest-(row, col) representative), while
     each grain-bearing CARD field stays its own variant: card-crop removal
     routes through the ruling-44 `remove_card_crop` chokepoint so its
     registered reactions fire.
   - **Night Loot is unplayable with fewer than 2 different building-resource
     types on revealed accumulation spaces** (a prereq — never a dead-end and
     never a partial take).
   - **Nail Basket's "wood accumulation space" family is the
     `WOOD_ACCUMULATION_SPACES` constant** (agricola/constants.py), hooked over
     the whole set for 4-player forward-compatibility (only Forest is live at
     2 players).

67. **Occupation-cost substitutions are COST CONVERSIONS under
   `action_kind="play_occupation"`** (2026-07-20; Working Gloves E60 built on it,
   Forest School migrated onto it). The rulings:
   - **"Pay X in place of food" cards resolve through the `effective_payments`
     chokepoint**, never as triggers or food sources: one
     `CommitPlayOccupation(payment=...)` per Pareto-minimal way to pay the
     OCCUPATION COST PROPER (the frame's route-supplied cost). Consequences, all
     structural: dominated offers are pruned (the user's requirement — Working
     Gloves' 1-wood payment suppresses Forest School's 2-wood on a 2-food cost;
     identical vectors de-duplicate), double-replacement is inexpressible (a
     payment replaces each food unit at most once), and ruling 65's mixed
     payments are ordinary frontier points. The no-substitution path keeps the
     legacy `payment=None` commit shape.
   - **Surcharges and individual printed costs are SEPARATE from the occupation
     cost and may never be reduced or modified** (user, 2026-07-20) — even when
     the code debits them simultaneously. A play-variant surcharge (Roof
     Ballaster) is added to the debit on top of the chosen payment, outside the
     pipeline; each (variant, payment) commit is gated on the COMBINED debit
     being payable.
   - **Working Gloves always replaces min(2, cost.food)** — "(up to) 2" never
     makes a smaller replacement a real choice (same 1-resource price, strictly
     dominated). The 2026-07-17 catalog scan backs the design: the occupation
     cost proper never exceeds 2 food anywhere (base ramps cap at 2 at 3-4
     players; Moonshine/Writing Desk grant at 2; nothing raises it), so Forest
     School is weakly dominated whenever Working Gloves is co-owned — enforced
     by the prune, not by card logic.
   - **The executor stamps `PendingPlayOccupation.paid_cost`** (base-cost payment
     only, surcharge excluded) alongside `played_card_id`, so "food paid as
     occupation cost" readers (Furniture Maker, ruling 63) are exact under
     partial substitution — the old all-or-nothing `triggers_resolved` guard is
     gone with the trigger it read.
   MACHINERY (all card-only/Family-inert): the `play_occupation` ctx +
   `can_pay`-based `_payable_occupation` (food sources simulate on top),
   payment-carrying wide commits, `CommitPlayOccupation.payment` +
   `PendingPlayOccupation.paid_cost` (both canonical-default-skipped), and the
   occupation-food-source seam re-scoped to PRODUCERS only.

68. **The 2026-07-20 tier-2 batch rulings** are recorded in
   `CARD_ENGINE_IMPLEMENTATION.md` §1 (the batch entry) and quoted per-card in the
   ten tier-2 modules — the number is reserved here so the sequence stays navigable.

69. **The 2026-07-20 tier-3 batch rulings** (each quoted in its card module):
   - **A21 Family Friendly Home** (name corrected from the data JSON's erroneous
     "Family Friend Home"): the rooms>people measure occurs BEFORE the Build Rooms
     action — before the first room is built — so the card lives on
     `before_build_rooms`; and if rooms>people at that instant, the 1 food is given
     whether or not the family growth is accepted (an automatic effect beside the
     optional growth trigger). "Take a 'Build Rooms' action" is read as the NAMED
     action only — gated on `PendingBuildRooms.build_rooms_action`, with Cottager's
     granted build-1-room corrected to set it False per the §9.6 flag contract.
     (The named-action gate — originally the driver's application of the RULES.md
     doctrine — was USER-CONFIRMED 2026-07-20: "gated to the named action only -
     this is correct".)
   - **B17 Forest Plow**: fires AFTER the take — an explicit per-card override of
     the "each time you use = before" default (the deposit is "for the next
     visitor"; before-timing would let the player's own sweep scoop the deposited
     wood straight back). The 2 wood is paid from the player's supply whatever its
     origin, the just-taken wood included — the clarification decouples the effect
     from how much wood the space actually yielded.
   - **C73 Seaweed Fertilizer**: an "unconditional" Sow action = one with no
     constraint on the number of fields sown or the types of crops/goods sown —
     i.e. a `PendingSow` with `max_fields == 0`, `crops_only == False`, and
     `required_crop is None`. Modeled Seasonal-Worker-style (one mandatory
     `after_sow` trigger whose options are round-gated: grain-only before round 11,
     grain-or-vegetable from round 11); the sow host's after-phase gained the
     standard mandatory-Stop gate (mirroring the build-major after-phase).
   - **D80 Brick Hammer**: "costing at least 2 clay" reads the PRINTED cost, never
     the payment actually made; for an improvement with multiple printed
     alternative costs, ANY >=2-clay alternative qualifies even when the player
     paid the alternative without clay (so a Cooking Hearth bought by returning a
     Fireplace qualifies — printed 4/5 clay). Machinery: the ownership-gated
     `PendingBuildMajor.built_major_idx` identity stamp
     (`register_build_major_identity` in `cards/triggers.py`).
   - **D1 Zigzag Harrow**: "zigzag" means, verbatim, a pattern like
     {(x, y), (x+1, y), (x+1, y+1), (x+2, y+1)},
     {(x, y), (x, y+1), (x+1, y+1), (x+1, y+2)},
     {(x, y), (x+1, y-1), (x+1, y), (x+2, y-1)}, or
     {(x, y), (x-1, y+1), (x, y+1), (x-1, y+2)} — the four orientations of the
     S/Z tetromino; the plowed field plus 3 existing field TILES must form one,
     translated anywhere on the farmyard. Machinery: `PendingPlow.allowed_cells`
     (mirroring `PendingBuildStables.allowed_cells`).
   - **E3 Tea Time**: the vacated space is OPEN — what makes a space illegal to
     place on is solely the presence of a worker on it; there is no residual
     "used this round" block, so either player may use Grain Utilization again
     that round after the return.

70. **The 2026-07-20 approvals batch** (user approvals + the Stone Clearing
    engine layer; each card ruling quoted in its module):
   - **Cluster C3 is APPROVED** (user, 2026-07-20): "take a good off an
     accumulation space without placing a worker" is a sanctioned mechanism —
     an optional trigger that edits `sp.accumulated`. Both members built:
     **A82 Work Certificate** (an `after_action_space` play-variant trigger on
     every own space use; its printed threshold "at least 4 building resources
     on it" is read as the TYPELESS total on the space, any mix — contrast
     Material Hub's typed wording — and any building-resource type present is
     takeable (USER-CONFIRMED 2026-07-20: "typless total is correct, and the
     player can take any resource type that exists on the relevant space");
     its clarification "Can be immediately triggered" means the very
     use that plays the card may fire it, the machinery's natural
     ownership-at-fire-time behavior) and **B81 Handcart** (a `before_work`
     prep-window play-variant trigger; the space's FAMILY sets the threshold
     NUMBER — wood 6 / clay 5 / reed 4 / stone 4 — but per the user's ruling,
     2026-07-20 verbatim: "the X resources of the same type do not need to be
     the native type of the action space. Additionally, the player can take
     any resource from the space, not just the resource that has a count of
     X+." — so ANY single type reaching the number qualifies the space, and
     any building-resource type present is takeable. This CORRECTED the
     driver's first-pass native-type analog of the Material Hub ruling).
   - **C6 Stone Clearing — the engine layer** (user go-ahead 2026-07-20, with
     the explicit instruction that stone-holding fields must never read as
     empty for sowing, card prerequisites, or card effects): `Cell.stone` +
     the `Cell.field_empty` / `Cell.field_planted` single-definition
     predicates; every emptiness/planted read swept onto them (sow legality,
     the sow executor, the restricted wrapper, and the reader cards —
     Greening Plan, Potato Digger, Asparagus Gift, Fern Seeds, Fodder
     Planter, Slurry Spreader C71 now exclude stone fields from
     empty/unplanted; Field Clay, Garden Claw, Ash Trees count them as
     planted per the errata "considered planted until the stone is gone");
     the field-phase take harvests stone normally (1/phase to supply, a
     `crop="stone"` manifest entry). **The scope question was RULED same day**
     (user, 2026-07-20, verbatim): ""place 1 stone on each of your empty
     fields" cover[s] empty card-fields too … Stone Clearing should place 1
     stone on all fields, including cards like beanfield and wood field that
     have restrictions on what can be sowed on them (wood field would get 1
     stone not 2)" — so every empty card-field gets exactly 1 stone per CARD
     (into one stack), sow-goods restrictions never restrict the placement,
     and the module is IMPLEMENTED. One driver-adopted reading rides along,
     TENTATIVELY AGREED by the user (2026-07-20 — "this is an interesting
     question. I will tentatively agree"; provisional, may be revisited):
     stone in one Wood Field stack leaves the other
     stack wood-sowable (the machinery's established per-stack sowability —
     the same behavior as a half-wood-planted Wood Field; the errata's
     "considered planted" is the field-level reader status).

72. **The 2026-07-21 boundary-buster batch** (user rulings 2026-07-21; each
    quoted in its card module):
   - **Carpenter's Bench B15 is 🚫 WONTFIX** — its "the taken wood (and only
     that)" payment-source restriction is the §8 goods-provenance cost gap,
     ruled not worth building for this card.
   - **Stone Company A23**: "immediately after each time you use a Quarry
     space" = the quarry host's after window; the grant is the NAMED composite
     with the new `CostCtx.min_spend=Resources(stone=1)` filter (post-modifier,
     pre-Pareto — the printed Stonecutter clarification is emergent); the
     Fireplace-return route never satisfies the constraint; a Merchant repeat
     is a fresh, unconstrained composite.
   - **Firewood C75**: "Fireplace / Cooking Hearth / oven" are the RULES.md
     collective terms INCLUDING the minor improvements whose name's second
     word is Oven/Fireplace (slug suffix `_oven`/`_fireplace` — iron_oven,
     simple_oven today; `oven_site` excluded); the deposit wood is from the
     general supply; "up to 4" is offered take-max only (min(4, stock) — the
     ruling-41 dominance shape); firing restricts the pending build/play to
     the qualifying targets (`allowed_majors` ∩ / the new
     `PendingPlayMinor.allowed_cards`).
   - **Fatstock Stretcher D56**: implemented as +1 to the sheep and boar
     cooking rates, per-component ONLY where the base conversion exists —
     (2,2,3)→(3,3,3), (0,0,0) stays (0,0,0), (3,0,5)→(4,0,5); flows through
     `cooking_rates` into every cook site; card-driven exchanges (not via a
     cooking improvement) get nothing. This builds the cooking-rate injection
     seam (`cooking_mods.py`) — the ruling-42 cluster's additive member may
     proceed ahead of the full cooking-modifier design pass.
   - **Renovation Company A13** (un-deferred — its 2026-07-15 blocker was the
     then-missing zero-cost grant parameter, since built as `cost_override`):
     "immediately after" = within the card's play; the free renovate keeps
     the NORMAL target menu (Conservator's wood→stone composes, free either
     way); the decline is the play-variant choice (the clarification's
     non-bankable decline); under a renovate-forbid card the renovate variant
     is withheld (the never-offer-a-dead-end rule) and the card stays playable
     for its unconditional +3 clay.

---

## Deferred for AMBIGUITY (the printed text is unclear — distinct from the power bans)

Cards here are set aside because their PRINTED TEXT does not determine a reading —
not because of strength (the banned list) or missing machinery (the defer clusters).
Each entry needs the user to pick a reading (or an official clarification to
surface) before implementation.

- **Perennial Rye C84** (minor; "Each round that does not end with a harvest, you
  can pay 1 grain to breed exactly 1 type of animal. (This is not considered a
  breeding phase.)") — deferred 2026-07-12 (ruling 50): the timing anchor is
  missing entirely (every sibling names "the end of each round" or "the returning
  home phase"), and the user found the card's intent unclear ("perennial rye does
  seem confused").

- **Heresy Teacher A113** (occupation, [1+]; "Each time you use a 'Lessons' action
  space, you get 1 vegetable in each of your fields with at least 3 grain and no
  vegetable. Place the vegetable below the grain." Clarification: "Fields with both
  crops can count as a grain field or a vegetable field, but not both
  simultaneously.") — UN-implemented and placed here by the user 2026-07-12
  (ruling 53): the card itself is clear, but as the only mixed-field producer it
  made the per-field interaction rulings too complicated; archived under
  `archive/deferred_cards/`.

- **Lumber Virtuoso D129** (occupation, [3+]; "Each harvest in which you have at
  least 5 wood in your supply, you can discard down to 5 wood to take a "Build
  Stables" or "Build Wood Rooms" action by paying the usual costs." Clarification:
  the "Build Wooden Rooms" action is a "Build Rooms" action limited to wood.) —
  placed here by the user 2026-07-12 (superseding the earlier waits-for-4p
  status; ruling 38's free-span timing stands if it is ever un-deferred). The
  "discard down to 5 wood" quantity clause does not determine a reading.

## Deferred 2026-07-12 — Braid Maker E109 (the converter cluster's one defer)

**Braid Maker (E109, occupation)**: "Each harvest, you can use this card to exchange
1 reed for 2 food. You can build the Basketmaker's Workshop for 1 reed and 1 stone
even when taking a "Minor Impr." action." The FIRST clause fits the converter seam
exactly (a pure reed->2-food `HarvestConversionSpec` + `frontier_fire`). The SECOND
clause needs a seam that does not exist: a play-MINOR surface (Basic Wish's minor
branch, Meeting Place's optional minor, the improvement spaces' play-minor branch)
additionally offering the build of one specific MAJOR at an alternate cost. The
existing composite host runs the other direction (the Major/Minor space offering
both), and no legality extension lets a card inject a major build into minor-only
surfaces. Per §0.1 and the recorded 2026-07-12 refinement (HARVEST_HANDOFF.md §16
item 3), a card defers WHOLE when any clause doesn't fit — implementing only the
converter clause would be an approximation. Build proposal: a
`register_minor_action_major_build(card_id, major_idx, alt_cost)` legality
extension on the play-minor enumerators; small, but user-gated like the other
shared-infra proposals.

## Group A — small, well-scoped, high-yield (recommend building on approval)

### A1. Card-granted Family Growth with NO space placement
> **PRIMITIVE BUILT 2026-07-03** (commit "card-granted family growth — place_on_space=False"):
> `PendingFamilyGrowth.place_on_space` landed exactly as proposed below, with tests
> (`tests/test_family_growth_grant.py`). The member cards are NOT yet implemented — Autumn
> Mother (C92) and Bed in the Grain Field (C24) ride the harvest-window card wave
> (HARVEST_WINDOWS_DESIGN.md); A93 / B92 / A21 below still await their own batch, and the
> A21 question (room-count timing + food coupling) is still open.

**Cards unblocked:** A93 Bed Maker, B92 Little Stick Knitter, A21 Family Friendly Home (rescued;
name corrected 2026-07-20 — the data JSON's "Family Friend Home" was wrong).

**Blocker.** Per the rules (your ruling), a card-granted "Family Growth" places the newborn on **no
action space**. But the engine's only growth primitive, `PendingFamilyGrowth`, resolves through
`_execute_family_growth` → `_resolve_wish_for_children`, which **forces** placing the newborn worker
on a board space (`_update_space(space_id, workers=…)`). So there is no correct `initiated_by_id` for
a card grant — a real space id mis-places the newborn (and would be read by worker-scanning cards like
Wood Pile), and a `"card:…"` id `KeyError`s.

**Proposed build.** Add `place_on_space: bool = True` to `PendingFamilyGrowth` (card-only, default
`True` → Family byte-identical; add to `__hash__` + skip-fields). Factor the people-increment out of
`_resolve_wish_for_children`; in `_execute_family_growth`, when `place_on_space=False`, increment
`people_total`/`newborns` **without** the `_update_space` call. Each card pushes
`PendingFamilyGrowth(initiated_by_id="card:<id>", place_on_space=False)` from an **optional**
`after_build_rooms` (A93, A21) / `before_action_space` sheep_market (B92) trigger, with eligibility
gated on the room predicate `people_total < 5 and people_total < _num_rooms(p)` (the primitive does
**not** self-check this) and, for A93, the 1-wood-1-grain cost.

**Effort:** ~15 lines engine + 3 thin card modules. **Risk:** low.
**Question (A21 Family Friendly Home only) — RESOLVED (user ruling 2026-07-20, ruling 69):**
"if you have more rooms than people" is measured **before** the Build Rooms action (before the first
room is built) — the note above proposing `after_build_rooms` / a post-build default is superseded;
the card lives on `before_build_rooms`. And the **+1 food is unconditional on the condition**: if
rooms>people at that instant, the food is given whether or not the family growth is accepted.
(Implemented 2026-07-20 as `family_friendly_home.py`.)

### A2. "On your turn" build exclusion (off-turn builds don't trigger)
**Cards unblocked:** A43 Farmyard Manure, A74 Stable Tree.

**Blocker.** Both schedule goods "each time you build 1+ stables **on your turn**," and the printed
clarification excludes off-turn builds (Groom B089 / Stable Planner A089). A naïve `after_build_stables`
auto also fires on those start-of-round grants.

**Proposed build.** A card-local eligibility predicate — the build is "on your turn" iff **no
preparation-window choice frame is on the stack**. In the current card set every off-turn stable
build is a preparation-ladder grant (Groom at `start_of_round`, Stable Planner at
`round_space_collection`), which carries a `PendingHarvestWindow` frame with a prep window id at
the bottom of the stack; a real worker-placement build never does. So "no `PendingHarvestWindow`
whose `window_id` is in `preparation.PREP_STEPS`" in the auto's eligibility is exact today. No
engine change. I'd add a shared helper `_is_on_turn_build(state)` for reuse.

**Effort:** ~5 lines/card + a 3-line helper. **Risk:** low-medium — correct for *all* current off-turn
sources; a future card that builds stables on the **opponent's** turn would need the predicate widened
(flag it then). I recommend building; it's a clean, testable predicate.

### A3. Minor-improvement play-variant (on-play binary choice)
**Cards unblocked:** B41 Hauberg (with A6 schedule_animals), B9 Beating Rod (partial — see note), and the
whole "you decide what to start with" family; also a prerequisite for some Group-B renovate cards.

**Blocker.** A *minor* with an on-play choice ("get 1 reed **or** −1 reed +1 cattle"; "start with
wood **or** boar") can't be expressed — play-variant machinery is **occupation-only**
(`register_play_occupation_variant`; `CommitPlayMinor` has no `variant`, the enumerator emits no
per-variant commits).

**Proposed build.** Mirror the occupation path: a `PLAY_MINOR_VARIANTS` registry +
`register_play_minor_variant(card_id, variants_fn)`; the `PendingPlayMinor` enumerator offers one
`CommitPlayMinor` per legal variant; `on_play` becomes `(state, idx, variant)`. (Symmetric with the
existing Roof-Ballaster occupation path, so the shape is proven.)

**Effort:** ~30 lines engine. **Risk:** medium (new enumerator branch; needs a test for the
two-variant offer + each on_play).
**Note (B9 Beating Rod):** even with this, the "+1 cattle" variant is an **immediate** animal grant,
which has no accommodation path (only scheduled/market/breeding/harvest do). So B9 needs *both* this
**and** an immediate-animal-accommodation decision — keep it deferred until we decide the immediate-grant
policy (see C-note). B41 Hauberg, by contrast, **schedules** its boar (sound per the red-team), so it is
fully unblocked by A3 + A6.

### A4. Optional renovate grant (declinable)
**Cards unblocked:** B1 Upscale Lifestyle; partially Renovation Company (A13 — **BUILT 2026-07-21**,
ruling 72, as a `cost_override` play-variant), Established Person (B88).

**Blocker.** A card that grants an **optional** renovation ("if you take the action…") can't use a bare
`PendingRenovate` — its before-phase enumerator emits only `CommitRenovate`, no `Stop`, so there's no
decline path.

**Proposed build.** A `PendingGrantedRenovate` choose-or-decline wrapper, exactly mirroring the existing
`PendingGrantedBuildFences` (sole sub-action `renovate` → push real `PendingRenovate`; the wrapper's
`Stop` is the decline). No change to House Redevelopment / Cottager.

**Effort:** ~20 lines. **Risk:** low-medium.

### A5. Bottom-row major classification — IMPLEMENTED (2026-07-15, `wage.py`)
**Card:** B7 Wage ("+1 food per owned bottom-row major improvement").

**Built:** `BOTTOM_ROW_MAJORS = frozenset({5, 6, 7, 8, 9})` (Clay Oven, Stone Oven, Joinery, Pottery,
Basketmaker's Workshop); Wage's on-play read counts owned bottom-row majors off
`board.major_improvement_owners`. Top row = {Fireplace ×2 (0,1), Cooking Hearth ×2 (2,3), Well (4)}.

**Confirmed (user, 2026-07-15):** the **Well (idx 4)** is TOP row — NOT counted by Wage; the
implementation is correct as-is. This top/bottom classification is now pinned (Well = top) for the
≥1 other card expected to reuse it.

### A6. `schedule_animals` helper + Acorns Basket
**Cards unblocked:** B84 Acorns Basket (and the boar half of B41 Hauberg with A3).

**Blocker.** No `schedule_animals` helper (only `schedule_resources` for `Resources` and
`schedule_effect` for effect ids). The accommodation path itself is **sound** (red-teamed this session).

**Proposed build.** Add `schedule_animals(state, idx, rounds, Animals)` to `cards/schedules.py`,
mirroring `schedule_resources` but writing `FutureReward(animals=…)` additively. Acorns Basket's
`on_play` then schedules 1 boar onto its target rounds.
**RESOLVED (2026-06-30, user ruling recorded in `acorns_basket.py`):** the 2 round spaces are the
NEXT 2 rounds (R+1, R+2). Built on `schedule_animals`; this item is done — kept for provenance.

### A7. Passing-status confirmation
**Card unblocked:** B5 Store of Experience (an otherwise-trivial tiered on-play; ~15 lines once known).
**Question:** is Store of Experience a **passing/traveling** minor (like Market Stall — executed then
handed to the opponent) or **kept**? Its text gives no passing instruction and the `passing_left` data
field has proven unreliable (it appears on both traveling and kept cards). Passing changes ownership +
scoring, so I won't guess.

---

## Group B — medium infra (build with more design care)

### B1. Resource high-water-mark latch — B35 Hook Knife
"Once this game, when you have 8 sheep → +2 VP." The one-shot latch sweep (`_fire_ready_one_shots`) only
runs at the play-card/renovate seams, never on an animal-count change, so it never fires at the right
moment. **Plan:** either call the sweep at every animal-count-increasing site (markets, breeding,
scheduled collection), or add a dedicated resource-threshold latch checked there. Generalizes to
boar/cattle/grain/veg threshold cards. **Medium effort, medium risk** (new call sites).

### B2. Passing-card-excluded after-event — B49 Scales
"+2 food when your occupations = your improvements; **passing cards never trigger this**." But
`after_play_minor` fires for passing minors too, and the auto signature `(state, owner)` can't tell a
passing-fire from a coincidentally-equal count. **Plan:** add an `after_play_kept_minor` event fired only
when `minor_improvements` actually grew (cleaner than threading the card id through every auto). **Medium.**

### B3. Build-payment provenance — A41 Vegetable Slicer
"+2 wood +1 veg when you build a Cooking Hearth **by returning a Fireplace**." `after_build_major` never
receives `commit.payment`, and post-build state can't distinguish "upgraded from my Fireplace" from
"never owned one." **Plan:** thread the `CommitBuildMajor` payment/variant into the `after_build_major`
event, or snapshot fireplace ownership before/after via CardStore. **Medium.**

### B4. Consumed-space snapshot + improvement grant — A95 Angler
"Each time you take ≤2 food from Fishing → you may play a Minor/Major Improvement." The catch amount is
zeroed by the resolver, so the ≤2 test needs a **before**-snapshot (CardStore), and firing pushes a
`PendingMajorMinorImprovement`. **Plan:** before_action_space snapshot the catch; after_action_space
optional trigger gated on stored catch ≤2 → push the improvement. **Verify** a card can push
`PendingMajorMinorImprovement`. **Medium.**

### B5. Scheduled-goods provenance — B76 Ceilings — BUILT 2026-07-20
"On next renovate, remove the wood **this card** still has promised on round spaces." `future_resources`
is a flat additive tuple with no per-card provenance, so a blind subtract is wrong when another scheduler
wrote the same slots. **Plan (executed as written, user-approved 2026-07-20):** a CardStore record of
which round slots Ceilings seeded; the mandatory `after_renovate` auto subtracts only its own
still-future wood and clears the record (the once-only latch). `ceilings.py` is the exemplar for any
future "take back promised goods" card.

---

## Group C — deliberate engine boundaries (a design decision, not just code)

### C1. Standalone "buy food → good" / at-any-time conversion
**Cards:** B70 New Purchase (round-start 2 food→1 grain / 4 food→1 veg), B82 Value Assets (post-harvest
food→building-resource buys), B29 Cookery Lesson (use a cooking improvement *the same turn*), B32 Kettle,
B69 Potters Market, A60 Oriental Fireplace, plus the §15 Grocer/Clay Carrier family.
**The boundary.** The engine deliberately never surfaces at-any-time / standalone conversions (a rational
agent defers them to where proceeds are needed). These cards each want a standalone optional buy. **Decision
needed:** do we introduce a standalone optional buy-conversion frame, and where is it hosted? B70 fits the
existing `start_of_round` host cleanly (it's the mildest — round-start-gated, no affordability closure); B82
additionally needs an **after-harvest** host that doesn't exist. I'd suggest starting with **B70 alone** as
the first member (lowest risk) if you want to test the shape.

### C2. Action substitution — A97 Freshman
"Instead of taking a Bake Bread action, you can play an occupation." Substitution (not the additive grant
the triage first assumed) + a legality change. Needs substitution machinery. **Question:** scope of "each
time you get a Bake Bread action" — only Grain Utilization's bake, or every granted bake (Oven Firing Boy /
Bread Paddle / the ovens)? And does its once-per-turn cap span sources? Defer until the substitution model
is designed with you.

### C3. Take-from-accumulation-without-placement — RESOLVED: APPROVED (user, 2026-07-20; ruling 70)
You flagged this exact mechanism as a blocker; on 2026-07-20 you approved it. Both members are
IMPLEMENTED (ruling 70): **A82 Work Certificate** (`after_action_space` play-variant trigger,
typeless ≥4 threshold) and **B81 Handcart** (`before_work` prep-window play-variant trigger,
6/5/4/4 thresholds keyed to the space family but satisfiable by ANY single type, any present
type takeable — ruled 2026-07-20, correcting the first-pass native-type analog). Kept for
provenance; no longer a blocker for future cards of this shape.

### C4. Multi-plow chain — A18 Wheel Plow (rescued)
The rescue proposed chaining `PendingPlow` via an `after_plow` re-arm (a 2-plow grant, once per game). It's
plausible but **unproven** — no existing card chains plows this way, and the re-arm/termination gating
(only re-arm from this card's own chain, cap at 2) needs careful testing. **Decision:** want me to build it
as proposed, or hold for the cleaner "bounded multi-plow" primitive (which would also unblock Double-Turn
Plow A20)?

### C5. Complex composition — B93 Confidant (rescued)
Buildable in principle (play-occupation-variant N=2/3/4 + scheduled food + a round-start sow/fences play-
variant grant), but it composes 4–5 mechanisms at once — high implementation risk. I'd build it **after**
A3 (minor play-variant) lands and only with a careful test. Holding for your go-ahead.

---

## The long tail — genuinely blocked (each needs a substantial new subsystem)

These are correctly deferred; grouped by the missing subsystem, for visibility (not proposing to build):

- **Grid/adjacency geometry:** Homekeeper (A85), Farm Hand (B85), Future Building Site (B38),
  Love for Agriculture (B72), Pottery-Yard-style orthogonal adjacency (**note:** B31 Pottery Yard was
  *rescued* — its adjacency is computed inline, no API needed). (**Shelter A1 was rescued and BUILT
  2026-07-20** — its 1-cell-pasture restriction is `PendingBuildStables.allowed_cells`, computed
  inline from `farmyard.pastures`, no geometry subsystem needed.)
- **Return-home / end-of-round hook — BUILT** (the §5c round-end ladder, `round_end.py`): Curator
  (A100), Asparagus Knife (A58), Lifting Machine (A70), Silage (A84), Ale-Benches, Credit (A54),
  Sculpture Course (B53), Informant (B117) are all implemented on it. Still blocked: **Toolbox
  (B27)**, which needs *turn-end* build detection (the end-of-turn boundary, §8) — a different event
  from round-end.
- **New shared action space:** Chapel (A39), Forest Inn (B42), Final Scenario (B23, owner-private space).
- **Randomness inside `step` (determinism invariant):** Paper Knife (A3), Moonshine (B3).
- **Temporary / extra worker:** Telegram (A22), Bassinet (A25), Stock Protector (B94),
  Lazy Sowman (A94, also needs a "declined sub-action" event). (**Walking Boots B22 — 🚫 WONTFIX**
  per the card data `status: wontfix`; previously listed in this cluster, reclassified 2026-07-22.)
- **Hidden round-space identity (reveal order is in the Environment, not GameState):** Knapper (A124),
  Master Workman (A126), Silokeeper (B112), Sweep (B120), Telegram's round-space half.
- **Card-as-animal-holder / new capacity slot:** the two ANONYMOUS-slot shapes were BUILT 2026-07-20
  (user direction: fold holders into the solver's capacity list, keep them distinct wherever card
  effects distinguish them) — `register_animal_cap_slots` (a pasture-like single-type bin; **Stockyard
  B12 implemented**) and `register_flexible_slots` (any-type mixable slots; **Petting Zoo E11
  implemented**, ruled mixed-type 2026-07-20; Feedyard B11's slot shape is now buildable — its
  after-breeding food payout is the remaining piece). TYPED (per-species) slots were BUILT 2026-07-21
  (`register_typed_slots` — the Dolly's-Mother greedy strip generalized to a per-type triple, plus
  `animal_holder_card_ids()` for "able to hold animals" wording): **Wildlife Reserve C11, Cattle Farm
  C12, Mud Patch A11 (eviction flags at after_sow / after_play_minor for the unplanted-count drops),
  and Sheep Agent D86 implemented**. The signature question resolved same day (user-approved): the
  whole chain was widened to carry GameState (`slots_fn(state, player_state)`; the doctored-player
  argument stays explicit), `helpers.completed_feeding_phases(state)` provides the GLOBAL game-time
  count (rulings: one shared count; ticks on harvest feeding regardless of participation, even if
  every player skipped), and **Truffle Searcher B86 + Woolgrower A148 [4] are implemented** — the
  typed-holder family is CLOSED. Special Food (B34) separately needs an accommodation event.
- **Per-card goods stack (beyond a CardStore scalar):** Hayloft Barn (B21), Muddy Puddles (B83),
  Forest Plow (B17, return-wood-to-space + partial-take legality — two 2026-07-20 rulings for its
  eventual build: it is an AFTER-window trigger, so the deposit lands after the sweeping player's
  `taken` stamp; and its returned wood on the space DOES count toward Material Hub's threshold for
  the next visitor — no deposit provenance needed, the native-type filter is final), Forest Stone
  (B48 — also an alternative cost), Maintenance Premium (**note:** B55 was *rescued* — it needs
  only a scalar).
- **Alternative printed cost ("A OR B" for the card's own play) — BUILT** via `alt_costs` on
  `MinorSpec` (the full pay-set is `(spec.cost,) + spec.alt_costs`, each enumerated as its own
  `CommitPlayMinor`): **Baseboards (A4), Barley Mill (A64), Forest Stone (B48) are all implemented.**
- **Legality / sub-action-menu changes:** Wooden Shed (A10), Forest School (**rescued** via the existing
  occupancy-override registry), Agrarian Fences (B26) (**Oven Site A27 was rescued and BUILT
  2026-07-20** — `PendingBuildMajor.allowed_majors` + `granted_by` on the build-major ctx + a
  grant-scoped cost formula; **Stone Company A23 likewise BUILT 2026-07-21** — the
  `CostCtx.min_spend` payment filter, ruling 72), Carpenter's Hammer (A14, per-action build-count
  discount), Chief Forester (A115, capped sow).
- **Misc one-offs:** Winnowing Fan (A61, state-dependent
  baking-rate conversion), Potato Ridger (A59, optional-at-harvest-field — the field hook is auto-only),
  Reclamation Plow (A17) / Wheel/Double-Turn plows, Grain Depot (B65, reads which resource paid),
  Moral Crusader (B106) / Shoreforester (B116) (pre-refill round-space read), Clutterer (B100, fragile
  static "accumulation-space text" card set + exact scoring rule), Wood Palisades (B30, alt fence piece +
  supply-cap bypass), Hawktower (B14), Carpenter's Bench (B15 — 🚫 **WONTFIX, user ruling 2026-07-21**:
  its "the taken wood (and only that)" payment-source restriction is the §8 goods-provenance cost gap,
  ruled not worth building for this card), Grassland Harrow was **rescued**. (**Shaving Horse A48 —
  🚫 WONTFIX** per the card data `status: wontfix`; had been listed above as an "after you obtain wood"
  deferral, reclassified 2026-07-22.)

---

## Summary for the morning

- **Group A (6 build-items, ~7 cards + a family):** all small, Family-safe, high-yield. Approve any subset
  and I build them. **Questions embedded:** A1 (A21 room-count timing + food coupling), A5 (bottom-row majors,
  esp. the Well), A6 (Acorns Basket's 2 rounds), A7 (B5 passing?).
- **Group B (5 cards):** medium infra; I can build on approval, each with a focused test.
- **Group C (decisions):** standalone conversions (C1), action substitution (C2), take-without-placement
  (C3, you flagged it), multi-plow (C4), Confidant (C5).
- The long tail stays deferred (real subsystems). One cheap extra: a small `alt_costs` on `MinorSpec`
  would unblock Baseboards / Barley Mill / Forest Stone — say the word.

---

## Round-end effects — the round-end ladder (BUILT 2026-07-12, rulings 49/50)

> **BUILT.** The design below was realized as the **round-end timing-window ladder** in
> `agricola/cards/round_end.py` (`_advance_round_end`) — not as a single `PendingRoundEnd` frame.
> It walks a small window sequence at the round boundary (`end_of_work`, `start_of_returning_home`,
> `returning_home` — PRE-reset, so the live board is the data — `after_returning_home` and
> `end_of_round`, post-reset), mirroring the harvest/preparation ladders
> (CARD_ENGINE_IMPLEMENTATION.md §5c). Many cards ride it (Ale-Benches, Apiary, Curator, Lifting
> Machine, Silage, Credit, Sculpture Course, Informant, …). **What is NOT yet built** is family 1
> below — the use-it-or-lose-it conversion members (Corn Schnapps Distillery, Mandoline, Pellet
> Press) and Claypipe's work-phase counter — which are card-level work *on* the built ladder, not
> the ladder itself. The original design is kept below for that residual.

**Original user-directed plan (2026-07-01).** Three related card families all resolve at the end of a
round. The realized ladder hosts them at the windows above; the three families and firing order
below were the blueprint.

### The three families the frame hosts

1. **Use-it-or-lose-it "once per round, you can …" options.** Cards worded *"Once per round, you
   can [pay a good to gain something]"* with **no** "at the start of each round" and **no**
   person-placement qualifier. They are usable at **any point during the round** and the option
   **expires at round end** if unused. The engine deliberately does not surface anytime
   conversions (a rational agent defers them to the last useful moment — see
   `CARD_AUTHORING_GUIDE.md` §2), so the correct realization is to offer each still-unused option
   as an **optional round-end `FireTrigger`** (the last moment it can be used). Modeling them at
   `start_of_round` is **wrong** (it forces the choice before the player has acquired the goods
   and removes the anytime flexibility). Members in the current data:
   - **Corn Schnapps Distillery (C64)** — pay 1 grain → 1 food on each of the next 4 round spaces.
     *(Was implemented at `start_of_round`; DEFERRED + archived 2026-07-01.)*
   - **Mandoline (C46)** — pay 1 vegetable → 1 bonus point + food on next round spaces. *(not implemented)*
   - **Pellet Press (D46)** — pay 1 reed → food on each of the next 4 round spaces. *(not implemented)*
   - *Not this family:* Tea House (D53, tied to skipping the 2nd person placement — a
     placement-time effect); Clay Carrier (D122, "at any time, but only once per round" — the
     anytime-conversion family, a separate deferral); Guest Room (E22, different mechanism).

2. **Round-end automatic effects** (choice-free). Example: **Claypipe** — "In the returning-home
   phase of each round, if you gained at least 7 building resources in the preceding work phase,
   you get 2 food." (Also needs a new *"building resources gained this work phase"* counter — a
   small piece of extra infra beyond the frame itself.)

3. **"At round end" triggers** — optional/at-round-end-worded card effects (the general case of
   family 2, surfaced as `FireTrigger`s rather than autos).

### Firing order (load-bearing)

Within `PendingRoundEnd`, resolve in this order:
1. **use-it-or-lose-it triggers FIRST** (family 1) — so their proceeds are on hand *before* the
   round-end automatics/at-round-end triggers compute or consume state;
2. then **round-end automatic effects** (family 2);
3. then **"at round end" triggers** (family 3).

### Status
**Ladder BUILT** (2026-07-12, rulings 49/50; `round_end.py`). The remaining work is card-level: the
family-1 use-it-or-lose-it members (Corn Schnapps Distillery — still archived in
`archive/deferred_cards/`; Mandoline; Pellet Press) and family-2's Claypipe (needs a
"building resources gained this work phase" counter) are not yet built on the ladder. Re-read each
member's exact text (§1) and re-classify when building it.

---

## After-the-feeding-phase conversions — the `after_feeding` window (BUILT)

> **BUILT.** Cards worded *"After the feeding phase of each harvest, you can …"* now fire on the
> harvest ladder's **`after_feeding` window** (position 10; user ruling 2026-07-05;
> CARD_ENGINE_IMPLEMENTATION.md §5b), offered only after the feeding payment resolves — so their
> proceeds cannot re-enter that harvest's feeding calculation. **Farm Store (C41)** — the card the
> food-laundering concern below was about — is implemented on it (un-archived and rebuilt), as are
> Studio and Social Benefits.

**The original concern (2026-07-01), now resolved.** Farm Store — "After the feeding phase of each
harvest, you can exchange exactly 1 food for 2 different building resources of your choice or 1
vegetable" — was first implemented as a during-feed `register_harvest_conversion`. Offered *during*
feeding, a player could buy a **vegetable** for 1 food and then **cook it** (Fireplace/Hearth) to pay
that same feeding — a food-laundering exploit the "after" wording exists to forbid. The
`after_feeding` window closes that hole by firing only once the feeding payment is done; any other
"after the feeding phase" card joins Farm Store on it.

---

## "Before the start of each round" — the `before_round` window (BUILT)

> **BUILT.** Cards worded *"Before the start of each round, …"* fire on the preparation ladder's
> **`before_round` window** (`preparation.py` position 0 — the ladder's FIRST rung, after any harvest
> and any round-end effects, before the reveal, round-space collection, and `start_of_round`; user
> ruling 2026-07-14). **resource_analyzer (C157)** is implemented on it as an automatic effect
> (played via Lessons); Small Animal Breeder and Civic Facade ride the same window.

**Why a distinct window (the original 2026-07-01 reasoning, preserved).** "Before the start of round
R+1" is its own instant — correctly served by `before_round`, and NOT by `start_of_round`:
1. `start_of_round` fires *after* the new round's scheduled income (`future_resources`) is
   distributed, so a building-resource comparison there would read *post-income* counts; `before_round`
   reads the intended pre-income snapshot. The divergence is reachable — building-resource scheduling
   cards exist (club_house schedules stone, cesspit clay, thick_forest wood), so the comparison can flip.
2. "Before the start of round R+1" is strictly later than the end-of-round-R boundary: on harvest
   rounds a harvest falls between them (WORK → RETURN_HOME → *harvest* → PREPARATION). The ladder
   ordering honors this — end-of-round effects (§5c) → (harvest, if any) → `before_round` → the
   round's income/reveal.

---

## Placement legality as reachability — the design arc (2026-07-06)

**Problem catalog of record: `LEGALITY_HARD_CASES.md` (repo root)** — the ten mechanisms
that break state-read placement legality, worked multi-card interactions, and per-mechanism
card lists; **solution sketch (ON HOLD): `PLACEMENT_REACHABILITY_DESIGN.md` (repo root)**,
backed by three full-catalog censuses (`CENSUS_AT_ANY_TIME.md`, `CENSUS_REACTIVE_TRIGGERS.md`,
`CENSUS_COST_IMPOSITION.md`, all repo root). The problem: cards that grant goods on placement,
at-any-time cards, and reactive cards (Potter's Yard family) make placement legality a
*reachability* question ("could the player complete this action?"), which the per-space
predicates in `legality.py` cannot answer. The design doc holds the general architecture
(a closure-by-simulation oracle), the phase ladder, and the soundness contract, but the
user is designing the approach — it is a sketch, not a plan. Nothing is implemented at this stamp; the reveal-order card
cluster (Brook / Master Workman / Knapper / Sweep / Silokeeper / Outrider / Pioneer /
Legworker / Bean Counter / Wholesaler / Pig Stalker / Task Artisan / Water Worker) is Phase
1's scope and supersedes this file's "Hidden round-space identity" long-tail entry when it
lands.

**Dated rulings recorded here:**
- **Reed Seller (D159) is permanently out of scope** (user ruling 2026-07-06): an at-any-time
  conversion the *opponent* can preempt by paying — free timing plus an out-of-turn opponent
  decision would need machinery nothing else in the 31-card at-any-time family needs, for one
  4+-only card. Do not re-triage.
- **Minstrel (A151) deferred** (2026-07-06): out-of-turn action-space use at returning home —
  a new subsystem (its errata "use the effect of that action space" doesn't change this).
- **Sidekick (A171) deferred** (2026-07-06): placing two workers in the same turn.
- **Witches' Dance Floor (D25) is permanently out of scope** (user ruling 2026-07-09,
  `status: wontfix` in the data): simultaneously a sowable field, an occupation, and
  the Fireplace major with all its effects, playable only via a Minor-Improvement
  action — a multi-identity chimera touching the card-as-field, identity-counting, and
  major-ownership subsystems at once. Do not re-triage.
