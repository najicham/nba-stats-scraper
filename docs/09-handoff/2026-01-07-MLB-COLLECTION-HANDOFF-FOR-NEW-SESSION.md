# MLB Pitcher Strikeouts - Handoff for New Session

**Date:** January 7, 2026, 2:50 PM PST
**Expected Check-in:** ~4:30 PM PST
**Project:** MLB Pitcher Strikeout Predictions

---

## Executive Summary

We're building an ML model to predict MLB pitcher strikeouts. Today we discovered and fixed a critical data pipeline gap where pitcher stats weren't being stored to BigQuery. Re-collection is now running and should complete by ~4:30 PM PST.

**Target:** Beat baseline MAE of 1.92 (from bottom-up formula)

---

## Current Status

### What's Running Now

```bash
# 2025 re-collection with pitcher stats - RUNNING
# Started: 2:47 PM PST
# ETA: ~3:40 PM PST

# 2024 will auto-start after 2025 completes
# ETA: ~4:30 PM PST
```

**Process ID:** 1512694 (2025 collection)

### Quick Status Check Commands

```bash
# Check if collection is running
ps aux | grep "collect_season" | grep -v grep

# Check 2025 progress
tail -20 /home/naji/code/nba-stats-scraper/logs/mlb_2025_recollect.log

# Check 2024 progress (after 2025 completes)
tail -20 /home/naji/code/nba-stats-scraper/logs/mlb_2024_recollect.log

# Check pitcher stats in BigQuery
bq query --nouse_legacy_sql 'SELECT COUNT(*) as cnt FROM mlb_raw.mlb_pitcher_stats WHERE game_date >= "2024-01-01"'
```

---

## Critical Issue Found & Fixed This Session

### The Problem

The collection script (`scripts/mlb/collect_season.py`) was extracting pitcher stats from MLB Stats API but **NOT storing them to BigQuery**:

```
BEFORE:
  MLB API → GameData (with pitcher stats) → BigQuery
                                              ↓
                              Only stored: mlb_game_lineups, mlb_lineup_batters
                              NOT stored:  pitcher stats (strikeouts, IP, etc.)

AFTER (FIXED):
  MLB API → GameData → BigQuery
                         ↓
             Now stores: mlb_game_lineups
                        mlb_lineup_batters
                        mlb_pitcher_stats ← NEW!
```

### Files Modified

| File | Change |
|------|--------|
| `scripts/mlb/collect_season.py` | Added `load_pitcher_stats()` method (lines 622-694), added call in `_process_date()` (line 817), added `walks` to `_extract_pitchers()` |
| `data_processors/analytics/mlb/pitcher_game_summary_processor.py` | Changed source table from `bdl_pitcher_stats` to `mlb_pitcher_stats`, updated field mappings |

### New BigQuery Table Created

```sql
-- Table: mlb_raw.mlb_pitcher_stats
-- Partitioned by: game_date
-- Clustered by: player_lookup, team_abbr

Schema:
  game_pk: INTEGER
  game_date: DATE
  game_id: STRING
  season_year: INTEGER
  player_id: INTEGER
  player_name: STRING
  player_lookup: STRING
  team_abbr: STRING
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

---

## Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MLB PITCHER STRIKEOUTS PIPELINE              │
└─────────────────────────────────────────────────────────────────┘

Phase 1: Raw Collection (RUNNING NOW)
─────────────────────────────────────
  scripts/mlb/collect_season.py
      ↓
  MLB Stats API → mlb_raw.mlb_pitcher_stats ← NEW!
               → mlb_raw.mlb_game_lineups
               → mlb_raw.mlb_lineup_batters

Phase 2: Analytics Processing (NEXT)
────────────────────────────────────
  data_processors/analytics/mlb/pitcher_game_summary_processor.py
      ↓
  mlb_raw.mlb_pitcher_stats → mlb_analytics.pitcher_game_summary

  Features computed:
    - k_avg_last_3, k_avg_last_5, k_avg_last_10 (rolling K averages)
    - k_std_last_10 (strikeout volatility)
    - ip_avg_last_5, ip_avg_last_10 (innings trends)
    - season_k_per_9, era_rolling_10, whip_rolling_10
    - days_rest, games_last_30_days

Phase 3: ML Training (FINAL)
───────────────────────────
  scripts/mlb/train_pitcher_strikeouts.py
      ↓
  mlb_analytics.pitcher_game_summary → XGBoost Model

  Target: actual_strikeouts
  Baseline MAE: 1.92
  Goal MAE: < 1.7
```

---

## When Collection Completes - Next Steps

### Step 1: Verify Pitcher Stats Collected

```bash
# Should show ~9,800+ rows (both seasons)
bq query --nouse_legacy_sql '
SELECT
  season_year,
  COUNT(*) as pitcher_starts,
  COUNT(DISTINCT player_lookup) as unique_pitchers,
  AVG(strikeouts) as avg_k
FROM mlb_raw.mlb_pitcher_stats
WHERE game_date >= "2024-01-01"
GROUP BY season_year
ORDER BY season_year
'
```

**Expected output:**
```
| season_year | pitcher_starts | unique_pitchers | avg_k |
|-------------|----------------|-----------------|-------|
| 2024        | ~4,900         | ~400            | ~5.5  |
| 2025        | ~4,900         | ~400            | ~5.5  |
```

### Step 2: Run Analytics Pipeline

```bash
cd /home/naji/code/nba-stats-scraper

# Process pitcher game summaries (creates rolling features)
PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor \
  --start-date 2024-03-28 --end-date 2025-09-28

# Verify analytics output
bq query --nouse_legacy_sql '
SELECT COUNT(*) as rows FROM mlb_analytics.pitcher_game_summary
WHERE game_date >= "2024-01-01"
'
```

### Step 3: Train ML Model

```bash
PYTHONPATH=. python scripts/mlb/train_pitcher_strikeouts.py
```

**Expected output:**
- Training on ~7,000+ pitcher starts
- Test MAE should be reported
- Model saved to `models/mlb/mlb_pitcher_strikeouts_v1_YYYYMMDD.json`

### Step 4: Evaluate Results

Compare test MAE to baseline:
- **Baseline MAE:** 1.92 (from bottom-up formula)
- **Target MAE:** < 1.7 (10%+ improvement)

If MAE > 1.92:
- Check feature importance
- Consider adding more features (platoon splits, umpire data)
- Check for data quality issues

---

## File Locations

### Key Scripts
```
scripts/mlb/collect_season.py          # Raw data collection
scripts/mlb/train_pitcher_strikeouts.py # ML training (NEW)
```

### Analytics Processors
```
data_processors/analytics/mlb/pitcher_game_summary_processor.py
data_processors/analytics/mlb/batter_game_summary_processor.py
```

### Precompute Processors
```
data_processors/precompute/mlb/pitcher_features_processor.py
data_processors/precompute/mlb/lineup_k_analysis_processor.py
```

### Log Files
```
logs/mlb_2025_recollect.log  # Current 2025 re-collection
logs/mlb_2024_recollect.log  # Will be created after 2025 completes
logs/mlb_2024_collection.log # Old 2024 collection (without pitcher stats)
logs/mlb_2025_collection.log # Old 2025 collection (without pitcher stats)
```

---

## BigQuery Tables

### Raw Layer (`mlb_raw`)
| Table | Records | Description |
|-------|---------|-------------|
| `mlb_pitcher_stats` | ~9,800 (after collection) | Pitcher game stats - NEW! |
| `mlb_game_lineups` | ~4,900 | Game metadata |
| `mlb_lineup_batters` | ~88,000 | Batter lineup positions |
| `bdl_pitcher_stats` | 15 | OLD - not usable (BDL unauthorized) |
| `bdl_batter_stats` | 0 | OLD - empty |

### Analytics Layer (`mlb_analytics`)
| Table | Records | Description |
|-------|---------|-------------|
| `pitcher_game_summary` | 0 (pending) | Rolling K features |
| `batter_game_summary` | 0 (pending) | Batter K rates |

---

## Known Issues & Workarounds

### 1. Ball Don't Lie API Unauthorized
- BDL MLB API returns 401 Unauthorized
- **Workaround:** Using MLB Stats API instead (free, no auth needed)
- Tables `bdl_pitcher_stats` and `bdl_batter_stats` are obsolete

### 2. Auto-Collection Script Stalled
- The original auto-collection bash script had a pgrep timing issue
- **Fix:** Manually restarted with simpler nohup command
- Collection now running correctly

### 3. Missing Fields in mlb_pitcher_stats
- `is_postseason`: Not tracked (defaulting to FALSE)
- `win`: Not tracked (NULL)
- `strikes`: Not tracked (0)
- These are non-critical for K prediction

---

## Timeline

| Time | Event |
|------|-------|
| 11:00 AM | Session started, read handoff |
| 11:30 AM | Discovered data pipeline gap |
| 12:00 PM | Fixed collection script, created table |
| 1:35 PM | Original 2024 collection finished |
| 2:47 PM | Started re-collection with pitcher stats |
| ~3:40 PM | 2025 re-collection expected complete |
| ~4:30 PM | 2024 re-collection expected complete |
| ~5:00 PM | Analytics + ML training can run |

---

## Success Criteria

1. **Collection complete:** ~9,800+ rows in `mlb_pitcher_stats`
2. **Analytics complete:** ~9,800+ rows in `pitcher_game_summary`
3. **Model trained:** Test MAE < 1.92 (beats baseline)
4. **Model saved:** `models/mlb/mlb_pitcher_strikeouts_v1_*.json`

---

## Questions for New Session

If you encounter issues:

1. **Collection not running?** Check `ps aux | grep collect_season`
2. **No data in mlb_pitcher_stats?** Re-run collection manually
3. **Analytics processor fails?** Check that `mlb_pitcher_stats` has data first
4. **ML training crashes?** Check for NULL values in features

---

## Contact/Context

This is part of a larger sports prediction platform:
- NBA predictions: Production (working)
- MLB predictions: Development (this project)
- Target: Pitcher strikeout over/under predictions
- Baseline: Bottom-up formula using batter K rates (MAE 1.92)
