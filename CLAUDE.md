# Claude Code Instructions

Instructions for Claude Code sessions on the NBA Stats Scraper project.

## Mission

Build profitable NBA player props prediction system (55%+ accuracy on over/under bets).

## Architecture Overview

**Six-Phase Data Pipeline:**
1. **Phase 1 - Scrapers**: 40+ scrapers → Cloud Storage JSON
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
│   ├── projections/     # External projection sources (NumberFire, FantasyPros, DFF, Dimers)
│   └── external/        # External analytics (TeamRankings, Hashtag, RotoWire, Covers, VSiN, NBA Tracking)
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
| Projections | `numberfire_projections`, `fantasypros_projections`, `dailyfantasyfuel_projections`, `dimers_projections` | `nba_raw.numberfire_projections`, etc. |
| External Analytics | `teamrankings_pace`, `hashtagbasketball_dvp`, `rotowire_lineups`, `covers_referee_stats`, `nba_tracking_stats`, `vsin_betting_splits` | `nba_raw.teamrankings_pace`, etc. |

**Naming:** `nbac_*` = NBA.com, `bdl_*` = Ball Don't Lie (disabled), `odds_api_*` = The Odds API, `bettingpros_*` = BettingPros, `numberfire_*`/`fantasypros_*`/`dailyfantasyfuel_*`/`dimers_*` = Projection sources, `teamrankings_*`/`hashtagbasketball_*`/`rotowire_*`/`covers_*`/`vsin_*`/`nba_tracking_*` = External analytics

## ML Model [Keyword: MODEL]

**Fleet:** 10+ enabled shadow models (CatBoost, LightGBM, XGBoost). No single production champion — best bets aggregates across all enabled models per player.

**Key settings:**
- V12_NOVEG is the strongest base feature set. Adding features consistently hurts.
- Optimal vegas weight: 0.15-0.25x. 56-day training window is sweet spot.
- Edge >= 3 filter is critical — 73% of predictions below edge 3 lose money.

### Retraining (Session 458)

**Retrain every 7 days.** Walk-forward across 2 seasons proves this is the single highest-ROI operation.
- **85% HR at edge 3+ validated** — audited for leakage (5 seeds, naive baselines, feature importance, permutation test). True skill: +27.5pp above structural baseline.
- **`weekly-retrain` CF fires every Monday 5 AM ET** — auto-retrains all enabled families, 56-day rolling window, governance gates enforced
- **`./bin/retrain.sh --all --enable`** — manual equivalent for ad-hoc retraining
- `retrain-reminder` CF alerts every Monday at 9 AM ET — backup alert if auto-retrain fails
- Stale models (10+ days) become confidently wrong: high edge but low HR
- Model needs ~4 months in-season data for peak accuracy (85%+ HR at edge 3+ by March)
- Walk-forward details: `docs/08-projects/current/model-management/MONTHLY-RETRAINING.md`

### Model Governance

**NEVER deploy a retrained model without passing ALL governance gates.**
**NEVER deploy a model without explicit user approval at each step.**
**Training is NOT deploying.** Use `/model-experiment` to train. Deployment requires separate user sign-off.

**Governance gates** (enforced in `quick_retrain.py`): Duplicate check, Vegas bias ±1.5, HR >= 60% at edge 3+, N >= 50 graded, no tier bias > ±5, MAE improvement.

**Process:** Train → Gates pass → Upload to GCS → Register → Shadow 2+ days → Promote
**Registry:** `./bin/model-registry.sh list|production|validate|sync`. After GCS manifest changes, run `sync`.
**Deactivation:** `python bin/deactivate_model.py MODEL_ID [--dry-run] [--re-export]`
**Rollback:** `gcloud run services update prediction-worker --region=us-west2 --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://..."`

**Dead ends:** See `docs/06-reference/model-dead-ends.md` — 80+ tested approaches that don't work.

### Cross-Model Monitoring

10 layers prevent shadow models from silently failing. Key ones: model sanity guard (>95% same-direction blocked), disabled model filter in exporter, decay state machine (HEALTHY→WATCH→DEGRADING→BLOCKED), filter dominance warnings, registry consistency checks.

**Filter audit:** `SELECT * FROM best_bets_filter_audit WHERE game_date >= CURRENT_DATE() - 7`
**Auto-disable:** BLOCKED models are auto-disabled by `decay_detection` CF (Session 389). Requires `AUTO_DISABLE_ENABLED=true` env var. Safety floor: 3+ models must remain enabled.

## Breakout Classifier [Keyword: BREAKOUT]

**Status:** Shadow mode, V2 (AUC 0.5708). Not production-ready. Always use `ml/features/breakout_features.py` for feature computation.

## Deployment [Keyword: DEPLOY]

### Auto-Deploy via Cloud Build

**Push to main auto-deploys changed services.** Each trigger also watches `shared/`.

**Cloud Run Services:** prediction-coordinator, prediction-worker, nba-phase3-analytics-processors, nba-phase4-precompute-processors, nba-phase2-raw-processors, nba-scrapers, nba-grading-service

**Cloud Functions (auto-deploy via `cloudbuild-functions.yaml`):** phase5b-grading, phase6-export, grading-gap-detector, phase3/4/5-to-next orchestrators, enrichment-trigger, daily-health-check, transition-monitor, pipeline-health-summary, nba-grading-alerts, live-freshness-monitor, self-heal-predictions, grading-readiness-monitor, post-grading-export, decay-detection (11 AM ET), retrain-reminder (Mon 9 AM ET), weekly-retrain (Mon 5 AM ET, 4GiB/1800s), validation-runner, filter-counterfactual-evaluator (11:30 AM ET), morning-deployment-check (6 AM ET), monthly-retrain (1st of month, DEPRECATED)

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
| `filter_counterfactual_daily` | Daily CF HR per negative filter. Auto-populated by filter-counterfactual-evaluator CF |
| `filter_overrides` | Runtime filter demotions (auto-demote system). Aggregator reads at export time |
| `best_bets_filtered_picks` | Picks blocked by filters, with graded actuals. Source for CF HR computation |
| `nba_raw.numberfire_projections` | NumberFire/FanDuel player projections (Session 401) |
| `nba_raw.fantasypros_projections` | FantasyPros consensus projections |
| `nba_raw.dailyfantasyfuel_projections` | DailyFantasyFuel projections |
| `nba_raw.dimers_projections` | Dimers projected points |
| `nba_raw.teamrankings_pace` | TeamRankings team pace ratings |
| `nba_raw.hashtagbasketball_dvp` | Hashtag Basketball defense-vs-position |
| `nba_raw.rotowire_lineups` | RotoWire expected lineups + minutes |
| `nba_raw.covers_referee_stats` | Covers referee O/U tendency stats |
| `nba_raw.nba_tracking_stats` | NBA.com player tracking/usage data |
| `nba_raw.vsin_betting_splits` | VSiN public betting percentages |
| `league_macro_daily` | Daily league macro trends — Vegas MAE, scoring env, edge availability, BB HR |
| `model_bb_candidates` | Per-model pipeline candidates with full provenance (45 cols). Partitioned by game_date |

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

-- Check league macro trends
SELECT game_date, vegas_mae_7d, model_mae_7d, mae_gap_7d, league_avg_ppg_7d, bb_hr_7d, market_regime
FROM nba_predictions.league_macro_daily
WHERE game_date >= CURRENT_DATE() - 7 ORDER BY game_date DESC;
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
| `features[OFFSET(N)]` | **Use `feature_N_value` columns instead** |
| BDL scraper 0 records | EXPECTED — BDL intentionally disabled |
| Orchestrator not triggering P3 | NOT a bug — Phase 3 uses direct Pub/Sub |
| Docker cache stale deploy | `./bin/hot-deploy.sh SERVICE` |
| Cloud Function env vars | Use `gcloud functions describe FUNC`, not `gcloud run services describe`. CFs are NOT Cloud Run services. |
| **Phase 6 trigger message format** | Use `{"export_types": ["signal-best-bets"], "target_date": "2026-02-24"}` — NOT `game_date`. See `phase6_export/main.py`. |
| **Worker requirements-lock.txt** | Worker Dockerfile uses `requirements-lock.txt`, NOT `requirements.txt`. Always update the lock file for dependency changes. |
| **Feature normalization mismatch** | Feature store values are normalized 0-1. Signal thresholds must match. Always check `feature_N_value` distributions before setting thresholds. |
| **Signal silently dead** | Signals can die when dependencies change. Check `signal_health_daily` for missing signals. Common: wrong threshold scale (raw vs 0-1), dead champion dependency. |
| **Disabled model still in best bets** | Use `python bin/deactivate_model.py MODEL_ID` — cascades through all systems. |
| **Auto-deploy cascade** | Push to main deploys ALL services from HEAD — keep code deployable. Session 388: docs commit deployed untested feature code. |
| **Quality scorer FEATURE_COUNT mismatch** | `quality_scorer.py` FEATURE_COUNT=54, `ml_feature_store_processor.py` FEATURE_COUNT=60. Truncate feature_sources before scoring. |
| **Scraper date=TODAY literal** | Session 402: ConfigMixin resolved `TODAY` to literal string, not actual date. Fixed: `resolve_today()` in scraper opts. |
| **NumberFire → FanDuel redirect** | Domain acquired by FanDuel. Scraper uses GraphQL API at `fdresearch-api.fanduel.com/graphql`. |
| **VSiN AJAX-loaded data** | VSiN data is server-rendered at `data.vsin.com`, not AJAX. Direct HTML parsing works. |
| **NBA Tracking stats.nba.com timeout** | Cloud IPs blocked. Install `nba_api` library (preferred path) or increase HTTP timeout to 120s with retry. |
| **CLV scheduler wrong target** | Evening CLV scheduler was targeting legacy `nba-phase1-scrapers`. Fixed to `nba-scrapers`. |
| **SQL escape `\_` in Python** | BigQuery LIKE doesn't need backslash-escaping underscores. Use `%_q4%` not `%\\_q4%`. |
| **Re-exports destroy picks** | FIXED Session 412. `signal_best_bets_picks` now uses scoped DELETE (only refreshed players). Published picks stay `signal_status='active'`. |
| **`win_flag` always FALSE** | `player_game_summary.win_flag` is FALSE for ALL teams/players. Use `plus_minus > 0` as win proxy. |
| **Gen2 CF scheduler URL mismatch** | Scheduler targeting Gen1 URL returns 500/INTERNAL. Update URI to `serviceConfig.uri` + add OIDC auth + IAM. Session 448. |
| **Scheduler DEADLINE_EXCEEDED** | Workflow scrapers (multi-source) need 1800s timeout, not 900s. Data still arrives despite timeout. Session 448. |

**Full troubleshooting:** `docs/02-operations/troubleshooting-matrix.md`, `docs/02-operations/session-learnings.md`

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
python bin/monitoring/signal_decay_monitor.py        # Signal decay/recovery (Session 411)
PYTHONPATH=. python ml/analysis/league_macro.py      # League macro trends (auto: post-grading)
```

- Auto-heals stalled batches (>90% complete, stalled 15+ min)
- Quality gates block bad data at Phase 2→3 transition
- Decay detection: `decay-detection` CF daily 11 AM ET, state machine HEALTHY→WATCH→DEGRADING→BLOCKED (models)
- Signal decay: `signal_decay_monitor.py` — detects signal DEGRADING/RECOVERED states, Slack alerts (Session 411)
- Meta-monitoring: `daily-health-check` CF verifies freshness of `model_performance_daily`, `signal_health_daily`, and `phase_completions`
- Model registry: `python bin/validation/validate_model_registry.py` — checks duplicates, orphans, GCS consistency
- Workflow health: `python bin/validation/validate_workflow_dependencies.py` — detects workflows monitoring disabled scrapers
- **Brier score calibration** (Session 399): `model_performance_daily` has `brier_score_7d/14d/30d`. Lower = better calibrated. Backfill: `PYTHONPATH=. python ml/analysis/model_performance.py --backfill --start 2025-11-02`
- **Filter auto-demote** (Session 432): `filter-counterfactual-evaluator` CF daily 11:30 AM ET. Computes CF HR per filter, auto-demotes to observation if CF HR >= 55% for 7 consecutive days (N >= 20). Max 2/run. Core filters excluded. Demotions in `filter_overrides` table, read by aggregator at export.

**Analysis tools:**
```bash
python bin/analysis/player_deep_dive.py PLAYER_LOOKUP [--seasons N] [--output PATH]  # 9-module player analysis
python bin/analysis/edge_calibration.py          # Edge vs HR calibration
python bin/analysis/model_correlation.py         # Inter-model agreement
```

**Slack:** `#deployment-alerts` (2h), `#canary-alerts` (30min), `#nba-alerts` (self-healing, grading, decay)

## Signal System [Keyword: SIGNALS]

**28 active signals + 27 shadow signals** (24 removed/disabled). **23 negative filters + 10 observation.**
**Full inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`

**Best Bets Pipeline:** `edge 3+ (or signal rescue) → negative filters → signal_count ≥ 3 → real_sc gate → rank by edge (OVER) or signal quality (UNDER)`

**Key concepts:**
- `real_sc` = non-base signal count. Base signals (model_health, high_edge, edge_spread_optimal, blowout_recovery, starter_under, blowout_risk_under) inflate SC to 3 with zero value. All SC gates use `real_sc`.
- **Signal rescue** (Session 398): Picks bypass edge floors via validated high-HR signals or 2+ real signals. Tags: `combo_3way`, `combo_he_ms`, `book_disagreement`, `sharp_book_lean_*`, `mean_reversion_under`, etc.
- **UNDER ranking** is signal-first (Session 400): UNDER edge is flat at 52-53% — meaningless for ranking. Weighted signal quality scores rank UNDER. 11 weighted UNDER signals in `UNDER_SIGNAL_WEIGHTS`.
- **Shadow signals** (Sessions 401-423): projection_consensus, predicted_pace, dvp_favorable, CLV, sharp_money, minutes_surge, hot_form, consistent_scorer, over_trend, usage_surge, scoring_momentum, career_matchup, minutes_load, blowout_risk, volatile_starter_under, downtrend_under, star_favorite_under, starter_away_overtrend_under — accumulating data.

**Top signals by HR:** `combo_3way` 95.5%, `combo_he_ms` 94.9%, `line_rising_over` 96.6%, `book_disagreement` 93.0%, `sharp_line_drop_under` 87.5%, `fast_pace_over` 81.5%

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

## Per-Model Best Bets Pipelines [Keyword: PIPELINES]

Per-model pipeline architecture (Session 445). Replaced winner-take-all with independent pipelines + pool-and-rank merge. Algorithm version: `v451_session451_filters`.

**How it works:**
1. Batch query ALL enabled models' predictions (1 BQ scan, no ROW_NUMBER dedup)
2. Shared context computed once: signal health, filters, combo registry, regime, blacklist
3. Per-model aggregator runs N times in `mode='per_model'` (skips team_cap, rescue_cap)
4. Pool ALL candidates, sort by `composite_score` DESC
5. First-occurrence player dedup + team cap (2/team) + volume cap (15/day) + rescue cap (40%)
6. Final picks written to `signal_best_bets_picks`

**Key differences from old consensus approach:**
- No `diversity_mult` or `consensus_bonus` — pure composite_score ranking
- All models compete equally; first-occurrence dedup in merge
- Signals evaluate per-model (gate on model-specific `recommendation`)
- Full provenance in `model_bb_candidates` BQ table (45 columns)
- `pipeline_agreement_count` tracked but NOT used for scoring (anti-correlated)

**Key files:** `ml/signals/per_model_pipeline.py`, `ml/signals/pipeline_merger.py`, `shared/config/cross_model_subsets.py`
**See:** `docs/08-projects/current/per-model-pipelines/00-ARCHITECTURE.md`

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
