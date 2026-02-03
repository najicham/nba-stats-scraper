# Session 94 Handoff - Prediction Quality & Timing System

**Date:** 2026-02-03
**Model:** Claude Opus 4.5
**Duration:** ~2 hours

---

## Executive Summary

Session 94 investigated why Feb 2's top 3 high-edge picks all MISSED. Root cause: **missing BDB shot zone data** caused low feature quality (82.73% vs 87.59%), leading to artificially conservative predictions that created false "high edge" picks.

Additionally discovered that predictions were created at **4:38 PM ET** instead of the expected **5:11 AM ET**, causing the 1 PM export to have 0 picks.

---

## Critical Findings

### 1. Missing Features = Bad Predictions

| Player | Quality | Predicted | Line | Actual | Edge | Result |
|--------|---------|-----------|------|--------|------|--------|
| Trey Murphy III | 82.73% | 11.1 | 22.5 | 27 | 11.4 | MISS |
| Jaren Jackson Jr | 82.73% | 13.8 | 22.5 | 30 | 8.7 | MISS |
| Jabari Smith Jr | 82.73% | 9.4 | 17.5 | 19 | 8.1 | MISS |
| Zion Williamson | **87.59%** | 21.0 | 23.5 | 14 | 2.5 | HIT |

**The 3 misses had MISSING shot zone data (pct_paint, pct_mid_range, pct_three = 0)**

### 2. Historical Performance by Quality Score

```
Quality >= 85%: 56.8% hit rate (1,208 predictions)
Quality 80-85%: 51.9% hit rate (270 predictions)
Quality < 80%:  48.1% hit rate (108 predictions)
```

### 3. RED Signal Validated

Feb 2 had pct_over = 2.2% (extremely heavy UNDER skew) with RED signal.
High-edge picks went **0/3 = 0% hit rate** - worse than the historical 54% warning.

### 4. Prediction Timing Failure

```
Expected:  5:11 AM ET (based on Jan 27-31 pattern)
Actual:    4:38 PM ET (Feb 2)
Export:    1:00 PM ET
Result:    0 picks exported (predictions didn't exist yet)
```

---

## Fixes Applied This Session

### 1. Feature Quality Filter (Committed, needs deploy)
**File:** `data_processors/publishing/all_subsets_picks_exporter.py`
```python
MIN_FEATURE_QUALITY_SCORE = 85.0
# Players with quality < 85% excluded from "top picks" exports
```

### 2. NULL Error Fix (Deployed)
**File:** `predictions/worker/execution_logger.py`
- Fixed float(None) error when list contains None values

### 3. New Scheduler Jobs (Created)

| Job | Time (ET) | Purpose |
|-----|-----------|---------|
| predictions-retry | 5:00 AM | Retry if early run failed |
| phase6-tonight-picks-morning | 11:00 AM | First export |
| phase6-tonight-picks-pregame | 5:00 PM | Pre-game export |

---

## Questions for Next Session to Decide

### Q1: What Time Should Predictions Run?

**Current Schedule:**
```
2:30 AM  predictions-early     (REAL_LINES_ONLY - fails if no lines)
5:00 AM  predictions-retry     (NEW - REAL_LINES_ONLY)
7:00 AM  overnight-predictions (allows estimated lines)
10:00 AM morning-predictions   (full run)
11:30 AM same-day-predictions  (another full run)
```

**Issue:** predictions-early at 2:30 AM requires real betting lines. If lines aren't available, ALL 136 players get filtered out and 0 predictions are created.

**Options to evaluate:**
1. Keep 2:30 AM but allow estimated lines as fallback
2. Move first prediction run to later (when lines more likely available)
3. Keep strict mode but add automatic retry with escalating fallbacks

### Q2: How Should Missing Data Be Handled?

**Current Behavior:**
- Missing betting lines -> Player filtered out (in REAL_LINES_ONLY mode)
- Missing BDB data -> Low quality score but prediction still made
- Missing opponent stats -> Features = 0, prediction still made

**Proposed Behavior (needs validation):**

| Missing Data | Attempt 1-2 | Attempt 3 (Final) |
|--------------|-------------|-------------------|
| Betting lines | PAUSE, alert, trigger scraper | Proceed with estimated line |
| BDB shot zones | PAUSE, alert, trigger scraper | Proceed but flag low-quality |
| Opponent stats | PAUSE, check Phase 3 | Proceed but flag |
| B2B prev game BDB | PAUSE (critical for fatigue) | Proceed but exclude from top picks |

### Q3: Should Missing Data Trigger Something?

**Options:**
1. **Alert only** - Send Slack alert, human decides
2. **Auto-trigger scraper** - Automatically run the missing data scraper
3. **Auto-trigger + retry** - Trigger scraper, schedule retry in 30 min

**Consideration:** Auto-triggering could cause cascade issues if scraper is broken.

### Q4: When to Proceed with Missing Features?

**User's requirement:** "Only force their prediction with low quality features if it is the last try"

**Proposed logic:**
```python
def should_proceed_with_prediction(player, attempt_number, max_attempts=3):
    quality = player.feature_quality_score
    is_b2b = player.b2b_flag

    # Always proceed for high quality
    if quality >= 85:
        return True

    # B2B players need previous game BDB data (critical for fatigue)
    if is_b2b and not player.has_previous_game_bdb:
        if attempt_number < max_attempts:
            return False  # PAUSE - wait for data
        else:
            # Final attempt: proceed but mark as low quality
            player.low_quality_flag = True
            player.exclude_from_top_picks = True
            return True

    # Non-B2B with medium quality (80-85%)
    if quality >= 80:
        return True  # Proceed, but not as top pick

    # Low quality (<80%)
    if attempt_number < max_attempts:
        return False  # PAUSE
    else:
        player.low_quality_flag = True
        return True
```

---

## Data Storage Questions

### Q5: Are Predictions Stored with Features Used?

**Current State:**
- player_prop_predictions table has prediction data
- ml_feature_store_v2 table has features
- They can be JOINed by player_lookup + game_date

**Gap:** No direct link storing WHICH features were used for WHICH prediction.

**Proposed:** Add to player_prop_predictions:
```sql
feature_store_snapshot_id STRING,  -- Link to specific feature row
feature_quality_score FLOAT64,     -- Copy of quality at prediction time
feature_version STRING,            -- Version of feature store used
b2b_missing_bdb BOOLEAN,           -- Flag for B2B without BDB
low_quality_reason STRING          -- Why quality is low
```

### Q6: Is There a Prediction History?

**Current State:**
- player_prop_predictions has is_active flag (only latest is TRUE)
- prediction_accuracy has graded predictions
- prediction_worker_runs has execution logs

**Gap:** No easy way to see ALL predictions made for a player/game (including superseded ones).

**Proposed:** Either:
1. Keep all predictions (don't deactivate old ones) with version numbers
2. Create prediction_history table that archives deactivated predictions
3. Add prediction_sequence_number to track order

---

## Files to Review

| File | Purpose | Changes Made |
|------|---------|--------------|
| data_processors/publishing/all_subsets_picks_exporter.py | Export logic | Added 85% quality filter |
| predictions/coordinator/coordinator.py | Prediction orchestration | Research only - no changes |
| predictions/coordinator/player_loader.py | Player filtering | Research only - no changes |
| predictions/worker/execution_logger.py | Execution logging | Fixed NULL in list |

---

## Verification Commands

```bash
# Check prediction timing
bq query --use_legacy_sql=false "
SELECT game_date,
  FORMAT_TIMESTAMP('%H:%M', MIN(created_at), 'America/New_York') as first_et,
  FORMAT_TIMESTAMP('%H:%M', MAX(created_at), 'America/New_York') as last_et,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
  AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1 ORDER BY 1 DESC"

# Check feature quality distribution
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN feature_quality_score >= 85 THEN 'High (85%+)'
       WHEN feature_quality_score >= 80 THEN 'Medium (80-85%)'
       ELSE 'Low (<80%)' END as tier,
  COUNT(*) as players,
  ROUND(AVG(feature_quality_score), 1) as avg_score
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1"

# Check scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep -E "predict|phase6-tonight"
```

---

## Recommended Actions for Next Session

### Priority 1: Decide on Timing Strategy
1. Review the current prediction schedule
2. Decide: Should early predictions allow estimated lines?
3. Decide: What's the right first-attempt time?

### Priority 2: Implement Missing Data Handling
1. Add quality gate to player_loader.py for B2B players
2. Add alerting when predictions are blocked
3. Decide on auto-trigger vs alert-only

### Priority 3: Ensure Data Lineage
1. Add feature_quality_score column to predictions table
2. Add low_quality_reason column
3. Consider prediction history/versioning

### Priority 4: Deploy Changes
1. Deploy all_subsets_picks_exporter.py with quality filter
2. Deploy any coordinator changes made

---

## Documentation Created

- docs/08-projects/current/prediction-quality-system/README.md
- docs/08-projects/current/prediction-quality-system/SMART-RETRY-DESIGN.md

---

## Commits Made

```
817b00fd docs: Add prediction quality system project documentation
40246fc8 fix: Add feature quality filter to subset picks export
e6bd999b fix: Filter None values inside line_values_requested list
```

---

## Key Insight

The model is working correctly - it's being conservative when data is missing. The problem is that we're treating these conservative predictions as "high confidence" picks because they have high edge. **High edge from missing data != high confidence bet.**

The solution is to:
1. Not make predictions when critical data is missing (pause)
2. Or make predictions but flag them as low-quality and exclude from "top picks"
3. Store the quality information with the prediction for transparency

---

**Session 94 Complete**
