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
7. [Anti-Patterns Discovered](#anti-patterns-discovered)
8. [Established Patterns](#established-patterns)

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

---

## Nested Metadata Access Pattern (Session 88)

**Symptom**: `NoneType has no attribute 'get'` when accessing nested metadata fields in BigQuery RECORD columns

**Cause**: Accessing nested fields with `.get('metadata').get('field')` fails when `metadata` is NULL

**Example Failure**:
```python
# WRONG - fails when metadata is NULL
model_file = prediction.get('metadata').get('model_file')
# TypeError: 'NoneType' object has no attribute 'get'
```

**Fix**: Use safe nested access pattern:
```python
# CORRECT - handles NULL metadata gracefully
model_file = prediction.get('metadata', {}).get('model_file')
# Returns None if metadata is NULL, doesn't crash
```

**Real Example**: Session 88 - Model attribution NULL bug in `subset_picks_notifier.py`
- Phase 6 exporters crashed when predictions lacked metadata
- Fixed by using `.get('metadata', {})` pattern throughout

**Prevention**: Always use empty dict default when accessing nested RECORD fields

---

## Anti-Patterns Discovered

Patterns that led to bugs or wasted effort in real sessions.

### 1. Assumption-Driven Debugging (Sessions 75, 76)

**Anti-Pattern**: Make assumptions about root cause and implement fixes without investigation

**Example**: Session 75 - Assumed CloudFront blocking was "random bad luck"
- Wrote fix for hypothetical race condition
- Real cause: IP blocking due to rapid requests from same source
- Wasted 2 hours on wrong fix

**Better Approach**:
1. Reproduce the issue first
2. Check logs/metrics for actual failure patterns
3. Confirm root cause with data
4. Then implement fix

### 2. Silent Failure Acceptance (Sessions 59, 62)

**Anti-Pattern**: Processor completes successfully but writes 0 records, no alerts raised

**Example**: Session 59 - Backfill "completed" with 0 records written
- Firestore published 5/5 completion events
- BigQuery had zero rows
- No alerts triggered
- Discovered days later during validation

**Better Approach**:
1. Always verify write counts match expectations
2. Add post-write validation: `assert records_written > 0`
3. Emit metrics for record counts
4. Alert on unexpected zero-record writes

### 3. Documentation Drift (Sessions 71-80)

**Anti-Pattern**: Implement features/fixes but don't update CLAUDE.md, session-learnings.md

**Example**: Phase 6 exporters built over 10 sessions, never added to system-features.md
- New sessions couldn't find documentation
- Repeated questions about "where are the exporters?"
- Wasted time searching codebase

**Better Approach**:
1. Update root docs immediately after feature ships
2. Add to CLAUDE.md quick reference
3. Create detailed docs in system-features.md
4. Include in monthly summary

### 4. Copy-Paste Schema Errors (Session 58)

**Anti-Pattern**: Copy schema from similar table, forget to update field names

**Example**: Session 58 - Upcoming game context schema copied from historical
- Used `game_date_historical` instead of `game_date_upcoming`
- Caused JOIN failures downstream
- Required schema migration to fix

**Better Approach**:
1. Use schema templates, not copy-paste
2. Run schema validation: `validate_schema_fields.py`
3. Test with real data before deploying
4. Review schema diffs in PRs

### 5. Recency Bias in ML (V9 Recency Experiments)

**Anti-Pattern**: Assume recent games matter more, discard historical data

**Example**: V9 recency experiments (Sessions 72-78)
- Tried 10-game, 20-game, 30-game rolling windows
- All performed WORSE than full historical approach
- Hypothesis: Player consistency requires full season context

**Learning**: Historical data > recency for NBA player props
- Keep full season training data
- Recent games already weighted via feature engineering
- Don't throw away data based on intuition

### 6. Single-Point Validation (Session 85)

**Anti-Pattern**: Test fix with one example, assume it works everywhere

**Example**: Session 85 - Fixed game_id mismatch for one game
- Verified fix worked for LAL vs GSW
- Deployed to production
- Failed for other games with different format (AWAY_HOME vs HOME_AWAY)

**Better Approach**:
1. Test with 10+ diverse examples
2. Check edge cases (doubleheaders, postponements)
3. Run validation query across full date range
4. Verify no regressions in other code

### 7. Premature Optimization (Session 60)

**Anti-Pattern**: Optimize code before measuring performance bottleneck

**Example**: Session 60 - Tried to parallelize player processing
- Added ProcessPoolExecutor complexity
- Gained 3% speedup
- Introduced __pycache__ import bugs
- Real bottleneck: BigQuery query, not Python loops

**Better Approach**:
1. Profile first: Identify actual bottleneck
2. Optimize the bottleneck, not random code
3. Measure before/after improvement
4. Keep it simple unless proven necessary

### 8. Batch Without Bounds (Session 64)

**Anti-Pattern**: Batch writes without max batch size limit

**Example**: Session 64 - BigQueryBatchWriter with unlimited batching
- Accumulated 50,000 predictions in memory
- Exceeded Cloud Run memory limit
- OOMKilled mid-batch, lost all data

**Better Approach**:
1. Set max batch size (e.g., 1,000 records)
2. Flush periodically (e.g., every 30 seconds)
3. Monitor memory usage
4. Handle flush errors gracefully

### 9. Deploy Without Verification (Sessions 55, 67)

**Anti-Pattern**: Deploy to Cloud Run, assume it worked

**Example**: Session 67 - Deployed prediction-worker, bug still present
- Assumed deployment succeeded
- Checked logs 2 hours later, saw old code running
- Deployment had failed silently due to symlink issue

**Better Approach**:
1. Wait for deployment completion
2. Check deployed commit SHA: `gcloud run services describe ... --format="value(metadata.labels.commit-sha)"`
3. Verify fix in logs immediately after deployment
4. Use `./bin/check-deployment-drift.sh` regularly

### 10. Ignore Schema Warnings (Session 81)

**Anti-Pattern**: BigQuery warns about REPEATED field NULL, ignore it

**Example**: Session 81 - Schema allowed NULL for REPEATED field
- Warning: "REPEATED fields should use [] not NULL"
- Ignored warning, deployed anyway
- Later: JSON parsing errors when reading field
- Had to migrate to `field or []` pattern throughout codebase

**Better Approach**:
1. Fix warnings before deploying
2. REPEATED fields: Always use `[]` not NULL
3. Update schema to prevent NULLs: `MODE REPEATED NOT NULL`
4. Add validation to catch this in tests

---

## Established Patterns

Proven patterns that worked well and should be repeated.

### 1. Multi-Agent Investigation (Session 76 - CatBoost V8 Incident)

**Pattern**: When facing complex issues, spawn multiple parallel agents to investigate different angles

**Example**: CatBoost V8 sudden accuracy drop
- Agent 1: Check training data quality
- Agent 2: Compare V8 vs V7 predictions
- Agent 3: Analyze recent games for patterns
- Agent 4: Validate feature engineering
- Agent 5: Check for data cascade issues
- Agent 6: Review deployment logs

**Outcome**: 6-hour investigation identified root cause (feature engineering bug)

**When to Use**: Debugging incidents with unclear root cause, need multiple hypotheses tested in parallel

### 2. Edge-Based Filtering (V9 Production Strategy)

**Pattern**: Filter predictions by confidence edge, not raw win rate

**Discovery**: 73% of predictions have edge < 3 and lose money (-8% ROI)

**Strategy**:
- **All bets (no filter)**: 54.7% hit rate, +4.5% ROI
- **Medium edge (3+)**: 65.0% hit rate, +24.0% ROI
- **High edge (5+)**: 79.0% hit rate, +50.9% ROI

**Implementation**: Always use `WHERE ABS(predicted_points - line_value) >= 3.0` for production picks

**When to Use**: Any prediction filtering or API exports

### 3. Signal-Aware Betting (Dynamic Subset System)

**Pattern**: Adjust bet volume based on daily prediction quality signal

**Signals**:
- **GREEN day**: >15 high-edge picks → Bet medium+ edge (82% hit rate)
- **YELLOW day**: 5-15 high-edge picks → Bet high-edge only (68% hit rate)
- **RED day**: <5 high-edge picks → Skip or high-edge only (51% hit rate)

**Outcome**: Avoids betting on low-quality days, concentrates capital on high-quality days

**When to Use**: Daily betting strategy, capital allocation

### 4. Validation-First Development (Sessions 83-87)

**Pattern**: Write validation scripts BEFORE implementing features

**Process**:
1. Define what "correct" looks like
2. Write validation query to check correctness
3. Run validation on current state (expect failures)
4. Implement feature
5. Run validation again (expect passes)

**Example**: Phase 6 exporters
- Wrote validation query: "Verify all high-edge picks exported"
- Ran before implementation: 0 files found (expected)
- Implemented exporters
- Ran after: All picks present ✅

**When to Use**: Any new feature or data pipeline work

### 5. Monthly Model Retraining (V9 Workflow)

**Pattern**: Retrain models monthly with trailing 90-day window

**Rationale**: NBA meta changes (injuries, trades, coaching changes)

**Workflow**:
```bash
# First day of month
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31
```

**Validation**:
1. Compare hit rate: New model >= baseline
2. Verify edge distribution: Similar to previous month
3. Check model file size: Should be ~10-15 MB
4. Deploy if validation passes

**When to Use**: First week of each month during NBA season

### 6. Batch Writer Pattern (All Processors)

**Pattern**: Use BigQueryBatchWriter for all bulk writes

**Anti-Pattern**: Individual writes in loops (`client.insert_rows_json()` per record)

**Correct Pattern**:
```python
from shared.utils.bigquery_batch_writer import get_batch_writer

writer = get_batch_writer(table_id, batch_size=1000)
for record in records:
    writer.add_record(record)  # Auto-batches, auto-flushes
# Final flush happens automatically on context exit
```

**Benefits**:
- 90%+ quota savings
- Faster writes
- Automatic retry logic
- Memory-bounded (max 1,000 records in memory)

**When to Use**: Any processor writing > 10 records

### 7. Partition Filter Enforcement (All Queries)

**Pattern**: Always include partition filter in BigQuery queries

**Reason**: Massive performance gains, cost savings

**Example**:
```sql
-- WRONG - scans entire table (expensive)
SELECT * FROM nba_raw.nbac_schedule WHERE game_id = 'xyz'

-- CORRECT - scans only relevant partition (fast)
SELECT * FROM nba_raw.nbac_schedule
WHERE game_date = '2026-02-02'  -- Partition filter
  AND game_id = 'xyz'
```

**Enforcement**: Pre-commit hook validates queries have partition filters

**When to Use**: Every BigQuery query in production code

### 8. Opus Architectural Review (Phase 6 Implementation)

**Pattern**: Use Opus model for architectural decisions before coding

**Process**:
1. Write detailed prompt with requirements
2. Ask Opus to design architecture
3. Review Opus's plan (6 agents spawned in Session 91)
4. Refine based on feedback
5. Implement using Sonnet

**Benefits**:
- Catches design flaws early
- Considers edge cases upfront
- Provides multiple alternatives
- Documents decision rationale

**When to Use**: New features, major refactors, data pipeline changes

**Cost**: ~$2-5 per architectural review (worth it to avoid rework)
