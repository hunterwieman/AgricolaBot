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
# Field-phase harvest cards — Scythe Worker is an occupation (also an on-play
# +1 grain; now an AUTO take-modifier fold-in per ruling 11); the related minors
# are registered below on the harvest-window machinery (the legacy
# `harvest_field` seam was retired 2026-07-05 once its last card migrated).
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
# harvest-window machinery (the legacy `harvest_field` seam is retired).
from agricola.cards import loom                  # noqa: F401
from agricola.cards import butter_churn          # noqa: F401
from agricola.cards import three_field_rotation  # noqa: F401
# Category 7 — the preparation ladder's start_of_round window (ruling 54,
# 2026-07-14; agricola/cards/preparation.py). Auto-effects (Small-scale Farmer
# +1 wood at exactly 2 rooms; Scullery +1 food in a wooden house — a minor) fire
# mechanically in the walk; OPTIONAL triggers (Plow Driver pay-1-food-plow, Groom
# build-a-stable) surface as FireTrigger on the window's choice host; the
# MANDATORY-with-choice Childless (+1 food + grain/veg pick) gates the host's
# Proceed; Scholar is the collapsed play-variant trigger (play an occupation OR a
# minor at round start). Hosting is eligibility-driven — no ownership index.
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
from agricola.cards import farm_building  # noqa: F401
from agricola.cards import stew  # noqa: F401
from agricola.cards import garden_claw  # noqa: F401
from agricola.cards import studio  # noqa: F401
from agricola.cards import woodcraft  # noqa: F401
from agricola.cards import schnapps_distillery  # noqa: F401
from agricola.cards import beer_stein  # noqa: F401
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

# The harvest-window new-card wave (windows 1-7; HARVEST_WINDOWS_DESIGN.md §12,
# 2026-07-05). The wave's two defers landed the next day on user rulings:
# winnowing_fan (best-rate direct conversion in lieu of a hook-suppressed
# bake) and market_stall_c54 (its stable play cost via the derived-supply
# removal seam in cost_mods; deck-suffixed id — B8 owns the name slug).
from agricola.cards import autumn_mother  # noqa: F401
from agricola.cards import barley_mill  # noqa: F401
from agricola.cards import bed_in_the_grain_field  # noqa: F401
from agricola.cards import beer_table  # noqa: F401
from agricola.cards import haydryer  # noqa: F401
from agricola.cards import land_surveyor  # noqa: F401
from agricola.cards import market_stall_c54  # noqa: F401
from agricola.cards import pipe_smoker  # noqa: F401
from agricola.cards import raised_bed  # noqa: F401
from agricola.cards import recluse  # noqa: F401
from agricola.cards import straw_manure  # noqa: F401
from agricola.cards import transactor  # noqa: F401
from agricola.cards import winnowing_fan  # noqa: F401

# The harvest-skip cards (rulings 1 + 14; the skip registry in harvest_windows).
from agricola.cards import lunchtime_beer  # noqa: F401
from agricola.cards import layabout  # noqa: F401

# The FEED/BREED-stage batch (2026-07-05, autonomous): feeding income + the
# post-feeding windows + the second take-modifier + the bare-take card.
# Deferred with build plans on record: baker (needs a DECLINABLE granted
# bake), milking_place (needs the house-pet-capacity negation),
# shepherds_whistle (needs a ruling on "unfenced stable without an animal" —
# animals aren't location-tracked).
from agricola.cards import bumper_crop  # noqa: F401
from agricola.cards import cubbyhole  # noqa: F401
from agricola.cards import dentist  # noqa: F401
from agricola.cards import farm_store  # noqa: F401
from agricola.cards import scythe  # noqa: F401
from agricola.cards import social_benefits  # noqa: F401
from agricola.cards import town_hall  # noqa: F401

# The three former defers, landed on user rulings 15-17 (2026-07-05): Baker
# (wide-play decline variants), Milking Place (the house-pet negation),
# Shepherd's Whistle (the capacity-theoretic free-stable test).
from agricola.cards import baker  # noqa: F401
from agricola.cards import milking_place  # noqa: F401
from agricola.cards import shepherds_whistle  # noqa: F401
from agricola.cards import treegardener  # noqa: F401

# The breeding/occasion/replace/feeding wave (2026-07-05, rulings 20-21 + the
# flagged Grain Thief reading): the breed-frame triggers' first consumers,
# the breeding-outcome sow grants, the per-occasion optional reactions, the
# replace-kind take-modifier, and the feeding-requirement fold.
from agricola.cards import stone_importer  # noqa: F401
from agricola.cards import fodder_planter  # noqa: F401
from agricola.cards import slurry  # noqa: F401
from agricola.cards import grain_thief  # noqa: F401
from agricola.cards import potato_ridger  # noqa: F401
from agricola.cards import food_merchant  # noqa: F401
from agricola.cards import childs_toy  # noqa: F401

# The after-harvest/occasion wave, flight 1 (2026-07-06, rulings 18/22-26):
# the merged after-harvest window's buy/income cards, the pile-take occasion
# reactor, and the final-harvest clay buy.
from agricola.cards import value_assets  # noqa: F401
from agricola.cards import uncaring_parents  # noqa: F401
from agricola.cards import eternal_rye_cultivation  # noqa: F401
from agricola.cards import field_cultivator  # noqa: F401
from agricola.cards import earthenware_potter  # noqa: F401
# Flight 2 (2026-07-06): the minor wide-play seam's first consumer.
from agricola.cards import facades_carving  # noqa: F401
from agricola.cards import craft_brewery  # noqa: F401
from agricola.cards import feed_pellets  # noqa: F401
# Dolly's Mother (2026-07-06, user-planned): single-parent sheep breeding +
# the sheep-only card slot via the greedy strip.
from agricola.cards import dollys_mother  # noqa: F401
# Mineral Feeder (2026-07-06, ruling 29): the pastured-sheep arrangement test
# + the cook-to-qualify frontier at the start-of-round host.
from agricola.cards import mineral_feeder  # noqa: F401
# Beer Stall (2026-07-06, ruling 30): the per-conversions-taken frontier with
# the exchanges bundled into the options, on the conversion-variants seam.
from agricola.cards import beer_stall  # noqa: F401
# The card-fields wave (rulings 43-48, 2026-07-12): "this card is a field"
# cards on the shared card_fields machinery (registry + sow/take/scoring
# integration). The three plain fields, then the reactive ones.
from agricola.cards import beanfield  # noqa: F401
from agricola.cards import wood_field  # noqa: F401
from agricola.cards import rock_garden  # noqa: F401
from agricola.cards import cherry_orchard  # noqa: F401
from agricola.cards import artichoke_field  # noqa: F401
from agricola.cards import melon_patch  # noqa: F401
from agricola.cards import lettuce_patch  # noqa: F401
from agricola.cards import crop_rotation_field  # noqa: F401
from agricola.cards import patch_caregiver  # noqa: F401
# The converter cluster (rulings 34-39, 2026-07-12): pure converters reach the
# generalized raise frame (frontier_fire); the rider-output buys are free-span
# (register_free_span_trigger). Braid Maker E109 joined 2026-07-21 (ruling 74
# closed the play-minor major-build gap — register_minor_action_major_build).
from agricola.cards import stone_carver  # noqa: F401
from agricola.cards import basket_carrier  # noqa: F401
from agricola.cards import paintbrush  # noqa: F401
# The round-end ladder's card wave (rulings 49-51, 2026-07-12): the queued
# round-end/returning-home cards. Perennial Rye C84 + Lumber Virtuoso D129
# are DEFERRED FOR AMBIGUITY (CARD_DEFERRED_PLANS.md).
from agricola.cards import credit  # noqa: F401
from agricola.cards import sculpture_course  # noqa: F401
from agricola.cards import swimming_class  # noqa: F401
from agricola.cards import lifting_machine  # noqa: F401
from agricola.cards import silage  # noqa: F401
from agricola.cards import baking_course  # noqa: F401
# The livestock-provider batch (2026-07-13): Early Cattle (on-play 2 cattle via
# grant_animals), Pigswill (before_action_space boar on the Fencing space —
# user-ruled BEFORE, so the boar can't ride the pastures built that turn),
# Automatic Water Trough (wide play-variant buy, min_keep-filtered
# accommodation), Bartering Hut (repeatable PendingCardChoice purchase menu).
from agricola.cards import early_cattle  # noqa: F401
from agricola.cards import pigswill  # noqa: F401
from agricola.cards import automatic_water_trough  # noqa: F401
from agricola.cards import bartering_hut  # noqa: F401
# The goods-provider batch (2026-07-13): two new additive engine seams + 7 cards.
# Vegetable Slicer rides the new `upgrade_to_cooking_hearth` event (fired at the
# return-Fireplace branch of _execute_build_major). Canvas Sack is the first
# `cost_labels` card (labeled alternative cost -> the coupled reward reaches
# on_play while the cost stays cost-modifier-visible). Beating Rod / Hauberg use
# the play-minor variant seam (effect-priced surcharge). Bee Statue is a Day
# Laborer CardStore dispenser; Water Gully / Muddy Waters are deferred schedulers.
from agricola.cards import vegetable_slicer  # noqa: F401
from agricola.cards import canvas_sack  # noqa: F401
from agricola.cards import beating_rod  # noqa: F401
from agricola.cards import hauberg  # noqa: F401
from agricola.cards import bee_statue  # noqa: F401
from agricola.cards import water_gully  # noqa: F401
from agricola.cards import muddy_waters  # noqa: F401
# The Ephipparius (deck E) batch (2026-07-13), wave 1 — the clean-fit cards: pure
# scoring / prereq (Heirloom E29 = 2 VP if your person is on Day Laborer; Nave E32 =
# 1/column with a room; Land Register E34 = 2 if no unused space; Misanthropy E35 =
# 2/3/5 for exactly 4/3/2 people), the Fishing wood-banker Rod Collection E38 (a
# play-variant "place up to 2 wood" trigger + a 1/4/7/10-excluded scoring formula), and
# Upholstery E31 (reed->point banked per later improvement, hooking BOTH after_play_minor
# and after_build_major with a same-turn self-exclusion latch in used_this_turn).
from agricola.cards import heirloom  # noqa: F401
from agricola.cards import nave  # noqa: F401
from agricola.cards import land_register  # noqa: F401
from agricola.cards import misanthropy  # noqa: F401
from agricola.cards import rod_collection  # noqa: F401
from agricola.cards import upholstery  # noqa: F401
# Wave 2 — the "empty-pasture" capacity restriction (new additive seam
# capacity_mods.register_empty_pasture, folded into extract_slots, no-op in Family):
# Herbal Garden E36 (any pasture must be empty) and Beaver Colony E33 (a pasture-WITH-
# stable must be empty; the two share one empty pasture when both are owned, and Beaver
# is vacuous with no stabled pasture). Beaver also banks +1 point per Reed Bank use.
from agricola.cards import herbal_garden  # noqa: F401
from agricola.cards import beaver_colony  # noqa: F401
# Wave 3 — the decision-BOUNDARY one-shot sweep (new seam
# triggers.register_boundary_one_shot + engine._fire_boundary_one_shots, run after the
# accommodation barrier at each boundary; Family no-op). Hook Knife B35: once per game,
# reaching 8 HOUSED sheep (2p) banks 2 points — the accommodation guard keeps a transient
# over-capacity grant from triggering it.
from agricola.cards import hook_knife  # noqa: F401
# Wave 4 — the minimal before-scoring decision window (new seam
# triggers.register_before_scoring + engine._push_before_scoring_choice at the
# BEFORE_SCORING boundary, reusing PendingCardChoice; Family no-op). Ox Skull E37: on-play
# +1 food, +3 at scoring with no cattle, and a keep/discard offer at exactly 1 cattle.
from agricola.cards import ox_skull  # noqa: F401
# Wave 5 — the animal-cook reaction seam (new triggers.register_animal_cook_reaction +
# resolution.note_animal_cook at the two work-phase cook sites; Family no-op). Cookery
# Lesson B29: 1 point per Lessons-placement turn on which you also cook an animal via a
# cooking improvement — granted AT the cook (paying the occupation cost, an on-play-grant
# overflow, or an explicit cook offered on the Lessons after-phase), never off a count-diff.
from agricola.cards import cookery_lesson  # noqa: F401
# The 2026-07-14 Points Provider batch — six bonus-point occupations, built on the
# new preparation ladder (ruling 54; agricola/cards/preparation.py) and three small
# additive seams:
#   Curator A100        — returning_home window trigger: >=3 people returning from
#                         accumulation spaces -> buy 1 point for 1 food (banked).
#                         Reads the new player-count/mode-aware category accessor
#                         helpers.accumulation_spaces (Wood Pile / Hand Truck /
#                         Steam Machine migrated onto it).
#   Clutterer B100      — counts the owner's qualifying plays AT PLAY TIME via the
#                         new `played_card_id` stamp on the two play-host frames
#                         (a scoring-time diff would miss the traveling Wood Pile).
#   Sugar Baker D101    — after grain_utilization: buy 1 point for 1 food; the food
#                         is owed to the space's next visitor (CardStore debt + an
#                         any_player before_action_space grant — the Milk Jug shape).
#   Prodigy E98         — 1st-occupation-only on-play bank: 1 point per improvement
#                         held at that instant (majors + minors, frozen at play).
#   Museum Caretaker E100 — start_of_work window: six-goods check as a LAST-ordered
#                         auto (the new register_auto order=) PLUS a same-window
#                         trigger for goods granted by other triggers (Cob);
#                         max 1/round via used_this_round.
#   Blighter E101       — banks 1 point per complete stage left at play; registers
#                         the new occupation-play blocker consulted at the
#                         playable_occupations chokepoint ("no more occupations").
from agricola.cards import curator           # noqa: F401
from agricola.cards import clutterer         # noqa: F401
from agricola.cards import sugar_baker       # noqa: F401
from agricola.cards import prodigy           # noqa: F401
from agricola.cards import museum_caretaker  # noqa: F401
from agricola.cards import blighter          # noqa: F401

# --- The 2026-07-14 agreed batch (waves; rulings recorded in CARD_DEFERRED_PLANS.md) ---
#   Cultivator D104     — after_plow auto: +1 wood +1 food per new field tile (any
#                         source; per-tile under multi-shot grants — the barrow_pusher
#                         twin, both fixed 2026-07-14 to read num_plowed).
#   Sculptor D105       — before-autos: clay accumulation (+1 food), stone
#                         accumulation (+1 grain); hooks clay_pit + both quarries.
#   Hill Cultivator E121 — before-autos on Grain/Vegetable Seeds: +2/+3 clay.
#   Kindling Gatherer E118 — before-autos on day_laborer + fishing: +1 wood when
#                         getting food from a space (card-provided food excluded
#                         per the 2026-07-14 ruling; Sugar Baker interaction below).
#   Fish Farmer D110    — before-autos on reed_bank/clay_pit/forest: +2 food when
#                         Fishing holds exactly 1 / exactly 2 / 3+ food (ruling:
#                         use-bonus reading; errata text Grove->Forest applied).
#   Forest Trader D125  — before variant trigger on forest/clay_pit: buy exactly 1
#                         building resource (wood/clay/reed 1 food, stone 2).
#   Sowing Master D109  — on-play +1 wood; after_action_space auto on the two
#                         sow-bearing spaces (+2 food, sow not required — ruled).
#   Fir Cutter E116     — on-play +1 food; after-market auto: wood by the Nth-person
#                         ordinal (1/1/2/2/3).
#   Little Stick Knitter B92 — round>=5 before-trigger on Sheep Market: optional
#                         room-only family growth (no space, place_on_space=False).
#   Seed Servant E115   — after Grain/Vegetable Seeds: optional granted Bake/Sow.
#   Young Farmer D112   — Major Improvement space: +1 grain before-auto + optional
#                         afterward Sow trigger.
#   Godmother E113      — before_family_growth auto +1 veg (+ the atomic Urgent
#                         Wish path via its own hook).
#   Interior Decorator D111 — before_renovate auto: 1 food on the next 6 round spaces.
#   Renovation Preparer D123 — after_build_rooms auto: 2 clay per wood room / 2 stone
#                         per clay room built this action.
#   Blackberry Farmer E108 — build-fences snapshot pair: 1 food on the next
#                         min(fences built, remaining) round spaces.
#   Spice Trader E104   — played round<=4: 3 veg scheduled to round 11.
#   Land Heir E119      — played round<=4: 4 wood + 4 clay scheduled to round 9.
#   Scrap Collector E120 — wood/clay alternating on the next 6 round spaces.
#   Beneficiary E97     — 3rd-occupation on-play grant: occupation (1 food) and/or
#                         minor, DEEP via the multi-category PendingGrantedSubAction.
from agricola.cards import cultivator          # noqa: F401
from agricola.cards import sculptor            # noqa: F401
from agricola.cards import hill_cultivator     # noqa: F401
from agricola.cards import kindling_gatherer   # noqa: F401
from agricola.cards import fish_farmer         # noqa: F401
from agricola.cards import forest_trader       # noqa: F401
from agricola.cards import sowing_master       # noqa: F401
from agricola.cards import fir_cutter          # noqa: F401
from agricola.cards import little_stick_knitter  # noqa: F401
from agricola.cards import seed_servant        # noqa: F401
from agricola.cards import young_farmer        # noqa: F401
from agricola.cards import godmother           # noqa: F401
from agricola.cards import interior_decorator  # noqa: F401
from agricola.cards import renovation_preparer  # noqa: F401
from agricola.cards import blackberry_farmer   # noqa: F401
from agricola.cards import spice_trader        # noqa: F401
from agricola.cards import land_heir           # noqa: F401
from agricola.cards import scrap_collector     # noqa: F401
from agricola.cards import beneficiary         # noqa: F401
#   Informant B117      — on-play +1 wood; after_work round-end auto: +1 wood when
#                         stone > clay.
#   Stallwright E89     — after 2nd/3rd/5th/7th occupation: optional free stable.
#   Emergency Seller E106 — on-play wide conversion: up to people_total building
#                         resources at 2 food (wood/clay) / 3 food (reed/stone).
#   Shed Builder E114   — after_build_stables auto: grain for lifetime stables 1-2,
#                         veg for 3-4 (per action, no retro-pay).
#   Bellfounder D107    — returning_home trigger: discard ALL clay for 3 food or
#                         1 banked point (wide; also in display.HISTORY_VP_CARDS).
#   Tax Collector E126  — stone-house start_of_round mandatory-with-choice:
#                         2 wood / 2 clay / 1 reed / 1 stone.
#   Green Grocer C103   — start_of_round wide variants: exactly one of the six
#                         printed exchanges (gains via grant_animals).
from agricola.cards import informant           # noqa: F401
from agricola.cards import stallwright         # noqa: F401
from agricola.cards import emergency_seller    # noqa: F401
from agricola.cards import shed_builder        # noqa: F401
from agricola.cards import bellfounder         # noqa: F401
from agricola.cards import tax_collector       # noqa: F401
from agricola.cards import green_grocer        # noqa: F401
#   Bonehead D118       — 6 wood on the card; 1 wood per own hand-card play
#                         (self-play paid inside on_play, ruling-60-aware guard).
from agricola.cards import bonehead            # noqa: F401
#   Merchant C96        — after the improvement ACTION (space or House Redev step):
#                         pay 1 food to take it a second time (no self-chain).
from agricola.cards import merchant            # noqa: F401
#   Seed Researcher C97 — returning_home: both seed spaces occupied by ANY people
#                         -> +2 food auto + optional free occupation play.
from agricola.cards import seed_researcher     # noqa: F401
#   Master Renovator E87 — end_of_work trigger, rounds 7/9: a personless renovate
#                         paying 1 building resource of choice less (the
#                         granted_by-scoped renovate conversion, seam 700d16a).
from agricola.cards import master_renovator    # noqa: F401
#   Field Doctor E92    — once per game, 2-room house surrounded (orth+diag) by
#                         4 field tiles: a Wish-space growth even without room
#                         (the growth room-gate override registry).
from agricola.cards import field_doctor        # noqa: F401
#   Clay Deliveryman D120 — 1 clay on each remaining round space in 6..14
#                         (the Well/Wood Collector band-schedule shape).
from agricola.cards import clay_deliveryman    # noqa: F401
# --- The 2026-07-15 follow-up batch (rulings 63+; revealed_round landed 9d5558c) ---
#   Moral Crusader B106 — before_round auto: +1 food when the entering round's
#                         slot holds goods promised to you (resources/animals).
#   Shoreforester B116  — on-play +1 wood; replenishment auto: +1 wood when the
#                         Reed Bank refill landed on an empty bank (reed == 1).
from agricola.cards import moral_crusader      # noqa: F401
from agricola.cards import shoreforester       # noqa: F401
#   Angler A95          — after Fishing used at <=2 pre-take food: an optional
#                         granted Major/Minor Improvement action (Merchant's
#                         composite-push idiom + a pre-take CardStore snapshot).
from agricola.cards import angler              # noqa: F401
#   Furniture Maker C116 — on-play +1 wood; +1 wood per food paid as occupation
#                         cost on later plays (played_card_id self-exclusion;
#                         OPEN user question: Forest School's substituted food).
from agricola.cards import furniture_maker     # noqa: F401
#   Task Artisan A96    — reveal-window wood + optional minor play when a quarry
#                         appears (revealed_round == the entering round); on-play
#                         wood + optional minor via the granted wrapper.
from agricola.cards import task_artisan        # noqa: F401
#   Sample Stable Maker D102 — start_of_returning_home variants: return a built
#                         stable (per cell) for wood+grain+food + an optional
#                         minor (accommodation flag set; pasture cache recomputed).
from agricola.cards import sample_stable_maker  # noqa: F401
#   Master Fencer E88   — stone-house start_of_round variants: pay 2/3 wood for
#                         up to 3/4 free fences (FenceRestrictions.max_edges).
from agricola.cards import master_fencer       # noqa: F401
#   Cottar E122         — mandatory wood-or-clay choice at each improvement's
#                         after window (ruling: the online implementation's
#                         instant; the two hosts gained the mandatory Stop gate).
from agricola.cards import cottar              # noqa: F401
#   Tinsmith Master B115 — +1 animal capacity per stable-less pasture (the
#                         per-pasture capacity seam); +1 crop per sown field,
#                         declinable per field (CommitSow boost counts + the
#                         SOW_BOOST_CARDS enumeration seam).
from agricola.cards import tinsmith_master     # noqa: F401

# --- 2026-07-15 food-provider batch (20 minor improvements) ---
#   Schedule food onto future round spaces (Pond Hut shape): Chicken Coop C44
#   (next 8), Barn Cats E43 (next stables+1), Fodder Beets E44 (remaining odd),
#   Fruit Ladder E45 (remaining even), Waterlily Pond E46 (next 2).
from agricola.cards import chicken_coop        # noqa: F401
from agricola.cards import barn_cats           # noqa: F401
from agricola.cards import fodder_beets        # noqa: F401
from agricola.cards import fruit_ladder        # noqa: F401
from agricola.cards import waterlily_pond      # noqa: F401
#   Traveling on-play food: Pumpernickel E7 (1 grain -> 4 food), Wage B7
#   (+2 food, +1 per owned bottom-row major).
from agricola.cards import pumpernickel        # noqa: F401
from agricola.cards import wage                # noqa: F401
#   "Each time you use [space]" income autos (atomic-space hooks): Comb and
#   Cutter E59 (Day Laborer + sheep on Sheep Market, cap 4), Stone Weir E55
#   (Fishing: +max(0, 4 - food on the space)).
from agricola.cards import comb_and_cutter     # noqa: F401
from agricola.cards import stone_weir          # noqa: F401
#   Food held on the card (CardStore): Forest Stone B48 (wood-space -> draw 1,
#   stone-space -> deposit 2), Whale Oil E51 (Fishing deposits; pays out before
#   each occupation play, non-consuming), Roman Pot E56 (drips 1 to the last
#   player each work phase).
from agricola.cards import forest_stone        # noqa: F401
from agricola.cards import whale_oil           # noqa: F401
from agricola.cards import roman_pot           # noqa: F401
#   Phase / reactive autos: Rolling Pin D52 (returning-home +1 food when
#   clay > wood), Twibil E49 (any-player, after a wood-room build -> +1 food),
#   Wild Greens E50 (+1 food per distinct good sown; card-field goods count,
#   user ruling 2026-07-15).
from agricola.cards import rolling_pin         # noqa: F401
from agricola.cards import twibil              # noqa: F401
from agricola.cards import wild_greens         # noqa: F401
#   Baking-improvement ovens (baking spec + reachability + an optional free bake
#   on build via the PendingGrantedSubAction("bake_bread") wrapper): Iron Oven
#   E63 (1 grain -> 6 food), Simple Oven E64 (1 grain -> 3 food).
from agricola.cards import iron_oven           # noqa: F401
from agricola.cards import simple_oven         # noqa: F401
#   Syrup Tap E47 — schedule 1 food when an action space itself supplies wood
#                   (Kindling Gatherer detection; user ruling 2026-07-15).
from agricola.cards import syrup_tap           # noqa: F401
#   Foreign Aid D50 — on-play +6 food; forbids the owner the rounds-12-14
#                     spaces (the new PLACEMENT_FORBID_EXTENSIONS seam).
from agricola.cards import foreign_aid         # noqa: F401
#   Asparagus Knife A58 — returning-home rounds 8/10/12: take 1 veg from a veg
#                         field, optionally exchange for 3 food + 1 banked point.
from agricola.cards import asparagus_knife     # noqa: F401

# --- 2026-07-15 batch: 34 cards implementable on existing seams (no engine change) ---
#   Income autos keyed on revealed_round / accumulation reads, and an exchange trigger:
from agricola.cards import mattock             # noqa: F401
from agricola.cards import barn_shed           # noqa: F401
from agricola.cards import field_spade         # noqa: F401
from agricola.cards import stone_axe           # noqa: F401
#   On-play goods / scoring / cost / capacity / occupancy:
from agricola.cards import farmers_market      # noqa: F401
from agricola.cards import recount             # noqa: F401
from agricola.cards import store_of_experience # noqa: F401
from agricola.cards import baseboards          # noqa: F401
from agricola.cards import almsbag             # noqa: F401
from agricola.cards import mayor_candidate     # noqa: F401
from agricola.cards import sheep_rug           # noqa: F401
from agricola.cards import lawn_fertilizer     # noqa: F401
from agricola.cards import wood_slide_hammer   # noqa: F401
#   Schedules / after-bake / after-build-stables:
from agricola.cards import granary             # noqa: F401
from agricola.cards import grain_depot         # noqa: F401
from agricola.cards import stable_tree         # noqa: F401
from agricola.cards import farmyard_manure     # noqa: F401
from agricola.cards import bookmark            # noqa: F401
from agricola.cards import cheese_fondue       # noqa: F401
#   Round-end / harvest / growth windows:
from agricola.cards import ale_benches         # noqa: F401
from agricola.cards import carrot_museum       # noqa: F401
from agricola.cards import storks_nest         # noqa: F401
from agricola.cards import harvest_festival_planning  # noqa: F401
from agricola.cards import iron_hoe            # noqa: F401
from agricola.cards import apiary              # noqa: F401
from agricola.cards import sundial             # noqa: F401
#   Granted sub-actions / play-variants / before-round buy:
from agricola.cards import chief_forester      # noqa: F401
from agricola.cards import acquirer            # noqa: F401
from agricola.cards import upscale_lifestyle   # noqa: F401
from agricola.cards import new_purchase        # noqa: F401

# --- 2026-07-15 seam-fit batch, Tier 2: 55 more cards on existing seams (3+/4 occupations) ---
from agricola.cards import braggart  # noqa: F401
from agricola.cards import potato_digger  # noqa: F401
from agricola.cards import roof_examiner  # noqa: F401
from agricola.cards import usufructuary  # noqa: F401
from agricola.cards import pig_owner  # noqa: F401
from agricola.cards import pastor  # noqa: F401
from agricola.cards import estate_master  # noqa: F401
from agricola.cards import champion_breeder  # noqa: F401
from agricola.cards import wealthy_man  # noqa: F401
from agricola.cards import stonecutter  # noqa: F401
from agricola.cards import brushwood_collector  # noqa: F401
from agricola.cards import chimney_sweep  # noqa: F401
from agricola.cards import greengrocer  # noqa: F401
from agricola.cards import seed_seller  # noqa: F401
from agricola.cards import storehouse_steward  # noqa: F401
from agricola.cards import forest_clearer  # noqa: F401
from agricola.cards import porter  # noqa: F401
from agricola.cards import flax_farmer  # noqa: F401
from agricola.cards import loudmouth  # noqa: F401
from agricola.cards import tree_cutter  # noqa: F401
from agricola.cards import carter  # noqa: F401
from agricola.cards import chairman  # noqa: F401
from agricola.cards import german_heath_keeper  # noqa: F401
from agricola.cards import kelp_gatherer  # noqa: F401
from agricola.cards import material_deliveryman  # noqa: F401
from agricola.cards import animal_dealer  # noqa: F401
# Action/reward replacement pair (ACTION_REPLACEMENT_DESIGN.md — the reward-suppression seam)
from agricola.cards import pet_lover  # noqa: F401
from agricola.cards import animal_catcher  # noqa: F401
from agricola.cards import turnip_farmer  # noqa: F401
from agricola.cards import bohemian  # noqa: F401
from agricola.cards import resource_analyzer  # noqa: F401
from agricola.cards import animal_tamers_apprentice  # noqa: F401
from agricola.cards import harpooner  # noqa: F401
from agricola.cards import huntsman  # noqa: F401
from agricola.cards import cattle_feeder  # noqa: F401
from agricola.cards import night_school_student  # noqa: F401
from agricola.cards import food_distributor  # noqa: F401
from agricola.cards import pig_breeder  # noqa: F401
from agricola.cards import pub_owner  # noqa: F401
from agricola.cards import ropemaker  # noqa: F401
from agricola.cards import animal_driver  # noqa: F401
from agricola.cards import beer_tent_operator  # noqa: F401
from agricola.cards import mountain_plowman  # noqa: F401
from agricola.cards import sheep_whisperer  # noqa: F401
from agricola.cards import trap_builder  # noqa: F401
from agricola.cards import plumber  # noqa: F401
from agricola.cards import stable_sergeant  # noqa: F401
from agricola.cards import nutrition_expert  # noqa: F401
from agricola.cards import parvenu  # noqa: F401
from agricola.cards import livestock_expert  # noqa: F401
from agricola.cards import bunny_breeder  # noqa: F401
from agricola.cards import vegetable_vendor  # noqa: F401
from agricola.cards import imitator  # noqa: F401
from agricola.cards import field_caretaker  # noqa: F401

# --- 2026-07-15 ruling-resolved pair (Grain Bag baking-improvement count; Housemaster
#     major-VP total) ---
from agricola.cards import grain_bag  # noqa: F401
from agricola.cards import housemaster  # noqa: F401
from agricola.cards import homekeeper  # noqa: F401
from agricola.cards import bunk_beds  # noqa: F401
from agricola.cards import reader  # noqa: F401
from agricola.cards import lodger  # noqa: F401
from agricola.cards import wooden_shed  # noqa: F401

# --- 2026-07-17 tier-1 batch (11 minors on existing seams; rulings 66 + the batch
#     rulings in CARD_DEFERRED_PLANS.md) ---
from agricola.cards import heart_of_stone  # noqa: F401
from agricola.cards import seed_almanac  # noqa: F401
from agricola.cards import recycled_brick  # noqa: F401
from agricola.cards import nail_basket  # noqa: F401
from agricola.cards import profiteering  # noqa: F401
from agricola.cards import double_turn_plow  # noqa: F401
from agricola.cards import furrows  # noqa: F401
from agricola.cards import pole_barns  # noqa: F401
from agricola.cards import lumber_pile  # noqa: F401
from agricola.cards import thunderbolt  # noqa: F401
from agricola.cards import night_loot  # noqa: F401

# --- 2026-07-20 the play_occupation cost-conversion chokepoint (ruling 67) ---
from agricola.cards import working_gloves  # noqa: F401

# --- 2026-07-20 tier-2 batch, first wave (user rulings 2026-07-20: Ceilings per
#     deferred-plans cluster B5; Sleight of Hand wide one-shot, disjoint-support
#     exchanges; Material Hub scoped to accumulation-space sweeps, native-type only) ---
from agricola.cards import ceilings  # noqa: F401
from agricola.cards import sleight_of_hand  # noqa: F401
from agricola.cards import material_hub  # noqa: F401

# --- 2026-07-20 tier-2 batch, second wave (the granted-primitive parameter seams:
#     plow adjacency waiver, forced-crop sow, renovate cost_override/forced_target,
#     stable cell restriction — user rulings 2026-07-20) ---
from agricola.cards import newly_plowed_field  # noqa: F401
from agricola.cards import fern_seeds  # noqa: F401
from agricola.cards import renovation_materials  # noqa: F401
from agricola.cards import shelter  # noqa: F401
from agricola.cards import oven_site  # noqa: F401

# --- 2026-07-20 tier-2 batch, animal-holder pair (the two capacity folds:
#     register_animal_cap_slots / register_flexible_slots; Petting Zoo ruled
#     mixed-type 2026-07-20) ---
from agricola.cards import stockyard  # noqa: F401
from agricola.cards import petting_zoo  # noqa: F401

# --- 2026-07-20 tier-3 batch (ruling 69; user rulings 2026-07-20: A21 pre-action
#     rooms>people measure + unconditional food, B17 after-the-take override,
#     C73 "unconditional Sow" definition, D80 printed-cost/any-alternative,
#     D1 the four zigzag templates, E3 the vacated space is open) ---
from agricola.cards import family_friendly_home  # noqa: F401
from agricola.cards import forest_plow  # noqa: F401
from agricola.cards import seaweed_fertilizer  # noqa: F401
from agricola.cards import brick_hammer  # noqa: F401
from agricola.cards import zigzag_harrow  # noqa: F401
from agricola.cards import tea_time  # noqa: F401

# --- 2026-07-20 approved-mechanism pair (ruling 70; user approval 2026-07-20 of
#     deferred-plans cluster C3 — take-from-accumulation-without-placement) ---
from agricola.cards import work_certificate  # noqa: F401
from agricola.cards import handcart  # noqa: F401
from agricola.cards import stone_clearing  # noqa: F401  (ruling 70 scope resolved: card-fields included)

# --- 2026-07-21 typed-slot batch (the per-species slot generalization of the
#     Dolly's-Mother strip — user ruling 2026-07-21; Mud Patch's unplanted
#     reading confirmed same day) ---
from agricola.cards import wildlife_reserve  # noqa: F401
from agricola.cards import cattle_farm  # noqa: F401
from agricola.cards import mud_patch  # noqa: F401
from agricola.cards import sheep_agent  # noqa: F401

# --- 2026-07-21 boundary-buster batch (user rulings 2026-07-21): the min-spend
#     payment filter (CostCtx.min_spend — Stone Company), the allowed_cards
#     play-menu restriction + take-max withdrawal (Firewood), the cooking-rate
#     bonus fold (cooking_mods.py — Fatstock Stretcher), and the free-renovate
#     play-variant (Renovation Company, un-deferred: its 2026-07-15 blocker was
#     the then-missing cost_override, since built for Renovation Materials) ---
from agricola.cards import stone_company  # noqa: F401
from agricola.cards import firewood  # noqa: F401
from agricola.cards import fatstock_stretcher  # noqa: F401
from agricola.cards import renovation_company  # noqa: F401

# --- 2026-07-21 completed-feeding-phases pair (the state-widened typed slots +
#     helpers.completed_feeding_phases; Woolgrower is [4] forward-compat) ---
from agricola.cards import truffle_searcher  # noqa: F401
from agricola.cards import woolgrower  # noqa: F401

# --- 2026-07-21 ruling-74 triage batch, Wave 1 (existing seams; per-card
#     rulings in CARD_DEFERRED_PLANS.md ruling 74) ---
from agricola.cards import bed_maker  # noqa: F401
from agricola.cards import site_manager  # noqa: F401
from agricola.cards import sheep_inspector  # noqa: F401
from agricola.cards import dung_collector  # noqa: F401
from agricola.cards import henpecked_husband  # noqa: F401

# --- 2026-07-21 ruling-74 triage batch, Wave 2 (the four new seams; per-card
#     rulings in CARD_DEFERRED_PLANS.md ruling 74) ---
from agricola.cards import livestock_feeder  # noqa: F401
from agricola.cards import stable_master  # noqa: F401
from agricola.cards import carpenters_apprentice  # noqa: F401
from agricola.cards import furnisher  # noqa: F401

# --- 2026-07-21 ruling-74 triage batch, Wave 3 ---
from agricola.cards import field_merchant  # noqa: F401
from agricola.cards import braid_maker  # noqa: F401
from agricola.cards import miller  # noqa: F401

# --- 2026-07-21 ruling-74 triage batch, Wave 4 (card-as-action-space) ---
from agricola.cards import collector  # noqa: F401
from agricola.cards import tree_inspector  # noqa: F401
# The craft majors' harvest-span windows (ruling 74's general pattern; Cards-only)
from agricola.cards import craft_major_span  # noqa: F401
from agricola.cards import canal_boatman  # noqa: F401
from agricola.cards import plow_builder  # noqa: F401
