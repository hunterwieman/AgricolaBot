"""Rules-fidelity lint over the card modules (CARD_AUTHORING_GUIDE.md §0.1).

The enforcement layer for the project's cardinal card rule: a card is implemented
exactly as printed or it is deferred — an implementing session has no authority to
shift a timing or narrow a mechanism, and a docstring may not ratify its own
deviation. The 2026-07-02 audit found that every rules deviation that reached the
codebase entered through exactly that vector: a docstring calling its deviation
"the established, accepted approximation" (or similar), which later sessions then
cited as precedent.

This test makes that vector mechanically impossible to reintroduce silently:

- Any card module whose text contains a SELF-RATIFICATION phrase must also carry a
  dated user-ruling attribution (``user ruling YYYY-MM-DD`` / ``owner ruling
  YYYY-MM-DD``). A deviation the user has ruled on is legitimate and citable; an
  unattributed deviation claim fails the suite — in the implementing agent's own
  test run, before it ever reaches review.

- The ALLOWLIST below names the modules with a known, user-acknowledged pending
  deviation. Each entry must cite why it is allowed and should be REMOVED when the
  card is re-deferred or re-timed — the allowlist is visible debt, not amnesty.

Scope: every non-framework module under agricola/cards/ that is on disk (wired or
not — an unwired module is a wiring away from live). Framework modules are
excluded; they legitimately discuss approximations in the abstract.
"""
from __future__ import annotations

import re
from pathlib import Path

CARDS_DIR = Path(__file__).resolve().parent.parent / "agricola" / "cards"

# Framework / registry modules — not card implementations.
FRAMEWORK = {
    "__init__.py", "specs.py", "triggers.py", "cost_mods.py", "capacity_mods.py",
    "schedules.py", "harvest_conversions.py", "display.py",
}

# Phrases by which a docstring ratifies its own deviation from the printed card
# text. Case-insensitive. Keep this list tight — it targets self-RATIFICATION
# language, not honest discussion (a module explaining why its reading is exactly
# faithful trips none of these).
SELF_RATIFICATION = [
    r"accepted approximation",
    r"established approximation",
    r"established,\s*accepted",
    r"behaviou?rally neutral",
    r"accepted home",
    r"accepted seam",
    r"accepted engine boundary",
    r"harmless (approximation|deviation|shift)",
    r"should be fine",
]
_BANNED = re.compile("|".join(f"(?:{p})" for p in SELF_RATIFICATION), re.IGNORECASE)

# A dated ruling attribution legitimizes a deviation claim.
_ATTRIBUTION = re.compile(r"(user|owner) ruling[,:]? \(?\d{4}-\d{2}-\d{2}", re.IGNORECASE)

# Modules with a known, user-acknowledged PENDING deviation. Remove an entry when
# its card is re-deferred or re-timed; never add one without a user decision.
ALLOWLIST: dict[str, str] = {
    # The harvest FEED-seam timing cluster, surfaced to the user 2026-07-02;
    # disposition (re-defer vs re-time onto the round-end/after-feeding hooks)
    # is the user's pending call. See CARD_ENGINE_IMPLEMENTATION.md §6.
    "cube_cutter.py": "FEED-seam pending user decision 2026-07-02",
    "winter_caretaker.py": "FEED-seam pending user decision 2026-07-02",
    "elephantgrass_plant.py": "FEED-seam pending user decision 2026-07-02",
}


def test_no_self_ratified_deviations():
    offenders = []
    for path in sorted(CARDS_DIR.glob("*.py")):
        if path.name in FRAMEWORK or path.name in ALLOWLIST:
            continue
        text = path.read_text(errors="replace")
        hit = _BANNED.search(text)
        if hit and not _ATTRIBUTION.search(text):
            offenders.append(f"{path.name}: {hit.group(0)!r}")
    assert not offenders, (
        "Card module(s) contain a self-ratified deviation claim with no dated user-"
        "ruling attribution (CARD_AUTHORING_GUIDE.md §0.1: a deviation you can "
        "justify is still a defer — implement the printed text exactly, or defer "
        "and ask the user):\n  " + "\n  ".join(offenders)
    )


def test_allowlist_entries_still_exist():
    """An allowlist entry for a deleted/renamed module is stale — prune it."""
    stale = [name for name in ALLOWLIST if not (CARDS_DIR / name).exists()]
    assert not stale, f"ALLOWLIST names missing modules (prune them): {stale}"
