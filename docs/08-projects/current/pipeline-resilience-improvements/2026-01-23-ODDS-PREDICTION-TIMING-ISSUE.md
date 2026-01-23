# Odds API → Predictions Timing Issue

**Date**: 2026-01-23
**Status**: Analysis Complete, Solutions Proposed

## Problem Summary

Today's predictions ran at 15:05 UTC (~10:05 AM ET) but found **no odds_api data** in BigQuery, resulting in:
- 235 predictions with `ACTUAL_PROP` (1 game - HOU@DET early scrape)
- 2,040 predictions with `NO_PROP_LINE` (6 games)

## Root Cause Analysis

### Timeline of Events

| Time (UTC) | Event | Status |
|------------|-------|--------|
| 14:08-14:33 | OddsAPI props scraped → GCS | ✅ 16 files |
| ~14:59 | Batch processor triggered | ⚠️ **SKIPPED** (deduplication) |
| 15:05-15:06 | Predictions coordinator ran | ❌ Found no data |
| 15:53 | Manual batch re-run | ✅ 433 rows loaded |

### Why Batch Processor Skipped

The batch processor checks `nba_reference.processor_run_history` for previous successful runs:

```sql
SELECT * FROM processor_run_history
WHERE processor_name = 'OddsApiPropsBatchProcessor'
  AND data_date = '2026-01-23'
  AND status IN ('running', 'success', 'partial')
```

If a record exists, it returns `True` (already processed) and skips.

**The bug**: A stale "success" record existed from a previous (failed) run, causing the real batch to skip.

## Current Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  OddsAPI        │────▶│  Batch Processor │────▶│  BigQuery      │
│  Scraper        │     │  (GCS trigger)   │     │  (props table) │
│  (on-demand)    │     │                  │     │                │
└─────────────────┘     └──────────────────┘     └────────────────┘
                                                         │
                                                         ▼
                              ┌────────────────────────────────────┐
                              │  Predictions Coordinator           │
                              │  - Scheduled: 11:30 AM ET          │
                              │  - OR Phase 4 completion           │
                              │  - Queries BigQuery for lines      │
                              └────────────────────────────────────┘
```

**Problem**: No coupling between "lines loaded" and "predictions run"

## Proposed Solutions

### Option 1: Data Readiness Check (Quick Win)

**Before predictions run, verify odds data exists:**

```python
def check_odds_data_ready(game_date: str) -> bool:
    """Check if odds_api data is loaded for today's games."""
    query = """
    SELECT COUNT(DISTINCT game_id) as games_with_lines
    FROM `nba_raw.odds_api_player_points_props`
    WHERE game_date = @game_date
      AND snapshot_timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
    """
    result = client.query(query).result()
    games_with_lines = next(result).games_with_lines

    # Compare against expected games
    expected_games = get_expected_games_count(game_date)

    if games_with_lines < expected_games * 0.8:  # 80% threshold
        logger.warning(f"Only {games_with_lines}/{expected_games} games have lines")
        return False
    return True
```

**Pros**: Simple, catches the issue before predictions run
**Cons**: Doesn't fix the underlying timing issue

### Option 2: Trigger Predictions After Lines Load

**Add a prediction trigger in the batch processor:**

```python
# In OddsApiPropsBatchProcessor.save_data()
if self.stats['rows_inserted'] > 0:
    # Notify prediction system that new lines are available
    pubsub_client.publish(
        'nba-predictions-lines-ready',
        {'game_date': game_date, 'rows': self.stats['rows_inserted']}
    )
```

**Prediction coordinator listens and re-runs if needed:**
- If predictions already ran with `NO_PROP_LINE`, trigger a re-run
- Only re-process players missing lines

**Pros**: Self-healing, always gets lines if available
**Cons**: More complex, potential duplicate predictions

### Option 3: Schedule Lines Earlier

**Current**: OddsAPI scraper runs on-demand (no schedule)
**Proposed**: Schedule scraper to run at fixed times:

| Time (ET) | Purpose |
|-----------|---------|
| 6:00 AM | Early morning lines (for overnight processing) |
| 10:00 AM | Morning refresh (before 11:30 AM predictions) |
| 2:00 PM | Afternoon refresh |
| 6:00 PM | Pre-game refresh |

**Pros**: Predictable timing, ensures lines before predictions
**Cons**: More API calls, may miss late-breaking lines

### Option 4: Fix Deduplication Bug

**Problem**: Batch processor skips if `processor_run_history` has a "success" record

**Fix**: Add validation that the "success" actually loaded data:

```python
def check_already_processed(...):
    # Current: Just checks status = 'success'
    # New: Also verify records_processed > 0

    query = """
    SELECT status, records_processed
    FROM processor_run_history
    WHERE processor_name = @name AND data_date = @date
      AND status IN ('running', 'success')
    ORDER BY started_at DESC
    LIMIT 1
    """

    row = client.query(query).result()
    if row.status == 'success' and row.records_processed == 0:
        # Stale/failed run - allow reprocessing
        return False
    return True
```

**Pros**: Fixes root cause
**Cons**: Doesn't address timing coupling

### Option 5: Add Alerting

**Alert if predictions run without odds data:**

```python
# In prediction coordinator
if no_prop_line_count > total_predictions * 0.5:
    send_alert(
        level='WARNING',
        message=f'Predictions ran with {no_prop_line_count} players missing lines',
        action='Check batch processor status'
    )
```

**Pros**: Visibility into issues
**Cons**: Reactive, not preventive

## Recommended Approach

**Phase 1 (Immediate)**:
1. ✅ Fix deduplication bug (Option 4) - validate records_processed > 0
2. Add alerting (Option 5) - know when this happens

**Phase 2 (Short-term)**:
3. Add data readiness check (Option 1) - fail fast if no data
4. Schedule lines earlier (Option 3) - 10:00 AM scrape before 11:30 predictions

**Phase 3 (Medium-term)**:
5. Trigger predictions after lines load (Option 2) - self-healing

## Resolution (2026-01-23)

### Fixes Deployed

**1. Deduplication Bug Fix** ✅
- Commit: `605ebcb3`
- Added `SKIP_DEDUPLICATION = True` to both batch processors
- Prevents conflict between Firestore locks and run_history deduplication

**2. Auto-Update Predictions** ✅
- Added `_update_predictions_with_new_lines()` to `OddsApiPropsBatchProcessor`
- When lines load, automatically updates `NO_PROP_LINE` predictions
- Sets: current_points_line, line_margin, has_prop_line, line_source, recommendation
- Only affects current/future dates (not historical)

**3. Today's Predictions Fixed** ✅
- Updated 330 predictions from `NO_PROP_LINE` → `ACTUAL_PROP`
- Final state: 565 ACTUAL_PROP, 78 NO_PROP_LINE (players without lines)

### Deployment

- Service: `nba-phase2-raw-processors`
- Revision: `nba-phase2-raw-processors-00110-dd9`
- Deployed: 2026-01-23 20:23 UTC

### Self-Healing Behavior

The system now self-heals:
1. Predictions run (some may be NO_PROP_LINE if lines aren't loaded yet)
2. Batch processor loads lines
3. Batch processor automatically updates predictions with new lines
4. No manual intervention needed

## Related Files

- `/data_processors/raw/oddsapi/oddsapi_batch_processor.py` - Batch processor
- `/shared/processors/mixins/run_history_mixin.py` - Deduplication logic
- `/predictions/coordinator/coordinator.py` - Prediction orchestration
- `/predictions/coordinator/player_loader.py` - Line lookup logic
