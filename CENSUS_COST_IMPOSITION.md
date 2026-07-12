# Census: cost-imposing cards (taxes on otherwise-free actions)

> **Corpus artifact (2026-07-09).** Full sweep of `agricola/cards/data/*.json` (840 cards,
> decks A–E, both types) for `PLACEMENT_REACHABILITY_DESIGN.md` §4b's spending-trigger /
> stranding-guard analysis. Question: which cards impose a MANDATORY cost on an action
> that is otherwise free (owner's or an opponent's)? Excluded by scope: priced-optional
> benefits ("you can pay 1 food to plow"), a card's own play-cost surcharges, and
> feeding-requirement folds (Child's Toy). Verbatim text via
> `python scripts/card_text.py <slug>`; implemented = `agricola/cards/<slug>.py` exists.

## Headline

**8 in-scope cards; none implemented.** So today every tax is hypothetical: the
free-mandatory hosts (Farmland, Day Laborer, the accumulation takes) are genuinely immune
to the Writing-Desk stranding pattern, and placement predicates need no AND-side yet.
Each future member below names the seam it will need.

## The 8, by shape

**Owner self-tax on free mandatory work (1 — the important one):**
- **Dwelling Mound (C37, minor)** — *"From now on, you must pay 1 food for each new field
  tile that you place in your farmyard."* Clarification: must be able to pay BEFORE
  placing. Turns every plow's field placement into a 1-food charge (any source: Farmland,
  Cultivation, granted plows, field-granting cards). **Seam needed when implemented:** a
  plow/field-placement cost chokepoint (`action_kind`-style) consulted by `_can_plow`,
  every plow-granting trigger's eligibility, and the stranding guards — plow currently has
  no cost concept anywhere.

**Opponent-taxed base spaces (2):**
- **Fishing Net (C51, minor)** — opponent must first pay the OWNER 1 food to use Fishing
  (and the Fishing food itself may not fund the payment — an ordering rule). AND-side
  placement check + a player-to-player transfer.
- **Forest Guardian (B138, occ 3+)** — before another player takes ≥5 wood from any wood
  accumulation space, they must first pay the owner 1 food. AND-side, quantity-conditioned.

**Card-created toll spaces (3):** Chapel (A39), Forest Inn (B42), Alchemists Lab (E81) —
"an action space for all"; opponents must first pay the owner 1 grain/food. Already in the
long-tail defer family "new shared action spaces"; the toll is an AND-side pre-pay on that
future machinery.

**Recurring upkeep / penalty on the owner (2):**
- **Credit (A54, minor)** — 5 food now; at the end of each non-harvest round pay 1 food or
  take a begging marker. Round-end family (`PendingRoundEnd` defer).
- **Animal Catcher (C168, occ 4+)** — opting for 3 animals at Day Laborer commits the owner
  to 1 food per remaining harvest. Opt-in benefit with a mandatory recurring tail.

## Near-misses worth remembering

- **Skimmer Plow (E17)** — "each time you sow, you must place 1 fewer good per field": the
  only mandatory downside on a free owner sub-action, but a yield reduction, not a payment.
- **Forest Owner (C162)** — "must give you 1 wood" is paid from the SUPPLY, not by the
  actor; mandatory wording, no tax.
- **Shaving Horse (A48, wontfix) / Potato Ridger (A59, implemented)** — forced conversions
  triggered by stockpile thresholds (net the owner food); not action taxes.
- **Tree Inspector (D116)** — event-triggered loss of card-held wood; not an action cost.

## Consequences recorded in the design doc

1. Today's guard scope: costly-mandatory hosts only (Lessons, the improvement space, the
   two renovation spaces, Fencing, Grain Utilization).
2. Guards and legality must price mandatory work **through chokepoints** so a future
   Dwelling Mound flows in automatically instead of re-auditing every guard by hand.
3. Fishing Net-style pre-pays are the AND-side seam's first real members; the payment is a
   transfer to the owner, with Fishing Net's "not from the space's own food" ordering rule.
