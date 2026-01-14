# MLB Pipeline Fix and Collection - 2026-01-07

## Session Summary

Fixed critical data pipeline gap and set up automated collection for MLB pitcher strikeouts prediction.

## Critical Issue Found & Fixed

### The Problem
- Collection script extracted pitcher stats (strikeouts, IP, etc.) from MLB Stats API
- BUT only stored game lineups and batter data to BigQuery
- Analytics processors needed `bdl_pitcher_stats` which was empty (BDL API unauthorized)
- Result: ML training had no source data

### The Fix
1. **Added `load_pitcher_stats()` method** to `BigQueryLoader` class
2. **Created `mlb_pitcher_stats` BigQuery table** with proper schema
3. **Updated `pitcher_game_summary_processor.py`** to read from new table
4. **Added walks_allowed** to collection for WHIP calculation

## Files Modified

| File | Change |
|------|--------|
| `scripts/mlb/collect_season.py` | Added `load_pitcher_stats()`, `_pitcher_row()` methods |
| `data_processors/analytics/mlb/pitcher_game_summary_processor.py` | Changed source from `bdl_pitcher_stats` to `mlb_pitcher_stats` |

## New Files Created

| File | Purpose |
|------|---------|
| `scripts/mlb/train_pitcher_strikeouts.py` | XGBoost training script for pitcher K predictions |

## Data Collection Status

### Completed (without pitcher stats - old code)
- 2025 season: 2,462 games, 4,924 pitcher starts
- 2024 season: In progress (will complete ~1:35 PM)

### Auto-Collection Running
```bash
# Monitoring log:
tail -f logs/mlb_auto_collection.log

# Process:
1. Waits for current 2024 collection to finish
2. Re-runs 2025 with pitcher stats (~50 min)
3. Re-runs 2024 with pitcher stats (~50 min)
```

**Expected completion: ~4:00 PM PST**

## BigQuery Tables

### New Table: `mlb_raw.mlb_pitcher_stats`
```sql
-- Schema
game_pk: INTEGER
game_date: DATE (partitioned)
game_id: STRING
season_year: INTEGER
player_id: INTEGER
player_name: STRING
player_lookup: STRING (clustered)
team_abbr: STRING (clustered)
opponent_team_abbr: STRING
is_home: BOOLEAN
is_starter: BOOLEAN
throws: STRING
strikeouts: INTEGER
innings_pitched: FLOAT
hits_allowed: INTEGER
walks_allowed: INTEGER
earned_runs: INTEGER
pitch_count: INTEGER
k_per_9: FLOAT
venue: STRING
game_status: STRING
source: STRING
created_at: TIMESTAMP
processed_at: TIMESTAMP
```

## Pipeline Flow (After Collection)

```
Raw Collection (mlb_pitcher_stats)
    ↓
Analytics (pitcher_game_summary)
    ↓
ML Training (train_pitcher_strikeouts.py)
    ↓
Model Output (target MAE < 1.92)
```

## Next Steps (After 4:00 PM)

1. **Verify pitcher stats collected**:
   ```bash
   bq query --nouse_legacy_sql 'SELECT COUNT(*) FROM mlb_raw.mlb_pitcher_stats WHERE game_date >= "2024-01-01"'
   ```

2. **Run analytics pipeline**:
   ```bash
   PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor \
     --start-date 2024-03-28 --end-date 2025-09-28
   ```

3. **Train ML model**:
   ```bash
   PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py
   ```

4. **Validate results** against baseline MAE 1.92

## Monitoring Commands

```bash
# Check auto-collection progress
tail -f logs/mlb_auto_collection.log

# Check if collections running
pgrep -f "collect_season"

# Check BigQuery data
bq query --nouse_legacy_sql 'SELECT COUNT(*) FROM mlb_raw.mlb_pitcher_stats WHERE game_date >= "2024-01-01"'
```

## Session Context

- Started: ~11:00 AM PST
- Auto-collection started: 1:11 PM PST
- Expected completion: ~4:00 PM PST
- Baseline MAE: 1.92 (from bottom-up formula)
- Target MAE: < 1.7 (with ML model)
