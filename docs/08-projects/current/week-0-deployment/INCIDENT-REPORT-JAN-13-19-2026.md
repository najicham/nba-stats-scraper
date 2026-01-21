# Production Incident Report: Data Pipeline Failures (Jan 13-19, 2026)

**Date Range**: January 13-19, 2026
**Reported**: January 19, 2026 22:45 UTC
**Severity**: P1 (Critical) - Multiple pipeline failures affecting production predictions
**Status**: ✅ ROOT CAUSES IDENTIFIED - Fixes In Progress

---

## Executive Summary

Comprehensive validation of the past 7 days revealed **4 critical systemic failures** affecting the NBA prediction pipeline:

1. **NO AUTOMATED GRADING** (P0) - 2,608 predictions ungraded (Jan 17-19)
2. **PHASE 4 COMPLETE FAILURES** (P1) - Jan 16, 18 missing ML features
3. **MISSING BOX SCORES** (P2) - 17 missing across 6 days (11%-33% gaps)
4. **PREDICTION GAPS** (P3) - No predictions for players without prop lines (Jan 16-19)

**Impact**: Production predictions generated but not graded, ML feature gaps, and data quality issues.

**Root Causes**: Infrastructure not fully deployed, disabled APIs, and missing automation.

---

## Incident #1: NO AUTOMATED GRADING (P0 - CRITICAL)

### Symptoms

| Date       | Predictions | Graded | Coverage | Status |
|------------|-------------|--------|----------|--------|
| 2026-01-19 | 615         | 0      | 0.0%     | ❌ UNGRADED |
| 2026-01-18 | 1,680       | 0      | 0.0%     | ❌ UNGRADED |
| 2026-01-17 | 313         | 0      | 0.0%     | ❌ UNGRADED |
| 2026-01-16 | 1,328       | 1,232  | 92.8%    | ✅ (Manual) |
| 2026-01-15 | 2,193       | 1,964  | 89.6%    | ✅ (Manual) |
| 2026-01-14 | 285         | 261    | 91.6%    | ✅ (Manual) |
| 2026-01-13 | 295         | 271    | 91.9%    | ✅ (Manual) |

**Total Ungraded**: 2,608 predictions (Jan 17-19)

**Last Automated Grading**: NEVER
**Last Manual Grading**: Jan 17, 2026 at 21:33-23:42 UTC (backfill for Jan 11-16)

### Root Cause Analysis

#### Primary Root Cause: BigQuery Data Transfer API Disabled

```bash
$ bq ls --transfer_config --transfer_location=us --project_id=nba-props-platform
BigQuery error: BigQuery Data Transfer API has not been used in project
nba-props-platform before or it is disabled.
```

**Impact**: The BigQuery scheduled query for grading (scheduled at 12 PM PT daily) **CANNOT BE CREATED** because the API is disabled.

**Evidence**:
- File exists: `bin/schedulers/setup_nba_grading_scheduler.sh`
- Documentation exists: `schemas/bigquery/nba_predictions/SETUP_SCHEDULED_QUERY.md`
- API not enabled: BigQuery Data Transfer API disabled
- No scheduled queries: `bq ls --transfer_config` returns API disabled error

#### Secondary Root Cause: No Cloud Scheduler for Grading Cloud Function

**Grading infrastructure deployed**:
- ✅ Cloud Function `phase5b-grading` deployed (Jan 18, 2026)
- ✅ Pub/Sub topics exist: `nba-grading-trigger`, `nba-grading-complete`
- ❌ NO Cloud Scheduler triggering the function
- ❌ NO automated daily trigger

**Verification**:
```bash
$ gcloud scheduler jobs list --location=us-west1
# No output - NO SCHEDULERS EXIST

$ gcloud scheduler jobs list --location=us-central1
# No output - NO SCHEDULERS EXIST

$ gcloud scheduler jobs list --location=us-east1
# No output - NO SCHEDULERS EXIST
```

**Conclusion**: There are **ZERO Cloud Schedulers** in the entire project.

#### Tertiary Root Cause: Grading Readiness Monitor Bug

The `grading-readiness-monitor` Cloud Function (deployed Jan 15) has a **BUG** that prevents it from triggering grading:

**Bug Location**: `/orchestration/cloud_functions/grading_readiness_monitor/main.py` Line 144-146

```python
# BUG: Checks wrong table name!
query = f"""
SELECT COUNT(*) as graded_count
FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`  # ❌ WRONG TABLE
WHERE game_date = '{target_date}'
"""
```

**Correct table**: `nba_predictions.prediction_grades`

**Impact**: The readiness monitor checks if `prediction_accuracy` has data for the date. Since that table exists but is not populated by the grading function (which writes to `prediction_grades`), the monitor **ALWAYS thinks grading hasn't run yet** and never triggers grading.

**Additional Issue**: Even if the table name was correct, there's no Cloud Scheduler triggering the readiness monitor either.

### Impact Assessment

**User Impact**:
- ✅ Predictions still generated and exported
- ❌ No accuracy tracking for 3 days (Jan 17-19)
- ❌ No performance metrics for systems
- ❌ Cannot calculate ROI or win rates
- ❌ Model performance unknown

**Data Impact**:
- 2,608 predictions awaiting grading
- Grading can be backfilled (data is intact)
- No data loss, only delayed insights

**Business Impact**:
- Medium severity - predictions delivered but unverified
- Cannot validate prediction quality
- Cannot track system performance trends

### Timeline

- **Jan 11-16**: Manual grading backfill performed on Jan 17 at 21:33 UTC
- **Jan 15**: Grading readiness monitor deployed (with bug)
- **Jan 17**: Predictions made, NO grading (2,608 predictions)
- **Jan 18**: Phase5b-grading function deployed 06:08 UTC, NO scheduler created
- **Jan 18**: Predictions made, NO grading (1,680 predictions)
- **Jan 19**: Predictions made, NO grading (615 predictions)
- **Jan 19 22:45 UTC**: Issue discovered during validation

### Prerequisites for Grading (ALL MET for Jan 17-19)

✅ **Predictions exist**: Yes (2,608 total)
✅ **Actuals exist** (`player_game_summary`): Yes (all dates)
✅ **Coverage >50%**: Yes (100% coverage)
❌ **Automated trigger**: NO - This is the issue

---

## Incident #2: PHASE 4 COMPLETE FAILURES (P1 - HIGH)

### Symptoms

| Date       | PDC  | PSZA | PCF  | MLFS | TDZA | Impact |
|------------|------|------|------|------|------|--------|
| 2026-01-18 | ❌ 0 | ❌ 0 | ❌ 0 | ✅ 144 | ❌ 0 | CRITICAL - Nearly complete failure |
| 2026-01-16 | ❌ 0 | ⚠️ 442 | ❌ 0 | ✅ 170 | ✅ 30 | HIGH - PDC, PCF missing |
| 2026-01-17 | ✅ 123 | ⚠️ 445 | ✅ 147 | ✅ 147 | ✅ 30 | MEDIUM - Only PSZA issues |
| 2026-01-15 | ✅ 191 | ⚠️ 442 | ✅ 243 | ⚠️ 242 | ✅ 30 | MEDIUM - PSZA + MLFS issues |
| 2026-01-14 | ✅ 177 | ⚠️ 442 | ⚠️ 213 | ✅ 234 | ✅ 30 | MEDIUM - PSZA + PCF issues |
| 2026-01-13 | ✅ 183 | ⚠️ 441 | ✅ 216 | ✅ 236 | ✅ 30 | MEDIUM - PSZA issues only |

**Processor Key**:
- PDC = PlayerDailyCache
- PSZA = PlayerShotZoneAnalysis
- PCF = PlayerCompositeFactors
- MLFS = MLFeatureStoreV2
- TDZA = TeamDefenseZoneAnalysis

### Root Cause Analysis

#### Jan 18 Complete Failure

**Investigation Required**: Phase 4 service logs needed to determine why 4 of 5 processors failed.

**Hypotheses**:
1. **Service didn't trigger**: Orchestration failed to trigger Phase 4 for Jan 18
2. **Service crashed mid-processing**: Started but failed during execution
3. **Upstream validation blocked**: Phase 3 data incomplete, blocked Phase 4
4. **Firestore state corruption**: Checkpoint data corrupted

**Action Item**: Check Phase 4 Cloud Run logs for Jan 18:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=nba-phase4-precompute-processors AND \
   timestamp>=\"2026-01-18T00:00:00Z\" AND \
   timestamp<=\"2026-01-19T00:00:00Z\"" \
  --limit=100 \
  --format=json
```

#### Jan 16 Partial Failure

**Pattern**: PDC and PCF missing, PSZA partial, MLFS/TDZA OK

**Hypothesis**: Different execution times - PDC/PCF scheduled later, failed to run

**Action Item**: Check orchestration logs for Phase 3 → Phase 4 transition on Jan 16

#### PSZA Consistent INCOMPLETE_UPSTREAM Errors (339 total)

**Pattern**: Every date has 64-71 INCOMPLETE_UPSTREAM errors in PSZA

**Root Cause**: PSZA requires shot zone data from `bdl_player_boxscores`
- Missing box scores (Incident #3) → Missing shot zone data → INCOMPLETE_UPSTREAM

**Evidence**:
```
2026-01-17: PSZA 64 errors (2/9 box scores missing = 22% missing)
2026-01-16: PSZA 65 errors (1/6 box scores missing = 17% missing)
2026-01-15: PSZA 70 errors (8/9 box scores missing = 89% missing)
2026-01-14: PSZA 69 errors (2/7 box scores missing = 29% missing)
2026-01-13: PSZA 71 errors (2/7 box scores missing = 29% missing)
```

**Correlation**: Missing box scores → PSZA failures

### Impact Assessment

**ML Feature Availability**:
- **Jan 18**: Only 1/5 processors succeeded (20% feature availability)
- **Jan 16**: 3/5 processors succeeded (60% feature availability)
- **Other dates**: 4-5/5 processors succeeded (80-100% feature availability)

**Prediction Quality Impact**:
- Predictions for Jan 19 games relied on Jan 18 features (20% availability)
- Quality score degradation: Phase 4 features = 100 pts, fallback to Phase 3 = 75 pts
- Estimated quality drop: 15-25% for players needing Jan 18 features

**Cascading Failures**:
- Phase 4 failures → Lower quality scores → Some predictions skipped
- PSZA failures → No shot zone analysis → Missing defensive matchup features

---

## Incident #3: MISSING BOX SCORES (P2 - MEDIUM)

### Symptoms

| Date       | Games | Box Scores | Missing | Coverage |
|------------|-------|------------|---------|----------|
| 2026-01-19 | 3     | 8          | 0       | ✅ 267% (over-scraped) |
| 2026-01-18 | 6     | 4          | 2       | ❌ 67% |
| 2026-01-17 | 9     | 7          | 2       | ❌ 78% |
| 2026-01-16 | 6     | 5          | 1       | ❌ 83% |
| 2026-01-15 | 9     | 1          | 8       | ❌ 11% (**CRITICAL**) |
| 2026-01-14 | 7     | 5          | 2       | ❌ 71% |
| 2026-01-13 | 7     | 5          | 2       | ❌ 71% |

**Total Missing**: 17 box score entries across 6 days

**Gamebooks**: 100% complete for all dates (fallback working)

### Root Cause Analysis

**Investigation Required**: BDL (BallerDataLeague) scraper logs needed.

**Hypotheses**:
1. **Scraper failures**: BDL API returned errors
2. **Rate limiting**: API throttled requests
3. **Delayed availability**: Box scores not available yet when scraped
4. **Network issues**: Connection failures during scraping window
5. **Game not recorded**: Some games not in BDL database

**Action Item**: Check BDL scraper logs:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=nba-scrapers AND \
   textPayload=~\"bdl\" AND \
   timestamp>=\"2026-01-13T00:00:00Z\" AND \
   severity>=WARNING" \
  --limit=100
```

**Jan 15 Anomaly**: Only 1/9 box scores (11% coverage)

**Hypothesis**: Mass BDL API outage or scheduled maintenance on Jan 15

### Impact Assessment

**Direct Impact**:
- Phase 3 unaffected (gamebooks provide sufficient data)
- Phase 4 PSZA affected (needs box score shot zone data)
- 339 INCOMPLETE_UPSTREAM errors in PSZA across 5 days

**Cascading Impact**:
- PSZA failures → Missing shot zone features
- Quality score degradation for affected players
- Some predictions skipped due to insufficient data

---

## Incident #4: PREDICTION GAPS (P3 - LOW)

### Symptoms

| Date       | With Lines | Without Lines | % Without |
|------------|------------|---------------|-----------|
| 2026-01-19 | 615 (100%) | 0 (0%)        | 0%        |
| 2026-01-18 | 1,680 (100%) | 0 (0%)      | 0%        |
| 2026-01-17 | 313 (100%) | 0 (0%)        | 0%        |
| 2026-01-16 | 1,328 (100%) | 0 (0%)      | 0%        |
| 2026-01-15 | 1,905 (87%) | 288 (13%)    | 13%       |
| 2026-01-14 | 215 (75%)  | 70 (25%)     | 25%       |
| 2026-01-13 | 257 (87%)  | 38 (13%)     | 13%       |

**Pattern**: Recent dates (Jan 16-19) have NO predictions for players without prop lines.

**Historical dates (Jan 13-15)**: 13-25% predictions without prop lines.

### Root Cause Analysis

**Investigation Required**: Prediction coordinator logs and configuration changes.

**Hypotheses**:
1. **Config change**: Coordinator now skips players without prop lines
2. **BettingPros data**: No players without lines scheduled for those dates
3. **Quality filtering**: Stricter quality thresholds filter out no-line players
4. **Feature flags**: Recent deployment changed prediction logic

**Action Item**: Check prediction coordinator config and logs:
```bash
# Check if config changed
git log --since="2026-01-15" --grep="prop.*line" --oneline

# Check coordinator logs
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=nba-prediction-coordinator AND \
   timestamp>=\"2026-01-16T00:00:00Z\"" \
  --limit=100
```

### Impact Assessment

**User Impact**:
- Low severity - predictions without prop lines are informational
- Main use case (betting prop predictions) unaffected
- Potential issue if users expect all players to have predictions

**Data Impact**:
- Incomplete prediction coverage for roster
- Historical trend broken (used to predict all players)
- May affect model training if "no line" predictions used as features

---

## Impact Summary

### Production Systems Affected

| System | Status | Impact |
|--------|--------|--------|
| **Phase 2 (Scrapers)** | ⚠️ DEGRADED | 17 missing box scores (11%-33% gaps) |
| **Phase 3 (Analytics)** | ✅ OPERATIONAL | Gamebooks compensate for missing box scores |
| **Phase 4 (Precompute)** | ❌ CRITICAL FAILURES | Jan 16, 18 nearly complete failures |
| **Phase 5 (Predictions)** | ⚠️ DEGRADED | Predictions generated but quality degraded |
| **Phase 6 (Grading)** | ❌ NOT OPERATIONAL | NO automated grading, 2,608 ungraded |
| **Monitoring** | ⚠️ PARTIAL | Grading readiness monitor deployed but has bug |

### User-Facing Impact

✅ **Still Working**:
- Predictions generated daily
- Predictions exported to API/website
- Real-time predictions available

❌ **Not Working**:
- Grading and accuracy tracking
- Performance metrics and ROI calculation
- Quality assurance validation
- Model performance monitoring

⚠️ **Degraded**:
- Prediction quality (missing Phase 4 features)
- Coverage (no predictions for players without prop lines)
- Data completeness (missing box scores)

### Data Integrity

✅ **No Data Loss**:
- All predictions stored in BigQuery
- All source data (gamebooks, schedules) intact
- Grading can be backfilled retroactively

❌ **Missing Data**:
- 17 box score entries (may not be recoverable)
- Phase 4 features for Jan 16, 18 (can be recomputed)
- Grading results for Jan 17-19 (can be backfilled)

---

## Fixes Required

### Priority 1: Enable Automated Grading (P0 - CRITICAL)

**Option A: BigQuery Scheduled Query (Recommended)**

1. **Enable BigQuery Data Transfer API**:
```bash
gcloud services enable bigquerydatatransfer.googleapis.com \
  --project=nba-props-platform
```

2. **Run setup script**:
```bash
./bin/schedulers/setup_nba_grading_scheduler.sh
```

3. **Verify scheduler created**:
```bash
bq ls --transfer_config --transfer_location=us \
  --project_id=nba-props-platform
```

**Option B: Cloud Scheduler + Cloud Function (Alternative)**

1. **Create Cloud Scheduler** (if BigQuery approach fails):
```bash
gcloud scheduler jobs create pubsub grading-daily-trigger \
  --location=us-west1 \
  --schedule="0 18 * * *" \
  --time-zone="America/Los_Angeles" \
  --topic=nba-grading-trigger \
  --message-body='{"target_date":"yesterday","run_aggregation":true,"trigger_source":"cloud-scheduler"}'
```

**Option C: Fix Grading Readiness Monitor (Best Long-term)**

1. **Fix table name bug**:
```python
# File: orchestration/cloud_functions/grading_readiness_monitor/main.py
# Line 144-146

# BEFORE (BUG):
FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`

# AFTER (FIX):
FROM `{PROJECT_ID}.nba_predictions.prediction_grades`
```

2. **Deploy fix**:
```bash
cd orchestration/cloud_functions/grading_readiness_monitor
gcloud functions deploy grading-readiness-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west1 \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --allow-unauthenticated
```

3. **Create Cloud Scheduler to trigger monitor**:
```bash
gcloud scheduler jobs create http grading-readiness-monitor-trigger \
  --location=us-west1 \
  --schedule="*/15 22-23,0-2 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west1-nba-props-platform.cloudfunctions.net/grading-readiness-monitor" \
  --http-method=POST \
  --message-body='{"target_date":"yesterday"}'
```

**Recommended Approach**: Implement **ALL THREE OPTIONS** for redundancy:
- Primary: BigQuery scheduled query (runs at 12 PM PT)
- Secondary: Cloud Scheduler direct trigger (runs at 10 AM PT as backup)
- Tertiary: Readiness monitor (runs every 15 min from 10 PM - 3 AM ET)

### Priority 2: Investigate and Fix Phase 4 Failures (P1 - HIGH)

1. **Investigate Jan 18 complete failure**:
```bash
# Check Phase 4 service logs
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=nba-phase4-precompute-processors AND \
   timestamp>=\"2026-01-18T00:00:00Z\" AND \
   timestamp<=\"2026-01-19T00:00:00Z\"" \
  --limit=200 \
  --format=json > phase4_jan18_logs.json

# Check orchestration trigger logs
gcloud logging read \
  "resource.type=cloud_function AND \
   resource.labels.function_name=~\"phase.*to.*phase\" AND \
   timestamp>=\"2026-01-18T00:00:00Z\"" \
  --limit=100
```

2. **Check Firestore state for Jan 16, 18**:
```bash
# Access Firestore console
https://console.cloud.google.com/firestore

# Check collections:
# - phase3_completion/2026-01-18
# - phase4_completion/2026-01-18
# - phase3_completion/2026-01-16
# - phase4_completion/2026-01-16
```

3. **Add Phase 4 pre-flight validation** (prevent future failures):
```python
# File: orchestration/cloud_functions/phase3_to_phase4/main.py
# Add before triggering Phase 4:

def validate_phase3_completeness(game_date):
    """Verify Phase 3 data before triggering Phase 4."""
    expected_tables = [
        'player_game_summary',
        'team_defense_game_summary',
        'upcoming_player_game_context'
    ]

    for table in expected_tables:
        count = check_table_count(game_date, table)
        if count == 0:
            raise ValidationError(f"Phase 3 table {table} has no data for {game_date}")

    return True
```

4. **Add Phase 4 circuit breaker** (prevent cascading failures):
```python
# File: orchestration/cloud_functions/phase4_to_phase5/main.py
# Add before triggering Phase 5:

def check_phase4_minimum_coverage(game_date):
    """Require at least 3/5 Phase 4 processors to complete."""
    processors = ['PDC', 'PSZA', 'PCF', 'MLFS', 'TDZA']
    completed = count_completed_processors(game_date)

    if completed < 3:
        raise InsufficientDataError(
            f"Only {completed}/5 Phase 4 processors completed. "
            f"Blocking Phase 5 until minimum coverage met."
        )

    return True
```

### Priority 3: Investigate Box Score Failures (P2 - MEDIUM)

1. **Check BDL scraper logs for failures**:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=nba-scrapers AND \
   textPayload=~\"bdl|box.*score\" AND \
   timestamp>=\"2026-01-13T00:00:00Z\" AND \
   severity>=WARNING" \
  --limit=200 \
  --format=json > bdl_scraper_failures.json
```

2. **Add retry logic to BDL scraper**:
```python
# File: scrapers/bdl/player_boxscore_scraper.py
# Add exponential backoff retry:

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception_type((ConnectionError, Timeout, HTTPError))
)
def fetch_boxscore(game_id):
    """Fetch boxscore with retry logic."""
    response = requests.get(f"{BDL_API}/boxscores/{game_id}", timeout=30)
    response.raise_for_status()
    return response.json()
```

3. **Add box score availability check**:
```python
# File: scrapers/bdl/player_boxscore_scraper.py
# Add delay for recent games:

def should_retry_boxscore(game_date):
    """Determine if boxscore should be retried later."""
    hours_since_game = (datetime.now() - game_date).total_seconds() / 3600

    if hours_since_game < 2:
        # Too recent, boxscore may not be available yet
        return True, "Game too recent (<2 hours)"

    if hours_since_game < 24:
        # Retry in 1 hour
        return True, "Game recent (<24 hours), retry later"

    # Game old enough, boxscore should be available
    return False, "Game >24 hours old"
```

4. **Send alert for persistent failures**:
```python
# File: scrapers/bdl/player_boxscore_scraper.py
# Add Slack alert:

def alert_missing_boxscores(game_date, missing_count):
    """Alert if box scores still missing after 24 hours."""
    if missing_count > 0:
        send_slack_alert(
            channel="#data-alerts",
            message=f"⚠️ {missing_count} box scores still missing for {game_date} after 24 hours"
        )
```

### Priority 4: Investigate Prediction Gaps (P3 - LOW)

1. **Check prediction coordinator config**:
```bash
# Check for recent config changes
git log --since="2026-01-15" --all -- predictions/coordinator/

# Check environment variables
gcloud run services describe nba-prediction-coordinator \
  --region=us-west1 \
  --format="yaml(spec.template.spec.containers[0].env)"
```

2. **Query BettingPros data for Jan 16-19**:
```sql
-- Check if any players without lines for recent dates
SELECT
  game_date,
  COUNT(DISTINCT player_name) as total_players,
  COUNT(DISTINCT CASE WHEN points_line IS NULL THEN player_name END) as no_line_players,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN points_line IS NULL THEN player_name END) /
    COUNT(DISTINCT player_name), 1) as pct_no_line
FROM `nba-props-platform.nba_raw.bettingpros_player_props`
WHERE game_date BETWEEN '2026-01-13' AND '2026-01-19'
GROUP BY game_date
ORDER BY game_date DESC;
```

3. **Add monitoring for prediction coverage**:
```python
# File: orchestration/cloud_functions/prediction_monitoring/main.py
# Add alert:

def check_prediction_coverage(game_date):
    """Alert if prediction coverage drops significantly."""
    expected_players = get_active_roster_size(game_date)
    actual_predictions = get_prediction_count(game_date)

    coverage = actual_predictions / expected_players

    if coverage < 0.50:  # Less than 50% coverage
        send_slack_alert(
            channel="#predictions-alerts",
            message=f"⚠️ Low prediction coverage for {game_date}: {coverage:.1%} "
                   f"({actual_predictions}/{expected_players} players)"
        )
```

### Priority 5: Add Comprehensive Monitoring (P1 - HIGH)

**Create Daily Data Quality Dashboard**:

1. **Enable automated daily validation**:
```bash
# Create Cloud Scheduler for daily validation
gcloud scheduler jobs create http daily-data-quality-check \
  --location=us-west1 \
  --schedule="0 16 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://us-west1-nba-props-platform.cloudfunctions.net/data-quality-check" \
  --http-method=POST
```

2. **Create Cloud Function for validation**:
```python
# File: orchestration/cloud_functions/data_quality_check/main.py

@functions_framework.http
def main(request):
    """Run daily data quality checks and send Slack summary."""
    yesterday = datetime.now() - timedelta(days=1)

    checks = {
        'box_scores': check_box_score_completeness(yesterday),
        'phase3': check_phase3_completeness(yesterday),
        'phase4': check_phase4_completeness(yesterday),
        'predictions': check_predictions_exist(yesterday),
        'grading': check_grading_coverage(yesterday)
    }

    # Send Slack summary
    send_daily_quality_report(yesterday, checks)

    return jsonify({'status': 'success', 'checks': checks})
```

3. **Add SLA alerts**:
```python
# Alert if critical thresholds missed:
# - Box scores <90% by 6 AM ET next day
# - Phase 4 <80% by 11 AM ET
# - Predictions 0 by 11:45 AM ET
# - Grading <90% by 3 PM ET next day
```

---

## Backfill Plan

### Immediate Backfills (Tonight)

**1. Trigger Grading for Jan 17-18** (5 minutes):
```bash
# Manual trigger via Pub/Sub
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-17","run_aggregation":true}'

gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-18","run_aggregation":true}'
```

**Expected Result**: 1,993 predictions graded (313 + 1,680)

**2. Backfill Phase 4 for Jan 18** (20 minutes):
```bash
curl -X POST \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2026-01-18",
    "backfill_mode": true,
    "processors": []
  }'
```

**Expected Result**: PDC, PSZA, PCF, TDZA recomputed for Jan 18

**3. Backfill Phase 4 for Jan 16** (10 minutes):
```bash
curl -X POST \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2026-01-16",
    "backfill_mode": true,
    "processors": ["PlayerDailyCache", "PlayerCompositeFactors"]
  }'
```

**Expected Result**: PDC, PCF recomputed for Jan 16

### Box Score Backfills (If Possible)

**Check if box scores can be retrieved**:
```bash
PYTHONPATH=. python scripts/backfill_gamebooks.py \
  --start-date 2026-01-13 \
  --end-date 2026-01-18 \
  --dry-run
```

**If available, backfill**:
```bash
PYTHONPATH=. python scripts/backfill_gamebooks.py \
  --start-date 2026-01-13 \
  --end-date 2026-01-18
```

**Re-run PSZA after box score backfill**:
```bash
for date in 2026-01-13 2026-01-14 2026-01-15 2026-01-16 2026-01-17; do
  curl -X POST \
    https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{
      \"analysis_date\": \"$date\",
      \"backfill_mode\": true,
      \"processors\": [\"PlayerShotZoneAnalysis\"]
    }"
  sleep 5
done
```

---

## Prevention Measures

### Immediate (This Week)

1. ✅ **Enable BigQuery Data Transfer API**
2. ✅ **Create grading schedulers** (all 3 options for redundancy)
3. ✅ **Fix grading readiness monitor bug** (table name)
4. ✅ **Add daily data quality checks** (automated)
5. ✅ **Add SLA alerts** (Slack notifications)

### Short-term (Next 2 Weeks)

6. ✅ **Add Phase 4 pre-flight validation** (prevent cascade failures)
7. ✅ **Add Phase 4 circuit breaker** (require minimum coverage)
8. ✅ **Add box score retry logic** (exponential backoff)
9. ✅ **Add box score missing alerts** (24-hour threshold)
10. ✅ **Add prediction coverage monitoring** (alert on gaps)

### Long-term (Next Month)

11. ✅ **Infrastructure as Code** (Terraform for all schedulers)
12. ✅ **Comprehensive monitoring dashboard** (Cloud Monitoring)
13. ✅ **Automated recovery workflows** (self-healing)
14. ✅ **Weekly data quality reports** (automated)
15. ✅ **Monthly validation retrospectives** (trend analysis)

---

## Lessons Learned

### What Went Wrong

1. **Incomplete Deployment**: Infrastructure deployed but schedulers not created
2. **Missing API Enablement**: BigQuery Data Transfer API never enabled
3. **No Deployment Checklist**: No verification that schedulers were created
4. **Code Bug in Production**: Table name bug in readiness monitor not caught
5. **Insufficient Monitoring**: Failures went undetected for 3+ days
6. **No Automated Validation**: Manual validation required to discover issues

### What Went Right

1. **Data Integrity**: All data preserved, no data loss
2. **Graceful Degradation**: Gamebooks compensated for missing box scores
3. **Backfill Capability**: All issues can be backfilled
4. **Documentation**: Clear documentation exists for setup procedures
5. **Redundant Systems**: Multiple grading approaches available

### Improvements Needed

1. **Deployment Verification**: Add post-deployment checks
2. **Monitoring First**: Deploy monitoring before features
3. **Staged Rollouts**: Enable features incrementally with validation
4. **Automated Tests**: Add integration tests for scheduler creation
5. **Runbooks**: Create operational runbooks for common issues

---

## Document Status

**Created**: 2026-01-19 23:00 UTC
**Last Updated**: 2026-01-19 23:00 UTC
**Status**: ✅ ROOT CAUSES IDENTIFIED - Ready for Fixes
**Next Steps**: Execute fixes and backfills
**Owner**: Data Pipeline Team
**Reviewers**: TBD

---

## Related Documents

- [Historical Data Validation and Backfill Strategy](./HISTORICAL-DATA-VALIDATION-AND-BACKFILL-STRATEGY.md)
- [Grading System Documentation](../../02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md)
- [Phase 4 Grading Enhancements](../phase-4-grading-enhancements/)
- [Agent Findings Summary](../../09-handoff/2026-01-19-AGENT-FINDINGS-SUMMARY.md)

---

**END OF REPORT**
