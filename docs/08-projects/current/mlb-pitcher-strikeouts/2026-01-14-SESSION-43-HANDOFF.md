# Session 43 Handoff: MLB Pitcher Strikeouts V2 Feature Engineering

**Date:** 2026-01-14
**Previous Session:** 42 (V2 Data Audit & V2-Lite Training)
**Status:** Feature engineering in progress, ready to continue

---

## Executive Summary

Session 42 made significant progress on V2 model development. We populated 4 new features, trained a V2-Lite model (which underperformed V1), and identified clear next steps. The session was cut off while investigating the splits scraper.

**Key Achievement:** Seasonal features are now 100% populated and scrapers exist for all remaining features.

---

## Current Feature Population Status

| Feature | Status | Population |
|---------|--------|------------|
| opponent_team_k_rate | ✅ DONE | 100% (9,793 rows) |
| ballpark_k_factor | ✅ DONE | 100% (9,793 rows) |
| month_of_season | ✅ DONE | 100% (9,793 rows) |
| days_into_season | ✅ DONE | 100% (9,793 rows) |
| home_away_k_diff | ⏳ Scraper Ready | 0% |
| day_night_k_diff | ⏳ Scraper Ready | 0% |
| vs_opponent_k_per_9 | ⏳ Scraper Ready | 0% |
| is_day_game | ❌ No Data Source | 0% |
| game_total_line | ❌ No Data Source | 0% |

---

## V2-Lite Training Results (Session 42)

**Model ID:** pitcher_strikeouts_v2_20260114_132434

| Metric | V1 (XGBoost) | V2-Lite (CatBoost) | Delta |
|--------|--------------|---------------------|-------|
| MAE | 1.46 | 1.75 | -19.7% (worse) |
| Hit Rate (Aug-Sep) | 59.52% | 54.90% | -4.62pp (worse) |

**Key Finding:** V2-Lite with CatBoost + 2 new features underperformed V1. This suggests:
1. CatBoost may need different hyperparameters
2. These 2 features alone aren't enough
3. Keep V1 as champion, add features incrementally with XGBoost

---

## Seasonal Performance Pattern Discovered

| Month | V1 Hit Rate | Trend |
|-------|-------------|-------|
| Mar | 75.45% | Peak |
| Apr | 70.09% | Strong |
| May | 69.65% | Strong |
| Jun | 65.27% | Declining |
| **Jul** | **58.92%** | **Worst** |
| **Aug** | **56.64%** | **Worst** |
| Sep | 62.87% | Recovery |

**Pattern:** Clear seasonal decline from March (75%) to August (57%). The month_of_season and days_into_season features should help the model learn this pattern.

---

## Available Scrapers for Remaining Features

### 1. mlb_player_splits.py
**Location:** `scrapers/mlb/balldontlie/mlb_player_splits.py`
**Provides:**
- Home/away K rates → `home_away_k_diff`
- Day/night K rates → `day_night_k_diff`
- Monthly performance
- Recent form (last 7/15/30 days)

**Usage:**
```bash
PYTHONPATH=. python scrapers/mlb/balldontlie/mlb_player_splits.py --player_id 123 --season 2025
```

### 2. mlb_player_versus.py
**Location:** `scrapers/mlb/balldontlie/mlb_player_versus.py`
**Provides:**
- Pitcher K rate vs specific teams → `vs_opponent_k_per_9`
- Favorable/unfavorable matchup identification
- Historical dominance indicators

**Usage:**
```bash
PYTHONPATH=. python scrapers/mlb/balldontlie/mlb_player_versus.py --player_id 12345 --season 2025
```

---

## Training Data Strategy

### Current State
- **Training data available:** 2024-2025 seasons (~9,793 pitcher game summaries)
- **Betting lines available:** Mid-2024 onwards (Odds API limitation)
- **Ball Don't Lie stats:** 2024-2025 (97,679 batter stats, pitcher stats available)

### Can We Backfill More Seasons?

| Data Type | 2022-2023 Available? | Notes |
|-----------|---------------------|-------|
| Pitcher stats | ✅ Yes | BDL API supports historical |
| Batter stats | ✅ Yes | BDL API supports historical |
| Betting lines | ❌ No | Odds API starts ~mid-2024 |
| Actual strikeouts | ✅ Yes | BDL game stats |

**Limitation:** We cannot train on 2022-2023 data with betting lines because Odds API doesn't have historical props that far back. The model needs the line to calculate edge.

### Recommendation
- **Keep current training window:** 2024-2025 is optimal given data availability
- **Backfill pitcher stats for features:** Can scrape 2022-2023 to calculate better historical averages
- **Don't extend training set:** Without betting lines, additional seasons can't be used for supervised training

---

## BigQuery Tables Created/Modified

### New Reference Tables
```sql
-- Team strikeout rates
mlb_reference.team_k_rates (63 rows, 32 teams × 2 seasons)

-- Ballpark strikeout factors
mlb_reference.ballpark_k_factors (39 venues)
```

### Modified Tables
```sql
-- Updated with new features
mlb_analytics.pitcher_game_summary
  + opponent_team_k_rate (100%)
  + ballpark_k_factor (100%)
  + month_of_season (100%)
  + days_into_season (100%)
```

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `scripts/mlb/training/train_pitcher_strikeouts_v2.py` | V2 CatBoost training script |
| `models/mlb/pitcher_strikeouts_v2_20260114_132434.cbm` | V2-Lite model (not production) |
| `docs/08-projects/current/mlb-performance-analysis/README.md` | Performance tracking index |
| `docs/08-projects/current/mlb-performance-analysis/PERFORMANCE-ANALYSIS-GUIDE.md` | Monitoring guide |
| `docs/08-projects/current/mlb-performance-analysis/FEATURE-IMPROVEMENT-ROADMAP.md` | Feature roadmap |
| `docs/08-projects/current/mlb-pitcher-strikeouts/2026-01-14-SESSION-42-V2-DATA-AUDIT.md` | Session 42 detailed notes |

---

## Recommended Next Steps (Prioritized)

### Immediate (This Session)

1. **Test XGBoost with New Features**
   - Keep V1 algorithm, add the 4 populated features
   - Compare against V1 baseline
   - This tests if features help without algorithm change

2. **Run Splits Scraper for All Pitchers**
   - Get list of pitcher IDs from pitcher_game_summary
   - Run mlb_player_splits.py for each
   - Store results for feature population

3. **Run Versus Scraper for All Pitchers**
   - Run mlb_player_versus.py for each pitcher
   - Calculate vs_opponent_k_per_9 for each matchup

### Short-term (Next Sessions)

4. **Populate Splits Features**
   - home_away_k_diff from splits data
   - day_night_k_diff from splits data

5. **Populate Versus Features**
   - vs_opponent_k_per_9 from versus data

6. **Retrain V2 with Full Feature Set**
   - All 4 populated features + splits + versus
   - Compare against V1

### Medium-term

7. **Investigate Umpire K Factor**
   - Check umpire_game_assignment table
   - Calculate umpire strikeout tendencies

8. **Game Totals Integration**
   - Research alternative data sources for game totals
   - The Odds API game_lines appears empty

---

## Commands to Resume

### Check Current Feature Status
```bash
python3 << 'EOF'
from google.cloud import bigquery
client = bigquery.Client()
query = """
SELECT
    COUNT(*) as total_rows,
    COUNTIF(opponent_team_k_rate > 0) as opp_k_rate,
    COUNTIF(ballpark_k_factor > 0) as ballpark,
    COUNTIF(month_of_season IS NOT NULL) as month,
    COUNTIF(days_into_season IS NOT NULL) as days
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-01-01'
"""
for row in client.query(query).result():
    print(f"Total: {row.total_rows}")
    print(f"opponent_team_k_rate: {row.opp_k_rate} ({100*row.opp_k_rate/row.total_rows:.0f}%)")
    print(f"ballpark_k_factor: {row.ballpark} ({100*row.ballpark/row.total_rows:.0f}%)")
    print(f"month_of_season: {row.month} ({100*row.month/row.total_rows:.0f}%)")
    print(f"days_into_season: {row.days} ({100*row.days/row.total_rows:.0f}%)")
EOF
```

### Get Pitcher IDs for Scraping
```bash
python3 << 'EOF'
from google.cloud import bigquery
client = bigquery.Client()
query = """
SELECT DISTINCT player_id, player_name
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-01-01' AND player_id IS NOT NULL
ORDER BY player_name
"""
for row in client.query(query).result():
    print(f"{row.player_id}: {row.player_name}")
EOF
```

### Test Splits Scraper
```bash
PYTHONPATH=. python scrapers/mlb/balldontlie/mlb_player_splits.py --player_id 12345 --season 2025 --debug
```

---

## Key Learnings from Session 42

1. **Don't change algorithm and features together** - Test new features with proven XGBoost first
2. **Seasonal patterns are real** - March 75% → August 57% is a significant drop
3. **ballpark_k_factor is valuable** - Ranked #2 in feature importance (10.3%)
4. **V1 remains champion** - 59.52% vs 54.90% on same test period
5. **Training data is limited by Odds API** - Can't backfill 2022-2023 betting lines

---

## Decision Points for Next Session

1. **Should we try XGBoost + 4 new features?** (Recommended: Yes)
2. **Should we run splits scraper for all pitchers?** (Recommended: Yes, if time permits)
3. **Should we extend training data to 2022-2023?** (Recommended: No, lacking betting lines)
4. **Should we investigate umpire data?** (Recommended: Lower priority, do features first)

---

## Session Status

**V1 Model:** Production champion (67.27% overall hit rate)
**V2-Lite Model:** Failed experiment (54.90% hit rate on test set)
**Feature Pipeline:** 4/10 features populated, scrapers ready for 3 more

**Ready to continue:** Yes - clear path forward with XGBoost + new features test
