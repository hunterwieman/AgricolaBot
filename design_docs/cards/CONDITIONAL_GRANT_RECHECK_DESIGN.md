# Conditional Grants, Re-Checked on State Change — Design

**Status:** proposal / not yet built. This document specifies a general mechanism and, as its
first step, a catalog sweep that must run *before* the mechanism is finalized.

## The problem

**The principle at stake.** The engine must never prohibit a legal move a rational player might want
to make. (This is the same principle that governs the engine's option-restriction machinery
everywhere else: it may prune *dominated* choices, never *non-dominated* ones.) Some cards reward a
game-state **condition** — "if you have no food left, get 1 wood and 1 clay"; "if you have at least
1 grain field, 1 vegetable field and 1 empty field, get 3 food." A player can often take a perfectly
legal — and frequently *optimal* — action to **make that condition true** and collect the reward.
Denying that action is a bug, not a technicality.

**The bug.** Today these grants are a one-shot automatic effect (`register_auto` on a window): the
condition is evaluated **once**, the instant the window opens. If it is false then, the grant is gone
— even if the player immediately does something, legally, that makes it true.

### Worked example (Social Benefits): a good move the code forbids

Social Benefits: *"immediately after the feeding phase, if you have no food left, get 1 wood and
1 clay."* Suppose the player also owns Farm Store (*"after the feeding phase, spend 1 food for
2 different building resources"*). They finish feeding holding exactly 1 food.

The plausibly-optimal play is obvious: **spend that 1 food at Farm Store, take 2 building resources,
and — now holding no food — collect Social Benefits' 1 wood + 1 clay.** One food turned into four
goods. Nothing about it is illegal or exploitative: the food is genuinely spent, and both effects
legitimately apply "after the feeding phase." A good player makes this move.

Here is exactly how the code forbids it, step by step:
1. The `after_feeding` window opens. The engine fires the window's automatic effects **once**
   (`engine._process_band_window` → `apply_auto_effects`). Social Benefits' auto checks `food == 0`;
   the player holds 1 food, so it does **not** fire. **That was its only evaluation.**
2. *Then* the engine hosts the window's trigger frame, and the player fires Farm Store, spending the
   1 food. Food is now 0.
3. Social Benefits' auto already ran and passed in step 1, and nothing re-checks it. So "no food
   left" is now true, yet the reward is never granted. The player collects Farm Store's goods but not
   Social Benefits' — the combined play the rules plainly allow is **unreachable**.

The player is not making a mistake and not exploiting anything; the engine is simply refusing a legal,
valuable, non-dominated move because it looked at the condition one moment too early.

(A simpler version is denied even *without* Farm Store: a player holding surplus food may discard it
to reach 0 — RULES.md permits discarding goods, food included, at any time — for the same
food-for-goods reason, and the one-shot check refuses it. That specific case has a dedicated discard
trigger; the *general* problem is any condition made true after the window opens.)

**The general fix** is to re-check the condition as the state changes within the window and fire the
grant the first time it holds — exactly once, guarded by a fire-once latch.

---

## Part 1 — First, sweep the entire card base

**Do not design or build against only the two cards known today.** The first task is a systematic
sweep of the **entire** catalog (both implemented and unimplemented cards, in
`agricola/cards/data/revised_occupations.json` and `revised_minor_improvements.json`) to find every
card that fits the shape:

> a card that **grants a benefit conditional on a game-state feature being true at a particular
> moment**, where that feature **can change** between the moment the window opens and the moment the
> player finishes acting in that window.

For each candidate, classify:
1. **The condition** — what feature of the state it reads (food/goods held, animals, fields, rooms,
   board occupancy, hand contents, …) and at which window/instant it is checked.
2. **Can that feature change inside the window?** — by a trigger the player fires in that window, or
   by an "at any time" action. If yes, the card is a consumer of this mechanism. If the feature is
   genuinely fixed for the duration of the window, it is not.

### How the game state can change mid-window — illustrations, NOT a comprehensive list

The reason "rooms / animals / fields can't change mid-window" is false: cards exist that change
those very features either at a trigger point or at any time. Three concrete examples (all currently
**unimplemented** — part of the deferred at-any-time boundary — but design inputs regardless):

- **Muddy Puddles** (B83) — *"…At any time, you can pay 1 clay to take the top good"* off the card
  (which includes sheep / boar / cattle). → **animals can change at any time.**
- **Roll-Over Plow** (C18) — *"At any time, if you have at least 3 planted fields, you can discard
  all goods from one of those fields to plow 1 field."* → **fields can change at any time.**
- **Stone House Reconstruction** (E13, *"At any time, you can renovate your clay house to a stone
  house without placing a person"*) **+ Hammer Crusher** (D14, *"Immediately before you renovate to
  stone … you can take a 'Build Rooms' action"*) → **rooms can be built at any time.**

**These three are examples, not the full set.** Many other cards — implemented and not, singly and
in combination — can move animals, crops, fields, rooms, goods, or board state at a trigger point or
at any time. The sweep must find them, not assume the list above is complete.

> **The project owner is very good at coming up with these cards and card combos.** When you are
> unsure whether a particular game-state threshold can change within a window (or in what
> circumstances), **ask him** — do not guess. His input on "can feature X change at moment Y" is the
> authoritative way to decide whether a conditional-grant card is a consumer of this mechanism.

### Seed list (already identified — extend it, don't treat it as closed)

Conditional-grant cards found so far, with the feature each reads. **Live consumers today** are the
ones whose feature is **food**, because food is the only good the player can already adjust
mid-window through surfaced actions (feeding conversions, food-spend triggers, the Social Benefits
discard); the rest become consumers when/if their feature can change within the window (which the
at-any-time cards above enable):

| Card | Window / instant | Condition feature |
|---|---|---|
| **Social Benefits** (D76, impl) | immediately after feeding | food == 0 |
| **Small Animal Breeder** (C111, impl) | before round start | food ≥ round number |
| **Three-Field Rotation** (B61, impl) | start of field phase | has ≥1 grain field, ≥1 veg field, ≥1 empty field |
| Pavior (B110, impl) | end of preparation | ≥1 stone in supply |
| Childless (B114, impl) | start of round | ≥3 rooms but exactly 2 people |
| Loom (B39, impl) | field phase | ≥1/4/7 sheep |
| Milking Stool (D38, impl) | field phase | ≥1/3/5 cattle |
| Land Surveyor (D107, impl) | field phase | ≥2/4/6/7 fields |
| Bale of Straw (D61, impl) | start of harvest | ≥3 grain fields |
| Rolling Pin (D52, impl) | returning home | more clay than wood |
| Museum Caretaker (E100, impl) | start of work | ≥1 each of wood/clay/reed/stone/grain/veg |
| Cheese Fondue (E57, impl) | on Bake Bread | ≥1 sheep / ≥1 cattle |
| Milking Parlor (A57, impl) | on play | ≥N sheep / ≥N cattle |

This table is a starting point. The sweep's output is the full, classified list.

---

## Part 2 — The mechanism

Replace the one-shot conditional auto with a **re-checked conditional grant**.

### Shape

A card registers a conditional grant declaring three things:
- **`condition_fn(state, idx) -> bool`** — is the granting condition true right now?
- **`grant_fn(state, idx) -> state`** — apply the grant (goods, etc.).
- **an active scope** — the window/phase during which the condition is live and should be
  re-checked (e.g. `after_feeding`, `before_round`, or a phase span for at-any-time cases).

The engine evaluates `condition_fn` at each decision boundary **while the scope is active** and fires
`grant_fn` **the first time it returns true** — then never again for that occurrence.

### The fire-once latch

A per-card, per-occurrence "already granted" latch prevents re-firing:
- Checked before firing; set when the grant fires — **from any path**, including an associated
  optional trigger (see Social Benefits below), so the two never double-grant.
- Card-only state (Family-inert): the Family game owns none of these cards, so the latch defaults
  to an inert value, is listed in `canonical._DEFAULT_SKIP_FIELDS`, and needs no C++ change. Likely
  home: `PlayerState.card_state` (the `CardStore`), keyed so it resets at the scope boundary (per
  harvest / per round). **[Open detail — pick the reset granularity per the scope.]**

### The re-check hook

Re-evaluate the registered conditional grants at the decision boundary
(`engine._advance_until_decision`), **scoped**: only the grants whose declared scope is currently
active, and only those not yet latched. This keeps it cheap — it is not "re-run every auto after
every action," it is "re-check this small registry of live conditional grants." A grant whose
condition newly holds fires and latches; the rest wait.

Because the check runs at the decision boundary after *every* applied action, it catches the change
whether it came from a trigger the player fired in the window (live today) or, in the future, from a
surfaced at-any-time action.

---

## Social Benefits — interaction with its existing discard trigger

Social Benefits already carries, besides the `food == 0` conditional grant, an **optional
`after_feeding` "discard all food → get 1 wood + 1 clay" trigger** (added so a player holding surplus
food can discard it to reach 0 and collect — RULES.md: goods, which include food, may be discarded
to the general supply at any time). Under this mechanism:

- The conditional grant becomes a **re-checked** grant (`food == 0`), gated by the shared latch.
- The discard trigger is unchanged: firing it discards the food, grants the reward, **and sets the
  shared latch** — so the subsequent re-check sees the latch set and does nothing. **No double
  grant.** (This is the whole point of the shared latch: any path that grants sets it.)
- **Consequence — a ruling change to confirm.** With the re-check, Social Benefits now fires whenever
  food reaches 0 *during* the window, not only at entry. So a player may spend their last food on
  Farm Store (collecting its goods) **and** collect Social Benefits. This supersedes the earlier
  "Social Benefits resolves first (autos before triggers)" ordering ruling. It is exploit-free: the
  food is genuinely spent, and Farm Store's own after-feeding timing (its proceeds cannot pay the
  feeding) is untouched.

Small Animal Breeder is the second live consumer: its +1-food grant (`food ≥ round number`) should
fire once if a convert-to-cross-the-threshold action taken in the `before_round` window makes the
condition true (the same shape; see the Small Animal Breeder finding in `CARD_AUDIT_FINDINGS.md`).

---

## Scope and staging

- **Live today (food-keyed):** Social Benefits, Small Animal Breeder. Build and verify these first.
- **Forward-looking:** the non-food conditional grants (Three-Field Rotation on fields, the animal /
  room / goods cards) become consumers only once the actions that change their feature *within the
  window* are surfaced — which for the animal/field/room cases means the deferred **at-any-time**
  action machinery (Muddy Puddles, Roll-Over Plow, Stone House Reconstruction + Hammer Crusher, and
  whatever else the Part-1 sweep surfaces). Building the mechanism general now means those cards need
  no re-architecture when their enablers land.
- **Family-inert throughout.** Card-only registry + card-only latch; the C++ differential gates stay
  green untouched.

## Open questions

1. **Latch reset granularity** — per harvest, per round, or per window-occurrence? Follows each
   grant's scope; nail it down per consumer.
2. **Registry shape** — a new `register_conditional_grant` seam, vs. extending `register_auto` with a
   "re-check + latch" flag. Prefer whichever keeps the one-shot autos (the common case) untouched.
3. **Re-check cost** — confirm the scoped re-check adds negligible per-decision overhead (it iterates
   only the live conditional-grant registry, expected to be a handful of entries).
4. **The Part-1 sweep output** feeds back here: it may reveal conditions that change in ways not yet
   considered, or consumers that need a different scope than the two food cases.
