# Session 41 Handoff: V2 Champion-Challenger Planning

**Date:** 2026-01-14
**Session:** 41
**Status:** V2 Planning Complete, Ready to Implement

---

## Executive Summary

This session continued from Session 40 (hit rate validation) to plan and begin V2 model development using the Champion-Challenger framework.

| Deliverable | Status |
|-------------|--------|
| V2 Strategy Confirmed | ✅ Option B (Champion-Challenger) |
| Feature Analysis | ✅ Complete |
| PROJECT-ROADMAP.md | ✅ Updated |
| V2 Predictor Skeleton | ✅ Created |
| Training Data Analysis | ✅ Complete |

---

## Key Decisions Made

### 1. Champion-Challenger Framework (Option B)

**Decision:** Run V2 alongside V1, compare performance before promoting.

**Rationale:**
- Safe comparison with existing baseline
- Easy rollback if V2 underperforms
- Mirrors successful NBA approach
- Data-driven promotion decision

### 2. V2 Feature Set (29 features)

**Expansion:** 19 → 29 features (+10)

| Category | V1 Features | V2 Features | New |
|----------|-------------|-------------|-----|
| Rolling Performance | 5 | 5 | 0 |
| Season Stats | 5 | 5 | 0 |
| Game Context | 2 | 5 | +3 |
| Matchup Context | 0 | 5 | +5 |
| Workload | 4 | 4 | 0 |
| Bottom-Up Model | 3 | 5 | +2 |
| **Total** | **19** | **29** | **+10** |

### 3. Algorithm Choice: CatBoost

**Decision:** Use CatBoost for V2 (vs XGBoost for V1)

**Rationale:**
- Proven success in NBA models
- Better categorical feature handling
- Built-in handling of missing values
- Good regularization out-of-the-box

---

## Feature Analysis

### Data Availability Check

| Table | Rows | Key Features |
|-------|------|--------------|
| mlb_analytics.pitcher_game_summary | 9,793 | Rolling K, season stats |
| mlb_precompute.pitcher_ml_features | 0 | Schema only, not populated |
| mlb_precompute.lineup_k_analysis | Populated | Bottom-up K expected |

### Features Already Populated (✅)

```
Rolling K averages (k_avg_last_3, k_avg_last_5, k_avg_last_10)
K volatility (k_std_last_10)
Innings pitched average (ip_avg_last_5)
Season stats (k_per_9, era, whip, games, total K)
Workload metrics (days_rest, games_last_30_days)
Data quality scores (data_completeness_score, rolling_stats_games)
```

### Features NOT Populated (❌ - Need to Add)

```
home_away_k_diff     - Column exists but 0% populated
day_night_k_diff     - Column exists but 0% populated
opponent_team_k_rate - Column exists but 0% populated
opponent_obp         - Column exists but 0% populated
ballpark_k_factor    - Column exists but 0% populated
vs_opponent_k_per_9  - Column exists but 0% populated
```

---

## Files Created/Modified

### New Files

| File | Purpose |
|------|---------|
| `predictions/mlb/pitcher_strikeouts_predictor_v2.py` | V2 predictor class (CatBoost) |
| `docs/.../2026-01-14-SESSION-41-HANDOFF-V2-PLANNING.md` | This document |

### Updated Files

| File | Changes |
|------|---------|
| `docs/.../PROJECT-ROADMAP.md` | Added V2 implementation plan |
| `docs/.../2026-01-14-SESSION-40-HANDOFF-HIT-RATE-ANALYSIS.md` | Previous session |

---

## V2 Predictor Details

### Architecture

```python
# predictions/mlb/pitcher_strikeouts_predictor_v2.py

class PitcherStrikeoutsPredictorV2:
    SYSTEM_ID = 'pitcher_strikeouts_v2'
    MODEL_VERSION = 'v2'
    ALGORITHM = 'catboost'

    V2_FEATURE_ORDER = [
        # Rolling Performance (5)
        'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
        'f03_k_std_last_10', 'f04_ip_avg_last_5',

        # Season Stats (5)
        'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
        'f08_season_games', 'f09_season_k_total',

        # Game Context (5) - EXPANDED
        'f10_is_home', 'f11_home_away_k_diff', 'f12_is_day_game',
        'f13_day_night_k_diff', 'f24_is_postseason',

        # Matchup Context (5) - NEW
        'f14_vs_opponent_k_rate', 'f15_opponent_team_k_rate',
        'f16_opponent_obp', 'f17_ballpark_k_factor', 'f18_game_total_line',

        # Workload (4)
        'f20_days_rest', 'f21_games_last_30_days',
        'f22_pitch_count_avg', 'f23_season_ip_total',

        # Bottom-Up Model (5) - EXPANDED
        'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand',
        'f27_platoon_advantage', 'f33_lineup_weak_spots', 'f34_matchup_edge',
    ]
```

### Key Differences from V1

| Aspect | V1 | V2 |
|--------|----|----|
| Algorithm | XGBoost | CatBoost |
| Features | 19 | 29 |
| Min Edge Threshold | 0.5 | 1.0 |
| Base Confidence | 70 | 75 |
| Has Fallback | No | Yes |
| Tracks model_version | Limited | Full |

---

## Implementation Plan

### Phase 2: Feature Engineering (Next Session)

**Tasks:**

1. **Populate missing analytics features**
   ```sql
   -- Task 2.1: Calculate home/away K diff
   UPDATE mlb_analytics.pitcher_game_summary
   SET home_away_k_diff = COALESCE(home_k_per_9, 0) - COALESCE(away_k_per_9, 0)
   WHERE game_date >= '2024-01-01';

   -- Task 2.2: Calculate opponent team K rate
   -- Join with team batting stats

   -- Task 2.3: Add ballpark K factors
   -- Load from mlb_reference.ballpark_factors
   ```

2. **Update feature processor**
   - Modify `pitcher_game_summary_processor.py`
   - Add calculation for missing columns

### Phase 3: Model Training (After Phase 2)

**Tasks:**

1. **Export training data**
   ```sql
   SELECT
       f00_k_avg_last_3, f01_k_avg_last_5, ...,
       actual_strikeouts
   FROM mlb_analytics.pitcher_game_summary
   WHERE game_date BETWEEN '2024-04-01' AND '2025-05-31'
     AND actual_strikeouts IS NOT NULL
   ```

2. **Train CatBoost model**
   ```python
   from catboost import CatBoostRegressor

   model = CatBoostRegressor(
       iterations=1000,
       learning_rate=0.05,
       depth=6,
       early_stopping_rounds=50,
       random_seed=42
   )
   model.fit(X_train, y_train, eval_set=(X_val, y_val))
   ```

3. **Save to GCS**
   ```
   gs://nba-scraped-data/ml-models/mlb/pitcher_strikeouts_v2_YYYYMMDD.cbm
   ```

### Phase 4: Champion-Challenger (After Phase 3)

**Tasks:**

1. **Run both models in parallel**
   - V1 and V2 predict for same games
   - Track with `model_version` field

2. **Daily comparison query**
   ```sql
   SELECT
       model_version,
       COUNT(*) as picks,
       COUNTIF(is_correct = TRUE) as wins,
       ROUND(COUNTIF(is_correct = TRUE) / COUNT(*) * 100, 2) as hit_rate
   FROM mlb_predictions.pitcher_strikeouts
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY model_version
   ```

3. **Promotion criteria**
   - Hit rate >= 67.27% (match V1)
   - MAE <= 1.46 (match V1)
   - 100+ picks over 7+ days

---

## Quick Reference

### Check V1 Performance (Baseline)
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    COUNT(*) as total,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM mlb_predictions.pitcher_strikeouts
WHERE is_correct IS NOT NULL
'''
for row in client.query(query): print(f'V1 Hit Rate: {row.hit_rate}%')
"
```

### Test V2 Predictor (Once Model Trained)
```bash
python predictions/mlb/pitcher_strikeouts_predictor_v2.py \
    --pitcher degrom-jacob \
    --date 2026-04-01 \
    --debug
```

### Compare V1 vs V2 (During Season)
```bash
python scripts/mlb/monitoring/model_comparison.py --days 7
```

---

## Current Backfill Status

| Phase | Status | Details |
|-------|--------|---------|
| Phase 1 (GCS Scraping) | ✅ 98% | 345/352 dates |
| Phase 2 (BQ Loading) | ✅ 100% | All loaded |
| Phase 3 (Matching) | ✅ 100% | 7,226 matched |
| Phase 4 (Grading) | ✅ 100% | 7,196 graded |
| Phase 5 (Hit Rate) | ✅ 100% | 67.27% |

---

## BettingPros Scraper Status

| Item | Status |
|------|--------|
| Scraper File | ✅ `scrapers/bettingpros/bp_mlb_player_props.py` |
| Market ID | ✅ 285 (pitcher strikeouts) |
| API Endpoint | ✅ `/v3/props` with FantasyPros headers |
| Historical Data | ❌ Live only (no historical) |
| Testing | Pending (MLB off-season) |

---

## Next Session Tasks

### Priority 1: Populate Missing Features

1. Run SQL updates for:
   - `home_away_k_diff`
   - `day_night_k_diff`
   - `opponent_team_k_rate`
   - `ballpark_k_factor`

2. Verify data population:
   ```sql
   SELECT
       COUNTIF(home_away_k_diff IS NOT NULL) as home_away_populated,
       COUNTIF(opponent_team_k_rate IS NOT NULL) as opp_k_populated,
       COUNT(*) as total
   FROM mlb_analytics.pitcher_game_summary
   WHERE game_date >= '2024-01-01'
   ```

### Priority 2: Export Training Data

1. Query features with actual strikeouts
2. Split into train/validation/test
3. Save to local CSV or BigQuery

### Priority 3: Train V2 Model

1. Install CatBoost if needed: `pip install catboost`
2. Train with hyperparameter tuning
3. Evaluate on test set
4. Upload to GCS

---

## Summary

Session 41 completed the planning phase for V2 model development:

1. **Confirmed Option B** (Champion-Challenger framework)
2. **Analyzed feature availability** - 29 features designed, need to populate ~6
3. **Created V2 predictor skeleton** with CatBoost architecture
4. **Updated PROJECT-ROADMAP.md** with implementation plan
5. **Identified next steps** for feature engineering and training

The V2 model infrastructure is ready. Next session should focus on populating missing features and training the model.
