# Session 44 Handoff - Deep Investigation & Feature Quality Problem

**Date:** 2026-01-30
**Duration:** ~2 hours
**Focus:** Critical bug fix, deep model drift investigation, feature quality systemic problem identified

---

## Executive Summary

Session 44 conducted a comprehensive 6-agent parallel investigation into model performance degradation. We found and fixed a **critical fatigue score bug**, but more importantly, we identified a **systemic problem**: we keep discovering feature quality issues reactively, after they've already damaged model performance.

**Key Insight:** We need proactive feature health monitoring, not reactive debugging.

---

## Critical Fix Applied

### Fatigue Score Bug (FIXED)

**Commit:** `cec08a99`

**Problem:** Jan 25 refactor (ef1b38a4) changed factor calculation to return adjustment (-5 to 0) instead of raw score (0-100), but processor still stored it as raw score.

**Evidence:**
| Date | Avg Fatigue Score | Status |
|------|-------------------|--------|
| Jan 18 | 95.29 | ✅ Correct |
| Jan 25 | -0.07 (1,221 zeros) | ❌ Broken |

**Fix:** Changed processor to use `factor_contexts['fatigue_context_json']['final_score']` instead of `factor_scores['fatigue_score']`.

**Deployment Needed:**
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

**Backfill Needed:** player_composite_factors and ml_feature_store_v2 for dates >= 2026-01-25

---

## Deep Investigation Findings

We ran 6 parallel investigations to understand model degradation:

### 1. Vegas Lines Analysis
- **Finding:** Vegas MAE is FLAT at 5.15-5.17 for last 3 months
- **Conclusion:** Vegas did NOT get sharper - we got worse

### 2. Model Raw Accuracy
- **Finding:** Our MAE increased from 4.1 to 5.7 (38% degradation)
- **Finding:** We went from beating Vegas by 0.9 pts to losing by 0.5 pts
- **Finding:** Star player accuracy degraded 71%, bench only 10%

### 3. NBA Scoring Patterns
- **Finding:** January 2026 (113 ppg) is historically normal
- **Finding:** December 2025 (116.7 ppg) was anomalously high
- **Conclusion:** NBA didn't change - our model may have overfit to December

### 4. Model Calibration
- **Finding:** Calibration slope = 0.75 (should be 1.0)
- **Finding:** Over-predicts 30+ pt scorers by 6.86 points
- **Finding:** Vegas line alone (MAE 5.03) beats our model (MAE 5.43)
- **Conclusion:** Model needs recalibration or post-hoc shrinkage

### 5. Specific Player Errors
- **Finding:** Breakout players are worst cases
- Examples: Brice Sensabaugh (+11.1), Julius Randle (+9.4), Keyonte George (+8.9)
- **Conclusion:** Model anchors too heavily on historical averages

### 6. Feature Data Quality
- **Finding:** CRITICAL BUG - fatigue_score storing 0 since Jan 25
- **Finding:** Upstream data quality issues growing (59 → 1,325 incomplete)
- **Finding:** Production ready dropped from 49% to 23%

---

## The Systemic Problem: Reactive Feature Debugging

### Pattern We Keep Seeing

1. Model performance drops
2. We investigate for hours/days
3. Find a feature with bad data
4. Fix the bug, backfill data
5. Repeat next time

### Past Examples (Just This Month)

| Date | Issue | How Discovered | Impact |
|------|-------|----------------|--------|
| Jan 25 | Fatigue score = 0 | Model drift investigation | 5+ days of bad data |
| Jan ~20 | Usage rate calculation | Spot check failures | Unknown |
| Jan ~15 | Rolling average cache | Validation failures | Data quality issues |

### Why This Keeps Happening

1. **No feature-level monitoring** - We monitor predictions, not inputs
2. **No baseline tracking** - We don't know what "normal" looks like for each feature
3. **Silent failures** - Features can break without errors
4. **Delayed detection** - We only notice when predictions suffer

---

## Proposed Solution: Feature Health Monitoring System

### Concept: Track Each Feature's "Vital Signs"

For every feature in `ml_feature_store_v2`, track:

1. **Statistical Distribution** - mean, stddev, min, max, percentiles
2. **Expected Range** - hard limits (e.g., fatigue_score: 0-100)
3. **Change Detection** - alert when distribution shifts significantly
4. **Null/Zero Rate** - track missing or suspicious values
5. **Correlation Stability** - features should maintain relationships

### Implementation Options

#### Option A: Add Monitoring Columns to Feature Store

Add columns to `ml_feature_store_v2`:

```sql
-- Per-feature quality flags
fatigue_score_valid BOOLEAN,  -- Is value in expected range?
fatigue_score_zscore FLOAT,   -- How many stddevs from rolling mean?

-- Aggregate quality
feature_anomaly_count INT,    -- How many features are anomalous?
feature_quality_tier STRING,  -- 'gold', 'silver', 'bronze', 'suspect'
```

**Pros:** Data lives with features, easy to query
**Cons:** Schema changes, more storage

#### Option B: Separate Feature Health Table

Create `nba_monitoring.feature_health_daily`:

```sql
CREATE TABLE feature_health_daily (
  report_date DATE,
  feature_name STRING,

  -- Distribution stats
  mean FLOAT,
  stddev FLOAT,
  min_value FLOAT,
  max_value FLOAT,
  p5 FLOAT,
  p50 FLOAT,
  p95 FLOAT,

  -- Quality metrics
  null_count INT,
  zero_count INT,
  out_of_range_count INT,
  total_count INT,

  -- Anomaly detection
  mean_vs_baseline FLOAT,  -- % change from 30-day baseline
  stddev_vs_baseline FLOAT,
  distribution_shift_score FLOAT,  -- KL divergence or similar

  -- Status
  health_status STRING,  -- 'healthy', 'warning', 'critical'
  alert_reasons ARRAY<STRING>
);
```

**Pros:** Clean separation, easy to build dashboards
**Cons:** Another table to maintain, join needed

#### Option C: Real-Time Validation in Processor

Add validation in `PlayerCompositeFactorsProcessor`:

```python
def _validate_feature_ranges(self, record: dict) -> List[str]:
    """Validate all features are in expected ranges."""
    violations = []

    EXPECTED_RANGES = {
        'fatigue_score': (0, 100),
        'shot_zone_mismatch_score': (-20, 20),
        'pace_score': (-10, 10),
        # ... all features
    }

    for feature, (min_val, max_val) in EXPECTED_RANGES.items():
        value = record.get(feature)
        if value is not None and (value < min_val or value > max_val):
            violations.append(f"{feature}={value} outside [{min_val}, {max_val}]")

    return violations
```

**Pros:** Catches issues immediately, fails fast
**Cons:** Only catches range violations, not distribution shifts

### Recommended Approach: Hybrid (A + B + C)

1. **Option C (Real-time validation)** - Catch obvious bugs immediately
2. **Option B (Daily health table)** - Track trends and detect drift
3. **Option A (Quality flags)** - Mark suspect records for filtering

### Daily Health Check Query

Run daily to detect issues:

```sql
WITH feature_stats AS (
  SELECT
    game_date,
    -- Fatigue score
    AVG(fatigue_score) as fatigue_mean,
    STDDEV(fatigue_score) as fatigue_std,
    COUNTIF(fatigue_score = 0) as fatigue_zeros,
    COUNTIF(fatigue_score < 0 OR fatigue_score > 100) as fatigue_invalid,

    -- Add similar for all features...
    COUNT(*) as total_records
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  game_date,
  fatigue_mean,
  fatigue_zeros,
  fatigue_invalid,
  CASE
    WHEN fatigue_zeros > total_records * 0.1 THEN 'CRITICAL: >10% zeros'
    WHEN fatigue_invalid > 0 THEN 'WARNING: Invalid values'
    WHEN ABS(fatigue_mean - 95) > 10 THEN 'WARNING: Mean shifted'
    ELSE 'OK'
  END as fatigue_status
FROM feature_stats
ORDER BY game_date DESC;
```

### Alert Thresholds

| Feature | Expected Mean | Warning | Critical |
|---------|---------------|---------|----------|
| fatigue_score | 90-100 | <80 or >100 | <50 or zeros |
| shot_zone_mismatch | -5 to +5 | ±10 | ±20 |
| pace_score | -2 to +2 | ±5 | ±10 |
| usage_spike_score | -2 to +2 | ±5 | ±10 |

---

## Files Created This Session

| File | Description |
|------|-------------|
| `docs/08-projects/current/2026-01-30-session-44-maintenance/README.md` | Session overview |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/INVESTIGATION-FINDINGS.md` | Initial investigation |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/MODEL-DRIFT-STATUS-UPDATE.md` | Model drift status |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/DEEP-INVESTIGATION-FINDINGS.md` | Full 6-agent investigation results |
| `docs/09-handoff/2026-01-30-SESSION-44-DEEP-INVESTIGATION-HANDOFF.md` | This handoff |

---

## Code Changes Made

| File | Change | Commit |
|------|--------|--------|
| `scrapers/nbacom/injury_parser.py` | Fix syntax error in stub functions | `e715694d` |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | Fix fatigue_score to use raw 0-100 value | `cec08a99` |

---

## Deployments Made

| Service | Revision | Commit | Fix |
|---------|----------|--------|-----|
| nba-scrapers | 00111-zn8 | e715694d | injury_parser syntax |
| nba-phase1-scrapers | 00025-wvt | e715694d | injury_parser syntax |

**Still Needs Deployment:**
- nba-phase4-precompute-processors (fatigue score fix)

---

## Next Session Checklist

### Priority 1: Deploy & Backfill (Immediate)

- [ ] Deploy Phase 4 processor with fatigue fix:
  ```bash
  ./bin/deploy-service.sh nba-phase4-precompute-processors
  ```

- [ ] Backfill player_composite_factors for Jan 25-30:
  ```bash
  # Trigger reprocessing for affected dates
  PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/precompute/player_composite_factors/backfill.py --start-date 2026-01-25 --end-date 2026-01-30
  ```

- [ ] Verify fix worked:
  ```sql
  SELECT game_date, ROUND(AVG(fatigue_score), 2) as avg_fatigue
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= '2026-01-25'
  GROUP BY 1 ORDER BY 1;
  -- Expected: ~90-100, not 0 or negative
  ```

### Priority 2: Feature Health Monitoring (This Week)

- [ ] Create `nba_monitoring.feature_health_daily` table
- [ ] Add scheduled query to populate daily
- [ ] Add feature range validation to processor
- [ ] Create Slack alert for feature anomalies

### Priority 3: Model Calibration (Medium Term)

- [ ] Add post-hoc calibration (shrinkage toward mean)
- [ ] Or blend predictions with Vegas line (70% model, 30% line)
- [ ] Fix confidence scores (currently meaningless 0.8-1.0)

### Priority 4: Breakout Detection (Medium Term)

- [ ] Add rolling trend features (pts_slope_10g)
- [ ] Flag players exceeding seasonal average significantly
- [ ] Weight recent games more for rising players

---

## Key Queries for Monitoring

### Feature Health Check
```sql
SELECT
  game_date,
  ROUND(AVG(fatigue_score), 2) as fatigue_mean,
  COUNTIF(fatigue_score = 0) as fatigue_zeros,
  COUNTIF(fatigue_score < 0 OR fatigue_score > 100) as fatigue_invalid
FROM nba_precompute.player_composite_factors
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1 DESC;
```

### Model Performance
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

### Upstream Data Quality
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as records,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  ROUND(AVG(feature_quality_score), 2) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Investigation Summary: Why Model Degraded

| Factor | Contribution | Evidence |
|--------|--------------|----------|
| **Fatigue Bug (Jan 25+)** | HIGH | All fatigue = 0 |
| Calibration Drift | MEDIUM | Slope 0.75, over-predict high scorers 6.9 pts |
| Breakout Detection | MEDIUM | Rising players under-predicted 8-11 pts |
| December Anomaly | LOW | Model may have overfit to high Dec scoring |
| Vegas Sharpening | NONE | Vegas MAE flat at 5.15 |

---

## Lessons Learned

1. **Feature quality can silently degrade** - No errors, just wrong values
2. **Refactoring can introduce subtle bugs** - The Jan 25 refactor changed return values
3. **We need proactive monitoring** - Not just predictions, but inputs
4. **Test feature outputs, not just code** - Unit tests didn't catch this
5. **Track distributions, not just means** - Zero count would have caught this immediately

---

## System Status at Session End

| Component | Status |
|-----------|--------|
| Pipeline | ✅ Healthy (Phase 3: 5/5) |
| Scrapers | ✅ Fixed & deployed |
| Phase 4 Processor | ⚠️ Fix committed, needs deployment |
| Model Performance | 🔴 Degraded (50% hit rate, negative Vegas edge) |
| Feature Quality | ⚠️ Fatigue broken since Jan 25, fix pending |

---

*Session 44 complete. Critical fatigue bug fixed. Feature health monitoring system proposed.*
*Next session: Deploy fix, backfill, implement feature monitoring.*
