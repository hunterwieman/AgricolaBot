"""Root conftest: keep pytest from collecting non-test trees.

`archive/` holds retired scripts + DEFERRED card modules and their tests (a deferred
card's test imports a module that is intentionally not under `agricola/cards/`, so
collecting it would error). Excluding the whole dir keeps the suite clean and lets
"archive, don't delete" coexist with a green `pytest tests/` / `pytest` run.
"""
collect_ignore = ["archive"]
