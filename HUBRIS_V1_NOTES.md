# HubrisHeuristic V1 — Design Reference

> Comprehensive reference for the V1 evaluator: what each term does, why
> it exists in that shape, how its coefficients were chosen, what its
> known limitations are. Companion to `HEURISTIC_TUNING_PLAN.md`
> (forward) and to the code itself (`agricola/agents/heuristic.py`).
>
> Audience: a future session working on V1, V2, or a successor. Code
> docstrings cover *what* each function does; this doc covers *why*
> things look the way they look — the rationale that doesn't fit
> naturally in inline comments.

---

## 1. Orientation

**What V1 is.** HubrisHeuristic V1 is the current default evaluator for
the heuristic agent. It estimates a player's expected final score from
any mid-game state, scaled so the agent's `argmax` (or softmax) over
candidate actions picks reasonably-good moves. Used inside
`HeuristicAgent` with 1-turn lookahead (greedy rollout through the
decider's own subsequent decisions, then evaluate at handoff).

**Files.**

- `agricola/agents/heuristic.py` — `evaluate_hubris_v1`, `HeuristicConfig`,
  all term helpers.
- `agricola/agents/base.py` — `HeuristicAgent`, `_skip_singletons`,
  `_rollout_value`, `play_game`.
- `tests/test_agents_heuristic.py` — smoke tests + breeding-helper
  anchors.

**Try it.**

```bash
python play_heuristic_game.py --p0 hubris --p1 random 42
python play_web.py --seats hubris hubris   # AI-vs-AI in browser, step with Enter
```

---

## 2. Composition (high-level reasoning)

`evaluate_hubris_v1(state, player_idx, config)` is the sum of three
contribution groups:

1. **`score(state, player_idx)`** — the engine's end-of-game scoring
   function, applied to current state. Treated as a "what's already locked
   in" baseline. Includes leaves for pastures, fields, animals, crops,
   rooms-by-material, people, begging, major improvements, craft bonuses,
   unused cells.
2. **Major-improvement override.** We *subtract* `score()`'s major
   contribution and *add* `_hubris_major_value` instead. Score()'s
   printed-VP-only model under-values cooking implements (which unlock
   food conversion strategy worth far more than 1 printed point) and
   over-values having multiple cooking implements (printed VPs stack but
   strategic value doesn't). The override fixes both.
3. **Hubris-only additive terms.** Each addresses something `score()`
   can't see: future value of family members not yet contributing actions,
   anticipated value of empty rooms, future breeding opportunities given
   farm configuration, location bonuses for fields/pastures, anticipated
   sowing potential, context-aware resource value, starting-player
   priority, and the food/begging term.

The whole thing is a weighted sum of scalar terms. There is no learned
component — every coefficient is hand-picked (see
`HEURISTIC_TUNING_PLAN.md` for the plan to replace these with self-play
tuned values).

**Why a weighted sum?** Compositional with `score()`, transparent (each
term's contribution can be read off in isolation), and the natural
substrate for both 1-turn lookahead and an eventual MCTS rollout policy.
It does *not* model opponent behavior — opponent-aware play is out of
scope for V1.

**Why no opponent modeling?** With 1-turn lookahead the agent can't
influence the opponent's choices regardless. A "(my score) − (opponent
score)" objective collapses to "(my score) − constant" given the
opponent is deterministic from the agent's perspective. Real opponent
modeling needs 2-turn lookahead (predict opponent action) and is parked
until MCTS lands.

---

## 3. The terms, one by one

For each: **what** it does, **why** it exists, **shape** of the formula,
**magnitude** of the coefficients, **known limitations**.

### 3.1 Family-future value (`_hubris_family_value`)

**What.** Adds `rate × remaining-plays` for each family member beyond
the starting two. Plays counted as future rounds (every member) plus the
current round (only for members at home and able to act this round).
Newborns aren't in `people_home` (engine invariant — they can't be
placed in their birth round), so they correctly get only future plays.

**Why.** `score()` credits each person at +3 (a fixed end-of-game
contribution), but a family member also generates plays — each play
roughly contributes another 3-5 strategic points via accumulating
resources, building, sowing, etc. The +3 alone wildly under-values a
3rd family member added in round 4 (who'll play 10+ more times) vs. one
added in round 13 (who'll play once).

**Shape.** Per-ordinal rate (3rd = 2.5/round, 4th = 2.0, 5th = 1.5) ×
plays-remaining. Diminishing returns by ordinal because the marginal
value of an extra family member decreases with family size (more
contention for the same action spaces).

**Magnitude (2.5 / 2.0 / 1.5).** Calibrated to "each play of a person ≈
2-3 strategic points." A 3rd member born in round 5 contributes 2.5 ×
9 = 22.5 future-bonus + 3 score = 25.5 total — a meaningful but not
overpowering term.

**Limitations.** The at-home bonus uses `min(people_home, bonus_eligible)`
which generously assumes at-home members are bonus-eligible whenever
possible. Marginal mis-estimation when starters are at home but
bonus-members are placed.

### 3.2 Empty-room anticipation (`_hubris_empty_room_value`)

**What.** Each empty room (room cell with no occupant yet) credits
`3 + rate × rounds-room-will-be-occupied`. Anticipates the family member
that will eventually move in.

**Why.** Without this term, building a 3rd room before Family Growth is
revealed scores zero in the heuristic (wood rooms = 0 in `score()`,
empty room has no occupant yet). Strategically the room is +EV because
it enables a future family member. We need to credit that anticipation
*before* the family member exists.

**Shape.**
- Before `basic_wish_for_children` is revealed: room fills around the
  basic-wish round; rate is `empty_room_rate_pre_basic_wish` (2.5).
- After basic-wish is revealed: room fills ~2 rounds out; rate is the
  same default but uses a later fill-round.
- Both paths cap the fill round at 12 (members joining after round 12
  contribute little — the game ends round 14).

**Magnitude (2.5/round).** Matches the 3rd-family-member rate from
`family_per_round`. The +3 baseline matches the score()'s person
contribution.

**Limitations.** Assumes the room *will* be filled. If the player never
takes Family Growth, this is overcredit. In practice the agent's other
terms make taking Family Growth attractive once eligible, so this
self-fulfills.

### 3.3 Breeding-opportunity value (`_hubris_breeding_value`)

**What.** Counts breeding-opportunity slots — for each future harvest,
how many animal types can the farm hold 3+ of? — and credits a
per-slot rate based on whether the player has cookware (active rate
1.0) or could afford one (0.8) or can't (0.6). Members without 2+
animals of a type get the lower "passive" rate (0.3).

**Why.** Pastures' `score()` contribution caps at +4 (4+ pastures = 4
pts). But pastures enable breeding which compounds animal counts over
harvests. A 2×1 pasture that holds 4 cattle, breeds annually, is worth
far more than +1 pasture-pt suggests.

**Shape.**
- Farm config determines max breeding types via greedy assignment of
  pastures + flex slots (house + standalone stables) to types, taking
  the most types where each can reach 3 animals.
- Future harvests have known available types (sheep in harvest 1+,
  pigs in harvest 3+, cattle in harvest 4+).
- Per-harvest breed count = min(farm_opps, types_available).
- Active vs passive: "active" = player has 2+ of that type (could
  breed today); "passive" = future-potential. Active rate × cooking
  state + passive rate × (slots − active).

**Magnitude.** Active rates (1.0 / 0.8 / 0.6) are per-breed-per-harvest.
Passive (0.3) is small but nonzero to encourage having unfilled pastures
(future animal acquisition fills them). With 2 farm_opps × 4 active
harvests × 1.0 = +8, a serious animal strategy contributes ~10-15
hubris points beyond `score()`.

**Limitations.** Treats "possible" sheep/pig/cattle market availability
as available (user's "We will count possible opportunities as
opportunities"). Greedy assignment is optimal for typical pasture
arrangements; degenerate edge cases not exhaustively analyzed.

### 3.4 Unfenced stable value (`_hubris_unfenced_stable_value`)

**What.** +0.4/unfenced-stable in rounds < 9; 0 thereafter.

**Why.** Unfenced stables score 0 in `score()` (only fenced stables
score). But they're useful early as flex animal storage and as
infrastructure for future fence-building (a stable inside a pasture
doubles capacity). After round 9 the agent should either be fencing
them in (where they score via the fenced-stables leaf) or accepting
the sunk cost.

**Magnitude (0.4).** Small. Reflects the +1-animal capacity flex they
provide. Could plausibly be higher if we modeled them as a path to
fenced-stable bonus + breeding capacity expansion.

**Limitations.** Hard round-9 cutoff is arbitrary. A smoother decay
would be more principled.

### 3.5 Location bonuses (field + pasture)

**What.**
- Field on (0,1) / (0,2) / (1,1) / (1,2) — center 4 cells — gets +0.1.
- Pasture cell on any (r, c) with `c >= 2` — right 9 cells — gets +0.05.

**Why field-center.** Per user spec — fields in central cells are
slightly preferred (heuristic — encourages compact field clusters).

**Why pasture-right-half.** Per user spec — pastures on the right keep
the left columns clear for room expansion (rooms grow from the starting
positions at (1,0) and (2,0), and rooms must be empty + non-enclosed
cells). The right-half is the "out of the way" zone for pastures.

**Magnitude (0.1 fields, 0.05 pastures).** Both deliberately small —
these are tie-breakers among otherwise-similar placements, not
strategy-drivers.

**Limitations.** The bonus is location-only; doesn't consider
neighbor relationships (e.g., a pasture cell next to a planned room
might be worse than one far away).

### 3.6 Crop + plowed-field pair bonus

**What.** Each (crop in supply, plowed-empty-field) pair credits a
small bonus that decays by round: 0.6 (< round 12) / 0.4 (12-13) /
0.0 (round 14).

**Why.** Crops in supply are worth +2 each via the score-leaf
0→1 jump (and more via supply-veg/grain scoring), but their *full
utility* is realized when sown into a plowed field (1 supply grain
becomes 3 grain in field, scored higher). The pair bonus credits the
sowing-potential.

**Shape.** `min(crops, plowed_empty_fields) × rate`. The min reflects
"you need both a crop AND a field" — extra crops without fields, or
fields without crops, don't pair.

**Magnitude.** 0.6 early — modest, reflects only the *option* to sow
(actual sowing realizes a larger gain). Decays to 0 in round 14 (no
more harvests in which to realize the sown crop).

**Limitations.** Doesn't consider adjacency rules for field-tile
placement. Counts "plowed empty fields" only, not "cells that could be
plowed" — that earlier interpretation was a bug fixed during this arc.

### 3.7 Resource value with tiered context (`_hubris_resource_value`)

The most complex single term. Models each of wood/clay/reed/stone as a
piecewise function of count, with overlays for game state and stage.

**Why piecewise.** Linear-per-resource rates over-value hoarded
resources. Each resource has a "useful" amount (enough for a build) and
an "excess" amount (won't realistically be spent before game end). The
tier breakpoints model this.

**Wood (3 tiers).**
- Tier 1 (`wood_per_fence_owed` = 0.8): up to `min(wood_tier1_cap=6,
  fences_left)`. The "first 6 wood are most useful for fences."
- Tier 2 (`wood_secondary` = 0.5): next `wood_tier2_cap=5`. "Additional
  wood for stables / second pasture / fences."
- Tier 3 (`wood_excess` = 0.15): rest. "Hoarded — likely won't be
  spent."

The `min(6, fences_left)` cap ensures a player who's already built most
fences doesn't get tier-1 credit for *more* fence wood.

**Wood no-room-built overlay.** First 5 wood at 1.5 instead of 0.8.
Reflects the strategic priority of building the first room (which
costs 5 wood + 2 reed). Activates when the player still has only the 2
starting wood rooms.

**Wood: stage-1 multiplier.** All four resource categories are
multiplied by `stage1_resource_mult = 1.5` in rounds 1-4. With the
no-room-built bonus, first-5 wood in round 1 is worth `1.5 × 1.5 = 2.25
each` — Forest's 3-wood haul becomes +6.75. Calibrated so Forest is
clearly the best round-1 placement.

**Clay (2 regimes, tiered each).**
- No cookware owned: first 5 clay × 1.0 (incentivizes buying a Hearth),
  rest × 0.3.
- Cookware owned: first `num_wood_rooms` clay × 0.8 (renovation
  potential — 1 clay per wood-room to renovate), rest × 0.3.
- Pottery owner: additional `min(clay, 7) × 0.5` (caps at the actual
  end-game craft-bonus threshold).

**Reed (2 regimes).**
- No-room-built: 1st reed × 1.0, 2nd reed × 2.0 ("the 2nd reed
  completes the room cost"), rest × 0.7. The 1st < 2nd ordering is
  intentional — alone, 1 reed builds nothing; together, 2 reed
  completes the room.
- Room built: first 2 × 0.8, rest × 0.3.
- BMW owner: additional `min(reed, 5) × 0.5`.

**Stone (1 tier + excess).**
- First 5 × 0.8 (matches Well/Stone Oven/major costs), rest × 0.3.

**Stage-1 inflation / late-game decay.**
- Stage 1 (rounds 1-4): raw resource pts × 1.5 (`stage1_resource_mult`).
- Round 13: raw × 0.75.
- Round 14: raw × 0.5.
- Pottery/BMW bonuses are *not* affected by these multipliers — those
  bonuses model end-game craft conversion, which is time-independent.

**Why tier-magnitudes are what they are.** Each tier was calibrated so
the marginal value of a resource matches its strategic role:
- 0.8 ≈ "useful for building" — converts to a real game piece.
- 0.5 ≈ "useful but speculatively" — might be spent, might not.
- 0.15 / 0.3 ≈ "unlikely to be spent" — small standing value, mostly
  tiebreaker.

The exact numbers are hand-picked. Self-play tuning is expected to
shift these (per `HEURISTIC_TUNING_PLAN.md`).

### 3.8 Major-improvement override (`_hubris_major_value`)

REPLACES `score()`'s major-improvement contribution (we subtract `bd.
major_improvement_points` before adding this back).

**Why.** Score() uses printed VP per major, which under-values strategic
utilities. Examples:
- Fireplace prints 1 VP but unlocks all animal/veg conversion (worth
  several points across the game).
- Well prints 4 VP but also drops 5 food on future round spaces.
- Cooking Hearth prints 1 VP but provides strictly-better rates than
  Fireplace.

**Cooking-primary-only rule.** Only the player's *single best* cooking
implement gets the utility value:
- Hearth (always better than Fireplace) is primary if owned: rate 6 / 3
  / 1 by round bucket.
- Otherwise Fireplace primary: rate 4 / 2 / 1 by round bucket.
- Any redundant cooking implement (e.g., owning both Hearth and
  Fireplace) contributes only `cooking_secondary_vp = 1` printed VP.

Without this rule, a player owning Hearth + Fireplace gets credited
6 + 4 = 10 for "cooking utility" — but the Fireplace adds zero
additional cooking capability beyond the Hearth.

**Round-bucket decay (cooking).** The instrumental value of cooking is
captured by the food-conversion term; the bonus value here reflects
remaining cooking utility, which decays as game-end approaches:
- Rounds 1-11: full value.
- Rounds 12-13: half value.
- Round 14: just printed VP (1).

**Well.** Printed 4 VP + 0.4 per future food deposit (capped at 5 —
the Well places 5 food tokens at purchase). The +0.4 reflects per-food
realization across rounds; 0.4 × 5 = +2 max bonus on top of the 4.

**Ovens/Crafts.** Roughly printed VP each (2/3/2/2/2).

**Limitations.** Doesn't model owning a craft alongside its
craft-bonus tier (the bonus is in `_hubris_resource_value`, scaled
correctly, but the *interaction* between owning the craft and the
specific resource count isn't deeply modeled — a Pottery + 3-clay
player gets +1 from the bonus tier, which roughly matches reality).

### 3.9 Starting-player bonus (`_hubris_starting_player_bonus`)

**What.** +1.0 if the player holds the SP token.

**Why.** SP places first each round, which matters when an action space
is contested. Hard to quantify precisely but consistently nonzero.

**Magnitude.** 1.0. Slightly less than 2 placements (≈3-5 points
worth) since SP only matters when contention exists.

**Limitations.** Constant — doesn't depend on the board state (which
spaces are accumulating, whether opponents are likely to pick the same
spaces, etc.). A more sophisticated version would model contention.

### 3.10 Food + begging (`_food_term_hubris`)

The most strategically-loaded term and the one with the known V1-vs-V2
trade-off (see § 4).

**What.**
- Food in supply is credited at stage-dependent rates:
  - Stage 1: at-need = 1.0, excess = 0.5.
  - Stage 2: at-need = 0.75, excess = 0.5.
  - Stages 3-6: at-need = 0.6, excess = 0.3.
- "At-need" portion = `min(food, need)`; "excess" = `max(0, food − need)`.
- `need` = food owed at the next harvest (2 × people_total minus
  same-round newborn discount).
- Begging penalty applied when `food + convertibles < need`. Penalty per
  food short is bucket-keyed by moves-remaining-before-harvest:
  - 0 moves: −3 (cost of a begging marker).
  - 1-2 moves: −2.
  - 3-4 moves: −1.
  - 5+ moves: −0.5.

**Why stage-dependent.** Food in stage 1 is critical (first harvest
looms; resource conversion options are sparse). Food in stage 6 has
diminishing value beyond what's needed for the round-14 harvest.

**Why moves-keyed begging.** The penalty for a "future" food shortfall
depends on whether the player has opportunities to acquire food before
the harvest. With 5+ moves remaining, the shortfall is hypothetical;
with 0 moves left, it's certain begging.

**The convertible-shortfall calculation.** Convertibles
(`_max_convertible_food`) = grain × 1 + veg × veg_rate + sheep ×
sheep_rate + boar × boar_rate + cattle × cattle_rate (rates from
`cooking_rates`). The penalty fires only on the shortfall *after*
counting full convertibles.

**The double-count.** This is the known imprecision: convertibles
reduce the shortfall (and thus the penalty), but the goods themselves
also score at their full direct value via `score()`'s leaves. The
heuristic effectively counts each convertible good twice — once as
goods, once as food. V2 fixes this via `harvest_feed_frontier`'s joint
optimization — but loses head-to-head to V1 (see §4).

---

## 4. The V1-vs-V2 finding

V2 was implemented to fix the double-count above. It uses
`harvest_feed_frontier` to enumerate Pareto-optimal feeding strategies
and credits the maximum-value option (post-conversion goods score +
food + begging). Theoretically more correct.

**But V2 loses head-to-head to V1** (V2 vs V1: 6-13-1 in one 20-seed
sample; ~tied with slight V1 edge in others).

**Worked example.** Player has 5 sheep, 0 food, need 4 food, Fireplace.

- **V1:** `_score_sheep(5) = +2`. Convertibles = 10 ≥ 4 → shortfall = 0,
  no penalty. Total contribution from sheep + food/begging: +2.
- **V2:** Enumerates frontier. Best option = "convert 2 sheep → 4
  food, keep 3 sheep." `_score_sheep(3) = +1`, no begging. Total: +1.

V2 is *technically correct* — the realistic harvest outcome with 5
sheep + need=4 is to convert 2 sheep (yielding 3-sheep score). V1's
"+2" over-counts in this isolated decision.

**Why V1 plays better despite the bug.** In the Family game, food
shortfalls are rare. Players who plan their food acquisition rarely
need to convert animals/grain at all — they preserve goods through to
scoring. V1's "I have lots of goods AND no penalty" is wrong locally
but *empirically accurate* for the game's typical outcomes.

V2's "I'd convert 2 sheep at harvest" assumes the player will hit a
shortfall they don't actually hit. So V2 systematically under-values
animal/grain acquisition, leading to fewer goods at scoring time.

**Conceptual gap.** What we'd really want: max over (final-state goods
value, mid-game-conversion utility), weighted by the probability of
each. V1's "bug" approximates the no-conversion case; V2 approximates
the will-convert case. Neither weighs them.

**Decision (2026-05-22).** Keep V1 as the default Hubris. V2 is
available but opt-in. Future work might:
- Add a "will I actually convert?" weighting to V2's joint frontier
  (downweight conversions when food shortfall is unlikely).
- Tune V1's coefficients to compensate for the double-count without
  removing it.
- Try a blend (use frontier when in food trouble; use V1's optimism
  otherwise).

---

## 5. Deferred / rejected alternatives (with reasoning)

These were considered and dropped during V1's iteration. Future sessions
might propose the same ideas — this section records why we said no.

### 5.1 Renovation bonus (commented out, not deleted)

**Idea.** Credit each completed renovation step (Wood→Clay = 1,
Clay→Stone = 2) at a small bonus per step (0.75 in stages 1-4, 1.5 in
stages 5-6) to make renovation strictly +EV without globally lowering
clay/stone rates.

**Why proposed.** Renovation Wood→Clay (3 rooms): cost ≈ 3 clay × 0.8 + 1
reed × 0.8 = 3.2; gain = +3 score (clay rooms now score 1 each); net
≈ -0.2. Roughly EV-neutral. So the agent doesn't strongly prefer
renovating.

**Why deferred (user decision, 2026-05-22).** User wants to defer the
decision rather than land it now. The helper (`_hubris_renovation_bonus`)
and config fields (`renovation_bonus_per_step_*`) are kept in code; the
call in `evaluate_hubris_v1` is commented out. To re-enable: uncomment
one line.

**Alternative not implemented (rate-lowering).** An earlier attempt
lowered `clay_per_wood_room` 0.8 → 0.55 and `stone_value` 0.8 → 0.6.
This made renovation +EV but degraded clay/stone valuation globally.
Reverted in favor of the post-renovation-bonus approach (now itself
deferred).

### 5.2 Newborn family-value discount (rejected)

**Idea.** Newborn family members get `rounds_left - 1` plays (they
can't act in their birth round) vs. non-newborns getting `rounds_left`.

**Why proposed.** A 5th family member born in round 13 was being valued
at full rate × 1 round = 1.5 bonus + 3 score = 4.5, but can only act
in round 14 (one play). Looked like overvaluation.

**Why rejected (user reasoning).** Family Growth's opportunity cost
(the action that creates the newborn) is also a turn spent. The
asymmetry the discount tried to capture is already symmetric — the
"-1 play for being a newborn" is balanced by the "-1 play for the
parent's placement creating them."

**What V1 does instead.** Treats all bonus-eligible members uniformly
with `rate × rounds_future`, plus a current-round bonus for at-home
members (which newborns aren't in by engine invariant). The current
formula correctly distinguishes "can act now" from "future-only" without
needing a newborn-specific case.

### 5.3 Joint-frontier as the default (this is V2)

See §4. Theoretically correct, empirically worse. Available as V2; not
the default.

### 5.4 Resource-rate lowering for renovation EV (reverted)

See §5.1's "alternative not implemented" — same idea, same outcome.
Lowered clay/stone tier-1 rates to make renovation +EV; reverted in
favor of the post-state bonus.

---

## 6. Known limitations / failure modes

Items the assistant raised during the iteration as potential failure
modes, with status as of V1:

### Implemented

- **A. Pottery/BMW bonus unbounded.** Caps at `min(clay, 7)` for Pottery
  and `min(reed, 5)` for BMW. Matches actual end-game bonus thresholds.

- **F. Starting-player bonus.** +1.0 for SP-token holder.

### Partially addressed

- **D. Pasture cell-blocking.** Location bonus for pastures on the
  right 9 cells (favors keeping the left clear for rooms). Doesn't model
  neighbor relationships explicitly.

### Deferred (active issues)

- **Early grain/sheep grabs from score-leaf 0→1 jumps.** A 1-grain or
  1-sheep pickup gives +2 in `score()` (the 0→1 transition from −1
  to +1). The heuristic treats this as if it's the *final* state value,
  but in stage 1 the player will plausibly acquire 1 of these
  organically — the +2 is partly *anticipated* rather than *earned*.
  Addressed in `HEURISTIC_TUNING_PLAN.md` Thread C (stage-dependent
  score-leaf reweighting).

- **C. Renovation underpricing.** Renovation is roughly EV-neutral in
  the heuristic. See §5.1 — both proposed fixes (rate-lowering and
  post-state bonus) are available in code but inactive.

- **E. PlaceWorker(non-atomic) blind picking.** 1-turn lookahead
  largely mitigated this (post-PlaceWorker(Farm Expansion) state with
  no sub-actions still looks identical to do-nothing). The remaining
  issue: greedy 1-ply rollout inside the lookahead can pick a
  sub-optimal sub-action that anchors the overall turn-evaluation.

- **G. Craft bonus timing.** Agent might over-spend resources that
  would qualify for end-game craft bonuses. Low severity; ignored.

- **I. Turn-order traps.** "Two preferred moves, two turns, one is
  illegal for opponent." Requires opponent-modeling. Out of scope for
  V1.

- **J. Opp-modeling-free play.** Requires 2-turn lookahead. Punted to
  MCTS (item G in POSSIBLE_NEXT_STEPS.md).

### Other quirks

- **Cooking-implement decay's hard round-12 cutoff.** Smoother
  transition would be more principled; round-12 was easy to express.
- **`stage1_resource_mult` is binary** (rounds 1-4 = 1.5, rest = 1.0).
  Time-varying parameters (Thread B in tuning plan) would smooth this.
- **Empty-room cap at round 12.** Rooms first filled in round 13/14
  contribute little; capped to avoid valuing late-game family growth
  as if it were earlier.

---

## 7. Suggested entry points for future work

If you want to improve V1's *coefficient values*: see Thread A of
`HEURISTIC_TUNING_PLAN.md` (self-play tuning harness). The 50+ hand-picked
values in `HeuristicConfig` are the natural search space.

If you want to address the *shape* of the early-grain grab: see Thread C
(score-leaf reweighting by stage).

If you want to make individual coefficients *time-varying* (e.g. wood
value declining smoothly through the game): see Thread B.

If you want to re-attempt V2: see §4. The natural next step is adding a
"likelihood of actual conversion" weighting so V2 doesn't systematically
under-value goods that won't actually be eaten.

If you want to re-enable the renovation bonus: uncomment the one line in
`evaluate_hubris_v1`. See §5.1 for the reasoning that led to deferral.
