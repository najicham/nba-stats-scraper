# Session Learnings - Historical Bug Fixes & Patterns

This document contains historical bug fixes and lessons learned from Claude Code sessions.
For current troubleshooting, see `troubleshooting-matrix.md`.

---

## Table of Contents

1. [BigQuery Issues](#bigquery-issues)
2. [Deployment Issues](#deployment-issues)
3. [Data Quality Issues](#data-quality-issues)
4. [Prediction System Issues](#prediction-system-issues)
5. [Orchestration Issues](#orchestration-issues)
6. [Monitoring Issues](#monitoring-issues)

---

## BigQuery Issues

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
1. Missing dataset in table reference: `f"{project}.{table}"` instead of `f"{project}.{dataset}.{table}"`
2. Wrong dataset name: Typo or project name duplicated
3. Permission errors: Service account lacks BigQuery write permissions
4. Table doesn't exist: Processor assumes table exists but it was deleted/renamed

**Fix Pattern**:
```python
# WRONG - Missing dataset
table_id = f"{self.project_id}.{self.table_name}"

# CORRECT - Use dataset_id from base class
table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
```

---

### BigQuery Partition Filter Required (Sessions 73-74)

**Symptom**: 400 BadRequest errors with message "Cannot query over table without a filter over column(s) 'game_date' that can be used for partition elimination"

**Cause**: Querying partitioned table without required partition filter

**Tables Requiring Partition Filters**:
```python
partitioned_tables = [
    'bdl_player_boxscores', 'espn_scoreboard', 'espn_team_rosters',
    'espn_boxscores', 'bigdataball_play_by_play', 'odds_api_game_lines',
    'bettingpros_player_points_props', 'nbac_schedule', 'nbac_team_boxscore',
    'nbac_play_by_play', 'nbac_scoreboard_v2', 'nbac_referee_game_assignments'
]

# Note: espn_team_rosters uses 'roster_date', others use 'game_date'
```

**Fix Pattern**:
```python
if table in partitioned_tables:
    partition_field = partition_fields.get(table, 'game_date')
    partition_filter = f"AND {partition_field} >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
else:
    partition_filter = ""
```

---

### BigQuery REPEATED Field NULL Error (Session 85)

**Symptom**: `JSON parsing error: Only optional fields can be set to NULL. Field: line_values_requested`

**Cause**: Python `None` converts to JSON `null`, but BigQuery REPEATED fields cannot be NULL

**Fix Pattern**:
```python
# WRONG - can be None
'line_values_requested': line_values,

# CORRECT - always use empty list for falsy values
'line_values_requested': line_values or [],
```

---

### Quota Exceeded

**Symptom**: "Exceeded rate limits: too many partition modifications"

**Cause**: Single-row `load_table_from_json` calls

**Fix**:
1. Use `BigQueryBatchWriter` from `shared/utils/bigquery_batch_writer.py`
2. Or use streaming inserts with `insert_rows_json`
3. Or buffer writes and flush in batches

---

## Deployment Issues

### Deployment Drift (Session 58)

**Symptom**: Service missing recent bug fixes, known bugs recurring in production

**Cause**: Manual deployments, no automation - fixes committed but never deployed

**CRITICAL RULE**: After committing bug fixes, ALWAYS deploy immediately:
```bash
./bin/deploy-service.sh <service-name>
```

**Verification**:
```bash
# Check what's currently deployed
gcloud run services describe SERVICE_NAME --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to latest main
git log -1 --format="%h"
```

---

### Backfill with Stale Code (Session 64)

**Symptom**: Predictions have poor hit rate despite code fix being committed

**Cause**: Backfill ran with OLD code that wasn't deployed yet

**CRITICAL RULE**: Always Deploy Before Backfill
```bash
# 1. Verify deployment matches latest commit BEFORE any backfill
./bin/verify-deployment-before-backfill.sh prediction-worker

# 2. If out of date, deploy first
./bin/deploy-service.sh prediction-worker

# 3. Only then run the backfill
```

---

## Data Quality Issues

### BDL Data Quality Issues (Session 41)

**Status**: BDL is DISABLED as backup source (`USE_BDL_DATA = False` in `player_game_summary_processor.py`)

**Monitoring**:
```sql
SELECT * FROM nba_orchestration.bdl_quality_trend ORDER BY game_date DESC LIMIT 7
```

**Re-enabling**: When `bdl_readiness = 'READY_TO_ENABLE'`, set `USE_BDL_DATA = True`

---

### Shot Zone Data Quality (Session 53)

**Symptom**: Shot zone rates look wrong - paint rate too low (<30%) or three rate too high (>50%)

**Cause**: Mixed data sources - paint/mid from play-by-play (PBP), three_pt from box score

**Fix Applied**: All zone fields now from same PBP source

**Validation**:
```sql
SELECT game_date,
  COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3 AND minutes_played > 0
GROUP BY 1 ORDER BY 1 DESC
```

---

### Validation Timing Confusion (Session 58)

**Symptom**: Validation shows "missing data" but games haven't finished yet

**Key Rule**: Always check game status before assuming data is missing:
```sql
SELECT game_id, home_team_tricode, game_status,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END
FROM nba_reference.nba_schedule
WHERE game_date = '<date-to-check>'
```

---

## Prediction System Issues

### Prediction Deactivation Bug (Session 78)

**Symptom**: Grading shows unexpectedly low coverage; most ACTUAL_PROP predictions have `is_active=FALSE`

**Cause**: Deactivation query partitioned by `(game_id, player_lookup)` but NOT by `system_id`

**Detection**:
```sql
SELECT game_date, line_source, is_active, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND system_id = 'catboost_v9'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
```

**Fix**: Added `system_id` to deactivation partition in `predictions/shared/batch_staging_writer.py:516`

---

### RED Signal Days Performance (Session 70/85)

**Finding**: Pre-game signal (pct_over) correlates strongly with hit rate:
- GREEN days (balanced): **79% high-edge hit rate**
- RED days (heavy UNDER): **63% high-edge hit rate**

**Check today's signal**:
```sql
SELECT daily_signal, pct_over, high_edge_picks
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
```

---

### Grading Table Selection (Session 68)

**CRITICAL**: Always verify grading completeness before model analysis.

**Pre-Analysis Verification**:
```sql
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
- `graded/predictions < 80%` → Use join approach with `player_game_summary`

---

## Orchestration Issues

### Mode-Aware Orchestration (Session 85)

**Finding**: Phase 3→4 orchestrator is MODE-AWARE - different processor expectations by time of day.

| Mode | Expected Processors | When |
|------|-------------------|------|
| **overnight** | 5/5 (all) | 6-8 AM ET |
| **same_day** | 1/1 (upcoming_player_game_context) | 10:30 AM / 5 PM ET |
| **tomorrow** | 1/1 (upcoming_player_game_context) | Variable |

**Check mode-aware completion**:
```bash
PYTHONPATH=. python shared/validation/phase3_completion_checker.py 2026-02-02 --verbose
```

---

## Monitoring Issues

### Monitoring Permissions Error (Session 61)

**Symptom**: `403 Permission 'monitoring.timeSeries.create' denied`

**Fix**:
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/monitoring.metricWriter"
```

---

### Feature Validation Errors

**Symptom**: "fatigue_score=-1.0 outside range"

**Cause**: Validation rejects sentinel values

**Fix**: Update validation in `data_loaders.py` to allow -1 as sentinel

---

## Schema Mismatch

**Symptom**: BigQuery writes fail with "Invalid field" error

**Fix**:
1. Run `python .pre-commit-hooks/validate_schema_fields.py` to detect
2. Add missing fields with `ALTER TABLE ... ADD COLUMN`
3. Update schema SQL file in `schemas/bigquery/`
