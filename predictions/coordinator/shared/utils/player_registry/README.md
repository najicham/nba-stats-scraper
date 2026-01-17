# NBA Player Registry System

Read-only access to the authoritative NBA Players Registry for downstream processors.

## Overview

The player registry system provides stable player identification across all data sources. It consists of:

- **Write Side** (Registry Processors): Build and maintain the registry from game and roster data
- **Read Side** (RegistryReader): Provides safe, cached access for downstream processors
- **Universal Player IDs**: Stable identifiers that persist across teams, seasons, and name variations

## Module Structure

```
shared/utils/player_registry/
├── __init__.py           # Module exports
├── reader.py             # RegistryReader (read-only access)
├── resolver.py           # UniversalPlayerIDResolver (ID creation)
├── exceptions.py         # Custom exceptions
└── tests/
    └── test_reader.py    # Unit tests
```

## Quick Start

```python
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

# Initialize with caching
registry = RegistryReader(
    source_name='player_game_summary',
    cache_ttl_seconds=300  # 5-minute cache
)

# Set context for unresolved tracking
registry.set_default_context(season='2024-25')

# Get universal player ID
uid = registry.get_universal_id('lebronjames')
# Returns: 'lebronjames_001'

# Get complete player record
player = registry.get_player('lebronjames', season='2024-25')
# Returns: {'player_name': 'LeBron James', 'team_abbr': 'LAL', ...}

# Batch operations
players = ['lebronjames', 'stephencurry', 'kevindurant']
uids = registry.get_universal_ids_batch(players)
# Returns: {'lebronjames': 'lebronjames_001', ...}

# Flush unresolved players at end
registry.flush_unresolved_players()
```

## Classes

### RegistryReader

Read-only access to player registry with caching, batch operations, and unresolved tracking.

**Key Features:**
- Efficient caching with configurable TTL
- Batch operations for multiple players
- Automatic unresolved player tracking
- Context management for debugging
- Strict and lenient modes

**Constructor:**
```python
RegistryReader(
    project_id=None,           # GCP project (defaults to env)
    bq_client=None,            # Optional BigQuery client
    source_name='unknown',     # Processor name for tracking
    cache_ttl_seconds=0,       # Cache TTL (0 = no cache)
    auto_flush=False,          # Auto-flush unresolved on exit
    test_mode=False            # Use test tables
)
```

**Core Methods:**
- `get_universal_id(player_lookup, required=True, context=None)` - Get universal ID
- `get_player(player_lookup, season=None, team_abbr=None, required=True)` - Get full record
- `get_current_team(player_lookup, season, required=True)` - Get current team
- `player_exists(player_lookup, season=None)` - Check existence

**Batch Methods:**
- `get_universal_ids_batch(player_lookups, context=None)` - Batch ID lookup
- `get_players_batch(player_lookups, season, context=None)` - Batch record lookup

**Team Methods:**
- `get_team_roster(team_abbr, season)` - Get all players on team
- `get_active_teams(season)` - Get all active teams

**Search Methods:**
- `search_players(name_pattern, season=None, limit=10)` - Search by name
- `lookup_by_display_name(display_name, season=None)` - Convert display name to lookup

**Validation:**
- `validate_player_team(player_lookup, team_abbr, season)` - Verify player-team combo

**Unresolved Tracking:**
- `set_default_context(**context)` - Set default context for run
- `flush_unresolved_players()` - Write accumulated unresolved to BigQuery

**Cache Management:**
- `clear_cache()` - Clear entire cache
- `clear_cache_for_player(player_lookup)` - Clear specific player
- `get_cache_stats()` - Get cache performance metrics

### UniversalPlayerIDResolver

Creates and resolves universal player IDs. Used by registry processors (write side).

See `resolver.py` for details.

## Exceptions

- `PlayerNotFoundError` - Player not in registry
- `MultipleRecordsError` - Player on multiple teams (need team filter)
- `AmbiguousNameError` - Multiple players match search
- `RegistryConnectionError` - BigQuery connection failed

## Usage Patterns

### Analytics Processor (Lenient Mode)

Continues processing even when players are missing:

```python
class PlayerGameSummaryProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='player_game_summary',
            cache_ttl_seconds=300
        )
    
    def process_games(self, games, season):
        self.registry.set_default_context(season=season)
        
        for game in games:
            for player in game.players:
                # Lenient mode - returns None if not found
                uid = self.registry.get_universal_id(
                    player.lookup,
                    required=False,  # Don't fail
                    context={'game_id': game.id}
                )
                
                if uid is None:
                    continue  # Skip missing player
                
                self._process_player(uid, player, game)
        
        self.registry.flush_unresolved_players()
```

### Critical Processor (Strict Mode)

Fails fast when players are missing:

```python
class PropBetProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='prop_bet_processor',
            cache_ttl_seconds=300
        )
    
    def process_prop_bet(self, prop_bet):
        try:
            # Strict mode - raises exception if not found
            uid = self.registry.get_universal_id(
                prop_bet.player_lookup,
                required=True  # Must exist
            )
            
            # Validate player-team combo
            if not self.registry.validate_player_team(
                prop_bet.player_lookup,
                prop_bet.team,
                '2024-25'
            ):
                raise ValueError("Invalid player-team combination")
            
            self._create_prop_bet_record(uid, prop_bet)
            
        except PlayerNotFoundError as e:
            logger.error(f"Cannot process prop bet: {e}")
            # Don't create record for unknown player
```

### Batch Processing

More efficient for multiple players:

```python
# Get all unique players
unique_players = list(set(
    player.lookup for game in games 
    for player in game.players
))

# Single batch query
uid_map = registry.get_universal_ids_batch(unique_players)

# Use mapping
for game in games:
    for player in game.players:
        uid = uid_map.get(player.lookup)
        if uid:
            process_record(uid, player, game)
```

### Context Manager

Auto-flush on exit:

```python
with RegistryReader(
    source_name='script',
    auto_flush=True
) as registry:
    registry.set_default_context(season='2024-25')
    
    for player in players:
        uid = registry.get_universal_id(player, required=False)
        if uid:
            analyze_player(uid, player)

# Auto-flushed on exit
```

## Configuration

### Environment Variables

- `GCP_PROJECT_ID` - GCP project ID (if not provided to constructor)
- `EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD` - Alert threshold (default: 50)

### Cache Recommendations

| Use Case | Cache TTL | Reason |
|----------|-----------|--------|
| Real-time processing | 60s | Fresh data |
| Daily batch jobs | 0 (disabled) | Run once |
| API endpoints | 300s (5min) | Balance freshness/performance |
| Reporting/Analytics | 3600s (1hr) | Historical data stable |

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Registry System                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  WRITE SIDE (Processors)                READ SIDE (RegistryReader)│
│  ├─ Gamebook Processor                  ├─ Player Game Summary   │
│  │  └─ UniversalPlayerIDResolver        │  └─ RegistryReader     │
│  │     └─ CREATE/UPDATE IDs             │     └─ READ IDs        │
│  │                                       │                        │
│  ├─ Roster Processor                    ├─ Prop Bet Processor    │
│  │  └─ UniversalPlayerIDResolver        │  └─ RegistryReader     │
│  │     └─ CREATE/UPDATE IDs             │     └─ READ IDs        │
│  │                                       │                        │
│  └─ Writes to:                          └─ Reads from:           │
│     ├─ nba_players_registry                ├─ nba_players_registry│
│     ├─ player_aliases                      ├─ player_aliases      │
│     └─ unresolved_player_names             └─ unresolved_player_names│
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Testing

Run unit tests:

```bash
python -m pytest shared/utils/player_registry/tests/test_reader.py -v
```

Mock BigQuery in tests:

```python
from unittest.mock import Mock, patch
import pandas as pd

@patch('shared.utils.player_registry.reader.bigquery.Client')
def test_my_processor(mock_client_class):
    mock_client = Mock()
    mock_df = pd.DataFrame([{'universal_player_id': 'test_001'}])
    mock_query_job = Mock()
    mock_query_job.to_dataframe.return_value = mock_df
    mock_client.query.return_value = mock_query_job
    
    registry = RegistryReader(bq_client=mock_client, source_name='test')
    uid = registry.get_universal_id('testplayer')
    
    assert uid == 'test_001'
```

## Monitoring

### Check Unresolved Players

```sql
SELECT 
    source,
    normalized_lookup,
    team_abbr,
    occurrences,
    first_seen_date,
    status
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
  AND first_seen_date >= CURRENT_DATE() - 7
ORDER BY occurrences DESC
LIMIT 50;
```

### Cache Performance

```python
stats = registry.get_cache_stats()
print(f"Cache hit rate: {stats['hit_rate']:.2%}")
print(f"Cache size: {stats['cache_size']}")
```

## Best Practices

✅ **DO:**
- Use batch operations for multiple players
- Enable caching for production (300s recommended)
- Always handle `PlayerNotFoundError`
- Set default context at start of run
- Flush unresolved players at end of run
- Use `required=False` for analytics (lenient)
- Use `required=True` for critical data (strict)

❌ **DON'T:**
- Loop with individual queries (use batch instead)
- Ignore unresolved players (check periodically)
- Create multiple RegistryReader instances (reuse)
- Query without season filter unless necessary
- Forget to flush unresolved players

## Migration from Direct Queries

1. Replace direct BigQuery player queries with `RegistryReader`
2. Update schema to use `universal_player_id` instead of `player_lookup`
3. Add error handling for `PlayerNotFoundError`
4. Add `flush_unresolved_players()` at end of runs
5. Test with both known and unknown players
6. Monitor `unresolved_player_names` table

## Support

For issues or questions:
- Check `unresolved_player_names` table for tracking
- Review processor logs for registry errors
- Verify BigQuery connectivity and quotas
- Check cache stats for performance issues

## Related Documentation

- [Registry Reader API Documentation](../../../documents/registry_reader_api.md)
- [Integration Examples](INTEGRATION_EXAMPLE.md)
- [Registry Processor Documentation](../../../data_processors/reference/README.md)