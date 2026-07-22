"""Field Merchant (occupation, Bubulcus Expansion; deck B #103; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 wood and
1 reed. Each time you decline a \"Minor/Major Improvement\" action, you get
1 food/vegetable instead."

Printed clarifications (verbatim): "Merchant C096 does not double a decline.
Stone Company A023 improvements are conditional on spending stone and can't be
declined. 《You can place onto the "Major Improvement" or "Improvement" (6p)
action space just to decline it.》"

GOVERNING RULING — USER RULING 74, 2026-07-21 (CARD_DEFERRED_PLANS.md, quoted):
"Field Merchant (B103) — corrected reading (user): declining a **'Minor
Improvement' action** → 1 food; declining a **'Major or Minor Improvement'
action** → 1 vegetable. Detection keys on the NAMED actions wherever they occur
— spaces and declinable card grants (Sample Stable Maker, Angler); **Equipper is
excluded** per its printed clarification ('This effect is not a "Minor
Improvement" action') (user). Exiting an improvement action you **could not use
counts as declining** (user) — Meeting Place with no playable minor pays, and
placing on the Major Improvement space with nothing affordable must be legal
(ownership-gated placement extension + a decline route on the composite host)."
The card text's slash is the standard correlation, expanded by the user in
exactly those words: "Minor/Major Improvement" action ↔ "1 food/vegetable".

How each clause maps onto the machinery:

- **On-play**: +1 wood +1 reed, a plain add.

- **The decline income** registers on the improvement-decline registry
  (`triggers.register_improvement_decline_income`); the DETECTION lives at the
  engine's decline seams, each a moment a named improvement action was
  offered-and-not-taken, each calling `note_improvement_action_declined(state,
  decliner_idx, kind)` exactly once per decline event:
    - Meeting Place / Basic Wish for Children exited (Proceed) with the minor
      branch unchosen -> "minor" (whether or not a minor was playable — the
      could-not-use ruling).
    - A granted NAMED minor action (`PendingGrantedSubAction` with
      `minor_is_action=True` — Sample Stable Maker, Task Artisan) popped via
      Stop with play_minor never entered -> "minor". The flag-False "play a
      minor" grants (Scholar, Beneficiary, Equipper) set no named-action flag,
      so the flag-keyed detection excludes them structurally — exactly
      Equipper's printed exclusion.
    - House Redevelopment exited (Proceed) with the optional composite step not
      entered -> "major_or_minor".
    - The composite host (`PendingMajorMinorImprovement` — the Major
      Improvement space, House Redevelopment's step, Angler-style grants, a
      Merchant repeat) declined via its ownership-gated
      `ChooseSubAction("decline_improvement")` route -> "major_or_minor". The
      route completes the composite with neither branch performed and without
      opening its after-window (a declined action was not TAKEN — Small Trader
      and Merchant's repeat never fire off it).
  A named minor action converted into a major build by the Braid-Maker swap
  (`helpers.swap_play_minor_to_build_major`) is TAKEN, never declined — the
  swap fires only after the branch was chosen, which every seam's
  unchosen-branch check structurally excludes.

- **Place just to decline** (the printed clarification): with a decline-income
  card owned, `legality._legal_major_improvement_cards` and the space wrapper's
  mandatory choose admit the owner regardless of affordability, so the composite
  (and its decline route) is reachable with nothing affordable/playable. The
  House Redevelopment placement is NOT extended — its renovate is the space's
  mandatory work.

- **"Merchant C096 does not double a decline"**: no doubling logic exists
  anywhere — each decline event pays each owned decline-income card exactly
  once, including the decline of a Merchant-repeated action (itself one fresh
  decline event, paid once). Once-per-decline-event satisfies the
  clarification.

- **"Stone Company A023 improvements ... can't be declined"**: the decline
  route is withheld from a min-spend composite (`min_spend is not None` — the
  mandatory-spend constraint is the structural marker; Stone Company's own
  printed clarification agrees: "Improvement action is not declinable in order
  to use Field Merchant B103").

Played via Lessons; the on-play is the goods add. The registry is ownership-
gated at every seam ("you decline" — only the declining player's OWN cards
pay), so the Family game — where no player ever owns a card — is byte-identical
and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_improvement_decline_income
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "field_merchant"


def _grant(state: GameState, idx: int, goods: Resources) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + goods)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _on_play(state: GameState, idx: int) -> GameState:
    """'When you play this card, you immediately get 1 wood and 1 reed.'"""
    return _grant(state, idx, Resources(wood=1, reed=1))


def _decline_income(state: GameState, idx: int, kind: str) -> GameState:
    """'Each time you decline a "Minor/Major Improvement" action, you get
    1 food/vegetable instead' — the slash-correlation, per ruling 74:
    "minor" (the "Minor Improvement" action) -> 1 food;
    "major_or_minor" (the "Major or Minor Improvement" action) -> 1 vegetable."""
    assert kind in ("minor", "major_or_minor"), kind
    goods = Resources(food=1) if kind == "minor" else Resources(veg=1)
    return _grant(state, idx, goods)


register_occupation(CARD_ID, _on_play)
register_improvement_decline_income(CARD_ID, _decline_income)
