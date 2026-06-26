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
# Category 3 (action-space hook) on the dedicated end_of_turn event — Firewood
# Collector ("+1 wood at the END of the turn that used Farmland / Grain Seeds /
# Grain Utilization / Cultivation"). The end_of_turn event fires at the turn's
# completion boundary (engine._apply_stop), so this is now un-deferred (Unit 4).
from agricola.cards import firewood_collector   # noqa: F401
# Category 3/4 on non-atomic spaces' after-phase (the multi-sub after-trigger model).
from agricola.cards import threshing_board      # noqa: F401
# Category 5 (build / renovate / bake / play-card hooks). Roughcaster is an
# occupation; the other four are minors registered below. The coarse
# `after_build_improvement` event (Junk Room) is fired by _execute_build_major
# and _execute_play_minor; `after_build_rooms` (Roughcaster's clay-room clause) is
# fired by _apply_stop at the build-rooms session end.
from agricola.cards import roughcaster          # noqa: F401

# Minor improvements (card game). Importing each registers its MinorSpec in
# agricola.cards.specs.MINORS at package load. See CARD_IMPLEMENTATION_PLAN.md II.4.
from agricola.cards import market_stall         # noqa: F401
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
