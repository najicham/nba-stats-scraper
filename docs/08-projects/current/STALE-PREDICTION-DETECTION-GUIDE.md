# Stale Prediction Detection - Implementation Guide

**Status:** ✅ IMPLEMENTED (2026-01-25)
**File:** `predictions/coordinator/player_loader.py` (line 1210)
**Feature:** Phase 6 real-time prediction regeneration

---

## Overview

The stale prediction detection feature identifies players whose predictions are based on outdated betting lines. When betting markets move significantly (e.g., line changes by 1+ points), the system can detect this and trigger prediction regeneration.

## Problem Solved

Before this feature, predictions could become stale when:
- Injury news breaks (line moves from 25.5 to 22.5)
- Starting lineup changes (bench player's line jumps 3-4 points)
- Market adjusts odds (overnight line movement)

Users would see predictions based on old lines, potentially misleading them.

## Implementation

### Method Signature

```python
def get_players_with_stale_predictions(
    self,
    game_date: date,
    line_change_threshold: float = 1.0
) -> List[str]:
```

### How It Works

1. **Query Current Lines:** Gets latest betting lines from `bettingpros_player_points_props`
2. **Query Prediction Lines:** Gets lines used when predictions were made from `player_prop_predictions`
3. **Compare:** Calculates `ABS(current_line - prediction_line)` for each player
4. **Filter:** Returns players where line change >= threshold
5. **Deduplicate:** Uses `QUALIFY ROW_NUMBER()` for efficient deduplication

### SQL Query

```sql
WITH current_lines AS (
    -- Get most recent betting line for each player
    SELECT
        player_lookup,
        points_line as current_line,
        created_at
    FROM `nba_raw.bettingpros_player_points_props`
    WHERE game_date = @game_date
      AND bet_side = 'over'
      AND is_active = TRUE
      AND points_line IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY created_at DESC
    ) = 1
),
prediction_lines AS (
    -- Get lines used in predictions (deduplicated by player)
    SELECT
        player_lookup,
        current_points_line as prediction_line,
        created_at
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
      AND current_points_line IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY created_at DESC
    ) = 1
)
SELECT DISTINCT
    p.player_lookup,
    p.prediction_line,
    c.current_line,
    ABS(c.current_line - p.prediction_line) as line_change
FROM prediction_lines p
JOIN current_lines c
    ON p.player_lookup = c.player_lookup
WHERE ABS(c.current_line - p.prediction_line) >= @threshold
ORDER BY line_change DESC
```

---

## Usage Examples

### Example 1: Basic Usage

```python
from predictions.coordinator.player_loader import PlayerLoader
from datetime import date

# Initialize loader
loader = PlayerLoader('nba-props-platform')

# Get stale predictions for today
stale_players = loader.get_players_with_stale_predictions(
    game_date=date(2026, 1, 24),
    line_change_threshold=1.0
)

print(f"Found {len(stale_players)} stale predictions")
print(f"Players: {stale_players}")

# Output:
# Found 6 stale predictions
# Players: ['klaythompson', 'tyresemaxey', 'nazreid', 'kellyoubrejr', 'najimarshall', 'vjedgecombe']
```

### Example 2: Integration with Coordinator

```python
# In predictions/coordinator/coordinator.py

def start_predictions(game_date: date):
    """Start prediction generation with stale detection"""

    # Check for stale predictions first
    loader = get_player_loader()
    stale_players = loader.get_players_with_stale_predictions(
        game_date=game_date,
        line_change_threshold=1.0
    )

    if stale_players:
        logger.info(f"🔄 Found {len(stale_players)} stale predictions - regenerating")
        # Create prediction requests only for stale players
        for player_lookup in stale_players:
            publish_prediction_request({
                'player_lookup': player_lookup,
                'game_date': game_date.isoformat(),
                'reason': 'stale_line'
            })

    # Then proceed with normal prediction generation
    # ...
```

### Example 3: Custom Threshold for Breaking News

```python
# Use lower threshold (0.5) for breaking injury news
# to catch even small line movements that indicate market reaction

stale_players = loader.get_players_with_stale_predictions(
    game_date=today,
    line_change_threshold=0.5  # More sensitive
)

# Use higher threshold (2.0) for routine checks
# to avoid over-regeneration from normal market noise

stale_players = loader.get_players_with_stale_predictions(
    game_date=today,
    line_change_threshold=2.0  # Less sensitive
)
```

### Example 4: Monitoring with Debug Logs

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# This will log details of each stale prediction:
# DEBUG:   klaythompson: prediction_line=11.5, current_line=12.5, change=1.0
# DEBUG:   tyresemaxey: prediction_line=26.5, current_line=27.5, change=1.0

stale_players = loader.get_players_with_stale_predictions(
    game_date=today,
    line_change_threshold=1.0
)
```

---

## Test Results (2026-01-24)

Tested on real production data:

| Threshold | Stale Players | Notes |
|-----------|---------------|-------|
| 0.5 points | 6 | Catches all movements >= 0.5 |
| 1.0 points | 6 | Standard threshold (recommended) |
| 2.0 points | 0 | Only major line movements |

### Detected Stale Predictions (Jan 24, 2026)

| Player | Prediction Line | Current Line | Change |
|--------|----------------|--------------|--------|
| Kelly Oubre Jr. | 12.5 | 13.5 | +1.0 |
| Klay Thompson | 11.5 | 12.5 | +1.0 |
| Naji Marshall | 17.5 | 16.5 | -1.0 |
| Naz Reid | 14.5 | 15.5 | +1.0 |
| Tyrese Maxey | 26.5 | 27.5 | +1.0 |
| VJ Edgecombe | 12.5 | 13.5 | +1.0 |

---

## Performance

- **Query Time:** ~1-2 seconds for full day
- **Scalability:** Efficient with `QUALIFY` (no separate deduplication step)
- **Resource Usage:** Standard BigQuery query (minimal cost)

---

## Recommended Integration Points

### 1. Pre-Prediction Check (Recommended)

Before generating predictions, check for stale ones:

```python
# In coordinator /start endpoint
stale = loader.get_players_with_stale_predictions(game_date)
if stale:
    regenerate_predictions(stale)
```

### 2. Scheduled Monitoring

Run every 30-60 minutes during game day:

```python
# Cloud Scheduler job: 0 */1 * * * (hourly)
def check_stale_predictions():
    loader = PlayerLoader('nba-props-platform')
    stale = loader.get_players_with_stale_predictions(
        game_date=date.today(),
        line_change_threshold=1.0
    )
    if stale:
        trigger_regeneration(stale)
```

### 3. Post-News Alert

After breaking news (injury, lineup change):

```python
# Triggered by external alert system
def handle_player_news(player_lookup: str, game_date: date):
    # Check if this player's line changed
    stale = loader.get_players_with_stale_predictions(
        game_date=game_date,
        line_change_threshold=0.5  # Lower threshold for news
    )
    if player_lookup in stale:
        regenerate_prediction(player_lookup, game_date)
```

---

## Monitoring

### Key Metrics to Track

1. **Stale Detection Rate:** How many predictions become stale per day
2. **Line Change Distribution:** Track threshold effectiveness
3. **Regeneration Success:** Ensure stale predictions are actually regenerated

### Example Monitoring Query

```sql
-- Daily stale prediction count
SELECT
    game_date,
    COUNT(*) as stale_count,
    AVG(line_change) as avg_line_change,
    MAX(line_change) as max_line_change
FROM (
    -- Same query as implementation
    ...
)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30
```

---

## Configuration

### Environment Variables (Future)

```bash
# Optional: Override default threshold
STALE_PREDICTION_THRESHOLD=1.0

# Optional: Enable auto-regeneration
STALE_PREDICTION_AUTO_REGEN=true
```

### Threshold Selection Guide

| Threshold | Use Case | Expected Volume |
|-----------|----------|-----------------|
| 0.5 points | Breaking news, high sensitivity | 10-20 players/day |
| 1.0 points | Standard production (recommended) | 5-10 players/day |
| 1.5 points | Conservative, major moves only | 2-5 players/day |
| 2.0 points | Rare events, injury replacements | 0-2 players/day |

---

## Limitations

1. **Only detects line changes:** Doesn't detect other staleness factors (injury updates without line change)
2. **Requires predictions exist:** Can't detect stale if no prediction was made yet
3. **Single sportsbook:** Currently uses bettingpros consensus, not per-sportsbook detection
4. **No time component:** Doesn't factor in how long ago prediction was made

---

## Future Enhancements

### Phase 6.1: Per-Sportsbook Detection

```python
# Detect stale predictions per sportsbook
stale = loader.get_players_with_stale_predictions_by_book(
    game_date=today,
    sportsbook='draftkings',
    threshold=1.0
)
```

### Phase 6.2: Time-Based Staleness

```python
# Consider both line change AND age
stale = loader.get_players_with_stale_predictions(
    game_date=today,
    line_change_threshold=1.0,
    max_age_minutes=120  # Also flag predictions > 2 hours old
)
```

### Phase 6.3: Injury-Aware Detection

```python
# Factor in injury status changes
stale = loader.get_players_with_stale_predictions(
    game_date=today,
    include_injury_changes=True  # Flag if injury status changed
)
```

---

## Troubleshooting

### No Stale Predictions Found (Expected 0)

**Cause:** Lines haven't moved, or predictions don't have line data

**Check:**
```sql
-- Verify predictions have line data
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-24' AND current_points_line IS NOT NULL;

-- Verify current lines exist
SELECT COUNT(*) FROM nba_raw.bettingpros_player_points_props
WHERE game_date = '2026-01-24' AND is_active = TRUE;
```

### Too Many Stale Predictions (>20)

**Cause:** Threshold too low, or mass line movement event

**Action:** Increase threshold or investigate mass movement cause

### Query Timeout

**Cause:** Large date range or dataset

**Action:** Add date partition pruning, ensure game_date is indexed

---

## Related Documentation

- [Prediction Coordinator Architecture](../../00-orchestration/services.md)
- [Phase 6 Features](../current/jan-23-orchestration-fixes/CHANGELOG.md)
- [Player Loader API](../../../predictions/coordinator/player_loader.py)

---

**Created:** 2026-01-25
**Last Updated:** 2026-01-25
**Status:** Production Ready ✅
