# Player Movement Registry Processor

## Overview

The Player Movement Registry Processor provides rapid updates to the player registry when trades occur, using NBA.com player movement data as the source of truth. This allows the registry to be updated within hours of a trade (when the player movement scraper runs), rather than waiting for nightly roster updates.

## Key Features

- **Fast Updates**: Updates registry within hours of trades being announced
- **Idempotent**: Safe to run multiple times - won't duplicate updates
- **Current Season Only**: Focuses on current season player movements
- **Team Normalization**: Handles team abbreviation variations (BRK→BKN, CHO→CHA, PHO→PHX)
- **Source Tracking**: Marks updates with `source_priority = 'player_movement'`
- **Configurable Lookback**: Can process trades from any time period

## Data Flow

```
NBA.com Player Movement
         ↓
nbac_player_movement scraper → nba_raw.nbac_player_movement
         ↓
PlayerMovementRegistryProcessor
         ↓
nba_reference.nba_players_registry (updated)
```

## Usage

### Command Line

```bash
# Process trades from last 24 hours (default)
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py

# Process trades from last 48 hours
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --lookback-hours 48

# Process specific season
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --season-year 2025

# Test mode
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --test-mode
```

### Using the Shell Script

```bash
# Process trades from last 24 hours
./bin/process-player-movement.sh

# Process trades from last 48 hours
./bin/process-player-movement.sh --lookback-hours 48

# Process trades for specific season
./bin/process-player-movement.sh --season-year 2025

# Test mode
./bin/process-player-movement.sh --test-mode
```

### Python API

```python
from data_processors.reference.player_reference import PlayerMovementRegistryProcessor

# Create processor
processor = PlayerMovementRegistryProcessor()

# Process recent trades
result = processor.process_recent_trades(
    lookback_hours=24,
    season_year=2025
)

print(f"Status: {result['status']}")
print(f"Trades found: {result['trades_found']}")
print(f"Records updated: {result['records_updated']}")
print(f"Players updated: {result['players_updated']}")
```

## Output

### Successful Run

```
Processing Results:
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

### No Updates Needed

```
Processing Results:
Status: success
Season: 2025-26
Trades found: 10
Records updated: 0

(All traded players already have correct team assignments)
```

## How It Works

### 1. Query Recent Trades

Queries `nba_raw.nbac_player_movement` for trades in the lookback period:

```sql
SELECT DISTINCT
    player_lookup,
    player_full_name,
    team_abbr,
    transaction_date,
    transaction_description
FROM nba_raw.nbac_player_movement
WHERE transaction_type = 'Trade'
  AND is_player_transaction = TRUE
  AND player_lookup IS NOT NULL
  AND scrape_timestamp >= @lookback_timestamp
```

### 2. Get Current Registry Records

Fetches existing registry records for the traded players:

```sql
SELECT
    player_lookup,
    player_name,
    team_abbr,
    season,
    source_priority,
    processed_at
FROM nba_reference.nba_players_registry
WHERE season = '2025-26'
  AND player_lookup IN (...)
```

### 3. Build Update Records

For each trade:
- Compare new team vs. current registry team
- Skip if already correct
- Build update record with normalized team abbreviation
- Set `source_priority = 'player_movement'`
- Update `processed_at` timestamp

### 4. Apply Updates via MERGE

Uses BigQuery MERGE statement for efficient updates:

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

## Team Normalization

The processor normalizes team abbreviations to match NBA.com standards:

| Input | Normalized |
|-------|------------|
| BRK   | BKN        |
| CHO   | CHA        |
| PHO   | PHX        |

## Integration Points

### Triggers

The processor should run after the player movement scraper completes:

1. **Player Movement Scraper** runs (automated hourly during trade season)
2. **PlayerMovementRegistryProcessor** runs (within 1-2 hours)
3. **Registry updated** with new team assignments

### Scheduling

Recommended schedule during trade season (Jan-Feb):
- Run every 2-4 hours to catch trades quickly
- Can run more frequently during trade deadline day
- Safe to run multiple times (idempotent)

Example Cloud Scheduler:
```bash
# Every 4 hours during trade season
gcloud scheduler jobs create http player-movement-registry \
  --schedule="0 */4 * 1-2 *" \
  --uri="https://nba-phase2-processors-f7p3g7f6ya-wl.a.run.app/process" \
  --http-method=POST \
  --message-body='{"processor":"player_movement_registry","season_year":2025}' \
  --time-zone="America/New_York"
```

## Validation

### Check Recent Updates

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

### Compare with Player Movement Data

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

## Error Handling

The processor handles several error conditions:

### No Trades Found
```
Status: success
Trades found: 0
Records updated: 0
Message: No trades in lookback period
```

### Player Not in Registry
```
WARNING: No registry record found for Player Name (playerlookup) in season 2025-26
```

This is expected for:
- Two-way players not yet in registry
- Players on non-NBA teams
- Players with incorrect lookups in player movement data

### Query Failures

All BigQuery errors are caught and logged, with notifications sent to configured alert channels.

## Testing

### Test Mode

Uses test tables (`nba_players_registry_test_FIXED2`):

```bash
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --test-mode
```

### Manual Test with Recent Trades

```bash
# Process trades from last 48 hours
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --lookback-hours 48

# Verify updates
bq query --use_legacy_sql=false "
SELECT player_lookup, player_name, team_abbr, source_priority, processed_at
FROM nba_reference.nba_players_registry
WHERE source_priority = 'player_movement'
  AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY player_name"

# Run again - should show 0 updates (idempotency test)
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py --lookback-hours 48
```

## Monitoring

### Key Metrics

- **Trades Found**: Number of player trades in lookback period
- **Records Updated**: Number of registry records updated
- **Processing Time**: Should complete in <30 seconds for typical trade volume

### Alerts

The processor sends notifications for:
- **Success**: When updates are made (info level)
- **Errors**: Query failures, MERGE failures (error level)
- **Warnings**: Players not found in registry (debug logs)

### Logs

```bash
# View recent processing logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND jsonPayload.message=~"Player Movement"' \
  --limit=50 \
  --format=json

# Check for errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND severity>=ERROR
  AND jsonPayload.processor_name="Player Movement Registry Processor"' \
  --limit=20
```

## Comparison with Roster Registry Processor

| Feature | Player Movement Processor | Roster Registry Processor |
|---------|---------------------------|---------------------------|
| **Speed** | Hours after trade | Daily (overnight) |
| **Source** | NBA.com player movement | ESPN/NBA.com/BR rosters |
| **Scope** | Trades only | All roster changes |
| **Authority** | High (official transactions) | Medium (roster assignments) |
| **Frequency** | On-demand or hourly | Daily |
| **Use Case** | Rapid trade updates | Comprehensive roster sync |

## Best Practices

1. **Run After Player Movement Scraper**: Wait 15-30 minutes after scraper completes to ensure data is available

2. **Increase Frequency During Trade Deadline**: Run hourly on trade deadline day for fastest updates

3. **Use Appropriate Lookback**: 24 hours is usually sufficient, use 48-72 hours after maintenance windows

4. **Monitor for Missing Players**: Players not found in registry may indicate:
   - New players not yet in system (should be added by roster processor)
   - Data quality issues with player lookups
   - Two-way players or G-League callups

5. **Coordinate with Roster Processor**: The roster processor will eventually update all players, but this processor provides faster updates for trades

## Troubleshooting

### Player Not Updating

Check if player exists in registry:
```sql
SELECT * FROM nba_reference.nba_players_registry
WHERE player_lookup = 'playerlookup'
  AND season = '2025-26'
```

If missing, wait for roster processor to add them, or manually add via gamebook processor.

### Team Abbreviation Mismatch

Check normalization mapping:
```python
TEAM_ABBR_NORMALIZATION = {
    'BRK': 'BKN',
    'CHO': 'CHA',
    'PHO': 'PHX',
}
```

### Stale Trades Showing Up

Check scrape_timestamp in player_movement:
```sql
SELECT player_lookup, team_abbr, transaction_date, scrape_timestamp
FROM nba_raw.nbac_player_movement
WHERE transaction_type = 'Trade'
  AND is_player_transaction = TRUE
ORDER BY scrape_timestamp DESC
LIMIT 10
```

## Future Enhancements

1. **Support for Other Transaction Types**: Signings, waivers, releases
2. **Historical Trade Processing**: Backfill historical trades
3. **Validation Against Box Scores**: Cross-check trades with actual game participation
4. **Multi-Player Trades**: Better grouping and reporting of multi-player trades
5. **Trade Metadata**: Store trade details (assets, picks, etc.)

## Related Documentation

- [Roster Registry Processor](../02-operations/runbooks/roster-registry-processor.md)
- [Player Movement Scraper](../../scrapers/README.md)
- [Registry Data Model](../01-architecture/data-models/registry.md)
- [Player Lookup System](../01-architecture/player-lookup-system.md)
