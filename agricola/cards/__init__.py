"""Card package.

Importing this package imports each card module so their register() calls
run at module load time, populating agricola.cards.triggers.TRIGGERS and
agricola.cards.triggers.CARDS, as well as predicate-extension registries
in agricola.legality (e.g., BAKE_BREAD_ELIGIBILITY_EXTENSIONS).

The harvest_conversions module is imported here too so the three built-in
craft conversions (joinery / pottery / basketmaker) register their entries
in HARVEST_CONVERSIONS at package load — paralleling the trigger registry
pattern.

Future card modules are added to this file as they're implemented.
"""
from agricola.cards import harvest_conversions  # noqa: F401
from agricola.cards import potter_ceramics      # noqa: F401

# Occupations (card game). Importing each registers its OccupationSpec in
# agricola.cards.specs.OCCUPATIONS at package load. See CARD_IMPLEMENTATION_PLAN.md II.4.
from agricola.cards import consultant           # noqa: F401
from agricola.cards import priest               # noqa: F401
from agricola.cards import stable_architect     # noqa: F401
# Category 6 (harvest-field hook, automatic field-phase income) — Scythe Worker is
# an occupation (also an on-play +1 grain); the other three are minors registered
# below. All register_auto on the `harvest_field` event + register_harvest_field_hook.
from agricola.cards import scythe_worker         # noqa: F401
# Category 3 (action-space hook, automatic income) — also populate AUTO_EFFECTS
# and the action-space hosting indexes via register_auto/register_action_space_hook.
from agricola.cards import wood_cutter          # noqa: F401
from agricola.cards import geologist            # noqa: F401
# Category 10 (bounded-hook wood->food conversion; optional FireTrigger).
from agricola.cards import mushroom_collector   # noqa: F401
# Category 4 (action-space hook, granted sub-action; optional FireTrigger that
# pushes an existing primitive pending).
from agricola.cards import assistant_tiller     # noqa: F401
from agricola.cards import oven_firing_boy      # noqa: F401
# Category 9 (opponent-action hook; any-player automatic effect on Cattle Market).
from agricola.cards import milk_jug             # noqa: F401
# NOTE: Firewood Collector ("+1 wood at the END of that turn") is DEFERRED, not
# imported here — its "end of turn" timing has no correct anchor until "at any time"
# card effects define a post-action turn-end window (firing at the space-host pop, as
# an earlier version did, would make the wood spendable within the turn). The module
# is preserved under archive/deferred_cards/. See CARD_IMPLEMENTATION_PLAN.md.
# Category 3/4 on non-atomic spaces' after-phase (the multi-sub after-trigger model).
from agricola.cards import threshing_board      # noqa: F401
# Category 4 — the build-room-OR-renovate choice on the Day Laborer host, modeled as
# a play-variant trigger (build_room / renovate) on before_action_space.
from agricola.cards import cottager             # noqa: F401
# Category 5 (build / renovate / bake / play-card hooks). Roughcaster is an
# occupation; the other four are minors registered below. The coarse
# `after_build_improvement` event (Junk Room) is fired by _execute_build_major
# and _execute_play_minor; `after_build_rooms` (Roughcaster's clay-room clause) is
# fired by _apply_stop at the build-rooms session end.
from agricola.cards import roughcaster          # noqa: F401
# Cost-modifier occupations (COST_MODIFIER_DESIGN.md). Passive cards that change what
# a build/renovate/improvement costs by registering rows in the cost-mod registries
# (agricola.cards.cost_mods), resolved through the `effective_payments` chokepoint;
# their on-play is a no-op. The three modifier kinds are all represented:
# Bricklayer (clay REDUCTION), Frame Builder (2 clay/stone -> 1 wood CONVERSION),
# Carpenter + Clay Plasterer (whole-cost FORMULAs). Renovate, build-room, and
# play-minor are the actions wired through the chokepoint so far.
from agricola.cards import bricklayer           # noqa: F401
from agricola.cards import frame_builder        # noqa: F401
from agricola.cards import carpenter            # noqa: F401
from agricola.cards import clay_plasterer       # noqa: F401
# Millwright: on-play +1 grain, plus the conversion SINK (replace up to 2 building
# resources with 1 grain each) that chains after feeder conversions (§4.4/§4.7).
from agricola.cards import millwright           # noqa: F401
# Master Bricklayer (occupation): build_major stone REDUCTION by the number of rooms
# built beyond the two starting rooms (a state-dependent delta, floored at 0).
from agricola.cards import master_bricklayer    # noqa: F401
# Cost-modifier MINORS. Carpenter's Parlor (build_room whole-cost FORMULA — 2 wood +
# 2 reed — only in a WOOD house); Lumber Mill (build_major + play_minor −1-wood
# REDUCTION; "every improvement" = major OR minor only, not rooms/renovation).
from agricola.cards import carpenters_parlor    # noqa: F401
from agricola.cards import lumber_mill          # noqa: F401
# Conservator (occupation): a renovate-TARGET extension — wood house may renovate
# directly to stone (skipping clay); the stone-tier cost flows through the chokepoint.
from agricola.cards import conservator          # noqa: F401
# Hedge Keeper (occupation, COST_MODIFIER_DESIGN.md §9): the first free-fence card —
# registers a free-fence SEED of +3 on a LITERAL Build Fences action (gated on
# build_fences_action). The seed is the single source of truth for the per-action
# free_fence_budget at all three sites (frame push, placement anticipation, during-
# building enumerator), so legality is now free-fence-aware: a tight-wood build the
# budget covers is enabled, not merely discounted. Cards-only deferred tally; no
# on-play effect.
from agricola.cards import hedge_keeper          # noqa: F401
# Rammed Clay (minor, COST_MODIFIER_DESIGN.md §9): a build_fence CONVERSION (clay may
# substitute for wood, 1:1, unlimited) + on-play +1 clay. A plain producer conversion;
# the settle payment menu surfaces the wood/clay splits, and the running-total legality
# lets clay enable a wood-tight build.
from agricola.cards import rammed_clay           # noqa: F401
# Briar Hedge (minor, COST_MODIFIER_DESIGN.md §9): the first POSITIONAL per-edge free-fence
# card — board-perimeter fence edges cost no wood (ungated, any fence build). Registers a
# free-fence EDGE fn (distinct from the scalar seed registry); prereq 1 animal of each type.
from agricola.cards import briar_hedge           # noqa: F401
# Field Fences (minor, COST_MODIFIER_DESIGN.md §9): GRANTS a Build Fences action on play
# (on_play pushes PendingBuildFences, initiated_by_id "card:field_fences") with a POSITIONAL
# discount scoped to that grant — edges next to a field tile cost no wood. Combines the grant
# pattern (Shifting Cultivation) with the provenance-gated positional fold. Cost 2 food.
from agricola.cards import field_fences          # noqa: F401
# Ash Trees (minor, COST_MODIFIER_DESIGN.md §9): the persistent free-fence POOL — on play
# moves up to 5 fences from the supply pile onto the card (a CardStore pool); building spends
# them free (the THIRD free-fence source, after positional + per-action budget). Uses the
# stored fences_in_supply field. Prereq 2 planted fields.
from agricola.cards import ash_trees             # noqa: F401
# Hunting Trophy (minor, COST_MODIFIER_DESIGN.md §9): three pieces — a 1-boar cost with an
# on-play cook-for-food bonus (cooking_rates), a +3 free-fence SEED on Farm Redevelopment, and
# a "1 building resource of your choice less" CONVERSION on improvements built via House
# Redevelopment (gated on a PendingHouseRedevelopment frame on the stack). 1 VP.
from agricola.cards import hunting_trophy         # noqa: F401
# Mini Pasture (minor, COST_MODIFIER_DESIGN.md §9.8): the first RESTRICTED grant — on play,
# MANDATORY-fence a free NEW 1×1 enclosure (FenceRestrictions exact_size=1, forbid_subdivision,
# max_pastures=1; free_fence_budget=4; build_fences_action=False). Unplayable unless such a 1×1
# is buildable (its prereq). Cost 2 food.
from agricola.cards import mini_pasture           # noqa: F401

# Minor improvements (card game). Importing each registers its MinorSpec in
# agricola.cards.specs.MINORS at package load. See CARD_IMPLEMENTATION_PLAN.md II.4.
from agricola.cards import market_stall         # noqa: F401
# Capacity-modifier minor: Drinking Trough — +2 animals per pasture (a flat per-pasture
# capacity bonus via the capacity_mods registry, the Animal Tamer pair).
from agricola.cards import drinking_trough      # noqa: F401
# Category 3 automatic-income minors.
from agricola.cards import corn_scoop           # noqa: F401
from agricola.cards import stone_tongs          # noqa: F401
from agricola.cards import pitchfork            # noqa: F401
from agricola.cards import basket               # noqa: F401
from agricola.cards import loam_pit             # noqa: F401
from agricola.cards import canoe                # noqa: F401
# Category 1 (end-game scoring terms — pure derived reads).
from agricola.cards import manger               # noqa: F401
from agricola.cards import wool_blankets        # noqa: F401
# Category 2 (on-play one-shot gains; both traveling/passing).
from agricola.cards import clay_embankment      # noqa: F401
from agricola.cards import young_animal_market  # noqa: F401
# Category 5 (build / renovate / bake / play-card hooks) minors. Junk Room (+1
# food on after_build_improvement), Mining Hammer (on_play +1 food; after_renovate
# grants a free stable), Bread Paddle (on_play +1 food; after_play_occupation
# grants a Bake Bread), Dutch Windmill (+3 food on after_bake_bread in a
# post-harvest round).
from agricola.cards import junk_room            # noqa: F401
from agricola.cards import mining_hammer        # noqa: F401
from agricola.cards import bread_paddle         # noqa: F401
from agricola.cards import dutch_windmill       # noqa: F401
# Shepherd's Crook (minor): a before/after_build_fences automatic pair — snapshot
# the pasture decomposition before fencing, then grant 2 sheep per new >= 4-space
# pasture after. The first card to hook the build_fences host (which gained its
# before/after phase for exactly this card).
from agricola.cards import shepherds_crook       # noqa: F401
# Category 6 (harvest-field hook) minors. Loom (1/2/3 food at ≥1/4/7 sheep + a
# scoring term), Butter Churn (1 food per 3 sheep + 1 per 2 cattle), Three-Field
# Rotation (3 food with a grain + veg + empty field). All register_auto on the
# `harvest_field` event.
from agricola.cards import loom                  # noqa: F401
from agricola.cards import butter_churn          # noqa: F401
from agricola.cards import three_field_rotation  # noqa: F401
# Category 7 (start-of-round phase hook) — the PendingPreparation host fires the
# `start_of_round` event. Auto-effects (Small-scale Farmer +1 wood at exactly 2
# rooms; Scullery +1 food in a wooden house — a minor) fire immediately at push;
# OPTIONAL triggers (Plow Driver pay-1-food-plow, Groom build-a-stable) surface as
# FireTrigger; the MANDATORY-with-choice Childless (+1 food + grain/veg pick) gates
# the host's Proceed; Scholar is the collapsed play-variant trigger (play an
# occupation OR a minor at round start). All but Scholar/Childless/Plow Driver/Groom
# also register_start_of_round_hook so the host frame is pushed when owned.
from agricola.cards import small_scale_farmer    # noqa: F401
from agricola.cards import scullery              # noqa: F401
from agricola.cards import plow_driver           # noqa: F401
from agricola.cards import groom                 # noqa: F401
from agricola.cards import childless             # noqa: F401
from agricola.cards import scholar               # noqa: F401
# Category 3 (action-space hook) — Seasonal Worker is the MANDATORY-with-choice
# trigger on the Day Laborer space-host: +1 grain each use (or +1 veg from round 6),
# the choice surfaced as a PendingCardChoice whose options are round-dependent.
from agricola.cards import seasonal_worker       # noqa: F401
# CardStore cards (per-card persistent state side-map, II.7). Tutor (occupation,
# Cat 1 — on_play snapshots len(occupations), scoring term counts occupations after
# it); Big Country (minor, Cat 2 — immediate food + banked bonus points scaled by
# complete rounds left, scoring term reads the bank); Moldboard Plow (minor, Cat 4 —
# twice-per-game granted plow on the Farmland after-hook, uses-left in CardStore);
# Roof Ballaster (occupation, Cat 2 — optional pay-1-food→1-stone-per-room, modeled
# as a play-VARIANT); Shifting Cultivation (minor, Cat 2, traveling — on_play pushes
# PendingPlow on top of the after-flipped play host).
from agricola.cards import tutor                 # noqa: F401
from agricola.cards import big_country           # noqa: F401
# Mantlepiece (minor, Cat 2 — bank 1 bonus point per complete round left, scoring term
# reads it back; −3 printed VPs; renovation permanently forbidden via _can_renovate).
from agricola.cards import mantlepiece           # noqa: F401
# Bottles (minor, Cat 2 — variable cost: people_total × (1 clay + 1 food) via cost_fn;
# 4 printed VPs; no on-play effect beyond paying the cost).
from agricola.cards import bottles               # noqa: F401
from agricola.cards import moldboard_plow        # noqa: F401
from agricola.cards import roof_ballaster        # noqa: F401
# Capacity-modifier occupation: Animal Tamer — wide wood/grain play-variant + the house
# holds one (any-type) animal per room (raises the house-pet flexible-slot count).
from agricola.cards import animal_tamer          # noqa: F401
from agricola.cards import shifting_cultivation  # noqa: F401
# Food-from-a-trigger (FOOD_PAYMENT_DESIGN.md §8): Ox Goad — pay 2 food (via the shared
# food-payment path, liquidation-aware) after Cattle Market to plow 1 field.
from agricola.cards import ox_goad               # noqa: F401
# Pay-food → plow cluster (PAY_FOOD_PLOW_CARDS.md): the same trigger shape as Ox Goad,
# differing only in event / filter / food amount. Plow Maker (occ, before_action_space on
# Farmland/Cultivation, 1 food); Shifting Cultivator (occ, before_action_space on the
# Forest wood-accumulation space — atomic, so action-space-hooked — 3 food); Drill Harrow
# (minor, before_sow — every sow is unconditional in the implemented set — 3 food); Plow
# Hero (occ, like Plow Maker but only with the FIRST worker placed in a round, derived
# from people_home == people_total − 1, 1 food). Mole Plow (minor) is the OUTLIER — the
# granted plow is FREE (the food is the play cost), so it is the Assistant Tiller template
# (optional trigger pushing a free PendingPlow) with a "round ≥ 9" prereq.
from agricola.cards import plow_maker            # noqa: F401
from agricola.cards import shifting_cultivator   # noqa: F401
from agricola.cards import drill_harrow          # noqa: F401
from agricola.cards import plow_hero             # noqa: F401
from agricola.cards import mole_plow             # noqa: F401
# Paper Maker (occ, FOOD_PAYMENT_DESIGN.md): an optional before_play_occupation trigger — pay
# 1 wood to get 1 food per occupation in front of you. Self-excludes via ownership timing.
# Also an OCCUPATION_FOOD_SOURCE so the Lessons/Scholar gate (`_payable_occupation`) offers a
# play payable only by firing it first; the play-occ commit gate then forces the fire order.
from agricola.cards import paper_maker           # noqa: F401
# Food-in-a-build-cost (FOOD_PAYMENT_DESIGN.md §9): Wood Expert — pay 1 food instead of up to
# 2 wood per improvement (a cost conversion on build_major/play_minor), +2 wood on play.
from agricola.cards import wood_expert           # noqa: F401
# Category 8 (deferred goods / effects on round spaces, II.5). These schedule goods
# onto future round-space slots (future_resources), collected at the start of each
# scheduled round in _complete_preparation. Wall Builder (occupation, food on the
# next 4 rounds at each room build, after_build_rooms); Manservant + Clay Hut
# Builder (occupations, gated on the house-material one-shot conditional latch —
# fired_once + _fire_ready_one_shots); Pond Hut / Strawberry Patch (1 food, next 3
# rounds, on_play); Large Greenhouse (1 veg on R+4/R+7/R+9); Sack Cart (1 grain on
# the remaining absolute rounds 5/8/11/14); Thick Forest (1 wood on remaining even
# rounds; "5 clay in supply" is a prereq, not a cost); Herring Pot (1 food on next
# 3 rounds each Fishing use, after_action_space). Handplow is the exotic EFFECT
# case: it schedules a round-start plow (future_rewards effect hook), pushed as
# PendingPlow when round R+5 is entered.
from agricola.cards import wall_builder          # noqa: F401
from agricola.cards import manservant            # noqa: F401
from agricola.cards import clay_hut_builder      # noqa: F401
from agricola.cards import pond_hut              # noqa: F401
from agricola.cards import large_greenhouse      # noqa: F401
from agricola.cards import strawberry_patch      # noqa: F401
from agricola.cards import sack_cart             # noqa: F401
from agricola.cards import thick_forest          # noqa: F401
from agricola.cards import herring_pot           # noqa: F401
from agricola.cards import handplow              # noqa: F401
# Legality relaxation (occupancy override): Sleeping Corner (minor A26) — the owner may
# place on a "Wish for Children" space occupied by ONE other player. Registers an
# occupancy-override predicate consulted by `_is_available` only on the occupied branch
# (counts PLAYERS, not workers — a used wish space already holds the parent + newborn).
from agricola.cards import sleeping_corner       # noqa: F401


# ===========================================================================

# Artifex (deck A) + Bubulcus (deck B) tier-1/2 batch + rescued tier-3 + a base

# card (Acorns Basket). Implemented 2026-06-30 via the card-batch process; full

# per-card specs in CARD_BATCH_TRIAGE.md, deferred siblings in CARD_DEFERRED_PLANS.md.

# ===========================================================================

# Artifex (A) — tier 1/2
from agricola.cards import fellow_grazer  # noqa: F401
from agricola.cards import cookery_outfitter  # noqa: F401
from agricola.cards import barrow_pusher  # noqa: F401
from agricola.cards import wood_carrier  # noqa: F401
from agricola.cards import pan_baker  # noqa: F401
from agricola.cards import seed_pellets  # noqa: F401
from agricola.cards import clay_puncher  # noqa: F401
from agricola.cards import food_basket  # noqa: F401
from agricola.cards import milking_parlor  # noqa: F401
from agricola.cards import gardeners_knife  # noqa: F401
from agricola.cards import storage_barn  # noqa: F401
from agricola.cards import drift_net_boat  # noqa: F401
from agricola.cards import forest_lake_hut  # noqa: F401
from agricola.cards import throwing_axe  # noqa: F401
from agricola.cards import hod  # noqa: F401
from agricola.cards import trellises  # noqa: F401
from agricola.cards import claw_knife  # noqa: F401
from agricola.cards import fire_protection_pond  # noqa: F401
from agricola.cards import cob  # noqa: F401
from agricola.cards import stable_planner  # noqa: F401
from agricola.cards import carpenters_axe  # noqa: F401
from agricola.cards import feeding_dish  # noqa: F401
from agricola.cards import wood_harvester  # noqa: F401
from agricola.cards import slurry_spreader  # noqa: F401
from agricola.cards import catcher  # noqa: F401
from agricola.cards import heresy_teacher  # noqa: F401
from agricola.cards import calcium_fertilizers  # noqa: F401
from agricola.cards import asparagus_gift  # noqa: F401
from agricola.cards import interim_storage  # noqa: F401
from agricola.cards import debt_security  # noqa: F401
from agricola.cards import bucksaw  # noqa: F401
from agricola.cards import loppers  # noqa: F401
from agricola.cards import portmonger  # noqa: F401
from agricola.cards import garden_hoe  # noqa: F401
from agricola.cards import small_trader  # noqa: F401

# Bubulcus (B) — tier 1/2
from agricola.cards import case_builder  # noqa: F401
from agricola.cards import lumberjack  # noqa: F401
from agricola.cards import estate_worker  # noqa: F401
from agricola.cards import grange  # noqa: F401
from agricola.cards import excursion_to_the_quarry  # noqa: F401
from agricola.cards import brewery_pond  # noqa: F401
from agricola.cards import chick_stable  # noqa: F401
from agricola.cards import club_house  # noqa: F401
from agricola.cards import reed_belt  # noqa: F401
from agricola.cards import gift_basket  # noqa: F401
from agricola.cards import cooperative_plower  # noqa: F401
from agricola.cards import tree_farm_joiner  # noqa: F401
from agricola.cards import furniture_carpenter  # noqa: F401
from agricola.cards import pavior  # noqa: F401
from agricola.cards import rustic  # noqa: F401
from agricola.cards import mineralogist  # noqa: F401
from agricola.cards import trimmer  # noqa: F401
from agricola.cards import wood_pile  # noqa: F401
from agricola.cards import chain_float  # noqa: F401
from agricola.cards import chophouse  # noqa: F401
from agricola.cards import digging_spade  # noqa: F401
from agricola.cards import growing_farm  # noqa: F401
from agricola.cards import tumbrel  # noqa: F401
from agricola.cards import crack_weeder  # noqa: F401
from agricola.cards import food_chest  # noqa: F401
from agricola.cards import brewing_water  # noqa: F401
from agricola.cards import tasting  # noqa: F401
from agricola.cards import mill_wheel  # noqa: F401
from agricola.cards import hand_truck  # noqa: F401
from agricola.cards import harvest_house  # noqa: F401
from agricola.cards import wood_workshop  # noqa: F401
from agricola.cards import corf  # noqa: F401

# Rescued tier-3 (Artifex/Bubulcus/base) — re-examined as buildable now
from agricola.cards import nest_site  # noqa: F401
from agricola.cards import maintenance_premium  # noqa: F401
from agricola.cards import grassland_harrow  # noqa: F401
from agricola.cards import baking_sheet  # noqa: F401
from agricola.cards import pottery_yard  # noqa: F401
from agricola.cards import beer_keg  # noqa: F401
from agricola.cards import forest_school  # noqa: F401
from agricola.cards import forestry_studies  # noqa: F401

# Base (Revised) — scheduled-animal grant (Acorns Basket, next-2-rounds boar)
from agricola.cards import acorns_basket  # noqa: F401

# ===========================================================================
# Corbarius (deck C) — tier-1 batch (from-scratch triage; 2026-06-30). Specs in
# CARD_TRIAGE_CDE.md. (Canvas Sack deferred — minor play-variant '/' cost, archived.)
# ===========================================================================
from agricola.cards import potato_harvester  # noqa: F401
from agricola.cards import small_animal_breeder  # noqa: F401
from agricola.cards import wood_collector  # noqa: F401
from agricola.cards import skillful_renovator  # noqa: F401
from agricola.cards import clay_kneader  # noqa: F401
from agricola.cards import freemason  # noqa: F401
from agricola.cards import soldier  # noqa: F401
from agricola.cards import sheep_provider  # noqa: F401
from agricola.cards import market_crier  # noqa: F401
from agricola.cards import cowherd  # noqa: F401
from agricola.cards import resource_analyzer  # noqa: F401
from agricola.cards import half_timbered_house  # noqa: F401
from agricola.cards import abort_oriel  # noqa: F401
from agricola.cards import greening_plan  # noqa: F401
from agricola.cards import lantern_house  # noqa: F401
from agricola.cards import christianity  # noqa: F401
from agricola.cards import writing_boards  # noqa: F401
from agricola.cards import remodeling  # noqa: F401
from agricola.cards import bookcase  # noqa: F401
from agricola.cards import blade_shears  # noqa: F401
from agricola.cards import private_forest  # noqa: F401
from agricola.cards import wood_cart  # noqa: F401
from agricola.cards import plant_fertilizer  # noqa: F401

# Corbarius (deck C) — tier-2 batch (from-scratch triage; 2026-06-30). Specs in
# CARD_TRIAGE_CDE.md. (Granary deferred — '/' alt-cost; not written.)
from agricola.cards import butler  # noqa: F401
from agricola.cards import tree_guard  # noqa: F401
from agricola.cards import schnapps_distiller  # noqa: F401
from agricola.cards import home_brewer  # noqa: F401
from agricola.cards import thresher  # noqa: F401
from agricola.cards import winter_caretaker  # noqa: F401
from agricola.cards import soil_scientist  # noqa: F401
from agricola.cards import excavator  # noqa: F401
from agricola.cards import wooden_hut_extender  # noqa: F401
from agricola.cards import second_spouse  # noqa: F401
from agricola.cards import private_teacher  # noqa: F401
from agricola.cards import straw_thatched_roof  # noqa: F401
from agricola.cards import trellis  # noqa: F401
from agricola.cards import cattle_whisperer  # noqa: F401
from agricola.cards import stable  # noqa: F401
from agricola.cards import steam_machine  # noqa: F401
from agricola.cards import flail  # noqa: F401
from agricola.cards import teachers_desk  # noqa: F401
from agricola.cards import elephantgrass_plant  # noqa: F401
from agricola.cards import clay_deposit  # noqa: F401
from agricola.cards import farm_store  # noqa: F401
from agricola.cards import farm_building  # noqa: F401
from agricola.cards import stew  # noqa: F401
from agricola.cards import garden_claw  # noqa: F401
from agricola.cards import studio  # noqa: F401
from agricola.cards import woodcraft  # noqa: F401
from agricola.cards import schnapps_distillery  # noqa: F401
from agricola.cards import beer_stein  # noqa: F401
from agricola.cards import corn_schnapps_distillery  # noqa: F401
from agricola.cards import clay_supply  # noqa: F401
from agricola.cards import reed_hatted_toad  # noqa: F401
from agricola.cards import stone_cart  # noqa: F401
from agricola.cards import rocky_terrain  # noqa: F401
from agricola.cards import hardware_store  # noqa: F401
from agricola.cards import field_watchman  # noqa: F401
from agricola.cards import cube_cutter  # noqa: F401

# ===========================================================================
# Dulcinaria (deck D) — tier-1/2 batch (from-scratch triage; 2026-06-30). Specs in
# CARD_TRIAGE_CDE.md. potter_ceramics (D66) is the pre-existing forward-compat trigger
# card, now made a dealable free minor (register_minor wiring added) — imported above.
# hammer_crusher (D14) deferred: "renovate to stone" needs target-conditional
# before_renovate firing (the renovate target isn't known until commit; gating on a
# clay house misses the reachable Conservator wood->stone case). See CARD_DEFERRED_PLANS.md.
# ===========================================================================
from agricola.cards import artisan_district  # noqa: F401
from agricola.cards import bale_of_straw  # noqa: F401
from agricola.cards import beer_tap  # noqa: F401
from agricola.cards import bookshelf  # noqa: F401
from agricola.cards import cesspit  # noqa: F401
from agricola.cards import churchyard  # noqa: F401
from agricola.cards import civic_facade  # noqa: F401
from agricola.cards import clay_supports  # noqa: F401
from agricola.cards import cross_cut_wood  # noqa: F401
from agricola.cards import dwelling_plan  # noqa: F401
from agricola.cards import education_bonus  # noqa: F401
from agricola.cards import field_clay  # noqa: F401
from agricola.cards import fodder_chamber  # noqa: F401
from agricola.cards import forest_well  # noqa: F401
from agricola.cards import game_trade  # noqa: F401
from agricola.cards import grain_sieve  # noqa: F401
from agricola.cards import gritter  # noqa: F401
from agricola.cards import horse_drawn_boat  # noqa: F401
from agricola.cards import hutch  # noqa: F401
from agricola.cards import lord_of_the_manor  # noqa: F401
from agricola.cards import luxurious_hostel  # noqa: F401
from agricola.cards import lynchet  # noqa: F401
from agricola.cards import milking_stool  # noqa: F401
from agricola.cards import new_market  # noqa: F401
from agricola.cards import petrified_wood  # noqa: F401
from agricola.cards import plowman  # noqa: F401
from agricola.cards import pulverizer_plow  # noqa: F401
from agricola.cards import reap_hook  # noqa: F401
from agricola.cards import reed_pond  # noqa: F401
from agricola.cards import roof_ladder  # noqa: F401
from agricola.cards import sculpture  # noqa: F401
from agricola.cards import sheep_well  # noqa: F401
from agricola.cards import small_basket  # noqa: F401
from agricola.cards import small_greenhouse  # noqa: F401
from agricola.cards import stable_manure  # noqa: F401
from agricola.cards import stablehand  # noqa: F401
from agricola.cards import storeroom  # noqa: F401
from agricola.cards import summer_house  # noqa: F401
from agricola.cards import supply_boat  # noqa: F401
from agricola.cards import trident  # noqa: F401
from agricola.cards import trout_pool  # noqa: F401
from agricola.cards import truffle_slicer  # noqa: F401
from agricola.cards import wholesale_market  # noqa: F401
from agricola.cards import wood_rake  # noqa: F401
from agricola.cards import wooden_whey_bucket  # noqa: F401
from agricola.cards import writing_desk  # noqa: F401

# "Plow up to 2 extra fields on Farmland/Cultivation" minors (multi-shot granted plow;
# per-use cap of 2 + lifetime tile pool / once-per-game). See POST_COMPACTION_DETOUR.md.
from agricola.cards import swing_plow  # noqa: F401
from agricola.cards import turnwrest_plow  # noqa: F401
from agricola.cards import wheel_plow  # noqa: F401
