# Multi-session roadmap — tackling all priorities across sessions

**Status:** IN PROGRESS. Sessions 1-5 complete. Session 6 = next active.
**Supersedes:** sequencing in `05-REVISED-PLAN.md` (which assumed single-week execution). The findings stay valid; this just paces them.

## Session log (actuals)

| Session | Date | What shipped | What's measuring | Next-session entry |
|---|---|---|---|---|
| 1 | 2026-05-12 | A3 weather scheduler + 2nd pre-game export; X2 confirms A1 vapor | `mlb_raw.mlb_weather` (blocked — no OWM API key) | Session 2 |
| 2 | 2026-05-13 (AM) | A2 narrowed (`MLB_MAX_EDGE=1.5→1.25`), algorithm_version `mlb_v9_max_edge_125`; A5 + B1 designs | A2 7-day monitor (DUE 2026-05-20) | Session 3 |
| 3 | 2026-05-13 (mid) | A5 CLV foundation (schema + scheduler), A4 walk-forward dev (`--loss-function` flag, training data Apr 2024-Sep 2025) | A4 WF (RMSE/Poisson) compute (background) | Session 4 |
| 4 | 2026-05-13 (PM) | A4 Quantile(0.5) WF; A4 decision doc — **RMSE wins decisively, A4 deploy skipped**; B1 backtest + recalibrated thresholds + CF/scheduler code written | none (A4 closed) | Session 5 |
| 5 | 2026-05-13 (eve) | **B1 monitor CF deployed** + scheduler created + test-fired; first state row = MLB/UNDER DEGRADING (HR 30.4%, N=46); B1 backtest temp table dropped | B1 daily state transitions; A2 7-day monitor still due 2026-05-20 | Session 6 |

**Original Session 5 ("A4 deploy") is SKIPPED** — see Session 4's `10-A4-DECISION.md`. RMSE production baseline holds. B1 deploy was pulled forward from original Session 4 (which couldn't deploy without the user-decision branch on webhook env).

**Philosophy:**
1. **Every session ends with something deployable or revertable.** No accumulated half-finished state.
2. **Correctness > monitoring > learning > speculation.** Bug fixes first, then visibility, then experiments.
3. **Long-running things go in the background.** A4 walk-forward, CLV data collection, and Phase C measurement windows bridge sessions — they don't block them.
4. **Branch points are decisions, not forecasts.** When the plan says "if Phase C result is X, do Y," that's a real fork.
5. **Governance is non-negotiable.** Each model deploy gets explicit user approval at the gate.

## Cluster map

The 26-agent review surfaced ~20 distinct items. Cluster them by dependency, urgency, and risk profile.

| Cluster | Items | Why grouped | Risk profile |
|---|---|---|---|
| **C1 — Correctness & operational hardening** | A3 (weather + 2nd export), A2 narrowed (MAX_EDGE tighten), X2 (verify A1 vapor) | Real bugs / data integrity. No model changes. | Low — reversible in minutes |
| **C2 — Monitoring foundations** | A5 (CLV table), B1 (early-warning) | Visibility infrastructure. Compounding payoff over time. | Low — additive, no behavior change |
| **C3 — Model improvement experiments** | A4 (Poisson WF), E1 (archetype categoricals WF) | Walk-forward only. Decide deploy with data. | Medium — compute cost, no live risk |
| **C4 — Model deploy (conditional)** | A4 ship, E1 ship | Real model changes through governance gates. | Medium-high — requires shadow + measure |
| **C5 — Upstream pipeline investigation** | X1 (lineup k_analysis) | Diagnostic to determine if A1 is salvageable. | Low — reading-only |
| **C6 — NBA-port infrastructure** | E2 (CF evaluator), E3 (health-weighted signals), E4 (edge-halt), E5 (audit table) | Compound infrastructure ports from NBA. | Low — additive monitoring/safety |
| **C7 — Conditional UNDER work** | Phase C decision, Phase D (if needed) | Only fires if A4 produces signal. | Low until triggered |
| **C8 — Speculative experiments** | Lane 11 new features, Lane 13 microstructure signals, full segment models | Open-ended. Run when bored. | Low — experiment-only, may produce nothing |

C1 is the ONLY cluster with anything that resembles urgency (scratched-pitcher bug exposes the public site). Everything else can be paced.

---

## Session-by-session plan

Each session targets 3-5 hours of focused work + governance review where applicable. Some sessions overlap with long-running background tasks. Sessions are numbered, not dated — pace them at your cadence.

### Session 1 — Correctness wins + verification (3-4h)

**Goal:** Fix the one real bug (scratched pitchers on public site) and verify the load-bearing claim that killed A1.

| Step | Effort | Notes |
|---|---|---|
| X2 — Verify A1 vapor BQ check | 15 min | Run Agent D's query yourself. Confirms whether to skip A1 or revive it. |
| X1-prelim — Lineup pipeline diagnosis | 45 min | `lineup_k_analysis_processor` schedule + last-run + output table row count. Don't fix yet, just scope. |
| A3 — Weather scheduler + 2nd pre-game export | 2-3h | Three files. Schema-free. Disables = pause schedulers. |
| Session handoff doc | 15 min | What ships, what's pending, branch on X2 result. |

**Deploy at session end:** Both A3 components (weather scheduler + 2nd export at 16:30 UTC).

**Verification next day:** `SELECT COUNT(*) FROM mlb_raw.mlb_weather WHERE game_date >= CURRENT_DATE() - 1` should be non-zero. Check that no scratched-pitcher picks reached `signal_best_bets_picks` for today.

**Branch on X2 result:**
- If A1 is confirmed vapor (5 features = 0.0): X1 stays in C5, defer indefinitely
- If A1 was NOT vapor (Agent D queried wrong table): revive A1 in Session 3

---

### Session 2 — Reversible ranking change + monitoring foundation (3-4h)

**Goal:** Ship the only OVER ranking change with strong evidence, and start the CLV foundation that Phase C will need.

| Step | Effort | Notes |
|---|---|---|
| A2 narrowed — Tighten MAX_EDGE 1.5 → 1.25 | 2h | Skip the bucket re-rank for now (Agent D's CI overlap concern). One constant change + algorithm_version bump. |
| 7-day monitor query for A2 | 30 min | Save as a BQ saved query: 7d OVER HR by edge bucket. Manual check next week. |
| A5 design — CLV table + scheduler schema | 1h | Design only, don't build. Write the schema SQL, scheduler config draft. Save to docs. |
| B1 backtest design | 30 min | Write the 2024/2025 false-positive query. Don't build B1 yet. |

**Deploy at session end:** A2 narrowed (MAX_EDGE tighten). A5 + B1 are designed but not built.

**Verification 7 days later:** OVER HR Wilson LB must not regress >2pp. If it does, revert.

---

### Session 3 — A5 CLV build + A4 walk-forward dev (4-5h)

**Goal:** Build the CLV foundation and kick off the Poisson walk-forward as a background task.

| Step | Effort | Notes |
|---|---|---|
| A5 schema migration | 30 min | `ALTER TABLE mlb_predictions.prediction_accuracy ADD COLUMN clv_raw, clv_directional` + create `mlb_raw.pitcher_props_closing`. Migration MUST land first per Lane 3. |
| A5 scheduler + materializer | 2h | New `mlb-pitcher-props-closing` scheduler every 15min from -90 to 0; Python job to compute closing line. Skip auto-demote. |
| A5 backfill from existing oddsa | 30 min | Backfill using `MIN(minutes_before_tipoff)` proxy. |
| A4 dev — Change loss function | 30 min | `train_regressor_v2.py:83` RMSE → Poisson. Adapt predictor for CDF math. |
| A4 walk-forward kickoff | 1h dev + multi-hour compute | Run `walk_forward_simulation.py` with `--training-start 2024-04-01` for both RMSE-current and Poisson variants. Compare WF HR @ edge 0.75. |

**Deploy at session end:** A5 foundation live (data collecting, table exists, no behavior change). A4 WF running in background.

**Background tracking:** A4 WF takes 4-12h to complete. Don't block Session 4 on it.

---

### Session 4 — B1 build + A4 results review (3-4h)

**Goal:** Ship early-warning detector with proper backtest validation; review A4 results.

| Step | Effort | Notes |
|---|---|---|
| B1 backtest on 2024/2025 | 1h | Run the false-positive check from Session 2's design. If T1 fires >3 times/season, recalibrate thresholds before building. |
| B1 build | 2h | Assumes backtest validates. Extend `bin/monitoring/mlb_daily_performance.py`. Slack alerts to `#nba-alerts`. |
| A4 results review | 30 min | Walk-forward HR @ edge 0.75; bias on OVER + UNDER subsets; governance gate dry-run (HR ≥ 53%, Vegas bias ±1.5). |
| Decision write-up | 30 min | Document A4 results and recommendation for Session 5. |

**Deploy at session end:** B1 monitor live. A4 deploy decision documented but NOT executed.

**Branch on A4 result:**
- If Poisson WF wins by ≥2pp HR or fixes UNDER bias absolute < 0.30K → proceed to Session 5 deploy
- If Poisson WF flat → fall back to Quantile(0.5), redo WF
- If both flat → abandon A4, skip to Session 6 with current model

---

### ~~Session 5 — A4 deploy with shadow + 2-day measure~~ — SKIPPED (A4 abandoned in Session 4)

**Replaced by:** B1 monitor deploy + Session 5 carry-overs (see Session log above; full record in `docs/09-handoff/2026-05-13-mlb-roadmap-session-5.md`).

**Original plan (kept for historical context):**

**Goal:** If WF wins, deploy A4 through governance gates.

| Step | Effort | Notes |
|---|---|---|
| User approval gate | conversation | Present WF results, confirm deploy. **REQUIRED per CLAUDE.md.** |
| Upload model to GCS, register | 30 min | `./bin/model-registry.sh` flow |
| Shadow 2+ days | passive | Compare new model vs current daily. Per CLAUDE.md governance. |
| Promote after shadow OK | 30 min | Update prediction-worker env var. Verify `latestRevision = True`. |
| Post-deploy 7-day monitor | passive | Watch `model_performance_daily` for new system_id. |

**Deploy at session end:** New model running. Phase C measurement window starts.

---

### Session 6 — UNDER pipeline decision + start NBA-port work (3-4h) — NEXT ACTIVE

**Goal:** Make the UNDER re-evaluation decision on the CURRENT RMSE baseline (no Poisson measurement to wait on); start compound infrastructure.

**Prerequisite changed (A4 abandoned):** No 14-day post-Poisson window to wait on. Instead, use:
- B1 daily state from `mlb_orchestration.direction_regime_state` (live since 2026-05-13 — currently DEGRADING)
- A2 7-day monitor result (DUE 2026-05-20 — confirm or revert `MLB_MAX_EDGE=1.25`)
- Existing graded UNDER predictions in `prediction_accuracy` (raw regressor UNDER predictions are graded but not published)

Entry condition: 2026-05-20 minimum (lets A2 monitor and B1 accumulate 7 days of state).

| Step | Effort | Notes |
|---|---|---|
| Phase C BQ check | 30 min | Run the query from `05-REVISED-PLAN.md`. Three-way branch on UNDER HR. |
| Cross-check with CLV | 15 min | A5 should have ~14 days of CLV data by now. Check directional CLV on new model's UNDER predictions. |
| Decision documentation | 30 min | Write `07-PHASE-C-DECISION.md` capturing rationale. |
| Start E2 — Filter CF evaluator | 2-3h | First NBA-port. CF computes hit rate of BLOCKED picks. No auto-demote yet — observation only. |

**Branch on Phase C result:**
- UNDER HR ≥ 56% post-Poisson AND CLV positive → skip shadow, ship UNDER live with OBSERVATION-ONLY filters (Session 7 = UNDER live)
- 53% ≤ UNDER HR < 56% → corrected shadow rollout (Session 7-12 = Phase D)
- UNDER HR < 53% → leave disabled, revisit only after E1 archetype categoricals (Session 8+)

---

### Sessions 7-N — Branch execution

The next sessions depend on the Phase C branch + scheduled NBA-port work. Three scenarios:

#### Scenario A (UNDER recovers strongly) — Live ship

| Session | Work |
|---|---|
| 7 | Ship UNDER live with corrected `MLB_UNDER_ENABLED=true` + observation-only filters. Frontend impact: zero (shared 5/day cap). |
| 8 | 7-day live UNDER HR monitor + decide whether to promote filters from observation to active |
| 9 | E2 CF evaluator finish + E3 health-weighted signal multipliers |
| 10 | E4 edge-based auto-halt with MLB thresholds + E5 model_predictions_audit MVP |
| 11 | E1 archetype categoricals retrain (walk-forward) |
| 12 | E1 deploy if WF wins |
| 13+ | Speculative ideas (Lane 11/13/20) opportunistically |

#### Scenario B (shadow needed) — Corrected shadow rollout

| Session | Work |
|---|---|
| 7 | Phase D Step 1 — Repair UNDER signal pipeline (Phase 0 Step 1 from original plan, minus the harmful weight changes). 6h. |
| 8 | Phase D Step 2 — Un-hardcode `recommendation='OVER'` bookkeeping. 3h. Schema migration first. |
| 9 | Phase D Step 3 — Shadow infrastructure WITH the scoped DELETE fix + corrected gate (N≥150, HR≥58%, Wilson LB monthly). |
| 10 | Phase D Step 4 — Filters as observation-only + historical backfill via `backfill_mode=True` kwarg |
| 11+ | 45-60 day passive shadow window. Sessions 11-N: E2/E3/E4 NBA ports while shadow accumulates. |
| Final | Phase D decision: live ship if corrected gate passes |

#### Scenario C (UNDER stays disabled) — Compound improvements only

| Session | Work |
|---|---|
| 7 | E1 archetype categoricals walk-forward |
| 8 | E1 deploy if WF wins (could indirectly revive UNDER) |
| 9 | E2 CF evaluator + auto-demote |
| 10 | E3 health-weighted signals |
| 11 | E4 edge-based auto-halt |
| 12 | E5 model_predictions_audit table |
| 13+ | X1 deeper lineup pipeline rebuild (if X2 confirmed vapor and we want to revive A1) |

---

## Long-running background tasks

These don't block sessions but need calendar tracking:

| Task | Started | Calendar | Done when |
|---|---|---|---|
| A4 walk-forward compute | Session 3 | 4-12h | Session 4 reviews |
| CLV data accumulation | Session 3 | 14+ days | Session 6+ has usable corr |
| Phase C measurement window | Session 5 deploy | 14 days | Session 6 decision possible |
| Phase D shadow window (if Scenario B) | Session 9 | 45-60 days | Session N graduation gate |
| A2 7-day monitor | Session 2 | 7 days | Confirm no regression by Session 3 |
| Post-A4 deploy monitor | Session 5 | 7 days | Confirm no regression |

## Dependency graph (simplified)

```
Session 1 (A3, X2)
    ↓
Session 2 (A2 narrowed, design A5/B1)
    ↓
Session 3 (A5 build, A4 WF dev) ────► A4 WF compute (background)
    ↓
Session 4 (B1 build, A4 review) ◄────┘
    ↓
Session 5 (A4 deploy + shadow) ─────► 14-day measurement (background)
    ↓                                  + CLV data (background)
Session 6 (Phase C decision) ◄────────┘
    ↓
[Branch A | Branch B | Branch C]
```

Independent tracks that can interleave:
- C5 — X1 lineup investigation (anytime after Session 1; results inform whether to revive A1)
- C6 — E2/E3/E4/E5 NBA ports (anytime after Session 6; compound payoff regardless of branch)
- C8 — Speculative experiments (anytime, no commitments)

## Stop-and-reassess triggers

The plan should ABORT or BRANCH if:

1. **A2 7-day OVER HR regresses >2pp Wilson LB after Session 2** — revert `MAX_EDGE`, file in Phase E to investigate
2. **A4 WF fails both Poisson and Quantile in Session 4** — skip Session 5, drop to Scenario C
3. **CLV table doesn't populate in Session 3** — investigate scheduler/scraper before relying on it for Phase C
4. **B1 backtest fires >3 times/season historically in Session 4** — recalibrate or skip B1 entirely
5. **A1 vapor finding contradicted by X2 in Session 1** — revive A1 with caution; rerun X1 to confirm
6. **Phase C inconclusive in Session 6 (N < 30 of new-model UNDER picks)** — extend measurement to 21 days

## What's NOT in this roadmap

Explicit DELETES from the agent recommendations:
- **The original 45-day shadow plan with N=60/HR=56% gate** — dead. Replaced with Phase C decision tree.
- **Both proposed UNDER filters as ACTIVE blocks** — observation-only only, after corrected shadow if shadow happens.
- **The original A1 lineup feature wire-up** — replaced with X1 investigation.
- **Standalone walk-forward results table** — folded into E5 unified `model_predictions_audit`.
- **B2 auto-demote on CLV** — design only, no build until 60+ days of CLV data validates the rule.

Items deferred indefinitely:
- Lane 11 new feature ideas (7 of them)
- Lane 13 market microstructure signals (5 of them)
- Lane 20 full per-archetype model fleet
- E1 archetype categoricals (could elevate if A4 underperforms — gives us another lever)

## Estimated total calendar

| Phase | Calendar |
|---|---|
| Sessions 1-2 — Correctness + reversible wins | Week 1 |
| Sessions 3-4 — CLV foundation + monitoring + A4 WF | Week 1-2 |
| Session 5 — A4 deploy + shadow | Week 2 |
| Session 6 — Phase C decision | Week 4 (after 14-day measurement) |
| Sessions 7-N — Branch execution | Weeks 4-12 depending on scenario |

Total active dev: ~40-60 hours over 12 weeks. Most of the calendar is measurement windows, not work.

## Per-session deliverables checklist

End of every session, produce:
- One-line "what shipped" entry
- One-line "what's measuring" entry (long-running background)
- One-line "next session entry condition" (prerequisite for moving forward)

This becomes a session-log doc that can be appended to `06-MULTI-SESSION-ROADMAP.md` as we go.

## User decisions at each branch point

The roadmap requires explicit user input at:
- **Session 5 governance gate** — approve A4 model deploy
- **Session 6 Phase C decision** — confirm branch A/B/C
- **Scenario B Session 9** — approve shadow infrastructure ship (engineering hazards verified)
- **Scenario A Session 8** — promote observation filters to active
- **Sessions 11/12 (E1)** — approve archetype categoricals deploy if WF wins

Everything else ships under your standing "code-only, reversible" approval.
