# Claude Code Instructions

Instructions for Claude Code sessions on the NBA Stats Scraper project.

## Mission

Build profitable NBA player props prediction system (55%+ accuracy on over/under bets).

## Architecture Overview

**Six-Phase Data Pipeline:**
1. **Phase 1 - Scrapers**: 30+ scrapers → Cloud Storage JSON
2. **Phase 2 - Raw Processing**: JSON → BigQuery raw tables
3. **Phase 3 - Analytics**: Player/team game summaries
4. **Phase 4 - Precompute**: Performance aggregates, matchup history
5. **Phase 5 - Predictions**: ML models (CatBoost V12)
6. **Phase 6 - Publishing**: JSON exports to GCS API

Phases connected via **Pub/Sub event triggers**. Daily workflow starts ~6 AM ET.

### Phase Triggering

- **Phase 2 → 3:** Direct Pub/Sub (`nba-phase3-analytics-sub`), backup Cloud Scheduler 10:30 AM ET. No orchestrator.
- **Phase 3 → 4:** Orchestrator (quality gates → `nba-phase4-trigger`)
- **Phase 4 → 5:** Orchestrator (gates Phase 5 behind Phase 4)
- **Phase 5 → 6:** Orchestrator (triggers publishing)

## Core Principles

- **Data quality first** - Discovery queries before assumptions
- **Zero tolerance for defaults** - Never predict with fabricated feature values
- **Always filter partitions** - Massive BigQuery performance gains
- **Batch over streaming** - Avoid 90-min DML locks
- **One small thing at a time** - With comprehensive testing

## Session Philosophy

1. **Understand root causes, not just symptoms** — Investigate WHY bugs happen
2. **Prevent recurrence** — Add validation, tests, or automation
3. **Use agents liberally** — Spawn multiple Task agents in parallel
4. **Keep documentation updated** — Update handoff docs and runbooks
5. **Fix the system, not just the code** — Schema issues need schema validation

## Quick Start [Keyword: START]

```bash
/daily-steering                             # 1. Morning steering report
/validate-daily                             # 2. Run daily validation
./bin/check-deployment-drift.sh --verbose   # 3. Check deployment drift
/best-bets-config                           # 4. Review best bets thresholds/models/signals
```

## Using Agents [Keyword: AGENTS]

| Agent Type | Use Case | Example |
|------------|----------|---------|
| `Explore` | Research, find patterns | "Find all BigQuery single-row writes" |
| `general-purpose` | Fix bugs, implement features | "Fix the NoneType error in metrics_utils.py" |
| `Bash` | Git, gcloud, bq queries | Direct commands |

**Best Practice:** Use Explore for research first, then general-purpose for fixes.

## Project Structure

```
nba-stats-scraper/
├── predictions/           # Phase 5 - Prediction worker and coordinator
├── data_processors/       # Phase 2-4 data processing
│   ├── raw/              # Phase 2
│   ├── analytics/        # Phase 3
│   └── precompute/       # Phase 4
├── scrapers/             # Phase 1 - Data scrapers
├── orchestration/        # Phase transition orchestrators
├── shared/               # Shared utilities
├── bin/                  # Scripts and tools
├── schemas/              # BigQuery schema definitions
└── docs/                 # Documentation
```

## Data Sources [Keyword: SOURCES]

**Full Inventory:** `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md`

| Data Type | Primary Source | BigQuery Table |
|-----------|----------------|----------------|
| Injuries | `nbac_injury_report` | `nba_raw.nbac_injury_report` |
| Schedule | `nbac_schedule` | `nba_raw.nbac_schedule` |
| Player Stats | `nbac_gamebook_player_stats` | `nba_raw.nbac_gamebook_player_stats` |
| Betting Lines | `odds_api_*` | `nba_raw.odds_api_*` |
| Play-by-Play | `nbac_play_by_play` | `nba_raw.nbac_play_by_play` |

**Naming:** `nbac_*` = NBA.com, `bdl_*` = Ball Don't Lie (disabled), `odds_api_*` = The Odds API, `bettingpros_*` = BettingPros

## ML Model [Keyword: MODEL]

| Property | Value |
|----------|-------|
| System ID | `catboost_v12` (interim champion since 2026-02-23) |
| Previous Champion | `catboost_v9` (BLOCKED — 37.4% Feb HR, demoted Session 332) |
| Production Model | `catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149` |
| Training | 2025-11-02 to 2026-01-31 (**27 days stale as of Feb 27**) |
| Edge 3+ HR | 48.7% Feb live — BELOW BREAKEVEN |
| Status | ALL PRODUCTION MODELS DEGRADING — shadow fleet rebuilding (Session 350) |

**15 enabled shadow models** (12 CatBoost + 2 LightGBM + 1 V16) + 1 production. Worker supports LightGBM (Session 350) and V16 feature set (Session 356). Session 364: Fixed Firestore duplicate path (`_mode` not set on duplicate Pub/Sub), deployed auto-retry-processor (34 days stale, hitting wrong endpoint).

**Session 365 filter improvements (deployed):**
- **Model HR-weighted selection**: Per-model rolling 14d HR scales edge in per-player ROW_NUMBER. V9 at 44% gets 0.80x weight, 55%+ models get 1.0x. Prevents stale models from winning selection.
- **AWAY block expanded**: v9 AWAY now blocked (48.1% HR, N=449). Was only v12_noveg.
- **Multi-model blacklist**: Default changed to aggregate across ALL models (was champion-only). Players escaping via non-champion models now caught.

**February decline diagnosis (Session 348):** Best bets HR dropped from 73.1% (Jan) to 60.5% (Feb). Root causes: (1) OVER predictions collapsed 80%→58%, specifically Starters OVER 90%→33%, (2) full-vegas architecture failing at 54.5% vs noveg at 100% (N=6), (3) edge quality weakened from 7.2→5.4, (4) all models past 21-day shelf life. **Session 370 adversarial validation:** `usage_spike_score` explains 47% of Dec-Jan → Feb drift (collapsed 1.14→0.28). AUC=0.99 — near-perfect discrimination. Seasonal pattern as rotations stabilize.

**Live fleet health (Feb 27):**
- `v9_low_vegas_train0106_0205`: 51.9% HR 7d (N=52) — best model, barely below breakeven
- **`v16_noveg_train1201_0215`**: NEW (Session 357) — 70.83% backtest HR edge 3+ (OVER 88.9%, UNDER 60.0%). First predictions expected Feb 28.
- Session 343-344 models (q55_tw, q55, q57, v9_lv): Accumulating data
- Session 348 `q55_tw_train0105_0215` (68% backtest): Accumulating data
- **LightGBM** (2 models, 67-73% backtest): Deployed, accumulating data
- `v12_noveg_q43_train0104_0215`: DISABLED Session 350 — 14.8% HR live (catastrophic UNDER)

**LightGBM models (Session 350):** First alternative framework. Genuine feature diversity from CatBoost (`points_avg_season` dominates vs CatBoost's `line_vs_season_avg`). Precision models — fewer edge 3+ picks but higher quality.
- `lgbm_v12_noveg_train1102_0209`: 73.3% backtest HR, OVER 75%, UNDER 71%
- `lgbm_v12_noveg_train1201_0209`: 67.7% backtest HR, OVER 80%, UNDER 62%

**V16 model (Session 357):** Adds 2 deviation-from-line features (`over_rate_last_10`, `margin_vs_line_avg_last_5`) to V12_NOVEG base. 52 features total. Feature store schema: `v2_57features` (57 columns). Backfilled Dec 1 → Feb 27.
- `catboost_v16_noveg_train1201_0215`: 70.83% backtest HR edge 3+, OVER 88.9%, UNDER 60.0%

**Vegas weight experiment (Session 359):** Systematic 12-experiment matrix testing vegas influence. Key finding: **optimal vegas weight is 0.25x** (not 1.0x default). At 0.25x, vegas_points_line drops from #1 feature (22.8%) to #8 (2.7%), `points_avg_season` dominates (28.1%), UNDER HR improves from 50% → 60%. New shadow models:
- `catboost_v12_train1201_0215`: V12 vegas=0.25 weight, **75.0% HR edge 3+ (OVER 100%, UNDER 60.0%)**
- `catboost_v16_noveg_rec14_train1201_0215`: V16 noveg + 14-day recency, **69.0% HR edge 3+ (OVER 81.8%, UNDER 61.1%)** — best UNDER model

**Session 365 promising experiments (need more eval data):**
- **Tier-weighted (v12_noveg_tierwt_vw025)**: 70.73% HR (N=41), OVER 90.9%, UNDER 63.3%. Star=2.0, starter=1.2, role=0.8, bench=0.5. Failed only sample size.
- **V13 shooting (v13_vw025)**: 65.79% HR (N=38), OVER 84.6%, UNDER 56.0%. MAE improved to 5.08. 6 new shooting features add signal.
- **60d window (v12_noveg_60d_vw025)**: 60.87% HR (N=23). Promising but tiny sample.

**CRITICAL:** Use edge >= 3 filter. 73% of predictions have edge < 3 and lose money.

### Model Governance

**NEVER deploy a retrained model without passing ALL governance gates.**
**NEVER deploy a model without explicit user approval at each step.**
**Training is NOT deploying.** Use `/model-experiment` to train. Deployment requires separate user sign-off.

**Governance gates** (enforced in `quick_retrain.py`):
1. Duplicate check: blocks if same training dates exist
2. Vegas bias: pred_vs_vegas within +/- 1.5
3. High-edge (3+) hit rate >= 60%
4. Sample size >= 50 graded edge 3+ bets
5. No critical tier bias (> +/- 5 points)
6. MAE improvement vs baseline

**Key lessons:**
- Lower MAE does NOT mean better betting (4.12 MAE crashed HR to 51.2% due to UNDER bias)
- **NEVER use in-sample predictions as training data for a second model** (88% apparent vs 56% real HR)
- **Edge Classifier (Model 2) does not add value** (AUC < 0.50)

**Process:** Train → Gates pass → Upload to GCS → Register → Shadow 2+ days → Promote
**Post-retrain verification:** `quick_retrain.py` auto-verifies registration + warns on duplicate families (Session 334). Run `python bin/validation/validate_model_registry.py` after any manual registry edits.
**Rollback:** `gcloud run services update prediction-worker --region=us-west2 --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://..."`

### Model Registry & Retraining

```bash
./bin/model-registry.sh list|production|validate|sync
./bin/retrain.sh --promote              # Full retrain + promote
./bin/retrain.sh --dry-run              # Preview
```

**After updating `manifest.json` in GCS, run `./bin/model-registry.sh sync`.**

7-day cadence, 42-day rolling window. `retrain-reminder` CF runs Mon 9 AM ET (Slack + SMS). Urgency: ROUTINE (7-10d), OVERDUE (11-14d), URGENT (15d+).

**Dead ends (don't revisit):** Grow policy, CHAOS+quantile, residual mode, two-stage pipeline, Edge Classifier, Huber loss (47.4% HR), recency weighting (33.3%), lines-only training (20%), min-PPG filter (33.3%), 96-day window, Q43+Vegas (20% HR edge 5+, catastrophic UNDER compounding), RSM 0.5 with v9_low_vegas (hurts HR), 87-day training window (too much old data dilutes signal), min-data-in-leaf 25/50 (kills feature diversity, top 2 features = 64-68%), Q60 quantile (generates OVER volume but not profitably — 50% OVER HR), health gate on raw model HR (blocked profitable multi-model filtered best bets — removed Session 347), blowout_recovery signal (50% HR 7-7 in best bets, 25% in Feb — disabled Session 349), no-vegas binary classifier (AUC 0.507 = random — features predict points not over/under), tier models on 42-day window (star: 244, starter: 933 — insufficient per-tier samples), starter tier model Dec 1 window (1/6 gates, Vegas bias +2.49, can't predict outside trained tier), noveg Q43 on fresh data (14.8% HR live — 0/54 UNDER, catastrophic compounding confirmed again), LightGBM Q55 (non-deterministic — swung 62%→52% between runs, MAE variants are stable), V16 Q55 quantile (53.3% HR — worse than MAE on same window, confirmed Session 365: 48.9% HR), V16 wide eval Feb 1-27 (55.9% — Feb degradation dilutes signal), V16 Nov 1 training start (92-day window too broad — 55.9% HR), anchor-line training (predict actual-prop_line: collapses feature importance, only 9 edge 3+ picks, UNDER 33.3%), V16 deviation features alone (61.5% vs V12's 73.7% — hurt quality, only work combined with recency), recency on well-calibrated models (V12 vegas=0.25 went 75%→59% with recency — don't add recency to models already performing well), vegas weight < 0.25 (0.1x UNDER 54.5% — worse than 0.25x at 60%), V17 opportunity risk features (blowout_minutes_risk, minutes_volatility_last_10, opponent_pace_mismatch — all <1% feature importance, 56.7% HR noveg, 58.1% with vegas=0.25 vs V12's 75% — model doesn't find signal in opportunity risk), LightGBM+vw025 (54.9% HR, N=51 — UNDER 50% below breakeven, Session 365), category weight dampening (composite=0.25/derived=0.25 — +4.2pp on current season seed 42 but fails cross-season at 61.4% vs 66.7%, increases variance 3.0pp vs 2.2pp StdDev, NOT significant across 5 seeds, Session 369), W6+dampening stacking (dampening hurts tight windows — 70-73% vs 75.4% baseline, Session 369), edge calibration isotonic regression (flat edge→P(win) at raw prediction level ~51% everywhere — filter stack does real selection, Session 370), derived feature D11 expected_scoring_possessions (amplifies usage_spike_score drift — hurt model 62.8% vs 68.6%, Session 370), derived feature D12 rolling_zscore_5v10 (<1% importance, no signal, Session 370), timezone proxy C9 (arena_timezone ALL NULL — no data), referee pace C10 (nbac_referee_game_assignments empty for 2025-26 — scraper pipeline broken), CatBoost uncertainty/virtual ensembles (Q1-Q4 gap reversed on 4/5 seeds — seed 42 was noise, Session 370), usage_spike_score exclusion (66.2% HR vs 68.6% baseline — model already handles drift internally, Session 370), usage_spike_score downweight=0.1 (65.3% vs 68.6% — same conclusion, Session 370), tier weights star=2.0/starter=1.2/role=0.8/bench=0.3 (ZERO effect — identical HR to baseline on same window across all 5 seeds, Session 370).

### Cross-Model Monitoring

3 layers prevent shadow models from silently failing:
1. `reconcile-yesterday` Phase 9 — next-day gap detection
2. `validate-daily` Phase 0.486 — same-day early warning
3. Pipeline canary auto-heal — automated every 30 min

## Breakout Classifier [Keyword: BREAKOUT]

**Status:** Shadow mode, V2 (AUC 0.5708). Not production-ready. Always use `ml/features/breakout_features.py` for feature computation.

## Deployment [Keyword: DEPLOY]

### Auto-Deploy via Cloud Build

**Push to main auto-deploys changed services.** Each trigger also watches `shared/`.

**Cloud Run Services:** prediction-coordinator, prediction-worker, nba-phase3-analytics-processors, nba-phase4-precompute-processors, nba-phase2-raw-processors, nba-scrapers, nba-grading-service

**Cloud Functions (auto-deploy via `cloudbuild-functions.yaml`):** phase5b-grading, phase6-export, grading-gap-detector, phase3/4/5-to-next orchestrators, enrichment-trigger, daily-health-check, transition-monitor, pipeline-health-summary, nba-grading-alerts, live-freshness-monitor, self-heal-predictions, grading-readiness-monitor, post-grading-export, decay-detection (11 AM ET), retrain-reminder (Mon 9 AM ET), validation-runner

**NOT auto-deployed (manual only):** auto-retry-processor

### CRITICAL: Always deploy from repo root
```bash
./bin/deploy-service.sh SERVICE           # Standard (8-10 min)
./bin/hot-deploy.sh SERVICE               # Hot-deploy (5-6 min)
./bin/check-deployment-drift.sh --verbose # Check drift
```

## Key Tables [Keyword: TABLES]

| Table | Notes |
|-------|-------|
| `prediction_accuracy` | **All grading queries** (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use |
| `nba_reference.nba_schedule` | Clean view, use for queries |
| `nba_raw.nbac_schedule` | Requires partition filter |
| `model_performance_daily` | Daily rolling HR/state per model. Auto-populated by post_grading_export |
| `signal_health_daily` | Signal regime (HOT/NORMAL/COLD) per timeframe |
| `signal_combo_registry` | 11 SYNERGISTIC combos |

**Game Status:** 1=Scheduled, 2=In Progress, 3=Final

## ML Feature Quality [Keyword: QUALITY]

**Zero tolerance:** Predictions blocked for ANY player with `default_feature_count > 0`. Three enforcement layers: Phase 4 quality_scorer, coordinator quality_gate (`HARD_FLOOR_MAX_DEFAULTS = 0`), worker defense-in-depth.

**Impact:** Coverage drops from ~180 to ~75 predictions per game day. Intentional — never relax the tolerance.

**37 base features** across 5 categories: matchup, player_history, team_context, vegas, game_context. Each has `feature_N_quality` and `feature_N_source` columns. **V16 adds 2 features** (55: `over_rate_last_10`, 56: `margin_vs_line_avg_last_5`) — feature store schema is `v2_57features` (57 columns total).

**CRITICAL:** When querying `ml_feature_store_v2`, use `feature_N_value` columns, NOT `features[OFFSET(N)]`. Array column is deprecated. Use `build_feature_array_from_columns(row)` from `shared/ml/feature_contract.py` for training code.

**See:** `docs/08-projects/current/feature-quality-visibility/`, `docs/08-projects/current/zero-tolerance-defaults/`

## Essential Queries [Keyword: QUERIES]

```sql
-- Check recent predictions
SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1

-- Check today's signal
SELECT daily_signal, pct_over, high_edge_picks
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v12'

-- Check games status
SELECT game_id, away_team_tricode, home_team_tricode, game_status
FROM nba_reference.nba_schedule WHERE game_date = CURRENT_DATE()

-- Check zero tolerance impact
SELECT game_date,
       COUNTIF(default_feature_count = 0) as clean_players,
       COUNTIF(default_feature_count > 0) as blocked_players
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1 ORDER BY 1 DESC;
```

**Full query library:** `docs/02-operations/useful-queries.md`

## Common Issues [Keyword: ISSUES]

| Issue | Fix |
|-------|-----|
| Deployment drift | `./bin/deploy-service.sh SERVICE` |
| **Env var drift** | **NEVER use `--set-env-vars` (wipes all). ALWAYS `--update-env-vars`** |
| Vegas line coverage <40% | NORMAL — threshold is 45% |
| Grading coverage 60-80% | NORMAL — NO_PROP_LINE excluded. Expect 95%+ of gradable. |
| Schema mismatch | `python .pre-commit-hooks/validate_schema_fields.py` |
| Partition filter 400 | Add `WHERE game_date >= ...` |
| Silent BQ write 0 records | Use `{project}.{dataset}.{table}` pattern |
| Cloud Function imports | Run symlink validation, fix shared/ paths |
| Stale batch blocks `/start` | Check `/status`, then `/reset` |
| `features[OFFSET(N)]` | **Use `feature_N_value` columns instead** |
| BDL scraper 0 records | EXPECTED — BDL intentionally disabled |
| Orchestrator not triggering P3 | NOT a bug — Phase 3 uses direct Pub/Sub |
| Docker cache stale deploy | `./bin/hot-deploy.sh SERVICE` |
| Coordinator backfill timeout | Increase timeout to 900s; player loader exceeds 540s on 11+ game days |
| Phase 3 partial game processing | Quality check filters invalid teams (0 pts/FGA) instead of rejecting all. Slack alert fires + canary auto-heals. |
| Team boxscore zeros for in-progress games | EXPECTED — scraper writes placeholders. Filtered at processing time (Session 302). |
| Cloud Function env vars | Use `gcloud functions describe FUNC`, not `gcloud run services describe`. CFs are NOT Cloud Run services. |
| **minScale drift on deploy** | **Deploy scripts now set `--min-instances` explicitly. Orchestrators + prediction services = 1, others = 0 (Session 338).** |
| **Phase 6 trigger message format** | Use `{"export_types": ["signal-best-bets"], "target_date": "2026-02-24"}` — NOT `game_date`. See `phase6_export/main.py`. |
| **SQL escape `\_` in Python** | BigQuery LIKE doesn't need backslash-escaping underscores. Use `%_q4%` not `%\\_q4%`. |
| **Trends page stale data** | `trends-tonight` was missing from `phase6-hourly-trends` scheduler. Fixed Session 349. If stale again, check scheduler export_types include `trends-tonight`. |
| **auto-retry-processor stale** | No Cloud Build trigger — must deploy manually. Check with: `gcloud functions describe auto-retry-processor --region=us-west2 --format='value(updateTime)'` |

**Full troubleshooting:** `docs/02-operations/session-learnings.md`

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
- id: validate-schema-fields       # BigQuery schema alignment
- id: validate-python-syntax        # Syntax errors break CF deploys
- id: validate-deploy-safety        # Detects dangerous --set-env-vars
- id: validate-dockerfile-imports   # Missing COPY dirs
- id: validate-pipeline-patterns    # Invalid enum, processor name gaps
- id: validate-model-references    # Hardcoded catboost_v* system_ids (Session 334)
```

### Cloud Function Deploy Patterns
- **Use `rsync -aL`** not `cp -r` when copying shared/ (cp misses symlinks)
- **Gen2 entry point is immutable** — add `main = actual_func` alias at end of main.py
- **Reporter functions MUST return 200** — scheduler treats non-200 as failure
- **No CLI tools in CF runtime** — use Python client libraries, not gcloud/gsutil/bq

### Batching Pattern
```python
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches
```

## Monitoring [Keyword: MONITOR]

```bash
python bin/monitoring/deployment_drift_alerter.py   # Deployment drift (auto: every 2h)
python bin/monitoring/pipeline_canary_queries.py     # Pipeline canaries (auto: every 30min)
python bin/monitoring/analyze_healing_patterns.py    # Self-healing audit (auto: every 15min)
python bin/monitoring/grading_gap_detector.py        # Grading gaps (auto: daily 9 AM ET)
```

- Auto-heals stalled batches (>90% complete, stalled 15+ min)
- Quality gates block bad data at Phase 2→3 transition
- Decay detection: `decay-detection` CF daily 11 AM ET, state machine HEALTHY→WATCH→DEGRADING→BLOCKED
- Meta-monitoring: `daily-health-check` CF verifies freshness of `model_performance_daily`, `signal_health_daily`, and `phase_completions`
- Model registry: `python bin/validation/validate_model_registry.py` — checks duplicates, orphans, GCS consistency
- Workflow health: `python bin/validation/validate_workflow_dependencies.py` — detects workflows monitoring disabled scrapers

**Slack:** `#deployment-alerts` (2h), `#canary-alerts` (30min), `#nba-alerts` (self-healing, grading, decay)

## Signal System [Keyword: SIGNALS]

**12 active signals** (21 removed). **Edge-first architecture** — signals are for filtering and annotation, not selection.

**Best Bets:** `edge 3+ → negative filters → signal count ≥ 3 → signal density (bypass edge ≥7) → rank by edge` (Session 370: signal floor raised 2→3, 74.5% HR backfill)

**Negative Filters:**
1. Player blacklist: `<40% HR on 8+ edge-3+ picks`
2. Avoid familiar: `6+ games vs opponent`
3. Edge floor: `edge < 3.0` (Session 352: lowered from 5.0 — edge 3-4 is best V12 band during degradation)
4. **Model-direction affinity blocking** (Session 343): Blocks model+direction+edge combos with HR < 45% on 15+ picks. V9 UNDER 5+ = 30.7% HR (N=88) — blocked. V9_low_vegas has separate affinity group (62.5% UNDER — protected).
5. Feature quality floor: `quality < 85` (24.0% HR)
6. Bench UNDER block: `UNDER + line < 12` (35.1% HR)
7. UNDER + line jumped 2+: `prop_line_delta >= 2.0` (38.2% HR)
8. UNDER + line dropped 2+: `prop_line_delta <= -2.0` (35.2% HR)
9. Away block: `v12_noveg/v9 family + AWAY game` (43-48% HR vs 57-59% HOME, Session 365)
10. Signal density: `base-only signals → skip unless edge ≥ 7.0` (Session 352 bypass for extreme edge)

### Active Signals

| Signal | Direction | HR | Status |
|--------|-----------|-----|--------|
| `model_health` | BOTH | 52.6% | PRODUCTION |
| `high_edge` | BOTH | 66.7% | PRODUCTION |
| `edge_spread_optimal` | BOTH | 67.2% | PRODUCTION |
| `combo_he_ms` | OVER | 94.9% | PRODUCTION |
| `combo_3way` | OVER | 95.5% | PRODUCTION |
| `bench_under` | UNDER | 76.9% | PRODUCTION |
| `3pt_bounce` | OVER | 74.9% | CONDITIONAL |
| `b2b_fatigue_under` | UNDER | 85.7% | CONDITIONAL |
| `rest_advantage_2d` | BOTH | 64.8% | CONDITIONAL (capped week 15) |
| `prop_line_drop_over` | OVER | 71.6% | PRODUCTION |
| `book_disagreement` | BOTH | 93.0% | WATCH |
| `blowout_recovery` | OVER | 50.0% | DISABLED (Session 349) |
| `ft_rate_bench_over` | OVER | 72.5% | WATCH |

**Pick Angles:** Each pick includes `pick_angles` — human-readable reasoning. See `ml/signals/pick_angle_builder.py`.

## Ultra Bets [Keyword: ULTRA]

High-confidence classification layer on best bets. Internal-only (stripped from public JSON until live-validated).

**Live Performance (Jan 9 - Feb 21):** 25-8 (75.8% HR), 33% of picks, 51% of profit. Ultra OVER: **17-2 (89.5%)**. Ultra UNDER: 8-6 (57.1%).

| Criteria | Live HR | Status |
|----------|---------|--------|
| `v12_edge_6plus` | 95.2% (20-1) | VALIDATED |
| `v12_over_edge_5plus` | 89.5% (17-2) | VALIDATED |
| `v12_edge_4_5plus` | 75.8% (25-8) | VALIDATED |

**Architecture:** `ml/signals/ultra_bets.py` → `ultra_tier` + `ultra_criteria` fields → BQ (internal), admin JSON (full), public JSON (stripped).

**Public exposure gate:** Ultra OVER N >= 50 and HR >= 80%. Currently 17-2, need ~31 more.

## Multi-Model Best Bets [Keyword: MULTIMODEL]

2-system consolidated architecture. SignalBestBetsExporter + SignalAnnotator bridge share same aggregator, blacklist, and filters. Algorithm version: `v314_consolidated`.

**Dynamic model discovery:** 6 families (`v9_mae`, `v12_mae`, `v9_q43`, `v9_q45`, `v12_q43`, `v12_q45`). `discover_models()` queries BQ, classifies by pattern — survives retrains automatically.

**CRITICAL:** V9+V12 agreement is ANTI-correlated with winning. `diversity_mult` removed.

**Consensus bonus:** `agreement_base = 0.05 * (n_agreeing - 2)` + `quantile_bonus = 0.10 if UNDER + all quantile agree`. Max 0.15.

**Key files:** `ml/signals/cross_model_scorer.py`, `shared/config/cross_model_subsets.py`
**See:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`

## GCP Resources

| Resource | Value |
|----------|-------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |
| Datasets | nba_predictions, nba_analytics, nba_raw, nba_orchestration |
| GCS API Bucket | `gs://nba-props-platform-api/v1/` |
| Frontend Domain | `playerprops.io` |

**Key API Endpoints** (daily, 6 AM ET): `v1/status.json`, `v1/systems/signal-health.json`, `v1/systems/model-health.json`, `v1/signal-best-bets/{date}.json`

## Conventions

### Commit Messages
```
type: Short description

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Style
- Python 3.11+, type hints for public APIs, docstrings for classes and complex functions

## Documentation [Keyword: DOC, DOCS]

- **Session work:** `docs/08-projects/current/<project-name>/`
- **Handoffs:** `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md` (template: `HANDOFF-TEMPLATE.md`)
- **Troubleshooting:** `docs/02-operations/troubleshooting-matrix.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
- **System features:** `docs/02-operations/system-features.md`
- **Architecture:** `docs/01-architecture/`
- **Runbooks:** `docs/02-operations/runbooks/`

## End of Session [Keyword: ENDSESSION]

```bash
git push origin main                                                          # 1. Push (auto-deploys)
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5   # 2. Verify builds
./bin/check-deployment-drift.sh --verbose                                     # 3. Check drift
./bin/model-registry.sh sync                                                  # 4. If model changes
# 5. Create handoff document
```

## Feature References

See `docs/02-operations/system-features.md` for: Heartbeat System, Evening Analytics, Early Predictions, Model Attribution, Signal System.
