# Smart Prediction Retry System Design

**Session 94 - 2026-02-03**

## Current Problem

```
2:30 AM - predictions-early runs
        - REAL_LINES_ONLY mode
        - Lines not available → 0 predictions
        - No retry, no alert

7:00 AM - overnight-predictions runs
        - Should work, but...
        - If features missing, proceeds anyway
        - Creates low-quality "top picks"

1:00 PM - Export runs
        - If predictions failed/late → empty export
        - Users see no picks
```

## Proposed Solution

### Prediction Run Modes

| Mode | Time (ET) | Real Lines | Quality Threshold | B2B Requirement | Behavior on Failure |
|------|-----------|------------|-------------------|-----------------|---------------------|
| EARLY | 2:30 AM | Required | 85% | BDB required | Alert + schedule retry |
| RETRY_1 | 5:00 AM | Required | 85% | BDB required | Alert if <50% coverage |
| OVERNIGHT | 7:00 AM | Preferred | 80% | BDB preferred | Flag low-quality |
| MORNING | 10:00 AM | Optional | 70% | Optional | Proceed with flags |

### Back-to-Back Player Logic

```python
def should_pause_prediction(player, attempt_number, is_b2b):
    """
    Determine if prediction should be paused for this player.

    For B2B players, we NEED their previous game's BDB data
    to accurately predict fatigue-adjusted performance.
    """
    if not is_b2b:
        # Non-B2B: standard quality threshold
        return player.feature_quality_score < MIN_QUALITY_THRESHOLD

    # B2B player: stricter requirements
    has_previous_game_bdb = player.previous_game_has_bdb_data

    if attempt_number <= 2:
        # Attempts 1-2: Require BDB data for B2B players
        if not has_previous_game_bdb:
            alert(f"B2B player {player.name} missing previous game BDB data")
            trigger_bdb_scraper(player.previous_game_id)
            return True  # PAUSE - wait for data

    # Attempt 3 (final): Proceed but flag as low quality
    if not has_previous_game_bdb:
        player.low_quality_flag = True
        player.exclude_from_top_picks = True
        log(f"B2B player {player.name} proceeding with missing BDB (final attempt)")

    return False  # Proceed with prediction
```

### Alert Flow

```
Attempt 1 (2:30 AM):
  ├─ Missing lines for player X → Log, don't alert (expected)
  ├─ 0 predictions total → ALERT: "No predictions created - lines unavailable"
  └─ Trigger: bettingpros_scraper for today's games

Attempt 2 (5:00 AM):
  ├─ Still missing lines for player X → Log + ALERT: "Player X still missing lines"
  ├─ <50% coverage → ALERT: "Low prediction coverage"
  └─ B2B player missing BDB → ALERT + trigger BDB scraper

Attempt 3 (7:00 AM):
  ├─ Proceed with all available data
  ├─ Flag low-quality predictions
  └─ B2B players without BDB → excluded from top picks, flagged
```

### Implementation Changes

#### 1. Coordinator Changes (`predictions/coordinator/coordinator.py`)

```python
# New prediction mode config
PREDICTION_MODES = {
    'EARLY': {
        'require_real_lines': True,
        'min_quality_score': 85.0,
        'b2b_requires_bdb': True,
        'max_attempts': 1,  # Just log, retry handled by next job
    },
    'RETRY': {
        'require_real_lines': True,
        'min_quality_score': 85.0,
        'b2b_requires_bdb': True,
        'alert_on_low_coverage': True,
        'coverage_threshold': 0.5,
    },
    'OVERNIGHT': {
        'require_real_lines': False,
        'min_quality_score': 80.0,
        'b2b_requires_bdb': False,  # Preferred but not required
        'flag_low_quality': True,
    },
    'MORNING': {
        'require_real_lines': False,
        'min_quality_score': 70.0,
        'b2b_requires_bdb': False,
        'allow_all': True,  # Final attempt - proceed with everything
    },
}
```

#### 2. Player Loader Changes (`predictions/coordinator/player_loader.py`)

```python
def _check_b2b_bdb_requirement(self, player, mode_config):
    """Check if B2B player has required BDB data."""
    if not player.is_b2b:
        return True  # Not B2B, no special requirement

    if not mode_config.get('b2b_requires_bdb', False):
        return True  # Mode doesn't require BDB for B2B

    # Check if previous game has BDB data
    has_bdb = self._query_previous_game_bdb_status(player)

    if not has_bdb:
        logger.warning(
            f"B2B_MISSING_BDB: {player.player_lookup} missing BDB data "
            f"for previous game {player.previous_game_id}"
        )
        return False

    return True
```

#### 3. New Scheduler Jobs

| Job | Schedule | Mode |
|-----|----------|------|
| `predictions-early` | 2:30 AM ET | EARLY |
| `predictions-retry` | 5:00 AM ET | RETRY (NEW) |
| `overnight-predictions` | 7:00 AM ET | OVERNIGHT |
| `morning-predictions` | 10:00 AM ET | MORNING |

### Export Schedule (Updated)

| Job | Time (ET) | Purpose |
|-----|-----------|---------|
| `phase6-tonight-picks-morning` | 11:00 AM | First export with morning predictions |
| `phase6-tonight-picks` | 1:00 PM | Mid-day refresh |
| `phase6-tonight-picks-pregame` | 5:00 PM | Final pre-game export |

### Quality Flags in Predictions Table

Add columns to `player_prop_predictions`:
- `feature_quality_score` - Already exists via join
- `b2b_missing_bdb` - New flag for B2B players without BDB
- `low_quality_reason` - Text explaining why quality is low
- `exclude_from_top_picks` - Boolean to exclude from exports

### Monitoring & Alerts

#### Slack Alerts

1. **Early Prediction Failure**
   - Trigger: 0 predictions at 2:30 AM
   - Channel: #nba-alerts
   - Action: Auto-trigger line scraper

2. **Low Coverage Alert**
   - Trigger: <50% expected players at 5:00 AM
   - Channel: #nba-alerts
   - Include: List of missing players

3. **B2B BDB Missing**
   - Trigger: B2B player missing previous game BDB
   - Channel: #app-error-alerts
   - Action: Trigger BDB scraper for specific game

#### Metrics Dashboard

```sql
-- Daily prediction quality summary
SELECT
  game_date,
  prediction_run_mode,
  COUNT(*) as total_predictions,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(b2b_flag = TRUE) as b2b_players,
  COUNTIF(b2b_flag = TRUE AND b2b_missing_bdb = TRUE) as b2b_missing_bdb,
  COUNTIF(exclude_from_top_picks = TRUE) as excluded_from_top
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

## Implementation Priority

1. **P0 (Today):** Add 5:00 AM retry scheduler job
2. **P1 (This week):** B2B quality gate in player_loader
3. **P2 (Next week):** Full smart retry with alerts
4. **P3 (Later):** Dashboard and monitoring

## Testing Plan

1. Manually trigger EARLY mode with no lines → verify alert
2. Manually trigger RETRY mode with partial lines → verify coverage alert
3. Test B2B player with missing BDB → verify pause behavior
4. Test final attempt with missing data → verify flag behavior
