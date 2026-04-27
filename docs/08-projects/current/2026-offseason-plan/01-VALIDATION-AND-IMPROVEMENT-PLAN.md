# Validation & Improvement Plan — 2026 Off-Season

**Created:** 2026-04-19 (Session 545)
**Source:** 4-agent Opus audit across data quality, model training, signal pipeline, monitoring
**Status:** Draft — awaiting prioritization sign-off

---

## Overview

Four independent Opus agents audited the system across four domains. Combined findings: **32 concrete issues** across data quality, training integrity, signal pipeline, and monitoring. Below they are triaged into three tiers based on impact and whether they block the 2026-27 season.

**Quick summary of what the agents found:**
- **1 confirmed bug** causing silent model blackouts today (signal pipeline)
- **3 training integrity issues** inflating walk-forward HR metrics (leakage, leaky val split, leaky governance eval)
- **4 unguarded pipeline boundaries** that let bad data reach predictions silently
- **3 monitoring bugs** producing either false positives or missing real failures
- **MLB monitoring is near-zero** despite being an active in-season product

---

## Tier 1 — Fix Before Season Starts (Bugs + Critical Gaps)

These block system reliability or produce silently wrong results today.

---

### T1-1. `high_book_std_under_block` UnboundLocalError — silent model blackout [BUG] ✅ FIXED 2026-04-26 (commit `06feba37`)

**File:** `ml/signals/aggregator.py:921`
**Problem:** `_record_filtered(pred, 'high_book_std_under_block', pred_edge, len(qualifying), tags)` references `qualifying` and `tags` before they are defined (line 1150). On first iteration where an UNDER pick has `multi_book_line_std >= 0.75`, the aggregator crashes with `UnboundLocalError`. The exception is swallowed by `per_model_pipeline.py:1678`, returning `candidates=[]` for the crashing model with no Slack alert. Downstream `best_bets_filtered_picks.signal_tags` rows for this filter contain stale data from the prior prediction.

**Fix:** Pass empty defaults in the early call: `_record_filtered(pred, 'high_book_std_under_block', pred_edge, 0, [])`, or move the block to after line 1152. Add a unit test with a single UNDER prediction at `multi_book_line_std >= 0.75`.

**Impact:** HIGH — any day with a qualifying UNDER pick silently drops an entire model's candidates.

---

### T1-2. Daily health check queries disabled BDL table — fires CRITICAL every morning [BUG] ✅ FIXED 2026-04-26 (commit `06feba37`)

**File:** `orchestration/cloud_functions/daily_health_check/main.py:586-593`
**Problem:** `check_game_completeness` queries `nba_raw.bdl_player_boxscores`, which has been intentionally empty since BDL was disabled. This check fires CRITICAL 0/N every morning, producing chronic alert fatigue in `#app-error-alerts` or silently failing the CF. There is no corresponding check on the actual primary source `nba_raw.nbac_gamebook_player_stats`.

**Fix:** Replace `bdl_player_boxscores` with `nbac_gamebook_player_stats` (per CLAUDE.md "Key Tables"). Use `nba_reference.nba_schedule` for expected game count with `game_status = 3` (Final).

**Impact:** MEDIUM-HIGH — morning health report is unreliable; BDL alert drowns real signals.

---

### T1-3. WARNING alerts suppressed when CRITICAL fires — Slack routing bug [BUG] ✅ FIXED 2026-04-26 (commit `06feba37`)

**File:** `orchestration/cloud_functions/daily_health_check/main.py:697`
**Problem:** `if results.warnings > 0 and not results.critical and SLACK_WEBHOOK_URL_WARNING:` — the `and not results.critical` clause means all warnings are silently dropped from `#nba-alerts` whenever any critical fires. During incidents, multiple issues fire simultaneously; the channel most likely to be watched misses secondary problems exactly when they matter most.

**Fix:** Remove `and not results.critical`. Warnings should post independently of critical state.

**Impact:** MEDIUM — alert quality degrades during incidents.

---

### T1-4. Phase 4→5 orchestrator has no feature-store coverage gate [CRITICAL GAP]

**File:** `orchestration/cloud_functions/phase4_to_phase5/main.py`
**Problem:** The Phase 3→4 orchestrator has three coverage gates. The Phase 4→5 orchestrator has none — it only waits for processor completion signals. If `MLFeatureStoreProcessor` crashes partway through (or silently produces 30 of 200 expected players), Phase 5 triggers and predicts on the partial set. The coordinator `quality_gate.py` only checks per-player quality at prediction time — by then the system is already producing a small, skewed pick set.

**Fix:** Add `verify_feature_store_ready(game_date)` in the phase4_to_phase5 CF, modeled after `check_data_coverage` in phase3_to_phase4:
```sql
SELECT
  COUNTIF(required_default_count = 0) as clean_players,
  (SELECT COUNT(DISTINCT player_lookup) FROM upcoming_player_game_context WHERE game_date=X) as expected_players
FROM ml_feature_store_v2 WHERE game_date = X
```
Block Phase 5 trigger if `clean_players < 0.6 * expected_players`. Alert with list of missing players to `#nba-alerts`.

**Impact:** HIGH — closes the only unguarded phase boundary.

---

### T1-5. Quality scoring blind to V16/V17 features (indices 54-59) [CRITICAL GAP]

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py:172`
**Problem:** `FEATURE_COUNT = 54` in the scorer vs `FEATURE_COUNT = 60` in the processor. Features 54-59 (V16: `over_rate_last_10`, `margin_vs_line_avg_last_5`; V17: additional) are written to the feature store but their quality is never tracked. `required_default_count` never increments for these features — a bug that zeros out `over_rate_last_10` for all players won't trip the zero-tolerance gate. The gate is blind to production-critical features.

**Fix:**
1. Extend `ml_feature_store_v2` BQ schema to add `feature_54_quality` through `feature_59_quality` + `feature_54_source` through `feature_59_source` columns.
2. Update `quality_scorer.py:172` to `FEATURE_COUNT = 60`. Add entries for 54-59 in `FEATURE_UPSTREAM_TABLES`, `DEFAULT_FALLBACK_REASONS`, `FEATURE_CATEGORIES`.
3. Add migration script in `schemas/bigquery/predictions/`.

**Impact:** MEDIUM-HIGH — zero-tolerance system is currently enforced for only 54 of 60 production features.

---

### T1-6. Published JSON vs BQ store consistency never reconciled [CRITICAL GAP]

**File:** `bin/monitoring/pipeline_canary_queries.py`
**Problem:** No canary checks that `v1/signal-best-bets/{date}.json` pick count matches `signal_best_bets_picks` for that date. The Session 481 scoped-DELETE limitation (empty output = nothing deleted from BQ but GCS IS updated) means published JSON and BQ can silently diverge. Users see the JSON; operators query BQ. Nobody monitors the reconciliation.

**Fix:** Add `check_published_vs_store_consistency()` canary — hourly, for today's date only:
```python
# Load v1/signal-best-bets/today.json from GCS
# Compare pick_count to COUNT(*) FROM signal_best_bets_picks WHERE game_date = today AND signal_status = 'active'
# Fail if |published - stored| > 0
```
Same pattern for `all-players.json` vs `player_prop_predictions`.

**Impact:** HIGH — site-vs-backend divergence is invisible to all current monitoring.

---

## Tier 2 — High-Impact Off-Season Work (Before Oct 2026 Season Start)

These require meaningful effort but directly impact prediction quality and system reliability.

---

### T2-1. Random train/val split enables temporal leakage in all deployed models [LEAKAGE]

**File:** `ml/experiments/quick_retrain.py:3836-3842` and `orchestration/cloud_functions/weekly_retrain/main.py`
**Problem:** Production retrain uses `sklearn.train_test_split(..., test_size=0.15, random_state=seed)` — a random split that interleaves future games into the validation set used for early stopping. `season_walkforward.py:541` gets this right with a temporal split, but the production path doesn't use it. Every model deployed since Session 458 has early-stopping tuned on a leaky val set. Likely responsible for 0.5-1.5pp of edge compression attributed to market tightness.

**Fix:** In `quick_retrain.py:3836`, sort `X_train_full`/`y_train_full` by `df_train['game_date']` and take the last 15% temporally as the val set. Apply identical fix to the weekly_retrain CF. Weights must follow the same index.

**Impact:** HIGH — cheap fix affecting every deployed model.

---

### T2-2. Governance gates have no holdout — N=15-25 samples cause fleet instability [LEAKAGE]

**File:** `orchestration/cloud_functions/weekly_retrain/main.py:484` and `quick_retrain.py:4622-4645`
**Problem:** `run_governance_gates` computes HR on the same 7-14 day eval window immediately following `train_end`. With `min_n_graded = 15` and edge-3+ mask yielding ~25-40 picks, one unlucky week fails valid models (false governance failure) and one lucky week ships bad models (false pass). The fleet ping-ponging Jan-Mar is likely caused by this. `GOVERNANCE_SEASON_RESTART` workaround at line 112 loosens gates further rather than fixing the stats.

**Fix:** Restructure: train on `[train_start, train_end - 14]`, use `[train_end - 13, train_end - 7]` for val/early-stop, hold `[train_end - 6, train_end]` strictly out. Require `min_n_graded >= 40` on combined val+holdout. Consider adding a reference-slice gate: new model must score within 2pp of champion on a fixed Dec 1-Jan 15 slice.
**Location:** `weekly_retrain/main.py:743`, `quick_retrain.py:4622-4645`.

**Impact:** HIGH — addresses the primary cause of fleet instability this season.

---

### T2-3. V12 feature augmentation joins future eval data when computing season averages [LEAKAGE]

**File:** `ml/experiments/quick_retrain.py:1090-1188`
**Problem:** `augment_v12_features` uses `WHERE game_date BETWEEN '2025-10-22' AND '{max_date}'` where `max_date = df['game_date'].max()` spanning train+eval. Season stats denominator for training rows therefore includes eval-period games — ~20% of training-row feature values are contaminated by future stats. In-sample metrics are inflated; walk-forward cycle-N mysteriously decays. This likely explains why V16/V17/V18 experiments looked promising in-sample but failed production.

**Fix:** In `augment_v12_features`, compute `season_stats` separately: training rows use window up to `train_end`, eval rows use window up to `game_date - 1` per row. Add a regression test: compute `season_avg` at row X with full dataset vs with data strictly-before-X; assert delta < 0.1 for 99% of rows. Audit V17 `minutes_volatility_last_10` (line 3380) similarly.

**Impact:** HIGH — affects all V12+ feature augmentation, which is every model in the fleet.

---

### T2-4. Wire Phase 2 Quality Gate into the production runtime path

**File:** `shared/validation/phase2_quality_gate.py` (written but never called)
**Problem:** `Phase2QualityGate.check_raw_data_quality()` is fully implemented but zero runtime callers exist — confirmed by grep. It only appears in tests and docs. Phase 3 triggers via direct Pub/Sub from Phase 2 with no raw-data quality check. If `nbac_gamebook_player_stats` returns a truncated roster, Phase 3 runs on partial data and the Phase 3→4 coverage gate (~6 hours later) is the first catch — but it uses `player_game_summary` as ground truth, inheriting the same blindspot.

**Fix:** Add a Phase 2 completion CF (or extend an existing processor) that calls `Phase2QualityGate.check_raw_data_quality()` before publishing to the `nba-phase3-analytics-trigger` Pub/Sub topic. Extend the gate to check odds line coverage for star players (0 lines for known starters is a silent-failure signature).

**Impact:** HIGH — catches the largest class of silent data corruption at the earliest possible point.

---

### T2-5. Compute `upstream_data_freshness_hours` in the feature store

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py:593-594`
**Problem:** Both `feature_store_age_hours` and `upstream_data_freshness_hours` are hardcoded as `0.0`/`None`. The schema and documentation describe exactly how they should be used, but the code never computes them. A feature computed from 3-day-old Phase 4 composite factors still scores as `phase4` quality=100 — a freshness bug identical to the Session 48/49 fatigue_score=0 incident.

**Fix:** In `ml_feature_store_processor.py`, before calling `quality_scorer.build_quality_visibility_fields()`, query `INFORMATION_SCHEMA.PARTITIONS` or `MAX(last_updated_at)` for the four Phase 4 upstream tables. Pass max staleness to the scorer. Gate: `upstream_data_freshness_hours > 24` → force `quality_score <= 49` → `is_quality_ready = False`.

**Impact:** HIGH — low code change, closes the biggest hole in zero-tolerance enforcement.

---

### T2-6. Deploy MLB services to deployment drift detection

**Files:** `bin/check-deployment-drift.sh:31-61`, `bin/monitoring/deployment_drift_alerter.py:37-57`
**Problem:** Zero MLB entries in either drift-detection tool. Additionally, `check-deployment-drift.sh:254-271` has a dead loop: `for service in $SERVICES` where `$SERVICES` is undefined — iterates zero times, so the Session 516 traffic-routing safety check was never actually enforced.

**Fix:**
1. Add `mlb-prediction-worker`, `mlb-prediction-coordinator`, `mlb-phase3-analytics-processors`, `mlb-grading-service`, and MLB CFs to both `SERVICE_SOURCES` maps.
2. In `check-deployment-drift.sh`, replace `for service in $SERVICES` with `for service in "${!SERVICE_SOURCES[@]}"`.

**Impact:** HIGH — half the platform has zero deployment monitoring during an active MLB season.

---

### T2-7. Expand MLB canary to match NBA coverage

**File:** `bin/monitoring/pipeline_canary_queries.py`
**Problem:** MLB has exactly 2 canary checks (predictions floor, pick ratio). NBA has 20+. The Session 520 MLB grading outage ("7 cascading bugs, 0 records ever") would have been caught immediately by a `check_grading_freshness` clone. Current MLB-specific Cloud Run Jobs (`mlb-gap-detection`, etc.) don't feed into the unified `#canary-alerts` stream.

**Fix:** Parameterize the 5 highest-value NBA canaries (`check_grading_freshness`, `check_pick_drought`, `check_registry_blocked_enabled`, `check_edge_collapse_alert`, `check_new_model_no_predictions`) to accept `(project_dataset, prediction_table, line_table)` and register MLB variants. Connect alerts to `#canary-alerts`.

**Impact:** HIGH — MLB is monitoring-unprotected during an active in-season product.

---

### T2-8. Add cross-model diversity gate to registry and weekly retrain

**File:** `bin/validation/validate_model_registry.py`, `orchestration/cloud_functions/weekly_retrain/main.py`
**Problem:** Session 487's fleet diversity collapse (r≥0.95 LGBM clones killing `combo_3way`/`book_disagreement`) was caught by human inspection after days. `validate_model_registry.py` checks duplicates, orphans, GCS consistency — but not pairwise prediction correlation. A fleet of 5 LGBM clones deploys every week with no automated gate.

**Fix:** Add `check_fleet_diversity(client)` to `validate_model_registry.py`: query `prediction_accuracy` for last 7 days, compute pairwise Pearson `r` of `predicted_points` across enabled models. FAIL if >50% of enabled-pair correlations are ≥0.92 or if no pair has r<0.80. Wire as a pre-deploy check in `weekly_retrain/main.py` after all families retrained but before enabling any.

**Impact:** MEDIUM — prevents the known regression mode that's expensive to diagnose.

---

### T2-9. Add a post-deploy smoke test before models start serving

**File:** `orchestration/cloud_functions/weekly_retrain/main.py` (after line ~1003)
**Problem:** After `weekly_retrain` enables a model, the first human-visible signal of a broken deploy (all-zero predictions, edge=0, feature mismatch) is ~36h later after grading. The decay state machine then takes 3+ more days to reach BLOCKED.

**Fix:** Before setting `enabled=TRUE` in the CF: make a live prediction call against the deployed worker for 5-10 known players. Verify predictions are in range [1, 60], std > 1.0 across players, and r > 0.3 with Vegas line. If smoke test fails, leave `enabled=FALSE` and write a `service_errors` alert. Add a nightly canary: for each enabled model, `std(predicted_points) > 1.0` on today's predictions.

**Impact:** MEDIUM — catches entire classes of deploy bugs (feature contract mismatch, model corruption) in minutes vs days.

---

### T2-10. Add playoff/offseason awareness to self-heal CF

**File:** `orchestration/cloud_functions/self_heal/main.py`, `orchestration/cloud_functions/mlb_self_heal/main.py`
**Problem:** The self-heal CF (12:45 PM ET) has no equivalent of the canary's `_is_playoff_window`. During playoffs, it sees "games scheduled, no predictions" and triggers the full Phase 3→4→predictions pipeline, fighting the auto-halt. `mlb_self_heal` has no season-start check.

**Fix:** Import `shared.utils.schedule_guard.has_regular_season_games` (already in canary) and add an offseason check at the top of `self_heal_check()`. Skip prediction-gap healing during NBA playoffs/offseason; still clear stuck run_history and check Phase 2 health. Apply MLB season boundaries to `mlb_self_heal`.

**Impact:** MEDIUM — wasted compute + potential conflict with auto-halt.

---

## Tier 3 — Medium-Priority Improvements (During Season / When Convenient)

---

### T3-1. `signal_health_daily` tracks a stale `ACTIVE_SIGNALS` set

**File:** `ml/signals/signal_health.py:49-128`
**Problem:** 9+ registered signals (including `quantile_ceiling_under`, `friday_over_block`, Session 462-469 active filters) are not in `ACTIVE_SIGNALS`. Health multipliers default to 1.0x for missing signals regardless of COLD streaks. The firing canary can't detect these as DEAD.

**Fix:** Add a CI assertion that every signal in `SignalRegistry.build_default_registry()` is in `ACTIVE_SIGNALS` or explicitly marked legacy. Back-populate the missing tags. Long-term: make signal registration the single source of truth by auto-populating `ACTIVE_SIGNALS` from the registry.

---

### T3-2. `ELIGIBLE_FOR_AUTO_DEMOTE` list hasn't kept pace with filter additions

**File:** `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py:31-46`
**Problem:** 14 filters eligible for auto-demotion; 16+ active blocking filters added in Sessions 462-514 are not in the list. Human-review debt grows with every new filter.

**Fix:** Audit the list. Add to `ELIGIBLE_FOR_AUTO_DEMOTE` or add to `NEVER_DEMOTE` with a justification comment. Better: move to a decorator on each filter class so registration is automatic.

---

### T3-3. Exception handling in `run_all_model_pipelines` is silent

**File:** `ml/signals/per_model_pipeline.py:1672-1688`
**Problem:** Any model pipeline crash (e.g., `UnboundLocalError` from T1-1) returns `candidates=[]` with only a log line — no Slack alert. The MQ model dropping out for a day is invisible until human investigation.

**Fix:** After the model loop, if `models_with_error` is non-empty, emit a Slack alert to `SLACK_WEBHOOK_URL_ALERTS`. Optionally raise when `mode=production` and fewer than 3 models succeeded.

---

### T3-4. `book_count` never populated — book-count-aware thresholds silently default

**Files:** `ml/signals/sharp_consensus_under.py:40-52`, `ml/signals/book_disagree_over.py:42-48`, `ml/signals/per_model_pipeline.py`
**Problem:** Session 522 added book-count-aware thresholds to fix the `0-14 BB` regression, but `book_count` is never queried or attached to predictions. All signals fall through to the "conservative unknown default" of 1.5, defeating the fix.

**Fix:** Add `book_count` to the ML feature store or surface it through `per_model_pipeline.py`'s `book_stats` CTE. The `book_std_source` column already plumbed at line 523 could carry this.

---

### T3-5. Pipeline merger has no family diversity gate

**File:** `ml/signals/pipeline_merger.py:322-333`
**Problem:** Warns when one model sources >40% of picks but doesn't check family diversity. LGBM clones with r=0.95 can dominate the merge without triggering any alert.

**Fix:** Add a family-diversity check using `classify_system_id` from `cross_model_subsets.py`. Log WARNING when all picks come from a single family. Optionally enforce a per-family cap (e.g., 60% max).

---

### T3-6. Scraper expected-count validation has no baseline

**File:** `scrapers/mixins/validation_mixin.py:65`
**Problem:** `expected_rows = actual_rows` — partial scraper output (8 of 12 games, 150 of 450 players) passes validation with `status=OK`. Schedule tells us exactly how many games to expect.

**Fix:** Add `_get_expected_row_count()` to schedule-aware scrapers. Flag WARNING if `actual/expected < 0.9`, CRITICAL if `< 0.5`. Alternatively compute rolling p10/p90 baselines from the existing `scraper_output_validation` table.

---

### T3-7. `--force-register` flag has no audit trail or guardrails

**File:** `ml/experiments/quick_retrain.py:374-375`
**Problem:** `--force-register` bypasses all governance gates with only a print statement. `--force-register --enable` together deploys a governance-failed model immediately with no Slack alert and no BQ audit row.

**Fix:** Require `--force-reason "text"` (20+ chars) alongside `--force-register`. Write to `nba_orchestration.service_errors` with `error_type='governance_override'`. Block `--force-register --enable` together — force-registered models must shadow 2+ days first. Add a canary that alerts when any enabled model has `notes LIKE 'FORCE_OVERRIDE:%'`.

---

### T3-8. Self-heal history is incomplete — healing_events table barely populated

**File:** `orchestration/cloud_functions/self_heal/main.py`, `bin/monitoring/pipeline_canary_queries.py`
**Problem:** The self-heal CF logs to Firestore (`log_healing_to_firestore`) but never calls `HealingTracker`. `mlb_self_heal` logs nothing. The canary's `auto_backfill_shadow_models` and `auto_retrigger_phase3` only send Slack alerts. `analyze_healing_patterns.py` reads exclusively from `healing_events`, so pattern-mining is blind to its most active consumers.

**Fix:** Call `HealingTracker().record_healing_event()` in (a) `self_heal/main.py` after each phase trigger, (b) `mlb_self_heal/main.py`, and (c) the two auto-heal blocks in `pipeline_canary_queries.py`.

---

### T3-9. Scheduler cadence drift has no canary

**File:** `bin/monitoring/pipeline_canary_queries.py`
**Problem:** `check_scheduler_health()` only flags non-OK status codes. Jobs that never ran because their month filter excludes them appear as `has_run=False` and are silently skipped. This is how the "MLB schedulers were April-only" (CLAUDE.md) bug persisted.

**Fix:** Add `check_scheduler_cadence_drift`: compare `(now - last_attempt_time)` against the cron's expected interval. Alert if a job should have fired but hasn't in 3× its interval while inside its active window. Maintain a static `EXPECTED_MAX_GAP_MINUTES` map for the ~20 highest-priority jobs.

---

### T3-10. MultiQuantile signals are dead code — quantile fields never flow through pipeline

**Files:** `ml/signals/quantile_ceiling_under.py`, `ml/signals/per_model_pipeline.py`
**Problem:** `quantile_ceiling_under` is in `UNDER_SIGNAL_WEIGHTS` with weight 3.0 but `pred['quantile_p75']`/`pred['quantile_p25']` are never populated — `per_model_pipeline._query_all_model_predictions()` doesn't parse `critical_features`. Signal never fires.

**Fix:** In `per_model_pipeline.py` around line 1040, parse `critical_features` JSON and attach `quantile_p25`/`quantile_p75` to the pred dict. SELECT `p.critical_features` in the `preds` CTE (line 187-215). Then graduate signals or confirm shadow status based on live data.

---

## Summary Table

| ID | Description | Domain | Impact | Effort |
|----|-------------|--------|--------|--------|
| T1-1 | `high_book_std_under_block` UnboundLocalError | Signal | HIGH | XS |
| T1-2 | Daily health check queries disabled BDL table | Monitor | MED-HIGH | XS |
| T1-3 | WARNING suppressed when CRITICAL fires | Monitor | MEDIUM | XS |
| T1-4 | No Phase 4→5 feature-store coverage gate | Data | HIGH | S |
| T1-5 | Quality scoring blind to V16/V17 features (54-59) | Data | MED-HIGH | M |
| T1-6 | Published JSON vs BQ store never reconciled | Monitor | HIGH | S |
| T2-1 | Random val split temporal leakage in all models | Training | HIGH | S |
| T2-2 | Governance gates no holdout — fleet instability | Training | HIGH | M |
| T2-3 | V12 feature augmentation joins future eval data | Training | HIGH | M |
| T2-4 | Phase 2 Quality Gate unwired | Data | HIGH | M |
| T2-5 | `upstream_data_freshness_hours` never computed | Data | HIGH | S |
| T2-6 | MLB services missing from deployment drift | Monitor | HIGH | S |
| T2-7 | MLB canary coverage ~10% of NBA | Monitor | HIGH | M |
| T2-8 | No cross-model diversity gate in registry | Training | MEDIUM | M |
| T2-9 | No post-deploy smoke test | Training | MEDIUM | S |
| T2-10 | Self-heal CF no playoff/offseason awareness | Monitor | MEDIUM | S |
| T3-1 | `ACTIVE_SIGNALS` stale in signal_health_daily | Signal | MEDIUM | S |
| T3-2 | `ELIGIBLE_FOR_AUTO_DEMOTE` list stale | Signal | MEDIUM | S |
| T3-3 | Model pipeline crashes are silent | Signal | MEDIUM | XS |
| T3-4 | `book_count` never populated | Signal | MEDIUM | S |
| T3-5 | Pipeline merger no family diversity gate | Signal | MEDIUM | S |
| T3-6 | Scraper expected-count validation | Data | MEDIUM | M |
| T3-7 | `--force-register` no audit trail | Training | MEDIUM | S |
| T3-8 | Self-heal history barely populated | Monitor | MEDIUM | S |
| T3-9 | Scheduler cadence drift canary | Monitor | MEDIUM | S |
| T3-10 | MultiQuantile signals dead code | Signal | MEDIUM | S |

**Effort:** XS = < 1h, S = 1-4h, M = half-day to full day

---

## Recommended Off-Season Execution Order

### Phase A — Immediate (this week, 1-3 days)
Fix the 3 confirmed bugs (T1-1, T1-2, T1-3) + the 2 single-file monitoring gaps (T1-6, T2-6). These are 1-2h each and improve system reliability immediately.

### Phase B — Pre-Season (June-August 2026)
Training integrity trifecta (T2-1, T2-2, T2-3) — these compound each other; fix together, then retrain the full fleet on clean walk-forward data. Expected to recover 1-3pp of HR. Add Phase 4→5 gate (T1-4) and freshness computation (T2-5) while touching the precompute pipeline.

### Phase C — Infrastructure Hardening (August-September)
Wire Phase 2 gate (T2-4), expand MLB canary (T2-7), add cross-model diversity gate (T2-8), self-heal playoff awareness (T2-10), smoke test (T2-9). Full quality scoring for V16/V17 (T1-5).

### Phase D — Polish (During Season)
T3 series: signal registry consistency check, auto-demote list audit, book_count plumbing, merger diversity gate, scraper baselines, force-register audit trail, healing_events completeness, scheduler cadence canary.

---

## Not Listed (Known Dead Ends / Lower Priority)

- `qualifying_subsets` provenance in per-model pipeline (T3 bonus from agent) — pick transparency improvement, doesn't affect accuracy
- `edge_zscore` computed but never used in `aggregator.py` — cleanup only
- `_weighted_signal_count` method never called — dead code removal
- `capped_composite_score` not used for ranking — evaluate after season
- `experiment_harness.py` seed variance conflated with data variance — affects experiment validity but Session 407-410 already found all features DEAD_END anyway
- SQL injection risk in `auto_register_in_model_registry` — internal tool, correctness fix (0.0 as NULL) is worth doing but not urgent
