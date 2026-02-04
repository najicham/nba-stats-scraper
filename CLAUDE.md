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

## Quick Start

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

## Using Agents

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

## ML Model - CatBoost V9

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

## Deployment

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

## Key Tables

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

## Essential Queries

### Check Predictions
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1"
```

### Hit Rate by Edge Tier
```sql
SELECT
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High (5+)'
    WHEN ABS(predicted_points - line_value) >= 3 THEN 'Medium (3-5)'
    ELSE 'Low (<3)'
  END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND recommendation IN ('OVER', 'UNDER')  -- Exclude PASS
GROUP BY tier
```

### Check Today's Signal
```sql
SELECT daily_signal, pct_over, high_edge_picks
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
```

### Check Games Status
```sql
SELECT game_id, away_team_tricode, home_team_tricode,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END
FROM nba_reference.nba_schedule
WHERE game_date = CURRENT_DATE()
```

## Common Issues - Quick Reference

| Issue | Symptom | Fix |
|-------|---------|-----|
| Deployment drift | Old bugs recurring | `./bin/deploy-service.sh SERVICE` |
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

**Full troubleshooting:** See `docs/02-operations/session-learnings.md`

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
- id: validate-schema-fields
  entry: python .pre-commit-hooks/validate_schema_fields.py
```

### Batching Pattern
```python
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches
```

## Handoff Template

Create at `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md`:

```markdown
# Session N Handoff - [Date]

## Session Summary
[What was accomplished]

## Fixes Applied
[Table of fixes with files and commits]

## Root Causes Identified
[Why issues happened]

## Prevention Mechanisms Added
[Validation, automation, tests]

## Known Issues Still to Address
[What's left]

## Next Session Checklist
[Prioritized TODO]
```

## End of Session Checklist

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

## Documentation Structure

### Key Directories

| Directory | Purpose | When to Use |
|-----------|---------|-------------|
| `docs/00-start-here/` | Quick start guides | First session, errors |
| `docs/01-architecture/` | System design, decisions | Architecture changes |
| `docs/02-operations/` | Runbooks, troubleshooting | Daily operations, incidents |
| `docs/03-phases/` | Phase 1-6 pipeline docs | Phase-specific work |
| `docs/05-development/` | Dev guides, patterns | Writing code, testing |
| `docs/08-projects/` | **Project tracking** | **Session work, handoffs** |
| `docs/09-handoff/` | Session handoffs | Session summaries |

### Project Directory (`docs/08-projects/`)

**Purpose:** Track all active, completed, and archived projects

**Structure:**
```
docs/08-projects/
├── current/              # Active projects (< 14 days or ongoing)
├── completed/            # Finished projects (keep 30 days)
├── archive/YYYY-MM/      # Historical projects by month
├── summaries/YYYY-MM.md  # Monthly summaries (Sessions 1-92 documented)
├── DOCUMENTATION-HYGIENE-GUIDE.md  # Cleanup guide
└── CLEANUP-PROMPT-2026-02.md       # Cleanup phases
```

**Key Files:**
- **Monthly Summaries:** `docs/08-projects/summaries/2026-01.md`, `2026-02.md`
  - 70+ sessions per month summarized
  - 10 anti-patterns + 8 established patterns documented
  - Reference these to avoid repeating mistakes

**Cleanup:** Use `/cleanup-projects` skill weekly (~15 min)

### Documentation Index

| Topic | Location |
|-------|----------|
| Troubleshooting | `docs/02-operations/troubleshooting-matrix.md` |
| Session learnings | `docs/02-operations/session-learnings.md` |
| System features | `docs/02-operations/system-features.md` |
| Doc standards | `docs/05-development/DOCUMENTATION-STANDARDS.md` |
| Architecture | `docs/01-architecture/` |
| Runbooks | `docs/02-operations/runbooks/` |
| **Projects** | `docs/08-projects/current/` |
| **Monthly summaries** | `docs/08-projects/summaries/` |
| Handoffs | `docs/09-handoff/` |

## Feature References

For detailed documentation on these features, see `docs/02-operations/system-features.md`:

- **Heartbeat System** - Firestore-based processor health tracking
- **Evening Analytics** - Same-night game processing (6 PM, 10 PM, 1 AM ET)
- **Early Predictions** - 2:30 AM predictions with REAL_LINES_ONLY mode
- **Model Attribution** - Track which model file generated predictions
- **Signal System** - GREEN/YELLOW/RED daily prediction signals
