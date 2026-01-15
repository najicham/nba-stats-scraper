# Session 44 Handoff: MLB Pitcher Strikeouts V1+4 Features Success

**Date:** 2026-01-14
**Previous Session:** 43 (Feature Engineering Planning)
**Status:** V1+4 features trained successfully, splits scraper blocked

---

## Executive Summary

Session 44 achieved a key milestone: **XGBoost + 4 new features improved model performance** (MAE 1.708 → 1.66, 2.8% improvement). However, the splits scraper investigation revealed blockers that need resolution before populating additional features.

**Key Achievement:** Proved that the 4 seasonal/contextual features improve the model when added to XGBoost (without algorithm change).

---

## What Was Accomplished

### 1. XGBoost + 4 Features Training (SUCCESS)

**Model ID:** `mlb_pitcher_strikeouts_v1_4features_20260114_142456`

| Metric | V1 Original (19 feat) | V1 + 4 Features (25 feat) | Change |
|--------|----------------------|---------------------------|--------|
| Train MAE | 1.519 | 1.45 | -0.07 (better) |
| Val MAE | 1.657 | 1.61 | -0.05 (better) |
| Test MAE | 1.708 | 1.66 | **-0.05 (better)** |
| Improvement vs baseline | 11.0% | 13.6% | **+2.6pp** |

**Feature Importance (Top 10):**
1. f06_season_era - 13.9%
2. f02_k_avg_last_10 - 12.4%
3. f01_k_avg_last_5 - 5.0%
4. f05_season_k_per_9 - 4.9%
5. f25_bottom_up_k_expected - 4.6%
6. f26_lineup_k_vs_hand - 4.3%
7. **f16_ballpark_k_factor - 3.9%** ← NEW FEATURE
8. f10_is_home - 3.8%
9. f27_avg_k_vs_opponent - 3.6%
10. f09_season_k_total - 3.3%

**Key Finding:** `ballpark_k_factor` ranked #7 in importance, validating this feature's value. The other 3 new features (opponent_team_k_rate, month_of_season, days_into_season) didn't make top 10 but contributed to overall improvement.

### 2. Code Changes Made

**Modified File:** `scripts/mlb/train_pitcher_strikeouts.py`

Changes made:
1. Added 4 new features to BigQuery query (lines 246-250):
   ```sql
   pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
   pgs.ballpark_k_factor as f16_ballpark_k_factor,
   pgs.month_of_season as f17_month_of_season,
   pgs.days_into_season as f18_days_into_season,
   ```

2. Added COALESCE defaults (lines 328-332):
   ```sql
   COALESCE(f15_opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
   COALESCE(f16_ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
   COALESCE(f17_month_of_season, 6) as f17_month_of_season,
   COALESCE(f18_days_into_season, 90) as f18_days_into_season,
   ```

3. Added features to feature_cols list (lines 449-453):
   ```python
   'f15_opponent_team_k_rate',
   'f16_ballpark_k_factor',
   'f17_month_of_season',
   'f18_days_into_season',
   ```

4. Updated model naming (line 653):
   ```python
   model_id = f"mlb_pitcher_strikeouts_v1_4features_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
   ```

### 3. Umpire Data Investigation (BLOCKED)

**Finding:** Table `mlb_reference.umpire_game_assignment` does not exist.
**Status:** Cannot calculate umpire K factors without this data.

### 4. Splits Scraper Investigation (BLOCKED)

**Finding:** BDL splits API returns excellent data BUT:

1. **Scraper transform doesn't parse response correctly**
   - Scraper expects: flat keys like `home`, `away`, `day`, `night`
   - API returns: nested arrays like `byBreakdown[].split_name = "Home"`

2. **Player ID mismatch**
   - Our data uses MLB Stats API IDs (e.g., Logan Webb = 657277)
   - BDL API uses different IDs (e.g., Logan Webb = 971)
   - Need to build mapping table

**Raw API Response Structure:**
```json
{
  "data": {
    "byArena": [...],      // Stats by ballpark
    "byBreakdown": [       // Home/Away/Day/Night
      {"split_name": "Home", "strikeouts_pitched": 79, ...},
      {"split_name": "Away", "strikeouts_pitched": 93, ...},
      {"split_name": "Day", "strikeouts_pitched": 70, ...},
      {"split_name": "Night", "strikeouts_pitched": 102, ...}
    ],
    "byDayMonth": [...],   // Monthly splits
    "byOpponent": [...]    // vs each team
  }
}
```

**Sample Data (Logan Webb 2024):**
- Home: 79 Ks in 101.2 IP (ERA 2.83)
- Away: 93 Ks in 103 IP (ERA 4.11)
- Day: 70 Ks in 77.2 IP (ERA 3.24)
- Night: 102 Ks in 127 IP (ERA 3.61)

---

## Remaining Todo Items (Prioritized)

### High Priority

#### 1. Fix Splits Scraper Transform
**File:** `scrapers/mlb/balldontlie/mlb_player_splits.py`
**Issue:** `transform_data()` method doesn't parse actual BDL response format
**Fix Required:**
```python
# Current (broken):
processed_splits["home"] = splits_data.get("home", {})

# Should be:
by_breakdown = splits_data.get("byBreakdown", [])
for split in by_breakdown:
    if split.get("split_name") == "Home":
        processed_splits["home"] = split
    elif split.get("split_name") == "Away":
        processed_splits["away"] = split
    # etc.
```

#### 2. Build BDL Player ID Mapping
**Need:** Map MLB Stats API player_id → BDL player_id
**Approach:**
- Query BDL `/players?search={name}` endpoint for each pitcher
- Store mapping in BigQuery or player registry
- Update `mlb_players_registry.bdl_player_id` column (currently NULL)

**Example mapping:**
| player_lookup | mlb_stats_id | bdl_player_id |
|---------------|--------------|---------------|
| logan_webb | 657277 | 971 |

#### 3. Run Splits Scraper for All Pitchers
After fixes above:
1. Get unique pitcher IDs from `pitcher_game_summary`
2. Map to BDL IDs
3. Run scraper for each pitcher × season (2024, 2025)
4. Calculate features:
   - `home_away_k_diff = (home_k_per_9 - away_k_per_9)`
   - `day_night_k_diff = (day_k_per_9 - night_k_per_9)`

### Medium Priority

#### 4. Historical Odds Backfill
**Status:** User is researching alternative historical prop odds sources
**Infrastructure:** 5-phase pipeline ready in `scripts/mlb/historical_odds_backfill/`
**Wait for:** User to confirm data source

#### 5. Run Versus Scraper
**File:** `scrapers/mlb/balldontlie/mlb_player_versus.py`
**Same issues as splits scraper likely apply:**
- Probably needs transform fix
- Needs BDL player ID mapping
- Populates `vs_opponent_k_per_9` feature

#### 6. Research is_day_game Data Source
**Current state:** `is_day_game` column in pitcher_game_summary is 0% populated
**Potential sources:**
- Retrosheet game logs (has day/night indicator)
- MLB Stats API (has game start times)
- ESPN API

#### 7. Backfill game_total_line
**Current state:** `oddsa_game_lines` table is empty
**Fix:** Extend historical backfill to include `totals` market from Odds API

### Lower Priority

#### 8. Integrate BettingPros Fallback
**File:** `scrapers/bettingpros/bp_mlb_player_props.py`
**Market ID:** 285 (pitcher strikeouts)
**Model on:** NBA fallback implementation
**Benefit:** Increase odds coverage from ~70% to ~95%

---

## Current Feature Population Status

| Feature | Status | Population | Notes |
|---------|--------|------------|-------|
| opponent_team_k_rate | ✅ DONE | 100% | In training |
| ballpark_k_factor | ✅ DONE | 100% | In training, #7 importance |
| month_of_season | ✅ DONE | 100% | In training |
| days_into_season | ✅ DONE | 100% | In training |
| home_away_k_diff | ⛔ BLOCKED | 0% | Scraper needs fix |
| day_night_k_diff | ⛔ BLOCKED | 0% | Scraper needs fix |
| vs_opponent_k_per_9 | ⛔ BLOCKED | 0% | Scraper needs fix |
| is_day_game | ❌ No Source | 0% | Need to research |
| game_total_line | ❌ Empty Table | 0% | Need to backfill |
| umpire_k_factor | ❌ No Table | 0% | Table doesn't exist |

---

## Model Comparison Summary

| Model | Algorithm | Features | Test MAE | Status |
|-------|-----------|----------|----------|--------|
| V1 Original | XGBoost | 19 | 1.708 | Production |
| V1 + 4 Features | XGBoost | 25 | **1.66** | Ready to deploy |
| V2-Lite | CatBoost | 21 | 1.75 | Failed experiment |

**Recommendation:** Promote V1+4 Features to production - it beats V1 on same test set.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/mlb/train_pitcher_strikeouts.py` | V1 training script (modified this session) |
| `models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json` | New model |
| `scrapers/mlb/balldontlie/mlb_player_splits.py` | Splits scraper (needs fix) |
| `scrapers/mlb/balldontlie/mlb_player_versus.py` | Versus scraper (likely needs fix) |
| `scripts/mlb/historical_odds_backfill/` | Historical backfill pipeline |
| `scrapers/bettingpros/bp_mlb_player_props.py` | BettingPros MLB scraper |

---

## Commands to Resume

### Check Current Model Performance
```bash
PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py
```

### Test BDL Splits API Directly
```bash
BDL_KEY=$(grep BDL_API_KEY .env | cut -d'=' -f2)
curl -s -H "Authorization: $BDL_KEY" \
  "https://api.balldontlie.io/mlb/v1/players/splits?player_id=971&season=2024" | python -m json.tool | head -100
```

### Search BDL for Player ID
```bash
BDL_KEY=$(grep BDL_API_KEY .env | cut -d'=' -f2)
curl -s -H "Authorization: $BDL_KEY" \
  "https://api.balldontlie.io/mlb/v1/players?search=webb" | python -m json.tool
```

### Check Feature Population
```bash
python3 << 'EOF'
from google.cloud import bigquery
client = bigquery.Client()
query = """
SELECT
    COUNT(*) as total,
    COUNTIF(opponent_team_k_rate > 0) as opp_k,
    COUNTIF(ballpark_k_factor > 0) as ballpark,
    COUNTIF(month_of_season IS NOT NULL) as month,
    COUNTIF(days_into_season IS NOT NULL) as days
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-01-01'
"""
for row in client.query(query).result():
    print(f"Total: {row.total}")
    print(f"opponent_team_k_rate: {row.opp_k} ({100*row.opp_k/row.total:.0f}%)")
    print(f"ballpark_k_factor: {row.ballpark} ({100*row.ballpark/row.total:.0f}%)")
EOF
```

---

## Decision Points for Next Session

1. **Should we deploy V1+4 Features to production?** (Recommended: Yes)
2. **Should we fix splits scraper first or build player ID mapping first?** (Recommend: ID mapping first - needed for all BDL scrapers)
3. **Should we proceed with historical backfill or wait for user's source?** (Wait for user)
4. **Should we investigate is_day_game via Retrosheet?** (Recommend: Yes, after splits scraper fixed)

---

## Session Statistics

- **Duration:** ~1 hour
- **Tasks Completed:** 2 (training + umpire check)
- **Tasks Blocked:** 2 (splits scraper, umpire factors)
- **Key Win:** +2.8% model improvement with 4 new features
- **Context Used:** 62% (124k/200k tokens)

---

## Next Session Priority Order

1. Build BDL player ID mapping table
2. Fix splits scraper transform_data()
3. Run splits scraper for all pitchers
4. Populate home_away_k_diff and day_night_k_diff
5. Retrain V2 with all features
6. Deploy best model to production
