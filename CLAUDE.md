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

**Status:** Shadow mode (no production impact)

The breakout classifier identifies role players (8-16 PPG) at risk of "breakout" games (1.5x season average). Uses CatBoost model trained on 10 features.

### Shared Feature Module (Session 134b)

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

### Models in GCS

```
gs://nba-props-platform-models/breakout/v1/
├── breakout_v1_20251102_20260205.cbm  # Active in production
└── breakout_v1_20251102_20260115.cbm  # Backup
```

**See:** `docs/09-handoff/2026-02-05-SESSION-134-COMPLETE-SUMMARY.md` for full context

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
