# Implementing the pay-food → plow cards (Category A)

A focused build guide for the cluster of cards that **pay food to plow a field** via an
optional trigger — the exact shape of the already-shipped **Ox Goad** (E19) and **Plow Driver**
(A90). They are the tightest, most uniform reuse of the food-payment machinery
(`FOOD_PAYMENT_DESIGN.md`): each differs from Ox Goad only in its *trigger event*, an
*eligibility filter*, and the *food amount*.

> **Cardinal rule first (`CARD_AUTHORING_GUIDE.md` §0).** Several of these carry timing /
> scope rulings a coding agent will get wrong. **Confirm each card's ruling with the user
> before building it** — they are flagged per-card below under "RULING TO CONFIRM." Do not
> guess.

---

## The template (copy Ox Goad / Plow Driver)

Every card in the clean set has the identical structure. `agricola/cards/ox_goad.py` and
`agricola/cards/plow_driver.py` are the two reference implementations — copy whichever matches
the trigger kind (`ox_goad` = action-space trigger; `plow_driver` = start-of-round). The body:

```python
from agricola.cards.specs import register_food_payment_resume, register_occupation  # or register_minor
from agricola.cards.triggers import register   # + register_action_space_hook for ATOMIC spaces
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources

CARD_ID = "<slug>"
_FOOD_COST = <N>            # the card's per-plow food price

def _pay_and_plow(state, idx):
    # Debit the food, push the plow. Reached directly (food on hand) AND as the
    # post-food-payment resume (the raise-only frame leaves the food in supply to debit).
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))

def _eligible(state, idx, triggers_resolved):
    p = state.players[idx]
    return (CARD_ID not in triggers_resolved                       # once per this host visit
            and <card-specific filter, e.g. space_id in {...}>
            and _can_plow(p)                                       # never a dead-end plow
            and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST)))  # raisable food

def _apply(state, idx):
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)                          # food on hand: pay + plow
    return push(state, PendingFoodPayment(                        # short: raise-only, then resume
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost()))

register_occupation(CARD_ID, lambda state, idx: state)            # or register_minor(..., cost=...)
register("<event>", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)             # the grant resume (food short path)
# register_action_space_hook(CARD_ID, {<atomic space ids>})      # ONLY for atomic spaces (see below)
```

Then add the import to `agricola/cards/__init__.py`.

### Why each line is load-bearing

- **`_liquidatable_to(..., Resources(food=N))`** in eligibility — NOT `food >= N`. This is the
  whole point: the card must fire when the player has 0 food but convertible goods. (This is the
  exact bug we just fixed in Plow Driver & Scholar; do not reintroduce it.)
- **`_can_plow(p)`** in eligibility — the plow is granted unconditionally once fired, and
  `PendingPlow`'s before-phase offers no decline, so firing it with no legal cell would
  **dead-state** the game (empty legal-action set). Gate on a plowable cell. (This is the bug we
  just fixed in Shifting Cultivation.)
- **`_apply` is a guard, `_pay_and_plow` the body** — raise-only frame: the food-payment frame
  never debits; `_pay_and_plow` debits the food itself, whether reached directly (food on hand)
  or via the resume (food raised into supply). The resume is registered under the card id and is
  wrapped by `_resume` in `_fire_subaction_before_auto`, so the pushed plow's `before_plow` autos
  fire. (See FOOD_PAYMENT_DESIGN.md §6.)
- **`reserved=Cost()`** — these cards' only cost is the food, so nothing is reserved from the
  conversion fuel.
- **`triggers_resolved`** gives once-per-host-visit ("each time you use [space]" fires once per
  use, not repeatedly within the same use). It's recorded automatically by `_apply_fire_trigger`.

---

## The clean set — build these (each pending its ruling)

| Card | Slug / deck# | Type | Event | Filter | Food | Atomic hook? |
|---|---|---|---|---|---|---|
| **Plow Maker** | `plow_maker` D90 | occ | `before_action_space` | `space_id ∈ {farmland, cultivation}` | 1 | no (both hosted) |
| **Shifting Cultivator** | `shifting_cultivator` A91 | occ | `before_action_space` | `space_id ∈ {wood accumulation spaces}` | 3 | **yes** (Forest etc. are atomic) |
| **Drill Harrow** | `drill_harrow` D17 (cost 1 wood) | minor | `before_sow` | "unconditional" sow only | 3 | n/a (sub-action) |

**Verbatim text:**
- Plow Maker: *"Each time you use the 'Farmland' or 'Cultivation' action space, you can pay 1 food to plow 1 additional field."*
- Shifting Cultivator: *"Each time you use a wood accumulation space, you can also play 3 food to plow 1 field."* — clarification: *"Food obtained via the Basket A056, or any other effect 'after' using the space may not be used to pay for this effect."*
- Drill Harrow: *"Each time before you take an unconditional 'Sow' action, you can pay 3 food to plow 1 field."*

### RULINGS TO CONFIRM (ask the user) — per card

- **All three — before vs after.** "Each time you use [space]" / "before you sow" reads as the
  **before**-phase per the trigger-timing ruling (`CARD_AUTHORING_GUIDE.md` §2). Confirm — for
  Plow Maker the "*additional* field" plow lands *before* the space's own plow, which can change
  field adjacency, so the phase is observable, not cosmetic.
- **Shifting Cultivator — which spaces are "wood accumulation spaces"?** Base/2-player: Forest.
  Confirm the exact set (expansions add more), since the filter is `space_id ∈ {...}` and these
  are **atomic** spaces needing `register_action_space_hook`. The clarification (food obtained
  *after* the space can't pay) is consistent with firing in the **before**-phase.
- **Drill Harrow — what is an "unconditional Sow"?** Presumably the standard Sow sub-action
  (Grain Utilization / Cultivation), excluding card-granted *conditional* sows. Confirm the
  definition and how to distinguish it on the `before_sow` event (likely via the `PendingSow`'s
  `initiated_by_id` / provenance).

---

## Pending-ruling / extra-state cards — confirm, may need a little more

- **Plow Hero** (`plow_hero` C91, occ): *"Each time you use the 'Farmland' or 'Cultivation'
  action space **with the first person you place in a round**, you can plow 1 additional field
  for 1 food."* Same as Plow Maker **plus** a "this is my first worker placement this round"
  gate. **Open question:** does the engine expose "is this my first placement this round"? If not,
  this needs a small piece of state or a derivation (e.g. workers-placed-this-round). Confirm the
  ruling AND check the engine before building.
- **Seed Almanac** (`seed_almanac` E18, minor; cost 1 reed, prereq 4 occupations): *"Each time
  after you play a minor improvement **after this one**, you can pay 1 food to plow 1 field."*
  Event `after_play_minor`, food 1. **Wiring nuance:** it must NOT fire on Seed Almanac's *own*
  play ("after this one" = subsequently-played minors) — but `after_play_minor` fires for the
  just-played minor, and by then Seed Almanac is already in the tableau. The eligibility needs to
  know *which* minor was just played to exclude self (and confirm whether a *passing* minor like
  Market Stall counts). Check whether `PendingPlayMinor` / the event carries the played card id;
  if not, this needs a small addition. Confirm the temporal semantics with the user.

---

## Outliers — related but NOT this template

- **Mole Plow** (`mole_plow` C20, minor; cost **3 wood + 1 food**, prereq round 9+): *"Each time
  you use the 'Farmland' or 'Cultivation' action space, you can plow 1 additional field."* The
  granted plow is **free** — the only food is in the **play cost** (already liquidation-payable
  via the central minor path). So this is the **Assistant Tiller** template (an optional trigger
  that pushes a free `PendingPlow`), not the pay-food template. Build it by copying
  `assistant_tiller.py`, filtered to `{farmland, cultivation}`, with no food in the grant.
- **Dung Collector** (`dung_collector` E90, occ): *"Each time you get 2 or more newborn animals,
  you can pay 1 food to plow 1 field."* The pay-food→plow body is identical, BUT there is **no
  existing trigger event** for "newborn animals gained" (breeding happens in the harvest-breed
  phase; no `after_breed` / `newborns_gained` hook exists). **Defer** until that event is added —
  this is a `CARD_AUTHORING_GUIDE.md` §0 (new machinery), not a clean reuse.

---

## Test checklist (per card)

Mirror `tests/test_cards_category7.py` (Plow Driver) and `tests/test_cards_food_payment.py`
(Ox Goad). For each card:

1. **Registered** (in OCCUPATIONS/MINORS + the trigger event list).
2. **Offered** when the food is affordable (on hand) AND a plowable cell exists, on the right
   event/space.
3. **Offered via liquidation** — 0 food but convertible goods (the liquidation case): firing
   pushes a raise-only `PendingFoodPayment`; paying it raises the food and plows. (This is the
   defining behavior — do not omit.)
4. **NOT offered when no plowable cell** (`_can_plow` false) — even with food. (Dead-state guard.)
5. **NOT offered when the food is truly unaffordable** (0 food, no convertible goods).
6. **Direct path** — with food on hand, firing debits the food and pushes `PendingPlow`.
7. **Wrong space / wrong phase does not fire** (filter correctness).
8. **Once per use** (`triggers_resolved`): after firing + resolving, not re-offered for the same
   space use.

After each card: full suite + C++ gates green (`~/miniconda3/bin/python -m pytest tests/ -n 4
--dist worksteal`). Card-only work stays Family-byte-identical; the C++ gates should pass
untouched. Update `CARD_IMPLEMENTATION_PLAN.md` status.

---

## Definition of done (per card)

- [ ] Exact text + errata/clarifications read (`python scripts/card_text.py "<name>"`) and quoted
      in the module docstring.
- [ ] **Ruling confirmed with the user** (before/after phase; space set; "unconditional"; "first
      person"; "after this one").
- [ ] Eligibility gates on `_liquidatable_to` (NOT `food >= N`), `_can_plow`, the filter, and
      `triggers_resolved`.
- [ ] `register_action_space_hook` added iff the space is atomic (Shifting Cultivator).
- [ ] `register_food_payment_resume(CARD_ID, _pay_and_plow)` registered.
- [ ] Imported in `agricola/cards/__init__.py`.
- [ ] Tests per the checklist above; full suite + C++ gates green.
</content>
