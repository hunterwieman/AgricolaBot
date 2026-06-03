# Hidden-Information Refactor — Design Doc

**Status:** **implemented** on branch `hidden-info-refactor` — Phase 1 (engine-core + migrations)
and Phase 2 (MCTS chance nodes) per §16; full test suite green (948 passed, incl. the new
`tests/test_reveal.py`). Remaining (§16 Phase 3): the V3 re-validation (§12 step 3) and the `.md`
documentation updates (§13). This doc remains the design reference for the change.

> **For new sessions:** read this plus `CLAUDE.md` (Foundations + Phase 1), `MCTS_DESIGN.md`
> (the search this changes), and the engine docs `ENGINE_IMPLEMENTATION.md` §1–2. The design
> rationale for *why chance nodes* (vs ISMCTS / determinization) lives in the conversation that
> produced this doc and is summarized in §2.

---

## 1. Problem statement

### 1.1 The leak

In the 2-player Family game the **only** hidden information is `round_card_order` — the
length-14 permutation of stage cards, shuffled within each stage at `setup` and baked into
`BoardState.round_card_order`. It determines, for each stage card, the round it appears
(`ActionSpaceState.round_revealed`), and `_resolve_preparation` reveals the next card at each
round boundary by reading it.

A real player does **not** know this order in advance: within each stage the round cards are
shuffled face-down and revealed one per round. But the order sits fully resolved inside every
`GameState`, so any agent that looks ahead across a round boundary plans against the *true*
future. This is a cheat.

### 1.2 Exactly two leak channels (grep-confirmed)

`grep -rn "round_card_order\|round_revealed" agricola/` shows the order is read in only four
places, and only two are leaks:

| Site | Reads | Leak? |
|---|---|---|
| `legality.py:153` `_is_available` | `sp.round_revealed <= state.round_number` | No — needs only the *revealed* status. |
| `engine.py:488` `_resolve_preparation` | refill where `round_revealed <= new_round` | No — the reveal mechanism itself. |
| `agents/nn/encoder.py:317,322` | `sp.round_revealed <= rn` | No — encodes only *revealed* cards. |
| `agents/heuristic.py:478` `_basic_wish_revealed_round` | scans the full order for a future card | **Yes** — direct future peek. |

Plus the structural leak: **MCTS (and any multi-step lookahead) crossing a round boundary** —
`step` reveals the true next card because the order is baked in.

**What is already clean and stays clean:**
- The **NN value head and its encoder** never saw the future order — `encoder.py` encodes only
  `revealed`-ness and `future_food` (constant 0 in Family). So the network never learned to
  cheat: **no `ENCODING_VERSION` bump, no retrain, existing checkpoints stay valid.**
- `restricted.py` reads neither field.
- Fencing macros (`mcts.py`) live within a turn and never cross a round boundary.

So the blast radius is: the engine reveal path, `_basic_wish_revealed_round`, and the
greedy-lookahead/MCTS consumers of cross-boundary states.

### 1.3 Goal

Make the public game state carry **no** information about the unrevealed order, model each
reveal as an explicit chance transition resolved by an environment (real games) or a chance
node (MCTS), and average evaluators over reveal outcomes instead of evaluating the
between-rounds state. Net effect: the agent can no longer condition on the hidden future, in
search or in leaf evaluation.

---

## 2. Approach & settled decisions

The hidden order is **symmetric** (neither player knows it), **exogenous** (nature's shuffle,
not a function of any private choice), and **revealed identically to both** at each boundary.
Under these conditions an information set is observer-independent and ISMCTS collapses onto
ordinary MCTS with chance nodes — so we use **explicit chance nodes**, the simplest correct
tool here. The in-search fan-out is tiny (≤3 — round 1's k=4 reveal is dealer-resolved at game
start and never reaches search, §4.5) and the reveal distribution is exactly uniform, so chance
nodes are cheap *and* bias-free (no strategy fusion).

Decisions reached in the design conversation, with one-line rationale:

| Decision | Choice | Why |
|---|---|---|
| Hidden-info technique | **Explicit chance nodes** | symmetric+uniform+≤3 → exact & cheap; no ISMCTS machinery needed |
| Reveal representation | **An explicit `RevealCard` action** consumed by the one `step` | keeps `step(state, action)->state` pure & uniform; the reveal *source* (dealer vs chance node) becomes a caller concern, like worker placements |
| Public-state masking | **Structural** — `ActionSpaceState.revealed: bool`, order removed from `BoardState` | `GameState.__hash__` then identifies info-equivalent states for free; no projection function to keep in sync (matches CLAUDE.md "structural invariant > caller discipline") |
| Revealed encoding | **`revealed: bool`, not `revealed_at: int`** | memoryless: two states with the same *revealed set* recombine in the DAG regardless of reveal order/timing; the only forward-relevant consequence of *when* (accumulated goods) already lives in the `accumulated` fields |
| Reveal probabilities | **Uniform, no `(card, prob)` pairs** | uniform is exactly correct for all of Agricola; YAGNI |
| Chance child sampling | **Deterministic round-robin** (per-edge counter) | guaranteed coverage of all ≤3 outcomes + variance reduction at low visit counts; immune to "first-explored looks best" because chance nodes average, not max |
| Round 14 | **Kept on the uniform path** (not special-cased) | all six k=1 reveals (rounds 4,7,9,11,13,14) are mechanically identical trivial 1-outcome nodes; dropping only 14 *adds* a special case for no benefit |
| Chance-node evaluation | **Never** evaluate a chance node; descend to a decision child and evaluate there | a chance node's value *is* the expectation over children; also keeps the NN in-distribution |

---

## 3. State model changes

### 3.1 `ActionSpaceState` (state.py:47)

```python
# before
round_revealed: int = 0   # 0 = always available; 1–14 = the round this card appears
# after
revealed: bool = False    # True once the card has been turned up (permanents: True from setup)
```

Permanent spaces are `revealed=True`; stage cards start `revealed=False` and flip to `True`
when their `RevealCard` transition fires — including round 1's card, via the round-1 nature step
at game start (§3.3, §4.5).

**Why bool, in full:** the round-of-reveal is non-Markov history. The only forward-relevant
consequence of revealing earlier vs later is how many goods piled up, and that is already
carried by `accumulated` / `accumulated_amount`. Two states with the same revealed set and the
same accumulated loads are future-equivalent; `bool` lets them share one DAG node, `int` would
wrongly split them. (The refactor is also what first makes this matter: with the order baked in,
one game = one fixed order, so `int` never blocked a recombination; once the order is hidden and
chance branches produce same-set/different-order states in one tree, `bool` is required for the
recombination to fire.)

Invariant worth asserting in tests: `sum(sp.revealed for stage-card spaces) == round_number`. It
holds at **every decision state** — both WORK states and reveal nodes (at a reveal node the card
isn't up yet, so `count == round_number` still holds; that equality is exactly the push
discriminator, §4.3). It is violated only transiently *inside* the reveal `step`, after
`RevealCard` turns the card up but before `_complete_preparation` increments `round_number`.

### 3.2 `BoardState` (state.py:106) and `with_space` (state.py:130)

- Remove the `round_card_order: tuple` field.
- `with_space` currently rebuilds `BoardState(..., round_card_order=board.round_card_order)`
  (state.py:138) — drop that kwarg.

The hidden order moves to a new `Environment` object (§3.4).

### 3.3 `setup.py`

With round 1 modelled as a nature step (§4.5), `setup` no longer reveals or pre-loads anything
stage-specific — the round-1 reveal does it, exactly like every other round:

- Permanent spaces → `revealed=True`, accumulation **empty** (the round-1 reveal's
  `_complete_preparation` fills them — see below).
- **All** stage cards (including `round_card_order[0]`) → `revealed=False`, accumulation empty.
- `setup_env` first builds the bare `round_number = 0`, `phase = PREPARATION` state (all stage
  cards `revealed=False`), then **resolves round 1 internally**: `_advance_until_decision` reaches
  the round-1 `PendingReveal` (Case 2, `count(0) == round_number(0)`), and `setup_env` applies
  `env.reveal_action` to it (dealing `order[0]`). The returned state is the resulting **round-1
  WORK** state — round 1's card revealed, accumulation filled — so `setup(seed)` stays
  content-compatible with today (§3.5).

Round 1 thus goes through the **same** `RevealCard` → `_complete_preparation` path as every other
round (it just fires inside `setup_env`). `_complete_preparation` increments `round_number` 0→1
and refills every `revealed` space (permanents + the just-revealed round-1 card) by one rate, so
all round-1 goods (including a round-1 `sheep_market`'s sheep) arrive correctly. This **subsumes
the round-1 accumulation bug** (§14) — no special round-1 loading left to get wrong, no standalone
step-0 fix.

`setup` no longer stores the order on the board; it lives in the returned `Environment` (§3.4).
See §3.5 for the function-signature decision.

### 3.4 New `Environment` object (the dealer / hidden ground truth)

The hidden order lives outside `GameState`, held by the game driver. A small frozen dataclass in
a **new module `agricola/environment.py`** (decided in review).

```python
@dataclass(frozen=True)
class Environment:
    """The hidden ground truth + nature policy for one game. Today: the round-card
    order. The driver consults it to resolve nature decisions; agents/MCTS never
    see it. (Forward-compat framing in §3.6.)"""
    round_card_order: tuple  # length 14; order[i] is round i+1's card

    def resolve(self, state: GameState) -> Action:
        # Nature policy: produce the true action for whatever nature decision is
        # pending. Today the only nature decision is a reveal.
        return self.reveal_action(state)

    def reveal_action(self, state: GameState) -> "RevealCard":
        # round_number is the round just COMPLETED (§4.5); the reveal turns up the
        # NEXT round's card = order[round_number]. At game start round_number == 0,
        # so this turns up round 1's card (order[0]) — round 1 is a nature step too
        # (§4.5).
        return RevealCard(self.round_card_order[state.round_number])
```

Notes:
- **Deterministic:** built from the same seed/shuffle `setup` already computes, so "all
  randomness resolved in `setup`" still holds — the order is just carried in the env rather than
  in the public state.
- **MCTS never uses the env.** The candidate set and uniform probabilities are reconstructable
  from public state (§5.2); only the *true* card a real game commits to needs the env.
- The dealer's true card is always one of the enumerator's candidates (it is the unrevealed
  current-stage card) — assert this in tests.

### 3.5 `setup` signature — recommendation

Keep the `setup(seed) -> GameState` signature and add `setup_env(seed) -> tuple[GameState,
Environment]` as the full constructor, with `setup(seed)` defined as `setup_env(seed)[0]`. Both
build the order once (single source — no fragile RNG-replay).

The returned `GameState` is a **round-1 WORK state**: `setup_env` resolves the round-1 reveal
internally (via `env.reveal_action`, §3.3) and hands back the post-reveal state, so `setup(seed)`
is content-compatible with today's round-1 WORK (plus the accumulation fix). Consequences:
- Full-game drivers use `state, env = setup_env(seed)` and pass `env.resolve` as the dealer; the
  loop deals rounds **2–14**'s reveals (round 1 is already done).
- Bare `setup(seed)` returns a playable round-1 WORK state (the ~36 existing callers keep
  working); it just can't be driven *past* the round-1→2 boundary without a dealer.
- Only tests that *drive full games* migrate to `setup_env` + dealer. Tests that inspect the
  round-1 state or build scenarios on it are unaffected (modulo the round-1 accumulation fix).

*(Alternatives considered: (a) change `setup` itself to return the tuple — breaks every call site
mechanically; (b) return the round-1 **nature node** instead of pre-dealing — more uniform (the
loop deals all 14 reveals, the literal "loop starts before round 1"), but it changes `setup`'s
content for ~36 callers (a nature node, not WORK) and makes bare `setup` un-driveable. Pre-dealing
keeps round 1 on the same nature machinery while preserving the WORK-state contract; when the
card-draft lands, `setup_env` simply stops being able to pre-resolve and returns the draft node,
moving the start point earlier then.)*

### 3.6 Forward-compatibility: common knowledge vs. hidden ground truth vs. observation

Future hidden information is **asymmetric** — players hold hands with some cards public and some
private. To keep today's symmetric design a clean special case of that, we hold to one invariant
and three layers:

| Layer | Holds | Today | Future |
|---|---|---|---|
| **`GameState`** | *common knowledge* (what **every** player knows) | board `revealed` bools, public resources/farmyard | + face-up/played cards |
| **`Environment`** | hidden ground truth + nature policy | round-card order | + each player's private hand + draw deck |
| **`observe(state, env, i)`** | the partial gamestate known to player i | identity (`== state`) | common knowledge **+ player i's own private cards**, masking opponent privates + deck |

**Invariant (load-bearing):** `GameState` contains only common knowledge; anything hidden from
anyone lives in `Environment`. This is already why the order is externalized; the same rule files
private hands into `Environment` later, with `observe(…, i)` splicing player i's own slice back
into their view.

To build this forward-compat **now**, without any card content:
1. Keep the invariant (free — we're doing it).
2. Frame `Environment` as "hidden ground truth + nature policy" with the seam
   `decider_of(state) is None → env.resolve(state) -> Action`. New nature events (draft, draw)
   later add `resolve` branches + `Pending*` frames; nothing structural changes.
3. Introduce `observe(state, env, i)` as a real seam — the identity today — and write *new*
   MCTS / NN-encoder code against it rather than against `state` directly. When asymmetric info
   arrives, only `observe` changes, not every consumer. (The one piece of design-for-the-future
   worth paying for now; the rest is YAGNI.)

What the asymmetric future adds *on top* (not built now): determinization / ISMCTS — the
searching player samples a full ground truth consistent with `observe(state, env, i)` (own hand +
common knowledge fixed; opponent hand + deck sampled), searches each sample as perfect-info, and
keys nodes on the information set `observe(…, i)`. Today's chance nodes are the symmetric special
case of this and the deck-reveal mechanism that survives into it — so this work is foundational,
with `observe` as the hinge. (Standard world-state / information-state split, cf. OpenSpiel.)

---

## 4. The reveal transition

### 4.1 `RevealCard` action (actions.py)

```python
@dataclass(frozen=True)
class RevealCard:
    """Nature's action: turn up `card` as the current round's stage card.
    Supplied by the environment (real games) or enumerated by the MCTS chance
    node. NOT a CommitSubAction — it is a top-level transition like PlaceWorker."""
    card: str   # a stage-card space id
```

Add to the `Action` union (actions.py:243). It is dispatched in `_apply_action`, not via the
`COMMIT_SUBACTION_HANDLERS` table.

### 4.2 `PendingReveal` frame (pending.py) + the nature (`None`) sentinel

```python
@dataclass(frozen=True)
class PendingReveal:
    """Nature's pending decision: which stage card is revealed for the round
    being entered. player_idx is None (the nature sentinel) so decider_of
    returns None and the driver routes to the dealer (never to a strategic
    agent)."""
    PENDING_ID: ClassVar[str] = "reveal"
    player_idx: None = None         # nature: no owning player
    initiated_by_id: str = "phase:reveal"
```

Add to the `PendingDecision` union (pending.py:452). This mirrors the harvest precedent
(`_initiate_harvest_feed` pushes `PendingHarvestFeed(player_idx=…, initiated_by_id="phase:…")`).

**Nature sentinel = `None` (decided).** `decider_of` (base.py:119) widens its return type to
`int | None` and is otherwise **unchanged** — it already returns `pending_stack[-1].player_idx`,
which is `None` for a `PendingReveal`. `None` is *not* a valid list index, so a forgotten guard
(`agents[None]`) raises `TypeError` immediately rather than silently routing to player 1 — no
footgun. Every consumer guards `if d is None: dealer(...) else: agents[d](...)` (§6, §7). A test
asserts no strategic agent is ever invoked at a nature node. *(This replaces the earlier
`NATURE = -1` proposal, whose negative-index value would have failed silently.)*

### 4.3 Engine: the reveal is the first thing in PREPARATION

`RevealCard` does **one thing**: turn the named card face-up and pop the `PendingReveal` frame —
it leaves `phase = PREPARATION` and does **not** touch `round_number`, `current_player`, or
accumulation. All the existing preparation work stays in the system walk, so it runs *after*
`step`'s alternation check has already passed (§4.4 — this is what avoids the rotate-away bug).

`_advance_until_decision` Case 2 (PREPARATION) becomes two-state, discriminated by the
`count(revealed stage cards) == round_number` invariant (no new field; a transient bool is
equally fine). The round increment is **deferred to completion**, so `round_number` still names
the round just finished while the reveal is pending — which is what makes the discriminator
self-resetting:

- **Card not up yet** (`count == round_number`): push `PendingReveal()` (`player_idx=None`).
  Case 1 (`if state.pending_stack: return`) pauses at the nature decision. The reveal turns up
  the *next* round's card.
- **Card up** (`count > round_number`, reveal already fired): run `_complete_preparation` —
  increment `round_number`, refill every accumulation space where `sp.revealed` (migrated from
  `round_revealed <= new_round`; same set), distribute `future_resources`, clear newborns, set
  `phase = WORK`, `current_player = starting_player`.

`_apply_reveal_card(state, action)` (new): set the card's `revealed=True`, pop the
`PendingReveal`. Register it in `_apply_action` (engine.py:186):
```python
if isinstance(action, RevealCard):
    return _apply_reveal_card(state, action)
```
*(This two-state Case 2 + `_complete_preparation` replaces the old monolithic
`_resolve_preparation` at engine.py:470, whose implicit "refill where `round_revealed <=
new_round`" reveal is exactly what we're making explicit.)*

### 4.4 The alternation guard needs no change

`step` (engine.py:129) rotates the active player on `phase == WORK and not pending_stack`.
Because `RevealCard` leaves `phase = PREPARATION`, the guard does not fire after a reveal step;
the prep-completion that sets `phase = WORK` and `current_player = starting_player` happens
later, in the system walk (§4.3), *after* the guard has already run. So
`current_player = starting_player` sticks with no special-casing. *(An earlier draft did
prep-completion inside the reveal apply, which set `phase = WORK` before the guard ran and so
rotated away from the starting player; the structure above dissolves that.)*

### 4.5 Round bookkeeping & boundary conditions

- At the reveal node `round_number` is the round just **completed** (R); the reveal turns up
  round **R+1**'s card, and `_complete_preparation` increments to R+1. So the candidate stage is
  `stage_of_round(round_number + 1)` (§5.2) and the dealer's true card is `order[round_number]`
  (`order[i]` is round `i+1`'s card — §3.4).
- **Round 1 is a nature step too** (§3.3), but resolved **inside `setup_env`** rather than by the
  game loop: at construction `round_number = 0`, `count = 0`, the discriminator pushes the round-1
  reveal, `setup_env` deals `order[0]`, and `_complete_preparation` increments 0→1. So all 14
  rounds use the same reveal machinery; the *loop* deals rounds **2–14** (round 1 is already done
  — §3.5).
- Round 1's reveal is the most informative — **k=4** (uniform over the 4 unrevealed stage-1
  cards); its randomness used to be hidden inside `setup`'s RNG and is now an explicit nature
  step. **It is resolved inside `setup_env`** (before any agent decision), so MCTS search and
  `_eval` averaging never face it — their reveal fan-out is **≤3** (round 2's k=3 stage-1 reveal
  is the largest they encounter). The k=1 reveals (rounds 4,7,9,11,13,14) are trivial 1-outcome
  nodes (§2).
- Harvest interaction: on harvest rounds RETURN_HOME → HARVEST_* → PREPARATION (round<14) hits
  the reveal; after round-14's harvest, `_advance_until_decision` Case 7 goes to BEFORE_SCORING —
  **no round-15 reveal.**
- `round_number = 0` is a brief pre-round-1 transient — audit for `round_number >= 1` assumptions
  (scoring, harvest checks, `future_resources` indexing — `_complete_preparation` increments
  *before* indexing `future_resources`, so round 1 reads index 0, not -1).

---

## 5. Legality

### 5.1 `_is_available` (legality.py:149)

```python
revealed = sp.round_revealed <= state.round_number   # before
revealed = sp.revealed                               # after
```

### 5.2 Reveal enumerator + dispatch

`_legal_actions_uncached` (legality.py:1638) already dispatches on `state.pending_stack` first,
so a `PendingReveal` on top routes to its enumerator. Add to `PENDING_ENUMERATORS`
(legality.py:1493):
```python
PendingReveal: _enumerate_pending_reveal,
```
```python
def _enumerate_pending_reveal(state, top):
    # round_number is the round just completed; we reveal the NEXT round's card (§4.5).
    stage = stage_of_round(state.round_number + 1)
    return [RevealCard(c) for c in STAGE_CARDS[stage]
            if not get_space(state.board, c).revealed]
```
The candidate set is derived purely from public state — `STAGE_CARDS[stage]` (static) minus the
already-revealed cards. For k=1 rounds it yields a single `RevealCard` (the trivial chance node).

### 5.3 `stage_of_round` helper (constants.py)

Add a round→stage map (stage boundaries from cumulative `STAGE_CARDS` sizes 4,3,2,2,2,1):
rounds 1–4 → 1, 5–7 → 2, 8–9 → 3, 10–11 → 4, 12–13 → 5, 14 → 6. A precomputed
`STAGE_OF_ROUND: dict[int,int]` or a small function; co-locate with `STAGE_CARDS`.

### 5.4 Restricted wrappers (restricted.py)

The strict/regular wrappers operate on placements and sub-actions; at a `PendingReveal` top they
must pass the enumerator output through unchanged. `_safe_narrow` already guarantees never
emptying a set; verify no filter touches `RevealCard`. Add a test that
`strict_restricted_legal_actions` at a reveal node returns the full candidate set.

`filter_implemented` (tests/test_utils.py:64) **already admits `RevealCard`** with no change — it
only constrains `PlaceWorker` space-ids and returns `True` for every other action type.

---

## 6. Drivers and the dealer

**Invariant (load-bearing):** strategic agents are **never** called at a nature node. The driver
resolves reveals via the dealer; MCTS resolves them internally via chance nodes. This is what
keeps every driver and the recorder simple.

`play_game` (base.py:437) gains a dealer:
```python
def play_game(initial_state, agents, dealer):
    state = initial_state
    trace = []
    while state.phase != Phase.BEFORE_SCORING:
        d = decider_of(state)
        action = dealer(state) if d is None else agents[d](state)
        trace.append(action)
        state = step(state, action)
    return state, trace
```
`dealer = env.resolve` (the general nature seam — §3.6). (Reveals appear in the trace as real
transitions — they are not singletons in the legal-actions sense, just resolved by the dealer's
policy.)

Two classes of driver (full file-by-file list in §15):

- **`play_game`-based** (heuristic / MCTS / recording — want the canonical per-stage-shuffle
  order so both seats face one consistent world): gain a `dealer` arg, passed `env.resolve` from
  `setup_env`. Covers `play_game`, `play_heuristic_game.py`, the match runners, and
  `agents/nn/recording.py` (`play_recording_game` takes the env; reveals aren't player-decision
  snapshots, so recorded dataset content is unchanged).
- **`random_agent_play` (test_utils.py)** — **no change.** It already picks a random legal action
  each step, so at a nature node it picks a random `RevealCard` = uniform self-sampling of the
  reveal; it stays env-free and seed-deterministic. Its callers (`play_random_game.py`,
  `count_replaces.py`, `profile_engine.py`) need no env. (The reveal *order* is now randomized
  rather than setup-fixed — fine under seed-divergence.)

UIs (`play.py`, `play_web.py`) need the env passed in for the dealer; displaying "revealed in
round X" is cosmetic and, if wanted, reconstructable from the env without entering `GameState`.

---

## 7. Evaluator averaging over reveals (heuristic **and** NN)

### 7.1 The problem

`EvaluatorAgent` lookahead (`_lookahead_value` → `_skip_singletons` → `_rollout_value`,
base.py:273–403) stops when `decider_of(state) != decider` and then calls
`self.evaluator(state, decider, config)`. After this refactor, stepping a round-ending placement
lands on a **nature node** (`decider_of(state) is None`), so the evaluator would be called on a
between-rounds state — out-of-distribution for the NN, and ignoring the reveal it can't see.
(`None != decider` is already True, so the existing stop condition fires correctly with no change.)

### 7.2 The fix

Route **every** evaluator call through one helper that expands and averages at nature nodes:
```python
def _eval(self, state, decider):
    if decider_of(state) is None:                                     # nature node (a reveal)
        outcomes = filter_implemented(self.legal_actions_fn(state))   # the ≤3 RevealCards
        vals = [self._eval(step(state, a), decider) for a in outcomes]
        return sum(vals) / len(vals)        # uniform mean = chance-node value
    return self.evaluator(state, decider, self.config)
```
Replace the direct `self.evaluator(...)` calls in `_lookahead_value` (action mode),
`_rollout_value` (both the per-candidate score and the final eval), and `_exhaustive_recurse`
with `self._eval(...)`. Lives in `EvaluatorAgent`, so `HubrisHeuristicV3` **and** `NNAgent`
inherit it.

Properties:
- **Correct, not just a patch:** a round-ending action's true value *is* the expectation over
  reveals; averaging computes it. Same "never evaluate a chance node; take the expectation over
  children" rule MCTS uses (§8) — state it once, apply in both places.
- **Bounded:** exactly one level deep (a post-reveal state is a normal WORK decision, never
  another nature node); uniform weights; ≤3× on the single round-ending decision. The NN can
  batch the outcomes.
- **De-cheats the greedy agents too:** today their end-of-round lookahead sees the *true* reveal;
  averaging makes them honest. This shifts the data-gen heuristics' end-of-round play slightly,
  feeding the V3 re-validation (§11). The NN stays clean.
- The driver still never *calls* an agent at a nature node; the agent only meets one *inside its
  own lookahead*, where it averages rather than chooses.

---

## 8. MCTS chance nodes

### 8.1 Node model (mcts.py:73)

A chance node is the MCTSNode for a reveal state. Add two fields:
```python
is_chance: bool = False                          # set in find_or_create_node
chance_counts: dict[Action, int] = field(default_factory=dict)  # per-outcome round-robin counter
```
In `find_or_create_node` (mcts.py:280):
```python
d = decider_of(state)                 # int | None (None at a reveal node)
is_chance = d is None
node = MCTSNode(state=state,
                decider=0 if is_chance else d,   # frame label when is_chance; real player otherwise
                is_chance=is_chance, search=self, ...)
```
**Frame convention.** Set a chance node's `decider = 0` (the canonical P0 reference frame —
`evaluate_leaf` already returns P0-frame values). This keeps the **backprop loop and UCB
read unchanged** (mcts.py:752 and 761): a chance node accumulates `+leaf_p0` (P0 frame) and its
decision-node parent reads it with the standard `child.decider != parent.decider` sign-flip
(flips iff the parent is P1, which is correct for a P0-frame value). `is_chance` — not `decider`
— flags routing. Document that for chance nodes `decider` is a frame label, not a player.

Round-robin makes the visit mix over outcomes exactly uniform, so a chance node's plain
`value_sum/visits` converges to the uniform expectation `Σ (1/k) V(child)` — no weighted
estimator needed. Round-robin reads a **per-node counter** `chance_counts[outcome]` (bumped on
each route), *not* `child.visits`: under the transposition DAG a post-reveal child can have other
parents, so `child.visits` is inflated by sims that never came through this chance node and would
skew the routing. The counter records only this node's own routing, so it stays uniform
regardless of sharing — correct always, ≤3 ints per chance node.

### 8.2 The descent (`_simulate`, mcts.py:697)

Chance nodes are **transparent**: always routed through, never expanded-as-leaf, never
evaluated. The leaf is always a decision or terminal node. Revised descent:

```
path = [root]; node = root
while True:
    if node.is_terminal(): break
    if node.is_chance:
        a = self._chance_route(node)                 # round-robin pick + increment counter
        child = node.children.get(a)
        new = child is None
        if new:
            child = find_or_create_node(step(node.state, a), parent=node, action_from_parent=a)
        path.append(child); node = child
        if new: break        # freshly created post-reveal decision node = leaf
        else:   continue     # existing outcome → keep descending
    # ---- decision node ----
    populate node._legal_actions if None
    if not node._legal_actions: break                # defensive
    if node._unvisited_actions:
        a = pick_unvisited(node); node._unvisited_actions.discard(a)
        child = node.children[a] if isinstance(a, MacroFencingAction) \
                else find_or_create_node(step(node.state, a), parent=node, action_from_parent=a)
        add_edge if macro
        path.append(child); node = child
        if node.is_chance: continue   # expanded into a chance node → route through it next
        break                          # decision/terminal leaf
    a = self._select_via_ucb(node); node = node.children[a]; path.append(node)

leaf_value_p0 = evaluate_leaf(node.state)            # node is never a chance node here
backprop over path (unchanged; chance nodes have decider=0 → P0 frame)
```

`_chance_route(node)`: ensure `node._legal_actions` populated (the RevealCards),
`a = argmin_{candidate} chance_counts.get(a, 0)` with RNG tiebreak, increment
`chance_counts[a]`, return `a`. First k routes create the k outcome children (each a leaf when
created); later routes balance and descend.

Note the two places a chance node is entered: (1) SELECT descends into an existing chance node;
(2) EXPAND of a decision node's round-ending action *creates* a chance node — handled by the
`if node.is_chance: continue` after expansion so we route through rather than evaluate it.

### 8.3 Re-root across a real reveal

After the real game reveals the true card (dealer), the agent's next call is at the post-reveal
decision state. `find_or_create_node` returns its node (created during search if a sim routed
through that outcome; fresh otherwise) and `re_root` (mcts.py:324) prunes to its subtree — the
chance node becomes an ancestor of the new root and is dropped along with the counterfactual
outcome subtrees, by the existing reachability walk. **No new code.** Tree-reuse benefit exists
only if search reached past the boundary. Shared-tree self-play is unaffected — the chance node
is just another shared node.

`MCTSAgent.__call__` is only ever invoked at decision states (the driver routes reveals to the
dealer); a defensive assert `decider_of(state) is not None` documents the contract.

---

## 9. Heuristic de-cheat (`_basic_wish_revealed_round`, heuristic.py:474)

The caller (`_hubris_empty_room_value`, heuristic.py:696) only uses the reveal round when
basic_wish is still in the *future* (`state.round_number < basic_wish`); once revealed it takes
the `now+2` branch and ignores the historical round. So `revealed: bool` is fully sufficient:
```python
sp = get_space(state.board, "basic_wish_for_children")
if sp.revealed:
    return state.round_number          # caller's `<` test false → unchanged "revealed" branch
future = [s for s in (5, 6, 7) if s > state.round_number]
return sum(future) / len(future)       # 6.0 (r≤4), 6.5 (r=5), 7.0 (r=6) — E[reveal | unrevealed]
```
Return type widens `int|None → float`; the `None` case disappears (basic_wish is always a known
stage-2 card). `fill_round` becoming a float flows through `max(0, 12 - fill_round)` fine.

---

## 10. Encoder (encoder.py:317,322)

`sp.round_revealed <= rn` → `sp.revealed` (two sites). The emitted feature vector is **identical**
(it already encoded revealed-ness as 0/1), so `ENCODING_VERSION` does not change and existing
checkpoints remain valid.

---

## 11. Testing strategy

Per-seed game identity vs. the old engine is **not** required (the round-1 fix and the evaluator
de-cheat legitimately change play — user-approved). Determinism-after-`setup` still holds (the new
engine is reproducible from a seed; it just needn't match the old engine's per-seed game).
Validation rests on:

1. **The full test suite** (logic correctness), migrated where needed — `play_game`-based full-game
   tests gain `setup_env` + the dealer; `random_agent_play`-based tests stay env-free (they
   self-sample reveals), needing only tolerance for `RevealCard` entries in their traces.
2. **No-leak (load-bearing).** MCTS search behavior is identical across two `Environment`s that
   share the same revealed prefix but differ in the hidden future — the actual "it stopped
   cheating" assertion (trivially true by construction since MCTS never reads the env; the test
   pins it).
3. **Aggregate sanity (optional, cheap).** Over many seeds, score / win-rate distributions are
   unchanged within noise — catches gross regressions without demanding per-seed identity.

Unit tests:
- `count(revealed stage cards) == round_number` at every WORK state of a full game.
- Chance node: round-robin covers all ≤3 outcomes; `mean_q` → uniform average; chance nodes are
  never leaf-evaluated and never UCB-select their children.
- Same-revealed-set states recombine (construct two states via factories differing only in past
  reveal order; assert equal hash / same transposition node).
- The dealer's true card is always in `_enumerate_pending_reveal`'s candidate set.
- `_basic_wish_revealed_round` returns 6 / 6.5 / 7 at rounds 4 / 5 / 6 when unrevealed, and the
  current round when revealed.
- Evaluator `_eval` averages over the ≤3 outcomes at a nature node (heuristic and NN agents).
- Migrate `play_game`-based full-game tests to `setup_env` + dealer; leave `random_agent_play`-based
  tests env-free (self-sampling), adjusting only any exact-trace assertions for `RevealCard` entries.

---

## 12. Sequencing (de-risk the blast radius)

1. **State + reveal-as-action + env.** State split (`revealed: bool`, order → `Environment`),
   `RevealCard` / `PendingReveal`, the prep restructure (§4.3, reveal-only-turns-card),
   enumerator, `setup_env`, dealer-aware `play_game`/drivers, heuristic + encoder migration. With
   round 1 as a nature step, this **subsumes the round-1 accumulation bug** (§3.3) — no separate
   step-0 fix. Gate: full test suite passes (after test-harness migration) + `count ==
   round_number` invariant.
2. **MCTS chance node.** `is_chance` + `chance_counts`, `find_or_create_node`, the `_simulate`
   descent. Only consumer that branches. Gate: no-leak test + chance-node units; MCTS-vs-baseline
   match strength not regressed beyond noise.
3. **Evaluator averaging + de-cheat** (the `_eval` wrapper and `_basic_wish`; may land in step 1
   or here). They shift heuristic play, so **run the V3 re-validation** (champion vs the 8-config
   ensemble) and confirm no regression. Re-tune only if it regresses.

## 13. Documentation updates on landing

**Style note (load-bearing):** `CLAUDE.md`, `MCTS_DESIGN.md`, and `ENGINE_IMPLEMENTATION.md` describe
the code **as it is** — write these edits as current-state descriptions (the reveal mechanism,
`PendingReveal`, chance nodes, the `Environment`, as they exist), **not** as before/after deltas. The
chronological "what changed / from-to / bug caught" narrative belongs only in `CHANGES.md` and
`SESSION_HISTORY.md`.

**`CLAUDE.md` (Required):**
- *Foundations → Engineering invariants → "Determinism after setup":* describe the public-state /
  `Environment` / `observe` split — the hidden order lives in the `Environment` (built at `setup`),
  reveals are nature steps that consume it, and `GameState` holds only common knowledge (the §3.6
  three layers). "All randomness resolved in `setup`" still holds.
- *Foundations → "Thinking about Agricola":* the round-card reveal is nature's move (a chance event);
  the engine state holds only common knowledge.
- *Phase 1 → state model:* the **decider rule** includes the nature case — a `PendingReveal` carries
  `player_idx = None`, so `decider_of` returns `None`. Document `ActionSpaceState.revealed: bool`, the
  order living in the `Environment` (not `BoardState`), and `setup_env`'s `(GameState, Environment)`.
- *Phase 1 → pending stack:* `PendingReveal` as a nature/phase frame.
- *Phase 1 → transition model + phase walk:* `RevealCard` in `_apply_action`; PREPARATION hosts the
  reveal nature step (the two-state Case 2 + `_complete_preparation`).
- *Phase 2.2 → MCTS:* describe the chance-node handling of reveals (round-robin, never-eval-chance,
  frame=0) as part of the current MCTS design.
- *Documentation index:* add the `HIDDEN_INFO_DESIGN.md` row.
- *Directory tree:* add `agricola/environment.py`; refresh the descriptions for `state.py`, `setup.py`,
  `actions.py`, `pending.py`, `engine.py`, `legality.py`, `constants.py`, `agents/base.py`,
  `agents/mcts.py`, and the entry points.

**`ENGINE_IMPLEMENTATION.md` (Required):**
- §1 dispatch — `RevealCard` in `_apply_action`; the PREPARATION two-state walk + `_apply_reveal_card` /
  `_complete_preparation`.
- §2 pending stack — `PendingReveal` (nature frame, `player_idx=None`, provenance `"phase:reveal"`); the
  decider rule's `None` case.
- §4 Harvest — the reveal at the start of each round (after the harvest exits to PREPARATION).
- §6 Card-trigger machinery — the `Environment` "nature policy" seam (`env.resolve`) and the `observe`
  forward-compat; the future card-draft as a pre-round-1 nature phase.

**`MCTS_DESIGN.md` (Required):**
- Glossary — "chance node," "nature decider (`None`)," "determinization / ISMCTS (and why not — §2)."
- §3 architecture — the chance-node design (symmetric-info → chance nodes; round-robin; never-eval-chance; frame=0).
- §4 data structures — `MCTSNode.is_chance` + `chance_counts`.
- §5 algorithm — the `_simulate` chance routing + `_chance_route`; re-root across reveals.

**`IMPLEMENTATION_CHOICES.md` (Recommended — "may need revisiting with cards"):** round-1 pre-deal
(start point moves to the draft when cards land); symmetric-info → chance-nodes-suffice (→ ISMCTS /
determinization under asymmetric hands); the `observe()` identity-today seam; the `decider = None`
sentinel; `chance_counts` vs `child.visits`.

**`FILE_DESCRIPTIONS.md` / `TEST_DESCRIPTIONS.md` (Required):** new `environment.py`; refreshed
descriptions for every core-edit module (§15) and the migrated/new tests.

**`CHANGES.md` (Recommended):** a "Change N — Hidden-information refactor" entry (the cross-cutting
delta narrative: public/private state split, reveal-as-action, MCTS chance nodes).

**`STRATEGY.md` (Recommended):** the hidden-information handling in the MCTS-approach rationale — why
chance nodes over ISMCTS / determinization (symmetric-info), and the common-knowledge / `observe`
forward-compat for the card phase.

**`SESSION_HISTORY.md` (Required on landing):** the session entry — what was built, the decisions, the
round-1 accumulation bug caught + fixed.

**Lighter / one-line (Optional):** `FIRST_NN.md` (encoder migrated with byte-identical output, no
`ENCODING_VERSION` bump; `play_recording_game` takes the env); `V3_DESIGN.md` (the `_basic_wish` change
+ re-validation outcome); `POSSIBLE_NEXT_STEPS.md` (asymmetric-info ISMCTS as a card-phase direction);
`WEB_UI_PLAN.md` (env threading / reveal display); `nn_models/REGISTRY.md` (**no change** — no retrain,
no version bump); `README.md` (optional one-liner).

**No change:** `RULES.md` (engine-internal; the round-1 fix just makes the engine match existing rules),
`task_files/*` (frozen), `PROFILING.md`, `FRONTIER_OPT_DESIGN.md`, `HUBRIS_V1_NOTES.md`,
`V3_TRAINING_PIPELINE.md`, `HEURISTIC_TUNING_PLAN.md`, `POSSIBLE_SPEEDUPS.md`, `CLEANUP.md`.

---

## 14. Open questions for the reviewer

**Resolved in review:**
- *Nature sentinel* → `decider_of -> int | None`, `PendingReveal.player_idx = None` (§4.2). `None`
  is not a valid index, so a missed guard fails loudly.
- *Per-seed identity* → not required; validation is test-suite + invariants + aggregate sanity (§11).
- *MCTS chance-node frame* → `is_chance` flag + `decider = 0` (frame label); backprop/UCB unchanged (§8.1).
- *Chance routing counter* → per-node `chance_counts` dict, not `child.visits` (which is inflated
  by other DAG parents under transposition); correct always, trivial cost (§8.1).
- *Round-1 reveal* → modelled as a nature step (§3.3, §4.5): uniform across all 14 rounds, exposes
  round 1's real k=4 randomness, and **subsumes** the round-1 accumulation bug (no standalone fix).
- *Forward-compat for private hands* → common-knowledge `GameState` + hidden-ground-truth
  `Environment` + an `observe(state, env, i)` seam (identity today); §3.6.
- *`Environment` home* → new module `agricola/environment.py` (§3.4).
- *`setup` signature* → additive `setup_env(seed) -> (GameState, Environment)` (with `setup =
  setup_env()[0]`), **pre-dealing round 1** so `setup` returns a round-1 WORK state — content-
  compatible with today (§3.3, §3.5).

**Still open:** none — all design questions resolved; the doc is implementation-complete.

---

## 15. Affected files — full impact map

*(From an exhaustive repo sweep — package, scripts, tests, entry points. Line numbers pre-refactor.)*

**New file:** `agricola/environment.py` — `Environment` (+ `resolve` / `reveal_action`; later `observe`).

**Core edits (the change itself):**
- `state.py` — `ActionSpaceState.round_revealed:int` → `revealed:bool` (63); drop
  `BoardState.round_card_order` (122) and the `with_space` rebuild kwarg (138).
- `setup.py` — `_make_action_spaces` (45–93) writes `revealed`; new `setup_env` builds the
  `Environment`, pre-deals round 1, and returns the round-1 WORK state; `setup = setup_env()[0]` (156–180).
- `actions.py` — add `RevealCard` + to the `Action` union (243).
- `pending.py` — add `PendingReveal` + to the `PendingDecision` union (452).
- `engine.py` — `_apply_action` RevealCard dispatch (186); split `_resolve_preparation` (470) into
  the Case-2 push + `_apply_reveal_card` + `_complete_preparation` inside `_advance_until_decision`
  (358); refill keyed on `revealed` (488).
- `legality.py` — `_is_available` `revealed` (153); add `_enumerate_pending_reveal` +
  `PENDING_ENUMERATORS` row (1493).
- `constants.py` — add `stage_of_round` / `STAGE_OF_ROUND` (near STAGE_CARDS, 46).
- `agents/base.py` — `decider_of -> int|None` (119); `play_game` `dealer` arg + `d is None` branch
  (437–455); the `_eval` averaging wrapper, routing the six `self.evaluator(...)` calls (287, 338,
  341, 345, 398, 403).
- `agents/mcts.py` — `MCTSNode.is_chance`/`chance_counts` (73); `find_or_create_node`
  is_chance/decider=0 (280); `_simulate` chance routing (697).
- `agents/heuristic.py` — `_basic_wish_revealed_round` expected-value (474/696).
- `agents/nn/encoder.py` — `round_revealed`→`revealed` (317, 322); `setup(0)` in `feature_names`
  (507/510) still returns a round-1 WORK state, so no change there.
- `agents/nn/recording.py` — `play_recording_game` takes the env/dealer (33, 78, 83).

**Field-rename readers — `round_revealed` → `revealed` (migrate every site):**
- engine/encoder: legality.py:153, engine.py:488, encoder.py:317/322.
- UI: play.py:181–184,550; play_web.py:477–495 (`_space_stage`, wire format).
- script: profile_states.py:114–124,393 (`mark_all_revealed`).
- tests — every `with_space(…, round_revealed=…)` / `_set_space(…, round_revealed=…)`:
  test_cultivation:40, test_animal_markets:36, test_legality_atomic:43–52,244–247,
  test_legality_non_atomic:53,557–675, test_resolution_atomic:40–44, test_house_redevelopment:42,
  test_farm_redevelopment:62, test_major_improvement:46, test_fencing:69, test_mcts:383;
  factories.py:125 (docstring).

**`round_card_order` removal readers:** setup.py:156–167; state.py:122/138; heuristic.py:478 (the
leak); constants.py:58 (comment); tests test_state.py:97/104/129, test_scoring.py:90–93,
test_replace.py:92; profile_states.py:121.

**`BoardState(…)` / `ActionSpaceState(…)` constructions:** setup.py; state.py:135; test_scoring.py:90;
test_replace.py:52/92; bench_replace.py:49/54.

**`setup` → `setup_env` (full-game drivers; bare `setup` returns a round-1 WORK state, content-compatible):**
- entry points: play.py:885, play_web.py:719/1080, play_heuristic_game.py:171, play_random_game.py:232.
- scripts: play_match:112, play_mcts_match:242, nn/play_match:265, play_mcts_v1_vs_v1heur:110,
  play_mcts_v1_vs_v3:142, run_exhaustive_vs_greedy_match:60, measure_mcts_tree:187,
  measure_exhaustive_leaves:120, measure_v3_prior_distribution:85, profile_engine:75,
  profile_frontier_helpers:219, profile_states (≥9 sites), bench_replace:30, nn/generate_training_data:482.
- agricola: encoder.py:507/510 (returns round-1 WORK, fine), schema.py:95 (doc).
- 36 test files call `setup()` (top: test_restricted_actions 38, test_engine 30, test_nn_encoder 23,
  test_mcts 20, test_harvest_feed 20, test_state 18, …): only those that *drive full games* migrate
  to `setup_env` + dealer; those that inspect or build on the round-1 state keep working (modulo
  the round-1 accumulation fix).

**`play_game` callers (gain `dealer`):** base.py:437(def); play_heuristic_game:178; scripts
play_match:114, play_mcts_match:251, nn/play_match:268, play_mcts_v1_vs_v1heur:117,
play_mcts_v1_vs_v3:149, run_exhaustive_vs_greedy_match:60, measure_mcts_tree:189,
profile_frontier_helpers:219; tests test_agents_heuristic, test_mcts, test_nn_agent,
test_nn_records, test_harvest_integration, test_engine, test_frontier_opt, test_fencing.

**`decider_of` consumers (handle `None`):** base.py (the `!= decider` stops at 304/339/388 already
tolerate `None`; `play_game`:455 needs the branch); mcts.py:301/491/561/582/612; recording.py:78;
encoder.py:303; **play.py:109 — a *duplicate* `decider_of` def** (+115/222/768/899); scripts
measure_exhaustive_leaves:75/125, measure_v3_prior_distribution:90, nn/validate_dataset:187.

**Indirect scripts (drive via the match runners — fixed transitively, no direct setup/play_game):**
tune_heuristic.py (`from play_match import play_match`), run_iterative_v3.py (orchestrates tune),
mcts_sweep.py (`play_match_parallel`), nn/eval_vs_ensemble.py (subprocess nn/play_match),
nn/retention_eval.py.

**No change needed (verified):**
- `filter_implemented` (test_utils.py:64) — only constrains `PlaceWorker` space-ids; returns
  `True` for every other action type, so `RevealCard` already passes.
- `random_agent_play` (test_utils.py:73) — picks a random legal action each step, so at a nature
  node it picks a random `RevealCard` (= uniform self-sampling); env-free, seed-deterministic.
  Callers play_random_game / count_replaces / profile_engine need no env.

**Name-conflict check (all clear):** `Environment`, `RevealCard`, `PendingReveal`, `NATURE`,
`stage_of_round`, `setup_env`, `resolve`, `observe` are unused — no collisions.

**`round_number = 0` transient — safe:** heuristic/scoring never evaluate at round 0 (the round-1
reveal is dealer-resolved at game start, before any agent call); `_complete_preparation` increments
before indexing `future_resources`. The `round_number`-comparison sites in heuristic.py
(372–376, 717, 833, 973–977, 2102, 2339) only ever see `round_number ≥ 1`.

---

## 16. Implementation action plan

Expands §12 into an ordered checklist. Three independently-mergeable phases, suite green at each
gate. Within Phase 1 the **engine-core** steps must land together (the codebase won't run a game
until all are in); the migration steps after them fix the resulting breaks.

### Phase 0 — prep
- Branch off main.
- Snapshot aggregate baselines: run a few hundred random + heuristic games on main and record the
  score / win-rate distributions, for the Phase-1 aggregate-sanity gate (§11). *(Per-seed identity
  is not a gate — §11.)*

### Phase 1 — state + reveal-as-action + env

**Engine core (land together):**
1. `constants.py` — add `STAGE_OF_ROUND` / `stage_of_round(round)` next to `STAGE_CARDS` (§5.3).
2. `actions.py` — `RevealCard(card: str)` + to the `Action` union (§4.1).
3. `pending.py` — `PendingReveal(player_idx=None, initiated_by_id="phase:reveal")` + to `PendingDecision` (§4.2).
4. `state.py` — `round_revealed:int → revealed:bool`; drop `BoardState.round_card_order`; fix `with_space` (§3.1–3.2).
5. `agricola/environment.py` (new) — `Environment(round_card_order)` with `resolve` / `reveal_action` (§3.4).
6. `legality.py` — `_is_available` → `sp.revealed`; add `_enumerate_pending_reveal` + `PENDING_ENUMERATORS` row (§5.1–5.2).
7. `engine.py` — `_apply_action` RevealCard dispatch; `_apply_reveal_card`; split `_resolve_preparation`
   into the two-state Case 2 (`count == round_number` → push `PendingReveal`; else `_complete_preparation`);
   refill on `revealed` (§4.3). The alternation guard is unchanged (§4.4) — but assert it: a `RevealCard`
   step must leave `current_player == starting_player`.
8. `setup.py` — write `revealed` bools; add `setup_env(seed) -> (GameState, Environment)` that builds the
   env, **pre-deals round 1** (apply `env.reveal_action` to the round-1 nature node) and returns the
   round-1 WORK state; `setup(seed) = setup_env(seed)[0]` (§3.3, §3.5).
9. `agents/base.py` — `decider_of -> int|None`; `play_game(initial, agents, dealer)` with the `d is None`
   branch; the `_eval` averaging wrapper (route the six evaluator calls) (§6, §7).

*Engine-core gate:* a hand-driven full game (`setup_env` + `play_game`, two heuristics, `env.resolve`
dealer) completes and scores; `count(revealed) == round_number` holds at every WORK state.

**Migrations (fix the breaks):**
10. `agents/heuristic.py` — `_basic_wish_revealed_round` expected-value (§9).
11. `agents/nn/encoder.py` — `round_revealed → revealed` (§10).
12. `agents/nn/recording.py` — `play_recording_game` takes the env/dealer.
13. Entry points (`play.py` incl. its duplicate `decider_of`, `play_web.py`, `play_heuristic_game.py`)
    + scripts (the `setup→setup_env` / `play_game`-dealer / `decider_of`-None sites in §15).
    `random_agent_play` and its callers (`play_random_game`, `count_replaces`, `profile_engine`) need **no** change.
14. Tests — `round_revealed→revealed` at every `with_space`/`_set_space` site; `play_game`-based
    full-game tests → `setup_env`+dealer; `decider_of`-None handling; the `test_scoring`/`test_replace`
    BoardState/ActionSpaceState constructions; `test_state` round_card_order assertions.
15. New tests — `count==round_number` invariant; `stage_of_round`; dealer-card-always-a-candidate;
    same-revealed-set recombination; `_basic_wish` = 6/6.5/7; `_eval` averaging (heuristic + NN).

*Phase-1 gate:* full suite green; aggregate score / win-rate distributions within noise of the Phase-0
baseline. **Subsumes the round-1 accumulation bug — no separate step-0.**

### Phase 2 — MCTS chance node
16. `agents/mcts.py` — `MCTSNode.is_chance` + `chance_counts`; `find_or_create_node` sets them
    (`decider=0` frame label); `_simulate` chance routing + `_chance_route` (§8).
17. New tests — round-robin covers all outcomes; `mean_q` → uniform average; chance nodes never
    leaf-evaluated / never UCB-select their children; re-root across a reveal prunes the counterfactual
    subtrees; the **no-leak** test (two envs sharing a revealed prefix → identical search).

*Phase-2 gate:* no-leak + chance-node units green; MCTS-vs-baseline match strength not regressed beyond noise.

### Phase 3 — validation + docs
18. **V3 re-validation** — champion vs the 8-config ensemble (the `_eval`/`_basic_wish` changes shift
    heuristic play); re-tune only on regression (§12 step 3).
19. Update the `.md` docs (§13) and add the `SESSION_HISTORY.md` + `CHANGES.md` entries.
