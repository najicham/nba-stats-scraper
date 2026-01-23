# Data Model: Schema Specifications

**Document:** 05-DATA-MODEL.md
**Created:** January 22, 2026

---

## Overview

This document specifies all schema changes, data structures, and type definitions for the data cascade architecture.

---

## Schema Change: ml_feature_store_v2

### New Column: historical_completeness

```sql
-- Migration script
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<
    -- Core counts
    games_found INT64,                        -- Actual games in window
    games_expected INT64,                     -- Expected games from schedule
    completeness_pct FLOAT64,                 -- games_found / games_expected * 100

    -- Game date arrays (lineage tracking)
    contributing_game_dates ARRAY<DATE>,      -- Dates of games actually used
    missing_game_dates ARRAY<DATE>,           -- Dates that should have data but don't

    -- Window metrics
    window_span_days INT64,                   -- Days from oldest to newest game
    oldest_game_date DATE,                    -- Oldest game in window
    newest_game_date DATE,                    -- Newest game in window

    -- Status flags
    is_complete BOOL,                         -- True if 100% complete
    is_reliable BOOL,                         -- True if >= 80% complete
    is_stale BOOL,                            -- True if window_span > 21 days

    -- Context flags
    is_new_player BOOL,                       -- First career games
    is_early_season BOOL,                     -- < 10 games available in season
    teams_in_window ARRAY<STRING>,            -- Track trades (e.g., ['LAL', 'BOS'])

    -- Reprocessing tracking
    needs_reprocessing BOOL,                  -- Flag for cascade re-run
    incompleteness_reason STRING              -- 'missing_games', 'new_player', 'stale_window', etc.
>;
```

### Field Specifications

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `games_found` | INT64 | Count of games retrieved | 8 |
| `games_expected` | INT64 | Count of games that should exist | 10 |
| `completeness_pct` | FLOAT64 | Percentage complete | 80.0 |
| `contributing_game_dates` | ARRAY<DATE> | Dates of games used | ['2026-01-20', '2026-01-18', ...] |
| `missing_game_dates` | ARRAY<DATE> | Dates that are missing | ['2026-01-01', '2026-01-05'] |
| `window_span_days` | INT64 | Days from oldest to newest | 21 |
| `oldest_game_date` | DATE | Oldest game in window | 2026-01-01 |
| `newest_game_date` | DATE | Newest game in window | 2026-01-20 |
| `is_complete` | BOOL | 100% complete flag | False |
| `is_reliable` | BOOL | >= 80% complete flag | True |
| `is_stale` | BOOL | Window too wide flag | False |
| `is_new_player` | BOOL | First career games | False |
| `is_early_season` | BOOL | < 10 games available | False |
| `teams_in_window` | ARRAY<STRING> | Teams player was on | ['LAL'] |
| `needs_reprocessing` | BOOL | Cascade re-run needed | True |
| `incompleteness_reason` | STRING | Why incomplete | 'missing_games' |

### Completeness Reason Values

| Value | Description |
|-------|-------------|
| `null` | Feature is complete |
| `'missing_games'` | Expected games not in source data |
| `'new_player'` | Player's first career game(s) |
| `'stale_window'` | Window spans too many days |
| `'no_data'` | No games found at all |
| `'early_season'` | Season just started, fewer games available |
| `'dnp_excluded'` | Games excluded due to DNP status |

---

## Python Data Classes

### WindowValidationResult

```python
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

@dataclass
class WindowValidationResult:
    """Result of validating a player's historical data window."""

    # Core counts
    games_found: int
    games_expected: int

    # Game date lists
    contributing_game_dates: List[date] = field(default_factory=list)
    missing_game_dates: List[date] = field(default_factory=list)

    # Window metrics
    window_span_days: int = 0
    oldest_game_date: Optional[date] = None
    newest_game_date: Optional[date] = None

    # Status flags
    is_complete: bool = False
    is_reliable: bool = False
    is_stale: bool = False

    # Context flags
    is_new_player: bool = False
    is_early_season: bool = False
    teams_in_window: List[str] = field(default_factory=list)

    # Reprocessing
    needs_reprocessing: bool = False
    incompleteness_reason: Optional[str] = None

    @property
    def completeness_pct(self) -> float:
        """Calculate completeness percentage."""
        if self.games_expected == 0:
            return 100.0  # New player - technically complete
        return (self.games_found / self.games_expected) * 100

    def to_bq_struct(self) -> dict:
        """Convert to BigQuery STRUCT format."""
        return {
            'games_found': self.games_found,
            'games_expected': self.games_expected,
            'completeness_pct': self.completeness_pct,
            'contributing_game_dates': [d.isoformat() for d in self.contributing_game_dates],
            'missing_game_dates': [d.isoformat() for d in self.missing_game_dates],
            'window_span_days': self.window_span_days,
            'oldest_game_date': self.oldest_game_date.isoformat() if self.oldest_game_date else None,
            'newest_game_date': self.newest_game_date.isoformat() if self.newest_game_date else None,
            'is_complete': self.is_complete,
            'is_reliable': self.is_reliable,
            'is_stale': self.is_stale,
            'is_new_player': self.is_new_player,
            'is_early_season': self.is_early_season,
            'teams_in_window': self.teams_in_window,
            'needs_reprocessing': self.needs_reprocessing,
            'incompleteness_reason': self.incompleteness_reason
        }
```

### DateCompletenessResult

```python
@dataclass
class TableCompleteness:
    """Completeness status for a single table."""
    table_name: str
    expected_dates: List[date]
    actual_dates: List[date]
    missing_dates: List[date]
    completeness_pct: float
    is_complete: bool


@dataclass
class DateCompletenessResult:
    """Result of checking historical completeness for a date."""

    target_date: date
    lookback_days: int
    tables: List[TableCompleteness]

    @property
    def is_complete(self) -> bool:
        """True if all tables are complete."""
        return all(t.is_complete for t in self.tables)

    @property
    def overall_completeness_pct(self) -> float:
        """Average completeness across all tables."""
        if not self.tables:
            return 100.0
        return sum(t.completeness_pct for t in self.tables) / len(self.tables)

    def get_all_missing_dates(self) -> List[date]:
        """Get all missing dates across all tables."""
        missing = set()
        for table in self.tables:
            missing.update(table.missing_dates)
        return sorted(missing)
```

### CascadeResult

```python
@dataclass
class CascadeResult:
    """Result of cascade detection."""

    backfilled_dates: List[date]
    affected_records: List[Tuple[date, str]]  # (game_date, player_lookup)

    @property
    def affected_dates(self) -> List[date]:
        """Get unique affected dates."""
        return sorted(set(r[0] for r in self.affected_records))

    @property
    def affected_players(self) -> List[str]:
        """Get unique affected players."""
        return sorted(set(r[1] for r in self.affected_records))

    @property
    def total_records(self) -> int:
        """Total records needing reprocessing."""
        return len(self.affected_records)

    def group_by_date(self) -> dict:
        """Group affected records by date."""
        grouped = {}
        for game_date, player in self.affected_records:
            if game_date not in grouped:
                grouped[game_date] = []
            grouped[game_date].append(player)
        return grouped
```

---

## Configuration: validation_config.yaml

```yaml
# shared/config/validation_config.yaml

historical_window:
  # Rolling window parameters
  default_window_size: 10          # Games for rolling average
  max_window_span_days: 21         # Alert if 10 games span > 21 days
  lookback_days: 60                # How far back to search for games

  # Completeness thresholds
  complete_threshold: 100          # Percentage for "complete" status
  reliable_threshold: 80           # Percentage for "reliable" status

  # Staleness detection
  stale_span_threshold: 21         # Days - window is stale if span exceeds this

cascade:
  # Forward impact calculation
  forward_impact_days: 21          # How far forward a backfill affects

  # Batch processing
  batch_size: 100                  # Players to process at once
  max_concurrent_dates: 5          # Dates to process in parallel

  # Safety limits
  max_affected_records: 50000      # Warn if cascade exceeds this

critical_tables:
  # Tables to check for historical completeness
  - name: nba_analytics.player_game_summary
    date_column: game_date
    entity_column: player_lookup
    priority: critical

  - name: nba_raw.nbac_team_boxscore
    date_column: game_date
    entity_column: team_abbr
    priority: critical

  - name: nba_analytics.team_defense_game_summary
    date_column: game_date
    entity_column: team_abbr
    priority: high

  - name: nba_precompute.player_daily_cache
    date_column: cache_date
    entity_column: player_lookup
    priority: high

early_season:
  # Bootstrap period handling
  bootstrap_days: 14               # First N days of season - relaxed rules
  min_games_for_reliable: 5        # Minimum games for reliable features

logging:
  # When to log warnings
  log_incomplete: true             # Log all incomplete features
  log_stale: true                  # Log all stale features
  log_new_player: false            # Don't log new players (expected)
  log_early_season: false          # Don't log early season (expected)
```

---

## Query Patterns

### Pattern 1: Find Incomplete Features for a Date Range

```sql
SELECT
    game_date,
    player_lookup,
    historical_completeness.games_found,
    historical_completeness.games_expected,
    historical_completeness.missing_game_dates
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN @start_date AND @end_date
  AND NOT historical_completeness.is_complete
ORDER BY game_date, player_lookup
```

### Pattern 2: Find Records Affected by Specific Missing Date

```sql
SELECT
    game_date,
    player_lookup
FROM `nba_predictions.ml_feature_store_v2`
WHERE DATE('2026-01-01') IN UNNEST(historical_completeness.missing_game_dates)
ORDER BY game_date
```

### Pattern 3: Daily Completeness Report

```sql
SELECT
    game_date,
    COUNT(*) as total,
    COUNTIF(historical_completeness.is_complete) as complete,
    COUNTIF(NOT historical_completeness.is_complete) as incomplete,
    ROUND(100.0 * COUNTIF(historical_completeness.is_complete) / COUNT(*), 2) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

### Pattern 4: Find All Players with Specific Missing Date

```sql
SELECT DISTINCT player_lookup
FROM `nba_predictions.ml_feature_store_v2`
WHERE DATE('2026-01-01') IN UNNEST(historical_completeness.missing_game_dates)
```

### Pattern 5: Calculate Cascade Scope

```sql
WITH backfill_dates AS (
    SELECT DATE('2026-01-01') as backfilled_date
    UNION ALL SELECT DATE('2026-01-02')
    UNION ALL SELECT DATE('2026-01-03')
)
SELECT
    bd.backfilled_date,
    DATE_ADD(bd.backfilled_date, INTERVAL 1 DAY) as cascade_start,
    DATE_ADD(bd.backfilled_date, INTERVAL 21 DAY) as cascade_end,
    MIN(DATE_ADD(bd.backfilled_date, INTERVAL 1 DAY)) OVER() as overall_start,
    MAX(DATE_ADD(bd.backfilled_date, INTERVAL 21 DAY)) OVER() as overall_end
FROM backfill_dates bd
```

---

## Migration Plan

### Step 1: Add Column (Non-Breaking)

```sql
-- Run once
ALTER TABLE `nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<...>;
```

### Step 2: Backfill Existing Records (Optional)

```sql
-- For existing records, set to "unknown" state
UPDATE `nba_predictions.ml_feature_store_v2`
SET historical_completeness = STRUCT(
    NULL as games_found,
    NULL as games_expected,
    NULL as completeness_pct,
    [] as contributing_game_dates,
    [] as missing_game_dates,
    NULL as window_span_days,
    NULL as oldest_game_date,
    NULL as newest_game_date,
    NULL as is_complete,
    NULL as is_reliable,
    NULL as is_stale,
    NULL as is_new_player,
    NULL as is_early_season,
    [] as teams_in_window,
    NULL as needs_reprocessing,
    'unknown_legacy' as incompleteness_reason
)
WHERE historical_completeness IS NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

### Step 3: Deploy Code Changes

1. Deploy `historical_window_validator.py`
2. Deploy modified `feature_extractor.py`
3. Deploy modified `ml_feature_store_processor.py`
4. New records will have completeness metadata

### Step 4: Verify

```sql
-- Check new records have metadata
SELECT
    game_date,
    COUNT(*) as total,
    COUNTIF(historical_completeness.games_found IS NOT NULL) as has_metadata
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= @deploy_date
GROUP BY game_date
ORDER BY game_date DESC
```

---

## Storage Impact

### Estimated Size Increase

| Field | Type | Bytes Per Record |
|-------|------|------------------|
| Scalar fields (counts, flags) | ~100 bytes | 100 |
| contributing_game_dates (10 dates) | ~80 bytes | 80 |
| missing_game_dates (avg 2 dates) | ~16 bytes | 16 |
| teams_in_window (avg 1.2 teams) | ~20 bytes | 20 |
| **Total** | | **~216 bytes** |

**Current record size:** ~2KB
**New record size:** ~2.2KB
**Increase:** ~10%

For 500 players × 365 days × 4 seasons = ~730,000 records
**Additional storage:** ~150 MB (negligible)

---

## Related Documents

- `04-SOLUTION-ARCHITECTURE.md` - How these structures are used
- `06-CASCADE-PROTOCOL.md` - Reprocessing workflow
- `07-IMPLEMENTATION-PLAN.md` - Rollout plan

---

**Document Status:** Complete
