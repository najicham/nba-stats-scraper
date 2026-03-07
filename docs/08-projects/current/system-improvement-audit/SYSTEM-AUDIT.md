# System Improvement Audit — Session 429

**Date:** 2026-03-07
**Purpose:** Comprehensive system audit to identify and prioritize improvements across the entire NBA prediction platform.

---

## Current System State

- **Fleet:** 9 enabled models (after 2 BLOCKED deactivations this session)
- **Algorithm:** v429_signal_weight_cleanup (deployed)
- **Signals:** 28 active + 26 shadow, 19 active + 10 obs negative filters
- **Pipeline:** 6-phase (Scrape → Raw → Analytics → Precompute → Predict → Publish)
- **Infrastructure:** 9 Cloud Run services, 57 Cloud Functions, 214 BQ schemas

---

## Keyword Map — Every Component of the System

### 1. MODEL LIFECYCLE

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 1.1 | **training** | quick_retrain.py, experiment_harness, monthly CF | Semi-auto (monthly CF + manual) | No auto-retrain on staleness threshold |
| 1.2 | **registry** | BQ model_registry (58 cols), model-registry.sh, GCS manifest | Auto (self-register on train) | GCS manifest not auto-synced after training |
| 1.3 | **deployment** | Env var model paths, Cloud Run update, --promote flag | Manual | No staging, no canary, no rollback mechanism |
| 1.4 | **versioning** | feature_contract.py (SSOT), model naming, feature_set tracking | Partial | Hardcoded feature lists in prediction_systems/*.py drift from contract |
| 1.5 | **selection** | model_selection.py, CHAMPION_MODEL_ID, worker model cache | Manual | Champion hardcoded in code, not queried from registry |
| 1.6 | **governance** | 5 training gates, 10-layer runtime protection, decay state machine | Multi-layer auto | AUTO_DISABLE not enabled, missing service_errors table |
| 1.7 | **retraining** | retrain_reminder CF (Mon 9AM), monthly_retrain CF, 56d window | Semi-auto | No force-retrain when staleness exceeds threshold |
| 1.8 | **retirement** | deactivate_model.py, decay_detection CF, status lifecycle | Semi-auto | No auto-cleanup of very old models, no auto-deactivation |
| 1.9 | **fleet_diversity** | 145 model pairs r>=0.95, cross_model_scorer.py | Broken | Zero true diversity — consensus bonus never meaningful |
| 1.10 | **experiment** | experiment_harness, walk-forward, backfill features, grid results | Manual | Results not auto-fed back into training decisions |

**Key Files:**
- `ml/experiments/quick_retrain.py` — Training with governance gates
- `ml/experiments/experiment_harness.py` — Multi-seed experiment runner
- `bin/model-registry.sh` — CLI registry management
- `bin/deactivate_model.py` — Cascade deactivation (7 steps)
- `bin/retrain.sh` — Family retraining orchestrator
- `shared/config/model_selection.py` — CHAMPION_MODEL_ID (hardcoded)
- `shared/ml/feature_contract.py` — Feature name/order SSOT
- `predictions/worker/prediction_systems/catboost_v*.py` — Feature list copies (drift risk)
- `orchestration/cloud_functions/decay_detection/main.py` — State machine CF
- `orchestration/cloud_functions/retrain_reminder/main.py` — Weekly staleness check
- `orchestration/cloud_functions/monthly_retrain/main.py` — Automated monthly retrain

---

### 2. DECAY & HEALTH MONITORING

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 2.1 | **decay_detection** | CF daily 11AM ET, HEALTHY->WATCH->DEGRADING->BLOCKED SM | Scheduled | AUTO_DISABLE_ENABLED not set; CF has query syntax error |
| 2.2 | **model_performance** | model_performance_daily table, rolling HR 7/14/30d, state | Event-driven (post-grading) | No alerting on sudden single-day drops |
| 2.3 | **signal_health** | signal_health_daily table, regime (HOT/NORMAL/COLD) | Auto-populated | signal_decay_monitor.py is manual-only, not scheduled |
| 2.4 | **service_errors** | Audit table for deactivations and CF failures | MISSING | Table doesn't exist — audit trail completely broken |
| 2.5 | **brier_calibration** | brier_score_7d/14d/30d in model_performance_daily | Auto-computed | Not used in any decision-making or alerting |
| 2.6 | **retrain_staleness** | retrain_reminder CF, days_since_training metric | Weekly (Mon 9AM) | No auto-escalation or force-retrain |

**Key Files:**
- `orchestration/cloud_functions/decay_detection/main.py` — 11 crash detection layers
- `orchestration/cloud_functions/post_grading_export/main.py` — Populates model_performance_daily
- `bin/monitoring/signal_decay_monitor.py` — Signal DEGRADING/RECOVERED detection
- `ml/analysis/model_performance.py` — Backfill tool for model_performance_daily

**Decay State Machine Thresholds:**
- WATCH: 7d HR < 58% for 2+ consecutive days
- ALERT: 7d HR < 55% for 3+ consecutive days
- BLOCK: 7d HR < 52.4% (breakeven at -110 odds)
- Safety floor: 3+ models must remain enabled

**Known Issues:**
- `AUTO_DISABLE_ENABLED` env var NOT SET on decay-detection CF
- CF has query syntax error at line 41:23 (pick volume anomaly check)
- `service_errors` table doesn't exist (audit logging silently fails)
- Signal decay monitor not scheduled (manual invocation only)

---

### 3. SIGNAL SYSTEM

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 3.1 | **signal_registry** | 28 active + 26 shadow signals, registry.py | Auto (evaluate on export) | 80+ dead signals in commented code |
| 3.2 | **signal_rescue** | Edge floor bypass via validated high-HR signals | Auto | Ad-hoc 40% cap, no principled qualification gate |
| 3.3 | **signal_weights** | UNDER_SIGNAL_WEIGHTS (signal-first ranking for UNDER) | Manual | Weights from backtest, never auto-recomputed |
| 3.4 | **negative_filters** | 19 active + 10 observation blocking filters | Auto | No auto-demotion when filter HR degrades over time |
| 3.5 | **combo_registry** | 11 SYNERGISTIC combos (3way, he_ms, etc.) | Auto | Combos can't self-reference; redundancy risk |
| 3.6 | **shadow_signals** | 26 signals accumulating data, not influencing picks | Auto (fire + track) | Some wait 30+ days for N (CLV, sharp_money) |
| 3.7 | **signal_environment** | Env correlation (bench_under r=-0.456, combo_he_ms r=+0.387) | Research only | No regime-aware signal weighting implemented |
| 3.8 | **pick_angles** | 32 templates, human-readable reasoning per pick | Auto | HR percentages hardcoded, never auto-updated |
| 3.9 | **signal_promotion** | HR >= 60% + N >= 30 -> production; HR >= 65% + N >= 15 -> rescue | Manual decision | No automated promotion pipeline |

**Key Files:**
- `ml/signals/aggregator.py` — Best bets selection engine (ALGORITHM_VERSION, weights, filters)
- `ml/signals/registry.py` — Signal registration and discovery
- `ml/signals/base_signal.py` — Abstract signal interface
- `ml/signals/combo_registry.py` — Combo definitions
- `ml/signals/signal_health.py` — MODEL_DEPENDENT_SIGNALS, regime tracking
- `ml/signals/pick_angle_builder.py` — Human-readable angle templates
- `ml/signals/cross_model_scorer.py` — Multi-model consensus (v314_consolidated)
- `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` — Full inventory

---

### 4. PREDICTION PIPELINE

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 4.1 | **coordinator** | Batch orchestration, 450 players, quality gates, Firestore locks | Fully auto (6AM ET) | Distributed lock 10x30s = 5min worst case |
| 4.2 | **worker** | Model loading, feature retrieval, multi-model inference (0-20 scale) | Fully auto (Pub/Sub) | Feature contract brittle (expects exactly 60 features) |
| 4.3 | **feature_store** | ml_feature_store_v2, 60 features, quality scoring | Fully auto (midnight) | Feature bloat — adding features consistently hurts |
| 4.4 | **feature_contract** | feature_contract.py (SSOT), feature names/order/count | Partial | Duplicated lists in prediction_systems/*.py |
| 4.5 | **zero_tolerance** | default_feature_count=0 blocks prediction entirely | Multi-layer enforcement | Coverage drops 180->75 per day (intentional) |
| 4.6 | **cross_model** | Consensus scoring, agreement bonus 0-0.15, diversity_mult removed | Auto | Fleet r>=0.95 makes consensus meaningless |
| 4.7 | **best_bets_aggregator** | Edge-first selection, filter stack, rescue, natural sizing | Fully auto | UNDER edge flat at 52-53% — workaround is signal-first |
| 4.8 | **ultra_bets** | High-confidence classification, internal-only, 3 criteria | Auto | 100% backtest on N=26 = likely overfitting |
| 4.9 | **data_loaders** | Batch feature loading (450 players/query), cache TTL | Auto | All-or-nothing: 1 player failure stalls batch |

**Key Files:**
- `predictions/coordinator/coordinator.py` — Phase 5 orchestration
- `predictions/worker/worker.py` — Model inference service
- `predictions/worker/data_loaders.py` — Feature + historical game loading
- `predictions/worker/prediction_systems/catboost_v*.py` — Per-version model loaders
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — Feature computation
- `ml/signals/ultra_bets.py` — Ultra classification

---

### 5. DATA PIPELINE (Phases 1-4)

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 5.1 | **scrapers** | 61 total (37 NBA + 24 MLB), registry-based, Flask Cloud Run | Scheduled | 4 projection sources dead (only NumberFire works) |
| 5.2 | **raw_processing** | 51 processors, JSON->BQ, BigQueryBatchWriter | Event-driven (Pub/Sub) | Streaming buffer conflicts on retry |
| 5.3 | **analytics** | Player/team game summaries, Phase 3 | Event-driven | win_flag always FALSE (broken, use plus_minus>0) |
| 5.4 | **precompute** | Feature aggregation, quality scoring, Phase 4 | Event-driven | Cascade dependency failure -> empty feature store |
| 5.5 | **orchestration** | 57 Cloud Functions, Pub/Sub triggers, quality gates | Multi-pattern | No DAG visualization; implicit dependencies |
| 5.6 | **pubsub_events** | 10+ topic hierarchy, sport-specific routing | Auto | No dead-letter queue monitoring |
| 5.7 | **data_sources** | 7 external sources (NumberFire, TeamRankings, DVP, etc.) | Manual canary | data_source_health_canary not scheduled |

**Key Files:**
- `scrapers/registry.py` — Central scraper registry (NBA + MLB)
- `scrapers/main_scraper_service.py` — Flask scraper service
- `data_processors/raw/processor_base.py` — Raw processor foundation
- `data_processors/analytics/analytics_base.py` — Analytics processor base
- `data_processors/precompute/precompute_base.py` — Precompute processor base
- `orchestration/master_controller.py` — Workflow decision engine
- `shared/config/pubsub_topics.py` — Topic definitions
- `bin/monitoring/data_source_health_canary.py` — External source freshness

---

### 6. PUBLISHING & GRADING

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 6.1 | **phase6_export** | JSON to GCS, signal-best-bets, status, model-health | Fully auto | BQ write failure blocks JSON export (no fallback) |
| 6.2 | **grading** | prediction_accuracy (419K+), void handling (DNP/injury) | Fully auto (11PM ET) | No real-time/streaming grading |
| 6.3 | **grading_gaps** | Gap detector CF, <80% coverage detection, auto-backfill | Daily 9AM ET | Edge cases in backfill logic |
| 6.4 | **pick_locking** | Scoped DELETE, never drop published picks, upsert logic | Auto | Complex upsert logic is fragile |
| 6.5 | **post_grading** | Re-export picks with actuals, model_performance_daily, signal_health | Event-driven (Pub/Sub) | Chain of 4-7 exports can fail partway |

**Key Files:**
- `data_processors/publishing/signal_best_bets_exporter.py` — Best bets export (~500 LOC)
- `orchestration/cloud_functions/grading/main.py` — Grading CF
- `orchestration/cloud_functions/post_grading_export/main.py` — Post-grading chain
- `bin/monitoring/grading_gap_detector.py` — Gap detection

---

### 7. MONITORING & ALERTING

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 7.1 | **deployment_drift** | Service vs code commit comparison, 8 services checked | Every 2h | Stale deploys still happen between checks |
| 7.2 | **pipeline_canary** | 7 canary queries across all phases | Every 30min | Uses old field names in some queries (drift risk) |
| 7.3 | **daily_health** | 11-check health (services, phases, signals, GCS, quotas) | Daily 8AM ET | Meta-monitoring is shallow |
| 7.4 | **self_healing** | Stalled batch recovery (>90% complete, >15min stalled) | 15min polling | Only handles stalled batches, not other failures |
| 7.5 | **slack_alerting** | 6 channels, rate-limited, severity-routed | Auto | No escalation (PagerDuty, etc.) |
| 7.6 | **data_source_health** | 7 external sources, freshness canary, health classification | Manual | Should be scheduled (currently on-demand only) |
| 7.7 | **filter_audit** | best_bets_filter_audit table, counterfactual analysis | Auto-populated | Analysis only — not used for auto-demotion |

**Key Files:**
- `bin/monitoring/deployment_drift_alerter.py` — 2h drift checks
- `bin/monitoring/pipeline_canary_queries.py` — 30min canary (999 LOC)
- `bin/monitoring/data_source_health_canary.py` — External source freshness
- `bin/monitoring/signal_decay_monitor.py` — Signal DEGRADING/RECOVERED
- `bin/monitoring/grading_gap_detector.py` — Grading coverage
- `bin/monitoring/analyze_healing_patterns.py` — Self-healing audit
- `orchestration/cloud_functions/daily_health_check/main.py` — Comprehensive health
- `shared/alerts/rate_limiter.py` — Alert rate limiting

**Slack Channels:**
- `#app-error-alerts` — CRITICAL issues
- `#nba-alerts` — Warnings, signal decay, grading
- `#deployment-alerts` — Deployment drift (2h)
- `#canary-alerts` — Pipeline canary (30min)
- `#daily-orchestration` — Daily summary
- `#grading-alerts` — Grading-specific

---

### 8. INFRASTRUCTURE

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 8.1 | **cloud_run** | 9 services, auto-scale 0-20, gunicorn | Auto-deploy from main | No canary/blue-green deploys |
| 8.2 | **cloud_functions** | 57 functions, gen2, HTTP/Pub/Sub/Scheduler triggers | Auto-deploy from main | Entry point immutable; symlink issues |
| 8.3 | **cloud_build** | Auto-triggers on push to main, model download step | Fully auto | Any push deploys ALL services from HEAD |
| 8.4 | **pre_commit** | 22 validation hooks (schema, syntax, deploy safety, etc.) | On commit | Local only — no CI enforcement |
| 8.5 | **bigquery_schemas** | 214 SQL files, 8 datasets | Manual migration | No automated schema evolution tracking |
| 8.6 | **gcs_storage** | 3 buckets (models, API, scraper output) | Manual retention | No explicit lifecycle policies |
| 8.7 | **cost_management** | BQ quota (1500 load/table/day), batch writer workaround | Passive | No per-phase cost attribution |
| 8.8 | **calendar_regime** | Toxic window detection (Jan 30-Feb 25), regime_multiplier | Auto detect | No regime-aware signal weights or auto-filter |
| 8.9 | **env_var_management** | Model paths, feature flags, API keys, deploy tracking | Manual per-service | Drift between services; no central config |

**Key Files:**
- `cloudbuild.yaml` — Cloud Run build config
- `cloudbuild-functions.yaml` — Cloud Function build config
- `.pre-commit-hooks/` — 22 validation scripts
- `schemas/bigquery/` — 214 SQL schema files
- `shared/config/calendar_regime.py` — Toxic window detection
- `shared/config/gcp_config.py` — Project/dataset config
- `shared/utils/bigquery_batch_writer.py` — Streaming insert batching

---

### 9. MULTI-SPORT

| # | Keyword | What It Covers | Automation Level | Key Gap |
|---|---------|---------------|-----------------|---------|
| 9.1 | **mlb_pipeline** | Separate worker, scrapers, processors, signals | Deployed (not enabled) | Season starts Mar 27; E2E test needed |
| 9.2 | **sport_routing** | SPORT env var, SportConfig, dataset/topic routing | Auto | MLB Cloud Functions not all deployed |
| 9.3 | **mlb_model** | CatBoost V1 (31 features, 120d window, 54.2% WF HR) | Trained (not enabled) | Needs BQ registry enable + scheduler setup |

**Key Files:**
- `predictions/mlb/worker.py` — MLB prediction worker
- `predictions/mlb/prediction_systems/catboost_v1_predictor.py` — 31-feature CatBoost
- `predictions/mlb/pitcher_loader.py` — Shared feature loader
- `scrapers/mlb/registry.py` — 24 MLB scrapers
- `ml/signals/mlb/registry.py` — MLB signal system
- `shared/config/sport_config.py` — Multi-sport routing

---

## Current Fleet State (9 Enabled Models)

| Model | Family | Status | 7d HR | 7d N | State |
|-------|--------|--------|-------|------|-------|
| catboost_v12_noveg_train0103_0227 | v12_noveg_mae | active | 52.9% | 17 | DEGRADING |
| catboost_v12_noveg_train0104_0215 | v12_noveg_mae | active | 75.0% | 8 | HEALTHY |
| catboost_v12_noveg_train0108_0215 | v12_mae | active | 82.4% | 17 | HEALTHY |
| catboost_v12_train0104_0222 | v12_mae | active | 92.9% | 14 | HEALTHY |
| catboost_v16_noveg_train0105_0221 | v16_noveg_mae | shadow | 50.0% | 14 | BLOCKED |
| catboost_v16_noveg_train1201_0215 | v16_noveg_mae | active | 66.7% | 21 | HEALTHY |
| lgbm_v12_noveg_vw015_train1215_0208 | lgbm_v12_noveg_mae | shadow | 53.6% | 28 | DEGRADING |
| xgb_v12_noveg_s42_train1215_0208 | xgb_v12_noveg_mae | shadow | 52.9% | 17 | DEGRADING |
| xgb_v12_noveg_s999_train1215_0208 | xgb_v12_noveg_mae | shadow | 73.3% | 15 | HEALTHY |

**Concerns:**
- 1 BLOCKED model still enabled (v16 shadow)
- 3 models DEGRADING (train0103, lgbm_vw015, xgb_s42)
- All model pairs r >= 0.95 (zero fleet diversity)
- 4 HEALTHY models carrying the fleet

---

## Known Broken Infrastructure

| Item | Impact | Effort to Fix |
|------|--------|---------------|
| `service_errors` BQ table doesn't exist | Audit trail broken for all deactivations | LOW — create table from schema |
| `AUTO_DISABLE_ENABLED` not set on decay-detection CF | BLOCKED models stay enabled indefinitely | LOW — set env var (but fix CF query first) |
| decay-detection CF query syntax error (line 41:23) | Pick volume anomaly check fails silently | MEDIUM — debug + fix query |
| `win_flag` always FALSE in player_game_summary | Downstream queries produce wrong results | MEDIUM — fix computation or document workaround |
| 4 projection sources dead (FP, Dimers, DFF) | Single-source projection consensus (NumberFire only) | HIGH — external dependency |
| data_source_health_canary not scheduled | External source failures detected late | LOW — add Cloud Scheduler |
| signal_decay_monitor not scheduled | Signal degradation detected late | LOW — add Cloud Scheduler |

---

## Improvement Candidates — Full List

### Tier 1: Quick Wins (LOW effort, HIGH impact)

| ID | Keyword | Improvement | Why |
|----|---------|------------|-----|
| A1 | 2.4 service_errors | Create BQ table from schema | Unblocks audit trail for all deactivations |
| A2 | 2.1 decay_detection | Fix CF query syntax error + set AUTO_DISABLE_ENABLED | BLOCKED models auto-deactivated |
| A3 | 7.6 data_source_health | Schedule data_source_health_canary via Cloud Scheduler | Detect external source failures early |
| A4 | 2.3 signal_health | Schedule signal_decay_monitor via Cloud Scheduler | Detect signal degradation automatically |
| A5 | 1.8 retirement | Deactivate remaining BLOCKED shadow model (v16) | Clean fleet state |

### Tier 2: Medium Effort, HIGH Impact

| ID | Keyword | Improvement | Why |
|----|---------|------------|-----|
| B1 | 1.3 deployment | Add rollback mechanism (keep N previous model versions) | Currently no way to undo bad promotion |
| B2 | 1.5 selection | Move CHAMPION_MODEL_ID to model_registry, query at startup | Eliminates hardcoded champion in code |
| B3 | 1.4 versioning | Remove hardcoded feature lists from prediction_systems/*.py, import from feature_contract | Prevents feature drift |
| B4 | 3.3 signal_weights | Auto-recompute UNDER_SIGNAL_WEIGHTS from rolling 30d backtest | Weights adapt to current regime |
| B5 | 3.4 negative_filters | Auto-demote filters when counterfactual HR drops below threshold | Prevents harmful filters from persisting |
| B6 | 8.8 calendar_regime | Add regime-aware signal weight multipliers during toxic windows | Prevents toxic-window losses |
| B7 | 3.9 signal_promotion | Automated shadow -> production promotion when HR >= 60% + N >= 30 | Reduces manual signal management |

### Tier 3: High Effort, HIGH Impact

| ID | Keyword | Improvement | Why |
|----|---------|------------|-----|
| C1 | 1.9 fleet_diversity | Train models with genuinely different feature sets or loss functions | Current fleet has zero diversity |
| C2 | 5.5 orchestration | DAG visualization and explicit dependency graph | 57 CFs with implicit deps are unmaintainable |
| C3 | 1.7 retraining | Auto-retrain when staleness exceeds threshold (not just remind) | Eliminates manual retrain cadence |
| C4 | 6.2 grading | Real-time/streaming grading for faster feedback | Currently grades next-day only |
| C5 | 8.4 pre_commit | CI enforcement of pre-commit hooks (GitHub Actions) | Local-only hooks get skipped |

### Tier 4: Nice to Have

| ID | Keyword | Improvement | Why |
|----|---------|------------|-----|
| D1 | 3.8 pick_angles | Auto-update HR percentages in angle templates from live data | Prevents stale messaging |
| D2 | 4.8 ultra_bets | Cross-season validation of ultra criteria | Backtest N=26 likely overfitting |
| D3 | 2.5 brier_calibration | Use Brier score in decay detection or model comparison | Currently computed but unused |
| D4 | 8.7 cost_management | Per-phase cost attribution dashboard | Understand where money goes |
| D5 | 5.3 analytics | Fix win_flag computation (always FALSE) | Enables win/loss-based analysis |
| D6 | 8.9 env_var_management | Central config service or secret manager | Prevents env var drift |
| D7 | 1.10 experiment | Auto-verdict from experiment harness feeds back into training | Closes experiment loop |
| D8 | 7.5 slack_alerting | Add PagerDuty/escalation for CRITICAL alerts | Currently Slack-only |
| D9 | 3.1 signal_registry | Clean up 80+ commented-out dead signals from registry.py | Code hygiene |
| D10 | 8.1 cloud_run | Canary/blue-green deploy for prediction-worker | Reduces deployment risk |

---

## Decision Framework

When prioritizing, consider:

1. **Revenue impact** — Does it prevent losing bets or increase winning ones?
2. **Reliability impact** — Does it prevent silent failures or data loss?
3. **Maintenance burden** — Does it reduce manual work or prevent recurring issues?
4. **Blast radius** — How bad if it goes wrong?
5. **Dependencies** — Does it unblock other improvements?

---

## Questions for Agent Review

1. What order should we tackle these improvements?
2. Are there dependencies between items that force a specific sequence?
3. Are there any improvements missing from this list?
4. Which items should we explicitly NOT do (over-engineering risk)?
5. What's the minimum viable improvement set for the biggest impact?
