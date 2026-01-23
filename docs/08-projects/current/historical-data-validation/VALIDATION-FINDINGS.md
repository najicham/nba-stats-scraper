# Historical Data Validation Findings

**Last Updated:** 2026-01-23
**Validated By:** Automated validation tools + manual review

---

## Executive Summary

A comprehensive audit of NBA data across 4+ seasons revealed systemic patterns in data gaps, primarily caused by the **bootstrap gap** at season start. All seasons consistently show ~93% prediction coverage due to this pattern.

---

## Season-by-Season Analysis

### 2021-22 Season

**Date Range:** Oct 19, 2021 - Jun 16, 2022

| Metric | Value | Status |
|--------|-------|--------|
| Analytics Dates | 213 | Complete |
| Prediction Dates | 199 | 14 missing |
| Graded Dates | 199 | Matches predictions |
| Odds Dates | 0 | No data |
| Coverage | 93.4% | Bootstrap gap |

**Missing Dates:**
```
2021-10-19 through 2021-11-01 (14 days)
```

**Grading Accuracy:** 16.4% (avg error: 4.57 pts)

**Issues:**
- No Odds API data - all predictions use estimated lines
- Bootstrap gap at season start

---

### 2022-23 Season

**Date Range:** Oct 18, 2022 - Jun 12, 2023

| Metric | Value | Status |
|--------|-------|--------|
| Analytics Dates | 212 | Complete |
| Prediction Dates | 198 | 14 missing |
| Graded Dates | 198 | Matches predictions |
| Odds Dates | 27 | Playoffs only |
| Coverage | 93.4% | Bootstrap gap |

**Missing Dates:**
```
2022-10-18 through 2022-10-31 (14 days)
```

**Grading Accuracy:** 16.7% (avg error: 4.63 pts)

**Issues:**
- Odds API only has playoff data (May-June 2023)
- Bootstrap gap at season start

---

### 2023-24 Season

**Date Range:** Oct 24, 2023 - Jun 17, 2024

| Metric | Value | Status |
|--------|-------|--------|
| Analytics Dates | 207 | Complete |
| Prediction Dates | 193 | 14 missing |
| Graded Dates | 193 | Matches predictions |
| Odds Dates | 207 | Full coverage |
| Coverage | 93.2% | Bootstrap gap |

**Missing Dates:**
```
2023-10-24 through 2023-11-06 (14 days)
```

**Grading Accuracy:** 17.8% (avg error: 4.61 pts)

**Issues:**
- Bootstrap gap at season start
- First season with full Odds API coverage

---

### 2024-25 Season

**Date Range:** Oct 22, 2024 - Jun 22, 2025

| Metric | Value | Status |
|--------|-------|--------|
| Analytics Dates | 213 | Complete |
| Prediction Dates | 199 | 14 missing |
| Graded Dates | 199 | Matches predictions |
| Odds Dates | 213 | Full coverage |
| Coverage | 93.4% | Bootstrap gap |

**Missing Dates:**
```
2024-10-22 through 2024-11-04 (14 days)
```

**Grading Accuracy:** 21.0% (avg error: 4.65 pts)

**Issues:**
- Bootstrap gap at season start
- Full odds coverage available

---

### 2025-26 Season (Current)

**Date Range:** Oct 22, 2025 - Present

| Metric | Value | Status |
|--------|-------|--------|
| Analytics Dates | 89 | In progress |
| Prediction Dates | 87 | 2 missing |
| Graded Dates | 56 | Delayed grading |
| Odds Dates | 89 | Full coverage |
| Coverage | 97.8% | Improved |

**Grading Accuracy:** 57.5% (avg error: 4.91 pts) - **Major Improvement!**

**Notes:**
- CatBoost V8 model deployed - significant accuracy improvement
- DNP voiding implemented (255 voided predictions)
- Minimal bootstrap gap (improved system)

---

## Cross-Season Patterns

### 1. Bootstrap Gap Pattern

Every season consistently loses the first ~14 days due to insufficient historical data for rolling averages.

```
Season Start → Wait ~14 days → Predictions begin
```

**Impact:** ~7% of season dates affected

### 2. Odds API Evolution

```
2021-22: No data
2022-23: Playoffs only (27 dates)
2023-24: Full season (207 dates)
2024-25: Full season (213 dates)
2025-26: Full season (89+ dates)
```

### 3. Grading Accuracy Evolution

```
2021-24: 16-21% (legacy models)
2025-26: 57.5% (CatBoost V8)
```

**3.5x improvement** with new model deployment.

### 4. Placeholder Lines

| Season | Placeholders | % |
|--------|-------------|---|
| 2021-22 | 0 | 0% |
| 2022-23 | 0 | 0% |
| 2023-24 | 0 | 0% |
| 2024-25 | 0 | 0% |
| 2025-26 | 54 | 0.06% |

Placeholder lines only appear in current season for low-usage players.

---

## Feature Calculation Validation

### Spot Check Results (2026-01-21)

| Player | Expected Avg | Cached Avg | Drift % | Status |
|--------|-------------|------------|---------|--------|
| demarderozan | 20.40 | 23.80 | 16.7% | FAIL |
| luguentzdort | 8.20 | 10.17 | 24.0% | FAIL |
| preciousachiuwa | 7.20 | 12.40 | 72.2% | FAIL |

**Root Cause:** Cross-season contamination in rolling window calculations

**Issues Found:**
1. `games_found` returns fewer games than expected
2. Contributing dates include previous season data
3. Rolling averages pulling data across season boundaries

---

## Validation Tools Used

| Tool | Purpose | Location |
|------|---------|----------|
| `bin/spot_check_features.py` | Feature validation | bin/ |
| `bin/validate_pipeline.py` | Pipeline validation | bin/ |
| `tools/monitoring/check_prediction_coverage.py` | Coverage gaps | tools/monitoring/ |
| `scripts/validation/validate_pipeline_completeness.py` | Completeness | scripts/validation/ |

---

## SQL Queries for Validation

### Check Prediction Coverage by Season
```sql
WITH season_dates AS (
  SELECT DISTINCT game_date,
    CASE
      WHEN game_date >= '2021-10-19' AND game_date <= '2022-06-30' THEN '2021-22'
      WHEN game_date >= '2022-10-18' AND game_date <= '2023-06-30' THEN '2022-23'
      WHEN game_date >= '2023-10-24' AND game_date <= '2024-06-30' THEN '2023-24'
      WHEN game_date >= '2024-10-22' AND game_date <= '2025-06-30' THEN '2024-25'
      ELSE 'other'
    END as season
  FROM `nba_analytics.player_game_summary`
),
predictions AS (
  SELECT DISTINCT game_date
  FROM `nba_predictions.player_prop_predictions`
  WHERE is_active = TRUE
)
SELECT season,
  COUNT(DISTINCT s.game_date) as analytics_dates,
  COUNT(DISTINCT p.game_date) as prediction_dates,
  ROUND(100.0 * COUNT(DISTINCT p.game_date) / COUNT(DISTINCT s.game_date), 1) as coverage_pct
FROM season_dates s
LEFT JOIN predictions p ON s.game_date = p.game_date
WHERE season != 'other'
GROUP BY 1 ORDER BY 1;
```

### Find Missing Prediction Dates
```sql
WITH analytics AS (
  SELECT DISTINCT game_date FROM `nba_analytics.player_game_summary`
),
predictions AS (
  SELECT DISTINCT game_date FROM `nba_predictions.player_prop_predictions`
  WHERE is_active = TRUE
)
SELECT a.game_date
FROM analytics a
LEFT JOIN predictions p ON a.game_date = p.game_date
WHERE p.game_date IS NULL
ORDER BY a.game_date;
```

---

## Next Steps

1. **Immediate:** Document bootstrap gap as known limitation
2. **Short-term:** Backfill 2024-25 missing dates (if odds data available)
3. **Medium-term:** Fix feature calculation cross-season contamination
4. **Long-term:** Implement early-season prediction strategy
