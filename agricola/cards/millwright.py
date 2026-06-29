"""Millwright (occupation, D-deck; Dulcinaria; players 1+).

Card text: "You immediately get 1 grain. Each time you build fences, stables, and rooms,
or renovate your house, you can replace up to 2 building resources of any type with 1
grain each."

Two effects:
- on-play: +1 grain (immediate).
- a passive cost-CONVERSION — the chaining SINK (COST_MODIFIER_DESIGN.md §4.4 / §4.7).
  Its generator returns the unchanged running cost plus every way to replace up to 2
  *building-resource* units (wood / clay / reed / stone — NOT food/grain/veg) with 1 grain
  each. Because Millwright consumes the OUTPUT of feeder conversions (e.g. Frame Builder's
  clay→wood), it registers at a HIGH `order` so `expand_conversions` applies it LAST — the
  apply-each-once, sink-last rule that keeps the clay→wood→grain chain legal without
  double-spending. The worked example: Frame Builder + Millwright let you build a clay room
  (5 clay + 2 reed) for 3 clay + 2 reed + 1 grain (Frame Builder turns 2 clay into 1 wood,
  Millwright turns that wood into 1 grain).

The "up to 2" budget is PER BUILD-ACTION, not per single build. In Agricola you build all
of a "Build Rooms"/"Build Stables" action's rooms/stables at once; the engine resolves them
one at a time for tractability, so Millwright must share its 2-grain budget across every
room/stable built in the *same* action (building 4 rooms still exchanges 2 grain total, not
2 per room). It does this with a per-action running count in its own CardStore slot (the
Shepherd's-Crook per-action-state pattern): `_expand` caps offered swaps at `2 − used`,
`_record` adds the units a committed payment used (its grain delta — the printed base has no
grain, even through a Frame-Builder chain), and the `after_build_rooms` / `after_build_stables`
/ `after_renovate` autos reset the count when the action completes. Renovate is a single
build (one CommitRenovate upgrades all rooms), so its budget never binds.

The build-fence clause is a SETTLE-ONLY conversion (COST_MODIFIER_DESIGN.md §9.2): fences
pay once at the whole-action Proceed settle, where `_build_fence_ctx(..., settle=True)` is
built, so Millwright's `build_fence` generator is gated on `ctx.settle is True`. It is thus
visible only in the settle payment menu — over the whole-action wood bill, with the full
2-grain budget — and INVISIBLE to the per-pasture during-building affordability
(`_check_entry_legal`, ctx `settle=False`). That gate matters: if the during-building path
saw Millwright it would over-grant the per-action cap and could enable a build whose settle
has no affordable payment. NOTE (documented follow-up): the during-building legality stays
wood-only (conservative) — Millwright's `min(grain, 2)` is NOT added to the per-pasture
affordability capacity, so a wood-affordable build can *choose* grain at settle but a
wood-TIGHT build is not enabled by holding grain. Enabling that is a separate increment.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "millwright"

# The four building resources Millwright may turn into grain.
_BUILDING_FIELDS = ("wood", "clay", "reed", "stone")

# "replace UP TO 2 building resources ... with 1 grain each" — per build-ACTION.
MAX_GRAIN = 2

# Sink order: higher than feeder conversions (default order 0, e.g. Frame Builder) so the
# sink is applied after the resources it consumes have been produced (§4.7).
_SINK_ORDER = 10


def _set_count(state: GameState, idx: int, value: int) -> GameState:
    """Write the per-action grain-conversion count to Millwright's CardStore slot."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, value))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    """Unchanged cost + every replacement of up to `MAX_GRAIN − used` building-resource
    units with grain (1 each), where `used` is how much of this build-ACTION's grain budget
    earlier rooms/stables already spent (read from the CardStore counter)."""
    remaining = MAX_GRAIN - state.players[idx].card_state.get(CARD_ID, 0)
    out = {cost}
    if remaining < 1:
        return list(out)
    avail = {f: getattr(cost, f) for f in _BUILDING_FIELDS}
    # Replace exactly one unit.
    for f in _BUILDING_FIELDS:
        if avail[f] >= 1:
            out.add(cost - Resources(**{f: 1}) + Resources(grain=1))
    # Replace exactly two units (only if the action still has >= 2 budget left).
    if remaining >= 2:
        for i, f1 in enumerate(_BUILDING_FIELDS):
            for f2 in _BUILDING_FIELDS[i:]:
                if f1 == f2:
                    if avail[f1] >= 2:
                        out.add(cost - Resources(**{f1: 2}) + Resources(grain=2))
                elif avail[f1] >= 1 and avail[f2] >= 1:
                    out.add(cost - Resources(**{f1: 1, f2: 1}) + Resources(grain=2))
    return list(out)


def _expand_fence(state, idx, ctx, cost: Resources) -> list[Resources]:
    """The fence clause of Millwright — a SETTLE-ONLY conversion (COST_MODIFIER_DESIGN.md
    §9.2). It mirrors `_expand` (replace up to 2 building-resource units with 1 grain each,
    sharing the per-action budget) but is gated on `ctx.settle is True`: fences pay once at
    the whole-action Proceed settle (`_build_fence_ctx(..., settle=True)`), so the conversion
    is offered ONLY there — over the whole-action wood bill with the full budget. During the
    per-pasture building affordability (`ctx.settle is False`) it returns the unchanged cost,
    so it is invisible to the during-building legality (which would otherwise over-grant the
    per-action cap and could enable a build with no affordable settle)."""
    if not getattr(ctx, "settle", False):
        return [cost]
    return _expand(state, idx, ctx, cost)


def _record(state, idx, payment) -> GameState:
    """Add the grain a committed payment converted (= Millwright units used) to this
    action's running count. The printed base of every affected build has 0 grain, so any
    grain in the payment is Millwright's doing (even when it consumed a Frame-Builder
    intermediate). A no-op for a non-resource / grain-free payment."""
    grain = payment.grain if isinstance(payment, Resources) else 0
    if grain == 0:
        return state
    return _set_count(state, idx, state.players[idx].card_state.get(CARD_ID, 0) + grain)


def _reset(state: GameState, idx: int) -> GameState:
    """Reset the per-action count at the build-action's after-phase (so the next action
    starts with the full budget). No-op when already zero, for state convergence."""
    if state.players[idx].card_state.get(CARD_ID, 0) == 0:
        return state
    return _set_count(state, idx, 0)


for _action in ("renovate", "build_room", "build_stable"):
    register_conversion(_action, CARD_ID, _expand, order=_SINK_ORDER, record=_record)
# build_fence: settle-only (see _expand_fence). Whole-action bill at the Proceed settle.
register_conversion("build_fence", CARD_ID, _expand_fence, order=_SINK_ORDER, record=_record)
for _event in ("after_renovate", "after_build_rooms", "after_build_stables",
               "after_build_fences"):
    register_auto(_event, CARD_ID, lambda state, idx: True, _reset)
register_occupation(CARD_ID, _on_play)
