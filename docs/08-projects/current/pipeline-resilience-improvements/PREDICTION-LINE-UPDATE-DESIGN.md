# Prediction Line Update Design

**Goal**: When predictions run without lines (NO_PROP_LINE), automatically update them when lines become available.

## Current Behavior

1. Predictions run at scheduled time
2. If no line found → `line_source = 'NO_PROP_LINE'`, `has_prop_line = false`
3. Prediction still generated (predicted_points calculated)
4. But recommendation is incomplete (no line to compare against)

## Proposed Behavior

1. Predictions run as normal
2. If no line found → mark as `NO_PROP_LINE` (same as now)
3. **NEW**: When batch processor loads lines, check for predictions needing updates
4. Update predictions with newly available lines

## Design Options

### Option A: Full Re-run (Complex)

```
Batch Processor completes
    ↓
Publish "lines-ready" event
    ↓
Prediction coordinator receives event
    ↓
Query predictions with NO_PROP_LINE for that date
    ↓
Re-run full prediction pipeline for those players
```

**Pros**: Most accurate, recalculates everything
**Cons**: Complex, expensive, may create duplicate predictions

### Option B: Line Update Only (Recommended)

```
Batch Processor completes
    ↓
Query predictions with NO_PROP_LINE for that date
    ↓
For each prediction, look up the new line
    ↓
UPDATE prediction SET:
  - current_points_line = new_line
  - line_margin = predicted_points - new_line
  - has_prop_line = true
  - line_source = 'ACTUAL_PROP'
  - recommendation = CASE WHEN line_margin > threshold THEN 'OVER' ELSE 'UNDER' END
```

**Pros**: Simple, fast, no duplicate predictions
**Cons**: Doesn't re-run model (but prediction itself doesn't depend on line)

### Option C: Separate "Line Fill" Table

Create a `prediction_line_updates` table that tracks:
- Original prediction_id
- Original line_source (NO_PROP_LINE)
- Updated line when available
- Update timestamp

**Pros**: Audit trail, doesn't modify original predictions
**Cons**: More tables, queries need to join

## Recommendation: Option B

The predicted_points value doesn't depend on the betting line - it's based on player stats, matchup, etc. The line is only used for:
1. Setting `line_margin` (predicted - line)
2. Determining `recommendation` (OVER/UNDER)

So we can safely UPDATE the prediction with the new line without re-running the model.

## Implementation

### Step 1: Add update logic to batch processor

```python
# In OddsApiPropsBatchProcessor.save_data() or post_process()

def _update_predictions_with_new_lines(self, game_date: str):
    """Update NO_PROP_LINE predictions with newly loaded lines."""

    query = """
    UPDATE `nba_predictions.player_prop_predictions` pred
    SET
        current_points_line = lines.points_line,
        line_margin = pred.predicted_points - lines.points_line,
        has_prop_line = TRUE,
        line_source = 'ACTUAL_PROP',
        line_source_api = 'ODDS_API',
        sportsbook = UPPER(lines.bookmaker),
        recommendation = CASE
            WHEN pred.predicted_points - lines.points_line > 1.5 THEN 'OVER'
            WHEN lines.points_line - pred.predicted_points > 1.5 THEN 'UNDER'
            ELSE 'HOLD'
        END,
        updated_at = CURRENT_TIMESTAMP()
    FROM (
        SELECT player_lookup, game_date, points_line, bookmaker,
               ROW_NUMBER() OVER (
                   PARTITION BY player_lookup
                   ORDER BY
                       CASE bookmaker WHEN 'draftkings' THEN 1 WHEN 'fanduel' THEN 2 ELSE 99 END,
                       snapshot_timestamp DESC
               ) as rn
        FROM `nba_raw.odds_api_player_points_props`
        WHERE game_date = @game_date
    ) lines
    WHERE pred.game_date = @game_date
      AND pred.is_active = TRUE
      AND pred.line_source = 'NO_PROP_LINE'
      AND pred.player_lookup = lines.player_lookup
      AND lines.rn = 1
    """
```

### Step 2: Track updates

Add logging so we know how many predictions were updated:

```python
logger.info(f"Updated {rows_affected} predictions with new lines for {game_date}")
```

### Step 3: Consider timing

- Only run this update for current/future game dates
- Don't update historical predictions (grading needs original state)

## Questions

1. Should we update `updated_at` timestamp? (Yes - for tracking)
2. Should we keep original `line_source` somewhere? (Maybe add `original_line_source` column)
3. What about predictions that already ran with a line - should we update if line changes? (Probably not - use original line for grading)

## Files to Modify

1. `data_processors/raw/oddsapi/oddsapi_batch_processor.py` - Add update logic
2. `nba_predictions.player_prop_predictions` schema - Maybe add `line_updated_at` column
