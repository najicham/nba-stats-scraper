# ESPN Virtual Source Pattern

## Overview

The ESPN boxscores data presents a unique pattern in our fallback chain system: a single scraped table (`espn_boxscores`) contains **both player-level and team-level** data, which we then treat as separate virtual sources for different chains.

## Data Structure

### Source Table: `nba_raw.espn_boxscores`

The `espn_game_boxscore` scraper produces rows with this structure:

```
┌─────────────────┬───────────────┬──────────────────┐
│ player_lookup   │ team_abbr     │ points, rebs...  │
├─────────────────┼───────────────┼──────────────────┤
│ stephencurry    │ GSW           │ 31, 5, 8...      │  ← Player row
│ NULL            │ GSW           │ 121, 45, 26...   │  ← Team totals row
│ NULL            │ LAL           │ 114, 42, 22...   │  ← Team totals row
└─────────────────┴───────────────┴──────────────────┘
```

**Key insight**: Team totals are identified by `player_lookup IS NULL AND team_abbr IS NOT NULL`.

## Virtual Sources

### 1. `espn_boxscores` (Player Data)

- **Chain**: `player_boxscores`
- **Filter**: `player_lookup IS NOT NULL`
- **Used by**: `PlayerGameSummaryProcessor` as fallback to gamebook/BDL

### 2. `espn_team_boxscore` (Team Data) - VIRTUAL

- **Chain**: `team_boxscores`
- **Filter**: `player_lookup IS NULL AND team_abbr IS NOT NULL`
- **Virtual**: Yes - extracted from the same `espn_boxscores` table
- **Used by**: `TeamDefenseGameSummaryProcessor`, `TeamOffenseGameSummaryProcessor`

## Configuration

### In `fallback_config.yaml`:

```yaml
sources:
  espn_boxscores:
    description: "ESPN game boxscores (players + teams)"
    table: espn_boxscores
    dataset: nba_raw
    is_primary: false
    is_virtual: false  # ← Actual scraped table

  espn_team_boxscore:
    description: "Team stats extracted from ESPN boxscores"
    table: espn_boxscores  # ← Same table!
    dataset: nba_raw
    is_virtual: true  # ← Virtual source
    extraction_method: extract_team_rows
```

### In `chain_config.py`:

```python
VIRTUAL_SOURCE_DEPENDENCIES = {
    'espn_team_boxscore': 'player_boxscores',  # ← Depends on player chain
}
```

## Validation Behavior

### Chain Validation Order

The `CHAIN_VALIDATION_ORDER` ensures `player_boxscores` is validated **before** `team_boxscores`:

```python
CHAIN_VALIDATION_ORDER = [
    'game_schedule',      # No dependencies
    'player_boxscores',   # Contains espn_boxscores
    'team_boxscores',     # Contains espn_team_boxscore (virtual)
    ...
]
```

### Virtual Source Availability Check

When validating `team_boxscores`, the chain validator:

1. Sees `espn_team_boxscore` is marked `is_virtual: true`
2. Calls `_check_virtual_source_available('espn_team_boxscore', validated_chains)`
3. Looks up dependency: `VIRTUAL_SOURCE_DEPENDENCIES['espn_team_boxscore']` → `'player_boxscores'`
4. Checks if `validated_chains['player_boxscores'].status` is `'complete'` or `'partial'`
5. If yes → virtual source is "available" (can provide data)
6. If no → virtual source status set to `'virtual_unavailable'`

### Why This Matters

**Without this logic**: If gamebook and BDL are missing but ESPN has data:
- `espn_boxscores` provides player data → `player_boxscores` chain is complete
- `espn_team_boxscore` could provide team data → but only if we know player chain has it

**The dependency check ensures**: We don't count `espn_team_boxscore` as "available" unless we've confirmed the underlying `espn_boxscores` table actually has data for this date.

## Extraction Method (Processor-Side)

When a processor uses this fallback, it extracts team rows with:

```sql
SELECT *
FROM `nba_raw.espn_boxscores`
WHERE game_date = @game_date
  AND player_lookup IS NULL
  AND team_abbr IS NOT NULL
```

This is documented in `reconstruction_methods.extract_team_rows` in the YAML config.

## Similar Pattern: `reconstructed_team_from_players`

Another virtual source in `team_boxscores` chain:

```yaml
reconstructed_team_from_players:
  is_virtual: true
  reconstruction_method: aggregate_player_stats_to_team
```

This aggregates player stats to derive team totals mathematically. The dependency logic is the same:

```python
VIRTUAL_SOURCE_DEPENDENCIES = {
    'reconstructed_team_from_players': 'player_boxscores',
}
```

## Summary

| Source | Table | Virtual? | Dependency |
|--------|-------|----------|------------|
| `espn_boxscores` | `espn_boxscores` | No | None |
| `espn_team_boxscore` | `espn_boxscores` | Yes | `player_boxscores` chain |
| `reconstructed_team_from_players` | N/A (computed) | Yes | `player_boxscores` chain |

The virtual source pattern allows us to:
1. Model logical data sources separately from physical tables
2. Express dependencies between sources clearly
3. Validate availability correctly without querying the same table twice
