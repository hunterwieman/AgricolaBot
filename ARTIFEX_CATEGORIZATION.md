# Artifex Card Implementation Categorization

A difficulty triage of the unimplemented Artifex (deck A) cards — 24 occupations and
60 minors — against the card machinery already built. Each card is classified by how
much (if any) new infrastructure it needs, with the template module to copy.

---

## Tier 1 — Trivially easy (direct template copy, mostly < 20 lines)

These map cleanly onto a single existing pattern with no new machinery.

### Occupations

| Card | Pattern | Note |
|------|---------|------|
| **A99 Fellow Grazer** | `register_scoring` → `stable_architect.py` | Count `pastures` with ≥3 cells, ×2 VP |
| **A101 Cookery Outfitter** | `register_scoring` → `stable_architect.py` | Count owned cooking improvements (fireplace/hearth/ovens) |
| **A105 Barrow Pusher** | `register_auto("after_plow", ...)` | +1 clay +1 food per plow; `corn_scoop.py` with `after_plow` event |
| **A117 Wood Carrier** | `on_play` → `consultant.py` | +1 wood per `minor_improvements ∪ major_improvements` |
| **A122 Pan Baker** | `register_auto("before_action_space", ...)` on `grain_utilization` | +2 clay +1 wood; exact `wood_cutter.py` shape |
| **A65 Seed Pellets** | `register_auto("before_sow", ...)` | +1 grain; `corn_scoop.py` with `before_sow` event |
| **A121 Clay Puncher** | `on_play` + `register_auto("before_action_space", ...)` on `{lessons, clay_pit}` | `clay_pit` is atomic → `register_action_space_hook`; on_play half is `consultant.py` |

### Minors

| Card | Pattern | Note |
|------|---------|------|
| **A8 Food Basket** | `on_play` → `consultant.py` | +1 grain +1 veg; simplest possible card |
| **A57 Milking Parlor** | `on_play` → `consultant.py` | Tiered food by sheep (thresholds 1/3/4 → 2/3/4) + cattle (1/2/3 → 2/3/4) |
| **A7 Gardener's Knife** | `on_play` → `consultant.py` | Count grain-fields → food; count veg-fields → grain |
| **A6 Storage Barn** | `on_play` → `consultant.py` | For each of {well, joinery, pottery, basketmakers_workshop} owned → give corresponding resource |
| **A51 Drift-Net Boat** | `register_auto("before_action_space", ...)` on `fishing` | +2 food; `herring_pot.py` is the exact template |
| **A42 Forest Lake Hut** | `register_auto("before_action_space", ...)` on `{fishing, forest}` | fishing→+1 wood, forest→+1 food; both atomic → `register_action_space_hook` for both |
| **A52 Throwing Axe** | `register_auto("before_action_space", ...)` on `forest` | +2 food when `get_space(state.board, "pig_market").animals.boar > 0`; atomic → hook |
| **A77 Hod** | `on_play` +1 clay + `register_auto("before_action_space", ..., any_player=True)` on `pig_market` | +2 clay to owner on any player's Pig Market use; `milk_jug.py` is the template |
| **A47 Trellises** | `on_play` + `schedule_resources` | Schedule food for next N rounds where N = fences built; `pond_hut.py` |
| **A43 Farmyard Manure** | `register_auto("after_build_stables", ...)` + `schedule_resources` | Schedule food for next 3 rounds after each stable build |
| **A74 Stable Tree** | Same as Farmyard Manure | Schedule wood instead of food |
| **A46 Claw Knife** | `register_auto("after_action_space", ...)` on `sheep_market` + `schedule_resources` | Schedule food for next 2 rounds; sheep_market already non-atomic |
| **A45 Fire Protection Pond** | `register_conditional` (house_material != WOOD) + `schedule_resources` | Schedule 6 rounds of food; `manservant.py` + `pond_hut.py` |
| **A76 Cob** | `start_of_round` optional trigger → `plow_driver.py` | Eligibility: clay ≥1 AND grain ≥1; apply: −1 grain +2 clay +1 food |

---

## Tier 2 — Moderate (one extra mechanism, clearly feasible)

These each need one thing beyond a clean template copy — a `CardStore`, a before/after
snapshot, checking space goods, or investigating an existing pending's parameters.

**A89 Stable Planner** — `schedule_effect` for rounds `current+3/+6/+9` → optional `start_of_round` trigger at each (exactly Handplow's shape) → apply fn pushes `PendingBuildStables(cost=Resources(), max_builds=1, build_stables_action=False)`. The free-stable primitive already exists in `mining_hammer.py`.

**A15 Carpenter's Axe** — `register("after_action_space", ...)` on `forest` (atomic → hook); eligibility: `p.resources.wood >= 7`; apply: push `PendingBuildStables(cost=Resources(wood=1), max_builds=1)`. Straightforward after confirming forest hosting works the same as fishing.

**A66 Feeding Dish** — `register_auto("before_action_space", ...)` on `{sheep_market, pig_market, cattle_market}`; eligibility: player already has ≥1 of the space's animal type; apply: +1 grain. The animal-type-to-space mapping is three lines of switch logic.

**A104 Wood Harvester** — `register_harvest_field_hook` + auto at `harvest_field`: iterate `BUILDING_ACCUMULATION_RATES` entries where the rate has wood; check `get_space(state.board, space_id).goods.wood` against thresholds (exactly 2 → +1 wood; ≥3 → +1 food). Scythe_worker template.

**A106 Slurry Spreader** — `register_harvest_field_hook` + auto at `harvest_field`: for each field in `players[idx].farmyard` where `grain == 1` → +2 food; `veg == 1` → +1 food. The field state is available in `state.players[idx].farmyard`; checks happen before the mechanical harvest removes the crop. Scythe_worker template.

**A107 Catcher** — `register_auto("before_action_space", ...)` on building resource accumulation spaces; eligibility: `people_placed_this_round = p.people_total - p.people_home` is in 1..3 AND `get_space(state.board, frame.space_id).goods` matches threshold `6 - people_placed`; apply: +1 food. The "how many workers placed this round" is derived from current player state at the before-phase (worker already placed, so `people_home` is decremented).

**A113 Heresy Teacher** — `register_auto("after_action_space", ...)` on `lessons`; iterate `farmyard` fields: if `grain >= 3` and `veg == 0` → apply `fast_replace(field, veg=field.veg+1)`. Lessons is non-atomic (already hosted), so no hook registration needed.

**A41 Vegetable Slicer** — `register_auto("after_build_major", ...)` on any space; eligibility: the just-built major was a Cooking Hearth (check `COOKING_HEARTH_INDICES` and whether a Fireplace was returned — the `CommitBuildMajor.major_idx` carries this). Apply: +2 wood +1 veg.

**A72 Calcium Fertilizers** — `register_action_space_hook` for quarry-type spaces + `register_auto("before_action_space", ...)` on those spaces; for each field with `(grain > 0) != (veg > 0)` (exactly one crop type) → add 1 of that crop. Need to identify quarry space IDs from the board — there's at least one in stage 2.

**A68 Asparagus Gift** — `register_auto("before_build_fences", ...)`: CardStore(`"fences_before"`) = `fences_built(state)`; `register_auto("after_build_fences", ...)`: if `fences_built(state) - get(card_state, "fences_before") >= state.round_number` → +1 veg. Shepherd's Crook is the exact template for the before/after snapshot pattern.

**A95 Angler** — `register_auto("before_action_space", ...)` on `fishing`: CardStore(`"food_pre"`) = accumulated food on the space. `register("after_action_space", ...)` on `fishing`: eligibility `get(card_state, "food_pre") <= 2`; apply: push `PendingMajorMinorImprovement(...)`.

**A81 Interim Storage** — `register_auto("before_action_space", ...)` on clay/reed/stone accumulation spaces: increment CardStore(`"wood_stored"`/`"clay_stored"`/`"reed_stored"`) per space type. `register_start_of_round_hook` + auto at `start_of_round` rounds 7, 11, 14: move all CardStore counters to supply, reset to 0. Multiple pieces but all standard machinery.

**A31 Debt Security** — `register_scoring`: `min(len(major_improvements), unused_space_count)` where unused = cells that are `EMPTY` and NOT in `enclosed_cells(farmyard)`. Reference `big_country.py`'s space-counting idiom.

**A37 Bucksaw** — `register("after_renovate", ...)`: eligibility: `p.resources.wood >= 1`; apply: −1 wood +1 grain + `CardStore("vps")++`. `register_scoring`: returns CardStore VP count.

**A34 Loppers** — `register("after_build_fences", ...)`: eligibility: `p.resources.wood >= 1` AND `p.fences_in_supply > 0`; apply: −1 wood −1 `fences_in_supply` +2 food + `CardStore("vps")++`. `register_scoring` reads the VP bank.

**A93 Bed Maker** — `register("after_build_rooms", ...)`: eligibility: `p.resources.wood >= 1` AND `p.resources.grain >= 1`; apply: −1 wood −1 grain, push `PendingFamilyGrowth(...)`. Need to verify `PendingFamilyGrowth` can be pushed for the "room only" variant (rooms > people gate is already in the legality; check if the pending distinguishes room-only from wish-space growth).

**A97 Freshman** — `register("before_bake_bread", ...)`: eligibility: `bool(p.hand_occupations)`; apply: push `PendingPlayOccupation(player_idx=idx, initiated_by_id="card:freshman", cost=Resources())`. Scholar is the reference for free occupation play.

**A103 Portmonger** — Same snapshot pattern as Angler: before_action_space on food accumulation spaces records food count, after gives tiered goods (1 food → +1 veg, 2 → +1 grain, 3+ → +1 reed). Need to enumerate food accumulation spaces (fishing, meeting_place in family mode).

**A79 Garden Hoe** — `register_auto("before_sow", ...)`: CardStore snapshot of veg-field count. `register_auto("after_sow", ...)`: if veg-field count increased → +1 clay +1 stone. CardStore snapshot is cleaner than diffing field state.

**A109 Small Trader** — `register_auto("after_build_major", ...)` AND `register_auto("after_play_minor", ...)`, both filtered to the composite major/minor improvement host's `initiated_by_id`: +3 food. Need to verify the `initiated_by_id` string for the composite major/minor host.

---

## Deferred — known blockers

These need infrastructure that either doesn't exist or requires a design decision.

| Card | Blocker |
|------|---------|
| A85 Homekeeper | Adjacency geometry (no grid-adjacency API) |
| A94 Lazy Sowman | No "decline sub-action" event |
| A100 Curator | No return_home phase hook |
| A3 Paper Knife | Randomness in `step` violates the determinism invariant |
| A10 Wooden Shed | Play-channel restriction + renovation lock + room-as-card |
| A11 Mud Patch | Fields as boar-holding locations (new accommodation slot type) |
| A14 Carpenter's Hammer | Conditional cost modifier on build count + material |
| A17 Reclamation Plow | Conditional on accommodation outcome |
| A18 Wheel Plow | Multi-plow (PendingPlow appears single-field only) |
| A20 Double-Turn Plow | Same + state-dependent cost |
| A21 Family Friend Home | Condition at before-phase, effect after (need CardStore + new analysis) |
| A22 Telegram | Temporary extra worker |
| A23 Stone Company | Mandatory PendingMajorMinorImprovement with stone-spend constraint |
| A25 Bassinet | First-space-used tracking + extra worker |
| A27 Oven Site | One-time cost override for specific major improvements |
| A28 Forest School | Legality override + occupation cost conversion |
| A29/A35/A58/A70/A84 | Return_home phase hook |
| A30 Baking Sheet | New bake option outside BAKING_IMPROVEMENT_SPECS |
| A36 Facades Carving | Variable-count food→VP conversion (unclear how many choices to surface) |
| A39 Chapel | Creates a new shared action space |
| A40 Potter's Yard | Per-cell goods markers |
| A48 Shaving Horse | No generic "goods obtained" event |
| A49 Nest Site | Preparation-phase refill hook |
| A4 Baseboards | Alternative cost (2 food OR 1 grain) |
| A54 Credit | End-of-round hook (distinct from start_of_round) |
| A59 Potato Ridger | Conditional mandatory on harvest vegetable quantity |
| A60 Oriental Fireplace | At-any-time conversions |
| A61 Winnowing Fan | Baking conversion outside the bake-bread action |
| A62 Beer Keg | Harvest feed phase hook |
| A64 Barley Mill | Alternative cost (4 clay OR 2 stone) |
| A73 Agricultural Fertilizers | Cross-action used-spaces tracking |
| A82 Work Certificate | Take from accumulation spaces without worker placement |
| A1 Shelter | Restricted stable placement to 1-cell pastures only |
| A13 Renovation Company | One-time free renovation (cost override at play time) |
| A115 Chief Forester | PendingSow has no max-fields parameter |
| A124 Knapper / A126 Master Workman | Which round each stage card appears is not in GameState |

---

## Summary

The **Tier 1 easiest batch** to implement in one session (all confirmed templates, no
ambiguity): A99, A101, A105, A117, A122, A65, A8, A57, A7, A6, A51, A42, A52, A77, A47,
A43, A74, A46, A45, A76 — 20 cards, mostly occupations with scoring terms or auto effects,
and minors with on-play goods or scheduled resources. A121 is one step up (needs
`register_action_space_hook` for clay_pit, a one-liner).

Tier 2 cards are individually ~30–60 lines, solid one-at-a-time work — the most notable
batch being A37/A34 (CardStore VP bank pattern), A89 (Handplow + Mining Hammer combo),
and A68 (Shepherd's Crook snapshot pattern).
</content>
</invoke>
