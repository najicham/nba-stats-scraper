# Player Movement Registry Processor Implementation

**Date**: 2026-02-02
**Status**: Complete and Tested

## Summary

Created a new `PlayerMovementRegistryProcessor` that updates the player registry within hours of trades occurring, using NBA.com player movement data as the source of truth. This provides much faster registry updates than waiting for overnight roster processing.

## What Was Built

### Core Processor
**File**: `data_processors/reference/player_reference/player_movement_registry_processor.py`

- Reads recent trades from `nba_raw.nbac_player_movement`
- Updates `nba_reference.nba_players_registry` with new team assignments
- Marks updates with `source_priority = 'player_movement'`
- Handles current season (2025-26) trades
- Idempotent (safe to run multiple times)
- Team abbreviation normalization (BRK→BKN, CHO→CHA, PHO→PHX)

### Key Features

1. **Fast Updates**: Updates within hours of trade announcement (vs. overnight for roster processor)
2. **Configurable Lookback**: Default 24 hours, can be adjusted for any period
3. **Idempotent**: Won't duplicate updates if run multiple times
4. **Schema Compatible**: Works with both old test tables and new production schema
5. **Error Handling**: Gracefully handles missing players, query failures
6. **Notification**: Sends alerts on success/failure via email

### Processing Logic

```python
# 1. Query recent trades
trades = get_recent_trades(lookback_hours=24)

# 2. Get current registry records
registry = get_registry_records_for_players(player_lookups, season)

# 3. Build update records
updates = build_update_records(trades, registry, season)

# 4. Apply via MERGE
apply_updates_via_merge(updates, season)
```

### MERGE Statement

Updates only core fields for maximum compatibility:
```sql
MERGE nba_reference.nba_players_registry AS target
USING temp_updates AS source
ON target.player_lookup = source.player_lookup
   AND target.season = source.season
WHEN MATCHED THEN
    UPDATE SET
        team_abbr = source.team_abbr,
        source_priority = source.source_priority,
        processed_at = source.processed_at
```

## Testing Results

### Production Test (2026-02-02)

Processed 10 trades from Feb 1, 2026:

```
Status: success
Season: 2025-26
Trades found: 10
Records updated: 9

Players updated:
  - Trae Young → WAS
  - CJ McCollum → ATL
  - Dario Šarić → CHI
  - De'Andre Hunter → SAC
  - Dennis Schröder → CLE
  - Vit Krejci → POR
  - Corey Kispert → ATL
  - Duop Reath → ATL
  - Keon Ellis → CLE
```

**Verification**:
```sql
SELECT player_lookup, player_name, team_abbr, source_priority, processed_at
FROM nba_reference.nba_players_registry
WHERE source_priority = 'player_movement'
  AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY player_name
```

Results confirmed:
- All 9 players updated with correct new teams
- `source_priority = 'player_movement'` for tracking
- `processed_at` timestamps correct

**Idempotency Test**:
- Ran processor again immediately
- Result: 0 updates (correctly detected all already up-to-date)

### Unit Tests

**File**: `tests/test_player_movement_registry_processor.py`

All 12 tests passing:
- ✅ Team normalization (BRK→BKN, CHO→CHA, PHO→PHX)
- ✅ Processor initialization
- ✅ Query structure
- ✅ Update record building with team changes
- ✅ Update record building when no change needed
- ✅ Handling of players not in registry
- ✅ Team normalization in updates
- ✅ Empty player list handling
- ✅ No updates needed scenario
- ✅ Module-level function

## Files Created

1. **Processor**: `data_processors/reference/player_reference/player_movement_registry_processor.py`
2. **Tests**: `tests/test_player_movement_registry_processor.py`
3. **Shell Script**: `bin/process-player-movement.sh`
4. **Documentation**: `docs/05-development/player-movement-registry-processor.md`
5. **Handoff**: `docs/09-handoff/2026-02-02-PLAYER-MOVEMENT-REGISTRY-PROCESSOR.md` (this file)

## Files Modified

1. **Package Init**: `data_processors/reference/player_reference/__init__.py`
   - Added `PlayerMovementRegistryProcessor` to exports

## Usage

### Command Line

```bash
# Process trades from last 24 hours (default)
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py

# Process trades from last 48 hours
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --lookback-hours 48

# Process specific season
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --season-year 2025
```

### Shell Script

```bash
# Simplified wrapper
./bin/process-player-movement.sh --lookback-hours 48
```

### Python API

```python
from data_processors.reference.player_reference import PlayerMovementRegistryProcessor

processor = PlayerMovementRegistryProcessor()
result = processor.process_recent_trades(lookback_hours=24, season_year=2025)
```

## Integration Recommendations

### Scheduling

During trade season (January-February), run every 2-4 hours:

```bash
# Cloud Scheduler job (every 4 hours during trade season)
gcloud scheduler jobs create http player-movement-registry \
  --schedule="0 */4 * 1-2 *" \
  --uri="https://nba-phase2-processors-f7p3g7f6ya-wl.a.run.app/process" \
  --http-method=POST \
  --message-body='{"processor":"player_movement_registry","season_year":2025}' \
  --time-zone="America/New_York"
```

### Workflow

1. **Player Movement Scraper** runs (hourly during trade season)
2. **Wait 15-30 minutes** for scraper to complete and data to be available
3. **PlayerMovementRegistryProcessor** runs
4. **Registry updated** with new team assignments

### Monitoring

Check registry updates:
```sql
SELECT
    player_lookup,
    player_name,
    team_abbr,
    source_priority,
    processed_at
FROM nba_reference.nba_players_registry
WHERE source_priority = 'player_movement'
  AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY processed_at DESC
```

Compare with trades:
```sql
-- Players traded but not yet updated in registry
SELECT
    pm.player_lookup,
    pm.player_full_name,
    pm.team_abbr AS new_team,
    reg.team_abbr AS registry_team,
    pm.transaction_date
FROM nba_raw.nbac_player_movement pm
LEFT JOIN nba_reference.nba_players_registry reg
    ON pm.player_lookup = reg.player_lookup
    AND reg.season = '2025-26'
WHERE pm.transaction_type = 'Trade'
  AND pm.is_player_transaction = TRUE
  AND pm.transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND pm.team_abbr != reg.team_abbr
```

## Design Decisions

### 1. Core Fields Only in MERGE

The processor only updates `team_abbr`, `source_priority`, and `processed_at` to ensure compatibility with older test table schemas. This makes it robust across different schema versions.

### 2. Idempotent by Design

Checks if player's current team already matches the trade destination before creating an update record. This prevents unnecessary writes and makes the processor safe to run multiple times.

### 3. Current Season Only

Focuses on current season (`2025-26`) since historical trades are handled by roster processor backfills. This keeps the processor simple and fast.

### 4. MERGE vs. Replace

Uses MERGE strategy for targeted updates. Does not support REPLACE mode since it's designed for incremental updates, not full rebuilds.

### 5. Schema Compatibility

Queries only fields that exist in all schema versions and adds default values for missing fields (like `roster_update_count`). This ensures test mode works even with older test tables.

## Comparison with Roster Registry Processor

| Feature | Player Movement | Roster Registry |
|---------|----------------|-----------------|
| **Speed** | Hours | Overnight |
| **Source** | NBA.com trades | ESPN/NBA.com/BR rosters |
| **Scope** | Trades only | All roster changes |
| **Authority** | High (official) | Medium (roster lists) |
| **Frequency** | Hourly | Daily |
| **Use Case** | Rapid trade updates | Comprehensive sync |

## Known Limitations

1. **Players Must Exist in Registry**: Can't update players who don't have registry records yet (logs warning, skips update)
2. **Current Season Only**: Historical trades not supported (by design)
3. **Trades Only**: Doesn't process signings, waivers, releases (could be added later)
4. **No Trade Metadata**: Doesn't store trade details like assets exchanged (could be added later)

## Future Enhancements

1. **Support Other Transaction Types**: Signings, waivers, releases
2. **Historical Trade Processing**: Backfill historical trades
3. **Validation Against Box Scores**: Cross-check trades with actual game participation
4. **Multi-Player Trades**: Better grouping and reporting
5. **Trade Metadata Storage**: Store full trade details

## Documentation

See `docs/05-development/player-movement-registry-processor.md` for:
- Complete API reference
- Integration patterns
- Monitoring queries
- Troubleshooting guide
- Testing procedures

## Next Steps

1. **Deploy to Cloud Run** (if needed as standalone service)
2. **Set up Cloud Scheduler** job for trade season
3. **Add to orchestration** framework
4. **Monitor during Feb 6 trade deadline** for high-volume testing
5. **Consider expansion** to other transaction types

## Success Metrics

✅ **Processor works correctly**: 9/10 trades updated (1 player not in registry yet)
✅ **Idempotent**: Second run shows 0 updates needed
✅ **Fast**: Completes in <30 seconds
✅ **Reliable**: All tests passing
✅ **Schema compatible**: Works with old test tables and new production schema
✅ **Well documented**: Complete documentation and usage examples

## Validation Commands

```bash
# Run processor
./bin/process-player-movement.sh --lookback-hours 48

# Check results
bq query --use_legacy_sql=false "
SELECT player_lookup, player_name, team_abbr, source_priority, processed_at
FROM nba_reference.nba_players_registry
WHERE source_priority = 'player_movement'
  AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY player_name"

# Test idempotency (should show 0 updates)
./bin/process-player-movement.sh --lookback-hours 48
```

## Contact

For questions or issues, see:
- Documentation: `docs/05-development/player-movement-registry-processor.md`
- Code: `data_processors/reference/player_reference/player_movement_registry_processor.py`
- Tests: `tests/test_player_movement_registry_processor.py`
