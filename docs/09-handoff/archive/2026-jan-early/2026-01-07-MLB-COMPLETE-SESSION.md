# MLB Pitcher Strikeouts - Complete Session Summary

**Date**: 2026-01-07
**Status**: Infrastructure 100% Complete, Awaiting Historical Data

---

## What Was Accomplished This Session

### 1. Created 11 New BigQuery Tables

| Table | Dataset | Purpose |
|-------|---------|---------|
| `bdl_standings` | mlb_raw | Playoff context, games back |
| `bdl_box_scores` | mlb_raw | Final game results for grading |
| `bdl_live_box_scores` | mlb_raw | Live game tracking |
| `bdl_team_season_stats` | mlb_raw | Team K rates |
| `bdl_player_versus` | mlb_raw | Pitcher vs team history |
| `mlb_game_feed` | mlb_raw | Pitch-by-pitch data |
| `statcast_pitcher_stats` | mlb_raw | Advanced metrics (whiff%, chase%) |
| `game_weather` | mlb_raw | Weather conditions at game time |
| `bdl_teams` | mlb_reference | Team reference data |
| `umpire_stats` | mlb_reference | Umpire K zone tendencies |
| `ballpark_factors` | mlb_reference | Park K adjustments |

### 2. Completed Feature Processor (All 25 Features)

Previously had 13 TODOs, now all resolved:

| Feature | Was | Now |
|---------|-----|-----|
| f11_home_away_k_diff | TODO | Calculated from pitcher splits |
| f13_day_night_k_diff | TODO | Calculated from pitcher splits |
| f14_vs_opponent_k_rate | TODO | From pitcher vs team history |
| f16_opponent_obp | TODO | Calculated from batter stats |
| f17_ballpark_k_factor | TODO | From ballpark_factors table |
| f18_game_total_line | TODO | From game lines table |
| f19_team_implied_runs | TODO | Calculated from moneyline |
| f22_pitch_count_avg | TODO | From pitcher analytics |
| f23_season_ip_total | TODO | From pitcher analytics |

**New data sources wired up:**
- `_get_pitcher_splits()` - Home/away, day/night K/9
- `_get_game_lines()` - Game totals and moneylines
- `_get_ballpark_factors()` - Park K adjustments
- `_get_pitcher_vs_team()` - Historical vs opponent
- `_moneyline_to_probability()` - Implied probability helper
- `_calculate_team_obp()` - Opponent OBP calculation

### 3. Verified API Connectivity

Ball Don't Lie MLB API confirmed working with test query for 2024-06-15 data.

---

## Current Infrastructure Summary

| Component | Count | Status |
|-----------|-------|--------|
| Scrapers | 28 | ✅ Complete |
| Raw Tables (mlb_raw) | 22 | ✅ Complete |
| Reference Tables (mlb_reference) | 3 | ✅ Complete |
| Analytics Tables | 2 | ✅ Complete |
| Precompute Tables | 1 | ✅ Complete |
| Raw Processors | 8 | ✅ Complete |
| Analytics Processors | 2 | ✅ Complete |
| Feature Processor | 1 | ✅ Complete (25/25 features) |
| Training Script | 0 | ❌ Not started |
| Prediction Workers | 0 | ❌ Not started |

---

## BigQuery Tables by Dataset

### mlb_raw (22 tables)
```
Ball Don't Lie:
├── bdl_pitcher_stats         (per-game pitcher stats)
├── bdl_batter_stats          (per-game batter stats)
├── bdl_games                 (game schedule/scores)
├── bdl_active_players        (roster snapshots)
├── bdl_injuries              (injury reports)
├── bdl_pitcher_season_stats  (season aggregates)
├── bdl_pitcher_splits        (home/away/day/night splits)
├── bdl_standings             (playoff context) NEW
├── bdl_box_scores            (final results) NEW
├── bdl_live_box_scores       (live tracking) NEW
├── bdl_team_season_stats     (team K rates) NEW
└── bdl_player_versus         (pitcher vs team) NEW

MLB Stats API:
├── mlb_schedule              (probable pitchers)
├── mlb_game_lineups          (lineup availability)
├── mlb_lineup_batters        (batter details)
└── mlb_game_feed             (pitch-by-pitch) NEW

Odds API:
├── oddsa_events              (event IDs)
├── oddsa_game_lines          (moneyline/totals)
├── oddsa_pitcher_props       (K lines)
└── oddsa_batter_props        (batter K lines)

Other:
├── statcast_pitcher_stats    (advanced metrics) NEW
└── game_weather              (weather data) NEW
```

### mlb_reference (3 tables)
```
├── bdl_teams                 (team reference) NEW
├── umpire_stats              (umpire tendencies) NEW
└── ballpark_factors          (park adjustments) NEW
```

### mlb_analytics (2 tables)
```
├── pitcher_game_summary      (rolling K stats)
└── batter_game_summary       (rolling K rates)
```

### mlb_precompute (1 table)
```
└── pitcher_ml_features       (25-feature vectors)
```

---

## What's Next

### Immediate Priority: Historical Backfill

Tables are empty. Need to run historical scrapers:

```bash
# Example backfill for 2024 season (April-October)
for date in 2024-04-{01..30} 2024-05-{01..31} ...; do
  SPORT=mlb python scrapers/mlb/balldontlie/mlb_pitcher_stats.py --date $date
  sleep 1
done
```

### After Backfill

1. **Process raw data** - Run raw processors to populate tables
2. **Run analytics** - Populate pitcher/batter game summaries
3. **Generate features** - Populate pitcher_ml_features
4. **Create training script** - `ml/train_pitcher_strikeouts_xgboost.py`
5. **Train model** - Use 2024 season data
6. **Create prediction workers** - Deploy for 2025 season

---

## Copy-Paste for Next Session

```
Continue the MLB pitcher strikeouts project.

Read: docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md

COMPLETED THIS SESSION:
- Created 11 new BigQuery tables (standings, box_scores, statcast, etc.)
- Completed all 25 features in pitcher_features_processor.py
- Verified API connectivity
- Updated all documentation

INFRASTRUCTURE STATUS:
- Scrapers: 28/28 complete
- Raw Tables: 22/22 complete
- Reference Tables: 3/3 complete
- Analytics Tables: 2/2 complete
- Feature Processor: 25/25 features complete

BLOCKER: Tables are empty - need historical data

NEXT STEPS:
1. Run historical backfill (2024 MLB season)
2. Process raw data into analytics tables
3. Create training script (ml/train_pitcher_strikeouts_xgboost.py)
4. Train initial model
```
