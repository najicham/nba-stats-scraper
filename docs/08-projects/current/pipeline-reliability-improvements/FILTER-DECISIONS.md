# Filter Decisions Log

**Purpose:** Document all prediction filtering decisions with full context for future review and potential reversal.

---

## Filter #1: Confidence Tier 88-90

| Field | Value |
|-------|-------|
| **Filter ID** | `confidence_tier_88_90` |
| **Decision Date** | 2026-01-09 |
| **Implemented Date** | 2026-01-10 |
| **Status** | ACTIVE |
| **Review Frequency** | Weekly shadow monitoring, Monthly formal review |

---

### Decision Summary

**Action:** Filter out predictions with confidence scores in the 88-90% range (0.88 ≤ confidence < 0.90).

**Rationale:** This tier consistently underperforms all other confidence tiers across 5 seasons of data, and performance is degrading over time. In the current season (2025-26), it's below breakeven.

---

### Supporting Analysis

#### Validation Query (Run 2026-01-09)

```sql
-- Full historical analysis with correct filters per EVALUATION-METHODOLOGY.md
WITH prediction_outcomes AS (
  SELECT
    p.game_date,
    p.player_lookup,
    p.confidence_score,
    p.recommendation,
    p.current_points_line as line_value,
    p.has_prop_line,
    a.points as actual_points,
    CASE
      WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN true
      WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN true
      WHEN p.recommendation = 'OVER' AND a.points < p.current_points_line THEN false
      WHEN p.recommendation = 'UNDER' AND a.points > p.current_points_line THEN false
      ELSE NULL  -- Push
    END as is_correct
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  JOIN `nba-props-platform.nba_analytics.player_game_summary` a
    ON p.player_lookup = a.player_lookup
    AND p.game_date = a.game_date
  WHERE p.system_id = 'catboost_v8'
    AND p.has_prop_line = true
    AND p.recommendation IN ('OVER', 'UNDER')
    AND a.points IS NOT NULL
)
SELECT
  CASE
    WHEN confidence_score >= 90 OR (confidence_score >= 0.90 AND confidence_score <= 1) THEN '1. 90+ (Very High)'
    WHEN (confidence_score >= 88 AND confidence_score < 90) OR (confidence_score >= 0.88 AND confidence_score < 0.90) THEN '2. 88-90 (Problem Tier)'
    WHEN (confidence_score >= 86 AND confidence_score < 88) OR (confidence_score >= 0.86 AND confidence_score < 0.88) THEN '3. 86-88 (Medium-High)'
    WHEN (confidence_score >= 84 AND confidence_score < 86) OR (confidence_score >= 0.84 AND confidence_score < 0.86) THEN '4. 84-86 (Medium)'
    ELSE '5. Other'
  END as confidence_tier,
  COUNT(*) as picks,
  COUNTIF(is_correct = true) as wins,
  COUNTIF(is_correct = false) as losses,
  ROUND(COUNTIF(is_correct = true) /
        NULLIF(COUNTIF(is_correct IS NOT NULL), 0) * 100, 1) as hit_rate,
  ROUND((COUNTIF(is_correct = true) * 91.0 -
         COUNTIF(is_correct = false) * 100.0) /
        NULLIF(COUNT(*) * 110.0, 0) * 100, 1) as roi_pct
FROM prediction_outcomes
GROUP BY 1
ORDER BY 1;
```

#### Results: All-Time Performance by Tier

| Confidence Tier | Picks | Wins | Losses | Hit Rate | ROI |
|-----------------|-------|------|--------|----------|-----|
| 90+ (Very High) | 35,538 | 26,883 | 8,572 | **75.8%** | +40.7% |
| **88-90 (Problem)** | **2,763** | **1,702** | **1,054** | **61.8%** | **+16.3%** |
| 86-88 (Medium-High) | 9,015 | 6,707 | 2,298 | **74.5%** | +38.4% |
| 84-86 (Medium) | 354 | 283 | 71 | **79.9%** | +47.9% |

#### Results: Performance by Season (88-90 Tier Only)

| Season | Picks | Wins | Losses | Hit Rate | Trend |
|--------|-------|------|--------|----------|-------|
| 2021-22 | 744 | 474 | 270 | 63.7% | - |
| 2022-23 | 506 | 340 | 166 | 67.2% | ↑ Best |
| 2023-24 | 524 | 314 | 209 | 60.0% | ↓ |
| 2024-25 | 892 | 529 | 357 | 59.7% | ↓ |
| 2025-26 | 97 | 45 | 52 | **46.4%** | ↓↓ Below breakeven |

#### Results: Comparison Across Tiers by Season

| Season | 90+ | 88-90 | 86-88 | Gap (90+ vs 88-90) |
|--------|-----|-------|-------|-------------------|
| 2021-22 | 77.4% | 63.7% | 77.1% | -13.7 pts |
| 2022-23 | 76.0% | 67.2% | 77.5% | -8.8 pts |
| 2023-24 | 73.9% | 60.0% | 72.5% | -13.9 pts |
| 2024-25 | 76.1% | 59.7% | 72.1% | -16.4 pts |
| 2025-26 | 75.7% | 46.4% | 69.6% | -29.3 pts |

---

### Key Findings

1. **Structural Problem:** The 88-90 tier has ALWAYS been 10-15 percentage points below other tiers
2. **Degrading Performance:** Hit rate declining from 67% (best) to 46% (current)
3. **Now Unprofitable:** 46.4% is below the 52.4% breakeven for -110 juice
4. **Other Tiers Stable:** 90+ tier remains rock-solid at 75-77% across all seasons
5. **Not Noise:** 2,763 picks across 5 seasons is statistically significant

---

### Implementation Details

#### What Gets Filtered

```python
# Confidence in range [0.88, 0.90) - handles both decimal and percentage formats
if 0.88 <= confidence_decimal < 0.90:
    is_actionable = False
    filter_reason = 'confidence_tier_88_90'
```

#### What Is Preserved

| Field | Preserved? | Notes |
|-------|------------|-------|
| recommendation | YES | Original OVER/UNDER kept (not changed to PASS) |
| confidence_score | YES | Unchanged |
| predicted_points | YES | Unchanged |
| All features | YES | Unchanged |

#### Shadow Tracking

Filtered picks are still:
- Stored in the predictions table
- Graded by the grading processor
- Tracked in the shadow performance view

---

### Rollback Instructions

#### Level 1: Quick Re-enable (SQL Only)

```sql
-- Re-enable all 88-90 tier predictions
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET is_actionable = true, filter_reason = NULL
WHERE filter_reason = 'confidence_tier_88_90';

-- Also update prediction_accuracy table
UPDATE `nba-props-platform.nba_predictions.prediction_accuracy`
SET is_actionable = true, filter_reason = NULL
WHERE filter_reason = 'confidence_tier_88_90';
```

#### Level 2: Code Disable

In `predictions/worker/worker.py`, comment out or modify the filtering logic:

```python
# DISABLED: Re-enabling 88-90 tier as of YYYY-MM-DD
# if 0.88 <= confidence_decimal < 0.90:
#     is_actionable = False
#     filter_reason = 'confidence_tier_88_90'
is_actionable = True
filter_reason = None
```

---

### Re-enabling Criteria

Monitor shadow performance weekly. Consider re-enabling if ALL of these are met:

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Hit rate | > 70% | Must be profitable at -110 juice |
| Duration | 3 consecutive months | Not just a hot streak |
| Sample size | 200+ picks per month | Statistically meaningful |
| Consistency | Both OVER and UNDER profitable | Not directional bias |

#### Shadow Performance Query

```sql
-- Check if 88-90 tier should be re-enabled
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = true) as wins,
  COUNTIF(prediction_correct = false) as losses,
  ROUND(COUNTIF(prediction_correct = true) /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0) * 100, 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE filter_reason = 'confidence_tier_88_90'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY 1
ORDER BY 1 DESC;
```

---

### Review Schedule

| Review Type | Frequency | Query/Action |
|-------------|-----------|--------------|
| Shadow performance check | Weekly | Run shadow view query |
| Formal review | Monthly | Full analysis, update this doc |
| Re-enable consideration | Quarterly | Check against re-enabling criteria |

---

### Document History

| Date | Change | Author |
|------|--------|--------|
| 2026-01-09 | Initial analysis and decision | Claude + Naji |
| 2026-01-10 | Implementation and documentation | Claude + Naji |

---

## Future Filters (Placeholder)

This section documents potential future filters under consideration:

| Filter ID | Description | Status |
|-----------|-------------|--------|
| `low_edge_under_2pts` | Filter picks with < 2 point edge | Under consideration |
| `injury_uncertainty` | Filter when key player questionable | Not started |
| `back_to_back_away` | Filter fatigue situations | Not started |

---
