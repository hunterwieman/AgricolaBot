# AgricolaBot — Complete Rules Reference

Agricola Revised Edition (AG2), 2-player Family game variant.
This is the complete rules reference for design conversations.
Clarifications established in design sessions are marked *.

---

## Contents

1. [Setup](#setup-2-player-family-game)
2. [Goods and Supplies](#goods-and-supplies)
3. [Round Structure](#round-structure)
4. [Farmyard](#farmyard)
5. [House and Rooms](#house-and-rooms)
6. [People](#people)
7. [Fields and Crops](#fields-and-crops)
8. [Animals](#animals)
9. [Stables](#stables)
10. [Fences and Pastures](#fences-and-pastures)
11. [Action Spaces](#action-spaces)
12. [Bake Bread Action](#bake-bread-action)
13. [Major Improvements](#major-improvements-all-10-family-game)
14. [Harvest](#harvest)
15. [Scoring](#scoring)
16. [Cards (Full Game Reference)](#cards-full-game-reference--for-when-cards-are-added)

---

## Setup (2-Player Family Game)

- Starting player determined randomly. SP gets **2 food**, other player gets **3 food**.
- Each player starts with 2 people placed in their 2 starting wood rooms.
  Remaining 3 people + 4 stables + 15 fences are in supply.
- **Starting room positions**: cells **(1,0) and (2,0)** in the 3×5 farmyard grid
  (row 0 = top, col 0 = left → rooms are at bottom-left).
- All 10 major improvements on supply board, unowned.
- 14 action space cards sorted into 6 stage stacks. **Cards within each stage are
  shuffled** (random order within stage); stage order is fixed.
- **Side Job tile**: always available as a permanent action space (not a stage card).
- **Meeting Place**: accumulates 1 food per round (Family game config). Food
  collected by whoever uses the space, not automatically by the SP.
- 2-player additional tile (Copse/Resource Market/Animal Market/Modest Wish):
  **not used** in our implementation.
- No occupation or minor improvement hand cards in Family game.

---

## Goods and Supplies

### Personal Supply
The goods a specific player controls, stored visibly in front of them.
Includes: building resources (wood, clay, reed, stone), crops (grain,
vegetables), food tokens, and animals. When a player "gets," "takes," or
"receives" goods, they move to that player's personal supply. When a player
"pays," "spends," or "uses" goods, they leave the personal supply.

### General Supply
The communal stock of all unused game components — the central reserve.
All goods that enter play come from the general supply; all discarded or spent
goods return to it. Key examples:
- Accumulation spaces are refilled each preparation phase with goods taken from
  the general supply.
- Food produced by major improvements (Fireplace, Joinery, etc.) comes from the
  general supply.
- Bonus crops added to a field during sowing come from the general supply.
- Newborn animals during breeding come from the general supply.
- Excess animals a player cannot accommodate are returned to the general supply.

### Crops on Field Tiles
Crops sown onto field tiles are neither in the personal supply nor the general
supply — they belong to the field and cannot be spent or used until harvested.
During scoring, crops on fields DO count toward the player's total.

### Goods Types
- **Building resources**: wood, clay, reed, stone
- **Crops**: grain, vegetables
- **Animals**: sheep, wild boar, cattle
- **Food**: food tokens (not building resources; excluded from tiebreaker)
- **Goods** (umbrella term): all of the above

---

## Round Structure

14 rounds. Harvests occur at the end of rounds 4, 7, 9, 11, 13, 14.

### 1. Preparation Phase
- Reveal top stage card, place on current round space.
- Collect any goods on that round space promised by prior card effects;
  these go to the owning player's personal supply.
- Replenish all **accumulation spaces** (spaces that collect goods each round;
  defined fully in the Action Spaces section): take the stated goods from the
  general supply and place them on the space, on top of any goods already there.

### 2. Work Phase
- Starting player first, then clockwise. Each player places exactly one person
  and immediately takes that action. Alternate until all people are placed.
- An occupied space cannot be used again (some card exceptions exist).
- Must take at least one available action when placing a person. It is illegal to place a person on an action space and perform no correcponding actions. The exception is that is is always legal to place a person on the meeting place action space.

### 3. Returning Home Phase
- All people return home to their rooms.
- Newborns placed on action spaces this round return home and become adults.

### 4. Harvest Phase (after rounds 4, 7, 9, 11, 13, 14)
Three sub-phases in order: Field → Feeding → Breeding. See the Harvest section.

---

## Farmyard

- 3 rows × 5 columns = 15 cells. Row 0 = top, column 0 = left.
- **Used cell**: has a room, field, or stable on it, or is enclosed by fences.
- **Unused cell**: empty or contains only goods/animals not explicitly "used".
  Scores −1 per unused cell at end of game.

---

## House and Rooms

- Starts as 2 wood rooms. No fixed room cap — the limit is physical (farmyard
  space, adjacency, and the empty/non-enclosed cell requirement).
- Each room holds 1 person. House also holds exactly **1 pet animal** of any type.
- **Building cost**: 5 wood/clay/stone + 2 reed per room. The built room must
  match the current material of the house (wood rooms in a wood house, etc.).
- New rooms must be orthogonally adjacent to an existing room.
  *Rooms chain adjacency within one action: a room just built counts immediately
  for the next room placed in the same action.*
- New rooms must be placed on an **empty, non-enclosed** cell — cells already
  enclosed by fences (i.e. inside a pasture) cannot have rooms built on them.
- **Renovation**: must renovate ALL rooms at once. Cannot renovate partially.
  Wood→Clay: 1 clay per room + 1 reed. Clay→Stone: 1 stone per room + 1 reed.
  *(The reed cost is 1 total, not per-room.)*

---

## People

- Start with 2. Maximum 5.
- **Family Growth**: requires a Wish for Children action space. "With Room Only"
  requires more rooms than people currently. "Even Without Room" has no restriction.
- **Newborn placement**: newborn meeple placed on the action space next to the
  parent. *The space now holds 2 of that player's meeples — relevant for
  occupancy-based card triggers.*
- Newborn cannot take an action in its birth round.
- Newborn requires **1 food** if a harvest occurs at the end of their birth round; **2 food** at every subsequent harvest. (If no harvest follows their birth round, they cost 2 food at the next harvest like any other adult.)
- Counts toward "number of people" immediately when placed.

---

## Fields and Crops

- First field tile: any empty, non-enclosed cell. Subsequent tiles: must be
  orthogonally adjacent to an existing field tile, and must also be placed on
  an empty, non-enclosed cell. Cells already enclosed by fences (i.e. inside a
  pasture) cannot have fields placed on them.
- **Sowing** (requires crops in personal supply and an empty field):
  - Grain: place 1 from personal supply onto the field, add 2 from the general
    supply = **3 grain total in field**
  - Vegetables: place 1 from personal supply onto the field, add 1 from the
    general supply = **2 vegetables total in field**
- *Cannot sow grain received in the same turn (e.g. from Grain Seeds). It goes
  to personal supply first; sowing requires a specific Sow action from Grain
  Utilization, Cultivation, or a played card.*
- Field phase of harvest: take exactly 1 crop from each planted field and move
  it to personal supply. Mandatory for all fields.

---

## Animals

### Accommodation
Animals must be accommodated on the farm. They are placed on the farmyard,
not simply held in personal supply.

**Capacity formula**: `2 × num_cells_in_pasture × (2 ^ num_stables_in_pasture)`

Examples:
- 1×1, 0 stables → 2
- 1×1, 1 stable → 4
- 2×1, 0 stables → 4
- 2×1, 1 stable → 8
- 2×1, 2 stables → 16

**Standalone (unfenced) stable**: holds exactly 1 animal of any type.
**House pet slot**: exactly 1 animal of any type, always present.

*Each pasture holds exactly ONE type of animal. The same type may be split
across multiple pastures (e.g. 2 sheep in pasture A, 3 sheep in pasture B).*

### Gaining Animals from Accumulation Spaces
Must take ALL animals from the space (they come from the general supply via the
accumulation space). Must then accommodate on the farmyard, convert to food
using a cooking improvement — Fireplace or Cooking Hearth, defined in Major
Improvements section — or return excess to the general supply. Cannot leave
animals on the accumulation space.

### Free Rearrangement
*Animals are the only farm components that can be freely rearranged at any
time. Rooms, fields, fences, and stables are permanent once placed.*
Animals can be discarded to the general supply at any time.

### Breeding Phase
The Breeding Phase is the third sub-phase of the Harvest (see Harvest section).
Fireplace and Cooking Hearth referenced below are defined in Major Improvements.

- Fires for each type where player has ≥ 2 AND capacity exists for the newborn.
  Newborns come from the general supply.
- **Cannot eat or exchange animals during the breeding phase.**
- *CAN eat animals immediately before breeding to create room for newborns.*
- *Players must accommodate newborns on the farm. If they have insufficient
  space, they must forgo newborn(s) or release existing animals to the general
  supply for free. Only after completing this accommodation step may they resume
  converting animals to food using the Fireplace or Cooking Hearth.*
- At most 1 newborn per animal type per harvest.
- Parents do not need to be in the same pasture to breed.

*Breeding frontier model (our implementation)*: Pre-breeding eating only. No
immediate post-breeding cooking step (optimal players preserve optionality and
only cook when immediately beneficial). Food formula per type (example: sheep):
- `food_s = (s+1−sF) × sR` if `s ≥ 2 AND sF ≥ 3` (breed fired)
- `food_s = (s−sF) × sR` otherwise
where s = sheep count pre-breeding, sF = sheep count post-breeding, sR =
sheep-to-food conversion rate. The condition `sF ≥ 3` is the exact indicator
that breeding fired and the newborn was accommodated.

---

## Stables

- 4 stables per player. No adjacency requirement. Max 1 per cell (cell must be empty).
- *Stable cost is action-dependent:*
  - Farm Expansion: 2 wood per stable (from personal supply)
  - Side Job tile: 1 wood for exactly 1 stable
  - Card effects: as stated on the card

---

## Fences and Pastures

- 15 fence pieces per player. Each fence costs 1 wood from personal supply
  (on the Fencing action space).
- Placed on edges between cells or on the farmyard boundary.
- **Validity**: a Build Fences action must result in at least one new fence
  being placed. After the action, all placed fences must be connected to other
  fences at both ends — meaning all fences enclose one or more pastures.
- **Enclosable cells**: fences may only enclose cells that are **empty or contain
  a stable**. Cells with rooms or fields cannot be enclosed (a Build Fences
  action that would enclose a room or field cell is illegal). Stables that end
  up inside a pasture become "fenced stables" and double the pasture's capacity
  per stable; standalone (unfenced) stables hold exactly 1 animal each.
- *Room tile and field tile borders do NOT count as fences. Every side of every
  pasture requires explicit fence pieces from the player's supply.*
- Fences cannot be demolished once placed.
- **Pasture adjacency**: first pasture anywhere; every subsequent pasture must be
  orthogonally adjacent to an existing pasture. Subdivisions satisfy this trivially.

---

## Action Spaces

### Accumulation Spaces
Action spaces marked with an ochre arrow are **accumulation spaces**. During
each preparation phase, the stated goods are taken from the general supply and
placed on the space, stacking on top of any goods already there from previous
rounds. If the space was not used last round, goods accumulate (e.g. Forest
unused for 3 rounds has 9 wood on it).

When you place a person on an accumulation space, you **must take ALL goods**
currently on it and move them to your personal supply. You cannot leave goods
behind (barring specific card effects).

Accumulation spaces in our 2-player Family game:

| Space | Accumulates | When available |
|---|---|---|
| Forest | +3 wood/round | Always |
| Clay Pit | +1 clay/round | Always |
| Reed Bank | +1 reed/round | Always |
| Fishing | +1 food/round | Always |
| Meeting Place | +1 food/round | Always (Family game variant) |
| Sheep Market | +1 sheep/round | Stage 1 |
| Western Quarry | +1 stone/round | Stage 2 |
| Pig Market | +1 boar/round | Stage 3 |
| Cattle Market | +1 cattle/round | Stage 4 |
| Eastern Quarry | +1 stone/round | Stage 4 |

All other action spaces are **permanent** (fixed effect each use, no
accumulation) or **stage card** spaces with fixed effects.

### "And/or" vs. "And Afterward"
- **"And/or"**: either sub-action, or both in either order. Must do at least one.
  *Each sub-action category may be taken at most once within the action;
  you cannot return to a category after switching to the other (e.g., on
  Farm Expansion: rooms-then-stables or stables-then-rooms, but not
  rooms-then-stables-then-rooms).*
- **"And afterward"**: first action mandatory, second optional (only after first).

*Cultivation ordering*: plowing first enables sowing the newly plowed field in
the same action. Only and/or space in Family game where ordering matters.

### All Action Spaces

| Space | Type | Effect |
|---|---|---|
| Farm Expansion | Permanent | Build Rooms (5 mat+2 reed each) **and/or** Build Stables (2 wood each) |
| Meeting Place | Accum + Permanent | Become SP (mandatory) + collect accumulated food (1/round) |
| Grain Seeds | Permanent | Get 1 grain from general supply |
| Farmland | Permanent | Plow 1 field |
| Lessons | Permanent | Play 1 occupation (unusable in Family game) |
| Day Laborer | Permanent | Get 2 food from general supply |
| Forest | Accumulation | Take all wood (+3/round from general supply) |
| Clay Pit | Accumulation | Take all clay (+1/round) |
| Reed Bank | Accumulation | Take all reed (+1/round) |
| Fishing | Accumulation | Take all food (+1/round) |
| Side Job | Permanent | Build exactly 1 stable (1 wood) **and/or** Bake Bread |
| Major Improvement | Stage 1 | Build 1 major or play 1 minor improvement |
| Fencing | Stage 1 | Build fences (1 wood/fence from personal supply) |
| Grain Utilization | Stage 1 | Sow **and/or** Bake Bread |
| Sheep Market | Stage 1, Accum | Take all sheep (+1/round) |
| Basic Wish for Children | Stage 2 | Family Growth (room required) + optional minor improvement |
| House Redevelopment | Stage 2 | Renovate **then** optionally Major or Minor Improvement |
| Western Quarry | Stage 2, Accum | Take all stone (+1/round) |
| Vegetable Seeds | Stage 3 | Get 1 vegetable from general supply |
| Pig Market | Stage 3, Accum | Take all boar (+1/round) |
| Cattle Market | Stage 4, Accum | Take all cattle (+1/round) |
| Eastern Quarry | Stage 4, Accum | Take all stone (+1/round) |
| Urgent Wish for Children | Stage 5 | Family Growth even without room |
| Cultivation | Stage 5 | Plow 1 field **and/or** Sow |
| Farm Redevelopment | Stage 6 | Renovate **then** optionally Build Fences |

---

## Bake Bread Action

"Bake Bread" is an **action**, not just a capability. Having a baking
improvement is not sufficient on its own — you need both an action that grants
"Bake Bread" and at least one baking improvement to use it.

**Sources of a Bake Bread action:**
- Grain Utilization action space ("Sow and/or Bake Bread")
- Side Job tile ("Build stable and/or Bake Bread")
- Purchasing a Clay Oven or Stone Oven (one free action immediately on purchase)
- Various card effects (full game)

**During a Bake Bread action**, each of your baking improvements may activate
once, in any order you choose. Multiple improvements can all fire within a
single action. The improvements are: Fireplace, Cooking Hearth, Clay Oven,
Stone Oven. Each states what it does "on a Bake Bread action" in the table below.

**Fireplace and Cooking Hearth have two distinct modes:**
- *"At any time"*: convert animals and vegetables to food. No Bake Bread action
  required; can be done at any point during the game.
- *"On Bake Bread"*: convert grain to food. Requires a Bake Bread action.

Clay Oven and Stone Oven activate **only during** a Bake Bread action and
convert grain only (no animal or vegetable conversion).

---

## Major Improvements (all 10, Family game)

| Idx | Name | Cost | Effect |
|---|---|---|---|
| 0 | Fireplace | 2 clay | *At any time*: sheep→2, boar→2, cattle→3, veg→2 food. *On Bake Bread*: grain→2 food. |
| 1 | Fireplace | 3 clay | Same as idx 0 |
| 2 | Cooking Hearth | 4 clay or return Fireplace | *At any time*: veg→3, sheep→2, boar→3, cattle→4. *On Bake Bread*: grain→3. |
| 3 | Cooking Hearth | 5 clay or return Fireplace | Same as idx 2 |
| 4 | Well | 3 stone + 1 wood | Places 1 food (from general supply) on each of next 5 round spaces; owner collects during prep |
| 5 | Clay Oven | 3 clay + 1 stone | *On Bake Bread*: exactly 1 grain → 5 food. Grants 1 free Bake Bread action upon purchase. |
| 6 | Stone Oven | 1 clay + 3 stone | *On Bake Bread*: up to 2 grain → 4 food each. Grants 1 free Bake Bread action upon purchase. |
| 7 | Joinery | 2 wood + 2 stone | Once per harvest: 1 wood → 2 food. End-game bonus: 3/5/7 wood → 1/2/3 pts (once only). |
| 8 | Pottery | 2 clay + 2 stone | Once per harvest: 1 clay → 2 food. End-game bonus: 3/5/7 clay → 1/2/3 pts (once only). |
| 9 | Basketmaker's | 2 reed + 2 stone | Once per harvest: 1 reed → 3 food. End-game bonus: 2/4/5 reed → 1/2/3 pts (once only). |

All food produced by major improvements comes from the general supply.
Resources spent on end-game bonuses leave personal supply and do NOT count
toward the tiebreaker.

**Cooking rates summary** (animal/veg-to-food conversion, "at any time" mode):
- Cooking Hearth: sheep→2, boar→3, cattle→4, veg→3
- Fireplace: sheep→2, boar→2, cattle→3, veg→2
- Neither: (0, 0, 0) — animals cannot be converted to food

---

## Harvest

### Field Phase
Take exactly 1 crop from each planted field and move it to personal supply.
Cannot skip any field. Mandatory for all fields.

### Feeding Phase
- Each adult requires 2 food from personal supply. A newborn born in the
  round just ended (the round that this harvest immediately follows) requires
  only 1 food. Newborns from earlier unharvested rounds — or from harvested
  rounds — count as adults and require 2 food.
- Grain and vegetables in personal supply (but not on fields) count as
  1 food each and are removed from personal supply when used this way.
- With a Fireplace or Cooking Hearth: animals and vegetables can be converted
  to food at stated rates (the "at any time" mode); food tokens come from the
  general supply.
- Joinery, Pottery, and Basketmaker's Workshop can each convert 1 building
  resource to food once per harvest; food comes from the general supply.
- Shortfall: take 1 begging marker per missing food (−3 pts each at scoring).
- *Cannot withhold food tokens to intentionally over-beg, but players are not
  required to convert goods into food if they would otherwise beg.*

### Breeding Phase
See Animals section.

---

## Scoring

| Category | Points |
|---|---|
| Field tiles | 0–1: −1; 2: 1; 3: 2; 4: 3; 5+: 4 |
| Pastures | 0: −1; 1–4: 1 pt each; max 4 |
| Grain (personal supply + fields) | 0: −1; 1–3: 1; 4–5: 2; 6–7: 3; 8+: 4 |
| Vegetables (personal supply + fields) | 0: −1; 1: 1; 2: 2; 3: 3; 4+: 4 |
| Sheep | 0: −1; 1–3: 1; 4–5: 2; 6–7: 3; 8+: 4 |
| Wild Boar | 0: −1; 1–2: 1; 3–4: 2; 5–6: 3; 7+: 4 |
| Cattle | 0: −1; 1: 1; 2–3: 2; 4–5: 3; 6+: 4 |
| Unused farmyard spaces | −1 each |
| Fenced stables | 1 pt each (max 4) |
| Clay rooms | 1 pt each |
| Stone rooms | 2 pts each |
| People | 3 pts each |
| Begging markers | −3 each |
| Major improvement points | Fireplace/Hearth: 1; Clay Oven: 2; Stone Oven: 3; Well: 4; Joinery/Pottery/BMW: 2 |
| Craft building bonuses | 3/5/7 wood or clay → 1/2/3 pts; 2/4/5 reed → 1/2/3 pts (once only at scoring) |

**Tiebreaker**: total building resources (wood+clay+reed+stone) in personal
supply after bonus spending. Food excluded.

---

## Cards (Full Game Reference — for when cards are added)

### Passing Minors
Cards 001–009 in each deck. Execute immediate effect (goods from/to general
supply as stated), then pass card to next player in turn order. Card stays in
circulation indefinitely.

- "Place in front of you" triggers (e.g. Scales B049): do NOT fire.
- "Play or build an improvement" triggers (e.g. Cottar E122): DO fire.

### Occupation Cost Counter
Lessons space cost progression counts ALL occupations played by that player via
ANY method (Lessons, Scholar, Forest School, Freshman, card effects, etc.).
Per-player lifetime counter, not per-space.

### Prerequisites vs. Conditions
Prerequisite: must be met to PLAY the card.
Condition: must be met to USE the effect. Distinct from prerequisite.

### Drafting Variant
Each player dealt X cards (7–10). Pick 1, pass X−1 left. Repeat 7 rounds.
If X > 7, final passed card is discarded. Players end with 7 of each type.
X=10: each player sees 49 cards during draft (high opponent-hand information).
