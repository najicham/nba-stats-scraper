# Issues to Fix

**Created:** 2026-01-25
**Updated:** 2026-01-25
**Priority:** P0

These issues were discovered during the comprehensive validation investigation.

---

## FIXED Issues

### Issue 1: Grading Filter Bug (FIXED)

**Status:** FIXED
**Fix Applied:** Removed `has_prop_line = TRUE` filter from grading processor

**Before:** Only 21 predictions graded for Jan 23
**After:** 1,294 predictions graded for Jan 23

**File Changed:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

The grading processor was filtering on `has_prop_line = TRUE`, but the `has_prop_line` field
has data inconsistencies. The `line_source` field is authoritative, so the fix uses
`line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')` without the `has_prop_line` check.

---

## Open Issues

---

## Issue 1: has_prop_line Data Bug

**Severity:** CRITICAL
**Impact:** 98% of predictions with real prop lines are NOT being graded

### Problem
The prediction system sets `has_prop_line=false` even when `line_source=ACTUAL_PROP`.

```sql
-- Jan 23 data shows:
| has_prop_line | line_source   | count |
|---------------|---------------|-------|
| false         | ACTUAL_PROP   |   218 |  <-- BUG
| true          | ACTUAL_PROP   |     4 |  <-- Only these graded
```

### Impact
- Grading processor filters on `has_prop_line = TRUE`
- 218 predictions are excluded from grading
- Accuracy metrics are based on only 4/222 predictions (2%)
- ML training data is severely limited

### Location of Bug
Need to investigate the prediction processor to find where `has_prop_line` is set.
Likely in `predictions/coordinator/` or `predictions/processors/`.

### Fix Options
1. **Fix prediction generator** - Set `has_prop_line = TRUE` when `line_source = 'ACTUAL_PROP'`
2. **Fix grading processor** - Grade all `ACTUAL_PROP` predictions regardless of flag
3. **Backfill fix** - Update historical data:
   ```sql
   UPDATE `nba_predictions.player_prop_predictions`
   SET has_prop_line = TRUE
   WHERE line_source = 'ACTUAL_PROP'
     AND has_prop_line = FALSE
   ```

### Validation
Run `bin/validation/comprehensive_health_check.py` - should show `prop_line_consistency` as OK.

---

## Issue 2: Feature Quality Degradation During Outage

**Severity:** HIGH
**Impact:** Prediction coverage dropped from normal 80%+ to 30%

### Problem
When pipeline is blocked, rolling window calculations (L7D, L14D) become incomplete.
This causes feature quality scores to drop, which filters out more players.

### Data
```
| Date   | Avg Quality | Low Quality % |
|--------|-------------|---------------|
| Jan 20 | 78.96       | 1.8%          |
| Jan 21 | 76.71       | 0.4%          |
| Jan 22 | 75.49       | 8.8%          |
| Jan 23 | 69.07       | 23.1%         |  <-- Outage impact
| Jan 24 | 64.43       | 74.6%         |  <-- Severe degradation
```

### Fix
Features need to be regenerated once analytics data is complete.

```bash
# Regenerate features for affected dates
./bin/backfill/run_phase4.sh --start-date 2026-01-23 --end-date 2026-01-24
```

---

## Issue 3: Grading Backfill Needed

**Severity:** HIGH
**Impact:** Historical predictions not graded for ML training

### Problem
After fixing Issue 1, need to re-run grading for affected dates.

### Fix
```bash
# After fixing has_prop_line bug:
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-15 --end-date 2026-01-24
```

---

## Issue 4: Props Coverage Below Target

**Severity:** MEDIUM
**Impact:** 33-62% coverage vs desired 80%+

### What is Props Coverage?

Props coverage = "Of players who have betting lines, what % received predictions?"

| Date | Players with Props | Predictions Made | Coverage |
|------|-------------------|------------------|----------|
| Jan 20 | 164 | 79 | 48.2% |
| Jan 21 | 136 | 46 | 33.8% |
| Jan 22 | 192 | 82 | 42.7% |
| Jan 23 | 107 | 67 | 62.6% |

### Why Isn't It 100%?

Three filters prevent 100% coverage (by design):

1. **Feature Quality Filter** (~23 players): Players with props but feature_quality_score < 65
2. **Data Availability** (~9 players): Players with props and good features but no prediction (BUG?)
3. **Player Registry** (~3 players): Players with props but not in our feature store

### Expected vs Actual

- **Expected coverage:** 80-90% (players with props AND good features should get predictions)
- **Current coverage:** 33-62%
- **Gap:** ~20-50% - some is filtering (OK), some is bugs (needs fix)

### Investigation Needed

The 9 players with good features but no predictions need investigation:
```sql
WITH props_players AS (
  SELECT DISTINCT player_lookup FROM `nba_raw.odds_api_player_points_props` WHERE game_date = '2026-01-23'
),
predictions AS (
  SELECT DISTINCT player_lookup FROM `nba_predictions.player_prop_predictions`
  WHERE game_date = '2026-01-23' AND system_id = 'catboost_v8' AND is_active = TRUE
),
features AS (
  SELECT player_lookup, feature_quality_score FROM `nba_predictions.ml_feature_store_v2` WHERE game_date = '2026-01-23'
)
SELECT pp.player_lookup, f.feature_quality_score
FROM props_players pp
LEFT JOIN predictions p ON pp.player_lookup = p.player_lookup
JOIN features f ON pp.player_lookup = f.player_lookup
WHERE p.player_lookup IS NULL AND f.feature_quality_score >= 65
```

---

## Issue 5: Workflow Decision Gap Alert Missing

**Severity:** MEDIUM
**Impact:** 45-hour outage went undetected

### Problem
No automated alert when master controller stops making decisions.

### Fix
Add Cloud Monitoring alert for workflow decision gaps:
```yaml
displayName: "Master Controller Decision Gap"
conditions:
  - displayName: "No decisions in 2 hours"
    conditionAbsent:
      filter: 'resource.type="cloud_run_revision" AND jsonPayload.message=~"workflow.*decision"'
      duration: "7200s"
```

Or add to daily validation:
```bash
# In morning validation cron
python bin/validation/comprehensive_health_check.py --alert
```

---

## Priority Order

1. **P0:** Fix has_prop_line bug (Issue 1) - Blocking all grading
2. **P0:** Run grading backfill (Issue 3) - After Issue 1 fix
3. **P1:** Regenerate features (Issue 2) - Improve prediction coverage
4. **P1:** Add workflow decision alert (Issue 5) - Prevent future undetected outages
5. **P2:** Investigate props coverage (Issue 4) - Optimization
