# Card rule-audit v2 — final triage (recovered + in-thread verified, 2026-07-01)

Source: workflow wf_c3da82f6-451 (152 audited, 134 ok, 15 flagged, 3 un-audited).
Verify phase cut off by weekly usage limit after 5 confirms; the remaining 10 were
verified in-thread (main loop) from card text + code — NO workflow rerun.

## GROUP 1 — confirmed bugs, clean fix
| Card | Class | Fix | Confirmed by |
|---|---|---|---|
| beer_stein | T1 | after_bake_bread -> before_bake_bread + grain stranding guard (>=2 grain +baker) | workflow |
| baking_sheet | T1 | same as beer_stein | workflow |
| dutch_windmill | T1 | after_bake_bread -> before_bake_bread (adds food only, no stranding) | in-thread |
| bucksaw | T1 | after_renovate -> before_renovate (pays 1 wood; renovate needs no wood, no strand) | in-thread |
| mining_hammer | T1 | after_renovate -> before_renovate (free-stable grant; no strand) | in-thread |
| rocky_terrain | T1 | after_plow -> before_plow (buy stone for food; no strand) | in-thread |
| loppers | T1+T2 | after_build_fences -> before_build_fences + fence-in-supply stranding guard | in-thread |
| drill_harrow | T2 | before_sow guard: reserve >=1 seed so liquidating for the 3 food can't strand the sow | workflow |
| tasting | scope | before_play_occupation over-fires on ALL occ plays; scope to Lessons-initiated only | in-thread |
| mini_pasture | O1 | register passing_left=True (it's a traveling minor, currently kept) | workflow |

## GROUP 2 — confirmed bugs, fix needs a shared decision / infra
| Card | Class | Issue | Needs |
|---|---|---|---|
| chophouse | C1 | cost "2 Wood/2 Clay" encoded as pay-both | alternative-cost (wide) infra, OR defer+archive |
| club_house | C1 | cost "3 Wood/2 Clay" encoded as pay-both (found earlier) | same |
| luxurious_hostel | SC1 | stone-house bonus double-counts with half_timbered_house | a stone-house-bonus mutual-exclusion mechanism |
| roughcaster | detection | over-grants +3 food on a Conservator wood->stone renovate (reads house==STONE, not "from clay") | renovate from-material tracking (same family as hammer_crusher deferral) |

## GROUP 3 — needs a ruling / fresh analysis
| Card | Issue |
|---|---|
| corn_schnapps_distillery | "Once per round" (anytime) modeled as start_of_round-only. Real divergence, but "anytime paid conversion" is exactly what the engine deliberately does NOT surface (guide §2). Accept approximation / defer / build infra — your call. |
| teachers_desk | Audit output was corrupt ("test"); UNVERIFIED. before_action_space matches the ruling; needs a proper fresh check for stranding of the host's mandatory build/renovate by the 1-food occ play. |

## UN-AUDITED (StructuredOutput cap — no verdict at all)
scholar, pavior, resource_analyzer

## Note
The 134 "ok" verdicts are single-pass (their adversarial verify never ran — the verify phase
only covers flagged cards). Treat "ok" as "no bug found by one auditor," not "proven clean."
