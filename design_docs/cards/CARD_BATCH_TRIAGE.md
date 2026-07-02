# Card Batch Triage — Artifex / Bubulcus Tier-1/2

_Triage of the Artifex and Bubulcus tier-1/2 cards, performed 2026-06-30._

**Counts (triage):** 70 implement / 15 defer (85 total, 85 returned).

This document drives implementation: each implement card's full `plan` and `ordering_note` are quoted verbatim. Defers are clustered by blocker group at the end.

---

## Reviewer revisions (2026-06-30)

After validating the triage against the engine code, the reviewer revised the split to **67 implement / 18 defer**:

- **A74 Stable Tree → DEFER.** Its text literally scopes the schedule to stables built "on your turn" and its clarification excludes off-turn builds (Groom B089 / Stable Planner A089) — the **same off-turn-build-exclusion** mechanism A43 Farmyard Manure is already deferred for. Grouped with A43 under `off_turn_build_exclusion`; a design plan (a card-local "is this build on my turn?" predicate — no `PendingPreparation` frame on the stack) will be brought to the user before implementing either.
- **A93 Bed Maker → DEFER** and **B92 Little Stick Knitter → DEFER.** Both push `PendingFamilyGrowth`, but a **card-granted Family Growth must place the newborn on NO action space** (per the rules). The engine's `_execute_family_growth` → `_resolve_wish_for_children` *forces* placing the newborn worker on a board space (`_update_space(space_id, workers=…)`), so there is no correct `initiated_by_id` for a card grant (a real space id mis-places the newborn and is read by worker-scanning cards; a `"card:…"` id `KeyError`s). Grouped under `card_granted_family_growth_no_placement`; plan: add a `place_on_space: bool = True` (card-only, default-skip) to `PendingFamilyGrowth` and skip the `_update_space` call when False. Bring to user, then implement both (the room-availability eligibility gate `people_total < 5 and people_total < _num_rooms(p)` in each spec is correct and reused).
- **B101 Furniture Carpenter → KEEP implement.** Reviewer initially suspected the `HarvestConversionSpec`/`side_effect_fn` route was a forced fit, but verified it is the **real designed mechanism** (the registry docstring names "Stone Sculptor +1 point per harvest"); the food→VP buy is surfaced as a discrete optional FEED-phase conversion. Defaulted "Joinery or an upgrade thereof" to **Joinery only (idx 7)** — see its section.
- **A103 Portmonger → KEEP implement, spec corrected** from cumulative to **banded** (take 1→veg, 2→grain, 3+→reed — one good by band), matching the codebase's slash-tier precedent. See its section.
- **B124 Trimmer → KEEP**, the per-work-phase `used_this_round` latch reading is confirmed correct by the verbatim text.

The remaining interpretation calls flagged for the user (do not block implementation; defaults chosen): **A103** banded vs cumulative; **B101** Joinery-only vs the {7,8,9} workshop family; **B5 Store of Experience** is deferred pending whether it is a passing/traveling minor.

---

## Implement (70)

### A99 Fellow Grazer

- **kind:** occupation
- **confidence:** high
- **template:** stable_architect.py
- **plan:** Copy stable_architect.py to fellow_grazer.py. CARD_ID = "fellow_grazer". _score(state, idx): return 2 * sum(1 for p in state.players[idx].farmyard.pastures if len(p.cells) >= 3). register_occupation("fellow_grazer", lambda state, idx: state)  # no-op on play. register_scoring("fellow_grazer", _score). Add the module import to cards/__init__.py. No cost/prereq/passing/vps overrides (occupation; played via Lessons).
- **ordering_note:** "Covering at least 3 farmyard spaces" = pasture size measured in CELLS, i.e. len(p.cells) >= 3, NOT capacity and NOT a stable/edge count. Stables inside the pasture do not change the cell count (they raise capacity, not coverage). Threshold is >= 3 (inclusive). VP is 2 PER qualifying pasture (multiply by 2, not a flat 2). Iterate farmyard.pastures (the BFS-derived enclosed components) — never cell_type, since a pasture is not a CellType and an empty fenced cell reads EMPTY.

### A101 Cookery Outfitter

- **kind:** occupation
- **confidence:** high
- **template:** stable_architect.py
- **plan:** Copy stable_architect.py shape. register_occupation("cookery_outfitter", lambda state, idx: state) (no-op on-play; played via Lessons). register_scoring("cookery_outfitter", _score) where _score(state, idx) = sum(1 for i in (0,1,2,3) if state.board.major_improvement_owners[i] == idx) — i.e. count owned Fireplaces (FIREPLACE_INDICES=(0,1)) + Cooking Hearths (COOKING_HEARTH_INDICES=(2,3)). Use FIREPLACE_INDICES + COOKING_HEARTH_INDICES from agricola.constants for clarity. No cost/prereq/vps/passing (occupation, played via Lessons).
- **ordering_note:** Majors live on state.board.major_improvement_owners (length-10 tuple, None=unowned else owner idx) — NOT on PlayerState; the scoring fn gets the full GameState so read state.board, exactly like scoring.py line 136. Count ONLY indices 0-3 (Fireplace x2 + Cooking Hearth x2); do NOT include Clay Oven (idx 5) or Stone Oven (idx 6).
- **errata:** clarifications field: "Ovens do not count towards this card." This DIRECTLY CONTRADICTS the prior agent's hypothesis (which counted clay/stone oven). Cooking improvements that count = Fireplace + Cooking Hearth ONLY. Excludes Clay Oven + Stone Oven. Impact: count major_improvement_owners indices {0,1,2,3}, never {5,6}.

### A105 Barrow Pusher

- **kind:** occupation
- **confidence:** high
- **template:** wall_builder.py
- **plan:** Occupation, on-play no-op: register_occupation("barrow_pusher", lambda state, idx: state). register_auto("after_plow", "barrow_pusher", _always, _apply) where _always = lambda state, idx: True and _apply adds Resources(clay=1, food=1) to the owner (owner-gated by default any_player=False, fires for the acting/plowing player only). No register_action_space_hook (after_plow is a sub-action host event, always emitted; not an atomic-space hook). No cost, no prereq, no vps, no passing. Add `from agricola.cards import barrow_pusher  # noqa: F401` to cards/__init__.py. Played via Lessons.
- **ordering_note:** Trigger on after_plow, NOT before_plow and NOT a Farmland/Cultivation action-space hook. The card grants per FIELD TILE, not per action: PendingPlow is a single-plow host that commits exactly one cell then flips to after-phase firing after_plow once, so a multi-field plow action (Cultivation, Mole Plow, etc.) pushes one PendingPlow per field and fires after_plow once per field — correct. Verified _execute_plow (resolution.py:1130) is the ONLY site creating a CellType.FIELD cell, so after_plow catches every field-tile acquisition exactly once; no non-plow path to a field tile exists in the implementable set. eligibility is unconditional (True): the event firing already means a field tile was just created, so there is nothing to gate. Prior hypothesis named corn_scoop.py as template — that is the WRONG template (it is a before_action_space atomic-space hook on grain_seeds); use wall_builder.py (occupation + register_auto after a build sub-action).

### A117 Wood Carrier

- **kind:** occupation
- **confidence:** high
- **template:** consultant.py
- **plan:** register_occupation("wood_carrier", _on_play). In _on_play(state, idx): n_minor = len(p.minor_improvements); n_major = sum(1 for owner in state.board.major_improvement_owners if owner == idx); count = n_minor + n_major; p = fast_replace(p, resources=p.resources + Resources(wood=count)); write player back via the consultant.py tuple idiom. No cost, no prereq, no vps, no passing, no scoring term, no triggers. Wood is a building resource (no accommodation concern). If count == 0 the grant is a harmless +0.
- **ordering_note:** "Improvements in front of you" = minor improvements PLUS major improvements, and EXCLUDES occupations. CRITICAL: majors are NOT a PlayerState field — the prior hypothesis's `major_improvements` does not exist. Minor count is len(p.minor_improvements); major count must be derived from the BOARD: sum(1 for owner in state.board.major_improvement_owners if owner == idx) (the established idiom in scoring.py:227 / harvest_conversions.py:78). Do NOT count p.occupations. Wood Carrier is itself an occupation, not an improvement, so it never counts itself; the count is read at play time (after it has entered the tableau, but it's not an improvement so this is moot).

### A122 Pan Baker

- **kind:** occupation
- **confidence:** high
- **template:** wood_cutter.py
- **plan:** register_occupation("pan_baker", lambda s, i: s)  # no on-play effect.
register_auto("before_action_space", "pan_baker", _eligible, _apply).
_eligible(state, idx): return state.pending_stack[-1].space_id == "grain_utilization" (2-arg AutoEntry signature; the grain_utilization parent frame's space_id is "grain_utilization", confirmed via PendingGrainUtilization.initiated_by_id="space:grain_utilization").
_apply(state, idx): add Resources(clay=2, wood=1) to player idx via fast_replace (mirror wood_cutter._apply exactly).
NO cost, prereq, vps, or passing (all empty per card data). NO register_action_space_hook call.
- **ordering_note:** grain_utilization is a NON-atomic space, so unlike the wood_cutter template DO NOT call register_action_space_hook (that index only governs whether ATOMIC spaces get a host frame). _initiate_grain_utilization always pushes PendingGrainUtilization and fires apply_auto_effects("before_action_space", ...) at the push (resolution.py:326), so the auto already fires. Timing: "each time you use" = BEFORE phase, which is correct here and order-irrelevant since +clay/+wood is independent of the space's own sow/bake effects (same rationale wood_cutter documents). Eligibility MUST read state.pending_stack[-1].space_id (uniform across hosts), not an isinstance check.

### A65 Seed Pellets

- **kind:** minor
- **confidence:** high
- **template:** drill_harrow.py
- **plan:** register_minor("seed_pellets", cost=Cost(), prereq=_three_fields) where _three_fields counts grid cells with cell_type==CellType.FIELD >= 3 (the ash_trees.py grid-iteration idiom, but no "planted" requirement — just 3 field tiles). _eligible(state, idx) -> always True (every implemented sow is unconditional; copy drill_harrow's note). _apply(state, idx): p.resources + Resources(grain=1), rebuild players tuple. register_auto("before_sow", "seed_pellets", _eligible, _apply). No vps, no passing, no on_play effect (the hook IS the effect). Add import to cards/__init__.py.
- **ordering_note:** Use register_auto (mandatory, choice-free), NOT register — the grant is free with no downside, so it must apply directly at the hook, never surface as an optional FireTrigger. Use the before_sow SUB-ACTION event (drill_harrow), NOT corn_scoop's grain_seeds action-space hook (grain_seeds is the "get 1 grain" space, a different action entirely). The grant fires BEFORE the sow's own effect — correct per "before you take" wording — and fires once per PendingSow push, covering both Grain Utilization and Cultivation automatically.

### A121 Clay Puncher

- **kind:** occupation
- **confidence:** high
- **template:** geologist.py
- **plan:** register_occupation("clay_puncher", on_play=_grant_clay) where _grant_clay adds Resources(clay=1) to player idx. register_auto("after_action_space", "clay_puncher", _eligible, _grant_clay) with _eligible = state.pending_stack[-1].space_id in {"lessons","clay_pit"}. register_action_space_hook("clay_puncher", {"clay_pit"}) ONLY (clay_pit is atomic and needs a host frame; lessons is non-atomic / already hosted by PendingSubActionSpace, which shares PENDING_ID "action_space" + a space_id property and reaches _enter_after_phase -> fires after_action_space). No cost/prereq/vps/passing (occupation). The same _grant_clay serves on_play and the auto.
- **ordering_note:** MUST be the AFTER phase, not before: the text says "each time AFTER you use" (explicit "immediately after" exception to the trigger-timing ruling) — register_auto on "after_action_space", NOT "before_action_space" as the prior hypothesis stated. The clarification "1+1=2 clay when played on Lessons" emerges automatically and must NOT be special-cased: playing the card via Lessons runs on_play (+1 clay, card now owned) during _execute_play_occupation, THEN the Lessons host flips to its after-phase and fires after_action_space, whose eligible auto grants +1 more = 2 total. Hook only clay_pit (atomic); hooking lessons would be redundant/incorrect since it is already a PendingSubActionSpace host.
- **errata:** Clarification field present: "Gives 1+1=2 clay when played on Lessons." Impact: confirms the on_play grant AND the after_action_space hook both fire on a same-turn Lessons play; this is produced for free by the on_play(+1) + owned-card after-hook(+1) composition — no extra code. No behavior-changing errata.

### A8 Food Basket

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** CARD_ID="food_basket". _on_play(state,idx): p=players[idx]; p=fast_replace(p, resources=p.resources+Resources(grain=1,veg=1)); return _update_player(state,idx,p). _prereq(state,idx): n_minor=len(p.minor_improvements); n_major=sum(1 for o in state.board.major_improvement_owners if o==idx); return (n_minor+n_major)>=2. register_minor("food_basket", cost=Cost(resources=Resources(reed=1)), min_occupations=2, prereq=_prereq, passing_left=True, vps=0). Add import to cards/__init__.py.
- **ordering_note:** TWO subtleties the prior hypothesis got wrong. (1) This is a TRAVELING/passing card — JSON passing_left='X' (same marker as the implemented Market Stall B8, which is passing_left=True in code), so it MUST be passing_left=True, NOT a kept consultant-style card. The on_play still fires for passing minors (resolution.py runs spec.on_play 'whether kept or passed'), so +1 grain +1 veg is applied then the card is handed to the opponent's hand_minors (never added to the owner's minor_improvements). (2) The prereq '2 Improvements' must count BOTH minor_improvements AND owned major-improvement slots (majors live on BoardState.major_improvement_owners, not on PlayerState); '2 Occupations' is min_occupations=2. prereq_met is checked at legality time before the card is played, so the card never counts toward its own prereq.

### A57 Milking Parlor

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** register_minor("milking_parlor", cost=Cost(resources=Resources(wood=2)), prereq=_at_least_4_unused, vps=1, on_play=_on_play). _at_least_4_unused: count cells that are CellType.EMPTY AND not in helpers.enclosed_cells(fy) over the 3x5 grid (inverse of big_country._all_farmyard_spaces_used); require count>=4. _on_play: s=p.animals.sheep, c=p.animals.cattle; sheep_food = 4 if s>=4 elif 3 if s>=3 elif 2 if s>=1 else 0; cattle_food = 4 if c>=3 elif 3 if c>=2 elif 2 if c>=1 else 0; p=fast_replace(p, resources=p.resources+Resources(food=sheep_food+cattle_food)); splice player back. No register_scoring needed (vps=1 handled by the registry). Pure food grant — no animal accommodation concern.
- **ordering_note:** The two clauses are INDEPENDENT and ADDITIVE ("the same applies" = a second separate bonus), and the two threshold ladders DIFFER: sheep 1/3/4→2/3/4 food, cattle 1/2/3→2/3/4 food. Evaluate each ladder top-down (highest threshold first) so the correct band is picked, then SUM the two food amounts. "Unused farmyard spaces" must count fenced-but-empty pasture cells as USED (cell_type stays EMPTY but the cell is enclosed) — use enclosed_cells, not cell_type alone (big_country's documented trap).

### A7 Gardener's Knife

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** register_minor("gardeners_knife", cost=Cost(resources=Resources(wood=1)), on_play=_on_play). _on_play walks the 3x5 grid: g_fields = count of cells where cell_type==CellType.FIELD and cell.grain>0; v_fields = count where cell_type==FIELD and cell.veg>0. p = fast_replace(p, resources=p.resources + Resources(food=g_fields, grain=v_fields)); splice player back into state. No prereq, no passing (passing_left=False default), vps=0. Copy market_stall.py's player-splice idiom and the grid-walk idiom from scoring.py lines 163-185.
- **ordering_note:** Count a "grain field" / "vegetable field" by what is SOWN on it (cell.grain>0 / cell.veg>0), NOT by cell_type alone. A field is FIELD-typed whether or not it is sown; an unsown field (grain==0 and veg==0) counts as NEITHER. A sown field holds grain XOR veg (never both — _execute_sow fills grain=3 OR veg=2 per cell), so the two counts never overlap. Verbatim text gives food per grain-field and grain per veg-field — do not transpose.

### A6 Storage Barn

- **kind:** minor
- **confidence:** high
- **template:** consultant.py
- **plan:** register_minor("storage_barn", on_play=_on_play) — no cost (cost=null), no prereq, no vps, NOT passing (passing_left defaults False). _on_play(state, idx): for each (major_idx, Resources) in [(4, Resources(stone=1)), (7, Resources(wood=1)), (8, Resources(clay=1)), (9, Resources(reed=1))], if state.board.major_improvement_owners[major_idx] == idx, add that resource to p.resources. Accumulate into one Resources delta, then fast_replace the player tuple (Consultant idiom). No register_scoring, no triggers — pure immediate on-play.
- **ordering_note:** The grant keys on BOARD ownership: state.board.major_improvement_owners[idx] == player_idx (a length-10 tuple, None=on supply), NOT a PlayerState.major_improvements set (which does not exist). The four major indices are Well=4, Joinery=7, Pottery=8, Basketmaker's Workshop=9 (from constants.py MAJOR_IMPROVEMENT_COSTS ordering) → stone/wood/clay/reed respectively. Double-check the index→resource mapping is correct since the card lists majors and resources in different orders (well→stone, joinery→wood, pottery→clay, basketmaker→reed). The "1 each max" clarification is automatic (a major is owned 0 or 1 times per player in 2p), so no dedup needed.
- **errata:** Clarification (not behavior-changing in 2p): "You may only get 1 of each resource even with multiple copies" — irrelevant here since 2p has exactly one copy of each major and ownership is 0/1. "Applies to the 10 major improvements" just confirms these are the standard majors. No mechanical impact on the implementation.

### A51 Drift-Net Boat

- **kind:** minor
- **confidence:** high
- **template:** canoe.py
- **plan:** New module agricola/cards/drift_net_boat.py copying canoe.py. CARD_ID="drift_net_boat", SPACES=frozenset({"fishing"}). _eligible(state,idx): state.pending_stack[-1].space_id in SPACES. _apply(state,idx): add Resources(food=2) to player idx via the two fast_replace idiom. register_minor("drift_net_boat", cost=Cost(resources=Resources(wood=1, reed=1)), vps=1) — NO prereq, NO min_occupations, not passing. register_auto("before_action_space", CARD_ID, _eligible, _apply). register_action_space_hook(CARD_ID, SPACES). Add the import to cards/__init__.py.
- **ordering_note:** Fire in the before_action_space phase, NOT after: the text is a bare "each time you use [space]" with no "immediately after", so per the trigger-timing ruling it fires BEFORE the space's own catch (same phase as Canoe/Herring Pot). The end state coincides either way for a pure income grant, but use before_action_space to match the ruling. Use register_auto (mandatory, choice-free — never surfaced as a FireTrigger), because +2 food is a downside-free pure-goods grant, not an optional/choice effect. register_action_space_hook is REQUIRED — fishing is an atomic accumulation space (in FOOD_ANIMAL_ACCUMULATION_RATES), so without the hook no host frame is pushed and before_action_space has nothing to fire on.

### A42 Forest Lake Hut

- **kind:** minor
- **confidence:** high
- **template:** canoe.py
- **plan:** Copy canoe.py. CARD_ID="forest_lake_hut"; SPACES=frozenset({"fishing","forest"}). _eligible(state,idx): state.pending_stack[-1].space_id in SPACES. _apply(state,idx): read sid=state.pending_stack[-1].space_id; grant Resources(wood=1) if sid=="fishing" else Resources(food=1) (sid=="forest") — per-space mapping is the only deviation from Canoe. register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2)), vps=1) (no prereq, not passing). register_auto("before_action_space", CARD_ID, _eligible, _apply); register_action_space_hook(CARD_ID, SPACES). Add import to cards/__init__.py.
- **ordering_note:** The paired-slash text "Fishing/Forest ... 1 wood/food" is a CROSSED mapping: Fishing -> +1 WOOD, Forest -> +1 FOOD (not fishing->food/forest->wood). _apply must branch on space_id and grant the OTHER element's resource. Both spaces hooked, but the granted good differs per space.

### A52 Throwing Axe

- **kind:** minor
- **confidence:** high
- **template:** canoe.py
- **plan:** register_minor("throwing_axe", cost=Cost(resources=Resources(wood=1)), prereq=lambda s,i: s.round_number >= 7, vps=0). SPACES=frozenset({"forest"}) (the only wood accumulation space; BUILDING_ACCUMULATION_RATES["forest"]=Resources(wood=3)). _eligible(state,idx)->bool: state.pending_stack[-1].space_id in SPACES and get_space(state.board,"pig_market").accumulated_amount >= 1. _apply: add Resources(food=2) to player idx. register_auto("before_action_space", "throwing_axe", _eligible, _apply); register_action_space_hook("throwing_axe", SPACES) (forest is atomic — must be hosted so a frame exists). No passing, no on_play.
- **ordering_note:** Two subtleties. (1) "A wood accumulation space" resolves to exactly ONE space here, forest — it is the only entry whose accumulated resource contains wood; do NOT also fire on clay_pit/quarries/reed_bank. (2) The condition reads the BOAR on the Pig Market accumulation space, i.e. get_space(board,"pig_market").accumulated_amount (an int, since pig_market is in FOOD_ANIMAL_ACCUMULATION_RATES) — NOT the player's owned boar; threshold is >=1. Use register_auto (eligibility sig is (state,idx), no triggers_resolved) since the +2 food is mandatory, choiceless, and has no downside, matching Canoe; before/after is immaterial to the value but "each time you use" canonically = before_action_space.

### A77 Hod

- **kind:** minor
- **confidence:** high
- **template:** milk_jug.py
- **plan:** register_minor("hod", cost=Cost(resources=Resources(wood=1)), on_play=_on_play). _on_play: owner.resources + Resources(clay=1) (rammed_clay shape). register_auto("before_action_space", "hod", _eligible, _apply, any_player=True). _eligible(state, idx): return state.pending_stack[-1].space_id == "pig_market". _apply(state, idx): add Resources(clay=2) to players[idx] ONLY (no opponent gain — unlike milk_jug). No register_action_space_hook (pig_market is non-atomic, already hosted via PendingPigMarket). No prereq, vps=0, not passing.
- **ordering_note:** Two subtleties: (1) any_player=True is required so the owner's +2 clay fires even on the OPPONENT's Pig Market turn; idx passed to apply is the OWNER (per apply_auto_effects routing), so add clay to players[idx] only — do NOT copy milk_jug's "other player gets food" branch (Hod gives nothing to the active/other player; the boar from pig_market still goes to the active player via normal resolution). (2) Fires on the before_action_space phase per the "each time you use [space]" ruling (SPACE_HOST_REFACTOR.md §11.1), matching milk_jug — not after.

### A47 Trellises

- **kind:** minor
- **confidence:** high
- **template:** pond_hut.py
- **plan:** register_minor("trellises", cost=Cost(resources=Resources(wood=1)), on_play=_on_play) — no prereq, no vps, not passing. _on_play(state, idx): R = state.round_number; n = fences_built(state.players[idx].farmyard) (from agricola.helpers); return schedule_resources(state, idx, range(R+1, R+1+n), Resources(food=1)). schedule_resources clamps slots outside 1..14, so it naturally yields min(fences_built, remaining rounds). No trigger/hook needed — the entire effect is at play; collection happens automatically via future_resources at each round's start in _complete_preparation.
- **ordering_note:** N = fences_built(farmyard) counts placed FENCE PIECES (sum of horizontal+vertical fence arrays), not pastures — this is the card's literal "fences you have built." Read it at play time (on_play), and use range(R+1, R+1+N): the next N round spaces starting one round after the current round_number. If N==0 the card legally schedules nothing (empty range) — fine, not illegal. The "up to ... next round spaces" cap on remaining rounds is handled for free by schedule_resources' 1..14 slot clamp; do NOT separately min() against remaining rounds.

### A74 Stable Tree

- **kind:** minor
- **confidence:** high
- **template:** shepherds_crook.py (after_build_stables register_auto) + sack_cart.py/thick_forest.py (schedule_resources for next-N round spaces)
- **plan:** register_minor("stable_tree", cost=Cost(resources=Resources(wood=1))) — no prereq, vps=0, not passing. register_auto("after_build_stables", "stable_tree", _eligible, _apply). _eligible(state, idx): return not isinstance(state.pending_stack[0], PendingPreparation) — ON-TURN gate (see ordering_note); the after-phase is only reached via Proceed (num_built>=1), so reaching it already guarantees >=1 stable built, no count check needed. _apply(state, idx): R = state.round_number; return schedule_resources(state, idx, [R+1, R+2, R+3], Resources(wood=1)) (the helper clamps rounds >14, so it auto-implements "the next 3 round spaces"). Collection is the existing _collect_future_rewards at each round start (future_resources slots) — no new infra. Register in cards/__init__.py.
- **ordering_note:** THE off-turn caveat is load-bearing and the prior hypothesis missed it. The card's clarification "Stables built off-turn (Groom B089 / Stable Planner A089) do NOT trigger" is real because Groom (IMPLEMENTED) pushes the SAME PendingBuildStables host at start_of_round, firing after_build_stables. So eligible=True would wrongly fire off-turn. Discriminator must be ON-TURN vs OFF-TURN, NOT card-pushed vs space-pushed: an off-turn (Groom) build runs under a PendingPreparation host at the stack BASE (stack = [PendingPreparation, PendingBuildStables], phase==WORK), whereas every on-turn build (Side Job, Farm Expansion, AND Mining Hammer-via-after_renovate) has a worker-placement/renovate parent at the base. Crucially Mining Hammer's stable IS on-turn and SHOULD count, so a naive "initiated_by_id starts with card:" gate is WRONG (it would exclude Mining Hammer). Correct gate: not isinstance(state.pending_stack[0], PendingPreparation), checked in _eligible where the frame is readable (after_build_stables autos fire while PendingBuildStables is still top, frame at base intact). Also: after_build_stables fires ONCE per build action (at Proceed/_enter_after_phase), never per-stable — so building 3 stables in one action schedules ONE set of 3 wood (not 9), matching "1 or more stables".
- **errata:** Clarification present and load-bearing: "Stables built off-turn, e.g. with Stable Planner A089 or Groom B089, do not trigger this card." Impact: drives the on-turn eligibility gate (not isinstance(pending_stack[0], PendingPreparation)) — without it the card over-fires when the owner uses Groom's start-of-round stable build.

### A46 Claw Knife

- **kind:** minor
- **confidence:** high
- **template:** herring_pot.py
- **plan:** register_minor("claw_knife", cost=Cost(resources=Resources(wood=1)), prereq=lambda state, idx: len(state.players[idx].farmyard.pastures) == 1). _eligible(state, idx): return state.pending_stack[-1].space_id == "sheep_market". _apply(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R+1, R+3), Resources(food=1)) (R+1..R+2 = next 2 round spaces). register_auto("before_action_space", "claw_knife", _eligible, _apply). NO any_player ("each time YOU use"). NO register_action_space_hook — sheep_market is non-atomic and self-hosts via _initiate_sheep_market, which itself fires apply_auto_effects("before_action_space"); the hook index only gates ATOMIC-space hosting (verified vs milk_jug.py's cattle_market precedent).
- **ordering_note:** Event MUST be before_action_space, NOT after (the prior hypothesis's error). "Each time you use [space]" fires in the BEFORE phase per the governing ruling, and the engine only ever fires before_action_space on this space: _initiate_sheep_market pushes PendingSheepMarket then calls apply_auto_effects(state, "before_action_space", ap). schedule_resources clamps rounds outside 1..14, so late-game uses (e.g. round 14) silently drop out-of-range slots — correct ("each REMAINING round space"). The "Exactly 1 Pasture" prereq is a PLAY-TIME gate (consumed via prereq_met in legality.py), NOT a per-use trigger condition: once played the sheep_market trigger fires unconditionally regardless of later pasture count. Pasture count = len(farmyard.pastures) (the canonical decomposition tuple), never a cell_type scan.

### A45 Fire Protection Pond

- **kind:** minor
- **confidence:** high
- **template:** clay_hut_builder.py
- **plan:** register_minor("fire_protection_pond", cost=Cost(resources=Resources(food=1)), prereq=lambda state, idx: state.players[idx].house_material == HouseMaterial.WOOD, on_play=lambda state, idx: state) — on_play is a no-op (the schedule is the latch fire). register_conditional("fire_protection_pond", _condition, _apply): _condition = state.players[idx].house_material != HouseMaterial.WOOD; _apply = schedule_resources(state, idx, range(R+1, R+7), Resources(food=1)) where R = state.round_number ("next 6 round spaces" = R+1..R+6, schedules.py clamps past/over-14 slots). No vps, not passing. Add import to cards/__init__.py.
- **ordering_note:** The window is a FIXED 6 rounds — range(R+1, R+7) — NOT "each remaining round space" (range(R+1,15)) as Manservant/Clay Hut Builder's wording differs; copy clay_hut_builder's range pattern but use R+7 (6 rounds) and food=1. The prereq "Still in Wooden House" (== WOOD) means play is only legal while wooden, so the latch never fires at play-time (condition != WOOD is false then); it always fires later via a renovate, where _fire_ready_one_shots (resolution.py:1320) re-checks. Slots past round 14 are silently dropped by schedule_resources — correct per "next 6" being clamped to the game length.

### A76 Cob

- **kind:** minor
- **confidence:** high
- **template:** groom.py
- **plan:** register_minor("cob", cost=Cost(resources=Resources(food=1)))  # no prereq, vps=0, passing_left=False.
register("start_of_round", "cob", _eligible, _apply); register_start_of_round_hook("cob").
_eligible(state, idx, triggers_resolved): p=state.players[idx]; return CARD_ID not in p.used_this_round and p.resources.clay >= 1 and p.resources.grain >= 1.
_apply(state, idx): p=state.players[idx]; p=fast_replace(p, resources=p.resources + Resources(grain=-1, clay=2, food=1), used_this_round=p.used_this_round | {CARD_ID}); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). Add import line to cards/__init__.py.
- **ordering_note:** Eligibility must require BOTH clay >= 1 (the verbatim "if you have at least 1 clay" gate — a real check even though the exchange GIVES clay) AND grain >= 1 (you spend exactly 1 grain). The prior hypothesis only checked grain; dropping the clay>=1 condition would be wrong. FIRE applies the swap directly (no pending push) and must latch used_this_round so it fires at most once per round; the host's Proceed is the decline path (do not make it register_auto — "you can" is optional).

### A89 Stable Planner

- **kind:** occupation
- **confidence:** high
- **template:** handplow.py
- **plan:** on_play: R=state.round_number; schedule_effect(state, idx, (R+3, R+6, R+9), "stable_planner") — schedules the deferred grant onto future_rewards (no immediate goods). register_occupation("stable_planner", _on_play). _eligible(state,idx,triggers_resolved): _scheduled_slot(p, state.round_number) is not None AND _can_build_stable(state, p, Resources()) (free). _apply: consume ONLY the current round's slot (remove "stable_planner" from future_rewards[round-1].effect_card_ids, exactly Handplow's slot-edit), then push(state, PendingBuildStables(player_idx=idx, initiated_by_id="card:stable_planner", cost=Resources(), max_builds=1)). register("start_of_round", "stable_planner", _eligible, _apply). Do NOT call register_start_of_round_hook — hosting is schedule-driven (has_scheduled_round_start_effect), like Handplow, so it only hosts on R+3/R+6/R+9. No cost/prereq/vps/passing (occupation, played free via Lessons).
- **ordering_note:** Per-round slot consumption: _apply must strip the card id from ONLY the entered round's future_rewards slot (via _scheduled_slot(p, round_number)), never all three — so each of R+3/R+6/R+9 independently surfaces its own optional free-stable grant, fires at most once, and the later grants survive. The grant is OPTIONAL (host's Proceed = decline), and eligibility must gate on a free stable being actually buildable (_can_build_stable with zero cost) so it never offers a dead-end. The build is at-no-cost (Resources()), max_builds=1.
- **errata:** Two clarifications. (1) "At the start of these rounds (not earlier)" — confirms it is a deferred start-of-round grant, not playable when the occupation is played; the schedule_effect-on-R+3/6/9 model captures this exactly. (2) "Stables built this way are not built on your turn and do not trigger Stable Tree A074 or Farmyard Manure A043." NO live impact today: neither Stable Tree nor Farmyard Manure is implemented, so there is no after_build_stables automatic effect that the pushed PendingBuildStables could spuriously fire. The pending's build_stables_action skip-field is currently only a canonical marker (no trigger reads it). The implementer should add a code comment flagging that when those two cards are implemented they must gate on whose-turn / off-turn-ness (not fire on this card's push). Sibling Groom (B89, named in the same clarification) already builds stables off-turn via the identical start_of_round→PendingBuildStables path without setting build_stables_action=False.

### A15 Carpenter's Axe

- **kind:** minor
- **confidence:** high
- **template:** ox_goad.py
- **plan:** register_minor("carpenters_axe", cost=Cost(resources=Resources(wood=1))) (cost 1 wood, no prereq, no vps, not passing). register("after_action_space", CARD_ID, _eligible, _apply) + register_action_space_hook(CARD_ID, {"forest"}) (forest is atomic → needs the hook to host the after-phase; Wood Cutter/Ox Goad confirm). _eligible(state, idx, triggers_resolved): CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id == "forest" AND state.players[idx].resources.wood >= 7 AND _can_build_stable(state, players[idx], Resources(wood=1)). _apply: push(state, PendingBuildStables(player_idx=idx, initiated_by_id="card:carpenters_axe", cost=Resources(wood=1), max_builds=1)). No on_play effect (omit / default _noop).
- **ordering_note:** The ≥7-wood test must read the wood AFTER the forest pickup. The text says "after you use ... if you THEN have at least 7 wood", and the engine guarantees this: for an atomic space hosted by PendingActionSpace, Proceed runs ATOMIC_HANDLERS["forest"] (adds 3 wood) FIRST, then _enter_after_phase flips to the after-phase where the after-trigger eligibility is evaluated (engine.py L622-631). So eligibility's resources.wood >= 7 sees the post-pickup supply. The ≥7 is a HAVE-check prerequisite (not consumed); the stable's 1-wood cost is separately gated by _can_build_stable(..., Resources(wood=1)). "Each time" = once per use, enforced by `CARD_ID not in triggers_resolved` (NOT used_this_round — it may fire on every forest use), exactly as Ox Goad.

### A66 Feeding Dish

- **kind:** minor
- **confidence:** high
- **template:** canoe.py
- **plan:** register_minor("feeding_dish", cost=Cost(resources=Resources(wood=1))) — no prereq, no vps, not passing.
register_auto("before_action_space", "feeding_dish", _eligible, _apply). NO register_action_space_hook: the three markets are NON-atomic (NONATOMIC_HANDLERS) so they always push a host frame and fire before_action_space from _initiate_*_market (like Milk Jug, unlike Canoe's atomic Fishing).
_eligible(state, idx): map top.space_id -> required animal field {sheep_market:sheep, pig_market:boar, cattle_market:cattle}; return False if space_id not one of the three, else getattr(state.players[idx].animals, field) >= 1.
_apply(state, idx): +1 grain to player idx via fast_replace (resources + Resources(grain=1)). Add to cards/__init__.py.
- **ordering_note:** The "while already having an animal of that type" check must read the player's CURRENT animal count at before-fire time, which is the PRE-PURCHASE count: _initiate_*_market stages the bought animals on the pending's `gained` field (NOT on the player) and fires before_action_space BEFORE CommitAccommodate moves them onto the player — so state.players[idx].animals correctly reflects holdings before this market use. Two subtleties: (1) it is per-SPACE-type, not "any animal" — at Sheep Market a player owning only cattle gets nothing, so match the animal field to the space, never check total animals; (2) threshold is >=1 of that specific type. before (not after) is mandated by the "each time you use a space" ruling and confirmed by the Animal Dealer A147 clarification (its buy-extra-animal effect resolves before Feeding Dish's check).
- **errata:** Clarification on card: "Animal Dealer A147's effect can be used before this." Animal Dealer is a 3+ player occupation (out of 2-player scope), so the interaction never arises here. Its only impact is confirming the BEFORE-phase ordering: Feeding Dish evaluates the pre-purchase animal count, which the before_action_space timing already yields. No behavior change for the 2-player implementation.

### A104 Wood Harvester

- **kind:** occupation
- **confidence:** high
- **template:** scythe_worker.py (firing wiring) + mushroom_collector.py (the get_space board-read idiom)
- **plan:** register_occupation("wood_harvester", lambda s,i: s)  # no on-play effect. register_auto("harvest_field", CARD_ID, _eligible, _apply); register_harvest_field_hook(CARD_ID). WOOD_SPACES = {"forest"} (the only wood accumulation space, per mushroom_collector/shifting_cultivator). _apply: w = get_space(state.board, "forest").accumulated.wood; gain = Resources(wood=1) if w==2 else Resources(food=1) if w>=3 else Resources(); if no gain return state else credit p.resources. _eligible: return get_space(state.board,"forest").accumulated.wood >= 2 (else no-op). No cost/prereq/vps/passing (occupation). NOTE the prior hypothesis mislabeled this a minor — it is an OCCUPATION, so register_occupation not register_minor.
- **ordering_note:** The text is the Agricola slash-template: "1 wood/1 food ... exactly 2 wood/at least 3 wood" = TWO parallel clauses — (1 wood per wood-accum-space with EXACTLY 2 wood) and (1 food per wood-accum-space with AT LEAST 3 wood). exactly-2 and ≥3 are mutually exclusive, so a single space yields at most one of {1 wood, 1 food}. With only `forest` as a wood accumulation space (2-player board, reused in cards mode), the whole effect collapses to: read forest.accumulated.wood → ==2 gives +1 wood, >=3 gives +1 food, <2 gives nothing. Read forest.accumulated.wood (the Resources field), NOT accumulated_amount (that scalar is for food/animal spaces). Don't accidentally OR the clauses into +1 wood +1 food.

### A106 Slurry Spreader

- **kind:** occupation
- **confidence:** high
- **template:** scythe_worker.py
- **plan:** Module slurry_spreader.py. register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect (played via Lessons). register_auto("harvest_field", CARD_ID, _eligible, _apply) + register_harvest_field_hook(CARD_ID). _eligible(state,idx): any FIELD cell with grain==1 or veg==1 in players[idx].farmyard.grid. _apply(state,idx): food = 2*(count FIELD cells grain==1) + 1*(count FIELD cells veg==1); credit p.resources + Resources(food=food); return rebuilt state. NO grid mutation — Slurry only reads (the mechanical take in _resolve_harvest_field removes the crop). cost/prereq/vps/passing: none (occupation, no cost — played via Lessons). Confirm AUTO_EFFECTS signature register_auto(event, card_id, eligibility_fn, apply_fn) (verified).
- **ordering_note:** "Last grain/vegetable from a field" = a field whose count is exactly 1, because the mechanical take removes exactly 1 crop/field this harvest, emptying it. So the threshold is grain==1 -> +2 food, veg==1 -> +1 food, read BEFORE the take (which is exactly when the harvest_field hook fires — fields still sown). Do NOT credit fields with grain>=2 (their last grain isn't taken this harvest). Grain takes precedence over veg in the mechanical take, but a field is sown with only one crop, so grain==1/veg==1 are mutually exclusive per cell. Subtle interaction: if a player also owns Scythe Worker, Scythe (also a harvest_field auto) fires first per registration order and may reduce a 2-grain field to 1 grain; reading field counts at Slurry's own fire time then correctly counts that field as grain==1 and awards +2 — rules-correct (Scythe's extra take + the mechanical take together empty the field). Reading live grid state (not a pre-snapshot) in _apply is therefore required and is what makes this correct regardless of import/registration order.

### A107 Catcher

- **kind:** occupation
- **confidence:** high
- **template:** wood_cutter.py
- **plan:** register_occupation(CARD_ID, no-op on_play). register_auto("before_action_space", CARD_ID, _eligible, _apply). register_action_space_hook(CARD_ID, BUILDING_SPACES) where BUILDING_SPACES=frozenset(BUILDING_ACCUMULATION_RATES) (forest, clay_pit, reed_bank, western_quarry, eastern_quarry) — these are ATOMIC so the hook is REQUIRED to host the frame. _eligible(state,idx): sid=state.pending_stack[-1].space_id; if sid not in BUILDING_SPACES return False; n_placed = p.people_total - p.people_home (this placement already decremented people_home — see plow_hero); required = {1:5, 2:4, 3:3}.get(n_placed); if required is None return False (4th/5th never trigger); acc=get_space(state.board,sid).accumulated; count = acc.wood+acc.clay+acc.reed+acc.stone; return count == required. _apply: p.resources + Resources(food=1). No cost/prereq/vps/passing (plain Lessons-played occupation, players 1+).
- **ordering_note:** The paired threshold is the trap: the goods count required is a FUNCTION of which person you place this round, not a constant — 1st person→exactly 5, 2nd→exactly 4, 3rd→exactly 3, and 4th/5th person never fire. It is EXACTLY-equal (==), not >=. Read the goods count BEFORE the space's own pickup (before_action_space fires before the space effect — Wood Cutter/Milk Jug/plow_hero all confirm), so the accumulated pile is read at full. n_placed = people_total - people_home is correct because before_action_space fires AFTER _apply_worker_placement decrements people_home for the placing worker (plow_hero derivation; robust to same-round newborns since a wish consumes a worker too). Count building resources as acc.wood+acc.clay+acc.reed+acc.stone (the Resources on a building accumulation space is purely building resources; never read accumulated_amount, which is 0 here).

### A113 Heresy Teacher

- **kind:** occupation
- **confidence:** high
- **template:** corn_scoop.py
- **plan:** Occupation, on_play = default no-op (whole effect is the hook). register_occupation("heresy_teacher", _noop). register_auto("before_action_space", "heresy_teacher", _eligible, _apply). _eligible(state,idx): state.pending_stack[-1].space_id == "lessons" (PendingSubActionSpace.space_id strips "space:" → "lessons"; lessons is already a hosted host frame, so NO register_action_space_hook). _apply(state,idx): rebuild the active player's Farmyard.grid — for each cell with cell_type==CellType.FIELD and grain>=3 and veg==0, set veg=1 (fast_replace the Cell), reassemble grid tuple, fast_replace Farmyard then the player then players tuple. No cost/prereq/vps/passing.
- **ordering_note:** Firing is BEFORE the space's effect (before_action_space), NOT after — the prior hypothesis's "after_action_space" is WRONG. The card text "Each time you use a Lessons action space" lacks the "immediately after" qualifier, so by the governing ruling it fires in the before-phase. (Behaviorally the before/after distinction is near-invisible here since Lessons' own effect is playing the occupation, but use before_action_space to honor the ruling and match corn_scoop.) Per-field condition is the literal "grain>=3 AND veg==0"; a field with any veg already fails veg==0 and is correctly skipped.
- **errata:** Clarification present: "Fields with both crops can count as a grain field or a vegetable field, but not both simultaneously." Verbatim-confirmed via card_text.py. Impact: NONE on this card's algorithm — the literal "no vegetable" (veg==0) test already excludes any field carrying veg, so a mixed grain+veg field never qualifies. The clarification governs categorizing mixed fields for OTHER counting effects, not this per-field test. No behavior change.

### A72 Calcium Fertilizers

- **kind:** minor
- **confidence:** high
- **template:** canoe.py
- **plan:** register_minor("calcium_fertilizers", cost=Cost(), prereq=_no_field_tiles, vps=0). prereq _no_field_tiles(state,idx): zero FIELD cells in farmyard.grid. register_auto("before_action_space", CARD_ID, _eligible, _apply); register_action_space_hook(CARD_ID, frozenset({"western_quarry","eastern_quarry"})). _eligible(state,idx): state.pending_stack[-1].space_id in QUARRY_SPACES. _apply(state,idx): for each grid[r][c] with cell_type==CellType.FIELD and exactly one of (grain>0, veg>0) true, add +1 to that same crop count (grain-only field +1 grain, veg-only field +1 veg); rebuild grid -> Farmyard -> PlayerState -> GameState via fast_replace. No cost, no vps, not passing.
- **ordering_note:** "Single type of crop" = a FIELD cell with EXACTLY ONE of {grain>0, veg>0} (XOR). A field with grain=0 and veg=0 is NOT planted (skip); a field with BOTH grain>0 and veg>0 is growing two types (skip — can occur via Cultivation sowing both). "Respective type" means add to the crop the field already grows, never the other. The crops live on Cell.grain/Cell.veg (NOT player.resources). Use before_action_space ("each time you use" = before-phase ruling), though here it is mechanically harmless since the quarry only yields stone and the effect only touches fields. register_auto (not register) because it is a guaranteed-beneficial grant with no choice/downside — never surface a FireTrigger. Note the apparent prereq/effect tension (you may PLAY it only with zero fields, yet it rewards fields) is intentional and coherent: prereq is a play-time have-check; the effect benefits fields plowed/sown later.

### A68 Asparagus Gift

- **kind:** minor
- **confidence:** high
- **template:** shepherds_crook.py
- **plan:** register_minor("asparagus_gift", cost=Cost(), vps=0, prereq=_one_unplanted_field). prereq: >=1 FIELD cell with grain==0 and veg==0 (read grid like strawberry_patch.py; Cell has .grain/.veg). before_build_fences (register_auto, eligible=lambda s,i:True): snapshot scalar n = helpers.fences_built(p.farmyard) into card_state.set(CARD_ID, n). after_build_fences (register_auto, eligible=True): delta = fences_built(p.farmyard) - card_state.get(CARD_ID, 0); if delta >= state.round_number: p.resources += Resources(veg=1); then reset card_state.set(CARD_ID, 0). No cost/passing/vps; veg always fits so register_auto (no FireTrigger, no accommodation).
- **ordering_note:** The threshold is on the count of fence PIECES (edges) built in ONE build_fences action (fences_built = sum of horizontal_fences + vertical_fences), NOT pastures/area — compute it once as the before/after delta over the whole action (the build-X-is-one-action ruling), never per pasture commit, and compare delta >= state.round_number. The grant is a FIXED 1 vegetable per qualifying action (not 1 per fence over the threshold). Snapshot a scalar count, not the pasture/cell set. Fires identically via the Fencing space and Farm Redevelopment Overhaul (both push PendingBuildFences). card_state defaults to 0 so Family stays byte-identical.

### A81 Interim Storage

- **kind:** minor
- **confidence:** high
- **template:** geologist.py (accumulation hook) + scullery.py (start_of_round release)
- **plan:** register_minor("interim_storage", cost=Cost(resources=Resources(food=2))) — no prereq/vps, not passing.
ACCUMULATE: register_action_space_hook("interim_storage", {clay_pit, reed_bank, western_quarry, eastern_quarry}); register_auto("before_action_space", id, eligible_accum, apply_accum). eligible_accum: state.pending_stack[-1].space_id in those 4 spaces. apply_accum: map space→good (clay_pit→Resources(wood=1); reed_bank→Resources(clay=1); western_quarry/eastern_quarry→Resources(reed=1)); cur = p.card_state.get("interim_storage", Resources()); p = fast_replace(p, card_state=p.card_state.set("interim_storage", cur+gain)).
RELEASE: register_start_of_round_hook("interim_storage"); register_auto("start_of_round", id, eligible_rel, apply_rel). eligible_rel: state.round_number in {7,11,14} and bool(p.card_state.get("interim_storage", Resources())). apply_rel: held = card_state.get(...); p = fast_replace(p, resources=p.resources+held, card_state=p.card_state.set("interim_storage", Resources())).
- **ordering_note:** Two subtleties. (1) The good mapping is a PARALLEL list, not "same good": clay accumulation space→1 WOOD, reed space→1 CLAY, stone space→1 REED (down a tier each). Stone = BOTH western_quarry AND eastern_quarry (the only stone spaces). (2) Release is gated on entering rounds 7/11/14 and at that point round_number is ALREADY the new round (engine._complete_preparation increments round_number at line 981 BEFORE _fire_preparation_hook fires the start_of_round autos), so `state.round_number in {7,11,14}` is correct. "Move ALL goods" = release everything then RESET the store to Resources() (empty), so accumulation restarts for the next window (8–11, 12–14). before_action_space is the right event per the "each time you use" ruling, matching the Geologist precedent; timing vs the space's own take is irrelevant since goods come from supply onto the card, not from the space.

### A31 Debt Security

- **kind:** minor
- **confidence:** high
- **template:** stable_architect.py
- **plan:** Module agricola/cards/debt_security.py, CARD_ID="debt_security". Define _score(state, idx): n_majors = sum(1 for o in state.board.major_improvement_owners if o == idx); fy = state.players[idx].farmyard; enclosed = enclosed_cells(fy); unused = sum(1 for r in range(3) for c in range(5) if fy.grid[r][c].cell_type is CellType.EMPTY and (r,c) not in enclosed); return min(n_majors, unused). Then register_minor(CARD_ID, cost=Cost(resources=Resources(food=2))) (on_play defaults to no-op; vps=0; not passing) and register_scoring(CARD_ID, _score). Add import to cards/__init__.py.
- **ordering_note:** Two precise points: (1) majors are NOT a PlayerState field — the prior hypothesis's len(major_improvements) is WRONG; count from state.board.major_improvement_owners (length-10 tuple of owner idx). (2) "unused" must use the engine's exact rule (scoring.py L194-199): cell_type == EMPTY AND not in enclosed_cells(farmyard); a fenced-but-empty pasture cell reads EMPTY but is NOT unused — using cell_type alone would overcount. The min() cap is the whole point of the card.

### A37 Bucksaw

- **kind:** minor
- **confidence:** high
- **template:** mining_hammer.py (after_renovate optional trigger) + big_country.py (CardStore VP bank + register_scoring)
- **plan:** CARD_ID="bucksaw". register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1))) — no on_play (no flat vps= field; the point is banked per-renovate). _eligible(state,idx,triggers_resolved): CARD_ID not in triggers_resolved and state.players[idx].resources.wood >= 1. _apply(state,idx): p = players[idx]; p = fast_replace(p, resources=p.resources - Resources(wood=1) + Resources(grain=1), card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID,0)+1)); splice back. register("after_renovate", CARD_ID, _eligible, _apply) — OPTIONAL trigger (player declines via host Proceed/Stop). _score(state,idx)=state.players[idx].card_state.get(CARD_ID,0); register_scoring(CARD_ID, _score). Add import in cards/__init__.py.
- **ordering_note:** The bonus point is NOT a fixed vps= on the minor spec — it is accumulated once per fired renovate in CardStore and read at scoring (a renovate-count-dependent quantity, exactly Big Country/Tutor's bank pattern); a flat vps= would wrongly award it without renovating. Use the OPTIONAL register("after_renovate",...) (FireTrigger, declinable) not register_auto — "you CAN also pay" is the player's choice. The "pay 1 wood" is an effect-internal charge subtracted directly in _apply (mirrors Paper Maker), NOT a build cost — it does NOT route through effective_payments/cost-modifiers. Gate eligibility on triggers_resolved (once per renovate) AND wood>=1. after_renovate (not before) matches the established renovate-hook convention (Mining Hammer/Roughcaster/Millwright all hook renovate via after_renovate); the grain (resource bank) and point (bank) are always accommodatable, so no dead-end/accommodation concern.

### A34 Loppers

- **kind:** minor
- **confidence:** high
- **template:** ox_goad.py (optional after-event trigger shape) + big_country.py (CardStore bonus-point bank + register_scoring)
- **plan:** register_minor("loppers", cost=Cost(resources=Resources(wood=1)), min_occupations=2). register("after_build_fences", "loppers", _eligible, _apply). _eligible(state,idx,triggers_resolved): "loppers" not in triggers_resolved AND p.resources.wood>=1 AND p.fences_in_supply>=1 (never a dead-end). _apply(state,idx): p = fast_replace(p, resources=p.resources - Resources(wood=1) + Resources(food=2), fences_in_supply=p.fences_in_supply-1, card_state=p.card_state.set("loppers", p.card_state.get("loppers",0)+1)); splice player back; return state (no pending pushed — simple state edit). register_scoring("loppers", lambda s,i: s.players[i].card_state.get("loppers",0)). No passing, no printed vps.
- **ordering_note:** Three subtleties: (1) Use the OPTIONAL register (FireTrigger, declined via the host's Stop), NOT register_auto — the text says "you CAN also use this card". (2) Event is after_build_fences (the after-phase host enumerates FireTriggers + Stop; reaching after-phase requires Proceed which requires pastures_built>=1, so "you build 1 or more fences" is satisfied by construction — no extra fence-count guard needed). (3) The fence cost is fences_in_supply specifically (the stored supply pile, location 4), NOT helpers.buildable_fences (which adds on-card pools like Ash Trees) — gate AND debit fences_in_supply. Once-per-action is automatic: _apply_fire_trigger stamps triggers_resolved before applying and _eligible reads it. The bonus point is BANKED in CardStore (vps=0) and emitted by register_scoring — do not put it on the printed vps.

### A93 Bed Maker

- **kind:** occupation
- **confidence:** high
- **template:** assistant_tiller.py
- **plan:** register_occupation("bed_maker", lambda s,i: s) (on-play no-op; played via Lessons). register("after_build_rooms", "bed_maker", _eligible, _apply). _eligible(state, idx, triggers_resolved): CARD_ID not in triggers_resolved AND CARD_ID in p.occupations AND p.resources.wood>=1 AND p.resources.grain>=1 AND p.people_total < 5 AND p.people_total < _num_rooms(p) (import _num_rooms from agricola.legality). _apply(state, idx): pay p.resources + Resources(wood=-1, grain=-1), then push(state, PendingFamilyGrowth(player_idx=idx, initiated_by_id="card:bed_maker")). No cost/prereq/vps/passing on the spec. No register_action_space_hook (build_rooms is already a hosted non-atomic sub-action).
- **ordering_note:** "Family Growth with Room Only" = the ROOM-REQUIRED growth condition, so eligibility MUST gate on people_total < 5 AND people_total < _num_rooms(p) (the _legal_basic_wish_for_children condition), NOT the room-free urgent-wish condition. PendingFamilyGrowth is a generic add-newborn primitive that does NOT itself re-check the room gate, so the gate lives entirely in _eligible. The after_build_rooms phase already reflects the just-built rooms in _num_rooms (people_total unchanged), so a freshly-built empty room satisfies the gate — which is the intended use. The fixed 1 wood + 1 grain is paid directly in _apply (a trigger cost, not modifiable — do NOT route it through the cost-modifier chokepoint). Firing once per build-rooms session (the after_build_rooms work-complete flip) automatically honors the clarification "exactly 1 growth regardless of how many rooms built". Must be OPTIONAL (register/FireTrigger, declinable via the host's Proceed/Stop), never register_auto — it has a real cost and grants a sub-action.
- **errata:** Clarification present and load-bearing: "This card allows exactly 1 growth action regardless of how many rooms are built." Impact: confirms the per-build-rooms-session firing model (after_build_rooms fires once per session) is exactly correct — no per-room firing, no counter needed.

### A103 Portmonger

- **kind:** occupation
- **confidence:** high
- **template:** canoe.py
- **plan:** register_occupation("portmonger", on_play=_noop) — no cost/prereq/vps/passing (pure occupation; effect is the hook). register_action_space_hook("portmonger", {"fishing","meeting_place"}) so the atomic food spaces get a host frame. register_auto("before_action_space", "portmonger", _eligible, _apply). _eligible(state,idx): top=state.pending_stack[-1]; return top.space_id in {"fishing","meeting_place"} and get_space(state.board, top.space_id).accumulated_amount >= 1. _apply(state,idx): n = get_space(state.board, space_id).accumulated_amount; reward = Resources(veg=1) if n == 1 else Resources(grain=1) if n == 2 else Resources(reed=1) (n >= 3) — a SINGLE good by band; add to players[idx].resources via fast_replace (Canoe idiom). Fires BEFORE the atomic take, while food is still on the space, so accumulated_amount == the food about to be taken (verified: engine pushes host + fires before_action_space prior to ATOMIC_HANDLERS).
- **ordering_note:** ⚠️ REVIEWER CORRECTION (2026-06-30): the reward is BANDED / single-tier, NOT cumulative. Take exactly 1 food → 1 veg; exactly 2 → 1 grain; 3+ → 1 reed — exactly ONE good, selected by which band the take falls in. This matches the codebase's own slash-tier precedent (Loom, Gift Basket, Milking Parlor are all single-tier reads of "N/M/K → a/b/c"), and the open "3+" band implies one top-tier reward, not an accumulation. Read accumulated_amount in the BEFORE phase — it is the food about to be taken (fishing/meeting_place atomic handlers zero it). In CARDS mode meeting_place still pays food today (the board reuses Family until the meeting_place_cards split lands), so hooking it is faithful and future-proof.
- **open_question:** RESOLVED to BANDED by the reviewer (see correction above) on codebase precedent; user may override to cumulative if the official ruling differs.

### A79 Garden Hoe

- **kind:** minor
- **confidence:** high
- **template:** shepherds_crook.py
- **plan:** CARD_ID="garden_hoe". register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1))). Helper _veg_field_count(p) = number of field cells with veg>0 (walk farmyard.grid). before_sow auto: snapshot count into card_state.set(CARD_ID, count) (eligibility lambda True). after_sow auto: read before; if (_veg_field_count(p) - before) >= 1 grant Resources(clay=1, stone=1) ONCE (flat, not scaled); always reset card_state.set(CARD_ID, 0) to a canonical value. Both via register_auto("before_sow",...)/register_auto("after_sow",...). No prereq, no vps, passing_left=False.
- **ordering_note:** Grant is FLAT (+1 clay +1 stone once per qualifying sow), NOT per veg-field — fire on (after_count - before_count) >= 1, never multiply by veg count. The auto's apply_fn receives only (state, idx), so commit.veg is invisible; you MUST detect veg-planting via the before/after veg-bearing-field-count delta (cumulative state alone can't tell this-sow veg from prior-round veg). after_sow fires post-fill in _enter_after_phase, so the after-snapshot already reflects the new veg. Reset the snapshot to a canonical value (0) in the after-hook so different commit orders converge (transposition-table safety).

### A109 Small Trader

- **kind:** occupation
- **confidence:** high
- **template:** dutch_windmill.py
- **plan:** CARD_ID="small_trader". register_occupation(CARD_ID, lambda state, idx: state)  # no on-play. register_auto("after_major_minor_improvement", CARD_ID, _eligible, _apply) (own-action; any_player default False). _eligible(state, idx): top = state.pending_stack[-1]; return getattr(top, "initiated_by_id", "") == "space:major_improvement" and getattr(top, "minor_chosen", False) — i.e. the composite host was reached via the Major Improvement action space AND a minor was played (not a major built). _apply(state, idx): p = fast_replace(state.players[idx], resources=p.resources + Resources(food=3)); return fast_replace(state, players=tuple(...)). No cost/prereq/vps/passing (occupation; spec is on-play registration only).
- **ordering_note:** Two gates are both load-bearing and verified: (1) fire on the PARENT composite host's after-event (after_major_minor_improvement), NOT after_play_minor — after_play_minor fires on EVERY minor play (House Redev, Basic Wish, Meeting Place too), but the card+clarification ("does not work unless you literally get that action") restricts it to the Major or Minor Improvement action SPACE. At after_major_minor_improvement the top frame IS PendingMajorMinorImprovement (phase="after", still top-of-stack after PendingPlayMinor pops), carrying initiated_by_id="space:major_improvement" (vs "house_redevelopment" for the House-Redev entry) — the only signal that distinguishes the two entry points (PendingPlayMinor.initiated_by_id is "major_minor_improvement" for BOTH, so it cannot distinguish). (2) Gate on minor_chosen (not major_chosen): "play an improvement from your hand" = a MINOR (majors come from the common board, not your hand), so building a major at that space gives NO +3 food.
- **errata:** clarifications field: "Does not work unless you literally get that action." Impact: confirms the trigger fires ONLY when you actually take the Major or Minor Improvement action space (initiated_by_id=="space:major_improvement"), never via a card-granted route to playing a minor (House Redevelopment's improvement step, Basic Wish for Children, Meeting Place). Mapped cleanly by the initiated_by_id gate.

### B105 Case Builder

- **kind:** occupation
- **confidence:** high
- **template:** priest.py
- **plan:** New module agricola/cards/case_builder.py; CARD_ID="case_builder". _on_play(state, idx): read base = state.players[idx].resources (the pre-grant snapshot); build gain = Resources(food=1 if base.food>=2 else 0, grain=1 if base.grain>=2 else 0, veg=1 if base.veg>=2 else 0, reed=1 if base.reed>=2 else 0, wood=1 if base.wood>=2 else 0); p = fast_replace(p, resources=base + gain); return fast_replace(state, players=tuple(...)). register_occupation("case_builder", _on_play). No cost/prereq/vps/passing (occupation — cost handled by the play entry point; vps=0). Add import to cards/__init__.py.
- **ordering_note:** All five ≥2 threshold checks must read the SAME pre-grant resources snapshot (base), not a mutated total. Goods are disjoint per-check (granting wood can't flip the grain check), so sequential-vs-snapshot is equivalent here, but compute every condition against base to be safe. Threshold is "at least 2" (>=2), and the good granted (vegetable) maps to Resources.veg.

### B119 Lumberjack

- **kind:** occupation
- **confidence:** high
- **template:** wall_builder.py (schedule_resources mechanism) + consultant.py (immediate on_play resource grant)
- **plan:** CARD_ID="lumberjack". register_occupation("lumberjack", _on_play). _on_play(state,idx): p=state.players[idx]; grant immediate p.resources+Resources(wood=1) via fast_replace; then N=helpers.fences_built(p.farmyard); R=state.round_number; return schedule_resources(state_after_grant, idx, range(R+1, R+1+N), Resources(wood=1)). schedule_resources auto-clamps rounds>14, and N=0 yields an empty range (player still keeps the +1 wood). No cost/prereq/vps/passing (plain occupation played via Lessons). Update the immediate-grant player tuple BEFORE calling schedule_resources so both edits land (schedule_resources reads state.players[idx] fresh).
- **ordering_note:** N = the count of fence PIECES on the board at play time, read via helpers.fences_built(p.farmyard) (each placed fence segment counts as one), NOT pastures and NOT buildable_fences/fences_in_supply. Two clamps stack: the explicit "up to N fences" (the range length) AND schedule_resources silently dropping any round >14 — so late-game plays place wood on fewer than N spaces. "next round spaces" = rounds R+1.., i.e. range(R+1, R+1+N) (mirrors Wall Builder's R+1 start); slot r-1 holds round r's goods. Do the immediate +1 wood grant first and feed the resulting state into schedule_resources so the on-card edits don't clobber each other.

### B125 Estate Worker

- **kind:** occupation
- **confidence:** high
- **template:** large_greenhouse.py
- **plan:** register_occupation("estate_worker", _on_play). _on_play(state, idx): R = state.round_number; chain four single-good schedule_resources calls — schedule_resources(state, idx, (R+1,), Resources(wood=1)) then (R+2,) clay, (R+3,) reed, (R+4,) stone, threading the returned state. No cost, no prereq, no min/max_occupations, no vps, not passing — all defaults. No triggers/hooks/animals/conversions. Add import to cards/__init__.py.
- **ordering_note:** "In this order" / "respective building resource" means the goods map positionally: wood→R+1, clay→R+2, reed→R+3, stone→R+4 — do NOT dump all four onto the same rounds (one good per round, not Wall Builder's same-good-on-all-4 shape). schedule_resources uses 1-indexed rounds and clamps any round > 14 away, so late plays silently drop the overflow rounds (correct for "the next 4 round spaces" that still exist).

### B37 Grange

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** Copy market_stall.py (a minor with on-play). CARD_ID="grange". _on_play(state,idx): p.resources + Resources(food=1), splice player back (exact market_stall body). Define _prereq(state,idx): count grid cells with cell_type is CellType.FIELD across the 3x5 grid (the scoring.py:163 / big_country idiom) and require >=6 AND a.sheep>=1 and a.boar>=1 and a.cattle>=1 (the briar_hedge all-animal-types predicate). register_minor("grange", prereq=_prereq, vps=3, on_play=_on_play). No cost, not passing. Printed VPs (3) are scored automatically from spec.vps (scoring.py:248) — do NOT add register_scoring. Add the import line to cards/__init__.py.
- **ordering_note:** The prereq is a have-check, never a cost — leave cost empty. "6 Field Tiles" counts field cells by cell_type alone (regardless of whether sown), matching scoring's num_fields; do NOT filter on .grain/.veg. A pasture-not-a-celltype subtlety does NOT bite here because fields are a real CellType (only the animal/empty-pasture checks need the enclosed_cells guard, which this card doesn't use). vps=3 must ride on register_minor (auto-scored), not register_scoring, to avoid double-counting.

### B6 Excursion to the Quarry

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** New module agricola/cards/excursion_to_the_quarry.py. _on_play(state, idx): p = state.players[idx]; p = fast_replace(p, resources=p.resources + Resources(stone=p.people_total)); return fast_replace(state, players=tuple(...)). register_minor("excursion_to_the_quarry", cost=Cost(resources=Resources(food=2)), min_occupations=1, on_play=_on_play). No passing, vps=0. Add the import to cards/__init__.py so register() fires. Stone needs no accommodation, so no extra gating.
- **ordering_note:** Use p.people_total (home + placed + newborns), NOT people_home — "number of people you have" counts placed workers and newborns. The state.py field doc and the card's clarification ("A newborn is a person") both confirm people_total already includes newborns, so no manual newborn addition is needed.
- **errata:** clarifications field: "A newborn is a person." Impact: confirms newborns count toward the stone gain, which people_total already includes — no code adjustment needed.

### B40 Brewery Pond

- **kind:** minor
- **confidence:** high
- **template:** herring_pot.py (and wood_cutter.py for the immediate-grant apply idiom)
- **plan:** Copy herring_pot.py shape. CARD_ID="brewery_pond"; SPACES=frozenset({"fishing","reed_bank"}). _eligible(state,idx): return state.pending_stack[-1].space_id in SPACES. _apply(state,idx): p=fast_replace(state.players[idx], resources=state.players[idx].resources + Resources(grain=1, wood=1)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). register_minor("brewery_pond", min_occupations=2, vps=-1) (no cost in data; cost=Cost() default). register_auto("before_action_space","brewery_pond",_eligible,_apply). register_action_space_hook("brewery_pond", SPACES). Add import in cards/__init__.py.
- **ordering_note:** Timing is BEFORE the space's own effect (before_action_space), per the "each time you use [space]" ruling — matches Wood Cutter / Herring Pot. Here the order is behaviorally irrelevant (the +1 grain +1 wood is independent of the fishing food / reed pickup), but the phase is fixed by the ruling, not by convenience. Eligibility must read the host frame's space_id (pending_stack[-1].space_id) so one effect serves both fishing and reed_bank. register_auto (mandatory, choice-free pure-goods grant) — never a FireTrigger. Confirm the card-data JSON carries no resource cost (cost=Cost() default); "2 Occupations" is a min_occupations=2 prereq (have-check), NOT a cost; vps=-1 flows through MINORS[cid].vps in scoring automatically, no register_scoring needed.

### B44 Chick Stable

- **kind:** minor
- **confidence:** high
- **template:** pond_hut.py
- **plan:** New module chick_stable.py. CARD_ID="chick_stable". _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, [R+3, R+4], Resources(food=2)). register_minor("chick_stable", cost=Cost(resources=Resources(wood=1, clay=1)), on_play=_on_play). NO prereq, NO occupation bounds, vps=0, passing_left=False (defaults). Import the module in cards/__init__.py so register fires.
- **ordering_note:** The food is 2 per space (Resources(food=2)), placed on exactly rounds R+3 and R+4 — NOT consecutive from R+1 like Pond Hut's range(R+1,R+4). Use the explicit list [R+3, R+4], not a range starting at R+1. schedule_resources clamps slots to 1..14 and silently drops out-of-range rounds, so late plays (R>=12, where R+4 or both exceed 14) correctly forfeit the unreachable round space(s) per "each corresponding round space" — no special handling needed.

### B46 Club House

- **kind:** minor
- **confidence:** high
- **template:** strawberry_patch.py
- **plan:** register_minor("club_house", cost=Cost(resources=Resources(wood=3, clay=2)), vps=1, on_play=_on_play). No prereq, not passing. _on_play(state, idx): R = state.round_number; state = schedule_resources(state, idx, range(R+1, R+5), Resources(food=1)); return schedule_resources(state, idx, [R+5], Resources(stone=1)). Two additive schedule_resources calls compose cleanly; slots past round 14 are silently dropped by the helper.
- **ordering_note:** "Next 4 round spaces" = food on rounds R+1..R+4 (range(R+1, R+5), an EXCLUSIVE upper bound — off-by-one is the trap); "the round space after that" = stone on R+5, a SINGLE round (use [R+5] or range(R+5, R+6), not a multi-round range). R is state.round_number (current round); food is rounds AFTER the current one, never the current round's slot. schedule_resources clamps to 1..14 and drops past-game rounds, so no manual bounds check needed.

### B78 Reed Belt

- **kind:** minor
- **confidence:** high
- **template:** sack_cart.py
- **plan:** Copy sack_cart.py. CARD_ID="reed_belt"; _REED_ROUNDS=(5,8,10,12). _on_play: R=state.round_number; remaining=[r for r in _REED_ROUNDS if r > R]; return schedule_resources(state, idx, remaining, Resources(reed=1)). register_minor("reed_belt", cost=Cost(resources=Resources(food=2)), on_play=_on_play). No prereq, vps=0 (none), not passing. Add import in cards/__init__.py.
- **ordering_note:** "Remaining spaces" must filter rounds with r > R (strictly after the current round), exactly as Sack Cart does — a round already entered has had its space collected. schedule_resources additionally clamps slot N-1 to 1..14, but the explicit >R filter is the faithful reading. The scheduled reed lands in future_resources and is auto-collected at each round's start (engine._complete_preparation) — reed always fits (no accommodation needed), so no animal/capacity concern.

### B73 Gift Basket

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** Create agricola/cards/gift_basket.py. _on_play(state, idx): count ROOM cells in p.farmyard.grid (mirror scoring.py's sum over CellType.ROOM; there is NO num_rooms field on PlayerState — the cheat-sheet is wrong here) into n; gain = {2: Resources(veg=1), 3: Resources(food=1), 4: Resources(grain=1), 5: Resources(veg=1)}.get(n); if gain is None return state unchanged, else p = fast_replace(p, resources=p.resources + gain) and rebuild players tuple. register_minor("gift_basket", cost=Cost(resources=Resources(reed=1)), min_occupations=3, vps=1, on_play=_on_play). passing_left defaults False (kept). Add import to cards/__init__.py.
- **ordering_note:** The slash-list alignment is the one error-prone spot: "exactly 2/3/4/5 rooms → 1 vegetable/food/grain/vegetable" means 2→veg, 3→food, 4→grain, 5→veg (2 and 5 BOTH give veg). Any room count outside {2,3,4,5} (e.g. the starting 2-room minimum is covered, but 6+ rooms, theoretically up to 15) yields NOTHING — return state unchanged. Count rooms by ROOM cells in the farmyard grid, not a field. "3 Occupations" prereq is a have-check (min_occupations=3), the cost (1 reed) is the only thing spent.

### B90 Cooperative Plower

- **kind:** occupation
- **confidence:** high
- **template:** mole_plow.py
- **plan:** register_occupation("cooperative_plower", lambda s,i: s) (no on-play effect; played via Lessons). register("before_action_space", CARD_ID, _eligible, _apply); register_action_space_hook is NOT needed (farmland is non-atomic/already hosted, per Mole Plow). _eligible(state,idx,triggers_resolved): CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id == "farmland" AND get_space(state.board,"grain_seeds").workers != (0,0) AND _can_plow(state.players[idx]). _apply: push(state, PendingPlow(player_idx=idx, initiated_by_id="card:cooperative_plower")). No cost/prereq/vps/passing (occupation; cost is the Lessons play path).
- **ordering_note:** The "while Grain Seeds is occupied" condition MUST be checked as occupancy directly — get_space(state.board,"grain_seeds").workers != (0,0) — NOT the prior agent's `not _is_available(state,"grain_seeds")`. _is_available is also False when the space is UNREVEALED, so the negation would wrongly grant the bonus when grain_seeds isn't even in play. (grain_seeds is a permanent space revealed from setup, so in practice it's always revealed, but checking workers != (0,0) is the correct robust predicate.) Standard "each time you use" = BEFORE phase (before farmland's own plow), once-per-use via triggers_resolved; optional grant (register, not register_auto), eligibility gated on _can_plow so it never grants a dead-end.

### B92 Little Stick Knitter

- **kind:** occupation
- **confidence:** high
- **template:** cottager.py
- **plan:** Occupation, no on-play/cost/prereq/vps/passing. register_occupation("little_stick_knitter", lambda s,i: s). register("before_action_space", CARD_ID, _eligible, _apply). NO register_action_space_hook (sheep_market is non-atomic/already hosted). _eligible(state, idx, triggers_resolved): CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id == "sheep_market" AND state.round_number >= 5 AND p.people_total < 5 AND p.people_total < _num_rooms(p) (the "with room only" gate, mirroring _legal_basic_wish_for_children; the primitive's CommitFamilyGrowth is an unconditional singleton, so eligibility must fully guarantee legality). _apply(state, idx): push(state, PendingFamilyGrowth(player_idx=idx, initiated_by_id="sheep_market")). Import _num_rooms from agricola.legality, PendingFamilyGrowth + push from agricola.pending.
- **ordering_note:** initiated_by_id MUST be the real board space id "sheep_market" (NOT "card:little_stick_knitter"): _execute_family_growth -> _resolve_wish_for_children does get_space(board, initiated_by_id) to place the newborn worker, which KeyErrors on a non-space id. This is the sole existing precedent's contract (the wish space passes bare "basic_wish_for_children"). Placing the newborn next to the parent on sheep_market is correct Agricola semantics and harmless: the space is already occupied (workers != (0,0)) and accumulated_amount already zeroed, so availability/collection are unaffected. Two more subtleties: (1) timing is BEFORE not after — "each time you use" = before_action_space per the binding ruling (the prior hypothesis said after_action_space, wrong; observationally neutral here since growth doesn't touch the sheep gain, but pick by ruling not convenience); (2) "with Room Only" is NOT a primitive parameter — there is no room-only field on PendingFamilyGrowth — it is the eligibility gate people_total < num_rooms, and people_total < 5.

### B96 Tree Farm Joiner

- **kind:** occupation
- **confidence:** high
- **template:** handplow.py
- **plan:** register_occupation("tree_farm_joiner", _on_play). _on_play: rounds=next 2 odd ints strictly > state.round_number; schedule_resources(state, idx, rounds, Resources(wood=1)) THEN schedule_effect(state, idx, rounds, CARD_ID) (both write the same odd-round slots; schedule helpers silently drop rounds>14). register("start_of_round", CARD_ID, _eligible, _apply) — do NOT call register_start_of_round_hook (schedule_effect already drives has_scheduled_round_start_effect→preparation hosting, like Handplow). _eligible(state,idx,triggers_resolved): _scheduled_slot(p, state.round_number) is not None AND len(legality.playable_minors(state, idx)) > 0 (≥1 affordable hand minor — else firing dead-ends). _apply: consume the grant (remove CARD_ID from this round's future_rewards slot, mirroring Handplow) then push(state, PendingPlayMinor(player_idx=idx, initiated_by_id="card:tree_farm_joiner")). No cost/prereq/vps/passing.
- **ordering_note:** Two subtleties. (1) OPTIONALITY: PendingPlayMinor has NO decline of its own — it forces exactly one minor once pushed. So the decline must live at the parent: model it as an OPTIONAL start_of_round trigger (FireTrigger at the PendingPreparation host; the host's Proceed IS the decline), NOT by auto-pushing PendingPlayMinor. Therefore eligibility MUST also require len(playable_minors(state,idx))>0, or a fired-but-unaffordable grant yields an empty legal set (dead-end). (2) WOOD-BEFORE-MINOR ORDERING is already correct and load-bearing: _complete_preparation distributes future_resources (the +1 wood) at step 2, BEFORE _fire_preparation_hook (step 5) surfaces the minor trigger — so the wood is on hand to pay the minor, matching "you get the wood and, immediately afterward, a Minor Improvement action."

### B101 Furniture Carpenter

- **kind:** occupation
- **confidence:** high
- **template:** harvest_conversions.py (HarvestConversionSpec entry) + stable_architect.py (no-op occupation) + big_country.py (CardStore bank + register_scoring)
- **plan:** In furniture_carpenter.py: CARD_ID="furniture_carpenter". register_occupation(CARD_ID, lambda s,i: s) (no on-play effect). Define _eligible(state, idx) = CARD_ID in state.players[idx].occupations AND state.board.major_improvement_owners[7] is not None (ANY player owning the Joinery — idx 7 — satisfies it; see ⚠️ note). Define _award(state, idx) returning state with players[idx].card_state.set(CARD_ID, card_state.get(CARD_ID,0)+1). register_harvest_conversion(HarvestConversionSpec(conversion_id="furniture_carpenter", input_cost=Resources(food=2), food_out=0, is_owned_fn=_eligible, side_effect_fn=_award)). register_scoring(CARD_ID, lambda s,i: s.players[i].card_state.get(CARD_ID,0)). cost=Cost() (no play cost), vps=0 (points are bought, not printed), passing_left=False. (VERIFIED by reviewer: HarvestConversionSpec.side_effect_fn is the real, designed mechanism for food→VP harvest buys — its docstring names exactly this "Stone Sculptor +1 point per harvest" use; the conversion is surfaced as a discrete optional CommitHarvestConversion during FEED, gated only on is_owned_fn + the once-per-harvest budget, so a food_out=0 spend IS offered.)
- **ordering_note:** Two subtleties. (1) The conversion enumerator (legality.py:2145) gates ONLY on is_owned_fn, and registrations are global, so is_owned_fn MUST include `furniture_carpenter in players[idx].occupations` — otherwise the buy-a-point is offered to the non-owner. (2) input_cost=Resources(food=2), food_out=0 is the INVERSE of the built-in crafts (which take goods and PRODUCE food); _execute_harvest_conversion does `resources - input_cost + Resources(food=food_out)`, so food=2 is correctly subtracted and 0 food added — verified this is the intended use of side_effect_fn (docstring: Stone Sculptor +1 point per harvest). Point banking must INCREMENT card_state each harvest (up to 6), not overwrite.
- **open_question:** ⚠️ REVIEWER DECISION (2026-06-30): defaulted to JOINERY ONLY (major idx 7). Rationale: in THIS engine the 10 majors (0–9) are distinct and there is NO "upgraded Joinery" — Pottery (8) and Basketmaker (9) are separate crafts, not upgrades of the Joinery — so "an upgrade thereof" maps to nothing reachable today and the literal condition is "owns the Joinery." If a future card adds an actual Joinery upgrade, it should register itself as satisfying this condition. User: confirm Joinery-only, or include the whole {7,8,9} workshop family.

### B110 Pavior

- **kind:** occupation
- **confidence:** high
- **template:** scullery.py
- **plan:** CARD_ID="pavior". register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect. _eligible(state, idx) -> state.players[idx].resources.stone >= 1 (re-checked each round). _apply(state, idx): gain = Resources(veg=1) if state.round_number == 14 else Resources(food=1); add to that player's resources via fast_replace; return updated state (no pending pushed). register_auto("start_of_round", CARD_ID, _eligible, _apply); register_start_of_round_hook(CARD_ID). No cost/prereq/vps/passing (occupation, played via Lessons).
- **ordering_note:** The round-14 (veg-instead-of-food) branch must read state.round_number INSIDE _apply and compare == 14. By the time start_of_round autos fire (in _complete_preparation -> _push_preparation_hosts, engine.py ~L981/1031/1136) round_number is ALREADY incremented to the new round, so state.round_number is the current round — use == 14 (the final round, NUM_ROUNDS=14), not >= 14 or the pre-increment value. Eligibility (stone>=1) is re-evaluated each round by register_auto, correctly matching "if you have at least 1 stone".

### B111 Rustic

- **kind:** occupation
- **confidence:** high
- **template:** shepherds_crook.py (before/after snapshot) + big_country.py (CardStore-banked VP + register_scoring)
- **plan:** register_occupation("rustic", no-op on_play). Helper _room_count(p) = count grid cells with CellType.ROOM (as scoring.py does). register_auto("before_build_rooms","rustic", lambda s,i:True, _snapshot) -> store _room_count into card_state under a snapshot key. register_auto("after_build_rooms","rustic", _eligible, _apply): _eligible = house_material==CLAY (rooms always match current material, so a session's rooms are clay iff house is clay); _apply: n = _room_count(p) - snapshot; grant Resources(food=2*n); bank vp via card_state["rustic_vp"] += 1*n; reset snapshot to canonical 0. register_scoring("rustic", lambda s,i: card_state.get("rustic_vp",0)). No cost/prereq/vps/passing on the occupation itself (occupations have no cost; played via Lessons).
- **ordering_note:** after_build_rooms fires ONCE per build-rooms session (not per room), so the per-room count REQUIRES a before/after room-count delta — never just a boolean like Roughcaster. Eligibility must read house_material==CLAY (renovated wood rooms and stone rooms excluded exactly as the text's parenthetical demands; a wood->clay renovate then build-rooms in separate actions is fine since material is clay at build time). The "1 bonus point each" must be BANKED in CardStore and accumulated across every build-rooms session over the game, then scored — NOT granted as immediate points (no immediate-VP mechanism exists). Use two distinct card_state keys (snapshot vs banked-vp) or pack them; reset only the snapshot to a canonical value at after-phase so commit-order convergence holds.

### B122 Mineralogist

- **kind:** occupation
- **confidence:** high
- **template:** geologist.py
- **plan:** Copy geologist.py. SPACES = frozenset({"clay_pit","western_quarry","eastern_quarry"}). _eligible(state,idx): state.pending_stack[-1].space_id in SPACES. _apply(state,idx): branch on space_id — clay_pit -> Resources(stone=1); western_quarry/eastern_quarry -> Resources(clay=1); add to players[idx].resources via fast_replace. register_occupation(CARD_ID, lambda s,i: s) (no on-play, no cost). register_auto("before_action_space", CARD_ID, _eligible, _apply). register_action_space_hook(CARD_ID, SPACES). No prereq/vps/passing. Add import in cards/__init__.py.
- **ordering_note:** The bonus is the OTHER good and is space-dependent — clay_pit (a clay space) grants +1 STONE; western_quarry/eastern_quarry (stone spaces) grant +1 CLAY. Geologist's apply is space-independent (always clay); Mineralogist's apply MUST branch on space_id. Getting the direction backwards (clay-for-clay / stone-for-stone) is the one likely bug. There are exactly two stone/quarry spaces (western_quarry, eastern_quarry) and one clay space (clay_pit); include all three in both SPACES and the hook. before_action_space is correct per "each time you use" (matches geologist); since the bonus is purely additive, before-vs-after is total-equivalent, but use before for convention consistency.

### B124 Trimmer

- **kind:** occupation
- **confidence:** high
- **template:** shepherds_crook.py
- **plan:** CARD_ID="trimmer". register_occupation(CARD_ID, lambda s,i: s) (no on-play). No cost/prereq/vps/passing (printed card has none). register_auto("before_build_fences", CARD_ID, lambda s,i: True, _snapshot) — store frozenset of enclosed_cells in CardStore (reuse helpers.enclosed_cells(p.farmyard) or shepherds_crook's pasture-union). register_auto("after_build_fences", CARD_ID, lambda s,i: True, _grant): newly = enclosed_cells(after) - before; if newly is non-empty AND CARD_ID not in p.used_this_round → p.resources += Resources(stone=2) and p.used_this_round |= {CARD_ID}; always reset the snapshot to frozenset(). Like shepherds_crook this fires whether fencing comes via the Fencing space or Farm Redevelopment (both push PendingBuildFences).
- **ordering_note:** "In each work phase ... you get 2 stone" is once-per-work-phase, NOT once-per-action — gate the after-grant on the used_this_round latch (reset at round start by _complete_preparation) so two enclosing actions in one round (e.g. Fencing space + Overhaul) grant only +2 total, not +4. "Subdividing does not count" needs NO special handling: pure subdivision encloses no NEW cell, so newly_enclosed = enclosed_cells(after) - enclosed_cells(before) is empty and the grant is naturally skipped — exactly why the diff is computed once at the after-flip, never per pasture commit. Use enclosed-cells diff (helpers.enclosed_cells), never cell_type.
- **open_question:** Scope: "In each work phase" — I read it as once per work phase (one +2 stone the first time you newly enclose, via the used_this_round latch), distinct from shepherds_crook's per-action "Each time you fence." If you instead intend +2 stone per qualifying Build Fences action (no latch), say so and I'll drop the latch.

### B4 Wood Pile

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** register_minor("wood_pile", cost=Cost(), passing_left=True, on_play=_on_play). _on_play(state, idx): n = sum(get_space(state.board, sid).workers[idx] for sid in ACCUMULATION_SPACES); p = fast_replace(state.players[idx], resources=p.resources + Resources(wood=n)); return _update_player(state, idx, p). No prereq, vps=0 (default). ACCUMULATION_SPACES is the ready-made frozenset in constants.py = {forest, clay_pit, reed_bank, western_quarry, eastern_quarry, fishing, meeting_place, sheep_market, pig_market, cattle_market}. Add import to cards/__init__.py.
- **ordering_note:** Two subtleties. (1) PASSING: card data passing_left:"X" means traveling — verified against the implemented B8 Market Stall (same "X" -> passing_left=True). So this must be register_minor(..., passing_left=True); after the wood gain it passes to the opponent and is NOT kept. The prior hypothesis omitted this. (2) WHICH SPACES: "accumulation spaces" must use constants.ACCUMULATION_SPACES exactly — the 5 building-resource + 5 food/animal spaces. Do NOT include grain_seeds/vegetable_seeds/day_laborer/farmland (fixed-yield, non-accumulating) nor the improvement space the worker is currently on (not an accumulation space, so the Wood Pile worker is correctly not self-counted). Count own people via workers[idx] (the per-player int on ActionSpaceState), summed over ACCUMULATION_SPACES; this naturally counts a parent worker as 1 during normal placement.

### B20 Chain Float

- **kind:** minor
- **confidence:** high
- **template:** handplow.py
- **plan:** Copy handplow.py as chain_float.py. CARD_ID="chain_float". _on_play: R=state.round_number; return schedule_effect(state, idx, (R+7, R+8, R+9), CARD_ID) — three offsets instead of one; schedules.py clamps slots>14 silently. Keep _scheduled_slot/_eligible/_apply verbatim (eligible = _scheduled_slot(p, round) is not None and _can_plow(p); apply removes CARD_ID from THIS round's slot only, then push(PendingPlow(player_idx=idx, initiated_by_id="card:chain_float"))). register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)), on_play=_on_play); register("start_of_round", CARD_ID, _eligible, _apply). No prereq, no vps, not passing. Add import in cards/__init__.py.
- **ordering_note:** CRITICAL TEXT READING: "Add 7, 8, and 9 to the current round" means offsets R+7, R+8, R+9 (current round number plus each), NOT fixed rounds 7/8/9 — exactly parallel to Handplow's "Add 5 to the current round" = R+5. The prior Sonnet hypothesis ("fixed rounds 7,8,9") is wrong. Second subtlety: _apply must consume ONLY the current round's slot (Handplow's _scheduled_slot(p, state.round_number) already does this), so firing the grant on round R+7 leaves the R+8/R+9 slots intact for those later rounds — the per-round-slot consumption handles the three-round case with no change. The plow grant is OPTIONAL ("you can plow"), surfaced as a FireTrigger with the PendingPreparation host's Proceed as decline; eligibility gated on _can_plow so it never offers a dead-end.

### B43 Chophouse

- **kind:** minor
- **confidence:** high
- **template:** herring_pot.py
- **plan:** Copy herring_pot.py. CARD_ID="chophouse"; SPACES=frozenset({"grain_seeds","vegetable_seeds"}). _eligible(state,idx): state.pending_stack[-1].space_id in SPACES. _apply(state,idx): R=state.round_number; sid=state.pending_stack[-1].space_id; n=3 if sid=="grain_seeds" else 2; return schedule_resources(state, idx, range(R+1, R+1+n), Resources(food=1)). register_minor("chophouse", cost=Cost(resources=Resources(wood=2, clay=2)), vps=1). register_auto("before_action_space","chophouse",_eligible,_apply). register_action_space_hook("chophouse", SPACES). No prereq, not passing.
- **ordering_note:** The single _apply must branch on pending_stack[-1].space_id to pick N (grain_seeds→3, vegetable_seeds→2) — a naive Herring-Pot copy would hardcode one N. "next N round spaces" = rounds R+1..R+N, i.e. range(R+1, R+1+n) (Herring Pot uses range(R+1,R+4)=R+1..R+3 for N=3); schedule_resources silently clamps rounds >14, matching "each remaining round space". Timing is before_action_space ("Each time you use" ruling); since food is scheduled to future rounds (not collected this turn) the end state is before/after-identical, but the ruling fixes the phase.
- **errata:** Card's clarifications field only cross-references "the errata for Swagman A129" — that errata ("the jump to a second action space may only be done once per turn") governs Swagman, a 3+ player occupation, and has NO bearing on Chophouse's mechanics. No Chophouse-specific errata. No behavioral impact.

### B51 Digging Spade

- **kind:** minor
- **confidence:** high
- **template:** loam_pit.py
- **plan:** register_minor("digging_spade", cost=Cost(resources=Resources(wood=1)), prereq=lambda state, idx: state.round_number >= 7).  # vps=0, no passing
_eligible(state, idx) -> state.pending_stack[-1].space_id == "clay_pit"  (register_auto's 2-arg signature, no triggers_resolved).
_apply(state, idx): n = state.players[idx].animals.boar; p = fast_replace(player, resources=player.resources + Resources(food=n)); return fast_replace(state, players=...). (No-op when n==0; still fine.)
register_auto("before_action_space", CARD_ID, _eligible, _apply); register_action_space_hook(CARD_ID, frozenset({"clay_pit"})). Add the import line to cards/__init__.py.
- **ordering_note:** "clay accumulation space" resolves to clay_pit ONLY — it is the sole clay entry in BUILDING_ACCUMULATION_RATES; do NOT include day_laborer or any other building space. Food = player's own animals.boar (a "wild boar in your farmyard"); this is a goods grant only, never an animal grant, so no accommodation concern. Timing is before_action_space per the "each time you use" ruling (the boar count is unaffected by taking the clay, so the amount is the same either way, but use BEFORE per the ruling, not convenience). Use register_auto (mandatory, choice-free "you also get") — NOT an optional register/FireTrigger; its eligible fn takes (state, idx) only.

### B52 Growing Farm

- **kind:** minor
- **confidence:** high
- **template:** big_country.py
- **plan:** In agricola/cards/growing_farm.py: CARD_ID="growing_farm". _prereq(state,idx)->bool: from agricola.helpers import enclosed_cells; fy=state.players[idx].farmyard; return len(enclosed_cells(fy)) >= state.round_number - 1. _on_play(state,idx): p=state.players[idx]; p=fast_replace(p, resources=p.resources + Resources(food=state.round_number)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). register_minor("growing_farm", cost=Cost(resources=Resources(clay=2, reed=1)), prereq=_prereq, vps=2, on_play=_on_play). No register_scoring (vps=2 is the printed-VP handled by the spec). Add the import line to cards/__init__.py.
- **ordering_note:** Two off-by-one / terminology traps, both opposite to the prior hypothesis. (1) "Pasture spaces" = the number of CELLS enclosed in pastures = len(enclosed_cells(fy)) (a 2-cell pasture counts as 2), NOT the number of distinct Pasture objects (len(farmyard.pastures)). (2) "Completed rounds" = round_number - 1 (the current round is in progress, not yet complete — mirrors big_country's 14 - round_number for "rounds left"), so the prereq is >= round_number - 1. The food grant is "current round" = round_number (NOT round_number - 1). So prereq threshold and food amount differ by exactly 1 and must not be conflated.

### B54 Tumbrel

- **kind:** minor
- **confidence:** high
- **template:** dutch_windmill.py (after-subaction register_auto income) + market_stall.py (on_play one-shot)
- **plan:** In a new tumbrel.py: CARD_ID="tumbrel". _on_play(state,idx): p.resources += Resources(food=2). _eligible(state,idx)->True (unconditional gain; 0 food when no stables is harmless). _apply(state,idx): built = 4 - stables_in_supply(state.players[idx].farmyard); p.resources += Resources(food=built). register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play). register_auto("after_sow", CARD_ID, _eligible, _apply). No vps, no passing, no prereq. Add the import to cards/__init__.py.
- **ordering_note:** "stables you have" = BUILT stables = 4 - helpers.stables_in_supply(farmyard) (stables_in_supply returns the unbuilt count, NOT the built count — do not use it directly). The auto fires on after_sow, which the PendingSow host emits once at the CommitSow flip-to-after (via _enter_after_phase -> apply_auto_effects("after_sow", ...)) for BOTH Grain Utilization and Cultivation sows. Use register_auto (mandatory, choice-free), not register — it's pure goods gain with no downside, so it must apply directly at the hook, never surfaced as a declinable FireTrigger. "after you take" = after_sow (the text literally states the after phase; no before/after judgment call). "Unconditional Sow": no conditional-sow card exists in the implemented set, so every after_sow event is an unconditional sow and the auto fires on all of them; if a conditional-sow card is ever added, this eligibility must inspect PendingSow provenance to exclude it (same caveat drill_harrow flags for before_sow).

### B58 Crack Weeder

- **kind:** minor
- **confidence:** high
- **template:** scythe_worker.py
- **plan:** register_minor("crack_weeder", cost=Cost(resources=Resources(wood=1)), on_play=_on_play) where _on_play credits p.resources + Resources(food=1). register_auto("harvest_field", "crack_weeder", _eligible, _apply); register_harvest_field_hook("crack_weeder"). _eligible: any FIELD cell with veg>0 in the owner's grid (i.e. a veg-sown field that will yield a veg this take). _apply: count = number of FIELD cells with veg>0; credit p.resources + Resources(food=count); do NOT mutate the grid (unlike Scythe Worker — this card does not TAKE extra veg, it only earns food alongside the mechanical take). No vps, no prereq, no passing.
- **ordering_note:** Two subtleties. (1) Do NOT decrement any veg — Crack Weeder counts the veg the mechanical take in _resolve_harvest_field already removes (1 per veg-sown field) and only adds food; copying Scythe Worker's grid mutation would wrongly double-deplete the fields. (2) The hook fires BEFORE the mechanical crop take (_fire_harvest_field_hook runs first in _resolve_harvest_field), so read the still-sown grid: count FIELD cells with veg>0 (grain XOR veg is enforced at sow, so veg>0 implies grain==0 and exactly mirrors the take's elif veg branch). Multi-veg fields still yield only 1 veg per harvest, so count fields not veg amount — Resources(veg=2) field contributes exactly 1 food.

### B59 Food Chest

- **kind:** minor
- **confidence:** high
- **template:** bread_paddle.py
- **plan:** register_minor("food_chest", cost=Cost(resources=Resources(wood=1)), on_play=_on_play)  (no prereq, vps=0, passing_left=False). _on_play(state, idx): via_major = any(getattr(f, "initiated_by_id", None) == "space:major_improvement" for f in state.pending_stack); gain = Resources(food=4 if via_major else 2); p = fast_replace(state.players[idx], resources=p.resources + gain); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). No trigger / scoring / hook. Add module import to cards/__init__.py.
- **ordering_note:** The "Major Improvement space" discriminator is a SCAN of the whole pending_stack for initiated_by_id == "space:major_improvement", NOT a read of the top frame: PendingPlayMinor's own initiated_by_id is "major_minor_improvement" (shared with the House-Redevelopment improvement path), so keying off the top frame would mis-classify. The distinguishing value lives one/two frames DOWN — _initiate_major_improvement sets "space:major_improvement" (resolution.py:417) and PendingMajorMinorImprovement inherits it (resolution.py:718), explicitly kept distinct from "space:house_redevelopment"/"house_redevelopment". The scan reads the LIVE stack inside on_play, which is correct because _execute_play_minor runs on_play (resolution.py:577) while the host frames are still on the stack (PendingPlayMinor is only flipped to its after-phase, the parent space/composite frames are still below it; the trailing Stop pops later). The four minor-play entry points are thereby separated: Major Improvement (4 food) vs House Redevelopment / Basic Wish for Children / Meeting Place (2 food). Use getattr(f,"initiated_by_id",None) since PendingReveal lacks the field.

### B60 Brewing Water

- **kind:** minor
- **confidence:** high
- **template:** ox_goad.py (optional cost-bearing trigger shape) + herring_pot.py (fishing hook + schedule_resources body)
- **plan:** register_minor("brewing_water", cost=Cost()) — free build, no prereq/vps/passing. register_action_space_hook("brewing_water", {"fishing"}) to host the atomic space. register("before_action_space", "brewing_water", _eligible, _apply) — OPTIONAL (mandatory=False) so it surfaces as a declinable FireTrigger ("you can"). _eligible(state, idx, triggers_resolved): return state.pending_stack[-1].space_id=="fishing" AND "brewing_water" not in triggers_resolved (once-per-use) AND state.players[idx].resources.grain >= 1 (affordable, no dead-end) AND state.round_number < NUM_ROUNDS (skip a pay-for-nothing fire in round 14). _apply(state, idx): debit 1 grain (p.resources - Resources(grain=1)), then R=state.round_number; schedule_resources(state, idx, range(R+1, R+7), Resources(food=1)). No PendingFoodPayment/resume needed — grain is a plain resource, not food.
- **ordering_note:** Timing is BEFORE, not after: "Each time you use [space]" with no "immediately after" fires in before_action_space per the ruling (matches Herring Pot, also a bare 'each time you use Fishing' card) — the prior hypothesis's "after fishing" is wrong. Schedule rounds are R+1..R+6 = range(R+1, R+7); schedule_resources silently clamps slots past round 14 (correctly handles 'next 6 round spaces' near game end). Eligibility MUST gate on grain>=1 (once fired the pay is mandatory, so a dead-end must be avoided) and once-per-use via triggers_resolved; optionally also round_number<14 to avoid offering a grain-for-zero-food fire.

### B63 Tasting

- **kind:** minor
- **confidence:** high
- **template:** paper_maker.py
- **plan:** New module agricola/cards/tasting.py, imported in cards/__init__.py. register_minor("tasting", cost=Cost(resources=Resources(wood=2)), vps=1) — no prereq, not passing, no on_play. register("before_play_occupation", "tasting", _eligible, _apply) where _eligible(state, idx, triggers_resolved) = "tasting" not in triggers_resolved and players[idx].resources.grain >= 1. _apply: p.resources - Resources(grain=1) + Resources(food=4). register_occupation_food_source("tasting", _food_source) where _food_source(state, idx) = (4, Resources(grain=1)) if grain>=1 else None — lets _payable_occupation (which checks owned = occupations | minor_improvements, so minors qualify) offer an occupation payable only after firing Tasting. _owns (triggers.py) also covers minors, so the trigger fires for an owned minor.
- **ordering_note:** Grain liquidates to food at a fixed 1:1 rate (food_payment_frontier: grain is always rate 1, no cooking improvement), so 1 grain -> 4 food is a strict 4x value trade and is NEVER Pareto-dominated — it must be offered even when the player already has enough food (exactly Paper Maker's "pure value trade, not folded into a food-payment frame" rationale). Gate firing on grain >= 1 in BOTH _eligible and _food_source. Once-per-play via triggers_resolved matches "each time you use Lessons" since each Lessons placement plays exactly one occupation. Like Paper Maker, Tasting never fires on the SAME-play affordability of itself — but that is irrelevant here since it's a minor, not the occupation being played.

### B64 Mill Wheel

- **kind:** minor
- **confidence:** high
- **template:** pitchfork.py
- **plan:** register_minor("mill_wheel", cost=Cost(resources=Resources(wood=2)), vps=1)  # no prereq, not passing.
register_auto("before_action_space", "mill_wheel", _eligible, _apply)  # mandatory, choice-free income via register_auto.
_eligible(state, idx): return state.pending_stack[-1].space_id == "grain_utilization" and get_space(state.board, "fishing").workers != (0, 0).
_apply(state, idx): p = fast_replace(state.players[idx], resources=state.players[idx].resources + Resources(food=2)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))).
NO register_action_space_hook — grain_utilization is non-atomic (in ACTION_SPACE_PENDING_IDS), so its host frame fires before_action_space at push automatically. Import get_space from agricola.state.
- **ordering_note:** Two subtleties. (1) before vs after: a bare "each time you use [Grain Utilization]" fires in the BEFORE phase (per the trigger-timing ruling and the Pitchfork/Milk Jug/Herring Pot precedent), so register on before_action_space, not after. The +2 food is pure income so before/after is end-state-identical, but use before to match the ruling/precedent. (2) The occupancy eligibility MUST be get_space(state.board, "fishing").workers != (0, 0) — NOT the prior agent's "not _is_available(state, 'fishing')". _is_available also returns False when the space is unrevealed and consults occupancy-override cards, so it would mis-fire (e.g. fire when fishing is merely unrevealed). The direct workers-tuple check is exactly what Pitchfork uses for Farmland.

### B67 Hand Truck

- **kind:** minor
- **confidence:** high
- **template:** dutch_windmill.py
- **plan:** register_minor("hand_truck", cost=Cost(resources=Resources(wood=1))) — no prereq, no VP, not passing. register_auto("before_bake_bread", "hand_truck", _eligible, _apply). _eligible(state,idx): "hand_truck" in state.players[idx].minor_improvements AND the owner's worker count on accumulation spaces > 0 (so a 0-grain no-op isn't applied). count = sum(get_space(state.board, sid).workers[idx] for sid in ACCUMULATION_SPACES) (import ACCUMULATION_SPACES from constants, get_space from state). _apply: p.resources + Resources(grain=count); standard player-tuple rebuild via fast_replace. register_auto (not the optional Potter-style register) because the card reads "you also get" and the clarification forces the grain to accompany the bake — it is mandatory, choice-free.
- **ordering_note:** Count is "each of YOUR people occupying an accumulation space" — index by the owner (workers[idx]), over ACCUMULATION_SPACES only ({forest, clay_pit, reed_bank, western_quarry, eastern_quarry, fishing, meeting_place, sheep_market, pig_market, cattle_market}). The bake host (Grain Utilization / Side Job / the ovens) is NOT an accumulation space, so the owner's own just-placed bake worker is correctly excluded — no self-count. Fire on before_bake_bread (the grain must arrive before CommitBake so it's bakeable this action), and gate _eligible on count>0 so no empty grant is applied.
- **errata:** clarifications field: "You must bake if you receive the grain." Impact: the grain is a baking-only bonus (you cannot take the grain and skip baking). This is satisfied FOR FREE by the engine: a before_bake_bread effect only runs inside a PendingBakeBread frame, which is reachable only after the player chose to bake at the parent, and the before-phase's only exit is CommitBake (Stop appears only in the after-phase). So "take grain, decline bake" is structurally impossible — no special handling needed. (Also: register_auto applies it unconditionally at the hook, exactly matching the mandatory "must bake / you also get" reading.)

### B71 Harvest House

- **kind:** minor
- **confidence:** high
- **template:** market_stall.py
- **plan:** register_minor("harvest_house", cost=Cost(resources=Resources(wood=1, clay=1, reed=1)), vps=2, on_play=_on_play). No prereq, not passing. In _on_play(state, idx): completed = len([h for h in HARVEST_ROUNDS if h < state.round_number]) (import HARVEST_ROUNDS from agricola.constants); n_occ = len(state.players[idx].occupations); if completed == n_occ: p = fast_replace(state.players[idx], resources=p.resources + Resources(food=1, grain=1, veg=1)) and splice back via the standard players-tuple idiom; else return state unchanged. Add the module import to cards/__init__.py.
- **ordering_note:** The one load-bearing subtlety is "number of completed harvests" = count of HARVEST_ROUNDS strictly LESS than the current round_number, NOT <=. Harvest of round R resolves at the WORK->PREPARATION boundary AFTER round R's worker placements, so a card played during WORK of round R has NOT yet experienced harvest R (confirmed by dutch_windmill's _POST_HARVEST_ROUNDS = {5,8,10,12,14}, i.e. harvest 4 completes before round 5). Use strict `<`. "Occupations you played" = len(occupations) (the played frozenset, exactly as specs.py's min/max_occupations check reads it); this minor is not an occupation so it doesn't affect the count. The grant is conditional (equality test), not unconditional — if unequal, no goods.

### B75 Wood Workshop

- **kind:** minor
- **confidence:** high
- **template:** dutch_windmill.py
- **plan:** CARD_ID="wood_workshop". _apply(state,idx): p.resources += Resources(wood=1); return rebuilt state. Use a trivially-True eligibility (lambda state,idx: True). register_auto("before_build_major", CARD_ID, _eligible, _apply) AND register_auto("before_play_minor", CARD_ID, _eligible, _apply) — "improvement" = major OR minor only (mirror lumber_mill's exact scope; NOT rooms/renovation). register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)), min_occupations=1) — no vps, not passing.
- **ordering_note:** MUST fire on the BEFORE phase, never after: the clarification "you can pay for the improvement with just the wood given by this card" requires the +1 wood to be in hand before payment. _fire_subaction_before_auto fires before_build_major/before_play_minor at the moment ChooseSubAction pushes PendingBuildMajor/PendingPlayMinor (engine.py:401), which is strictly before the CommitBuildMajor/CommitPlayMinor that charges the cost — so the granted wood is spendable on that very improvement, and any surplus banks (it's a real grant, not a cost reduction floored at 0). Hooking the play_minor/build_major SUB-ACTION events (not the major_minor_improvement composite host) is what makes it fire uniformly across ALL entry points (Major/Minor Improvement space, House Redevelopment, Basic Wish for Children, Meeting Place). Self-firing is correctly avoided: apply_auto_effects gates on _owns (card already in minor_improvements), and Wood Workshop is added only at CommitPlayMinor — after its own before_play_minor fires.
- **errata:** Clarification present (not behavior-changing errata): "You are able to pay for the improvement with just the wood given by this card." This pins down the timing (grant fires BEFORE cost payment) and confirms it is a real wood grant whose proceeds can fund the improvement — which the before-phase register_auto delivers automatically. No further impact.

### B79 Corf

- **kind:** minor
- **confidence:** high
- **template:** milk_jug.py (+ geologist.py for the atomic-space hook registration)
- **plan:** register_minor("corf", cost=Cost(resources=Resources(reed=1))). QUARRY_SPACES = frozenset({"western_quarry","eastern_quarry"}). _eligible(state, idx): top = state.pending_stack[-1]; return top.space_id in QUARRY_SPACES and get_space(state.board, top.space_id).accumulated.stone >= 3. _apply(state, idx): owner += Resources(stone=1) via fast_replace (stone has no capacity limit — safe). register_auto("before_action_space", "corf", _eligible, _apply, any_player=True). register_action_space_hook("corf", QUARRY_SPACES, any_player=True) — REQUIRED because both quarries are atomic and the owner must fire on the OPPONENT's quarry turn too. on-play no-op (register_minor's default). No prereq, vps=0, passing_left=False.
- **ordering_note:** Read the threshold from the goods STILL ON the space at the before-phase: get_space(board, space_id).accumulated.stone >= 3. The atomic quarry effect has NOT run yet at before_action_space (it runs later at Proceed/work-complete), so accumulated.stone is the full amount that will be taken — _resolve_building_accumulation sweeps the entire accumulated (no partial take), so "stone taken" == accumulated.stone. Quarries gain +1 stone/round, so the ≥3 threshold is met only when a quarry has sat untaken for ≥3 rounds. Use any_player=True on BOTH register_auto and register_action_space_hook so the host frame is pushed and the owner's stone fires even on the opponent's quarry placement.

---

## Defer (15)

### A43 Farmyard Manure

- **blocker_group:** off_turn_build_exclusion
- **reason:** Printed clarification forbids triggering on OFF-TURN stable builds (Groom B089, which IS implemented), but Groom's round-start build pushes the same PendingBuildStables host that fires after_build_stables — and phase is already WORK at that point, so a naive register_auto would wrongly fire. Distinguishing in-turn from off-turn needs a non-obvious new eligibility discriminator; flag for the user.
- **open_question:** How should Farmyard Manure detect an in-turn vs off-turn stable build so it does NOT fire on Groom's start-of-round build? Two viable mechanisms: (a) eligible() returns False if a PendingPreparation frame is present anywhere below the build host on the stack; or (b) gate on the build host's initiated_by_id NOT starting with "card:" (i.e., only space-initiated builds — side_job/farm_expansion — qualify). Which discriminator do you prefer, and should this generalize to a reusable "in-turn build" predicate for future cards with the same clause?
- **ordering_note:** after_build_stables fires ONCE per build-stables host session (at the Proceed work-complete flip via _enter_after_phase), independent of the number of stables — correctly matching "build 1 or more stables in one turn", NOT per-piece. The trap: Groom (implemented, groom.py) builds an off-turn stable at start_of_round by pushing the IDENTICAL PendingBuildStables primitive, and _complete_preparation sets phase=Phase.WORK before pushing the PendingPreparation host (engine.py line 1034 vs the step-5 push), so phase cannot tell the two apart. The clarification ("stables built off-turn ... do not trigger this card") therefore REQUIRES a stack/provenance-based eligibility check (e.g. a PendingPreparation frame beneath the build host, or initiated_by_id == "card:groom"), which no existing card does — this is the load-bearing decision to confirm with the user.

### A41 Vegetable Slicer

- **blocker_group:** build_payment_provenance
- **reason:** Trigger must fire only on the Fireplace-RETURN payment path, but the after_build_major trigger machinery never receives commit.payment, and the post-build state can't distinguish "upgraded from my Fireplace" from "never owned a Fireplace."
- **ordering_note:** "Upgrade a Fireplace to a Cooking Hearth" is specifically the ReturnImprovement(fp) payment route (commit.payment), NOT building a Cooking Hearth (major_idx 2/3) by paying clay. A player who owns a Fireplace may build a CH with clay and keep the Fireplace — that is NOT an upgrade and must not fire. The prior hypothesis (fire on any CommitBuildMajor with major_idx in COOKING_HEARTH_INDICES) is wrong: it triggers on the clay path and ignores the actual discriminator.

### A95 Angler

- **blocker_group:** consumed_space_amount_snapshot
- **reason:** The "≤2 food on that space" threshold is checked AFTER use, but _resolve_food_accumulation zeroes fishing's accumulated_amount on use and no frame retains the catch amount — the condition is unobservable without new infra (a host-frame snapshot field / CardStore before→after read).
- **open_question:** Confirm the intended reading of "at most 2 food on that space": standard interpretation is the catch (printed-plus-accumulated food the player took) was ≤2, snapshotted before the take. Also: should the snapshot be taken before or after before-phase income cards that touch fishing (e.g. Canoe's +1 food goes to the player, not the space, so it shouldn't count — confirm)? And do you want the new before→after snapshot stored as a PendingActionSpace field or via CardStore?
- **ordering_note:** Two subtleties for whoever builds it later: (1) "after you use ... while there are at most 2 food on that space" — fishing's accumulated_amount is already 0 in the after phase (resolution.py:155-162 resets it on take), so eligibility must compare against a value snapshotted in the before phase, i.e. the food the player just collected (printed 1/round + leftovers). (2) The grant is an OPTIONAL improvement action — surface it as an after_action_space FireTrigger (decline via host Stop), once-per-use via triggers_resolved, mirroring ox_goad/basket; PendingMajorMinorImprovement already exists. The improvement push is buildable; only the threshold read is blocked.

### A97 Freshman

- **blocker_group:** action_substitution
- **reason:** "instead of taking the [Bake Bread] action, you can play an occupation" is action SUBSTITUTION, not the additive PendingBakeBread grant the proposed before_bake_bread/template approach assumes. No substitution machinery exists, and the clarification forces a legality change.
- **open_question:** Confirm the intended scope of "each time you get a Bake Bread action": does it cover only Grain Utilization's own bake, or every granted bake (Oven Firing Boy, Bread Paddle, Threshing Board, Clay/Stone Oven free-bakes) — i.e. wherever a PendingBakeBread would be pushed? And should the once-per-turn cap interact across those sources? This determines how broad the new substitution hook must be.
- **ordering_note:** The proposed before_bake_bread + push PendingPlayOccupation is wrong twice over: (1) a before_bake_bread trigger only fires once a PendingBakeBread frame already exists, so it ADDS an occupation play but does NOT suppress the bake — the player still faces CommitBake afterward, contradicting "instead of." (2) The clarification ("may use Grain Utilization while unable to Sow or Bake Bread, as this card substitutes the Bake Bread action") requires offering the substitute even when _can_bake_bread is False — a before_bake_bread trigger can never reach that state because ChooseSubAction("bake_bread") is gated on _can_bake_bread. So Freshman must make a "play occupation instead of baking" CHOICE legal at every Bake Bread offer site (ChooseSubAction("bake_bread") at Grain Utilization, AND the granted PendingBakeBread pushes from Oven Firing Boy / Bread Paddle / Threshing Board / Clay-Stone Oven), pushing PendingPlayOccupation(cost=Resources()) in place of the bake. Note BAKE_BREAD_ELIGIBILITY_EXTENSIONS only broadens can-bake; it cannot introduce a substitute action.

### B5 Store of Experience

- **blocker_group:** passing_minor_status
- **reason:** Effect is a trivial tiered on_play, but whether this is a TRAVELING (passing) minor is unresolved: the JSON passing_left field is unreliable and passing changes scoring + ownership.
- **open_question:** Is Store of Experience a TRAVELING/passing minor (passed to the opponent after play, like Market Stall), or a kept improvement? The card text gives no passing instruction (traveling status is the card's frame icon in real Agricola), and the JSON passing_left:"X" marker is proven unreliable in this dataset — it appears on genuinely-traveling cards (Market Stall, Young Animal Market) AND on kept cards (Mini Pasture, Sleeping Corner, Field Fences, all implemented WITHOUT passing_left=True). Once you confirm traveling vs kept, this is a ~15-line implement: register_minor(card_id, passing_left=<answer>, on_play=tiered-grant), template consultant.py/market_stall.py.
- **ordering_note:** The effect itself is settled and not the blocker: text reads "occupations left in hand" = len(state.players[idx].hand_occupations) (UNPLAYED occupations remaining), NOT len(occupations) (played). Tiers map by that count: 0-4 -> Resources(stone=1); exactly 5 -> Resources(reed=1); exactly 6 -> Resources(clay=1); exactly 7 -> Resources(wood=1) (use n<=4 / ==5 / ==6 / else, since 7 is the deal max). consultant.py / market_stall.py on_play shape. cost=Cost() (cost null), vps=0 (null), no prereq. The ONLY open bit is passing_left.

### B1 Upscale Lifestyle

- **blocker_group:** optional_renovate_grant
- **reason:** The granted "Renovation" action is OPTIONAL ("If you take the action..."), but a bare PendingRenovate pushed on-play is MANDATORY: its before-phase enumerator (legality.py:1672-1676) emits only CommitRenovate options and NO Stop, so there is no decline path. No existing frame makes an on-play renovate declinable.
- **open_question:** Confirm the preferred decline mechanism for an on-play optional renovate: an optional choose-or-decline wrapper frame (mirroring the existing PendingGrantedBuildFences for granted fences), versus adding a guarded Stop to PendingRenovate's before-phase. The former is the consistent pattern but is new infra; the latter risks affecting House Redevelopment/Cottager, where an entered renovate is not declinable.
- **ordering_note:** The +5 clay is unconditional and is granted BEFORE the optional renovate, so the new clay is spendable on the renovation cost — important since renovation pays a per-room building material; the clay grant must land first (which on_play ordering gives naturally). Also passing_left=True (the hypothesis missed this — passing_left:"X" in the JSON): the card travels to the opponent after play.

### B7 Wage

- **blocker_group:** bottom_row_major_classification
- **reason:** Mechanic is a trivial on-play food gain, but it needs a NEW shared classification (which of the 10 majors are "bottom row of the supply board") that does not exist in the code and whose exact membership is a load-bearing rules fact I should not guess.
- **open_question:** Which of the 10 major-improvement indices (0 Fireplace2c, 1 Fireplace3c, 2 CookingHearth4c, 3 CookingHearth5c, 4 Well, 5 ClayOven, 6 StoneOven, 7 Joinery, 8 Pottery, 9 Basketmaker) count as "bottom row of the supply board"? My proposed mapping from the standard Revised layout is bottom-row = {5 Clay Oven, 6 Stone Oven, 7 Joinery, 8 Pottery, 9 Basketmaker's Workshop} and top-row = {0,1,2,3,4} (the four cooking-baking Fireplaces/Hearths plus Well). I want you to confirm this — especially whether Well (idx 4) is top-row or bottom-row — before I hard-code BOTTOM_ROW_MAJORS, since at least 3 other cards (the occupation that builds bottom-row majors at the Minor action, and a 3/4/5-bottom-row scoring minor) will reuse the same constant.
- **ordering_note:** "each major improvement you have from the bottom row" = count, over major indices 0-9, those where BoardState.major_improvement_owners[i] == idx AND i is a bottom-row major. Gain is 2 + that count food. The only real subtlety is which indices are bottom-row; the mechanic itself has no before/after or accommodation concerns.

### B9 Beating Rod

- **blocker_group:** minor_play_variant_choice
- **reason:** A MINOR with an on-play binary CHOICE (get 1 reed OR exchange 1 reed for 1 cattle) — the wide play-variant machinery is occupation-only; no minor-variant path exists. Also a net +1 immediate animal grant.
- **open_question:** Two ways forward, your call: (a) add a PLAY_MINOR_VARIANTS registry mirroring PLAY_OCCUPATION_VARIANTS (variant threaded through CommitPlayMinor / _execute_play_minor / the minor enumerator) so on-play-choice minors become buildable as a class; or (b) one-off model Beating Rod with a self-pushed PendingCardChoice in its on_play. Also: is a net +1 immediate animal grant (reed→cattle, unlike Young Animal Market's net-zero sheep→cattle swap) acceptable given the engine doesn't force accommodation on gain?
- **ordering_note:** none

### B29 Cookery Lesson

- **blocker_group:** at_any_time_conversion
- **reason:** Condition is "USE a cooking improvement on the same turn" (not own one); using a cooking improvement = an at-any-time food conversion the engine deliberately never surfaces as an action, so there is no event to detect, and it must co-occur with a Lessons placement in one turn.
- **open_question:** Confirmed defer; no blocking question. If you later want it, the real design choice is whether to surface an explicit at-any-time "cook food via a cooking improvement" action on a Lessons turn (which the engine currently refuses to model) versus reinterpreting "use a cooking improvement" as merely owning one or having cooked via it at some harvest, which would be rules-wrong.
- **ordering_note:** If ever built: the trigger is on the LESSONS placement (before_action_space, space_id=="lessons"), and "+1 bonus point" must be BANKED into CardStore at fire time then read by register_scoring (no printed VPs) — it is NOT an end-game derived count, since "use" events are play-time. The hard part is the co-condition: you must additionally know a cooking improvement was used THIS TURN, and the Lessons turn (play an occupation) never contains a cooking step, so the two uses essentially never co-occur in the current turn model.

### B35 Hook Knife

- **blocker_group:** resource_threshold_latch
- **reason:** "Once this game, when you have 8 sheep" is a high-water-mark latch on SHEEP COUNT, but the existing conditional one-shot sweep (_fire_ready_one_shots) only fires at three house-material seams (play-occupation, play-minor, renovate) — never when sheep count changes (animal markets, breeding, harvest feeding), so the latch would never fire at the right moment.
- **open_question:** Two implementation routes for a sheep-count latch: (a) call _fire_ready_one_shots at every animal-count-increasing site (sheep_market resolve, harvest breed, plus any animal grants) — generalizes the existing latch but adds several engine call sites; or (b) a dedicated high-water-mark-on-resource latch mechanism. Which infra direction do you prefer, and should it be built generically for the Bubulcus deck's likely sibling cards (boar/cattle/grain/veg thresholds)?
- **ordering_note:** "Once this game" means the 2 VP latch the FIRST moment sheep>=8 and is KEPT even if sheep later drop below 8 (e.g. paid for feeding/sold). So a naive end-game register_scoring `sheep>=8 -> +2` is WRONG (misses players who peaked at 8 then dropped). A real latch is required — and it must be evaluated at every sheep-increasing event, which is exactly the seam the current latch infra lacks.

### B41 Hauberg

- **blocker_group:** minor_play_variant
- **reason:** "You decide what to start with" is a play-time binary variant (wood-first vs boar-first) that minors cannot express: CommitPlayMinor has no `variant` field, there is no PLAY_MINOR_VARIANTS registry, _enumerate_pending_play_minor emits no per-variant commits, and _execute_play_minor calls on_play(state, idx) with no variant. That mechanism exists only for occupations.
- **open_question:** Want me to build the small minor play-variant mechanism (a `variant` field on CommitPlayMinor + a PLAY_MINOR_VARIANTS registry + per-variant enumeration in _enumerate_pending_play_minor + variant-passing in _execute_play_minor, plus a one-line C++ re-port), which would unblock this whole "you decide what to start with" card family? Separately: Acorns Basket (B84) appears mis-deferred — its only blocker (round-start animal accommodation as a decision point) is now shipped+tested, so it just needs a trivial `schedule_animals` helper and no variant choice. Should I revisit it?
- **ordering_note:** If/when built: the "alternate" + "you decide what to start with" means exactly two schedules across rounds R+1..R+4 (capped at 14): wood-first = [2 wood, 1 boar, 2 wood, 1 boar], boar-first = [1 boar, 2 wood, 1 boar, 2 wood], offsetting odd/even slots. Wood rides on future_resources via schedule_resources; boar must ride on FutureReward.animals (future_rewards). Round-start boar housing is deterministic Pareto-best with NO player decision (engine._collect_future_rewards, already shipped+tested) — do NOT add an overflow decision frame. "Next 4 round spaces" = R+1..R+4, not absolute rounds.

### B49 Scales

- **blocker_group:** passing_minor_after_event
- **reason:** Cannot honor the "passing cards never trigger this" clarification: after_build_improvement/after_play_minor fire unconditionally for passing minors, but the auto eligibility sig is only (state, owner) — it can't tell a passing-card fire from a coincidentally-equal count, so a passing minor would false-award +2 food.
- **open_question:** Confirm the intended fix for the passing-minor exclusion: my lean is a tiny new event/signal that distinguishes a non-passing minor landing in the tableau from any minor play (e.g. thread the triggering card_id into the auto eligibility signature, add a dedicated after_play_kept_minor event fired only when minor_improvements actually grew, or stash the just-played card on the actor for the eligibility fn to read). Which shape do you prefer? Also confirm "improvements" should include majors (I read it as minors+majors per standard Agricola).
- **ordering_note:** "improvements" = minors + majors (majors are NOT on PlayerState; they live on board.major_improvement_owners — count via sum(1 for o in owners if o==idx), plus len(minor_improvements)); "occupations" = len(occupations). The newly-played card IS already in its tableau set before the after-event fires (verified: occ added at resolution.py 513-517 before _enter_after_phase at 529; minor added at 554-559 before 573; major owner set at 1384-1387 before 1404), so a same-state count-equality check is correct for non-passing plays. The error-prone subtlety that BLOCKS it: a passing minor is NOT added to minor_improvements (gated at resolution.py 558) yet still fires after_build_improvement/after_play_minor (573-574 unconditional), so the count is unchanged and a pre-existing equality would wrongly re-award +2 — exactly the case the clarification forbids.

### B70 New Purchase

- **blocker_group:** food_to_good_buy
- **reason:** "Pay food → buy a crop" standalone action: 2 food→1 grain and/or 4 food→1 veg at round start. Same food→good buy family the design explicitly defers (§15 Clay Carrier = 2 food→2 clay), no implemented template, plus a novel two-independent-optional-buys choice structure.
- **open_question:** Two design calls for you: (a) Should a standalone "pay food → buy a crop" action be surfaced at all? It is the same food→good buy family you flagged as the hardest OPEN/UNRESOLVED problem in CARD_SYSTEM_DESIGN.md §15 (Clay Carrier 2 food→2 clay is structurally identical, and unimplemented), and surfacing a speculative food→crop buy runs against the engine's preserve-optionality principle (the bought crop isn't tied to a decision point that needs it). New Purchase is milder than Grocer/Clay Carrier because it is round-start-gated (not "at any time"), so it does NOT create the §15 affordability-closure problem — would you accept it as the first member of this family on those grounds? (b) If yes, is the two-independent-optional-buys-at-one-host pattern (two separate latched optional triggers) acceptable, or do you want a dedicated buy-choice frame?
- **ordering_note:** Two subtleties for whoever later builds it. (1) Timing: "before the start of each round that ends with a harvest" maps to the start_of_round hook (PendingPreparation host) gated to HARVEST_ROUNDS={4,7,9,11,13,14} — fires at the round-entry boundary BEFORE that round's WORK, so the bought crops are available for that round (incl. its harvest feeding). (2) The hard part: the player may buy grain AND/OR veg INDEPENDENTLY, each optional, each a different fixed price (2 food / 4 food), each at most once. This is NOT a forced single pick (so PendingCardChoice/Childless shape is wrong) and not a single grant (so the single-FireTrigger Plow-Driver shape is incomplete). The plausible build is TWO separate optional start_of_round triggers (grain-buy + veg-buy) with distinct used_this_round latch keys, each declinable via the host Proceed; price paid directly from supply (food held), no conversion-closure needed since it's a direct food spend.

### B76 Ceilings

- **blocker_group:** scheduled_goods_provenance
- **reason:** The "remove the wood promised by THIS card on next renovate" clause has no expressible mechanism: future_resources is a flat additive tuple[Resources,...] with zero per-card provenance, so a blind wood-subtract is silently wrong when any other wood-scheduler or a 2nd copy wrote the same slots, and there is no record of which of its own 5 slots remain unpaid.
- **open_question:** Do you want to add per-card provenance to the future-resource schedule (e.g. a CardStore record of exactly which round slots Ceilings seeded, decremented as each pays out at round-start) so the after_renovate hook can remove its own remaining wood precisely? That is the new shared infra this card needs, and it would generalize to any future "take back promised goods" card.
- **ordering_note:** If ever built: the removal must clear ONLY this card's still-unpaid slots (rounds already collected at round-start must NOT be re-subtracted), fire only on the FIRST renovate after play, and never touch other cards' wood on the same slots. Resources.__sub__ permits negatives, so a naive subtract corrupts silently rather than erroring.

### B82 Value Assets

- **blocker_group:** at_any_time_conversion
- **reason:** Core effect is a standalone buy-food→building-resource conversion (the engine deliberately never surfaces these), AND "after each harvest" has no timing anchor — the only harvest hook (harvest_field) fires BEFORE the crop take, not after.
- **open_question:** Two design decisions are needed: (1) how to surface an optional, choose-at-most-one buy-food→resource purchase (a new income-conversion mechanism / a PendingCardChoice-style frame, since the existing cost-modifier registries only modify BUILD costs, not free-standing purchases); and (2) where to host an "after each harvest" per-player optional decision — a post-harvest (post-BREED, pre-PREPARATION) hook does not exist today. Should I add a generic "after_harvest" host frame, or model this as a deferred/scheduled choice? This likely clusters with other post-harvest food-purchase cards.
- **ordering_note:** none

---

## Defers clustered by blocker_group

### action_substitution

- **A97 Freshman** — "instead of taking the [Bake Bread] action, you can play an occupation" is action SUBSTITUTION, not the additive PendingBakeBread grant the proposed before_bake_bread/template approach assumes. No substitution machinery exists, and the clar…

### at_any_time_conversion

- **B29 Cookery Lesson** — Condition is "USE a cooking improvement on the same turn" (not own one); using a cooking improvement = an at-any-time food conversion the engine deliberately never surfaces as an action, so there is no event to detect, and it must co-occur…
- **B82 Value Assets** — Core effect is a standalone buy-food→building-resource conversion (the engine deliberately never surfaces these), AND "after each harvest" has no timing anchor — the only harvest hook (harvest_field) fires BEFORE the crop take, not after.

### bottom_row_major_classification

- **B7 Wage** — Mechanic is a trivial on-play food gain, but it needs a NEW shared classification (which of the 10 majors are "bottom row of the supply board") that does not exist in the code and whose exact membership is a load-bearing rules fact I should…

### build_payment_provenance

- **A41 Vegetable Slicer** — Trigger must fire only on the Fireplace-RETURN payment path, but the after_build_major trigger machinery never receives commit.payment, and the post-build state can't distinguish "upgraded from my Fireplace" from "never owned a Fireplace."

### consumed_space_amount_snapshot

- **A95 Angler** — The "≤2 food on that space" threshold is checked AFTER use, but _resolve_food_accumulation zeroes fishing's accumulated_amount on use and no frame retains the catch amount — the condition is unobservable without new infra (a host-frame snap…

### food_to_good_buy

- **B70 New Purchase** — "Pay food → buy a crop" standalone action: 2 food→1 grain and/or 4 food→1 veg at round start. Same food→good buy family the design explicitly defers (§15 Clay Carrier = 2 food→2 clay), no implemented template, plus a novel two-independent-o…

### minor_play_variant

- **B41 Hauberg** — "You decide what to start with" is a play-time binary variant (wood-first vs boar-first) that minors cannot express: CommitPlayMinor has no `variant` field, there is no PLAY_MINOR_VARIANTS registry, _enumerate_pending_play_minor emits no pe…

### minor_play_variant_choice

- **B9 Beating Rod** — A MINOR with an on-play binary CHOICE (get 1 reed OR exchange 1 reed for 1 cattle) — the wide play-variant machinery is occupation-only; no minor-variant path exists. Also a net +1 immediate animal grant.

### off_turn_build_exclusion

- **A43 Farmyard Manure** — Printed clarification forbids triggering on OFF-TURN stable builds (Groom B089, which IS implemented), but Groom's round-start build pushes the same PendingBuildStables host that fires after_build_stables — and phase is already WORK at that…

### optional_renovate_grant

- **B1 Upscale Lifestyle** — The granted "Renovation" action is OPTIONAL ("If you take the action..."), but a bare PendingRenovate pushed on-play is MANDATORY: its before-phase enumerator (legality.py:1672-1676) emits only CommitRenovate options and NO Stop, so there i…

### passing_minor_after_event

- **B49 Scales** — Cannot honor the "passing cards never trigger this" clarification: after_build_improvement/after_play_minor fire unconditionally for passing minors, but the auto eligibility sig is only (state, owner) — it can't tell a passing-card fire fro…

### passing_minor_status

- **B5 Store of Experience** — Effect is a trivial tiered on_play, but whether this is a TRAVELING (passing) minor is unresolved: the JSON passing_left field is unreliable and passing changes scoring + ownership.

### resource_threshold_latch

- **B35 Hook Knife** — "Once this game, when you have 8 sheep" is a high-water-mark latch on SHEEP COUNT, but the existing conditional one-shot sweep (_fire_ready_one_shots) only fires at three house-material seams (play-occupation, play-minor, renovate) — never…

### scheduled_goods_provenance

- **B76 Ceilings** — The "remove the wood promised by THIS card on next renovate" clause has no expressible mechanism: future_resources is a flat additive tuple[Resources,...] with zero per-card provenance, so a blind wood-subtract is silently wrong when any ot…
