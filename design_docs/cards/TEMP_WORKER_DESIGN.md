# TEMP_WORKER_DESIGN.md — Motivator (E93) and workers that exist outside the family

> **Status: DESIGN DRAFT (2026-07-21).** Written to jump-start a dedicated session on the
> temporary-worker mechanism. It is **not a plan of record**: sections marked ⚠️ UNRESOLVED are
> deliberately incomplete — they are either open rules questions for the user or design
> choices the building session must settle (with the user where marked). Dated rulings quoted
> here were given by the user on 2026-07-21 in the card-triage conversation.

---

## 1. The problem

**Motivator (E93, occupation, deck E, [1+]).** Card text (verbatim):

> "On your first turn each round, if you have no unused farmyard spaces, you can place a
> person from your supply."

The mechanism this needs: a meeple from the player's **supply** acts as a worker for one round
**without becoming a family member**. Nothing in the engine models a worker that is neither at
home (`people_home`) nor part of the family (`people_total`) — every current placement flows
through `people_home`, and every people-reader (feeding, scoring, growth, the
Nth-person-placed idiom) assumes workers ⊆ family.

## 2. Ruled semantics (user, 2026-07-21)

- **The loaner reading is confirmed.** The supply person is a loaner for the round: it is
  placed like a worker, returns to **supply** (not home) in the returning-home phase, never
  becomes a family member, requires no food (it is back in supply before any harvest), and
  scores nothing.
- **The physical-meeple constraint.** A player owns 5 meeples. While the loaner is on the
  board it occupies a supply meeple, so **Family Growth to a 5th member is illegal while no
  free supply meeple remains**. Declining Motivator's offer to keep growth open can therefore
  be strictly optimal — the offer must always be declinable (consistent with the standing
  granted-sub-actions-are-optional rule; the card says "you can").

## 3. The key discovery: `workers_in_supply` already models the pool

`PlayerState.workers_in_supply` (state.py) is a **stored** field: "Family-member meeples in
the player's SUPPLY: the pool a Family Growth draws from." It is the growth gate (growth
legal only while `> 0`), decremented at the single growth chokepoint (`_grow_family`), and
already adjusted by cards (Lodger removes a meeple from the game without replenishing it;
Telegram et al. adjust the pile). It is Family-serialized and mirrored in C++.

**Consequence:** the loaner borrows from this existing pool.

- Placing the loaner: `workers_in_supply -= 1` (meeple leaves supply onto the board).
- Returning-home reset: `workers_in_supply += (number of loaners out)`.
- **Growth blocking then needs no new legality code at all** — the existing gate reads the
  field, so a player at 4 family with the loaner out has `workers_in_supply == 0` and growth
  is already illegal. Exactly the physical game.

This also means Motivator changes the *value* of a Family-serialized field but not its shape:
no C++ change (card content never runs there), no canonical change for this field.

## 4. Proposed state model

- **New card-only `PlayerState` field: `temp_worker_spaces: tuple[str, ...] = ()`** — the
  space id(s) currently occupied by loaner meeples. Default-skip in `canonical.py`, added to
  `PlayerState.__hash__`. It carries both the **count** (how many loaners are out — needed by
  the reset and the supply arithmetic) and the **identity** (which spaces they stand on).
  Identity is required because `space.workers` stores per-player *counts*, so a mid-round
  "return a person" effect (Sheep Inspector, Tea Time) cannot otherwise tell a loaner from a
  family member on the same space.
- **Why not put the loaner in `people_home`/`people_total`:** feeding, scoring, and growth all
  read `people_total` (must not move — the ruled semantics), and the Nth-person-placed idiom
  `(people_total − newborns) − people_home` would corrupt if a non-family meeple entered
  either term.
- Alternative considered: CardStore on the granting card. ⚠️ UNRESOLVED lean, revisit at
  build: the state is read by cross-cutting engine bookkeeping (the reset, the supply
  arithmetic, possibly ordinal readers) and the mechanism will be shared by future analogous
  cards, which favors a first-class field; but the state-placement rule
  (CARD_ENGINE_IMPLEMENTATION.md §4) admits either.

## 5. The extra-placement mechanism (⚠️ the hard part — UNRESOLVED design choice)

The loaner's placement is a full worker placement: it takes a real action space, performs its
whole action (hosts, sub-decisions, card triggers), and blocks the space. Two candidate
mechanisms for scheduling a placement that is *not* the player's normal one-per-turn move:

- **(a) In-turn pending frame.** A frame whose enumerator offers PlaceWorker-shaped commits
  for the loaner, resolved inside the current turn. Downside: a "turn within a frame" — the
  whole placement pipeline (space hosts, atomic handlers, sub-stacks) would need to run
  beneath a frame in a way it never does today.
- **(b) Extra-turn scheduling marker.** After the player's triggering turn completes,
  `current_player` does not advance; a card-only marker ("this player's next placement is a
  loaner") makes the *next* placement — which runs through the entire existing turn pipeline
  unchanged — do loaner bookkeeping (decrement `workers_in_supply`, record in
  `temp_worker_spaces`) instead of `people_home -= 1`.

**Lean: (b)** — it reuses the full existing placement machinery untouched, and the same
"don't advance the player once" scheduling is what **Lasso (B24)** needs ("You can place
exactly two people immediately after one another if at least one of them uses the 'Sheep
Market', 'Pig Market', or 'Cattle Market' accumulation space"), so one mechanism serves the
family. ⚠️ UNRESOLVED: the interaction with `_advance_current_player` and the round's
all-placed detection needs a careful walk before committing to (b).

Round-flow gates under either mechanism: the work phase's "all workers placed" detection
keys on `people_home`, which the loaner never enters — so a placed loaner cannot extend or
shorten the round's turn count beyond the extra placement itself.

## 6. Reading of Motivator itself (⚠️ partly UNRESOLVED)

- **Condition** "if you have no unused farmyard spaces": used = room/field/stable **or
  enclosed by fences**. Must use the fence-aware check (`big_country.py`'s
  `_all_farmyard_spaces_used` is the reference); `cell_type` alone undercounts empty pasture
  cells (CARD_AUTHORING_GUIDE.md §2).
- **"On your first turn each round … you can place a person"** — ⚠️ UNRESOLVED sequencing:
  does the loaner placement happen immediately after the normal first placement (back-to-back,
  the Lasso shape), immediately *before* it, or does the loaner merely join the pool for later
  turns? Likely reading (unconfirmed): immediately with the first turn, back-to-back. Needs
  the user.
- **Trigger surface:** depends on the sequencing ruling. Under the back-to-back-after reading:
  an optional trigger in the first turn's after-window — which requires the space to be
  hosted, i.e. `register_action_space_hook` over all spaces (the Work Certificate pattern),
  with eligibility = (this was my first placement this round) ∧ (no unused farmyard spaces) ∧
  (`workers_in_supply ≥ 1`) ∧ (a legal placement exists for the loaner — never a dead-end).
  Once per round is structural (only the first turn qualifies), but a `used_this_round` latch
  is cheap insurance.
- The loaner's placement is a real use of a space: it blocks the space and (lean, ⚠️ confirm
  with user) fires the normal before/after action-space card events like any placement.

## 7. Touch-point checklist

1. Placement executor: loaner branch — `space.workers` +1 (attribution is free; the board
   already stores per-player counts), `workers_in_supply` −1, `temp_worker_spaces` +=
   (space,), `people_home` untouched.
2. Returning-home reset (`_return_home_reset`): `workers_in_supply` += len(loaners), clear
   `temp_worker_spaces`. Board worker markers are already cleared by the reset.
3. Growth legality: **no change needed** (§3). Verify with a test: 4 family + loaner out →
   growth illegal at every growth site (wish spaces, card growth grants); legal again after
   the reset.
4. Nth-person-placed idiom (`(people_total − newborns) − people_home`): loaner placements are
   invisible to it as-is. ⚠️ UNRESOLVED rules question: *should* a loaner placement advance
   "the Nth person you place this round" for readers like Catcher — and can the loaner be
   "the second person you place" for Henpecked Husband (D94)? Ask before building; if yes,
   the idiom must add the loaner placements made this round (which needs a this-round count —
   `temp_worker_spaces` provides it if cleared only at the reset).
5. Mid-round return effects: Sheep Inspector (D93) and Tea Time (E3) return placed persons
   home. For a loaner, "home" is ⚠️ UNRESOLVED: return to supply (freeing the meeple, ending
   its round — the physical-reading lean), or somewhere it can be placed again? Identity for
   targeting comes from `temp_worker_spaces`. (Related settled ruling for calibration: Sheep
   Inspector *can* return the worker parked on Canal Boatman's card — user, 2026-07-21.)
6. Cards reading live occupancy (Swimming Class at the `returning_home` window;
   occupancy-conditioned triggers): the loaner is a real occupying worker; lean — no special
   handling.
7. Canonical/hash: `temp_worker_spaces` default-skip + hash-included. `workers_in_supply`
   already serialized. Family byte-identity preserved (Family never sets the new field); C++
   untouched.
8. Web UI: space worker counts already render; needs the extra-placement prompt and ideally a
   supply-meeple indicator so the growth-blocking tradeoff is visible to the player.

## 8. Analogous cards (design inputs — survey before freezing the design)

- **Lasso (B24, minor):** two consecutive placements of *family* workers — shares the
  extra-turn scheduling of §5(b), no supply interaction.
- **Canal Boatman (D103, occupation):** a family worker parked *on a card* rather than a board
  space (ruled 2026-07-21: after-space trigger; multiple workers may accumulate on the card in
  one round). Shares the "worker is neither home nor on a board space" bookkeeping shape, but
  not the supply pool.
- **Wood Saw (E14, minor):** a named "Build Rooms" action "without placing a person" — *not*
  a temp-worker card (no meeple involved); listed to bound the family.
- ⚠️ INCOMPLETE: before freezing the design, sweep the catalog (`scripts/card_text.py`, the
  data JSONs — search "place a person", "from your supply", "another person", "immediately
  after one another") for further supply-meeple / extra-placement cards. Per the CLAUDE.md
  Phase-3 directive, [3+]/[4] cards are design inputs even though they are not dealt at 2
  players.

## 9. Test checklist (first pass)

- Growth blocked exactly while (4 family ∧ loaner out); legal after reset; legal if the offer
  was declined.
- Loaner placement: blocks the space; performs the full action; fires space hooks (per the
  §6 ruling once confirmed); returns to supply at the reset; absent at feeding; scores
  nothing; `people_total`/`people_home` never move on its account.
- Motivator eligibility boundaries: one unused farmyard cell → not offered; no supply meeple →
  not offered; no legal placement for the loaner → not offered; declinable.
- Interplay per rulings: Sheep Inspector / Tea Time on a loaner (§7.5), Nth-person readers
  (§7.4).
- Family byte-identity: full suite + the C++ differential gates green untouched.

## 10. Consolidated open questions for the user

1. Sequencing of "on your first turn": loaner placed back-to-back after the first placement?
   Before? Or pooled for later turns? (§6)
2. Does the loaner's placement fire other cards' action-space hooks like any placement? (§6 —
   lean yes.)
3. Do loaner placements count for "the Nth person you place this round" readers — and can the
   loaner be Henpecked Husband's "second person you place"? (§7.4)
4. When a card returns a loaner "home" mid-round (Sheep Inspector / Tea Time), does it go to
   supply for the rest of the round, or become placeable again? (§7.5)
5. Design sign-off on the extra-turn scheduling mechanism (§5(b)) once the building session
   has walked `_advance_current_player` and the all-placed detection.
