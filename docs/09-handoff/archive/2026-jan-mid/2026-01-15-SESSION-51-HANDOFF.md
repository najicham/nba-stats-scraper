# Session 51 Handoff: V1.5 Model Training & Data Segmentation Analysis

**Date**: 2026-01-15
**Focus**: BettingPros feature analysis, V1.5 model training, data segmentation strategies
**Status**: V1.5 baseline trained, data segmentation experiments recommended

---

## Executive Summary

This session trained the first V1.5 model with BettingPros features and discovered important insights about data segmentation from NBA ML model research. **Key finding: More data doesn't mean better performance.**

### Session Results

| Task | Status | Finding |
|------|--------|---------|
| BettingPros feature analysis | ✅ Done | `perf_last_5` is strongest signal (18pp edge) |
| V1.5 model training | ✅ Done | 52.98% hit rate (baseline) |
| NBA ML strategy research | ✅ Done | 2.5-3 season window optimal |
| Data segmentation experiments | ⏳ Recommended | Test different training windows |

---

## BettingPros Feature Analysis

### Projection Accuracy (Market 285: Strikeouts)

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Projection MAE | 1.88 | BP projections off by ~1.88 Ks |
| Line MAE | 1.83 | Lines slightly better than projections |
| Projection Hit Rate | **52%** | Barely above random |

**Insight:** BettingPros projections are NOT significantly better than the betting line itself.

### Performance Trend Features (The Strong Signal)

| Scenario | Over Rate | Sample Size | Edge |
|----------|-----------|-------------|------|
| Trending Over (4+ of last 5) | **60.9%** | 3,296 | +10% |
| Trending Under (≤1 of last 5) | **42.5%** | 3,748 | -9% |
| Baseline | 51.4% | 14,521 | 0% |

**This is an 18.4 percentage point spread** - highly actionable!

### Combined Signal Strength

| Signal Combo | Over Rate | Count |
|--------------|-----------|-------|
| Both favor over | **62.2%** | 2,344 |
| Trend over, proj under | 57.6% | 952 |
| Mixed signals | 51.7% | 7,477 |
| Both favor under | **42.9%** | 2,017 |

**When both signals agree: 19.3pp spread**

---

## V1.5 Model Results

### Model Architecture

```python
# Features: 28 total (20 V1 + 8 BettingPros)
V1 Features: Recent K averages, season stats, workload, context
BP Features: betting_line, projection, projection_diff,
             perf_last_5_over_pct, perf_last_10_over_pct,
             perf_season_over_pct, combined_signal, implied_prob
```

### Performance Metrics

| Metric | Training | Validation | Test |
|--------|----------|------------|------|
| MAE | 1.395 | 1.679 | **1.731** |
| Within 2K | 74.2% | 66.2% | 64.1% |

### Hit Rate (Betting Performance)

| Metric | Value |
|--------|-------|
| Hit Rate | **52.98%** |
| Baseline | 50.0% |
| Edge | +2.98% |

**Note:** This is below V1's reported 67.27% hit rate. Possible reasons:
1. Different test periods
2. Different grading methodology
3. V1 uses different line thresholds

### Feature Importance

| Rank | Feature | Type | Importance |
|------|---------|------|------------|
| 1 | f40_betting_line | BP | **30.0%** |
| 2 | f41_bp_projection | BP | 4.6% |
| 3 | f45_perf_season_over_pct | BP | 3.1% |
| 4 | f46_combined_signal | BP | 3.1% |
| 5 | f47_over_implied_prob | BP | 3.1% |

**BettingPros features total: 51.6% of importance**

The betting line itself is the dominant feature - the market is already efficient!

---

## NBA ML Model Research: Data Segmentation Insights

### Key Finding: More Data ≠ Better Performance

From `/docs/08-projects/current/ml-model-v8-deployment/`:

| Model | Data Window | Hit Rate | Result |
|-------|-------------|----------|--------|
| V8 (champion) | 2.5 seasons | **72.5%** | Winner |
| V10 (challenger) | 4+ seasons | 72.2% | Lost |

**V8 wins 52.3% vs V10's 47.7% in head-to-head**

### Why More Data Hurt Performance

1. **Market efficiency improved** - 2026 Vegas lines are 10% more accurate
2. **Distribution shift** - Game patterns changed (rest days -28.5%)
3. **Feature quality degraded** - Recent data has more missing values
4. **Ceiling effect** - Already near optimal, more data causes overfitting

### Optimal Training Strategy

```
Recommended: 2.5-3 season rolling window

Why:
- Enough samples for statistical stability (50,000+)
- Recent enough for current dynamics
- Avoids outdated patterns from efficient markets
```

### Seasonal Performance Patterns

| Season Phase | Performance | Notes |
|--------------|-------------|-------|
| Early season | Best (88%+) | Stable rosters |
| Mid-season | Moderate (50-60%) | Injuries, rest |
| Late season | Worse (45-47%) | Playoff positioning |
| Playoffs | Better (55-57%) | Predictable games |

---

## Recommended Data Segmentation Experiments

### Experiment 1: Training Window Comparison

```python
# Test different training windows
experiments = [
    {"name": "recent_only", "years": [2025], "description": "Most recent season only"},
    {"name": "two_seasons", "years": [2024, 2025], "description": "2.5 season sweet spot"},
    {"name": "all_data", "years": [2022, 2023, 2024, 2025], "description": "Full BettingPros history"},
]
```

### Experiment 2: Season Phase Analysis

```sql
-- Compare performance by season phase
SELECT
  CASE
    WHEN EXTRACT(MONTH FROM game_date) IN (4, 5) THEN 'early_season'
    WHEN EXTRACT(MONTH FROM game_date) IN (6, 7) THEN 'mid_season'
    WHEN EXTRACT(MONTH FROM game_date) IN (8, 9) THEN 'late_season'
  END as season_phase,
  COUNT(*) as games,
  AVG(CASE WHEN actual_over THEN 1.0 ELSE 0.0 END) as over_rate
FROM training_data
GROUP BY 1
```

### Experiment 3: Market Efficiency Over Time

```sql
-- Track line accuracy by year
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  AVG(ABS(over_line - actual_value)) as line_mae,
  COUNT(*) as samples
FROM `mlb_raw.bp_pitcher_props`
WHERE market_id = 285
GROUP BY 1
ORDER BY 1
```

---

## Background Tasks Status

### GCS Backfill (Task: b77281f)

| Market | Status | Files |
|--------|--------|-------|
| pitcher-strikeouts | ✅ DONE | 740/740 |
| pitcher-earned-runs | ✅ DONE | 740/740 |
| All 9 batter markets | 52% | ~385/740 each |

**ETA:** ~4-5 more hours for complete batter backfill

### Monitor Command

```bash
# Check progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py

# Monitor live output
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output
```

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `scripts/mlb/training/train_pitcher_strikeouts_v1_5.py` | V1.5 training script |
| `models/mlb/mlb_pitcher_strikeouts_v1_5_bp_20260115_074103.json` | V1.5 model |
| `models/mlb/mlb_pitcher_strikeouts_v1_5_bp_20260115_074103_metadata.json` | Model metadata |

---

## Next Session Priorities

### 1. Data Segmentation Experiments (High Priority)

Create script to test different training windows:

```bash
# Recommended next step
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v1_5.py \
    --training-window "2024-2025"  # Test 2-season window
```

### 2. Load Batter Props (When Backfill Completes)

```bash
# After batter backfill reaches 100%
python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter
```

### 3. Hit Rate Validation

The 52.98% hit rate needs investigation:
- Compare grading methodology with V1
- Verify test set overlap with V1 evaluation
- Check for line threshold filtering

### 4. Market Efficiency Analysis

```sql
-- Compare line accuracy 2022 vs 2025
SELECT year, line_mae, count FROM line_accuracy_by_year
```

---

## Key Insights for Future Work

### The Betting Line Problem

The model's #1 feature is `f40_betting_line` at 30% importance. This means:
1. The market is already efficient
2. Our model is largely learning to predict the line, not beat it
3. Edge comes from the OTHER 70% of features

### Strategy Implications

1. **Focus on edge cases** - Where perf_last_5 and projection diverge from line
2. **Confidence filtering** - Only bet when model has high conviction
3. **Seasonal timing** - Early season may be more profitable

### Data Quality Watchlist

- Monitor for fake/default lines (V8 NBA had 26% corrupted data)
- Check feature coverage percentages
- Watch for distribution shift year-to-year

---

## Quick Reference Commands

```bash
# Check backfill progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py

# Query BigQuery pitcher props
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM mlb_raw.bp_pitcher_props WHERE market_id = 285'

# Train V1.5 model
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_v1_5.py

# View model metadata
cat models/mlb/mlb_pitcher_strikeouts_v1_5_bp_20260115_074103_metadata.json | jq
```

---

## Handoff Checklist

- [x] BettingPros feature analysis complete
- [x] V1.5 model trained (baseline)
- [x] NBA data segmentation strategies researched
- [x] Handoff documentation written
- [ ] Data segmentation experiments (next session)
- [ ] Batter props loading (after backfill)
- [ ] Hit rate validation against V1

---

## Key Takeaway

**The biggest opportunity isn't more features - it's better data selection.** The NBA ML model research shows that V8 with 2.5 seasons outperformed V10 with 4+ seasons. For MLB, we should test whether training on 2024-2025 only beats training on all 4 years of BettingPros data.

The `perf_last_5` feature is the strongest BettingPros signal (18pp edge), but the betting line itself dominates the model (30% importance), suggesting the market is already quite efficient at pricing pitcher strikeouts.
