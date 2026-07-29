"""TRIPWIRE — the improvement before-windows carry no automatic effects.

Wood Workshop B75 ("Each time before you play or build an improvement, you get
1 wood") was the sole auto ever registered on ``before_build_major`` /
``before_play_minor``. It is BANNED (official ban list — external knowledge,
not recorded in the repo's card data; user ruling 2026-07-29, ruling 87) and
archived, leaving both windows auto-free — and the affordability gates depend
on exactly that: ``_can_afford_any_major_improvement`` and ``playable_minors``
evaluate on the CURRENT state, while a before-window auto lands its goods only
at the sub-action leaf's push, AFTER every placement/choose gate has answered.
An income auto here therefore makes the gates too strict at the affordability
boundary — a rules-legal placement refused, which is never acceptable
(CARD_AUTHORING_GUIDE.md §0.4).

If this test fails, you registered an auto on one of these windows:

- If it grants goods (income): STOP and inform the user — the gates must first
  learn to anticipate the grant (the doctored-state probe of ruling 87, the
  Thresher/Drill Harrow seams' sibling for mandatory effects) before such a
  card can be legal to implement.
- If it is pure bookkeeping (no resource change): update this test's
  expectation consciously, stating here why the gates are unaffected.

(Optional TRIGGERS on these windows are fine and exist — Firewood, the
Braid Maker / Plow Builder swaps; a player choice can't be presumed by a gate,
and their enabling potential is a separate, per-card question.)
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.cards.triggers import AUTO_EFFECTS


def test_improvement_before_windows_have_no_autos():
    for event in ("before_build_major", "before_play_minor"):
        assert not AUTO_EFFECTS.get(event, []), (
            f"an automatic effect is registered on {event!r} — before-window "
            "income changes affordability AFTER the gates have answered; read "
            "this file's docstring before proceeding"
        )
