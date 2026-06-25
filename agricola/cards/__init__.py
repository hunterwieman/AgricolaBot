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

# Minor improvements (card game). Importing each registers its MinorSpec in
# agricola.cards.specs.MINORS at package load. See CARD_IMPLEMENTATION_PLAN.md II.4.
from agricola.cards import market_stall         # noqa: F401
# Category 3 automatic-income minors.
from agricola.cards import corn_scoop           # noqa: F401
from agricola.cards import stone_tongs          # noqa: F401
from agricola.cards import pitchfork            # noqa: F401
from agricola.cards import basket               # noqa: F401
# Category 1 (end-game scoring terms — pure derived reads).
from agricola.cards import manger               # noqa: F401
from agricola.cards import wool_blankets        # noqa: F401
# Category 2 (on-play one-shot gains; both traveling/passing).
from agricola.cards import clay_embankment      # noqa: F401
from agricola.cards import young_animal_market  # noqa: F401
