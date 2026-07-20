"""Tests for Renovation Materials (minor improvement, E2) — the mandatory zero-cost,
target-pinned renovate on play.

Card text: "Immediately renovate to clay at no cost. (You must pay the cost of this card
though.)"  Cost 3 clay + 1 reed; prereq "Wooden House"; a TRAVELING (passing) minor.

Renovation Materials' `on_play` pushes a `PendingRenovate` carrying two push-time fields
(user ruling 2026-07-20): `cost_override=Resources()` (the renovate is free — "at no cost")
and `forced_target=HouseMaterial.CLAY` (the target is pinned — "to clay", so a co-owned
Conservator can't widen it to stone). The card's OWN 3-clay-1-reed cost is paid normally at
play. The renovate flows through the normal `PendingRenovate` frame, so every before/after
renovate event still fires (here driven by co-owning Roof Ladder's `after_renovate` +1 stone).

The tests push `PendingPlayMinor` directly (the established factory pattern, mirroring
test_card_dwelling_plan.py) with the card in hand, then drive play → (card passes) →
renovate → Stop.
"""
import agricola.cards.renovation_materials  # noqa: F401
import agricola.cards.roof_ladder  # noqa: F401 — an after_renovate auto to drive the reaction
import agricola.cards.conservator  # noqa: F401 — the wood->stone target extension guarded against

from agricola.actions import CommitRenovate, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor, sole_renovate

CARD_ID = "renovation_materials"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _n_rooms(p) -> int:
    return sum(1 for row in p.farmyard.grid for cell in row
               if cell.cell_type == CellType.ROOM)


def _card_state(seed=5, *, res=None, house=None, occupations=None, minors=None):
    """A 2-player card-mode state with `renovation_materials` in the active player's hand
    and the given fields overridden; opponent hand cleared so only our card is in play."""
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


def _play(cs, cp):
    """Play the card through a PendingPlayMinor host; return the state at the pushed
    PendingRenovate."""
    cs = _push_minor(cs, cp)
    return step(cs, sole_play_minor(cs, CARD_ID))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=3, reed=1))
    assert spec.passing_left is True            # E2 is a traveling minor
    assert spec.vps == 0
    assert spec.prereq is not None              # "Wooden House" prerequisite


# ---------------------------------------------------------------------------
# Prerequisite — "Wooden House": playable on wood, not on clay / stone
# ---------------------------------------------------------------------------

def test_prereq_wooden_house():
    spec = MINORS[CARD_ID]
    for house, expected in (
        (HouseMaterial.WOOD, True),
        (HouseMaterial.CLAY, False),
        (HouseMaterial.STONE, False),
    ):
        cs, cp = _card_state(house=house, res=Resources(clay=3, reed=1))
        assert prereq_met(spec, cs, cp) is expected


def test_not_playable_with_renovate_forbid_card():
    """User ruling 2026-07-20: a renovate-forbid card in play (Mantlepiece /
    Wooden Shed) blocks the play entirely — the card's mandatory renovate could
    never happen, and `forced_target` bypasses the target enumeration where the
    forbid normally lives."""
    import agricola.cards.mantlepiece  # noqa: F401 — registers the forbid

    spec = MINORS[CARD_ID]
    cs, cp = _card_state(house=HouseMaterial.WOOD, res=Resources(clay=3, reed=1),
                         minors=("mantlepiece",))
    assert prereq_met(spec, cs, cp) is False
    cs2 = _push_minor(cs, cp)
    assert CARD_ID not in {a.card_id for a in legal_actions(cs2)
                           if hasattr(a, "card_id")}


def test_not_playable_on_clay_house():
    # Affordable, but a clay house fails the prereq → the card is not offered at play.
    cs, cp = _card_state(house=HouseMaterial.CLAY, res=Resources(clay=3, reed=1))
    assert CARD_ID not in playable_minors(cs, cp)


def test_playable_on_wooden_house():
    cs, cp = _card_state(house=HouseMaterial.WOOD, res=Resources(clay=3, reed=1))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    assert CARD_ID in playable_minors(cs, cp)


# ---------------------------------------------------------------------------
# Full flow — card cost debited, then a free wood->clay renovate
# ---------------------------------------------------------------------------

def test_full_play_renovates_wood_to_clay_at_no_cost():
    # Extra clay/reed beyond the 3+1 card cost, to prove the renovate itself spends nothing.
    cs, cp = _card_state(res=Resources(clay=5, reed=2))
    assert cs.players[cp].house_material is HouseMaterial.WOOD
    rooms0 = _n_rooms(cs.players[cp])

    cs = _play(cs, cp)
    # Card cost paid normally: 3 clay + 1 reed.
    assert cs.players[cp].resources.clay == 5 - 3
    assert cs.players[cp].resources.reed == 2 - 1
    # Traveling: passed to the opponent, never kept in the tableau.
    assert CARD_ID not in cs.players[cp].minor_improvements
    assert CARD_ID in cs.players[1 - cp].hand_minors
    # The pushed renovate primitive is on top.
    assert isinstance(cs.pending_stack[-1], PendingRenovate)

    # The single offered renovate is the zero-cost, clay-pinned commit.
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitRenovate)]
    assert len(commits) == 1
    assert commits[0].payment == Resources()
    assert commits[0].to_material is HouseMaterial.CLAY

    clay1, reed1 = cs.players[cp].resources.clay, cs.players[cp].resources.reed
    cs = step(cs, sole_renovate(cs))            # apply the free renovate
    # House upgraded, NO further resources spent, room count preserved.
    assert cs.players[cp].house_material is HouseMaterial.CLAY
    assert cs.players[cp].resources.clay == clay1
    assert cs.players[cp].resources.reed == reed1
    assert _n_rooms(cs.players[cp]) == rooms0

    # Renovate flipped to its after-phase (Stop available); pop it, then the play-minor host.
    assert Stop() in legal_actions(cs)
    cs = step(cs, Stop())                        # pop PendingRenovate
    cs = step(cs, Stop())                        # pop PendingPlayMinor
    assert not any(isinstance(f, (PendingRenovate, PendingPlayMinor))
                   for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# Conservator co-owned — the pinned target stays clay-only (never widened to stone)
# ---------------------------------------------------------------------------

def test_conservator_does_not_widen_to_stone():
    # Conservator adds wood->stone as a renovate target, but forced_target=CLAY pins it.
    cs, cp = _card_state(res=Resources(clay=5, reed=2), occupations={"conservator"})
    cs = _play(cs, cp)
    assert isinstance(cs.pending_stack[-1], PendingRenovate)
    commits = [a for a in legal_actions(cs) if isinstance(a, CommitRenovate)]
    # Exactly one commit, and it targets clay — Conservator's stone target is excluded.
    assert len(commits) == 1
    assert commits[0].to_material is HouseMaterial.CLAY
    assert all(c.to_material is not HouseMaterial.STONE for c in commits)


# ---------------------------------------------------------------------------
# An after_renovate reaction still fires on this granted renovate
# ---------------------------------------------------------------------------

def test_after_renovate_reaction_fires():
    # Co-own Roof Ladder: its after_renovate auto grants +1 stone at the renovate's
    # after-phase flip. (Its renovate cost-reduction is bypassed by cost_override, which is
    # correct — the override IS the single payment.)
    cs, cp = _card_state(res=Resources(clay=3, reed=1, stone=0), minors={"roof_ladder"})
    assert cs.players[cp].resources.stone == 0
    cs = _play(cs, cp)
    cs = step(cs, sole_renovate(cs))            # commit → flips to after-phase, auto fires
    assert cs.players[cp].house_material is HouseMaterial.CLAY
    assert cs.players[cp].resources.stone == 1  # Roof Ladder's after_renovate +1 stone fired
