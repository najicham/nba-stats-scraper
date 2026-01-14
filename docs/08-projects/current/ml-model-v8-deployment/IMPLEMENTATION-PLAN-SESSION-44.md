# Implementation Plan: Session 44 - Tiered Best Bets & Pipeline Fixes

**Created:** 2026-01-14
**Status:** Ready for Implementation
**Priority:** HIGH - Directly impacts prediction quality

---

## Executive Summary

Analysis of 10,000+ predictions reveals massive performance variations that the current best bets system ignores. Implementing data-driven filtering can improve hit rate from ~74% to **90%+** for premium picks.

### The Core Problem

The current `best_bets_exporter.py`:
1. Uses naive top-N ranking by composite score
2. **No UNDER vs OVER filtering** (UNDER 95% vs OVER 53%)
3. **No edge threshold** (5+ edge = 92.9%, <2 edge = 24.1%)
4. **No player tier filtering** (bench 89% vs stars 43%)
5. **No exclusion of 88-90% confidence tier** (42% hit rate - broken)

### The Solution

Implement tiered selection with data-driven criteria:

| Tier | Criteria | Expected Hit Rate |
|------|----------|-------------------|
| **Premium** | UNDER, 90%+ conf, 5+ edge, <18 pts | 92-95% |
| **Strong** | UNDER, 90%+ conf, 4+ edge, <20 pts | 80-85% |
| **Value** | UNDER, 80%+ conf, 5+ edge, <22 pts | 70-75% |

---

## Critical Findings (Why This Matters)

### 1. UNDER Dramatically Outperforms OVER

| Recommendation | Confidence | Picks | Hit Rate |
|----------------|------------|-------|----------|
| **UNDER** | 90%+ | 7,709 | **95.4%** |
| OVER | 90%+ | 1,794 | 53.2% |

**Impact:** +42 percentage points by focusing on UNDER only

### 2. Edge Threshold is Critical

| Edge | Confidence 90%+ | Hit Rate |
|------|-----------------|----------|
| 5+ pts | 7,623 picks | **92.9%** |
| <2 pts | 1,387 picks | **24.1%** |

**Impact:** +68 percentage points by requiring 5+ edge

### 3. Player Tier Matters Enormously

| Player Tier | Predicted Points | Hit Rate | MAE |
|-------------|------------------|----------|-----|
| Bench | <12 | **89.0%** | 3.13 |
| Star | 25+ | 43.6% | 16.55 |

**Impact:** +45 percentage points by excluding stars

### 4. The 88-90% Confidence Anomaly

This tier hits only **42%** even with 4+ edge. Already filtered in some places but must be explicitly excluded from best bets.

---

## Implementation Tasks

### Phase 1: Best Bets Exporter (HIGH PRIORITY)

**File:** `data_processors/publishing/best_bets_exporter.py`

#### 1.1 Add Tier Configuration

```python
TIER_CONFIG = {
    'premium': {
        'recommendation': 'UNDER',
        'min_confidence': 0.90,
        'min_edge': 5.0,
        'max_predicted_points': 18,
        'max_picks': 5,
        'exclude_confidence_range': (0.88, 0.90),
    },
    'strong': {
        'recommendation': 'UNDER',
        'min_confidence': 0.90,
        'min_edge': 4.0,
        'max_predicted_points': 20,
        'max_picks': 10,
        'exclude_confidence_range': (0.88, 0.90),
    },
    'value': {
        'recommendation': 'UNDER',
        'min_confidence': 0.80,
        'min_edge': 5.0,
        'max_predicted_points': 22,
        'max_picks': 10,
        'exclude_confidence_range': (0.88, 0.90),
    },
}

AVOID_CRITERIA = {
    'recommendation': 'OVER',           # 53% hit rate
    'min_edge': 2.0,                    # Below this = 17-24% hit rate
    'max_predicted_points': 25,         # Above this = star players, 43% hit rate
    'exclude_confidence_range': (0.88, 0.90),  # Broken tier, 42% hit rate
}
```

#### 1.2 Modify SQL Query

Add tier calculation and filtering:

```sql
-- Add to the WHERE clause
WHERE p.game_date = @target_date
  AND p.system_id = 'catboost_v8'
  AND p.recommendation = 'UNDER'  -- CRITICAL: UNDER only
  AND p.predicted_points < 25      -- Exclude star players
  AND ABS(p.predicted_points - p.line_value) >= 2.0  -- Minimum edge
  AND NOT (p.confidence_score >= 0.88 AND p.confidence_score < 0.90)  -- Exclude broken tier

-- Add tier classification
CASE
  WHEN confidence_score >= 0.90
       AND ABS(predicted_points - line_value) >= 5.0
       AND predicted_points < 18 THEN 'premium'
  WHEN confidence_score >= 0.90
       AND ABS(predicted_points - line_value) >= 4.0
       AND predicted_points < 20 THEN 'strong'
  WHEN confidence_score >= 0.80
       AND ABS(predicted_points - line_value) >= 5.0
       AND predicted_points < 22 THEN 'value'
  ELSE 'standard'
END as tier
```

#### 1.3 Modify Output Format

Add tier field to each pick:

```json
{
  "picks": [
    {
      "rank": 1,
      "tier": "premium",
      "player_lookup": "...",
      "recommendation": "UNDER",
      ...
    }
  ],
  "tier_summary": {
    "premium": 3,
    "strong": 5,
    "value": 7
  }
}
```

#### 1.4 Update Selection Logic

Option A: Fill by tier (recommended)
- Take up to 5 premium picks
- Fill remaining with strong picks (up to 10)
- Fill remaining with value picks (up to 10)
- Total max: 15-25 picks

Option B: Single tier filter
- User selects tier, only get picks from that tier

### Phase 2: Enrichment Processor Cloud Function (HIGH PRIORITY)

**Problem:** Processor exists but runs manually. Props are scraped at 18:00 UTC but processor not scheduled.

**Solution:** Create Cloud Function wrapper.

**Files to create:**
```
orchestration/cloud_functions/enrichment_trigger/
├── __init__.py
├── main.py
└── requirements.txt
```

**Schedule:** 18:40 UTC daily (via Cloud Scheduler or Pub/Sub trigger)

**Pattern to follow:** `orchestration/cloud_functions/phase3_to_phase4/`

### Phase 3: Phase 3 Timing Fix (HIGH PRIORITY)

**Problem:** Phase 3 runs at 17:45 UTC, but props aren't scraped until 18:00 UTC.

**Fix:**
```bash
gcloud scheduler jobs update http same-day-phase3-tomorrow \
  --location=us-west2 \
  --schedule="0 19 * * *"
```

This ensures Phase 3 runs at 19:00 UTC, after props are available.

### Phase 4: System Investigation (MEDIUM PRIORITY)

#### 4.1 Investigate 88-90% Confidence Anomaly

This tier underperforms at ALL edge levels. Need to understand why.

**Query to run:**
```sql
SELECT
  system_id,
  recommendation,
  ROUND(AVG(ABS(predicted_points - line_value)), 2) as avg_edge,
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE confidence_score >= 0.88 AND confidence_score < 0.90
  AND game_date >= '2025-10-01'
  AND line_value IS NOT NULL
GROUP BY 1, 2
ORDER BY picks DESC;
```

#### 4.2 Investigate xgboost_v1 vs catboost_v8

Analysis shows xgboost_v1 (87.5%) significantly outperforms catboost_v8 (74.8%). But:

**IMPORTANT DISCOVERY:** xgboost_v1 is NOT currently running in the worker!

The worker runs: moving_average, zone_matchup_v1, similarity_balanced_v1, catboost_v8, ensemble_v1

**Options:**
1. Re-enable xgboost_v1 in worker (requires investigation)
2. Use xgboost_v1 for premium tier only
3. Stay with catboost_v8 but with better filtering (current plan)

### Phase 5: Monitoring (LOW PRIORITY)

#### 5.1 Cloud Monitoring Alert

Create alert for auth errors using existing log-based metric.

---

## Key Decisions Needed

### 1. UNDER-Only vs Weighted?

**Recommendation:** UNDER-only for premium/strong tiers. The data is unambiguous - OVER hits 53% vs UNDER 95%.

### 2. Expose Tier Labels on Website?

**Options:**
- A) Show tier labels (Premium/Strong/Value)
- B) Show all picks sorted by tier (tier is internal)
- C) Separate endpoints per tier

**Recommendation:** Option A - transparency helps users understand pick quality.

### 3. System Filter?

**Current:** catboost_v8 only
**Alternative:** Re-enable xgboost_v1 for premium picks

**Recommendation:** Stay with catboost_v8 for now, implement better filtering. Investigate xgboost_v1 as separate task.

### 4. Volume vs Quality?

| Strategy | Picks/Day | Expected Hit Rate |
|----------|-----------|-------------------|
| Premium only | ~2-3 | 90%+ |
| Premium + Strong | ~8-10 | 82-85% |
| All Tiers | ~15-20 | 75-80% |

**Recommendation:** Provide all tiers, let users choose.

---

## Files to Modify

| File | Change |
|------|--------|
| `data_processors/publishing/best_bets_exporter.py` | Add tier logic, filtering |
| `tests/unit/publishing/test_best_bets_exporter.py` | Update tests |
| `backfill_jobs/publishing/daily_export.py` | Potentially update top_n handling |

## Files to Create

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/enrichment_trigger/main.py` | Cloud Function wrapper |
| `orchestration/cloud_functions/enrichment_trigger/requirements.txt` | Dependencies |

---

## Success Criteria

1. **Premium tier hit rate:** 90%+ over 7-day rolling window
2. **Strong tier hit rate:** 80%+ over 7-day rolling window
3. **Value tier hit rate:** 70%+ over 7-day rolling window
4. **No OVER picks** in premium/strong tiers
5. **No star players** (25+ predicted) in any tier
6. **No 88-90% confidence** picks in any tier

---

## Verification Queries

### Post-Implementation Validation

```sql
-- Check tier distribution
SELECT
  tier,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0) * 100, 1) as hit_rate
FROM (
  SELECT
    CASE
      WHEN confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 5.0 AND predicted_points < 18 THEN 'premium'
      WHEN confidence_score >= 0.90 AND ABS(predicted_points - line_value) >= 4.0 AND predicted_points < 20 THEN 'strong'
      WHEN confidence_score >= 0.80 AND ABS(predicted_points - line_value) >= 5.0 AND predicted_points < 22 THEN 'value'
      ELSE 'standard'
    END as tier,
    prediction_correct,
    predicted_points,
    line_value,
    confidence_score
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND system_id = 'catboost_v8'
    AND recommendation = 'UNDER'
    AND predicted_points < 25
    AND ABS(predicted_points - line_value) >= 2.0
    AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)
    AND line_value IS NOT NULL
)
GROUP BY tier
ORDER BY
  CASE tier
    WHEN 'premium' THEN 1
    WHEN 'strong' THEN 2
    WHEN 'value' THEN 3
    ELSE 4
  END;
```

---

## Investigation Results (Session 44)

### 88-90% Confidence Anomaly - EXPLAINED

The 42% hit rate in the 88-90% confidence tier is **NOT uniform across all systems**:

| System | Recommendation | Picks | Hit Rate | Avg Edge |
|--------|----------------|-------|----------|----------|
| ensemble_v1 | UNDER | 155 | **93.5%** | 15.78 |
| similarity_balanced_v1 | UNDER | 477 | **84.7%** | 9.5 |
| catboost_v8 | UNDER | 295 | 71.5% | 9.56 |
| similarity_balanced_v1 | OVER | 95 | 56.8% | 3.88 |
| catboost_v8 | OVER | 98 | **44.9%** | 7.11 |

**Root Cause:** The poor performance is driven by:
1. OVER recommendations (44.9-56.8% in this tier)
2. catboost_v8 specifically in this confidence range

**Our Solution:** By filtering to UNDER-only, we avoid the worst performers in this tier. However, we still exclude the 88-90% tier entirely as a safety measure since the catboost_v8 UNDER performance (71.5%) is below our target thresholds.

### xgboost_v1 vs catboost_v8 Gap - EXPLAINED

| System | Rec | Conf Tier | Picks | Hit Rate | Avg Edge |
|--------|-----|-----------|-------|----------|----------|
| xgboost_v1 | UNDER | 90%+ | 1,068 | **99.6%** | 15.27 |
| catboost_v8 | UNDER | 90%+ | 3,675 | 95.0% | 12.19 |
| xgboost_v1 | UNDER | 80-90% | 4,373 | 94.4% | 13.2 |
| catboost_v8 | UNDER | 80-90% | 2,012 | 90.0% | 14.43 |

**Key Finding:** xgboost_v1 is MORE SELECTIVE:
- Gives 90%+ confidence less often (1,068 vs 3,675 picks)
- But when it does, it's nearly perfect (99.6% hit rate)
- Has higher average edge (15.27 vs 12.19 points)

**Why xgboost_v1 isn't in production:**
- xgboost_v1 is NOT currently running in the worker!
- The historical data is from before it was disabled
- catboost_v8 was deployed as the primary system

**Recommendation for Future:**
1. Re-enable xgboost_v1 in the worker
2. Use xgboost_v1 for premium tier picks (99.6% accuracy!)
3. Keep catboost_v8 for volume (more picks, still good accuracy)

---

## Completed Implementation (Session 44)

### Code Changes
- `data_processors/publishing/best_bets_exporter.py` - Tiered selection logic
- `tests/unit/publishing/test_best_bets_exporter.py` - 25 passing tests

### New Files
- `orchestration/cloud_functions/enrichment_trigger/` - Cloud Function for betting line enrichment
- `bin/orchestrators/deploy_enrichment_trigger.sh` - Deployment script

### Documentation
- This file (IMPLEMENTATION-PLAN-SESSION-44.md)

---

## Production Fix Applied (Session 44 - Continued)

**Issue Discovered:** CatBoost V8 model was NOT loading in production (Jan 12-14, 2026)

**Root Cause:** `CATBOOST_V8_MODEL_PATH` environment variable was missing from `nba-phase3-analytics-processors` Cloud Run service.

**Evidence:**
- Cloud logs showed: `FALLBACK_PREDICTION: CatBoost V8 model not loaded`
- All predictions had confidence = 0.5 (fallback value)
- All recommendations were PASS (fallback behavior)

**Fix Applied:**
```bash
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"

gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 \
  --to-latest
```

**Result:** New revision deployed (00056) with model path configured. Next prediction run will use real model.

---

## Related Documentation

- [ANALYSIS-FRAMEWORK.md](./ANALYSIS-FRAMEWORK.md) - Complete dimensional analysis
- [BEST-BETS-SELECTION-STRATEGY.md](../pipeline-reliability-improvements/BEST-BETS-SELECTION-STRATEGY.md) - Strategy overview
- [SESSION-43-HANDOFF.md](../../09-handoff/2026-01-14-SESSION-43-ANALYSIS-FRAMEWORK-HANDOFF.md) - Previous session context

---

*Last Updated: 2026-01-14 (Session 44)*
