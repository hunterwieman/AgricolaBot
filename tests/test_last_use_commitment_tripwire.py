"""TRIPWIRE — the last-use-commitment contract for unbuilt cards (2026-07-27).

`PlayerState.last_use_committed` (set by Steam Machine's fire) records that a
player has committed a use as the work phase's LAST — implicitly declining every
optional future placement/use for the round (the user's ruled Telegram-arc
principle). Current parties: Steam Machine sets and reads it; the turn-offer
chokepoint (`turn_offers.pending_turn_start_offer`), Straw Hat's relocation
variants, and Sheep Inspector's return consult it.

Three unbuilt cards must join the seam ON IMPLEMENTATION. Each test below fails
the moment the card registers, pointing its implementer here — the executable
form of the ledger's ⚠ ON BUILD notes (the Large Pottery pattern,
`tests/test_liquidation_disjointness.py`).

- **MARKET MASTER E131** (occupation, 3+): "Immediately after each time you
  place your last person in a round on the 'Traveling Players' accumulation
  space, you can play 1 occupation for an occupation cost of 1 food." (Errata:
  Resource Market in 3-player games.) The catalog's only other
  own-last-placement instant: its FIRE must SET `last_use_committed` with Steam
  Machine's exact semantics. AND the same-window sibling rule: Traveling
  Players IS an accumulation space, so Market Master and Steam Machine can both
  legitimately fire in the SAME after-window — both conditions ride the same
  last placement, and nothing makes them exclusive. A blind
  `not last_use_committed` eligibility read would wrongly block whichever fires
  second, so at that point Steam Machine's read (and Market Master's, if any)
  must be scoped to commitments from a DIFFERENT window — e.g. block only when
  the latch is set AND no latch-setting card is in this frame's
  `triggers_resolved`. Sheep Inspector's foreclosure consult is unaffected (a
  return contradicts the commitment whichever sibling made it).

- **ADOPTIVE PARENTS A92** (occupation, 1+): "For 1 food, you can take an
  action with offspring in the same round you get it." A payable newborn
  activation is an optional future placement living OUTSIDE `people_home`, so
  whatever seam offers the pay-and-activate must CONSULT the latch (foreclosed
  once a last use is committed), exactly like the loaner offers.

- **ARCHWAY D51** (minor): its relocation sits on the `after_work` rung;
  whether that use counts for "the last action space you use" is an OPEN user
  question (CARD_DEFERRED_PLANS.md, 2026-07-27) that must be resolved before
  the build. If ruled in scope, its use-branch consults the latch like Straw
  Hat's; if ruled out, it neither consults nor falsifies.

When a test fires: implement the contract (or obtain the ruling), then flip the
assert into positive coverage of it — do not just delete the test.
"""
import agricola.cards  # noqa: F401  -- populate the registries

from agricola.cards.specs import MINORS, OCCUPATIONS


def test_market_master_unbuilt_must_join_the_latch_seam_when_it_lands():
    assert "market_master" not in OCCUPATIONS, (
        "Market Master has registered: its fire must SET last_use_committed, "
        "and the same-window sibling rule now applies to Steam Machine's "
        "eligibility read — see this file's docstring")


def test_adoptive_parents_unbuilt_must_consult_the_latch_when_it_lands():
    assert "adoptive_parents" not in OCCUPATIONS, (
        "Adoptive Parents has registered: its newborn-activation offer must "
        "CONSULT last_use_committed — see this file's docstring")


def test_archway_unbuilt_needs_the_last_use_timing_ruling_first():
    assert "archway" not in MINORS, (
        "Archway has registered: resolve the open after_work-vs-work-phase "
        "question for 'the last action space you use' first — see this file's "
        "docstring and CARD_DEFERRED_PLANS.md")
