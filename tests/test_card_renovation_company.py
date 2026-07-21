"""Tests for Renovation Company (minor improvement, A13) — +3 clay on play, then
an optional free renovate resolved within the play.

Card text: "When you play this card, you immediately get 3 clay. Immediately
after, you can renovate without paying any building resources."
Cost 4 Wood; prereq "In Wooden House with Exactly 2 Rooms"; no VPs; kept (not
traveling). Clarification: "The renovation can be declined, but the free cost
cannot be applied later."

Surfaced WIDE via the minor play-variant seam (user rulings 2026-07-21): one
CommitPlayMinor per route — "renovate" (play + the free renovate, pushed as a
`PendingRenovate` with `cost_override=Resources()` and NO forced_target, so the
target menu is the normal `_legal_renovate_targets` and Conservator's
wood→stone is free too) and "decline" (play, forfeit the renovate forever).

The tests push `PendingPlayMinor` directly (the established factory pattern,
mirroring test_card_renovation_materials.py) with the card in hand, then drive
play → renovate/decline → Stop.
"""
import agricola.cards.renovation_company  # noqa: F401

from agricola.actions import CommitPlayMinor, CommitRenovate, Stop
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_pending_stack

CARD_ID = "renovation_company"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _n_rooms(p) -> int:
    return sum(1 for row in p.farmyard.grid for cell in row
               if cell.cell_type == CellType.ROOM)


def _card_state(seed=5, *, res=None, house=None, occupations=None, minors=None):
    """A 2-player card-mode state with `renovation_company` in the active player's
    hand and the given fields overridden; opponent hand cleared. Default setup
    geometry: a 2-room wooden house — the card's prereq holds by default."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    changes = {"hand_minors": frozenset({CARD_ID})}
    if res is not None:
        changes["resources"] = res
    if house is not None:
        changes["house_material"] = house
    if occupations is not None:
        changes["occupations"] = frozenset(occupations)
    if minors is not None:
        changes["minor_improvements"] = frozenset(minors)
    p = fast_replace(cs.players[cp], **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


def _variants_offered(cs):
    return sorted(a.variant for a in legal_actions(cs)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)


def _commit(cs, variant):
    return next(a for a in legal_actions(cs)
                if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                and a.variant == variant)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=4))
    assert spec.passing_left is False           # kept in the tableau, not traveling
    assert spec.vps == 0
    assert spec.prereq is not None              # "In Wooden House with Exactly 2 Rooms"
    assert CARD_ID in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# Prerequisite — wooden house AND exactly 2 rooms
# ---------------------------------------------------------------------------

def test_prereq_house_material():
    spec = MINORS[CARD_ID]
    for house, expected in (
        (HouseMaterial.WOOD, True),
        (HouseMaterial.CLAY, False),
        (HouseMaterial.STONE, False),
    ):
        cs, cp = _card_state(house=house, res=Resources(wood=4))
        assert _n_rooms(cs.players[cp]) == 2
        assert prereq_met(spec, cs, cp) is expected


def test_not_playable_on_clay_house():
    # Affordable, but a clay house fails the prereq → the card is not offered.
    cs, cp = _card_state(house=HouseMaterial.CLAY, res=Resources(wood=4))
    assert CARD_ID not in playable_minors(cs, cp)


def test_not_playable_with_three_rooms():
    # A third ROOM cell (still wooden) breaks the "exactly 2 rooms" prereq.
    cs, cp = _card_state(res=Resources(wood=4))
    cs = with_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.ROOM)})
    assert _n_rooms(cs.players[cp]) == 3
    assert prereq_met(MINORS[CARD_ID], cs, cp) is False
    assert CARD_ID not in playable_minors(cs, cp)


def test_playable_in_two_room_wooden_house():
    cs, cp = _card_state(res=Resources(wood=4))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    assert _n_rooms(cs.players[cp]) == 2
    assert CARD_ID in playable_minors(cs, cp)


# ---------------------------------------------------------------------------
# The wide variants — both routes offered, zero surcharge (same play cost)
# ---------------------------------------------------------------------------

def test_both_variants_offered():
    cs, cp = _card_state(res=Resources(wood=4))
    cs = _push_minor(cs, cp)
    assert _variants_offered(cs) == ["decline", "renovate"]
    # Zero surcharge on both: each commit's payment is exactly the 4-wood card cost.
    for a in legal_actions(cs):
        if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID:
            assert a.payment == Resources(wood=4)


# ---------------------------------------------------------------------------
# Full flow, renovate variant — +3 clay, then a free wood→clay renovate
# ---------------------------------------------------------------------------

def test_renovate_variant_free_wood_to_clay():
    # Exactly 4 wood, NO clay and NO reed: a normal 2-room wood→clay renovate
    # costs 2 clay + 1 reed, so the upgrade below is possible only because the
    # granted renovate is free ("without paying any building resources").
    cs, cp = _card_state(res=Resources(wood=4))
    rooms0 = _n_rooms(cs.players[cp])
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "renovate"))

    p = cs.players[cp]
    assert p.resources.wood == 0                # the card's 4-wood cost, nothing more
    assert p.resources.clay == 3                # the immediate +3 clay
    assert CARD_ID in p.minor_improvements      # kept minor, lands in the tableau
    assert CARD_ID not in p.hand_minors
    # The pushed free-renovate primitive is on top: cost overridden, target NOT pinned
    # (user ruling 2026-07-21 #2 — the normal target menu applies).
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingRenovate)
    assert top.cost_override == Resources()
    assert top.forced_target is None
    assert top.initiated_by_id == f"card:{CARD_ID}"

    # The single offered renovate is the zero-cost wood→clay commit.
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitRenovate)]
    assert len(commits) == 1
    assert commits[0].payment == Resources()
    assert commits[0].to_material is HouseMaterial.CLAY

    cs = step(cs, commits[0])                   # apply the free renovate
    p = cs.players[cp]
    assert p.house_material is HouseMaterial.CLAY
    assert p.resources == Resources(clay=3)     # NOTHING spent beyond the play cost
    assert _n_rooms(p) == rooms0

    # After-flip ordering (ruling 2026-07-21 #1 / the deferred after-flip): the
    # renovate resolved before the host flipped; pop both frames cleanly.
    assert Stop() in legal_actions(cs)
    cs = step(cs, Stop())                        # pop PendingRenovate
    cs = step(cs, Stop())                        # pop PendingPlayMinor
    assert not any(isinstance(f, (PendingRenovate, PendingPlayMinor))
                   for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Decline variant — +3 clay lands, no renovate frame, the grant is forfeited
# ---------------------------------------------------------------------------

def test_decline_variant_no_renovate_frame():
    cs, cp = _card_state(res=Resources(wood=4))
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "decline"))

    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.clay == 3                # the +3 clay is unconditional
    assert p.house_material is HouseMaterial.WOOD
    assert CARD_ID in p.minor_improvements
    # No renovate frame anywhere — the clarification: declined at play, gone forever.
    assert not any(isinstance(f, PendingRenovate) for f in cs.pending_stack)
    cs = step(cs, Stop())                        # pop the flipped PendingPlayMinor host
    assert not any(isinstance(f, PendingPlayMinor) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Conservator co-owned — the free renovate offers the stone target too
# ---------------------------------------------------------------------------

def test_conservator_widens_free_renovate_to_stone():
    # Ruling 2026-07-21 #2: no forced_target, so Conservator's wood→stone extension
    # applies to the granted renovate — and it is free either way.
    import agricola.cards.conservator  # noqa: F401 — registers the target extension

    cs, cp = _card_state(res=Resources(wood=4), occupations={"conservator"})
    cs = _push_minor(cs, cp)
    cs = step(cs, _commit(cs, "renovate"))
    assert isinstance(cs.pending_stack[-1], PendingRenovate)

    commits = [a for a in legal_actions(cs) if isinstance(a, CommitRenovate)]
    assert {c.to_material for c in commits} == {HouseMaterial.CLAY, HouseMaterial.STONE}
    assert all(c.payment == Resources() for c in commits)   # free either way

    stone = next(c for c in commits if c.to_material is HouseMaterial.STONE)
    cs = step(cs, stone)
    p = cs.players[cp]
    assert p.house_material is HouseMaterial.STONE
    assert p.resources == Resources(clay=3)     # still nothing paid for the renovate


# ---------------------------------------------------------------------------
# Renovate-forbid card owned — only the decline route is offered
# ---------------------------------------------------------------------------

def test_forbid_card_withholds_renovate_variant():
    # Deliberate addition beyond the wide-variant baseline: with a renovate-forbid
    # card in play (Mantlepiece — RENOVATE_FORBID_CARDS), `_legal_renovate_targets`
    # is empty, so the pushed frame would have no commit and no Stop. The variants_fn
    # gates the "renovate" route on that same function, keeping "variant offered ⇔
    # the frame has a legal commit" exact. The card itself stays playable — the
    # +3 clay is unconditional (contrast Renovation Materials, whose MANDATORY
    # renovate blocks the whole play under a forbid — its 2026-07-20 ruling).
    import agricola.cards.mantlepiece  # noqa: F401 — registers the forbid

    cs, cp = _card_state(res=Resources(wood=4), minors={"mantlepiece"})
    assert CARD_ID in playable_minors(cs, cp)   # still playable (prereq is house-only)
    cs = _push_minor(cs, cp)
    assert _variants_offered(cs) == ["decline"]
