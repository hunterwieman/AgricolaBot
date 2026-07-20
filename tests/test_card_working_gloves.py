import agricola.cards.working_gloves  # noqa: F401
import agricola.cards.forest_school  # noqa: F401
import agricola.cards.writing_desk  # noqa: F401
import agricola.cards.roof_ballaster  # noqa: F401

"""Tests for Working Gloves (minor improvement E60) — the second consumer of the
play_occupation cost-conversion chokepoint (ruling 67, 2026-07-20).

Covers: registration (a CONVERSIONS entry, no trigger); the on-play +1 food; the
resource-choice payment menu (1 building resource in place of min(2, cost.food) food,
filtered by holdings); the DOMINANCE requirement next to Forest School (its 2-wood
payment is pruned, the identical 1-wood payments de-duplicate — the user's
no-dominated-offers ask, plus the structural impossibility of double-replacement);
and the SURCHARGE separation (user ruling 2026-07-20): Roof Ballaster's 1-food
surcharge is never substitutable — it is paid in real food on top of the chosen
base-cost payment, and the `paid_cost` stamp excludes it.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayMinor,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
)
from agricola.cards.cost_mods import CONVERSIONS
from agricola.cards.specs import MINORS
from agricola.cards.working_gloves import CARD_ID
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor, PendingPlayOccupation, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("consultant", "priest", "stable_architect", "roof_ballaster")
    + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "forest_school", "writing_desk") + tuple(f"m{i}" for i in range(20)),
)


def _play_state(*, owned=(CARD_ID,), occupations=(), hand=(), hand_minors=(),
                food=0, wood=0, clay=0, reed=0, stone=0):
    """p0-to-move CARDS state with the listed minors in the tableau, occupations in
    front, the given hands and resources."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        minor_improvements=frozenset(owned),
        occupations=frozenset(occupations),
        hand_occupations=frozenset(hand),
        hand_minors=frozenset(hand_minors),
        resources=Resources(food=food, wood=wood, clay=clay, reed=reed, stone=stone),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _writing_desk_grant(*, owned, **res):
    """Fire Writing Desk's 2-food granted play (the real Lessons flow); returns the
    state paused on the granted PendingPlayOccupation."""
    cs, cp = _play_state(owned=tuple(owned) + ("writing_desk",),
                         occupations=("priest",),
                         hand=("consultant", "stable_architect"), **res)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, FireTrigger(card_id="writing_desk"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=2)
    return cs, cp


def _consultant_payments(la):
    return {a.payment for a in la
            if isinstance(a, CommitPlayOccupation) and a.card_id == "consultant"}


# ---------------------------------------------------------------------------
# Registration + on-play
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.vps == 0
    assert spec.passing_left is False
    # Ruling 67: the substitution is a play_occupation COST CONVERSION.
    assert any(cid == CARD_ID
               for _o, cid, _fn, _rec in CONVERSIONS.get("play_occupation", ()))


def test_on_play_grants_one_food():
    cs, cp = _play_state(owned=(), hand_minors=(CARD_ID,), food=0)
    cs = push(cs, PendingPlayMinor(player_idx=cp, initiated_by_id="test"))
    commit = next(a for a in legal_actions(cs)
                  if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID)
    cs = step(cs, commit)
    p = cs.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.food == 1


# ---------------------------------------------------------------------------
# The payment menu
# ---------------------------------------------------------------------------

def test_one_resource_covers_two_food():
    # Writing Desk's 2-food granted play: ONE held building resource replaces BOTH
    # foods; unheld resource types never surface (the affordability filter).
    cs, _cp = _writing_desk_grant(owned=(CARD_ID,), food=2, wood=1, clay=1)
    assert _consultant_payments(legal_actions(cs)) == {
        Resources(food=2), Resources(wood=1), Resources(clay=1)}


def test_one_food_cost_replaces_only_one():
    # The Lessons 1-food play caps the replacement at min(2, cost.food) = 1 — the
    # resource still costs 1, it just replaces less.
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",),
                         food=1, stone=1)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert _consultant_payments(legal_actions(cs)) == {
        Resources(food=1), Resources(stone=1)}
    cs = step(cs, CommitPlayOccupation(card_id="consultant",
                                       payment=Resources(stone=1)))
    p = cs.players[cp]
    assert p.resources.stone == 0
    assert p.resources.food == 1          # the food stayed home
    assert cs.pending_stack[-1].paid_cost == Resources(stone=1)


# ---------------------------------------------------------------------------
# Dominance next to Forest School (the no-dominated-offers requirement)
# ---------------------------------------------------------------------------

def test_dominates_forest_school_on_two_food_cost():
    # Both substitution cards owned, 2 food + 2 wood: Working Gloves pays 1 wood where
    # Forest School pays 2 — the (2 wood) and (1 wood + 1 food) payments are DOMINATED
    # by (1 wood) and never offered; the food payment survives (Pareto-incomparable).
    # Double-replacement is inexpressible: no payment beyond these can exist.
    cs, _cp = _writing_desk_grant(owned=(CARD_ID, "forest_school"), food=2, wood=2)
    assert _consultant_payments(legal_actions(cs)) == {
        Resources(food=2), Resources(wood=1)}


def test_identical_payments_deduplicate_on_one_food_cost():
    # On a 1-food cost both cards' wood substitutions are the same (1 wood) vector —
    # one button, not two.
    cs, _cp = _play_state(owned=(CARD_ID, "forest_school"),
                          occupations=("priest",), hand=("consultant",),
                          food=1, wood=1)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert _consultant_payments(legal_actions(cs)) == {
        Resources(food=1), Resources(wood=1)}


# ---------------------------------------------------------------------------
# Surcharge separation (user ruling 2026-07-20)
# ---------------------------------------------------------------------------

def _roof_ballaster_menu(*, food, wood):
    cs, cp = _play_state(occupations=("priest",), hand=("roof_ballaster",),
                         food=food, wood=wood)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs, cp


def test_surcharge_not_substitutable():
    # Roof Ballaster's optional 1-food payment is an effect price OUTSIDE the pipeline:
    # with 0 food + 2 wood the base 1-food cost is payable in wood, but the "pay"
    # variant (base + 1 REAL food) is not — no substitution ever covers a surcharge.
    cs, _cp = _roof_ballaster_menu(food=0, wood=2)
    la = legal_actions(cs)
    decline = CommitPlayOccupation(card_id="roof_ballaster", variant="decline",
                                   payment=Resources(wood=1))
    assert decline in la
    assert not any(isinstance(a, CommitPlayOccupation) and a.variant == "pay"
                   for a in la)


def test_surcharge_paid_in_real_food_beside_a_substituted_base():
    # With 1 real food the "pay" variant unlocks — but only on the wood-substituted
    # base payment (food-base + food-surcharge = 2 food > 1 held). The debit is
    # 1 wood (the base, substituted) + 1 food (the surcharge, real), and the
    # `paid_cost` stamp carries the BASE payment only (Furniture Maker's scoping).
    cs, cp = _roof_ballaster_menu(food=1, wood=2)
    la = legal_actions(cs)
    pay_wood = CommitPlayOccupation(card_id="roof_ballaster", variant="pay",
                                    payment=Resources(wood=1))
    assert pay_wood in la
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="pay",
                                payment=Resources(food=1)) not in la
    cs = step(cs, pay_wood)
    p = cs.players[cp]
    assert p.resources.food == 0          # the surcharge, paid in real food
    assert p.resources.wood == 1          # 2 - 1 (the substituted base)
    assert p.resources.stone == 2         # Roof Ballaster: 1 stone per room (2 rooms)
    assert cs.pending_stack[-1].paid_cost == Resources(wood=1)   # surcharge excluded