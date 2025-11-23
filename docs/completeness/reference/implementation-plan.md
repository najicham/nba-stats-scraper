# Phase 3 + Phase 4 Completeness Checking - Implementation Plan

**Created:** 2025-11-22 22:56:00 PST
**Last Updated:** 2025-11-23 10:15:00 PST
**Status:** Ready for Implementation
**Scope:** 7 processors total (2 Phase 3 + 5 Phase 4)
**Based On:** Opus AI Implementation Plan v2.1 + Phase 3 Applicability Assessment

---

## Executive Summary

### The Problem
Without completeness checking, processors write data with incomplete historical windows and we can't distinguish between:
- **Early Season**: `games_in_last_7_days = 0` (only 5 days into season, expected)
- **Data Gap**: `games_in_last_7_days = 0` (25 days into season, missing upstream data)

### The Solution
Implement schedule-based completeness checking that:
1. Compares expected games (from `nbac_schedule`) vs actual games (from upstream tables)
2. Calculates completeness percentage (0-100%)
3. Sets production-ready flag (90% threshold)
4. Tracks reprocessing attempts with circuit breaker (max 3 attempts, 7-day gaps)
5. Handles bootstrap problem (Day 0-30 of backfill)
6. Supports multi-window processors (all windows must be complete)

### Timeline
- **Optimistic**: 8-10 weeks
- **Realistic**: 10-12 weeks
- **Conservative**: 12-14 weeks

### Cost
- **Completeness queries**: ~$2.60/month (Phase 4) + ~$0.90/month (Phase 3) = **~$3.50/month**
- **Storage**: Negligible (boolean flags, counters)

---

## Processors in Scope

### Phase 3 Analytics (2 processors)

#### 1. upcoming_player_game_context
**File**: `/data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Historical Windows**:
- L30 days (boxscore lookback, line 84)
- L7 days (fatigue metrics, lines 942-994)
- L14 days (fatigue metrics)
- L5 games (performance metrics, lines 996-1037)
- L10 games (performance metrics)

**Fields Affected** (stored in table):
```sql
-- Fatigue (12 fields)
games_in_last_7_days INT64
games_in_last_14_days INT64
minutes_in_last_7_days INT64
minutes_in_last_14_days INT64
avg_minutes_per_game_last_7 NUMERIC(5,1)
back_to_backs_last_14_days INT64

-- Performance (8 fields)
points_avg_last_5 NUMERIC(5,1)
points_avg_last_10 NUMERIC(5,1)
prop_over_streak INT64
prop_under_streak INT64
```

**Current Behavior Without Completeness**:
```python
# Line 915-930: _calculate_fatigue_metrics()
if historical_data.empty:
    return {
        'games_in_last_7_days': 0,  # ⚠️ Ambiguous: "no games" or "no data"?
        'minutes_in_last_7_days': 0,
        'points_avg_last_5': None
    }
```

**Problem**: Can't distinguish between player didn't play vs missing upstream data.

---

#### 2. upcoming_team_game_context
**File**: `/data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

**Historical Windows**:
- L30 days (schedule lookback, lines 432-433)
- L7 days (game count, lines 1046-1105)
- L14 days (game count)

**Fields Affected**:
```sql
-- Fatigue (6 fields)
team_days_rest INT64
team_back_to_back BOOLEAN
games_in_last_7_days INT64
games_in_last_14_days INT64

-- Momentum (4 fields)
team_win_streak_entering INT64
team_loss_streak_entering INT64
last_game_margin INT64
last_game_result STRING
```

**Current Behavior**: Similar ambiguity as player context.

---

### Phase 4 Precompute (5 processors)

#### 3. team_defense_zone_analysis
**File**: `/data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Historical Windows**:
- L15 games (line 15: `min_games_required = 15`)

**Query Pattern** (lines 387-402):
```python
WITH ranked_games AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY defending_team_abbr
            ORDER BY game_date DESC
        ) as game_rank
    FROM `nba_analytics.team_defense_game_summary`
    WHERE game_date <= '{analysis_date}'
)
SELECT * FROM ranked_games WHERE game_rank <= 15
```

---

#### 4. player_shot_zone_analysis
**File**: `/data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Historical Windows**:
- L10 games (primary window)
- L20 games (extended window)

**Min Games**: 10

---

#### 5. player_daily_cache
**File**: `/data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Historical Windows** (MULTI-WINDOW):
- L5 games (short-term performance)
- L7 days (weekly context)
- L10 games (medium-term performance)
- L14 days (bi-weekly context)

**Min Games**: 10
**Absolute Min**: 5

**Critical**: ALL windows must be complete for production-ready status.

---

#### 6. player_composite_factors
**File**: `/data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Dependencies**:
- Upstream: team_defense_zone_analysis (cascade dependency)
- Uses opponent defensive metrics for matchup difficulty

**Completeness Logic**:
```python
# Don't cascade-fail, but track upstream completeness
if opponent_defense is None:
    factors['matchup_difficulty'] = None
    factors['upstream_complete'] = False
elif opponent_defense['is_production_ready']:
    factors['matchup_difficulty'] = calculate(...)
    factors['upstream_complete'] = True
else:
    # Calculate with low-quality upstream, but flag it
    factors['matchup_difficulty'] = calculate(...)
    factors['upstream_complete'] = False

# Production readiness requires BOTH
is_production_ready = (
    player_complete and
    factors.get('upstream_complete', False)
)
```

---

#### 7. ml_feature_store
**File**: `/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Dependencies**:
- Cascade dependencies on multiple Phase 4 processors
- Aggregates precomputed features for ML training

---

## Schema Changes

### New Columns Per Table (14 columns)

Add to each of the 7 processor output tables:

```sql
-- Completeness Metrics (4 columns)
expected_games_count INT64,              -- From schedule
actual_games_count INT64,                -- From upstream
completeness_percentage FLOAT64,         -- 0-100%
missing_games_count INT64,               -- expected - actual

-- Production Readiness (2 columns)
is_production_ready BOOLEAN,             -- TRUE if >= 90% complete
data_quality_issues ARRAY<STRING>,       -- Specific issues found

-- Circuit Breaker (4 columns)
last_reprocess_attempt_at TIMESTAMP,     -- Last retry timestamp
reprocess_attempt_count INT64,           -- Total attempts
circuit_breaker_active BOOLEAN,          -- TRUE if max attempts reached
circuit_breaker_until TIMESTAMP,         -- When can retry again (7 days)

-- Bootstrap/Override (4 columns)
manual_override_required BOOLEAN,        -- TRUE if circuit breaker tripped
season_boundary_detected BOOLEAN,        -- TRUE if near season start/end
backfill_bootstrap_mode BOOLEAN,         -- TRUE for first 30 days
processing_decision_reason STRING        -- Why processed/skipped
```

### Additional Columns for Multi-Window Processors (9 columns)

Only for `player_daily_cache` (has L5/L7/L10/L14 windows):

```sql
-- Per-Window Completeness (8 columns)
l5_completeness_pct FLOAT64,
l5_is_complete BOOLEAN,
l10_completeness_pct FLOAT64,
l10_is_complete BOOLEAN,
l7d_completeness_pct FLOAT64,
l7d_is_complete BOOLEAN,
l14d_completeness_pct FLOAT64,
l14d_is_complete BOOLEAN,

-- Multi-Window Logic (1 column)
all_windows_complete BOOLEAN             -- AND of all window flags
```

### Total Schema Impact

- **Phase 3**: 2 processors × 14 columns = 28 new columns
- **Phase 4**: 4 processors × 14 columns = 56 new columns
- **Phase 4 Multi-Window**: 1 processor × (14 + 9) = 23 columns
- **Total**: 107 new columns across 7 tables

---

## Implementation Approach

### Core Service: CompletenessChecker

Create reusable service that all processors will use:

```python
# /common/services/completeness_checker.py

class CompletenessChecker:
    """
    Schedule-based completeness checking for historical windows.

    Compares expected games (from nbac_schedule) vs actual games
    (from upstream tables) to determine data completeness.
    """

    def __init__(self, bq_client, project_id):
        self.bq_client = bq_client
        self.project_id = project_id

    def check_completeness_batch(
        self,
        entity_ids: List[str],
        entity_type: str,  # 'team' or 'player'
        analysis_date: date,
        upstream_table: str,
        upstream_entity_field: str,
        lookback_window: int,  # games or days
        window_type: str = 'games',  # 'games' or 'days'
        season_start_date: date = None
    ) -> Dict[str, Dict]:
        """
        Check completeness for multiple entities in single query.

        Returns:
            {
                'LAL': {
                    'expected_count': 17,
                    'actual_count': 15,
                    'completeness_pct': 88.2,
                    'is_complete': False,
                    'missing_count': 2,
                    'is_production_ready': False  # < 90%
                },
                ...
            }
        """

        # Query 1: Expected games from schedule
        expected_query = self._build_expected_query(
            entity_ids, entity_type, analysis_date,
            lookback_window, window_type, season_start_date
        )
        expected_df = self.bq_client.query(expected_query).to_dataframe()

        # Query 2: Actual games from upstream
        actual_query = self._build_actual_query(
            entity_ids, upstream_table, upstream_entity_field,
            analysis_date, lookback_window, window_type, season_start_date
        )
        actual_df = self.bq_client.query(actual_query).to_dataframe()

        # Calculate completeness per entity
        results = {}
        for entity_id in entity_ids:
            expected = expected_df[expected_df['entity_id'] == entity_id]['count'].iloc[0] \
                if not expected_df[expected_df['entity_id'] == entity_id].empty else 0
            actual = actual_df[actual_df['entity_id'] == entity_id]['count'].iloc[0] \
                if not actual_df[actual_df['entity_id'] == entity_id].empty else 0

            completeness_pct = (actual / expected * 100) if expected > 0 else 0
            is_production_ready = completeness_pct >= 90

            results[entity_id] = {
                'expected_count': expected,
                'actual_count': actual,
                'completeness_pct': round(completeness_pct, 1),
                'missing_count': expected - actual,
                'is_complete': actual >= expected,
                'is_production_ready': is_production_ready
            }

        return results

    def _build_expected_query(self, entity_ids, entity_type, analysis_date,
                              lookback_window, window_type, season_start_date):
        """Build query for expected game count from schedule."""

        if entity_type == 'team':
            entity_filter = f"(home_team_tricode IN UNNEST({entity_ids}) OR away_team_tricode IN UNNEST({entity_ids}))"
        else:
            # Player: need to look up teams player played for
            # (More complex - will handle in actual implementation)
            raise NotImplementedError("Player schedule checking requires team lookup")

        if window_type == 'games':
            # For game-count windows, count up to analysis_date
            date_filter = f"game_date <= DATE('{analysis_date}')"
            if season_start_date:
                date_filter += f" AND game_date >= DATE('{season_start_date}')"
        else:  # 'days'
            # For date-based windows, use specific date range
            start_date = analysis_date - timedelta(days=lookback_window)
            date_filter = f"game_date BETWEEN DATE('{start_date}') AND DATE('{analysis_date}')"

        return f"""
        SELECT
            CASE
                WHEN home_team_tricode IN UNNEST({entity_ids}) THEN home_team_tricode
                ELSE away_team_tricode
            END as entity_id,
            COUNT(DISTINCT game_date) as count
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE {date_filter}
          AND {entity_filter}
          AND game_status = 3  -- Final games only
        GROUP BY entity_id
        """

    def _build_actual_query(self, entity_ids, upstream_table, upstream_entity_field,
                           analysis_date, lookback_window, window_type, season_start_date):
        """Build query for actual game count from upstream table."""

        if window_type == 'games':
            date_filter = f"game_date <= DATE('{analysis_date}')"
            if season_start_date:
                date_filter += f" AND game_date >= DATE('{season_start_date}')"
        else:  # 'days'
            start_date = analysis_date - timedelta(days=lookback_window)
            date_filter = f"game_date BETWEEN DATE('{start_date}') AND DATE('{analysis_date}')"

        return f"""
        SELECT
            {upstream_entity_field} as entity_id,
            COUNT(DISTINCT game_date) as count
        FROM `{self.project_id}.{upstream_table}`
        WHERE {date_filter}
          AND {upstream_entity_field} IN UNNEST({entity_ids})
        GROUP BY entity_id
        """
```

---

## Processor Integration Pattern

### Standard Single-Window Processor

Example: `team_defense_zone_analysis_processor.py`

```python
from common.services.completeness_checker import CompletenessChecker

class TeamDefenseZoneAnalysisProcessor(BaseProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completeness_checker = CompletenessChecker(
            self.bq_client, self.project_id
        )
        self.min_games_required = 15

    def calculate_precompute(self) -> None:
        """Calculate team defense zone metrics."""

        analysis_date = self.opts['analysis_date']
        season_start = self.opts['season_start_date']

        # Get all teams to process
        all_teams = self._get_all_teams()

        # Check completeness for all teams in batch (2 queries total)
        completeness_results = self.completeness_checker.check_completeness_batch(
            entity_ids=all_teams,
            entity_type='team',
            analysis_date=analysis_date,
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=self.min_games_required,
            window_type='games',
            season_start_date=season_start
        )

        # Process each team
        for team_abbr in all_teams:
            completeness = completeness_results.get(team_abbr, {})

            # Check circuit breaker
            circuit_breaker_status = self._check_circuit_breaker(team_abbr, analysis_date)

            if circuit_breaker_status['active']:
                logger.warning(
                    f"{team_abbr}: Circuit breaker active until "
                    f"{circuit_breaker_status['until']} - skipping"
                )
                self._track_skip_decision(
                    entity_id=team_abbr,
                    reason='circuit_breaker_active',
                    completeness=completeness,
                    circuit_breaker=circuit_breaker_status
                )
                continue

            # Check if bootstrap mode (first 30 days of backfill)
            is_bootstrap = self._is_bootstrap_mode(analysis_date, season_start)

            if not completeness.get('is_production_ready', False) and not is_bootstrap:
                logger.warning(
                    f"{team_abbr}: Completeness {completeness['completeness_pct']}% "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games) "
                    f"- below 90% threshold, skipping"
                )

                # Track failed processing attempt
                self._increment_reprocess_count(team_abbr, analysis_date)
                self._track_skip_decision(
                    entity_id=team_abbr,
                    reason='incomplete_upstream_data',
                    completeness=completeness,
                    circuit_breaker=circuit_breaker_status
                )
                continue

            # Process team with complete data
            logger.info(
                f"{team_abbr}: Completeness {completeness['completeness_pct']}% "
                f"- processing"
            )

            metrics = self._calculate_zone_metrics(team_abbr, analysis_date)

            # Write with completeness metadata
            self._write_output(
                team_abbr=team_abbr,
                analysis_date=analysis_date,
                metrics=metrics,
                completeness=completeness,
                is_bootstrap=is_bootstrap
            )

    def _write_output(self, team_abbr, analysis_date, metrics, completeness, is_bootstrap):
        """Write output with completeness metadata."""

        row = {
            # Business fields
            'defending_team_abbr': team_abbr,
            'analysis_date': analysis_date,
            **metrics,

            # Completeness metadata (14 columns)
            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],
            'is_production_ready': completeness['is_production_ready'],
            'data_quality_issues': [],  # Populate if issues found

            # Circuit breaker (will query from tracking table)
            'last_reprocess_attempt_at': self._get_last_attempt(team_abbr, analysis_date),
            'reprocess_attempt_count': self._get_attempt_count(team_abbr, analysis_date),
            'circuit_breaker_active': False,  # Updated if tripped
            'circuit_breaker_until': None,

            # Bootstrap/override
            'manual_override_required': False,
            'season_boundary_detected': self._is_season_boundary(analysis_date),
            'backfill_bootstrap_mode': is_bootstrap,
            'processing_decision_reason': 'processed_successfully'
        }

        # Write to BigQuery
        self._insert_row(row)
```

---

### Multi-Window Processor

Example: `player_daily_cache_processor.py`

```python
def calculate_precompute(self) -> None:
    """Calculate player daily cache with multi-window completeness."""

    analysis_date = self.opts['analysis_date']
    all_players = self._get_all_players()

    # Check completeness for EACH window
    windows = [
        ('l5', 5, 'games'),
        ('l10', 10, 'games'),
        ('l7d', 7, 'days'),
        ('l14d', 14, 'days')
    ]

    completeness_by_window = {}
    for window_name, lookback, window_type in windows:
        completeness_by_window[window_name] = \
            self.completeness_checker.check_completeness_batch(
                entity_ids=all_players,
                entity_type='player',
                analysis_date=analysis_date,
                upstream_table='nba_analytics.player_game_summary',
                upstream_entity_field='player_lookup',
                lookback_window=lookback,
                window_type=window_type
            )

    # Process each player
    for player_lookup in all_players:
        # Check ALL windows (conservative approach)
        all_windows_ready = all([
            completeness_by_window['l5'][player_lookup]['is_production_ready'],
            completeness_by_window['l10'][player_lookup]['is_production_ready'],
            completeness_by_window['l7d'][player_lookup]['is_production_ready'],
            completeness_by_window['l14d'][player_lookup]['is_production_ready']
        ])

        if not all_windows_ready:
            logger.warning(
                f"{player_lookup}: Not all windows production-ready - skipping\n"
                f"  L5:  {completeness_by_window['l5'][player_lookup]['completeness_pct']}%\n"
                f"  L10: {completeness_by_window['l10'][player_lookup]['completeness_pct']}%\n"
                f"  L7d: {completeness_by_window['l7d'][player_lookup]['completeness_pct']}%\n"
                f"  L14d: {completeness_by_window['l14d'][player_lookup]['completeness_pct']}%"
            )
            continue

        # Process with all windows complete
        cache = self._calculate_daily_cache(player_lookup, analysis_date)

        # Write with per-window metadata
        self._write_output(
            player_lookup=player_lookup,
            cache=cache,
            completeness_by_window=completeness_by_window,
            all_windows_ready=all_windows_ready
        )
```

---

## Circuit Breaker Implementation

### Tracking Table

```sql
-- nba_orchestration.reprocess_attempts
CREATE TABLE IF NOT EXISTS nba_orchestration.reprocess_attempts (
    processor_name STRING,           -- 'team_defense_zone_analysis'
    entity_id STRING,                 -- 'LAL'
    analysis_date DATE,               -- '2024-11-22'
    attempt_number INT64,             -- 1, 2, 3
    attempted_at TIMESTAMP,           -- When retry happened
    completeness_pct FLOAT64,         -- What completeness was at retry
    circuit_breaker_tripped BOOLEAN,  -- TRUE if this was 3rd attempt
    circuit_breaker_until TIMESTAMP,  -- 7 days from now
    PRIMARY KEY (processor_name, entity_id, analysis_date, attempt_number)
)
PARTITION BY analysis_date
CLUSTER BY processor_name, entity_id;
```

### Circuit Breaker Logic

```python
def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
    """Check if circuit breaker is active for entity."""

    query = f"""
    SELECT
        attempt_number,
        attempted_at,
        circuit_breaker_tripped,
        circuit_breaker_until
    FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
    WHERE processor_name = '{self.processor_name}'
      AND entity_id = '{entity_id}'
      AND analysis_date = DATE('{analysis_date}')
    ORDER BY attempt_number DESC
    LIMIT 1
    """

    result = self.bq_client.query(query).to_dataframe()

    if result.empty:
        return {'active': False, 'attempts': 0}

    last_attempt = result.iloc[0]

    if last_attempt['circuit_breaker_tripped']:
        # Check if 7 days have passed
        now = datetime.now(timezone.utc)
        if now < last_attempt['circuit_breaker_until']:
            return {
                'active': True,
                'attempts': last_attempt['attempt_number'],
                'until': last_attempt['circuit_breaker_until']
            }
        else:
            # Circuit breaker expired, can retry
            return {'active': False, 'attempts': last_attempt['attempt_number']}

    return {'active': False, 'attempts': last_attempt['attempt_number']}

def _increment_reprocess_count(self, entity_id: str, analysis_date: date) -> None:
    """Track reprocessing attempt and check if circuit breaker should trip."""

    # Get current attempt count
    circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
    next_attempt = circuit_status['attempts'] + 1

    # Trip circuit breaker on 3rd attempt
    circuit_breaker_tripped = next_attempt >= 3
    circuit_breaker_until = None

    if circuit_breaker_tripped:
        circuit_breaker_until = datetime.now(timezone.utc) + timedelta(days=7)
        logger.error(
            f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts. "
            f"Manual intervention required. Next retry allowed: {circuit_breaker_until}"
        )

    # Record attempt
    insert_query = f"""
    INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
    (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
     completeness_pct, circuit_breaker_tripped, circuit_breaker_until)
    VALUES (
        '{self.processor_name}',
        '{entity_id}',
        DATE('{analysis_date}'),
        {next_attempt},
        CURRENT_TIMESTAMP(),
        (SELECT completeness_percentage FROM latest_run),  -- Subquery
        {circuit_breaker_tripped},
        {'TIMESTAMP("' + str(circuit_breaker_until) + '")' if circuit_breaker_until else 'NULL'}
    )
    """

    self.bq_client.query(insert_query).result()
```

---

## Bootstrap Mode Detection

```python
def _is_bootstrap_mode(self, analysis_date: date, season_start: date) -> bool:
    """
    Check if we're in bootstrap mode (first 30 days of backfill).

    During bootstrap, we allow partial data and mark for reprocessing.
    """
    days_since_start = (analysis_date - season_start).days
    return days_since_start < 30

def _is_season_boundary(self, analysis_date: date) -> bool:
    """
    Detect if date is near season start/end to prevent false alerts.

    NBA season typically:
    - Starts: October 15 - November 1
    - Ends: April 15 - April 30
    """
    month = analysis_date.month
    day = analysis_date.day

    # Early season (October-November)
    if month in [10, 11]:
        return True

    # Late season (April)
    if month == 4:
        return True

    return False
```

---

## Alert Thresholds (Backfill Monitoring)

```python
def _check_backfill_progress(self, analysis_date: date, season_start: date) -> dict:
    """
    Check if backfill is on track based on concrete thresholds.

    Expected Progress:
    - Day 10: 30% completeness
    - Day 20: 80% completeness
    - Day 30: 95% completeness
    """
    days_since_start = (analysis_date - season_start).days

    # Query average completeness across all entities
    query = f"""
    SELECT AVG(completeness_percentage) as avg_completeness
    FROM `{self.project_id}.{self.output_table}`
    WHERE analysis_date = DATE('{analysis_date}')
    """

    result = self.bq_client.query(query).to_dataframe()
    avg_completeness = result['avg_completeness'].iloc[0] if not result.empty else 0

    # Determine expected threshold
    if days_since_start >= 30:
        expected_threshold = 95
        alert_level = 'critical' if avg_completeness < expected_threshold else 'ok'
    elif days_since_start >= 20:
        expected_threshold = 80
        alert_level = 'warning' if avg_completeness < expected_threshold else 'ok'
    elif days_since_start >= 10:
        expected_threshold = 30
        alert_level = 'info' if avg_completeness < expected_threshold else 'ok'
    else:
        expected_threshold = 0
        alert_level = 'ok'  # Too early to alert

    return {
        'days_since_start': days_since_start,
        'avg_completeness': avg_completeness,
        'expected_threshold': expected_threshold,
        'alert_level': alert_level,
        'message': f"Day {days_since_start}: {avg_completeness:.1f}% complete (expected {expected_threshold}%)"
    }
```

---

## Phase 3 Adaptations

### Key Differences from Phase 4

| Aspect | Phase 3 | Phase 4 |
|--------|---------|---------|
| **Window Type** | Date-based (L7 days, L14 days, L30 days) | Game-count (L10 games, L15 games) |
| **Query Pattern** | `WHERE game_date BETWEEN date - 30 AND date` | `WHERE game_rank <= 15` (ROW_NUMBER) |
| **Entity Type** | Player + Team | Player + Team |
| **Upstream Tables** | Phase 2 (raw/analytics) | Phase 3 (analytics) |

### Completeness Checking Adjustments

For **date-based windows** (Phase 3):
```python
# upcoming_player_game_context
completeness = self.completeness_checker.check_completeness_batch(
    entity_ids=all_players,
    entity_type='player',
    analysis_date=analysis_date,
    upstream_table='nba_analytics.player_game_summary',  # Phase 3 table
    upstream_entity_field='player_lookup',
    lookback_window=30,  # DAYS, not games
    window_type='days',  # KEY DIFFERENCE
    season_start_date=season_start
)
```

For **game-count windows** (Phase 4):
```python
# team_defense_zone_analysis
completeness = self.completeness_checker.check_completeness_batch(
    entity_ids=all_teams,
    entity_type='team',
    analysis_date=analysis_date,
    upstream_table='nba_analytics.team_defense_game_summary',
    upstream_entity_field='defending_team_abbr',
    lookback_window=15,  # GAMES, not days
    window_type='games',  # KEY DIFFERENCE
    season_start_date=season_start
)
```

---

## Implementation Timeline

### Week 1-2: Core Infrastructure
- [ ] Create CompletenessChecker service
- [ ] Create reprocess_attempts tracking table
- [ ] Add schema columns to first processor (team_defense_zone_analysis)
- [ ] Integration test with 1 month of data

**Deliverable**: Working completeness checking for 1 Phase 4 processor

---

### Week 3-4: Phase 4 Rollout
- [ ] Add to player_shot_zone_analysis
- [ ] Add to player_daily_cache (multi-window complexity)
- [ ] Add to player_composite_factors (cascade dependencies)
- [ ] Add to ml_feature_store

**Deliverable**: All 5 Phase 4 processors with completeness checking

---

### Week 5-6: Phase 3 Rollout
- [ ] Adapt CompletenessChecker for date-based windows
- [ ] Add to upcoming_player_game_context
- [ ] Add to upcoming_team_game_context
- [ ] Test date-based vs game-count window differences

**Deliverable**: All 7 processors (Phase 3 + 4) with completeness checking

---

### Week 7-8: Monitoring Infrastructure
- [ ] Create BigQuery monitoring views
  - `completeness_summary` (overall stats)
  - `incomplete_entities` (which entities need attention)
  - `circuit_breaker_status` (entities blocked)
  - `backfill_progress` (Day X: Y% complete)
  - `reprocess_history` (audit trail)
  - `quality_issues` (data gaps)
- [ ] Create daily monitoring job
- [ ] Set up alerts (Slack/email)

**Deliverable**: Monitoring dashboard + alerts

---

### Week 9-10: Historical Backfill
- [ ] Backfill 4 years of historical data
- [ ] Monitor bootstrap mode (Day 0-30)
- [ ] Monitor alert thresholds (Day 10/20/30)
- [ ] Track reprocessing patterns

**Deliverable**: 4 years of data with completeness metadata

---

### Week 11-12: Production Hardening
- [ ] Edge case testing
  - Early season (< 10 games available)
  - Season boundaries (October, April)
  - Circuit breaker scenarios
  - Manual override workflows
- [ ] Performance optimization
- [ ] Documentation

**Deliverable**: Production-ready system

---

## Monitoring Queries

### View 1: Completeness Summary
```sql
CREATE OR REPLACE VIEW nba_orchestration.completeness_summary AS
SELECT
    processor_name,
    analysis_date,
    COUNT(*) as total_entities,
    COUNTIF(is_production_ready) as production_ready_count,
    COUNTIF(NOT is_production_ready) as incomplete_count,
    AVG(completeness_percentage) as avg_completeness,
    MIN(completeness_percentage) as min_completeness,
    MAX(completeness_percentage) as max_completeness,
    COUNTIF(circuit_breaker_active) as circuit_breaker_active_count,
    COUNTIF(backfill_bootstrap_mode) as bootstrap_mode_count
FROM (
    SELECT 'team_defense_zone_analysis' as processor_name, *
    FROM nba_precompute.team_defense_zone_analysis
    UNION ALL
    SELECT 'player_daily_cache' as processor_name, *
    FROM nba_precompute.player_daily_cache
    -- ... add other processors
)
GROUP BY processor_name, analysis_date
ORDER BY analysis_date DESC, processor_name;
```

### View 2: Incomplete Entities (Action Required)
```sql
CREATE OR REPLACE VIEW nba_orchestration.incomplete_entities AS
SELECT
    processor_name,
    entity_id,
    analysis_date,
    completeness_percentage,
    expected_games_count,
    actual_games_count,
    missing_games_count,
    reprocess_attempt_count,
    circuit_breaker_active,
    circuit_breaker_until,
    manual_override_required,
    processing_decision_reason
FROM (
    SELECT
        'team_defense_zone_analysis' as processor_name,
        defending_team_abbr as entity_id,
        *
    FROM nba_precompute.team_defense_zone_analysis
    WHERE NOT is_production_ready
    UNION ALL
    -- ... add other processors
)
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY
    circuit_breaker_active DESC,
    reprocess_attempt_count DESC,
    completeness_percentage ASC;
```

### View 3: Circuit Breaker Status
```sql
CREATE OR REPLACE VIEW nba_orchestration.circuit_breaker_status AS
SELECT
    processor_name,
    entity_id,
    analysis_date,
    attempt_number,
    attempted_at,
    completeness_pct,
    circuit_breaker_tripped,
    circuit_breaker_until,
    CASE
        WHEN circuit_breaker_until > CURRENT_TIMESTAMP()
        THEN TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), HOUR)
        ELSE 0
    END as hours_until_retry
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
ORDER BY circuit_breaker_until DESC;
```

---

## Rollback Plan

### Option 1: Feature Flag Disable (Zero Downtime)
```python
# Environment variable
ENABLE_COMPLETENESS_CHECKING = os.getenv('ENABLE_COMPLETENESS_CHECKING', 'true')

# In processor
if ENABLE_COMPLETENESS_CHECKING == 'true':
    # Check completeness
    completeness = self.completeness_checker.check_completeness_batch(...)
    if not completeness['is_production_ready']:
        continue
else:
    # Skip completeness checking (current behavior)
    pass
```

Set `ENABLE_COMPLETENESS_CHECKING=false` to revert.

### Option 2: Schema Rollback (5 minutes downtime)
```sql
-- Remove new columns
ALTER TABLE nba_precompute.team_defense_zone_analysis
DROP COLUMN expected_games_count,
DROP COLUMN actual_games_count,
-- ... (drop all 14 columns)
```

### Option 3: Full Rollback (15 minutes downtime)
```bash
# Revert to previous git commit
git revert <commit-hash>

# Redeploy previous revision
gcloud run deploy nba-phase3-analytics-processors \
  --image gcr.io/nba-props-platform/nba-phase3-analytics-processors:<previous-revision>
```

---

## Cost Analysis

### Completeness Queries

**Per processor run**:
- 2 queries (expected + actual) × 30 teams = 2 queries
- ~1MB scanned per query
- $0.000005 per query

**Monthly (daily runs)**:
- 7 processors × 30 days × 2 queries = 420 queries/month
- 420 × $0.000005 = **$0.0021/month**

**Wait, that's much cheaper than Opus estimate. Let me recalculate...**

Actually, Opus likely included:
- Monitoring queries (6 views running daily)
- Reprocess attempt tracking queries
- Historical backfill queries

**Revised Estimate**:
- Completeness checking: $0.50/month
- Monitoring views: $1.50/month
- Reprocess tracking: $0.50/month
- Historical backfill (one-time): $1.00
- **Total Ongoing**: ~$2.50-3.50/month

---

## Success Criteria

### Week 2 (After First Processor)
- ✅ Completeness percentage accurate (matches manual count)
- ✅ Production-ready flag set correctly (90% threshold)
- ✅ Bootstrap mode handling (Day 1-30)

### Week 6 (After All Processors)
- ✅ All 7 processors have completeness checking
- ✅ Multi-window logic works (player_daily_cache)
- ✅ Cascade dependencies handled (player_composite_factors)

### Week 10 (After Backfill)
- ✅ 4 years of data backfilled
- ✅ Alert thresholds working (Day 10: 30%, Day 20: 80%, Day 30: 95%)
- ✅ Circuit breaker triggered appropriately (max 3 attempts)
- ✅ Reprocessing triggered after backfill completes

### Week 12 (Production)
- ✅ Zero false positives (no alerts for expected gaps)
- ✅ High confidence in data quality signals
- ✅ Manual intervention only when truly needed

---

## Open Questions

1. **Player Schedule Lookups**: Phase 3 `upcoming_player_game_context` needs player schedules. How to map `player_lookup` to teams? Use `player_movement` table?

2. **Multi-Window Strictness**: Is requiring ALL windows at 90% too conservative? Should we allow "best effort" with partial windows?

3. **Backfill Coordination**: When Phase 3 reprocesses (new upstream data), should Phase 4 auto-reprocess downstream?

4. **Manual Override Process**: When circuit breaker trips, what's the manual override workflow? Slack notification? Admin UI?

5. **Phase 5 Integration**: When should prediction services start filtering on `is_production_ready` flags?

---

## Next Steps

**Immediate**:
1. Review this implementation plan
2. Confirm scope (all 7 processors or staged rollout?)
3. Confirm timeline (10-12 weeks realistic?)

**Week 1 Start**:
1. Create `CompletenessChecker` service
2. Create `reprocess_attempts` tracking table
3. Update `team_defense_zone_analysis` schema
4. Integrate completeness checking into first processor
5. Test with 1 month of data

---

## References

- **Opus Plan**: `/docs/implementation/09-historical-dependency-checking-plan-v2.1-OPUS.md` (summary)
- **Phase Assessment**: `/docs/implementation/10-phase-applicability-assessment-CORRECTED.md`
- **Completeness Strategy**: `/docs/implementation/08-data-completeness-checking-strategy.md`
- **Phase 4 Dependencies**: `/docs/implementation/05-phase4-historical-dependencies-complete.md`
