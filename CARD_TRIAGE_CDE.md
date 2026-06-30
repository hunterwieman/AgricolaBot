# Card Triage — Corbarius (C) / Dulcinaria (D) [partial] — from-scratch (2026-06-30)

Triage of unimplemented C/D cards. The C/D/E run hit the monthly spend limit during deck D, so deck D
is partial and deck E was not reached. Raw specs: `card_triage_cde_specs.json` (+ session scratchpad
`triage_cde/<deck>_<num>.json`). Drives the implement pass.

## Deck C — 61 implement / 101 defer (162 triaged)

### Implement

#### potato_harvester  (tier 1, occupation, conf high) — C_106.json
- template: agricola/cards/scythe_worker.py (occupation on-play food + register_auto('harvest_field') + register_harvest_field_hook). Potato Harvester is strictly simpler than scythe_worker because its harvest clause only COUNTS the mechanical take rather than modifying fields.
- plan: register_occupation(CARD_ID, _on_play) where _on_play credits +3 food to player idx. _eligible(state, idx) -> any FIELD cell with veg>0 (those are the veg taken this harvest). _apply(state, idx): count FIELD cells with veg>0 (each yields exactly 1 veg in the mechanical take, since a field is sown grain XOR veg and grain takes precedence), credit that many food (no field mutation). register_auto('harvest_field', CARD_ID, _eligible, _apply) + register_harvest_field_hook(CARD_ID). No cost/prereq/vps/passing on the occupation (just on-play + scoring-neutral harvest reward).
- ordering: The harvest_field auto fires BEFORE the mechanical crop take (_fire_harvest_field_hook runs first inside _resolve_harvest_field), so fields are still sown when _apply runs — count veg fields THERE, not after. Unlike scythe_worker, _apply must NOT decrement the fields: it only awards food for the veg the normal take will harvest. Count is per veg-field (each veg-field gives exactly 1 veg per harvest because grain takes precedence and a field holds grain XOR veg), so 'for each vegetable you get from your fields' = count of FIELD cells with veg>0.
- errata: None reported by card_text.py (no errata/clarifications printed). Card is Consul Dirigens expansion, deck C #106, Food Provider, players 1+.
- open_q: Confirm '1 additional food per vegetable' counts only the SINGLE veg the mechanical take removes from each veg-field this harvest (i.e. fields are not double-harvested) — the engine takes exactly 1 crop per field per harvest, so the food bonus equals the number of veg-sown fields. This matches the rules reading; no ambiguity expected.

#### small_animal_breeder  (tier 1, occupation, conf high) — C_111.json
- template: agricola/cards/scullery.py (start_of_round register_auto + register_start_of_round_hook; condition re-checked each round)
- plan: register_occupation(CARD_ID, on_play=lambda s,i: s)  # no on-play effect.
_eligible(state, idx) -> state.players[idx].resources.food >= state.round_number  # round_number is already the round being entered when start_of_round autos fire.
_apply(state, idx): p=fast_replace(state.players[idx], resources=p.resources+Resources(food=1)); return fast_replace(state, players=tuple-swap).
register_auto('start_of_round', CARD_ID, _eligible, _apply); register_start_of_round_hook(CARD_ID).  # no cost/prereq/vps/passing (occupation).
- ordering: The 'current round number' is the round being ENTERED, not the one just finished. Verified in engine.py: _complete_preparation increments round_number to new_round (line 981/1031) BEFORE _push_preparation_hosts fires the start_of_round autos, so at firing time state.round_number == the round about to be played. Compare food >= state.round_number directly (no +1). Mandatory choice-free (use register_auto, not register), and the condition is re-checked every round so income switches on/off with the player's food level. Income is granted AFTER that round's future_resources are already added (step 2 of _complete_preparation), so 'have food >= round' is evaluated on the post-distribution food total, which matches the card (you check your food at the start of the round).
- errata: No errata. Clarification baked into card text: 'e.g., 8+ food in round 8'.

#### wood_collector  (tier 1, occupation, conf high) — C_118.json
- template: agricola/cards/estate_worker.py (and lumberjack.py deferred half) — Category 8 deferred-goods-on-round-spaces via schedule_resources
- plan: register_occupation('wood_collector', _on_play). _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R+1, R+6), Resources(wood=1)). No cost/prereq/vps/passing (all defaults). schedule_resources clamps rounds >14 (silently drops), matching 'each of the next 5 round spaces' near game end. Verified schedule_resources exists in agricola/cards/schedules.py (1-indexed rounds, additive, slot r-1, drops out-of-range).
- ordering: The 'next 5 round spaces' are rounds R+1..R+5 (R = current round_number at play time), so use range(R+1, R+6) — NOT range(R, R+5) and NOT round_number-based off-by-one. schedule_resources uses 1-indexed rounds (slot r-1, the Well index convention) and silently drops any round >14, so a late play correctly places on only the remaining future round spaces. Collection is automatic at start-of-round via engine._complete_preparation reading future_resources — no start_of_round hook to register (resources, unlike effect-cards, need no trigger).
- errata: none — no clarifications/errata on this card. (Note: 'Wood Collector' is distinct from 'Firewood Collector' [A119, end-of-turn +1 wood on certain spaces] and 'Brushwood Collector' [B145]; do not conflate.)

#### skillful_renovator  (tier 1, occupation, conf high) — C_119.json
- template: consultant.py (on-play goods) + maintenance_premium.py (after_renovate register_auto granting goods)
- plan: register_occupation(CARD_ID, _on_play) where _on_play adds Resources(wood=1, clay=1) to the player (Consultant pattern). register_auto('after_renovate', CARD_ID, _eligible, _apply): _eligible returns True (owner gate is applied by apply_auto_effects, no prereq/cost on this card). _apply computes placed = p.people_total - p.newborns - p.people_home (people placed this round), then adds Resources(wood=placed) to the player. No cost, no prereq, no vps, not passing. Mandatory choiceless (text says 'you get', no downside) -> register_auto, not register.
- ordering: The 'number of people you placed that round' = people_total - newborns - people_home, computed at after_renovate time. This is correct because: (1) a renovate is reached via a PlaceWorker (house/farm redevelopment) which decrements people_home BEFORE the renovate frame is pushed (resolution.py:124), so the worker that triggered this renovate is already counted -> matches the clarification '3rd placed person -> 3 wood'. (2) newborns must be subtracted (clarification: 'Newborns are not placed'); newborns are included in people_total and not cleared until next round's preparation, so they would otherwise inflate the count. (3) people_home is reset to people_total at end-of-round (_resolve_return_home, engine.py:858), so the per-round count is correct. after_renovate (not before) is the right hook (fires once post-application, per the Mining Hammer / Roughcaster / Maintenance Premium renovate convention).
- errata: Clarifications: 'If you renovate with your 3rd placed person of a round, this card triggers a payout of 3 wood. Newborns are not placed.' Card text: 'When you play this card, you immediately get 1 wood and 1 clay. Each time after you renovate, you get a number of wood equal to the number of people you placed that round.' Deck C #119, Consul Dirigens Expansion, category Building Resource Provider.

#### clay_kneader  (tier 1, occupation, conf high) — C_121.json
- template: agricola/cards/clay_puncher.py (near-exact: on-play goods grant + after_action_space auto +1 clay on atomic-hosted spaces). corn_scoop.py confirms the grain_seeds/vegetable_seeds hook shape.
- plan: register_occupation(CARD_ID, _grant_on_play) where _grant_on_play does p.resources + Resources(wood=1, clay=2) (the immediate +1 wood +2 clay).
Separately _grant_clay(state, idx) = p.resources + Resources(clay=1).
_eligible(state, idx) -> state.pending_stack[-1].space_id in {'grain_seeds','vegetable_seeds'}.
register_auto('after_action_space', CARD_ID, _eligible, _grant_clay)  # mandatory choiceless +1 clay.
register_action_space_hook(CARD_ID, {'grain_seeds','vegetable_seeds'})  # both ATOMIC, must be hosted.
No cost/prereq/vps/passing (plain on-play occupation, players 1+).
- ordering: Text reads 'Each time AFTER you use' -> the recurring grant MUST ride after_action_space (NOT before_action_space). corn_scoop uses before_action_space precisely because its text omits 'after'; clay_puncher uses after_action_space for the same 'after you use' wording. Wrong event = clay granted before the seed pickup instead of after; both spaces are atomic so they require register_action_space_hook to surface the after-phase (non-atomic auto-hosting does not apply). On-play wood+clay is a separate one-time register_occupation grant, independent of the hook.
- errata: No errata/clarifications surfaced by card_text.py. (Unlike clay_puncher, which carries a '1+1=2 on Lessons' clarification — not applicable here since neither hooked space is a play-card space.)

#### freemason  (tier 1, occupation, conf high) — C_123.json
- template: agricola/cards/small_scale_farmer.py (start_of_round register_auto + register_start_of_round_hook, exactly-2-rooms gate); house-material check pattern from agricola/cards/priest.py
- plan: register_occupation("freemason", lambda s,i: s)  # no on-play effect. _num_rooms(p)=count CellType.ROOM cells (3x5 grid), as in priest/small_scale_farmer. _eligible(state, idx): material = state.players[idx].house_material; return _num_rooms(p)==2 and material in (HouseMaterial.CLAY, HouseMaterial.STONE). _apply(state, idx): p=state.players[idx]; gain = Resources(clay=2) if p.house_material is HouseMaterial.CLAY else Resources(stone=2); p=fast_replace(p, resources=p.resources+gain); write player back. register_auto("start_of_round", "freemason", _eligible, _apply); register_start_of_round_hook("freemason"). No cost/prereq/vps/passing (plain occupation).
- ordering: Grant is MANDATORY/choiceless ('you get', not 'you can') -> register_auto, NOT register/FireTrigger (cf. cob which uses register because it says 'you can'). The grant TYPE/AMOUNT is material-conditioned: clay house -> +2 clay, stone house -> +2 stone, wood house -> nothing -- the 'clay/stone' and '2 clay/stone' X/Y notation must be split by house_material inside _apply, with the wood case excluded by _eligible. Condition is re-checked every round in _eligible (income auto-stops on renovate to wood or room-count change); no used_this_round latch needed since the engine fires start_of_round once per owner per round.
- errata: Clarification (not errata): 'Cards that provide room for a person do not count for this effect unless they self-identify as a room.' -> count only true CellType.ROOM cells, exactly as priest/small_scale_farmer/childless already do; no special handling needed since no implemented card grants a non-room living space.

#### soldier  (tier 1, occupation, conf high) — C_133.json
- template: agricola/cards/stable_architect.py (pure end-game scoring occupation: register_occupation no-op + register_scoring)
- plan: register_occupation('soldier', lambda state, idx: state)  # no on-play effect; played via Lessons.
def _score(state, idx): r = state.players[idx].resources; return min(r.wood, r.stone)  # 1 VP per stone-wood pair in supply.
register_scoring('soldier', _score).
No cost/prereq/vps/passing (occupation). Resources fields verified: r.wood, r.stone on state.players[idx].resources.
- ordering: Score is the number of PAIRS = min(wood, stone), NOT wood+stone. The errata clause 'you cannot score additional points for the resources scored with this card' is a no-op in this engine: base scoring (scoring.py) never scores raw wood/stone in supply (it scores fields/pastures/animals/rooms/people/majors/craft-bonuses/begging). The craft-building bonus consumes resources into built rooms rather than scoring the raw pile, so there is no double-count path to suppress.
- errata: Card text: 'During scoring, you get 1 bonus point for each stone-wood pair in your supply. You cannot score additional points for the resources scored with this card.' Corbarius Expansion, deck C #133, players 3+, category Points Provider. No printed cost/prereq/vps/passing.
- open_q: Card is printed 'players 3+'. Confirm it should be included in the 2-player card pool at all (the no-other-resource-scoring clause is moot in 2p anyway, so the effect is identical) -- but pool-inclusion of a 3+ card is a curation question, not a mechanics blocker.

#### sheep_provider  (tier 1, occupation, conf high) — C_141.json
- template: agricola/cards/catcher.py (occupation no-op on-play + before_action_space auto) crossed with agricola/cards/corf.py (any_player=True owner-fires-on-opponent-turn, +1 goods) and agricola/cards/claw_knife.py (same sheep_market space, confirms NO register_action_space_hook needed)
- plan: register_occupation('sheep_provider', lambda state, idx: state)  # no-op on play; the hook IS the effect. _eligible(state, idx): return state.pending_stack[-1].space_id == 'sheep_market'. _apply(state, idx): p = fast_replace(state.players[idx], resources=state.players[idx].resources + Resources(grain=1)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). register_auto('before_action_space', 'sheep_provider', _eligible, _apply, any_player=True). Occupation has no cost/prereq/vps. Add module import to cards/__init__.py.
- ordering: Two coupled subtleties: (1) any_player=True is REQUIRED — 'each time ANY player (including you) uses Sheep Market' means the owner gains grain on the OPPONENT's Sheep Market turn too; apply_auto_effects iterates owners=range(2) only when any_player is set (triggers.py:138). (2) Despite any_player, NO register_action_space_hook is needed: sheep_market is NON-ATOMIC and self-hosts — _initiate_sheep_market (resolution.py:364-376) calls apply_auto_effects(state,'before_action_space',ap) on every use including the opponent's, so the host frame already exists (the hook index only conditionally hosts ATOMIC spaces; verified vs Claw Knife / Milk Jug). Adding the hook would be harmless-but-wrong noise. Grain has no capacity limit so the +1 grant is always safe; before- vs after-phase is immaterial here (pure goods grant, not threshold-on-accumulated like Corf).
- errata: Printed text reads 'players 3+' (Corbarius Expansion crop-provider). This restriction is irrelevant in the 2-player engine and has no mechanical effect — implement normally. No errata/clarification on the effect itself; card_text.py shows status todo.

#### market_crier  (tier 1, occupation, conf high) — C_142.json
- template: agricola/cards/brewing_water.py (optional before_action_space trigger on an atomic space, goods grant) + agricola/cards/milk_jug.py (the 'other = 1 - idx' opponent-grant pattern); corn_scoop.py is the same grain_seeds atomic-host structure but mandatory.
- plan: register_occupation('market_crier', lambda s, i: s)  # no on-play effect.
register_action_space_hook('market_crier', frozenset({'grain_seeds'}))  # host the atomic Grain Seeds space when owned.
register('before_action_space', 'market_crier', _eligible, _apply)  # OPTIONAL declinable FireTrigger ('you can get'); decline = host Proceed.
_eligible(state, idx, triggers_resolved): CARD_ID not in triggers_resolved (once per use) AND pending_stack[-1].space_id == 'grain_seeds'. No resource gate (pure gain).
_apply(state, idx): self gets Resources(grain=1, veg=1); other = 1 - idx gets Resources(grain=1) (milk_jug pattern, both in one atomic apply). No cost/prereq/vps/passing.
- ordering: Must be OPTIONAL (register, not register_auto) because 'if you do, each other player gets 1 grain' is a real downside the owner may want to decline late game — corn_scoop's mandatory register_auto would be wrong. The self-grant (grain+veg) and the opponent's grain MUST resolve together in the single _apply: 'if you do' couples them, so you cannot take your grain/veg and skip giving the opponent grain. Use the optional-trigger arity: _eligible(state, idx, triggers_resolved) 3-arg, _apply(state, idx) 2-arg. before_action_space (per 'each time you use [space]' ruling, no 'immediately after'); the once-per-use semantics come from the host's triggers_resolved guard.
- errata: None reported by card_text.py (no errata/clarifications section emitted). Printed 'players 3+' (Consul Dirigens), but the slug is registered for the 2-player card game; in 2p 'each other player' is exactly the single opponent (other = 1 - idx) — well-defined, no scaling needed.
- open_q: Card is printed for 3+ players; confirm it is in-scope for the 2-player pool (mechanics are fully well-defined for 2p — one opponent). No engine blocker either way.

#### cowherd  (tier 1, occupation, conf high) — C_147.json
- template: agricola/cards/milk_jug.py (Milk Jug, A50 — Cattle Market before_action_space auto) + feeding_dish.py (confirms the gained-staging mechanism); on-play no-op like catcher.py
- plan: register_occupation('cowherd', _on_play) where _on_play is identity (no-op). register_auto('before_action_space', 'cowherd', _eligible, _apply) with any_player=False (owner-only, 'each time YOU use'). _eligible(s,i): return s.pending_stack[-1].space_id == 'cattle_market'. _apply(s,i): top = s.pending_stack[-1]; return replace_top(s, fast_replace(top, gained=top.gained + 1)). No cost/prereq/vps/passing — occupations played via Lessons. Imports: register_occupation (specs), register_auto (triggers), replace_top (pending), fast_replace (replace).
- ordering: DO NOT add cattle directly to player.resources/animals. _initiate_cattle_market stages the picked-up cattle on PendingCattleMarket.gained (an int, NOT on the player) and fires before_action_space with that frame ON TOP of the stack, BEFORE CommitAccommodate moves them onto the player. Cowherd must bump that frame's `gained` by 1 via replace_top, so the +1 cattle flows through the SAME accommodation/overflow Pareto frontier as the market's own cattle (capacity, conversion-on-overflow). Adding to the player directly would bypass accommodation and is wrong. Fires unconditionally on use even if gained==0 (empty space): 0->1 is still correct.
- errata: None. Verbatim text: 'Each time you use the "Cattle Market" accumulation space (introduced in round 10 or 11), you get 1 additional cattle.' Card is printed 'players 3+' / Consul Dirigens, but cattle_market exists as a stage-4 accumulation space (rounds 10-11) in this 2p engine — STAGE_CARDS[4]=['cattle_market', ...] in constants.py, NONATOMIC_HANDLERS — so the hook maps cleanly. cattle_market is NON-ATOMIC (self-hosts via _initiate_cattle_market's apply_auto_effects before_action_space call), so NO register_action_space_hook is needed.

#### resource_analyzer  (tier 1, occupation, conf high) — C_157.json
- template: agricola/cards/small_scale_farmer.py (register_auto('start_of_round') choiceless-mandatory +resource income with an eligibility re-checked each round). childless.py is the start_of_round occupation analog; this card is simpler (no crop choice, so register_auto not register(mandatory=True)).
- plan: register_occupation('resource_analyzer', lambda s,i: s)  # no on-play effect. register_auto('start_of_round', 'resource_analyzer', _eligible, _apply). register_start_of_round_hook('resource_analyzer'). _eligible(state, idx) -> bool: me=state.players[idx].resources; opp=state.players[1-idx].resources; count = sum(getattr(me,t) > getattr(opp,t) for t in ('wood','clay','reed','stone')); return count >= 2. _apply(state, idx): p=state.players[idx]; p=fast_replace(p, resources=p.resources+Resources(food=1)); return fast_replace(state, players=tuple(...)). No cost/prereq/vps/passing (plain occupation).
- ordering: STRICT '>' not '>=' ('more building resources than' = strictly greater), and the threshold is 'at least two TYPES' (>=2 of the 4 building-resource types {wood,clay,reed,stone}, NOT total quantity). Count the types where my count strictly exceeds the opponent's, require count>=2. In 2-player 'all other players' = the single opponent (1-idx). register_auto eligibility is the 2-arg (state, idx) signature (no triggers_resolved) per small_scale_farmer; effect is choiceless so it is register_auto, not register(mandatory=True).
- errata: None. No errata or clarifications surfaced by card_text.py. Card is printed for 4+ players but reduces cleanly to a single-opponent comparison in 2p.
- open_q: Printed-player-count is 4+ ('all other players'); 2p interpretation collapses to the one opponent and is unambiguous, so no blocker. Confirm the project includes Corbarius-expansion cards in scope (card is Corbarius #157, status todo) -- but that is a scope question, not an implementation blocker.

#### half_timbered_house  (tier 1, minor, conf high) — C_30.json
- template: stable_architect.py (pure register_scoring end-game term); mantlepiece.py / fellow_grazer.py are equivalent minor-scoring siblings
- plan: register_minor('half_timbered_house', cost=Cost(Resources(wood=1, clay=1, stone=2, reed=1)), on_play=lambda s,i: s).  register_scoring('half_timbered_house', _score) where _score(state, idx): ps=state.players[idx]; if ps.house_material != HouseMaterial.STONE: return 0; return sum(1 for r in range(3) for c in range(5) if ps.farmyard.grid[r][c].cell_type == CellType.ROOM).  vps=0 (the bonus comes entirely from register_scoring; printed VP field is blank).  No prereq, not passing.
- ordering: Score 0 unless house_material == HouseMaterial.STONE (a stone room is a ROOM cell in a STONE house). Count CellType.ROOM cells, NOT pastures/stables, and gate on STONE first so a clay/wood house yields 0. This mirrors scoring.py lines 210-216 exactly (num_rooms gated by house_material). Use register_scoring (additive to base scoring), not the printed vps field.
- errata: No errata or clarifications returned by card_text.py. The trailing sentence 'You can only use one card to get bonus points for your stone house' is a mutual-exclusion clause shared only with Luxurious Hostel (revised minor, line 4304, 'more stone rooms than people -> 4 bonus points'). Luxurious Hostel is NOT implemented, so the clause is inert today; scoring this card alone is correct.
- open_q: The 'only use one card to get bonus points for your stone house' dedup clause is unenforceable with the current register_scoring model (each scoring fn is independent and additive). It is a no-op now because the only co-card (Luxurious Hostel) is unimplemented. If/when Luxurious Hostel lands, the two will need a shared mutual-exclusion mechanism (e.g. a 'stone house bonus' group key resolved in scoring) so a player holding both only scores one. Defer that infra until the second card exists.

#### abort_oriel  (tier 1, minor, conf high) — C_32.json
- template: agricola/cards/grange.py (minor with prereq= + vps=3, no on_play needed)
- plan: register_minor('abort_oriel', cost=Cost(Resources(clay=2)), prereq=_prereq, vps=3)  # no on_play, no scoring term (vps auto-scored).
_prereq(state, idx): for both players p in state.players, count len(p.occupations)+len(p.minor_improvements); return True iff EVERY player's count < 5 (i.e. no player already has >=5 cards in front). Built majors are NOT 'cards in front' so do not count major_improvement_owners.
No on_play effect, no triggers, no hooks. Cost 2 clay paid at play via the standard Cost path.
- ordering: prereq is evaluated at legality/play-time over the CURRENT state, BEFORE this card is added to the tableau (legality.py:1308 -> prereq_met). So when the playing player has exactly 4 cards in front and no one is >=5, the prereq passes and this becomes their 5th card -- exactly satisfying the clarification 'may be played as one's fifth card'. Use strict '< 5' (block at >=5), never '<= 5'. Count is per-player over ALL players (the restriction triggers on ANY player, including the opponent, reaching 5+).
- errata: Clarification only: 'This card may be played as one's fifth card.' (handled automatically because prereq reads pre-play state). No errata changing the effect.
- open_q: What counts as a 'card in front of you'? Implemented as occupations + minor improvements only (standard Agricola: built major improvements are tiles, not cards). If the user wants majors counted too, add len of owned majors -- but per rules they should NOT be counted.

#### greening_plan  (tier 1, minor, conf high) — C_33.json
- template: agricola/cards/stable_architect.py (register_scoring) + agricola/cards/grange.py (minor field-count idiom)
- plan: register_minor('greening_plan', cost=Cost(resources=Resources(food=3))). No prereq, no on_play (no-op), no vps (bonus is variable, scored via register_scoring not the flat vps).  register_scoring('greening_plan', _score) where _score(state, idx) counts unplanted fields n = sum over grid cells with cell_type==CellType.FIELD and grain==0 and veg==0, then maps via a threshold ladder: return 5 if n>=6 else 3 if n>=5 else 2 if n>=4 else 1 if n>=2 else 0.
- ordering: The threshold ladder is non-uniform (>=2/4/5/6 -> 1/2/3/5 pts; note the GAP at 3 fields gives the same 1pt as 2, and the JUMP from 3 to 5 pts between 5 and 6 fields) -- evaluate from the highest threshold down so each band returns the correct value; a naive linear formula is wrong. 'Unplanted' means a FIELD cell that is sown to nothing (grain==0 AND veg==0); a plowed-but-never-sown field and a field whose crop was fully harvested both count. Scoring runs after the final harvest (phase BEFORE_SCORING), so by the time _score is called all rounds-14 crops are already consumed -- no special timing handling needed; just read the terminal farmyard.
- errata: Clarifications (from card_text): Garden Designer C099 plants FOOD on fields, so a food-planted field is NOT unplanted and must not count -- but Garden Designer is not implemented and food-on-field is not representable (Cell only has grain/veg), so this is a non-issue here. Boar held on unplanted field tiles via Mud Patch A011 do not affect this card's scoring -- also not implemented. Fields are checked after the final harvest is completed. None of these edge cards exist in the engine, so the plain grain==0 and veg==0 test is exact for the implementable scope.

#### lantern_house  (tier 1, minor, conf high) — C_35.json
- template: agricola/cards/debt_security.py (minor + cost + register_scoring, no on_play); same shape as stable_architect's negative-equivalent scoring term
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), max_occupations=0, vps=7)  # printed 7 VP via MinorSpec.vps; prereq 'No Occupations' maps to max_occupations=0 (enforced by prereq_met, specs.py L180). register_scoring(CARD_ID, _score) where _score(state, idx) = -(len(ps.hand_occupations) + len(ps.hand_minors)) for ps = state.players[idx] — one negative point per card still in hand at scoring.
- ordering: Score is NEGATIVE: return -(hand size), not +. Count the DECIDER's own hand only (hand_occupations + hand_minors on PlayerState), not the opponent's. The printed 7 VP must come through MinorSpec.vps (added by scoring.py's minor-vps loop), NOT inside _score — putting +7 in _score would double-count against the vps loop. The two text clauses ('cannot discard cards unplayed', 'cannot play if you already have') are rules/draft constraints with no engine surface (this engine never discards hand cards unplayed; cards are unique within a pool so no duplicate), so they are inert — implement nothing for them.
- open_q: None blocking. prereq 'No Occupations' = max_occupations=0 (verified enforced by prereq_met, specs.py L178-180). The two text clauses ('cannot discard cards unplayed' / 'cannot play if you already have [this card]') have no engine surface and need no implementation — confirm with user only if they want a defensive duplicate-play guard, but cards are unique within a pool so it cannot arise.

#### christianity  (tier 1, minor, conf high) — C_38.json
- template: market_stall.py (on-play minor) + claw_knife.py (exact-count prereq predicate)
- plan: def _prereq(state, idx): return state.players[idx].animals.sheep == 1.  def _on_play(state, idx): opp = 1 - idx; p = fast_replace(state.players[opp], resources=state.players[opp].resources + Resources(food=1)); return fast_replace(state, players=tuple(p if i==opp else state.players[i] for i in range(2))).  register_minor('christianity', cost=Cost(), prereq=_prereq, vps=2, on_play=_on_play).  No printed cost (cost defaults to Cost()).
- ordering: The on-play effect grants food to the OPPONENT (1-idx), not the player who plays it (idx) — easy to wire to the wrong index. Also: 'Exactly 1 Sheep' is a PREREQ (== 1, a HAVE-check, never spent), distinct from any cost; use animals.sheep == 1 (not >= 1).
- errata: none surfaced by card_text.py

#### writing_boards  (tier 1, minor, conf high) — C_4.json
- template: agricola/cards/market_stall.py (on-play minor with cost) + agricola/cards/consultant.py (on-play resource grant)
- plan: register_minor('writing_boards', cost=Cost(resources=Resources(food=1)), on_play=_on_play). _on_play(state, idx): p = state.players[idx]; n = len(p.occupations); p = fast_replace(p, resources=p.resources + Resources(wood=n)); return fast_replace(state, players=tuple(...)). No prereq, no vps, not passing.
- ordering: Count is len(p.occupations) at play time. Playing this MINOR does NOT mutate p.occupations (that frozenset holds played occupation card_ids only), so there is no self-counting / off-by-one risk; the on_play fires after the card is committed but the occupations set is unchanged. Grant is exactly the current occupation count (0 wood if none played yet).
- errata: none surfaced by card_text.py

#### canvas_sack  (tier 1, minor, conf high) — C_40.json
- template: agricola/cards/market_stall.py (on-play immediate-goods minor); also consultant.py for the on_play resource-add idiom
- plan: register_minor("canvas_sack", cost=Cost(resources=Resources(grain=1, reed=1)), max_occupations=0, vps=1, on_play=_on_play). _on_play: p=state.players[idx]; p=fast_replace(p, resources=p.resources + Resources(veg=1, wood=4)); return fast_replace(state, players=tuple(...)). No passing, no CardStore, no prereq predicate (max_occupations=0 covers "No Occupations").
- ordering: The '/' in 'cost 1 Grain/1 Reed' and 'get 1 vegetable/4 wood' is NOT a player-count branch (unlike Consultant's '2/3/4-player' slashes) — it is a COMBINED list: cost = 1 grain AND 1 reed; gain = 1 veg AND 4 wood. Encode both fields in one Resources(). The 'paying grain/reed for it' clause is auto-satisfied because on_play fires only after the printed cost is charged; no alternate-payment route exists for this minor, so no guard needed.
- errata: None. JSON: cost '1 Grain/1 Reed', vps 1, prereq 'No Occupations'. No errata/clarifications returned by card_text.py.

#### remodeling  (tier 1, minor, conf high) — C_5.json
- template: agricola/cards/market_stall.py (on-play one-shot minor) — but NOT passing; resource-add idiom; count clay rooms + owned majors at play time
- plan: register_minor('remodeling', cost=Cost(resources=Resources(food=1)), on_play=_on_play). _on_play(state, idx): p=state.players[idx]; grid=p.farmyard.grid; clay_rooms = sum(1 for r in range(3) for c in range(5) if grid[r][c].cell_type==CellType.ROOM) if p.house_material==HouseMaterial.CLAY else 0; n_majors = sum(1 for o in state.board.major_improvement_owners if o==idx); gain = clay_rooms + n_majors; p=fast_replace(p, resources=p.resources+Resources(clay=gain)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). No prereq, no vps, NOT passing.
- ordering: Clay-rooms count is gated on house_material==CLAY (a STONE house has zero clay rooms, even though they were once clay — 'clay room' means a room currently made of clay). Reuse scoring.py L211-216 idiom exactly. Majors count includes ALL majors the player owns (Fireplace, Cooking Hearth, ovens, Well, etc.), each +1 clay regardless of type — no filtering. gain can be 0 (early game, wood house, no majors); that is legal and fine.
- errata: None reported by card_text.py (no errata/clarifications surfaced). Cost 1 Food, no prereq, no VPs, Corbarius Expansion deck C #5, category Building Resource Provider.

#### bookcase  (tier 1, minor, conf high) — C_68.json
- template: agricola/cards/feeding_dish.py (register_auto goods-grant) + agricola/cards/bread_paddle.py (after_play_occupation event wiring)
- plan: register_minor("bookcase", cost=Cost(resources=Resources(wood=2)), prereq=lambda s,i: len(s.players[i].occupations) >= 1).  Define _eligible(s, i) -> True (unconditional; a vegetable always fits, no accommodation, no threshold).  Define _apply(s, i): p = fast_replace(s.players[i], resources=s.players[i].resources + Resources(veg=1)); return fast_replace(s, players=tuple(...)).  register_auto("after_play_occupation", CARD_ID, _eligible, _apply)  (any_player=False default = owner-gated).  No on_play, no vps, no passing.
- ordering: Owner-gating is the one correctness point: leave any_player=False (default) so +1 veg fires ONLY on the owner's own occupation plays, not the opponent's. Timing is AFTER the occupation is played (after-phase of the play-occupation host, exactly where bread_paddle's after_play_occupation fires) — so it never affects/feeds the occupation it triggers on. No threshold, no CardStore snapshot needed: every occupation play grants exactly 1 veg unconditionally, so register_auto (mandatory, choiceless) over register (declinable) is correct.
- errata: None. Card text: 'Each time after you play an occupation, you get 1 vegetable.' Cost 2 Wood, prereq 1 Occupation (a PREREQ on play, not a recurring gate), 0 VP, not passing.

#### blade_shears  (tier 1, minor, conf high) — C_7.json
- template: agricola/cards/food_basket.py (on-play one-shot goods grant) + agricola/cards/consultant.py
- plan: register_minor('blade_shears', cost=Cost(resources=Resources(wood=1)), prereq=_prereq, on_play=_on_play). _prereq(state,idx): at least 1 pasture -> len(state.players[idx].farmyard.pastures) >= 1. _on_play(state,idx): p=state.players[idx]; gain=max(3, p.animals.sheep); p=fast_replace(p, resources=p.resources+Resources(food=gain)); splice p back via tuple comprehension. No vps, no passing.
- ordering: The 'choose 3 food OR 1 food per sheep' is NOT a real decision frame: food is a pure free good with no downside, so the rational and only sensible choice is always max(3, sheep). Collapse to a deterministic max(3, sheep) grant rather than pushing a PendingCardChoice. (Sheep are kept per the card text — never subtract them.) prereq '1 Pasture' is a PREREQ (a have-check, derived from farmyard.pastures), not a cost.
- errata: Clarification: 'Choose exactly 3 food, or food equal to your sheep.' No errata. Confirms it is exactly max(3, sheep), with sheep kept.
- open_q: Confirm a pasture-count prereq should read len(farmyard.pastures) (the enclosed-pasture decomposition) — a pasture is not a CellType. Verify exact attribute path on PlayerState.farmyard (cached pastures tuple).

#### private_forest  (tier 1, minor, conf high) — C_74.json
- template: agricola/cards/thick_forest.py (near-identical effect; same Category-8 deferred-goods schedule_resources path)
- plan: register_minor('private_forest', cost=Cost(resources=Resources(food=2)), min_occupations=1, on_play=_on_play). _on_play(state, idx): R=state.round_number; even_rounds=[r for r in range(R+1,15) if r%2==0]; return schedule_resources(state, idx, even_rounds, Resources(wood=1)). No prereq fn, no vps, not passing. schedule_resources is in agricola/cards/schedules.py; food=2 spendable cost is an established pattern (debt_security, forestry_studies, excursion_to_the_quarry).
- ordering: Schedule only REMAINING even round spaces: iterate range(R+1, 15), NOT range(R, 15) -- the current round's space is already collected at the start of R, so placing on it would be lost/wrong. Use strict R+1 lower bound (matches thick_forest exactly). Slots are clamped to 1..14 in schedule_resources, so no extra guard needed.
- errata: None. card_text.py reports no errata/clarifications. Effect text is byte-identical to Thick Forest (B74); only cost (2 Food spendable, vs Thick Forest's 5-clay PREREQUISITE) and prereq (1 Occupation) differ.

#### wood_cart  (tier 1, minor, conf high) — C_76.json
- template: agricola/cards/throwing_axe.py (near-exact: before_action_space auto on forest + register_action_space_hook; simpler — no Pig Market condition). Also milk_jug.py for the before_action_space pattern.
- plan: SPACES = frozenset({'forest'})  # the only wood accumulation space on the 2-player board. _eligible(state, idx): return state.pending_stack[-1].space_id in SPACES. _apply(state, idx): p = fast_replace(state.players[idx], resources=state.players[idx].resources + Resources(wood=2)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). register_minor('wood_cart', cost=Cost(resources=Resources(wood=3)), min_occupations=3, vps=0). register_auto('before_action_space', 'wood_cart', _eligible, _apply)  # NOT any_player — 'you' = owner only. register_action_space_hook('wood_cart', SPACES)  # forest is ATOMIC, needs a host frame to fire before/after.
- ordering: Fire on the BEFORE phase (before_action_space), per the 'each time you use [space]' ruling — same as Throwing Axe/Canoe/Milk Jug — so the +2 wood lands before the Forest's own accumulated wood take (order is immaterial here since it's a pure additive grant, but before is the canonical/correct phase). Use register_auto (mandatory, choiceless, no downside), NOT an optional FireTrigger. Do NOT pass any_player=True: 'each time YOU use' is owner-only, unlike Milk Jug's 'any player'. forest is atomic so register_action_space_hook is REQUIRED — without it no host frame exists and the auto never fires.
- errata: None. Card text is unambiguous: cost 3 Wood, prereq 3 Occupations (a play-prerequisite via min_occupations, NOT a spendable cost), no VPs, not passing.

#### plant_fertilizer  (tier 1, minor, conf high) — C_8.json
- template: agricola/cards/market_stall.py (passing on-play minor shell: register_minor passing_left=True, cost=Cost(), no vps/prereq) + agricola/cards/calcium_fertilizers.py::_apply (field-grid edit body), with the threshold changed from grain/veg > 0 to == 1.
- plan: ["register_minor('plant_fertilizer', cost=Cost(), passing_left=True, on_play=_on_play)  # cost/vps/prereq all null in JSON; passing_left='X' => passing card.", "_on_play(state, idx): walk p.farmyard.grid; for each Cell with cell_type is CellType.FIELD, check 'exactly 1 good': if cell.grain == 1 and cell.veg == 0 -> fast_replace(cell, grain=2); elif cell.veg == 1 and cell.grain == 0 -> fast_replace(cell, veg=2); else leave.", "Rebuild grid -> fast_replace(p.farmyard, grid=...) (pasture cache rides along: fields never lie in pastures) -> fast_replace(p, farmyard=...) -> splice player back into state.players tuple. Return state unchanged if nothing changed.", "No action-space hook, no FireTrigger, no CardStore: it is a one-shot pure-goods grant applied automatically at play time (no downside). __init__.py already imports every card module; add the import line."]
- ordering: THE threshold trap: 'exactly 1 good' means cell.grain == 1 (xor) cell.veg == 1, NOT > 0. Calcium Fertilizers (the body template) uses > 0 and must NOT be copied verbatim. A freshly-sown field holds 3 grain or 2 veg, so it does NOT qualify; only fields harvested down to a single token do (each harvest_field decrements grain/veg by 1, engine.py:1254-1259). Result of fertilizing is 2 of that type. Also: a field carrying BOTH grain and veg is two types -> skipped (the grain==1 and veg==0 / veg==1 and grain==0 XOR guards handle this).
- errata: cost=null, vps=null, prerequisites=null, passing_left='X' (=> traveling/passing card). Clarifications reference Mud Patch (A011, boar-on-fields) and Wood Field (D075) which are unimplemented and not in the current pool -> moot; no handling needed.
- open_q: Wording is 'you can immediately place' (optional). Treating it as automatic (apply to all eligible fields) per the cheat-sheet's 'pure-goods you can grant with no downside may stay automatic' ruling, matching Calcium Fertilizers. Adding free crops to your own fields is strictly beneficial, so no declinable FireTrigger frame is needed. Flag if the user wants strict optionality, but automatic is the correct convention here.

#### butler  (tier 2, occupation, conf high) — C_100.json
- template: tutor.py (CardStore play-time snapshot via on_play + register_scoring) combined with childless.py's _num_rooms grid-count idiom
- plan: register_occupation("butler", _on_play): _on_play snapshots the play round into CardStore as a gate, e.g. p.card_state.set("butler", 1 if state.round_number <= 11 else 0). register_scoring("butler", _score): _score returns 4 if the stored gate flag is truthy AND _num_rooms(p) > p.people_total else 0, where _num_rooms counts CellType.ROOM cells in p.farmyard.grid (copy childless._num_rooms). Played via Lessons; printed vps=0 (the 4 points are conditional, so NOT a flat vps= on the spec).
- ordering: The round-11-or-before gate is known ONLY at play time, so it MUST be captured in _on_play (which sees state.round_number = the play round) and read back at scoring; do NOT try to infer it during _score (round_number is 14/terminal there). 'more rooms than people' is STRICT >, not >=, and 'people' = people_total (not people_home). The 4 points are all-or-nothing, not per-room. Use card_state.get default that means 'not gated in' (default 0) so a never-snapshotted state scores 0 rather than awarding the bonus.

#### tree_guard  (tier 2, occupation, conf high) — C_102.json
- template: agricola/cards/carpenters_axe.py (optional after_action_space trigger on the wood accumulation space, once-per-use via triggers_resolved, atomic-space host via register_action_space_hook). Borrow the accumulated-pile read/write idiom from agricola/cards/wood_harvester.py / corf.py (get_space/with_space on ActionSpaceState.accumulated).
- plan: WOOD_SPACES = frozenset({'forest'}) (2-player board: Forest is the only wood accumulation space; Copse/Grove are 3-4p only). register_occupation('tree_guard', _on_play=no-op). register('after_action_space', 'tree_guard', _eligible, _apply); register_action_space_hook('tree_guard', WOOD_SPACES). _eligible(s,i,triggers_resolved): 'tree_guard' not in triggers_resolved AND s.pending_stack[-1].space_id in WOOD_SPACES AND s.players[i].resources.wood >= 4 (HAVE-check on POST-pickup supply, since after_action_space fires after Forest's +3 pickup). _apply(s,i): p=fast_replace(s.players[i], resources=p.resources - Resources(wood=4) + Resources(stone=2, clay=1, reed=1, grain=1)); then board=with_space(s.board, sid, get_space(...).accumulated += Resources(wood=4)) to PLACE the 4 wood back onto Forest; return fast_replace(s, players=..., board=...). No cost/prereq/vps/passing.
- ordering: TWO subtleties. (1) Direction of the 4 wood: it is PAID from supply but PLACED ONTO that accumulation space (it joins Forest's accumulated pile for a later player to pick up) — NOT discarded to general supply. The apply MUST credit get_space(board,'forest').accumulated.wood += 4 via with_space, in addition to debiting the player -4 wood. Forgetting the deposit silently changes the rules. (2) after_action_space fires AFTER Forest's atomic pickup empties the space and credits the player's +3 wood, so the >=4-wood eligibility HAVE-check reads the POST-pickup supply (a player at 1 wood who picks up 3 now has 4 and qualifies); and the deposited 4 wood lands on a space that was just reset to empty.
- errata: None. Verbatim text: 'Each time after you use a wood accumulation space, you can place 4 wood from your supply on that space to get 2 stone, 1 clay, 1 reed, and 1 grain.' No errata/clarifications in the card data. Category Goods Provider, Corbarius Expansion, deck C #102, players 1+.
- open_q: Confirm the 'place 4 wood on that space' deposit semantics: the rule literally returns the 4 wood to the Forest accumulation space (pickable next round/turn), rather than removing it from the game. This is the implementation's only real interpretive call; all existing wood-accumulation cards only READ accumulated, none WRITE a deposit, so verify with_space(accumulated += wood) is the intended/desired model (vs. just spending the 4 wood to general supply if a simpler reading is preferred).

#### schnapps_distiller  (tier 2, occupation, conf high) — C_109.json
- template: agricola/cards/furniture_carpenter.py (occupation no-op on-play + register_harvest_conversion); food-producing conversion shape from harvest_conversions.py built-ins (joinery/pottery/basketmaker).
- plan: register_occupation('schnapps_distiller', lambda state, idx: state)  # no on-play effect (played via Lessons).
register_harvest_conversion(HarvestConversionSpec(conversion_id='schnapps_distiller', input_cost=Resources(veg=1), food_out=5, is_owned_fn=_eligible)).
_eligible(state, idx): return 'schnapps_distiller' in state.players[idx].occupations  # registrations are global; must gate ownership here so the non-owner is not offered the conversion.
No cost, no prereq, no vps, not passing. No side_effect_fn, no scoring term, no CardStore.
- ordering: is_owned_fn MUST confirm THIS player owns the occupation (conversion registry is global; the HARVEST_FEED enumerator gates only on is_owned_fn) — otherwise the conversion is offered to the non-owner. The once-per-harvest 'exactly 1 vegetable' is enforced automatically: firing marks the id in harvest_conversions_used (reset each harvest's FEED), so no manual cross-variant guard is needed (single entry, unlike Beer Keg).
- errata: None. Card text is unambiguous: 'In the feeding phase of each harvest, you can use this card to turn exactly 1 vegetable into 5 food.' Optional ('you can'), once-per-harvest (single conversion entry), no points.

#### home_brewer  (tier 2, occupation, conf high) — C_110.json
- template: agricola/cards/beer_keg.py (multi-variant once-per-harvest HarvestConversionSpec + CardStore-banked VP + register_scoring); occupation registration + no-op on_play per agricola/cards/stable_architect.py
- plan: register_occupation('home_brewer', lambda s,i: s)  # effect is the recurring harvest conversion only. Two HARVEST_CONVERSIONS variants, both input_cost=Resources(grain=1): 'home_brewer_food' food_out=3 side_effect_fn=None ; 'home_brewer_vp' food_out=0 side_effect_fn banks +1 in CardStore (p.card_state.set('home_brewer', banked+1)). Both is_owned_fn: return ('home_brewer' in p.occupations) and not any(cid.startswith('home_brewer') for cid in p.harvest_conversions_used)  # once-per-harvest choice across the two variants. register_scoring('home_brewer', lambda s,i: s.players[i].card_state.get('home_brewer', 0)). No cost/prereq/passing/vps (occupation).
- ordering: Cross-variant once-per-harvest guard: BOTH variants' is_owned_fn must return False when ANY 'home_brewer_*' id is already in harvest_conversions_used (use cid.startswith('home_brewer'), like beer_keg), not just its own id — else a player fires both the food AND the VP variant in one harvest, breaking 'turn exactly 1 grain' (one grain, one output, once per harvest). Affordability (1 grain) and the per-id used-guard are handled by the FEED enumerator; the cross-variant suppression is the card's job.
- errata: None. Verbatim: 'After the field phase of each harvest, you can use this card to turn exactly 1 grain into your choice of 3 food or 1 bonus point.' Surfaced during HARVEST_FEED (the engine's harvest-conversion seam runs after FIELD). Occupation, Consul Dirigens, deck C #110, Food Provider, players 1+, vps 0, no cost/prereq, not passing.
- open_q: Immediate-VP is unsupported, so the '1 bonus point' output is banked in CardStore and read back by a scoring term (same as beer_keg / furniture_carpenter) — confirm this banking is acceptable vs any preference for a different VP representation.

#### thresher  (tier 2, occupation, conf high) — C_112.json
- template: agricola/cards/threshing_board.py (same before_action_space + optional register shape over {farmland, cultivation} + grain_utilization) for structure; agricola/cards/potter_ceramics.py for the goods-swap apply (-1 food, +1 grain); agricola/cards/assistant_tiller.py / barrow_pusher.py for the trigger-only occupation no-op on_play idiom.
- plan: CARD_ID='thresher'; SPACES=frozenset({'grain_utilization','farmland','cultivation'}). _eligible(state,idx,triggers_resolved)-> CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id in SPACES AND state.players[idx].resources.food >= 1. _apply(state,idx)-> p=state.players[idx]; fast_replace(state, players=tuple of p with resources+Resources(food=-1, grain=1)). register_occupation(CARD_ID, _noop_on_play) (from specs; no on-play effect). register('before_action_space', CARD_ID, _eligible, _apply) -> OPTIONAL declinable FireTrigger. No cost/prereq/vps/passing on the occupation; no register_action_space_hook (all three spaces are non-atomic and already hosted).
- ordering: Must be the OPTIONAL declinable form (register, FireTrigger) not register_auto, because 'you can buy' is optional. Eligibility MUST gate on food>=1, else it offers a dead-end FireTrigger the player cannot pay. Use 'before_action_space' (per the 'each time you use [space]' -> before ruling and the card's own clarification 'this effect happens before using the space'); triggers_resolved scoping makes it re-eligible each space-use and limits it to once per use. The clarification 'must happen before Flail C026' is just the before-phase ruling restated; no special inter-card ordering code is needed now (registry handles fire order once Flail exists).
- errata: Clarification (from card_text): 'This effect happens before using the space, and must happen before effects such as Flail C026.' Confirms the before_action_space placement and that the grain bought here is available to the subsequent sow/space effect.

#### winter_caretaker  (tier 2, occupation, conf high) — C_113.json
- template: agricola/cards/furniture_carpenter.py (recurring harvest food-buy via HarvestConversionSpec.side_effect_fn) + on-play grain grant like consultant.py; veg-grant idiom from market_stall.py
- plan: register_occupation('winter_caretaker', _on_play) where _on_play returns state with p.resources + Resources(grain=1) (immediate +1 grain on play). register_harvest_conversion(HarvestConversionSpec(conversion_id='winter_caretaker', input_cost=Resources(food=2), food_out=0, is_owned_fn=_eligible, side_effect_fn=_grant_veg)). _eligible(state,idx) = 'winter_caretaker' in state.players[idx].occupations (registrations are global -> must gate on ownership here; no other prereq). _grant_veg(state,idx) edits player via fast_replace(p, resources=p.resources + Resources(veg=1)). No scoring term (the vegetable is a normal good). Add 'from agricola.cards import winter_caretaker' to cards/__init__.py. No cost/prereq/vps/passing.
- ordering: Card says 'At the END of each harvest' but the harvest-conversion registry is surfaced during the FEED sub-phase (FIELD->FEED->BREED), i.e. mid-harvest not literally end-of-harvest. This is mechanically harmless here: nothing observable happens between FEED/BREED and harvest-end that interacts with holding +1 vegetable, and the conversion is once-per-harvest (harvest_conversions_used) which correctly enforces 'buy EXACTLY 1'. The food->good direction (food_out=0 + side_effect_fn grants the good, never negative food) is the same shape Furniture Carpenter uses; the enumerator already gates on _can_afford so the buy is only offered when the player holds 2 food.
- open_q: Minor: 'end of harvest' vs the FEED-phase surfacing point of the harvest-conversion registry (no observable difference here, so treated as the intended hook). If the user wants strict end-of-harvest (after BREED) timing, that would need a new harvest-end hook — not built; not warranted for this card.

#### soil_scientist  (tier 2, occupation, conf high) — C_114.json
- template: agricola/cards/carpenters_axe.py (optional after_action_space trigger on an atomic accumulation space, gated once-per-use via triggers_resolved + affordability) combined with mineralogist.py / clay_puncher.py (the clay_pit/western_quarry/eastern_quarry hooking + per-space branch). Soil Scientist's granted effect is a pure goods swap in _apply (no new pending frame), simpler than carpenters_axe's PendingBuildStables.
- plan: register_occupation('soil_scientist', lambda s,i: s)  # no on-play effect. register('after_action_space', 'soil_scientist', _eligible, _apply) and register_action_space_hook('soil_scientist', {'clay_pit','western_quarry','eastern_quarry'}) (all three atomic, must be hosted). _eligible(s,i,triggers_resolved): False if CARD_ID in triggers_resolved (once per use); sid=s.pending_stack[-1].space_id; if sid=='clay_pit' return p.resources.stone>=1; if sid in {'western_quarry','eastern_quarry'} return p.resources.clay>=2; else False. _apply(s,i): if sid=='clay_pit' delta=Resources(stone=-1,grain=2) else delta=Resources(clay=-2,veg=1); p=fast_replace(player, resources=p.resources+delta); return fast_replace(s, players=...). No cost, no prereq, no vps, not passing (occupation, played via Lessons).
- ordering: Two ASYMMETRIC branches that are easy to cross-wire: clay accumulation space (clay_pit) -> pay 1 STONE, gain 2 grain; stone accumulation spaces (western/eastern quarry) -> pay 2 CLAY, gain 1 vegetable. The cost good is the OPPOSITE mineral of the space used. Both quarries share the identical stone-branch effect. Must be after_action_space (the space's own pickup resolves first; 'each time after you use' is the explicit immediately-after exception), and gated once-per-use by triggers_resolved (not used_this_round) so it can fire on each separate quarry/pit use. 'place X on the space' is flavor only -- goods leave supply, no per-card goods stack needed.
- errata: None. card_text.py reports no errata/clarifications.

#### excavator  (tier 2, occupation, conf high) — C_126.json
- template: agricola/cards/clay_puncher.py (after_action_space auto-grant on an atomic space + register_action_space_hook) for the mandatory wood+clay grant; agricola/cards/basket.py (optional after_action_space FireTrigger that exchanges goods, eligibility gates affordability + triggers_resolved once-per-use) for the optional 'buy 1 stone for 1 food' conversion. Both kinds coexist on the one day_laborer host (triggers.py line 85: 'A hook can host both kinds').
- plan: Occupation, on-play no-op (register_occupation(CARD_ID, lambda s,i: s)). SPACES={'day_laborer'}; register_action_space_hook(CARD_ID, SPACES) to host the atomic space. Mandatory part: register_auto('after_action_space', CARD_ID, _eligible_auto, _apply_auto) where _eligible_auto checks pending_stack[-1].space_id in SPACES and _apply_auto adds Resources(wood=1, clay=1) to player idx. Optional buy: register('after_action_space', CARD_ID, _eligible_buy, _apply_buy) where _eligible_buy(state,idx,triggers_resolved) = CARD_ID not in triggers_resolved and space_id in SPACES and players[idx].resources.food>=1; _apply_buy does Resources(food=-1, stone=1). No cost/prereq/vps/passing.
- ordering: Must register on after_action_space (text says 'each time AFTER you use'), NOT before. This is load-bearing twice: (1) the clarification 'these resources may not be used to pay for Cottager B087' is enforced FOR FREE because Cottager fires before_action_space (its build/renovate resolves before Excavator's after-grant exists) — do not try to special-case the cross-card constraint. (2) The mandatory auto and the optional FireTrigger are SEPARATE registrations on the same event; the optional buy must gate on triggers_resolved (once per use) and on food>=1 so it never offers a dead-end. The +1 wood/+1 clay is choiceless -> register_auto (never surfaced); the 'buy 1 stone' is a player choice -> register (declinable FireTrigger, decline = host Stop/Proceed).
- errata: Clarification: 'These resources may not be used to pay for the effect of the Cottager B087.' Enforced automatically by the before/after_action_space timing split (no code needed). Day Laborer is an ATOMIC space, so register_action_space_hook is required to push a PendingActionSpace host whose Proceed flips to the after-phase.
- open_q: Food cost is fixed at 1 and on-hand-only, so unlike Ox Goad no PendingFoodPayment/liquidation path is needed (eligibility just checks food>=1). Confirm that's acceptable rather than routing the 1-food purchase through the food-payment frontier; the rules treat it as a simple at-the-moment 1-food spend, so direct debit is correct.

#### wooden_hut_extender  (tier 2, occupation, conf high) — C_128.json
- template: agricola/cards/carpenters_parlor.py (wood-house-gated build_room register_formula) + carpenter.py (occupation registration via register_occupation + _noop_on_play). Closest precedent is carpenters_parlor; only delta is occupation-not-minor and the round-dependent wood amount.
- plan: register_formula('build_room', 'wooden_hut_extender', applies=lambda s,i,ctx: s.players[i].house_material==HouseMaterial.WOOD, formula=_formula). _formula(s,i,ctx)->Resources: wood = 5 if s.round_number<=5 else 4 if s.round_number<=7 else 3; return Resources(wood=wood, reed=1). register_occupation('wooden_hut_extender', _noop_on_play). No cost/prereq/vps on the occupation itself (occupations have no resource cost). The chokepoint effective_payments already surfaces the formula beside the printed ROOM_COSTS[WOOD]=5 wood+2 reed and Pareto-mins; reductions (e.g. Bricklayer) stack on top automatically.
- ordering: Two thresholds must be exact: reed becomes 1 (NOT 2 -- the printed wood-room base is 5 wood + 2 reed, so the card drops reed to 1 AND swaps the wood schedule). Wood is round-banded: rounds 1-5 -> 5 wood, rounds 6-7 -> 4 wood, round 8+ -> 3 wood (i.e. s.round_number<=5, <=7, else). Read round from GameState.round_number (1-14). Because reed=1 < printed 2, the formula is a STRICT improvement over the base in every round (5w+1r through r5 dominates 5w+2r), so Pareto-min always keeps the formula when applicable; in a clay/stone house the gate is False and only the printed base survives -- byte-identical to today.
- errata: None surfaced by card_text.py (no errata/clarification lines printed).
- open_q: Card is Corbarius Expansion deck C, marked 'players 3+'. Target scope is the 2-player card game. The MECHANIC is fully 2-player-compatible (no per-player-count logic), but if the project is excluding 3+-only cards from the 2p pool the user may want it omitted from card_pool dealing rather than unimplemented. Recommend implementing the module (harmless, correct) and letting pool-selection decide inclusion.

#### second_spouse  (tier 2, occupation, conf high) — C_129.json
- template: agricola/cards/sleeping_corner.py (clause 1: register_occupancy_override on a wish space) + agricola/cards/stable_architect.py (no-op on_play occupation idiom)
- plan: register_occupation('second_spouse', lambda state, idx: state)  # pure occupancy relaxer, no on-play effect. register_occupancy_override(_occupancy_override). _occupancy_override(state, space_id): return False unless space_id == 'urgent_wish_for_children'; ap = state.current_player; require CARD_ID in state.players[ap].occupations; require get_space(state.board, space_id).workers[ap] == 0; others = sum(1 for i,w in enumerate(workers) if i != ap and w > 0); return others == 1. No cost/prereq/vps (Lessons-played occupation).
- ordering: COUNT PLAYERS, NOT WORKERS: a normally-used urgent-wish space already holds TWO of the first player's workers (parent placed + newborn generated by _resolve_wish_for_children), so the clarification 'not if any second/third person occupies it' means exactly one OTHER PLAYER may hold it (others_with_workers == 1), tolerating that player's parent+newborn pair — never a raw worker count. The 'from round 12-13' phrasing is purely descriptive of the space's stage-5 reveal timing (urgent_wish_for_children is a stage-5 card; _is_available short-circuits on `not sp.revealed`, so the override is only ever consulted once the space exists) — it is NOT a separate round-gate to enforce.
- errata: Clarification on card: 'But not if any second, third, etc. people occupy it.' (i.e. relaxation applies only when occupied by another player's FIRST person — one other player.)
- open_q: Confirm Second Spouse targets ONLY urgent_wish_for_children (not basic_wish_for_children) — card text names only the Urgent space, so the override is scoped to that single space (distinct from Sleeping Corner, which covers both wish spaces).

#### private_teacher  (tier 2, occupation, conf medium) — C_131.json
- template: agricola/cards/assistant_tiller.py (occupation + optional before_action_space trigger on an ATOMIC space hosted via register_action_space_hook, pushing a sub-decision pending) crossed with agricola/cards/scholar.py (pushing PendingPlayOccupation(cost=Resources(food=1)) and the playable+payable occupation eligibility gate via playable_occupations + _payable_occupation).
- plan: register_occupation('private_teacher', lambda s,i: s)  # no on-play effect. SPACES=frozenset({'grain_seeds'}); register_action_space_hook('private_teacher', SPACES) (grain_seeds is ATOMIC, needs a host frame). _eligible(s,i,triggers_resolved): 'private_teacher' not in triggers_resolved AND s.pending_stack[-1].space_id in SPACES AND lessons is occupied: get_space(s.board,'lessons').workers != (0,0) AND playable_occupations(s,i) AND _payable_occupation(s,i,s.players[i],Resources(food=1)). _apply(s,i): return push(s, PendingPlayOccupation(player_idx=i, initiated_by_id='card:private_teacher', cost=Resources(food=1))). register('before_action_space','private_teacher',_eligible,_apply) (OPTIONAL declinable FireTrigger — 'you can also play'). No cost/prereq/vps/passing.
- ordering: Two coupled subtleties: (1) the gate is occupancy of a DIFFERENT space (Lessons), not Grain Seeds' own state — check get_space(board,'lessons').workers != (0,0), NOT _is_available (which would falsely block on the card-game occupancy-override path / require revealed). In 2p there is exactly one Lessons space and the placing worker is on Grain Seeds, so the opponent's worker on Lessons is what makes the trigger live. (2) 'each time you use Grain Seeds' = before_action_space (a Lessons-occupied check is a board read, not 'immediately after'), and the trigger is OPTIONAL/declinable (use register, not register_auto) because 'you can also play' — decline = the host's Proceed. The clarification ('if the played occupation has a Grain Seeds effect, it also triggers immediately') needs NO special handling: because we fire before_action_space (BEFORE the Grain Seeds effect resolves) and the new occupation registers its own before_action_space hook, the host's trigger loop will re-poll and surface that occupation's effect on the same Grain Seeds frame automatically.
- errata: Clarification (verbatim): 'If the played occupation has an effect when using “Grain Seeds”, it also triggers immediately.' No errata. Printed players 3+ — but the effect is fully meaningful in 2p (one Lessons space; opponent can occupy it), and the codebase precedent (geologist/chophouse) implements 3+-tagged cards' 2p-applicable behavior; the 3+ tag here is the game-size requirement, not a clause to drop.
- open_q: VERIFY before implementing: (a) Does pushing PendingPlayOccupation(cost=food=1) from a non-Lessons before_action_space context resolve cleanly through _enumerate_pending_play_occupation / _execute_play_occupation, OR does it expect a play-occupation-variant registration? Scholar registers register_play_variant_trigger but that is for its occupation-OR-minor CHOICE; Private Teacher has no choice (occupation only), so it likely needs none — confirm the enumerator does not KeyError on an unregistered variant card and that the flat 1-food cost rides on the frame correctly. (b) Confirm the trigger fires for the GRAIN-SEEDS-placing current player (before_action_space player_idx = the active placer), so 'when Lessons is occupied' reads the OPPONENT's worker on Lessons. (c) triggers_resolved scoping: 'each time you use Grain Seeds' = once per Grain Seeds placement — confirm the before_action_space triggers_resolved budget is per-placement so it can re-fire on a later Grain Seeds turn but not twice in one.

#### straw_thatched_roof  (tier 2, minor, conf high) — C_14.json
- template: agricola/cards/bricklayer.py (register_reduction on 'renovate' + 'build_room'); prereq helper modeled on agricola/cards/asparagus_gift.py field-cell iteration
- plan: def _no_reed(state, idx, ctx, cost): return cost - Resources(reed=cost.reed)  # zero out the reed component (floor-at-0 in apply_reductions makes plain subtraction safe, but subtracting cost.reed is exact). register_reduction('renovate', CARD_ID, _no_reed); register_reduction('build_room', CARD_ID, _no_reed). prereq=_three_grain_fields(state,idx): count FIELD cells in farmyard.grid (3x5) with cell.grain>0, return count>=3. register_minor(CARD_ID, prereq=_three_grain_fields, vps=1)  # cost is FREE per card_text (no cost printed); no min/max_occupations.
- ordering: Effect is 'no longer NEED reed' = remove the reed component ENTIRELY, not a fixed -1. Use cost - Resources(reed=cost.reed) so a build needing 2 reed (e.g. renovate to clay) drops the full 2, not just 1. A literal '-1 reed' (Bricklayer-style) would be WRONG for any cost with reed>=2. Register on 'renovate' and 'build_room' ONLY (singular event names per cost_mods registry) -- NOT build_major/play_minor (card says renovate or build a room only).
- errata: None reported by card_text. Note prereq '3 Grain Fields' is a PREREQ (must hold at play time), not a cost; printed cost is FREE (none shown).
- open_q: Interpretation of '3 Grain Fields' prereq: taken as >=3 FIELD cells currently carrying grain (cell.grain>0). Could alternatively mean fields growing grain specifically vs any sown field -- 'grain field' wording strongly implies grain present. Confirm if user reads it as grain-bearing fields (assumed) vs something looser.

#### trellis  (tier 2, minor, conf high) — C_15.json
- template: agricola/cards/ox_goad.py (optional before/after_action_space trigger on an animal-market space that grants a sub-action) crossed with agricola/cards/field_fences.py (the PendingGrantedBuildFences choose-or-decline Build-Fences grant). milk_jug.py is the before_action_space + space_id==... eligibility example.
- plan: register_minor('trellis', cost=Cost(), min_occupations=2)  # cost null, vps null, kept (passing_left null).
register('before_action_space', 'trellis', _eligible, _apply)  # OPTIONAL declinable ('you can'); FireTrigger IS the opt-in, declining = host's Stop. NOT register_auto.
_eligible(state, idx, triggers_resolved): return ('trellis' not in triggers_resolved) and state.pending_stack[-1].space_id == 'pig_market' and _any_legal_pasture_commit(state, state.players[idx], space_id='card:trellis', initiated_by_id='card:trellis')  # once-per-use + dead-end guard.
_apply(state, idx): from agricola.pending import PendingGrantedBuildFences, push; return push(state, PendingGrantedBuildFences(player_idx=idx, initiated_by_id='card:trellis'))  # multi-shot host; 'pay wood as usual' => register NO free-fence/discount, so PendingBuildFences pushed by the wrapper uses normal wood cost, build_fences_action=True.
- ordering: Event MUST be before_action_space, not after: text says 'Each time BEFORE you use the Pig Market space' (and the ruling 'each time you use [space]' = before_action_space; before-auto/trigger fires at the host frame's push). pig_market is NON-ATOMIC (it is in NONATOMIC_HANDLERS, pushing PendingPigMarket), so its host frame is always present and NO register_action_space_hook is needed. The 'you can' optionality must be the FireTrigger itself (register with mandatory default False), NOT a register_auto. eligibility must gate on a buildable pasture existing now (via _any_legal_pasture_commit) so it never offers a dead-end FireTrigger, AND gate 'trellis' not in triggers_resolved so it fires at most once per Pig Market use. 'pay wood for the fences as usual' => register NO free-fence seed/edge/pool and NO cost reduction; the granted PendingBuildFences just pays normal wood.
- errata: None reported by card_text.py. Note: card_text 'Trellis' query also returns a DIFFERENT card 'Trellises' [trellises] (Artifex deck A #47, already implemented) — do not confuse; this is deck C #15 [trellis], Corbarius.
- open_q: Whether _apply should push PendingGrantedBuildFences (the choose-or-decline wrapper, as field_fences does) or push the real multi-shot PendingBuildFences host directly (as ox_goad pushes PendingPlow directly). Recommend the wrapper: the FireTrigger already supplied the opt-in, but the wrapper gives the natural multi-shot 'build a pasture / Stop' loop and matches the only existing card that grants a literal Build Fences action. Confirm this is consistent with how a FireTrigger-initiated grant nests above the PendingPigMarket host frame (the wrapper lands on top of the market frame; after it pops, the market action proceeds since this is the BEFORE phase).

#### cattle_whisperer  (tier 2, occupation, conf high) — C_166.json
- template: agricola/cards/estate_worker.py (occupation + schedule_*) crossed with agricola/cards/acorns_basket.py (schedule_animals for animals)
- plan: register_occupation('cattle_whisperer', _on_play). In _on_play: R = state.round_number; return schedule_animals(state, idx, (R+5, R+8), Animals(cattle=1)). No cost / prereq / vps / passing (occupation, played via Lessons; the schedule IS the effect). schedule_animals (cards/schedules.py) places 1 cattle on each of the two future round slots; they are collected + auto-accommodated at the start of those rounds by engine._collect_future_rewards (same pareto/can_accommodate machinery as the animal markets). Rounds > 14 are silently dropped by schedule_animals, correctly modeling 'place on each corresponding round space' near game-end.
- ordering: 'Add 5 and 8 to the CURRENT round' is printed-board phrasing for offsets R+5 and R+8 from the round when the card is played (state.round_number), NOT fixed rounds 5 and 8. schedule_animals is 1-indexed and writes slot r-1; pass the absolute round numbers (R+5, R+8), not the offsets. Because the slots are R-relative, playing late (e.g. R>=10) means one or both rounds exceed 14 and are silently dropped by the helper's 1..14 clamp — the desired behavior. The animals are scheduled (future_rewards), NOT granted immediately, so the 'immediate animal grant has no accommodation -> DEFER' caveat does NOT apply: scheduled round-start grants are the explicitly-supported accommodation path (Acorns Basket is the named precedent in schedule_animals' docstring).
- errata: None in card_text output. Status 'todo'. Tagged 'players 4+' / Consul Dirigens Expansion deck C #166, category Livestock Provider.
- open_q: Card is from a 4+ player deck (printed 'players 4+'). Mechanically it is single-player and works fine in the 2-player engine, but whether it should be INCLUDED in the 2-player card pool is a pool-membership/scope decision for the user, separate from implementability. Implementation itself has no blocker.

#### stable  (tier 2, minor, conf high) — C_2.json
- template: agricola/cards/mini_pasture.py (on-play restricted/free granted build + playability prereq); the build-stable push itself mirrors agricola/cards/groom.py (PendingBuildStables(cost, max_builds=1)).
- plan: register_minor('stable', cost=Cost(resources=Resources(wood=1)), prereq=_can_build_free_stable, on_play=_on_play).
_on_play: return push(state, PendingBuildStables(player_idx=idx, initiated_by_id='card:stable', cost=Resources(), max_builds=1, build_stables_action=False)).  # stable is FREE; card cost (1 wood) is paid by the play-minor path, not the build.
_can_build_free_stable(state, idx): from agricola.legality import _can_build_stable; return _can_build_stable(state, state.players[idx], Resources())  # >=1 stable in supply AND a legal empty cell; free cost is trivially payable. Mirrors Mini Pasture's mandatory-playability gate so the grant never deadlocks.
No vps, no prereq-card-count, not passing. The PendingBuildStables enumerator handles cell selection + only allows Proceed once num_built>=1, so with max_builds=1 the build is effectively forced (matches 'Immediately build 1 stable').
- ordering: The grant is effectively MANDATORY: PendingBuildStables's enumerator offers Proceed only once num_built>=1, so at num_built=0/max_builds=1 it returns ONLY CommitBuildStable cells (no decline path). That is fine ('Immediately build 1 stable'), BUT it means if no legal stable can be built when the card is played the action set is EMPTY -> deadlock. Therefore the playability prereq (a legal empty cell AND >=1 stable in supply, checked via _can_build_stable with FREE cost) is load-bearing and must exactly anticipate the grant, exactly as Mini Pasture's prereq does. Secondary: set build_stables_action=False (card effect, not the literal Build Stables action) so future action-scoped stable-build triggers (e.g. Stable Tree) don't fire on it -- mirrors Mini Pasture's build_fences_action=False; today this field has no trigger consumer (canonical skip-field only) but =False is the correct forward-compat choice.
- errata: No errata/clarifications on this card. Text reminder: '(The stable costs you nothing, but you must pay the cost shown on this card.)' => the build is free; the 1-wood card cost rides the normal play-minor cost path, NOT the PendingBuildStables.cost (which is Resources()).
- open_q: Confirm the build is intended as mandatory-on-play (the default PendingBuildStables behavior gives no decline path). The text 'Immediately build 1 stable' reads as mandatory and matches the user's Mini Pasture ruling ('Immediately fence' = mandatory), so implementing it mandatory is the proposed default -- but worth a one-line confirm since 'granted sub-actions are optional unless you must' is the general rule and 'Immediately' is the borderline word the Mini Pasture precedent resolved toward mandatory.

#### steam_machine  (tier 2, minor, conf high) — C_25.json
- template: carpenters_axe.py (after_action_space over accumulation spaces, optional FireTrigger, register_action_space_hook for atomic hosting) + bread_paddle.py (pushes PendingBakeBread gated on _can_bake_bread)
- plan: ["register_minor('steam_machine', cost=Cost(resources=Resources(wood=2)), vps=1)  # 2 Wood; 1 VP; no prereq; not passing.", "Define ACC_ATOMIC = frozenset({'fishing','forest','clay_pit','reed_bank','western_quarry','eastern_quarry'}) (the 6 ATOMIC accumulation spaces that need hosting); the 3 markets (sheep/pig/cattle) are non-atomic and self-host, so they need NO hook but DO surface after_action_space.", "_eligible(state, idx, triggers_resolved): return (CARD_ID not in triggers_resolved) and (state.pending_stack[-1].space_id in ACCUMULATION_SPACES) and (state.players[idx].people_home == 0)  # people_home==0 => this was the player's LAST placement of the work phase (decremented at placement, before after-phase) and _can_bake_bread(state, state.players[idx]) so it never grants a dead-end.", "_apply(state, idx): return push(state, PendingBakeBread(player_idx=idx, initiated_by_id='card:steam_machine'))  # the granted, optional Bake Bread sub-action.", "register('after_action_space', CARD_ID, _eligible, _apply)  # OPTIONAL declinable FireTrigger ('you can ... take a Bake Bread'); decline = don't fire.", "register_action_space_hook(CARD_ID, ACC_ATOMIC)  # host ONLY the 6 atomic accumulation spaces; markets self-host."]
- ordering: Two interlocking subtleties. (1) 'last action space you use' = the placing player's people_home == 0 at the after_action_space moment (people_home is decremented in _place_worker_on_space BEFORE the after-phase fires, and engine.py line 783 uses people_home==0 as the canonical 'done placing' signal), so the check is exact. (2) Hosting scope: register_action_space_hook is required ONLY for the 6 ATOMIC accumulation spaces (in ATOMIC_HANDLERS: fishing/forest/clay_pit/reed_bank/western_quarry/eastern_quarry) to push a PendingActionSpace frame; the 3 animal markets are NON-atomic, self-host their before/after lifecycle (verified vs Claw Knife/Milk Jug), and must NOT be added to the hook (but ARE matched by the ACCUMULATION_SPACES membership test, so they still grant the Bake Bread). Gate on _can_bake_bread so the fire is never a dead-end.
- errata: None. Card text verbatim: 'Each work phase, if the last action space you use is an accumulation space, you can immediately afterward take a Bake Bread action.' Cost 2 Wood, 1 VP, no prereq, not passing. Deck C (Consul Dirigens) #25, category Actions Booster.
- open_q: Confirm the 'last action space you use' = people_home==0 mapping is acceptable: in the 2p game with fixed family size and no in-scope extra-worker grants, the player's final placement is exactly when people_home hits 0 after decrement, so the mapping is exact. (If a future extra-worker card lands, the eligibility would need to consult that; flagged but not blocking.) Also confirm ACCUMULATION_SPACES from constants.py is the intended 'accumulation space' set (the 5 building + fishing + 3 markets); meeting_place is excluded in the card game since it gives no food/accumulation there.

#### flail  (tier 2, minor, conf high) — C_26.json
- template: oven_firing_boy.py (recurring optional granted Bake Bread on before_action_space) + food_basket.py (on-play +N food via register_minor on_play)
- plan: register_minor("flail", cost=Cost(resources=Resources(wood=1)), on_play=_on_play) where _on_play adds Resources(food=2) to player idx (food_basket idiom). For the recurring part: SPACES=frozenset({"farmland","cultivation"}); _eligible(state,idx,triggers_resolved) = CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id in SPACES AND _can_bake_bread(state, state.players[idx]); _apply pushes PendingBakeBread(player_idx=idx, initiated_by_id="card:flail"); register("before_action_space", "flail", _eligible, _apply). NO register_action_space_hook (both spaces are non-atomic, already host before_action_space and set space_id farmland/cultivation). No prereq, no vps, not passing.
- ordering: Grant fires on before_action_space (the parent-frame push), correct per 'each time you use [space]' = before, no 'immediately after' qualifier; bake consumes the player's own grain not the space's output so before vs after is observationally fine (same as oven_firing_boy). The granted Bake Bread is OPTIONAL (declinable FireTrigger via register, not register_auto) because granted sub-actions are optional unless 'you must'. Cap at one extra bake per action via the CARD_ID-not-in-triggers_resolved guard (text: 'a Bake Bread action', singular).
- errata: none (card_text.py reported no errata/clarifications)

#### teachers_desk  (tier 2, minor, conf high) — C_28.json
- template: agricola/cards/forestry_studies.py (optional before/after_action_space trigger that pushes PendingPlayOccupation with a card-set cost; gate on playable_occupations + once-per-use triggers_resolved). Cost-on-frame value differs (food=1, not the Lessons ramp) — Scholar/Forestry precedent for a non-Lessons fixed-cost occupation play.
- plan: register_minor('teachers_desk', cost=Cost(resources=Resources(wood=1)), min_occupations=1)  # prereq '1 Occupation' = min_occupations, NOT a cost.
register('before_action_space', 'teachers_desk', _eligible, _apply)  # OPTIONAL trigger ('you can also'); decline = host's Proceed. Both Major Improvement (PendingSubActionSpace, space_id 'major_improvement') and House Redevelopment (PendingHouseRedevelopment, space_id 'house_redevelopment') fire before_action_space in their before-phase enumerators — single registration covers both. NO register_action_space_hook (both spaces are non-atomic, already hosted).
_eligible(s,i,triggers_resolved): return 'teachers_desk' not in triggers_resolved AND s.pending_stack[-1].space_id in {'major_improvement','house_redevelopment'} AND s.players[i].resources.food>=1 AND bool(playable_occupations(s,i))  # liquidation-aware affordability for the 1-food is fine since gate also matched by enumerator's commit; never a dead-end fire.
_apply(s,i): return push(s, PendingPlayOccupation(player_idx=i, initiated_by_id='card:teachers_desk', cost=Resources(food=1)))  # _execute_play_occupation reads cost off the frame and debits 1 food. No on_play. No VPs. Not passing.
- ordering: TIMING = before, not after. 'Each time you use the action space' with NO 'after'/'immediately after' wording => before_action_space per the cheat-sheet ruling (Forestry Studies rides after_action_space ONLY because its text says 'after you use'). The one real subtlety: for House Redevelopment the before-phase fires at the host's push BEFORE the mandatory renovate has run, so the occupation play nests on top of a PendingHouseRedevelopment whose renovate is still unchosen — verify in implementation that pushing/popping PendingPlayOccupation in that before-window leaves the renovate-then-improvement Proceed lifecycle intact (this nesting depth is proven for the generic/atomic host via Forestry+Cottager but not specifically inside the House-Redev Proceed-host; smoke-test a play). Optionality lives at the parent host (no SkipTrigger); eligibility MUST gate on a playable hand occupation existing AND >=1 food because once PendingPlayOccupation is pushed its enumerator offers no decline (Scholar/Forestry precedent).
- errata: None. card_text.py reports no errata/clarifications. cost: 1 Wood; prereq: 1 Occupation; no VPs; not passing.
- open_q: Confirm pushing PendingPlayOccupation in the BEFORE phase of PendingHouseRedevelopment (renovate still mandatory-unchosen) cleanly returns to the renovate->improvement->Proceed lifecycle after the occupation pops — the only nesting interaction not directly exercised by the Forestry/Cottager precedents (which host on PendingActionSpace/PendingSubActionSpace, not the House-Redev Proceed-host). Low risk; verify with a play-through test, do not block.

#### elephantgrass_plant  (tier 2, minor, conf high) — C_34.json
- template: agricola/cards/furniture_carpenter.py (near-exact: food_out=0 harvest-conversion + CardStore bonus-point counter + register_scoring; also beer_keg.py)
- plan: register_minor('elephantgrass_plant', cost=Cost(Resources(clay=2, stone=1)), min_occupations=2)  # no on_play, no vps (the point is earned, not printed). register_harvest_conversion(HarvestConversionSpec(conversion_id='elephantgrass_plant', input_cost=Resources(reed=1), food_out=0, is_owned_fn=_eligible, side_effect_fn=_award)) where _eligible(s,i)= CARD_ID in s.players[i].minor_improvements (no extra ownership gate — unlike Furniture Carpenter there is no Joinery condition). _award banks +1 via p.card_state.set(CARD_ID, p.card_state.get(CARD_ID,0)+1). register_scoring(CARD_ID, lambda s,i: s.players[i].card_state.get(CARD_ID,0)).
- ordering: Timing: card says 'immediately after each harvest' but the only once-per-harvest seam in the engine is the FEED sub-phase HARVEST_CONVERSIONS mechanism (harvest_conversions_used reset once at FIELD = exactly once/harvest). This is the SAME accepted pattern Furniture Carpenter ('each harvest...') and Beer Keg use — there is no separate post-BREED seam. Safe because reed is never a feeding/cooking input, so surfacing the reed→VP swap mid-FEED rather than strictly after BREED has zero feeding interaction. Use food_out=0 (VP-only, NOT food). The point must be banked in CardStore and read back at scoring (no immediate-VP mechanism); do NOT set vps= (that scores the printed-keep VP, which is 0 here).
- errata: none reported by card_text.py (no errata/clarifications shown).
- open_q: Confirm the FEED-phase HARVEST_CONVERSIONS seam is the intended home for 'immediately after each harvest' (consistent with already-implemented Furniture Carpenter / Beer Keg); the engine has no separate after-harvest hook, and reed-vs-feeding non-interaction makes the sub-moment difference behaviorally inert.

#### clay_deposit  (tier 2, minor, conf high) — C_36.json
- template: basket.py (after_action_space exchange + return good to the space) fused with baking_sheet.py (bank a bonus point in CardStore + register_scoring); clay_pit hosting mirrors clay_puncher.py
- plan: register_minor('clay_deposit', cost=Cost(resources=Resources(food=2)), min_occupations=1)  # cost 2 Food; prereq '1 Occupation' = occupations-count prereq. register('after_action_space','clay_deposit',_eligible,_apply)  # OPTIONAL ('you can'); _eligible(s,i,tr): 'clay_deposit' not in tr AND s.pending_stack[-1].space_id=='clay_pit' AND s.players[i].resources.clay>=1. _apply: p.resources += Resources(clay=-1); p.card_state.set('clay_deposit', get(...,0)+1) to bank 1 bonus point; then return the clay to the space via get_space/with_space (sp.accumulated + Resources(clay=1)). register_action_space_hook('clay_deposit', {'clay_pit'})  # clay_pit is atomic. register_scoring('clay_deposit', lambda s,i: s.players[i].card_state.get('clay_deposit', 0)).
- ordering: Output is a BONUS POINT, not a resource — must be BANKED in CardStore per fire and read at scoring (register_scoring), NOT a flat vps= on the spec (that would award it without ever exchanging). 'Immediately after' = after_action_space (not before); once-per-action is enforced by triggers_resolved (each clay_pit use gets a fresh frame). 'place the clay on the accumulation space' = return the spent clay to clay_pit's accumulated (net: player loses 1 clay AND gains 1 VP; the clay sits back on the space for the next taker). OPTIONAL (register, not register_auto) since 'you can'.

#### farm_store  (tier 2, minor, conf high) — C_41.json
- template: agricola/cards/beer_keg.py (multi-entry HarvestConversionSpec with cross-variant once-per-harvest guard); food-as-input + non-food output precedent is agricola/cards/furniture_carpenter.py (input_cost=Resources(food=...), food_out=0, side_effect_fn grants the reward).
- plan: register_minor('farm_store', cost=Cost(resources=Resources(wood=2, clay=2)), vps=0).  Define 7 output variants: the 6 distinct building-resource pairs C(4,2) over {wood,clay,reed,stone} plus the single-veg option, e.g. _OUTPUTS = [Resources(wood=1,clay=1), Resources(wood=1,reed=1), Resources(wood=1,stone=1), Resources(clay=1,reed=1), Resources(clay=1,stone=1), Resources(reed=1,stone=1), Resources(veg=1)].  For each, register_harvest_conversion(HarvestConversionSpec(conversion_id=f'farm_store_{tag}', input_cost=Resources(food=1), food_out=0, is_owned_fn=_make_is_owned(), side_effect_fn=_make_grant(out))).  _make_is_owned: returns True iff 'farm_store' in p.minor_improvements AND no cid in p.harvest_conversions_used startswith 'farm_store' (cross-variant once-per-harvest guard, exactly beer_keg._make_is_owned).  _make_grant(out): p = fast_replace(p, resources=p.resources + out); _update_player.  No scoring term, no prereq, not passing.
- ordering: ONCE PER HARVEST across all 7 entries. Firing one variant marks only its own conversion_id in harvest_conversions_used; the enumerator re-checks is_owned_fn every call, so EACH variant's is_owned_fn must read harvest_conversions_used and return False once ANY 'farm_store_*' has fired (the beer_keg cross-variant guard). Omitting this lets the player exchange 1 food per variant (up to 7 food -> 14 goods) per harvest. side_effect_fn only adds goods (food_out=0, input_cost=Resources(food=1)), so no food double-count. Affordability/timing is correct-by-machinery: conversions are offered during HARVEST_FEED AFTER feeding cost is pre-debited and only when the 1 food is affordable, so 'after the feeding phase' maps exactly to spending surplus food (precedent: Furniture Carpenter's 'each harvest you can buy ... for food').
- errata: None. Verbatim: 'After the feeding phase of each harvest, you can exchange exactly 1 food for 2 different building resources of your choice or 1 vegetable.' cost 2 Wood 2 Clay; vps 0; not passing; no prereq.
- open_q: '2 DIFFERENT building resources' is read as exactly the 6 distinct unordered pairs (no doubles like wood+wood) plus the 1-veg option = 7 variants; confirm the intended reading is distinct-pair (not 'any 2 building resources, repeats allowed' which would be 10 multiset combos). The distinct-pair reading matches the card's word 'different'.

#### farm_building  (tier 2, minor, conf high) — C_43.json
- template: agricola/cards/clay_hut_builder.py (schedule_resources deferred-goods body) + agricola/cards/junk_room.py (register_auto on an improvement-build event). New module agricola/cards/farm_building.py.
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1, reed=1)), vps=1).  # no on-play, no prereq, no passing
register_auto("after_build_major", CARD_ID, lambda s, i: True, _apply).
def _apply(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1)).
Fires each major build (after_build_major dispatches via apply_auto_effects in _enter_after_phase, _execute_build_major step 4); apply_auto_effects already gates on ownership, so eligibility just returns True. Mandatory + choiceless => register_auto (not declinable register). Collection at start of each scheduled round is the existing future_resources plumbing (engine._complete_preparation), proven by the Well.
- ordering: Round indexing is the trap. schedule_resources takes 1-INDEXED rounds and does slot = rnd-1 internally, so 'next 3 round spaces' = range(R+1, R+4) (mirror Clay Hut Builder, NOT the Well's 0-indexed range(R, R+3) which writes future_resources[r] directly). schedule_resources already clamps rounds outside 1..14, so a late-game major (e.g. round 13 -> only round 14 gets food; round 14 -> nothing) is handled correctly = 'on each REMAINING round space'. Event must be after_build_major (majors only), NOT after_build_improvement (which also fires for minors).
- errata: None. Verbatim: 'Each time you build a major improvement, place 1 food on each of the next 3 round spaces. At the start of these rounds, you get the food.' cost 1 Clay/1 Reed; vps 1; no prereq; not passing; Corbarius Expansion deck C #43, category Food Provider.

#### stew  (tier 2, minor, conf high) — C_45.json
- template: agricola/cards/chophouse.py (near-exact: before_action_space schedule onto next-N round spaces, collected at start_of_round). Same shape but single space + fixed N=4.
- plan: register_minor('stew', cost=Cost(resources=Resources(clay=1)))  # no vps, not passing, no prereq
SPACES = frozenset({'day_laborer'})
_eligible(state, idx): return state.pending_stack[-1].space_id in SPACES
_apply(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R+1, R+1+4), Resources(food=1))
register_auto('before_action_space', 'stew', _eligible, _apply)  # 'each time you use' = before; pure-benefit -> auto (choiceless), matching Chophouse
register_action_space_hook('stew', SPACES)  # day_laborer is ATOMIC (in ATOMIC_HANDLERS) so must be explicitly hosted
- ordering: Two subtleties. (1) 'Each time you use the Day Laborer action space' = before_action_space per the Trigger-Timing ruling (a bare 'each time you use [space]' fires BEFORE the space's own effect, like Chophouse/Corn Scoop). Because food is placed onto FUTURE round spaces (not collected this turn), before/after is end-state-identical, but use before_action_space to honor the ruling. (2) day_laborer is ATOMIC, so it does NOT self-host -- register_action_space_hook is REQUIRED or the before_action_space frame is never pushed and the effect silently never fires (Cottager already hosts day_laborer this exact way). schedule_resources writes 1-indexed rounds R+1..R+4 and clamps slots outside 1..14, so late-game uses silently drop out-of-range round spaces ('each REMAINING round space'). Collection at round start is automatic via future_resources in engine._complete_preparation -- no start_of_round trigger needed.
- errata: None. card_text.py reports no errata/clarifications for stew.

#### garden_claw  (tier 2, minor, conf high) — C_47.json
- template: agricola/cards/trellises.py (deferred-goods Category 8, schedule_resources); planted-field counter copied from agricola/cards/ash_trees.py _prereq_two_planted_fields
- plan: register_minor("garden_claw", cost=Cost(resources=Resources(wood=1)), on_play=_on_play). _on_play(state, idx): R = state.round_number; grid = state.players[idx].farmyard.grid; planted = sum(1 for r in range(3) for c in range(5) if grid[r][c].cell_type == CellType.FIELD and (grid[r][c].grain > 0 or grid[r][c].veg > 0)); n = 3 * planted; return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(food=1)). No prereq, no vps, not passing. schedule_resources clamps slots to 1..14 so 'each REMAINING round space' is free; n==0 (no planted fields) schedules nothing.
- ordering: The cap is min(remaining round spaces, 3*planted_fields). DON'T add a separate min against rounds-left: schedule_resources silently drops slots outside 1..14, so range(R+1, R+1+3*planted) yields the 'each remaining round space, up to 3x' clamp for free (Trellises relies on exactly this). Also: count is 3x PLANTED fields (FIELD cell with grain>0 OR veg>0) measured AT PLAY-TIME on_play, not total/unplanted fields and not fence pieces; placement starts at R+1 (next round, never the current round), matching the Well/Trellises slot convention (slot N-1 holds round N).
- errata: none reported by card_text.py (no errata/clarifications block printed)

#### studio  (tier 2, minor, conf high) — C_55.json
- template: agricola/cards/beer_keg.py (the multi-variant once-per-harvest HarvestConversionSpec with cross-variant mutual-exclusion); simpler than Beer Keg because Studio has no banked points (no CardStore / side_effect_fn / scoring term).
- plan: register_minor('studio', cost=Cost(resources=Resources(clay=1, reed=1)), vps=1)  # printed point handled by register_minor's vps; no prereq, no on_play. Then register THREE HarvestConversionSpec entries (studio_wood: input Resources(wood=1) food_out=2; studio_clay: input Resources(clay=1) food_out=2; studio_stone: input Resources(stone=1) food_out=3), each with side_effect_fn=None. Each variant's is_owned_fn(state, idx): return ('studio' in state.players[idx].minor_improvements) AND not any(cid.startswith('studio') for cid in state.players[idx].harvest_conversions_used)  -- the cross-variant guard enforces 'use the card once per harvest'. Wire into cards/__init__.py with 'from agricola.cards import studio  # noqa: F401'.
- ordering: Cross-variant MUTUAL EXCLUSION is the load-bearing subtlety: the three options are ONE registry-of-three but 'exactly 1 wood/clay/stone' = the card may fire AT MOST ONCE per harvest. Each variant is a separate HARVEST_CONVERSIONS entry, and the enumerator gates only on is_owned_fn + affordability + 'conversion_id not in harvest_conversions_used'. The per-id used-set does NOT block the OTHER two ids, so is_owned_fn MUST read harvest_conversions_used directly and suppress ALL studio_* variants once any one has fired (mirror Beer Keg's _make_is_owned guard with cid.startswith('studio')). Without this guard a player could illegally fire wood+clay+stone in a single harvest. harvest_conversions_used is reset to empty at each harvest's FEED start, so each of the 6 harvests gets one fresh use.
- errata: None. Card text verbatim: 'In the feeding phase of each harvest, you can use this card to turn exactly 1 wood/clay/stone into 2/2/3 food.' Cost 1 Clay + 1 Reed; vps 1; no prereq; not passing. (Note: distinct from 'Studio Boat' [studio_boat], deck C #39, a different card.)
- open_q: None blocking. The wood/clay/stone are spent at face value (subtract-only) and produce food at 2/2/3 — matches the existing HarvestConversionSpec input_cost/food_out exactly. No conversion-closure or affordability-search machinery needed (these are raw resources the player already holds).

#### woodcraft  (tier 2, minor, conf high) — C_58.json
- template: agricola/cards/wood_cutter.py (action-space hook + register_auto) crossed with agricola/cards/basket.py (after_action_space + register_action_space_hook on the Forest wood space)
- plan: CARD_ID='woodcraft'; WOOD_SPACES=frozenset({'forest'}) (2p: Forest only).
_eligible(s,idx): return s.pending_stack[-1].space_id in WOOD_SPACES and s.players[idx].resources.wood <= 5  (threshold checked AFTER the space's wood income, which after_action_space guarantees).
_apply(s,idx): p=fast_replace(s.players[idx], resources=p.resources+Resources(food=1)); return fast_replace(s, players=tuple(p if i==idx else s.players[i] for i in range(2))).
register_minor(CARD_ID, cost=Cost(), min_occupations=1)  # prereq '1 Occupation' -> min_occupations=1; no spendable cost, no VPs, not passing.
register_auto('after_action_space', CARD_ID, _eligible, _apply)  # mandatory/choiceless -> auto, not a declinable FireTrigger.
register_action_space_hook(CARD_ID, WOOD_SPACES)  # host the atomic Forest space.
- ordering: MUST use the after_action_space event (NOT before): the '<=5 wood' threshold is read AFTER the Forest space's own +3 wood pickup lands; firing before would read pre-income wood and give food incorrectly. The clarification ('checked before cards that trigger after, e.g. Tree Guard C102') is about relative ordering AMONG after-triggers and does not change that this is an after_action_space effect. Use register_auto (mandatory, choiceless 'you get 1 food') and therefore NO triggers_resolved guard is needed (after-autos fire once per action-space flip naturally) — unlike Basket which guards because it is a declinable conversion.
- errata: Clarification (from card JSON): 'This effect is checked before cards that trigger "after", e.g. Tree Guard C102.' I.e. Woodcraft's after-trigger resolves ahead of other after-triggers; informational only for the single-card implementation.

#### schnapps_distillery  (tier 2, minor, conf high) — C_59.json
- template: agricola/cards/beer_keg.py (harvest-conversion + register_scoring twin); also harvest_conversions.py for the spec dataclass
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(stone=2, veg=1)), vps=2). One HarvestConversionSpec: register_harvest_conversion(HarvestConversionSpec(conversion_id='schnapps_distillery', input_cost=Resources(veg=1), food_out=5, is_owned_fn=lambda s,i: CARD_ID in s.players[i].minor_improvements, side_effect_fn=None)). No CardStore, no variants. register_scoring(CARD_ID, _score) where _score computes total_veg = p.resources.veg + sum(grid[r][c].veg for FIELD cells) then returns (1 if total_veg>=5 else 0) + (1 if total_veg>=6 else 0).
- ordering: The 5th/6th-vegetable scoring bonus MUST count vegetables exactly as scoring.py line 181 does: total_veg = resources.veg + sum(field-cell .veg), NOT just resources.veg. Using only supply veg undercounts a player holding vegetables on unharvested fields. The single conversion entry + per-FEED reset of harvest_conversions_used automatically enforces 'exactly 1 vegetable per feeding phase' (once-per-harvest), so no extra guard is needed.
- errata: None. Card text is unambiguous; cost 2 Stone + 1 Vegetable, 2 VP, not passing.

#### beer_stein  (tier 2, minor, conf high) — C_61.json
- template: agricola/cards/baking_sheet.py (A30) — IDENTICAL card text + clarification; Beer Stein differs only in cost (1 clay vs none) and prereq (none vs 'No Grain Field'). Same family: loppers.py (after-event optional trigger + CardStore-banked VP + register_scoring).
- plan: register_minor('beer_stein', cost=Cost(resources=Resources(clay=1)))  # no prereq, vps=0
register('after_bake_bread', 'beer_stein', _eligible, _apply)  # OPTIONAL trigger
register_scoring('beer_stein', _score)
_eligible(s,i,triggers_resolved): CARD_ID not in triggers_resolved and players[i].resources.grain >= 1
_apply(s,i): resources += Resources(grain=-1, food=2); card_state.set(CARD_ID, get(CARD_ID,0)+1); rebuild players tuple via fast_replace
_score(s,i): players[i].card_state.get('beer_stein', 0)  # 1 VP per fired exchange
- ordering: Use after_bake_bread, NOT before_bake_bread. The clarification 'You must bake normally to make this exchange' is satisfied structurally because PendingBakeBread's before-phase offers only FireTrigger+CommitBake, so the after-phase is reachable only once a normal bake is committed. before_bake_bread (Potter Ceramics' event) would let the exchange fire without a committed bake and could deplete grain the bake needs — wrong. The VP must be CardStore-banked + register_scoring (use-count dependent), NOT a flat vps= on the spec (which would award the point without ever exchanging). Once-per-action is automatic: _apply_fire_trigger stamps triggers_resolved before applying; each new bake action gets a fresh PendingBakeBread with empty triggers_resolved.
- errata: Clarification: 'You must bake normally to make this exchange.' No errata. cost 1 Clay; printed 0 VP (bonus point earned per exchange); deck C #61; Corbarius Expansion; Food Provider category.

#### corn_schnapps_distillery  (tier 2, minor, conf high) — C_64.json
- template: agricola/cards/plow_driver.py (optional start_of_round trigger, once-per-round used_this_round latch, pay-a-cost-then-effect) + agricola/cards/schedules.py:schedule_resources (deferred goods onto future round spaces, as in trellises.py / Well)
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=2)), vps=1, on_play=lambda s,i: s)  # no on-play effect; the recurring effect is the start_of_round trigger. _eligible(state, idx, triggers_resolved): CARD_ID not in p.used_this_round AND p.resources.grain >= 1. _apply(state, idx): debit 1 grain, latch used_this_round |= {CARD_ID}, then schedule_resources(state, idx, range(R+1, R+5), Resources(food=1)) where R=state.round_number (schedules food on the next 4 round spaces; clamps past round 14 for free). register('start_of_round', CARD_ID, _eligible, _apply); register_start_of_round_hook(CARD_ID)  # persistent every-round host, like Plow Driver (NOT Grassland Harrow's schedule-gated single host).
- ordering: The scheduled food lands on rounds R+1..R+4 (the NEXT 4 round spaces, exclusive of the current round R), collected at each of those rounds' start via future_resources in _complete_preparation/_collect path. Use range(R+1, R+5), NOT range(R, R+4). The once-per-round latch is correct because engine._complete_preparation clears used_this_round (step 3) BEFORE _fire_preparation_hook surfaces this round's start_of_round triggers (step 5) — so the latch resets each round automatically. Cost is plain grain (a real Resources field), so debit p.resources - Resources(grain=1) directly; NO PendingFoodPayment liquidation path is needed (unlike Plow Driver's food cost). Eligibility must require grain>=1 so the trigger is never a dead-end.
- errata: None in card_text.py output (no errata/clarifications printed). vps=1, cost 1 Wood + 2 Clay, not passing, no prerequisite, Corbarius Expansion deck C #64, category Food Provider.
- open_q: Modeling choice: the printed 'Once per round, you can pay...' is physically usable at ANY point during the round, but the only clean engine seam for a recurring per-round paid grant is the start_of_round trigger (this is how Plow Driver / Handplow model 'at the start of each round, you can' and the analogous 'once per round' grants). Firing only at round start (before worker placements) is a faithful and standard approximation here — worth a one-line confirm with the user but does not block implementation.

#### granary  (tier 2, minor, conf high) — C_65.json
- template: agricola/cards/strawberry_patch.py (Category-8 deferred-goods minor; uses schedule_resources on play). Closest non-relative-round sibling logic; copy its structure, swap food->grain and the relative range for the fixed rounds [8,10,12], and drop the prereq.
- plan: from agricola.cards.schedules import schedule_resources; from agricola.cards.specs import register_minor; from agricola.resources import Cost, Resources.
def _on_play(state, idx): return schedule_resources(state, idx, (8, 10, 12), Resources(grain=1))
register_minor('granary', cost=Cost(resources=Resources(wood=3, clay=3)), vps=1, on_play=_on_play)
No prereq, not passing. schedule_resources writes future_resources slots 7/9/11; engine._complete_preparation auto-collects grain into resources.grain at the start of rounds 8/10/12.
- ordering: schedule_resources uses FIXED 1-indexed rounds (8,10,12), NOT a play-round-relative range like Strawberry Patch's range(R+1,R+4) — do not subtract/add round_number. The 'remaining spaces' clause needs NO special handling: if Granary is played at/after round 8 or 10, schedule_resources still writes that slot but it was already distributed-and-cleared by _complete_preparation, so a past-round slot is a harmless dead write that is never re-collected — exactly matching 'place on the remaining spaces.' Collected grain lands in the general grain supply (resources.grain), not on a field.
- errata: None. Card text is complete; cost 3 Wood/3 Clay, 1 VP, no prerequisite, not passing.

#### clay_supply  (tier 2, minor, conf high) — C_77.json
- template: agricola/cards/lumberjack.py (relative next-N-round-spaces window via schedule_resources) / agricola/cards/reed_belt.py (minor wrapper)
- plan: register_minor("clay_supply", cost=Cost(resources=Resources(food=1)), on_play=_on_play). _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R+1, R+1+3), Resources(clay=1)). No prereq, no vps, not passing. schedule_resources writes slot r-1 (the engine Well-index convention) and clamps/drops any round > 14, matching 'next 3 round spaces' near game end.
- ordering: 'next 3 round spaces' = rounds R+1, R+2, R+3 (NOT the current round R, whose round-space goods were already collected when R was entered). Use range(R+1, R+1+3) exactly as Lumberjack does; do not start at R. schedule_resources clamps to the 14-round game so a late play (e.g. R=13) silently places on fewer than 3 spaces. Clay always fits (no accommodation), so no capacity concern. Collected automatically at start-of-round by engine._complete_preparation; no start_of_round hook or trigger needed.
- errata: none (no errata or clarifications printed); cost 1 Food, no prereq, no VPs, not passing

#### reed_hatted_toad  (tier 2, minor, conf high) — C_78.json
- template: agricola/cards/chick_stable.py (exact wording-twin: "Add X and Y to the current round and place N <good> on each corresponding round space. At the start of these rounds, you get the <good>." — on_play schedule_resources with an explicit offset list). Brewing Water is the same Category-8 deferred-goods family but triggered, not on-play.
- plan: Category 8 deferred-goods, pure on-play minor (no condition, no trigger). The numbers 5/7/9/11/13 are OFFSETS added to the current round (chick_stable's "Add 3 and 4 to the current round" -> [R+3,R+4]), so:
  def _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, [R+5, R+7, R+9, R+11, R+13], Resources(reed=1))
  register_minor("reed_hatted_toad", cost=Cost(resources=Resources(food=1)), on_play=_on_play)
schedule_resources writes future_resources slots (clamped to 1..14; out-of-range offsets silently dropped), collected at start-of-round by engine._complete_preparation. cost 1 food; no prereq; vps 0; not passing.
- ordering: The printed numbers 5,7,9,11,13 are OFFSETS to add to the current round (R+5..R+13), NOT absolute round numbers — verbatim text is 'Add 5, 7, 9, 11, and 13 to the current round', mirroring chick_stable's 'Add 3 and 4 to the current round' = [R+3,R+4]. Do not hardcode absolute rounds [5,7,9,11,13]; use [R+5,R+7,R+9,R+11,R+13]. schedule_resources clamps so a late play (where some offsets exceed round 14) correctly forfeits the unreachable round spaces per 'each corresponding round space'. Resource is REED (reed=1), not food.
- errata: Clarification: name was 'Toad' in the Wizkids printing. No rules errata.

#### stone_cart  (tier 2, minor, conf high) — C_79.json
- template: agricola/cards/sack_cart.py (near-exact copy; deferred-goods Category 8 via agricola/cards/schedules.py::schedule_resources)
- plan: register_minor("stone_cart", cost=Cost(resources=Resources(wood=2)), min_occupations=2, on_play=_on_play). _on_play(state, idx): R = state.round_number; remaining = [r for r in (2,4,6,8,10,12,14) if r > R]; return schedule_resources(state, idx, remaining, Resources(stone=1)). No vps, not passing. schedule_resources writes future_resources slots (collected at start of each scheduled round by engine._complete_preparation).
- ordering: "remaining" = rounds strictly AFTER the current round_number (r > R, not >=): a round already entered has had its space collected, so it must be excluded — mirror Sack Cart's `> R` filter exactly. The round set is the EVEN-numbered round spaces {2,4,6,8,10,12,14} (do NOT confuse with Sack Cart's {5,8,11,14}). schedule_resources is additive and clamps out-of-range slots, so no manual bounds check needed.
- errata: none (no errata or clarifications in card_text.py output or JSON metadata)

#### rocky_terrain  (tier 2, minor, conf high) — C_80.json
- template: agricola/cards/plow_hero.py (pay-food optional FireTrigger + food-payment resume) crossed with agricola/cards/barrow_pusher.py (the after_plow per-PendingPlow-commit event). Reward body differs: add +1 stone, NOT push a PendingPlow.
- plan: ["register_minor('rocky_terrain', cost=Cost(resources=Resources(food=1)))  # play cost 1 food; no prereq/vps/passing.", "register('after_plow', CARD_ID, _eligible, _apply); register_food_payment_resume(CARD_ID, _buy_stone)  # OPTIONAL declinable FireTrigger (each plow's after-phase enumerator surfaces it + Stop as decline).", "_eligible(s,i,triggers_resolved): CARD_ID not in triggers_resolved AND _liquidatable_to(s,i,p,Resources(food=1))  # once-per-plow; liquidation-aware (food is at-any-time convertible, per FOOD_PAYMENT_DESIGN / PAY_FOOD_PLOW_CARDS doc: use _liquidatable_to, NOT food>=1). No _can_plow gate (reward is goods, not a plow, so no dead-end).", "_apply(s,i): if food>=1 -> _buy_stone (debit 1 food, +1 stone directly); else push PendingFoodPayment(player_idx=i, food_needed=1, resume_kind=CARD_ID, reserved=Cost()).", "_buy_stone(s,i): p.resources + Resources(stone=1) - Resources(food=1) via fast_replace (reached directly OR as the food-payment resume which leaves raised food in supply to debit).", "Add import to agricola/cards/__init__.py. after_plow fires once per PendingPlow commit for the plowing player (verified via _enter_after_phase player_idx + barrow_pusher), so a multi-field plow (Cultivation/Mole Plow) correctly offers the buy once per field."]
- ordering: Event is after_plow (NOT before_action_space): the plow is the TRIGGER, the buy is the reward, and it must fire per-FIELD-PLOWED (once per PendingPlow commit, like barrow_pusher) not per space-use — a Cultivation/Mole-Plow multi-field plow offers the buy once per field. Reward is GOODS (+1 stone -1 food), so unlike every existing food-payment-resume card (plow_hero/ox_goad/etc. push a PendingPlow) the resume body just adds stone — and there is therefore NO _can_plow eligibility gate (the reward never dead-states). The clarification 'playing field cards counts as plowing' is INERT in the current engine (no field-tile-as-card type implemented; the play_minor path creates no FIELD cell), so no play_minor hook is needed.
- errata: Clarification: 'Playing field cards counts as plowing a field.' Inert in the current implementation (field-tile cards are not implemented). No errata.
- open_q: Liquidation depth of the reward's food cost: should 'buy 1 stone for 1 food' let the player liquidate OTHER goods (grain/veg/animals) into food to afford the 1 food (the rules-correct, doc-mandated _liquidatable_to reading, spec'd here), or be a plain food>=1 swap? Spec'd as liquidation-aware to match PAY_FOOD_PLOW_CARDS/FOOD_PAYMENT_DESIGN, but note: no existing food-payment-resume card has a goods reward (all push PendingPlow), so the resume->add-stone shape is new (low-risk: the resume mechanism is reward-agnostic). Confirm with user.

#### hardware_store  (tier 2, minor, conf high) — C_82.json
- template: agricola/cards/ox_goad.py (optional paid after_action_space trigger w/ food-payment liquidation) + agricola/cards/basket.py / loam_pit.py (day_laborer atomic space-host hook, flat-goods grant)
- plan: register_minor('hardware_store', cost=Cost(resources=Resources(wood=1, clay=1)), vps=1).  register('after_action_space','hardware_store',_eligible,_apply) where _eligible(s,i,triggers_resolved): 'hardware_store' not in triggers_resolved AND s.pending_stack[-1].space_id=='day_laborer' AND _liquidatable_to(s,i,p,Resources(food=2)) (never a dead-end; goods grant is always possible so only the 2-food payability gates).  _apply: if p.resources.food>=2 call _buy directly else push PendingFoodPayment(player_idx=i, food_needed=2, resume_kind='hardware_store', reserved=Cost()).  _buy(s,i): debit Resources(food=2), credit Resources(wood=1,clay=1,reed=1,stone=1); register_food_payment_resume('hardware_store',_buy).  register_action_space_hook('hardware_store', frozenset({'day_laborer'})) so atomic Day Laborer is hosted.
- ordering: Event MUST be after_action_space ('each time AFTER you use Day Laborer'), NOT before_action_space (contrast loam_pit/seasonal_worker which fire before). Once-per-use via 'hardware_store' in triggers_resolved. The 2-food cost must route through the liquidation path (PendingFoodPayment + register_food_payment_resume, the raise-only frame leaves food in supply for _buy to debit) like ox_goad — do NOT just subtract food in _apply, or a player short on banked food but rich in crops/animals is wrongly denied. Goods grant is flat (no PendingPlow), so the grant itself never gates eligibility — only food payability does.
- errata: none (no errata/clarifications printed)

#### field_watchman  (tier 2, occupation, conf high) — C_90.json
- template: agricola/cards/assistant_tiller.py (near-exact copy; same shape as cooperative_plower.py minus the extra occupancy condition)
- plan: register_occupation('field_watchman', lambda s,i: s)  # no on-play effect, no cost/prereq/vps. SPACES=frozenset({'grain_seeds'}). _eligible(s,i,triggers_resolved) = CARD_ID not in triggers_resolved and s.pending_stack[-1].space_id in SPACES and _can_plow(s.players[i]). _apply(s,i) = push(s, PendingPlow(player_idx=i, initiated_by_id='card:field_watchman')). register('before_action_space','field_watchman',_eligible,_apply). register_action_space_hook('field_watchman', SPACES)  # grain_seeds is ATOMIC (in ATOMIC_HANDLERS), so the hook is REQUIRED to host it. Add import in cards/__init__.py.
- ordering: grain_seeds is an ATOMIC space — without register_action_space_hook the before_action_space event never fires (atomic spaces are unhosted unless a hook claims them). The grant is OPTIONAL ('you can also plow') -> use register (declinable FireTrigger), NEVER register_auto. 'Each time you use [space]' = BEFORE phase (no 'immediately after'), and once-per-use is enforced by the host's triggers_resolved set (CARD_ID not in triggers_resolved). Gate on _can_plow so a dead-end plow is never offered.
- errata: None. Verbatim text: 'Each time you use the "Grain Seeds" action space, you can also plow 1 field.' No cost/prereq/vps/passing.

#### cube_cutter  (tier 2, occupation, conf high) — C_98.json
- template: agricola/cards/furniture_carpenter.py (near-exact copy; banks bonus points via HarvestConversionSpec.side_effect_fn + CardStore + register_scoring). beer_keg.py is the secondary reference.
- plan: register_occupation(cube_cutter, on_play=+1 wood) via p.resources + Resources(wood=1). register_harvest_conversion(HarvestConversionSpec(conversion_id='cube_cutter', input_cost=Resources(wood=1, food=1), food_out=0, is_owned_fn=_eligible, side_effect_fn=_award)). _eligible(state,idx) = (cube_cutter in state.players[idx].occupations) -- NO Joinery/major gate (differs from Furniture Carpenter). _award banks +1 in p.card_state[cube_cutter] (max 6 harvests). register_scoring(cube_cutter, lambda reads card_state.get('cube_cutter',0)). No cost/prereq/vps on the occupation itself (played via Lessons).
- ordering: The card text says 'field phase of each harvest' but the engine surfaces ALL harvest conversions during HARVEST_FEED, not the FIELD sub-phase -- this is the established, accepted approximation (Furniture Carpenter / Beer Keg do the same; field-vs-feed makes no mechanical difference here since the exchange touches no crops). Do NOT try to hook harvest_field. Also: the bonus point CANNOT be granted immediately (no immediate-VP mechanism) -- it MUST be banked in CardStore and read back by register_scoring at end-game, exactly like furniture_carpenter. Affordability (1 wood + 1 food) and the once-per-harvest cap are handled by the legality enumerator (_can_afford + harvest_conversions_used) automatically -- don't re-implement them.
- errata: None reported by card_text.py (no errata/clarification fields). 'exactly 1 wood and 1 food' = single fixed-cost exchange; 'each harvest' + the engine's harvest_conversions_used set make it once-per-harvest (the natural reading of 'exchange exactly ... for 1 bonus point').
- open_q: Is the exchange intended once per harvest (engine default for a single registered conversion id), or repeatable within a harvest? Card text 'exchange exactly 1 wood and 1 food for 1 bonus point' reads as one fixed exchange per harvest; implementing as once-per-harvest (the established pattern). Worth a one-line confirm but low-risk.

### Defer (by blocker)

**3plus_only_space**
- forest_reviewer — 

**4plus_player_and_new_shared_infra**
- parrot_breeder — 

**4plus_player_only_no_2p_branch**
- potato_digger — 

**accommodation_capacity_new_slot_kind**
- stable_master — 

**action-board-geometry**
- legworker — 

**after_phase_mandatory_with_choice_gate**
- seaweed_fertilizer — 

**alt_cost_A_or_B**
- chicken_coop — 

**ambiguous-last-one-stable-reward-semantics**
- feed_fence — 

**animal_in_pasture_location**
- mineral_feeder — 

**at-any-time / standalone player-initiated action**
- roll_over_plow — 

**at-any-time-standalone-optional-action**
- mason — 

**at_any_time_conversion_food_payment**
- basketmakers_wife — 

**at_any_time_food_build_cost**
- stable_cleaner — 

**at_any_time_standalone**
- sower — 

**at_any_time_standalone_conversion**
- stall_holder — 
- crudit — 
- land_consolidation — 

**build-major-on-play**
- basket_weaver — 

**buy-good-for-food**
- stone_buyer — 

**buy_food_to_good**
- basket_carrier — 

**card_as_animal_holder**
- cattle_farm — 
- mud_wallower — 

**card_as_field**
- lettuce_patch — 

**card_as_new_action_space**
- forest_owner — 

**card_granted_family_growth_no_space**
- lover — 

**card_owned_action_space**
- collector — 

**card_provides_room**
- den_builder — 

**cook_to_food_event**
- gypsys_crock — 

**extra_worker_placement**
- nightworker — 
- basket_chair — 
- carriage_trip — 
- inner_districts_director — 

**fence_ordinal_free**
- carpenters_apprentice — 

**first_renovation_latch**
- wood_slide_hammer — 

**four_player_only_duplicate_accumulation_spaces**
- twin_researcher — 

**global_each_player_conditional_scoring**
- constable — 

**grant-retake-action-space**
- merchant — 

**granted_build_major_subaction**
- small_potters_oven — 

**granted_family_growth_no_space**
- bed_in_the_grain_field — 

**harvest-conversion-needs-field-grain-and-earned-vp**
- craft_brewery — 

**harvest_conversion_repeatable_and_geometry**
- beer_stall — 

**harvest_cooking_double_rate**
- cooking_hearth_extension — 

**harvest_phase_skip**
- layabout — 

**harvest_timing_and_offspace_family_growth**
- autumn_mother — 

**hidden-round-space-identity**
- outrider — 

**immediate-animal-grant-no-accommodation**
- green_grocer — 
- german_heath_keeper — 

**immediate_animal_grant**
- animal_feeder — 
- game_catcher — 
- automatic_water_trough — 

**immediate_animal_grant_no_accommodation**
- early_cattle — 

**immediate_animal_grant_plus_recurring_harvest_obligation**
- animal_catcher — 

**majors_via_minor_action**
- blueprint — 

**midgame_vp_grant_and_atwill_conversion**
- mandoline — 

**missing_action_space**
- outskirts_director — 

**missing_action_space_traveling_players**
- fishermans_friend — 

**multi-grant-per-use**
- swing_plow — 

**multi_space_single_worker_placement**
- job_contract — 

**needs-end-of-turn-event**
- farmstead — 

**needs-new-shared-infra**
- harvest_festival_planning — 

**needs-new-shared-infra (breeding-phase hook event) + buy-good-for-food conversion**
- stone_importer — 

**needs-shared-infra-built-major-identity**
- charcoal_burner — 

**needs_end_of_harvest_event_seam**
- eternal_rye_cultivation — 

**needs_negative_points_accessor**
- writing_chamber — 

**needs_new_event_before_place_person**
- forest_campaigner — 

**needs_return_home_phase_hook_AND_4plus_scope**
- food_distributor — 

**new-cell-field-and-custom-field-harvest**
- stone_clearing — 

**new-shared-action-space**
- studio_boat — 

**new_feeding_phase_hook_event**
- baker — 

**no_grain_obtain_event**
- agricultural_labourer — 

**no_traveling_players_space__four_plus_player_card**
- puppeteer — 

**numeric_granted_placement**
- timber_shingle_maker — 

**opponent-placement-legality + return-home-accumulation-deposit**
- fishing_net — 

**opponent_optional_trigger**
- pattern_maker — 

**opponent_routed_optional_trigger**
- sowing_director — 

**opponent_side_scoring_award**
- ranch_provost — 

**optional-out-of-turn-trigger + granted-build-room-for-nonacting-player**
- resource_recycler — 

**optional_field_phase_decision + cross_player_food_grant**
- beer_table — 

**out-of-scope-4plus + immediate-animal-grant + buy-food-to-good-conversion**
- cattle_buyer — 

**out_of_scope_3plus_player**
- reed_roof_renovator — 

**out_of_scope_4plus_player_only**
- material_deliveryman — 

**out_of_scope_player_count**
- hoof_caregiver — 

**people_capacity_growth_gate**
- bunk_beds — 

**per_card_goods_stack**
- workshop_assistant — 

**per_cell_animal_location**
- cow_prince — 

**per_container_animal_tracking_and_consumable_keyed_capacity**
- livestock_feeder — 

**play_occupation_introspection**
- furniture_maker — 

**plow_affordability_gate**
- dwelling_mound — 

**plow_geometry_relaxation**
- newly_plowed_field — 

**raze_fences_and_animal_preservation**
- overhaul — 

**return_home_event**
- seed_researcher — 

**return_home_firing_seam + card_stockpile_liquidation_to_supply**
- firewood — 

**reveal_event_AND_personless_family_growth**
- heart_of_stone — 

**ruling_ambiguity_gross_vs_net_animal_acquisition**
- huntsmans_hat — 

**scoring_phase_agent_choice**
- garden_designer — 

**single_type_breed**
- perennial_rye — 

**standalone_at_any_time_conversion**
- stable_yard — 

**subaction_substitution_at_minor_host**
- packaging_artist — 

**takes-scope-ambiguity**
- material_hub — 

**temp_extra_worker**
- ravenous_hunger — 

**typed_animal_holder_accommodation**
- wildlife_reserve — 

## Deck D — 48 implement / 46 defer (94 triaged)

### Implement

#### clay_supports  (tier 1, minor, conf high) — D_15.json
- template: agricola/cards/carpenters_parlor.py (minor + register_formula on build_room, gated by house material); see also clay_plasterer.py build_room clause (identical _in_clay_house gate).
- plan: Passive cost-FORMULA minor. CARD_ID='clay_supports'. def _in_clay_house(state, idx, ctx) -> bool: return state.players[idx].house_material == HouseMaterial.CLAY. def _formula(state, idx, ctx) -> Resources: return Resources(clay=2, wood=1, reed=1). register_formula('build_room', CARD_ID, _in_clay_house, _formula). register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2))). No prereq, no vps, no on_play. Add import in cards/__init__.py.
- ordering: The applies-gate must be house_material == HouseMaterial.CLAY (a 'clay room' = a room built while living in a clay house; printed ROOM_COSTS[CLAY] = 5 clay + 2 reed, matching the card's 'instead of'). This mirrors clay_plasterer's existing _in_clay_house clause exactly. Do NOT gate on the room cell type or to_material (that is renovate ctx, not build_room). The formula is mutually exclusive with the printed base; effective_payments offers both and Pareto-min keeps the cheaper, so no need to hand-check that 2 clay+1 wood+1 reed beats 5 clay+2 reed.
- errata: None reported by card_text.py (no errata/clarifications block).

#### artisan_district  (tier 1, minor, conf high) — D_30.json
- template: agricola/cards/pottery_yard.py (minor + register_scoring reading major_improvement_owners; cost/prereq/vps via register_minor)
- plan: register_minor('artisan_district', cost=Cost(Resources(stone=1)), prereq=lambda s,i: len(s.players[i].occupations) >= 3, vps=1).  register_scoring('artisan_district', _score) where _score counts n = number of bottom-row majors owned by i: n = sum(1 for m in (5,6,7,8,9) if s.board.major_improvement_owners[m] == i); return {3:2,4:5,5:8}.get(n, 0).  'prereq 3 Occupations' = PREREQ (len(occupations)>=3), NOT a cost. Printed VP 1 scored automatically by vps=1; the 2/5/8 bonus is the register_scoring term.
- ordering: 'bottom row of the supply board' is physical board geometry not stored in the engine. The 10 majors index Fireplace/Fireplace/Hearth/Hearth/Well as the TOP row (indices 0-4) and the five work-station crafts Clay Oven/Stone Oven/Joinery/Pottery/Basketmaker as the BOTTOM row (indices 5,6,7,8,9). Count ONLY indices 5-9 owned by THIS player (== i, not 'is not None'). Bonus is a step function on the count (3->2, 4->5, 5->8), nothing below 3, and exactly 5 bottom-row majors exist so 5 is the cap.
- errata: none reported by card_text.py
- open_q: Confirm the engine's bottom-row major mapping is indices 5-9 (the five non-cooking crafts: Clay Oven, Stone Oven, Joinery, Pottery, Basketmaker's Workshop) vs top-row 0-4 (Fireplaces, Cooking Hearths, Well). This matches the physical supply-board layout and is high-confidence, but it is the one assumption to verify with the user.

#### storeroom  (tier 1, minor, conf high) — D_31.json
- template: agricola/cards/big_country.py (minor with register_minor(vps=...) + register_scoring); crop-counting idiom mirrored from agricola/scoring.py lines 172-186
- plan: register_minor(CARD_ID, cost=Cost(Resources(wood=1, stone=2)), vps=1) and register_scoring(CARD_ID, _score). _score(state, idx): pool total = total_grain + total_veg where each = ps.resources.<crop> + sum of grid[r][c].<crop> over r in range(3), c in range(5) where cell_type == CellType.FIELD (verbatim scoring.py idiom). pairs = total // 2; return points = -(-pairs // 2) i.e. math.ceil(pairs / 2) -- '1/2 point per pair, rounded up'. No on_play, no prereq, no passing.
- ordering: The bonus math is the whole risk: a 'pair' = 2 crops drawn from the POOLED grain+vegetable count (not grain-paired-with-veg separately), so total = grain+veg pooled, pairs = total // 2, then 1/2 point per pair rounded UP => ceil(pairs/2). Two nested halvings (crops->pairs, pairs->points) with a single ceil only on the second. e.g. 5 grain + 4 veg = 9 crops -> 4 pairs -> ceil(4/2)=2 pts; 3+0=3 crops -> 1 pair -> ceil(1/2)=1 pt. Count grain/veg across BOTH supply and FIELD cells (cell_type==FIELD only), not pasture/other cells.
- errata: none reported by card_text.py
- open_q: Exact rounding interpretation of '1/2 bonus point for each pair ... rounded up': taken as points = ceil((grain+veg)//2 / 2). If the intended reading is instead 1 point per pair-of-(grain,veg) matched columns or a different pairing, the formula changes -- worth a one-line confirm, but the pooled-crops reading matches the parenthetical 'considering all crops in your supply and fields'.

#### summer_house  (tier 1, minor, conf high) — D_33.json
- template: agricola/cards/stable_architect.py (pure register_scoring) + agricola/cards/big_country.py / milking_parlor.py (house_material prereq + EMPTY-and-not-enclosed unused-cell definition)
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3, stone=1)), prereq=_in_wooden_house, on_play=lambda s,i: s)  # prereq: state.players[i].house_material == HouseMaterial.WOOD (play-time). register_scoring(CARD_ID, _score). _score returns 0 unless players[i].house_material == HouseMaterial.STONE at end-game; else 2 * (count of cells that are EMPTY and not in enclosed_cells(fy) and orthogonally adjacent to at least one CellType.ROOM cell). Compute room cells = {(r,c): grid[r][c].cell_type==ROOM}; for each unused cell check its up/down/left/right neighbors (in-bounds 3x5 grid) for membership in room cells. No CardStore, no on-play effect.
- ordering: House material is OPPOSITE at the two timings: prereq requires WOOD to PLAY the card, but the +2 bonus only pays out if the house is STONE at SCORING. Gate the scoring term on house_material==STONE (return 0 otherwise) and the prereq on house_material==WOOD; don't conflate. 'Unused' MUST be EMPTY-and-not-enclosed (a fenced-but-empty pasture cell reads EMPTY but is USED), matching scoring.py:195. The parenthetical 'you still lose the points for these unused spaces' confirms base scoring already subtracts -1 per unused cell; this card adds an INDEPENDENT +2 per qualifying cell, so do NOT try to offset/cancel the base penalty.
- errata: None reported by card_text.py. Note the play-time prereq ('Still in Wooden House') vs scoring-time stone-house condition is printed-card design, not errata.

#### luxurious_hostel  (tier 1, minor, conf high) — D_34.json
- template: agricola/cards/stable_architect.py (register_scoring scoring-term pattern), but registered via register_minor instead of register_occupation
- plan: register_minor('luxurious_hostel', cost=Cost(resources=Resources(wood=1, clay=2)), on_play=lambda s, i: s)  # no on-play effect; vps=0 (the 4 pts are conditional, awarded by the scoring term, not a flat VP). register_scoring('luxurious_hostel', _score) where _score(state, idx): ps = state.players[idx]; num_rooms = count grid cells with cell_type==CellType.ROOM; stone_rooms = num_rooms if ps.house_material==HouseMaterial.STONE else 0; return 4 if stone_rooms > ps.people_total else 0.
- ordering: Award is conditional (+4 only if stone_rooms > people_total) and must NOT go in register_minor's vps= (that is a flat unconditional VP) — it belongs in the register_scoring term, evaluated at end-game on the final farmyard. 'more stone rooms than people' is STRICT > (not >=). Use ps.people_total (total people incl. placed, range 2-5), NOT people_home. stone_rooms is 0 unless house_material==STONE (all rooms share one material), so a player with e.g. 3 stone rooms and 2 people scores +4; equal counts score 0.
- errata: No errata or clarifications printed. Cost 1 Wood + 2 Clay; no prereq; passing=false; printed vps field is the conditional 4-bonus (implemented via scoring term, not flat vps).
- open_q: The clause 'You can only use one card to get bonus points for your stone house' is a multi-card de-duplication rule across the Dulcinaria stone-house bonus cards. No other such card is implemented today, so this clause is inert and a standalone scoring term is faithful. If/when a sibling stone-house bonus card is added, a shared cross-card mutual-exclusion mechanism would be needed (out of scope now; not a blocker for this card).

#### fodder_chamber  (tier 1, minor, conf high) — D_35.json
- template: agricola/cards/manger.py (pure end-game scoring minor with printed vps; same shape as stable_architect.py)
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(stone=3, grain=3)), vps=2). register_scoring(CARD_ID, _score) where _score(state, idx) reads a = state.players[idx].animals; total = a.sheep + a.boar + a.cattle; return total // 5 (2-player: 1 bonus pt per 5th animal). No on_play, no prereq, no passing. PlayerState.animals is the canonical farm-total (already includes pasture/stable/house animals) and is exactly what score() reads for animal scoring.
- ordering: Threshold is divisor-based and player-count-specific: in the 2-player game it is the 5th-animal tier, so the bonus is floor(total_animals / 5), NOT // 7 (1p) or // 4 (3p) or // 3 (4p). Use integer floor division (every COMPLETE group of 5). The printed 2 vps is separate and rides on register_minor(vps=2) — do NOT add it inside _score (that would double-count); register_scoring returns ONLY the per-5-animals bonus.
- errata: None reported by card_text.py (no errata/clarifications section emitted).

#### sculpture  (tier 1, minor, conf high) — D_37.json
- template: agricola/cards/big_country.py (prereq computed from 14-round_number and farmyard cell usage) + agricola/cards/strawberry_patch.py (cost=Cost + prereq + vps=2, no on_play/register_scoring)
- plan: register_minor("sculpture", cost=Cost(resources=Resources(stone=1)), prereq=_prereq, vps=2). _prereq(state, idx): complete_rounds_left = 14 - state.round_number; unused = count of farmyard cells where grid[r][c].cell_type is CellType.EMPTY AND (r,c) not in enclosed_cells(fy) (over 3x5); return complete_rounds_left > unused. No on_play, no register_scoring (vps=2 auto-summed at scoring.py:248).
- ordering: The prereq is a STRICT '>' (more rounds left THAN unused spaces), not '>='. 'Complete rounds left' = rounds played AFTER the in-progress current round = 14 - round_number (mirror Big Country: round 14 -> 0 left). 'Unused farmyard spaces' must count a fenced-but-empty pasture cell (cell_type==EMPTY but enclosed) as USED, so the unused count = cells that are EMPTY AND NOT in enclosed_cells(fy) -- exactly the complement of big_country._all_farmyard_spaces_used. Counting raw cell_type==EMPTY would overcount unused and wrongly relax the prereq.
- errata: None reported by card_text.py. Prereq text is printed-on-card ('prereq: see below'); no errata/clarification block returned.

#### cross_cut_wood  (tier 1, minor, conf high) — D_4.json
- template: agricola/cards/consultant.py (on-play goods grant) / agricola/cards/market_stall.py (register_minor with cost+prereq)
- plan: def _on_play(state, idx): p = state.players[idx]; n = p.resources.stone; p = fast_replace(p, resources=p.resources + Resources(wood=n)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). register_minor("cross_cut_wood", cost=Cost(resources=Resources(food=1)), min_occupations=3, on_play=_on_play). No vps, not passing.
- ordering: Amount is computed from the CURRENT supply: wood gained = p.resources.stone at play time (read fresh inside _on_play, do not precompute). It only ADDS wood (does not consume the stone) — the stone count is just the multiplier. '3 Occupations' is a PREREQUISITE (min_occupations=3), not a cost; the only cost is 1 food.

#### hutch  (tier 1, minor, conf high) — D_43.json
- template: agricola/cards/strawberry_patch.py (Category-8 deferred-goods; uses schedules.schedule_resources). Pond Hut is the same shape.
- plan: register_minor('hutch', cost=Cost(resources=Resources(wood=1, reed=1)), vps=1, on_play=_on_play). No prereq, not passing. In _on_play(state, idx): R = state.round_number; place increasing food on the next 4 round spaces: amount k food on round R+1+k for k in 0..3 (so R+1 gets 0 = skip, R+2 gets 1, R+3 gets 2, R+4 gets 3). Either loop calling schedule_resources(state, idx, [R+1+k], Resources(food=k)) for k in 1..3 (skip the 0), or one chained call per amount. schedule_resources clamps rounds past 14 / already-past, so late-game plays silently drop overflow slots.
- ordering: Off-by-one alignment of amount-to-round is the only trap: amounts are 0,1,2,3 IN THIS ORDER on rounds R+1,R+2,R+3,R+4 (R = current round_number). So the increasing food maps amount k -> round R+1+k for k in 0..3; R+1 (the very next round) gets 0 food and is a genuine no-op, NOT round R. Do not place a flat amount across all 4 rounds (that is the Strawberry Patch shape) and do not start the food at the current round.
- errata: None. No prerequisites, passing_left null, vps 1, cost '1 Wood,1 Reed', card_category Food Provider, Consul Dirigens (deck D #43). No clarifications in the JSON.

#### forest_well  (tier 1, minor, conf high) — D_44.json
- template: agricola/cards/thick_forest.py (remaining-round-space scheduler) crossed with agricola/cards/trellises.py ("up to N" count cap, no goods spent)
- plan: register_minor("forest_well", cost=Cost(resources=Resources(stone=1, food=1)), min_occupations=2, vps=1, on_play=_on_play). _on_play(state, idx): R = state.round_number; n = state.players[idx].resources.wood; rounds = list(range(R + 1, 15))[:n]; return schedule_resources(state, idx, rounds, Resources(food=1)). Each scheduled round gets +1 food collected at start-of-round by engine._complete_preparation via future_resources.
- ordering: "up to the amount of wood in your supply" caps the COUNT of round spaces, NOT a per-space wood debit — wood is never spent (printed cost is only 1 stone + 1 food). So slice the first `wood` of the remaining rounds (range(R+1,15)[:wood]); do NOT add wood to Cost and do NOT remove wood. schedule_resources already clamps to <=14, so an oversized wood count just maxes out at "every remaining round space". Read wood AT PLAY (resources.wood); the cost (1 stone + 1 food) is debited by the play-card engine BEFORE on_play runs, but stone/food don't affect the wood count so order is moot here.
- errata: None (card_text.py reported no errata/clarifications).

#### civic_facade  (tier 1, minor, conf high) — D_48.json
- template: agricola/cards/pavior.py (mandatory start_of_round food grant via register_auto, eligibility re-checked each round). Cost pattern from drinking_trough.py: cost=Cost(resources=Resources(clay=1)). Room-count prereq pattern from animal_tamer.py's _num_rooms (count CellType.ROOM cells in farmyard grid).
- plan: ["CARD_ID='civic_facade'; from agricola.cards.specs import register_minor; from agricola.cards.triggers import register_auto, register_start_of_round_hook; from agricola.resources import Cost, Resources; from agricola.constants import CellType.", "_num_rooms(p) = sum(1 for r in range(3) for c in range(5) if p.farmyard.grid[r][c].cell_type == CellType.ROOM)  # copied from animal_tamer.", "prereq(state, idx) -> bool: return _num_rooms(state.players[idx]) >= 3   # '3 Rooms' is a HAVE-check at play time.", "_eligible(state, idx) -> bool: p=state.players[idx]; return len(p.hand_occupations) > len(p.hand_minors)   # STRICT >, counts UNPLAYED hand cards.", "_apply(state, idx) -> state: p=state.players[idx]; p=fast_replace(p, resources=p.resources+Resources(food=1)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))).", "register_minor('civic_facade', cost=Cost(resources=Resources(clay=1)), prereq=prereq); register_auto('start_of_round','civic_facade',_eligible,_apply); register_start_of_round_hook('civic_facade'); add import to cards/__init__.py."]
- ordering: Two strict subtleties: (1) the condition compares the player's UNPLAYED HAND (p.hand_occupations vs p.hand_minors frozensets), NOT the played occupations/minor_improvements lists — 'in your hand' is literal; most cards reference played cards, this one does not. (2) STRICT inequality (more occupations than improvements => len(occ) > len(min), not >=); a tie grants nothing. 'Improvements in your hand' = hand_minors only (the hand contains exactly occupations + minor improvements; no majors are ever in hand). Timing 'before the start of each round' = the start_of_round auto hook, which fires AFTER _complete_preparation has incremented round_number — fine here since the effect is round-independent. Eligibility is re-evaluated every round, so as the player plays cards out of hand the grant naturally turns on/off; mandatory choice-free => register_auto, not register.
- errata: None reported. No errata/clarification block returned by card_text.py.

#### field_clay  (tier 1, minor, conf high) — D_5.json
- template: agricola/cards/ash_trees.py (planted-field count + minor on-play) crossed with market_stall.py (Cost(food=1) + scaled-goods on_play; no passing)
- plan: register_minor("field_clay", cost=Cost(resources=Resources(food=1)), prereq=_one_planted_field, vps=0, on_play=_on_play). _one_planted_field(state,idx): >=1 FIELD cell with grain>0 or veg>0 (copy ash_trees._prereq_two_planted_fields, threshold 1). _on_play(state,idx): n = count of those planted FIELD cells; p = fast_replace(p, resources=p.resources + Resources(clay=n)); splice player back into state.players. No CardStore, no triggers, no passing.
- ordering: A 'planted field' is a FIELD cell with a crop on it (grain>0 OR veg>0) at play-time, NOT every FIELD cell. A freshly-plowed-but-unsown field does not count — counting all FIELD cells would over-grant. Reuse ash_trees' exact predicate (grain>0 or veg>0). The grant is computed immediately at play; prereq of 1 planted field guarantees n>=1.
- errata: none (no errata/clarifications returned by card_text.py)

#### trout_pool  (tier 1, minor, conf high) — D_54.json
- template: agricola/cards/nest_site.py (start_of_round auto reading an accumulation space via get_space(...).accumulated.X); pavior.py / small_scale_farmer.py for the register_auto + register_start_of_round_hook + register_minor shape
- plan: register_minor("trout_pool", cost=Cost(resources=Resources(clay=2)), vps=1)  # 1 VP, cost 2 clay, no prereq/passing. _eligible(state, idx) -> get_space(state.board, "fishing").accumulated.food >= 3. _apply(state, idx) -> add Resources(food=1) to players[idx] via fast_replace (same body as nest_site). register_auto("start_of_round", "trout_pool", _eligible, _apply); register_start_of_round_hook("trout_pool"). Add import in cards/__init__.py.
- ordering: Eligibility reads the POST-REFILL Fishing food count: _complete_preparation runs the +1-food refill BEFORE firing start_of_round autos (per nest_site docstring). The card's '3 food at the start of the work phase' refers to that post-refill board, so the literal threshold get_space(...).accumulated.food >= 3 is correct AS-WRITTEN with NO off-by-one adjustment (unlike Nest Site, which used >=2 to back out the refill because its condition was about the pre-refill bank). Round 1 is naturally excluded (no preparation phase before the first WORK state). Choice-free mandatory income -> register_auto, never an optional FireTrigger.
- errata: None. Verbatim text: 'At the start of each work phase, if there are at least 3 food on the "Fishing" accumulation space, you get 1 food from the general supply.' Dulcinaria Expansion, deck D #54, Food Provider, cost 2 Clay, 1 VP, not passing, no prereq.

#### new_market  (tier 1, minor, conf high) — D_55.json
- template: agricola/cards/calcium_fertilizers.py (before_action_space auto-effect + register_action_space_hook over a fixed space set, any_player=False). Milk Jug is the food-grant body analog.
- plan: NEW_MARKET_SPACES = frozenset({'vegetable_seeds','pig_market','cattle_market','eastern_quarry'}) (= all of stage 3 + stage 4 cards, which exactly fill round slots 8-11; the within-stage shuffle is hidden but the UNION is order-independent and public). _eligible(state, idx) -> state.pending_stack[-1].space_id in NEW_MARKET_SPACES. _apply(state, idx) -> add Resources(food=1) to players[idx] via fast_replace. register_minor('new_market', cost=Cost(resources=Resources(wood=1, clay=1)), vps=1). register_auto('before_action_space', 'new_market', _eligible, _apply)  # any_player defaults False. register_action_space_hook('new_market', NEW_MARKET_SPACES)  # hosts the two ATOMIC members (vegetable_seeds, eastern_quarry); harmless for the two non-atomic ones (pig_market, cattle_market already host).
- ordering: Use before_action_space (the project's 'each time you use [space]' ruling) NOT after_action_space, and any_player=False (card says 'you', unlike Milk Jug's any_player=True). The food grant is timing-neutral, but before_action_space is what hosts the atomic spaces and matches the ruling. register_action_space_hook is REQUIRED because vegetable_seeds and eastern_quarry are atomic (no host frame by default) so before_action_space would never fire on them otherwise; pig_market/cattle_market are non-atomic and already hosted.
- errata: None reported by card_text (no errata/clarifications printed).
- open_q: Confirm the rules reading that 'round spaces 8 to 11' = the four stage-3+4 action-space CARDS (vegetable_seeds, pig_market, cattle_market, eastern_quarry), not any permanent space. This is robust because rounds 8-9 = all of stage 3 and rounds 10-11 = all of stage 4, so the set is fixed regardless of the hidden per-game reveal order (no hidden-info dependence) — but a reviewer who knows the physical card should sanity-check this mapping.

#### wholesale_market  (tier 1, minor, conf high) — D_57.json
- template: agricola/cards/trellises.py (closest: on-play schedule_resources of food onto future round spaces; also lumberjack.py / chophouse.py)
- plan: from agricola.cards.schedules import schedule_resources; from agricola.cards.specs import register_minor; cost=Cost(resources=Resources(wood=2,vegetable=2)), vps=3, not passing, no prereq. _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R+1, 15), Resources(food=1)).  register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, vegetable=2)), vps=3, on_play=_on_play).  No trigger registration needed: future_resources are collected automatically in engine._complete_preparation at start of each scheduled round.
- ordering: Use range(R+1, 15) -- 'each REMAINING round space' = rounds R+1..14 (1-indexed printed round numbers), with NO count cap (unlike trellises/lumberjack which cap at fences built). schedule_resources clamps slots to 1..14 so any out-of-range round is silently dropped; the upper bound 15 is exclusive so round 14 IS included. Do NOT start at R (the current round's goods were already collected when this round was entered) -- start at R+1, matching trellises/chophouse. Resources field name is 'vegetable' (the veg cost) -- confirm exact field name against agricola.resources.Resources before writing.
- errata: None. card_text.py reported no errata/clarifications for this card.

#### bale_of_straw  (tier 1, minor, conf high) — D_61.json
- template: agricola/cards/butter_churn.py (register_auto on harvest_field; conditional food grant). Also crack_weeder.py for the FIELD/grain-cell counting idiom.
- plan: register_minor("bale_of_straw", cost=<from data json>, vps=<from data json>). Define _eligible(state, idx) -> sum(1 for row in p.farmyard.grid for cell in row if cell.cell_type==CellType.FIELD and cell.grain>0) >= 3. Define _apply(state, idx): if eligible, p.resources + Resources(food=2) via fast_replace (mirror butter_churn._apply's player-tuple rebuild). register_auto("harvest_field", CARD_ID, _eligible, _apply); register_harvest_field_hook(CARD_ID). No CardStore, no prereq beyond what data json lists.
- ordering: harvest_field fires BEFORE the mechanical crop take (engine.py:1242, _fire_harvest_field_hook runs first in _resolve_harvest_field), so _eligible reads the STILL-SOWN grid — count grain-sown FIELD cells (grain>0). 'At the start of each harvest' = the field phase (first harvest sub-phase FIELD->FEED->BREED); register_auto on harvest_field is the correct timing/firing kind (MANDATORY, choiceless, no downside). The parenthetical 'including field cards with planted grain' refers to expansion field-card mechanics not modeled in this engine, so it adds nothing here — just count grain>0 FIELD cells.
- errata: None reported by card_text.py. Threshold is >=3 grain fields (grain>0), grant is a flat 2 food (not per-field).
- open_q: Confirm exact cost / printed VPs / prereq from agricola/cards/data/revised_*.json at implementation time (card_text.py showed text+timing but the spec writer should read the structured cost/vps fields directly). Card_text reported category 'Food Provider', vps unconfirmed in this triage output.

#### grain_sieve  (tier 1, minor, conf high) — D_65.json
- template: agricola/cards/wood_harvester.py (harvest_field register_auto, pure goods grant) + count-grain-fields eligibility from agricola/cards/scythe_worker.py
- plan: register_minor('grain_sieve', cost=Cost(Resources(wood=1))); on_play no-op. Helper _grain_count(state, idx) = number of FIELD cells with cell.grain > 0 (each yields exactly 1 grain in the mechanical take, which fires AFTER this hook). _eligible(state, idx) -> _grain_count(state, idx) >= 2. _apply(state, idx) grants +1 grain from supply: p = fast_replace(state.players[idx], resources=p.resources + Resources(grain=1)); splice back. register_auto('harvest_field', 'grain_sieve', _eligible, _apply); register_harvest_field_hook('grain_sieve').
- ordering: harvest_field hook fires BEFORE the mechanical crop take (_fire_harvest_field_hook runs first in _resolve_harvest_field), so the grid is still fully sown. 'Harvest at least 2 grain' therefore counts FIELD cells with grain>0 (each gives exactly 1 in the upcoming take), NOT total grain on fields (a single 3-grain field would harvest only 1 grain). Do NOT sum cell.grain; count grain-bearing fields. Threshold is >=2 fields, not >=2 grain-on-a-field.
- errata: none (no errata/clarifications returned by card_text.py)

#### trident  (tier 1, minor, conf high) — D_7.json
- template: agricola/cards/trellises.py (round-keyed on-play grant; also market_stall.py for the plain on-play +food shape)
- plan: register_minor('trident', cost=Cost(resources=Resources(wood=1)), prereq=lambda s,i: s.round_number in (3,6,9,12), on_play=_on_play). _on_play(state, idx): R=state.round_number; food = R//3 + 2  (3->3, 6->4, 9->5, 12->6); p=state.players[idx]; p=fast_replace(p, resources=p.resources+Resources(food=food)); return fast_replace(state, players=tuple(...)).  vps=0, not passing.
- ordering: The round restriction (only rounds 3/6/9/12) is a PREREQ (a HAVE/when-check on state.round_number gating legality), NOT a cost — mirror mole_plow.py/digging_spade.py which gate via prereq=lambda s,i: state.round_number>=N. Without the prereq the card would be playable any round (and the food formula R//3+2 would give wrong/garbage values for off-cycle rounds). The food amount is keyed to state.round_number at play time, read inside on_play exactly as trellises.py does — do not hardcode a single amount.
- errata: None reported. The '3/6/9/12 -> 3/4/5/6 food' slash list is the standard positional schedule (food = round/3 + 2).

#### reed_pond  (tier 1, minor, conf high) — D_78.json
- template: agricola/cards/pond_hut.py (near-exact: 'Place 1 X on each of the next 3 round spaces'); reed_belt.py / sack_cart.py are the absolute-rounds cousins.
- plan: register_minor("reed_pond", cost=Cost(), min_occupations=3, on_play=_on_play). _on_play(state, idx): R = state.round_number; return schedule_resources(state, idx, range(R + 1, R + 4), Resources(reed=1)). Cost is null (Cost() = free); vps null (omit); prereq '3 Occupations' = min_occupations=3 (NO max_occupations); not passing. Mechanism schedule_resources verified in agricola/cards/schedules.py (writes future_resources slots r-1, clamps to 1..14, collected at engine._complete_preparation).
- ordering: 'next 3 round spaces' is RELATIVE to the current round -> range(R+1, R+4) (rounds R+1, R+2, R+3), NOT absolute board rounds like reed_belt/sack_cart. And '3 Occupations' = min_occupations=3 with NO max (at-least-3), unlike Pond Hut's 'Exactly 2' which sets min==max==2. schedule_resources auto-clamps slots past round 14, so a late play correctly forfeits unreachable round spaces.
- errata: None. card_text.py shows no errata/clarifications. JSON: cost null, vps null, prerequisites '3 Occupations', passing_left null.

#### game_trade  (tier 1, minor, conf high) — D_9.json
- template: agricola/cards/young_animal_market.py (near-identical: on-play animal exchange, passing). Also market_stall.py for the passing-goods exchange shape.
- plan: register_minor('game_trade', cost=Cost(animals=Animals(sheep=2)), passing_left=True, on_play=_on_play). _on_play: p = state.players[idx]; p = fast_replace(p, animals=p.animals + Animals(boar=1, cattle=1)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))). No prereq, no vps. Cost (2 sheep) debited by _execute_play_minor via Cost.animals; gain is the immediate boar+cattle.
- ordering: This is the accepted on-play-animal-gain idiom (see young_animal_market), NOT a 'defer immediate animal grant' case: the engine does NOT force accommodation on a gain, so no can_accommodate/pareto_frontier handling is needed and none should be added. Two easy misses: (1) it is a TRAVELING card -- the JSON has passing_left='X' -- so passing_left=True is REQUIRED (the card_text.py CLI's 'players -' line is player-count, not passing; confirm via the JSON's passing_left field). (2) the cost is paid as Cost(animals=...), debited by _execute_play_minor, not inside _on_play -- only the +1 boar +1 cattle gain belongs in _on_play.
- errata: None. JSON: cost '2 Sheep', vps null, prerequisites null, passing_left 'X' (traveling), category Livestock Provider, deck D #9. Parenthetical in text ('effectively exchanging 2 sheep for 1 wild boar and 1 cattle') is flavor restating the cost+gain, no extra mechanic.

#### lord_of_the_manor  (tier 2, occupation, conf high) — D_100.json
- template: agricola/cards/stable_architect.py (pure scoring occupation; register_occupation no-op + register_scoring) — but the _score body must recompute per-category point values, NOT call scoring.score() (re-entrancy), so it is closer in spirit to scoring.py's own category logic.
- plan: register_occupation('lord_of_the_manor', lambda s,i: s)  # on-play no-op. register_scoring('lord_of_the_manor', _score). _score(state,idx): recompute the 8 capped-at-4 category point values from state WITHOUT calling scoring.score() (that would recurse through SCORING_TERMS): field_tiles count -> _score_field_tiles; len(pastures) -> _score_pastures; grain total (resources.grain + grain on FIELD cells) -> _score_grain; veg total -> _score_veg; sheep/boar/cattle -> _score_sheep/_score_boar/_score_cattle; fenced_stables (stables inside any pasture, capped 4) -> min(cnt,4). Return sum(1 for each of those 8 == 4). Mirror agricola/scoring.py exactly (reuse its _score_* private helpers via import; the raw counts are inline in score() so duplicate that counting). No cost/prereq/vps on the spec (occupation, played via Lessons).
- ordering: RE-ENTRANCY: _score must NOT call scoring.score(state,idx) — score() iterates SCORING_TERMS and would re-invoke this very term, infinite recursion. Recompute the eight category point-values inline (or via scoring._score_field_tiles etc.) from raw state instead. The eight eligible categories are precisely those whose scoring table maxes at exactly 4 points: field_tiles, pastures, grain, vegetables, sheep, boar, cattle, fenced_stables. Rooms (clay x1 / stone x2), people (x3), majors, unused, begging are NOT counted — their values are not capped at 4 and the rule is 'maximum 4 points'. The card text confirms fenced stables counts ('also awarded for 4 fenced stables'). Watch grain/veg: the count is supply + crops sitting on FIELD cells, not just resources.
- errata: No errata. Clarification (in-text): the bonus point is also awarded for 4 fenced stables — confirming fenced_stables is one of the eight max-4 categories.
- open_q: Tier could arguably be 1 (single register_scoring + register_occupation no-op like Stable Architect), but bumped to 2 because the _score body must faithfully mirror scoring.py's eight per-category count+lookup computations (a sync-with-scoring obligation) rather than a one-line derived count. Confirm the eight-category set: standard Agricola Lord of the Manor counts the 8 farm categories that cap at 4 (fields, pastures, grain, veg, sheep, boar, cattle, fenced stables) — high confidence given the parenthetical about fenced stables.

#### hammer_crusher  (tier 2, minor, conf medium) — D_14.json
- template: mining_hammer.py (renovate hook + goods grant) + cottager.py (optional before_renovate FireTrigger that pushes PendingBuildRooms(max_builds=1)); goods-grant mirrors hand_truck.py (before_<sub> register_auto).
- plan: register_minor('hammer_crusher', cost=Cost(resources=Resources(wood=1))).  Goods (MANDATORY): register_auto('before_renovate', CARD_ID, eligible=lambda s,i: s.players[i].house_material==HouseMaterial.CLAY, apply=+2 clay +1 reed via fast_replace).  Build Rooms (OPTIONAL): register('before_renovate', CARD_ID, eligible=lambda s,i,tr: CARD_ID not in tr and s.players[i].house_material==HouseMaterial.CLAY and _can_build_room(s, s.players[i]), apply=push PendingBuildRooms(player_idx=i, initiated_by_id='card:hammer_crusher', max_builds=1)).  Room cost paid normally via the cost-modifier chokepoint at the pushed frame. No prereq/vps/passing.
- ordering: Fire BEFORE the renovate commit (before-phase), so the 2 clay + 1 reed arrive in time to pay the stone renovate / room build this same action. The before-phase fires once per renovate regardless of which target the player will pick — gate eligibility on house_material==CLAY (the only material whose sole standard renovate target is STONE), NOT on the chosen to_material (unknown at before-fire time). Goods are a register_auto (mandatory 'you get'); Build Rooms is a separate optional FireTrigger ('you can') so declining does not forfeit the free goods. Both must independently gate on CLAY.
- errata: No errata/clarifications printed. Cost 1 Wood, 0 VP, not passing, no prereq. Dulcinaria Expansion, deck D #14, category Farm Planner.
- open_q: 'to stone' is a TARGET-conditional before_renovate fire, but the before-phase fires before to_material is chosen. For a CLAY house this is unambiguous (stone is the only target), so gating on house_material==CLAY is exact. BUT Conservator (implemented, in pool) lets a WOOD house renovate directly to STONE — there a wood-house owner has BOTH clay and stone as legal targets and the before-phase cannot know which they'll pick, so gating on CLAY would MISS the wood->stone-via-Conservator case (under-grant). No mechanism fires a before_renovate effect conditioned on the to_material. Confirm with user: ship the clean clay->stone path and accept the rare Conservator wood->stone under-grant as a documented limitation, OR defer until a target-conditional renovate hook exists?

#### wooden_whey_bucket  (tier 2, minor, conf high) — D_16.json
- template: mole_plow.py (optional before_action_space granted sub-action) + stable_planner.py for the PendingBuildStables push shape; cost-per-space mapping idiom from forest_lake_hut.py
- plan: register_minor('wooden_whey_bucket', cost=Cost(resources=Resources(wood=1, food=1))).  SPACES={'sheep_market','cattle_market'}; _stable_cost(sid)=Resources(wood=1) if sid=='sheep_market' else Resources() (slash-correspondence: Sheep->1 wood, Cattle->free).  _eligible(state,idx,triggers_resolved): CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id in SPACES AND _can_build_stable(state, state.players[idx], _stable_cost(sid)).  _apply: sid=pending_stack[-1].space_id; push(state, PendingBuildStables(player_idx=idx, initiated_by_id='card:wooden_whey_bucket', cost=_stable_cost(sid), max_builds=1)).  register('before_action_space', CARD_ID, _eligible, _apply)  (OPTIONAL/declinable, not register_auto -- 'you can build').  No register_action_space_hook: sheep_market/cattle_market are NON-ATOMIC (PendingSheepMarket/PendingCattleMarket host frames, in NONATOMIC_HANDLERS).  No prereq/passing; 0 VP.
- ordering: Two coupled subtleties: (1) The granted stable's cost is SPACE-DEPENDENT (1 wood at sheep_market, free at cattle_market) -- the slash in 'for 1 wood/at no cost' pairs with the slash in 'Sheep Market/Cattle Market' (verified against forest_lake_hut's crossed Fishing->wood/Forest->food mapping). _eligible MUST compute the cost from the SAME space_id it will apply with, or it will offer an unaffordable grant or block an affordable free one. (2) Timing is BEFORE the market action ('Each time BEFORE you use', and 'each time you use' = before_action_space anyway) -- so the stable is offered/built BEFORE the animals are taken; the player has not yet gained the market animals, which is correct (building a stable raises capacity ahead of acquiring animals, the card's whole point). Use register (declinable) not register_auto -- a stable consumes a farmyard cell and may be unwanted, so it must be optional; once-per-use via CARD_ID not in triggers_resolved.
- errata: None. Clarifications: none returned by card_text.py. Note the card_text.py output renders the paired-list text inline ('Sheep Market'/'Cattle Market' ... '1 wood/at no cost') -- the / is a per-space correspondence, NOT a player-count variant (this expansion's player-variant numbers appear as a/b/c triples elsewhere, e.g. Milking Parlor 1/3/4).
- open_q: Confirm the slash-correspondence reading (Sheep Market -> stable for 1 wood; Cattle Market -> stable free) vs. an alternative where both costs apply to both spaces. High confidence it is per-space correspondence (matches Forest Lake Hut's verified convention), but the asymmetric cost is unusual, so worth a one-line user confirm before implementing.

#### pulverizer_plow  (tier 2, minor, conf high) — D_19.json
- template: agricola/cards/ox_goad.py (near-exact: optional after_action_space trigger -> pay -> granted PendingPlow). Secondary: cooperative_plower.py (granted-plow eligibility shape), clay_puncher.py (atomic clay_pit needs register_action_space_hook).
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=1, vps=0). _eligible(s,i,triggers_resolved): CARD_ID not in triggers_resolved AND s.pending_stack[-1].space_id=='clay_pit' AND s.players[i].resources.clay>=1 AND _can_plow(p) (never a dead-end). _apply(s,i): debit Resources(clay=1) from player; add Resources(clay=1) to clay_pit's accumulated via get_space/with_space (board=with_space(s.board,'clay_pit', fast_replace(sp, accumulated=sp.accumulated+Resources(clay=1)))); rebuild state with new players+board; then push(state, PendingPlow(player_idx=i, initiated_by_id='card:pulverizer_plow')). register('after_action_space', CARD_ID, _eligible, _apply). register_action_space_hook(CARD_ID, {'clay_pit'}) -- clay_pit is ATOMIC so it must be explicitly hosted. NO food-payment machinery (cost is clay, a plain supply resource).
- ordering: Two ordering subtleties. (1) Timing: 'Immediately after each time you use' => after_action_space, NOT before (clay_puncher confirms the 'immediately after' exception to the default 'each time you use'=before rule); firing must occur once per clay_pit use, enforced by 'CARD_ID not in triggers_resolved' on the host frame. (2) The 1 clay is paid AND immediately placed BACK on the accumulation space -- net-zero to the clay_pit's clay (player -1, board +1). Must do BOTH the player debit and the with_space accumulated bump in _apply BEFORE pushing PendingPlow, and gate eligibility on clay>=1 AND _can_plow so the fired (mandatory-once-fired) plow is never a dead-end. Easy bug: forgetting the with_space side-effect (the clay must land on the space, not vanish) or forgetting that clay_pit is atomic and needs register_action_space_hook (unlike Ox Goad's non-atomic cattle_market).
- errata: None reported by card_text.py (no errata/clarification lines).

#### dwelling_plan  (tier 2, minor, conf high) — D_2.json
- template: agricola/cards/bread_paddle.py (on-play card that registers an after_play_<X> OPTIONAL trigger pushing a sub-action primitive); cottager.py for the PendingRenovate push + _can_renovate gate.
- plan: register_minor('dwelling_plan', cost=Cost(resources=Resources(food=1))) with NO on_play (default no-op) and NO prereq/vps/passing. register('after_play_minor', 'dwelling_plan', _eligible, _apply) as an OPTIONAL declinable trigger. _eligible(s,i,triggers_resolved): return ('dwelling_plan' not in triggers_resolved) and _can_renovate(s, s.players[i]) (from agricola.legality). _apply(s,i): return push(s, PendingRenovate(player_idx=i, initiated_by_id='card:dwelling_plan')). Renovate cost (1 material/room + 1 reed) resolves itself through effective_payments at the pushed frame's enumerator (nothing to compute here). No CardStore, schedule, or occupancy gate.
- ordering: OPTIONALITY is the trap. Card says 'You can immediately take a Renovation' -> declinable. Do NOT mirror shifting_cultivation by pushing PendingRenovate from on_play: PendingRenovate's before-phase enumerator (_enumerate_pending_renovate) offers CommitRenovate but NO Stop, so an unconditional push gives no decline path. Instead grant it as an OPTIONAL after_play_minor trigger: the host PendingPlayMinor's after-phase already offers FireTrigger('dwelling_plan') (=renovate) OR Stop (=decline). _execute_play_minor moves the card into minor_improvements and flips the host to after-phase BEFORE on_play, so dwelling_plan IS owned at the after-phase and its trigger is eligible. Gate eligibility on _can_renovate so the grant never dead-ends (no legal/affordable renovate target) and never fires twice (triggers_resolved guard).
- errata: None. No errata/clarifications returned by card_text.py.
- open_q: Confirm whether the renovate is intended to be declinable (treating 'You can' as optional per the standard ruling). If the user wants it mandatory-when-possible, switch to shifting_cultivation's shape: gate playability on a _can_renovate prereq and push PendingRenovate directly from on_play (no Stop needed).

#### writing_desk  (tier 2, minor, conf high) — D_28.json
- template: agricola/cards/forestry_studies.py (optional after_action_space FireTrigger that pushes PendingPlayOccupation with a non-standard cost); Scholar/scholar.py for the liquidation-aware _payable_occupation gate.
- plan: register_minor('writing_desk', cost=Cost(resources=Resources(wood=1)), min_occupations=2, vps=1)  # '2 Occupations'=PREREQ via min_occupations, NOT a cost; cost is 1 wood.
register('after_action_space', 'writing_desk', _eligible, _apply)  # Lessons is NON-ATOMIC (already hosted via PendingSubActionSpace) -> NO register_action_space_hook.
_eligible(s,i,triggers_resolved): CARD_ID not in triggers_resolved AND s.pending_stack[-1].space_id=='lessons' AND playable_occupations(s,i) AND _payable_occupation(s,i,p,Resources(food=2))  # never a dead-end fire; 2-food gate is liquidation-aware.
_apply(s,i): push PendingPlayOccupation(player_idx=i, initiated_by_id='card:writing_desk', cost=Resources(food=2))  # flat 2-food cost rides on the frame; _execute_play_occupation debits it (food-shortfall guard liquidates if short). No goods debit in _apply.
Decline path = host's Proceed/Stop (do not fire). 'Each time'=per-Lessons-use latch via triggers_resolved (NOT used_this_round). on_play: none.
- ordering: before vs after_action_space is the one real judgment call. The 'each time you use [space]' default ruling = before_action_space, BUT the granted occupation is ADDITIONAL (independent of the mandatory Lessons play), and the closest Lessons-grant template (Forestry Studies) rides after_action_space so the host's mandatory play_occupation resolves first, then the optional grant surfaces cleanly in the after-phase. Recommend after_action_space (cleaner; mandatory Lessons occupation done before the extra is offered; verified the delegating host's _enter_after_phase fires after_action_space optional FireTriggers). Either way uses triggers_resolved (per-use), never used_this_round.
- errata: None. Verbatim: 'Each time you use a "Lessons" action space, you can play 1 additional occupation for an occupation cost of 2 food.' cost 1 Wood, prereq 2 Occupations, 1 VP, not passing. Consul Dirigens, deck D #28, Actions Booster.
- open_q: Confirm before_ vs after_action_space for the grant (recommend after_, mirroring Forestry Studies). Note: the flat 2-food cost is independent of the Lessons occupation-cost ramp (this is an ADDITIONAL occupation, not the mandatory one), so no occupation_cost(len(...)) ramp applies here.

#### wood_rake  (tier 2, minor, conf high) — D_32.json
- template: loom.py (register_minor + register_auto('harvest_field') + register_harvest_field_hook + register_scoring) combined with big_country.py's CardStore-banking pattern
- plan: register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1))).  _eligible(state, idx): return state.round_number == 14 and (sum of cell.grain+cell.veg over all FIELD cells in players[idx].farmyard.grid) >= 7.  _apply(state, idx): bank 2 via p.card_state.set(CARD_ID, 2) (fast_replace player into state); grants no goods.  register_auto('harvest_field', CARD_ID, _eligible, _apply); register_harvest_field_hook(CARD_ID).  _score(state, idx): return players[idx].card_state.get(CARD_ID, 0).  register_scoring(CARD_ID, _score). No prereq, no printed vps (the 2 pts are conditional, so they MUST be banked, not given via the spec's vps=).
- ordering: The harvest_field hook fires BEFORE the mechanical crop take (engine _resolve_harvest_field calls _fire_harvest_field_hook first), so at round 14 the fields are still sown — this is exactly the card's 'before the final harvest' read; do NOT score off the terminal state (fields are empty by then). Two gates are load-bearing: (1) round_number == 14 only (the hook fires at EVERY harvest round 4/7/9/11/13/14; without the round gate an earlier harvest's >=7 goods would wrongly bank). (2) 'goods in your fields' = grain+veg summed across FIELD cells, NOT total grain/veg the player owns (uncollected stockpile in fields only). Banking (not a derived end-game read) is required because the qualifying field state no longer exists at scoring time — mirror big_country.
- errata: none reported by card_text.py (no errata/clarifications section printed)
- open_q: Minor wording ambiguity: 'at least 7 goods in your fields' — assumed grain+veg on FIELD cells just before the round-14 field crop take (after round 14 sowing, before harvesting). If the intended reading is the post-take count it would differ, but 'before the final harvest' clearly means pre-take, which the harvest_field hook timing matches.

#### milking_stool  (tier 2, minor, conf high) — D_38.json
- template: agricola/cards/loom.py (harvest_field auto-food on an animal threshold + register_scoring bonus); cattle analog of Butter Churn's cattle clause)
- plan: register_minor("milking_stool", cost=Cost(resources=Resources(wood=1)), min_occupations=2, vps=0)  # '2 Occupations' is a PREREQ (min_occupations), printed VPs=0.
_eligible(state, idx) -> True (0 cattle => 0 food, apply no-ops).
_apply: cattle = state.players[idx].animals.cattle; food = 3 if cattle>=5 else 2 if cattle>=3 else 1 if cattle>=1 else 0; if food: p=fast_replace(p, resources=p.resources+Resources(food=food)); splice player back.
_score(state, idx) -> state.players[idx].animals.cattle // 2  # 1 bonus point per 2 cattle.
register_auto("harvest_field", CARD_ID, _eligible, _apply); register_harvest_field_hook(CARD_ID); register_scoring(CARD_ID, _score).
- ordering: Two distinct cattle-count tables that are easy to conflate: the FOOD thresholds are 1/3/5 cattle -> 1/2/3 food (step at >=1, >=3, >=5), while SCORING is a separate cattle//2 (so 6 cattle = 3 food in harvest, 3 VP at scoring). Do NOT reuse one number for both. harvest_field auto fires in the FIELD phase BEFORE the mechanical crop take (per _resolve_harvest_field), and is MANDATORY/choiceless (register_auto, no FireTrigger / decline path). Income is per-harvest (rounds 4,7,9,11,13,14), evaluated against current cattle each time.
- errata: None reported by card_text.py (no errata/clarifications section). Note printed VPs = 0 (card has no printed point; all VP comes from the cattle//2 scoring term) — unlike Loom/Butter Churn which print 1.

#### truffle_slicer  (tier 2, minor, conf high) — D_39.json
- template: wood_cutter.py (forest before_action_space host via register_action_space_hook) + loppers.py (OPTIONAL pay-goods-for-a-BANKED-bonus-point: register FireTrigger + CardStore counter + register_scoring)
- plan: register_minor('truffle_slicer', cost=Cost(resources=Resources(wood=1)), prereq=lambda s,i: s.round_number >= 8, vps=0).  WOOD_SPACES=frozenset({'forest'}) (the only 2p wood accumulation space). register_action_space_hook('truffle_slicer', WOOD_SPACES) to host the atomic forest.  register('before_action_space','truffle_slicer',_eligible,_apply)  (optional, mandatory=False default).  _eligible(s,i,triggers_resolved): 'truffle_slicer' not in triggers_resolved AND s.pending_stack[-1].space_id in WOOD_SPACES AND p.animals.boar>=1 AND p.resources.food>=1 (never a dead-end).  _apply(s,i): p = fast_replace(p, resources=p.resources - Resources(food=1), card_state=p.card_state.set('truffle_slicer', p.card_state.get('truffle_slicer',0)+1)); rebuild players tuple.  register_scoring('truffle_slicer', lambda s,i: s.players[i].card_state.get('truffle_slicer',0)) emits 1 VP per use banked.
- ordering: 'Each time you use a wood accumulation space' = before_action_space (Wood Cutter ruling: a bare 'each time you use [space]' fires BEFORE the space's own +3 wood pickup, NOT after — order is immaterial to the food/VP effect but the phase is fixed by the ruling). Optionality lives in the FireTrigger (decline = the host's Stop, no SkipTrigger flag). Once-per-use is enforced by `_apply_fire_trigger` stamping `triggers_resolved | {card_id}` before apply, which `_eligible` reads — so it fires at most once per forest use but can fire on every forest use across the game (hence the cumulative CardStore bank). VP is BANKED at fire time and scored later (vps=0 on the spec, register_scoring reads the count), exactly like Loppers/Big Country.
- errata: None in card data. Cost 1 Wood; prereq 'Play in Round 8 or Later'; category Points Provider; passing=false; vps printed as a bonus-point engine (0 base VP).
- open_q: Food-payment liquidation: the 1-food cost is gated on on-hand `food >= 1` (Loppers-style direct pay), NOT routed through the PendingFoodPayment liquidation path (Ox Goad-style _liquidatable_to). This is a minor rules simplification: a player with 0 food but spare grain/veg/animals technically could liquidate 1 food to claim the point, but won't be offered it. Recommend keeping direct-pay for Tier-2 simplicity (only 1 food, late-game, marginal); flag if the user wants exact liquidation parity (would bump toward the food-payment-frame machinery).

#### cesspit  (tier 2, minor, conf high) — D_40.json
- template: agricola/cards/acorns_basket.py (deferred-goods Category-8 animal variant; near-exact). Combine with the resource sibling schedule_resources for the clay half.
- plan: register_minor('cesspit', cost=Cost() [card JSON cost=null], min_occupations=1, prereq=_two_fields, vps=-1, on_play=_on_play). _two_fields(state,idx): count grid cells with cell_type is CellType.FIELD over the 3x5 grid, return >=2 (NO crop requirement, unlike ash_trees). _on_play(state,idx): R=state.round_number; remaining=range(R+1,15); clay_rounds=[r for i,r in enumerate(remaining) if i%2==0]; boar_rounds=[r for i,r in enumerate(remaining) if i%2==1]; state=schedule_resources(state,idx,clay_rounds,Resources(clay=1)); state=schedule_animals(state,idx,boar_rounds,Animals(boar=1)); return state. schedule_animals already collects+auto-accommodates the boar decision-free at start-of-round (engine._collect_future_rewards), so no immediate-animal-grant problem; schedule_resources clamps rounds outside 1..14.
- ordering: Alternation is over the SEQUENCE of remaining round spaces starting at R+1 (clay = 1st/3rd/5th remaining, boar = 2nd/4th/6th), NOT over even/odd round NUMBERS. Key on enumerate-index of range(R+1,15), i.e. (rnd-(R+1))%2, never rnd%2 (R's parity varies). 'starting with clay' fixes the first remaining space (R+1) to clay. 'At the start of these rounds you get the respective good' = the standard schedule collection (resources via future_resources, boar via future_rewards + auto-accommodate) at _complete_preparation — no separate hook needed.
- errata: None. Card JSON: cost=null (no resource cost), vps=-1 (penalty, supported — cf. brewery_pond/mantlepiece), prereq '2 Fields and 1 Occupation', passing_left=null. status=todo.
- open_q: Confirm 'remaining round spaces' excludes the CURRENT round R (i.e. first scheduled space is R+1, matching Acorns Basket's maintainer-confirmed R+1/R+2 convention). If the maintainer intends the current round's space to also be loaded, shift to range(R,15) — but R's space action is already in progress, so R+1 is the expected reading.

#### horse_drawn_boat  (tier 2, minor, conf high) — D_41.json
- template: agricola/cards/acorns_basket.py (schedule_animals) + agricola/cards/thick_forest.py / sack_cart.py (schedule_resources, 'remaining round space' = rounds > R)
- plan: register_minor('horse_drawn_boat', cost=Cost(resources=Resources(wood=2)), min_occupations=3, on_play=_on_play). In _on_play: R=state.round_number; remaining=[r for r in range(R+1,15)]; food_rounds = remaining[0::2] (R+1,R+3,...  the odd offsets, 'starting with food'); sheep_rounds = remaining[1::2] (R+2,R+4,...). state=schedule_resources(state, idx, food_rounds, Resources(food=1)); state=schedule_animals(state, idx, sheep_rounds, Animals(sheep=1)); return state. Food rides future_resources; sheep ride future_rewards and are auto-accommodated decision-free at each scheduled round start by engine._collect_future_rewards (same pareto_frontier/can_accommodate the markets use), so the no-accommodation DEFER rule does NOT apply. No VPs, not passing.
- ordering: Alternation phase must key to POSITION in the remaining-rounds sequence, NOT absolute round parity. 'Starting with food' means the first REMAINING round space (R+1) is food; use remaining[0::2]=food / remaining[1::2]=sheep. Tying food/sheep to (round % 2) instead of offset-from-R mis-assigns every good and even flips the leading good depending on whether the card is played on an odd or even round.
- errata: None. card_text.py reports no errata/clarifications. 'remaining round space' semantics (rounds strictly after current R) are settled by Sack Cart / Thick Forest; 'round spaces start at R+1' is settled by Acorns Basket (confirmed with maintainer 2026-06-30).
- open_q: Confirm 'starting with food' is anchored to the first REMAINING space (R+1) regardless of which round the card is played — i.e. the alternation does not track the board's fixed printed alternation. Reading favors anchor-to-first-remaining (the standard interpretation), so implementing that; flag for a one-line maintainer confirm.

#### education_bonus  (tier 2, minor, conf medium) — D_42.json
- template: bread_paddle.py (after_play_occupation hook) + assistant_tiller.py (optional trigger pushing PendingPlow for the 'field' grant)
- plan: ["register_minor('education_bonus', cost=Cost(resources=Resources(food=1)), prereq=lambda s,i: len(state.players[i].minor_improvements)+len(state.players[i].occupations) >= 2)  # prereq '2 Improvements' (verify exact prereq idiom vs prereq_met; '2 Improvements' = 2 played minors/majors \u2014 confirm against an existing N-improvements prereq card before finalizing).", "register_auto('after_play_occupation', 'education_bonus', eligible=lambda s,i: 1 <= len(s.players[i].occupations) <= 5, apply=_grant) where _grant dispatches on n=len(p.occupations): n=1->grain, 2->clay, 3->reed, 4->stone, 5->veg via fast_replace(p, resources=p.resources+Resources(...)). Occupation is ALREADY in p.occupations at after-phase (resolution.py:516), so len is the 1-based count directly.", "register('after_play_occupation', 'education_bonus', eligible=lambda s,i,tr: 'education_bonus' not in tr and len(s.players[i].occupations)==6 and _can_plow(s.players[i]), apply=lambda s,i: push(s, PendingPlow(player_idx=i, initiated_by_id='card:education_bonus')))  # the 6th grant '1 field' = a free, declinable PendingPlow (granted sub-action is optional).", "vps=0 (printed null). on_play=no-op (grants are all hook-driven; 'not retroactively' => earlier occupations grant nothing)."]
- ordering: The good granted is keyed to the GAME-TOTAL occupation count (len(p.occupations)), NOT to occupations played since this card was acquired. 'not retroactively' is satisfied automatically because the hook only fires on the ACT of playing an occupation while owned (earlier ones never re-fire) — but the count still uses the lifetime total, so playing this card after 2 occupations then playing your 3rd grants reed (the 3rd reward), not grain. Do NOT count from card-acquisition. Also: the occupation is added to p.occupations BEFORE the after_play_occupation hook fires (resolution.py:513-518), so len() is already the correct 1-based index — do not +1.
- errata: None. Card text is self-contained; data JSON carries no extra clarification.
- open_q: Two minor items to confirm before/while implementing, neither blocking: (1) the exact prereq idiom for '2 Improvements' (count of played minors+majors; confirm against an existing N-improvements-prereq card e.g. via prereq= and how improvements are counted — majors live on board.major_improvement_owners, not PlayerState). (2) Whether granting '1 field' as a free PendingPlow is the intended semantics (matches Assistant Tiller/Cooperative Plower convention; a granted field tile = a plow). If the user prefers field-grant != plow (e.g. pre-plowed/no-cost-distinction), flag — but PendingPlow is the established mechanism and is the right default.

#### sheep_well  (tier 2, minor, conf high) — D_45.json
- template: agricola/cards/trellises.py (near-exact clone; only the cap source differs)
- plan: register_minor("sheep_well", cost=Cost(resources=Resources(stone=2)), vps=2, on_play=_on_play). _on_play(state, idx): R = state.round_number; n = state.players[idx].animals.sheep; return schedule_resources(state, idx, range(R+1, R+1+n), Resources(food=1)). No prereq, not passing. schedule_resources clamps slots to 1..14, so the 'up to ... next round spaces' remaining-rounds cap is free; food is auto-collected at each scheduled round start by engine._complete_preparation (future_resources path).
- ordering: The cap N = sheep count is evaluated ONCE at play time (on_play), not re-checked per round, and is a fixed number of consecutive next-round spaces (R+1..R+N) NOT one-food-per-future-round-while-you-own-sheep. Use animals.sheep (live count), not a stored snapshot; schedule_resources reads state fresh and clamps >14, so no separate min against rounds remaining. N==0 (no sheep) schedules nothing (legal +0).

#### churchyard  (tier 2, minor, conf high) — D_47.json
- template: agricola/cards/thick_forest.py (deferred-goods via schedule_resources) + agricola/cards/food_basket.py (have-check prereq counting occupations + minor_improvements + owned majors)
- plan: from agricola.cards.schedules import schedule_resources; from agricola.cards.specs import register_minor; from agricola.resources import Cost, Resources. CARD_ID='churchyard'. _on_play(state, idx): R = state.round_number; remaining = range(R + 1, 15); return schedule_resources(state, idx, remaining, Resources(food=2))  # 'place 2 food on each remaining round space', collected at start of each scheduled round by engine._complete_preparation. _prereq(state, idx): p = state.players[idx]; n = len(p.occupations) + len(p.minor_improvements) + sum(1 for o in state.board.major_improvement_owners if o == idx); return n >= 10  # '10 Cards (Occupations and Improvements) in front of you'. register_minor(CARD_ID, cost=Cost(resources=Resources(stone=1, reed=1)), prereq=_prereq, vps=1, on_play=_on_play).
- ordering: 'remaining round space' = rounds STRICTLY AFTER the current round (range(R+1, 15)) — the current round's space was already collected at this round's start, so it must NOT be re-scheduled. This mirrors thick_forest's range(R+1, 15). The prereq is a HAVE-check evaluated at legality time BEFORE the card is added to minor_improvements, so it never counts itself (count must reach 10 from the other 10+ cards already in front; the played card is the 11th). schedule_resources is additive and clamps slots outside 1..14, so no late-game out-of-range guard is needed.
- errata: Clarification on card: 'Cards must be Occupations and Improvements' — i.e. the 10-card prereq counts only occupations + improvements (minors + owned majors), which is the universe of cards 'in front of you' anyway. No errata altering the effect. Note the cost field '1 Stone, 1 Reed' is a genuine spendable debit (NOT a 'in supply' prereq like thick_forest's clay), so it goes in Cost(), not prereq.
- open_q: Confirm whether owned MAJOR improvements count toward the '10 Cards' prereq. Card text says 'Occupations and Improvements'; the clarification reads 'Occupations and Improvements'. Standard Agricola treats Major improvements as Improvements, so I include owned majors (food_basket precedent counts majors as improvements). If the user intends minors-only, drop the major_improvement_owners term.

#### bookshelf  (tier 2, minor, conf high) — D_49.json
- template: agricola/cards/paper_maker.py (before_play_occupation trigger + occupation-food-source registration); near-identical shape, but Bookshelf is mandatory/auto and unconditional.
- plan: register_minor('bookshelf', cost=Cost(resources=Resources(wood=1)), min_occupations=3, vps=1)  # no on_play effect (the effect is the trigger). register_auto('before_play_occupation', 'bookshelf', _eligible, _apply): _eligible(s,i)->bool returns True always (pure-goods, no cost); _apply(s,i) adds Resources(food=3) to player i via fast_replace. ALSO register_occupation_food_source('bookshelf', lambda s,i: (3, Resources())) so the Lessons/Scholar affordability gate (_payable_occupation) offers an occupation whose food cost is only payable via Bookshelf's 3 food. Imports: register_minor + register_occupation_food_source from cards.specs; register_auto from cards.triggers; Cost/Resources from resources; fast_replace from replace.
- ordering: TIMING/FOOD-SOURCE is the subtle point. (1) 'even before paying the occupation cost' = the food must land BEFORE the cost debit. before_play_occupation autos fire at frame-push time (_fire_subaction_before_auto when ChooseSubAction('play_occupation') pushes PendingPlayOccupation), and the cost debit happens later in _execute_play_occupation — so an auto correctly lands the 3 food pre-payment. (2) Use register_auto NOT register: 'you get 3 food' is mandatory pure-goods with no downside, not declinable. (3) The food-source registration is the EXTRA mechanism that makes this tier 2: the outer Lessons/Scholar gate (_payable_occupation) only runs _payable directly, which does NOT see the not-yet-applied auto food; without registering bookshelf as an OCCUPATION_FOOD_SOURCE, an occupation affordable only via Bookshelf's food would be wrongly un-offered. No double-count risk: the source is consulted at the gate (offer decision), the auto applies food at frame-push (later, distinct evaluation point). Unlike Paper Maker, NO commit-gate withholding is needed since the food is applied automatically before the commit is reachable.
- errata: None. card_text.py reports no errata/clarifications. Verbatim: 'Immediately before each time you play an occupation (even before paying the occupation cost), you get 3 food.' Consul Dirigens Expansion, deck D #49, Food Provider, cost 1 Wood, prereq 3 Occupations, 1 VP.
- open_q: Confirm the OCCUPATION_FOOD_SOURCE registration is wanted for a MANDATORY (auto) food grant. Paper Maker registers it because it is an OPTIONAL trigger that must be fired before the commit; Bookshelf's food lands automatically, so the source is only needed for the outer offer-gate edge case (occupation affordable solely via Bookshelf's 3 food). It is harmless and correct to register it, but if the implementer prefers, they could verify whether _payable_occupation already accounts for pending auto effects (it does NOT today, so the registration is needed).

#### gritter  (tier 2, minor, conf high) — D_58.json
- template: garden_hoe.py (before/after veg-field CardStore snapshot to detect a veg-planting sow) + tumbrel.py (per-sow food payout via register_auto on after_sow). Hybrid of the two.
- plan: register_minor('gritter', cost=Cost(resources=Resources(wood=1)), prereq=lambda state, idx: state.round_number >= 5).  Reuse garden_hoe's _veg_field_count (FIELD cells with veg>0).  register_auto('before_sow','gritter', lambda s,i: True, _snapshot_before)  -> store _veg_field_count into card_state['gritter'].  register_auto('after_sow','gritter', lambda s,i: True, _grant_after): planted_veg = (_veg_field_count(p) - before) >= 1; if planted_veg grant Resources(food=_veg_field_count(p)) (CURRENT count, incl. new fields), else +0; always reset card_state['gritter']=0.  No vps, no passing, no on_play.
- ordering: Gate on the before/after DELTA (>=1 new veg field this sow) but PAY the CURRENT post-sow veg-field count (text: 'including the new ones'). Unlike tumbrel, must NOT pay on a grain-only sow, so the snapshot gate is mandatory, not optional. after_sow fires post-fill so _veg_field_count already reflects the new vegetables. Always reset the CardStore snapshot to canonical 0 in the after-hook for transposition-table safety.
- errata: None. Text verbatim: 'At the end of each action in which you sow vegetables in a field, you get 1 food for each vegetable field you have (including the new ones).' cost 1 Wood; prereq 'Play in Round 5 or Later' (= round_number >= 5); no vps; not passing.
- open_q: Confirm whether a sow that overwrites/expands veg into an additional NEW field but where total veg-field count is reachable both ways is fine — it is: grain XOR veg per cell (garden_hoe note), so veg-field count delta cleanly isolates this sow's veg planting; no edge case. The 'including the new ones' phrasing is fully covered by reading the current count in after_sow.

#### petrified_wood  (tier 2, minor, conf high) — D_6.json
- template: agricola/cards/seasonal_worker.py (PendingCardChoice + register_card_choice_resolver) for the choice frame; agricola/cards/childless.py for the same on a minor; consultant.py / specs.register_minor for the registration shape.
- plan: register_minor('petrified_wood', cost=Cost(), min_occupations=2, vps=0, on_play=_on_play). _on_play(state, idx): n_max = min(3, state.players[idx].resources.wood); options = tuple(range(0, n_max+1)); push(state, PendingCardChoice(player_idx=idx, initiated_by_id='card:petrified_wood', options=options)). register_card_choice_resolver('petrified_wood', _resolve) where _resolve(state, idx, n): p.resources += Resources(wood=-n, stone=+n); update player; return pop(state). No event hooks, no scoring, not passing. 'each' = 1:1 rate (1 wood -> 1 stone, capped at 3 wood).
- ordering: The amount choice is OPTIONAL (0 is valid -- 'up to 3', the player may decline entirely), but PendingCardChoice has NO Stop/decline path. So 0 MUST be an explicit option in the options tuple (options = (0,1,2,3) capped by wood, NOT (1,2,3)). Cap options at min(3, current wood) so no illegal over-spend is ever offered; if wood==0 the only option is (0,) which singleton-skips to a no-op. Confirmed: a minor on_play that PUSHes a frame is supported (resolution.py L575-584 runs on_play AFTER the after-phase pivot; _fire_subaction_before_auto is a safe no-op on a card_choice frame since 'card_choice' is not in SUBACTION_PENDING_IDS).
- errata: None in card_text output (no errata/clarifications printed). 'for 1 stone each' = strict 1:1 wood->stone.

#### beer_tap  (tier 2, minor, conf high) — D_62.json
- template: agricola/cards/beer_keg.py (multi-variant HarvestConversionSpec, once-per-harvest cross-variant guard) + agricola/cards/market_stall.py (_on_play goods grant)
- plan: register_minor('beer_tap', cost=Cost(resources=Resources(wood=1)), vps=0, on_play=_on_play) where _on_play adds Resources(food=2) to the owner (market_stall pattern). Define _VARIANTS=((2,3),(3,6),(4,9)) = (grain_in, food_out); for each, register_harvest_conversion(HarvestConversionSpec(conversion_id=f'beer_tap_{grain}', input_cost=Resources(grain=grain), food_out=food, is_owned_fn=_make_is_owned(), side_effect_fn=None)). _make_is_owned gates on: 'beer_tap' in p.minor_improvements AND not any(cid.startswith('beer_tap') for cid in p.harvest_conversions_used) — the cross-variant once-per-harvest guard, copied verbatim from beer_keg. No prereq, no passing, no scoring term, no CardStore (pure food, simpler than Beer Keg).
- ordering: The conversion is a single CHOICE once per harvest, NOT three independent fires — must use the cross-variant guard (suppress all beer_tap_* once ANY has fired this harvest) exactly as beer_keg does; gating only on the per-id harvest_conversions_used membership would wrongly let the player fire all three (2+3+4 grain -> 18 food) in one harvest. harvest_conversions_used resets at the start of each harvest's FEED phase, so each harvest gets a fresh single use.
- errata: None reported by card_text.py (no errata/clarifications shown).
- open_q: Confirm the tiered conversion is read as a single once-per-harvest choice among 2/3/4 grain (matching the official 'each harvest, turn 2/3/4 grain into 3/6/9' wording and Beer Keg's established interpretation), not a per-tier repeatable use. The implementation assumes single-choice. Also note the 1:1.5 grain->food density (3 food / 2 grain) is the card's Food-Provider value; no point-banking unlike Beer Keg.

#### lynchet  (tier 2, minor, conf high) — D_63.json
- template: agricola/cards/three_field_rotation.py (harvest_field auto income) + inline orthogonal-adjacency scan from agricola/cards/pottery_yard.py
- plan: register_minor('lynchet')  # cost null/free, no vps, no prereq, no passing.
register_auto('harvest_field', 'lynchet', _eligible, _apply); register_harvest_field_hook('lynchet').
_eligible(s,i): True iff any sown FIELD cell (grain>0 or veg>0) has an orthogonally adjacent ROOM cell (else no-op).
_apply(s,i): grid=s.players[i].farmyard.grid (3x5); count = number of cells where cell_type==FIELD and (grain>0 or veg>0) and some neighbor (|dr|+|dc|==1, in-bounds) has cell_type==CellType.ROOM; add Resources(food=count) to p.resources via fast_replace; rebuild players tuple (mirror three_field_rotation._apply).
- ordering: 'harvested field tile' = a field that actually yields this harvest = a SOWN field (grain>0 or veg>0); empty/unsown fields do NOT count. The harvest_field hook fires BEFORE the mechanical crop take in _resolve_harvest_field, so _apply reads the still-sown grid — read grain/veg BEFORE the take (correct here; do NOT count an empty FIELD). 'house' = ROOM cells; adjacency is plain grid orthogonality (|dr|+|dc|==1, bounds 3x5), NOT pasture/fence geometry, so no new geometry helper is needed.
- errata: None. card_text.py reports no errata/clarifications; JSON record has cost=null, vps=null, prerequisites=null, passing_left=null.
- open_q: Confirm the 'harvested = sown' reading (a field tile counts only if it holds grain or veg this harvest, not every field tile adjacent to the house). This is the standard Agricola interpretation of 'harvested field tile' and matches the hook firing before the take, but it is the one interpretive call. If the user instead intends 'every field tile adjacent to the house regardless of sown state', drop the grain/veg>0 condition (still Tier 1-2).

#### potter_ceramics  (tier 2, minor, conf high) — D_66.json
- template: agricola/cards/potter_ceramics.py (already exists) + agricola/cards/hand_truck.py (sibling before_bake_bread trigger). For the missing register_minor wiring, copy the no-effect minor registration shape from any simple minor (e.g. market_stall.py) but with on_play=noop.
- plan: The behavioral trigger ALREADY EXISTS and is verified working in agricola/cards/potter_ceramics.py: register(event='before_bake_bread', card_id='potter_ceramics', eligibility_fn=_eligible, apply_fn=_apply) — declinable FireTrigger, eligible when card owned AND clay>=1 AND not in triggers_resolved; apply = -1 clay +1 grain; plus register_bake_bread_extension(_can_bake_bread_extension) so a Potter+baker owner can bake with 0 grain (the swap supplies it). The ONLY gap is that the card is not registered as a PLAYABLE minor, so it cannot be dealt/played. Add register_minor(CARD_ID, cost=Cost(), prereq=None, passing_left=False, vps=0, on_play=_noop) — JSON has cost=null, vps=null, prereq=null, passing_left=null, so all defaults (free, no prereq, not passing, 0 VP). No CardStore/schedule needed.
- ordering: The clarification 'You must bake if you make this exchange' is satisfied STRUCTURALLY, not by a separate guard: the swap fires on the before_bake_bread event INSIDE a PendingBakeBread (which the host only pushes when a Bake Bread action is being taken), so the grain produced by the swap is committed in that same bake — you cannot exchange and then walk away. The eligibility 'each time' = before EACH bake action, scoped by the per-frame triggers_resolved set (a fresh PendingBakeBread => empty set => Potter re-eligible), which is exactly how it is coded. Do NOT convert this to an after_bake_bread or a register_auto (mandatory) trigger — it is an OPTIONAL 'you can' exchange, so it must stay a declinable register() FireTrigger.
- errata: Clarification: 'You must bake if you make this exchange.' (no errata). JSON cost/vps/prerequisites/passing_left are all null.
- open_q: Confirm Tier: the trigger is done, but completing it to playable still touches the play-card machinery (register_minor wiring + the existing bake_bread legality extension), so it is graded Tier 2 rather than Tier 1. CLAUDE.md still says Potter Ceramics is 'not part of any game until the trigger/hook system lands' — but the host before/after lifecycle and before_bake_bread firing are now implemented (see hand_truck.py using the same event), so the card can be made live now.

#### reap_hook  (tier 2, minor, conf high) — D_67.json
- template: agricola/cards/sack_cart.py (schedule_resources onto round-space slots; the deferred-goods Category-8 pattern, identical to Strawberry Patch/Club House but grain on specific round spaces)
- plan: register_minor("reap_hook", cost=Cost(resources=Resources(wood=1)), on_play=_on_play). _on_play(state, idx): R = state.round_number; rounds = [rnd for rnd in (4,7,9,11,13,14) if rnd > R][:3]; return schedule_resources(state, idx, rounds, Resources(grain=1)). No prereq, no vps, not passing. schedule_resources (agricola/cards/schedules.py) writes 1-indexed round N to future_resources slot N-1 additively; engine._complete_preparation pays it out at the start of each scheduled round (verified). schedule_resources also silently clamps out-of-range slots, so the [:3] slice + > R filter fully define semantics.
- ordering: Two coupled subtleties: (1) 'next 3 OF the spaces 4,7,9,11,13,14' means the next 3 of THAT specific list strictly after the current round, NOT the literal next 3 rounds (R+1,R+2,R+3) and NOT all remaining of the list (that is Sack Cart's 'remaining'). Filter the list to rnd > R, then slice [:3]. (2) Use STRICTLY greater than R (rnd > R, mirroring Sack Cart), not >=: a round whose space has already been collected (current round entered) must not be scheduled, or schedule_resources would write a slot that is never paid out (or, if R's payout hasn't fired yet, double-pay). The > R + [:3] combination is the whole correctness story.
- errata: None. JSON status=todo; no errata or clarifications field. cost '1 Wood', vps null, prerequisites null, passing_left null.
- open_q: Confirm the canonical reading is 'the next 3 entries of the list {4,7,9,11,13,14} after the current round' (so on/before round 4 it schedules rounds 4,7,9 -> wait, on round <4 it is 4,7,9; played after round 9 it is 11,13,14; after round 13 only 14 is left). This is the standard Agricola wording for these round-space cards and matches Sack Cart's family, so confidence is high; no design call needed.

#### small_basket  (tier 2, minor, conf high) — D_68.json
- template: agricola/cards/basket.py (optional bounded-hook conversion on an atomic accumulation space, hosted via register_action_space_hook). brewery_pond.py confirms the bare-"each time you use" -> before_action_space timing ruling for reed_bank.
- plan: register_minor('small_basket', min_occupations=2)  # prereq 2 Occupations (have-check, NOT cost); no printed cost (Cost() default); no VPs.
SPACES=frozenset({'reed_bank'}); _eligible(state,idx,triggers_resolved): CARD_ID not in triggers_resolved AND state.pending_stack[-1].space_id in SPACES AND state.players[idx].resources.reed>=1.
_apply(state,idx): p=fast_replace(player, resources=player.resources+Resources(reed=-1,veg=1)); splice player back. NO with_space reed-return (the 'place reed on space' clause is 4+-player-only; inert in 2p).
register('before_action_space','small_basket',_eligible,_apply)  # OPTIONAL/declinable FireTrigger (default mandatory=False).
register_action_space_hook('small_basket',{'reed_bank'})  # reed_bank is ATOMIC, must be hosted.
- ordering: Timing: this is before_action_space, NOT after. Card text is a bare 'Each time you use the Reed Bank' with no 'immediately after', so per the ruling (confirmed by brewery_pond.py vs basket.py) it fires BEFORE the space's reed pickup. The optional/declinable nature (register with mandatory=False, eligibility owns reed>=1) is the other must-get; do NOT use register_auto (that's mandatory, choiceless) — Basket itself uses optional register(). The 4+-player reed-return clause is omitted entirely (no with_space step), unlike basket.py which DOES return the wood in 2p; here the return is player-count-gated to 4+ so it never fires in the 2p game.
- errata: None reported by scripts/card_text.py (no errata/clarifications section returned). The '4+ players' branch is a no-op in the 2-player engine.

#### small_greenhouse  (tier 2, minor, conf high) — D_69.json
- template: agricola/cards/plow_driver.py (paid optional start-of-round grant via register + register_food_payment_resume) fused with agricola/cards/chain_float.py (schedule_effect onto future round spaces + per-slot scoping so hosting/firing is per-scheduled-round, NOT register_start_of_round_hook). Contrast sibling agricola/cards/large_greenhouse.py which uses schedule_resources because its pickup is FREE.
- plan: ["CARD_ID='small_greenhouse'; _FOOD_COST=1. register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=1, on_play=_on_play). (prereq '1 Occupation' = min_occupations=1; vps=1; NOT passing.)", "_on_play(state, idx): R=state.round_number; return schedule_effect(state, idx, (R+4, R+7), CARD_ID).  # effect-hook tuple (paid/optional pickup), NOT schedule_resources.", "_scheduled_slot(p, rn): Chain-Float helper -> slot index if CARD_ID in p.future_rewards[rn-1].effect_card_ids else None.", "_eligible(state, idx, triggers_resolved): return _scheduled_slot(p, state.round_number) is not None and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST)).  # no _used_this_round latch; the slot IS the per-round gate.", "_buy_veg(state, idx): debit 1 food (p.resources - Resources(food=1)), grant +1 veg, AND consume this round's slot (effect_card_ids - {CARD_ID}); single body reached directly and as the food-payment resume.", "_apply(state, idx): if food>=1 return _buy_veg directly; else push PendingFoodPayment(player_idx=idx, food_needed=1, resume_kind=CARD_ID, reserved=Cost()).  register('start_of_round', CARD_ID, _eligible, _apply); register_food_payment_resume(CARD_ID, _buy_veg).  Do NOT register_start_of_round_hook (schedule drives hosting via has_scheduled_round_start_effect, like Chain Float)."]
- ordering: Slot consumption + veg grant + food debit MUST all live in the single _buy_veg body that is reached BOTH directly (food on hand) AND via the food-payment resume (raise-only frame leaves raised food in supply for this body to debit). If slot-consume were done in _apply instead, the resume path would grant veg without consuming the slot (re-offer next visit) or double-debit. Mirror Chain Float's per-slot consume inside the post-payment body, not at _apply. Also: the optional FireTrigger's decline is the PendingPreparation host's Proceed (no SkipTrigger) — buying is 'you can', so it must be declinable.
- errata: None reported by card_text.py (no errata/clarifications section). Verbatim: 'Add 4 and 7 to the current round and place 1 vegetable on each corresponding round space. At the start of these rounds, you can buy the vegetable for 1 food.' cost 2 Wood; prereq 1 Occupation; vps 1; Consul Dirigens, deck D #69; category Crop Provider; not passing.
- open_q: 'Add 4 and 7 to the current round' is read as offsets R+4 and R+7 (current-round-relative, exactly parallel to Large Greenhouse 'Add 4,7,9' = R+4/R+7/R+9 and Chain Float 'Add 7,8,9' = R+7/R+8/R+9), NOT fixed rounds 4 and 7. High-confidence given the implemented sibling Large Greenhouse uses the same wording with the same offset reading; flag only because the implementation pass should reuse that exact convention. schedule_effect silently drops any offset > 14 (late play = legal but wasted), matching 'place on each corresponding round space'.

#### stable_manure  (tier 2, minor, conf high) — D_72.json
- template: agricola/cards/scythe_worker.py (harvest_field auto that takes 1 extra crop FROM fields; depletes field by 2 total). Borrow count_unfenced_stables() from agricola/cards/stable_architect.py for the cap.
- plan: register_minor('stable_manure', max_occupations=1)  # free, no vps, not passing; prereq 'At Most 1 Occupation' = max_occupations=1. register_auto('harvest_field', 'stable_manure', _eligible, _apply); register_harvest_field_hook('stable_manure'). N = count_unfenced_stables(p.farmyard). _eligible: N>0 AND some FIELD cell with grain>=2 or veg>=2. _apply: import count_unfenced_stables; iterate FIELD cells, for the first min(N, eligible) cells with grain>=2 take 1 grain (cell.grain-1, +Resources(grain=1)) and with veg>=2 take 1 veg (cell.veg-1, +Resources(veg=1)); stop after N taken; rebuild grid via fast_replace(p.farmyard, grid=...) (fields never lie in pastures so pasture cache rides along). Fires BEFORE the mechanical take so fields are still fully sown.
- ordering: Two coupled subtleties. (1) CAP semantics: unlike Scythe Worker (every eligible field), this is capped at N = count_unfenced_stables, so _apply must COUNT taken goods and stop at N — and it applies to BOTH grain (>=2) and veg (>=2) fields, not grain only. (2) FIRE ORDER / depletion: fires in _resolve_harvest_field BEFORE the mechanical 1-per-field take while fields are fully sown, so only a field with >=2 of its crop can spare an extra (a 1-count field's single crop belongs to the normal take). Take-maximum models the 'you can' as mandatory (per Scythe's deferred-choice convention). Field SELECTION among eligible fields is value-neutral at fire time (every eligible field yields exactly +1 of its own crop), so first-N-eligible is a fine deterministic order; do NOT over-engineer a grain-vs-veg priority. Read the LIVE grid at fire time (no pre-snapshot) so interaction with another harvest_field card that registered earlier (e.g. Scythe Worker reducing a 2-grain field to 1) is counted correctly.
- errata: None. Card data: cost null (free), vps null, passing null, category Crop Provider, prereq 'At Most 1 Occupation'.

#### supply_boat  (tier 2, minor, conf high) — D_73.json
- template: agricola/cards/cottager.py (OPTIONAL play-variant trigger on a hosted atomic space, decline = host Proceed); after-phase wiring + explicit-after timing per agricola/cards/carpenters_axe.py; resource-swap apply per agricola/cards/potter_ceramics.py.
- plan: ["register_minor('supply_boat', cost=Cost(Resources(wood=1)), min_occupations=1, vps=1, on_play=lambda s,i: s)  # cost 1 wood; prereq 1 occupation; 1 VP; no on-play effect.", "SPACES = frozenset({'fishing'}); register_action_space_hook('supply_boat', SPACES)  # fishing is ATOMIC -> must host so a PendingActionSpace after-phase frame surfaces the trigger.", "_legal_variants(state, idx): returns ['grain'] if food>=1 then append 'vegetable' if food>=3 (affordability gate, exactly like Cottager gates room/renovate; empty list -> nothing offered).", "register_play_variant_trigger('supply_boat', _legal_variants)  # collapses the 'A OR B' choice into one FireTrigger(card_id, variant=...) per affordable route.", "_eligible(state, idx, triggers_resolved): top=pending_stack[-1]; return getattr(top,'space_id',None) in SPACES and bool(_legal_variants(...)) (triggers_resolved once-per-use handled by _apply_fire_trigger).", "_apply(state, idx, variant): swap = Resources(food=-1, grain=1) if variant=='grain' else Resources(food=-3, veg=1); p=fast_replace(p, resources=p.resources+swap); rebuild players; return state (NO push -- apply is a direct swap, no sub-frame, so NO PendingCardChoice/resolver needed). register('after_action_space','supply_boat',_eligible,_apply)  # OPTIONAL (not register_auto/mandatory); decline = host Stop in after-phase."]
- ordering: TWO subtleties. (1) TIMING: text says 'Each time AFTER you use Fishing' -> the explicit 'immediately after' exception, so it rides after_action_space (the after-phase frame), NOT before_action_space; decline is the after-phase Stop (not Proceed). Fishing's own +1 food pickup has already happened, so the food the player pays with may include this turn's catch -- correct. (2) OPTIONALITY + AFFORDABILITY: 'you can choose to buy' is OPTIONAL (plain register, not register_auto/mandatory) -- declining must be possible, so the variant enumerator MUST gate each option on affordability (food>=1 for grain, food>=3 for veg) to never surface a dead-end fire; with neither affordable, no FireTrigger is offered and the after-phase Stop is the only action.
- errata: None in card_text.py output (no errata/clarifications listed).
- open_q: Confirm card intent: the printed prices are 1 grain for 1 food and 1 vegetable for 3 food (buy ONE good per Fishing use, choice of which) -- the plan buys exactly one per use, declinable. If the user reads it as 'may buy up to one of EACH' the variant model still works (re-fire would need both, but triggers_resolved caps at one fire/use); flag only if a multi-buy reading is intended.

#### roof_ladder  (tier 2, minor, conf high) — D_81.json
- template: bricklayer.py (register_reduction('renovate',...)) for the reed reduction + roughcaster.py (register_auto('after_renovate',...)) for the deferred +1 stone
- plan: register_minor('roof_ladder', cost=Cost(resources=Resources(wood=1)), on_play=_noop_on_play)  # 0 VP, no on-play effect. def _less_1_reed(state, idx, ctx, cost): return cost - Resources(reed=1); register_reduction('renovate', CARD_ID, _less_1_reed)  # apply_reductions floors at 0. def _grant_stone(state, idx): p = fast_replace(state.players[idx], resources=state.players[idx].resources + Resources(stone=1)); return fast_replace(state, players=tuple(p if i==idx else state.players[i] for i in range(2))); register_auto('after_renovate', CARD_ID, lambda s, i: True, _grant_stone)  # choiceless pure-goods grant, fires once per renovate at the after-phase flip.
- ordering: The +1 stone is a deferred ('at the end of the action') choiceless pure-goods grant, so it MUST be register_auto (mandatory, no FireTrigger), NOT the declinable register() that Mining Hammer uses — Mining Hammer is declinable only because it pushes a granted sub-action (a real choice); here there is no downside. Use after_renovate (post-application), per the renovate-hook convention, and eligibility is unconditional (lambda s,i: True) — the +1 stone applies to EVERY renovate (clay->clay, clay->stone, etc.), unlike Roughcaster which gates on house_material. Confirm the reed reduction does not need to be gated: clay-renovate costs reed (reduction bites), stone-renovate costs no reed (apply_reductions floors the signed -1 reed at 0, so it is a safe no-op there).
- errata: None reported by card_text.py (no errata/clarifications block).

#### stablehand  (tier 2, occupation, conf high) — D_89.json
- template: agricola/cards/mining_hammer.py (near-exact: 'each time you <X>, you can also build a stable without paying wood' = optional after-event FireTrigger pushing PendingBuildStables free, cap 1). Hook event swaps after_renovate -> after_build_fences (see loppers.py / shepherds_crook.py for the build_fences host).
- plan: register_occupation('stablehand', lambda state, idx: state) -- no cost/prereq/vps; on_play is a mandatory callable so use the verified no-op idiom from stable_architect.py (register_occupation requires a Callable, specs.py:38). register('after_build_fences','stablehand', _eligible, _apply). _eligible(state,idx,triggers_resolved): return 'stablehand' not in triggers_resolved and _can_build_stable(state, state.players[idx], Resources()) -- import _can_build_stable from agricola.legality. _apply(state,idx): return push(state, PendingBuildStables(player_idx=idx, initiated_by_id='card:stablehand', cost=Resources(), max_builds=1)). The after_build_fences after-phase is only reached when >=1 fence was built (Proceed requires pastures_built>=1), so 'each time you build at least 1 fence' needs no extra fence-count guard. No register_scoring/CardStore/schedule needed.
- ordering: The 'at least 1 fence' precondition is satisfied BY CONSTRUCTION at the after_build_fences flip -- do NOT add a fence-count guard (loppers.py documents Proceed already requires pastures_built>=1). The once-per-action limit (one free stable per Build Fences action, not per individual fence) is enforced by the triggers_resolved guard 'CARD_ID not in triggers_resolved' in _eligible, exactly as Mining Hammer does for per-renovate; _apply_fire_trigger stamps the card id before applying. Use cost=Resources() (free of wood) and gate eligibility on a free stable being buildable so the trigger never offers a dead-end.
- errata: None. card_text.py reports no errata/clarifications for Stablehand. (Sibling note: unlike Stable Planner's scheduled off-turn stables, this is an on-turn grant during the player's own Build Fences action, so no off-turn Stable Tree / Farmyard Manure caveat applies.)
- open_q: Confirm 'each time you build at least 1 fence' means once per Build Fences ACTION (the modeled per-action after-phase fire), not once per individual fence piece -- standard ruling and matches Mining Hammer/Loppers per-action semantics, so implemented as once-per-action. (No-op on_play question RESOLVED: register_occupation requires a Callable, stable_architect uses 'lambda state, idx: state'.)

#### plowman  (tier 2, occupation, conf high) — D_91.json
- template: agricola/cards/handplow.py (schedule + start-of-round optional plow grant) FUSED WITH agricola/cards/plow_driver.py (pay-1-food-to-plow via the shared food-payment path)
- plan: On play: schedule_effect(state, idx, (R+4, R+7, R+10), 'plowman') where R=state.round_number (schedule_effect clamps rounds>14 for free). register_occupation('plowman', _on_play); register('start_of_round', 'plowman', _eligible, _apply); register_food_payment_resume('plowman', _pay_and_plow). _eligible(state,idx,tr): the card id sits in THIS round's future_rewards slot (Handplow's _scheduled_slot helper) AND _liquidatable_to(state,idx,p,Resources(food=1)) AND _can_plow(p). _apply(state,idx): FIRST remove 'plowman' from this round's future_rewards slot (Handplow consume), THEN Plow-Driver body: if p.resources.food>=1 -> _pay_and_plow (debit 1 food, push PendingPlow init 'card:plowman'); else push PendingFoodPayment(player_idx=idx, food_needed=1, resume_kind='plowman', reserved=Cost()). _pay_and_plow debits the 1 food then pushes the plow (it is also the registered resume). NOT register_start_of_round_hook (schedule drives hosting only on the 3 due rounds, like Handplow). No cost/prereq/vps/passing.
- ordering: The once-per-scheduled-round guarantee must come from CONSUMING the schedule slot (Handplow's pattern), NOT from used_this_round (Plow Driver's latch, which it needs only because it fires every round). Consume the slot in _apply (the GUARD), BEFORE the food-payment branch -- so when food is short and a PendingFoodPayment is pushed, the start-of-round FireTrigger no longer re-qualifies while that frame resolves. Putting the slot-consume in _pay_and_plow (the body/resume) would re-offer the trigger during the food-raise. (Plowman therefore consumes its slot in _apply, unlike Plow Driver which latches in its body, because Plowman's gate is the schedule slot, not used_this_round.)
- errata: none (no errata/clarifications surfaced by card_text.py)
- open_q: The physical 'place a field tile on each corresponding round space' is modeled as cosmetic only (a round-space reminder), exactly as Handplow ignores its identical 'place 1 field tile on the corresponding round space' clause -- no field-tile supply is tracked in state. Worth a one-line confirm with the user that this is the intended modeling, but Handplow sets the precedent so this is not a blocker.

### Defer (by blocker)

**animal-accommodation-infra (sheep-only / type-restricted per-card flexible slots)**
- sheep_agent — 

**animal_location_tracking**
- muck_rake — 

**animal_output_harvest_conversion**
- feed_pellets — 

**any_player_after_subaction_needs_acting_player**
- recycled_brick — 

**anytime_action**
- master_builder — 

**at-any-time-standalone-action**
- pellet_press — 

**at_any_time_build_cost_food_renovate**
- trowel — 

**at_any_time_conversion + return_improvement_minor_cost**
- earth_oven — 

**at_any_time_window**
- changeover — 

**build-major-site-and-multibuild**
- carpenters_yard — 

**card_as_field_per_card_goods_stack**
- wood_field — 

**card_granted_family_growth_no_space_placement**
- child_ombudsman — 

**cooking_conversion_bonus**
- fatstock_stretcher — 

**end_of_round_hook**
- baking_course — 

**end_of_round_timing_seam**
- carrot_museum — 

**end_of_turn_timing**
- royal_wood — 

**geometry**
- zigzag_harrow — 

**granted-improvement-action**
- furnisher — 

**granted_constrained_sow**
- fern_seeds — 

**house_animal_capacity_negation**
- milking_place — 

**immediate-animal-grant-no-accommodation**
- pigswill — 

**major_improvement_swap**
- retraining — 

**minor-play-variant / subaction-injection at minor-improvement hosts (new shared infra)**
- recruitment — 

**multi_grant_within_one_host_visit**
- turnwrest_plow — 

**needs-game-history-tracking (cumulative non-breeding-sheep-acquisition counter + sheep-into-food latch; new shared event taxonomy + multi-site instrumentation)**
- breed_registry — 

**needs_built_improvement_identity_in_auto_signature**
- brick_hammer — 

**new_shared_action_space+extra_worker+return_home_hook**
- archway — 

**occupation-grants-build-major + occupation-prereq**
- site_manager — 

**optional_choice_harvest_field**
- straw_manure — 

**per_pasture_size_aware_capacity_mod**
- lawn_fertilizer — 

**placement-forbid-extension (new shared legality infra) + hidden round-space identity**
- foreign_aid — 

**polymorphic_entity**
- witches_dance_floor — 

**post_feed_hook**
- social_benefits — 

**private_action_space**
- pioneering_spirit — 

**return-major-as-play-cost; at-any-time-standalone-conversion**
- large_pottery — 

**return_home_event_seam**
- rolling_pin — 

**return_home_phase_hook**
- steam_plow — 

**return_home_phase_timing + spaceless_family_growth**
- storks_nest — 

**room_capacity_modifier**
- reader — 

**sow-field-cap**
- furrows — 

**start_of_harvest_hook+free_occupation_play**
- begging_student — 

**temp_extra_worker**
- work_permit — 

**temporary_extra_worker_mid_phase_return**
- sheep_inspector — 

**turn_order_consecutive_placement**
- brotherly_love — 

**turn_order_deferred_placement**
- tea_house — 

**worker-return-mid-round + placement-order/which-space provenance**
- henpecked_husband — 
