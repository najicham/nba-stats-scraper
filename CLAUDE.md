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
# Latest: 2026-02-02-SESSION-71-FINAL-HANDOFF.md
```

### 2. Run Daily Validation
```bash
/validate-daily
```

### 3. Check Deployment Drift
```bash
./bin/check-deployment-drift.sh --verbose
```

### 4. Manual Scraper Triggers (When Needed)

**Trade Detection & Registry Update (FULLY AUTOMATED - Session 74)**

System now automatically updates player registry within 30 minutes of trade detection:

```bash
# Automated Flow (no manual triggers needed):
# 1. Player movement scraper: 8 AM & 2 PM ET (detects trades)
# 2. Registry processor: 8:10 AM & 2:10 PM ET (updates teams)
# 3. BR rosters: 6:30 AM ET daily (validation)

# Manual triggers (if needed for testing):
# Player movement
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_movement","year":"2026","group":"prod"}'

# Registry update from player movement (immediate)
./bin/process-player-movement.sh --lookback-hours 48

# BR roster backfill (validation only, not needed for trades)
gcloud run jobs execute br-rosters-backfill --region=us-west2
# Wait 2-3 min, then:
PYTHONPATH=. GCP_PROJECT_ID=nba-props-platform \
python backfill_jobs/raw/br_roster_processor/br_roster_processor_raw_backfill.py \
  --season 2024 --teams all
```

**Registry Update Latency:**
- **Before Session 74**: 24-48 hours (waited for Basketball Reference)
- **After Session 74**: 30 minutes (uses NBA.com player movement data)

**Trade Deadline Ready:** ✅ Fully automated, no manual intervention needed

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

## ML Models

### Current Production Model: CatBoost V9

| Property | Value |
|----------|-------|
| System ID | `catboost_v9` |
| Training | Current season only (Nov 2025+) |
| Features | 33 (same as V8) |
| Premium Hit Rate | 56.5% |
| High-Edge Hit Rate | 72.2% |
| MAE | 4.82 |

**Why V9?** V8's 84% hit rate was fake due to data leakage (Session 66). V9 is trained on clean, current season data only.

### Model Version Control

```bash
# Default: V9 (current season training)
CATBOOST_VERSION=v9 ./bin/deploy-service.sh prediction-worker

# Rollback to V8 if needed
CATBOOST_VERSION=v8 ./bin/deploy-service.sh prediction-worker
```

### Monthly Retraining

V9 is designed for monthly retraining:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31
```

**See:** `docs/08-projects/current/ml-challenger-experiments/` for full documentation.

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

### Grading Table Selection (Session 68 Learning)

**CRITICAL**: Always verify grading completeness before model analysis.

**Two sources of graded prediction data:**

| Table | Use For | Grading Status |
|-------|---------|----------------|
| `prediction_accuracy` | Live production analysis, historical data | Complete for production, may lag for backfills |
| `player_prop_predictions` + `player_game_summary` join | Backfilled predictions, any analysis with incomplete grading | Always complete |

**Pre-Analysis Verification (REQUIRED)**:

```sql
-- Check grading completeness before analyzing a model
SELECT
  system_id,
  COUNT(*) as predictions,
  (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy pa
   WHERE pa.system_id = p.system_id AND pa.game_date >= DATE('2026-01-09')) as graded
FROM nba_predictions.player_prop_predictions p
WHERE system_id = 'catboost_v9' AND game_date >= DATE('2026-01-09')
GROUP BY system_id
```

**Decision Rule**:
- `graded/predictions >= 80%` → Use `prediction_accuracy`
- `graded/predictions < 80%` → Use join approach (below)

**Join Approach for Incomplete Grading**:

```sql
-- When prediction_accuracy is incomplete, use this pattern
SELECT
  p.system_id,
  CASE WHEN ABS(p.predicted_points - p.current_points_line) >= 5 THEN 'High Edge' ELSE 'Other' END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9'
  AND p.current_points_line IS NOT NULL
GROUP BY 1, 2
```

**Why This Matters**: Session 68 analyzed V9 using `prediction_accuracy` (94 records) instead of `player_prop_predictions` (6,665 records). Wrong conclusion: "42% hit rate". Actual: **79.4% high-edge hit rate**.

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
-- Standard hit rate query (use catboost_v9 for new predictions, catboost_v8 for historical)
SELECT
  'Premium (92+ conf, 3+ edge)' as filter,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'  -- or 'catboost_v8' for pre-Feb 2026
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

## Heartbeat System

**Purpose:** Processors emit periodic heartbeats to Firestore to track health and progress in the unified dashboard.

**Implementation:** `shared/monitoring/processor_heartbeat.py`

### How It Works

1. **Each processor has ONE Firestore document** identified by `processor_name`
2. **Heartbeats update this single document** with current status, progress, timestamp
3. **Dashboard queries Firestore** to show health score and recent activity
4. **Document structure:**
   ```python
   {
       "processor_name": "PlayerGameSummaryProcessor",
       "status": "running",  # or "completed", "failed"
       "last_heartbeat": timestamp,
       "progress": {"current": 50, "total": 100},
       "data_date": "2026-02-01",
       "run_id": "abc123"
   }
   ```

### Critical Design: One Document Per Processor

**Correct implementation (current):**
```python
@property
def doc_id(self) -> str:
    """Uses processor_name as ID - each processor has ONE document."""
    return self.processor_name
```

**Anti-pattern (old, WRONG):**
```python
# DON'T DO THIS - creates unbounded document growth!
def doc_id(self) -> str:
    return f"{self.processor_name}_{self.data_date}_{self.run_id}"
```

**Why this matters:**
- Old pattern created 106,000+ documents for 30 processors (3,500 new docs/day)
- Dashboard showed low health scores (39/100) due to stale duplicates
- Firestore costs and query performance degraded

### When to Run Cleanup Script

Run `bin/cleanup-heartbeat-docs.py` if:
- Dashboard health score is unexpectedly low (<50/100)
- Firestore collection has >100 documents (should be ~30)
- After deploying heartbeat fix to all services

**Usage:**
```bash
# Preview what will be deleted
python bin/cleanup-heartbeat-docs.py --dry-run

# Execute cleanup (requires confirmation)
python bin/cleanup-heartbeat-docs.py
```

**Expected result:** Reduces collection from 106k+ docs to ~30 docs (one per processor)

### Verifying Heartbeat System

```bash
# Check Firestore document count (should be ~30)
gcloud firestore collections list

# Check dashboard health score (should be 70+/100)
curl https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health

# View recent heartbeats in logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND jsonPayload.message=~"Heartbeat"' \
  --limit=20 \
  --format=json
```

### Troubleshooting

**Low dashboard health score:**
1. Check if all services deployed with heartbeat fix
2. Run cleanup script to remove old documents
3. Verify Firestore collection size (~30 docs)

**Firestore collection growing:**
- Indicates a service still using old heartbeat format
- Deploy latest version of service with heartbeat fix
- Run cleanup script after deployment

**References:**
- Implementation: `shared/monitoring/processor_heartbeat.py`
- Cleanup script: `bin/cleanup-heartbeat-docs.py`
- Session 61 handoff: `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md`

## Evening Analytics Processing (Session 73)

**Purpose:** Process completed games same-night instead of waiting until 6 AM next day.

### Evening Schedulers

| Job | Schedule (ET) | Purpose |
|-----|---------------|---------|
| `evening-analytics-6pm-et` | 6 PM Sat/Sun | Weekend matinees |
| `evening-analytics-10pm-et` | 10 PM Daily | 7 PM games |
| `evening-analytics-1am-et` | 1 AM Daily | West Coast games |
| `morning-analytics-catchup-9am-et` | 9 AM Daily | Safety net |

### Boxscore Fallback

`PlayerGameSummaryProcessor` normally requires `nbac_gamebook_player_stats` (from PDF parsing, available next morning). For evening processing, it falls back to `nbac_player_boxscores` (scraped live during games).

**How it works:**
```
Check nbac_gamebook_player_stats → Has data? → Use gamebook (gold)
                                      ↓ No
Check nbac_player_boxscores (Final) → Has data? → Use boxscores (silver)
                                      ↓ No
                                Skip processing
```

**Configuration:** `USE_NBAC_BOXSCORES_FALLBACK = True` in `player_game_summary_processor.py`

**Verify which source was used:**
```sql
SELECT game_date,
  COUNTIF(primary_source_used = 'nbac_boxscores') as from_boxscores,
  COUNTIF(primary_source_used = 'nbac_gamebook') as from_gamebook
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC
```

**References:**
- Implementation: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- Project docs: `docs/08-projects/current/evening-analytics-processing/`
- Session 73 handoff: `docs/09-handoff/2026-02-02-SESSION-73-HANDOFF.md`

## Early Prediction Timing (Session 74)

**Purpose:** Generate predictions earlier (2:30 AM ET) using REAL_LINES_ONLY mode, instead of waiting until 7 AM.

### Background

Vegas lines are available at ~2:00 AM ET (from BettingPros), but predictions were running at 7:00 AM. This 5-hour delay meant predictions might miss optimal timing for user consumption.

### Prediction Schedulers

| Job | Schedule (ET) | Mode | Expected Players |
|-----|---------------|------|-----------------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | ~140 |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | ~200 |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch stragglers |

### REAL_LINES_ONLY Mode

The `require_real_lines` parameter filters out players without real betting lines:

```bash
# Early predictions - only players WITH real lines
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "require_real_lines": true, "force": true}'
```

**How it works:**
- Players with `line_source='ACTUAL_PROP'` are included
- Players with `line_source='NO_PROP_LINE'` are filtered out
- Results in ~140 high-quality predictions at 2:30 AM

### Verify Line Availability

```sql
-- Check lines available for today
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL;

-- Check line source distribution for today's predictions
SELECT line_source, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY line_source;
```

**References:**
- Implementation: `predictions/coordinator/player_loader.py`, `predictions/coordinator/coordinator.py`
- Setup script: `bin/orchestrators/setup_early_predictions_scheduler.sh`
- Project docs: `docs/08-projects/current/prediction-timing-improvement/DESIGN.md`

## Common Issues and Fixes

### Schema Mismatch
**Symptom**: BigQuery writes fail with "Invalid field" error
**Cause**: Code writes fields that don't exist in BigQuery schema
**Fix**:
1. Run `python .pre-commit-hooks/validate_schema_fields.py` to detect
2. Add missing fields with `ALTER TABLE ... ADD COLUMN`
3. Update schema SQL file in `schemas/bigquery/`

### Silent BigQuery Write Failure (Session 59)
**Symptom**: Processor completes successfully, Firestore completion events publish, but BigQuery table has zero records
**Cause**: BigQuery write fails (wrong table reference, missing dataset, permissions) but processor doesn't fail the request
**Real Example**: Session 59 - `upcoming_team_game_context` backfill appeared successful, published Firestore completion (5/5), but wrote 0 records due to missing `dataset_id` in table reference
**Detection**:
```bash
# Check logs for BigQuery 404 errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND severity>=ERROR
  AND textPayload=~"404.*Dataset"' \
  --limit=20 --freshness=2h

# Verify record counts match expectations
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as records, MAX(processed_at) as latest
  FROM nba_analytics.upcoming_team_game_context
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
  GROUP BY game_date"
```
**Common Causes**:
1. **Missing dataset in table reference**: `f"{project}.{table}"` instead of `f"{project}.{dataset}.{table}"`
2. **Wrong dataset name**: Typo or project name duplicated (e.g., `nba-props-platform:nba-props-platform`)
3. **Permission errors**: Service account lacks BigQuery write permissions
4. **Table doesn't exist**: Processor assumes table exists but it was deleted/renamed

**Fix**:
1. Always use `f"{self.project_id}.{self.dataset_id}.{self.table_name}"` pattern from base class
2. Add error handling that fails completion if BigQuery writes fail
3. Add integration tests that verify actual BigQuery writes
4. Monitor for "404 Not found: Dataset" errors in production logs

**Prevention**:
```python
# WRONG - Missing dataset
table_id = f"{self.project_id}.{self.table_name}"

# CORRECT - Use dataset_id from base class
table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
```

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

### BigQuery Partition Filter Required (Sessions 73-74)
**Symptom**: 400 BadRequest errors with message "Cannot query over table without a filter over column(s) 'game_date' that can be used for partition elimination"
**Cause**: Querying partitioned table without required partition filter
**Real Example**: Sessions 73-74 - cleanup processor queried 21 Phase 2 tables, but 12 required partition filters
**Impact**:
- Scheduler returning 400 errors
- Cleanup processor failing silently
- Automation broken

**Detection**:
```bash
# Check for partition filter errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND severity>=ERROR
  AND textPayload=~"partition elimination"' \
  --limit=10

# Check table partition requirements
bq show --format=json nba-props-platform:nba_raw.TABLE_NAME | \
  jq '{requirePartitionFilter: .requirePartitionFilter, partitionField: .timePartitioning.field}'
```

**Root Cause**:
- Tables with `requirePartitionFilter: true` MUST have partition column filter in WHERE clause
- 12 of 21 Phase 2 tables require partition filters (game_date or roster_date)
- Query only filtered by `processed_at`, not partition columns

**Fix Pattern**:
```python
# Map tables to their partition fields
partition_fields = {
    'espn_team_rosters': 'roster_date',  # Non-standard partition field
    # Most tables use 'game_date'
}

# List tables requiring partition filters
partitioned_tables = [
    'bdl_player_boxscores', 'espn_scoreboard', 'espn_team_rosters',
    'espn_boxscores', 'bigdataball_play_by_play', 'odds_api_game_lines',
    'bettingpros_player_points_props', 'nbac_schedule', 'nbac_team_boxscore',
    'nbac_play_by_play', 'nbac_scoreboard_v2', 'nbac_referee_game_assignments'
]

# Add conditional partition filter
if table in partitioned_tables:
    partition_field = partition_fields.get(table, 'game_date')
    partition_filter = f"AND {partition_field} >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
else:
    partition_filter = ""

# Build query with both filters
query = f"""
    SELECT * FROM `nba_raw.{table}`
    WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
    {partition_filter}
"""
```

**Key Learnings**:
1. Check table schema for `requirePartitionFilter` before querying
2. Partition filter lookback should be wider than processing lookback (7 days vs 4 hours)
3. Different tables may use different partition fields (game_date vs roster_date)
4. Multiple bugs can cause same 400 error symptom

**Prevention**:
- Query table schema before building UNION queries
- Add integration tests for full scheduler flow
- Monitor for partition elimination errors specifically

**References**: Sessions 73-74 handoffs, `orchestration/cleanup_processor.py`

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

### Monitoring Permissions Error (Session 61)
**Symptom**: `403 Permission 'monitoring.timeSeries.create' denied` errors in logs
**Cause**: Service account missing `roles/monitoring.metricWriter` IAM role
**Impact**: Custom metrics (hit rate, latency, etc.) not recording to Cloud Monitoring
**Fix**:
```bash
# Grant monitoring write permissions to service account
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/monitoring.metricWriter"

# Example for prediction-worker
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```
**Verification**:
```bash
# Check metrics are now recording
gcloud monitoring metrics-descriptors list --filter="custom.googleapis.com/prediction"

# View recent metrics
gcloud monitoring time-series list \
  --filter='metric.type="custom.googleapis.com/prediction/hit_rate"' \
  --interval-start-time="2026-02-01T00:00:00Z"
```
**Prevention**: When creating new Cloud Run services, ensure service account has monitoring.metricWriter role
**References**: Session 61 handoff Part 3

### Backfill with Stale Code (Session 64)
**Symptom**: Predictions have poor hit rate despite code fix being committed
**Cause**: Backfill ran with OLD code that wasn't deployed yet
**Real Example**: Session 64 - Feature enrichment fix committed Jan 30 03:17 UTC, but backfill ran at 07:41 UTC with OLD code. Fix wasn't deployed until 19:10 UTC (12 hours too late). Result: 50.4% hit rate instead of expected 58%+
**Impact**:
- 35% higher prediction error (MAE 5.8 vs 4.3)
- 26-point collapse in high-edge hit rate (76.6% → 50.9%)
- Required full re-generation of 20 days of predictions

**CRITICAL RULE: Always Deploy Before Backfill**
```bash
# 1. Verify deployment matches latest commit BEFORE any backfill
./bin/verify-deployment-before-backfill.sh prediction-worker

# 2. If out of date, deploy first
./bin/deploy-service.sh prediction-worker

# 3. Only then run the backfill
PYTHONPATH=. python backfill_jobs/predictions/backfill_v8_predictions.py --start-date 2026-01-09 --end-date 2026-01-28
```

**Detection**: Compare deployed commit to latest main
```bash
# Check deployed commit
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to repo
git log -1 --format="%h"
```

**Prevention**:
1. **Pre-backfill check script**: `./bin/verify-deployment-before-backfill.sh <service-name>`
2. **New tracking fields**: `build_commit_sha`, `predicted_at` in predictions table
3. **Execution log**: `prediction_execution_log` table for full audit trail

**References**: Session 64 handoff, `docs/08-projects/current/feature-quality-monitoring/V8-INVESTIGATION-LEARNINGS.md`

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
