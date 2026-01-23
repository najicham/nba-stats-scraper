# Solution Architecture: Historical Completeness Tracking

**Document:** 04-SOLUTION-ARCHITECTURE.md
**Created:** January 22, 2026

---

## Design Principles

1. **100% Completeness Target:** Flag anything less than complete
2. **Flag, Don't Block:** Allow processing but track issues
3. **Full Lineage:** Know exactly what data contributed to each calculation
4. **Easy Remediation:** After backfill, know exactly what to re-run
5. **Observable:** Daily metrics on completeness across the pipeline

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW WITH COMPLETENESS                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────────┐  │
│  │   Schedule  │    │   Roster    │    │     player_game_summary         │  │
│  │   (expected │    │   (current  │    │     (actual games)              │  │
│  │    games)   │    │    team)    │    │                                 │  │
│  └──────┬──────┘    └──────┬──────┘    └───────────────┬─────────────────┘  │
│         │                  │                           │                     │
│         └──────────────────┼───────────────────────────┘                     │
│                            │                                                 │
│                            ▼                                                 │
│              ┌─────────────────────────────┐                                 │
│              │  COMPLETENESS CALCULATOR    │                                 │
│              │                             │                                 │
│              │  • Expected games (schedule)│                                 │
│              │  • Actual games (found)     │                                 │
│              │  • Missing dates            │                                 │
│              │  • Window span              │                                 │
│              │  • Staleness detection      │                                 │
│              └──────────────┬──────────────┘                                 │
│                             │                                                │
│                             ▼                                                │
│              ┌─────────────────────────────┐                                 │
│              │    FEATURE GENERATOR        │                                 │
│              │                             │                                 │
│              │  • Generate features        │                                 │
│              │  • Attach completeness      │                                 │
│              │    metadata                 │                                 │
│              │  • Log if incomplete        │                                 │
│              └──────────────┬──────────────┘                                 │
│                             │                                                │
│                             ▼                                                │
│              ┌─────────────────────────────┐                                 │
│              │   ml_feature_store_v2       │                                 │
│              │                             │                                 │
│              │  • Features + metadata      │                                 │
│              │  • historical_completeness  │                                 │
│              │    struct                   │                                 │
│              └──────────────┬──────────────┘                                 │
│                             │                                                │
│                             ▼                                                │
│              ┌─────────────────────────────┐                                 │
│              │   PREDICTION COORDINATOR    │                                 │
│              │                             │                                 │
│              │  • Can filter on            │                                 │
│              │    is_complete = True       │                                 │
│              │  • Or generate with flag    │                                 │
│              └─────────────────────────────┘                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component 1: Historical Window Validator

**Purpose:** Calculate completeness for a player's rolling window.

**Location:** `shared/validation/historical_window_validator.py` (NEW)

### Class Design

```python
class HistoricalWindowValidator:
    """
    Validates that historical data windows are complete before/during processing.

    This is the core component that answers: "Do we have all the data we need
    to calculate rolling averages for this player on this date?"
    """

    # Configuration
    DEFAULT_WINDOW_SIZE = 10          # Games for rolling average
    MAX_WINDOW_SPAN_DAYS = 21         # 10 games shouldn't span > 3 weeks
    LOOKBACK_DAYS = 60                # How far back to search for games

    def __init__(self, bq_client: bigquery.Client):
        self.client = bq_client
        self._schedule_cache = {}     # Cache schedule queries
        self._roster_cache = {}       # Cache roster lookups

    def validate_player_window(
        self,
        player_lookup: str,
        target_date: date,
        window_size: int = 10
    ) -> WindowValidationResult:
        """
        Validate a single player's rolling window completeness.

        Returns:
            WindowValidationResult with:
            - games_found: int
            - games_expected: int
            - contributing_game_dates: List[date]
            - missing_game_dates: List[date]
            - window_span_days: int
            - is_complete: bool (100% of expected games)
            - is_reliable: bool (>=80% of expected games)
            - is_stale: bool (span > 21 days)
            - incompleteness_reason: Optional[str]
        """
        pass

    def validate_player_window_batch(
        self,
        player_lookups: List[str],
        target_date: date,
        window_size: int = 10
    ) -> Dict[str, WindowValidationResult]:
        """
        Validate windows for multiple players in a single query.
        Much more efficient than per-player validation.

        Returns:
            Dict mapping player_lookup to WindowValidationResult
        """
        pass

    def validate_date_historical_completeness(
        self,
        target_date: date,
        critical_tables: List[str] = None,
        lookback_days: int = 7
    ) -> DateCompletenessResult:
        """
        Check if critical tables have data for recent historical dates.

        Used for pre-flight checks before processing.

        Returns:
            DateCompletenessResult with per-table status
        """
        pass
```

### Validation Result Structure

```python
@dataclass
class WindowValidationResult:
    """Result of validating a player's rolling window."""

    # Core counts
    games_found: int                      # How many games we have
    games_expected: int                   # How many we should have

    # Game lists (for lineage tracking)
    contributing_game_dates: List[date]   # Dates of games we're using
    missing_game_dates: List[date]        # Dates we should have but don't

    # Window metrics
    window_span_days: int                 # Days from oldest to newest game
    oldest_game_date: Optional[date]
    newest_game_date: Optional[date]

    # Status flags
    is_complete: bool                     # 100% complete (games_found == games_expected)
    is_reliable: bool                     # >=80% complete (usable but flagged)
    is_stale: bool                        # Window spans too many days

    # Context
    is_new_player: bool                   # First career games
    is_early_season: bool                 # Less than window_size games in season
    is_injury_return: bool                # Long gap due to injury
    teams_in_window: List[str]            # Track trades

    # Reason for incompleteness
    incompleteness_reason: Optional[str]  # 'missing_data', 'dnp', 'new_player', etc.

    @property
    def completeness_pct(self) -> float:
        if self.games_expected == 0:
            return 100.0  # New player - technically complete
        return (self.games_found / self.games_expected) * 100
```

---

## Component 2: Feature Metadata Structure

**Purpose:** Store completeness information with each feature record.

**Location:** Schema change to `ml_feature_store_v2`

### Schema Addition

```sql
-- Add to ml_feature_store_v2
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<
    -- Core counts
    games_found INT64,
    games_expected INT64,
    completeness_pct FLOAT64,

    -- Game lists (lineage)
    contributing_game_dates ARRAY<DATE>,
    missing_game_dates ARRAY<DATE>,

    -- Window metrics
    window_span_days INT64,
    oldest_game_date DATE,
    newest_game_date DATE,

    -- Status flags
    is_complete BOOL,
    is_reliable BOOL,
    is_stale BOOL,

    -- Context
    is_new_player BOOL,
    is_early_season BOOL,
    teams_in_window ARRAY<STRING>,

    -- For cascade reprocessing
    needs_reprocessing BOOL,
    incompleteness_reason STRING
>;
```

### Indexing Considerations

```sql
-- Create index for incomplete feature queries
CREATE INDEX IF NOT EXISTS idx_incomplete_features
ON nba_predictions.ml_feature_store_v2(game_date)
WHERE NOT historical_completeness.is_complete;

-- Partition by game_date for efficient date-range queries
-- (Already partitioned in existing schema)
```

---

## Component 3: Modified Feature Extractor

**Purpose:** Track game dates during extraction for lineage.

**Location:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

### Changes to `_batch_extract_last_10_games()`

```python
def _batch_extract_last_10_games_with_completeness(self, game_date):
    """
    Extract last 10 games for all players, WITH game date tracking.

    Returns:
        Dict[player_lookup, Dict]:
            'games': List of game records
            'game_dates': List of dates used
            'games_found': Count of games
            'window_span_days': Days from oldest to newest
            'oldest_game': Oldest game date
            'newest_game': Newest game date
    """
    query = f"""
    WITH player_games AS (
        SELECT
            player_lookup,
            game_date,
            points,
            minutes_played,
            ft_makes,
            fg_attempts,
            paint_attempts,
            mid_range_attempts,
            three_pt_attempts,
            team_abbr,
            ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY game_date DESC
            ) as game_num
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date < @target_date
          AND game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
    ),
    player_stats AS (
        SELECT
            player_lookup,
            COUNT(*) as games_found,
            MIN(game_date) as oldest_game,
            MAX(game_date) as newest_game,
            DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as window_span_days,
            ARRAY_AGG(game_date ORDER BY game_date DESC) as game_dates,
            ARRAY_AGG(DISTINCT team_abbr) as teams_in_window
        FROM player_games
        WHERE game_num <= 10
        GROUP BY player_lookup
    )
    SELECT
        pg.*,
        ps.games_found,
        ps.oldest_game,
        ps.newest_game,
        ps.window_span_days,
        ps.game_dates,
        ps.teams_in_window
    FROM player_games pg
    JOIN player_stats ps USING (player_lookup)
    WHERE pg.game_num <= 10
    ORDER BY pg.player_lookup, pg.game_date DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", game_date),
        ]
    )

    results = self.client.query(query, job_config=job_config)

    # Group by player and extract both games and metadata
    player_data = {}
    for row in results:
        player = row.player_lookup
        if player not in player_data:
            player_data[player] = {
                'games': [],
                'game_dates': row.game_dates,
                'games_found': row.games_found,
                'window_span_days': row.window_span_days,
                'oldest_game': row.oldest_game,
                'newest_game': row.newest_game,
                'teams_in_window': row.teams_in_window
            }
        player_data[player]['games'].append(dict(row))

    return player_data
```

---

## Component 4: Modified Feature Store Processor

**Purpose:** Integrate completeness validation into feature generation.

**Location:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

### Integration Point

```python
class MLFeatureStoreProcessor:

    def __init__(self, ...):
        # ... existing init ...
        self.window_validator = HistoricalWindowValidator(self.bq_client)

    def _generate_player_features(
        self,
        player_lookup: str,
        game_date: date,
        extraction_data: Dict
    ) -> Dict:
        """Generate features with completeness metadata."""

        # Get extraction metadata
        player_extraction = extraction_data.get(player_lookup, {})

        # Build completeness metadata
        completeness = self._build_completeness_metadata(
            player_lookup=player_lookup,
            game_date=game_date,
            extraction_data=player_extraction
        )

        # Log if incomplete
        if not completeness['is_complete']:
            self.logger.warning(
                f"Incomplete window for {player_lookup} on {game_date}: "
                f"{completeness['games_found']}/{completeness['games_expected']} games "
                f"({completeness['completeness_pct']:.1f}%) - "
                f"Reason: {completeness['incompleteness_reason']}"
            )

        # Generate features (existing logic)
        features = self._calculate_features(player_lookup, game_date, extraction_data)

        # Attach completeness metadata
        features['historical_completeness'] = completeness

        return features

    def _build_completeness_metadata(
        self,
        player_lookup: str,
        game_date: date,
        extraction_data: Dict
    ) -> Dict:
        """Build the historical_completeness struct."""

        games_found = extraction_data.get('games_found', 0)
        game_dates = extraction_data.get('game_dates', [])
        window_span = extraction_data.get('window_span_days', 0)
        teams = extraction_data.get('teams_in_window', [])

        # Determine expected games (from schedule)
        games_expected = self._get_expected_game_count(
            player_lookup, game_date, window_size=10
        )

        # Calculate missing dates
        missing_dates = self._find_missing_dates(
            player_lookup, game_date, game_dates, games_expected
        )

        # Determine status
        is_complete = (games_found >= games_expected) if games_expected > 0 else True
        is_reliable = (games_found / max(games_expected, 1)) >= 0.8
        is_stale = window_span > 21

        # Determine reason if incomplete
        incompleteness_reason = None
        if not is_complete:
            if games_found == 0:
                if self._is_new_player(player_lookup, game_date):
                    incompleteness_reason = 'new_player'
                else:
                    incompleteness_reason = 'no_data'
            elif missing_dates:
                incompleteness_reason = 'missing_games'
            elif is_stale:
                incompleteness_reason = 'stale_window'

        return {
            'games_found': games_found,
            'games_expected': games_expected,
            'completeness_pct': (games_found / max(games_expected, 1)) * 100,
            'contributing_game_dates': game_dates,
            'missing_game_dates': missing_dates,
            'window_span_days': window_span,
            'oldest_game_date': extraction_data.get('oldest_game'),
            'newest_game_date': extraction_data.get('newest_game'),
            'is_complete': is_complete,
            'is_reliable': is_reliable,
            'is_stale': is_stale,
            'is_new_player': games_expected == 0,
            'is_early_season': games_expected < 10,
            'teams_in_window': teams,
            'needs_reprocessing': not is_complete,
            'incompleteness_reason': incompleteness_reason
        }
```

---

## Component 5: Cascade Detector

**Purpose:** Given a backfilled date, find all features that need re-running.

**Location:** `bin/cascade_reprocessor.py` (NEW)

### Design

```python
class CascadeDetector:
    """
    Detects which feature records are affected by a backfill.
    """

    FORWARD_IMPACT_DAYS = 21  # How far forward a backfill affects

    def __init__(self, bq_client: bigquery.Client):
        self.client = bq_client

    def find_affected_by_backfill(
        self,
        backfilled_date: date
    ) -> List[Tuple[date, str]]:
        """
        Find all (game_date, player_lookup) pairs affected by backfilling a date.

        Logic:
        1. Find features where backfilled_date is in missing_game_dates
        2. Find features where backfilled_date is in contributing_game_dates
           (these used old data that may now be different)
        3. Find features in forward window that may not have metadata yet
        """
        query = """
        WITH affected AS (
            -- Features that were missing this date
            SELECT DISTINCT game_date, player_lookup, 'was_missing' as reason
            FROM `nba_predictions.ml_feature_store_v2`
            WHERE @backfilled_date IN UNNEST(historical_completeness.missing_game_dates)
              AND game_date > @backfilled_date
              AND game_date <= DATE_ADD(@backfilled_date, INTERVAL @forward_days DAY)

            UNION ALL

            -- Features that used this date (may need re-run if data changed)
            SELECT DISTINCT game_date, player_lookup, 'used_date' as reason
            FROM `nba_predictions.ml_feature_store_v2`
            WHERE @backfilled_date IN UNNEST(historical_completeness.contributing_game_dates)
              AND game_date > @backfilled_date
              AND game_date <= DATE_ADD(@backfilled_date, INTERVAL @forward_days DAY)
        )
        SELECT DISTINCT game_date, player_lookup
        FROM affected
        ORDER BY game_date, player_lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("backfilled_date", "DATE", backfilled_date),
                bigquery.ScalarQueryParameter("forward_days", "INT64", self.FORWARD_IMPACT_DAYS),
            ]
        )

        results = self.client.query(query, job_config=job_config)
        return [(row.game_date, row.player_lookup) for row in results]

    def find_affected_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[date, List[str]]:
        """
        Find affected records for a range of backfilled dates.

        Returns:
            Dict mapping target_date to list of player_lookups
        """
        all_affected = {}

        current = start_date
        while current <= end_date:
            affected = self.find_affected_by_backfill(current)
            for target_date, player in affected:
                if target_date not in all_affected:
                    all_affected[target_date] = set()
                all_affected[target_date].add(player)
            current += timedelta(days=1)

        # Convert sets to lists
        return {d: list(players) for d, players in all_affected.items()}

    def calculate_cascade_scope(
        self,
        backfill_start: date,
        backfill_end: date
    ) -> Tuple[date, date]:
        """
        Calculate the full date range that needs reprocessing.

        Returns:
            (reprocess_start, reprocess_end)
        """
        # Reprocessing starts the day after backfill starts
        reprocess_start = backfill_start + timedelta(days=1)

        # Reprocessing ends FORWARD_IMPACT_DAYS after backfill ends
        reprocess_end = backfill_end + timedelta(days=self.FORWARD_IMPACT_DAYS)

        return reprocess_start, reprocess_end
```

---

## Component 6: Query Views

**Purpose:** Easy access to completeness status and cascade candidates.

### View: Incomplete Features

```sql
CREATE OR REPLACE VIEW `nba_predictions.v_incomplete_features` AS
SELECT
    game_date,
    player_lookup,
    historical_completeness.games_found,
    historical_completeness.games_expected,
    historical_completeness.completeness_pct,
    historical_completeness.missing_game_dates,
    historical_completeness.window_span_days,
    historical_completeness.incompleteness_reason,
    historical_completeness.is_stale,
    historical_completeness.teams_in_window
FROM `nba_predictions.ml_feature_store_v2`
WHERE NOT historical_completeness.is_complete
ORDER BY game_date DESC, player_lookup;
```

### View: Daily Completeness Summary

```sql
CREATE OR REPLACE VIEW `nba_predictions.v_daily_completeness_summary` AS
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_complete) as complete_features,
    COUNTIF(NOT historical_completeness.is_complete) as incomplete_features,
    COUNTIF(historical_completeness.is_stale) as stale_features,
    ROUND(COUNTIF(historical_completeness.is_complete) / COUNT(*) * 100, 2) as completeness_pct,

    -- Breakdown by reason
    COUNTIF(historical_completeness.incompleteness_reason = 'missing_games') as missing_games_count,
    COUNTIF(historical_completeness.incompleteness_reason = 'new_player') as new_player_count,
    COUNTIF(historical_completeness.incompleteness_reason = 'stale_window') as stale_window_count
FROM `nba_predictions.ml_feature_store_v2`
GROUP BY game_date
ORDER BY game_date DESC;
```

### View: Cascade Candidates

```sql
CREATE OR REPLACE VIEW `nba_predictions.v_cascade_candidates` AS
SELECT
    game_date,
    player_lookup,
    historical_completeness.missing_game_dates,
    historical_completeness.incompleteness_reason
FROM `nba_predictions.ml_feature_store_v2`
WHERE historical_completeness.needs_reprocessing
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
ORDER BY game_date DESC;
```

---

## Integration Flow

### During Normal Processing

```
1. Feature Extractor runs batch extraction
   └── Returns: games + game_dates + metadata per player

2. For each player:
   ├── Build completeness metadata
   ├── If incomplete: LOG WARNING
   ├── Generate features (existing logic)
   └── Attach historical_completeness struct

3. Write to ml_feature_store_v2
   └── Includes completeness metadata

4. Prediction Coordinator (optional)
   └── Can filter: WHERE historical_completeness.is_complete = True
```

### After Backfill

```
1. Run bin/cascade_reprocessor.py --backfilled-date 2026-01-01
   └── Queries ml_feature_store_v2 for affected records

2. Output: List of (game_date, player_lookup) to re-run

3. Run feature generation for affected records
   └── bin/backfill_feature_store.py --affected-file cascade_output.json

4. Verify completeness improved
   └── Query v_daily_completeness_summary
```

---

## Performance Considerations

| Operation | Estimated Time | Notes |
|-----------|---------------|-------|
| Batch extraction with metadata | +5-10s | Single query, minimal overhead |
| Completeness metadata build | ~1ms per player | In-memory calculation |
| Cascade detection query | 5-15s | Depends on date range |
| Full cascade re-run | 2-4 hours | 500 players × 21 days |

### Optimization Strategies

1. **Batch everything:** Never query per-player in hot path
2. **Cache schedule:** Schedule doesn't change frequently
3. **Partition queries:** Use game_date partitioning in BigQuery
4. **Parallel cascade:** Process multiple dates concurrently

---

## Related Documents

- `03-CORNER-CASES.md` - Edge cases this architecture handles
- `05-DATA-MODEL.md` - Detailed schema specifications
- `06-CASCADE-PROTOCOL.md` - Step-by-step reprocessing workflow
- `07-IMPLEMENTATION-PLAN.md` - Phased rollout plan

---

**Document Status:** Complete
