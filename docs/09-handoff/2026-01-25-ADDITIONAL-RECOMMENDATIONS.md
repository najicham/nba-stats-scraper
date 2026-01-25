# Additional Recommendations & Risk Mitigations

**Date:** 2026-01-25
**Purpose:** Supplementary findings to review before deployment
**Priority:** HIGH - Review before deploying auto-retry fix

---

## New Finding: Duplicate Prediction Records

### The Problem

Predictions are being inserted twice for the same player/game/system combination:

```
| game_date  | total_rows | unique_player_games | duplicate_rows |
|------------|------------|---------------------|----------------|
| 2026-01-22 |        609 |                  88 |            521 |
| 2026-01-23 |       5193 |                  85 |           5108 |
| 2026-01-24 |        486 |                  65 |            421 |
| 2026-01-25 |        467 |                  81 |            386 |
```

### Root Cause

The prediction processor ran twice without deduplication:
- First batch: 2026-01-23 22:48:24
- Second batch: 2026-01-24 12:18:57

Same values, same systems (moving_average, catboost_v8, etc.), just inserted twice.

### Impact

- Inflated row counts
- Potential double-counting in analytics
- Grading may process same prediction multiple times

### Fix Options

**Option 1: Cleanup existing duplicates**
```sql
-- Create deduplicated view or delete duplicates
CREATE OR REPLACE TABLE `nba_predictions.player_prop_predictions_deduped` AS
SELECT * FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id, system_id, game_date
      ORDER BY created_at DESC
    ) as rn
  FROM `nba_predictions.player_prop_predictions`
)
WHERE rn = 1;
```

**Option 2: Add unique constraint/deduplication to processor**
```python
# In prediction processor, before insert:
DELETE FROM predictions WHERE game_date = @date AND system_id = @system
INSERT INTO predictions ...
```

### Priority

MEDIUM - Not blocking, but should be cleaned up to ensure accurate counts.

---

## Critical: HTTP Endpoint URL Mismatch

### The Problem

The auto-retry processor HTTP endpoints use a **different URL format** than the actual Cloud Run services:

**Code uses (lines 48-51 in auto_retry_processor/main.py):**
```python
PHASE_HTTP_ENDPOINTS = {
    'phase_2': 'https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_3': 'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_4': 'https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process',
    'phase_5': 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/predict',
}
```

**Actual Cloud Run service URLs (from `gcloud run services list`):**
```
nba-phase2-raw-processors         https://nba-phase2-raw-processors-756957797294.us-west2.run.app
nba-phase3-analytics-processors   https://nba-phase3-analytics-processors-756957797294.us-west2.run.app
nba-phase4-precompute-processors  https://nba-phase4-precompute-processors-756957797294.us-west2.run.app
prediction-coordinator            https://prediction-coordinator-756957797294.us-west2.run.app
```

### Risk

The `-f7p3g7f6ya-wl.a.run.app` format is the Cloud Functions (2nd gen) alias. It may work, but should be verified before deployment.

### Verification Before Deployment

```bash
# Test that the URL format works (should return 200 or 403, not DNS error)
curl -s -o /dev/null -w "%{http_code}\n" \
  https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/health

# If it returns 000 or DNS error, use the direct format instead:
curl -s -o /dev/null -w "%{http_code}\n" \
  https://nba-phase2-raw-processors-756957797294.us-west2.run.app/health
```

### Recommended Fix (if URLs don't resolve)

```python
# Update to use actual Cloud Run URLs
PHASE_HTTP_ENDPOINTS = {
    'phase_2': 'https://nba-phase2-raw-processors-756957797294.us-west2.run.app/process',
    'phase_3': 'https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process',
    'phase_4': 'https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process',
    'phase_5': 'https://prediction-coordinator-756957797294.us-west2.run.app/predict',
}
```

---

## Missing Infrastructure

### 1. Gate Overrides Audit Table Not Created

The FINAL-COMPREHENSIVE-HANDOFF mentions a gate override strategy with an audit table, but the table doesn't exist:

```bash
# Verify (returns empty = doesn't exist)
bq query --use_legacy_sql=false "
SELECT table_name FROM nba_orchestration.INFORMATION_SCHEMA.TABLES
WHERE table_name = 'gate_overrides'"
```

**Create it:**
```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.gate_overrides` (
    override_id STRING DEFAULT GENERATE_UUID(),
    gate_name STRING NOT NULL,
    target_date DATE NOT NULL,
    overridden_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    overridden_by STRING,
    reason STRING,
    original_decision STRING,
    metadata JSON
)
PARTITION BY DATE(overridden_at)
CLUSTER BY gate_name, target_date;
```

### 2. Daily Reconciliation Not Automated

The `daily_reconciliation.py` script exists but is NOT scheduled:

```bash
# Current scheduled jobs (no reconciliation)
gcloud scheduler jobs list --location us-central1 | grep -i "reconcil\|health"
# Returns nothing
```

**Recommendation:** Add to validation scheduling (P1.1) when implemented.

### 3. IAM Verification (Confirmed OK)

The compute service account has `roles/run.invoker` permission:
```
756957797294-compute@developer.gserviceaccount.com → roles/run.invoker
```

This is correct - auto-retry can invoke the Cloud Run services.

---

## Operational Risks & Mitigations

### Risk 1: Retry Idempotency

**Problem:** If a retry succeeds but the status update fails, the processor may run again creating duplicates.

**Current State:** Not explicitly addressed in the code.

**Mitigation:** The processors themselves should have idempotency (MERGE_UPDATE pattern). Verify:
```python
# In processor_base.py, confirm this pattern exists:
# DELETE existing records for game_date/game_id
# INSERT new records
# This ensures retries don't create duplicates
```

### Risk 2: ESPN Fallback Not Implemented

**Problem:** The boxscore fallback strategy mentions ESPN, but it's P2.5 (not done).

**Current State:** If BDL fails repeatedly, there's NO fallback.

**Impact:** GSW@MIN may never be recovered if BDL doesn't have the data.

**Mitigation:**
1. Check if BDL now has GSW@MIN data:
```bash
curl -s "https://api.balldontlie.io/v1/stats?dates[]=2026-01-24" \
  -H "Authorization: YOUR_API_KEY" | jq '.data | length'
```
2. If still missing, consider manual data entry or marking as permanently unavailable.

### Risk 3: No Fallback for HTTP Retry Failures

**Problem:** If HTTP calls fail (network issue, service down), there's no secondary mechanism.

**Mitigation:** Add alerting for consecutive HTTP failures:
```python
# In auto_retry_processor, track consecutive failures
if consecutive_http_failures >= 3:
    send_slack_alert(f"Auto-retry HTTP calls failing: {endpoint}")
```

---

## Pre-Deployment Checklist

### Before Deploying Auto-Retry Fix

- [ ] **Verify HTTP URLs resolve:**
  ```bash
  curl -s -o /dev/null -w "%{http_code}" \
    https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/health
  # Should return 200, 401, 403, or 404 (NOT 000 or connection refused)
  ```

- [ ] **Test with one endpoint manually:**
  ```bash
  # Get auth token
  TOKEN=$(gcloud auth print-identity-token)

  # Test Phase 2 endpoint
  curl -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action": "health_check"}' \
    https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process
  ```

- [ ] **Verify IAM permissions:**
  ```bash
  gcloud run services get-iam-policy nba-phase2-raw-processors --region us-west2
  # Should show 756957797294-compute with run.invoker
  ```

### After Deploying Auto-Retry Fix

- [ ] **Monitor for errors:**
  ```bash
  gcloud functions logs read auto-retry-processor --region us-west2 --limit 20 \
    | grep -E "ERROR|Failed|HTTP"
  # Should see "HTTP 200" or "HTTP 202", NOT errors
  ```

- [ ] **Verify GSW@MIN gets retried:**
  ```bash
  bq query --use_legacy_sql=false "
  SELECT status, retry_count, last_retry_at
  FROM nba_orchestration.failed_processor_queue
  WHERE game_date = '2026-01-24'"
  # Should show status='retrying' or 'succeeded'
  ```

---

## Tonight's Games Monitoring (Jan 25)

7 games scheduled. After ~11 PM ET:

```bash
# 1. Check all games have boxscores
bq query --use_legacy_sql=false "
SELECT
  (SELECT COUNT(DISTINCT game_id) FROM nba_raw.bdl_player_boxscores WHERE game_date = '2026-01-25') as boxscores,
  (SELECT COUNT(*) FROM nba_raw.v_nbac_schedule_latest WHERE game_date = '2026-01-25' AND game_status = 3) as completed_games"
# Expected: both = 7

# 2. Check auto-retry is clean (no new failures)
bq query --use_legacy_sql=false "
SELECT game_date, processor_name, status, error_message
FROM nba_orchestration.failed_processor_queue
WHERE game_date = '2026-01-25'"
# Expected: empty or all 'succeeded'

# 3. Check analytics processed
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id)
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-25'"
# Expected: 7

# 4. Check predictions were made
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-25'"
# Expected: 7
```

---

## Test New Validators

Before relying on them in production:

```bash
# Run each validator and verify no Python errors

# 1. Quality trend monitor
python bin/validation/quality_trend_monitor.py --date 2026-01-24
# Should output trend analysis, not crash

# 2. Cross-phase consistency
python bin/validation/cross_phase_consistency.py --date 2026-01-24
# Should show phase transition rates

# 3. Entity tracing
python bin/validation/trace_entity.py --player "lebron-james" --date 2026-01-24
# Should trace through all phases

# 4. Post-backfill validation
python bin/validation/validate_backfill.py --phase raw --date 2026-01-24
# Should report on data completeness
```

---

## Feature Quality Recovery Timeline

**Current State:** Avg 64.4 (all bronze tier)

**Root Cause:** Rolling windows became stale during 45-hour Firestore outage.

**Recovery Process:**
1. As new games complete, rolling windows rebuild
2. L5D (last 5 days) recovers first (~2-3 days)
3. L10D (last 10 days) takes longer (~7-10 days)
4. Full recovery expected in ~2 weeks

**Monitoring:**
```bash
# Track daily quality improvement
bq query --use_legacy_sql=false "
SELECT
  game_date,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNT(*) as features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-22'
GROUP BY 1
ORDER BY 1"
```

**Expected Trend:**
- Jan 24: 64.4 (bronze)
- Jan 26: ~66 (bronze)
- Jan 28: ~70 (silver threshold)
- Feb 1: ~75 (gold threshold)

---

## Phase Execution Log Investigation

The table exists but has no data. Investigation steps:

```bash
# 1. Check if logging function is called in deployed code
gcloud functions describe phase3-to-phase4-orchestrator --region us-west2 \
  --format='value(buildConfig.source.storageSource.object)' 2>/dev/null

# 2. Search logs for any logging-related errors
gcloud functions logs read phase3-to-phase4-orchestrator --region us-west2 --limit 100 \
  | grep -i "phase_execution\|logging\|bigquery\|permission"

# 3. Test manual insert
bq query --use_legacy_sql=false "
INSERT INTO nba_orchestration.phase_execution_log
(execution_timestamp, phase_name, game_date, status, duration_seconds, games_processed)
VALUES (CURRENT_TIMESTAMP(), 'manual_test', '2026-01-25', 'test', 0.1, 0)"

# 4. Check if it was inserted
bq query --use_legacy_sql=false "
SELECT * FROM nba_orchestration.phase_execution_log
WHERE phase_name = 'manual_test'"
```

**If manual insert works:** The logging function isn't being called or is silently failing.

**If manual insert fails:** Permission issue with the table or BigQuery.

---

## Bare Except Cleanup Priority

7,061 instances across codebase. Prioritize by impact:

```bash
# Find worst offenders in critical paths
grep -rn "except:" --include="*.py" orchestration/ shared/ data_processors/ \
  | grep -v "except.*:" | cut -d: -f1 | sort | uniq -c | sort -rn | head -15
```

**Recommended Phase 1 (highest impact):**
1. `/orchestration/cloud_functions/*/main.py`
2. `/shared/utils/bigquery_utils.py`
3. `/shared/utils/phase_execution_logger.py`
4. `/data_processors/raw/processor_base.py`

**Pattern to use:**
```python
# Before
try:
    risky_operation()
except:
    pass

# After
try:
    risky_operation()
except Exception as e:
    logger.warning(f"Non-critical operation failed: {e}")
    # Or for truly ignorable errors:
    logger.debug(f"Expected failure: {e}")
```

---

## Summary Checklist

| Item | Priority | Status |
|------|----------|--------|
| Verify HTTP endpoint URLs resolve | CRITICAL | Verify before deploy |
| Test one endpoint manually | CRITICAL | Verify before deploy |
| Create gate_overrides table | HIGH | Not created |
| Monitor tonight's games | HIGH | After 11 PM ET |
| Test new validators | MEDIUM | Before relying on them |
| Track feature quality recovery | MEDIUM | Ongoing |
| Investigate phase execution log | MEDIUM | After critical fixes |
| Schedule daily reconciliation | LOW | Part of P1.1 |
| Start bare except cleanup | LOW | Phased approach |

---

*Created: 2026-01-25*
*Purpose: Pre-deployment verification and risk mitigation*
*Related: FINAL-COMPREHENSIVE-HANDOFF.md, MASTER-PLAN-ADDITIONS.md*
