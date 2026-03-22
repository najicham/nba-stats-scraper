# Session 478 Handoff — Grading Outage Fix + System Hardening

**Date:** 2026-03-21
**Previous:** Session 477 (error tracking, pipeline bulletproofing, MLB schedulers resumed)

---

## TL;DR

Fixed a 6-day grading pipeline outage caused by a BigQuery-incompatible SQL pattern introduced in commit `ab289a57` (Mar 16). Backfilled all missing data for Mar 16-20. Deactivated the last edge-collapsed CatBoost model. Then ran 4 diagnostic agents (2 Opus, 2 Sonnet) to analyze root causes and implemented all 8 recommended improvements: new canary, BadRequest re-raise, post_grading_export resilience, league_macro all-model filter, pre-commit BQ SQL hook, fleet CRITICAL escalation, automated recovery script, and DEGRADING signal normalization.

---

## What Was Done

### 1. Grading Outage Root Cause + Fix (CRITICAL)

**Bug:** Commit `ab289a57` (Mar 16, 20:37 ET) introduced a multi-column `IN` subquery in `prediction_accuracy_processor.py`:
```sql
(player_lookup, system_id) IN (SELECT player_lookup, system_id FROM ...)
```
BigQuery does NOT support multi-column `IN` subqueries — raises `400 BadRequest: Subquery of type IN must have only one output column`. Every grading run failed silently for 6 days.

**Silent failure chain:** `BadRequest` was caught with transient errors → returned `[]` → treated as `no_predictions` → published `status=skipped` → `post_grading_export` bailed on `status != success` → `league_macro`, `signal_health`, `model_performance`, `filter_counterfactual` all went stale → UI showed no recent grades.

**Fix:** Replaced with `EXISTS` correlated subquery (commit `310c01fc`). `BadRequest` is now re-raised (permanent bug, not transient).

**Backfill:** Triggered grading for all 6 missing dates. `prediction_accuracy` restored:

| Date | Graded |
|------|--------|
| Mar 15 | 142 (pre-bug baseline) |
| Mar 16 | 36 |
| Mar 17 | 87 |
| Mar 18 | 51 |
| Mar 19 | 74 |
| Mar 20 | 31 |

`league_macro_daily` backfilled for Mar 15-17, 19. Mar 18/20 missing — expected (only non-v12 CatBoost ran those days; league_macro filter extended to all models going forward). `signal_health_daily` manually backfilled Mar 16-20. Phase 6 export re-triggered, UI JSONs updated.

### 2. CatBoost Edge-Collapsed Model Deactivated

**Model:** `catboost_v12_noveg_train0103_0214`
**Why:** avg_abs_diff = 1.15, below the 1.2 CatBoost collapse threshold. Generating predictions but none making it into best bets.
**Result:** disabled in `model_registry`, 150 active predictions deactivated (Mar 21).

**Current fleet (as of Session 478 EOD):**

| Model | Status | Notes |
|-------|--------|-------|
| `lgbm_v12_noveg_train0103_0227` | active+enabled | Feb 27 training end. Feb-trained = healthy edge. |
| `lgbm_v12_noveg_train1215_0214` | active+enabled | Dec 15 training start. First full week in progress. |
| `catboost_v12_noveg_train0103_0214` | **DISABLED** | Deactivated this session. Edge collapsed. |

**Two LGBM models, both Feb-trained — healthy edge.**

### 3. Eight Monitoring + Resilience Improvements (commit `6b631ac8`)

Implemented all 8 recommendations from 4-agent analysis:

| # | Change | File |
|---|--------|------|
| 1 | **Grading freshness canary** — alerts within 30 min of any grading outage | `pipeline_canary_queries.py` |
| 2 | **Re-raise BadRequest** — permanent SQL bugs no longer silently swallowed | `prediction_accuracy_processor.py` |
| 3 | **post_grading_export always runs analytics** regardless of grading status; accepts deprecated `graded_date` key | `post_grading_export/main.py` |
| 4 | **league_macro all-model filter** — queries `model_registry WHERE enabled=TRUE` instead of hardcoded catboost_v12 | `ml/analysis/league_macro.py` |
| 5 | **validate-bq-sql-patterns pre-commit hook** — blocks multi-column IN, `::cast`, ILIKE, EXCEPT ALL at commit time | `.pre-commit-hooks/`, `.pre-commit-config.yaml` |
| 6 | **Fleet CRITICAL escalation** — edge collapse alert adds CRITICAL when `healthy_edge_models < 2` | `pipeline_canary_queries.py` |
| 7 | **bin/recover-grading.sh DATE_START DATE_END** — automates 8-step recovery in one command | `bin/recover-grading.sh` |
| 8 | **DEGRADING signal guard** — requires `picks_7d >= 5` before classifying DEGRADING, prevents false alarms from grading gaps | `ml/signals/signal_health.py` |

### 4. MLFeatureStoreProcessor False-Positive Fix

`_has_games_on_date()` was called at line 857 but never defined (Session 478 commit `310c01fc`). Implemented method — queries `nba_reference.nba_schedule` and gracefully skips no-game dates instead of raising AttributeError.

### 5. pipeline-health-summary Redeployed

Was 3 days stale (stuck at commit `5c9c87b`, Mar 15). Manually triggered via `gcloud builds triggers run deploy-pipeline-health-summary`. Now at `310c01fc`.

### 6. MLB System Status

- **Worker:** Deployed and healthy (revision `00020-vcs`, updated Mar 21)
- **Model registry:** `catboost_mlb_v2_regressor_36f_20250928` enabled=TRUE, is_production=TRUE, 70% HR
- **0 predictions:** Expected — `mlb_raw.mlb_schedule` only has data through 2025-09-28. No 2026 schedule scraped yet.
- **Opening Day:** March 27, 2026
- **All 35 schedulers:** ENABLED (resumed Session 477)

---

## State of Key Tables (as of Mar 21 EOD)

| Table | Status |
|-------|--------|
| `prediction_accuracy` | ✅ Current through Mar 20 (Mar 21 pending tonight's Phase 3) |
| `league_macro_daily` | ✅ Mar 15-17, 19 backfilled. Mar 18/20 legitimately empty (no v12 data) |
| `signal_health_daily` | ✅ Backfilled Mar 16-20 |
| `signal_best_bets_picks` | ✅ Mar 16-20 graded. Mar 21 LeBron pick pending tonight |
| `filter_overrides` | ✅ Empty = normal (no filters hit demote threshold) |
| `filter_counterfactual_daily` | Last: Mar 15 — will catch up automatically as grading flows |
| `model_performance_daily` | Will catch up via post_grading_export after tonight's grading |

---

## Open Items / Next Session

### Must Do Before March 27 (MLB Opening Day)
- Verify MLB schedule data is populated for 2026 season. If not by Mar 24, manually trigger the schedule scraper.
- Confirm `mlb-resume-reminder-mar24` fires correctly on March 24.
- Check MLB predictions are being generated for Opening Day games (Mar 27 AM).

### Monitor This Week
- **lgbm_1215 first full week:** Watch hit rate — if below 52.4% by Mar 25, deactivate.
- **Weekly-retrain CF:** Still paused (Vegas MAE ~5.4-5.7, gate is 5.0). Do NOT resume.
- **OVER floor at 5.0:** Do NOT lower to 4.5 until lgbm_1215 has a full week of data.
- **Mar 18/20 league_macro gap:** Now fixed for future dates (all-model filter). Historical gap is permanent and acceptable.

### Known Constraints (from Sessions 477-478)
- Do NOT resume `weekly-retrain` CF (Vegas MAE gate: 5.0)
- Do NOT re-enable `catboost_v9_low_vegas` (45.6% HR + sanity guard loop)
- Do NOT lower OVER floor to 4.5 (wait for lgbm_1215 full week)

---

## Key Files Changed This Session

```
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py  # v5.4 SQL fix + BadRequest re-raise
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py     # _has_games_on_date() added
orchestration/cloud_functions/post_grading_export/main.py                      # always run analytics, accept graded_date
ml/analysis/league_macro.py                                                    # all-model filter
ml/signals/signal_health.py                                                    # DEGRADING picks_7d guard
bin/monitoring/pipeline_canary_queries.py                                       # freshness canary + CRITICAL escalation
.pre-commit-hooks/validate_bq_sql_patterns.py                                  # NEW: BQ SQL pattern hook
.pre-commit-config.yaml                                                         # added validate-bq-sql-patterns
bin/recover-grading.sh                                                          # NEW: automated recovery script
```

**Commits this session:**
- `310c01fc` — grading fix + MLFeatureStore _has_games_on_date
- `6b631ac8` — all 8 monitoring/resilience improvements

---

## Recovery Reference

If grading fails again, the entire recovery is now one command:
```bash
./bin/recover-grading.sh YYYY-MM-DD YYYY-MM-DD
```

This replaces the 8-step manual process from Session 478.

---

## Session Learnings Added

1. **BigQuery multi-column IN subquery** — BQ rejects `(col1, col2) IN (SELECT ...)` at runtime. Valid ANSI SQL, invisible to Python syntax checks and mocked BQ tests. Use `EXISTS` instead. New pre-commit hook blocks this pattern.

2. **Error swallowing chain** — catching `BadRequest` with transient errors made a permanent SQL bug indistinguishable from "no games today." Re-raise permanent errors so monitoring can catch them.

3. **post_grading_export analytics should always run** — analytics use rolling windows and stay fresh regardless of grading status. Gating them behind `status=success` caused 6 days of stale `league_macro_daily`, `signal_health_daily`, `model_performance_daily`.

4. **post_grading_export message format** — `{"target_date": "DATE", "status": "success", "graded_count": N}` — must have all three. CF now also accepts deprecated `graded_date` key.
