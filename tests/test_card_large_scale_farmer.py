"""Tests for Large-Scale Farmer (occupation, B150; players 4+).

Card text: "Each time after you use the 'Farm Expansion' or 'Major Improvement'
action space while the other is unoccupied, you can pay 1 food to use that other
space with the same person."

Clarification: "The person ends on the second action space used."
Errata: "The 'jump' to a second action space may only be done once per turn."

Ruling 81 (2026-07-26): the jump is an optional trigger in the SOURCE's
after-window; firing pays the food, moves the acting worker, and runs the
destination's FULL action; "while the other is unoccupied" is checked at the
trigger time; no placement number is minted.

A 4+-player card — never dealt at 2 players; these tests inject it (the Lodger
precedent). The two sources host DIFFERENT events (after_action_space on the Farm
Expansion host; after_major_minor_improvement on the Major Improvement space's
composite), and the major side is provenance-gated to the SPACE-pushed composite
("space:major_improvement") — House Redevelopment's step and card grants must
not offer the jump.
"""
import agricola.cards.large_scale_farmer  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction, CommitBuildRoom, CommitFoodPayment, FireTrigger,
    PlaceWorker, Proceed, Stop,
)
from agricola.cards.large_scale_farmer import (
    CARD_ID, _eligible_major_improvement,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions, playable_minors
from agricola.pending import (
    PendingFarmExpansion, PendingFoodPayment, PendingMajorMinorImprovement,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_pending_stack
from tests.test_utils import sole_build_major, sole_renovate

_POOL = CardPool(
    occupations=("large_scale_farmer",) + tuple(f"o{i}" for i in range(20)),
    minors=("cob", "corn_scoop") + tuple(f"m{i}" for i in range(20)),
)

_FIRE = FireTrigger(card_id=CARD_ID)


def _offered(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state))


# ---------------------------------------------------------------------------
# State helper — mirrors tests/test_card_merchant.py
# ---------------------------------------------------------------------------

def _state(*, seed=5, occ=(CARD_ID,), hand_occ=(), minors=(), res=None):
    """Card-mode state with BOTH Farm Expansion and Major Improvement revealed
    and free, the current player given the played occupations / hand cards /
    exact resources. Opponent's hand is emptied so the flow stays deterministic."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    for sid in ("farm_expansion", "major_improvement"):
        sp = fast_replace(get_space(cs.board, sid), revealed=True, workers=(0, 0))
        cs = fast_replace(cs, board=with_space(cs.board, sid, sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     hand_occupations=frozenset(hand_occ),
                     hand_minors=frozenset(minors),
                     resources=res if res is not None else Resources())
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _fe_after_window(cs):
    """Drive the real Farm Expansion flow — place, build ONE room (5 wood +
    2 reed), exit — to the FE host's after-window (where the jump is offered)."""
    cs = step(cs, PlaceWorker(space="farm_expansion"))
    assert isinstance(cs.pending_stack[-1], PendingFarmExpansion)
    cs = step(cs, ChooseSubAction(name="build_rooms"))
    room = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = step(cs, room)
    cs = step(cs, Proceed())     # build_rooms leaf -> its after-phase
    cs = step(cs, Stop())        # pop the leaf -> FE host (room_chosen)
    cs = step(cs, Proceed())     # FE host -> after-phase: the jump window
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion) and top.phase == "after"
    return cs


def _mi_after_window(cs, major_idx=0):
    """Drive the real Major Improvement flow — place, build the major — to the
    composite's after-window (where the jump is offered)."""
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, major_idx))
    cs = step(cs, Stop())        # pop build-major -> composite flips to after
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    return cs


def _walk_out(cs):
    """Exit every open frame (Stop/Proceed) until the turn ends."""
    while cs.pending_stack:
        la = legal_actions(cs)
        if Stop() in la:
            cs = step(cs, Stop())
        elif Proceed() in la:
            cs = step(cs, Proceed())
        else:
            raise AssertionError(f"cannot exit frame: {la}")
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    for event in ("after_action_space", "after_major_minor_improvement"):
        entries = [e for e in TRIGGERS.get(event, ()) if e.card_id == CARD_ID]
        assert len(entries) == 1, event
        assert not entries[0].mandatory   # "you can pay" — optional


# ---------------------------------------------------------------------------
# POSITIVE: Farm Expansion -> Major Improvement (end to end)
# ---------------------------------------------------------------------------

def test_jump_farm_expansion_to_major_improvement():
    # wood 7 / reed 2: one room (5w+2r) leaves 2 wood — a stable stays buildable,
    # so at the destination's own window ONLY the once-per-turn latch can block
    # the reverse jump. food 2: 1 for the fee, 1 left over for the same reason.
    cs, cp = _state(res=Resources(wood=7, reed=2, clay=2, food=2))
    cs = _fe_after_window(cs)

    assert _offered(cs)
    cs = step(cs, _FIRE)

    # The fee is paid, the person MOVED (clarification: ends on the second
    # space), and no placement number was minted (ruling 79).
    assert cs.players[cp].resources.food == 1
    assert get_space(cs.board, "farm_expansion").workers[cp] == 0
    assert get_space(cs.board, "major_improvement").workers[cp] == 1
    assert placements_this_round(cs.players[cp]) == 1
    assert CARD_ID in cs.players[cp].used_this_turn

    # The destination's FULL action runs: its space host is on top.
    top = cs.pending_stack[-1]
    assert type(top).PENDING_ID == "action_space"
    assert top.initiated_by_id == "space:major_improvement"

    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())                    # pop build-major -> composite after

    # Errata / chain-back: the destination's composite window would offer the
    # reverse jump (source vacated, stable affordable, food on hand) but the
    # once-per-turn latch blocks it.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    assert top.initiated_by_id == "space:major_improvement"
    assert not _offered(cs)

    cs = step(cs, Stop())                    # pop the composite
    assert not _offered(cs)                  # MI space host's own after-window
    cs = step(cs, Stop())                    # pop the MI space host

    # Back at the source's after-window: once per window (triggers_resolved).
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion) and top.phase == "after"
    assert CARD_ID in top.triggers_resolved
    assert not _offered(cs)

    owners = cs.board.major_improvement_owners
    assert owners[0] == cp
    assert cs.players[cp].resources.clay == 0
    cs = _walk_out(cs)


# ---------------------------------------------------------------------------
# POSITIVE: Major Improvement -> Farm Expansion (the composite-host side)
# ---------------------------------------------------------------------------

def test_jump_major_improvement_to_farm_expansion():
    # After the jump the player owns a Fireplace, so a Cooking Hearth stays
    # affordable by returning it — at the FE window only the latch blocks the
    # reverse jump (food 2 leaves 1 after the fee).
    cs, cp = _state(res=Resources(clay=2, wood=5, reed=2, food=2))
    cs = _mi_after_window(cs)                # Fireplace built (2 clay)

    assert _offered(cs)
    cs = step(cs, _FIRE)

    assert cs.players[cp].resources.food == 1
    assert get_space(cs.board, "major_improvement").workers[cp] == 0
    assert get_space(cs.board, "farm_expansion").workers[cp] == 1
    assert placements_this_round(cs.players[cp]) == 1

    # The destination's full action: the FE host is on top, before-phase.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion)
    assert top.initiated_by_id == "space:farm_expansion"

    cs = step(cs, ChooseSubAction(name="build_rooms"))
    room = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = step(cs, room)                      # 5 wood + 2 reed
    cs = step(cs, Proceed())
    cs = step(cs, Stop())                    # pop the build-rooms leaf
    cs = step(cs, Proceed())                 # FE host -> after-phase

    # Chain-back blocked by the latch (MI is vacated and the Fireplace-return
    # route keeps a major affordable, so the latch is the one blocker).
    assert not _offered(cs)
    cs = step(cs, Stop())                    # pop the FE host

    # Back at the source composite's after-window: latched by triggers_resolved.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    assert CARD_ID in top.triggers_resolved
    assert not _offered(cs)

    rooms = sum(1 for row in cs.players[cp].farmyard.grid
                for cell in row if cell.cell_type.name == "ROOM")
    assert rooms == 3
    cs = _walk_out(cs)


# ---------------------------------------------------------------------------
# Provenance gate: only the SPACE-pushed composite offers the jump
# ---------------------------------------------------------------------------

def test_house_redevelopment_composite_does_not_offer():
    # Everything else is eligible: FE unoccupied + a room/stable affordable,
    # food on hand. Only the provenance (initiated_by_id "house_redevelopment",
    # not "space:major_improvement") blocks.
    cs, cp = _state(res=Resources(clay=7, reed=3, wood=5, food=5))
    cs = step(cs, PlaceWorker(space="house_redevelopment"))
    cs = step(cs, ChooseSubAction(name="renovate"))
    cs = step(cs, sole_renovate(cs))         # wood -> clay: 2 clay + 1 reed
    cs = step(cs, Stop())                    # pop the renovate after-phase
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())                    # pop build-major -> composite after

    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    assert top.initiated_by_id == "house_redevelopment"
    assert not _offered(cs)
    cs = _walk_out(cs)


def test_granted_composite_provenance_unit():
    """The major-side eligibility keys on the composite's provenance: the space's
    own push fires, House Redevelopment's step and card grants never do."""
    cs, cp = _state(res=Resources(wood=2, food=1))
    # Put the acting worker on the Major Improvement space, FE free.
    mi = get_space(cs.board, "major_improvement")
    workers = tuple(1 if i == cp else 0 for i in range(2))
    cs = fast_replace(cs, board=with_space(
        cs.board, "major_improvement", fast_replace(mi, workers=workers)))

    def _at(iby):
        s = with_pending_stack(cs, (PendingMajorMinorImprovement(
            player_idx=cp, initiated_by_id=iby, phase="after"),))
        return _eligible_major_improvement(s, cp, frozenset())

    assert _at("space:major_improvement")        # the space's composite
    assert not _at("house_redevelopment")        # HR's optional step
    assert not _at("card:angler")                # a card-granted composite
    assert not _at("card:merchant")              # a Merchant repeat


# ---------------------------------------------------------------------------
# "While the other is unoccupied" — checked at the trigger time
# ---------------------------------------------------------------------------

def test_not_offered_when_destination_occupied():
    cs, cp = _state(res=Resources(wood=5, reed=2, clay=2, food=1))
    # The opponent stands on Major Improvement.
    mi = get_space(cs.board, "major_improvement")
    workers = tuple(0 if i == cp else 1 for i in range(2))
    cs = fast_replace(cs, board=with_space(
        cs.board, "major_improvement", fast_replace(mi, workers=workers)))

    cs = _fe_after_window(cs)
    assert not _offered(cs)


# ---------------------------------------------------------------------------
# The food gate
# ---------------------------------------------------------------------------

def test_not_offered_without_food_or_fuel():
    # Destination legal (2 clay -> Fireplace), but no food and nothing to
    # liquidate.
    cs, cp = _state(res=Resources(wood=5, reed=2, clay=2, food=0))
    cs = _fe_after_window(cs)
    assert not _offered(cs)


def test_liquidation_pays_the_fee():
    # No food on hand, 1 grain of fuel; the destination (Fireplace, 2 clay) is
    # unaffected by cooking the grain -> offered; firing pushes the raise-only
    # food frame, whose sole bundle cooks the grain; the resume debits the food
    # and runs the jump.
    cs, cp = _state(res=Resources(wood=5, reed=2, clay=2, grain=1, food=0))
    cs = _fe_after_window(cs)

    assert _offered(cs)
    cs = step(cs, _FIRE)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.resume_kind == f"{CARD_ID}:major_improvement"   # direction-keyed (ruling 82)

    bundles = legal_actions(cs)
    assert bundles == [CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)]
    cs = step(cs, bundles[0])

    # Raised 1, fee debited 1; the jump ran.
    assert cs.players[cp].resources.food == 0
    assert cs.players[cp].resources.grain == 0
    assert CARD_ID in cs.players[cp].used_this_turn
    assert get_space(cs.board, "farm_expansion").workers[cp] == 0
    assert get_space(cs.board, "major_improvement").workers[cp] == 1

    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="build_major"))
    cs = step(cs, sole_build_major(cs, 0))   # Fireplace (2 clay)
    cs = step(cs, Stop())
    assert cs.board.major_improvement_owners[0] == cp
    cs = _walk_out(cs)


# ---------------------------------------------------------------------------
# Never a dead end: the destination must stay usable AFTER the payment
# ---------------------------------------------------------------------------

def test_not_offered_when_fee_strands_the_only_minor():
    # 1 food in supply and the destination is reachable only via Cob (a 1-food
    # minor): paying the fee would leave the Major Improvement host with no
    # legal child -> not offered. (Cob IS playable before the fee.)
    cs, cp = _state(minors=("cob",), res=Resources(wood=5, reed=2, food=1))
    cs = _fe_after_window(cs)
    assert playable_minors(cs, cp, composite_only_ok=True) == ["cob"]
    assert not _offered(cs)


def test_not_offered_when_liquidation_strands_the_only_minor():
    # No food, the only fuel is 1 grain, and the destination is reachable only
    # via Cob (1 food): the sole raise bundle cooks the grain to exactly the
    # fee, leaving 0 food and no fuel -> the destination would be stranded ->
    # not offered (the all-bundles post-payment gate).
    cs, cp = _state(minors=("cob",), res=Resources(wood=5, reed=2, grain=1, food=0))
    cs = _fe_after_window(cs)
    assert not _offered(cs)


def test_not_offered_when_destination_has_no_action():
    # Food on hand, but nothing at the destination: no clay/majors affordable,
    # no hand minor, no decline-income card -> the jump would land on a host
    # with no legal child -> not offered.
    cs, cp = _state(res=Resources(wood=5, reed=2, food=3))
    cs = _fe_after_window(cs)
    assert not _offered(cs)


# ---------------------------------------------------------------------------
# Optionality / inertness / the ordinal suite
# ---------------------------------------------------------------------------

def test_declinable():
    cs, cp = _state(res=Resources(wood=5, reed=2, clay=2, food=1))
    cs = _fe_after_window(cs)
    assert _offered(cs)
    assert Stop() in legal_actions(cs)
    cs = step(cs, Stop())                    # decline: pop the host instead

    assert cs.players[cp].resources.food == 1        # nothing paid
    assert get_space(cs.board, "farm_expansion").workers[cp] == 1
    assert get_space(cs.board, "major_improvement").workers[cp] == 0
    assert CARD_ID not in cs.players[cp].used_this_turn


def test_hand_only_is_inert():
    cs, cp = _state(occ=(), hand_occ=(CARD_ID,),
                    res=Resources(wood=5, reed=2, clay=2, food=1))
    cs = _fe_after_window(cs)
    assert not _offered(cs)


# ---------------------------------------------------------------------------
# Ruling 82 — SOME preserving bundle suffices; the frame filters to exactly those
# ---------------------------------------------------------------------------

def test_exists_a_preserving_bundle_offers_and_filters():
    """The EXISTENCE flip ruling 82 makes: the Major Improvement space is usable
    only via a 1-GRAIN minor (Market Stall in hand; no goods for any major, and
    the owned cooker is a Cooking Hearth so no return-route build exists). Fuel =
    that grain + 1 sheep. Bundles: cook the grain (strands the
    destination ✗) or cook the sheep (preserves ✓). The old all-bundles gate
    withheld the jump entirely — deleting a legal line; now it is offered, and the
    food frame offers ONLY the sheep bundle."""
    from agricola.actions import CommitFoodPayment
    from tests.factories import with_majors
    cs, cp = _state(res=Resources(wood=5, reed=2, grain=1, food=0))
    p = cs.players[cp]
    p = fast_replace(p, animals=fast_replace(p.animals, sheep=1),
                     hand_minors=frozenset({"market_stall"}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    # A COOKING HEARTH (major #2), not a Fireplace: it cooks the sheep but —
    # unlike an owned Fireplace — funds no return-route major build, so the
    # destination genuinely hinges on the grain-costing minor.
    cs = with_majors(cs, owner_by_idx={2: cp})
    cs = _fe_after_window(cs)
    assert _offered(cs), "some preserving bundle exists -> the jump must be offered"
    cs = step(cs, _FIRE)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    bundles = [a for a in legal_actions(cs) if isinstance(a, CommitFoodPayment)]
    assert bundles
    assert all(b.grain == 0 for b in bundles), (
        "a bundle cooking the destination's only funding grain must be withheld")
    assert any(b.sheep == 1 for b in bundles)
