# Action / reward replacement — design brief

> **STATUS: BUILT (2026-07-16).** The reward-suppression seam and both cards (Animal Catcher C168,
> Pet Lover D138) are implemented and tested. **As built:** the seam is one helper,
> `helpers.suppress_space_reward(state)`, that a card's optional before-window replace-trigger calls
> to suppress the top action-space host's OWN reward — host-aware because the two host kinds
> represent their reward differently: an **atomic host** (`PendingActionSpace` — Day Laborer) sets a
> new `suppressed: bool` that `_apply_proceed` checks to SKIP the atomic handler (so the `taken`
> delta reads `Resources()` and food-reactors self-correct), while an **animal market** restores the
> swept animals to the space (`accumulated_amount += gained`) and zeroes `gained` (leave-on-space).
> Each card's alternate reward is a SEPARATE plain grant (`grant_animals` + resources), never routed
> through the suppressed channel. Only `PendingActionSpace.suppressed` is new engine state
> (card-only, canonical-default-skipped, Family-inert — C++ gates green untouched). The original
> brief follows unchanged, as the record of the objective and correctness properties.
>
> ---
>
> **Original brief (a handoff brief for the session that built it).** Two deferred cards let the player
> OPTIONALLY forgo an action space's normal reward for an alternate. They need a small
> "reward-suppression / replacement" seam. This doc explains the cards, the objective the seam must
> meet, and — most importantly — the correctness properties it must satisfy (the interaction with the
> Refactor A `taken` mechanism). **It deliberately does NOT prescribe a solution.**

## Scope

Exactly **two** cards, both deferred (3+/4, so not urgent):
- **Animal Catcher** (C168, occupation, [4])
- **Pet Lover** (D138, occupation, [3+])

Agrarian Fences (B26) is a **forward-compat nice-to-have** (see the end) — not required. The related
Minor-Improvement-action substitution family (Packaging Artist C140, Recruitment D21, Ambition E24)
is being handled as a separate effort and is out of scope here.

## The two cards

**Animal Catcher (C168):** *"Each time you use the 'Day Laborer' action space, instead of 2 food, you
can get 3 different animals from the general supply. If you do, you must pay 1 food each harvest left
to play."*
- Optional. On Day Laborer: **forgo the 2 food**; take 1 sheep + 1 boar + 1 cattle from the general
  supply; and take on a persistent tax of 1 food at each remaining harvest.
- Host: **Day Laborer is an ATOMIC space** — its handler grants a fixed `+2 food`.

**Pet Lover (D138):** *"Each time you use an accumulation space providing exactly 1 animal, you can
leave it on the space and get one from the general supply instead, as well as 3 food and 1 grain."*
(Clarification: may use Animal Dealer A147 to acquire a second animal of the taken type.)
- Optional. On an animal market holding exactly 1 animal: **leave that animal on the space** (do not
  sweep it); instead take an equivalent animal from the **general supply** + 3 food + 1 grain.
- Host: **the animal markets are NON-ATOMIC hosts** — the accumulated count is staged on the market
  frame's `gained`.

## The objective

Build an **optional, player-chosen replacement of an action space's normal reward with an alternate**.
When the player chooses it:
1. the space's **normal reward is genuinely NOT received** (suppressed), and
2. an **alternate reward is granted from the general supply**, possibly with a side cost.

When the player declines, the space resolves normally. That's the objective — *not* a solution. The
open design question is **how to make the suppression genuine at each host type** (atomic vs market),
and where the player's choice lives.

## Correctness properties the solution MUST satisfy

Genuine suppression matters because **downstream reactors read what was actually received from the
space**. Refactor A records this: for an ATOMIC space, `PendingActionSpace.taken` is the `Resources`
delta the player obtained from the space's own effect; for a MARKET, the take is the frame's `gained`.
Cards key off these. So:

1. **Animal Catcher must neutralize Kindling Gatherer.** Kindling Gatherer ("each time you get food
   from an action space, +1 wood") fires as an `after_action_space` auto reading `taken.food >= 1`.
   If Animal Catcher genuinely suppresses Day Laborer's 2 food (grants animals instead), then
   `taken.food == 0`, so Kindling Gatherer — and every other "each time you get food from an action
   space" reactor — **does not fire, with zero special-casing**. So the seam's whole job on the atomic
   side is to make Day Laborer actually grant 0 food; the `taken` delta and the reactors self-correct.
   *(This is the payoff of the delta-based `taken` design — it reflects what really happened,
   replacement included.)* The 3 animals come from the general supply, so a "get an animal (any
   source)" reactor still fires on them — correctly.

2. **Pet Lover must neutralize any "animal(s) taken from an animal market" reactor** (if/when such a
   card exists). Because Pet Lover **leaves the market's animal on the space**, the market's take is
   nothing — so its `gained` must read 0, and a card keying on "each time you take/get an animal from
   an animal market" (via `gained`) must **not** fire. Note the distinctions the seam must preserve:
   the space is still **used** (a worker is placed), so "each time you use [the market]" reactors
   (e.g. Milk Jug, German Heath Keeper) **still fire**; and the replacement animal comes from the
   general supply, so "get an animal (any source)" reactors **do** fire on it. Only the
   *taken-from-the-space* channel is zeroed.

**In one line:** after the replacement, the space's own reward channel (`taken` for an atomic space,
`gained` for a market) must read "nothing received from the space," while the alternate is a separate
general-supply grant.

## The two host types the seam must span

- **Atomic (Animal Catcher / Day Laborer):** the atomic handler grants a fixed reward. Suppression =
  make it grant nothing (so the Refactor A `taken` delta is 0). The player's opt-in is a before-window
  choice that must reach the take at `Proceed` (today the atomic handler `_resolve_day_laborer` is a
  fixed `+2 food` with no override seam — that's the missing piece, and why the card is deferred).
- **Non-atomic market (Pet Lover):** the take is staged on the frame's `gained`. Suppression = do not
  sweep the market's animal (leave it on the space; `gained` = 0), and grant the alternate from supply.

A single, small seam should reach both paths.

## Side pieces (standard, not the hard part)

- Animal Catcher's **per-harvest 1-food tax** — a persistent feeding-phase cost, latched on when the
  option is taken (a `register_feeding_requirement` fold or a harvest-window charge).
- Both alternate rewards route their animals through `helpers.grant_animals` (accommodation barrier).

## Forward-compat nice-to-have (not required)

**Agrarian Fences (B26, minor):** *"Each time you use the 'Grain Utilization' action space, you can
take a 'Build Fences' action instead of one of the two actions provided by the action space."* This is
an **action substitution** (replace a *granted sub-action* with a different action), not a goods-reward
suppression. If the seam generalizes to "replace a granted action/sub-action with an alternate," it
would cover this too — a nice bonus, **but not necessary** for Animal Catcher / Pet Lover. Do not let
it complicate the two in-scope cards.

## Pointers

- The `taken` mechanism: `agricola/pending.py` (`PendingActionSpace.taken`) + `agricola/engine.py`
  (`_apply_proceed`, the delta stamp) — read this first; it's why property (1) falls out for free.
- Day Laborer's handler: `resolution._resolve_day_laborer` (the fixed `+2 food` to override).
- Market take + `gained`: `resolution._initiate_sheep_market` / `_pig_market` / `_cattle_market`.
- The deliberate boundaries this brief lives against: `CARD_ENGINE_IMPLEMENTATION.md` §8; the defer
  cluster it belongs to: `CARD_DEFERRED_PLANS.md`.
