# Line Quality Self-Healing Architecture

**Status:** Implemented
**Created:** 2026-01-23
**Author:** Claude Code

## Problem Statement

When predictions are generated before betting lines are available, they use estimated lines (ESTIMATED_AVG) based on player averages. Later, real betting lines become available from odds_api or bettingpros, but the system had no way to detect this and regenerate predictions with the better data.

### Impact
- Predictions based on estimated lines may have lower accuracy
- Users don't get the benefit of real sportsbook lines
- Grading may be skewed by comparing predictions to lines that weren't available at prediction time

### Example Timeline
```
9:00 AM - Predictions generated with ESTIMATED_AVG (no real lines yet)
10:30 AM - BettingPros scraper runs, real lines now available
12:00 PM - Lines exist but predictions still use old estimated values
```

## Solution Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    Line Quality Self-Heal                        │
│                    Cloud Function (HTTP)                         │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Detect     │ -> │  Deactivate  │ -> │   Trigger    │      │
│  │  Placeholders│    │  Old Preds   │    │ Coordinator  │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
           │                    │                    │
           v                    v                    v
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   BigQuery       │  │   BigQuery       │  │  Coordinator     │
│   Query for      │  │   UPDATE         │  │  /start API      │
│   placeholders   │  │   is_active=F    │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Flow

1. **Detection Phase**
   - Query `player_prop_predictions` for active predictions with:
     - `line_source IN ('ESTIMATED_AVG', 'NEEDS_BOOTSTRAP')` OR
     - `line_source IS NULL` OR
     - `current_points_line = 20.0` (known placeholder value)
   - Join with `odds_api_player_points_props` and `bettingpros_player_points_props`
   - Find predictions where real lines NOW exist

2. **Deactivation Phase**
   - For each affected date, set `is_active = FALSE` on placeholder predictions
   - This allows new predictions to become the active ones
   - Preserves audit trail (old predictions not deleted)

3. **Regeneration Phase**
   - Call coordinator `/start` endpoint for affected dates
   - Coordinator generates new predictions using now-available real lines
   - New predictions inserted with `is_active = TRUE`

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_PLAYERS_FOR_REGENERATION` | 5 | Minimum affected players to trigger regeneration |
| `LOOKBACK_DAYS` | 3 | How many days back to check |
| `MIN_AGE_HOURS` | 2 | Minimum age of predictions to consider (avoid racing) |

### Scheduling

```bash
# Run every 2 hours from 8 AM to 8 PM ET
gcloud scheduler jobs create http line-quality-self-heal-job \
    --schedule "0 8-20/2 * * *" \
    --time-zone "America/New_York" \
    --uri https://[FUNCTION_URL] \
    --http-method POST \
    --location us-west2
```

### Deployment

```bash
# Deploy the function
gcloud functions deploy line-quality-self-heal \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source orchestration/cloud_functions/line_quality_self_heal \
    --entry-point check_line_quality \
    --trigger-http \
    --allow-unauthenticated \
    --memory 512MB \
    --timeout 300s \
    --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK
```

## Key Design Decisions

### 1. Deactivate vs Delete
We **deactivate** old predictions rather than delete them:
- Preserves audit trail
- Allows analysis of placeholder vs real line accuracy
- Supports rollback if needed

### 2. Minimum Threshold
We require at least 5 affected players before regenerating:
- Avoids thrashing for edge cases
- Reduces unnecessary coordinator load
- Single-player issues may be data quality problems

### 3. Age Guard (MIN_AGE_HOURS)
We only consider predictions older than 2 hours:
- Avoids racing with normal prediction flow
- Lines may still be incoming in the normal flow
- Gives time for all scrapers to complete

### 4. Date-Level Regeneration
We regenerate entire dates, not individual players:
- Simpler coordinator interface
- More efficient batch processing
- Ensures consistent line sources within a date

## Monitoring & Alerting

### Metrics Tracked
- `placeholder_count`: Predictions detected with placeholders
- `regenerated`: Dates successfully regenerated
- `skipped`: Dates skipped (below threshold or errors)

### Slack Notifications
Automatic notification sent with:
- Count of affected predictions
- Dates regenerated
- Dates skipped and why

### Audit Log
All actions logged to `nba_orchestration.self_heal_log`:
```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.self_heal_log (
    timestamp TIMESTAMP,
    game_date DATE,
    action STRING,
    details STRING,  -- JSON
    source STRING
)
```

## Testing

### Dry Run Mode
```bash
# Check what would be regenerated without taking action
curl "https://[FUNCTION_URL]?dry_run=true"
```

### Local Testing
```bash
cd orchestration/cloud_functions/line_quality_self_heal
python main.py --dry-run
```

## Related Components

- **Prediction Coordinator**: Handles regeneration requests
- **Player Loader**: Fetches betting lines (odds_api then bettingpros fallback)
- **Missing Prediction Detector**: Detects coverage gaps (different problem)
- **Grading Function**: Grades predictions (uses line_source to filter)

## Operational Status (2026-01-23)

**Last Verified:** 2026-01-23 ~14:00 UTC

The self-heal function is deployed and running correctly:
```json
{
  "status": "no_action_needed",
  "placeholder_count": 0,
  "dates_checked": ["2026-01-22", "2026-01-23"],
  "message": "No placeholder predictions found that have real lines available"
}
```

**Note:** The function correctly detected no placeholders because predictions with ESTIMATED_AVG are working as expected - it's the upstream data (betting lines) that's missing, not a timing issue.

## Future Enhancements

1. **Player-Level Regeneration**: Only regenerate specific affected players
2. **Line Source Preference**: Allow configuration of preferred line source
3. **Staleness Alert**: Alert if same predictions keep needing regeneration
4. **Integration with Data Quality Dashboard**: Surface self-heal metrics
5. **Upstream Data Monitoring**: Alert when betting lines data is missing (not just placeholders)
