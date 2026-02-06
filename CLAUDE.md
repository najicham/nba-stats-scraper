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

## Core Principles

- **Data quality first** - Discovery queries before assumptions
- **Zero tolerance for defaults** - Never predict with fabricated feature values (Session 141)
- **Always filter partitions** - Massive BigQuery performance gains
- **Batch over streaming** - Avoid 90-min DML locks
- **One small thing at a time** - With comprehensive testing
- **99.2% player name resolution** - Via universal registry

## Session Philosophy

1. **Understand root causes, not just symptoms** - Investigate WHY bugs happen
2. **Prevent recurrence** - Add validation, tests, or automation
3. **Use agents liberally** - Spawn multiple Task agents in parallel
4. **Keep documentation updated** - Update handoff docs and runbooks
5. **Fix the system, not just the code** - Schema issues need schema validation

## Documentation Procedure [Keyword: DOC]

**When creating session documentation:**
- **Location:** `docs/08-projects/current/<project-name>/`
- Use existing project directory if work relates to ongoing project
- Create new subdirectory for new projects/investigations
- See "Documentation Index" section below for other doc locations

**Shorthand:** When you say "doc this" or "use doc procedure", Claude will follow this pattern.

## Quick Start [Keyword: START]

### 1. Read the Latest Handoff
```bash
ls -la docs/09-handoff/ | tail -5
```

### 2. Run Daily Validation
```bash
/validate-daily
```

### 3. Check Deployment Drift
```bash
./bin/check-deployment-drift.sh --verbose
```

## Monitoring & Self-Healing [Keyword: MONITOR]

**Session 135** - Six-layer resilience system with full observability

### Layer 1: Deployment Drift (2-hour detection)
```bash
# Manual check
python bin/monitoring/deployment_drift_alerter.py

# Automated: Runs every 2 hours, alerts to #deployment-alerts
# Detects services with stale code, provides deploy commands
```

### Layer 2: Pipeline Canaries (30-minute validation)
```bash
# Manual check
python bin/monitoring/pipeline_canary_queries.py

# Automated: Runs every 30 minutes, alerts to #canary-alerts
# Validates all 6 phases with real data quality checks
```

### Layer 3: Quality Gates
```python
# Phase 2→3 gate validates raw data before analytics
from shared.validation.phase2_quality_gate import Phase2QualityGate
gate = Phase2QualityGate(bq_client, project_id)
result = gate.check_raw_data_quality(game_date)
# Blocks bad data (NULL rates, missing games, stale data)
```

### Auto-Batch Cleanup (Self-Healing)
```bash
# Check recent healing events
python bin/monitoring/analyze_healing_patterns.py

# Automated: Runs every 15 minutes
# Auto-heals stalled batches (>90% complete, stalled 15+ min)
# Tracks everything: root cause, before/after state, success rate
# Alerts if healing too frequent (indicates systemic issue)
```

**Key Principle:** "Auto-heal, but track everything so we can prevent"

**Healing Workflow:**
1. System auto-heals issue (e.g., completes stalled batch)
2. Records full audit trail (why, what, before/after)
3. Pattern detection alerts if too frequent
4. Human analyzes root causes → implements prevention
5. Healing frequency decreases over time

**Slack Channels:**
- `#deployment-alerts` - Stale deployments (every 2h)
- `#canary-alerts` - Pipeline failures (every 30min)
- `#nba-alerts` - Self-healing events (when triggered)

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
| **Injuries** | `nbac_injury_report` (NBA.com) ⭐ | `nba_raw.nbac_injury_report` | Official PDFs, 15-min updates |
| | `bdl_injuries` (Ball Don't Lie) | `nba_raw.bdl_injuries` | Fallback only |
| **Schedule** | `nbac_schedule` (NBA.com) | `nba_raw.nbac_schedule` | 100% coverage |
| **Player Stats** | `nbac_gamebook_player_stats` | `nba_raw.nbac_gamebook_player_stats` | Official stats |
| **Betting Lines** | `odds_api_*` (The Odds API) | `nba_raw.odds_api_*` | 10+ sportsbooks |
| **Play-by-Play** | `nbac_play_by_play` | `nba_raw.nbac_play_by_play` | Every possession |

**Table Naming Conventions:**
- `nbac_*` = NBA.com official sources
- `bdl_*` = Ball Don't Lie API
- `odds_api_*` = The Odds API
- `bettingpros_*` = BettingPros

## ML Model - CatBoost V9 [Keyword: MODEL]

| Property | Value |
|----------|-------|
| System ID | `catboost_v9` |
| Training | Current season only (Nov 2025+) |
| **Medium Quality (3+ edge)** | **65.0% hit rate, +24.0% ROI** - RECOMMENDED |
| **High Quality (5+ edge)** | **79.0% hit rate, +50.9% ROI** |
| All Bets (no filter) | 54.7% hit rate, +4.5% ROI |

**CRITICAL:** Use edge >= 3 filter. 73% of predictions have edge < 3 and lose money.

### Monthly Retraining
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31
```

## Breakout Classifier [Keyword: BREAKOUT]

**Status:** Shadow mode (no production impact) - V3 development in progress

The breakout classifier identifies role players (8-16 PPG) at risk of "breakout" games (1.5x season average). Currently using V2 model with 14 features (AUC 0.5708).

**Critical Issue (Session 135):** No high-confidence predictions (max <0.6, need 0.769+). V3 development focuses on contextual features to unlock high-confidence signals.

### Shared Feature Module (Sessions 134b, 135)

**CRITICAL:** Always use `ml/features/breakout_features.py` for feature computation to ensure train/eval consistency.

```python
from ml.features.breakout_features import (
    get_training_data_query,
    prepare_feature_vector,
    validate_feature_distributions
)
```

**Why this matters:** Session 134b discovered that training with one feature pipeline and evaluating with another caused AUC to drop from 0.62 to 0.47 (worse than random). Using the shared module fixed this.

### Training & Evaluation

**Production Training (recommended):**
```bash
# Use shared mode for production consistency
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
  --name "PROD_V2" \
  --mode shared \
  --train-start 2025-11-02 \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-05
```

**Experimental Research:**
```bash
# Test new features before promoting to shared module
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
  --name "EXP_CV_RATIO" \
  --mode experimental \
  --features "cv_ratio,cold_streak_indicator,pts_vs_season_zscore" \
  --train-start 2025-11-02 \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-05
```

**Quick Evaluation:**
```bash
# Train with shared features and evaluate on holdout
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-05
```

### V2 Performance (Session 135)

**Current Production Model:** `breakout_shared_v1_20251102_20260205.cbm`
- **AUC:** 0.5708 (14 features)
- **Precision@0.5:** 23.9%
- **Critical Issue:** No high-confidence predictions (max <0.6)
- **Best Feature:** `minutes_increase_pct` (16.9% importance)

**Why V2 Isn't Production-Ready:**
- Target: 60% precision at 0.769 threshold
- Actual: No predictions above 0.6 confidence
- Root cause: Statistical features plateau, need contextual features

### V3 Roadmap (Next Priority)

**High-Impact Features to Add:**
1. `star_teammate_out` - Star teammates OUT (+0.04-0.07 AUC expected)
2. `fg_pct_last_game` - Hot shooting rhythm
3. `points_last_4q` - 4Q performance signal
4. `opponent_key_injuries` - Weakened defense

**Infrastructure Ready:**
- Injury integration: `predictions/shared/injury_integration.py`
- Shared feature module: `ml/features/breakout_features.py`
- Dual-mode experiment runner

### Models in GCS

```
gs://nba-props-platform-models/breakout/v1/
├── breakout_shared_v1_20251102_20260205.cbm  # V2 Production (AUC 0.5708)
├── breakout_v2_14features.cbm                # V2 Experimental
└── breakout_v1_20251102_20260115.cbm         # V1 Backup
```

**See:**
- `docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md` - V3 roadmap and quick start
- `docs/09-handoff/2026-02-05-SESSION-135-BREAKOUT-V2-AND-V3-PLAN.md` - Full session details
- `docs/09-handoff/NEXT-SESSION-PROMPT.md` - Copy-paste prompt for Session 136

## Deployment [Keyword: DEPLOY]

### CRITICAL: Always deploy from repo root
```bash
# Correct
./bin/deploy-service.sh prediction-worker

# Wrong - will fail
cd predictions/worker && gcloud run deploy --source .
```

### Services
| Service | Dockerfile |
|---------|------------|
| prediction-coordinator | predictions/coordinator/Dockerfile |
| prediction-worker | predictions/worker/Dockerfile |
| nba-phase3-analytics-processors | data_processors/analytics/Dockerfile |
| nba-phase4-precompute-processors | data_processors/precompute/Dockerfile |
| nba-phase2-processors | data_processors/raw/Dockerfile |
| nba-scrapers | scrapers/Dockerfile |

### Deployment Options

**Standard deploy** (full validation, ~8-10 min):
```bash
./bin/deploy-service.sh SERVICE
```

**Hot-deploy** (skips non-essential checks, ~5-6 min):
```bash
./bin/hot-deploy.sh SERVICE
```

Hot-deploy skips:
- Dockerfile dependency validation
- 120s BigQuery write verification
- Env var preservation checks

Use hot-deploy for quick fixes, standard for major changes.

### Always Deploy After Bug Fixes
```bash
# Check deployed commit
gcloud run services describe SERVICE --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to latest
git log -1 --format="%h"

# Redeploy if different
./bin/deploy-service.sh SERVICE
```

## Key Tables [Keyword: TABLES]

### Grading
| Table | Use For |
|-------|---------|
| `prediction_accuracy` | **All grading queries** (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use |

### Schedule
| Table | Notes |
|-------|-------|
| `nba_reference.nba_schedule` | Clean view, use for queries |
| `nba_raw.nbac_schedule` | Requires partition filter |

**Game Status:** 1=Scheduled, 2=In Progress, 3=Final

## ML Feature Quality [Keyword: QUALITY]

**Status:** Session 141 - Zero tolerance for default features

The ML feature store has comprehensive per-feature quality tracking:
- **122 fields total:** 74 per-feature columns (37 quality + 37 source) + 48 aggregate/JSON fields
- **37 features tracked** across 5 categories: matchup(6), player_history(13), team_context(3), vegas(4), game_context(11)
- **Detection time:** <5 seconds for quality issues (vs 2+ hours manual)
- **Zero tolerance (Session 141):** Predictions blocked for ANY player with `default_feature_count > 0`

### Quick Quality Checks

```sql
-- Check overall quality (includes quality gate readiness)
SELECT game_date, AVG(feature_quality_score) as avg_quality,
       COUNTIF(quality_alert_level = 'red') as red_count,
       COUNTIF(is_quality_ready) as quality_ready_count,
       COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;

-- Check category quality
SELECT game_date,
       ROUND(AVG(matchup_quality_pct), 1) as matchup,
       ROUND(AVG(player_history_quality_pct), 1) as history,
       ROUND(AVG(game_context_quality_pct), 1) as context
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;

-- Find bad features (direct columns - FAST)
SELECT player_lookup, feature_5_quality, feature_6_quality, feature_7_quality, feature_8_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
  AND (feature_5_quality < 50 OR feature_6_quality < 50 OR feature_7_quality < 50 OR feature_8_quality < 50);
```

**Note (Session 139):** The `prediction_made_before_game` field in `player_prop_predictions` tracks whether a prediction was generated before game start time, enabling accurate grading of pre-game vs backfill predictions.

### Zero Tolerance Policy (Session 141)

**CRITICAL:** Predictions are blocked for any player with `default_feature_count > 0`. Three enforcement layers:
1. **Phase 4 (quality_scorer.py):** `is_quality_ready=false` when any defaults exist
2. **Coordinator (quality_gate.py):** `HARD_FLOOR_MAX_DEFAULTS = 0` hard floor blocks all modes
3. **Worker (worker.py):** Defense-in-depth sets `is_actionable=false`

**Impact:** Coverage drops from ~180 to ~75 predictions per game day. This is intentional -- accuracy > coverage. To increase coverage, fix the data pipeline (Phase 4 processors, vegas line coverage), never relax the tolerance.

**Audit:** `default_feature_count` and `default_feature_indices` are written to `player_prop_predictions` for every prediction.

**Feature Completeness (Session 142):** `default_feature_indices ARRAY<INT64>` tracks exactly which feature indices used defaults. See `shared/ml/feature_contract.py` for `FEATURE_SOURCE_MAP` mapping indices to pipeline components. See `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md` for gap analysis.

### Per-Feature Quality Fields

Each of 37 features has:
- `feature_N_quality` - Quality score 0-100 (direct column)
- `feature_N_source` - Source type: 'phase4', 'phase3', 'calculated', 'default' (direct column)

**Critical features to monitor:**
- Features 5-8: Composite factors (fatigue, shot zone, pace, usage)
- Features 13-14: Opponent defense (def rating, pace)

### Category Definitions

| Category | Features | Critical? |
|----------|----------|-----------|
| **matchup** | 5-8, 13-14 (6 total) | ✅ Yes - Session 132 issue |
| **player_history** | 0-4, 29-36 (13 total) | No |
| **team_context** | 22-24 (3 total) | No |
| **vegas** | 25-28 (4 total) | No |
| **game_context** | 9-12, 15-21 (11 total) | No |

### Common Issues

| Issue | Detection | Fix |
|-------|-----------|-----|
| All matchup features defaulted | `matchup_quality_pct = 0` | Check PlayerCompositeFactorsProcessor ran |
| Any defaults present | `default_feature_count > 0` | Prediction blocked (Session 141 zero tolerance). Fix upstream data gaps. |
| Low training quality | `training_quality_feature_count < 30` | Investigate per-feature quality scores |

### Documentation

**Project docs:** `docs/08-projects/current/feature-quality-visibility/`
- 00-PROJECT-OVERVIEW.md - Problem analysis and solution
- 07-FINAL-HYBRID-SCHEMA.md - Complete schema design
- Session 134 handoff: `docs/09-handoff/2026-02-05-SESSION-134-START-HERE.md`

**Key insight:** "The aggregate feature_quality_score is a lie" - it masks component failures. Always check category-level quality (matchup, history, context, vegas, game_context) for root cause.

**Session 141:** Zero tolerance project docs at `docs/08-projects/current/zero-tolerance-defaults/`

## Phase 3 Health Check [Keyword: PHASE3]

```bash
./bin/monitoring/phase3_health_check.sh  # Daily health check
python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix  # Fix tracking issues
```

**See:** `docs/02-operations/runbooks/phase3-orchestration.md` for full details

## Essential Queries [Keyword: QUERIES]

```sql
-- Check recent predictions
SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1

-- Check today's signal
SELECT daily_signal, pct_over, high_edge_picks
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'

-- Check games status (1=Scheduled, 2=In Progress, 3=Final)
SELECT game_id, away_team_tricode, home_team_tricode, game_status
FROM nba_reference.nba_schedule WHERE game_date = CURRENT_DATE()

-- Check quality-blocked predictions (Session 139)
SELECT game_date, COUNT(*) as blocked,
       ARRAY_AGG(DISTINCT quality_alert_level) as alert_levels
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
  AND quality_alert_level = 'red'
GROUP BY 1 ORDER BY 1 DESC;

-- Session 141: Check zero tolerance impact (defaults vs clean)
SELECT game_date,
       COUNTIF(default_feature_count = 0) as clean_players,
       COUNTIF(default_feature_count > 0) as blocked_players,
       COUNTIF(is_quality_ready) as quality_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;

-- Session 142: Diagnose which features are most commonly defaulted
SELECT idx, COUNT(*) as default_count
FROM nba_predictions.ml_feature_store_v2,
UNNEST(default_feature_indices) as idx
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 2 DESC;
```

**Full query library:** See `docs/02-operations/useful-queries.md`

## Common Issues [Keyword: ISSUES]

| Issue | Symptom | Fix |
|-------|---------|-----|
| Deployment drift | Old bugs recurring | `./bin/deploy-service.sh SERVICE` (See Session 128 prevention plan) |
| Vegas line coverage low | <40% line coverage in feature store | NORMAL - threshold is 45%, not 80% (Session 128) |
| **Env var drift** | **Missing env vars, service crashes** | **NEVER use `--set-env-vars` (wipes all vars), ALWAYS use `--update-env-vars`** |
| Schema mismatch | "Invalid field" error | `python .pre-commit-hooks/validate_schema_fields.py` |
| Partition filter | 400 error on query | Add `WHERE game_date >= ...` |
| Silent BQ write fail | 0 records written | Use `{project}.{dataset}.{table}` pattern |
| Quota exceeded | Rate limit error | Use `BigQueryBatchWriter` |
| CloudFront blocking | 403 on rapid requests | Enable proxy rotation, throttle requests |
| game_id mismatch | JOIN failures between tables | Use game_id_reversed for reversed format tables |
| REPEATED field NULL | JSON parsing error | Use `field or []` instead of allowing None |
| Cloud Function imports | ModuleNotFoundError | Run symlink validation, fix shared/ paths |
| Orphan superseded predictions | Players missing active predictions after regen | Re-run regeneration (Session 102 auto-skips edge filter) |
| Feature cache stale | Wrong predicted values, low hit rate | Regenerate predictions for affected dates |
| **Silent service failure** | **Service running but requests fail** | **Check `/health/deep` endpoint - missing module or broken dependency (Session 129)** |
| **ML train/eval mismatch** | **Model has poor holdout performance despite good training metrics** | **Use shared feature module (`ml/features/`) for both training and evaluation (Session 134b)** |
| **Low feature quality** | **`matchup_quality_pct < 50` or `default_feature_count > 0`** | **Check which processor didn't run: query `missing_processors` field or check phase_completions table** |
| **Session 132 recurrence** | **All matchup features (5-8) at quality 40** | **PlayerCompositeFactorsProcessor didn't run - check scheduler job configuration** |
| **Predictions skipped due to quality** | **`PREDICTIONS_SKIPPED` Slack alert** | **Check Phase 4 processor logs, BACKFILL next day: `POST /start {"game_date":"YYYY-MM-DD","prediction_run_mode":"BACKFILL"}`** |
| **Zero tolerance blocking** | **`zero_tolerance_defaults_N` in quality gate logs** | **Normal behavior (Session 141). Fix by ensuring Phase 4 processors run for all players. Never relax the tolerance.** |

**Full troubleshooting:** See `docs/02-operations/session-learnings.md`

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
- id: validate-schema-fields
  entry: python .pre-commit-hooks/validate_schema_fields.py
```

### Dependency Lock Files (Session 133)
**Ensures deterministic builds** and prevents version drift issues

All services use `requirements-lock.txt` for pinned dependencies:
- **Faster builds:** Saves 1-2 min per build (no pip dependency resolution)
- **Deterministic:** Same package versions every time
- **Prevents drift:** Eliminates version conflict bugs (e.g., db-dtypes)

**Update lock files when dependencies change:**
```bash
cd <service-dir>
docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c \
  "pip install --quiet --upgrade pip && \
   pip install --quiet -r requirements.txt && \
   pip freeze > requirements-lock.txt"
```

**Note:** Keep `requirements.txt` for documentation, use `requirements-lock.txt` for builds.

### Health Checks & Smoke Tests (Sessions 129-132)
**Prevents silent service failures** (e.g., missing modules, broken dependencies)

- **Deep health checks:** `/health/deep` endpoint validates critical imports and connectivity
- **Deployment smoke tests:** Automatically verify service functionality after deployment
- **Drift monitoring:** Slack alerts for stale deployments (every 2 hours)
- **Defense-in-depth:** 6 layers of validation from build to recovery

**See:** `docs/05-development/health-checks-and-smoke-tests.md` for implementation guide

### Batching Pattern
```python
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches
```

## Handoff Template [Keyword: HANDOFF]

Create at `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md`

**Template:** See `docs/09-handoff/HANDOFF-TEMPLATE.md`

## End of Session Checklist [Keyword: ENDSESSION]

**CRITICAL:** Before ending any session where code was changed:

```bash
# 1. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 2. Deploy stale services (if any)
./bin/deploy-service.sh <service-name>

# 3. Verify deployments
./bin/whats-deployed.sh

# 4. Create handoff document
```

**Why this matters:** Sessions 64, 81, 82, and 97 had fixes committed but not deployed, causing recurring issues. Deployment drift is the #1 cause of "already fixed" bugs reappearing.

| If you changed... | Deploy... |
|-------------------|-----------|
| `predictions/worker/` | `prediction-worker` |
| `predictions/coordinator/` | `prediction-coordinator` |
| `data_processors/analytics/` | `nba-phase3-analytics-processors` |
| `data_processors/precompute/` | `nba-phase4-precompute-processors` |
| `shared/` | ALL services that use shared code |

## Conventions

### Commit Messages
```
type: Short description

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Style
- Python 3.11+
- Type hints for public APIs
- Docstrings for classes and complex functions

## GCP Resources

| Resource | Value |
|----------|-------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |
| Datasets | nba_predictions, nba_analytics, nba_raw, nba_orchestration |

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

**Monthly Summaries:** `docs/08-projects/summaries/` - 70+ sessions/month, anti-patterns, and lessons learned

## Feature References

For detailed documentation on these features, see `docs/02-operations/system-features.md`:

- **Heartbeat System** - Firestore-based processor health tracking
- **Evening Analytics** - Same-night game processing (6 PM, 10 PM, 1 AM ET)
- **Early Predictions** - 2:30 AM predictions with REAL_LINES_ONLY mode
- **Model Attribution** - Track which model file generated predictions
- **Signal System** - GREEN/YELLOW/RED daily prediction signals
