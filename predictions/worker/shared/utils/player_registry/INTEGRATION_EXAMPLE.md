# Registry Reader Integration Example

This document shows how to integrate RegistryReader into processors, using `player_game_summary` as an example.

## Quick Start

```python
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

class PlayerGameSummaryProcessor:
    def __init__(self):
        # Initialize registry reader
        self.registry = RegistryReader(
            source_name='player_game_summary',
            cache_ttl_seconds=300  # 5-minute cache
        )
    
    def process_games(self, games, season):
        # Set default context once for entire run
        self.registry.set_default_context(season=season)
        
        for game in games:
            self._process_game(game)
        
        # Flush unresolved players at end
        self.registry.flush_unresolved_players()
    
    def _process_game(self, game):
        for player_stat in game.player_stats:
            # Get universal ID (lenient mode for analytics)
            uid = self.registry.get_universal_id(
                player_stat.player_lookup,
                required=False,  # Don't fail on missing players
                context={'game_id': game.id, 'team_abbr': player_stat.team}
            )
            
            if uid is None:
                # Player not in registry - skip this record
                continue
            
            # Process with universal_player_id
            summary_record = {
                'universal_player_id': uid,
                'game_id': game.id,
                'points': player_stat.points,
                # ... other fields
            }
            
            self._save_summary(summary_record)
```

## Pattern 1: Analytics Processor (Lenient Mode)

Analytics processors can continue without all players identified:

```python
class PlayerGameSummaryProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='player_game_summary',
            cache_ttl_seconds=300
        )
        self.skipped_count = 0
    
    def process_batch(self, games):
        self.registry.set_default_context(season='2024-25')
        
        # Use batch operation for efficiency
        all_player_lookups = [
            player.lookup for game in games 
            for player in game.players
        ]
        
        # Get all universal IDs in one query
        uid_map = self.registry.get_universal_ids_batch(all_player_lookups)
        
        # Process games
        for game in games:
            for player in game.players:
                uid = uid_map.get(player.lookup)
                
                if uid is None:
                    self.skipped_count += 1
                    continue  # Skip missing player
                
                # Process with uid
                self._create_summary(uid, player, game)
        
        # Flush at end
        self.registry.flush_unresolved_players()
        
        if self.skipped_count > 0:
            logger.warning(f"Skipped {self.skipped_count} records due to missing players")
```

## Pattern 2: Critical Processor (Strict Mode)

Prop bet processors must have valid player IDs:

```python
class PropBetProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='prop_bet_processor',
            cache_ttl_seconds=300
        )
    
    def process_prop_bets(self, prop_bets):
        self.registry.set_default_context(season='2024-25')
        
        for prop_bet in prop_bets:
            try:
                # Strict mode - raises exception if not found
                uid = self.registry.get_universal_id(
                    prop_bet.player_lookup,
                    required=True,  # MUST exist
                    context={
                        'team_abbr': prop_bet.team,
                        'sportsbook': prop_bet.sportsbook
                    }
                )
                
                # Validate player-team combination
                if not self.registry.validate_player_team(
                    prop_bet.player_lookup,
                    prop_bet.team,
                    '2024-25'
                ):
                    logger.error(
                        f"Player {prop_bet.player_lookup} not on {prop_bet.team}"
                    )
                    continue
                
                # Create prop bet record
                self._create_prop_bet_record(uid, prop_bet)
                
            except PlayerNotFoundError as e:
                logger.error(f"Cannot process prop bet: {e}")
                # Don't create record for unknown player
                continue
        
        self.registry.flush_unresolved_players()
```

## Pattern 3: Base Class Integration

Add convenience property to analytics base class:

```python
# data_processors/analytics/analytics_base.py

from shared.utils.player_registry import RegistryReader

class AnalyticsBase(ProcessorBase):
    """Base class for analytics processors."""
    
    # Override in subclass if needed
    REGISTRY_CACHE_TTL = 300  # 5 minutes default
    
    @property
    def registry(self):
        """Lazy-loaded registry reader."""
        if not hasattr(self, '_registry'):
            self._registry = RegistryReader(
                source_name=self.processor_name,
                cache_ttl_seconds=self.REGISTRY_CACHE_TTL
            )
        return self._registry
    
    def finalize_processing(self):
        """Call at end of processor run."""
        if hasattr(self, '_registry'):
            self._registry.flush_unresolved_players()
        super().finalize_processing()
```

Then in processors:

```python
class PlayerGameSummaryProcessor(AnalyticsBase):
    # Just use self.registry - base class handles creation
    
    def process_games(self, games):
        self.registry.set_default_context(season='2024-25')
        
        for game in games:
            for player in game.players:
                uid = self.registry.get_universal_id(player.lookup, required=False)
                if uid:
                    self._process_player(uid, player, game)
        
        # Base class finalize_processing() will flush
        self.finalize_processing()
```

## Pattern 4: Context Manager (Simple Scripts)

For one-off scripts or simple use cases:

```python
from shared.utils.player_registry import RegistryReader

def analyze_player_data():
    with RegistryReader(
        source_name='analysis_script',
        auto_flush=True  # Auto-flush on exit
    ) as registry:
        registry.set_default_context(season='2024-25')
        
        players = ['lebronjames', 'stephencurry', 'kevindurant']
        
        for player in players:
            uid = registry.get_universal_id(player, required=False)
            if uid:
                print(f"{player}: {uid}")
    
    # Auto-flushed on exit
```

## Common Patterns

### Batch Processing

```python
# Get all unique players first
unique_players = list(set(player.lookup for game in games for player in game.players))

# Single batch query
uid_map = registry.get_universal_ids_batch(unique_players)

# Use mapping for all records
for game in games:
    for player in game.players:
        uid = uid_map.get(player.lookup)
        if uid:
            process_record(uid, player, game)
```

### Handling Traded Players

```python
# Player on multiple teams - need to specify which team
try:
    player = registry.get_player('jamesharden', season='2023-24')
except MultipleRecordsError as e:
    # Specify team
    player = registry.get_player(
        'jamesharden',
        season='2023-24',
        team_abbr='LAC'  # His final team
    )
```

### Current Team Lookup

```python
# Get player's current team for the season
current_team = registry.get_current_team('lebronjames', season='2024-25')

# Then get the record for that team
player = registry.get_player('lebronjames', season='2024-25', team_abbr=current_team)
```

### Search and Discovery

```python
# Search for players by name
results = registry.search_players('james', season='2024-25', limit=10)
for player in results:
    print(f"{player['player_name']} - {player['team_abbr']}")

# Convert display name to lookup
try:
    lookup = registry.lookup_by_display_name('LeBron James')
    uid = registry.get_universal_id(lookup)
except AmbiguousNameError as e:
    print(f"Multiple players match: {e.matches}")
```

## Error Handling

### Full Example

```python
from shared.utils.player_registry import (
    RegistryReader,
    PlayerNotFoundError,
    MultipleRecordsError,
    AmbiguousNameError,
    RegistryConnectionError
)

registry = RegistryReader(source_name='my_processor')

try:
    uid = registry.get_universal_id('player_name', required=True)
except PlayerNotFoundError as e:
    logger.error(f"Player not found: {e.player_lookup}")
    # Will be logged to unresolved table on flush
except RegistryConnectionError as e:
    logger.error(f"Database error: {e}")
    # Handle infrastructure error

try:
    player = registry.get_player('player_name', season='2024-25')
except MultipleRecordsError as e:
    logger.warning(f"Player on multiple teams: {e.teams}")
    # Specify team_abbr parameter
except PlayerNotFoundError:
    # Player not in registry
    pass
```

## Performance Tips

1. **Use batch operations** for multiple players
2. **Enable caching** for repeated lookups (300s recommended)
3. **Set context once** at start of run
4. **Flush once** at end of run
5. **Use required=False** for analytics (continue on missing)
6. **Use required=True** for critical data (fail fast on missing)

## Migration Checklist

When migrating existing processor to use RegistryReader:

- [ ] Add `from shared.utils.player_registry import RegistryReader`
- [ ] Create RegistryReader instance in `__init__`
- [ ] Replace direct BigQuery player queries with `registry.get_universal_id()`
- [ ] Add `registry.set_default_context()` at start of run
- [ ] Add `registry.flush_unresolved_players()` at end of run
- [ ] Update schema to use `universal_player_id` instead of `player_lookup`
- [ ] Add error handling for `PlayerNotFoundError`
- [ ] Consider using batch operations for efficiency
- [ ] Test with both existing and new players
- [ ] Monitor unresolved_player_names table

## Testing

```python
import unittest
from unittest.mock import Mock, patch
from shared.utils.player_registry import RegistryReader

class TestMyProcessor(unittest.TestCase):
    @patch('shared.utils.player_registry.reader.bigquery.Client')
    def test_process_with_registry(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock registry response
        import pandas as pd
        mock_df = pd.DataFrame([{'universal_player_id': 'test_001'}])
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        mock_client.query.return_value = mock_query_job
        
        # Test processor
        processor = MyProcessor()
        result = processor.process_data(test_data)
        
        self.assertIsNotNone(result)
```

## Monitoring

Check unresolved players regularly:

```sql
-- View recent unresolved players
SELECT 
    source,
    normalized_lookup,
    team_abbr,
    season,
    occurrences,
    first_seen_date,
    last_seen_date,
    status
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
  AND first_seen_date >= CURRENT_DATE() - 7
ORDER BY occurrences DESC, last_seen_date DESC
LIMIT 50;
```