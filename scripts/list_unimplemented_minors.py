#!/usr/bin/env python
"""List the minor improvements that are NOT yet implemented and NOT decided against.

A card counts as *unimplemented* when its slug is absent from the live `MINORS` registry
(no card module has registered it), and *not decided against* when the catalog JSON does
not mark it `wontfix`. Everything else — including cards merely *deferred* pending a
rules/infrastructure decision — is listed, because deferred is not the same as rejected.

Because it reads the registry live at every run, the output always reflects the current
state of the catalog: implement a card, and it drops off this list automatically.

    python scripts/list_unimplemented_minors.py                 # grouped terminal list
    python scripts/list_unimplemented_minors.py --deck E        # only deck E
    python scripts/list_unimplemented_minors.py --category "Food Provider"
    python scripts/list_unimplemented_minors.py --count         # just the tallies
    python scripts/list_unimplemented_minors.py --markdown out.md
    python scripts/list_unimplemented_minors.py --html out.html # filterable web page

The occupations twin is scripts/list_unimplemented_occupations.py; both share the rendering
core in scripts/_unimplemented_cards.py.
"""
from __future__ import annotations

from _unimplemented_cards import run

if __name__ == "__main__":
    run(
        json_filename="revised_minor_improvements.json",
        registry_name="MINORS",
        noun="Minor Improvements",
    )
