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

### Deployment Drift - Recurring Pattern (Sessions 64, 81, 82, 97, 128)

**Symptom**: Bug fixes committed to repository but not deployed to production services, causing "already fixed" bugs to recur

**Cause**: Manual deployment process with no automated drift detection

**Real Examples**:
- Session 128: 3 services 8+ hours stale (phase3, coordinator, worker)
- Session 97: Worker env vars fix committed but not deployed
- Session 82: Coordinator fix committed but not deployed
- Session 81: Worker fix committed but not deployed
- Session 64: Backfill ran with OLD code 12 hours after fix committed

**Impact**:
- Degraded system performance (missing optimizations)
- Bugs appear "fixed" in code but still occur in production
- Confusion during debugging (code looks correct, old version running)
- Time wasted re-investigating "fixed" issues

**Detection**:
```bash
# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Check specific service
gcloud run services describe SERVICE --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
git log -1 --format="%h"  # Compare
```

**Prevention** (Session 128 - See `docs/02-operations/DEPLOYMENT-DRIFT-PREVENTION.md`):
1. **Layer 1**: Automated drift monitoring (Cloud Function every 2 hours)
2. **Layer 2**: Post-commit hook reminder
3. **Layer 3**: Pre-prediction validation gate (blocks stale worker)
4. **Layer 4**: CI/CD auto-deploy on merge to main
5. **Layer 5**: Deployment dashboard with status visibility

**Immediate Fix**:
```bash
./bin/deploy-service.sh SERVICE_NAME
```

**Long-term Fix**: Deploy drift monitoring Cloud Function
```bash
./bin/infrastructure/setup-drift-monitoring.sh
```

---

### Timeout Cascade - Bug Fix Reveals Performance Issue (Session 201)

**Symptom**: After fixing a crash bug, system starts timing out at exactly 540 seconds. Files that were previously created (due to fast crash) are now missing.

**Real Example**: Phase 6 export - Fixed NoneType crash in `tonight_player_exporter.py`. Instead of crashing at 1 second, it now successfully processes all 200+ players, taking 400-600 seconds and consuming the entire 540s Cloud Function timeout BEFORE reaching critical exports (subset-picks, daily-signals).

**Evidence**:
```
18:55 execution: latency=540.000711350s (exact timeout)
19:03 execution: latency=540.001498303s (exact timeout)
```

**Root Cause Pattern**:
1. Code has crash bug that fails fast (1-5s)
2. Crash is caught by try/except, execution continues to later exports
3. Fix the crash bug → now processes successfully but slowly (400-600s)
4. Slow processing consumes timeout before reaching later exports
5. Later exports silently never execute (no error, just timeout cutoff)

**Why It's Hard to Detect**:
- Logs don't show "timeout" error - just silent cutoff
- Earlier exports succeed, creating false sense of health
- Latency is EXACTLY the timeout value (540.000s), not an error code

**Solution Pattern - Reorder by Performance**:
```python
# BEFORE (crash at step 2, steps 3+ still run)
step1_fast()    # 5s
step2_crashes() # 1s (crash, caught by try/except)
step3_critical()# Never reached due to crash, BUT try/except lets it run
step4_slow()    # Never runs due to crash

# AFTER FIX (step 2 now slow, step 3+ never reached due to timeout)
step1_fast()    # 5s
step2_fixed()   # 500s (now works but slow) ← CONSUMES TIMEOUT
step3_critical()# NEVER REACHED (timeout at 540s)
step4_slow()    # NEVER REACHED

# SOLUTION (reorder by speed, critical first)
step1_fast()    # 5s ✅
step3_critical()# 20s ✅ (MOVED UP)
step2_fixed()   # 500s (may timeout, but critical exports already done) ⚠️
step4_slow()    # May not run, but less critical
```

**Detection**:
```bash
# Check Cloud Run latencies for exact timeout
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="FUNCTION_NAME"' \
  --limit=20 \
  --format="value(timestamp,httpRequest.latency)" \
  | grep "540\\..*s"  # Exact 540s = timeout
```

**Prevention**:
1. **Order exports by criticality AND speed** - Fast critical exports first
2. **Increase timeout** - If slow export is unavoidable, increase timeout (e.g., 540s → 900s)
3. **Split slow exports** - Separate Cloud Function/scheduler for slow operations
4. **Monitor latencies** - Alert if approaching timeout threshold (>80% of limit)

**Key Lesson**: Fixing a crash bug can reveal a hidden performance issue. When exports that previously "worked" (via fast crash + try/except) suddenly stop after a fix, check for timeout cascade.

**See**: `docs/08-projects/current/phase6-export-fix/` for full details (Session 201)

---

### Cloud Function CLI Tool Unavailability (Session 218B)

**Symptom**: Cloud Function fails with `gsutil: command not found` or `gcloud: command not found`

**Cause**: Cloud Functions Python runtime does NOT include CLI tools (gcloud, gsutil, bq). Shell scripts calling these tools will always fail.

**Real Example**: `bigquery-daily-backup` used a bash script with `bq extract` and `gsutil cp` commands. Worked locally but failed in CF runtime. Session 217 fixed `gsutil` → `gcloud storage` but that also doesn't exist in CF.

**Fix**: Rewrite to use Python client libraries (`google-cloud-bigquery`, `google-cloud-storage`) instead of shell commands. Session 218B rewrote the entire backup function in Python.

**Rule**: NEVER use subprocess/shell calls to gcloud/gsutil/bq in Cloud Functions. Always use Python client libraries.

---

### Cloud Function Reporter Pattern (Sessions 219-220)

**Symptom**: Cloud Scheduler shows INTERNAL (code 13) errors for monitoring/alerting jobs

**Cause**: Reporter Cloud Functions returned HTTP 500 when they detected data quality issues. Cloud Scheduler interprets non-200 as "job failed."

**Real Example**: `daily-health-check` returned 500 when finding CRITICAL pipeline issues. `validate-freshness` returned 400 for stale data. Scheduler logged these as failures.

**Fix**: Reporter/monitoring functions should ALWAYS return 200. Put findings in the response body, not the HTTP status code. Only return 500 for actual infrastructure failures (can't connect to BigQuery, etc.).

**Applied to**: daily-health-check, validation-runner, reconcile, validate-freshness, pipeline-health-summary, live-freshness-monitor

---

### Gen2 Cloud Function Entry Point Immutability (Session 219)

**Symptom**: Re-deploying a Gen2 Cloud Function with `--entry-point=new_func` still uses the old entry point

**Cause**: Gen2 Cloud Functions' entry point is set at creation time and ignored on re-deploys.

**Workaround**: Add `main = actual_entry_point` alias at end of main.py. Example:
```python
# Gen2 functions may have "main" as immutable entry point
main = backup_bigquery_tables
```

**Alternative**: Delete and recreate the function (loses invocation history).

---

### Docker Layer Cache Staleness (Session 220)

**Symptom**: Service deployed from latest commit but runs old code. `check-deployment-drift.sh` shows correct SHA.

**Cause**: Cloud Build Docker layer cache serves stale code layers when only docs/config changed (code layer hash unchanged because ADD/COPY of unchanged files).

**Fix**: Added `--no-cache` to Docker build steps in `cloudbuild.yaml` and `bin/hot-deploy.sh`. Trade-off: slower builds (~1-2 min) but guaranteed fresh code.

---

### Coordinator Backfill Timeout — Player Loader Exceeds 540s (Session 328-329)

**Symptom**: Coordinator `/start` backfill triggered, logs show "Found 365 players" and hundreds of `NO_LINE_DIAGNOSTIC` messages, but NO quality gate, dispatch, or completion logs. Predictions never generated.

**Cause**: Cloud Run request timeout is 540s (9 min). Player loader emits per-player line diagnostic messages (NO_PROP_LINE, LINE_SOURCE, LINE_SANITY_REJECT) that each involve BQ lookups. For 365 players on an 11-game day, player loading alone takes ~12+ minutes — exceeding the timeout. The `/start` handler is killed silently before reaching quality gate or Pub/Sub dispatch.

**Timeline of actual failure (Session 328)**:
```
23:02:25 — /start triggered (BACKFILL mode), 365 players queried
23:02:25 to 23:15:03 — Player loader diagnostic messages (NO_LINE, etc.)
23:11:25 — ~540s elapsed, Cloud Run kills the request
~23:15 — Last straggling log messages, then silence
```

**Detection**:
```bash
# 1. Check coordinator logs for quality gate messages (should appear after player loading)
gcloud logging read '...service_name="prediction-coordinator" AND ("QUALITY_GATE" OR "viable" OR "published")' ...

# 2. If NO quality gate logs after a /start — timeout killed the request
# 3. Check Cloud Run timeout setting
gcloud run services describe prediction-coordinator --region=us-west2 --format="value(spec.template.spec.timeoutSeconds)"
# Returns: 540 (9 min) — too low for large game days
```

**Fix applied**: Increase coordinator timeout to 900s (15 min):
```bash
gcloud run services update prediction-coordinator --region=us-west2 \
  --update-env-vars="" --timeout=900
```

**Prevention**:
1. Set coordinator timeout to 900s+ (15 min) for safety margin on 11+ game days
2. Monitor for exact-timeout latencies: `latency="540.0"` in logs
3. Consider optimizing player_loader line diagnostics — batch BQ lookups instead of per-player queries
4. Never trigger two backfills in quick succession (causes interleaved processing, wasting time)

**Related**: Session 201 "Timeout Cascade" — same pattern where fixing one bug reveals timeout as bottleneck

---

### Phase 4 Same-Day Defensive Check Bypass (Session 220)

**Symptom**: Phase 4 processors fail with "0% game summary coverage" for today's games

**Cause**: Defensive checks expected `player_game_summary` data for today, but games haven't been played yet.

**Fix**: `defensive_check_mixin.py` now auto-skips dependency checks when `analysis_date >= today`. `strict_mode: false` override is no longer needed for same-day requests.

---

### Auto-Retry Infinite Loop (Session 220)

**Symptom**: 322 retry attempts in 6 hours for the same failed processor

**Cause**: (1) Auto-retry processor sent requests to `/process` (expects Pub/Sub envelope) instead of `/process-date` (accepts JSON). (2) 4xx errors left entries as `pending` forever.

**Fix**: (1) Changed Phase 4 retry endpoint to `/process-date`. (2) 4xx responses now mark entries as `failed_permanent`.

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

### Backfill Script Overwrites pick_angles (Session 327-329)

**Symptom**: All BQ `signal_best_bets_picks` rows have `pick_angles: []` after running `bin/backfill_dry_run.py --write`

**Cause**: The backfill script called the aggregator directly but skipped `build_pick_angles()` and `CrossModelScorer`, writing empty angles for every row.

**Fix (Session 328)**: Added `build_pick_angles()` + `CrossModelScorer` to `simulate_date()` in the backfill script.

**Recovery**: Re-run the full backfill: `PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write` (~10 min), then trigger Phase 6 re-export.

**Prevention**: Any script that writes to `signal_best_bets_picks` must include the full pick pipeline (angles, cross-model scoring, ultra classification).

---

### Stale BEST_BETS_MODEL_ID Env Var (Session 329)

**Symptom**: Dashboard shows wrong `best_bets_model` (e.g., `catboost_v12` when champion is `catboost_v9`). Direction health and decay detection queries reference wrong model.

**Cause**: `BEST_BETS_MODEL_ID` env var was set on `phase6-export` and `post-grading-export` CFs during a prior model evaluation, never cleaned up when champion changed.

**Fix**: Remove the env var so CFs use the code default (`CHAMPION_MODEL_ID` in `shared/config/model_selection.py`):
```bash
gcloud run services update phase6-export --region=us-west2 --project=nba-props-platform --remove-env-vars="BEST_BETS_MODEL_ID"
gcloud run services update post-grading-export --region=us-west2 --project=nba-props-platform --remove-env-vars="BEST_BETS_MODEL_ID"
```

**Prevention**: After any model champion change, audit CF env vars for stale overrides.

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

### BigDataBall (BDB) Release Timing (Session 94)

**Symptom**: Validation shows "BDB 0% coverage - CRITICAL" but files are just not released yet

**Root Cause**: BigDataBall releases play-by-play files 6+ hours AFTER games end. This is normal.

**Timeline**:
- Games end: ~10-11 PM PT
- BDB uploads to Google Drive: ~4-7 AM PT the next day
- Our scraper retries every 4-5 minutes until files appear

**Key Rules**:
1. **Before 6 AM PT**: 0% BDB coverage is NORMAL (files not uploaded yet)
2. **After 6 AM PT**: Files SHOULD be available - check scraper logs
3. **After 12+ hours**: Files MUST be available - investigate if missing

**Validation Timing**:
| Validation Time (PT) | BDB Expectation | Missing = Severity |
|----------------------|-----------------|-------------------|
| Evening (6 PM - 12 AM) | NOT expected | ℹ️ INFO |
| Night (12 AM - 6 AM) | NOT expected | ℹ️ INFO |
| Morning (6 AM - 12 PM) | SHOULD exist | ⚠️ WARNING |
| Afternoon+ (12 PM+) | MUST exist | 🔴 CRITICAL |

**If 0% after 6 AM PT**:
```bash
# Check if scraper is finding files
gcloud logging read 'textPayload=~"bigdataball" AND textPayload=~"Found game file"' \
  --limit=10 --freshness=6h --project=nba-props-platform
```

**False Alarm Example (Session 94)**:
- Validation ran at 9:41 PM PT on Feb 2 for Feb 2 games
- Flagged as "P0 CRITICAL - BDB scraper Google Drive failures"
- Reality: Games hadn't even finished yet; files were uploaded ~6 AM PT Feb 3

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

### Infinite Pub/Sub Retries for Injured Players (Session 131)

**Symptom**: Injured (OUT) players stuck in infinite Pub/Sub retry loop, batches never reach 100% completion

**Cause**: Worker returned HTTP 500 (TRANSIENT) for OUT players instead of 204/4xx (PERMANENT)

**Root Cause**:
```python
# predictions/worker/worker.py - Missing skip reason
PERMANENT_SKIP_REASONS = {
    'player_not_found',
    'no_prop_lines',
    'game_not_found',
    'player_inactive',
    'no_historical_data',
    # Missing: 'player_injury_out' ❌
}
```

**Impact**:
- 17 injured players retried forever (Pub/Sub default behavior for 500 errors)
- Excessive worker logs (noise)
- Pub/Sub message buildup
- Batches stuck at ~87% completion
- Predictions for healthy players worked fine

**Detection**:
```bash
# Check for TRANSIENT retries on injured players
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"TRANSIENT.*player_injury_out"' --limit=10

# Verify batch stuck at partial completion
# Firestore: prediction_batches/{batch_id}
# Shows: completed_players: 119, expected_players: 136 (87.5%)
```

**Fix**:
```python
PERMANENT_SKIP_REASONS = {
    'player_not_found',
    'no_prop_lines',
    'game_not_found',
    'player_inactive',
    'no_historical_data',
    'player_injury_out',  # ✅ Returns 204 - stops retries
}
```

**Verification**:
```bash
# After fix - check for PERMANENT acknowledgments
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"PERMANENT.*player_injury_out"' --limit=10
```

**Pattern**: Always classify skip reasons as PERMANENT or TRANSIENT explicitly. Default behavior (500) assumes transient and retries forever.

**Related**: Session 130 (batch unblock), Session 104 (original injury skip logic)

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

### 11. ML Feature Train/Eval Mismatch (Session 134b)

**Anti-Pattern**: Train ML model with one feature pipeline, evaluate/inference with a different one

**Example**: Session 134b - Breakout classifier trained with AUC 0.62, evaluated with AUC 0.47
- Training computed `explosion_ratio` from game history
- Backfill hardcoded `explosion_ratio = 1.5`
- Training got `pts_vs_season_zscore` from feature store
- Backfill computed it inline
- Model predictions were INVERSELY correlated with actual outcomes

**Detection**:
```python
# Compare feature distributions between train and eval
from ml.features.breakout_features import validate_feature_distributions
validate_feature_distributions(df_train, "training")
validate_feature_distributions(df_eval, "evaluation")
```

**Better Approach**:
1. Create SHARED feature module used by both training and inference
2. Never hardcode feature values - always compute from data
3. Validate feature distributions match between train/eval
4. Store feature computation logic WITH the model

**Solution**: Created `ml/features/breakout_features.py` as single source of truth

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
