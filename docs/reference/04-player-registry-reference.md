# NBA Player Registry Reference

**Created:** 2025-11-21 17:30:00 PST
**Last Updated:** 2025-11-21 17:30:00 PST

Quick reference for integrating with the NBA Player Registry system.

## Overview

**Purpose:** Universal player identification across all data sources

**Tables:**
- `nba_reference.nba_players_registry` - Authoritative player records
- `nba_reference.unresolved_player_names` - Unresolved player tracking
- `nba_reference.player_aliases` - Name variation mappings

**Key Concept:** One player = One `universal_player_id` across all team-season combinations

## Which Tool Do I Use?

### RegistryReader (Most Common)

**Use when:** Reading player data, analytics, reports, lookups

```python
from shared.utils.player_registry import RegistryReader

registry = RegistryReader(
    source_name='my_processor',
    cache_ttl_seconds=300
)
uid = registry.get_universal_id('lebronjames')
```

**Purpose:** Read-only access with caching

### UniversalPlayerIDResolver (Registry Processors Only)

**Use when:** Building/updating the registry itself

```python
from shared.utils.player_registry import UniversalPlayerIDResolver

resolver = UniversalPlayerIDResolver()
uid = resolver.resolve_or_create_universal_id('lebronjames')
```

**Purpose:** Creates/updates registry records

**Warning:** Only use in registry processors (`gamebook_registry_processor`, `roster_registry_processor`)

## Quick Start

### 5-Minute Integration

```python
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

class MyProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='my_processor',
            cache_ttl_seconds=300  # 5-minute cache
        )

    def process_data(self, season):
        # 1. Set context once at start
        self.registry.set_default_context(season=season)

        # 2. Get universal IDs
        uid = self.registry.get_universal_id(
            'lebronjames',
            required=False  # Lenient mode
        )

        if uid is None:
            return  # Skip unknown players

        # 3. Use in your records
        record = {
            'universal_player_id': uid,
            'points': 25
        }

    def finalize(self):
        # 4. Flush unresolved at end
        self.registry.flush_unresolved_players()
```

## Common Patterns

### Pattern 1: Analytics (Lenient)

**Use:** Player stats, general analytics - skip unknown players

```python
def process_games(self, games, season):
    self.registry.set_default_context(season=season)
    skipped = 0

    for game in games:
        for player_stat in game.player_stats:
            # Lenient - returns None if not found
            uid = self.registry.get_universal_id(
                player_stat.player_lookup,
                required=False
            )

            if uid is None:
                skipped += 1
                continue  # Skip, logged automatically

            # Process with valid uid
            self._save_summary(uid, player_stat)

    self.registry.flush_unresolved_players()
    logger.info(f"Skipped {skipped} unknown players")
```

### Pattern 2: Critical Data (Strict)

**Use:** Prop bets, financial data - must have valid IDs

```python
def process_prop_bets(self, prop_bets, season):
    self.registry.set_default_context(season=season)
    errors = []

    for prop_bet in prop_bets:
        try:
            # Strict - raises exception if not found
            uid = self.registry.get_universal_id(
                prop_bet.player_lookup,
                required=True
            )

            self._save_prop_bet(uid, prop_bet)

        except PlayerNotFoundError as e:
            errors.append(prop_bet.player_lookup)
            logger.error(f"Invalid prop bet: {e}")

    self.registry.flush_unresolved_players()

    if errors:
        notify_error(f"Failed {len(errors)} prop bets")
```

### Pattern 3: Batch Processing

**Use:** Large datasets - 100x faster than individual lookups

```python
def process_games_batch(self, games, season):
    self.registry.set_default_context(season=season)

    # Collect all unique players
    unique_players = set()
    for game in games:
        for player in game.players:
            unique_players.add(player.lookup)

    # Single batch query
    logger.info(f"Looking up {len(unique_players)} players")
    uid_map = self.registry.get_universal_ids_batch(
        list(unique_players)
    )
    logger.info(f"Found {len(uid_map)} players")

    # Process with pre-fetched mapping
    for game in games:
        for player in game.players:
            uid = uid_map.get(player.lookup)
            if uid:
                self._process_player(uid, player, game)

    self.registry.flush_unresolved_players()
```

**Performance:** 500 players in 1 second vs 50 seconds individually

### Pattern 4: Traded Players

**Use:** Handle players on multiple teams in same season

```python
from shared.utils.player_registry import MultipleRecordsError

def get_player_data(self, player_lookup, season):
    try:
        # Try without team first
        return self.registry.get_player(
            player_lookup,
            season=season
        )

    except MultipleRecordsError as e:
        # Player traded - get current team
        logger.info(f"{player_lookup} on multiple teams: {e.teams}")

        current_team = self.registry.get_current_team(
            player_lookup,
            season
        )

        return self.registry.get_player(
            player_lookup,
            season=season,
            team_abbr=current_team
        )
```

## Core API

### Get Universal ID (Most Common)

```python
# Lenient mode (analytics)
uid = registry.get_universal_id(
    'lebronjames',
    required=False  # Returns None if not found
)

# Strict mode (critical data)
uid = registry.get_universal_id(
    'lebronjames',
    required=True  # Raises PlayerNotFoundError
)

# With context
uid = registry.get_universal_id(
    'lebronjames',
    context={'game_id': '0022400089', 'team_abbr': 'LAL'}
)
```

### Get Player Record

```python
# Full player record
player = registry.get_player(
    'lebronjames',
    season='2024-25',      # Filter by season
    team_abbr='LAL',       # For traded players
    required=True
)

# Returns dict with:
# - universal_player_id
# - player_name
# - team_abbr
# - season
# - games_played
# - jersey_number
# - position
```

### Batch Operations

```python
# Batch universal IDs (recommended)
players = ['lebronjames', 'stephencurry', 'kevindurant']
uid_map = registry.get_universal_ids_batch(players)
# Returns: {'lebronjames': 'lebronjames_001', ...}

# Batch full records
records = registry.get_players_batch(players, season='2024-25')
# Returns: {'lebronjames': {full_record}, ...}
```

### Validation

```python
# Check existence
exists = registry.player_exists('lebronjames', season='2024-25')

# Validate player-team combo
valid = registry.validate_player_team(
    'lebronjames',
    'LAL',
    '2024-25'
)

# Get current team
team = registry.get_current_team('lebronjames', season='2024-25')
```

### Team Operations

```python
# Get team roster
roster = registry.get_team_roster('LAL', season='2024-25')

# Get all active teams
teams = registry.get_active_teams(season='2024-25')
```

### Search

```python
# Search by name pattern
results = registry.search_players('james', season='2024-25', limit=10)

# Convert display name to lookup
lookup = registry.lookup_by_display_name('LeBron James')
# Returns: 'lebronjames'
```

### Context & Cleanup

```python
# Set default context (once at start)
registry.set_default_context(season='2024-25', team_abbr='LAL')

# Flush unresolved players (once at end)
registry.flush_unresolved_players()

# Cache management
registry.clear_cache()
registry.clear_cache_for_player('lebronjames')
stats = registry.get_cache_stats()
```

## Error Handling

### Common Exceptions

```python
from shared.utils.player_registry import (
    PlayerNotFoundError,
    MultipleRecordsError,
    AmbiguousNameError,
    RegistryConnectionError
)

# Player not found
try:
    uid = registry.get_universal_id('unknownplayer', required=True)
except PlayerNotFoundError as e:
    logger.error(f"Player not found: {e.player_lookup}")
    # Logged to unresolved_player_names on flush

# Multiple teams (traded)
try:
    player = registry.get_player('jamesharden', season='2023-24')
except MultipleRecordsError as e:
    logger.warning(f"Multiple teams: {e.teams}")
    # Specify team_abbr parameter

# Ambiguous search
try:
    lookup = registry.lookup_by_display_name('James')
except AmbiguousNameError as e:
    logger.warning(f"Multiple matches: {e.matches}")

# Connection error
try:
    uid = registry.get_universal_id('lebronjames')
except RegistryConnectionError as e:
    logger.error(f"Database error: {e.original_error}")
```

### Error Strategy

**Analytics (Lenient):**
```python
uid = registry.get_universal_id(player, required=False)
if uid is None:
    continue  # Skip, logged automatically
```

**Critical Data (Strict):**
```python
try:
    uid = registry.get_universal_id(player, required=True)
except PlayerNotFoundError:
    raise ProcessingError("Missing required player")
```

## Best Practices

### ✅ DO

**Use batch operations:**
```python
# Good - 1 query
uids = registry.get_universal_ids_batch(all_players)

# Bad - N queries
for player in all_players:
    uid = registry.get_universal_id(player)
```

**Enable caching:**
```python
registry = RegistryReader(
    source_name='my_processor',
    cache_ttl_seconds=300  # 5 minutes
)
```

**Set context once:**
```python
def process_data(self, season):
    self.registry.set_default_context(season=season)
    # All subsequent calls include this
```

**Always flush:**
```python
def finalize(self):
    self.registry.flush_unresolved_players()
```

### ❌ DON'T

**Loop with individual queries:**
```python
# Bad - very slow
for player in players:
    uid = registry.get_universal_id(player)

# Good - fast
uids = registry.get_universal_ids_batch(players)
```

**Create multiple instances:**
```python
# Bad - no cache sharing
for game in games:
    registry = RegistryReader(...)  # Don't recreate!

# Good - reuse instance
registry = RegistryReader(...)
for game in games:
    # Use same instance
```

**Ignore unresolved players:**
```python
# Bad - no tracking
uid = registry.get_universal_id(player, required=False)
# Never call flush_unresolved_players()

# Good - track and review
uid = registry.get_universal_id(player, required=False)
# At end: registry.flush_unresolved_players()
```

## Troubleshooting

### High Unresolved Count

**Check unresolved players:**
```sql
SELECT
    source,
    normalized_lookup,
    team_abbr,
    occurrences,
    first_seen_date
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
  AND first_seen_date >= CURRENT_DATE() - 7
ORDER BY occurrences DESC
LIMIT 50;
```

**Common causes:**
- Name variations (create aliases)
- New players (wait for registry update)
- Data source changes (update normalizer)

### Slow Performance

**Check cache stats:**
```python
stats = registry.get_cache_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Cache size: {stats['cache_size']}")
```

**Solutions:**
- Enable caching (`cache_ttl_seconds=300`)
- Use batch operations
- Add season filter to queries

### Stale Cache

**Solutions:**
```python
# Reduce cache TTL
registry = RegistryReader(cache_ttl_seconds=60)

# Clear cache manually
registry.clear_cache()

# Clear for specific player
registry.clear_cache_for_player('lebronjames')
```

## Registry Tables

### nba_players_registry

```sql
-- Primary table
CREATE TABLE nba_reference.nba_players_registry (
    player_name STRING,              -- Display name
    player_lookup STRING,            -- Normalized: "lebronjames"
    universal_player_id STRING,      -- Unique: "lebronjames_001"
    team_abbr STRING,                -- Team code
    season STRING,                   -- Format: "2024-25"

    first_game_date DATE,            -- First appearance
    last_game_date DATE,             -- Last appearance
    games_played INT64,              -- Active games
    total_appearances INT64,         -- All gamebook entries

    jersey_number INT64,
    position STRING,

    source_priority STRING,          -- "nba_gamebook", etc.
    confidence_score FLOAT64,        -- 0.7-1.0
    processed_at TIMESTAMP
)
PARTITION BY season
CLUSTER BY player_lookup, team_abbr, season;
```

### unresolved_player_names

```sql
-- Tracks unknown players
CREATE TABLE nba_reference.unresolved_player_names (
    source STRING,                   -- Processor name
    normalized_lookup STRING,        -- Player lookup attempted
    team_abbr STRING,
    season STRING,

    occurrences INT64,               -- How many times seen
    first_seen_date DATE,
    last_seen_date DATE,

    status STRING,                   -- "pending", "resolved", "invalid"
    resolution_notes STRING,
    processed_at TIMESTAMP
);
```

## Monitoring

```sql
-- Processing with registry
SELECT
  processor_name,
  COUNT(*) as total_records,
  COUNT(universal_player_id) as with_uid,
  COUNT(*) - COUNT(universal_player_id) as missing_uid
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY processor_name;

-- Unresolved trends
SELECT
  source,
  COUNT(DISTINCT normalized_lookup) as unique_players,
  SUM(occurrences) as total_occurrences
FROM nba_reference.unresolved_player_names
WHERE status = 'pending'
  AND first_seen_date >= CURRENT_DATE() - 7
GROUP BY source
ORDER BY total_occurrences DESC;
```

## Files

**Registry System:**
- `shared/utils/player_registry/reader.py` - RegistryReader
- `shared/utils/player_registry/resolver.py` - UniversalPlayerIDResolver
- `shared/utils/player_registry/exceptions.py` - Custom exceptions

**Registry Processors:**
- `data_processors/reference/player_reference/gamebook_registry_processor.py`
- `data_processors/reference/player_reference/roster_registry_processor.py`

**Schemas:**
- `schemas/bigquery/nba_reference/nba_players_registry.sql`
- `schemas/bigquery/nba_reference/unresolved_player_names.sql`

## See Also

- [Analytics Processors Reference](03-analytics-processors-reference.md)
- [Processors Reference](02-processors-reference.md)
