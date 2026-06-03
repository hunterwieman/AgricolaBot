# Hidden-Information Refactor — Design Doc

**Status:** proposed (not yet implemented). This is the working spec for removing the
round-card-order information leak from the engine and modelling the reveal as an explicit
chance event. The user has reviewed and agreed the high-level shape across a design
conversation; this doc is the careful, file-level plan for implementation review.

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
tool here. The fan-out is tiny (≤3) and the reveal distribution is exactly uniform, so chance
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
when their `RevealCard` transition fires (round 1's card is flipped at `setup`, see §3.3).

**Why bool, in full:** the round-of-reveal is non-Markov history. The only forward-relevant
consequence of revealing earlier vs later is how many goods piled up, and that is already
carried by `accumulated` / `accumulated_amount`. Two states with the same revealed set and the
same accumulated loads are future-equivalent; `bool` lets them share one DAG node, `int` would
wrongly split them. (The refactor is also what first makes this matter: with the order baked in,
one game = one fixed order, so `int` never blocked a recombination; once the order is hidden and
chance branches produce same-set/different-order states in one tree, `bool` is required for the
recombination to fire.)

Invariant worth asserting in tests: `sum(sp.revealed for stage-card spaces) == round_number`,
**at WORK decision states** (it is transiently false at the reveal chance node, by design — see
§4.3).

### 3.2 `BoardState` (state.py:106) and `with_space` (state.py:130)

- Remove the `round_card_order: tuple` field.
- `with_space` currently rebuilds `BoardState(..., round_card_order=board.round_card_order)`
  (state.py:138) — drop that kwarg.

The hidden order moves to a new `Environment` object (§3.4).

### 3.3 `setup.py`

`_make_action_spaces` (setup.py:45) currently stamps `round_revealed = i+1` on each stage card.
After:

- Permanent spaces → `revealed=True`, accumulation pre-loaded as today.
- The **round-1 card** (`round_card_order[0]`) → `revealed=True`, and if it is an accumulation
  space its **round-1 goods preloaded** like a permanent. *Today setup leaves it empty, so a
  round-1 `sheep_market` sits at 0 sheep in round 1 — a **pre-existing bug** (§14): every other
  reveal gets its goods on its reveal round via `_resolve_preparation`; only round 1 misses it
  because setup handles round 1. Fix it first in a standalone commit (§12 step 0).*
- All other stage cards (`round_card_order[1:]`) → `revealed=False`, accumulation empty.

`setup` no longer stores the order on the board. Instead it returns the order inside an
`Environment` (§3.4). See §3.5 for the function-signature decision.

### 3.4 New `Environment` object (the dealer)

The hidden order lives outside `GameState`, held by the game driver. Proposed: a small frozen
dataclass (new module `agricola/environment.py`, or appended to `setup.py`).

```python
@dataclass(frozen=True)
class Environment:
    """Holds the hidden round-card order for one game. The driver consults it to
    resolve reveal chance events; agents and MCTS never see it."""
    round_card_order: tuple  # length 14; order_card[i] is round i+1's card

    def reveal_action(self, state: GameState) -> "RevealCard":
        # At a reveal node, round_number is the round just COMPLETED (§4.5); the
        # reveal turns up the NEXT round's card = order[round_number] (order[i]
        # is round i+1's card; round 1's card was applied at setup).
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

Keep `setup(seed) -> GameState` (returns the public state; tests and factory callers
unaffected) and add `setup_env(seed) -> tuple[GameState, Environment]` as the full constructor,
with `setup(seed)` defined as `setup_env(seed)[0]`. Both build the order once (single source —
no fragile RNG-replay).

A `GameState` from bare `setup` cannot be *driven across a reveal* (no dealer); that's by design.
Every full-game driver (and full-game test harness like `random_agent_play`) migrates to
`setup_env` + the dealer-aware loop (§6). Mid-game factory states that don't cross a boundary are
unaffected.

*(Alternative considered: change `setup` itself to return the tuple. Rejected — it breaks every
call site mechanically for no benefit over the additive `setup_env`.)*

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

### 4.2 `PendingReveal` frame (pending.py) + the NATURE sentinel

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
- Reveals fire at the start of rounds **2–14** (round 1 is applied at setup). 13 reveals total.
- Harvest interaction: on harvest rounds RETURN_HOME → HARVEST_* → PREPARATION (round<14) hits
  the reveal; after round-14's harvest, `_advance_until_decision` Case 7 goes to BEFORE_SCORING —
  **no round-15 reveal.**
- Round 14's reveal is a k=1 nature node turning up `farm_redevelopment`; kept uniform (§2).

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

`filter_implemented` (tests/test_utils) must admit `RevealCard`.

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
        action = dealer(state) if d == NATURE else agents[d](state)
        trace.append(action)
        state = step(state, action)
    return state, trace
```
`dealer = env.reveal_action`. (Reveals appear in the trace as real transitions — they are not
singletons in the legal-actions sense, just resolved by the dealer's policy.)

**Drivers/harnesses to update** (each gains `setup_env` + a NATURE branch, or routes through the
updated `play_game`): `agents/base.play_game`, `tests/test_utils.random_agent_play`, `play.py`,
`play_web.py`, `play_random_game.py`, `play_heuristic_game.py`, `scripts/play_match.py`,
`scripts/play_mcts_match.py`, `scripts/nn/generate_training_data.py`, and
`agents/nn/recording.py` (`play_recording_game` takes the env to supply reveals; reveals are not
player-decision snapshots, so recorded dataset content is unchanged). UIs (`play.py`,
`play_web.py`) need the env passed in; displaying "revealed in round X" is cosmetic and, if
wanted, reconstructable from the env without entering `GameState`.

Any *generic* rollout that crosses a boundary without a dealer (none today — `random_agent_play`
becomes dealer-aware) would have to resolve nature itself (uniform sample).

---

## 7. Evaluator averaging over reveals (heuristic **and** NN)

### 7.1 The problem

`EvaluatorAgent` lookahead (`_lookahead_value` → `_skip_singletons` → `_rollout_value`,
base.py:273–403) stops when `decider_of(state) != decider` and then calls
`self.evaluator(state, decider, config)`. After this refactor, stepping a round-ending placement
lands on a **nature node** (`decider_of == NATURE`), so the evaluator would be called on a
between-rounds state — out-of-distribution for the NN, and ignoring the reveal it can't see.

### 7.2 The fix

Route **every** evaluator call through one helper that expands and averages at nature nodes:
```python
def _eval(self, state, decider):
    if decider_of(state) == NATURE:
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
estimator needed. The per-edge `chance_counts` (not `child.visits`, which is DAG-global under
transposition) is what makes the routing uniform even when a post-reveal child is shared.

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
dealer); a defensive assert `not decider_of(state) == NATURE` documents the contract.

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

1. **The full test suite** (logic correctness), migrated where needed — test harnesses that play
   full games (`random_agent_play` and friends) move to `setup_env` + the dealer-aware loop.
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
- Migrate existing full-game tests (`random_agent_play` and friends) to `setup_env` + dealer.

---

## 12. Sequencing (de-risk the blast radius)

0. **Round-1 accumulation bug fix (standalone).** Tiny `setup.py` correction — the round-1 card
   gets its reveal-round goods (§3.3). Independently reviewed and merged before the refactor.
1. **State + reveal-as-action + env.** State split (`revealed: bool`, order → `Environment`),
   `RevealCard` / `PendingReveal`, the prep restructure (§4.3, reveal-only-turns-card),
   enumerator, `setup_env`, dealer-aware `play_game`/drivers, heuristic + encoder migration. Gate:
   full test suite passes (after test-harness migration) + `count == round_number` invariant.
2. **MCTS chance node.** `is_chance` + `chance_counts`, `find_or_create_node`, the `_simulate`
   descent. Only consumer that branches. Gate: no-leak test + chance-node units; MCTS-vs-baseline
   match strength not regressed beyond noise.
3. **Evaluator averaging + de-cheat** (the `_eval` wrapper and `_basic_wish`; may land in step 1
   or here). They shift heuristic play, so **run the V3 re-validation** (champion vs the 8-config
   ensemble) and confirm no regression. Re-tune only if it regresses.

## 13. Doc/registry updates on landing

- Update `CLAUDE.md`: the documentation index (add this file) and the directory tree
  (`environment.py` if added, the `revealed`/`RevealCard`/`PendingReveal` field/action notes),
  and the Foundations note that the only hidden info is now modelled via chance nodes.
- `ENGINE_IMPLEMENTATION.md`: the reveal transition + `PendingReveal` in §2, the prep split in §1.
- `MCTS_DESIGN.md`: a chance-node section (§3.x) + the `is_chance`/round-robin descent.
- `FILE_DESCRIPTIONS.md`, `TEST_DESCRIPTIONS.md`: new module/fields/tests.

---

## 14. Open questions for the reviewer

**Resolved in review:**
- *Nature sentinel* → `decider_of -> int | None`, `PendingReveal.player_idx = None` (§4.2). `None`
  is not a valid index, so a missed guard fails loudly.
- *Round-1 accumulation* → a pre-existing bug; fix in a standalone commit first (§3.3, §12 step 0).
- *Per-seed identity* → not required; validation is test-suite + invariants + aggregate sanity (§11).
- *MCTS chance node frame* → `is_chance` flag + `decider = 0` (frame label); backprop/UCB unchanged (§8.1).

**Still open:**
1. **`Environment` home:** new `agricola/environment.py` vs appended to `setup.py`. Leaning new
   module (keeps `setup.py` focused; `Environment` is a first-class game object).
2. **`setup` signature:** additive `setup_env` (recommended, §3.5) vs changing `setup`'s return.
3. **Chance routing counter:** per-node `chance_counts` dict (recommended for DAG correctness)
   vs leaning on `child.visits` (simpler, wrong under post-reveal state sharing — likely rare but
   not provably absent).
4. **Round-1 reveal mechanism:** with the §3.3 bug fixed, still decide whether round 1's card is
   applied at `setup` (recommended — round 1 is public from the start) vs modelled as an initial
   nature step before the first WORK decision (uniform, but adds a nature node to drive past at
   game start).
