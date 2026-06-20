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
12. [Board Geography](#board-geography)
13. [Bake Bread Action](#bake-bread-action)
14. [Major Improvements](#major-improvements-all-10-family-game)
15. [Harvest](#harvest)
16. [Scoring](#scoring)
17. [Cards (Full Game Reference)](#cards-full-game-reference--for-when-cards-are-added)
18. [3- and 4-Player Games](#3--and-4-player-games)

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

In the Revised Edition "goods" is the umbrella term and now *includes food* (the
old term "items", which excluded food, no longer exists). "Resources" = crops +
building resources. The card-text verbs are precise and worth distinguishing:

- **Obtain**: the umbrella for *any* way a good moves into your personal supply —
  from an accumulation space, from the general supply for any reason, by
  harvesting, or from a card in front of you. Many card triggers key off "each
  time you obtain X" and fire regardless of the source.
- **Costs / pay / spend**: when you (have to) pay goods, they must come from your
  personal supply. A **building cost** is the goods paid for rooms, stables,
  fences, renovations, and cards; an **occupation cost** is the food paid to play
  an occupation. Goods *spent* leave the supply — which is why resources spent for
  end-game bonus points (Joinery etc.) no longer count toward the tiebreaker,
  while resources a card merely *checks you have* still do.

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

## Board Geography

A handful of card effects depend not on *which* action space you use but on
*where it physically sits* on the board — "the four spaces above Fishing", "an
action space orthogonally adjacent to another occupied space", "round spaces 8 to
11", and so on. This section documents that physical layout. It is a **Phase 3
(cards) concern**: the engine currently models the action spaces as an unordered
set (`BoardState.action_spaces`, a canonical tuple keyed by id), with **no 2-D
geometry**. None of the spaces surfaced in the Family game care about position, so
nothing today reads this — but the card system will, and several cards below
cannot be implemented without giving the board coordinates.

Keep this distinct from the **farmyard** (each player's own 3×5 grid of
rooms/fields/pastures — see [Farmyard](#farmyard)). Both have a geometry and some
cards reference each; they are different boards.

### The two board pieces

The physical board is two interlocking jigsaw pieces:

- **2-player main board** — every action space used in our Family game: the 14
  numbered **round spaces** plus the block of **fixed (always-available) action
  spaces** to their left.
- **4-player extension** — a separate piece adding spaces used only at 3–4
  players (Copse, Grove, Hollow, Resource Market, a second Lessons, Traveling
  Players). **Not used in the 2-player game** (matching the setup note that the
  2-player additional tile is also unused in our implementation).

### Adjacency convention

"**Adjacent**" used alone always means **orthogonally adjacent** — sharing an
edge (up / down / left / right). A card only counts diagonals when it explicitly
says "orthogonally *or diagonally* adjacent". This convention holds for both the
action board and the farmyard. Note that **"above"/"below" ≠ "adjacent"**: a space
can be above another (same column, higher up) without being orthogonally adjacent
to it — only the *immediately* neighboring space is adjacent.

### The action-board grid

The fixed spaces and round spaces share one 2-D grid, but **the cards are not all
the same size**: the round spaces (and the accumulation-space "Round 1" card) are
roughly **double the height** of the small fixed cards. A round space therefore
straddles *two* fixed-card rows, and adjacency is staggered — a tall space can be
orthogonally adjacent to *two* spaces in the column beside it.

To express this exactly, the grid below is drawn in **half-height "unit rows"** (a
double-height space occupies two consecutive unit rows; its name is repeated in
both). The left columns are the fixed spaces; the round spaces extend rightward,
grouped by stage. Each **stage** owns a contiguous run of round numbers, revealed
onto its round space (Stage 1 = rounds 1–4, Stage 2 = 5–7, Stage 3 = 8–9, Stage 4
= 10–11, Stage 5 = 12–13, Stage 6 = round 14). Top unit row = top of board; a "—"
is empty board (no action space):

| unit row | Col A (fixed) | Col B (fixed) | Col C — Stage 1 | Col D — Stage 2 | Col E — Stage 3 | Col F — Stage 4 | Col G — Stage 5 | Col H — Stage 6 |
|---|---|---|---|---|---|---|---|---|
| 1 | Farm Expansion | Round 1 | Round 2 | Round 5 | Round 8 | Round 10 | Round 12 | Round 14 |
| 2 | Meeting Place | Round 1 | Round 2 | Round 5 | Round 8 | Round 10 | Round 12 | Round 14 |
| 3 | Grain Seeds | Forest | Round 3 | Round 6 | Round 9 | Round 11 | Round 13 | — |
| 4 | Farmland | Clay Pit | Round 3 | Round 6 | Round 9 | Round 11 | Round 13 | — |
| 5 | Lessons | Reed Bank | Round 4 | Round 7 | — | — | — | — |
| 6 | Day Laborer | Fishing | Round 4 | Round 7 | — | — | — | — |

A name spanning two unit rows (e.g. **Round 1** in rows 1–2, **Round 3** in rows
3–4) is one double-height space; the six single-height fixed cards of Col A line up
one-per-unit-row. (The **Side Job** tile is also an always-available fixed space;
it is placed onto the board separately and no geography card references its
neighbors, so its exact cell is not pinned here.)

**At 3–4 players, an additional column of action spaces is added to the *left* of
Col A** (the 4-player extension piece: Copse, Grove, Hollow, Resource Market, a
second Lessons, Traveling Players). The 2-player grid above is the right-hand piece
in isolation.

The relationships cards actually rely on:

- **Round 1 is orthogonally adjacent to both Farm Expansion and Meeting Place** —
  the tall Round 1 card spans both of their unit rows. Likewise **Round 3 is
  adjacent to both Forest and Clay Pit**, and **Round 4 to both Reed Bank and
  Fishing**.
- **Column B, top to bottom: Round 1 → Forest → Clay Pit → Reed Bank → Fishing.**
  The **four spaces above Fishing** are therefore Reed Bank, Clay Pit, Forest, and
  the **Round 1** space (Brook B056's set). "Above" ≠ "adjacent": of those four,
  only Reed Bank is orthogonally adjacent to Fishing.
- **Fishing's three orthogonal neighbors** (Water Worker D144) are exactly **Reed
  Bank** (above), **Day Laborer** (left, same unit row), and **Round 4** (right —
  the tall Round 4 spans Fishing's unit row). Fishing is the bottom-left corner, so
  it has no neighbor below.
- **Day Laborer and Lessons are orthogonally adjacent** (Col A, stacked) — the
  Job Contract C023 pair.
- **Round spaces are addressable by number / band** — "round spaces 1/2/3/4",
  "round spaces 3 and 6", "round spaces 8 to 11", "round space 14", etc.
- **Accumulation / market stage cards occupy round spaces**, so a market's board
  neighbors are whatever sits next to the round space it was revealed onto (the
  animal markets are Sheep = Stage 1, Pig = Stage 3, Cattle = Stage 4).
- **Reveal order is itself a position** — "the most recently placed/revealed
  action space card" and "the card left of the most recently placed card" pick a
  space out by *when/where* it entered the board.

### Cards that reference board geography

The action-board cards (would-be Phase 3 work — the engine has no action-space
coordinates yet):

| Card | # | What it keys off |
|---|---|---|
| Brook | B056 | the four spaces **above Fishing** (Round 1, Forest, Clay Pit, Reed Bank) |
| Water Worker | D144 | Fishing **and its three orthogonally adjacent** spaces |
| Job Contract | C023 | Day Laborer **and the adjacent Lessons** (one person uses both) |
| Legworker | C117 | using a space **orthogonally adjacent to another space occupied** by your person |
| Pig Stalker | D165 | occupying the space **immediately above or below** an animal accumulation space |
| Sweep | B120 | the card **left of the most recently placed** round card |
| Sidekick | A171 | placing a second person on the card **immediately to the left** (chaining) |
| Outrider / Pioneer | C160 / E105 | the **most recently revealed** round card |
| Master Workman | A126 | **round spaces 1/2/3/4** → wood/clay/reed/stone |
| Bullcatcher | D179 | both **round spaces 3 and 6** occupied |

Cards keyed to the **farmyard** geometry (the engine *does* model per-cell, so
these are straightforward — listed for completeness):

| Card | # | What it keys off |
|---|---|---|
| Summer House | D033 | unused farmyard cells **orthogonally adjacent to your house** |
| Lynchet | D063 | harvested fields **orthogonally adjacent to your house** |
| Petting Zoo | E011 | a pasture **orthogonally adjacent to your house** |
| Homekeeper | A085 | a room **adjacent to both a field and a pasture** |

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

### Trigger Timing
"Each time you use [an action space]" triggers have been ruled to resolve **before**
taking the actions/goods that space provides. A card firing on the *use* of a space
therefore acts on the state as it was *before* the space's own effect is applied.

- Cards meant to fire *after* the space's effect say so explicitly — e.g. "immediately
  after each time you use…" (Mushroom Collector) or "at the end of that turn"
  (Firewood Collector). Honor the card's wording; the default for a bare "each time you
  use" is *before*.

### Card Timing & Terminology (general rulings)

These clarifications from the official rulebook/appendix apply across the whole
card system and are the ones most likely to bite an implementation:

- **The four timings.** Between any two consecutive things in the game flow
  (phases, rounds, actions, a space and its effect) there is an interim period.
  Every step has four associated timings, in order: **(1) "before" = immediately
  before** → **(2) the normal step** → **(3) immediately after** → **(4) after**.
  Card wording ("before", "immediately after", "at the end of") selects one of
  these slots, and "before"-cards resolve ahead of "after"-cards on the same step.
- **"Each time you use [an action space]" fires *before* the space's actions.**
  "Using" a space = *place the person*, **then** take its actions; the trigger
  fires at the comma — on the state as it was before the space's effect. (See
  Trigger Timing above.)
- **A newly-played card's "each time" trigger only fires on *later* turns**, not
  the turn it was played (e.g. Work Certificate A082, Animal Teacher A168). Cards
  that explicitly say "immediately after…" still may not self-trigger on the play
  turn.
- **"Another player" never includes you.** An effect that triggers on "another
  player" doing something fires only when *some other* player meets the condition;
  a card that means everyone must say "any player (including you)" explicitly.
- **You must be able to *accommodate* a newborn to actually receive it** — breeding
  / "get a newborn" effects are gated on having capacity (already reflected in the
  [Breeding Phase](#breeding-phase) model).
- **You may use a space and take *none* of its actions only if a card substitutes
  another action** for it (e.g. Freshman A097, Agrarian Fences B026). Otherwise
  "using" a space requires taking ≥1 of its actions. (Meeting Place is the standing
  exception — placement there is always legal.)
- **An occupied "Meeting Place" can never be used again** (errata) — this overrides
  *every* "use an occupied space" card, which is silently capped here.
- **"Once" / "each time".** "Each time" (replacing the old "whenever") means the
  effect happens every time its condition is met; an effect that triggers "once"
  may happen only a single time.
- **Field vs. field tile.** A "field" is the generic term covering both field
  *tiles* and field *cards* (e.g. Beanfield); field cards count as fields for
  prerequisites/triggers, but **only field tiles score points**.

### Example Cards — the diversity of effects

The Family game uses **no cards** (only Potter Ceramics exists, purely to exercise
the trigger machinery — see CLAUDE.md Phase 3). The full game's ~470 occupations
and minor improvements recombine the same primitive sub-actions into an enormous
variety of effects. A representative sample, by mechanic, to convey the range the
card system must eventually support:

**Personal goods stores / repeatable buys**
- **Grocer A102** — stack a fixed pile of goods on the card; buy the top good for
  1 food at any time (a personal vending machine).
- **Clay Carrier D122** — get 2 clay when played; once per round, buy 2 clay for
  2 food (on-play bonus + a metered repeatable purchase).

**Novel scoring**
- **Cow Prince C134** — at scoring, +1 point per farmyard space (rooms included)
  holding at least 1 cattle (a scoring rule unlike any base category).

**Per-action-space triggers ("each time you / another player uses X")**
- **Milk Jug A050** — whenever *any* player uses Cattle Market, you get 3 food and
  each opponent gets 1 (a board-wide payout).
- **Fishing Net C051** — each time *another* player uses Fishing, they must first
  pay *you* 1 food (a toll on opponents).

**Delayed payouts onto future round spaces**
- **Wood Collector C118** — place 1 wood on each of the next 5 round spaces; collect
  it at the start of each (the same mechanic as the Well major improvement).

**Conversion / exchange engines**
- **Hard Porcelain B080** — at any time, exchange 2/3/4 clay for 1/2/3 stone
  (rate-laddered upgrade).
- **Sheep Walker B104** — at any time, exchange 1 sheep for 1 wild boar, 1
  vegetable, or 1 stone (a flexible any-time swap).

**Cost reducers**
- **Lumber Mill A075** — every improvement costs you 1 wood less.
- **Forest School A028** — pay occupation costs in wood instead of food, and treat
  Lessons as unoccupied (it changes the *currency* of a cost, not just the amount).

**Replacement / alternative actions** (substitute one action for another)
- **Freshman A097** — when you get a Bake Bread action, instead play an occupation
  for free (the canonical substitute-action card; lets you "use" Grain Utilization
  even when you couldn't sow or bake).
- **Agrarian Fences B026** — at Grain Utilization, take a Build Fences action
  instead of one of the two provided actions — even when you can't sow or bake.

**Animal / field specials that bend core rules**
- **Dolly's Mother E084** — you need only 1 sheep (not 2) to breed sheep.
- **Wood Field D075** — sow and harvest *wood* on a card as though it were grain on
  2 fields (farming a building resource).

**Bending placement rules**
- **Mummy's Boy A130** — place a later person on the space already holding your
  second person and use that occupied space again (exactly what the Meeting Place
  errata forbids in general).

### Drafting Variant
Each player dealt X cards (7–10). Pick 1, pass X−1 left. Repeat 7 rounds.
If X > 7, final passed card is discarded. Players end with 7 of each type.
X=10: each player sees 49 cards during draft (high opponent-hand information).

---

## 3- and 4-Player Games

The rest of this document describes the **2-player Family game**, which is what the
engine implements. This section is reference for the eventual multi-player /
Phase 3 extension (CLAUDE.md lists 4-player as a possible-but-unstarted direction;
the player-alternation logic already uses modular arithmetic that generalizes to N
players, but `setup`, the action board, and the card-pool composition assume 2
players). Agricola RE is a **1–4 player** game in the base box.

### What changes: extra action spaces on the board extension

More players means more workers competing for spaces, so the board grows. A
**game-board extension** with extra action spaces is attached to the **left of
Column A** (see [Board Geography](#board-geography) — the extension is the column
the geography grid notes is added at 3–4 players). Which spaces are active and
their yields depend on the player count:

| Extension space | 3-player | 4-player |
|---|---|---|
| Copse | — (not used) | Accumulation: +1 wood |
| Grove | Accumulation: +2 wood | Accumulation: +2 wood |
| Hollow | Accumulation: +1 clay | Accumulation: +2 clay |
| Resource Market | 1 food **and** (1 reed *or* 1 stone) | 1 reed, 1 stone, **and** 1 food |
| Lessons (extra) | Play 1 occupation (cost 2 food) | Play 1 occupation (cost 2 food; first **two** cost 1 each) |
| Traveling Players | — (not used) | Accumulation: +1 food |

So a 3-player game adds 4 extension spaces (Grove, Hollow, Resource Market, the
extra Lessons); a 4-player game adds all 6 (also Copse and Traveling Players, and
bumps Hollow to +2 clay and broadens Resource Market). The extra **Lessons** space
is why a multi-player game has *two* Lessons spaces — the count-progression of the
[occupation-cost counter](#occupation-cost-counter) is per-player across both.

### The additional "variant" tile

The game ships **two variant tiles** — one for the 2-player game, one for the 3-/4-
player game — each adding a small cluster of spaces. The **3–4 player tile** adds:

- **Wish for Children** — from round 5: Family Growth (room required).
- **Animal Market** — buy 1 cattle for 1 food, *either/or* receive 1 sheep + 1 food,
  *either/or* receive 1 wild boar.

(The 2-player tile — Copse / Wish for Children / Resource Market / Animal Market —
is the one our implementation deliberately omits; see [Setup](#setup-2-player-family-game).)

### Cards are filtered by player count

In the full (non-Family) game each player has private hands of occupations and
minor improvements. Every card is marked with a **minimum player count**, and you
return the cards above your count to the box before dealing:

- **[1+]** — used at 1–4 players (always in).
- **[3+]** — used at 3–4 players only.
- **[4]** — used at 4 players only.

So raising the player count *shuffles in more cards* (the [3+] then the [4] cards),
widening the card pool. (The compendium also documents 5+ player cards and 6-player
major-improvement duplicates; those need a separate expansion and are out of scope
for the 1–4 base game.) The 2-player Family game we model uses **no** hand cards at
all — the Side Job tile replaces them — so this filtering does not apply to it.

### What stays the same

- **Setup food** — the rule is unchanged, just applied to more players: the
  starting player gets **2 food**, **every other player gets 3 food**.
- **Turn order** — still place exactly one person at a time, in clockwise order
  from the starting player, alternating until everyone has placed all their people.
- **Major improvements** — one shared set of 10 (two Fireplaces, two Cooking
  Hearths), claimed first-come, same as 2-player.
- **Family** — still start with 2 people, maximum 5; **rounds** (14, with harvests
  after 4/7/9/11/13/14); **scoring categories**; and the farmyard, fences, animals,
  and harvest rules are all identical to the 2-player game described above.
