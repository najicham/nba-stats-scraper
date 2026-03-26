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
9. [prediction_accuracy JOIN Pattern](#prediction_accuracy-join-pattern)

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

### minScale Drift on Cloud Run Deploy (Session 338)

**Symptom**: All Cloud Run services had `minScale=0` despite expecting `minScale=1`. `phase4-to-phase5-orchestrator` had 20+ "no available instance" cold start errors in a 1-hour window.

**Cause**: `gcloud run deploy` creates a new revision. If `--min-instances` is not explicitly passed, the new revision doesn't inherit the previous setting — it resets to the default (0). Both `deploy-service.sh` and `cloudbuild.yaml` were missing this flag.

**Fix**: Added `--min-instances` to all deploy paths:
- `bin/deploy-service.sh`: Per-service `get_min_instances()` function (orchestrators + prediction services → 1, others → 0)
- `bin/hot-deploy.sh`: Same function
- `cloudbuild.yaml`: `_MIN_INSTANCES` substitution variable (default: 0), set to 1 per-trigger for prediction-worker/coordinator

**Cloud Build triggers**: Cannot use `gcloud builds triggers update` with substitutions for repository-event triggers. Use the REST API instead:
```bash
curl -X PATCH "https://cloudbuild.googleapis.com/v1/projects/PROJECT/locations/REGION/triggers/TRIGGER_ID" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d @trigger_full.json
```

**Prevention**: Deploy scripts now explicitly set `--min-instances` on every deploy. Cost: ~$0.01/hr per warm instance (~$1.20/day for 5 services).

---

### BigQuery SQL Escape Sequence in Python f-strings (Session 338)

**Symptom**: Phase 6 export fails with `Illegal escape sequence: \_ at [194:82]`. Today's best bets file not generated.

**Cause**: Python f-string contained `'%\\_q4%'` — the backslash-underscore is not a valid Python escape sequence AND BigQuery LIKE patterns don't need underscore escaping.

**Real Code**: `shared/config/cross_model_subsets.py` line 152:
```python
# WRONG — backslash before underscore
return f"({col} NOT LIKE '%\\_q4%')"

# CORRECT — no escaping needed
return f"({col} NOT LIKE '%_q4%')"
```

**Detection**: Check Phase 6 logs for SQL compilation errors. Also run `python -W error -c "import shared.config.cross_model_subsets"` to catch DeprecationWarning on invalid escapes.

**Prevention**: Pre-commit hook could check for `\_` in Python strings (unlikely to be intentional). Also, BigQuery's LIKE operator uses `%` and `_` as wildcards — the only way to escape them is with a ESCAPE clause, not backslash.

---

## Data Quality Issues

### Play-by-Play Data Silent Failure — GCS Data Never Reaches BQ (Session 396)

**Problem**: `nba_raw.nbac_play_by_play` had only 506 rows (single test day from Jan 15) despite the scraper running daily via `post_game_window_3` workflow. 59 dates of data existed in GCS but Phase 2 never processed them.

**Root Cause Chain**:
1. Scraper downloads play-by-play and exports to GCS correctly
2. `_determine_execution_status()` in `execution_logging_mixin.py` checks `self.data` for standard patterns (`records`, `games`, `players`, etc.)
3. Play-by-play uses `{"metadata": {...}, "playByPlay": {...}}` — no standard key matches
4. Status reported as `no_data (0 records)` to Pub/Sub
5. Phase 2 receives `status=no_data` → "No file to process" → skips

**Secondary Issue**: Cloud Scheduler calls `/scrape` directly every 4h with only `date` param, bypassing the parameter resolver which would provide `game_id`. Always fails with "Missing required option [game_id]".

**Why Undetected**: (1) Daily validation doesn't check `nbac_play_by_play` table, (2) scraper marked `critical: false` in workflows, (3) validation config exists in YAML but not wired into daily runner.

**Fix**: Added `record_count` key to `self.data` in `transform_data()`:
```python
self.data["record_count"] = len(actions)
```

**Key Lessons**:
1. Any scraper with non-standard `self.data` structure will silently report `no_data`
2. GCS data existence does NOT mean BQ data existence — Phase 2 depends on Pub/Sub status
3. Validation must cover ALL raw tables, not just predictions and analytics
4. `critical: false` scrapers need separate monitoring — they can fail for months undetected
5. Direct `/scrape` route bypasses parameter resolver — per-game scrapers need workflow orchestration

### win_flag Always FALSE in player_game_summary (Session 417)

**Problem**: `player_game_summary.win_flag` is FALSE for ALL teams, ALL players, ALL seasons. Zero TRUE values in the entire table.

**Impact**: Any analysis using win_flag returns wrong results (e.g., "0 wins" for every player).

**Workaround**: Use `plus_minus > 0` as a proxy for wins. Applied in `bin/analysis/player_deep_dive.py`.

**Status**: Not fixed at source. Root cause not investigated (likely Phase 3 processor never populates it correctly).

### Phase 3 All-or-Nothing Quality Rejection (Session 302)

**Problem**: `TeamOffenseGameSummaryProcessor` quality check rejected ALL team records when ANY team had zeros (points=0, fg_attempted=0). On an 11-game night with 5 late games still in progress, the scraper wrote zero-value placeholders for 10 teams. The quality check rejected all 22 teams — even the 12 valid ones from 6 completed games. This cascaded: PlayerGameSummary blocked on empty team dependency → Phase 4/5/6 all failed.

**Root cause**: Quality check used `return pd.DataFrame()` (reject entire batch) instead of filtering invalid rows.

**Fix**: Changed to filter-not-reject pattern:
- Invalid teams (0 pts/FGA) are filtered out with a warning
- Valid teams proceed normally
- Slack `notify_warning` fires immediately listing filtered teams
- Canary auto-heal re-triggers Phase 3 after remaining games finish
- If ALL teams invalid, still returns empty (fallback chain activates)

**Key learning**: Quality gates should filter individual bad rows, not reject entire batches. Partial success (12/22 teams) is far better than total failure (0/22 teams).

**Three-layer visibility**:
1. Processor Slack alert — immediate when teams are filtered
2. Pipeline canary auto-heal — every 30 min, auto-re-triggers Phase 3
3. `/validate-daily` Phase 0.35 — manual per-game coverage check

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

### XGBoost Version Mismatch — Best Bets Poisoned (Session 378c)

**Symptom**: XGBoost model produces ALL UNDER predictions with avg 4.93 points (players avg ~14 points). Inflated edges (8.8-12.6) dominate per-player selection, overwriting all CatBoost/LightGBM best bets picks.

**Root Cause**: Model trained with `xgboost==3.1.2` (local), loaded in production with `xgboost==2.0.2`. XGBoost model JSON format is NOT backward-compatible across major versions. Predictions are systematically ~8.6 points too low with **no error or warning**.

**Impact**: 7 all-UNDER XGBoost picks replaced 3 legitimate CatBoost/LightGBM picks in Phase 6 export. GCS JSON served broken picks to frontend.

**Timeline**:
- Session 377: XGBoost model trained locally with v3.1.2
- Session 378: DMatrix fix deployed, XGBoost starts producing predictions
- Session 378b: "avg predicted 4.9 pts" flagged but not disabled
- Session 378c: Root cause found, model blocked, picks restored

**Fix**:
1. Blocked XGBoost in model_registry (enabled=FALSE, status='blocked')
2. Deactivated 134 XGBoost predictions (is_active=FALSE)
3. Re-triggered Phase 6 export to restore CatBoost/LightGBM picks
4. Upgraded production to xgboost==3.1.2 (matching training env)
5. Added version compatibility check in quick_retrain.py
6. Added model sanity guard in aggregator (blocks models with >95% one direction)

**Lessons**:
- **Framework version mismatches are silent killers** — XGBoost, LightGBM, and CatBoost all have format compatibility concerns across major versions
- **The aggregator had no model-level sanity check** — a single broken model could dominate all selections via inflated edges
- **Disabling a model in the registry doesn't deactivate existing predictions** — must also set is_active=FALSE in player_prop_predictions
- **Always pin and match versions** between training and production environments

**Prevention**:
- Version check in quick_retrain.py warns on major version mismatch
- Model sanity guard in aggregator blocks models with extreme direction imbalance (>95% one direction on 20+ predictions)
- Pin identical versions in requirements.txt and training environment

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

### Gen2 Cloud Function Scheduler URL Mismatch (Session 448)

**Symptom**: Cloud Scheduler jobs targeting Gen2 Cloud Functions return INTERNAL (code 13) or never execute (code -1)

**Cause**: Gen2 CFs get a Cloud Run-backed URL (`https://FUNC-HASH.a.run.app`) but scheduler jobs still point at the Gen1 URL (`https://REGION-PROJECT.cloudfunctions.net/FUNC`). The Gen1 URL returns 500 because the function no longer serves there. Additionally, Gen2 CFs require OIDC authentication which Gen1 didn't need.

**Real Examples (Session 448)**:
- `morning-deployment-check`: INTERNAL/500 — scheduler hit Gen1 URL
- `signal-weight-report-weekly`: code -1 — never ran, Gen1 URL + no OIDC
- `monthly-retrain-job`: INTERNAL/500 — no OIDC auth token

**Fix**:
```bash
# 1. Update scheduler URI to Gen2 URL
gcloud scheduler jobs update http JOB_NAME \
  --location=us-west2 --project=nba-props-platform \
  --uri="https://FUNC-HASH.a.run.app" \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com"

# 2. Add IAM on the backing Cloud Run service
gcloud run services add-iam-policy-binding FUNC_NAME \
  --region=us-west2 --project=nba-props-platform \
  --member='serviceAccount:756957797294-compute@developer.gserviceaccount.com' \
  --role='roles/run.invoker'
```

**Prevention**: After deploying Gen2 CFs, verify scheduler URI matches `serviceConfig.uri` (not `httpsTrigger.url`). Phase 0.675 regression detector catches these.

---

### Scheduler Timeout Too Short for Workflow Scrapers (Session 448)

**Symptom**: DEADLINE_EXCEEDED on scheduler jobs, but scraped data still arrives

**Cause**: Multi-source scraper workflows (betting lines, CLV closing) take longer than the scheduler `attemptDeadline`

**Rule of Thumb**:
- Simple scrapers (single source): 600s
- Workflow scrapers (multi-source): 1800s

**Fix**: `gcloud scheduler jobs update http JOB --attempt-deadline=1800s`

---

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

---

## Session 386: Poisoned Published Picks Prevention System

**Incident**: XGBoost model (`xgb_v12_noveg_train1221_0208`) with version mismatch produced predictions ~8.6pts too low (all UNDER, edges -8 to -10). These got locked into `best_bets_published_picks` via pick locking before the model was deactivated. After deactivation, the 8 poisoned picks persisted on the site as ungraded because:
1. Signal pipeline correctly dropped them from `signal_best_bets_picks`
2. But pick locking preserved them in `best_bets_published_picks`
3. The all.json exporter only JOINed grading data for picks IN `signal_best_bets_picks`
4. Published-only picks carried no grading columns and no `system_id`

**Root cause**: Pick locking (Session 340) was designed to prevent legitimate picks from disappearing mid-day, but had no mechanism to detect when locked picks came from a now-disabled model. No `system_id` was stored, so the source model was invisible.

**Fixes implemented**:
1. **Immediate cleanup**: Deleted 8 poisoned picks from `best_bets_published_picks` for 2026-03-01, re-exported all.json
2. **system_id + signal_status tracking**: Published picks now store which model sourced them and whether they're `active`, `dropped`, or `model_disabled`
3. **Published-only grading**: New `_query_grading_for_published_picks()` method grades locked-but-dropped picks using prediction_accuracy (with player_game_summary fallback)
4. **Disabled model detection**: `_merge_and_lock_picks()` checks model_registry for disabled models and marks their picks as `model_disabled`
5. **Signal exporter defense-in-depth**: `signal_best_bets_exporter.py` filters out picks from disabled models before writing to `signal_best_bets_picks`
6. **Pick event logging**: New `best_bets_pick_events` BQ table tracks why picks were dropped (event_type: `dropped_from_signal`, `model_disabled`, `manually_removed`)
7. **Deactivation CLI**: `bin/deactivate_model.py` — single command to disable registry + deactivate predictions + remove signal picks + audit trail + optional re-export

**Key files**:
- `data_processors/publishing/best_bets_all_exporter.py` — grading, disabled model check, pick events
- `data_processors/publishing/signal_best_bets_exporter.py` — disabled model filter
- `bin/deactivate_model.py` — deactivation CLI
- `schemas/bigquery/nba_predictions/best_bets_pick_events.sql` — event table

**Prevention layers (4-deep)**:
1. **Model sanity guard** (aggregator, Session 378c) — blocks >95% same-direction models
2. **Signal exporter disabled model filter** — prevents disabled model picks from entering signal_best_bets_picks
3. **All exporter disabled model detection** — marks locked picks from disabled models as `model_disabled`
4. **Published-only grading** — grades dropped picks so they show results instead of appearing as phantom ungraded picks

**Learning**: Pick locking is a necessary safeguard but creates a trust boundary. Locked picks must carry full lineage (model source, signal status) so downstream exporters can validate them. Defense-in-depth across 4 layers prevents any single system failure from poisoning published picks.

## Session 387: Silent Signal Failures & Fleet Lifecycle

**Incident**: Two high-value signals (`line_rising_over` 96.6% HR, `fast_pace_over` 81.5% HR) were discovered to be completely dead in production — never firing, no alerts, no detection. Additionally, 4 models had inconsistent registry states (`enabled=False` but `status=active`), and the `deactivate_model.py` CLI had a column reference bug preventing execution.

### Root Cause 1: Champion Model Dependency (`line_rising_over`)

The `prev_prop_lines` CTE in `ml/signals/supplemental_data.py` queried predictions filtered by `system_id = '{model_id}'` where `model_id` was the production champion (`catboost_v12`). When the champion stopped producing predictions (BLOCKED state, 0 active predictions), `prev_line_value` became NULL for all players, causing `prop_line_delta` to never be set.

**Impact**: Not just `line_rising_over` — ALL negative filters depending on `prop_line_delta` were also broken:
- `line_jumped_under` (filter 7)
- `line_dropped_under` (filter 8)
- `line_dropped_over` (filter 13)

These filters still "worked" in the sense that NULL `prop_line_delta` didn't match `>= 2.0` or `<= -2.0`, so no picks were incorrectly blocked. But they also weren't BLOCKING picks that should have been blocked.

**Fix**: Removed `AND pp.system_id = '{model_id}'` from the CTE. Prop lines are bookmaker lines, not model-dependent — any model's previous prediction has the same line.

### Root Cause 2: Feature Normalization Mismatch (`fast_pace_over`)

The signal checked `opponent_pace >= 102.0` where `opponent_pace` came from `feature_18_value` in the ML feature store. However, feature_18 is normalized to a 0-1 scale (P75=0.49, P90=0.76, P95=0.93). The threshold of 102.0 can never be met on a 0-1 scale — the signal was dead on arrival.

**Fix**: Changed `MIN_OPPONENT_PACE` from `102.0` to `0.75` (≈ top 25% of teams by pace, maps to raw pace ~102+).

### Root Cause 3: model_health in ACTIVE_SIGNALS

The `model_health` signal is intentionally excluded from `pick_signal_tags` in `signal_annotator.py` (line 134: `if signal.tag != 'model_health'`). It's a meta-signal used for signal density checks, not a taggable pick signal. But it was listed in `ACTIVE_SIGNALS` in `signal_health.py`, creating an impossible expectation that it would appear in `signal_health_daily`.

**Fix**: Removed `model_health` from `ACTIVE_SIGNALS`.

### Root Cause 4: Inconsistent Registry States

4 models had `enabled=False` but `status` was still `active` or `shadow` instead of `blocked`. The `deactivate_model.py` script had a bug: it referenced `updated_at` which doesn't exist in `model_registry` (only `created_at` exists), causing the UPDATE to fail on execution.

**Fix**: Removed `updated_at = CURRENT_TIMESTAMP()` from the UPDATE query. Deactivated all 4 inconsistent models.

### Additional Fixes

- **Edge storage**: UNDER predictions stored with negative signed edge (`predicted - line`) in `signal_best_bets_picks` and JSON exports since Feb 22. Fixed to use `abs(edge)` consistently. Backfilled 10 historical rows.
- **Scheduler noise**: `nba-env-var-check-prod` was firing every 5 minutes against a non-existent `/internal/check-env` endpoint on prediction-worker. Paused.

### Key Learnings

1. **Signals that depend on external state can die silently.** No monitoring existed for "signal stopped firing." A signal firing canary is needed — compare current firing rate to historical baseline.

2. **Feature normalization must be validated at signal creation time.** Always query `MIN/MAX/P50/P90` of the feature before setting thresholds. Normalized (0-1) vs raw scale mismatches are invisible in code review.

3. **Champion model death cascades.** When the production champion stops producing predictions, anything that queries its predictions breaks. Supplemental data, line deltas, and potentially other features all had hidden champion dependencies.

4. **Registry state consistency matters.** `enabled=False` without `status=blocked` is an inconsistent state that can confuse monitoring tools and manual inspections. The deactivation cascade should enforce both.

5. **Column existence must be verified.** The `updated_at` column bug in `deactivate_model.py` was never caught because the script was created in Session 386 and only tested in dry-run mode (which doesn't execute the UPDATE).

### Forward Plan

See `docs/08-projects/current/fleet-lifecycle-automation/00-PLAN.md` for the 3-tier automation plan:
- Tier 1: Auto-disable BLOCKED shadow models
- Tier 2: Signal firing canary
- Tier 3: Registry hygiene automation

---

## Session 401-402: Scraper Infrastructure Issues

### ConfigMixin date=TODAY Bug

**Symptom:** Scraper scheduler sends `date=TODAY` parameter. Scraper passes literal string `"TODAY"` into JSON data and GCS paths. Phase 2 processor rejects it as invalid DATE for BigQuery.

**Root Cause:** `ConfigMixin.resolve_opts()` did not resolve the `TODAY` sentinel to an actual date string. It was treated as a passthrough value.

**Fix (Session 402):** Added `resolve_today()` in scraper opts processing that converts `TODAY` → `YYYY-MM-DD` (Eastern time) before any downstream use.

**Prevention:** Any new scraper inheriting `ScraperBase` automatically gets date resolution. Test with `--date TODAY` locally before deploying.

### Playwright Library vs Browser Binary

**Symptom:** `playwright==1.52.0` installed via pip, but `playwright.chromium.launch()` fails with "Executable doesn't exist" at runtime.

**Root Cause:** The `playwright` Python package is just the API bindings. The actual Chromium binary (~150MB) must be installed separately via `playwright install chromium`. In Docker, `--with-deps` is also needed for system libraries (libnss3, libatk, etc.).

**Fix:** Added `RUN playwright install chromium --with-deps` to `scrapers/Dockerfile` after pip install step.

**Note:** Adds ~150-200MB to Docker image. Monitor cold start times.

### Referee Processor Missing load_data()

**Symptom:** `NbacRefereeProcessor` in Phase 2 failed silently — no data loaded from GCS, transform produced empty results.

**Root Cause:** `ProcessorBase` requires `load_data()` override. The referee processor was created in December but `load_data()` was never implemented — it inherited a no-op default.

**Fix (Session 402):** Implemented `load_data()` to read JSON from GCS path. Historical files (~59 dates from December onward) need backfill via `bin/backfill_referee_data.py`.

### NumberFire → FanDuel Domain Redirect

**Symptom:** NumberFire projections URL returns 301 redirect to `fanduel.com/research/nba/fantasy/dfs-projections`. The FanDuel page is a React SPA with no data in static HTML.

**Root Cause:** FanDuel acquired NumberFire and redirected the domain. The projections data is rendered client-side via a GraphQL API.

**Fix (Session 403):** Rewrote scraper to call `fdresearch-api.fanduel.com/graphql` directly. Two queries: `getSlates(sport: NBA)` to find today's slate ID, then `getProjections(slateId)` for all player projections. No Playwright needed. Returns ~140 players with points/minutes/rebounds/assists.

### VSiN "AJAX" Assumption Was Wrong

**Symptom:** VSiN scraper returned 0 games. Initial assessment said data was AJAX-loaded.

**Root Cause:** The data IS server-side rendered at `data.vsin.com/nba/betting-splits/` (not `www.vsin.com`). The HTML parser was looking for column headers like "team", "over%", "under%" that don't exist — the actual structure uses a freezetable layout with team names in `txt-color-vsinred` links and percentages in nested `div` elements.

**Fix (Session 403):** Rewrote `transform_data()` to match actual HTML structure. No Playwright needed. Tested: all 6 games parse correctly.

**Lesson:** Always curl the actual URL and inspect the HTML before assuming AJAX. `data.vsin.com` ≠ `www.vsin.com`.

### Playwright Debian Package Breakage

**Symptom:** `playwright install chromium --with-deps` fails with "Package 'ttf-unifont' has no installation candidate" on Debian Trixie.

**Root Cause:** Debian Trixie renamed `ttf-unifont` → `fonts-unifont` and removed `ttf-ubuntu-font-family`. Playwright's `--with-deps` flag hardcodes the old package names.

**Fix (Session 403):** Removed Playwright entirely from Dockerfile and requirements. All scrapers that used it were rewritten to use APIs or server-rendered HTML.

**Lesson:** Avoid Playwright in production Docker images — fragile system dependencies, adds 150MB+ to image, and alternatives (APIs, server-rendered HTML) are almost always available.

### GCS-BQ Consistency Gap in Signal Exporter

**Symptom:** `best_bets_filter_audit` showed 1 passed pick for Mar 3, but `signal_best_bets_picks` had 0 rows.

**Root Cause:** `_write_to_bigquery()` filtered disabled model picks in a LOCAL variable. The calling `export()` method still had the original unfiltered `json_data['picks']`. BQ got 0 rows (correct), GCS got 1 pick (wrong), filter_audit counted the unfiltered pick.

**Fix (Session 403):** Moved disabled model filter from `_write_to_bigquery()` to `export()` before BOTH BQ write and GCS upload. Now all three outputs see the same filtered set.

**Lesson:** Defense-in-depth filters must modify the shared data, not create local copies.

### Scraper download_and_decode Override Bypasses Proxy

**Symptom:** NBA Tracking scraper had `proxy_enabled = True` but all requests went direct to stats.nba.com and timed out.

**Root Cause:** Custom `download_and_decode()` override bypassed the `ScraperBase.download_data_with_proxy()` infrastructure. The override checked `self.proxy_url` (always None) instead of calling `get_healthy_proxy_urls_for_target()`.

**Fix (Session 403):** Added `_get_proxy_url()` helper that queries the proxy pool, then passes the URL to both `_fetch_via_nba_api(proxy=...)` and `_fetch_via_http(proxies=...)`.

**Lesson:** When overriding `download_and_decode()`, manually integrate proxy infrastructure — it won't happen automatically.

### Training/Eval Date Overlap Gate (Session 405)

**Symptom:** `quick_retrain.py` blocked with "TRAINING/EVAL DATE OVERLAP DETECTED" when train-end was after eval-start.

**Root Cause:** Using `--train-end 2026-03-04 --eval-start 2026-02-20` creates 13 days of overlap. Model trains on the same games it evaluates on, producing inflated HR (87%+ instead of real 62%).

**Fix:** Set `--train-end` before `--eval-start` (e.g., train Jan 7 → Feb 19, eval Feb 20 → Mar 3).

**Lesson:** Always ensure train-end < eval-start. The governance gate catches this automatically.

### Model Fleet Has Zero Diversity (Session 405)

**Symptom:** 22 models, but model_correlation.py showed ALL 145 pairs have r >= 0.95 (REDUNDANT). Zero diverse pairs (r < 0.70).

**Root Cause:** All models use the same feature set (v12_noveg), same training data source (player_game_summary + ml_feature_store), and similar training windows. CatBoost, LightGBM, and XGBoost converge to nearly identical predictions despite algorithmic differences.

**Implication:** Multi-model agreement is NOT a useful diversity signal. V9+V12 agreement anti-correlation finding (CLAUDE.md) extends to ALL model pairs. The fleet provides redundancy (if one model fails, others have same predictions) but not complementary information.

**Lesson:** True model diversity requires different feature sets, different target variables, or fundamentally different modeling approaches (e.g., player-specific models, game-context specialists).

### Post-ASB Edge Compression Kills Combo Signals (Session 405)

**Symptom:** combo_3way (95.5% HR) and combo_he_ms (94.9% HR) dead since Feb 11.

**Root Cause:** All-Star Break + model staleness compressed edge distributions. Edge 4+ OVER predictions dropped from 34/day (Feb 11) to 0-3/day. Combined with minutes surge >= 3 requirement, the intersection is zero.

**Lesson:** Combo signals with multiple threshold gates are fragile to distribution shifts. The edge gate is the weakest contributor — minutes surge is the real quality discriminator. Consider adaptive thresholds or relative (percentile-based) instead of absolute edge thresholds.

### LightGBM UNDER Calibration Issue (Session 405)

**Symptom:** LightGBM retrain (Jan 7 → Feb 19) achieved 56.6% HR at edge 3+ but UNDER direction was 51.3% — below breakeven. Governance gate correctly blocked.

**Root Cause:** LightGBM's UNDER predictions are biased — Stars UNDER at 47.1%, Starters UNDER at 45.5%. Only Role UNDER performs (63.6%). CatBoost and XGBoost don't show this tier-dependent UNDER failure.

**Lesson:** LightGBM may need tier-specific training or separate OVER/UNDER models. Framework-specific UNDER calibration should be monitored.

### Re-exports Destroy Published Picks (Session 412)

**Symptom:** KAT UNDER 17.5 published at 1:16 PM, dropped at 6:46 PM. Scored 17 (WIN) but never graded. 19 exports ran for Mar 4 with 3 different algorithm versions.

**Root Cause:** `SignalBestBetsExporter._write_to_bigquery()` deleted ALL rows for a game date on every export, then re-inserted only picks from the current signal run. The "lock" in `best_bets_published_picks` only preserved metadata — it didn't prevent signal_best_bets_picks rows from being destroyed.

**Fix:** Changed DELETE scope from "all rows for date" to "only rows for players being refreshed" (`player_lookup IN UNNEST(@player_lookups)`). Picks dropped by signal on re-run stay in the table. Published picks always get `signal_status='active'` (no more 'dropped').

**Lesson:** Write operations on grading-critical tables must be scoped. Never delete rows that might be needed for downstream processes (grading, record tracking). Use upsert patterns instead of delete-all+insert.

### OVER Edge 3-5 Net-Negative in 4/5 Seasons (Session 468)

**Symptom:** OVER picks at edge 3-5 consistently losing money despite edge appearing viable.

**Root Cause:** 5-season discovery analysis across 79K predictions showed OVER at edge 3-5 is net-negative in 4 of 5 historical seasons: 2021-22 (43%), 2022-23 (45%), 2023-24 (49%), 2024-25 (50%). Only 2025-26 (58%) was profitable — a single-season artifact. UNDER at edge 3-5 was stable at 56.7%.

**Fix:** Raised OVER edge floor from 4.0 to 5.0 in `aggregator.py`. Only HSE rescue bypasses this floor.

**Lesson:** Direction-specific edge floors matter. OVER and UNDER have fundamentally different edge-HR curves. Cross-season validation is essential — single-season results are unreliable.

### Hot Shooting Mean Reversion Kills OVER (Session 468)

**Symptom:** OVER picks on players with hot recent shooting consistently lose.

**Root Cause:** Archetype analysis showed FG% hot (diff >= 10%) = 24.1% OVER HR (N=58), 3PT% hot (diff >= 15%) = 28.6% OVER HR (N=56). Players shooting significantly above season average regress, making OVER a losing bet.

**Fix:** Added `hot_shooting_over_block` filter — blocks OVER when FG diff >= 10% OR 3PT diff >= 15%.

**Lesson:** Mean reversion is asymmetric. Hot shooting kills OVER (24-29% HR) but hot 3PT shooting doesn't help UNDER as strongly. The market already partially prices hot streaks into lines, but not enough.

### Picks Vanish From Site After Model Disable (Session 468)

**Symptom:** March 10 had 7 published picks visible on playerprops.io. After Session 466 disabled 5 stale models, all 7 picks disappeared from the site.

**Root Cause (two bugs):**
1. `all.json` read history exclusively from `signal_best_bets_picks`, which had 0 rows for March 10 (BQ write failure during original export). The `best_bets_published_picks` table had all 7 picks, but wasn't used for historical dates.
2. `model_disabled` status (Session 386) caused published picks to be marked as hidden. The `_merge_and_lock_picks` method set `signal_status='model_disabled'` when a pick's source model was later disabled, effectively removing it from display.

**Fix:**
1. `_query_all_picks()` now UNIONs with `best_bets_published_picks` as fallback for dates missing from `signal_best_bets_picks`. Published picks are the source of truth for "was this shown to users."
2. `model_disabled` no longer hides picks. Once published, a pick stays `signal_status='active'` regardless of whether the source model is later disabled. Model disablement is logged for audit but doesn't affect visibility.

**Lesson:** "True pick locking" must be end-to-end. Locking picks in one table while reading history from another creates a gap. Published picks = user-visible commitment — they should never vanish. Internal model lifecycle events (disable, retrain) should not retroactively erase user-facing data.

### Static Signal Weights Miss Health Regime Changes (Session 469)

**Symptom:** `home_under` signal at 33.3% 7d HR (COLD regime) still had 2.0 weight in UNDER composite scoring, boosting bad UNDER picks to the top of rankings.

**Root Cause:** `UNDER_SIGNAL_WEIGHTS` and `OVER_SIGNAL_WEIGHTS` were static dictionaries. Signal health regime (HOT/NORMAL/COLD from `signal_health_daily`) was only used for pick angle context and rescue health gates, NOT for composite scoring. A COLD signal boosted picks identically to a HOT signal.

**Fix:** Added `_health_multiplier()` method to `BestBetsAggregator`. Composite scoring now applies health-regime multipliers: COLD behavioral → 0.5x, COLD model-dependent → 0.0x, HOT → 1.2x, NORMAL → 1.0x. Self-correcting — signals recover weight when HR improves.

**Lesson:** Any data-driven weight should be health-aware. Static weights ignore regime changes and can amplify bad signals during cold streaks. The rescue health gate (Session 437) caught this for rescue eligibility but not for ranking weights.

### Fighting the Market is Consistently Losing (Session 469)

**Symptom:** OVER picks where BettingPros line rose >= 1.0 (market moving against OVER) had 38.9% HR (N=54, 5-season cross-validated).

**Fix:** Promoted `over_line_rose_heavy` from observation to active blocking filter. 5-season confirmation provides sufficient evidence.

**Lesson:** When the market moves strongly in one direction (line rising = books raising the bar), betting the opposite is structurally disadvantaged. The model's edge is real but the market already priced in the same information — and then some.

### Registry Status Stale After Model Re-Enable (Session 477)

**Symptom:** Models re-enabled in `model_registry` (`enabled=TRUE`) still produced 0 picks for 2+ days. BB pipeline ran daily but silently skipped all picks. No alert fired.

**Root Cause:** The decay CF (`decay-detection`) is one-directional: it sets `status='blocked'` when HR drops, but never auto-unblocks when HR recovers. After manual re-enable (`UPDATE ... SET enabled=TRUE`), the `status` column remained `'blocked'`. The BB aggregator checks `status != 'blocked'` before processing any model — so `enabled=TRUE, status='blocked'` models are completely invisible to the pipeline.

**Fix:**
1. `./bin/unblock-model.sh MODEL_ID` — resets `status='active'` for re-enabled models
2. Three new canaries added: `check_registry_blocked_enabled`, `check_model_recovery_gap`, `check_bb_candidates_today`
3. New script `bin/unblock-model.sh` documents the two-step re-enable process

**Lesson:** `enabled` and `status` are independent registry fields with no sync enforcement. Re-enabling a model resets `enabled` only — `status` must be separately reset. Any re-enable workflow must include both fields. The BB pipeline's silent skip (no error, no log, just 0 picks) makes this failure mode invisible without explicit monitoring.

### BB Pipeline Stall — Phase 4 Complete, Phase 5 Never Triggered (Session 477)

**Symptom:** Phase 4 precompute completed at ~9 AM ET. Best bets pipeline produced 0 picks for 2 consecutive days. No Slack alert. Workers showed as healthy in Cloud Run.

**Root Cause:** Phase 5 → Phase 6 (BB export) is triggered by a Pub/Sub message from the Phase 5 orchestrator. The Pub/Sub trigger was not received — either the message was never published or the subscription ACKed it without delivery. The BB pipeline uses a separate execution path from regular predictions (Phase 5 covers predictions; Phase 6 covers BB export). Phase 4 completion does not directly trigger Phase 6.

**Fix:** Manual trigger via Pub/Sub:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "YYYY-MM-DD"}'
```
Added `check_bb_candidates_today` canary: fires when Phase 4 complete but `model_bb_candidates` has 0 rows after 2+ hours.

**Lesson:** Pub/Sub delivery is not guaranteed for low-frequency messages. The orchestration chain (Phase 4 → 5 → 6) has no end-to-end validation. A stall anywhere silently produces 0 picks with no error surfaced to operators. Every phase boundary needs an explicit "did the next phase start?" check, not just "did this phase complete?"

### Cloud Run Traffic Stays Pinned After `services update --image` (Session 482)

**Symptom:** `gcloud run services update mlb-prediction-worker --image=NEW_IMAGE` reports "Creating Revision... Done" but the service keeps serving the old image. New revisions appear in `gcloud run revisions list` with status `Retired`.

**Root Cause:** When a Cloud Run service has explicit revision routing (e.g., `100% → 00022-mlg`), `gcloud run services update --image` creates a new revision but does NOT automatically route traffic to it. The new revision gets immediately retired because nothing sends it traffic.

**Fix:** After `services update`, always follow with:
```bash
gcloud run services update-traffic SERVICE --region=us-west2 --to-latest
```
Or deploy with `gcloud run deploy` (which defaults to routing to latest).

**Lesson:** `services update` and traffic routing are independent operations in Cloud Run when explicit revision pinning is active. Verify with `gcloud run services describe SERVICE --format="yaml(status.traffic)"` after any image update.

### MLB Cloud Service Class Name Mismatch → Silent 503 (Session 482)

**Symptom:** `mlb-phase6-grading` health check returns 503. Logs show `ImportError: cannot import name 'MLBShadowGradingProcessor'`. All endpoints return 503 — service never boots.

**Root Cause:** `main_mlb_grading_service.py` imported `MLBShadowGradingProcessor` but the class in `mlb_shadow_grading_processor.py` is named `MlbShadowModeGradingProcessor`. Python class naming inconsistency (one all-caps acronym, one camelCase) caused a startup crash on every cold start.

**Fix:**
```python
# Before (broken)
from data_processors.grading.mlb.mlb_shadow_grading_processor import MLBShadowGradingProcessor

# After (fixed)
from data_processors.grading.mlb.mlb_shadow_grading_processor import MlbShadowModeGradingProcessor as MLBShadowGradingProcessor
```

**Detection:** The `mlb-shadow-grading-daily` scheduler showed `NOT_FOUND (gRPC 5)` — but the real symptom was `health` endpoint returning 503, not 404. Always test `/health` endpoint after MLB service deploys.

**Lesson:** MLB services are manually deployed (not auto-deployed from main). Import errors go undetected until the next cold start. After any MLB service deploy, immediately test `curl /health` before closing the session.

### `.gcloudignore` Missing `.venv/` Inflates Cloud Build Uploads 10x (Session 482)

**Symptom:** `gcloud builds submit` output shows "15,166 file(s) totalling 1.1 GiB" and upload takes 10+ minutes. Expected: ~3,000 files, ~100 MB.

**Root Cause:** `.gcloudignore` had `venv/` (no dot) but not `.venv/` (with dot prefix). Virtual environment at `.venv/` (1.7 GB) and `models/` (327 MB) were included in every Cloud Build archive.

**Fix:** Add to `.gcloudignore`:
```
.venv/
models/
```

**Lesson:** When Cloud Build uploads are unexpectedly large, check `.gcloudignore` for dotfile directories (`.venv/`, `.cache/`, `.pytest_cache/`). The `venv/` pattern does NOT match `.venv/`.

### 9-Agent Review: Observation-Mode Guardrails Never Block (Session 483)

**Context:** After the March 8 disaster (4-12, 25% HR on 16 picks), a 9-agent review
(5 Opus 4 + 4 Sonnet) reviewed all system code and identified the root cause pattern.

**Finding:** The system had built every necessary market-awareness guard. None were blocking.
- `mae_gap_obs` filter in `aggregator.py`: written, fires, comment says "BB HR craters to
  40-50%" — but had `# Observation only — does NOT block`
- `regime_context.disable_over_rescue`: computed, passed to aggregator — but aggregator had
  `# Observation mode — do NOT disable rescue`
- `regime_context.over_edge_floor_delta`: fetched from regime_context but the floor code
  had `# Observation: track what regime floor WOULD block` and never applied it
- `market_regime = 'TIGHT'` stored in `league_macro_daily` — never read by aggregator

**Root quote from Opus agent:** *"This is a system that built the guardrails, labeled them
'observation,' and then watched itself drive off the cliff while logging the event."*

**Fixes (Session 483):**
1. `mae_gap_obs` → blocks OVER when gap > 0.5 (model badly losing to books)
2. `regime_rescue_blocked` → now actually blocks OVER rescue when `disable_over_rescue=True`
3. `over_edge_floor_delta` → now actually raises the floor (5.0 → 6.0 when regime triggered)
4. `regime_context.py` → now queries `vegas_mae_7d`; when < 4.5 sets floor +1.0 + disables rescue
5. `sc3_over_block` → OVER edge 7+ now bypasses (mirrors existing UNDER bypass)
6. `home_under` → moved to BASE_SIGNALS (48% 30d HR, was active in rescue_tags + UNDER_SIGNAL_WEIGHTS)
7. `signal_health.py` HOT gate → requires picks_7d >= 5 AND hr_30d >= 50% to be HOT

**Lesson:** When adding observation mode for a new filter, set a calendar reminder to
promote it. Every observation filter should have a "promote by N=30" threshold in comments.

### March 8 Root Cause: One Model + Tight Market + Correlated Losses (Session 483)

**What happened:** 16 picks, 4-12 (25% HR). Root causes in priority order:
1. `lgbm_v12_noveg_vw015_train1215_0208` sourced 9 of 16 picks (56%) — fleet concentration risk
2. Vegas MAE was 4.40 (TIGHT) — books were highly accurate, our "edge" was model noise
3. UNDER collapse: blowout_risk_under + starter_under + downtrend_under all fired on same
   night as scoring eruption. Stars all exceeded lines by +5 to +7.5 points.
4. 3 rescue picks (all OVER, edge 3.1-3.2) all lost — `sharp_book_lean_over` rescued low-line
   role players in a tight market.

**Without March 8** (ex-disaster): 30d HR was 57.4%. The system ex-disaster is OK.
30d window fully washes out March 8 around April 7.

**Model fleet consequence:** Fleet went from 6 enabled to 2 after decay detection correctly
blocked the bad models. With 2 models, you're below the MIN_ENABLED_MODELS=3 safety floor.

**Lesson:** Single-model dominance (>40% of picks from one model) is a red flag now
monitored by `signal_decay_monitor.py`. Target fleet size: 4-6 enabled models.

### Retrain Gate Logic Was Backwards (Session 483)

The weekly-retrain CF was PAUSED because "Vegas MAE 5.43, gate requires MAE < 5.0 to retrain."
But 5.43 is a LOOSE market — the best time to train. The gate was blocking training DURING
loose markets when it should be blocking training ON tight-market DATA.

**Correct logic:** Retrain continuously on schedule, but cap `train_end` to the last date
where `vegas_mae_7d >= 5.0`. This prevents edge-collapsed models (trained through tight
markets) while allowing retraining whenever the market is exploitable.

**Short-term workaround:** `./bin/retrain.sh --all --enable --train-end 2026-02-28`
pins training data to pre-tightening period manually.

### MLB Grading Service Silent 503 (Session 482, follow-up 483)

The mlb-phase6-grading service was 503 on all endpoints for weeks due to an import name
mismatch. The `/health` endpoint was decoupled from the actual grading code — it returned
200 even when every functional endpoint was 503.

**Pattern:** Cloud Run health checks only test the `/health` route. Import errors or missing
dependencies only surface when the first functional route is called.

**Detection fix:** `mlb_phase5_to_phase6` orchestrator now sends a Slack alert to `#nba-alerts`
when the grading HTTP call returns non-200. Previously only logged.

**Lesson:** After any MLB service deploy, immediately test a functional endpoint (not just
`/health`). For the grading service, test `curl /grade-date` with a recent date.

### `quick_retrain.py` Eval Query Hardcoded to `catboost_v9` (Session 483)

**Symptom:** `quick_retrain.py` with `--use-production-lines` (default) always returns 39 eval
samples regardless of the eval date range. Hit the `df_eval < 100` threshold — "ERROR: Not
enough data" — on every attempt with a March eval window.

**Root cause:** `load_eval_data_from_production()` at line 569 has `system_id='catboost_v9'`
hardcoded. The eval query JOINs on `prediction_accuracy WHERE system_id = 'catboost_v9'`.
When `catboost_v9` is INSUFFICIENT_DATA (no recent predictions), the join returns almost
nothing. March 2026: only 39 catboost_v9 predictions existed in the entire month.

**Workaround:** `--no-production-lines` uses `load_eval_data()` with DraftKings lines from
the feature store — returns all players, no system_id filter. HR eval is slightly different
(raw line vs production line) but governance gates still valid.

**Permanent fix:** In `quick_retrain.py`, change default `system_id` to auto-detect from
enabled models in the registry, or accept it as a CLI argument.

**Impact for future retrains:** If CatBoost is disabled or INSUFFICIENT_DATA, all `--use-production-lines` retrains will silently fail with "Not enough data". Use `--no-production-lines` as the standard flag until this is fixed.

---

## prediction_accuracy JOIN Pattern

### Always include `recommendation` + `line_value` in JOINs to prediction_accuracy (Session 493)

**Symptom:** Duplicate picks appeared in the best bets UI (every pick shown 2-3x). Root cause
traced to `prediction_accuracy` containing multiple rows per `(player_lookup, game_date, system_id)`
due to two bugs in the grading processor.

**Root cause — two grading bugs:**
1. **Dedup partition included `line_value`:** When lines move during the day (23.5 → 24.5),
   each version was treated as a distinct business key and survived dedup — producing 2+ rows per
   player/game/model. Fixed: partition now `(player_lookup, game_id, system_id)`.
2. **EXISTS rescue clause too broad:** When any BB pick existed for a player/model, ALL historical
   line versions of that prediction passed the EXISTS filter. Fixed: added
   `AND bb.line_value = p.current_points_line` to the EXISTS clause.

**Downstream effect:** Any JOIN to `prediction_accuracy` on only `(player_lookup, game_date, system_id)`
fans out — one BB pick produces 2-3 result rows, inflating W-L counts and HR by up to +6.9pp.

**The fix (always include in JOINs):**
```sql
JOIN prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
  AND pa.recommendation = bb.recommendation   -- NEW: prevents direction fan-out
  AND pa.line_value = bb.line_value           -- NEW: pins to the matched line version
```

**Exception — `pick_signal_tags` JOINs:** `pick_signal_tags` has no `recommendation`/`line_value`
columns. When joining PA through `pick_signal_tags`, pre-dedup `prediction_accuracy` inline:
```sql
WITH deduped_pa AS (
  SELECT * EXCEPT(rn) FROM (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY player_lookup, game_date, system_id
        ORDER BY
          CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
          CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END,
          graded_at DESC
      ) AS rn
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= @start AND game_date <= @end
  ) WHERE rn = 1
)
```

**Long-term fix:** `prediction_accuracy_deduped` BQ view in
`schemas/bigquery/nba_predictions/prediction_accuracy_deduped.sql` — self-heals all 854
existing duplicate groups. Deploy and migrate all 22 consumers once validated.

**Files fixed (Session 493):**
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` — source fix
- `data_processors/publishing/best_bets_all_exporter.py` — commit `0b7c4a88`
- `data_processors/publishing/best_bets_record_exporter.py`, `today_best_bets_exporter.py`,
  `admin_dashboard_exporter.py`, `admin_picks_exporter.py`, `predictions_exporter.py` — PR 1
- `orchestration/cloud_functions/decay_detection/main.py` — PR 3 (model auto-disable)
- `ml/signals/regime_context.py`, `signal_health.py` — PR 3 (OVER floor, HOT/COLD weights)
- `ml/analysis/model_performance.py`, `league_macro.py` — PR 3

**Still to fix (PR 2):** `model_profile.py`, `edge_calibrator.py`, `model_family_dashboard.py`,
`replay_per_model_pipeline.py`, `scoring_tier_processor.py`, `feature_extractor.py`,
`v_signal_performance.sql`, `v_signal_combo_performance.sql`, `bin/` analysis scripts.
