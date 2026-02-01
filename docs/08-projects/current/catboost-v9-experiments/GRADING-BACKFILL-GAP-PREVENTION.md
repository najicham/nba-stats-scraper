# Grading Backfill Gap - Prevention Plan

**Date**: February 1, 2026
**Issue**: Session 68 - V9 analysis based on incomplete grading data
**Priority**: P1 - Prevent validation confusion

---

## What Went Wrong

### The Data Flow Gap

```
┌─────────────────────────────────────────────────────────────────┐
│ V9 Backfill Process (What Actually Happened)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ 1. ml/backfill_v8_predictions.py                                │
│    ├─ Reads: ml_feature_store_v2                                │
│    └─ Writes: player_prop_predictions ✅ (6,665 records)        │
│                                                                  │
│ 2. ❌ MISSING STEP: Grading backfill NOT run                    │
│    └─ prediction_accuracy table NOT updated                     │
│                                                                  │
│ 3. Daily grading (prediction_accuracy_processor.py)             │
│    ├─ Only grades NEW predictions (Jan 31+)                     │
│    └─ Writes: prediction_accuracy ✅ (94 records - Jan 31 only) │
│                                                                  │
│ 4. Validation (/validate-daily)                                 │
│    ├─ Uses: prediction_accuracy (WRONG SOURCE!)                 │
│    └─ Result: Sees 94 records, concludes V9 is bad ❌           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### The Correct Flow (What Should Have Happened)

```
┌─────────────────────────────────────────────────────────────────┐
│ Correct V9 Backfill Process                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ 1. ml/backfill_v8_predictions.py                                │
│    └─ Writes: player_prop_predictions ✅                        │
│                                                                  │
│ 2. ✅ AUTOMATIC: Trigger grading backfill                       │
│    └─ backfill_jobs/grading/prediction_accuracy/                │
│       prediction_accuracy_grading_backfill.py                   │
│       └─ Writes: prediction_accuracy ✅ (6,665 records)         │
│                                                                  │
│ 3. Validation                                                   │
│    ├─ Uses: prediction_accuracy (NOW COMPLETE!)                 │
│    └─ Result: Sees 6,665 records, correct analysis ✅           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Root Causes

### 1. Manual Two-Step Process ❌

**Problem**: Prediction backfill and grading backfill are separate manual scripts

**Evidence**:
- `ml/backfill_v8_predictions.py` - generates predictions
- `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py` - grades predictions
- NO automatic trigger between them

**Impact**: Easy to forget the second step

### 2. Validation Uses Wrong Data Source for Backfills ❌

**Problem**: `/validate-daily` and all validation skills use `prediction_accuracy` table

**Evidence**:
```python
# From .claude/skills/validate-daily/SKILL.md
SELECT * FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'  # Only has live-graded predictions!
```

**Impact**: Validation misses backfilled predictions entirely

### 3. No Data Completeness Checks ❌

**Problem**: No validation that checks if both tables are in sync

**Evidence**: We had 6,665 predictions vs 94 graded - no alert fired

**Impact**: Silent data gaps go undetected

---

## Prevention Measures

### Fix 1: Automatic Grading Trigger (P1 - CRITICAL)

**Change**: Make prediction backfill scripts automatically trigger grading

**Implementation**:

```python
# In ml/backfill_v8_predictions.py - add at the end of main()

def run_grading_backfill(start_date: date, end_date: date, dry_run: bool = False):
    """Automatically trigger grading backfill after predictions."""
    if dry_run:
        logger.info(f"[DRY RUN] Would trigger grading backfill for {start_date} to {end_date}")
        return

    logger.info(f"Triggering grading backfill for {start_date} to {end_date}")

    # Import grading backfill
    from backfill_jobs.grading.prediction_accuracy.prediction_accuracy_grading_backfill import PredictionAccuracyBackfill

    grader = PredictionAccuracyBackfill()
    grader.backfill_date_range(start_date, end_date)

    logger.info("Grading backfill completed")

# In main() after predictions are written:
if not args.dry_run:
    logger.info("=== Step 2: Running grading backfill ===")
    run_grading_backfill(args.start_date, args.end_date, args.dry_run)
    logger.info("=== Backfill complete (predictions + grading) ===")
```

**Files to Change**:
- `ml/backfill_v8_predictions.py`
- Any other prediction backfill scripts

**Testing**:
```bash
# Test with small date range
PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2026-02-01 --end-date 2026-02-01 --dry-run

# Verify both steps are triggered
```

### Fix 2: Validation Data Source Fallback (P1 - CRITICAL)

**Change**: Update validation to check BOTH tables and warn on discrepancy

**Implementation**:

Add to `.claude/skills/validate-daily/SKILL.md`:

```sql
-- NEW: Data Completeness Check (Priority 0.3)
WITH prediction_counts AS (
  SELECT
    'player_prop_predictions' as source,
    system_id,
    COUNT(*) as record_count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id

  UNION ALL

  SELECT
    'prediction_accuracy' as source,
    system_id,
    COUNT(*) as record_count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as pred_count,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded_count,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as grading_coverage_pct,
  CASE
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 50
    THEN '🔴 CRITICAL - Grading backfill missing'
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 80
    THEN '🟡 WARNING - Partial grading gap'
    ELSE '✅ OK'
  END as status
FROM prediction_counts
GROUP BY system_id
ORDER BY system_id
```

**Alert Thresholds**:
- <50% grading coverage → 🔴 CRITICAL
- 50-80% → 🟡 WARNING
- ≥80% → ✅ OK

### Fix 3: Use Correct Source for Backfilled Data (P1 - CRITICAL)

**Change**: When analyzing models with backfilled data, use `player_prop_predictions` + `player_game_summary` join

**Implementation**:

Add to validation skills documentation:

```markdown
## IMPORTANT: Data Source Selection

### When to Use Each Table

| Use Case | Table | Why |
|----------|-------|-----|
| **Live production analysis** | `prediction_accuracy` | Real-time grading, all fields populated |
| **Backfilled predictions** | `player_prop_predictions` + `player_game_summary` | Grading may be delayed/missing |
| **Historical analysis (2021-2025)** | `prediction_accuracy` | Fully graded historical data |

### Detection Rule

**If record count discrepancy >20%**, use the join approach:

```sql
-- CORRECT for backfilled data
SELECT
  p.system_id,
  p.game_date,
  p.predicted_points,
  p.current_points_line as line_value,
  pgs.points as actual_points,
  CASE
    WHEN pgs.points > p.current_points_line AND p.recommendation = 'OVER' THEN TRUE
    WHEN pgs.points < p.current_points_line AND p.recommendation = 'UNDER' THEN TRUE
    WHEN pgs.points = p.current_points_line THEN NULL  -- Push
    ELSE FALSE
  END as prediction_correct
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup
  AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9'
```
```

### Fix 4: Automated Data Completeness Alert (P2 - HIGH)

**Change**: Create daily automated check for grading gaps

**Implementation**:

Create `bin/alerts/grading_completeness_check.py`:

```python
#!/usr/bin/env python3
"""
Daily check for grading completeness across prediction tables.

Alerts if prediction_accuracy is missing >20% of player_prop_predictions
for any model in the last 7 days.

Run via Cloud Scheduler: daily at 6 AM ET (after overnight grading)
"""

from google.cloud import bigquery
from datetime import datetime, timedelta
import requests
import os

PROJECT_ID = 'nba-props-platform'

def check_grading_completeness():
    """Check if grading is complete for all models."""
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    WITH prediction_counts AS (
      SELECT
        'predictions' as source,
        system_id,
        COUNT(*) as record_count
      FROM nba_predictions.player_prop_predictions
      WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      GROUP BY system_id

      UNION ALL

      SELECT
        'graded' as source,
        system_id,
        COUNT(*) as record_count
      FROM nba_predictions.prediction_accuracy
      WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      GROUP BY system_id
    )
    SELECT
      system_id,
      MAX(CASE WHEN source = 'predictions' THEN record_count END) as pred_count,
      MAX(CASE WHEN source = 'graded' THEN record_count END) as graded_count,
      ROUND(100.0 * MAX(CASE WHEN source = 'graded' THEN record_count END) /
            NULLIF(MAX(CASE WHEN source = 'predictions' THEN record_count END), 0), 1) as coverage_pct
    FROM prediction_counts
    GROUP BY system_id
    HAVING coverage_pct < 80  -- Alert on <80% coverage
    """

    results = client.query(query).to_dataframe()

    if len(results) > 0:
        # Send Slack alert
        send_slack_alert(results)

    return results

def send_slack_alert(results):
    """Send alert to Slack about grading gaps."""
    # Build message
    message = "🔴 *Grading Completeness Alert*\n\n"
    message += "The following models have incomplete grading:\n\n"

    for _, row in results.iterrows():
        message += f"• *{row['system_id']}*: {row['coverage_pct']}% graded ({row['graded_count']}/{row['pred_count']})\n"

    message += f"\n*Action Required:* Run grading backfill\n"
    message += "```\npython backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date <date> --end-date <date>\n```"

    # Send to Slack webhook
    webhook_url = os.getenv('SLACK_WEBHOOK_URL_ERROR')
    requests.post(webhook_url, json={'text': message})

if __name__ == '__main__':
    check_grading_completeness()
```

**Cloud Scheduler Job**:
```bash
gcloud scheduler jobs create http grading-completeness-check \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-run.googleapis.com/.../grading-completeness-check" \
  --http-method=POST
```

### Fix 5: Documentation Updates (P2 - HIGH)

**Change**: Update CLAUDE.md with grading table selection guidance

**Add to CLAUDE.md**:

```markdown
### Grading Tables (IMPORTANT!)

**Two sources of prediction grading data:**

| Table | Use For | Completeness |
|-------|---------|--------------|
| `prediction_accuracy` | Live production analysis, historical data | May miss backfills |
| `player_prop_predictions` + join | Backfilled predictions, data quality analysis | Always complete |

**Rule**: Always check record counts. If `prediction_accuracy` has <80% of `player_prop_predictions`, use the join approach.

**Verification Query** (run before model analysis):
```sql
SELECT
  COUNT(*) as predictions,
  (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-09') as graded,
  ROUND(100.0 * (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-09') / COUNT(*), 1) as coverage_pct
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date >= '2026-01-09'
```

If `coverage_pct` < 80%, use player_prop_predictions for analysis.
```

---

## Implementation Priority

| Fix | Priority | Complexity | Impact |
|-----|----------|------------|--------|
| 1. Auto grading trigger | P1 | Medium | Prevents gap creation |
| 2. Validation fallback | P1 | Low | Detects existing gaps |
| 3. Correct source docs | P1 | Low | Prevents wrong analysis |
| 4. Automated alert | P2 | Medium | Ongoing monitoring |
| 5. Documentation | P2 | Low | Knowledge sharing |

---

## Immediate Actions (Today)

### 1. Fix V9 Grading Gap ✅ DONE (User Already Corrected)

The gap has been identified and documented. V9 is performing excellently (79.4% high-edge hit rate).

### 2. Backfill V9 Grading to prediction_accuracy

```bash
# Run the grading backfill for V9's date range
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-31
```

**Expected Result**: `prediction_accuracy` should have ~6,665 V9 records after this runs

### 3. Verify Grading Backfill Worked

```sql
-- Check before/after counts
SELECT
  'player_prop_predictions' as source,
  COUNT(*) as v9_records
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'

UNION ALL

SELECT
  'prediction_accuracy',
  COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
```

**Target**: Both sources should show ~6,665 records

---

## Testing Plan

### Test Scenario 1: New Model Backfill

```bash
# 1. Create small test backfill
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --model-version v9 \
  --start-date 2026-02-01 \
  --end-date 2026-02-01 \
  --dry-run

# 2. Verify it triggers grading
# Should see: "=== Step 2: Running grading backfill ==="

# 3. Check both tables have same count
# Query both tables, verify counts match
```

### Test Scenario 2: Validation Detects Gap

```bash
# 1. Create prediction without grading (simulate gap)
# Insert into player_prop_predictions only

# 2. Run validation
/validate-daily

# 3. Verify alert fires
# Should see: "🔴 CRITICAL - Grading backfill missing (50% coverage)"
```

### Test Scenario 3: Automated Alert

```bash
# 1. Run grading completeness check
python bin/alerts/grading_completeness_check.py

# 2. If gap exists, verify Slack alert sent
# Check #app-error-alerts channel
```

---

## Success Metrics

After implementing all fixes:

| Metric | Before | Target |
|--------|--------|--------|
| Manual grading backfill required | Always | Never (automatic) |
| Validation false negatives | 100% (Session 68) | 0% |
| Time to detect grading gap | Never (silent) | <24 hours (automated alert) |
| Analysis accuracy | Wrong (94 vs 6,665 records) | Correct (use right source) |

---

## Lessons Learned

### For Future Development

1. **Two-phase operations need automation** - If step A requires step B, automate the trigger
2. **Always verify data completeness** - Don't assume tables are in sync
3. **Document data source selection** - Multiple tables → need clear usage rules
4. **Alert on silent failures** - Missing data should trigger alerts, not just errors
5. **Backfills are special cases** - Daily orchestration logic ≠ backfill logic

### For Future Analysis

1. **Check record counts first** - Before analyzing, verify you have complete data
2. **Use the join when in doubt** - `player_prop_predictions` + `player_game_summary` is always complete
3. **Verify across tables** - If numbers seem wrong, check alternate data sources
4. **Small samples are red flags** - 94 records when expecting thousands → investigate

---

## Related Documents

- Original incorrect analysis: `V9-EDGE-FINDING-PERFORMANCE-ISSUE.md` (superseded)
- Session handoff: `docs/09-handoff/2026-02-01-SESSION-68-VALIDATION-V9-ANALYSIS.md`
- Session 67 handoff: `docs/09-handoff/2026-02-01-SESSION-67-HANDOFF.md` (correct V9 data)

---

**Status**: 📋 Action Plan Created
**Next Step**: Implement Fix 1 (Auto grading trigger) and Fix 2 (Validation fallback)
**Owner**: Next session
**Review Date**: After implementation, verify with test backfill

---

*Created: Session 68, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
