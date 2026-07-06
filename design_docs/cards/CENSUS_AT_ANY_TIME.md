# Census: the "at any time" card family

> **Corpus artifact (2026-07-06).** Produced by a full sweep of `agricola/cards/data/*.json`
> (840 cards, decks A–E, both types) for `PLACEMENT_REACHABILITY_DESIGN.md`. Summary tables
> only — each card's verbatim text is retrievable with `python scripts/card_text.py <slug>`.
> Implemented-status was checked against `agricola/cards/<slug>.py` existence (the JSON
> `status` field is unreliable).

## Headline

- The literal phrase **"at any time" appears on exactly 31 cards, and all 31 are genuine
  family members** (usable at player-chosen moments). **None is implemented** — consistent
  with `CARD_ENGINE_IMPLEMENTATION.md` §8's deliberate at-any-time boundary.
- **No card without the literal phrase qualified.** Every other conversion/purchase/build
  grant in the catalog is anchored to a named space, phase, round boundary, or event. The
  family is closed and enumerable, not an open-ended pattern.
- **Reed Seller (D159) is permanently out of scope** — user ruling 2026-07-06 (at-any-time
  conversion + an out-of-turn opponent preemption; too weird/difficult, 4+-only).

## The 31 family members

Funds? = output can pay for placement-gated work (build/renovate/fence resources, card-play
food, or a farmyard change). Mutates? = using it changes farmyard/board state, not just the
resource pool.

| Slug | Deck# | Type | Players | Capability | Inputs → Outputs | Bound | Funds? | Mutates? |
|---|---|---|---|---|---|---|---|---|
| oriental_fireplace | A60 | Min | all | conversion→food (+bake) | veg/sheep/cattle→food | unbounded | food | no |
| clearing_spade | A71 | Min | all | move crop | crop: field(≥2)→empty field | unbounded | no | **yes** |
| kettle | B32 | Min | all | grain→food+VP | 1/3/5 grain→3/4/5 food+0/1/2 VP | unbounded | food | no |
| hard_porcelain | B80 | Min | all | clay→stone | 2/3/4 clay→1/2/3 stone | unbounded | **stone** | no |
| muddy_puddles | B83 | Min | all | buy from pile | 1 clay→top good (5-item pile) | pile | food/animals | yes (animals) |
| potters_market | B69 | Min | all | pay→scheduled veg | 4 clay+2 food→veg ×2 rounds | unbounded | veg (deferred) | no |
| roll_over_plow | C18 | Min | all | plow (discard-fueled) | discard a field's goods→plow 1 | gated ≥3 planted | **plows** | **yes** |
| stable_yard | C50 | Min | all | animal swap | sheep+boar→cattle | unbounded | no | yes (animals) |
| crudit | C57 | Min | all | veg→food | discard field veg→4 food | unbounded | food | **yes** |
| land_consolidation | C69 | Min | all | in-field grain→veg | 3 grain in field→1 veg there | unbounded | no | **yes** |
| trowel | D13 | Min | all | **renovate to stone** | per-room stone(+reed+food) | until stone | **renovates** | **yes** |
| earth_oven | D59 | Min | all | conversion→food (+bake) | veg/animals→food | unbounded | food | no |
| large_pottery | D60 | Min | all | clay→food | clay→2 food | unbounded | food | no |
| changeover | D71 | Min | all | discard→sow | field's lone harvest-good→Sow there | conditional | **sows** | **yes** |
| stone_house_reconstruction | E13 | Min | all | **renovate clay→stone**, no person | normal reno cost | until stone | **renovates** | **yes** |
| piggy_bank | E27 | Min | all | build major (stored food) | 6 food off card→free major | stored food | **free major** | **yes** |
| grocer | A102 | Occ | 1+ | buy from pile | 1 food→top good (8-item pile; any amount at once per clar.) | pile | **wood/reed/stone/clay** | no |
| sheep_walker | B104 | Occ | 1+ | sheep→goods | 1 sheep→boar/veg/**stone** | unbounded | **stone** | yes (animals) |
| salter | B157 | Occ | 4+ | animal→scheduled food | sheep/boar/cattle→food ×3/5/7 rounds | unbounded | food (deferred) | yes (animals) |
| mason | C87 | Occ | 1+ | **add a room** (free) | stone house ≥4 rooms→card's room | once | **free room** | **yes** |
| stable_cleaner | C94 | Occ | 1+ | **build stables**, no person | 1 wood+1 food per stable | unbounded | **stables** | **yes** |
| sower | C115 | Occ | 1+ | move reed / Sow | card reed→supply or Sow action | reed per major built | reed / **sows** | **yes** |
| basketmakers_wife | C139 | Occ | 3+ | reed→food | 1 reed→2 food | unbounded | food | no |
| master_builder | D87 | Occ | 1+ | **add a room** (free) | house ≥5 rooms→room | **once/game** | **free room** | **yes** |
| whisky_distiller | D106 | Occ | 1+ | grain→scheduled food | 1 grain→4 food in 2 rounds | unbounded | food (deferred) | no |
| seed_trader | D114 | Occ | 1+ | buy from card | 2 food→grain; 3 food→veg | 2+2 on card | crops | no |
| clay_carrier | D122 | Occ | 1+ | buy clay | 2 food→2 clay | **once/round** | **clay** | no |
| emissary | D124 | Occ | 1+ | good→stone | 1 distinct good (incl. food)→1 stone | distinct-goods rule | **stone** | no |
| reed_seller | D159 | Occ | 4+ | reed→food (interactive) | 1 reed→3 food; opp may preempt (2 food) | unbounded | food | no |
| clay_firer | D162 | Occ | 4+ | clay→stone | 2 clay→1 stone; 3→2 | unbounded | **stone** | no |
| pen_builder | E86 | Occ | 1+ | wood→capacity on card | wood (irretrievable)→2× animal slots | wood stock | capacity | **yes** |

## The difficulty core (~10 of 31)

1. **Food → build resources** (grocer, seed_trader, emissary, clay_carrier, hard_porcelain,
   clay_firer, sheep_walker): affordability stops being a function of the resource pool;
   grocer/muddy_puddles/seed_trader draw from **depleting card piles** (grocer clarification:
   buy any amount at once).
2. **Free-timing farmyard/board mutations** (stable_cleaner, trowel,
   stone_house_reconstruction, mason, master_builder, piggy_bank, roll_over_plow, changeover,
   clearing_spade): field/room/stable/house-material preconditions are not stable within a
   turn; these are the chain fuel for reactive cards (Potter's Yard family) and invalidate
   non-resource gates (house-material prereqs, empty-field checks).
3. **Net-positive cycles across pairs exist but are designer-bounded** — e.g. clay_carrier
   (2 food→2 clay, once/round) + large_pottery (clay→2 food, unbounded) nets +2 food/round;
   every such cycle found is cut by a once-per-round latch, a pile, or a budget. An engine
   closure must enforce these bounds from card state, never assume steady-state.

## Borderline exclusions (grouped; each anchored to a named event, so NOT family)

- **Space-use anchored:** basket, mushroom_collector, shaving_horse, wood_worker, huntsman,
  forest_plow, pulverizer_plow, clay_deposit, ox_goad, truffle_slicer, brewing_water,
  small_basket, tasting, hardware_store, excavator, profiteering, junior_artist, sugar_baker,
  trade_teacher, thresher, animal_dealer, full_peasant, large_scale_farmer, illusionist,
  cooperative_plower, mole_plow, skimmer_plow, plow_maker, plow_hero, agrarian_fences,
  forest_tallyman, wolf, roastmaster, sheep_inspector, merchant, canal_boatman, carpenters_bench,
  nail_basket.
- **Harvest-phase anchored:** value_assets, farm_store, beer_stall, market_stall_c54, beer_keg,
  beer_table, paintbrush, feed_pellets, straw_manure, beer_tap, smuggler, veggie_lover,
  treegardener, haydryer, winter_caretaker, furniture_carpenter, basket_carrier, game_provider,
  lumber_virtuoso, stall_holder, food_merchant, new_purchase, potato_ridger.
- **Round-boundary anchored:** cob, green_grocer, nutrition_expert, groom, master_fencer,
  entrepreneur, stone_buyer, lifting_machine, iron_hoe, baking_course, perennial_rye, silage,
  storks_nest, ale_benches, curator, tea_house, straw_hat, sundial, master_renovator,
  mandoline, corn_schnapps_distillery, pellet_press, guest_room (the once-per-round
  use-it-or-lose-it members stay on the `PendingRoundEnd` defer — CARD_AUTHORING_GUIDE.md §9).
- **Event anchored (build/play/growth/opponent):** paper_maker, contraband, working_gloves,
  seed_almanac, saddler, plow_builder, dung_collector, clay_supports, drill_harrow,
  potter_ceramics, retraining, iron_oven, simple_oven, melon_patch, reclamation_plow,
  double_turn_plow, carpenters_axe, stallwright, furnisher, craftsmanship_promoter,
  braid_maker, elder_baker, heart_of_stone, wood_saw, recreational_carpenter, steam_plow,
  riparian_builder, resource_recycler, cabbage_buyer, pattern_maker, cattle_buyer, buyer,
  culinary_artist, lutenist, puppeteer, stable_sergeant, stable_planner, hawktower.
- **Play-time-only one-shots:** facades_carving, miller (its build clause), renovation_company,
  crudit's buy clause, stable_yard's food clause.
- **Static/passive capabilities:** domestician_expert, animal_tamer, pet_broker, sheep_agent,
  conservator, wood_slide_hammer, den_builder.

## Hardest 5 for a placement-time "can the player complete this?" engine

1. **grocer + seed_trader + emissary** — food→build-resources from depleting piles;
   affordability is reachability over interleaved buys and spends (the §8 Grocer problem).
2. **piggy_bank** — free-timing build-a-major fueled by an off-pool accumulated budget.
3. **trowel / stone_house_reconstruction** — free-timing renovate: every house-material gate
   in the catalog becomes reachability-conditional.
4. **roll_over_plow / changeover / clearing_spade** — free-timing farmyard topology changes:
   field-count/empty-field/planted-field preconditions unstable within a turn.
5. **mason / master_builder** — free-timing zero-cost rooms: room-count gates (growth
   legality, capacity) become reachability questions.
