# Orchestration Improvements Handoff

**Date:** 2025-12-02
**Status:** ✅ COMPLETE - All issues implemented

## Summary

This session implemented several orchestration improvements identified during deep analysis of the daily pipeline flow:

## Implemented Changes

### 1. Centralized Orchestration Config (`shared/config/orchestration_config.py`)

New configuration file with dataclasses for:
- **PhaseTransitionConfig**: Lists expected processors for each phase transition
- **ScheduleStalenessConfig**: Max stale hours with manual override support
- **PredictionModeConfig**: Strict vs fallback mode, multiple lines default
- **ProcessingModeConfig**: Daily vs backfill mode
- **NewPlayerConfig**: Min games required, bootstrap handling

**Environment Variable Overrides:**
```bash
SCHEDULE_STALENESS_OVERRIDE_HOURS=12
SCHEDULE_STALENESS_OVERRIDE_EXPIRES=2025-12-03T00:00:00
PREDICTION_MODE=strict|fallback
PROCESSING_MODE=daily|backfill
USE_MULTIPLE_LINES_DEFAULT=true|false
```

### 2. Multiple Lines by Default (Issue 4)

**File:** `predictions/coordinator/coordinator.py`

Changed default from `False` to config-driven:
```python
use_multiple_lines = request_data.get(
    'use_multiple_lines',
    orch_config.prediction_mode.use_multiple_lines_default  # True by default
)
```

Now generates predictions for line ±2 points by default (5 lines per player).

### 3. New Player Cold Start Handling (Issue 3)

**File:** `predictions/coordinator/player_loader.py`

- Players with < 3 games are marked `needs_bootstrap: true`
- No default 15.5 line (was causing bad predictions for rookies)
- These players are skipped from prediction batch
- Logged for visibility: "Skipped N players needing bootstrap"

**Config options:**
```python
NewPlayerConfig:
    min_games_required: int = 3      # Minimum games before predictions
    use_default_line: bool = False   # Don't use fallback 15.5
    mark_needs_bootstrap: bool = True
```

### 4. Phase Transition Processor Lists (Issue 8)

**File:** `shared/config/orchestration_config.py`

Moved hardcoded "21 processors" to config:
```python
phase2_expected_processors: List[str] = [
    'bdl_player_boxscores',
    'nbac_gamebook_player_stats',
    # ... all 21 processors listed
]

phase3_expected_processors: List[str] = [
    'player_game_summary',
    # ... all 5 processors
]
```

### 5. Schedule Staleness Override (Issue 7)

**File:** `shared/config/orchestration_config.py`

Manual override when NBA.com is down:
```python
schedule_staleness:
    max_stale_hours: 6              # Default
    override_hours: 12              # Manual override
    override_expires_at: datetime   # Auto-revert
```

### 6. Prediction Mode Fallback (Issue 9)

**File:** `shared/config/orchestration_config.py`

Config for strict vs fallback mode:
```python
PredictionModeConfig:
    mode: str = 'strict'            # or 'fallback'
    fallback_rerun_enabled: bool = True
    fallback_quality_multiplier: float = 0.7
```

### 7. Daily vs Backfill Driver (Issue 1) - IMPLEMENTED

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Problem:** The processor used gamebook as driver for ALL modes, but gamebook only exists AFTER games finish. Daily predictions couldn't work because there was no gamebook data for today's games.

**Solution:** Added auto-detection of processing mode and separate driver queries:

```python
def _determine_processing_mode(self) -> str:
    # 1. Check PROCESSING_MODE env var (explicit override)
    # 2. Query gamebook - if data exists, use BACKFILL mode
    # 3. If gamebook empty AND date is today/future, use DAILY mode

def _extract_players_daily_mode(self) -> None:
    # Uses schedule + roster (pre-game data)
    # LEFT JOINs with injury report for player status
    # Found 248 players for today's 6 games

def _extract_players_backfill_mode(self) -> None:
    # Uses gamebook (post-game actual players)
    # Original query, refactored
```

**Test Results:**
- Daily mode (2025-12-02): Found 248 players from roster
- Backfill mode (2024-11-22): Found 468 players from gamebook

**Deployed:** Revision `nba-phase3-analytics-processors-00011-5mn`

---

### 8. Player Universe Consistency (Issue 5) - IMPLEMENTED

**File:** `shared/validation/context/player_universe.py`

**Problem:** Different components used different sources for player universe.

**Solution:** Enhanced `get_player_universe()` to be the single source of truth:
- Supports `mode='daily'` (schedule + roster) and `mode='backfill'` (gamebook → BDL)
- Auto-detects mode based on gamebook availability
- Same logic as Issue 1 fix, now centralized

**Usage:**
```python
from shared.validation.context.player_universe import get_player_universe

# Auto-detect mode
universe = get_player_universe(game_date)

# Explicit mode
universe = get_player_universe(game_date, mode='daily')
universe = get_player_universe(game_date, mode='backfill')
```

### 9. Roster Staleness Check (Issue 6) - IMPLEMENTED

**File:** `shared/validation/context/player_universe.py`

**Solution:** Built into `get_player_universe()`:
- Added `roster_date` field to `PlayerUniverse` dataclass
- Tracks which roster date was used
- Logs warning if roster is > 7 days stale
- Displays staleness in `format_player_universe()`:
  ```
  Total Rostered: 248 players across 12 teams  📋 Roster mode  ⚠️ 45 days stale
  ```

---

### 10. Cloud Function Config Sync (Issue A) - IMPLEMENTED

**Files:**
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- `orchestration/cloud_functions/phase3_to_phase4/main.py`

**Problem:** Cloud functions had hardcoded `EXPECTED_PROCESSORS = 21` (or `5`) values that could get out of sync with `orchestration_config.py`.

**Solution:**
- Cloud functions now import expected processors from centralized config
- Fallback list included for Cloud Function deployment (where imports may fail)
- Added `missing_processors` field to status responses for debugging
- Added `expected_processors` list to trigger messages

**Verification:**
```bash
PYTHONPATH=. python3 -c "
from orchestration.cloud_functions.phase2_to_phase3.main import EXPECTED_PROCESSOR_COUNT
print(f'Phase 2→3: {EXPECTED_PROCESSOR_COUNT} processors')
"
```

### 11. Phase 4 → Phase 5 Orchestrator (Issue B) - IMPLEMENTED

**File:** `orchestration/cloud_functions/phase4_to_phase5/main.py`

**Problem:** No event-driven trigger for Phase 5 predictions. The prediction coordinator was only triggered by Cloud Scheduler at a fixed time, not when Phase 4 actually completed.

**Solution:** Created a new cloud function that:
- Listens to: `nba-phase4-processor-complete` (Phase 4 processors publish here)
- Tracks completion in: Firestore `phase4_completion/{game_date}`
- When all 5 Phase 4 processors complete:
  1. Publishes to `nba-phase4-precompute-complete` topic
  2. Calls prediction coordinator `/start` endpoint directly via HTTP

**Phase 4 Processors Tracked:**
- team_defense_zone_analysis
- player_shot_zone_analysis
- player_composite_factors
- player_daily_cache
- ml_feature_store

**Deployment (when ready):**
```bash
gcloud functions deploy phase4-to-phase5-orchestrator \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase4_to_phase5 \
  --entry-point=orchestrate_phase4_to_phase5 \
  --trigger-topic=nba-phase4-processor-complete
```

### 12. Stuck Transition Monitor (Issue C) - IMPLEMENTED

**File:** `orchestration/cloud_functions/transition_monitor/main.py`

**Problem:** If a processor fails silently, the phase transition hangs forever with no alerting.

**Solution:** Created a monitoring cloud function that:
- Checks all phase transitions (2→3, 3→4, 4→5) for stuck states
- Triggered by Cloud Scheduler (recommended: hourly)
- Detects stuck transitions based on:
  - Document age > timeout (2h for Phase 2, 1h for Phase 3/4)
  - Not all expected processors complete
  - Not yet triggered
- Sends alerts with:
  - Which phase is stuck
  - Which processors are missing
  - How long it's been stuck
- Integrates with existing email alerter

**Deployment (when ready):**
```bash
# Deploy the function
gcloud functions deploy transition-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/transition_monitor \
  --entry-point=monitor_transitions \
  --trigger-http

# Create Cloud Scheduler job
gcloud scheduler jobs create http transition-monitor-hourly \
  --location=us-west2 \
  --schedule="0 * * * *" \
  --uri="FUNCTION_URL" \
  --http-method=GET
```

### 13. Schedule Staleness Override Wiring (Issue D) - IMPLEMENTED

**File:** `orchestration/master_controller.py`

**Problem:** The `_ensure_schedule_current()` method had a hardcoded `6` hour threshold for schedule staleness, not using the configurable override from `orchestration_config.py`.

**Solution:**
- Now imports `get_orchestration_config()` at module level
- Uses `_orchestration_config.schedule_staleness.get_effective_max_hours()`
- This respects manual overrides when NBA.com is down

**Usage for override (when NBA.com down):**
```bash
# Set environment variables before starting master controller
export SCHEDULE_STALENESS_OVERRIDE_HOURS=24
export SCHEDULE_STALENESS_OVERRIDE_EXPIRES="2025-12-03T00:00:00"
```

---

## All Issues Status

| Issue | Description | Status |
|-------|-------------|--------|
| 1 | Daily vs Backfill Driver | ✅ Deployed |
| 3 | New Player Cold Start | ✅ Implemented |
| 4 | Multiple Lines Default | ✅ Implemented |
| 5 | Player Universe Consistency | ✅ Implemented |
| 6 | Roster Staleness Check | ✅ Implemented |
| 7 | Schedule Staleness Override | ✅ Implemented |
| 8 | Phase Transition Processor Lists | ✅ Implemented |
| 9 | Prediction Mode (strict/fallback) | ✅ Implemented |
| A | Cloud Function Config Sync | ✅ Implemented |
| B | Phase 4 → Phase 5 Orchestrator | ✅ Implemented |
| C | Stuck Transition Monitor | ✅ Implemented |
| D | Schedule Staleness Override Wiring | ✅ Implemented |

## Files Modified

| File | Changes |
|------|---------|
| `shared/config/orchestration_config.py` | NEW - Centralized config |
| `predictions/coordinator/coordinator.py` | Import config, use_multiple_lines default |
| `predictions/coordinator/player_loader.py` | New player handling, config imports |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Issue 1 fix - daily vs backfill driver |
| `shared/validation/context/player_universe.py` | Issues 5 & 6 - daily mode, roster staleness |
| `orchestration/cloud_functions/phase2_to_phase3/main.py` | Issue A - import from centralized config |
| `orchestration/cloud_functions/phase3_to_phase4/main.py` | Issue A - import from centralized config |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | NEW - Issue B - Phase 4→5 orchestrator |
| `orchestration/cloud_functions/transition_monitor/main.py` | NEW - Issue C - Stuck transition monitor |
| `orchestration/master_controller.py` | Issue D - Use config for schedule staleness |

## Testing

```bash
# Verify config loads
python3 -c "from shared.config.orchestration_config import get_orchestration_config; c = get_orchestration_config(); print(f'multiple_lines_default={c.prediction_mode.use_multiple_lines_default}')"

# Verify prediction coordinator starts
# (requires deployed environment)
```

## Environment Variables for Production

Add to Cloud Run service:
```yaml
env:
  - name: USE_MULTIPLE_LINES_DEFAULT
    value: "true"
  - name: PREDICTION_MODE
    value: "strict"
```

## Related Documentation

- `docs/08-projects/current/validation/VALIDATION-V2-DESIGN.md` - Validation system updates
- `shared/config/orchestration_config.py` - Full config reference
