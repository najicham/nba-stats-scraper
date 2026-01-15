# Session 58 Handoff: V1.6 Shadow Mode + Line Timing Feature

**Date**: 2026-01-15
**Focus**: V1.4/V1.6 Parallel Deployment + line_minutes_before_game Implementation
**Status**: All implementation complete, ready for production testing

---

## Quick Start for New Chat

```bash
# Read this handoff
cat docs/09-handoff/2026-01-15-SESSION-58-HANDOFF.md

# Test shadow mode runner (dry run)
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --dry-run

# Test pitcher loader
PYTHONPATH=. python predictions/mlb/pitcher_loader.py --date 2025-06-15

# Check V1.6 model
MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print(f'V1.6 loaded: {p.model_metadata[\"model_id\"]}')
"
```

---

## What Was Accomplished (Session 58)

### 1. Shadow Mode Runner for V1.4 vs V1.6
Created `predictions/mlb/shadow_mode_runner.py` that:
- Loads both V1.4 champion and V1.6 challenger models
- Runs predictions in parallel for all pitchers on a date
- Stores comparison results to `mlb_predictions.shadow_mode_predictions`
- Tracks prediction differences, recommendation agreement

**Usage:**
```bash
# Run for today
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py

# Run for specific date
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --date 2025-06-15

# Dry run (no BigQuery writes)
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --dry-run
```

### 2. Line Timing Feature (v3.6)
Implemented `line_minutes_before_game` tracking across the full pipeline:

| Component | Change |
|-----------|--------|
| `oddsa_pitcher_props` | Added `game_start_time`, `minutes_before_tipoff` columns |
| `pitcher_strikeouts` | Added `line_minutes_before_game` column |
| `mlb_pitcher_props_processor.py` | Calculates timing from `commence_time - snapshot_time` |
| `pitcher_loader.py` | NEW: Queries lines with timing metadata |
| `worker.py` | Passes timing through to BigQuery |
| `mlb_prediction_grading_processor.py` | Added `analyze_timing()` and `get_timing_summary()` |

**Timing Buckets:**
- `VERY_EARLY`: >4 hours before game
- `EARLY`: 1-4 hours before game
- `CLOSING`: <1 hour before game

### 3. BigQuery Schema Updates
Applied ALTER TABLE commands:
```sql
-- Raw props table
ALTER TABLE mlb_raw.oddsa_pitcher_props
ADD COLUMN game_start_time TIMESTAMP,
ADD COLUMN minutes_before_tipoff INT64;

-- Predictions table
ALTER TABLE mlb_predictions.pitcher_strikeouts
ADD COLUMN line_minutes_before_game INT64;

-- Created new shadow table
CREATE TABLE mlb_predictions.shadow_mode_predictions (...)
```

---

## Files Created

| File | Purpose |
|------|---------|
| `predictions/mlb/shadow_mode_runner.py` | Run V1.4 + V1.6 in parallel |
| `predictions/mlb/pitcher_loader.py` | Query lines with timing |
| `schemas/bigquery/mlb_predictions/shadow_predictions_tables.sql` | Shadow comparison table |

## Files Modified

| File | Changes |
|------|---------|
| `schemas/bigquery/mlb_raw/oddsa_tables.sql` | Added timing columns |
| `schemas/bigquery/mlb_predictions/strikeout_predictions_tables.sql` | Added line timing |
| `data_processors/raw/mlb/mlb_pitcher_props_processor.py` | Calculate timing |
| `predictions/mlb/worker.py` | Pass timing through |
| `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | Timing analysis |

---

## Background Tasks

### BettingPros Historical Backfill
- **Task ID**: `b77281f`
- **Status**: Running (~66% complete as of session start)
- **Monitor**: `tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output`

---

## Next Session Priorities

### HIGH PRIORITY

#### 1. Run Shadow Mode for 7+ Days
```bash
# Add to daily cron or Cloud Scheduler
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py
```
After 7 days, query performance:
```sql
SELECT * FROM mlb_predictions.shadow_model_comparison
```

#### 2. Grade Shadow Predictions
Create a grading script for shadow predictions table (update `actual_strikeouts`, `v1_4_correct`, `v1_6_correct` columns after games complete).

#### 3. Deploy V1.6 to Production (if shadow mode shows improvement)
```bash
# Update Cloud Run env var
export MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
```

### MEDIUM PRIORITY

#### 4. Line Timing Analysis
After data accumulates, analyze accuracy by timing:
```sql
SELECT
  CASE
    WHEN line_minutes_before_game > 240 THEN 'VERY_EARLY'
    WHEN line_minutes_before_game > 60 THEN 'EARLY'
    WHEN line_minutes_before_game > 0 THEN 'CLOSING'
  END as timing_bucket,
  COUNT(*) as predictions,
  COUNTIF(is_correct) as correct,
  ROUND(COUNTIF(is_correct) * 100.0 / COUNT(*), 1) as accuracy
FROM mlb_predictions.pitcher_strikeouts
WHERE is_correct IS NOT NULL
  AND line_minutes_before_game IS NOT NULL
GROUP BY timing_bucket
```

#### 5. Complete BettingPros Backfill
Let background task complete, then verify data loaded correctly.

### LOWER PRIORITY

#### 6. Opening Line Tracking
Track line when first captured vs closing line for line movement analysis.

#### 7. Ensemble Model
Combine V1.4 + V1.6 predictions for potentially better accuracy.

---

## Key Queries

### Compare V1.4 vs V1.6 (after grading)
```sql
SELECT
  model_version,
  COUNT(*) as predictions,
  COUNTIF(is_correct) as correct,
  ROUND(COUNTIF(is_correct) * 100.0 / COUNT(*), 1) as accuracy
FROM mlb_predictions.shadow_mode_predictions
WHERE actual_strikeouts IS NOT NULL
GROUP BY model_version
```

### Daily Shadow Comparison
```sql
SELECT * FROM mlb_predictions.shadow_daily_comparison
```

### Line Timing Distribution
```sql
SELECT
  CASE
    WHEN minutes_before_tipoff > 240 THEN 'VERY_EARLY'
    WHEN minutes_before_tipoff > 60 THEN 'EARLY'
    WHEN minutes_before_tipoff > 0 THEN 'CLOSING'
  END as bucket,
  COUNT(*) as count,
  AVG(minutes_before_tipoff) as avg_minutes
FROM mlb_raw.oddsa_pitcher_props
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND minutes_before_tipoff IS NOT NULL
GROUP BY bucket
```

---

## Architecture Reference

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   V1.6 SHADOW MODE DATA FLOW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐                                                           │
│  │ shadow_mode_ │                                                           │
│  │  runner.py   │                                                           │
│  └──────┬───────┘                                                           │
│         │                                                                   │
│         ├──────────────────┬──────────────────┐                             │
│         ▼                  ▼                  ▼                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                    │
│  │ V1.4 Champion│   │ V1.6 Chllngr │   │  BigQuery    │                    │
│  │  Predictor   │   │  Predictor   │   │   Query      │                    │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                    │
│         │                  │                  │                             │
│         └────────┬─────────┘                  │                             │
│                  │                            │                             │
│                  ▼                            │                             │
│         ┌──────────────────┐                  │                             │
│         │  shadow_mode_    │◀─────────────────┘                             │
│         │  predictions     │                                                │
│         │  (comparison)    │                                                │
│         └──────────────────┘                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                   LINE TIMING DATA FLOW (v3.6)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Odds API ───┐                                                              │
│              │ commence_time, snapshot_time                                 │
│              ▼                                                              │
│  ┌────────────────────────┐                                                 │
│  │ mlb_pitcher_props_     │                                                 │
│  │ processor.py           │                                                 │
│  │ - calc minutes_before  │                                                 │
│  └──────────┬─────────────┘                                                 │
│             │                                                               │
│             ▼                                                               │
│  ┌────────────────────────┐                                                 │
│  │ oddsa_pitcher_props    │                                                 │
│  │ + game_start_time      │                                                 │
│  │ + minutes_before_tipoff│                                                 │
│  └──────────┬─────────────┘                                                 │
│             │                                                               │
│             ▼                                                               │
│  ┌────────────────────────┐                                                 │
│  │ pitcher_loader.py      │                                                 │
│  │ - queries with timing  │                                                 │
│  └──────────┬─────────────┘                                                 │
│             │                                                               │
│             ▼                                                               │
│  ┌────────────────────────┐     ┌────────────────────────┐                 │
│  │ worker.py              │────▶│ pitcher_strikeouts     │                 │
│  │ - passes timing thru   │     │ + line_minutes_before  │                 │
│  └────────────────────────┘     └──────────┬─────────────┘                 │
│                                            │                                │
│                                            ▼                                │
│                                 ┌────────────────────────┐                 │
│                                 │ grading_processor.py   │                 │
│                                 │ - analyze_timing()     │                 │
│                                 │ - get_timing_summary() │                 │
│                                 └────────────────────────┘                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Model Versions

| Model | Path | Features | Status |
|-------|------|----------|--------|
| V1.4 Champion | `mlb_pitcher_strikeouts_v1_4features_20260114_142456.json` | 25 | Production |
| V1.6 Challenger | `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json` | 35 | Shadow testing |

---

## Session 58 Summary

1. **Created shadow mode runner** for V1.4 vs V1.6 parallel comparison
2. **Implemented line timing** across full pipeline (scraper → grading)
3. **Applied schema updates** to BigQuery tables
4. **Created pitcher loader** for timing-aware line queries
5. **Added timing analysis** to grading processor

**Key Result**: Infrastructure ready to compare V1.4 vs V1.6 performance and analyze prediction accuracy by line timing.

---

**Session 58 Handoff Complete**
