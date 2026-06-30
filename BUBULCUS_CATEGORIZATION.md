# Bubulcus Card Implementation Categorization

A difficulty triage of the unimplemented Bubulcus (deck B) cards — 25 occupations and
59 minors — against the card machinery already built. Each card is classified by how
much (if any) new infrastructure it needs, with the template module to copy.

---

## Tier 1 — Trivially easy (direct template copy, mostly < 20 lines)

### Occupations

| Card | Pattern | Note |
|------|---------|------|
| **B105 Case Builder** | `on_play` → `consultant.py` | +1 of each of {food, grain, veg, reed, wood} you already hold ≥2 of |
| **B119 Lumberjack** | `on_play` + `schedule_resources` | +1 wood now; schedule wood on next N rounds where N = fences built; `wall_builder.py` / A47 Trellises shape |
| **B125 Estate Worker** | `on_play` + `schedule_resources` | wood/clay/reed/stone on the next 4 rounds in order; sequenced schedule calls |

### Minors

| Card | Pattern | Note |
|------|---------|------|
| **B37 Grange** | `on_play` → `consultant.py` | +1 food; simplest possible card |
| **B5 Store of Experience** | `on_play` → `consultant.py` | Reads `len(hand_occupations)` → stone/reed/clay/wood by tier |
| **B6 Excursion to the Quarry** | `on_play` → `consultant.py` | +stone = `people_total` |
| **B40 Brewery Pond** | `register_auto("before_action_space", ...)` on `{fishing, reed_bank}` | +1 grain +1 wood; both atomic → `register_action_space_hook`; `herring_pot.py`/A42 shape |
| **B44 Chick Stable** | `on_play` + `schedule_resources` | 2 food on rounds `current+3`, `current+4`; `pond_hut.py` |
| **B46 Club House** | `on_play` + `schedule_resources` | food on next 4 rounds, stone on the 5th; mixed-good schedule |
| **B78 Reed Belt** | `on_play` + `schedule_resources` | reed on rounds 5, 8, 10, 12 (only those still remaining) |
| **B73 Gift Basket** | `on_play` → `consultant.py` | Reads `num_rooms` (exactly 2/3/4/5) → veg/food/grain/veg |

---

## Tier 2 — Moderate (one extra mechanism, clearly feasible)

### Occupations

**B90 Cooperative Plower** — `register("before_action_space", ...)` on `farmland` (non-atomic, no hook); eligibility: Grain Seeds space occupied (`not _is_available(state, "grain_seeds")`) AND `_can_plow`; apply: push optional `PendingPlow`. Assistant Tiller / Mole Plow shape with an occupancy gate.

**B92 Little Stick Knitter** — `register("after_action_space", ...)` on `sheep_market`; eligibility: `round_number >= 5`; apply: push `PendingFamilyGrowth` (room-only variant). Same room-only-growth verification as A93 Bed Maker.

**B96 Tree Farm Joiner** — `schedule_effect` granting a Minor Improvement action at the next 2 odd-numbered rounds; round-start trigger pushes `PendingPlayMinor`. Handplow's deferred-effect shape, but pushing a play-minor instead of a plow.

**B101 Furniture Carpenter** — `register_harvest_field_hook` + optional trigger at `harvest_field`: eligibility: any player owns Joinery (or upgrade) AND `p.resources.food >= 2`; apply: −2 food + `CardStore("vps")++`. `register_scoring` reads the bank.

**B110 Pavior** — `register_start_of_round_hook` + auto at `start_of_round`: if `p.resources.stone >= 1` → +1 food (round 14 → +1 veg instead). Scullery template, conditional + round-14 special-case.

**B111 Rustic** — `register_auto("after_build_rooms", ...)`: count rooms built this action whose material is CLAY → +2 food +1 VP each (`CardStore` VP bank + `register_scoring`). Needs the before/after room-count snapshot + house-material check.

**B122 Mineralogist** — `register_auto("before_action_space", ...)` on clay and stone accumulation spaces; apply: +1 of the *other* good. clay_pit atomic → hook; need the stone (quarry) space id. Geologist shape.

**B124 Trimmer** — `register_auto("before_build_fences", ...)` snapshots pasture decomposition; `register_auto("after_build_fences", ...)`: if a new enclosure was created (not a subdivision) → +2 stone. Shepherd's Crook is the exact before/after-diff template.

### Minors

**B1 Upscale Lifestyle** — `on_play`: +5 clay, push optional `PendingRenovate` (player pays the cost). `shifting_cultivation.py` (push-a-primitive on_play).

**B4 Wood Pile** — `on_play`: +wood = count of own workers on accumulation spaces (scan the board for spaces in `ACCUMULATION_SPACES` where this player has a worker).

**B7 Wage** — `on_play`: +2 food + 1 food per owned bottom-row major improvement. Needs the bottom-row major classification.

**B9 Beating Rod** — play-variant `on_play`: get 1 reed OR −1 reed +1 cattle. Roof Ballaster / play-variant pattern (two `CommitPlayMinor` variants).

**B20 Chain Float** — `schedule_effect` for rounds 7, 8, 9 (fixed): optional `start_of_round` trigger grants a plow. Handplow shape, three fixed rounds. (The "place 1 field" then plow it reads as a granted plow.)

**B29 Cookery Lesson** — `register("after_action_space", ...)` on `lessons`; eligibility: owns a cooking improvement; apply: `CardStore("vps")++`. `register_scoring` reads the bank.

**B35 Hook Knife** — `register_conditional`: fires once when `sheep >= 8` (2-player threshold) → +2 VP, latched in `fired_once`. Manservant conditional-latch + `register_scoring`.

**B41 Hauberg** — `on_play`: alternate 2 wood / 1 boar on the next 4 round spaces; wood via `schedule_resources`, boar via `future_rewards` (animals auto-accommodate at round start). Both scheduling paths exist.

**B43 Chophouse** — `register_auto("after_action_space", ...)` on Grain Seeds / Vegetable Seeds; `schedule_resources` food for next 3 / 2 rounds. Claw Knife shape; need the seed-space ids.

**B49 Scales** — `register_auto("after_play_minor"/"after_play_occupation"/"after_build_major", ...)`: if `len(occupations) == len(minor_improvements ∪ majors)` → +2 food.

**B51 Digging Spade** — `register_auto("before_action_space", ...)` on `clay_pit` (atomic → hook); apply: +food = boar count in farmyard.

**B52 Growing Farm** — custom `prereq`: pasture-space count ≥ completed rounds; `on_play`: +food = `round_number`.

**B54 Tumbrel** — `on_play` +2 food; `register_auto("after_sow", ...)`: +1 food per stable owned. Garden Hoe shape.

**B58 Crack Weeder** — `on_play` +1 food; `register_harvest_field_hook` + auto at `harvest_field`: +1 food per veg about to be harvested from a field. Slurry Spreader (A106) shape.

**B59 Food Chest** — `on_play`: read where played (`initiated_by_id` = the Major Improvement space) → +4 food, else +2.

**B60 Brewing Water** — `register("after_action_space", ...)` on `fishing`; optional trigger, pay 1 grain → `schedule_resources` food for next 6 rounds.

**B63 Tasting** — `register("before_action_space", ...)` on `lessons`; optional trigger, exchange 1 grain → 4 food before paying the occupation cost.

**B64 Mill Wheel** — `register_auto("before_action_space", ...)` on `grain_utilization`; eligibility: Fishing space occupied (`not _is_available(state, "fishing")`); apply: +2 food. Occupancy-gate shape (cf. Cooperative Plower).

**B67 Hand Truck** — `register_auto("before_bake_bread", ...)`: +1 grain per own worker on an accumulation space. Same worker-scan as Wood Pile.

**B70 New Purchase** — `register_start_of_round_hook` (harvest rounds only) + optional trigger: buy 2 food → 1 grain and/or 4 food → 1 veg. Surfaced as optional triggers at the preparation host.

**B71 Harvest House** — `on_play`: if completed-harvest count (derived from `round_number`) == `len(occupations)` → +1 food +1 grain +1 veg.

**B75 Wood Workshop** — `register_auto("before_build_major", ...)` + `register_auto("before_play_minor", ...)`: +1 wood. "improvement" = major or minor.

**B76 Ceilings** — `on_play` + `schedule_resources` wood on next 5 rounds; `register_auto("after_renovate", ...)` clears the remaining scheduled wood. The clear-on-renovate is the only unusual part.

**B79 Corf** — `register_auto("before_action_space", ..., any_player=True)` on stone accumulation spaces; eligibility: the space holds ≥3 stone; apply: +1 stone to owner. Milk Jug / Hod any-player shape.

**B82 Value Assets** — `register_harvest_field_hook` (or post-harvest) + optional triggers: buy 1 food→1 wood / 1 food→1 clay / 2 food→1 reed / 2 food→1 stone, each at most once.

---

## Deferred — known blockers

| Card | Blocker |
|------|---------|
| B85 Farm Hand | 2×2-field geometry + restricted stable placement + person-capacity stable |
| B86 Truffle Searcher | Card-as-animal-holder (new capacity slot) keyed on completed feeding phases |
| B88 Established Person | One-time free renovation (cost override at play) + chained fences |
| B93 Confidant | Variable schedule count (2/3/4) + round-start Sow/Fences choice grant |
| B94 Stock Protector | Extra worker after the Fencing action |
| B100 Clutterer | Card-play-order tracking + "after this one" self-exclusion + text scan |
| B103 Field Merchant | No "decline improvement action" event (cf. Lazy Sowman) |
| B106 Moral Crusader | Inspect goods promised on the remaining round space, per round |
| B112 Silokeeper | Which card was revealed before the last harvest is not in GameState (hidden reveal order) |
| B113 Patch Caregiver | Card-as-field (new mechanic) + play-variant buy |
| B115 Tinsmith Master | Per-pasture capacity (conditional on "no stable") + extra-crop-on-sow |
| B116 Shoreforester | Preparation-phase reed-refill hook (cf. Nest Site) |
| B117 Informant | No "after each work phase" phase hook |
| B120 Sweep | Board-position / reveal adjacency of round-space cards |
| B3 Moonshine | Randomness in `step` violates determinism |
| B11 Feedyard | Card-as-animal-holder + breed-phase hook |
| B12 Stockyard | Card-as-animal-holder |
| B14 Hawktower | Round-space scheduled conditional build (stone room on round 12) |
| B15 Carpenter's Bench | Restricted "build 1 pasture from taken wood" + free fence |
| B17 Forest Plow | Return paid wood to the accumulation space (wood-to-space mechanic) |
| B18 Grassland Harrow | Variable schedule count by resources held + field + plow |
| B21 Hayloft Barn | Per-card goods stack + grain-gained event + family growth |
| B22 Walking Boots | Temporary extra worker (removed next return-home) |
| B23 Final Scenario | Private/owner-only action space |
| B26 Agrarian Fences | Modifies the Grain Utilization sub-action menu (legality change) |
| B27 Toolbox | Turn-end build-detection + push specific majors |
| B28 Forestry Studies | Return wood to the Forest space (wood-to-space) to play an occupation |
| B30 Wood Palisades | Alternative fence-piece (2 wood) mechanic + VP |
| B31 Pottery Yard | Orthogonal-adjacency geometry |
| B32 Kettle | At-any-time grain→food+VP conversion |
| B34 Special Food | Conditional on accommodation outcome (cf. Reclamation Plow) |
| B38 Future Building Site | Placement restriction + house-adjacency geometry |
| B42 Forest Inn | Creates a new shared action space + toll |
| B48 Forest Stone | Per-card goods stack |
| B53 Sculpture Course | End-of-round (no-harvest) hook |
| B55 Maintenance Premium | Per-card goods stack |
| B65 Grain Depot | Reads which resource paid the card's cost (payment-type not tracked) |
| B69 Potters Market | At-any-time conversion |
| B72 Love for Agriculture | Sow in pastures / pastures-as-fields (major new mechanic) |
| B81 Handcart | Take from accumulation space without worker placement (cf. Work Certificate) |
| B83 Muddy Puddles | Per-card ordered goods stack + at-any-time take |

---

## Summary

The **Tier 1 easiest batch** (all confirmed templates, no ambiguity): B105, B119, B125,
B37, B5, B6, B40, B44, B46, B78, B73 — 11 cards, mostly on-play goods and scheduled
resources.

Tier 2 is the large workable middle (32 cards), individually ~30–60 lines — the notable
clusters being the occupancy-gate income cards (B90, B64), the CardStore-VP-bank cards
(B101, B29, B35, B111), the harvest-field income cards (B58, B82, B101), and the
any-player hook (B79, Corf).
</content>
