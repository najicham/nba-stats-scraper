# Session 42: V2 Feature Data Audit

**Date:** 2026-01-14
**Focus:** Audit data availability for V2 model training
**Status:** Data gaps identified, 2 features populated, training script in progress

---

## Executive Summary

Audited BigQuery tables to determine V2 feature availability. Found that **all 10 new V2 features are at 0% population** despite columns existing in the schema. The source data for several key features (pitcher splits, game totals) does not exist.

---

## V2 Feature Availability Audit

### pitcher_game_summary Table Status

| Feature | Schema Exists | Data Populated | Source Available |
|---------|--------------|----------------|------------------|
| **Core V1 Features** | | | |
| k_avg_last_3/5/10 | ✅ | ✅ 94.8% | bdl_pitcher_stats |
| season_k_per_9, era, whip | ✅ | ✅ ~90% | bdl_pitcher_stats |
| days_rest, games_last_30 | ✅ | ✅ ~85% | Calculated |
| strikeouts (actual) | ✅ | ✅ 100% | bdl_pitcher_stats |
| **V2 NEW Features** | | | |
| home_away_k_diff | ✅ | ❌ 0% | ❌ bdl_pitcher_splits empty |
| is_day_game | ✅ | ❌ 0% | ❓ Needs investigation |
| day_night_k_diff | ✅ | ❌ 0% | ❌ bdl_pitcher_splits empty |
| vs_opponent_k_per_9 | ✅ | ❌ 0% | ❌ bdl_pitcher_splits empty |
| opponent_team_k_rate | ✅ | ❌ 0% | ✅ bdl_batter_stats has data |
| opponent_obp | ✅ | ❌ 0% | ✅ bdl_batter_stats has data |
| ballpark_k_factor | ✅ | ❌ 0% | ❌ Reference table empty |
| game_total_line | ✅ | ❌ 0% | ❌ oddsa_game_lines empty |
| platoon_advantage | ❌ No column | ❌ N/A | ❌ No source |
| matchup_edge | ❌ No column | ❌ N/A | ❌ No source |

### Raw Data Source Status

```
mlb_raw.bdl_pitcher_splits:          0 rows (partitioned by snapshot_date, empty)
mlb_raw.bdl_pitcher_home_away_splits: VIEW -> depends on bdl_pitcher_splits
mlb_raw.bdl_pitcher_day_night_splits: VIEW -> depends on bdl_pitcher_splits
mlb_raw.oddsa_game_lines:            0 rows
mlb_raw.bdl_batter_stats:            97,679 rows (2024+) ✅
mlb_reference.ballpark_factors:       0 rows (schema exists)
```

### Predictions Table Status (for training labels)

```
mlb_predictions.pitcher_strikeouts:
  Total rows:           8,130
  Has strikeouts_line:  7,226 (89%)
  Has actual_strikeouts: 8,130 (100%)
  Has is_correct:       7,196 (88.5%)
```

---

## Data Gap Analysis

### Features We CAN Populate (from existing data)

1. **opponent_team_k_rate** - Calculate from `bdl_batter_stats`
   - 97,679 batter game rows available
   - Aggregate by team + season to get team K rate

2. **opponent_obp** - Calculate from `bdl_batter_stats`
   - Same source as opponent_team_k_rate

3. **ballpark_k_factor** - Populate reference table
   - Need to create/populate `mlb_reference.ballpark_factors`
   - Can use external data source (FanGraphs park factors)

4. **is_day_game** - May be derivable from game start time
   - Check `mlb_raw.mlb_schedule` or `bdl_games`

### Features We CANNOT Populate (source data missing)

1. **home_away_k_diff** - Requires `bdl_pitcher_splits` (empty)
2. **day_night_k_diff** - Requires `bdl_pitcher_splits` (empty)
3. **vs_opponent_k_per_9** - Requires `bdl_pitcher_splits` (empty)
4. **game_total_line** - Requires `oddsa_game_lines` (empty)
5. **platoon_advantage** - No schema, no source
6. **matchup_edge** - No schema, no source

---

## Recommended Strategy

### Option A: V2-Lite (Train with Available Features)

**Approach:** Train V2 with ~22 features instead of 29
- All V1 features (19) ✅
- + opponent_team_k_rate (calculate from batter stats)
- + opponent_obp (calculate from batter stats)
- + ballpark_k_factor (populate reference table)

**Pros:**
- Can start training immediately
- Minimal infrastructure work
- May still improve over V1

**Cons:**
- Missing 7 planned V2 features
- Home/away and day/night splits unavailable

### Option B: Full V2 (Populate Missing Data First)

**Approach:** Scrape/populate missing raw data before training
- Scrape pitcher splits data from Ball Don't Lie API
- Scrape game totals from The Odds API
- Then populate all 29 features

**Pros:**
- Full V2 feature set
- Better potential for improvement

**Cons:**
- Significant infrastructure work
- Historical splits data may not be available via API
- Delays training by days/weeks

### Recommendation

**Start with Option A (V2-Lite)** to validate the approach:
1. Populate opponent_team_k_rate + opponent_obp (1-2 hours)
2. Populate ballpark_k_factor (1 hour)
3. Train V2 with ~22 features
4. Compare to V1 baseline (67.27%)

If V2-Lite shows promise, then pursue Option B for full feature set.

---

## Execution Progress

1. [x] Create team K rate reference table from bdl_batter_stats
   - Created `mlb_reference.team_k_rates` with 63 records (32 teams × 2 seasons)
   - Average K rate: 0.2499, Range: 0.21 - 0.32

2. [x] Populate opponent_team_k_rate in pitcher_game_summary
   - **9,793 / 9,793 rows populated (100%)**
   - Range: 0.2928 - 0.3157

3. [x] Create/populate ballpark_k_factor reference table
   - Created `mlb_reference.ballpark_k_factors` with 39 venues
   - K factors calculated from actual strikeout data
   - Range: 0.41 (Bristol special event) - 1.19 (T-Mobile Park)

4. [x] Populate ballpark_k_factor in pitcher_game_summary
   - **9,793 / 9,793 rows populated (100%)**
   - Range: 0.4142 - 1.1868

5. [x] Check if is_day_game can be derived from schedule
   - **NOT AVAILABLE** - game_time columns are NULL in both mlb_schedule and bdl_games

6. [x] Create V2 training script (21 features - V2-Lite)
7. [x] Train and evaluate V2-Lite model
8. [ ] Document results and decide on full V2 approach

## V2-Lite Training Results

**Date:** 2026-01-14 13:24
**Model ID:** pitcher_strikeouts_v2_20260114_132434

### Performance Comparison

| Metric | V1 Baseline | V2-Lite | Change |
|--------|-------------|---------|--------|
| **MAE** | 1.46 | 1.75 | -19.7% (worse) |
| **Hit Rate** | 67.27% | 54.90% | -12.37pp (worse) |
| Test Picks | - | 847 | - |

### Training Details

- **Algorithm:** CatBoost (vs V1's XGBoost)
- **Features:** 21 (V1's 19 + opponent_team_k_rate + ballpark_k_factor)
- **Training samples:** 5,836 pitcher starts
- **Test set:** 2025-08-08 to 2025-09-28 (the "decline period")
- **Early stopping:** Iteration 168/1000 (overfitting detected)

### Edge Bucket Analysis (V2)

| Edge | Picks | Win Rate |
|------|-------|----------|
| 0.5-1.0 | 265 | 54.3% |
| 1.0-1.5 | 204 | 53.4% |
| 1.5-2.0 | 167 | 59.3% |
| 2.0+ | 211 | 53.6% |

**Critical Finding:** Unlike V1, V2 shows no edge correlation - higher edge doesn't mean higher win rate.

### Top Feature Importance

1. **f02_k_avg_last_10** - 13.9% (rolling average)
2. **f17_ballpark_k_factor** - 10.3% (V2 NEW FEATURE!)
3. **f25_bottom_up_k_expected** - 9.0%
4. **f05_season_k_per_9** - 7.2%
5. **f01_k_avg_last_5** - 6.6%

V2 new feature **ballpark_k_factor** ranked #2 in importance (10.3%), but **opponent_team_k_rate** only 1.2%.

### V1 vs V2 Same-Period Comparison

| Period | V1 Hit Rate | V2 Hit Rate | V1 Better By |
|--------|-------------|-------------|--------------|
| Train (Apr24-May25) | 70.97% | N/A | - |
| Val (Jun-Jul 2025) | 62.19% | N/A | - |
| **Test (Aug-Sep 2025)** | **59.52%** | **54.90%** | **+4.62pp** |

**Key Finding:** V1 also struggles in Aug-Sep 2025 (59.52%), but V2 is even worse (54.90%).

### V1 Monthly Performance (2025)

| Month | Picks | V1 Hit Rate | Trend |
|-------|-------|-------------|-------|
| Mar | 110 | 75.45% | Peak |
| Apr | 662 | 70.09% | Strong |
| May | 715 | 69.65% | Strong |
| Jun | 668 | 65.27% | Declining |
| **Jul** | 628 | **58.92%** | **Worst** |
| **Aug** | 715 | **56.64%** | **Worst** |
| Sep | 614 | 62.87% | Recovery |

**Pattern:** Clear seasonal decline from March (75%) to August (57%), then partial recovery in September.

### Root Cause Analysis

1. **Test Period Issue:** The test set (Aug-Sep 2025) is a genuinely difficult period. V1 drops from 70.97% to 59.52% here. But V2 should still match V1's 59.52%, not underperform by 4.6pp.

2. **No Edge Correlation:** V2's win rate is flat across edge buckets (~54%), suggesting the model's confidence doesn't translate to accuracy.

3. **CatBoost vs XGBoost:** The algorithm change may need different hyperparameter tuning. Early stopping at 168 iterations suggests potential underfitting.

4. **Missing Features:** V2-Lite only adds 2 of the planned 10 new features. The missing splits data (home/away, day/night) may be critical.

### Recommendations

1. **Try XGBoost with new features** - Keep V1 algorithm, just add the 2 new features
2. **Tune CatBoost hyperparameters** - Increase iterations, adjust learning rate
3. **Test on different time periods** - Validate that Aug-Sep 2025 is genuinely difficult
4. **Populate missing features** - Scrape pitcher splits data from Ball Don't Lie API

## Updated Feature Status

| Feature | Status | Population |
|---------|--------|------------|
| opponent_team_k_rate | ✅ POPULATED | 100% |
| ballpark_k_factor | ✅ POPULATED | 100% |
| is_day_game | ❌ NO DATA | 0% |
| home_away_k_diff | ❌ NO SOURCE | 0% |
| day_night_k_diff | ❌ NO SOURCE | 0% |
| vs_opponent_k_per_9 | ❌ NO SOURCE | 0% |
| game_total_line | ❌ NO SOURCE | 0% |

**V2-Lite Feature Count: 21 features** (19 V1 + opponent_team_k_rate + ballpark_k_factor)

---

## Key Files

- `predictions/mlb/pitcher_strikeouts_predictor_v2.py` - V2 inference code (ready)
- `data_processors/analytics/mlb/pitcher_game_summary_processor.py` - Feature processor
- `scripts/mlb/historical_odds_backfill/` - Backfill infrastructure

---

## Appendix: BigQuery Queries Used

### Check Feature Population
```sql
SELECT
    COUNT(*) as total_rows,
    COUNTIF(home_away_k_diff IS NOT NULL AND home_away_k_diff != 0) as home_away_k_diff_pop,
    COUNTIF(opponent_team_k_rate IS NOT NULL AND opponent_team_k_rate != 0) as opponent_team_k_rate_pop,
    -- ... etc
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-01-01'
```

### Check Source Data
```sql
SELECT COUNT(*) FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`
WHERE snapshot_date >= '2024-01-01'  -- Returns 0

SELECT COUNT(*) FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= '2024-01-01'  -- Returns 97,679
```

---

## Session 42 Summary

### Completed Tasks

1. **Data Audit:** Identified that 8/10 V2 features have 0% population due to missing source data
2. **Feature Population:** Successfully populated 2 features:
   - `opponent_team_k_rate` - 100% (9,793 rows)
   - `ballpark_k_factor` - 100% (9,793 rows)
3. **Training Script:** Created `scripts/mlb/training/train_pitcher_strikeouts_v2.py`
4. **Model Training:** Trained V2-Lite CatBoost model with 21 features
5. **Evaluation:** V2-Lite underperformed V1 (54.90% vs 59.52% on same test period)

### Key Learnings

1. **Data Gaps Block Full V2:** Pitcher splits, game totals, and day/night data don't exist in BigQuery
2. **Aug-Sep 2025 is Challenging:** Both V1 and V2 struggle in this period (market shift?)
3. **Algorithm Choice Matters:** CatBoost with these features performs worse than XGBoost
4. **ballpark_k_factor is Valuable:** Ranked #2 in feature importance (10.3%)

### Recommendations for Next Session

1. **Keep V1 as Champion** - It outperforms V2-Lite on the same test data
2. **Try XGBoost + New Features** - Add the 2 populated features to V1's algorithm
3. **Scrape Pitcher Splits** - Ball Don't Lie API may have home/away, day/night splits
4. **Investigate Aug-Sep Decline** - Why does both models struggle late in the season?

### Files Created/Modified

- `mlb_reference.team_k_rates` - New BigQuery table
- `mlb_reference.ballpark_k_factors` - New BigQuery table
- `mlb_analytics.pitcher_game_summary` - opponent_team_k_rate, ballpark_k_factor populated
- `scripts/mlb/training/train_pitcher_strikeouts_v2.py` - New training script
- `models/mlb/pitcher_strikeouts_v2_20260114_132434.cbm` - V2-Lite model (not production-ready)
- `docs/08-projects/current/mlb-performance-analysis/` - New performance tracking directory
  - `PERFORMANCE-ANALYSIS-GUIDE.md` - Monitoring commands and patterns
  - `FEATURE-IMPROVEMENT-ROADMAP.md` - Future feature priorities

### Status

**V1 remains champion.** V2-Lite demonstrated that:
- The 2 new features alone don't improve performance
- CatBoost may need more tuning or different hyperparameters
- The remaining 8 V2 features may be critical for improvement
