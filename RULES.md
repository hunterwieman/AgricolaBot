# Agricola — Complete Rules Reference (Revised Edition)

Agricola is a worker-placement farming game for 1–4 players, played over 14 rounds.
On each turn a player places one worker on an action space and takes its action; over the
game you develop a farm, and the player whose farm is worth the most points wins.

This document is the complete rules reference for the **2-player game**. It treats the **full
game — played with occupation and minor-improvement cards — as the default**, and documents the
**cardless game** (often called the *Family game*) and the **3- and 4-player game** as variants
in their own sections. Items marked **\*** are clarifications that resolve points the base
rulebook leaves implicit.

---

## Contents

1. [Setup](#setup-2-players-full-game)
2. [Goods and Supplies](#goods-and-supplies)
3. [Round Structure](#round-structure)
4. [Farmyard](#farmyard)
5. [House and Rooms](#house-and-rooms)
6. [People](#people)
7. [Fields and Crops](#fields-and-crops)
8. [Stables](#stables)
9. [Fences and Pastures](#fences-and-pastures)
10. [Animals](#animals)
11. [Primitive Sub-Actions](#primitive-sub-actions)
12. [Action Spaces](#action-spaces)
13. [Major Improvements](#major-improvements-all-10)
14. [Bake Bread Action](#bake-bread-action)
15. [Cards: Occupations and Minor Improvements](#cards-occupations-and-minor-improvements)
16. [Board Geography](#board-geography)
17. [Harvest](#harvest)
18. [Scoring](#scoring)
19. [The Family Game (Cardless Variant)](#the-family-game-cardless-variant)
20. [3- and 4-Player Games](#3--and-4-player-games)

---

## Setup (2 Players, Full Game)

- **Starting player** determined randomly. The starting player (SP) gets **2 food**; the other
  player gets **3 food**.
- Each player takes their 5 people, 4 stables, and 15 fences in their color. Place **2 people**
  in the 2 starting wood rooms; the remaining **3 people + 4 stables + 15 fences** stay in supply.
- **Starting room positions**: the two rooms sit in the **lower-left** of the 3×5 farmyard board.
  (In the (row, col) grid introduced later under [Farmyard](#farmyard) — row 0 = top, col 0 = left —
  they are cells **(1,0) and (2,0)**.)
- All **10 major improvements** go on the supply board, available to either player.
- The **14 action-space cards** come into play over the game in **6 stages**: each round, one new
  action space is revealed onto that round's *round space* (the board's 14 numbered spaces). The
  stages are fixed bands of rounds (Stage 1 = rounds 1–4, Stage 2 = 5–7, Stage 3 = 8–9, Stage 4 =
  10–11, Stage 5 = 12–13, Stage 6 = round 14), but **the order of the cards within each stage is
  shuffled**, so which space appears in which round varies from game to game.
- **Hand cards (the draft).** Each player ends setup with a private, hidden hand of
  **7 occupations + 7 minor improvements** (the two kinds of hand card — see
  [Cards](#cards-occupations-and-minor-improvements)), chosen by a draft (see below). No further
  cards are drawn during the game — you must make the best of these 14.
- **Meeting Place** in the full game lets you become starting player and play a minor improvement;
  it does **not** accumulate food (that is the cardless variant).
- The **Side Job tile** and the **2-player additional tile** are **not used** in the full game
  (see [Action Spaces → Optional action spaces](#optional-action-spaces-not-in-the-main-game)).

### The draft

Cards are acquired by drafting rather than dealt as fixed hands. The two card types are drafted
**together** — on each pass you pick one of each type, not all occupations first and then all
minors.

- Deal each player an equal number of occupations and minor improvements — a **hand size of 7**,
  dealt from anywhere between **7 and 9 of each type** (more cards dealt = more selection and more
  information about what is in circulation).
- Each player picks **one occupation and one minor improvement** to keep, then passes the rest to
  the next player. (With 2 players, the two piles pass back and forth.) Repeat until each player
  has kept **7 of each type**.
- If more than 7 of a type were dealt, the surplus cards left undrafted at the end are removed
  from the game.

\* Draft procedures vary in practice (hand of 7 drawn from 7, 8, or 9 of each type; some groups
draft all occupations and then all minors). This reference assumes the **combined draft** described
above: both types drafted simultaneously, ending at 7 + 7.

---

## Goods and Supplies

### Personal Supply
The goods a specific player controls, stored visibly in front of them. Includes: building
resources (wood, clay, reed, stone), crops (grain, vegetables), food tokens, and animals. When a
player "gets," "takes," or "receives" goods, they move to that player's personal supply. When a
player "pays," "spends," or "uses" goods, they leave the personal supply.

### General Supply
The communal stock of all unused game components — the central reserve. All goods that enter play
come from the general supply; all discarded or spent goods return to it. Key examples:
- Accumulation spaces are refilled each preparation phase with goods taken from the general supply.
- Food produced by major improvements (Fireplace, Joinery, etc.) comes from the general supply.
- Bonus crops added to a field during sowing come from the general supply.
- Newborn animals during breeding come from the general supply.
- Excess animals a player cannot accommodate are returned to the general supply.

### Crops on Field Tiles
Crops sown onto field tiles are neither in the personal supply nor the general supply — they
belong to the field and cannot be spent or used until harvested. During scoring, crops on fields
DO count toward the player's total.

### Goods Types
- **Building resources**: wood, clay, reed, stone
- **Crops**: grain, vegetables
- **Animals**: sheep, wild boar, cattle
- **Food**: food tokens (not a building resource; excluded from the tiebreaker)
- **Goods** (umbrella term): all of the above. "Resources" = crops + building resources.

In the Revised Edition "goods" is the umbrella term and now *includes food* (the old term "items",
which excluded food, no longer exists). The card-text verbs are precise and worth distinguishing:

- **Obtain**: the umbrella for *any* way a good moves into your personal supply — from an
  accumulation space, from the general supply for any reason, by harvesting, or from a card in
  front of you. Many card triggers key off "each time you obtain X" and fire regardless of source.
- **Costs / pay / spend**: when you (have to) pay goods, they must come from your personal supply
  (animals come from your farm). A **building cost** is the goods paid for rooms, stables, fences,
  renovations, and cards; an **occupation cost** is the food paid to play an occupation. Goods
  *spent* leave the supply — which is why resources spent for end-game bonus points (Joinery etc.)
  no longer count toward the tiebreaker, while resources a card merely *checks you have* still do.

### Trading and discarding
Players may **not** give each other goods or trade. You **may** discard goods to the general
supply at any time (but not components in your player color — fences, stables, people).

---

## Round Structure

14 rounds. Harvests occur at the end of rounds 4, 7, 9, 11, 13, 14.

### 1. Preparation Phase
- Reveal the top stage card and place it on the current round space.
- Collect any goods on round spaces promised by prior card effects; these go to the owning
  player's personal supply. (You may not decline goods owed to you on a round space; you may
  decline an *exchange* offered on a round space, but then cannot make it later.)
- Replenish all **accumulation spaces** — action spaces (marked with an ochre arrow) that gather a
  fixed amount of goods each round, which the player who later uses the space takes all at once.
  Place the stated goods from the general supply on each one, on top of any goods left from earlier
  rounds. (Full list in the [Action Spaces](#action-spaces) section.)

### 2. Work Phase
- Starting player first, then clockwise. Each player places exactly one person and immediately
  takes that action. Alternate until all people are placed.
- An occupied space cannot be used again that round (some card exceptions exist).
- You must take at least one available action when placing a person. It is illegal to place a
  person on an action space and perform no corresponding action. The exception is that placing a
  person on the **Meeting Place** is always legal. (A card may also substitute a replacement
  action, allowing you to "use" a space you otherwise couldn't.)

### 3. Returning Home Phase
- All people return home to their rooms.
- Newborns placed on action spaces this round return home and become adults.

### 4. Harvest Phase (after rounds 4, 7, 9, 11, 13, 14)
Three sub-phases in order: Field → Feeding → Breeding. See the Harvest section.

---

## Farmyard

- 3 rows × 5 columns = 15 cells. Row 0 = top, column 0 = left.
- **Used cell**: has a room, field, or stable on it, or is (directly or indirectly) enclosed by
  fences. (A card may also define a cell as used.)
- **Unused cell**: empty, or containing only goods/animals not on a "used" cell.
  Scores −1 per unused cell at end of game.

---

## House and Rooms

- Starts as 2 wood rooms. No fixed room cap — the limit is physical (farmyard space, adjacency,
  and the empty/non-enclosed cell requirement).
- Each room holds 1 person. The house also holds exactly **1 pet animal** of any type.
- **Building cost**: 5 wood/clay/stone + 2 reed per room. The built room must match the current
  material of the house (wood rooms in a wood house, etc.).
- New rooms must be orthogonally adjacent to an existing room.
  *Rooms chain adjacency within one action: a room just built counts immediately for the next room
  placed in the same action.*
- New rooms must be placed on an **empty, non-enclosed** cell — cells already enclosed by fences
  (i.e. inside a pasture) cannot have rooms built on them.
- **Renovation**: upgrades the house **one material step**, and must renovate ALL rooms at once
  (cannot renovate partially, and at most one step per Renovate action — no wood→clay→stone in a
  single action). Wood→Clay: 1 clay per room + 1 reed. Clay→Stone: 1 stone per room + 1 reed.
  *(The reed cost is 1 total, not per-room.)* Once you live in a clay house you can only add clay
  rooms; once in a stone house, only stone rooms.

---

## People

- Start with 2. Maximum 5. Your unborn 3rd–5th people are called **offspring** while in supply; a
  person added by a Family Growth action is a **newborn** for the rest of that round, then becomes
  an **adult**.
- **Family Growth**: requires a Wish for Children action space. "With Room Only" requires more
  rooms than people currently. "Even Without Room" has no such restriction.
- **Newborn placement**: the newborn meeple is placed on the action space next to the parent.
  *The space now holds 2 of that player's meeples — relevant for occupancy-based card triggers.*
  (A card that grants family growth outside a Wish space places the newborn next to the person who
  took the most recent action.)
- A newborn cannot take an action in its birth round; it becomes an adult at the end of the round.
- A newborn requires **1 food** if a harvest occurs at the end of its birth round; **2 food** at
  every subsequent harvest. (If no harvest follows their birth round, they cost 2 food at the next
  harvest like any other adult.)
- A newborn counts toward "number of people" immediately when placed.

---

## Fields and Crops

- First field tile: any empty, non-enclosed cell. Subsequent tiles: must be orthogonally adjacent
  to an existing field tile, and must also be placed on an empty, non-enclosed cell. Cells already
  enclosed by fences (i.e. inside a pasture) cannot have fields placed on them.
- **Sowing** (requires crops in personal supply and an empty field):
  - Grain: place 1 from personal supply onto the field, add 2 from the general supply =
    **3 grain total in field**.
  - Vegetables: place 1 from personal supply onto the field, add 1 from the general supply =
    **2 vegetables total in field**.
  - In a single Sow action you may plant any number of empty fields; you are not required to plant
    every one.
- *Cannot sow a crop received the same turn (e.g. from Grain Seeds). It goes to personal supply
  first; sowing requires a specific Sow action from Grain Utilization, Cultivation, or a card.*
- **Field vs. field tile vs. field card.** "Field" is the umbrella term for both field *tiles*
  (placed on the board) and field *cards* (cards that identify themselves as fields, e.g.
  Beanfield). Field cards count as fields for prerequisites and crop-scoring, but **only field
  tiles score points in the Field-tiles category**.
- A field with ≥ 1 grain is a "grain field"; once you harvest its last grain it is no longer one
  (likewise for vegetables). An "unplanted" field has no harvestable crop; an "empty" field has
  literally nothing on it.
- Field phase of harvest: take exactly 1 crop from each planted field and move it to personal
  supply. Mandatory for all fields.

---

## Stables

- 4 stables per player. No adjacency requirement. Max 1 per cell (cell must be empty / not covered
  by a tile).
- *Stable cost is action-dependent:*
  - Farm Expansion: 2 wood per stable (from personal supply).
  - Card effects: as stated on the card.
- A stable inside a pasture becomes a "fenced stable" and doubles the pasture's capacity per
  stable; a standalone (unfenced) stable holds exactly 1 animal. Stables are built one at a time.

---

## Fences and Pastures

- 15 fence pieces per player. Each fence costs 1 wood from personal supply (on the Fencing action
  space). In a single action you can build as many fences as you can afford.
- Fences are placed on **fence spaces**: edges between adjacent cells, or on the farmyard boundary.
- **Validity**: a Build Fences action must place at least one new fence, and after the action every
  placed fence must be connected to other fences at both ends — i.e. all fences fully enclose one
  or more pastures (no incomplete pastures).
- **Enclosable cells**: fences may only enclose cells that are **empty or contain a stable**. Cells
  with rooms or fields cannot be enclosed (a Build Fences action that would enclose a room or field
  cell is illegal).
- *Room-tile and field-tile borders do NOT count as fences. Every side of every pasture requires
  explicit fence pieces from the player's supply.*
- Adjacent pastures share the fences bordering them. You may **subdivide** an existing pasture by
  building fences inside it.
- Fences cannot be demolished once placed.
- **Pasture adjacency**: the first pasture may be anywhere; every subsequent pasture must be
  orthogonally adjacent to an existing pasture. Subdivisions satisfy this trivially.

---

## Animals

### Accommodation
Animals must be accommodated on the farm — placed on the farmyard, not simply held in personal
supply. They live in **pastures** (the fenced enclosures from the previous section), in stables, or
as the single house pet.

**Capacity formula** for a pasture: `2 × num_cells_in_pasture × (2 ^ num_stables_in_pasture)` —
i.e. **2 animals per cell, doubled once for each stable built inside the pasture** (a pasture holds
at most one stable per cell).

Examples:
- 1×1, 0 stables → 2
- 1×1, 1 stable → 4
- 2×1, 0 stables → 4
- 2×1, 1 stable → 8
- 2×1, 2 stables → 16

**Standalone (unfenced) stable**: holds exactly 1 animal of any type.
**House pet slot**: exactly 1 animal of any type, always present.

*Each pasture holds exactly ONE type of animal. The same type may be split across multiple
pastures (e.g. 2 sheep in pasture A, 3 sheep in pasture B).*

### Gaining Animals from Accumulation Spaces
You must take ALL animals from the space (they come from the general supply via the accumulation
space). You must then accommodate them on the farmyard, convert them to food using a cooking
improvement — Fireplace or Cooking Hearth, defined in Major Improvements — or return excess to the
general supply. You cannot leave animals on the accumulation space.

### Free Rearrangement
*Animals are the only farm components that can be freely rearranged at any time. Rooms, fields,
fences, and stables are permanent once placed.* Animals can be discarded to the general supply at
any time.

### Breeding Phase
The Breeding Phase is the third sub-phase of the Harvest (see Harvest section). Fireplace and
Cooking Hearth referenced below are defined in Major Improvements.

- Breeding fires for each type where the player has ≥ 2 of that type AND capacity exists for the
  newborn. Newborns come from the general supply.
- **You cannot eat or exchange animals *during* the breeding phase.**
- *You CAN eat animals immediately before breeding to make room for newborns* — and you can eat or
  exchange animals again after breeding, before the next round or scoring begins.
- *Players must accommodate newborns on the farm. With insufficient space, they must forgo
  newborn(s) or release existing animals to the general supply for free.*
- At most 1 newborn per animal type per harvest.
- Parents do not need to be in the same pasture to breed.

---

## Primitive Sub-Actions

Most action spaces — and most cards — are not atomic. A single worker placement initiates one or
more **primitive sub-actions**: the small, reusable units by which a player actually changes the
game state. The same primitive shows up under many different action spaces and cards (for example,
both Farmland and Cultivation let you *plow*; both Grain Utilization and the Clay Oven let you
*bake bread*). A useful way to value a turn is to value each primitive it unlocks: an action space
is worth the sum of its primitives.

The primitives, by area:

**Farm development**
- **Plow a field** — place a new field tile on an empty, non-enclosed cell.
- **Build room(s)** — add rooms to your house (5 of your current house material + 2 reed each).
- **Build stable(s)** — place stables on empty cells.
- **Build fences** — enclose one or more cells to form a pasture (1 wood per fence).
- **Renovate** — upgrade your whole house one material step (wood→clay, then clay→stone).

**Crops**
- **Sow** — plant grain or vegetables from your supply onto empty fields.
- **Bake bread** — turn grain in your supply into food using a baking improvement.

**People**
- **Family growth** — add a newborn person (with a spare room, or — on the Urgent Wish for Children
  space — even without one).
- **Become starting player** — take the starting-player token.

**Cards**
- **Play an occupation** — put an occupation from your hand into play (paying its occupation cost).
- **Build a major / play a minor improvement** — put an improvement into play (paying its cost).

**Goods**
- **Take accumulated goods** — sweep all goods off an accumulation space.
- **Get fixed goods** — take the stated goods from a permanent space (e.g. 1 grain, 2 food).
- **Convert goods → food** — cooking (animals/vegetables), baking (grain), or crafting (building
  resources, once per harvest), at the rates set by your improvements. Convertible "at any time" or
  only "on a Bake Bread action," depending on the improvement.

**Harvest**
- **Harvest field** — take 1 crop from each planted field.
- **Feed** — pay food for each person.
- **Breed** — gain newborn animals for each type you have ≥ 2 of.

Many placements bundle several primitives, and the *ordering* between them follows the
"and/or" vs "and afterward" rule (see [Action Spaces](#andor-vs-and-afterward)).

---

## Action Spaces

### Accumulation Spaces
Action spaces marked with an ochre arrow are **accumulation spaces**. During each preparation
phase, the stated goods are taken from the general supply and placed on the space, stacking on top
of any goods already there from previous rounds. If the space was not used last round, goods
accumulate (e.g. Forest unused for 3 rounds has 9 wood on it).

When you place a person on an accumulation space, you **must take ALL goods** currently on it and
move them to your personal supply. You cannot leave goods behind (barring specific card effects).

Accumulation spaces in the 2-player game:

| Space | Accumulates | When available |
|---|---|---|
| Forest | +3 wood/round | Always |
| Clay Pit | +1 clay/round | Always |
| Reed Bank | +1 reed/round | Always |
| Fishing | +1 food/round | Always |
| Sheep Market | +1 sheep/round | Stage 1 |
| Western Quarry | +1 stone/round | Stage 2 |
| Pig Market | +1 boar/round | Stage 3 |
| Cattle Market | +1 cattle/round | Stage 4 |
| Eastern Quarry | +1 stone/round | Stage 4 |

All other action spaces are **permanent** (fixed effect each use, no accumulation) or **stage
card** spaces with fixed effects. (In the cardless variant, Meeting Place is also an accumulation
space at +1 food/round; in the full game it is not.)

### "And/or" vs. "And Afterward"
- **"And/or"**: either sub-action, or both in either order. Must do at least one.
  *Each sub-action category may be taken at most once within the action; you cannot return to a
  category after switching to the other (e.g., on Farm Expansion: rooms-then-stables or
  stables-then-rooms, but not rooms-then-stables-then-rooms).*
- **"And afterward"**: the first action is mandatory, the second optional (only available after
  the first). On Basic Wish for Children, you may not skip the family growth just to play the
  optional minor improvement.

*Cultivation ordering*: plowing first enables sowing the newly plowed field in the same action.

### All Action Spaces (2-player, full game)

| Space | Type | Effect |
|---|---|---|
| Farm Expansion | Permanent | Build Rooms (5 mat + 2 reed each) **and/or** Build Stables (2 wood each) |
| Meeting Place | Permanent | Become starting player (mandatory) **and afterward** play 1 minor improvement (optional) |
| Grain Seeds | Permanent | Get 1 grain from general supply |
| Farmland | Permanent | Plow 1 field |
| Lessons | Permanent | Play 1 occupation (first one free, each later one 1 food) |
| Day Laborer | Permanent | Get 2 food from general supply |
| Forest | Accumulation | Take all wood (+3/round) |
| Clay Pit | Accumulation | Take all clay (+1/round) |
| Reed Bank | Accumulation | Take all reed (+1/round) |
| Fishing | Accumulation | Take all food (+1/round) |
| Major Improvement | Stage 1 | Build 1 major **or** play 1 minor improvement |
| Fencing | Stage 1 | Build fences (1 wood/fence) |
| Grain Utilization | Stage 1 | Sow **and/or** Bake Bread |
| Sheep Market | Stage 1, Accum | Take all sheep (+1/round) |
| Basic Wish for Children | Stage 2 | Family Growth (room required) **and afterward** play 1 minor improvement (optional) |
| House Redevelopment | Stage 2 | Renovate **then** optionally build 1 major **or** play 1 minor improvement |
| Western Quarry | Stage 2, Accum | Take all stone (+1/round) |
| Vegetable Seeds | Stage 3 | Get 1 vegetable from general supply |
| Pig Market | Stage 3, Accum | Take all boar (+1/round) |
| Cattle Market | Stage 4, Accum | Take all cattle (+1/round) |
| Eastern Quarry | Stage 4, Accum | Take all stone (+1/round) |
| Urgent Wish for Children | Stage 5 | Family Growth even without room |
| Cultivation | Stage 5 | Plow 1 field **and/or** Sow |
| Farm Redevelopment | Stage 6 | Renovate **then** optionally Build Fences |

The stage card spaces enter play over the game: Stage 1 = rounds 1–4, Stage 2 = 5–7, Stage 3 = 8–9,
Stage 4 = 10–11, Stage 5 = 12–13, Stage 6 = round 14. Within a stage the order is shuffled, so the
exact round each space appears varies (e.g. Sheep Market arrives somewhere in rounds 1–4).

### Optional action spaces (not in the main game)

The game ships extra action-space tiles that the full 2-player game does **not** use. They are
listed here for completeness:

- **Side Job tile** — *for the cardless game only.* "Build exactly 1 stable (1 wood) **and/or**
  Bake Bread." Without hand cards, baking access is scarce, so this tile restores it. It is not
  part of the card game.
- **2-player additional tile** — an optional cluster of four spaces (Copse, Resource Market,
  Animal Market, Modest Wish for Children). When you place a person on the tile you choose exactly
  **one** of the four and use it; all four are then blocked for the rest of the round.
  - *Copse* — accumulation space, +1 wood (the others leave the wood on it).
  - *Resource Market* — get 1 stone and 1 food.
  - *Animal Market* — choose one: get 1 sheep + 1 food; or get 1 wild boar; or buy 1 cattle for
    1 food.
  - *Modest Wish for Children* — from round 5 on, Family Growth with room only.

  This tile *can* be added to a 2-player game (with or without cards), but the main game described
  here omits it.

---

## Major Improvements (all 10)

The 10 major improvements are available to all players from a shared supply board, claimed
first-come. They are built at the **Major Improvement** space (or, as a bonus, on **House
Redevelopment** after renovating). Each is worth points (shown in a yellow circle).

Two cards each appear twice in the table below — rows 0–1 are the two **Fireplaces** and rows 2–3
the two **Cooking Hearths**, genuine duplicate cards differing only in cost (one player may own
more than one). The food conversions shown are the *improved* rates: **grain and vegetables already
convert to food at 1:1 with no improvement at all** (see the note after the table), so an
improvement's worth is the *extra* food it yields.

| # | Name | Cost | Effect |
|---|---|---|---|
| 0 | Fireplace | 2 clay | *At any time*: sheep→2, boar→2, cattle→3, veg→2 food. *On Bake Bread*: grain→2 food. |
| 1 | Fireplace | 3 clay | Same as #0 |
| 2 | Cooking Hearth | 4 clay or return Fireplace | *At any time*: veg→3, sheep→2, boar→3, cattle→4. *On Bake Bread*: grain→3. |
| 3 | Cooking Hearth | 5 clay or return Fireplace | Same as #2 |
| 4 | Well | 3 stone + 1 wood | Places 1 food (from general supply) on each of next 5 round spaces; owner collects during prep |
| 5 | Clay Oven | 3 clay + 1 stone | *On Bake Bread*: exactly 1 grain → 5 food. Grants 1 free Bake Bread action upon purchase. |
| 6 | Stone Oven | 1 clay + 3 stone | *On Bake Bread*: up to 2 grain → 4 food each. Grants 1 free Bake Bread action upon purchase. |
| 7 | Joinery | 2 wood + 2 stone | Once per harvest: 1 wood → 2 food. End-game bonus: 3/5/7 wood → 1/2/3 pts (once only). |
| 8 | Pottery | 2 clay + 2 stone | Once per harvest: 1 clay → 2 food. End-game bonus: 3/5/7 clay → 1/2/3 pts (once only). |
| 9 | Basketmaker's | 2 reed + 2 stone | Once per harvest: 1 reed → 3 food. End-game bonus: 2/4/5 reed → 1/2/3 pts (once only). |

A single player may own both Fireplaces and both Cooking Hearths if they like. A Cooking Hearth is
an **upgrade** of a Fireplace: when taking a Major/Minor Improvement action you may return a
Fireplace you built to take a Cooking Hearth without paying extra (the returned Fireplace becomes
buildable again).

All food produced by major improvements comes from the general supply. Resources spent on end-game
bonuses leave personal supply and do NOT count toward the tiebreaker.

**Cooking rates summary** (animal/veg-to-food conversion, "at any time" mode):
- Cooking Hearth: sheep→2, boar→3, cattle→4, veg→3
- Fireplace: sheep→2, boar→2, cattle→3, veg→2
- Neither: sheep→0, boar→0, cattle→0, veg→1

**Grain and vegetables always convert to food at 1:1, at any time, with no cooking improvement
required** — this is the base rate. Cooking improvements only raise the *vegetable* rate (Fireplace
2, Cooking Hearth 3) and the *animal* rates, and enable *grain→food via Bake Bread*. Without a
cooking improvement, animals cannot be converted to food at all, but grain and vegetables still
convert at 1:1.

---

## Bake Bread Action

"Bake Bread" is an **action**, not just a capability. Having a baking improvement is not sufficient
on its own — you need both an action that grants "Bake Bread" and at least one baking improvement
(a Fireplace, Cooking Hearth, Clay Oven, or Stone Oven, defined in the previous section) to use it.

**Sources of a Bake Bread action:**
- Grain Utilization action space ("Sow and/or Bake Bread")
- Purchasing a Clay Oven or Stone Oven (one free action immediately on purchase)
- Various card effects (e.g. Threshing Board grants one on Farmland/Cultivation)
- The Side Job tile, in the cardless game

**During a Bake Bread action**, each of your baking improvements may activate once, in any order
you choose. Multiple improvements can all fire within a single action. The improvements are:
Fireplace, Cooking Hearth, Clay Oven, Stone Oven. Each states what it does "on a Bake Bread action"
in the Major Improvements table above.

**Fireplace and Cooking Hearth have two distinct modes:**
- *"At any time"*: convert animals and vegetables to food. No Bake Bread action required; can be
  done at any point during the game.
- *"On Bake Bread"*: convert grain to food. Requires a Bake Bread action.

Clay Oven and Stone Oven activate **only during** a Bake Bread action and convert grain only (no
animal or vegetable conversion).

---

## Cards: Occupations and Minor Improvements

Cards are what make each game of Agricola different. There are three types:

- **Occupations** (yellow) — passive abilities you play into your tableau. They have **no
  prerequisites** and **no printed victory points**; their value is the ongoing ability they grant.
- **Minor improvements** (orange) — one-time or ongoing effects you play into your tableau. They
  usually have a **prerequisite** (top-left) and a **cost** (top-right), and most are worth
  points.
- **Major improvements** (red) — the shared set of 10 (see [Major Improvements](#major-improvements-all-10)).

A played card's text always takes precedence over these general rules. While a card is in your
hand it does nothing; it only takes effect once played. You draw no extra cards during the game —
you play out of the 7 occupations + 7 minor improvements you drafted at setup (see
[Setup → the draft](#the-draft)).

### Playing occupations

Occupations are played at the **Lessons** action space, placing one occupation from your hand face
up in front of you. The **occupation cost** is food, and it ramps with how many occupations you
have already played:

- 2-player: the **first occupation is free**; each one after that costs **1 food**.

A few occupations also carry an **individual cost** printed on the card itself (rare, e.g. an extra
food payment); this is paid in addition to the occupation cost and, if it is food, can never be
removed. Some cards let you play an occupation without using Lessons (and state their own
occupation cost) or without placing a person at all.

### Playing minor improvements

A minor improvement is always one branch of a larger action; there is no standalone "play a minor"
space. You can play one when you take:

- **Major Improvement** (build a major *or* play a minor),
- **House Redevelopment** (renovate, then optionally a major *or* a minor),
- **Basic Wish for Children** (family growth, then optionally a minor),
- **Meeting Place** (become starting player, then optionally a minor).

Two requirements gate a minor improvement:

- **Prerequisite** (top-left): something you must *have* to play the card — never something you
  pay. Read each prerequisite as starting with "at least" unless it says "exactly" or "at most"
  (e.g. "2 Occupations" means ≥ 2). A prerequisite of "No X" means you may not have X *now*
  (whether you had it before doesn't matter). The required cards must be in front of you (played
  traveling cards don't count).
- **Cost** (top-right): goods you pay to play the card (usually building resources, sometimes a
  crop, food, or even an animal).

### Passing (traveling) minors

Some minor improvements are **traveling cards** (marked with a left-pointing arrow — they are
the lowest-numbered minor improvements, numbers 001–009, in each deck). When you play one, you
carry out its immediate effect and then
**pass it to the player on your left**, who takes it into their hand, rather than keeping it in
your tableau. Such a card stays in circulation indefinitely and can even be played more than once
in the same work phase by different players. Example: **Market Stall** (get 1 vegetable, then pass).

### Card categories

Every occupation and minor improvement belongs to one of eight categories (a thematic symbol on the
card), useful for comparing cards across decks:

| Category | What it tends to do |
|---|---|
| Farm Planner | Help develop the farmyard board |
| Actions Booster | Provide extra actions / flexibility |
| Points Provider | Worth a lot of points / bonus points |
| Goods Provider | Cards that fit several categories at once |
| Food Provider | Provide food (e.g. turning grain into food) |
| Crop Provider | Provide grain and vegetables |
| Building Resource Provider | Provide wood, clay, reed, stone |
| Livestock Provider | Provide sheep, wild boar, cattle |

### The card pool

The full Revised card pool spans **336 occupations and 336 minor improvements** (the base game plus
its expansions). Each card carries an ID — a deck letter plus a number, such as **A102** or
**B039** — used to reference it. Each occupation is also marked with a **minimum player count**:
**[1+]** (used at 1–4 players), **[3+]** (3–4 players only), or **[4]** (4 players only); cards
above your player count are removed before the draft. Minor improvements carry no player-count
marking and are used at all counts. A handful of cards are **banned from competitive play** for
being too strong or too disruptive.

### Card timing & terminology

These clarifications apply across the whole card system and are the ones most likely to bite:

- **The four timings.** Between any two consecutive things in the game flow (phases, rounds,
  actions, a space and its effect) there is an interim period with four ordered timing slots:
  **(1) "before" = immediately before** → **(2) the normal step** → **(3) immediately after** →
  **(4) after**. Card wording ("before", "immediately after", "at the end of") selects a slot, and
  "before"-cards resolve ahead of "after"-cards on the same step.
- **"Each time you use [an action space]" fires *before* the space's actions.** "Using" a space =
  *place the person*, **then** take its actions; the trigger fires at the comma — on the state as
  it was before the space's effect is applied. Cards meant to fire *after* say so explicitly
  ("immediately after each time you use…", "at the end of that turn").
- **A newly-played card's "each time" trigger only fires on *later* turns**, not the turn it was
  played.
- **"Another player" never includes you.** An effect that triggers on "another player" fires only
  when *some other* player meets the condition; an effect that means everyone says "any player
  (including you)" explicitly.
- **Prerequisite vs. condition.** A *prerequisite* must be met to **play** the card; a *condition*
  must be met to **use** its effect. They are distinct.
- **"Once" / "each time".** "Each time" means the effect happens every time its condition is met;
  an effect that triggers "once" may happen only a single time.
- **Slashes / "respectively".** "When you take clay/stone you also get 1 food/grain" correlates the
  options: clay→food, stone→grain. If a card lists "a/b/c" conditions giving "A/B/C", at most one
  condition holds at a time (a→A, b→B, c→C).
- **Collective terms.** *Wells* = improvements whose name ends "Well"; *Ovens* = name ends "Oven";
  *Fields* = field tiles plus field cards.
- **"On the next x round spaces."** If fewer than x rounds remain, place only on the remaining
  spaces. If you lose the card granting the goods, you lose your claim to them.
- You may **not** decline goods owed to you on a round space; you **may** decline an exchange
  offered there (but then cannot make it later).

### Example cards — the range of effects

Occupations and minor improvements recombine the same primitive sub-actions into an enormous
variety of effects. A representative sample, grouped by mechanic, with verbatim card text. (IDs and
costs/prerequisites are shown where they sharpen the example. Occupations marked [3+]/[4] are not
used at 2 players — included only to illustrate a mechanic.)

**Goods stores / metered purchases**
- **Grocer (A102, occupation)** — *"Pile the following goods on this card (wood, grain, reed,
  stone, vegetable, clay, reed, vegetable). At any time, you can buy the top good for 1 food."* A
  personal vending machine consumed top-first.
- **Clay Carrier (D122, occupation)** — *"When you play this card, you immediately get 2 clay. At
  any time, but only once per round, you can buy 2 clay for 2 food."* On-play bonus + a metered
  repeatable buy.

**Conversion / exchange engines**
- **Sheep Walker (B104, occupation)** — *"At any time, you can exchange 1 sheep for either 1 wild
  boar, 1 vegetable, or 1 stone."*
- **Hard Porcelain (B080, minor, cost 1 clay)** — *"At any time, you can exchange 2/3/4 clay for
  1/2/3 stone."* A rate-laddered upgrade.

**Novel scoring**
- **Organic Farmer (B098, occupation)** — *"During the scoring, you get 1 bonus point for each
  pasture containing at least 1 animal while having unused capacity for at least three more
  animals."*
- **Tutor (B099, occupation)** — *"During scoring, you get 1 bonus point for each occupation played
  after this one."*
- **Manger (A032, minor, cost 2 wood)** — *"During scoring, if your pastures cover at least
  6/7/8/10 farmyard spaces, you get 1/2/3/4 bonus points."*
- **Cow Prince (C134, occupation [3+])** — *"During scoring, you get 1 bonus point for each space
  in your farmyard (including rooms) holding at least 1 cattle."* A scoring rule unlike any base
  category.

**Per-action-space triggers (yours or an opponent's)**
- **Corn Scoop (A067, minor, cost 1 wood)** — *"Each time you use the 'Grain Seeds' action space,
  you get 1 additional grain."*
- **Pitchfork (B062, minor, cost 1 wood)** — *"Each time you use the 'Grain Seeds' action space, if
  the 'Farmland' action space is occupied you also get 3 food."* A conditional payout.
- **Milk Jug (A050, minor, cost 1 clay)** — *"Each time any player (including you) uses the 'Cattle
  Market' accumulation space, you get 3 food, and each other player gets 1 food."* A board-wide
  payout.
- **Fishing Net (C051, minor, cost 1 reed)** — *"Each time another player uses the 'Fishing'
  accumulation space, they must first pay you 1 food. Then, in the returning home phase of that
  round, place 2 food on 'Fishing'."* A toll on opponents.

**Granted sub-actions**
- **Threshing Board (A024, minor, cost 1 wood, prereq 2 occupations)** — *"Each time you use the
  'Farmland' or 'Cultivation' action space, you get an additional 'Bake Bread' action."*
- **Moldboard Plow (B019, minor, cost 2 wood, prereq 1 occupation)** — *"Place 2 field tiles on
  this card. Twice this game, when you use the 'Farmland' action space, you can also plow 1 field
  from this card."*

**Delayed payouts onto future round spaces**
- **Pond Hut (A044, minor, cost 1 wood, prereq exactly 2 occupations)** — *"Place 1 food on each of
  the next 3 round spaces. At the start of these rounds, you get the food."*
- **Wood Collector (C118, occupation)** — *"Place 1 wood on each of the next 5 round spaces. At the
  start of these rounds, you get the wood."* (The same mechanic as the Well major improvement.)

**Cost reducers**
- **Lumber Mill (A075, minor, cost 2 stone, prereq at most 3 occupations)** — *"Every improvement
  costs you 1 wood less."*
- **Forest School (A028, minor, cost 1 wood + 1 clay)** — *"You can consider the 'Lessons' action
  spaces not occupied. You can replace each food that an occupation costs with wood."* Changes the
  *currency* of a cost, not just the amount.

**Replacement / substitute actions**
- **Freshman (A097, occupation)** — *"Each time you get a 'Bake Bread' action, instead of taking
  the action, you can play an occupation without paying an occupation cost."* Lets you "use" a space
  even when you couldn't perform its normal action.
- **Agrarian Fences (B026, minor)** — *"Each time you use the 'Grain Utilization' action space, you
  can take a 'Build Fences' action instead of one of the two actions provided by the action space."*

**Rule-bending farm/field cards**
- **Beanfield (B068, minor, cost 1 food, prereq 2 occupations)** — *"This card is a field that can
  only grow vegetables."* A field card.
- **Wood Field (D075, minor, cost 1 food, prereq 1 occupation)** — *"You can plant wood on this
  card as though it were 2 fields, but it is considered 1 field. Sow and harvest wood on this card
  as you would grain."* Farming a building resource.
- **Shepherd's Crook (A083, minor, cost 1 wood)** — *"Each time you fence a new pasture covering at
  least 4 farmyard spaces, you immediately get 2 sheep on this pasture."*

**Placement-rule benders**
- **Lasso (B024, minor, cost 1 reed)** — *"You can place exactly two people immediately after one
  another if at least one of them uses the 'Sheep Market', 'Pig Market', or 'Cattle Market'
  accumulation space."* Take two turns back-to-back.

**Passive / start-of-round income**
- **Small-scale Farmer (B118, occupation)** — *"As long as you live in a house with exactly 2
  rooms, at the start of each round, you get 1 wood."*
- **Plow Driver (A090, occupation)** — *"Once you live in a stone house, at the start of each round,
  you can pay 1 food to plow 1 field."*
- **Scholar (B097, occupation)** — *"Once you live in a stone house, at the start of each round, you
  can play an occupation for an occupation cost of 1 food, or a minor improvement (by paying its
  cost)."* Plays cards without placing a person.
- **Paper Maker (B109, occupation)** — *"Immediately before playing each occupation after this one,
  you can pay 1 wood total to get 1 food for each occupation you have in front of you."*

**On-play one-shots**
- **Consultant (B102, occupation)** — *"When you play this card in a 1-/2-/3-/4-player game, you
  immediately get 2 grain/3 clay/2 reed/2 sheep."* A player-count-scaled gain.
- **Shifting Cultivation (A002, minor, traveling)** — *"Immediately plow 1 field. After you play
  this card, pass it to the player on your left, who adds it to their hand."*

---

## Board Geography

A handful of card effects depend not on *which* action space you use but on *where it physically
sits* on the board — "the four spaces above Fishing", "an action space orthogonally adjacent to
another occupied space", "round spaces 8 to 11", and so on. This section documents that physical
layout. It matters **only for cards**: no space used in the cardless game cares about position.

Keep this distinct from the **farmyard** (each player's own 3×5 grid of rooms/fields/pastures — see
[Farmyard](#farmyard)). Both have a geometry and some cards reference each; they are different
boards.

### The two board pieces

The physical board is two interlocking jigsaw pieces:

- **2-player main board** — every action space used in the 2-player game: the 14 numbered **round
  spaces** plus the block of **fixed (always-available) action spaces** to their left.
- **4-player extension** — a separate piece adding spaces used only at 3–4 players (Copse, Grove,
  Hollow, Resource Market, a second Lessons, Traveling Players). **Not used in the 2-player game.**

### Adjacency convention

"**Adjacent**" used alone always means **orthogonally adjacent** — sharing an edge (up / down /
left / right). A card only counts diagonals when it explicitly says "orthogonally *or diagonally*
adjacent". This convention holds for both the action board and the farmyard. Note that
**"above"/"below" ≠ "adjacent"**: a space can be above another (same column, higher up) without
being orthogonally adjacent to it — only the *immediately* neighboring space is adjacent.

### The action-board grid

The 14 **round spaces** (numbered 1–14) are where the stage cards get revealed — one per round.
Most sit in the stage columns (C–H of the grid below), but **round space 1 sits at the top of the
fixed column (Col B)**, above Forest — which is why the grid shows "Round 1" there rather than in a
stage column. ("Round 1" the *space* is distinct from "round 1" the *turn number*.)

The fixed spaces and round spaces share one 2-D grid, but **the cards are not all the same size**:
the round spaces (round space 1 included) are roughly **double the height** of the small fixed
cards. A round space therefore straddles *two* fixed-card rows, and adjacency is staggered — a tall
space can be orthogonally adjacent to *two* spaces in the column beside it.

To express this exactly, the grid below is drawn in **half-height "unit rows"** (a double-height
space occupies two consecutive unit rows; its name is repeated in both). The left columns are the
fixed spaces; the round spaces extend rightward, grouped by stage. Each **stage** owns a contiguous
run of round numbers, revealed onto its round space (Stage 1 = rounds 1–4, Stage 2 = 5–7, Stage 3 =
8–9, Stage 4 = 10–11, Stage 5 = 12–13, Stage 6 = round 14). Top unit row = top of board; a "—" is
empty board (no action space):

| unit row | Col A (fixed) | Col B (fixed) | Col C — Stage 1 | Col D — Stage 2 | Col E — Stage 3 | Col F — Stage 4 | Col G — Stage 5 | Col H — Stage 6 |
|---|---|---|---|---|---|---|---|---|
| 1 | Farm Expansion | Round 1 | Round 2 | Round 5 | Round 8 | Round 10 | Round 12 | Round 14 |
| 2 | Meeting Place | Round 1 | Round 2 | Round 5 | Round 8 | Round 10 | Round 12 | Round 14 |
| 3 | Grain Seeds | Forest | Round 3 | Round 6 | Round 9 | Round 11 | Round 13 | — |
| 4 | Farmland | Clay Pit | Round 3 | Round 6 | Round 9 | Round 11 | Round 13 | — |
| 5 | Lessons | Reed Bank | Round 4 | Round 7 | — | — | — | — |
| 6 | Day Laborer | Fishing | Round 4 | Round 7 | — | — | — | — |

A name spanning two unit rows (e.g. **Round 1** in rows 1–2, **Round 3** in rows 3–4) is one
double-height space; the six single-height fixed cards of Col A line up one-per-unit-row.

**At 3–4 players, an additional column of action spaces is added to the *left* of Col A** (the
4-player extension piece: Copse, Grove, Hollow, Resource Market, a second Lessons, Traveling
Players). The 2-player grid above is the right-hand piece in isolation.

The relationships cards actually rely on:

- **Round 1 is orthogonally adjacent to both Farm Expansion and Meeting Place** — the tall Round 1
  card spans both of their unit rows. Likewise **Round 3 is adjacent to both Forest and Clay Pit**,
  and **Round 4 to both Reed Bank and Fishing**.
- **Column B, top to bottom: Round 1 → Forest → Clay Pit → Reed Bank → Fishing.** The **four spaces
  above Fishing** are therefore Reed Bank, Clay Pit, Forest, and the **Round 1** space. "Above" ≠
  "adjacent": of those four, only Reed Bank is orthogonally adjacent to Fishing.
- **Fishing's three orthogonal neighbors** are exactly **Reed Bank** (above), **Day Laborer** (left,
  same unit row), and **Round 4** (right — the tall Round 4 spans Fishing's unit row). Fishing is
  the bottom-left corner, so it has no neighbor below.
- **Day Laborer and Lessons are orthogonally adjacent** (Col A, stacked).
- **Round spaces are addressable by number / band** — "round spaces 1/2/3/4", "round spaces 3 and
  6", "round spaces 8 to 11", "round space 14", etc.
- **Accumulation / market stage cards occupy round spaces**, so a market's board neighbors are
  whatever sits next to the round space it was revealed onto (the animal markets are Sheep = Stage
  1, Pig = Stage 3, Cattle = Stage 4).
- **Reveal order is itself a position** — "the most recently placed/revealed action space card" and
  "the card left of the most recently placed card" pick a space out by *when/where* it entered the
  board.

### Cards that reference board geography

These tables are **illustrative, not exhaustive** — they show the *kinds* of board-position
dependency cards rely on, with representative examples. Many more cards key off board geometry,
including whole families this sample omits — e.g. round-space *bands* ("round spaces 5–7", "8 to
11"), specific round-space slots ("round space 13/14"), and card reveal / fill order.

Action-board cards key off where a space sits:

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

Cards keyed to the **farmyard** geometry (each player's own 3×5 grid):

| Card | # | What it keys off |
|---|---|---|
| Summer House | D033 | unused farmyard cells **orthogonally adjacent to your house** |
| Lynchet | D063 | harvested fields **orthogonally adjacent to your house** |
| Petting Zoo | E011 | a pasture **orthogonally adjacent to your house** |
| Homekeeper | A085 | a room **adjacent to both a field and a pasture** |

---

## Harvest

There is a harvest at the end of rounds 4, 7, 9, 11, 13, and 14. Each harvest goes through three
sub-phases in order.

### Field Phase
Take exactly 1 crop from each planted field and move it to personal supply. Cannot skip any field.
Mandatory for all fields.

### Feeding Phase
- Each adult requires 2 food from personal supply. A newborn born in the round just ended (the
  round this harvest immediately follows) requires only 1 food. Newborns from earlier unharvested
  rounds — or from harvested rounds — count as adults and require 2 food.
- Grain and vegetables in personal supply (but not on fields) count as 1 food each and are removed
  from personal supply when used this way.
- With a Fireplace or Cooking Hearth: animals and vegetables can be converted to food at stated
  rates (the "at any time" mode); food tokens come from the general supply.
- Joinery, Pottery, and Basketmaker's Workshop can each convert 1 building resource to food once
  per harvest; food comes from the general supply.
- Shortfall: take 1 begging marker per missing food (−3 pts each at scoring).
- *You cannot withhold food tokens to intentionally over-beg — but you are never forced to convert
  goods into food: you may choose to take begging markers instead of cashing in goods.*

### Breeding Phase
See the [Animals → Breeding Phase](#breeding-phase).

---

## Scoring

The game ends after the round-14 harvest, and the player with the most points wins.

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
| Major improvement points | Fireplace/Hearth: 1; Clay Oven: 2; Stone Oven: 3; Well: 4; Joinery/Pottery/Basketmaker's: 2 |
| Craft building bonuses | 3/5/7 wood or clay → 1/2/3 pts; 2/4/5 reed → 1/2/3 pts (once only at scoring) |

**Card scoring.** Each major and minor improvement scores the value printed in its yellow circle
(only cards face up in front of you — not those in hand or discarded). **Occupations have no
printed points.** Some cards instead (or additionally) provide **bonus points** described in their
text; these are summed in the bonus-points category, from which card-text penalties and begging
markers are subtracted (the total can go negative). Goods on cards count toward the goods-scoring
categories only when the card states the goods belong to you (e.g. a field card or an animal-holding
card); goods held on a card as a future reward you have not yet earned do not count.

**Tiebreaker**: total building resources (wood + clay + reed + stone) in personal supply after
bonus spending. Food excluded. If still tied, the players share the rank.

---

## The Family Game (Cardless Variant)

The **Family game** (the rulebook's "Beginner's Variant without Hand Cards") is the full game
played **without occupation or minor-improvement hand cards**. It keeps the entire farm — the
farmyard, house, fields, animals, fences, harvest, major improvements, and scoring are all
identical — and only the card-driven parts change. It is the simpler game to teach and to reason
about, since the action set is fixed and fully public.

What changes relative to the full game:

- **No hand cards.** No occupations, no minor improvements, no draft. As a consequence:
  - **Lessons** is never usable (there are no occupations to play).
  - The optional "play a minor improvement" branch of **Major Improvement**, **House
    Redevelopment**, **Basic Wish for Children**, and **Meeting Place** is inert — those spaces
    offer only their major/renovate/family-growth/starting-player actions.
- **Meeting Place becomes a food accumulation space.** It accumulates **+1 food per round**;
  whoever uses it becomes starting player and collects the accumulated food. (In the full game it
  gives no food.)
- **The Side Job tile is added.** Because baking bread is otherwise hard to reach without cards,
  the Side Job tile is made available as a permanent action space: "Build exactly 1 stable (1 wood)
  **and/or** Bake Bread."
- Everything else — setup food (SP 2, others 3), the 14 action-space cards and their stages, the
  10 major improvements, harvests, and scoring — is unchanged.

The 2-player additional tile (Copse / Resource Market / Animal Market / Modest Wish for Children) is
an optional add-on and is not part of this variant as described here.

---

## 3- and 4-Player Games

The body of this document describes the **2-player game**. This section covers what changes at 3
and 4 players. Agricola is a **1–4 player** game; turn order, rounds (14, with harvests after
4/7/9/11/13/14), the family (start 2, max 5), the farmyard, fences, animals, harvest, scoring, and
the single shared set of 10 major improvements are all identical to the 2-player game.

### Extra action spaces on the board extension

More players mean more workers competing for spaces, so the board grows. A **game-board extension**
with extra action spaces attaches to the **left of Column A** (see [Board Geography](#board-geography)).
Which spaces are active and their yields depend on the player count:

| Extension space | 3-player | 4-player |
|---|---|---|
| Copse | — (not used) | Accumulation: +1 wood |
| Grove | Accumulation: +2 wood | Accumulation: +2 wood |
| Hollow | Accumulation: +1 clay | Accumulation: +2 clay |
| Resource Market | 1 food **and** (1 reed *or* 1 stone) | 1 reed, 1 stone, **and** 1 food |
| Lessons (extra) | Play 1 occupation (cost 2 food) | Play 1 occupation (cost 2 food; first **two** cost 1 each) |
| Traveling Players | — (not used) | Accumulation: +1 food |

A 3-player game adds 4 extension spaces (Grove, Hollow, Resource Market, the extra Lessons); a
4-player game adds all 6 (also Copse and Traveling Players, and bumps Hollow to +2 clay and broadens
Resource Market). The extra **Lessons** space is why a multi-player game has *two* Lessons spaces —
and the occupation-cost progression is **per-player across both** (your total number of occupations
played sets the cost, regardless of which Lessons space you use).

### The 3–4 player additional tile

The game ships two variant tiles — one for the 2-player game, one for the 3-/4-player game. The
**3–4 player tile** adds (place a person, choose one of the two):

- **Animal Market** — choose one: get 1 sheep + 1 food; or get 1 wild boar; or buy 1 cattle for
  1 food.
- **Modest Wish for Children** — from round 5 on, Family Growth with room only.

### Cards are filtered by player count

Every **occupation** is marked with a minimum player count, and you remove the cards above your
count before drafting:

- **[1+]** — used at 1–4 players (always in).
- **[3+]** — used at 3–4 players only.
- **[4]** — used at 4 players only.

So raising the player count *shuffles in more cards* (the [3+] then the [4] cards), widening the
pool. **Minor improvements carry no player-count marking** and are used at every count.

### What stays the same

- **Setup food** — the starting player gets **2 food**; **every other player gets 3 food**.
- **Turn order** — place exactly one person at a time, clockwise from the starting player,
  alternating until everyone has placed all their people (skip players who run out of people early).
- **Major improvements** — one shared set of 10 (two Fireplaces, two Cooking Hearths), claimed
  first-come.
- **Family, rounds, harvests, scoring categories, and all farm rules** are identical to the
  2-player game described above.
