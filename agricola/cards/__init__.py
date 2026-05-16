"""Card package.

Importing this package imports each card module so their register() calls
run at module load time, populating agricola.cards.triggers.TRIGGERS and
agricola.cards.triggers.CARDS, as well as predicate-extension registries
in agricola.legality (e.g., BAKE_BREAD_ELIGIBILITY_EXTENSIONS).

Future card modules are added to this file as they're implemented.
"""
from agricola.cards import potter_ceramics   # noqa: F401
