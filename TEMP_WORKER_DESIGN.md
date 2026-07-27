# TEMP_WORKER_DESIGN.md — the supply-loaner mechanism (an extra worker beyond the household)

> **Status: MECHANISM BUILT (2026-07-24); 3 of 7 cards remain.** Specifies the **supply-loaner**
> mechanism: a family of cards that give a player an *extra* worker, drawn from their meeple
> **supply**, to place for one round without it ever becoming a family member.
>
> **THE FAMILY IS COMPLETE (2026-07-26).** Built and green: the shared mechanism —
> `PlayerState.temp_workers_active`, `helpers.activate_temp_worker`, the ordinal counter
> `PlayerState.placements_this_round` (ruling 79 — see CARD_ENGINE_IMPLEMENTATION.md §6), the
> start-of-turn offer seam `cards/turn_offers.py`, the `engine._can_act` outstanding-offer
> widening of the turn flow, and the returning-home restore — plus all four buildable cards:
> **Motivator E93** (first-turn offer), **Telegram A22** (scheduled future round, offer at the
> owner's last usable moment), **Work Permit D22** (meeple parked at play time — supply debited
> early, growth blocked until its round), and **Delayed Wayfarer E125** (one-shot offer at the
> all-players-placed boundary; its loaner is visible to the `end_of_work` readers — Iron Hoe
> integration-tested). The other three are excluded: Guest Room E22 banned as too powerful
> (user, 2026-07-24), Walking Boots B22 and Nightworker C125 wontfix. As-built reference:
> CARD_ENGINE_IMPLEMENTATION.md §1, the 2026-07-24 and 2026-07-26 entries.
>
> Dated rulings quoted here are the user's, given 2026-07-21 and 2026-07-24.

---

## 1. Scope — the supply-loaner family, and the four families it is NOT

A **supply loaner** is a meeple a player takes from their **supply** to act as a worker for one
round **without ever becoming a family member**. It is placed like a normal worker (it takes a
real action space, performs the whole action, and blocks the space), then returns to supply at the
end of the round — never fed, never scored, never part of the family. Seven cards across decks A–E
do exactly this; they are the subject of this document.

The point of building **one shared mechanism** rather than seven bespoke cards: all seven share
the same state (a borrowed supply meeple), the same end-of-round return (back to supply), and the
same interaction with Family Growth (the borrowed meeple physically blocks growth to a 5th
person). They differ only in **when** the loaner is placed, **where** it may go, and small
per-card riders. §5 is the shared mechanism; §2 is the per-card variation.

### Four adjacent families look similar but are different mechanisms — all OUT of scope here

The prior draft's central mistake was treating these as one problem. They are not. Each is named
by its mechanism, not by this document's structure, so the distinctions survive out of context:

| Family | Defining move | Members | Why it is NOT a supply loaner |
|---|---|---|---|
| **Early-newborn** | a *newborn* acts the round it is born (normally it waits a round) | Adoptive Parents (A92) | the extra worker is a **real, permanent family member**, not a borrowed supply meeple. Shares this doc's *turn-budget* problem (§5) but none of its supply-pool state. A user call whether to fold it in (§7). |
| **Consecutive-placement** | place two of your **own household** workers in a row, without the opponent interleaving | Lasso (B24), Stock Protector, Carriage Trip, Brotherly Love, Inner/Outskirts Director, Ravenous Hunger, Bassinet, Lazy Sowman, Spin Doctor, Canal Boatman (built) | no supply meeple, no extra worker — a normal family worker, placed off the normal alternation. **This** is the "don't advance `current_player`" mechanism the old draft mis-assigned to Motivator. |
| **Worker-reuse / relocate** | give an **already-placed** worker a second action (move it, or use it again) | Archway (D51), Straw Hat (E10), Swagman, Mummy's Boy | the worker is already on the board; nothing new is placed. Archway rides the existing card-as-action-space machinery (`card_spaces.py`). |
| **Skip-and-defer** | on your turn, decline a placement, take a benefit, and place that worker **later** | Tea House (D53), Oyster Eater (D134), Sour Dough (E62) | reduces/reschedules placements rather than adding one — the inverse of a loaner. (Sour Dough's payoff is a granted Bake Bread action; same skip-and-defer placement mechanic as Tea House.) |

**Explicitly dropped as irrelevant:** the "take an action *without placing a person*" cards
(Wood Saw E14, Steam Plow, Stable Cleaner, Recreational Carpenter, Stone House Reconstruction,
Elder, and the implemented Heart of Stone / Sundial / Master Renovator). No meeple is involved at
all — they grant an action directly and have nothing to do with a worker outside the family. The
old draft listed Wood Saw only as a "boundary marker"; it caused more confusion than it prevented.

---

## 2. The build set — the seven supply-loaner cards

None are implemented. They are **not uniform**: each carries a rider of varying weight beyond the
loaner itself, and the "cleanest" cards (loaner and little else) are the natural first targets.

| Card | Deck/# | Tag | Recurs? | When the loaner is placed | Where it may go | Return semantics | Rider beyond the loaner |
|---|---|---|---|---|---|---|---|
| **Motivator** | E93 | 1+ | every round | on the player's **first turn** | any legal space | → supply at returning-home | gated on **"no unused farmyard spaces"** (fence-aware — §6) |
| **Delayed Wayfarer** | E125 | 1+ | play round (likely — §7) | **after all people placed** this round | any legal space | → supply | on-play: +1 building resource of choice |
| **Guest Room** | E22 | — | every round | any time, **once per round** | any legal space | → supply | must **discard 1 food** banked on the card to place; on-play banks food |
| **Nightworker** | C125 | 1+ | every round | **before each work phase** (prep window) | a **building-resource accumulation space** not in your supply | → supply | placement target is constrained to an accumulation space |
| **Walking Boots** | B22 | — | play round | **immediately on play**, mandatory (per errata) | any legal space | **REMOVED from play** — permanent | on-play +2 food; the removed meeple caps your family below 5 forever |
| **Telegram** | A22 | — | play round | in the round you **advance to** | any legal space | → supply | **advances the round marker** +1 per fence in supply; prereq ≥1 fence in supply; cost 2 food; 1 VP |
| **Work Permit** | D22 | — | play round | in the round you **advance to** | on the **round space** you advanced to | → supply | **advances the round marker** +1 per building resource; prereq ≥1 building resource |

Notes that shape the build:

- **Return semantics are not uniform.** Six return the loaner to supply at the returning-home
  phase (growth reopens next round). **Walking Boots removes it from play permanently** — the
  same shape as Lodger's round-9 eviction: `workers_in_supply` is decremented and *never*
  replenished, so the family cap drops to 4 forever ("you may never grow to 5 people", per its
  clarification). Whatever field tracks placed loaners must distinguish "return to supply" from
  "remove from game".
- **Placement target is not uniform.** Most place on any legal space; **Nightworker** is confined
  to a building-resource accumulation space, **Work Permit** to the round space it advanced to.
- **Two cards carry a round-advancement rider** (Telegram, Work Permit: "add 1 to the current
  round for each …"). That is its own non-trivial mechanism, orthogonal to the loaner, and likely
  the harder half of those two cards. Treat it as a separate design concern; the loaner mechanism
  should not wait on it.
- **Three cards are marked `status: wontfix`** in `agricola/cards/data/*.json` (Guest Room,
  Nightworker, Walking Boots). Per CLAUDE.md the JSON status is a *lagging* tracker, not an
  authoritative decision — but it is a signal these were looked at and set aside before. Confirm
  intent with the user before scoping them in (§7).

**Suggested implementation order** (cleanest loaner first, riders last): Motivator → Delayed
Wayfarer → Guest Room → Walking Boots (adds remove-from-play) → Nightworker (adds
accumulation-target) → Telegram / Work Permit (add round-advancement). This is a suggestion, not a
decree — the user sets priority.

---

## 3. Ruled semantics

### The loaner reading (user, 2026-07-21)

- **The loaner is a borrowed worker for one round.** It is placed like a worker, returns to
  **supply** (not home) in the returning-home phase, never becomes a family member, requires no
  food (it is back in supply before any harvest), and scores nothing. (Walking Boots is the one
  variant: its loaner is *removed from play* rather than returned — §2.)
- **The physical-meeple constraint.** A player owns exactly 5 meeples. While the loaner is on the
  board it occupies a supply meeple, so **Family Growth to a 5th member is illegal while no free
  supply meeple remains**. Declining the loaner offer to keep growth open can therefore be
  strictly optimal — so **the offer must always be declinable** (consistent with the standing
  rule that granted actions are optional; every one of these cards says "you can" — Walking Boots'
  errata-mandatory placement is the exception, and it is mandatory-*with*-no-choice, not a grant).

### Rulings settled 2026-07-24 (this document's rewrite)

- **A loaner advances the "Nth person you place this round" ordinal — YES** (plain reading of the
  card text). Consequence: this is a *live* interaction with cards **already in the codebase**.
  Five ordinal readers are shipped — Wheel Plow, Plow Hero, Second Spouse, Henpecked Husband,
  Fir Cutter — and a loaner **can** be, e.g., Henpecked Husband's "second person you place." So
  the ordinal counting (§4 idiom) must include loaner placements; this cannot be deferred as a
  future-card concern.
- **Returning a loaner "home" mid-round makes it placeable again — it is not a hard question.** A
  returned worker is available to place again; that is the entire benefit of returning it (Sheep
  Inspector, Tea Time). The prior draft posed a false dichotomy ("supply for the rest of the round
  *or* placeable again"). The answer is unambiguously *placeable again*. The one real (confirming)
  wrinkle: a returned loaner does **not** go back to supply until the returning-home phase, so it
  keeps occupying its supply meeple and **growth stays blocked until round end** — exactly the
  physical model.
- **Motivator's sequencing: the loaner is placed FIRST.** "On your first turn each round … you can
  place a person from your supply" means the loaner is the player's first placement of the round;
  the household workers follow on subsequent turns under **normal alternation**. There is **no**
  "two placements in one turn" — that resolves the prior draft's §6 open question for Motivator
  (and re-bases the mechanism — §5). The other six cards each specify their own placement instant
  (§2); this ruling is Motivator-specific.

---

## 4. State model

### The pool already exists — growth-blocking is free (verified against the engine)

`PlayerState.workers_in_supply` (`state.py:338`, default `3`) is a **stored** field: the pool a
Family Growth draws from. It is already the growth gate — growth is legal only while it is `> 0`
(`legality.py:1049`, `1063`) — decremented at the single growth chokepoint `_grow_family`
(`resolution.py:301`), hash-included (`state.py:369`), serialized, and mirrored in the C++
PlayerState. It is *not* derived as `5 − people_total`, precisely because a card can remove a
meeple from the game (Lodger; and Walking Boots — §2).

**The loaner borrows from this existing pool:**

- Placing the loaner: `workers_in_supply -= 1` (the meeple leaves supply onto the board).
- Returning-home reset: `workers_in_supply += (loaners returned)` — but **not** for a
  removed-from-play loaner (Walking Boots), which never comes back.
- **Growth-blocking needs no new legality code at all.** The existing gate reads the field, so a
  player at 4 family with a loaner out has `workers_in_supply == 0` and growth is already illegal —
  exactly the physical game. This is the prior draft's one correct load-bearing insight, and it
  holds.

Because this only changes the *value* of an already-serialized field, it needs **no canonical
change and no C++ change** on the field's account (card content never runs in C++).

### The one new field: `temp_workers_active` (AS BUILT)

A **card-only** `PlayerState` field, **`temp_workers_active: int = 0`** — how many loaner meeples
this player has in play this round. Default-skip in `canonical._DEFAULT_SKIP_FIELDS` and added to
`PlayerState.__hash__`, so the Family game stays byte-identical and the C++ gates stay green
untouched. Written at exactly two sites: `helpers.activate_temp_worker` and the returning-home
restore.

**A COUNT, not identities.** An earlier draft proposed a tuple of the space ids loaners stand on,
to let a mid-round "return a person" effect (Sheep Inspector, Tea Time) tell a loaner from a
family member. That is unnecessary and was actively harmful: once activated, a loaner is
**fungible** with a family worker (identical wooden tokens), and returning either does the same
thing — `people_home` +1. Worse, the tuple *loses* a returned loaner (it leaves the tuple while
still being out of supply), so the round-end restore would silently destroy a supply meeple. A
return is **loaner-count-neutral** by construction, which is exactly why the count is enough.

**Why the count is STORED and not derived.** The tempting derivation
`people_home + markers − people_total` is **unsound**, for two verified reasons:

- **No-space newborns.** Nine cards grant family growth that occupies no action space
  (`PendingFamilyGrowth(place_on_space=False)` — Heart of Stone, Autumn Mother, Bed in the Grain
  Field, Bed Maker, Stork's Nest, Little Stick Knitter, Godmother, Family Friendly Home, and
  Sheep Inspector's variant). Each raises `people_total`/`newborns` while placing **no marker**,
  and `newborns` does not distinguish them from wish-space newborns, so the correction term is
  unrecoverable. **Family Friendly Home fires on `before_build_rooms` — mid-WORK** — so this is
  reachable during placement, not just at a phase boundary.
- **Lodger's eviction.** It drops `people_total` at the round-9 `returning_home` window without
  clearing the evicted meeple's board marker (harmless today only because the reset wipes all
  markers a moment later). A derived count would read a phantom loaner there and credit a supply
  meeple that no longer exists — in games with **no loaner card at all**.

The same finding killed a marker-based ordinal (`markers − newborns`), which reads one low after
a no-space birth; the shipped `(people_total − newborns) − people_home` form is the robust one,
and the loaner term is added to it rather than replacing it.

**Why the loaner DOES pass through `people_home`.** `people_home` is widened from "family members
at home" to "**meeples available to place this round**". Feeding (`2·people_total − newborns`) and
scoring read `people_total`, which the loaner never touches, so it stays unfed and unscored. But
alternation, the all-placed gate, the placement enumerator's `people_home < 1` early-out, and
mid-round return effects are all keyed on `people_home` — so putting the loaner there means every
one of those paths handles it **unchanged**, with no special-casing anywhere.

### No "pending loaner" state is needed

An earlier draft worried the turn flow must track a player *owed* a loaner placement. For
Motivator it does not: the offer and its answer both happen at a turn the player is already
taking, so there is never a gap where a loaner is owed but unplaced. What the offer *does* need is
a **latch** (`used_this_round`, set by the resolver on **both** options) — see §5.

---

## 5. The mechanism — an extra worker in the normal turn flow

**This is where the prior draft was wrong.** It framed the hard part as "scheduling a placement
that is not the player's normal one-per-turn move" and leaned on freezing `current_player` so the
same player places twice in a row. That is the **consecutive-placement family's** mechanism (Lasso
— §1), and it is not what a supply loaner needs. A loaner is simply an **extra worker the player
places on a normal turn**; the alternation is untouched.

### The seam, as built: activation, then the ordinary placement path

The work phase is an alternation over `people_home`:

- `_advance_current_player` (`engine.py`) rotates to the next player with `people_home > 0`.
- the work phase ends when `all(p.people_home == 0 for p in state.players)`, flipping to
  RETURN_HOME.
- and `legal_placements` early-outs with no actions at all when `people_home < 1`.

Because activation puts the loaner **into `people_home`** (§4), all three keep working untouched:
the player simply has one more meeple, takes one more turn, and the work phase waits for it.

**The offer** is a `PendingCardChoice` ("take" / "decline") pushed at the WORK-phase decision
boundary *before* the player places — the instant Motivator's "on your first turn" names. That
frame was chosen because it is options-only (so "decline" is just an option rather than needing a
`Stop` path), its resolver both applies the choice and pops the frame, and it is **already** exempt
from the turn-alternation trigger — so answering the offer does not hand the turn to the opponent.

**The latch is a liveness requirement.** Eligibility is re-tested at every WORK decision boundary,
so an offer whose eligibility survived a *decline* would be re-pushed immediately and forever — the
player declines, nothing about the state moved, the offer returns. The resolver therefore sets
`used_this_round` on **both** options. It is not merely a "once per round" nicety; without it the
round cannot end. (It also stops a mid-round return from re-opening the window by dropping the
placement count back to 0.)

**Deferred to the remaining cards:** a loaner offered when the player has **no** household workers
left (Delayed Wayfarer's "once all people have been placed") is the one shape this does not yet
cover — there, `all(people_home == 0)` is exactly the work-phase-end condition, so the two turn-flow
predicates would have to consult an outstanding offer. The engine **anticipated** it:
`_advance_current_player`'s comment reads *"Future cards may allow placing with `people_home == 0`
… the predicate below would need to consult those card states at that time."* See §7.

### Consequences

- **The loaner placement reuses the entire existing placement pipeline** — space hosts, atomic
  handlers, sub-stacks, card triggers — unchanged, because it *is* an ordinary placement of an
  ordinary meeple.
- **The loaner fires other cards' before/after action-space events like any placement.** It is a
  real use of a space and blocks it.
- **Order is the player's.** Having activated, the player holds N+1 fungible meeples and places
  them in whatever order they like; nothing pins the loaner to a particular turn.

---

## 6. Touch-point checklist (all BUILT unless marked)

1. **Activation** — `helpers.activate_temp_worker`: `workers_in_supply` −1, `people_home` +1,
   `temp_workers_active` +1. `people_total` untouched. No placement-executor change at all: the
   loaner is placed by the ordinary path.
2. **Returning-home reset** (`_return_home_reset`, the `people_home = people_total` site):
   `workers_in_supply += temp_workers_active`, then zero the count. `people_home = people_total`
   already drops any loaner still at home, and the blanket marker wipe clears the board. Both
   edits are no-ops at count 0, so Family stays byte-identical.
3. **Growth legality** — **no change needed**, verified: the wish gate already reads
   `workers_in_supply`. Tested both ways — taking the loaner with one meeple left makes Basic Wish
   illegal; declining leaves it legal; with two meeples in supply, taking still leaves growth open.
4. **Ordinal readers** — `helpers.placements_this_round` is the single definition, with the loaner
   term included; six cards migrated onto it (§ the ordinal note in §4). Pinned by
   `tests/test_placements_this_round.py`, including an exhaustive equivalence check against the
   pre-loaner expression so the migration is provably a refactor.
5. **Mid-round return effects** (Sheep Inspector D93, Tea Time E3) — **no loaner awareness needed**:
   a return is loaner-count-neutral (`people_home` +1, count unchanged), so the borrowed meeple
   stays borrowed and growth stays blocked until the reset. End-to-end conservation test in
   `tests/test_card_motivator.py`. (Calibration ruling, 2026-07-21: Sheep Inspector can return the
   worker parked on Canal Boatman's card.)
6. **Cards reading live occupancy** (Swimming Class at `returning_home`; occupancy-conditioned
   triggers) — the loaner is a real occupying worker; lean no special handling.
6. **Cards reading live occupancy** (Swimming Class at `returning_home`; occupancy-conditioned
   triggers) — the loaner is a real occupying worker; no special handling.
7. **Canonical / hash** — `temp_workers_active` default-skip + hash-included; `workers_in_supply`
   already serialized. Family byte-identity preserved and the C++ gates green untouched.
8. **Web UI** — NOT DONE. Space worker counts already render, but the take/decline prompt shows as
   a bare card-choice and there is no supply-meeple indicator, so the growth-blocking tradeoff the
   card is *about* is invisible to a human player.

---

## 7. What the remaining three cards still need

Motivator is built; these are what each of the others requires **on top of** the shared mechanism.

**Telegram (A22)** — its loaner lands in a specified future round, and by the deferral argument
below the offer should be surfaced at the last usable moment in that round, which is after the
player's own workers are exhausted. That needs the two turn-flow predicates extended
(`_advance_current_player` and the all-placed gate) to grant a player one more turn while an offer
is outstanding, plus the placement enumerator's `people_home < 1` early-out. It also carries the
**round-advancement rider** ("add 1 to the current round for each fence in your supply, and mark
that round space"), which is a separate scheduling mechanism, not a loaner one.

**Work Permit (D22)** — the same rider, plus the meeple is parked **on the round space at play
time** (so it is out of supply, and growth is blocked, from then until that round). The parked
meeple must be card state, **not** a board worker marker, or it will be miscounted; and its
activation in the target round must not debit supply a second time.

**Delayed Wayfarer (E125)** — fires once **all players'** workers are placed, which is the
end-of-work boundary and therefore gated on the timing-ladder ordering pass the user flagged
(several cards say variously "after all players place", "at the end of the work phase", "right
after the work phase"; the engine already has ordered round-end rungs to classify them onto).
Its recurrence is also unsettled — the text reads one-shot ("when you play this card … this
round") versus Motivator's explicit "each round".

**Not being implemented:** Guest Room E22 (banned as too powerful — user, 2026-07-24), Walking
Boots B22 and Nightworker C125 (`wontfix` in the card data).

**The deferral argument (why a wide-window offer belongs at the last moment).** Activating a loaner
never grants a placement *now* — the player still places one meeple per turn — so accepting early
buys nothing and only forecloses growth sooner. Deferring therefore weakly dominates, and every
earlier offer would be a dominated choice inflating the action set. Motivator is exempt because its
text pins the decision to the first turn. The precondition to re-check before relying on this: no
card may make *early* activation valuable (one triggering on "placing a person from your supply",
or rewarding a low supply pile) — none exists today.

**Boundary, still a user call:** **Adoptive Parents (A92)** lets a *newborn* act the round it is
born. It shares the "extra worker beyond the household" feel but none of the state — the extra
worker is a real, permanent family member, so it flows through `people_home`/`people_total` with no
loaner bookkeeping at all. Recommended to keep separate.

---

## 8. Test coverage (as built)

`tests/test_placements_this_round.py` (13) — the shared ordinal: the base count; **both** newborn
shapes, including the no-space birth that rules out a marker-based count; the loaner term (a loaner
is the first person placed, the next family worker the second); an activated-but-unplaced loaner
not counting; and an exhaustive equivalence check against the pre-loaner expression across every
reachable `(people_total, people_home, newborns)`, which is what makes the six-card migration a
provable refactor rather than a hopeful one.

`tests/test_card_motivator.py` (18) — the offer surfaces on the first turn with both options;
taking moves supply → hand with `people_total` untouched; declining changes nothing; **answering
the offer does not end the turn** (no alternation); the offer is not repeated after either answer
(the liveness pin); eligibility boundaries (no card / an unused farmyard cell / no supply meeple /
not the first turn); **the growth fork both ways** — taking blocks Basic Wish with one meeple left,
declining leaves it legal, and with two in supply taking still leaves growth open; the loaner as
ordinal 1; **5 placements versus 4** over a real round; the returning-home restore with meeple
conservation (`people_total + workers_in_supply` back to 5) and the loaner *not* left at home; the
offer returning in a later round; and **Sheep Inspector returning a worker mid-round**, still
conserving meeples — the case that killed the identity-tracking design.

Family byte-identity: full suite **6891 passed**, including all **139** C++ differential gates,
untouched.

**Not covered** (needs the remaining cards): the work phase staying open for a loaner when
`people_home == 0` for everyone, and a loaner's interaction with feeding at a harvest round (it is
structurally absent — `people_total` never moves — but there is no end-to-end harvest test).

---

## 9. What changed from the prior draft, and why

The prior draft (2026-07-21) is superseded on two counts; its §3 supply-pool discovery is the
piece that carried forward intact (§4 here).

1. **It conflated three mechanisms.** "Extra placement" was treated as one problem spanning
   Motivator (an extra worker from supply), Lasso (two of your own workers in a row), and Canal
   Boatman (a worker parked on a card). These are three different mechanisms with different state
   and different control flow (§1). This document scopes to the **supply-loaner family only** and
   names the other three as explicitly separate.
2. **It built the control-flow analysis around the wrong mechanism.** Its §5 leaned on "don't
   advance `current_player`" so a player places twice back-to-back — which is the
   consecutive-placement (Lasso) mechanism. A supply loaner is instead an **extra worker in the
   normal alternation**, integrated at the two `people_home`-keyed predicates (§5). The correction
   follows from the user's 2026-07-24 ruling that Motivator's loaner is placed *first* under normal
   turn order, not back-to-back with a household worker.

Along the way this rewrite also: completed the card list (the prior §8 was flagged incomplete and
missed Telegram, Work Permit, Delayed Wayfarer, Guest Room, and Nightworker); settled the two
"open questions" the prior draft over-thought (the ordinal and mid-round-return questions — §3);
surfaced the per-card riders that make the seven non-uniform (§2); and dropped the irrelevant
"without placing a person" cards.

### Two further corrections made during the build (2026-07-24)

3. **Identity tracking was dropped.** Both drafts proposed recording *which spaces* loaners stand
   on. Unnecessary — an activated loaner is fungible with a family worker, and returning either
   does the identical thing — and actively wrong: a returned loaner leaves such a record while
   still being out of supply, so the round-end restore would destroy a supply meeple. A count
   suffices, because a return is count-neutral (§4).
4. **The count is stored, not derived.** An intermediate design derived it from
   `people_home + markers − people_total`, which is unsound: nine cards grant family growth with
   no action space (raising `people_total`/`newborns` while placing no marker, one of them
   mid-WORK), and `newborns` cannot distinguish those; Lodger's eviction breaks it independently.
   The same finding rejected a marker-based ordinal and kept the shipped
   `(people_total − newborns) − people_home` form, with the loaner term added to it (§4).
