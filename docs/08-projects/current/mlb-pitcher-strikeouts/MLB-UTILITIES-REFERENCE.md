# MLB Utilities Reference

**Created:** 2026-01-13
**Status:** Complete - Ready for Use

## Overview

This document describes the MLB-specific utilities created to support pitcher strikeout
predictions and future MLB betting models. These utilities mirror the NBA infrastructure
and provide consistent player identification, team mapping, and analytics support.

## Utilities Summary

| Utility | Location | Purpose |
|---------|----------|---------|
| MLB Team Mapper | `shared/utils/mlb_team_mapper.py` | Team code normalization, stadium data |
| MLB Game ID Converter | `shared/utils/mlb_game_id_converter.py` | Game ID standardization |
| MLB Player Registry | `shared/utils/mlb_player_registry/` | Universal player ID system |
| MLB Travel Info | `shared/utils/mlb_travel_info.py` | Stadium and travel analytics |

## 1. MLB Team Mapper

### Purpose
Normalize team codes across data sources (Statcast, ESPN, Odds API, Ball Don't Lie).

### Features
- All 30 MLB teams with complete metadata
- Multiple code systems (MLB, ESPN, Statcast, BR)
- Fuzzy matching for typos
- Stadium data (dimensions, park factors, location)
- League/division structure

### Usage

```python
from shared.utils.mlb_team_mapper import (
    get_mlb_team_mapper,
    normalize_mlb_team,
    get_mlb_team_info
)

# Get singleton mapper
mapper = get_mlb_team_mapper()

# Normalize any team identifier
code = normalize_mlb_team("Yankees")  # Returns "NYY"
code = normalize_mlb_team("TBR")      # Returns "TB"

# Get full team info
team = get_mlb_team_info("NYY")
print(team.full_name)        # "New York Yankees"
print(team.stadium_name)     # "Yankee Stadium"
print(team.park_factor_hr)   # 1.15

# Fuzzy match
team = mapper.fuzzy_match("yanks")  # Finds Yankees

# Get teams by division
al_east = mapper.get_teams_by_division("AL East")
```

### Team Codes Supported

| Primary | Alternates | Team |
|---------|------------|------|
| NYY | NY, NYA | New York Yankees |
| NYM | NYN | New York Mets |
| LAD | LA, LAN | Los Angeles Dodgers |
| LAA | ANA, CAL | Los Angeles Angels |
| TB | TBR, TAM | Tampa Bay Rays |
| CWS | CHW | Chicago White Sox |
| KC | KCR | Kansas City Royals |
| SF | SFG | San Francisco Giants |
| SD | SDP | San Diego Padres |
| WSH | WSN, WAS | Washington Nationals |

## 2. MLB Game ID Converter

### Purpose
Standardize game IDs across sources to format: `YYYYMMDD_AWAY_HOME`

### Features
- Multiple input format support
- Doubleheader handling (`_1`, `_2` suffix)
- Validation against valid team codes
- Date extraction utilities

### Usage

```python
from shared.utils.mlb_game_id_converter import (
    MLBGameIdConverter,
    standardize_mlb_game_id,
    create_mlb_game_id,
    validate_mlb_game_id
)

converter = MLBGameIdConverter()

# Standardize various formats
standardize_mlb_game_id("2024-06-15_NYY@BOS")   # "20240615_NYY_BOS"
standardize_mlb_game_id("20240615-NYY-BOS")     # "20240615_NYY_BOS"

# Create game ID
game_id = create_mlb_game_id("2024-06-15", "NYY", "BOS")
# Returns: "20240615_NYY_BOS"

# Doubleheader
game1 = create_mlb_game_id("2024-06-15", "NYY", "BOS", game_number=1)
# Returns: "20240615_NYY_BOS_1"

# Parse components
parsed = converter.parse("20240615_NYY_BOS")
print(parsed.game_date)    # date(2024, 6, 15)
print(parsed.away_team)    # "NYY"
print(parsed.home_team)    # "BOS"

# Validate
is_valid = validate_mlb_game_id("20240615_NYY_BOS")  # True
```

## 3. MLB Player Registry

### Purpose
Universal player ID system for consistent player identification across all data sources.

### Components

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `resolver.py` | Create/resolve universal IDs (write side) |
| `reader.py` | Read-only access with caching (read side) |
| `exceptions.py` | Custom exceptions |

### BigQuery Tables

Created in `mlb_reference` dataset:

| Table | Purpose |
|-------|---------|
| `mlb_players_registry` | Main player registry |
| `mlb_player_aliases` | Name variations |
| `mlb_unresolved_players` | Tracking for manual review |

### Views

| View | Purpose |
|------|---------|
| `mlb_active_pitchers` | Pitchers active in last 30 days |
| `mlb_active_batters` | Batters active in last 30 days |
| `mlb_high_k_pitchers` | High-strikeout pitchers |

### Usage

```python
from shared.utils.mlb_player_registry import (
    MLBRegistryReader,
    MLBPlayerIDResolver,
    MLBPlayerNotFoundError
)
from google.cloud import bigquery

# READER (for analytics/predictions)
registry = MLBRegistryReader(
    source_name='pitcher_strikeouts_predictor',
    cache_ttl_seconds=300
)

# Strict lookup (raises exception if not found)
try:
    uid = registry.get_universal_id('loganwebb', player_type='pitcher')
except MLBPlayerNotFoundError:
    print("Player not found")

# Lenient lookup (returns None if not found)
uid = registry.get_universal_id('unknownplayer', required=False)

# Batch lookup
pitchers = ['loganwebb', 'gerritcole', 'corbinburnes']
uid_map = registry.get_universal_ids_batch(pitchers, player_type='pitcher')

# RESOLVER (for processors that create new entries)
bq_client = bigquery.Client()
resolver = MLBPlayerIDResolver(bq_client, 'nba-props-platform')

# Create or resolve ID
uid = resolver.resolve_or_create('loganwebb', player_type='pitcher')
```

### Universal ID Format

Format: `{normalized_name}_{sequence}`

Examples:
- `loganwebb_001` - First Logan Webb
- `loganwebb_002` - If there were another Logan Webb

## 4. MLB Travel Info

### Purpose
Stadium data and travel analytics for fatigue modeling.

### Features
- Stadium coordinates (lat/long)
- Distance calculations (Haversine)
- Park factors
- Timezone tracking
- Travel impact analysis

### Usage

```python
from shared.utils.mlb_travel_info import (
    get_mlb_stadium_info,
    calculate_travel_distance,
    get_timezone_for_team,
    get_hitter_friendly_parks,
    get_pitcher_friendly_parks,
    get_travel_schedule_impact
)

# Stadium info
info = get_mlb_stadium_info("NYY")
print(info.stadium_name)      # "Yankee Stadium"
print(info.park_factor_hr)    # 1.15
print(info.roof_type)         # "Open"

# Travel distance
distance = calculate_travel_distance("NYY", "LAD")
print(f"{distance:.0f} miles")  # ~2451 miles

# Park analysis
hitter_parks = get_hitter_friendly_parks()
for park in hitter_parks[:3]:
    print(f"{park.stadium_name}: {park.park_factor_runs}")

# Travel impact for road trip
impact = get_travel_schedule_impact("NYY", ["BOS", "TOR", "TB"])
print(f"Total distance: {impact['total_distance_miles']} miles")
print(f"Timezone changes: {impact['timezone_changes']}")
```

### Park Factors Reference

| Stadium | Runs Factor | HR Factor | Notes |
|---------|-------------|-----------|-------|
| Coors Field (COL) | 1.25 | 1.35 | Highest in MLB (altitude) |
| Great American (CIN) | 1.12 | 1.25 | Small park |
| Citizens Bank (PHI) | 1.08 | 1.15 | Hitter friendly |
| Oracle Park (SF) | 0.90 | 0.82 | Pitcher friendly |
| Tropicana (TB) | 0.92 | 0.88 | Dome, pitcher friendly |

## Setup Script

To initialize the BigQuery tables:

```bash
# Create all tables and views
python scripts/mlb/setup/create_mlb_registry_tables.py

# Dry run (show SQL only)
python scripts/mlb/setup/create_mlb_registry_tables.py --dry-run
```

## Comparison with NBA Utilities

| Feature | NBA | MLB |
|---------|-----|-----|
| Team Mapper | `nba_team_mapper.py` | `mlb_team_mapper.py` |
| Game ID | `game_id_converter.py` | `mlb_game_id_converter.py` |
| Player Registry | `player_registry/` | `mlb_player_registry/` |
| Travel Info | `travel_team_info.py` | `mlb_travel_info.py` |
| Team Count | 30 | 30 |
| Season Format | "2024-25" | 2024 |
| Division Structure | 6 divisions | 6 divisions |

## Integration Points

### Prediction Pipeline

```python
from shared.utils.mlb_team_mapper import normalize_mlb_team
from shared.utils.mlb_player_registry import MLBRegistryReader

# In prediction code
team = normalize_mlb_team(raw_team_name)
registry = MLBRegistryReader('predictions')
uid = registry.get_universal_id(pitcher_lookup, player_type='pitcher')
```

### Historical Odds Matching

The `match_lines_to_predictions.py` script uses name normalization
to match odds data to predictions. See `PLAYER-NAME-MATCHING-GUIDE.md`.

### Future: Batter Props

The player registry supports both PITCHER and BATTER types,
ready for future batter strikeout prop predictions.

## Related Documentation

- `PLAYER-NAME-MATCHING-GUIDE.md` - Name normalization details
- `FORWARD-VALIDATION-PIPELINE-DESIGN.md` - Live betting pipeline
- `ENHANCED-ANALYSIS-SCRIPTS.md` - Analysis scripts
- `2026-01-13-SESSION-37-HANDOFF-VALIDATION-FIXES.md` - Session handoff
