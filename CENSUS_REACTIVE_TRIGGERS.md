# Census: reactive / event-triggered cards

> **Corpus artifact (2026-07-06).** Produced by a full sweep of `agricola/cards/data/*.json`
> (840 cards, decks A–E, both types) for `PLACEMENT_REACHABILITY_DESIGN.md`. Summary tables
> only — verbatim text via `python scripts/card_text.py <slug>`. Implemented-status checked
> against `agricola/cards/<slug>.py` existence (the JSON `status` field is wrong for 256
> cards). Two same-name pairs use `_c<num>` module suffixes (`market_stall_c54`,
> `slurry_spreader_c71`) — distinct cards, not duplicates.

## Scope

Cards whose effect fires **automatically in reaction to a state change or game event that is
NOT "the owner uses a named action space / sub-action at their own placement."** Canonical
exemplar: Potter's Yard (A40) — reacts to a farmyard cell turning used *however caused*.

**The pivotal exclusion:** "each time you use [space/category]" cards (Wood Cutter, Basket,
~50 more) react to *the owner's own worker placement* — the ordinary hook family the engine
already models (`before_action_space`) — and are excluded. Kept in-scope: acquisition-worded
cards ("each time you **get/obtain/take** [good]"), which in principle cover card-caused
acquisitions. Excluded-on-reflection (pure play-time schedulers, no ongoing trigger — verified
`_on_play → schedule_resources` in code): garden_claw, trellises, forest_well, sheep_well,
reap_hook, cattle_whisperer.

**In-scope count: 153** (49 occupations, 104 minors; **47 implemented**, 106 not).

Legend — A/O: **A**=automatic choice-free, **O**=optional/with-choice. Afford? = payload can
feed affordability of builds/renovations/fences/card-plays or mutate the farmyard.
Chains? = payload can trigger another reactive card.

## Class 1 — farmyard/board state change (build/plow/fence/renovate/cell-used), however caused

| slug | deck# | players | impl | payload | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| potters_yard | MIN A40 | all | ✗ | clay→2 food per cell→used | O | yes | **yes — canonical** |
| farmstead | MIN C48 | all | ✗ | +1 food per turn w/ cell→used | A | yes | consumer |
| shepherds_crook | MIN A83 | all | ✓ | +2 sheep on new ≥4 pasture | A | farm | yes |
| asparagus_gift | MIN A68 | all | ✓ | +1 veg on fence-count≥round | A | yes | no |
| loppers | MIN A34 | all | ✓ | wood+fence→2 food+VP on fence-build | O | yes | no |
| stablehand | OCC D89 | 1+ | ✓ | free stable on ≥1 fence built | O | farm | yes |
| stable_tree | MIN A74 | all | ✗ | schedule wood ×3 on stable-build (on-turn only per clar.) | A | yes | yes |
| farmyard_manure | MIN A43 | all | ✗ | schedule food ×3 on stable-build (on-turn only) | A | yes | no |
| stable_milker | OCC D166 | 4+ | ✗ | +1 cattle on ≥2 stables/turn | A | farm | yes |
| feed_fence | MIN C56 | all | ✗ | food per stable (last=3) + cost swap | A/O | yes | no |
| breeder_buyer | OCC A167 | 4+ | ✗ | +1 animal on room+stable same turn | A | farm | yes |
| wall_builder | OCC A111 | 1+ | ✓ | schedule food ×4 on room-build | O | yes | no |
| roughcaster | OCC A110 | 1+ | ✓ | +3 food on clay-room / clay→stone reno | A | yes | no |
| bed_maker | OCC A93 | 1+ | ✗ | pay wood+grain→growth on add-rooms | O | farm | yes |
| master_bricklayer | OCC B95 | 1+ | ✓ | stone-cost reduction on build-major | A | cost mod | no |
| master_huntsman | OCC E165 | 4+ | ✗ | +1 boar on build-major | A | farm | yes |
| saddler | OCC E128 | 3+ | ✗ | 1 food→plow on build-major | O | farm | yes |
| brick_hammer | MIN D80 | all | ✗ | +1 stone on ≥2-clay improvement | A | yes | yes |
| junk_room | MIN A55 | all | ✓ | +1 food after any improvement | A | yes | no |
| farm_building | MIN C43 | all | ✓ | schedule food ×3 on build-major | A | yes | no |
| interior_decorator | OCC D111 | 1+ | ✗ | schedule food ×6 on renovate | A | yes | no |
| blackberry_farmer | OCC E108 | 1+ | ✗ | schedule food ≤fences on fence-build | A | yes | no |
| lumberjack | OCC B119 | 1+ | ✓ | wood + schedule ≤fences at play | A | yes | yes |
| cubbyhole | MIN E52 | all | ✓ | food/room banked→each feeding | A | yes | no |
| renovation_preparer | OCC D123 | 1+ | ✗ | +2 clay/stone per new room | A | yes | yes |
| carpenters_hammer | MIN A14 | all | ✗ | discount on ≥2-room builds | A | cost mod | no |
| clay_supports | MIN D15 | all | ✓ | alt clay-room cost | O | cost mod | no |
| frame_builder | OCC A123 | 1+ | ✓ | 2 clay/stone→1 wood per room/reno | O | cost mod | no |
| brushwood_collector | OCC B145 | 3+ | ✗ | reed→1 wood on reno/room | O | cost mod | no |
| millwright | OCC D88 | 1+ | ✓ | ≤2 resources→grain each, all builds | O | cost mod | no |
| bucksaw | MIN A37 | all | ✓ | 1 wood→VP+grain on renovate | O | yes | no |
| mining_hammer | MIN B16 | all | ✓ | free stable on renovate | O | farm | yes |
| roof_ladder | MIN D81 | all | ✓ | −1 reed, +1 stone on renovate | A | both | yes |
| skillful_renovator | OCC C119 | 1+ | ✓ | wood = people placed, after reno | A | yes | yes |
| pasture_master | OCC B168 | 4+ | ✗ | +2 food +1 animal/stable-pasture on reno | A | farm | yes |
| furnisher | OCC D96 | 1+ | ✗ | −1 wood next improvement per new room | O | cost mod | no |
| mountain_plowman | OCC E164 | 4+ | ✗ | +1 sheep per plowed field | A | farm | yes |
| rocky_terrain | MIN C80 | all | ✓ | buy stone for food on plow (tile or card) | O | yes | yes |
| barrow_pusher | OCC A105 | 1+ | ✓ | +1 clay+1 food per new field tile, any source | A | yes | yes |
| cultivator | OCC D104 | 1+ | ✗ | +1 wood+1 food per new field tile | A | yes | yes |
| field_spade | MIN E79 | all | ✗ | +1 stone after sow | A | yes | yes |
| tinsmith_master | OCC B115 | 1+ | ✗ | +1 crop per sown field (+capacity) | O | crops | no |
| cow_patty | MIN E71 | all | ✗ | +1 crop on pasture-adjacent sow | O | crops | no |
| calcium_fertilizers | MIN A72 | all | ✓ | +1 crop to single-type fields on Quarry use | A | crops | no |
| vegetable_slicer | MIN A41 | all | ✗ | +2 wood+1 veg on Fireplace→Hearth upgrade | A | yes | yes |
| sower | OCC C115 | 1+ | ✗ | reed on card per major; →supply/Sow at any time | O | yes | yes |
| field_cultivator | OCC D126 | 1+ | ✓ | top good off 7-pile per field harvested | O | yes | yes |
| cherry_orchard | MIN E68 | all | ✗ | +1 veg on last wood harvested off card | A | yes | no |
| melon_patch | MIN E69 | all | ✗ | plow on last veg harvested off card | O | farm | yes |
| upholstery | MIN E31 | all | ✗ | reed→VP on later improvement (≤rooms) | O | no | no |
| riparian_builder | OCC A128 | 3+ | ✗ | build discounted room on opp Reed Bank | O | farm | yes |
| stagehand | OCC A150 | 4+ | ✗ | build action of choice on opp Traveling Players | O | farm | yes |
| toolbox | MIN B27 | all | ✗ | build craft major after build-turn | O | board | yes |
| carpenters_bench | MIN B15 | all | ✗ | build pasture from just-taken wood only | O | farm; **payment-source restriction (§8 gap)** | yes |
| nail_basket | MIN E15 | all | ✗ | Build-Fences after wood space (pay 1 stone onto space) | O | farm | yes |
| barn_cats | MIN E43 | all | ✗ | schedule food by stable count at play | A | yes | no |

## Class 2 — resource/animal acquisition, however caused

| slug | deck# | players | impl | payload | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| kindling_gatherer | OCC E118 | 1+ | ✗ | +1 wood on getting food from a space | A | yes | yes |
| mattock | MIN E77 | all | ✗ | +1 clay on getting reed/stone from a space | A | yes | yes |
| beaver_colony | MIN E33 | all | ✗ | +1 VP per reed-get (+pasture restriction) | A | no | no |
| syrup_tap | MIN E47 | all | ✗ | schedule 1 food on getting wood | A | yes | no |
| boar_spear | MIN E53 | all | ✗ | boar→4 food on non-breeding boar gain | O | yes | no |
| huntsmans_hat | MIN C52 | all | ✗ | +1 food per boar from a space effect | A | yes | no |
| portmonger | OCC A103 | 1+ | ✓ | +veg/grain/reed by food-take tier | A | yes (reed) | yes |
| storehouse_steward | OCC A146 | 3+ | ✗ | +stone/reed/clay/wood by exact food take | A | yes | yes |
| forest_clearer | OCC B162 | 4+ | ✗ | +wood/food by exact wood take (ordered before Basket per clar.) | A | yes | yes |
| wild_greens | MIN E50 | all | ✗ | +1 food per distinct sown type | A | yes | no |
| cheese_fondue | MIN E57 | all | ✗ | +1/+2 food on bake, per sheep/cattle held | A | yes | no |
| wolf | OCC E103 | 1+ | ✗ | pile-match good→supply +1 boar | O | yes | yes |
| slurry_spreader_c71 | MIN C71 | all | ✓ | +Sow on ≥2 newborn types (breeding) | O | farm | yes |
| fodder_planter | OCC D115 | 1+ | ✓ | sow 1 field per newborn (breeding) | O | crops | yes |
| dung_collector | OCC E90 | 1+ | ✗ | 1 food→plow on ≥2 newborns **any source** (§8 gap) | O | farm | yes |
| champion_breeder | OCC E133 | 3+ | ✗ | +1/+2 VP on 2/3+ newborns placed | A | no | no |
| childs_toy | MIN E30 | all | ✓ | newborns eat 2 (requirement fold) | A | no | no |
| swimming_class | MIN A35 | all | ✗ | +2 VP/newborn returned from Fishing | A | no | no |
| omnifarmer | OCC E134 | 3+ | ✗ | bank crop/newborn→endgame VP | O | no | no |
| adoptive_parents | OCC A92 | 1+ | ✗ | 1 food→offspring acts now, not "newborn" | O | person-timing | no |
| bed_in_the_grain_field | MIN C24 | all | ✓ | growth at next harvest start if room | O | farm | yes |
| wares_salesman | OCC E144 | 3+ | ✗ | +resource+reed when ANY player plays a resource→food card | A | yes | yes |
| recycled_brick | MIN D77 | all | ✗ | +1 clay per room on ANY renovate-to-stone | A | yes | yes |

## Class 3 — accumulation on the card itself

| slug | deck# | players | impl | mechanism | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| bonehead | OCC D118 | 1+ | ✗ | 6 wood on card; 1 off per hand-card play | A | yes | yes |
| bean_counter | OCC D158 | 4+ | ✗ | food/space-use rounds 1–8; **at 3 → supply** (the one literal card-threshold trigger) | A | yes | no |
| forest_stone | MIN B48 | all | ✗ | food shuttled by wood/stone space use | O | yes | no |
| maintenance_premium | MIN B55 | all | ✓ | food drip on wood-space; refill on reno | O/A | yes | no |
| material_hub | MIN C81 | all | ✗ | 2×each resource on card; drip on ANY big take — **Grocer-class** | A | yes | yes |
| interim_storage | MIN A81 | all | ✓ | banked resources released rounds 7/11/14 | A | yes | yes |

*(sower, field_cultivator, cubbyhole, omnifarmer, wolf also carry card-store aspects — see
their primary classes.)*

## Class 4 — another card being played

| slug | deck# | players | impl | payload | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| bookshelf | MIN D49 | all | ✓ | +3 food **before** occupation play (pre-cost) | A | **yes — pre-payment** | no |
| bookcase | MIN C68 | all | ✓ | +1 veg after occupation | A | yes | no |
| patron | OCC D152 | 4+ | ✗ | +2 food before later occupations (pre-cost) | A | yes | no |
| furniture_maker | OCC C116 | 1+ | ✗ | +1 wood per food paid on later occ ("after this one" — §8 payload gap) | A | yes | yes |
| education_bonus | MIN D42 | all | ✓ | tiered resource/**field** at Nth occupation | A | yes | yes |
| stallwright | OCC E89 | 1+ | ✗ | free stable at 2nd/3rd/5th/7th occupation | O | farm | yes |
| patroness | OCC E163 | 4+ | ✗ | +1 chosen resource after later occs (§8 gap) | A | yes | yes |
| cottar | OCC E122 | 1+ | ✗ | +1 wood/clay after paying improvement cost | O | yes | yes |
| contraband | MIN E54 | all | ✗ | +1 printed-cost resource→3 food on later improvements (§8 gap) | O | yes | no |
| seed_almanac | MIN E18 | all | ✗ | 1 food→plow after later minors (**§8's named exemplar**) | O | farm | yes |
| craft_teacher | OCC A131 | 3+ | ✗ | ≤2 free occupations after craft majors | O | plays cards | yes |
| charcoal_burner | OCC C137 | 3+ | ✗ | +wood+food on ANY cooking improvement | A | yes | yes |
| claypit_owner | OCC E156 | 4+ | ✗ | +food+clay on opp clay-cost improvement | A | yes | yes |
| reseller | OCC E146 | 3+ | ✗ | refund printed cost once/game | O | yes | yes |
| seaweed_fertilizer | MIN C73 | all | ✗ | +grain/veg after unconditional Sow | A | yes | no |

## Class 5 — opponent's action

| slug | deck# | players | impl | payload | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| milk_jug | MIN A50 | all | ✓ | +3 food on any Cattle Market use (engine's any_player exemplar) | A | yes | no |
| hod | MIN A77 | all | ✓ | +2 clay on any Pig Market use | A | yes | yes |
| corf | MIN B79 | all | ✓ | +1 stone on any ≥3-stone take | A | yes | yes |
| sheep_provider | OCC C141 | 3+ | ✓ | +1 grain on any Sheep Market use | A | yes | no |
| cordmaker | OCC A142 | 3+ | ✗ | grain / buy-veg on any ≥2-reed take | O | yes | no |
| clay_warden | OCC B143 | 3+ | ✗ | +clay on opp Hollow use | A | yes | yes |
| reed_roof_renovator | OCC C144 | 3+ | ✗ | +1 reed on opp renovate | A | yes | yes |
| workshop_assistant | OCC C146 | 3+ | ✗ | staged resource pair on opp renovate | O | yes | yes |
| resource_recycler | OCC C149 | 4+ | ✗ | 2 food→free clay room on opp reno-to-stone | O | farm | yes |
| pattern_maker | OCC C153 | 4+ | ✗ | 2 wood→grain+food+VP on opp renovate | O | yes | no |
| journeyman_bricklayer | OCC D163 | 4+ | ✗ | +1 stone on opp stone reno/room | A | yes | yes |
| material_deliveryman | OCC C163 | 4+ | ✗ | +resource on any 5/6/7/8+ take | A | yes | yes |
| german_heath_keeper | OCC C164 | 4+ | ✗ | +1 sheep on any Pig Market use | A | farm | yes |
| cattle_buyer | OCC C167 | 4+ | ✗ | buy animal on opp Fencing use | O | farm | yes |
| casual_worker | OCC D149 | 4+ | ✗ | food OR free stable on opp Quarry use | O | both | yes |
| midwife | OCC D160 | 4+ | ✗ | +1 grain on opp first-person growth | A | yes | no |
| chairman | OCC D139 | 3+ | ✗ | +1 food on opp Meeting Place | A | yes | no |
| cabbage_buyer | OCC D161 | 4+ | ✗ | buy veg tiered on any reno+build combo | O | yes | no |
| paymaster | OCC A154 | 4+ | ✗ | give grain→VP on opp food space | O | no | no |
| buyer | OCC A156 | 4+ | ✗ | pay opp 1 food→matching good | O | yes | yes |
| culinary_artist | OCC A158 | 4+ | ✗ | good→food on opp Traveling Players | O | yes | no |
| joiner_of_the_sea | OCC A159 | 4+ | ✗ | give wood→food on opp Fishing/Reed Bank | O | yes | no |
| lutenist | OCC A160 | 4+ | ✗ | +food+wood on opp Traveling Players | A | yes | yes |
| puppeteer | OCC C152 | 4+ | ✗ | pay opp 1 food→free occupation | O | plays cards | yes |
| fishing_net | MIN C51 | all | ✗ | **opp must pay owner 1 food to use Fishing** — a placement TAX (AND-side legality) | A | yes | no |
| barn_shed | MIN E66 | all | ✗ | +1 grain on opp Forest use | A | yes | no |
| kelp_gatherer | OCC E160 | 4+ | ✗ | +1 veg on opp Fishing | A | yes | no |
| miller | OCC E95 | 1+ | ✗ | Bake on opp Grain Seeds use | O | yes | no |
| packaging_artist | OCC C140 | 3+ | ✗ | Bake instead of a granted Minor action | O | yes | no |
| margrave | OCC E154 | 4+ | ✗ | +2 food on any renovate (stone-house gate) | A | yes | no |
| lieutenant_general | OCC B159 | 4+ | ✗ | +1 food per opp adjacent field placement (only opp-farmyard reactor) | A | yes | no |
| huntsman | OCC B147 | 3+ | ✗ | 1 grain→boar after wood space | O | farm | yes |
| recruitment | MIN D21 | all | ✗ | growth instead of granted Minor action (room gate) | O | farm | yes |

## Class 6 — threshold/level becomes true

| slug | deck# | players | impl | condition → effect | A/O | afford? | chains? |
|---|---|---|---|---|---|---|---|
| fire_protection_pond | MIN A45 | all | ✓ | leave wood house→schedule food ×6 (`register_conditional`) | A | yes | yes |
| clay_hut_builder | OCC A120 | 1+ | ✓ | leave wood house→schedule clay ×5 | A | yes | yes |
| manservant | OCC B107 | 1+ | ✓ | stone house→schedule 3 food × remaining | A | yes | no |
| hook_knife | MIN B35 | all | ✗ | reach N sheep→+2 VP (**resource-count sweep gap, §8**) | A | no | no |
| pig_owner | OCC A153 | 4+ | ✗ | reach 5 boars→+3 VP (same gap) | A | no | no |
| sheep_keeper | OCC B154 | 4+ | ✗ | reach 7 sheep→+3 VP+2 food (same gap) | A | yes | no |
| pastor | OCC B163 | 4+ | ✗ | sole 2-room house→resource bundle (relative/opp-state condition) | A | yes | yes |
| party_organizer | OCC D157 | 4+ | ✗ | opp 5th person→+8 food (opp-state threshold) | A | yes | no |
| bunk_beds | MIN C10 | all | ✗ | 4 rooms→house holds 5 (passive; derived, likely no firing needed) | A | capacity | no |
| reader | OCC D85 | 1+ | ✗ | 6 occs→+1 person capacity (always-on once played per project note) | A | capacity | no |
| estate_master | OCC B132 | 3+ | ✗ | full farmyard→+1 VP/harvested veg thereafter (latches, stays on) | A | no | no |
| farm_hand | OCC B85 | 1+ | ✗ | 2×2 fields→center-stable build unlock (legality extension) | O | farm | yes |
| mason | OCC C87 | 1+ | ✗ | stone ≥4 rooms→free room at any time | O | farm | yes |
| master_builder | OCC D87 | 1+ | ✗ | ≥5 rooms→free room once, any time | O | farm | yes |
| plow_driver | OCC A90 | 1+ | ✓ | stone-house gate + start-of-round plow (hybrid gate+timer) | O | farm | yes |
| groom | OCC B89 | 1+ | ✓ | stone-house gate + SoR stable | O | farm | yes |
| scholar | OCC B97 | 1+ | ✓ | stone-house gate + SoR cheap card play (can play another reactive card) | O | plays cards | yes |
| master_fencer | OCC E88 | 1+ | ✗ | stone-house gate + SoR fences | O | farm | yes |
| tax_collector | OCC E126 | 1+ | ✗ | stone-house gate + SoR chosen resources | A | yes | yes |
| housebook_master | OCC B134 | 3+ | ✗ | reno-to-stone by round window→food+VP once | A | yes | no |

## Hardest 5 for a legality/reachability engine

1. **potters_yard + farmstead** — need a `cell-became-used` event fired on ANY cause; the
   placement-legality version is the §8 "Pan-Baker-enables-Potter" compound shape.
2. **material_hub / forest_stone / bonehead** — goods **on a card** participating in
   affordability = the §8 Grocer/conversion-reachability problem (dominance unsound).
3. **dung_collector / champion_breeder** — need the deliberately-absent any-source
   newborns-gained event (markets included).
4. **seed_almanac / furniture_maker / patroness / contraband** — need the "after this one"
   self-vs-later distinction = the §8 no-event-payload gap.
5. **mason / master_builder / sower + the stone-house SoR gates** — free builds/conversions
   needing the co-dependent end-of-turn / at-any-time window design (Scholar can even play
   another reactive card mid-gate).

## Coverage notes

The 47 implemented in-scope cards ride: `after_build_*`/`after_sow`/`after_plow`/
`after_renovate`/`after_play_occupation` autos (classes 1/4), `any_player=True` hooks
(class 5), `register_conditional` (class 6), gated `start_of_round` hooks, the
`breeding_outcome` registry, and reactive-front-end `future_resources` schedules.
