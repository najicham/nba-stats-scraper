# Claude Code Instructions

This file contains instructions and context for Claude Code sessions working on the NBA Stats Scraper project.

## Session Philosophy

**Every session should follow these principles:**

1. **Understand root causes, not just symptoms** - When fixing a bug, investigate WHY it happened
2. **Prevent recurrence** - Add validation, tests, or automation to stop issues from happening again
3. **Use agents liberally** - Spawn multiple Task agents in parallel for investigation and fixes
4. **Keep documentation updated** - Update handoff docs, runbooks, and code comments
5. **Fix the system, not just the code** - Schema issues need schema validation, deployment drift needs automation

## Quick Start

### 1. Read the Latest Handoff
```bash
ls -la docs/09-handoff/ | tail -5
# Read the most recent handoff document
```

### 2. Run Daily Validation
```bash
/validate-daily
```

### 3. Check Deployment Drift
```bash
./bin/check-deployment-drift.sh --verbose
```

## Using Agents Effectively

### Parallel Investigation Pattern
When facing multiple issues, spawn agents in parallel:

```
Task(subagent_type="Explore", prompt="Find all places where X happens")
Task(subagent_type="Explore", prompt="Investigate why Y is failing")
Task(subagent_type="general-purpose", prompt="Fix the bug in Z file")
Task(subagent_type="general-purpose", prompt="Migrate component A to use pattern B")
```

### Agent Types and Use Cases

| Agent Type | Use Case | Example |
|------------|----------|---------|
| `Explore` | Research, find patterns, understand code | "Find all BigQuery single-row writes" |
| `general-purpose` | Fix bugs, implement features, run commands | "Fix the NoneType error in metrics_utils.py" |
| `Bash` | Git operations, gcloud, bq queries | Direct bash commands |

### Best Practices

1. **Give detailed prompts** - Include file paths, line numbers, expected behavior
2. **Use Explore for research first** - Understand before changing
3. **Check agent results** - Verify fixes, commit changes
4. **Track in handoff docs** - Document what agents found

## Project Structure

```
nba-stats-scraper/
├── predictions/           # Phase 5 - Prediction worker and coordinator
│   ├── worker/           # Prediction generation
│   └── coordinator/      # Batch orchestration
├── data_processors/      # Phase 2-4 data processing
│   ├── raw/              # Phase 2 - Raw data processors
│   ├── analytics/        # Phase 3 - Analytics processors
│   └── precompute/       # Phase 4 - Precompute processors
├── scrapers/             # Phase 1 - Data scrapers
├── orchestration/        # Phase transition orchestrators
├── shared/               # Shared utilities
├── bin/                  # Scripts and tools
├── schemas/              # BigQuery schema definitions
└── docs/                 # Documentation
```

## Documentation Locations

| Directory | Purpose |
|-----------|---------|
| `docs/01-architecture/` | System architecture, data flow |
| `docs/02-operations/` | Runbooks, deployment, troubleshooting |
| `docs/03-phases/` | Phase-specific documentation |
| `docs/05-development/` | Development guides, best practices |
| `docs/09-handoff/` | Session handoff documents |

## Deployment Patterns

### CRITICAL: Always deploy from repo root

All service Dockerfiles expect to be built from the repository root because they need access to `shared/` modules. Building from within the service directory will fail.

**Correct:**
```bash
./bin/deploy-service.sh prediction-worker
```

**Wrong:**
```bash
cd predictions/worker && gcloud run deploy --source .  # WILL FAIL - no shared/ access
```

### Deployment Script

Use `./bin/deploy-service.sh <service-name>` for all deployments:

| Service | Dockerfile |
|---------|------------|
| prediction-coordinator | predictions/coordinator/Dockerfile |
| prediction-worker | predictions/worker/Dockerfile |
| mlb-prediction-worker | predictions/mlb/Dockerfile |
| nba-phase3-analytics-processors | data_processors/analytics/Dockerfile |
| nba-phase4-precompute-processors | data_processors/precompute/Dockerfile |
| nba-phase2-processors | data_processors/raw/Dockerfile |
| nba-scrapers | scrapers/Dockerfile |

The script:
1. Builds from repo root with correct Dockerfile
2. Tags with commit hash for traceability
3. Sets BUILD_COMMIT and BUILD_TIMESTAMP env vars
4. Deploys to Cloud Run
5. Shows recent logs for verification

### Dockerfile Organization

**See `deployment/dockerfiles/README.md` for complete conventions.**

Key principles:
- Service Dockerfiles stay with service code (e.g., `predictions/worker/Dockerfile`)
- Utility/validator Dockerfiles go in `deployment/dockerfiles/{sport}/`
- NO Dockerfiles at repository root
- ALL builds happen from repository root (for `shared/` module access)

Utility Dockerfiles (validators, backfill jobs) are organized by sport:
- `deployment/dockerfiles/mlb/` - MLB validators and monitors
- `deployment/dockerfiles/nba/` - NBA utilities and backfill jobs

### Startup Verification

Services should use the startup verification utility to log deployment info:

```python
from shared.utils.startup_verification import verify_startup

# At service startup
verify_startup(
    expected_module="coordinator",
    service_name="prediction-coordinator"
)
```

This helps detect deployment issues where wrong code is deployed.

## Key Commands

### Validation
```bash
# Daily validation skill
/validate-daily

# Historical validation
/validate-historical 2026-01-27 2026-01-28

# Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

### BigQuery
```bash
# Check predictions
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1"

# Check feature store
bq query --use_legacy_sql=false "SELECT COUNT(*), COUNT(DISTINCT player_lookup) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"

# Check shot zone data quality (NEW - Jan 2026)
bq query --use_legacy_sql=false "
  SELECT game_date,
    COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete,
    ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
      THEN SAFE_DIVIDE(paint_attempts * 100.0, paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as paint_rate
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 3 AND minutes_played > 0
  GROUP BY 1 ORDER BY 1 DESC"
```

### Grading Tables

**IMPORTANT:** Use the correct grading table:

| Table | Use For | Data Range |
|-------|---------|------------|
| `prediction_accuracy` | **All grading queries** | Nov 2021 - Present (419K+ records) |
| `prediction_grades` | DEPRECATED - do not use | Jan 2026 only (9K records) |

Always query `prediction_accuracy` for grading validation, accuracy metrics, and ML analysis.

### Hit Rate Measurement (IMPORTANT)

**Always use these two standard filters when reporting hit rates:**

| Filter Name | Definition | Use Case |
|-------------|------------|----------|
| **Premium Picks** | `confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3` | Highest hit rate, fewer bets |
| **High Edge Picks** | `ABS(predicted_points - line_value) >= 5` (any confidence) | Larger sample size |

**Don't confuse these metrics:**

| Metric | What It Measures | Good Value |
|--------|------------------|------------|
| **Hit Rate** | % correct OVER/UNDER calls (`prediction_correct = TRUE`) | ≥52.4% |
| **Model Beats Vegas** | % where model closer to actual than Vegas line | ≥50% |

These are DIFFERENT. You can have 78% hit rate but only 40% model-beats-vegas.

**Always show weekly trends** to catch drift - monthly averages can mask recent degradation.

```sql
-- Standard hit rate query
SELECT
  'Premium (92+ conf, 3+ edge)' as filter,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND confidence_score >= 0.92
  AND ABS(predicted_points - line_value) >= 3
  AND prediction_correct IS NOT NULL
```

### Schedule Data

**IMPORTANT:** Use the correct schedule table:

| Use Case | Table | Notes |
|----------|-------|-------|
| General queries | `nba_reference.nba_schedule` | View with clean column names |
| Raw data access | `nba_raw.nbac_schedule` | Requires `WHERE game_date >= ...` partition filter |

**Column names:** `home_team_tricode`, `away_team_tricode`, `game_id`, `game_date`, `game_status`

**Game Status Codes** (IMPORTANT for investigation):
- `game_status = 1`: **Scheduled** - Game has not started yet
- `game_status = 2`: **In Progress** - Game is currently being played
- `game_status = 3`: **Final** - Game has completed

```sql
-- Example: Get today's games with status
SELECT game_id, away_team_tricode, home_team_tricode, game_status,
  CASE game_status
    WHEN 1 THEN 'Scheduled'
    WHEN 2 THEN 'In Progress'
    WHEN 3 THEN 'Final'
  END as status_text
FROM nba_reference.nba_schedule
WHERE game_date = CURRENT_DATE()
```

**Data source:** GCS `gs://nba-scraped-data/nba-com/schedule/` → BigQuery `nba_raw.nbac_schedule` → View `nba_reference.nba_schedule`

### Deployments
```bash
# Check current revisions
gcloud run services describe SERVICE_NAME --region=us-west2 --format="value(status.latestReadyRevisionName)"

# Deploy a service
gcloud run deploy SERVICE_NAME --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/SERVICE_NAME:latest --region=us-west2
```

### Logs
```bash
# Prediction worker logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker"' --limit=50

# Check for errors
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --limit=20
```

## Common Issues and Fixes

### Schema Mismatch
**Symptom**: BigQuery writes fail with "Invalid field" error
**Cause**: Code writes fields that don't exist in BigQuery schema
**Fix**:
1. Run `python .pre-commit-hooks/validate_schema_fields.py` to detect
2. Add missing fields with `ALTER TABLE ... ADD COLUMN`
3. Update schema SQL file in `schemas/bigquery/`

### Deployment Drift (Session 58)
**Symptom**: Service missing recent bug fixes, known bugs recurring in production
**Cause**: Manual deployments, no automation - fixes committed but never deployed
**Real Example**: Session 57 quota fixes (Jan 31) not deployed until Session 58 (Feb 1), causing 24 hours of recurring errors
**Fix**:
1. After committing bug fixes, **ALWAYS deploy immediately**: `./bin/deploy-service.sh <service-name>`
2. **Verify deployment**: Check deployed commit matches latest main
3. Run `./bin/check-deployment-drift.sh --verbose` to detect drift
4. GitHub workflow will create issues for future drift

**Deployment Verification** (CRITICAL after bug fixes):
```bash
# Check what's currently deployed
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to latest main
git log -1 --format="%h"

# If different, redeploy immediately!
./bin/deploy-service.sh nba-phase3-analytics-processors
```

### Quota Exceeded
**Symptom**: "Exceeded rate limits: too many partition modifications"
**Cause**: Single-row `load_table_from_json` calls
**Fix**:
1. Use `BigQueryBatchWriter` from `shared/utils/bigquery_batch_writer.py`
2. Or use streaming inserts with `insert_rows_json`
3. Or buffer writes and flush in batches

### Feature Validation Errors
**Symptom**: "fatigue_score=-1.0 outside range"
**Cause**: Validation rejects sentinel values
**Fix**: Update validation in `data_loaders.py` to allow -1 as sentinel

### BDL Data Quality Issues (Session 41)
**Symptom**: BDL boxscores show ~50% of actual values for some players
**Cause**: BDL API returns inconsistent/incorrect data
**Status**: BDL is DISABLED as backup source (`USE_BDL_DATA = False` in `player_game_summary_processor.py`)
**Monitoring**:
1. Check quality trend: `SELECT * FROM nba_orchestration.bdl_quality_trend ORDER BY game_date DESC LIMIT 7`
2. Look for `bdl_readiness = 'READY_TO_ENABLE'` (requires <5% major discrepancies for 7 consecutive days)
3. Daily automated check runs at 7 PM ET via `data-quality-alerts` Cloud Function
**Re-enabling**: When `bdl_readiness = 'READY_TO_ENABLE'`, set `USE_BDL_DATA = True` in `player_game_summary_processor.py`

### Validation Timing Confusion (Session 58)
**Symptom**: Validation shows "missing data" but games haven't finished yet
**Cause**: Checking data for in-progress games, timezone confusion (UTC vs ET)
**Real Example**: Jan 31 validation at 8:56 PM EST showed "missing data" - games were in progress!
**Fix**:
1. **Always check current time** when investigating "missing" data
2. Use correct validation mode:
   - **Pre-game check**: For today's games (8 AM - 6 PM ET) - expect predictions but no final stats
   - **Post-game check**: For yesterday's games (6 AM - noon ET next day) - expect complete data
3. Verify game status in schedule before assuming scraper failure:
```bash
# Check if games have actually finished
bq query --use_legacy_sql=false "
SELECT game_id, home_team_tricode, game_status,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END as status
FROM nba_reference.nba_schedule
WHERE game_date = '<date-to-check>'"
```
4. **Timezone awareness**:
   - UTC vs ET vs PT can differ by dates
   - Feb 1 01:00 UTC = Jan 31 20:00 EST (still Saturday night!)

### Shot Zone Data Quality (FIXED Jan 2026)
**Symptom**: Shot zone rates look wrong - paint rate too low (<30%) or three rate too high (>50%)
**Cause**: Mixed data sources - paint/mid from play-by-play (PBP), three_pt from box score
**Impact**: When PBP missing, paint/mid = 0 but three_pt = actual value → corrupted rates
**Fix Applied**: All zone fields now from same PBP source (Session 53)
**Validation**:
```sql
-- Check shot zone completeness (expect 50-90% depending on BDB availability)
SELECT game_date,
  COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3 AND minutes_played > 0
GROUP BY 1 ORDER BY 1 DESC
```
**Prevention**:
- Use `WHERE has_complete_shot_zones = TRUE` filter for ML training and analytics
- Daily validation checks zone completeness and rate ranges
- `has_complete_shot_zones` flag tracks data integrity
**References**:
- Fix documentation: `docs/09-handoff/2026-01-31-SESSION-53-SHOT-ZONE-FIX-COMPLETE.md`
- Troubleshooting: `docs/02-operations/troubleshooting-matrix.md` Section 2.4

## Prevention Mechanisms

### Pre-commit Hooks
```yaml
# Schema validation - blocks commits with schema mismatches
- id: validate-schema-fields
  entry: python .pre-commit-hooks/validate_schema_fields.py
```

### GitHub Workflows
```yaml
# Deployment drift check - runs daily, creates issues
.github/workflows/check-deployment-drift.yml
```

### Batching Patterns
```python
# Use BigQueryBatchWriter for high-frequency writes
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches and flushes
```

## Handoff Document Template

When ending a session, create a handoff document at `docs/09-handoff/YYYY-MM-DD-SESSION-N-HANDOFF.md`:

```markdown
# Session N Handoff - [Date]

## Session Summary
[What was accomplished]

## Fixes Applied
[Table of fixes with files and commits]

## Root Causes Identified
[Why issues happened, not just what was fixed]

## Prevention Mechanisms Added
[Validation, automation, tests added]

## Known Issues Still to Address
[What's left for future sessions]

## Next Session Checklist
[Prioritized TODO list]

## Key Learnings
[Insights for future sessions]
```

## Project Conventions

### Commit Messages
```
type: Short description

Longer explanation if needed.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Style
- Python 3.11+
- Type hints for public APIs
- Docstrings for classes and complex functions
- Logging with structured fields

### Testing
```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/path/to/test.py -v
```

## GCP Resources

| Resource | Location |
|----------|----------|
| Project | nba-props-platform |
| Region | us-west2 |
| Registry | us-west2-docker.pkg.dev/nba-props-platform/nba-props |
| BigQuery | nba_predictions, nba_analytics, nba_raw, nba_orchestration |

## Contact and Escalation

For issues outside Claude's scope:
- Check `docs/02-operations/troubleshooting-matrix.md`
- Review recent handoff documents
- Check GitHub issues for known problems
