# Sonnet Fix Task: Prediction Timing Race Condition

## Objective
Ensure predictions are generated even when betting lines arrive after Phase 3 processing.

## Problem
On Jan 27:
- Phase 3 `upcoming_player_game_context` ran at **3:30 PM**
- Betting lines scraped at **4:46 PM** (76 minutes later)
- Result: All 236 players marked `has_prop_line = FALSE`
- Prediction coordinator found 0 eligible players → 0 predictions

## Root Cause
The `upcoming_player_game_context` processor sets `has_prop_line` based on betting lines available AT PROCESSING TIME. If betting lines arrive later, the flag is never updated.

## Solution Design

### Option A: Re-trigger Phase 3 When Betting Lines Arrive (RECOMMENDED)

Add a Pub/Sub trigger from the betting line scraper to re-process `upcoming_player_game_context`.

**Files to modify**:

1. **Betting line scraper** (to publish completion message):
   - File: `scrapers/odds_api/player_props_scraper.py` (or similar)
   - Add Pub/Sub publish after scrape completes

2. **Analytics service** (to handle new trigger):
   - File: `data_processors/analytics/main_analytics_service.py`
   - Add `odds_api_player_points_props` to ANALYTICS_TRIGGERS

**Changes**:

In `main_analytics_service.py`, add to ANALYTICS_TRIGGERS:
```python
ANALYTICS_TRIGGERS = {
    # ... existing triggers ...

    # NEW: Betting lines trigger context refresh
    'odds_api_player_points_props': [UpcomingPlayerGameContextProcessor],
}
```

In the betting line scraper, ensure it publishes to `nba-phase2-raw-complete`:
```python
# After successful scrape:
from shared.pubsub import publish_completion
publish_completion(
    topic='nba-phase2-raw-complete',
    output_table='odds_api_player_points_props',
    game_date=target_date,
    record_count=len(records)
)
```

### Option B: Query Betting Lines at Prediction Time

Instead of relying on `has_prop_line` flag in Phase 3, query betting lines directly in prediction coordinator.

**File**: `prediction_coordinator/player_loader.py` (or equivalent)

**Change**: Modify the player query to JOIN to raw betting lines:
```sql
SELECT
    ctx.*,
    CASE WHEN props.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
FROM `nba_analytics.upcoming_player_game_context` ctx
LEFT JOIN (
    SELECT DISTINCT player_lookup, game_date
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date = @target_date
) props ON ctx.player_lookup = props.player_lookup AND ctx.game_date = props.game_date
WHERE ctx.game_date = @target_date
  AND (ctx.avg_minutes_per_game_last_7 >= @min_minutes OR props.player_lookup IS NOT NULL)
```

### Option C: Add Betting Line Refresh Job

Create a separate Cloud Scheduler job that refreshes `has_prop_line` after betting lines are expected.

**New job**: `refresh-prop-line-flags`
- Schedule: 5:30 PM PT (after betting lines typically scraped)
- Action: Query betting lines, UPDATE `has_prop_line` in `upcoming_player_game_context`

```sql
UPDATE `nba_analytics.upcoming_player_game_context` ctx
SET has_prop_line = TRUE
WHERE game_date = CURRENT_DATE('America/Los_Angeles')
  AND player_lookup IN (
    SELECT DISTINCT player_lookup
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date = CURRENT_DATE('America/Los_Angeles')
  )
```

## Recommended Approach

**Option A** (re-trigger) is cleanest:
- Uses existing infrastructure (Pub/Sub, analytics service)
- No schema changes
- Automatic - no manual timing

**Option B** is a good backup if Option A is complex to implement.

## Implementation Steps

### For Option A:

1. Verify betting line scraper publishes to Pub/Sub:
```bash
grep -r "publish" scrapers/odds_api/
```

2. If not, add publish call after successful scrape:
```python
# In the scraper's main() or save() method:
from shared.pubsub.publisher import publish_phase2_complete

publish_phase2_complete(
    output_table='odds_api_player_points_props',
    target_date=scrape_date,
    record_count=records_saved,
    processor_name='odds_api_player_props_scraper'
)
```

3. Add trigger mapping in `main_analytics_service.py`:
```python
# Find ANALYTICS_TRIGGERS dict and add:
'odds_api_player_points_props': [UpcomingPlayerGameContextProcessor],
```

4. Deploy updated analytics service

5. Verify by checking:
```bash
# After betting lines scraped, check if context was re-processed:
bq query "SELECT MAX(processed_at), COUNTIF(has_prop_line) FROM upcoming_player_game_context WHERE game_date = CURRENT_DATE()"
```

## Testing

1. Manually trigger betting line scrape
2. Check if `upcoming_player_game_context` is re-processed
3. Verify `has_prop_line = TRUE` for players with lines
4. Trigger prediction coordinator
5. Verify predictions are generated

## Validation Query
```sql
-- Before fix (shows the problem):
SELECT
  game_date,
  COUNT(*) as total_players,
  COUNTIF(has_prop_line = TRUE) as with_prop_lines,
  MAX(processed_at) as last_updated
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= CURRENT_DATE('America/Los_Angeles')
GROUP BY game_date

-- After fix: with_prop_lines should be > 0 after betting lines scraped
```

## Monitoring Alert
Add alert for when `has_prop_line = FALSE` for all players on a game day after 5 PM:
```sql
-- Alert condition:
SELECT COUNT(*) = 0
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE('America/Los_Angeles')
  AND has_prop_line = TRUE
  AND CURRENT_TIME('America/Los_Angeles') > TIME(17, 0, 0)
```
