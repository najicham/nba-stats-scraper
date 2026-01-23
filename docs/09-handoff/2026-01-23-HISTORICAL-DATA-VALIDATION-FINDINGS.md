# Historical Data Validation Findings

**Date:** 2026-01-23
**Purpose:** Document validation findings, root causes, and improvement recommendations
**Status:** Active Investigation

---

## Executive Summary

A comprehensive validation of historical data across the 2024-25 NBA season revealed several data gaps and quality issues that need attention. The most critical finding is **14 days of missing predictions** at the start of the season (Oct 22 - Nov 4, 2024).

### Key Findings

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| Missing Oct 2024 predictions | CRITICAL | 14 dates with zero predictions | Needs Backfill |
| Feature calculation drift | HIGH | Rolling averages 16-72% off | Under Investigation |
| Low grading accuracy (2024) | MEDIUM | 20-22% vs 40-66% in 2025-26 | Model Issue |
| Placeholder lines remaining | LOW | 50 across season (0.02%) | Acceptable |

---

## Detailed Findings

### 1. Missing Predictions: October 22 - November 4, 2024

**Problem:** The first 14 dates of the 2024-25 NBA season have NO predictions despite having analytics data.

**Affected Dates:**
```
2024-10-22 through 2024-10-31 (10 dates)
2024-11-01 through 2024-11-04 (4 dates)
```

**Data State:**
- Analytics Layer (L3): Has data for all 14 dates
- Predictions Layer (L5): ZERO predictions
- Grading Layer: Cannot grade what doesn't exist

**Root Cause Analysis:**
1. **Season Start Bootstrap Issue**: The prediction system likely wasn't operational at season start
2. **Insufficient Historical Data**: Early season has limited game history for rolling averages
3. **Missing Odds Data**: Odds API may not have been collecting data yet

**Impact:**
- ~14,000 missing predictions (estimate: 14 dates × 10 games × 100 players)
- ML training data missing early season patterns
- Grading accuracy incomplete for season analysis

**Recommended Fix:**
```bash
# Backfill predictions for Oct-Nov 2024
# 1. Verify odds data exists for these dates
# 2. Run prediction coordinator in backfill mode
# 3. Grade the backfilled predictions
```

---

### 2. Feature Calculation Drift

**Problem:** The `bin/spot_check_features.py` tool found significant discrepancies between Phase 3 (raw calculation) and Phase 4 (cached features).

**Sample Failures (2026-01-21):**
| Player | Expected Avg | Cached Avg | Drift % |
|--------|-------------|------------|---------|
| demarderozan | 20.40 | 23.80 | 16.67% |
| luguentzdort | 8.20 | 10.17 | 23.98% |
| preciousachiuwa | 7.20 | 12.40 | **72.22%** |

**Additional Issues Found:**
- `games_found` accuracy: Expected 10 games, found only 5-6
- Contributing dates mismatch: Old season dates (2025-04, 2025-05) appearing in lookbacks
- Cross-season contamination in rolling window calculations

**Root Cause Analysis:**
1. **Season Boundary Handling**: Rolling averages are pulling data from previous season
2. **Precompute Cache Staleness**: Phase 4 cache may not be refreshed properly
3. **Date Filtering Bug**: `games_expected` calculation appears incorrect

**Impact:**
- Prediction accuracy degraded due to incorrect feature inputs
- ML model training on dirty features
- Bootstrap detection may be unreliable

**Recommended Fixes:**
1. Add season boundary filtering to rolling average calculations
2. Implement precompute cache invalidation on new season start
3. Add validation check to Phase 4 processor

---

### 3. Grading Accuracy Discrepancy

**Problem:** Grading accuracy shows a dramatic shift between early 2024-25 season (20-22%) and late 2025-early 2026 (40-66%).

**Accuracy by Period:**
| Period | Accuracy % | Notes |
|--------|-----------|-------|
| Nov 2024 | 22.6% | Season start |
| Dec 2024 | 19.7% | Still low |
| Jan-Apr 2025 | 20-21% | Consistent but low |
| Nov 2025 | 65.9% | New season improvement |
| Dec 2025 | 56.5% | Sustained improvement |
| Jan 2026 | 41.9% | Recent performance |

**Root Cause Analysis:**
1. **Model Improvement**: CatBoost V8 deployment in late 2025 significantly improved accuracy
2. **Feature Quality**: Earlier predictions using incorrect rolling averages
3. **Bootstrap Impact**: Early season bootstrap mode may have affected predictions

**Impact:**
- Historical model performance metrics are unreliable
- Backtesting results may be inflated for recent period

**Recommended Actions:**
1. Document model version transitions and expected accuracy ranges
2. Consider re-running predictions for 2024-early 2025 with current model
3. Add model version to prediction_accuracy table for segmented analysis

---

### 4. Betting Lines Data Quality

**Problem:** Minor placeholder line issues remain.

**Status by Month:**
| Month | Placeholders | Total | % |
|-------|-------------|-------|---|
| Jan 2026 | 4 | 41,077 | 0.01% |
| Nov 2025 | 15 | 40,874 | 0.04% |
| Dec 2025 | 35 | 66,956 | 0.05% |

**Root Cause:** Low-usage players not in betting markets (expected behavior)

**Status:** ACCEPTABLE - No action needed

---

## Validation Tools Inventory

### Available Tools

| Tool | Purpose | Usage |
|------|---------|-------|
| `bin/spot_check_features.py` | Validate ML feature calculations | `python bin/spot_check_features.py --date YYYY-MM-DD --count N` |
| `bin/validate_pipeline.py` | Comprehensive pipeline validation | `python bin/validate_pipeline.py YYYY-MM-DD --verbose` |
| `scripts/validation/validate_pipeline_completeness.py` | Multi-layer completeness check | `python scripts/validation/validate_pipeline_completeness.py` |
| `tools/monitoring/check_prediction_coverage.py` | Prediction gap detection | `python tools/monitoring/check_prediction_coverage.py --date YYYY-MM-DD` |

### Key SQL Queries

**Check prediction coverage by month:**
```sql
SELECT
  EXTRACT(MONTH FROM game_date) as month,
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as prediction_dates
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE
GROUP BY 1, 2 ORDER BY 2, 1;
```

**Find dates with games but no predictions:**
```sql
WITH game_dates AS (
  SELECT DISTINCT game_date FROM `nba_analytics.player_game_summary`
),
prediction_dates AS (
  SELECT DISTINCT game_date FROM `nba_predictions.player_prop_predictions`
  WHERE is_active = TRUE
)
SELECT g.game_date
FROM game_dates g
LEFT JOIN prediction_dates p ON g.game_date = p.game_date
WHERE p.game_date IS NULL
ORDER BY g.game_date;
```

---

## Recommended Improvements

### Short-term (This Week)

1. **Backfill Oct-Nov 2024 Predictions**
   - Verify historical odds data exists
   - Run prediction coordinator for each missing date
   - Grade backfilled predictions

2. **Investigate Feature Drift**
   - Run spot_check_features.py on sample of 2024 dates
   - Compare Phase 3 vs Phase 4 calculations
   - Identify root cause of cross-season contamination

### Medium-term (Next 2 Weeks)

3. **Add Automated Validation**
   - Create daily validation job that runs after orchestration
   - Alert on prediction coverage gaps (< 95% of expected players)
   - Alert on feature drift (> 10% discrepancy)

4. **Enhance Spot Check Tool**
   - Add season boundary validation
   - Add precompute cache freshness check
   - Export results to BigQuery for trending

### Long-term (Next Month)

5. **Self-Healing System**
   - Automatically detect and backfill missing predictions
   - Implement cascade validation (if L3 changes, validate L4/L5)
   - Add data lineage tracking

6. **Historical Accuracy Dashboard**
   - Create Looker/Grafana dashboard for accuracy by:
     - Model version
     - Season period
     - Player archetype
     - Betting line source

---

## Action Items

- [ ] Backfill predictions for Oct 22 - Nov 4, 2024
- [ ] Investigate feature calculation drift in spot_check_features.py
- [ ] Add season boundary filtering to rolling average calculation
- [ ] Document model version history and accuracy expectations
- [ ] Create automated daily validation job
- [ ] Add coverage gap detection to monitoring

---

## Related Documentation

- [Scrapers Reference - Historical Odds API](../06-reference/scrapers.md#historical-odds-api-backfill-workflow)
- [Backfill Guide - Historical Betting Lines](../02-operations/backfill/backfill-guide.md)
- [Prediction Coordinator Troubleshooting](../06-reference/processor-cards/phase5-prediction-coordinator.md)

---

**Next Session:** Focus on backfilling Oct-Nov 2024 predictions and investigating feature drift root cause.
