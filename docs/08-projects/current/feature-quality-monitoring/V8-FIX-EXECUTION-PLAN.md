# V8 Hit Rate Fix - Execution Plan

**Created:** 2026-02-01 (Session 63)
**Updated:** 2026-02-01 (Session 64) - Root Cause Corrected
**Status:** Ready for Execution
**Priority:** CRITICAL

---

## ⚠️ Session 64 Update: Original Hypothesis DISPROVEN

The original Session 63 hypothesis (Vegas line coverage difference) was **WRONG**.

### Original Hypothesis (DISPROVEN)

> Daily mode uses Phase 3 for Vegas lines (43% coverage) while backfill uses raw tables (95% coverage).

### Actual Root Cause (CONFIRMED)

> Jan 30 morning backfill ran with **broken code** because the feature enrichment fix was committed but not deployed.

**Evidence:**

| Period | Vegas Coverage | Hit Rate | Conclusion |
|--------|---------------|----------|------------|
| Jan 1-7 | 37.5% | 66.1% | Lower coverage, HIGHER hit rate |
| Jan 9+ | 45.3% | 50.4% | Higher coverage, LOWER hit rate |

The Vegas coverage is actually **HIGHER** in the broken period!

### Timeline (UTC)

| Time | Event |
|------|-------|
| Jan 30 03:17 | Feature enrichment fix committed (ea88e526) |
| Jan 30 07:41 | Jan 9+ backfill ran → **Used BROKEN code** |
| Jan 30 19:10 | Fix finally deployed → **12 hours too late** |

---

## Executive Summary

V8 hit rate collapsed from 62-70% (Jan 1-7) to 40-58% (Jan 9+). The root cause is a **deployment timing bug**: the Jan 30 backfill ran before the feature enrichment fix was deployed.

The fix is already deployed. We need to:
1. **Regenerate** Jan 9-28 predictions with fixed code
2. **Add monitoring** to prevent recurrence
3. **Add schema fields** for better future investigations

---

## Phase 1: Verify Fix is Deployed ✅ COMPLETE

The fix (commit ea88e526) was deployed on Jan 30 19:10 UTC.

**Verification:**
```bash
gcloud run revisions describe prediction-worker-00047-qkx --region=us-west2 \
  --format="value(metadata.creationTimestamp)"
# Returns: 2026-01-30T21:29:28.111003Z (after fix)
```

**Evidence fix works:**
- Predictions made AFTER fix: 58.5% hit rate
- Predictions made BEFORE fix: 50.6% hit rate
- Improvement: +8 percentage points

---

## Phase 2: Regenerate Predictions

### Goal
Re-run predictions for Jan 9-28 using the fixed code.

### Step 2.1: Mark Old Predictions as Superseded

```sql
-- Mark broken predictions so they don't affect grading
UPDATE nba_predictions.player_prop_predictions
SET
  superseded = TRUE,
  superseded_at = CURRENT_TIMESTAMP(),
  superseded_reason = 'Session 64: Regenerating with fixed code (ea88e526)',
  is_active = FALSE
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  AND created_at >= '2026-01-30 07:00:00'  -- The broken backfill
  AND created_at < '2026-01-30 19:00:00'   -- Before fix deployed
```

### Step 2.2: Regenerate Predictions

```bash
# Verify deployment first
./bin/check-deployment-drift.sh

# Dry run
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28 \
  --dry-run

# Actual regeneration
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28
```

### Step 2.3: Verify Improvement

```sql
-- Compare hit rates before/after regeneration
SELECT
  'Before regeneration' as period,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09' AND game_date <= '2026-01-28'
  AND prediction_correct IS NOT NULL
  -- Add filter for superseded once regenerated
```

**Success Criteria:** Hit rate improves from ~50% to >58%

---

## Phase 3: Add Tracking Fields to Schema

### Goal
Add fields to make future investigations easier.

### Step 3.1: Add Schema Fields

```sql
-- Add to player_prop_predictions
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS deployment_revision STRING,
ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS critical_features JSON;

-- Add to ml_feature_store_v2
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS feature_source_mode STRING,
ADD COLUMN IF NOT EXISTS vegas_line_source STRING;

-- Add to prediction_accuracy
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN IF NOT EXISTS build_commit_sha STRING,
ADD COLUMN IF NOT EXISTS critical_features JSON;
```

### Step 3.2: Update Code to Populate Fields

See [V8-INVESTIGATION-LEARNINGS.md](./V8-INVESTIGATION-LEARNINGS.md) for detailed code changes.

Key changes:
1. Prediction worker reads BUILD_COMMIT from env
2. Prediction worker stores critical_features JSON
3. Feature store processor tracks feature_source_mode

---

## Phase 4: Add Automated Monitoring

### Goal
Detect hit rate issues within 24 hours, not 3 weeks.

### Step 4.1: Add Hit Rate Monitoring to /validate-daily

```sql
-- Daily hit rate with alerts
WITH daily_rates AS (
  SELECT game_date, COUNT(*) as preds,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v8'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND prediction_correct IS NOT NULL
  GROUP BY 1
)
SELECT game_date, preds, hit_rate,
  CASE
    WHEN hit_rate < 50 THEN '🔴 CRITICAL'
    WHEN hit_rate < 55 THEN '🟠 WARNING'
    ELSE '✅ OK'
  END as status
FROM daily_rates
ORDER BY game_date DESC
```

### Step 4.2: Add Feature Quality Checks

```sql
-- Check for broken features
SELECT
  'Vegas has_vegas_line' as feature,
  ROUND(100.0 * COUNTIF(features[OFFSET(28)] = 1.0) / COUNT(*), 1) as coverage_pct,
  CASE WHEN ... < 30 THEN '🔴 LOW' ELSE '✅ OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1
```

### Step 4.3: Create Pre-Backfill Check Script

```bash
#!/bin/bash
# bin/verify-deployment-before-backfill.sh

SERVICE=$1
REQUIRED_COMMIT=$(git rev-parse HEAD)
DEPLOYED_COMMIT=$(gcloud run services describe $SERVICE --region=us-west2 \
  --format="value(metadata.labels.commit-sha)")

if [[ "$DEPLOYED_COMMIT" != "$REQUIRED_COMMIT" ]]; then
  echo "❌ DEPLOYMENT MISMATCH! Deploy first."
  exit 1
fi
echo "✅ Safe to run backfill."
```

---

## Phase 5: Process Improvements

### 5.1 Deployment-First Policy

**Rule:** Always deploy fixes BEFORE running backfills.

Add to CLAUDE.md:
```markdown
### CRITICAL: Deploy Before Backfill

Before running any backfill:
1. Commit all fixes
2. Run `./bin/deploy-service.sh <service>`
3. Run `./bin/verify-deployment-before-backfill.sh <service>`
4. Then run backfill
```

### 5.2 Code Version in All Outputs

**Rule:** Every generated table includes `build_commit_sha`.

---

## Execution Timeline

| Phase | Task | Priority | Status |
|-------|------|----------|--------|
| **1** | Verify fix deployed | HIGH | ✅ COMPLETE |
| **2.1** | Mark old predictions superseded | HIGH | TODO |
| **2.2** | Regenerate predictions | HIGH | TODO |
| **2.3** | Verify improvement | HIGH | TODO |
| **3.1** | Add schema fields | MEDIUM | TODO |
| **3.2** | Update code for new fields | MEDIUM | TODO |
| **4.1** | Add hit rate to /validate-daily | HIGH | TODO |
| **4.2** | Add feature quality checks | MEDIUM | TODO |
| **4.3** | Create pre-backfill script | HIGH | TODO |
| **5** | Update CLAUDE.md | MEDIUM | TODO |

---

## Success Criteria

| Metric | Before Fix | After Fix | Target |
|--------|------------|-----------|--------|
| Jan 9+ hit rate | 50.4% | ? | >58% |
| High-edge hit rate | 50.9% | ? | >65% |
| MAE | 5.8 pts | ? | <5.0 pts |
| Code version tracked | No | Yes | 100% |
| Hit rate monitoring | None | Daily | Automated |

---

## Related Documents

- [Session 64 Investigation](../../09-handoff/2026-02-01-SESSION-64-INVESTIGATION.md) - Root cause analysis
- [V8 Investigation Learnings](./V8-INVESTIGATION-LEARNINGS.md) - Prevention improvements
- [Session 63 Investigation (superseded)](./2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md)

---

*Created: 2026-02-01 Session 63*
*Updated: 2026-02-01 Session 64 - Root cause corrected*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
