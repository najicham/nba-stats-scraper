# Session 114 Handoff - Phase 5B v3 Schema Enhancements

**Date:** 2025-12-10
**Focus:** Enhanced prediction_accuracy schema with team context, minutes, and calibration fields

---

## Executive Summary

This session implemented Phase 5B v3 schema enhancements based on Claude Web design review feedback. The `prediction_accuracy` table now includes:

- **Team context** (`team_abbr`, `opponent_team_abbr`) for opponent analysis
- **Minutes context** (`minutes_played`) to explain prediction failures
- **Confidence calibration** (`confidence_decile`) for calibration curves

---

## What Was Done

### 1. Schema Changes Applied

Added 4 new columns to `nba_predictions.prediction_accuracy`:

```sql
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN team_abbr STRING,               -- Player's team (e.g., 'LAL')
ADD COLUMN opponent_team_abbr STRING,      -- Opponent team (e.g., 'BOS')
ADD COLUMN confidence_decile INT64,        -- 1-10 bucket for calibration
ADD COLUMN minutes_played NUMERIC(5, 1);   -- Actual minutes from box score
```

### 2. Processor Updates

Updated `prediction_accuracy_processor.py` to:
- Fetch team_abbr, opponent_team_abbr, minutes_played from player_game_summary
- Compute confidence_decile from confidence_score (buckets: 0.0-0.09 → 1, ..., 0.9-1.0 → 10)
- Store new fields when grading predictions

Key changes:
- `get_actuals_for_date()` now returns full player context dict, not just points
- `grade_prediction()` extracts new fields from actual_data
- `compute_confidence_decile()` computes calibration bucket

### 3. Schema File Updated

Updated `schemas/bigquery/nba_predictions/prediction_accuracy.sql` to v3:
- Added team context section
- Added minutes_played in actual result section
- Added confidence_decile in prediction snapshot section

### 4. Backfill Status

- **Backfill running:** 62 dates from Nov 2021 - Nov 2025
- **Expected records:** ~47,395
- **New fields:** Will be populated with team context and calibration data

---

## Current prediction_accuracy Schema (v3)

| Column | Type | Description |
|--------|------|-------------|
| player_lookup | STRING | Primary key |
| game_id | STRING | Primary key |
| game_date | DATE | Primary key, partition key |
| system_id | STRING | Primary key, cluster key |
| **team_abbr** | STRING | **NEW:** Player's team abbreviation |
| **opponent_team_abbr** | STRING | **NEW:** Opponent team abbreviation |
| predicted_points | NUMERIC(5,1) | Prediction value |
| confidence_score | NUMERIC(4,3) | Confidence 0.0-1.0 |
| **confidence_decile** | INT64 | **NEW:** Calibration bucket 1-10 |
| recommendation | STRING | OVER/UNDER/PASS |
| line_value | NUMERIC(5,1) | Betting line |
| referee_adjustment | NUMERIC(5,1) | Feature input |
| pace_adjustment | NUMERIC(5,1) | Feature input |
| similarity_sample_size | INT64 | Feature input |
| actual_points | INT64 | Actual result |
| **minutes_played** | NUMERIC(5,1) | **NEW:** Actual minutes played |
| absolute_error | NUMERIC(5,1) | MAE component |
| signed_error | NUMERIC(5,1) | Bias direction |
| prediction_correct | BOOL | Win/loss |
| predicted_margin | NUMERIC(5,1) | pred - line |
| actual_margin | NUMERIC(5,1) | actual - line |
| within_3_points | BOOL | Threshold check |
| within_5_points | BOOL | Threshold check |
| model_version | STRING | Version tracking |
| graded_at | TIMESTAMP | Processing timestamp |

---

## Files Modified

### Code Changes

1. **`schemas/bigquery/nba_predictions/prediction_accuracy.sql`**
   - Updated to v3 with new fields documented

2. **`data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`**
   - `get_actuals_for_date()` returns full player context
   - `compute_confidence_decile()` new method
   - `grade_prediction()` populates new fields

---

## Verification Commands

After backfill completes, verify with:

```sql
-- Check new fields are populated
SELECT
  game_date,
  COUNT(*) as records,
  COUNT(team_abbr) as with_team,
  COUNT(minutes_played) as with_minutes,
  COUNT(confidence_decile) as with_decile
FROM nba_predictions.prediction_accuracy
GROUP BY 1
ORDER BY 1
LIMIT 10;

-- Sample team context
SELECT
  player_lookup,
  team_abbr,
  opponent_team_abbr,
  minutes_played,
  confidence_decile,
  predicted_points,
  actual_points,
  absolute_error
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2021-11-10'
LIMIT 10;

-- Confidence calibration analysis
SELECT
  confidence_decile,
  COUNT(*) as predictions,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_pct,
  ROUND(AVG(absolute_error), 2) as avg_mae
FROM nba_predictions.prediction_accuracy
WHERE confidence_decile IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Performance by opponent
SELECT
  opponent_team_abbr,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_pct
FROM nba_predictions.prediction_accuracy
WHERE opponent_team_abbr IS NOT NULL
GROUP BY 1
ORDER BY avg_mae
LIMIT 10;
```

---

## Known Limitations

### minutes_played Field

The `minutes_played` field is NULL for early dates (Nov 2021 - early 2022) because the source `player_game_summary` table does not have this data populated for those dates. This is a data gap in the analytics layer, not a bug in the grading processor.

```sql
-- Check which dates have minutes data
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(*) as records,
  COUNT(minutes_played) as with_minutes
FROM nba_analytics.player_game_summary
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 20;
```

The processor correctly passes through NULL values when the source data is missing.

---

## Phase 6 Impact

The new fields enable richer Phase 6 aggregations:

1. **Team context:**
   - Performance vs elite defenses
   - Home/away split analysis
   - Division matchup analysis

2. **Minutes context:**
   - Identify predictions that failed due to reduced minutes
   - Filter out DNPs from accuracy calculations

3. **Confidence calibration:**
   - Build calibration curves by decile
   - Validate confidence scores are well-calibrated
   - Create reliability diagrams

---

## Claude Web Design Review Decisions

Based on Claude Web feedback, these decisions were made:

### Implemented Now
- Team context (team_abbr, opponent_team_abbr)
- Minutes context (minutes_played)
- Confidence calibration (confidence_decile)

### Deferred for Later
- System agreement score (requires Phase 5A changes)
- Game context flags (BLOWOUT, GARBAGE_TIME)
- Player context flags (FOUL_TROUBLE, MINUTES_RESTRICTED)
- Bias tracking table (query on-demand instead)

### Schema Consolidation
- **Confirmed:** `prediction_results` table does NOT exist
- **Decision:** Keep `prediction_accuracy` as single source of truth
- **Future:** Create VIEW for frontend if needed

---

## Next Steps

1. **Verify backfill completion:** Check all 62 dates have new fields populated
2. **Create prediction_results VIEW:** Optional frontend view if needed
3. **Continue Phase 6:** Use enriched data for system_daily_performance aggregations
4. **Implement deferred features:** System agreement, context flags when ready

---

## Backfill Command Reference

```bash
# Re-run grading backfill (if needed)
rm -f /tmp/backfill_checkpoints/grading_backfill_2021-11-01_2025-11-30.json
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-01 --end-date 2025-11-30 --skip-preflight
```

---

## Related Documents

- `docs/09-handoff/2025-12-10-SESSION112-GRADING-PROCESSOR-IMPLEMENTED.md` - Original grading implementation
- `docs/09-handoff/2025-12-10-SESSION113-PHASE6-PUBLISHING-HANDOFF.md` - Phase 6 design handoff
- `docs/archive/2025-12/prompts/claude-web-phase6-design-review.md` - Design review prompt

---

**End of Handoff**
