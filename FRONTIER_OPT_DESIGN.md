# Frontier & Accommodation Optimization — Design Doc

Design spec for speeding up the Pareto-frontier / accommodation helpers that dominate MCTS
self-time. Everything here is **toggleable** so each layer can be A/B-profiled and disabled
independently if it regresses or is ever suspected of a correctness bug.

> **Status: IMPLEMENTED.** All levels are live behind `agricola/opt_config.py`
> (`PARETO_OPT_LEVEL` 0-3, `FENCE_SCAN_CACHE`), **now default-on** (originally default-off so the
> baseline was unchanged; flipped to on once proven — level 0 remains the unoptimized baseline). Landed:
> Phase 0 (`breeding_food_gained`, CLEANUP.md Cleanup 4); Phase 1 (Level-1 algorithmic); Phase 2+3
> (Level-2 exact/clipped caches + Level-3 Φ); the S7 fence-scan cache; and the measurement harness
> `scripts/profile_frontier_helpers.py` (§8.2). Validated by `tests/test_frontier_opt.py` (cross-level
> equivalence at all levels + fence on/off trace parity) — full suite 935 pass. **Measured:**
> per-call food_payment ~53×, harvest_feed ~7×, pareto/breeding ~1.8×; end-to-end MCTS ~8-9% wall-clock
> (level 3 + fence cache vs baseline, 150 sims). **Deferred (profile-gated, not worth it yet):** the
> feeding inner `food_payment` cache (§6.5 — the 95% outer hit rate doesn't justify it) and the
> structured Φ build (§6.2 — the shipped Φ uses the naive `can_accommodate` build, a deferred speed
> refinement).

---

## 1. Purpose & scope

MCTS is slow, and a large fraction of its self-time is recomputation of the accommodation /
Pareto helpers in `agricola/helpers.py`:

- `pareto_frontier` — animal-market accommodation (sheep/pig/cattle market).
- `breeding_frontier` — harvest breeding.
- `harvest_feed_frontier` / `food_payment_frontier` — harvest feeding.

Plus one sibling in `agricola/legality.py`:

- the fence-universe scan (`_any_legal_pasture_commit` / `_enumerate_pending_build_fences`).

The waste has a specific shape: these helpers read only a small **projection** of `GameState`,
so two different states that agree on that projection produce identical output — yet each
recomputes from scratch. MCTS reaches the same projection from many different paths
(transpositions, action reorderings, repeated visits), so the redundancy is large.

This doc covers two orthogonal axes of speedup, organized into three cumulative levels plus an
independent fencing track:

- **Algorithmic** (Level 1) — make each computation cheaper (reduce *miss cost*).
- **Caching** (Levels 2–3) — compute less often (reduce *miss count*).

---

## 2. Background

### 2.1 What each helper reads (its projection)

| Helper | Projection it actually depends on | Notes |
|---|---|---|
| `pareto_frontier` | `(pasture_capacities, num_flexible, s_avail, b_avail, c_avail)` + `rates` | `rates` only annotates food; **frontier itself is rate-independent** |
| `breeding_frontier` | `(pasture_capacities, num_flexible, s, b, c)` + `rates` | desired bounds derive from `(s,b,c)`; **frontier rate-independent** |
| `harvest_feed_frontier` | `(grain, veg, sheep, boar, cattle, food_owed, rates)` | uses cooking conversion, **not** pastures; **frontier IS rate-dependent** |
| `food_payment_frontier` | same as feed, one `paid` level | the param is *named* `food_owed`; the wrapper calls it for each `paid ∈ [0, food_owed]` |
| fence scan | `(farmyard, wood, subdivision_started)` | see S7 in `SPEEDUPS.md` |

`pasture_capacities` is the per-pasture capacity list; `num_flexible` = standalone stables + 1
(house pet). Both come from `extract_slots(player_state)`. `s_avail = animals.sheep +
gained.sheep`, etc.

Crucial asymmetry for caching:

- **Animal frontiers (`pareto_frontier`, `breeding_frontier`)**: the *set of Pareto-optimal
  animal configs* does not depend on `rates` at all — `rates` only decides the food number
  attached to each point. So `rates` can be dropped from the cache key and food annotated on
  retrieval.
- **Feed frontier**: `rates` change *which* remaining-goods configs are Pareto-optimal (how much
  you must consume to cover `food_owed` depends on conversion rates), so `rates` stays in the key.

### 2.2 Why existing caches miss this

- `legal_actions_cache()` (`agricola/legality.py`) keys on `id(state)` — the *same object*. The
  forest→sheep-market vs sheep-market→forest reorderings are different objects, never collide.
- The MCTS transposition table keys on the full `GameState` content hash — those two reorderings
  have *different* content (wood differs), so they don't collide either.

Both are blind to the projection. The new idea throughout: cache on the **value of the
projection** (cheap to hash because it's a short tuple), which collides across the wide set of
states that share it.

### 2.3 The double-call is already gone

Earlier this work assumed each helper ran twice per frame (enumerate + resolve). That was true
**only** for breeding, and `breeding_food_gained` (CLEANUP.md Cleanup 4) removed it.
`_execute_accommodate` and `_execute_convert` already compute food via a direct formula and never
re-enumerate. So every helper below is now called **once per relevant pending per state** — the
sole remaining payoff for caching is cross-node reuse in MCTS.

---

## 3. The toggle

A single cumulative knob covers the three pareto levels; the fencing cache is an independent
boolean (it's a different subsystem). Put these in a small new module
`agricola/opt_config.py` so both `helpers.py` and `legality.py` can import without cycles:

```python
# agricola/opt_config.py
# Cumulative levels; the §3 table has the animal-vs-feeding specifics.
# 0 = baseline (today's code)
# 1 = + algorithmic fast paths (no caching)
# 2 = + projection cache (animals: exact farm+caps; feeding: clipped outer)
# 3 = + coarse layer (animals: Phi farm-shape; feeding: inner food_payment)
PARETO_OPT_LEVEL: int = 3      # default-on (0 = the unoptimized baseline)

# Independent of the pareto levels (legality subsystem, not helpers).
FENCE_SCAN_CACHE: bool = True  # default-on
```

Semantics (cumulative — each level includes everything below it):

| Level | `pareto_frontier` / `breeding_frontier` | feed path | New code |
|---|---|---|---|
| 0 | brute box enumeration + O(n²) Pareto filter | brute box + filter | — |
| 1 | max-corner fast path + anchor pruning | `food_payment` rate-descending rewrite | algorithmic only |
| 2 | + exact LRU on rates-free frontier points | + **clipped** outer feed cache (`⊕ excess`) | cache wrappers |
| 3 | + Φ cache (clip + re-Pareto on miss) | + inner clipped `food_payment` cache (cross-`food_owed`) | Φ build / inner cache |

Note the asymmetry between the two paths' Level-3 entries. The animal Level 3 (Φ) is a real new
layer — it builds a feasibility-frontier structure and runs clip + re-Pareto per call. Feeding's
*coarsening* (clipping strategically-dead excess goods, since goods beyond `⌈food_owed/rate⌉` can
never be consumed) is **trivial** — inline `min` + a uniform `⊕ excess` translation that needs no
re-Pareto — so it is folded into **Level 2**, not deferred. The only feeding item that warrants
Level 3 is a genuinely separate second cache: the inner `food_payment` cache for cross-`food_owed`
reuse. See §6.5.

**Why a single nested knob:** the levels are genuinely cumulative for the animal frontiers (L3's
clip path wants L1's max-corner check; L3 stores into L2's exact cache as a hierarchy). A single
int keeps the common "turn it up / turn it down" workflow trivial and the test matrix small (4
settings, not 2ⁿ flag combinations). If finer control is ever needed for debugging, add private
override booleans — but start with the int.

**Read the flag once per call, cheaply.** Each helper branches on `PARETO_OPT_LEVEL` at the top.
The branch cost is one module-global read + an int compare — negligible relative to the work it
guards.

---

## 4. Correctness invariants (apply to every level)

Every level must produce **set-identical frontiers to Level 0** for the same input. The
optimizations are valid because of these standing facts:

1. **Pareto dimensions are the upstream goods only** (animals for pareto/breeding; the 5-tuple
   remaining-goods + begging for feed). Food surplus is never a Pareto dim. This is the
   "Preserving optionality" principle (CLAUDE.md Foundations) and is what licenses dropping
   `rates` from the animal-frontier key.
2. **`can_accommodate` is downward-closed**: if `(s,b,c)` is feasible and `(s',b',c') ≤ (s,b,c)`
   componentwise, then `(s',b',c')` is feasible. (Accommodating fewer animals is always
   possible.) This licenses the Φ clip lemma (§6.3) and the max-corner short-circuit (§5.2).
3. **Keeping/breeding-more weakly dominates releasing-for-food** (animal frontiers only), because
   food isn't a Pareto dim. So the componentwise-maximal config, when feasible, is the unique
   frontier point. Feeding has no analog — you must spend, not keep (§6.5 point 2).
4. **Food-payment frontier is generated by greedy fills in rate-descending order** (§5.1) — a
   property of the Level-1 algorithm; the ordering is load-bearing for correctness, not just speed
   (proven in Appendix A).

A projection cache needs **no explicit invalidation**: the key *is* the projection, so any change
to an input yields a different key. The only discipline required is clearing caches between tests
(§8).

---

## 5. Level 1 — Algorithmic fast paths (no caching)

Reduces the cost of a single computation. Helps every workload, MCTS or not; composes with the
caches above it.

### 5.1 `food_payment_frontier` — rate-descending nested enumeration

**Today.** Enumerates the full 5-D consumption box `[0,grain_cap]×…×[0,cattle_cap]`, filters
those meeting `food_owed`, then runs an O(n²) Pareto pass.

**New.** Enumerate consumption with goods ordered by **conversion rate, descending** (grain is
rate-1; rate-0 goods are excluded — they can never reduce begging). Each nested level bounds the
inner consumption by the residual need, so the leaves are exactly the minimal-consumption
corners — the frontier — with **no post-hoc Pareto filter**:

```python
# goods sorted by rate desc, rate-0 excluded; supply[i], rate[i] for the i-th good
def emit(level, remaining, partial):
    if level == n:
        if remaining <= 0:
            record(partial)                      # fully pays food_owed
        return
    upper = min(supply[level], ceil(max(0, remaining) / rate[level]))
    for x in range(upper + 1):
        partial[level] = x
        emit(level + 1, remaining - x * rate[level], partial)
```

**Why rate-descending is required (not just faster).** With a low-rate good outermost, each
increment of it barely shifts the burden onto an inner tight bound and emits a config dominated
by "one less of the low-rate good." High-rate-outermost makes each increment trade off against
the inner goods rather than be dominated. (Worked counterexample: rates `(1,3)`, `food_owed=4` —
low-first emits dominated points `(8,9)`,`(7,9)` under `(9,9)`; high-first emits only mutually
non-dominated corners.) **Proven sound + complete in Appendix A** — the enumeration emits exactly
the frontier (each point once, no post-filter), and descending order is required for soundness
specifically.

**`harvest_feed_frontier` benefits for free** — it wraps `food_payment_frontier` over
`paid ∈ [0, food_owed]`. No change to the wrapper; it just gets faster underneath.

**Est.** ~10–50× on the helper for typical inputs; more in late game. Pure function,
frontier-*set*-preserving (Appendix A); see §8 on preserving output *order*.

### 5.2 `pareto_frontier` / `breeding_frontier` — max-corner + anchor pruning

Two stacked prunings over the brute enumeration:

**(a) Max-corner fast path.** The componentwise-maximal config — keep everything
(`(s_avail,b_avail,c_avail)`) for pareto, breed every eligible type
(`(s_desired,b_desired,c_desired)`) for breeding — dominates all others when feasible (invariant
3). So:

```python
maxc = (s_avail, b_avail, c_avail)               # or the breeding desired-bounds
if can_accommodate(pasture_capacities, num_flexible, *maxc):
    return [(Animals(*maxc), food(maxc))]        # singleton frontier
```

One `can_accommodate` call handles the common roomy-farm case. Food for the singleton is 0 for
pareto (nothing released) / 0 for breeding (nothing eaten).

**(b) Anchor pruning (S1).** When the max corner is infeasible, enumerate but skip the prism
dominated by the pre-action anchor: the pre-gain animals for pareto, the "no-eat-no-breed"
current animals for breeding. Any candidate `≤` the anchor on every axis (strict on one) is
dominated and skippable at emit time. (S2 geometric pruning — every confirmed-feasible point
carves its own dominated prism, swept high-corner-first — is a further extension; defer unless
profiling still flags `can_accommodate`.)

See `SPEEDUPS.md` S1/S2 for the original framing. At Level ≥ 3 the Φ build (§6.2)
supersedes (b) entirely — Φ generates only maximal corners by construction — so anchor pruning
would matter only at Level 1–2.

> **Shipped:** (a) max-corner only. **Anchor pruning (b) was *not* implemented** — the max-corner
> short-circuit captured the win and the brute fallback keeps correctness, so Level 1–2 use
> max-corner + brute enumeration. (b)/S2 remain a future speed-only refinement, unlikely to be
> worth it since these helpers are cold in MCTS (§10). See §9.

Both (a) and (b) are **capacity-specific** — they exploit "maximize animals subject to a capacity
bound." Feeding inverts that (minimize goods spent subject to a food *floor*) and adds a begging
dimension, so neither transfers. See §6.5 for feeding's level-by-level specialization.

---

## 6. Levels 2 & 3 — Caching

§6.1–6.4 cover the **animal frontiers** (`pareto_frontier` / `breeding_frontier`). Feeding's
Level 2 and Level 3 specialize differently (clipped key, no Φ) and live entirely in §6.5.

### 6.1 Level 2 — exact projection cache (farm + caps → frontier)

Cache the **rates-free frontier points** keyed on the full projection *minus rates*; annotate
food on retrieval.

```python
@lru_cache(maxsize=...)
def _pareto_points(pasture_caps, num_flexible, s_avail, b_avail, c_avail):
    # returns tuple[Animals, ...] — the rates-free frontier (Level-1 logic inside)
    ...

def pareto_frontier(p, gained, rates):
    proj = _project(p, gained)                   # canonicalize: sort pasture_caps
    if PARETO_OPT_LEVEL >= 2:
        pts = _pareto_points(*proj)
    else:
        pts = _pareto_points_l1gen(*proj)        # same generator §6.4 names; uncached here
    return [(pt, _pareto_food(pt, proj, rates)) for pt in pts]
```

Key points:

- **Canonicalize `pasture_capacities`** (sort it) so permutations of the same multiset collide.
- **Drop `rates`** from the key (invariant 1); the per-retrieval food annotation is ~3 mults per
  point. Honest note: the hit-rate gain from dropping `rates` is marginal (a player rarely owns
  different cooking improvements across nodes in one search) — do it for cleanliness and because
  it's the natural form for Level 3, not for a big win.
- **Placement — enumerator level vs helper level.** For animal markets and breeding,
  `legal_actions(state)` at that pending *is* the frontier (one `CommitX` per point), so caching
  the **enumerator's output list** (`_enumerate_pending_animal_market`,
  `_enumerate_pending_harvest_breed`) would also amortize the `CommitX` wrapper construction;
  caching the bare helper is the simpler fallback. **Shipped: the helper-level form** —
  `_animal_points_cached` in `helpers.py` wraps the rates-free frontier generation. The
  enumerator-level amortization was not pursued: the helper cache already removes the frontier
  cost, the `CommitX` build is cheap, and the profile later showed these helpers are cold in MCTS
  anyway (§10), so it wasn't worth touching `legality.py`.
- `breeding_frontier`'s key uses `(pasture_caps, num_flexible, s, b, c)` (current animals; the
  desired bounds derive from them) and annotates food via `breeding_food_gained`.

### 6.2 Level 3 — Φ farm-shape cache

Φ(farm) = the Pareto-max of the feasible animal set, depending **only** on
`(pasture_capacities, num_flexible)` — not on animal caps, not on rates. One Φ cache serves
**both** `pareto_frontier` and `breeding_frontier` (same `can_accommodate`, same farm key).

**Per-call path (given Φ):**

```python
def frontier_from_phi(phi, caps):
    # max-corner: does any Phi point dominate caps? -> singleton
    if any(P[0] >= caps[0] and P[1] >= caps[1] and P[2] >= caps[2] for P in phi):
        return [caps]
    clipped = {(min(P[0],caps[0]), min(P[1],caps[1]), min(P[2],caps[2])) for P in phi}
    return pareto_max(clipped)                   # cheap: |phi| is tiny
```

`caps` = `(s_avail,b_avail,c_avail)` for pareto, the desired-bounds for breeding. Food annotated
afterward (per-helper formula). The max-corner check from §5.2 becomes a pure Φ-dominance test —
no `can_accommodate` call at all.

**Φ-miss build — grouped structured enumeration.** Group every accommodation *unit* by capacity:
flexible slots are capacity-1; pastures contribute their capacities (2, 4, 8, …). For each
capacity group of multiplicity `m`, enumerate how its identical units split across the 3 types
(`a+b+c = m`, all units used — leaving one idle is dominated). The corner is the summed dedicated
vector; Φ is the Pareto-max over the product of group splits.

```python
def build_phi(pasture_capacities, num_flexible):
    groups = Counter(pasture_capacities)
    groups[1] += num_flexible                    # flexible units are capacity-1
    # per group: all (a,b,c) with a+b+c = m  ->  C(m+2,2) splits
    corners = {(0,0,0)}
    for cap, m in groups.items():
        new = set()
        for (cs,cb,cc) in corners:
            for (a,b,c) in compositions_3(m):    # a+b+c = m
                new.add((cs+a*cap, cb+b*cap, cc+c*cap))
        corners = new                            # dedup as we go (set)
    return pareto_max(corners)
```

- **Empty/idle units are dropped** (always dominated → not in Φ), so it's `3`-way splits, not
  4-way, and `a+b+c = m` exactly.
- **Count** = ∏ over capacity groups of `C(m_v+2, 2)`, deduped via the running set. Concrete
  worst realistic case (5 cap-2 pastures + 5 flexible): `C(7,2)·C(7,2) = 441` candidates vs the
  naive `3⁵·C(7,2) = 5103` — grouping by capacity is the key reduction (Agricola caps pastures at
  5, and many share a capacity). Sub-millisecond, paid once per farm shape.
- **Fallback — and what shipped.** The **naive box sweep** (`_build_phi`: a triangular
  `s+b+c ≤ max-single-type-capacity` sweep filtered by `can_accommodate`, then `pareto_max`) **is
  what shipped** — the same feasibility oracle as the baseline, so guaranteed correct, one-time per
  farm shape. The structured grouped build sketched above is the deferred speed refinement; adopt
  it only if Φ-misses show in a profile (§9).

### 6.3 Φ correctness lemma

> **Claim.** For any caps, `query_frontier = pareto_max{ clip(P, caps) : P ∈ Φ }`.
>
> **Proof.** `can_accommodate` is downward-closed (invariant 2). For any query-feasible `x`
> (feasible and `≤ caps`), Φ contains some `P ≥ x` (Φ is the max-frontier of the feasible set).
> Then `x ≤ clip(P, caps)`, and `clip(P, caps)` is feasible (`≤ P`, downward-closure) and
> `≤ caps`, hence query-feasible. So every query-feasible point is dominated by some clipped Φ
> point ⇒ the clipped Φ generates exactly the query frontier. ∎

Note clipping does **not** preserve the antichain property (clipped Φ can contain dominations),
so the per-call `pareto_max` over the clipped set is mandatory — but it's a cheap dominance sweep
over `|Φ| ≲ 20` points with no `can_accommodate` calls. Dedup the clipped set first; the
max-corner short-circuit skips it entirely in the common case.

### 6.4 L2 vs L3 — a hierarchy, not alternatives

L3's hit set is a superset of L2's (farm-only key vs farm+caps), but on the hits they share, L2
returns a stored list (~200 ns) while L3 does clip + re-Pareto (~1–3 µs). They compose as a cache
hierarchy: at Level 3, check L2 exact first; on miss, get Φ (L3), run `frontier_from_phi`, store
the result back into L2.

```python
if PARETO_OPT_LEVEL >= 2 and proj in L2: return annotate(L2[proj])
if PARETO_OPT_LEVEL >= 3:
    phi = _phi_cached(pasture_caps, num_flexible)     # L3
    pts = frontier_from_phi(phi, caps)
else:
    pts = _pareto_points_l1gen(...)                   # L1 algorithmic gen (no Φ)
if PARETO_OPT_LEVEL >= 2: L2[proj] = pts
return annotate(pts)
```

The same-object exact repeat (the most common MCTS case) is already served upstream by
`legal_actions_cache` before either layer is consulted, so L2/L3 only handle the different-object
hits. Under the cumulative knob, **level 3 always includes the L2 exact cache** — it is the fast
path for exact (farm+caps) repeats, with Φ as the miss-path generator; there is no "Φ without the
exact memo" setting. The open question is therefore not whether to keep L2, but whether Φ's coarser
farm-only hits outweigh its clip + re-Pareto cost versus simply regenerating via the L1 path on an
exact-cache miss — i.e. whether level 3 earns its keep over level 2 (§10).

### 6.5 Feeding — how Levels 1–3 specialize (the structural exception)

`harvest_feed_frontier` / `food_payment_frontier` differ from the animal frontiers in three ways
that change what each level can do. Spelling them out, because the differences are easy to get
wrong:

1. **No farm capacity → no Φ. Φ's *spirit* (a coarser key) transfers, but trivially.** Feeding
   converts goods → food; there is no `can_accommodate`, no pastures, no Φ. The coarsening idea
   does transfer — **goods beyond `⌈food_owed / rate⌉` can never be consumed** (the existing
   per-good caps already encode this), so excess goods are irrelevant and can be clipped out of the
   key — but unlike Φ this is *free*: an inline `min` plus a uniform `⊕ excess` translation with no
   build step and no re-Pareto. So the clip is simply **folded into the Level-2 key** (it strictly
   dominates an exact key), *not* deferred to a separate level. The only feeding item left for
   Level 3 is a genuinely separate second cache (the inner `food_payment` cache, §"Level 3" below).

2. **Begging is a genuine Pareto dimension** (`−begging`, fewer-is-better). Under-paying configs
   (pay some, beg the rest) are *legitimate frontier points*. Three knock-on effects:
   - **No max-corner singleton.** The animal frontiers collapse to one point when "keep
     everything" is feasible. Feeding has no such config — you must *spend* to reduce begging,
     and the minimal-spend corners trade off across goods. §5.2(a) has no feeding analog.
   - **No anchor pruning.** The "pay nothing, beg everything" config is the *worst* on the
     `−begging` axis, so it dominates nothing (SPEEDUPS.md S1 table marks
     `harvest_feed_frontier` ✗). §5.2(b) has no feeding analog either.
   - **"Emit-only-frontier" holds only for full payment.** The rate-descending enumeration
     (§5.1) emits the exact frontier for `food_payment_frontier` (which *must* fully pay
     `food_owed`). `harvest_feed_frontier` keeps its paid-level wrapper precisely because begging
     scatters frontier points across payment levels — there is no single rate-descending pass
     that yields them all without a post-filter.

3. **Rates stay in the cache key.** For the animal frontiers the frontier is rate-independent
   (rates only annotate food), so rates drop from the key. For feeding the opposite holds: rates
   set how much you must consume to cover `food_owed`, so they change *which* remaining-goods
   configs are Pareto-optimal. Rates are part of the projection.

**Level 1 (feeding).** Rate-descending rewrite of `food_payment_frontier` (§5.1);
`harvest_feed_frontier` benefits transitively through its wrapper. No max-corner, no anchor.

**Level 2 (feeding) — clipped outer cache.** Cache `harvest_feed_frontier`, keyed on the
**clipped** supplies `(cap_grain, cap_veg, cap_sheep, cap_boar, cap_cattle, food_owed, rates)`,
where `cap_g = min(supply_g, ⌈food_owed / rate_g⌉)` (grain: `min(grain, food_owed)`). No good is
ever consumed beyond `cap_g` (converting more is strictly dominated), and these caps are *already
computed* inside `food_payment_frontier`. `food_owed` and `rates` are in the key; begging is in the
output. The clip is folded in here, not given its own level, because it is free (point 1).

- **Why clip in the key.** It collapses every variant differing only in strategically-dead excess
  onto one entry — e.g. 5 sheep vs 4, both owing `F ≤ 8` at `sR = 2` (`⌈8/2⌉ = 4`), share an
  entry; the 5th sheep is never useful. Big hit-rate gain for goods-/animal-hoarding states; a
  free no-op for lean states.
- **Reconstruct** by adding `excess_g = supply_g − cap_g` back to each frontier point's
  `g`-coordinate (begging unchanged): `actual_frontier = clipped_frontier ⊕ excess`.

**Reconstruction needs no re-Pareto — it's a uniform translation.** Clean contrast with the pareto
Φ path (§6.3), where clipping is a componentwise `min` (a projection) that can create dominations
and *requires* a re-Pareto sweep. Here every frontier point satisfies `remaining_g ≥ excess_g`
(consumption never exceeds `cap_g`), so the true frontier is the clipped frontier shifted by the
*same constant vector* `excess` on every point — dominance-preserving, no filtering. This is why
clipping is trivial enough to live at Level 2.

> **Lemma.** `actual_frontier = { p ⊕ excess : p ∈ clipped_frontier }`.
> **Proof.** On the frontier, `consumed_g ≤ cap_g` for every good (consuming more produces surplus
> food from one good that one-less-unit already covered — dominated). So consuming the same amounts
> as the clipped problem gives `actual_remaining_g = (supply_g − consumed_g) = excess_g +
> (cap_g − consumed_g) = excess_g + clipped_remaining_g`, and no frontier point is lost because the
> player never wants to touch the excess. Begging depends only on `consumed`/`produced`, both
> unchanged. ∎

**Cache the outer wrapper, not the inner `food_payment` calls (at L2).** The wrapper does three
things per call: the `food_owed + 1` `food_payment_frontier(ps, paid, rates)` calls, the
natural-fit filter, and the final 6-dim Pareto aggregation (5 goods + `−begging`). Caching the
outer returns the whole frontier wholesale, skipping all three — `food_payment` is never reached.
Caching only `food_payment` would still re-run the natural-fit + O(n²) aggregation every call. The
inner `food_payment` cache helps *only* on a feed **miss** (cross-`food_owed` reuse) and is
deferred to Level 3. The Level-1 rate-descending rewrite of `food_payment` still pays off here — it
speeds the feed **miss** path, which re-runs the wrapper.

**Helper-level** (both feeding and the animal frontiers shipped at the helper level — §6.1). The
*structural* reason feeding couldn't even be enumerator-level if we wanted: unlike the animal
markets (whose enumerator output *is* purely the frontier), the feed enumerator additionally offers
the cheap craft-conversion decisions
(joinery/pottery/basketmaker fire-actions, gated on `harvest_conversions_used` +
affordability). Those are trivial to re-enumerate; folding them in would only widen the key with
conversion-availability for no real saving. So cache the expensive helper and leave the cheap
craft enumeration uncached. (`food_owed` derives deterministically from the player's
`people_total` / `newborns` and held food at feed time, so it is a stable part of the projection.)

**Level 3 (feeding) — add the clipped inner `food_payment` cache.** The one feeding item that is a
genuinely separate caching layer (more memory, a second lookup), not just a coarser key. It catches
the cross-`food_owed` reuse deferred from L2: keyed `(clipped-by-paid supplies, paid, rates)` where
the clip uses `paid` (not `food_owed`), so `food_payment(ps, k, rates)` is shared across every outer
call with `food_owed ≥ k` *and* across all excess-goods variants. Same `⊕ excess` reconstruction,
same no-re-Pareto translation, same `consumed_g ≤ cap_g` correctness invariant as the outer clip.
This is feeding's analog of the animal L2/L3 hierarchy (§6.4): the clipped outer cache (L2) is the
fast layer; the clipped inner cache (L3) is the higher-hit layer that pays off on outer misses.
Marginal — profile-gated.

---

## 7. Fencing-scan cache (independent track — `FENCE_SCAN_CACHE`)

Same projection-cache technique applied to the fence-universe scan. Fully specified as **S7 in
`SPEEDUPS.md`** — summarized here for completeness:

- Cache `_legal_pasture_commits(farmyard, wood, subdivision_started)` → tuple of
  `(entry, h_new_bm, v_new_bm)`. `_any_legal_pasture_commit` becomes a length check; the
  enumerator builds `CommitBuildPasture`s from the cached triples.
- Invalidators (key changes): plow, build-rooms, build-fences, any wood change. Notably **stable
  builds don't invalidate** (STABLE cells stay enclosable; `pasture_bms` reads `.cells`, not
  `.num_stables`).
- Active-universe caveat: `cache_clear()` on `active_universe(...)` entry/exit.

Gated by `FENCE_SCAN_CACHE` rather than the pareto level because it's a different subsystem with
no Level-1/3 analog.

---

## 8. Testing & benchmarking

### 8.1 Correctness

The toggle structure *is* the test oracle. **Level 0 is today's code, untouched** (so the default
— and every current script that doesn't set the flag — is unchanged). The optimized levels (1–3)
must be **set-identical to Level 0** (same frontier set + food/begging values) and **behavior-
identical to one another**.

- **Cross-level equivalence (the key test).** Parametrize over `PARETO_OPT_LEVEL ∈ {0,1,2,3}` and
  `FENCE_SCAN_CACHE ∈ {False, True}`; for a corpus of states (existing factory states + random
  playouts): assert levels **1–3 are identical to each other as ordered lists** (they all
  canonically sort — see the next bullet), and that each is **set-identical** to Level 0 with the
  same food/begging values. Level 0 keeps its legacy emission order, so it is compared as a set,
  not a list. This catches any correctness divergence from the baseline and any inconsistency among
  the optimized levels.
- **Order preservation (subtle but load-bearing).** The proofs guarantee set-identical frontiers,
  but downstream consumers are order-sensitive: argmax/softmax tie-breaking takes the *first*
  equal-value action in list order, and `strict_restricted_legal_actions`' harvest-feed cap samples
  "2 random" by position. So a reordered-but-equal frontier can still change trajectories and
  determinism — meaning *set*-identical does not imply *behavior*-identical. Mandate a **canonical
  sort** of the frontier output on the optimized levels (cheap — the frontier is tiny) so they are
  mutually list-identical (set-identical ⟹ list-identical ⟹ behavior-identical *among levels 1–3*).
  Any fixed total order works (frontier points are pairwise distinct — an antichain — so there are
  no in-sort ties); use a plain **lexicographic sort** on the point's tuple, with an explicit key
  (`Animals` is frozen but not `order=True`):
    - animal frontiers (`pareto_frontier` / `breeding_frontier`): key `(sheep, boar, cattle)`;
    - feeding (`food_payment_frontier`): key on the remaining 5-tuple
      `(grain, veg, sheep, boar, cattle)`;
    - `harvest_feed_frontier`: key `((grain, veg, sheep, boar, cattle), begging)`.
  **Do *not* sort at Level 0** — leave it byte-for-byte today's code so the default never moves.
  The sort lives only on the opt-in levels. Consequence: *enabling* the optimization (0 → 1+) is an
  opt-in change that may shift a few tie-breaks versus the legacy order — benign (tied configs are
  equal-value), the price of a clean reorder-free optimized path; the default itself is unchanged.
- **Cache-clear hygiene.** `lru_cache` persists across tests in-process. Add an autouse `conftest`
  fixture that calls `.cache_clear()` on every cache (and resets the flags to defaults) between
  tests. Pure functions of frozen inputs shouldn't pollute, but the fixture is a cheap safety net
  and prevents flaky cross-test coupling when a test flips the level.
- **Φ unit tests.** `build_phi` against hand-computed Φ for small farms (0 pastures + k flexible;
  one cap-2 pasture; mixed capacities); assert the clip lemma on random caps by brute-force
  comparison to a direct `can_accommodate` frontier.
- **`food_payment` equivalence.** The rate-descending rewrite must match the current
  implementation's frontier set on a sweep of `(supplies, food_owed, rates)`; a numerical
  cross-check on the Appendix A proof, exhaustive over a small grid.
- **Existing suites** (`test_harvest_*`, `test_animal_markets`, `test_fencing`, etc.) run at the
  default level (0) and must stay green; the parametrized test covers the rest.

### 8.2 Benchmarking — measuring the speedup

Correctness (8.1) is a pytest pass/fail; **speedup is a benchmark** — timing is machine/noise-
dependent, so it lives in a re-runnable script + recorded numbers (the `profile_engine.py` /
`PROFILING.md` convention), not in CI.

**Why the toggle makes it measurable — with one catch.** Run the *same* workload at different
`PARETO_OPT_LEVEL`s and attribute the wall-clock delta to the optimization. Clean comparison:
**levels 1/2/3 explore the identical MCTS tree** (mutually behavior-identical → identical
helper-call counts), so the delta among them is *pure per-call speedup*. Confounded comparison:
**level 0 vs ≥1** can explore slightly different trees (the canonical sort shifts tie-breaks), so a
raw 0→1 timing mixes the algorithmic gain with a small, equal-value tree-shape change. Attribution
therefore comes from several angles, each clean for what it measures.

The four measurements (the first two are runnable **today**, before any optimization lands, via
`scripts/profile_frontier_helpers.py`):

1. **Helper microbench — per-call cost, tree-independent** (`--mode microbench`). `timeit` each
   helper over the 9 prefab states; the Level-0 run is the baseline, and re-running at each
   `--level` after the optimization lands reads the algorithmic (Level-1) and warm-cache gains
   directly. *Baseline already measured:* `harvest_feed_frontier` dominates (~1.6 ms mean, ~16 ms
   worst case) — far above `food_payment` (~0.5 ms), `breeding`/`pareto` (~60–80 µs) — so the feed
   path is the highest-value algorithmic target.
2. **Projection-collision — predicted cache hit rate** (`--mode collision`). Wraps the helpers to
   record their projection key over one MCTS game and reports `1 − distinct/total` = the hit rate a
   perfect projection cache would achieve, **without building the cache**. This is the Phase-2/3
   gate (§10). *Smoke run (60 sims, one game) already shows:* harvest_feed **99%** with the clipped
   key (vs 96% exact — the clipping buys it), fence scan **94%**, breeding **83%**, food_payment
   **74%**, pareto **68%** — all well above the floor, and higher at realistic sim counts.
3. **End-to-end MCTS wall-clock A/B.** Use `scripts/play_mcts_match.py` (fixed `--seeds` + `--sims`,
   `--jobs 1`, `python -O`, median of N runs). Clean number among levels 1/2/3; headline "vs today"
   from level 0 vs 3 over many seeds so tie-break tree differences average out.
4. **cProfile + tree-identity check.** cProfile the MCTS workload at level 0 vs 3 — confirm the
   targeted helpers' self-time dropped *and* no new hotspot (the sort or the cache lookup) ate the
   gain. Separately, run `scripts/measure_mcts_tree.py` at levels 1/2/3 on one seed and diff the
   logs (transposition-table size + chosen action per call): identical logs prove the trees match,
   which both validates correctness and certifies the 1-vs-2-vs-3 timing comparison.

**Rigor:** fixed seeds + sim budget, single-thread, `python -O`, report median + spread over N
runs. Record results (and add an MCTS workload) in `PROFILING.md`, which today is random-play only.

**Decision gates:** after Phase 1, the microbench says whether the rewrite earns its place; after
Phase 2, the hit-rate measurement says whether Level 3 is worth building — if it's low, stop.

---

## 9. Implementation phasing — **all landed**

Each phase shipped independently, default-off, behind `opt_config` (the defaults were later flipped to
**on** once proven). What actually landed:

1. **Phase 0 — done.** `breeding_food_gained` extraction (CLEANUP.md Cleanup 4).
2. **Phase 1 — done.** Level-1 algorithmic behind `PARETO_OPT_LEVEL >= 1`: `food_payment`
   rate-descending (Appendix A) + max-corner fast path for pareto/breeding + the canonical sort.
   Implemented in `agricola/helpers.py` Part 5 (level 0 = baseline, untouched, via an early-return
   guard). *Anchor pruning (S1) was not implemented* — max-corner captures the dominant win and the
   brute fallback keeps correctness; anchor remains a future speed-only refinement.
3. **Phase 2+3 — done together.** Level-2 exact `lru_cache` for the animal frontiers + clipped outer
   `harvest_feed` cache (`⊕ excess` reconstruction); Level-3 Φ shared by pareto/breeding (naive
   `can_accommodate` build, the structured §6.2 build deferred). The cross-level equivalence test +
   conftest cache-clear landed with Phase 1.
4. **Fencing track — done.** S7 behind `FENCE_SCAN_CACHE` (`agricola/legality.py`), with
   `active_universe(...)` clearing the cache on swap. Independent of the pareto level.

**Deferred (profile-gated, not justified):** the feeding inner `food_payment` cache (§6.5 — the
measured 95% outer hit rate doesn't justify a second layer) and the structured Φ build (§6.2 — a
speed refinement; the naive build already amortizes per farm shape).

---

## 10. Open questions & uncertainties

- **Hit rates: measured, good.** `--mode collision` projection prediction (60-sim smoke): 68–99%.
  Confirmed live via `cache_info()` in an 80-sim MCTS game: animal exact 75%, Φ 89% (only 5 distinct
  farm shapes built), harvest_feed clipped 95%. End-to-end MCTS wall-clock came in at ~8–9% (150
  sims, level 3 + fence cache vs baseline) — within the predicted 5–20%, modest because the helpers
  are only a fraction of total MCTS time (leaf eval / UCB / hashing dominate the rest). Worth a
  cProfile pass to see if a different subsystem is now the ceiling. Random play benefits ~nothing.
- **Φ keyspace / hit rate.** How many distinct `(pasture_capacities, num_flexible)` shapes recur
  in a search is the gating unknown for Level 3. Within-rollout animal progression on a stable
  farm argues for high hits, but it's unverified. Memory isn't a concern (Φ is tiny).
- **Does Φ (level 3) earn its keep over level 2?** The exact cache is shared by both levels
  (cumulative — §6.4), so the question is purely whether Φ's coarse farm-only hits outweigh its
  clip + re-Pareto cost versus regenerating via the L1 path on an exact-cache miss. Empirical;
  profile the level-2 hit/miss split first (§9).
- **Worst-case Φ build** (many pastures) is bounded by the grouped count but unrealistic in
  Agricola (≤ 5 pastures); if ever a concern, dedup + a sort-based 3-D skyline replace the naive
  `pareto_max`.

---

## 11. File-touch summary

| File | Change |
|---|---|
| `agricola/opt_config.py` (new) | `PARETO_OPT_LEVEL`, `FENCE_SCAN_CACHE` |
| `agricola/helpers.py` | **(landed, Part 5)** level branches in `pareto_frontier` / `breeding_frontier` / `food_payment_frontier`; `_animal_points_cached` (exact, L2) + `_build_phi` / `_frontier_from_phi` (naive Φ, L3); rate-descending `_food_payment_points`; clipped `_harvest_feed_cached` (`⊕ excess`). Inner `food_payment` cache deferred (§6.5). |
| `agricola/legality.py` | **(landed)** `_legal_pasture_commits_compute` / `_legal_pasture_commits_cached` — the fencing track only. (The animal/breed caches live in `helpers.py`, not the enumerators — see §6.1.) |
| `tests/conftest.py` | autouse cache-clear + flag-reset fixture |
| `tests/test_frontier_opt.py` (new) | cross-level equivalence + Φ unit tests + `food_payment` equivalence |
| `scripts/profile_frontier_helpers.py` (**done**) | microbench + projection-collision profiler (§8.2); runnable today for the baseline + Phase-2/3 gate |
| `PROFILING.md` | add an MCTS workload + record the §8.2 benchmark numbers |
| `SPEEDUPS.md` | cross-reference this doc from S1/S2/S7 |
| `CLAUDE.md` doc index | add this doc (optional, on landing) |

---

## Appendix A — Proof: rate-descending enumeration emits exactly the frontier

Proves the §5.1 claim: the rate-descending nested enumeration of `food_payment_frontier` emits
**exactly** the Pareto frontier — every emitted point is on it (sound), every frontier point is
emitted (complete), each exactly once — so no post-Pareto filter is needed. It also pins down why
descending order is required (and that *only* soundness needs it).

**Setup.** Goods `1..n` sorted by rate descending, `r_1 ≥ r_2 ≥ … ≥ r_n ≥ 1` (rate-0 goods
excluded; grain is rate 1), supplies `s_i ≥ 0`, target `F = food_owed`. A consumption vector `x`
with `0 ≤ x ≤ s` is *feasible* iff `Σ_i r_i·x_i ≥ F`. Because remaining `= s − x` is an
order-reversing bijection, Pareto-max remaining ⟺ Pareto-min consumption, so the target frontier is

> `𝓕 = { x : 0 ≤ x ≤ s, Σ_i r_i·x_i ≥ F, x Pareto-minimal among feasible vectors }`.

The algorithm chooses `x_k ∈ {0,…,U_k}` in order, with residual `R_{k-1} = F − Σ_{i<k} r_i·x_i` and
cap `U_k = min(s_k, ⌈max(0, R_{k-1}) / r_k⌉)`, recording a leaf iff `R_n ≤ 0`. Call the recorded
set `𝓡`, and write the surplus `σ := Σ_j r_j·x_j − F`.

**Lemma (minimality).** Feasibility is upward-closed in `x` (consuming more never loses
`≥ F`). For an upward-closed set, `x` is Pareto-minimal iff no single unit can be dropped feasibly:
for every used good `i` (`x_i ≥ 1`), `x − e_i` is infeasible, i.e. `σ < r_i`. Equivalently
`σ < r_ℓ`, where `ℓ = max{ i : x_i ≥ 1 }` is the last — hence, by the sort, lowest-rate — used good.
*(This second equivalence is the first use of the descending sort: `r_ℓ = min{ r_i : x_i ≥ 1 }`.)*

**Soundness (`𝓡 ⊆ 𝓕`).** Take a recorded `x` (so `σ ≥ 0`); let `ℓ` be its last used good. Goods
after `ℓ` are 0, so `σ = −R_ℓ`. Reachability gave `x_ℓ ≤ ⌈max(0, R_{ℓ-1})/r_ℓ⌉`, and `x_ℓ ≥ 1`
forces that ceiling `≥ 1`, hence `R_{ℓ-1} > 0`. With `m* = ⌈R_{ℓ-1}/r_ℓ⌉ < R_{ℓ-1}/r_ℓ + 1`:

> `σ = r_ℓ·x_ℓ − R_{ℓ-1} ≤ r_ℓ·m* − R_{ℓ-1} < (R_{ℓ-1} + r_ℓ) − R_{ℓ-1} = r_ℓ`.

So `0 ≤ σ < r_ℓ`; by the Lemma `x` is minimal. ∎

**Completeness (`𝓕 ⊆ 𝓡`).** Take `x ∈ 𝓕`; it passes the feasibility check. For reachability at good
`k` (reached via `x`'s own prefix, so the residual is exactly `R_{k-1}`): if `x_k = 0`, trivial. If
`x_k ≥ 1`, minimality makes `x − e_k` infeasible, i.e. `σ < r_k`. Since
`σ = (r_k·x_k − R_{k-1}) + Σ_{i>k} r_i·x_i ≥ r_k·x_k − R_{k-1}`, we get `r_k·(x_k − 1) < R_{k-1}`.
That forces `R_{k-1} > 0` and `x_k − 1 < R_{k-1}/r_k`, so the integer `x_k ≤ ⌈R_{k-1}/r_k⌉ = U_k`.
Every cap admits `x`, so it is recorded. ∎

Distinct leaves differ in some coordinate and the recursion fixes each coordinate once, so there
are no duplicates: `𝓡 = 𝓕`, each point emitted exactly once.

**Why descending order — and why only soundness needs it.** Completeness used no ordering
assumption: the caps never exclude a minimal point in any order. Only soundness used it, at one
step — it bounds the final surplus by the *last* used good's rate (`σ < r_ℓ`), which certifies
minimality only because `r_ℓ` is the *minimum* used rate (descending order). Under any other order,
a lower-rate good used earlier may still have `σ ≥ r_j`, so `x − e_j` stays feasible and a
dominated point is emitted. This is exactly the §5.1 counterexample: ascending `(r_1, r_2) = (1, 3)`,
`F = 4`, branch `x = (2, 1)` has `σ = 1`; the last used good is good 2 (`r = 3`), so its cap permits
`x_2 = 1`, but the min used rate is 1 and `1 ≮ 1` — dropping a unit of good 1 gives feasible
`(1, 1)`, so `(2, 1)` is dominated. Hence **ascending is complete but unsound (needs a post-Pareto
filter); descending is sound (no filter).**

**Edge cases.** Rate-0 goods, if consumed, add no food but spend a unit ⇒ dominated ⇒ `x_i = 0` in
every minimal point, so excluding them from the enumeration and leaving them at full remaining is
exact. Ties `r_i = r_{i+1}` are fine — the Lemma only needs `r_ℓ ≤ r_j` for used `j`. Infeasible
instances (`Σ_i r_i·s_i < F`) record nothing (`𝓡 = ∅ = 𝓕`). `F ≤ 0` (short-circuited in code anyway)
enumerates only `x = 0`, the unique minimal point.

**Takeaway.** The frontier is characterized by a one-line invariant — *a feasible point is minimal
iff its food surplus is strictly less than the lowest rate it spends* (`σ < r_ℓ`) — and the cap
`⌈R_{k-1}/r_k⌉` is exactly the device that enforces this at the last used good while never excluding
a true minimal point.
