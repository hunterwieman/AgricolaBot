"""TRIPWIRE — at most ONE space-enable extension per space (ruling 87, 2026-07-29).

The space-enable registry (`legality.SPACE_ENABLE_EXTENSIONS`) evaluates each
extension IN ISOLATION: an extension answers "could the player complete this
space's action via MY before-window effect?", simulating its own effect and
asking the shared capability predicates. Cross-LEVEL chains compose exactly
(a host-window buy feeding a frame-window route — Thresher × Drill Harrow —
because the evaluation nests the way the engine forces the play order), but
same-window SIBLINGS do not: two host-window enablers whose effects jointly
(and only jointly) enable a space would each answer False alone, and the gate
would wrongly refuse a rules-legal placement.

Today that case is vacuous — Thresher is the only registrant. If this test
fails, you registered a SECOND enabler for some space: STOP and inform the
user — the cooperative-sibling question opens (the recorded starting point is
a bounded search over the window's once-per-use fires; see ruling 87 in
CARD_DEFERRED_PLANS.md), and it must be settled before the second card ships.
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.legality import SPACE_ENABLE_EXTENSIONS


def test_at_most_one_enable_extension_per_space():
    for space_id, exts in SPACE_ENABLE_EXTENSIONS.items():
        assert len(exts) <= 1, (
            f"{space_id!r} has {len(exts)} enabling extensions — same-window "
            "sibling enablers are evaluated in isolation and cannot see joint "
            "routes; read this file's docstring before proceeding"
        )
