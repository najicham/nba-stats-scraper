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
5. **Phase 5 - Predictions**: ML models (CatBoost V9)
6. **Phase 6 - Publishing**: JSON exports to GCS API

Phases connected via **Pub/Sub event triggers**. Daily workflow starts ~6 AM ET.

### Phase Triggering

- **Phase 2 → 3:** Direct Pub/Sub (`nba-phase3-analytics-sub`), backup Cloud Scheduler at 10:30 AM ET. No orchestrator needed (removed Session 205).
- **Phase 3 → 4:** Orchestrator FUNCTIONAL (quality gates, publishes to `nba-phase4-trigger`)
- **Phase 4 → 5:** Orchestrator FUNCTIONAL (gates Phase 5 behind Phase 4)
- **Phase 5 → 6:** Orchestrator FUNCTIONAL (triggers publishing)

## Core Principles

- **Data quality first** - Discovery queries before assumptions
- **Zero tolerance for defaults** - Never predict with fabricated feature values
- **Always filter partitions** - Massive BigQuery performance gains
- **Batch over streaming** - Avoid 90-min DML locks
- **One small thing at a time** - With comprehensive testing

## Session Philosophy

1. **Understand root causes, not just symptoms** - Investigate WHY bugs happen
2. **Prevent recurrence** - Add validation, tests, or automation
3. **Use agents liberally** - Spawn multiple Task agents in parallel
4. **Keep documentation updated** - Update handoff docs and runbooks
5. **Fix the system, not just the code** - Schema issues need schema validation

## Documentation Procedure [Keyword: DOC]

- **Location:** `docs/08-projects/current/<project-name>/`
- Use existing project directory if work relates to ongoing project
- Create new subdirectory for new projects/investigations
- **Shorthand:** "doc this" or "use doc procedure" triggers this pattern

## Quick Start [Keyword: START]

```bash
ls -la docs/09-handoff/ | tail -5          # 1. Read latest handoff
/validate-daily                             # 2. Run daily validation
./bin/check-deployment-drift.sh --verbose   # 3. Check deployment drift
```

## Monitoring & Self-Healing [Keyword: MONITOR]

```bash
python bin/monitoring/deployment_drift_alerter.py   # Deployment drift (auto: every 2h)
python bin/monitoring/pipeline_canary_queries.py     # Pipeline canaries (auto: every 30min)
python bin/monitoring/analyze_healing_patterns.py    # Self-healing audit (auto: every 15min)
python bin/monitoring/grading_gap_detector.py        # Grading gaps (auto: daily 9 AM ET)
```

- Auto-heals stalled batches (>90% complete, stalled 15+ min), tracks root cause
- Quality gates block bad data at Phase 2→3 transition (`shared.validation.phase2_quality_gate`)
- Grading gap detector checks gradable predictions only (excludes NO_PROP_LINE)

**Slack:** `#deployment-alerts` (2h), `#canary-alerts` (30min), `#nba-alerts` (self-healing, grading gaps)

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

## Data Sources Quick Reference [Keyword: SOURCES]

**Full Inventory:** See `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md`

| Data Type | Primary Source | BigQuery Table | Notes |
|-----------|----------------|----------------|-------|
| **Injuries** | `nbac_injury_report` (NBA.com) | `nba_raw.nbac_injury_report` | Official PDFs, 15-min updates |
| **Schedule** | `nbac_schedule` (NBA.com) | `nba_raw.nbac_schedule` | 100% coverage |
| **Player Stats** | `nbac_gamebook_player_stats` | `nba_raw.nbac_gamebook_player_stats` | Official stats |
| **Betting Lines** | `odds_api_*` (The Odds API) | `nba_raw.odds_api_*` | 10+ sportsbooks |
| **Play-by-Play** | `nbac_play_by_play` | `nba_raw.nbac_play_by_play` | Every possession |

**Naming:** `nbac_*` = NBA.com, `bdl_*` = Ball Don't Lie (disabled), `odds_api_*` = The Odds API, `bettingpros_*` = BettingPros

## ML Model - CatBoost V9 [Keyword: MODEL]

| Property | Value |
|----------|-------|
| System ID | `catboost_v9` |
| Production Model | `catboost_v9_33features_20260201_011018` |
| Training | 2025-11-02 to 2026-01-08 |
| **Medium Quality (3+ edge)** | **71.2% hit rate** (at launch; see decay note) |
| **High Quality (5+ edge)** | **79.0% hit rate, +50.9% ROI** (at launch) |
| MAE | 4.82 |
| SHA256 (prefix) | `5b3a187b1b6d` |
| Status | PRODUCTION (since 2026-02-08) — **DECAYING** |

**CRITICAL:** Use edge >= 3 filter. 73% of predictions have edge < 3 and lose money.

**MODEL DECAY (Session 220):** Champion has decayed from 71.2% → 39.9% edge 3+ HR (35+ days stale). Well below 52.4% breakeven. Q43 quantile challenger at 48.3% (29/50 picks, not ready for promotion). Monthly retrain warranted. Monitor with `validate-daily` Phase 0.56.

### Model Governance

**NEVER deploy a retrained model without passing ALL governance gates.**
**NEVER deploy a model without explicit user approval at each step.**
**Training is NOT deploying.** Use `/model-experiment` to train. Deployment requires separate user sign-off.

**Key lessons:**
- Lower MAE does NOT mean better betting. A retrain with better MAE (4.12) crashed hit rate to 51.2% due to systematic UNDER bias.
- **NEVER use a model's in-sample predictions as training data for a second model.** In-sample predictions have artificially high accuracy (~88% hit rate vs ~56% real-world), making downstream classifiers useless. Always use out-of-fold (OOF) predictions via temporal cross-validation. (Session 230)
- **Edge Classifier (Model 2) does not add value.** Pre-game features cannot predict which edges will hit (AUC < 0.50). Use Model 1 + edge threshold instead. (Session 230)

**Governance gates** (enforced in `quick_retrain.py`):
1. Duplicate check: blocks if same training dates exist
2. Vegas bias: pred_vs_vegas within +/- 1.5
3. High-edge (3+) hit rate >= 60%
4. Sample size >= 50 graded edge 3+ bets
5. No critical tier bias (> +/- 5 points)
6. MAE improvement vs baseline

**Process:** Train -> Gates pass -> Upload to GCS -> Register -> Shadow 2+ days -> Promote
**Rollback:** `gcloud run services update prediction-worker --region=us-west2 --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://..."`
**Naming:** `catboost_v9_33f_train{start}-{end}_{timestamp}.cbm`

### Model Registry
```bash
./bin/model-registry.sh list              # List all models with SHA256
./bin/model-registry.sh production        # Show production model
./bin/model-registry.sh validate          # Verify GCS paths + SHA256 integrity
./bin/model-registry.sh sync              # Sync GCS manifest → BQ registry
```

**IMPORTANT:** After updating `manifest.json` in GCS, run `./bin/model-registry.sh sync` to update BigQuery registry.

### Monthly Retraining
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MAR_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-02-28
# Script outputs ALL GATES PASSED/FAILED — do NOT deploy without passing
```

### Parallel Models & Quantile Discovery

Shadow challengers run alongside champion. Each gets own `system_id`, graded independently, no user-facing impact.

**Active challengers:** `catboost_v9_train1102_0108`, `_0131_tuned`, `_q43_train1102_0131`, `_q45_train1102_0131`
**Key finding:** Quantile alpha=0.43 achieves 65.8% HR 3+ when fresh (vs 33.3% baseline). First model to solve retrain paradox. Champion decaying (71.2% → 47.9%, 33+ days stale).
**Session 210 results (Feb 8-10):** Q43 60.0% edge 3+ HR (10 picks), Q45 60.0% (5 picks), vs champion 38.1% (21 picks). Awaiting 50+ edge 3+ graded for promotion decision.

**Dead ends (don't revisit):** Grow policy, NO_VEG+quantile, CHAOS+quantile, residual mode, two-stage pipeline, **Edge Classifier (Model 2)** (Session 230: AUC < 0.50, pre-game features cannot discriminate winning edges from losing ones).

**V12 Model 1 (Session 228-230):** Vegas-free CatBoost, 50 features, MAE loss. Avg 67% HR edge 3+ across 4 eval windows. Best: 78.7% Jan 2026. Ready for production deployment. See `docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md`.

```bash
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 7  # Monitor
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q43" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-01-31 --walkforward --force  # Train quantile
```

**Cross-model monitoring (Session 210):** 3 layers prevent shadow models from silently failing:
1. `reconcile-yesterday` Phase 9 — next-day gap detection
2. `validate-daily` Phase 0.486 — same-day early warning
3. Pipeline canary auto-heal (`pipeline_canary_queries.py`) — automated detection every 30 min + auto-triggers BACKFILL

**Promote:** Update `CATBOOST_V9_MODEL_PATH` env var. **Retire:** Set `enabled: False` in config.
**See:** `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md`, `docs/08-projects/current/session-179-validation-and-retrain/05-SESSION-186-QUANTILE-DISCOVERY.md`

## Breakout Classifier [Keyword: BREAKOUT]

**Status:** Shadow mode, V2 model (AUC 0.5708, 14 features). Not production-ready (no high-confidence predictions, max <0.6).

**CRITICAL:** Always use `ml/features/breakout_features.py` for feature computation (train/eval consistency).

```bash
# Production training
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py --name "PROD_V2" --mode shared --train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-05
```

**V3 roadmap:** Add `star_teammate_out`, `fg_pct_last_game`, `points_last_4q`, `opponent_key_injuries`.
**See:** `docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md`

## Deployment [Keyword: DEPLOY]

### Auto-Deploy via Cloud Build Triggers

**Primary method: Push to main auto-deploys changed services.** Each trigger also watches `shared/`.

**Cloud Run Services:**

| Service | Dockerfile |
|---------|------------|
| prediction-coordinator | predictions/coordinator/Dockerfile |
| prediction-worker | predictions/worker/Dockerfile |
| nba-phase3-analytics-processors | data_processors/analytics/Dockerfile |
| nba-phase4-precompute-processors | data_processors/precompute/Dockerfile |
| nba-phase2-raw-processors | data_processors/raw/Dockerfile |
| nba-scrapers | scrapers/Dockerfile |

**Cloud Functions (all auto-deploy via `cloudbuild-functions.yaml`):**

| Function | Trigger | Notes |
|----------|---------|-------|
| phase5b-grading | Pub/Sub: `nba-grading-trigger` | Grading orchestrator |
| phase6-export | Pub/Sub: `nba-phase6-export-trigger` | Publishing/export |
| grading-gap-detector | HTTP (Cloud Scheduler 9 AM ET) | Daily gap detection |
| phase3-to-phase4-orchestrator | Pub/Sub: `nba-phase3-analytics-complete` | Phase transition |
| phase4-to-phase5-orchestrator | Pub/Sub: `nba-phase4-precompute-complete` | Phase transition |
| phase5-to-phase6-orchestrator | Pub/Sub: `nba-phase5-predictions-complete` | Phase transition |
| enrichment-trigger | HTTP (Cloud Scheduler 18:40 UTC) | Enriches predictions with prop lines |
| daily-health-check | HTTP (Cloud Scheduler 9 AM ET) | Daily pipeline health check + Slack alerts |
| transition-monitor | HTTP (Cloud Scheduler) | Phase transition health monitoring |
| pipeline-health-summary | HTTP (Cloud Scheduler 6 AM PT) | Daily pipeline health email summary |
| nba-grading-alerts | HTTP (Cloud Scheduler) | Grading coverage/accuracy Slack alerts |
| live-freshness-monitor | HTTP (Cloud Scheduler) | Live game data freshness monitoring |
| self-heal-predictions | HTTP (Cloud Scheduler) | Auto-heal stalled/missing predictions |
| grading-readiness-monitor | HTTP (Cloud Scheduler) | Post-game grading readiness monitor |
| post-grading-export | Pub/Sub: `nba-grading-complete` | Re-exports picks with actuals after grading |

phase2-to-phase3-orchestrator REMOVED (Session 205).

Monitoring function triggers created via `./bin/infrastructure/create_monitoring_function_triggers.sh`.

```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5  # Check recent builds
gcloud builds log BUILD_ID --region=us-west2 --project=nba-props-platform    # View build logs
```

### Manual Deploy Options
```bash
./bin/deploy-service.sh SERVICE   # Standard (8-10 min)
./bin/hot-deploy.sh SERVICE       # Hot-deploy (5-6 min)
```

### CRITICAL: Always deploy from repo root
```bash
./bin/deploy-service.sh prediction-worker   # Correct
# cd predictions/worker && gcloud run deploy  # WRONG - will fail
```

### Check Deployment Status
```bash
gcloud run services describe SERVICE --region=us-west2 --format="value(metadata.labels.commit-sha)"
./bin/check-deployment-drift.sh --verbose
```

## Key Tables [Keyword: TABLES]

| Table | Notes |
|-------|-------|
| `prediction_accuracy` | **All grading queries** (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use |
| `nba_reference.nba_schedule` | Clean view, use for queries |
| `nba_raw.nbac_schedule` | Requires partition filter |

**Game Status:** 1=Scheduled, 2=In Progress, 3=Final

## ML Feature Quality [Keyword: QUALITY]

**Zero tolerance:** Predictions blocked for ANY player with `default_feature_count > 0`. Three enforcement layers: Phase 4 quality_scorer, coordinator quality_gate (`HARD_FLOOR_MAX_DEFAULTS = 0`), worker defense-in-depth.

**Impact:** Coverage drops from ~180 to ~75 predictions per game day. Intentional (accuracy > coverage). To increase coverage, fix upstream data pipeline, never relax the tolerance.

```sql
-- Quick quality check
SELECT game_date, AVG(feature_quality_score) as avg_quality,
       COUNTIF(quality_alert_level = 'red') as red_count,
       COUNTIF(is_quality_ready) as quality_ready_count, COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;
```

**37 features** across 5 categories: matchup(5-8,13-14), player_history(0-4,29-36), team_context(22-24), vegas(25-28), game_context(9-12,15-21). Each has `feature_N_quality` (0-100) and `feature_N_source` columns.

**Key insight:** The aggregate `feature_quality_score` masks component failures. Always check category-level quality for root cause.
**Audit:** `default_feature_count` and `default_feature_indices` in `player_prop_predictions`. See `shared/ml/feature_contract.py` for `FEATURE_SOURCE_MAP`.
**See:** `docs/08-projects/current/feature-quality-visibility/`, `docs/08-projects/current/zero-tolerance-defaults/`

## Phase 3 Health Check [Keyword: PHASE3]

```bash
./bin/monitoring/phase3_health_check.sh
python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix
```

**See:** `docs/02-operations/runbooks/phase3-orchestration.md`

## Essential Queries [Keyword: QUERIES]

```sql
-- Check recent predictions
SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1

-- Check today's signal
SELECT daily_signal, pct_over, high_edge_picks
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'

-- Check games status
SELECT game_id, away_team_tricode, home_team_tricode, game_status
FROM nba_reference.nba_schedule WHERE game_date = CURRENT_DATE()

-- Check zero tolerance impact
SELECT game_date,
       COUNTIF(default_feature_count = 0) as clean_players,
       COUNTIF(default_feature_count > 0) as blocked_players,
       COUNTIF(is_quality_ready) as quality_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;

-- Check grading coverage (Session 212)
WITH gradable AS (
  SELECT game_date,
    COUNT(*) as total_predictions,
    COUNTIF(line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')) as gradable_predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= CURRENT_DATE() - 3 AND is_active = TRUE
  GROUP BY 1
),
graded AS (
  SELECT game_date, COUNT(*) as graded_count
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= CURRENT_DATE() - 3
  GROUP BY 1
)
SELECT
  g.game_date,
  g.total_predictions,
  g.gradable_predictions,
  COALESCE(gr.graded_count, 0) as graded,
  ROUND(100.0 * COALESCE(gr.graded_count, 0) / g.gradable_predictions, 1) as grading_pct
FROM gradable g
LEFT JOIN graded gr USING (game_date)
ORDER BY 1 DESC;
-- Expected: 95%+ grading_pct (graded / gradable, not graded / total)
```

**Full query library:** See `docs/02-operations/useful-queries.md`

## Common Issues [Keyword: ISSUES]

| Issue | Symptom | Fix |
|-------|---------|-----|
| Deployment drift | Old bugs recurring | `./bin/deploy-service.sh SERVICE` |
| **Env var drift** | **Missing env vars, service crashes** | **NEVER use `--set-env-vars` (wipes all vars), ALWAYS use `--update-env-vars`** |
| Vegas line coverage low | <40% line coverage | NORMAL - threshold is 45%, not 80% |
| **Grading coverage 60-80%** | **Only 60-80% of predictions graded** | **NORMAL - NO_PROP_LINE predictions intentionally excluded from grading. Expected: 95%+ of gradable predictions (those with real prop lines).** |
| Schema mismatch | "Invalid field" error | `python .pre-commit-hooks/validate_schema_fields.py` |
| Partition filter | 400 error on query | Add `WHERE game_date >= ...` |
| Silent BQ write fail | 0 records written | Use `{project}.{dataset}.{table}` pattern |
| Quota exceeded | Rate limit error | Use `BigQueryBatchWriter` |
| game_id mismatch | JOIN failures | Use `game_id_reversed` for reversed format tables |
| Cloud Function imports | ModuleNotFoundError | Run symlink validation, fix shared/ paths |
| Silent service failure | Service running but requests fail | Check `/health/deep` endpoint |
| ML train/eval mismatch | Poor holdout despite good training | Use shared feature module (`ml/features/`) for both |
| Low feature quality | `matchup_quality_pct < 50` | Check which processor didn't run via `missing_processors` field |
| Zero tolerance blocking | `zero_tolerance_defaults_N` in logs | Normal. Fix by ensuring Phase 4 processors run. Never relax. |
| Stale batch blocks `/start` | `already_running` response | Check `/status`, then `/reset` the stale batch |
| Model decay | Hit rate declining weekly | Monitor QUANT_43 shadow, promote when validated. Q43 60% edge 3+ on Feb 8-10. |
| Shadow model gap | Shadow model 0 predictions | **Auto-healed by pipeline canary** (Session 210). Also detected by `reconcile-yesterday` Phase 9 and `validate-daily` Phase 0.486. If auto-heal fails, manual: `/start` with BACKFILL mode. |
| BDL scraper not running | 0 BDL records | EXPECTED: BDL intentionally disabled. 60-70% minutes coverage is normal. |
| Orchestrator not triggering | Phase 2 complete, `_triggered=False` | NOT a bug. Phase 3 uses direct Pub/Sub, not orchestrator. |
| Cloud Build trigger stale | Trigger deploys old commit SHA | Delete and recreate trigger (`gcloud builds triggers delete/create`). Session 213 fix. |
| Scheduler jobs failing | Jobs return non-SUCCESS status | Run `validate-daily` Phase 0.67/0.675. Session 219: fixed all 15 failing → 0. Common: reporter 500→200, missing shared/, Gen2 entry point. |
| game_id format mismatch | "Missing: N games" but 100% coverage | Schedule uses numeric game_ids, gamebook/analytics use `YYYYMMDD_AWAY_HOME`. Match by team pairs. Session 217. |
| Cloud Build Docker cache | Old code deployed despite new commit | Use `./bin/hot-deploy.sh SERVICE` to force fresh build without Docker layer cache. Session 217. |
| UPCG race condition | Games with 0 predictions/lines | UPCG props readiness check now BLOCKING (raises 500, Pub/Sub retries). Validate with Phase 0.715. Session 218. |
| Out players with predictions | Injured-out players shown in API | Enrichment trigger (18:40 UTC) now rechecks injuries and deactivates. Validate with Phase 0.72. Session 218. |
| Tonight export incomplete | Some games missing from export | Check `is_active = TRUE` filter (Session 218), then UPCG prop coverage. Validate with Phase 0.975. |
| CF runtime no CLI tools | `gcloud: command not found` in Cloud Function | Use Python client libraries (`google-cloud-bigquery`, `google-cloud-storage`), NOT shell commands. Session 218B. |
| Scheduler INTERNAL errors | Reporter CFs return 500 for data findings | Reporter functions MUST return 200. Put findings in response body. Session 219. |
| Gen2 entry point stuck | Re-deployed CF still uses old entry point | Gen2 entry point is immutable. Add `main = func` alias at end of main.py. Session 219. |
| Phase 4 same-day failure | 0% coverage for today's games | FIXED: Defensive checks auto-skip for `analysis_date >= today`. No longer need `strict_mode: false`. Session 220. |
| Auto-retry infinite loop | 100s of retries for same processor | Check `failed_processor_queue`. 4xx now marks `failed_permanent`. Validate with Phase 0.695. Session 220. |
| Champion model decay | Hit rate below breakeven (52.4%) | Monitor with validate-daily Phase 0.56. Champion at 39.9% (35+ days stale). Consider retrain. Session 220. |

**Full troubleshooting:** See `docs/02-operations/session-learnings.md`

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
- id: validate-schema-fields       # BigQuery schema alignment
- id: validate-python-syntax        # Syntax errors break Cloud Function deploys (Session 213)
- id: validate-deploy-safety        # Detects dangerous --set-env-vars (Session 81/213)
- id: validate-dockerfile-imports   # Missing COPY dirs cause ModuleNotFoundError
- id: validate-pipeline-patterns    # Invalid enum, processor name gaps
```

### Dependency Lock Files
All services use `requirements-lock.txt` for pinned, deterministic builds. Update when dependencies change:
```bash
cd <service-dir>
docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c \
  "pip install --quiet --upgrade pip && pip install --quiet -r requirements.txt && pip freeze > requirements-lock.txt"
```

### Cloud Function Deploy Patterns (Session 219)
- **Use `rsync -aL`** not `cp -r` when copying shared/ (cp misses symlinked files)
- **Gen2 entry point is immutable** — add `main = actual_func` alias at end of main.py
- **Functions Framework doesn't route paths** — add `if request.path == '/route':` in entry point
- **Reporter functions MUST return 200** — scheduler treats non-200 as job failure
- **No CLI tools in CF runtime** — use Python client libraries, not gcloud/gsutil/bq

### Health Checks
- `/health/deep` endpoint validates critical imports and connectivity
- Deployment smoke tests auto-verify after deploy
- **See:** `docs/05-development/health-checks-and-smoke-tests.md`

### Batching Pattern
```python
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches
```

## Handoff Template [Keyword: HANDOFF]

Create at `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md`. **Template:** See `docs/09-handoff/HANDOFF-TEMPLATE.md`

## End of Session Checklist [Keyword: ENDSESSION]

```bash
git push origin main                                                          # 1. Push (auto-deploys)
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5   # 2. Verify builds
./bin/check-deployment-drift.sh --verbose                                     # 3. Check drift
./bin/model-registry.sh sync                                                  # 4. If model changes
# 5. Create handoff document
```

**Fallback:** `./bin/hot-deploy.sh <service-name>`

## Conventions

### Commit Messages
```
type: Short description

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Style
- Python 3.11+, type hints for public APIs, docstrings for classes and complex functions

## GCP Resources

| Resource | Value |
|----------|-------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |
| Datasets | nba_predictions, nba_analytics, nba_raw, nba_orchestration |
| GCS API Bucket | `gs://nba-props-platform-api/v1/` |
| GCS API Base URL | `https://storage.googleapis.com/nba-props-platform-api/v1/` |
| Frontend Domain | `playerprops.io` |

**Key API Endpoints** (auto-generated daily, 6 AM ET):
- `v1/schedule/game-counts.json` - Season game counts for calendar
- `v1/status.json` - System status + active break detection (All-Star, holidays)

## Documentation Index [Keyword: DOCS]

| Topic | Location |
|-------|----------|
| **Session work** | `docs/08-projects/current/<project>/` |
| **Session handoffs** | `docs/09-handoff/` |
| Troubleshooting | `docs/02-operations/troubleshooting-matrix.md` |
| Session learnings | `docs/02-operations/session-learnings.md` |
| System features | `docs/02-operations/system-features.md` |
| Architecture | `docs/01-architecture/` |
| Runbooks | `docs/02-operations/runbooks/` |
| Development guides | `docs/05-development/` |
| Monthly summaries | `docs/08-projects/summaries/` |

## Feature References

See `docs/02-operations/system-features.md` for: Heartbeat System, Evening Analytics, Early Predictions, Model Attribution, Signal System.
