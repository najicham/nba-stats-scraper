# Phase 4: Precompute Processors - Dependency Checks
**Detailed Specification**
**Version**: 1.1
**Last Updated**: 2025-11-21 14:15:00 PST
**Status**: Core Documented - Multi-phase patterns TBD

📖 **Parent Document**: [Dependency Checking System Overview](./00-overview.md)

⚠️ **NOTE**: Multi-phase dependency checking (Phase 4 checking Phase 2 directly) and historical backfill patterns are documented as proposed approaches. Exact implementation details still being finalized based on operational requirements.

---

## Table of Contents

1. [Phase 4 Overview](#phase-4-overview)
2. [Dependency Check Pattern](#dependency-check-pattern)
3. [Processor Specifications](#processor-specifications)
4. [Cross-Dataset Dependencies](#cross-dataset-dependencies)
5. [Failure Scenarios](#failure-scenarios)

---

## Phase 4 Overview

### Purpose

Phase 4 processors precompute and cache ML features from Phase 3 analytics data, optimizing for Phase 5 prediction performance.

### Key Characteristics

- **5 Total Processors** (4 precompute + 1 ML feature store)
- **Dependencies**: Primarily Phase 3 analytics tables (2-4 per processor)
- **Caching Strategy**: Daily precompute for fast real-time lookups
- **Output**: Cached features in `nba_precompute.*` and `nba_predictions.ml_feature_store_v2`
- **Processing Strategy**: Daily batch (12:00 AM nightly)

### Data Flow

```
Phase 3 (Analytics Tables)
    ↓ 2-4 sources per processor
Phase 4 (Precompute Processors) - THIS PHASE
    ├─ Dependency Check: Phase 3 analytics available?
    ├─ Completeness Check: Sufficient historical data?
    ├─ Feature Extraction: Compute advanced metrics
    ├─ Caching: Store for fast lookups
    └─ ML Features: Combine into 25-feature vectors
    ↓
Phase 5 (Prediction Systems)
```

---

## Dependency Check Pattern

### Standard Phase 4 Dependency Check

```python
class Phase4ProcessorBase:
    """Base class for Phase 4 precompute processors."""

    def check_dependencies(self, game_date: str, entity_id: str = None) -> Dict[str, Any]:
        """
        Check all Phase 3 dependencies for given game/entity.

        Args:
            game_date: Target game date for processing
            entity_id: Player or team identifier (optional)

        Returns:
            {
                'all_met': bool,
                'sources': {
                    'source_name': {
                        'available': bool,
                        'rows_found': int,
                        'completeness_pct': float,
                        'last_updated': str,
                        'data_hash': str,
                        'status': 'healthy|warning|critical',
                        'historical_depth': int  # Days of history available
                    }
                },
                'overall_completeness': float,
                'can_proceed': bool,
                'historical_sufficiency': bool  # Enough history for ML features?
            }
        """
```

### Key Differences from Phase 3

**1. Historical Depth Requirements:**
- Phase 3: Processes current game data
- Phase 4: Requires 10-20 games of historical data per player/team
- Early season handling: Graceful degradation when < 10 games available

**2. Multi-Phase Dependencies:**
- Phase 3: Only checks Phase 2 tables
- Phase 4: Can check both Phase 3 (primary) AND Phase 2 (for quality verification)
- **Example**: ML Feature Store may verify Phase 2 injury data directly for confidence scoring

---

## Processor Specifications

### 1. Player Daily Cache Processor

**File**: `data_processors/precompute/player_daily_cache_processor.py`
**Table**: `nba_precompute.player_daily_cache`
**Dependencies**: 2 Phase 3 sources

#### Dependency Map

| Priority | Source Table | Purpose | Historical Requirement |
|----------|--------------|---------|------------------------|
| **CRITICAL** | `player_game_summary` | Recent performance stats | 10-20 games |
| **CRITICAL** | `upcoming_player_game_context` | Next game context | Current only |

#### What It Does

Caches rolling averages and recent performance metrics for fast lookups during real-time prediction updates.

**Key Metrics Cached:**
- Rolling averages: last 5, 10, 20 games
- Standard deviations: consistency metrics
- Usage rates: minutes, shot attempts
- Team context: pace, offensive rating

#### Dependency Check Logic

```python
def check_dependencies(self, player_lookup: str, game_date: str) -> Dict[str, Any]:
    """
    Check if sufficient historical data exists for player.

    Critical checks:
    1. At least 5 games in player_game_summary (minimum viable)
    2. At least 10 games preferred (for reliable rolling averages)
    3. Recent data (< 7 days old)
    """
    # TODO: Implement detailed logic
    pass
```

#### Historical Requirements

**Lookback Window**: 20 games per player
**Minimum Viable**: 5 games (early season)
**Preferred**: 10+ games (stable metrics)

**Early Season Handling:**
```python
if games_found < 5:
    # Skip player - insufficient data
    return {'can_proceed': False, 'reason': 'insufficient_history'}
elif games_found < 10:
    # Process but flag as early_season
    return {'can_proceed': True, 'early_season_flag': True}
else:
    # Normal processing
    return {'can_proceed': True, 'early_season_flag': False}
```

---

### 2. Player Composite Factors Processor

**File**: `data_processors/precompute/player_composite_factors_processor.py`
**Table**: `nba_precompute.player_composite_factors`
**Dependencies**: 3 Phase 3 sources

#### Dependency Map

| Priority | Source Table | Purpose |
|----------|--------------|---------|
| **CRITICAL** | `player_game_summary` | Player stats |
| **CRITICAL** | `team_offense_game_summary` | Team context |
| **CRITICAL** | `team_defense_game_summary` | Opponent defense |

#### What It Does

Calculates composite adjustment factors for ML predictions:
- **Fatigue Score**: Rest days + recent workload (0-100)
- **Shot Zone Mismatch**: Player zones vs opponent defense (-10 to +10)
- **Pace Score**: Game pace impact (-3 to +3)
- **Usage Spike Score**: Recent usage changes (-3 to +3)

---

### 3. Player Shot Zone Analysis Processor

**File**: `data_processors/precompute/player_shot_zone_analysis_processor.py`
**Table**: `nba_precompute.player_shot_zone_analysis`
**Dependencies**: 2 Phase 3 sources

#### Dependency Map

| Priority | Source Table | Purpose |
|----------|--------------|---------|
| **CRITICAL** | `player_game_summary` | Shot distribution data |
| **OPTIONAL** | `team_defense_game_summary` | Opponent zone defense |

#### What It Does

Analyzes player shot zone preferences and efficiency:
- Paint shot rate and efficiency
- Mid-range shot rate and efficiency
- Three-point shot rate and efficiency
- Zone matchup scoring vs opponent

---

### 4. Team Defense Zone Analysis Processor

**File**: `data_processors/precompute/team_defense_zone_analysis_processor.py`
**Table**: `nba_precompute.team_defense_zone_analysis`
**Dependencies**: 2 Phase 3 sources

#### Dependency Map

| Priority | Source Table | Purpose |
|----------|--------------|---------|
| **CRITICAL** | `team_defense_game_summary` | Defensive stats by zone |
| **OPTIONAL** | `team_offense_game_summary` | Team pace context |

#### What It Does

Analyzes team defensive patterns by zone for matchup predictions:
- Paint defense efficiency
- Perimeter defense efficiency
- Three-point defense rate
- Defensive pace and pressure metrics

---

### 5. ML Feature Store V2 Processor

**File**: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
**Table**: `nba_predictions.ml_feature_store_v2` (cross-dataset write)
**Dependencies**: 4 Phase 4 sources + 3 Phase 3 fallbacks

#### Dependency Map

| Priority | Source Table | Purpose | Fallback |
|----------|--------------|---------|----------|
| **CRITICAL** | `player_daily_cache` | Features 0-4, 18-20, 22-23 | Phase 3 tables |
| **CRITICAL** | `player_composite_factors` | Features 5-8 | Defaults |
| **CRITICAL** | `player_shot_zone_analysis` | Features 18-20 | Phase 3 tables |
| **CRITICAL** | `team_defense_zone_analysis` | Features 13-14 | Phase 3 tables |
| **FALLBACK** | `player_game_summary` | Backup for features 0-4 | - |
| **FALLBACK** | `upcoming_player_game_context` | Backup for features 15-17 | - |
| **FALLBACK** | `team_offense_game_summary` | Backup for feature 24 | - |

#### What It Does

**Most Complex Processor**: Combines 4 Phase 4 sources + 3 Phase 3 fallbacks into 25 ML features per player.

**Key Features:**
- **Array-Based Storage**: Flexible for feature evolution (25 → 47+ without schema changes)
- **Quality Scoring**: Tracks data source quality (0-100) for confidence adjustments
- **Phase 4 → Phase 3 Fallback**: Ensures robustness when Phase 4 incomplete
- **Feature Versioning**: Tracks which features are present

**Processing Strategy:**
1. Try Phase 4 sources first (preferred, pre-computed)
2. Fallback to Phase 3 if Phase 4 incomplete
3. Use hardcoded defaults if both unavailable
4. Calculate quality_score based on source usage

#### Dependency Check Logic

```python
def check_dependencies(self, player_lookup: str, game_date: str) -> Dict[str, Any]:
    """
    Check 7 total dependencies (4 Phase 4 + 3 Phase 3 fallbacks).

    MAY ALSO check Phase 2 directly for:
    - Quality verification (is raw data complete?)
    - Confidence scoring adjustments
    - Root cause analysis when Phase 3/4 incomplete

    Returns quality metadata for each source:
    - source_daily_cache_completeness_pct
    - source_composite_completeness_pct
    - source_shot_zones_completeness_pct
    - source_team_defense_completeness_pct
    """
    results = {}

    # Primary: Check Phase 4 sources
    phase4_sources = self.check_phase4_sources(player_lookup, game_date)

    # Fallback: Check Phase 3 if Phase 4 incomplete
    if not all_phase4_available:
        phase3_sources = self.check_phase3_sources(player_lookup, game_date)

    # OPTIONAL: Verify Phase 2 for quality scoring
    # This is not a dependency check, but a quality verification
    phase2_quality = self.verify_phase2_quality(player_lookup, game_date)
    if phase2_quality['injury_data_missing']:
        results['quality_score'] *= 0.9  # Reduce confidence by 10%

    return results
```

#### Quality Score Calculation

```python
SOURCE_WEIGHTS = {
    'phase4': 100,      # Preferred (pre-computed)
    'phase3': 75,       # Fallback (calculated from raw)
    'calculated': 100,  # Always accurate (calculated fresh)
    'default': 40       # Last resort (hardcoded)
}

# Example: 20 from phase4, 3 calculated, 2 defaults
quality_score = ((20*100) + (3*100) + (2*40)) / 25 = 95.2
```

**Quality Tiers:**
- **95-100**: Excellent (all Phase 4 + calculated)
- **85-94**: Good (some Phase 3 fallback)
- **70-84**: Medium (significant Phase 3 reliance)
- **<70**: Low (many defaults, early season)

---

## Multi-Phase Dependency Checking

### Phase 4 Can Check Phase 2 Directly

**Important**: Unlike Phase 3 (which only checks Phase 2), Phase 4 processors can check BOTH Phase 3 AND Phase 2.

**Why This Happens**:
1. **Quality Verification**: Ensure upstream raw data is complete
2. **Confidence Scoring**: Adjust feature quality based on raw data completeness
3. **Root Cause Analysis**: When Phase 3 is incomplete, check if Phase 2 is the problem
4. **Historical Backfill Detection**: Detect when Phase 2 data was backfilled and needs re-processing

**Example: ML Feature Store Checking Phase 2**:

```python
def check_dependencies_with_phase2_verification(self, player_lookup: str, game_date: str):
    """
    ML Feature Store checks Phase 4 (primary), Phase 3 (fallback),
    AND Phase 2 (quality verification).
    """
    # Step 1: Check Phase 4 sources (primary)
    phase4_status = self.check_phase4_cache(player_lookup, game_date)

    # Step 2: Check Phase 3 sources (fallback)
    if not phase4_status['sufficient']:
        phase3_status = self.check_phase3_analytics(player_lookup, game_date)

    # Step 3: VERIFY Phase 2 raw data (quality check)
    # This is NOT a dependency, but a quality verification
    phase2_quality = {
        'injury_report': self.check_phase2_injury_completeness(game_date),
        'boxscores': self.check_phase2_boxscore_completeness(game_date),
        'props': self.check_phase2_props_completeness(game_date)
    }

    # Adjust quality score based on Phase 2 completeness
    quality_score = 100.0
    if phase2_quality['injury_report'] < 0.8:
        quality_score *= 0.9  # -10% for incomplete injury data
    if phase2_quality['boxscores'] < 0.8:
        quality_score *= 0.95  # -5% for incomplete boxscores

    return {
        'phase4_available': phase4_status['sufficient'],
        'phase3_fallback_used': phase3_status['used'],
        'phase2_quality_verified': True,
        'quality_score': quality_score,
        'data_source': 'phase4' if phase4_status['sufficient'] else 'phase3'
    }
```

**Query Pattern for Phase 2 Verification**:

```sql
-- Check Phase 2 injury report completeness for quality scoring
SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as injury_count,
    -- Expect 40-60 players on injury report typically
    CASE
        WHEN COUNT(DISTINCT player_lookup) >= 40 THEN 1.0  -- Full quality
        WHEN COUNT(DISTINCT player_lookup) >= 30 THEN 0.9  -- Good quality
        WHEN COUNT(DISTINCT player_lookup) >= 20 THEN 0.7  -- Medium quality
        ELSE 0.5  -- Low quality
    END as injury_data_quality_score
FROM `nba_raw.nbac_injury_report`
WHERE game_date = @target_date
  AND scrape_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY game_date;
```

---

## Historical Data Dependency Checking

### Phase 4 Checks Historical Data, Not Just Current

**Critical Difference**: Phase 4 processors check for 10-20 games of historical data per player/team, not just today's game.

**Historical Dependency Pattern**:

```python
def check_historical_dependencies(self, player_lookup: str, game_date: str):
    """
    Check if sufficient historical data exists for player.

    Unlike Phase 2/3 which check current game only, Phase 4 needs:
    - 10-20 games of historical player_game_summary data
    - 10 games of team offense/defense data
    - Recent injury history (last 30 days)
    """
    # Check historical depth
    query = f"""
    SELECT
        COUNT(*) as games_found,
        MIN(game_date) as earliest_game,
        MAX(game_date) as latest_game,
        TIMESTAMP_DIFF(MAX(game_date), MIN(game_date), DAY) as days_span
    FROM `nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date <= '{game_date}'
      AND game_date >= DATE_SUB('{game_date}', INTERVAL 60 DAY)
    """

    result = self.bq_client.query(query).result()
    games_found = result.games_found

    # Determine if sufficient history
    if games_found >= 10:
        return {
            'historical_sufficiency': True,
            'games_found': games_found,
            'can_proceed': True,
            'early_season_flag': False
        }
    elif games_found >= 5:
        return {
            'historical_sufficiency': False,
            'games_found': games_found,
            'can_proceed': True,  # Process but with warning
            'early_season_flag': True,
            'warning': 'Insufficient history for stable rolling averages'
        }
    else:
        return {
            'historical_sufficiency': False,
            'games_found': games_found,
            'can_proceed': False,  # Too little data
            'early_season_flag': True,
            'error': f'Only {games_found} games found (need 5+)'
        }
```

**Historical Backfill Detection**:

```python
def detect_historical_backfill(self, player_lookup: str, game_date: str):
    """
    Detect if Phase 3 data was backfilled for historical games.

    This is important because:
    1. Phase 2 may backfill missing data from 5 days ago
    2. Phase 3 processes that backfilled data
    3. Phase 4 needs to re-process if new Phase 3 data appeared

    We check: Has player_game_summary been updated for dates < today?
    """
    query = f"""
    SELECT
        game_date,
        processed_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR) as hours_since_processed
    FROM `nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < CURRENT_DATE()  -- Historical data
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
      AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    ORDER BY game_date DESC
    """

    results = self.bq_client.query(query).result()

    if results.total_rows > 0:
        # New historical data found - need to re-process!
        return {
            'backfill_detected': True,
            'games_to_reprocess': [row.game_date for row in results],
            'reason': 'Phase 3 processed historical data in last 48 hours'
        }
    else:
        return {
            'backfill_detected': False,
            'games_to_reprocess': []
        }
```

**Historical Query Pattern (30-day lookback)**:

```sql
-- Find games that need Phase 4 processing (historical aware)
SELECT DISTINCT
    p3.player_lookup,
    p3.game_date,
    p3.game_id,
    p3.processed_at as phase3_processed_at,
    p4.processed_at as phase4_processed_at,
    -- Flag games where Phase 3 is newer than Phase 4 (backfill scenario)
    CASE
        WHEN p4.processed_at IS NULL THEN 'never_processed'
        WHEN p3.processed_at > p4.processed_at THEN 'needs_reprocessing'
        ELSE 'up_to_date'
    END as processing_status
FROM `nba_analytics.player_game_summary` p3
LEFT JOIN `nba_precompute.player_daily_cache` p4
    ON p3.player_lookup = p4.player_lookup
    AND p3.game_date = p4.game_date
WHERE p3.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND (
        p4.processed_at IS NULL  -- Never processed
        OR p3.processed_at > p4.processed_at  -- Phase 3 newer (backfill)
    )
ORDER BY p3.game_date ASC;
```

**Key Insight**: Phase 4 must check for historical backfills in Phase 3, not just process "today's games".

---

## Cross-Dataset Dependencies

### Why ML Feature Store Writes to Different Dataset

**Table**: `nba_predictions.ml_feature_store_v2` (NOT `nba_precompute.*`)

**Rationale:**
- Phase 5 prediction systems read from `nba_predictions` dataset
- Avoids cross-dataset queries in hot path (prediction generation)
- ML features are the "input contract" for Phase 5
- Logically belong with predictions, not precompute cache

**Pattern:**
```python
# Phase 4 writes to nba_predictions
target_table = 'nba_predictions.ml_feature_store_v2'

# Phase 5 reads from same dataset
features = bq.query('SELECT * FROM nba_predictions.ml_feature_store_v2')
```

---

## Failure Scenarios

### Scenario 1: Insufficient Historical Data (Early Season)

**Impact**: Cannot compute rolling averages
**Action**: Process with early_season_flag, use available data
**Confidence**: Reduce Phase 5 confidence by 10-20%

```python
if games_found < 10:
    logger.warning(f"Early season: only {games_found} games for {player}")
    # Still process but flag
    record['early_season_flag'] = True
    record['insufficient_data_reason'] = f'only_{games_found}_games'
```

### Scenario 2: Phase 4 Processor Failed, Fallback to Phase 3

**Impact**: ML Feature Store uses slower Phase 3 queries
**Action**: Continue with Phase 3 fallback, quality_score drops to 70-85
**User Impact**: Predictions still generated, confidence slightly lower

```python
# Try Phase 4 first
phase4_data = self.get_phase4_cache(player, game_date)
if not phase4_data:
    logger.warning("Phase 4 cache miss, falling back to Phase 3")
    phase3_data = self.get_phase3_analytics(player, game_date)
    data_source = 'phase3'
    quality_score = 75  # Lower than phase4 (100)
```

### Scenario 3: All Phase 4 Sources Missing (Critical)

**Impact**: Cannot generate ML features
**Action**: Do not publish prediction for this player
**User Experience**: Player not included in predictions list

```python
if all_phase4_missing and all_phase3_missing:
    logger.error(f"Cannot generate features for {player}: all sources missing")
    notify_error(
        title="ML Feature Store: Missing Dependencies",
        message=f"Player {player} has no data in Phase 4 or Phase 3",
        details={
            'player': player,
            'game_date': game_date,
            'action': 'No prediction will be generated'
        }
    )
    return None  # Skip this player
```

---

## Processing Schedule

**Phase 4 Execution Order:**

```
12:00 AM: player_daily_cache (runs first)
12:05 AM: player_composite_factors (depends on daily cache)
12:10 AM: player_shot_zone_analysis (parallel with team_defense)
12:10 AM: team_defense_zone_analysis (parallel with shot_zone)
12:15 AM: ml_feature_store_v2 (runs LAST - waits for all 4)
```

**Why This Order:**
1. Daily cache must complete first (other processors depend on it)
2. Composite factors needs daily cache
3. Shot zone and team defense can run in parallel
4. ML feature store waits for all 4 to maximize quality

---

## Monitoring & Alerts

### Key Metrics

1. **Historical Depth Coverage**
   - % of players with 10+ games: Target > 80% (after week 3)
   - % of players with 5+ games: Target > 90%

2. **Phase 4 Availability**
   - Daily cache completion rate: Target 100%
   - Feature store quality score: Target > 85

3. **Fallback Usage Rate**
   - % using Phase 3 fallback: Target < 20%
   - Indicates Phase 4 health

### Monitoring Query

```sql
-- Daily Phase 4 health report
SELECT
    COUNT(DISTINCT player_lookup) as players_processed,
    AVG(feature_quality_score) as avg_quality,
    COUNTIF(early_season_flag) as early_season_count,
    COUNTIF(data_source = 'phase4') as phase4_count,
    COUNTIF(data_source = 'phase3') as phase3_fallback_count,
    COUNTIF(data_source = 'mixed') as mixed_count
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

---

## Dependency Verification Queries

### Historical Sufficiency Check (Phase 4 Dependency Requirement)

```sql
-- Check if we have sufficient historical data for Phase 4 processing
WITH player_history AS (
  SELECT
    player_lookup,
    COUNT(*) as games_in_last_60_days,
    MIN(game_date) as earliest_game,
    MAX(game_date) as latest_game
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND game_date < CURRENT_DATE()
  GROUP BY player_lookup
)
SELECT
  COUNT(CASE WHEN games_in_last_60_days >= 10 THEN 1 END) as sufficient_players,
  COUNT(CASE WHEN games_in_last_60_days >= 5 AND games_in_last_60_days < 10 THEN 1 END) as early_season_players,
  COUNT(CASE WHEN games_in_last_60_days < 5 THEN 1 END) as insufficient_players,
  COUNT(*) as total_players,
  ROUND(100.0 * COUNT(CASE WHEN games_in_last_60_days >= 10 THEN 1 END) / COUNT(*), 1) as sufficient_pct
FROM player_history;
```

**Expected** (after week 3 of season):
- sufficient_pct > 80%
- early_season_players < 20%
- insufficient_players < 10%

**If insufficient_pct > 30%**: Historical data dependency not met - check for backfill issues or early in season

### Verify Phase 3 Dependencies Are Available

```sql
-- Check if Phase 3 data exists for Phase 4 to depend on
SELECT COUNT(*) as rows
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1;
```

**Expected**: rows > 200 (for typical game day)

**If rows = 0**: Phase 3 dependency not met - Phase 4 cannot proceed

---

## Historical Data Patterns

### Why Phase 4 Needs Historical Data

Unlike Phase 2/3 (current game only), Phase 4 requires historical depth:

**Rolling Averages**: Last 5, 10, 20 games per player
**Trend Detection**: Performance trajectory over 30 days
**Matchup History**: Team defense patterns over season
**ML Features**: Require stable statistics (10+ games minimum)

### Handling Insufficient History

```python
def check_historical_sufficiency(player_lookup):
    """Determine if enough history for reliable Phase 4 processing."""
    games_found = count_recent_games(player_lookup, days=60)

    if games_found >= 10:
        return {
            'status': 'sufficient',
            'can_proceed': True,
            'early_season_flag': False,
            'quality_multiplier': 1.0
        }
    elif games_found >= 5:
        return {
            'status': 'early_season',
            'can_proceed': True,  # Process but flag
            'early_season_flag': True,
            'quality_multiplier': 0.85  # Reduce quality 15%
        }
    else:
        return {
            'status': 'insufficient',
            'can_proceed': False,  # Skip player
            'early_season_flag': True,
            'reason': f'Only {games_found} games (need 5+)'
        }
```

**Impact on Predictions**:
- Sufficient (10+): Normal confidence
- Early Season (5-9): Confidence reduced 10-15%
- Insufficient (<5): No prediction generated

---

## Related Documentation

### Implementation Guides
- [Dependency Checking Strategy](../implementation/04-dependency-checking-strategy.md) - Historical range patterns
- [Smart Idempotency Guide](../implementation/03-smart-idempotency-implementation-guide.md)

### Processor Details
- [ML Feature Store Card](../processor-cards/phase4-ml-feature-store-v2.md)
- [Player Daily Cache Card](../processor-cards/phase4-player-daily-cache.md)
- [Player Composite Factors](../processor-cards/phase4-player-composite-factors.md)

### Operations
- [Cross-Phase Troubleshooting](../operations/cross-phase-troubleshooting-matrix.md) §2.3
- [Daily Processing Timeline](../processor-cards/workflow-daily-processing-timeline.md)

---

**Status**: ✅ **Core Documented** - Multi-phase and historical patterns documented (TBD on exact implementation)

**Previous**: [Phase 3 Dependency Checks](./02-analytics-processors.md)
**Next**: [Phase 5 Dependency Checks](./04-predictions-coordinator.md)

**Last Updated**: 2025-11-21 15:00:00 PST
**Version**: 1.2
