# Multi-Snapshot Historical Odds Backfill Design

**Created**: 2026-01-23
**Status**: Design Draft

## Problem Statement

When backfilling historical odds data, we currently capture only one snapshot per game date (typically 18:00:00 UTC). This creates several issues:

1. **Games at different times**: A 7pm EST game captured at 6pm UTC is ~13 hours before tipoff, while a 10:30pm EST game at that same snapshot is ~18 hours before tipoff
2. **No line movement**: We can't see how lines changed throughout the day
3. **Stale lines**: Some predictions may use lines that are many hours old
4. **Missing closing lines**: The "closing line" (final line before game starts) is often the most accurate market estimate

## Current System Architecture

### How Lines Are Stored

The `nba_raw.odds_api_player_points_props` table already supports multiple snapshots:

| Column | Description |
|--------|-------------|
| `snapshot_timestamp` | When the line was captured (e.g., 2026-01-23 14:08:15) |
| `snapshot_tag` | Human-readable tag (e.g., "snap-1408") |
| `minutes_before_tipoff` | How many minutes before game start |
| `game_start_time` | When the actual game starts |

### How Predictions Select Lines

From `predictions/coordinator/player_loader.py`:

```sql
SELECT points_line, bookmaker, minutes_before_tipoff
FROM odds_api_player_points_props
WHERE player_lookup = @player_lookup
  AND game_date = @game_date
ORDER BY snapshot_timestamp DESC
LIMIT 1
```

**Key insight**: The system uses the **most recent snapshot** (`snapshot_timestamp DESC`).

### What's Tracked

Predictions already store `line_minutes_before_game` which tells us how fresh the line was.

## Proposed Multi-Snapshot Strategy

### Option A: Fixed Time Slots (Recommended for Historical Backfill)

Capture snapshots at specific times relative to the typical NBA schedule:

| Snapshot | UTC Time | Purpose |
|----------|----------|---------|
| Morning | 14:00:00Z (9am EST) | Initial lines, early movers |
| Afternoon | 18:00:00Z (1pm EST) | Mid-day lines |
| Pre-Game 1 | 22:00:00Z (5pm EST) | Before early games (7pm EST) |
| Pre-Game 2 | 01:00:00Z (8pm EST) | Before late games |
| Pre-Game 3 | 03:00:00Z (10pm EST) | Near-closing for early games |

**Pros**: Simple to implement, predictable API costs
**Cons**: Fixed times don't adapt to actual game schedules

### Option B: Game-Relative Snapshots (Ideal but Complex)

For each game, capture:
- 6 hours before tipoff
- 2 hours before tipoff
- 30 minutes before tipoff (closing line)

**Pros**: Gets lines at consistent freshness levels
**Cons**: Requires per-game scheduling, more API calls

### Option C: Hybrid Approach

1. Use fixed time slots for bulk historical backfill
2. For current/future games, use game-relative scheduling

## Implementation Plan

### Phase 1: Historical Backfill Enhancement

Modify `scripts/backfill_historical_props.py` to accept multiple snapshots:

```python
# New CLI arguments
parser.add_argument('--snapshots',
    default='18:00:00Z',
    help='Comma-separated snapshot times (e.g., "14:00:00Z,18:00:00Z,22:00:00Z")')
```

### Phase 2: Freshness Tracking for Grading

Add columns to predictions table or create a line freshness summary:

```sql
-- Example: How fresh were our lines?
SELECT
    game_date,
    AVG(line_minutes_before_game) as avg_minutes_before,
    MIN(line_minutes_before_game) as min_minutes_before,
    MAX(line_minutes_before_game) as max_minutes_before,
    COUNT(CASE WHEN line_minutes_before_game < 60 THEN 1 END) as lines_within_1hr
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-01'
GROUP BY game_date
ORDER BY game_date
```

### Phase 3: Line Selection Strategy

Options for how predictions should select lines:

1. **Most Recent** (current): Use `snapshot_timestamp DESC`
2. **Freshness Threshold**: Only use lines <N hours before game
3. **Closing Line Preference**: Prefer lines closest to game time

## API Cost Considerations

Odds API charges per request. Multiple snapshots increase costs:

| Strategy | Snapshots/Day | Games/Day | API Calls | Monthly Cost* |
|----------|---------------|-----------|-----------|--------------|
| Current (1x) | 1 | ~12 | ~12 | ~$X |
| Option A (5x) | 5 | ~12 | ~60 | ~$5X |
| Option B (3x per game) | 3 | ~12 | ~36 | ~$3X |

*Actual costs depend on Odds API pricing tier

## Questions to Resolve

1. **Which line should predictions use?**
   - Most recent snapshot?
   - Snapshot closest to N hours before game?
   - Weighted average of snapshots?

2. **How do we handle missing snapshots?**
   - Some games may not have lines at certain times
   - Should we fall back to earlier snapshot?

3. **Should line freshness affect prediction confidence?**
   - A line 30 min before game is more reliable than 12 hours before
   - Could weight predictions by line freshness

4. **Storage considerations**
   - 5x more data in `odds_api_player_points_props`
   - Consider partitioning/clustering strategy

## Current State (2026-01-23)

### Data in GCS (NOT loaded to BigQuery yet)

| Date | snap-1800 (Opening) | snap-0200 (Closing) |
|------|---------------------|---------------------|
| Jan 19 | 11 files | 5 files |
| Jan 20 | 7 files | 11 files |
| Jan 21 | 15 files | 9 files |
| Jan 22 | 8 files | 14 files |

**Location**: `gs://nba-scraped-data/odds-api/player-props-history/{date}/`

**Note**: Closing snapshot (02:00 UTC) has fewer files for some dates because games had already finished.

### What's in BigQuery

Only snap-1800 data is loaded. The snap-0200 data is in GCS awaiting schema decision.

### Schema Consideration

Before loading snap-0200 to BigQuery, consider:

1. **Current queries use `ORDER BY snapshot_timestamp DESC LIMIT 1`**
   - This will automatically pick the 02:00 snapshot (most recent)
   - Is that what we want? Or do we want explicit "opening" vs "closing" columns?

2. **Options**:
   - **Option A**: Load as-is, queries naturally get most recent
   - **Option B**: Add `snapshot_type` column ('opening', 'closing', 'intraday')
   - **Option C**: Create separate view/table for closing lines

3. **Grading implications**:
   - Need to decide if grading should use opening line, closing line, or both
   - Opening line = what we predicted against
   - Closing line = market's final estimate

## Recommended Next Steps

1. **Decide schema approach** for multi-snapshot data
2. **Short-term**: Add freshness analysis to grading reports
3. **Medium-term**: Implement line selection strategy based on freshness
4. **Long-term**: Consider game-relative snapshot scheduling for live scraping

## Related Files

- `scripts/backfill_historical_props.py` - Historical scraper
- `scrapers/oddsapi/oddsa_player_props_his.py` - Historical props scraper
- `predictions/coordinator/player_loader.py` - Line selection logic
- `predictions/coordinator/shared/utils/odds_player_props_preference.py` - Line utilities
