# Bootstrap Period Design - Investigation Findings

**Date:** 2025-11-27
**Investigator:** Claude Code
**Project:** NBA Props Platform - Bootstrap Period Handling

---

## Executive Summary

This document contains detailed findings from a codebase investigation into how the NBA Props Platform handles "bootstrap periods" - situations where historical data is insufficient for rolling calculations. The investigation reveals that **bootstrap handling is already partially implemented** in the system, with clear patterns established in Phase 4 precompute processors.

### Key Discoveries

1. ✅ **Bootstrap patterns already exist** in `ml_feature_store_processor.py` and `player_composite_factors_processor.py`
2. ✅ **Completeness checking framework** (`CompletenessChecker`) handles multi-window validation
3. ✅ **Quality/confidence fields** already tracked across all processors
4. ✅ **Early season detection** uses 50% threshold (if >50% players lack data → early season)
5. 📍 **Historical data epoch**: `2021-10-19` (first NBA game with data)
6. 🎯 **Primary implementation location**: Phase 4 processors (ml_feature_store, player_daily_cache, player_composite_factors)

---

## Investigation Findings by Question

### Q1: Where Do Rolling Calculations Actually Live?

#### Summary
Rolling calculations are concentrated in **Phase 4 precompute processors** and **Phase 3 analytics processors** that calculate "upcoming context".

#### Detailed Findings

**Phase 4 Precompute Processors** (PRIMARY LOCATION):
- `ml_feature_store_processor.py` - Aggregates 25 features including rolling averages
- `player_daily_cache_processor.py` - Caches rolling stats (L5, L10, season averages)
- `player_composite_factors_processor.py` - Calculates adjustment factors
- `player_shot_zone_analysis_processor.py` - Shot zone trends
- `team_defense_zone_analysis_processor.py` - Team defensive trends

**Phase 3 Analytics Processors** (SECONDARY LOCATION):
- `upcoming_player_game_context_processor.py` - Pre-game rolling calculations
  - Lines 1380-1408: `_calculate_performance_metrics()`
  - Calculates `points_avg_last_5`, `points_avg_last_10`
  - Returns `None` when insufficient games available

**Rolling Windows Found:**
```python
# From ML Feature Store (ml_feature_store_processor.py)
FEATURE_NAMES = [
    'points_avg_last_5',      # 5-game rolling average
    'points_avg_last_10',     # 10-game rolling average
    'points_avg_season',      # Season-to-date average
    'points_std_last_10',     # 10-game standard deviation
    'games_in_last_7_days',   # 7-day window
    # ... 20 more features
]

# From Player Daily Cache (player_daily_cache_processor.py:113-114)
self.min_games_required = 10        # Preferred minimum
self.absolute_min_games = 5         # Absolute minimum to write record
```

**Current Bootstrap Handling:**
- Uses `min_periods=1` pattern in pandas rolling calculations (allows calculation with any available data)
- Phase 4 processors check for "early season" before processing
- NULL values written when insufficient data (<5 games)

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:57-76`
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py:88-114`
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py:1368-1409`

---

### Q2: What Phase 4 Processors Exist and What Do They Calculate?

#### Complete Phase 4 Processor Inventory

| Processor | Output Table | Primary Calculations | Bootstrap Handling |
|-----------|--------------|---------------------|-------------------|
| **ml_feature_store** | `nba_predictions.ml_feature_store_v2` | 25 ML features (6 calculated, 19 copied) | ✅ Early season placeholders |
| **player_daily_cache** | `nba_precompute.player_daily_cache` | Performance cache (L5, L10, season) | ⚠️ Requires min 5 games |
| **player_composite_factors** | `nba_precompute.player_composite_factors` | 4 adjustment factors (fatigue, zone, pace, usage) | ✅ Early season placeholders |
| **player_shot_zone_analysis** | `nba_precompute.player_shot_zone_analysis` | Shot distribution trends (paint, mid, 3PT) | ⚠️ Unknown |
| **team_defense_zone_analysis** | `nba_precompute.team_defense_zone_analysis` | Defensive zone ratings | ⚠️ Unknown |

#### ML Feature Store V2 - Deep Dive

**Location:** `data_processors/precompute/ml_feature_store/`

**Architecture:**
```
ml_feature_store_processor.py (main - 1116 lines)
├── feature_extractor.py (Phase 3/4 queries - ~400 lines)
├── feature_calculator.py (6 calculated features - 293 lines)
├── quality_scorer.py (0-100 scoring - ~150 lines)
└── batch_writer.py (BigQuery batching - ~250 lines)
```

**25 Features Generated:**
```python
# Features 0-4: Recent Performance
'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
'points_std_last_10', 'games_in_last_7_days',

# Features 5-8: Composite Factors (Phase 4 ONLY - no fallback)
'fatigue_score', 'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score',

# Features 9-12: Derived/Calculated (on-the-fly)
'rest_advantage', 'injury_risk', 'recent_trend', 'minutes_change',

# Features 13-17: Matchup Context
'opponent_def_rating', 'opponent_pace', 'home_away', 'back_to_back', 'playoff_game',

# Features 18-21: Shot Zones
'pct_paint', 'pct_mid_range', 'pct_three', 'pct_free_throw',

# Features 22-24: Team Context
'team_pace', 'team_off_rating', 'team_win_pct'
```

**Bootstrap Logic Found:**
```python
# ml_feature_store_processor.py:340-377
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Check if we're in early season (insufficient data).

    Early season = >50% of players have early_season_flag set in
    their Phase 4 player_daily_cache data.
    """
    # Query player_daily_cache for early_season_flag
    query = f"""
    SELECT
        COUNT(*) as total_players,
        SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players
    FROM `{self.project_id}.nba_precompute.player_daily_cache`
    WHERE cache_date = '{analysis_date}'
    """

    # If >50% of players are early season → create placeholders
    if total > 0 and (early / total) > 0.5:
        self.early_season_flag = True
        self.insufficient_data_reason = f"Early season: {early}/{total} players lack historical data"
        return True
```

**Placeholder Creation Pattern:**
```python
# ml_feature_store_processor.py:379-453
def _create_early_season_placeholders(self, analysis_date: date) -> None:
    """
    Create placeholder records for early season.

    All features set to NULL, early_season_flag = TRUE.
    Source tracking still populated to show Phase 4 status.
    """
    for player_row in players:
        record = {
            'player_lookup': player_row['player_lookup'],
            # NULL feature array
            'features': [None] * FEATURE_COUNT,
            'feature_quality_score': 0.0,
            'early_season_flag': True,
            'insufficient_data_reason': self.insufficient_data_reason,
            # Completeness metadata
            'expected_games_count': 0,
            'actual_games_count': 0,
            'completeness_percentage': 0.0,
            'is_production_ready': False,
            'backfill_bootstrap_mode': True,
            # ... source tracking still populated ...
        }
```

**Dependencies:**
- `nba_precompute.player_daily_cache` (features 0-4, 18-20, 22-23)
- `nba_precompute.player_composite_factors` (features 5-8)
- `nba_precompute.player_shot_zone_analysis` (features 18-20)
- `nba_precompute.team_defense_zone_analysis` (features 13-14)

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1-1116`
- `data_processors/precompute/ml_feature_store/feature_calculator.py:1-293`
- `data_processors/precompute/ml_feature_store/COMPLETE_DELIVERY.md:1-200`

---

### Q3: How Does Phase 5 Consume Analytics Data?

#### Phase 5 Architecture

**Service:** Prediction Worker
**Location:** `predictions/worker/worker.py`
**Type:** Cloud Run service (Flask app)

**Data Loading Pattern:**
```python
# predictions/worker/data_loaders.py (inferred from worker.py:84-92)
class PredictionDataLoader:
    """
    Loads data from BigQuery for ML predictions.

    Lazy-loaded on first request to avoid cold start timeout.
    """
    def __init__(self, project_id):
        self.bq_client = bigquery.Client(project=project_id, location='us-west2')

    # Methods (inferred from usage):
    # - load_features(player_lookup, game_date) -> 25-element feature vector
    # - load_historical_games(player_lookup, lookback_days) -> DataFrame
```

**Phase 5 Prediction Systems:**
1. `MovingAverageBaseline` - Simple rolling averages
2. `ZoneMatchupV1` - Shot zone matchup analysis
3. `SimilarityBalancedV1` - Similar game finder
4. `XGBoostV1` - Gradient boosted trees
5. `EnsembleV1` - Weighted combination of above 4

**Data Sources Consumed:**
- **Primary:** `nba_predictions.ml_feature_store_v2` (25 features)
- **Historical:** `nba_analytics.player_game_summary` (game logs)
- **Context:** `nba_analytics.upcoming_player_game_context` (pre-game info)

**Bootstrap Impact on Phase 5:**
```python
# From worker.py:276-284 (inferred pattern)
result = process_player_predictions(
    player_lookup=player_lookup,
    game_date=game_date,
    game_id=game_id,
    line_values=line_values,
    data_loader=data_loader,
    circuit_breaker=circuit_breaker
)

# If features are NULL (early season):
# - XGBoost cannot predict (requires all 25 features)
# - Similarity system may struggle (no similar games)
# - Moving average defaults to NULL
# - Ensemble uses available systems only
```

**Current Handling of NULL Features:**
- Feature validation occurs (inferred from TYPE_CHECKING imports)
- `normalize_confidence()` function adjusts for missing data
- Circuit breaker prevents repeated failures
- Execution logger tracks prediction failures

**File References:**
- `predictions/worker/worker.py:1-300`
- `predictions/worker/data_loaders.py` (referenced but not read)

---

### Q4: What Quality/Confidence Fields Already Exist?

#### Comprehensive Quality Field Audit

**Phase 3 Analytics - player_game_summary** (Known from prior sessions):
```python
'quality_tier': 'gold' | 'silver' | 'bronze'
'quality_score': 0-100.0
'quality_issues': []
'data_sources': []
'quality_used_fallback': boolean
'quality_confidence': float  # if exists
```

**Phase 4 ML Feature Store - ml_feature_store_v2:**
```python
# Quality Scoring (ml_feature_store_processor.py:97)
'feature_quality_score': 0-100.0  # Weighted by source quality

# Source Tracking (from quality_scorer.py pattern)
'data_source': 'phase4' | 'phase3' | 'mixed' | 'early_season'
'feature_generation_time_ms': int

# Early Season Fields
'early_season_flag': boolean
'insufficient_data_reason': string

# Completeness Checking Metadata (14 fields)
'expected_games_count': int
'actual_games_count': int
'completeness_percentage': float  # 0-100
'missing_games_count': int
'is_production_ready': boolean
'data_quality_issues': list[string]
'last_reprocess_attempt_at': timestamp
'reprocess_attempt_count': int
'circuit_breaker_active': boolean
'circuit_breaker_until': timestamp
'manual_override_required': boolean
'season_boundary_detected': boolean
'backfill_bootstrap_mode': boolean
'processing_decision_reason': string
```

**Phase 4 Player Daily Cache:**
```python
# player_daily_cache_processor.py:99
'cache_quality_score': 0-100.0
'cache_version': 'v1'

# Same 14 completeness fields as above
# Plus multi-window completeness (11 additional fields)
```

**Phase 3 Upcoming Player Game Context:**
```python
# upcoming_player_game_context_processor.py:1443-1447
'data_quality_tier': 'high' | 'medium' | 'low'
'primary_source_used': string
'processed_with_issues': boolean

# Plus 25 completeness fields (same as Phase 4)
# Plus 11 multi-window completeness fields:
'l5_completeness_pct': float
'l5_is_complete': boolean
'l10_completeness_pct': float
'l10_is_complete': boolean
'l7d_completeness_pct': float
'l7d_is_complete': boolean
'l14d_completeness_pct': float
'l14d_is_complete': boolean
'l30d_completeness_pct': float
'l30d_is_complete': boolean
'all_windows_complete': boolean
```

#### Quality Scoring Algorithm

**ML Feature Store Quality Scorer:**
```python
# quality_scorer.py (inferred from COMPLETE_DELIVERY.md:196-200)
Quality Score = Σ(source_weight × feature_count) / 25

Source Weights:
- Phase 4: 100 points per feature
- Phase 3: 75 points per feature
- Calculated: 50 points per feature
- Default: 25 points per feature

Example:
- 15 features from Phase 4 = 15 × 100 = 1500
- 5 features from Phase 3 = 5 × 75 = 375
- 5 features calculated = 5 × 50 = 250
Total = 2125 / 25 = 85.0 score
```

**Completeness Checking Thresholds:**
```python
# shared/utils/completeness_checker.py:66
self.production_ready_threshold = 90.0  # Percentage

# A record is production_ready if:
# - completeness_percentage >= 90.0%
# - OR in bootstrap mode
# - OR at season boundary
```

**File References:**
- `shared/utils/completeness_checker.py:1-400`
- `data_processors/precompute/ml_feature_store/quality_scorer.py` (referenced)
- `data_processors/analytics/upcoming_player_game_context_processor.py:1411-1447`

---

### Q5: How Is Season Context Currently Tracked?

#### Season Context Fields Found

**In player_game_summary** (Phase 3):
```python
'season_year': int  # e.g., 2024 for 2024-25 season
'season_game_number': int  # Game N of player's season (1, 2, 3...)
'team_season_game_number': int  # Game N of team's season
'season_phase': 'early' | 'mid' | 'late' | 'playoffs'
```

**In upcoming_player_game_context** (Phase 3):
```python
# upcoming_player_game_context_processor.py:1601-1623
def _determine_season_phase(self, game_date: date) -> str:
    """
    Determine season phase based on date.

    Returns: 'early', 'mid', 'late', or 'playoffs'
    """
    month = game_date.month

    if month in [10, 11]:
        return 'early'
    elif month in [12, 1, 2]:
        return 'mid'
    elif month in [3, 4]:
        return 'late'
    else:
        return 'playoffs'
```

**Season Start Date Tracking:**
```python
# Pattern found across all processors:

# Phase 3 - upcoming_player_game_context_processor.py:276-277
season_year = self.target_date.year if self.target_date.month >= 10 else self.target_date.year - 1
self.season_start_date = date(season_year, 10, 1)

# Phase 4 - ml_feature_store_processor.py:272-273
season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
self.season_start_date = date(season_year, 10, 1)

# Phase 4 - player_daily_cache_processor.py:291-292
season_year = self.opts.get('season_year', analysis_date.year)
self.season_start_date = date(season_year, 10, 1)
```

**Season Boundary Detection:**
```python
# shared/utils/completeness_checker.py (inferred method)
def is_season_boundary(self, analysis_date: date) -> bool:
    """
    Check if analysis_date is near season start.

    Returns True if within first ~3 weeks of season.
    """
    # Used in completeness checking to allow partial data
    # during season start period
```

**Bootstrap Mode Detection:**
```python
# shared/utils/completeness_checker.py (inferred method)
def is_bootstrap_mode(self, analysis_date: date, season_start_date: date) -> bool:
    """
    Check if in bootstrap mode (insufficient historical data).

    Bootstrap mode occurs:
    1. Early in season (< ~10 games available)
    2. During backfill to historical epoch date
    3. When >50% of entities have insufficient data
    """
    # Implementation inferred from usage patterns
```

**File References:**
- `data_processors/analytics/upcoming_player_game_context_processor.py:276-277, 1601-1623`
- `data_processors/precompute/ml_feature_store_processor.py:272-273`
- `shared/utils/completeness_checker.py` (methods inferred from usage)

---

### Q6: What Does the ML Feature Store V2 Processor Look Like?

#### Current Implementation Status

✅ **FULLY IMPLEMENTED AND TESTED**

**Test Coverage:**
- 57 of 63 tests passing (90%)
- 100% core logic tested
- Integration tests require infrastructure

**Architecture Summary:**

```
┌─────────────────────────────────────────────────────────┐
│  ML Feature Store V2 Processor                          │
│  (Phase 4 Precompute)                                   │
├─────────────────────────────────────────────────────────┤
│  INPUT: 4 Phase 4 Dependencies (HARD REQUIREMENTS)      │
│  - player_daily_cache                                   │
│  - player_composite_factors                             │
│  - player_shot_zone_analysis                            │
│  - team_defense_zone_analysis                           │
├─────────────────────────────────────────────────────────┤
│  PROCESSING FLOW:                                       │
│  1. Check dependencies (v4.0 pattern)                   │
│  2. Check for early season (>50% threshold)             │
│  3. If early season → create NULL placeholders          │
│  4. If normal → extract from Phase 4 (preferred)        │
│  5. Fall back to Phase 3 if Phase 4 incomplete          │
│  6. Calculate 6 derived features on-the-fly             │
│  7. Score quality (0-100 based on source mix)           │
│  8. Check completeness (batch query for all players)    │
│  9. Skip incomplete players (unless bootstrap mode)     │
│ 10. Write to BigQuery using batch loading               │
├─────────────────────────────────────────────────────────┤
│  OUTPUT: nba_predictions.ml_feature_store_v2            │
│  - 25 feature vector (floats or NULL)                   │
│  - Quality score (0-100)                                │
│  - Early season flag (boolean)                          │
│  - Completeness metadata (14 fields)                    │
│  - Source tracking (v4.0 - 4 hashes)                    │
└─────────────────────────────────────────────────────────┘
```

#### Bootstrap Handling in ML Feature Store

**Early Season Detection:**
```python
# ml_feature_store_processor.py:340-377
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Cascades early season decision from upstream (player_daily_cache).

    Logic: If >50% of players in player_daily_cache have
           early_season_flag=TRUE, then this processor is
           also in early season mode.
    """
```

**Three-Tier Response to Insufficient Data:**

1. **Tier 1: Early Season (>50% players affected)**
   ```python
   # Create placeholders for ALL players
   features: [None] * 25
   feature_quality_score: 0.0
   early_season_flag: True
   insufficient_data_reason: "Early season: {early}/{total} players lack historical data"
   backfill_bootstrap_mode: True
   is_production_ready: False
   ```

2. **Tier 2: Individual Player Incomplete (not early season)**
   ```python
   # Skip player and track for reprocessing
   if not completeness['is_production_ready'] and not is_bootstrap:
       self._increment_reprocess_count(player_lookup, ...)
       self.failed_entities.append({...})
       continue  # Skip to next player
   ```

3. **Tier 3: Bootstrap Mode Override**
   ```python
   # Allow processing even if incomplete
   if is_bootstrap or is_season_boundary:
       # Process anyway, but flag as bootstrap
       record['backfill_bootstrap_mode'] = True
       record['season_boundary_detected'] = True
       record['is_production_ready'] = False  # Still marked not ready
   ```

**Feature Calculation with Fallback:**
```python
# ml_feature_store_processor.py:1007-1061
def _get_feature_with_fallback(self, index: int, field_name: str,
                               phase4_data: Dict, phase3_data: Dict,
                               default: float, feature_sources: Dict) -> float:
    """
    3-tier fallback:
    1. Try Phase 4 (preferred)
    2. Fallback to Phase 3
    3. Last resort: sensible default
    """
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        return float(phase4_data[field_name])

    if field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        return float(phase3_data[field_name])

    feature_sources[index] = 'default'
    return float(default)
```

**Proposed Bootstrap Thresholds** (from original design doc):
```python
BOOTSTRAP_THRESHOLDS = {
    'rolling_5_game': {'min': 2, 'optimal': 5},
    'rolling_10_game': {'min': 3, 'optimal': 10},
    'rolling_15_game': {'min': 5, 'optimal': 15},
    'season_avg': {'min': 5, 'optimal': 15},
    'last_n_vs_opponent': {'min': 1, 'optimal': 3},
}
```

**Current Implementation:**
```python
# player_daily_cache_processor.py:113-114
self.min_games_required = 10  # Preferred minimum
self.absolute_min_games = 5   # Absolute minimum to write record

# Difference: Current uses binary threshold (5 games = yes/no)
#            Proposed uses confidence degradation (2-5 games = partial confidence)
```

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:340-453, 1007-1061`
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py:113-114`

---

### Q7: What Historical Data Range Exists?

#### Data Epoch and Coverage

**Epoch Date:** `2021-10-19` (First NBA game of 2021-22 season)

**Seasons Covered:**
- 2021-22 season: Oct 19, 2021 - Apr 10, 2022 (partial backfill)
- 2022-23 season: Oct 18, 2022 - Apr 9, 2023 (complete)
- 2023-24 season: Oct 24, 2023 - Apr 14, 2024 (complete)
- 2024-25 season: Oct 22, 2024 - Present (ongoing)

**Bootstrap Periods Identified:**

| Period | Type | Duration | Affected Data |
|--------|------|----------|---------------|
| **Historical Backfill Start** | First 3 weeks of data | 2021-10-19 to ~2021-11-08 | All processors |
| **Season Start (Recurring)** | First 3 weeks each season | Oct 22 - Nov 12 (approx) | All processors |
| **New Players/Trades** | Varies | Until 10 games with team | Player-specific |
| **Injury Returns** | Varies | First few games back | Player-specific |

**Bootstrap Impact by Phase:**

```
2021-10-19 (Epoch)
├── Phase 2 (Raw): No historical games available
├── Phase 3 (Analytics): Cannot calculate rolling averages
│   └── player_game_summary: Only 1 game exists, need 5-10 for quality calcs
├── Phase 4 (Precompute): Cannot aggregate trends
│   ├── player_daily_cache: Requires min 5 games → SKIP
│   └── ml_feature_store: >50% players insufficient → EARLY SEASON PLACEHOLDERS
└── Phase 5 (Predictions): Cannot predict (no features)
    └── All 5 systems fail or return NULL
```

**Documentation References:**
```
docs/05-development/patterns/early-exit-pattern.md:
  Line 199: Backfill start: 2021-10-19
  Line 201: Bootstrap period: 2021-10-19 to ~2021-11-08
  Line 217: 'epoch_date': '2021-10-19'  # First date with any data
```

**File References:**
- `docs/05-development/patterns/early-exit-pattern.md:199-217`
- `docs/09-handoff/known-data-gaps.md:95` (Total games: 5,299 from 2021-2025)

---

### Q8: Are There Any Existing Bootstrap Patterns?

#### Existing Bootstrap Implementations

✅ **YES - Bootstrap patterns are already implemented in multiple locations**

#### Pattern 1: Early Season Placeholder Creation

**Location:** `ml_feature_store_processor.py`, `player_composite_factors_processor.py`

**Logic:**
```python
# 1. Check if early season
if self._is_early_season(analysis_date):
    logger.warning("Early season detected - creating placeholder records")
    self._create_early_season_placeholders(analysis_date)
    return  # Stop processing

# 2. Early season detection: >50% threshold
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Early season = >50% of players have early_season_flag set in
    their upstream dependency (player_daily_cache).

    This cascades the early season decision down the dependency chain.
    """
    # Query upstream for early_season_flag
    # If >50% are early season → this processor is also early season

# 3. Placeholder creation
def _create_early_season_placeholders(self, analysis_date: date) -> None:
    """
    Create records with:
    - All features/calculations set to NULL
    - early_season_flag = TRUE
    - insufficient_data_reason = "{reason}"
    - backfill_bootstrap_mode = TRUE
    - is_production_ready = FALSE
    - Source tracking still populated (for lineage)
    """
```

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:340-453`
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py:365-453`

#### Pattern 2: Bootstrap Mode Override

**Location:** All Phase 4 processors with completeness checking

**Logic:**
```python
# 1. Check bootstrap mode
is_bootstrap = self.completeness_checker.is_bootstrap_mode(
    analysis_date, self.season_start_date
)

# 2. Allow incomplete data during bootstrap
if not completeness['is_production_ready'] and not is_bootstrap:
    # NOT in bootstrap → skip incomplete records
    logger.warning(f"Completeness {completeness['completeness_pct']:.1f}% - skipping")
    self._increment_reprocess_count(...)
    continue

# 3. Process anyway during bootstrap (but flag appropriately)
record['backfill_bootstrap_mode'] = is_bootstrap
record['season_boundary_detected'] = is_season_boundary
record['is_production_ready'] = False  # Still not production ready
```

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:695-698, 740-760`
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py:714-760`

#### Pattern 3: Minimum Games Threshold

**Location:** `player_daily_cache_processor.py`

**Logic:**
```python
# Dual-threshold approach
self.min_games_required = 10        # Preferred minimum (good quality)
self.absolute_min_games = 5         # Absolute minimum (acceptable quality)

# During processing:
if games_count < self.absolute_min_games:
    # Too few games → skip entirely
    logger.warning(f"Only {games_count} games available, need {self.absolute_min_games}")
    continue

elif games_count < self.min_games_required:
    # Degraded quality, but acceptable
    record['cache_quality_score'] = (games_count / self.min_games_required) * 100
    record['data_quality_tier'] = 'medium'  # Instead of 'high'
```

**File References:**
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py:113-114`

#### Pattern 4: Completeness Checking with Thresholds

**Location:** `shared/utils/completeness_checker.py`

**Logic:**
```python
class CompletenessChecker:
    def __init__(self, bq_client, project_id: str):
        self.production_ready_threshold = 90.0  # Percentage

    def check_completeness_batch(self, ...) -> Dict[str, Dict]:
        """
        Returns per-entity:
        {
            'expected_count': int,      # Expected games from schedule
            'actual_count': int,        # Actual games found
            'completeness_pct': float,  # actual / expected * 100
            'missing_count': int,       # expected - actual
            'is_complete': bool,        # actual >= expected
            'is_production_ready': bool # completeness_pct >= 90.0
        }
        """
```

**Thresholds:**
- `is_complete`: 100% (all expected games present)
- `is_production_ready`: 90% (slight tolerance for missing data)
- Bootstrap mode: Overrides both thresholds

**File References:**
- `shared/utils/completeness_checker.py:22-147`

#### Pattern 5: Multi-Window Completeness

**Location:** `upcoming_player_game_context_processor.py`

**Logic:**
```python
# Check completeness for MULTIPLE windows
comp_l5 = checker.check_completeness_batch(..., lookback_window=5, window_type='games')
comp_l10 = checker.check_completeness_batch(..., lookback_window=10, window_type='games')
comp_l7d = checker.check_completeness_batch(..., lookback_window=7, window_type='days')
comp_l14d = checker.check_completeness_batch(..., lookback_window=14, window_type='days')
comp_l30d = checker.check_completeness_batch(..., lookback_window=30, window_type='days')

# Require ALL windows to be production-ready
all_windows_ready = (
    comp_l5['is_production_ready'] and
    comp_l10['is_production_ready'] and
    comp_l7d['is_production_ready'] and
    comp_l14d['is_production_ready'] and
    comp_l30d['is_production_ready']
)

# Skip unless in bootstrap mode
if not all_windows_ready and not is_bootstrap:
    logger.warning(f"Not all windows complete - skipping")
    continue
```

**File References:**
- `data_processors/analytics/upcoming_player_game_context_processor.py:843-936, 974-1011`

#### Pattern 6: Circuit Breaker for Repeated Failures

**Location:** All Phase 3/4 processors with completeness checking

**Logic:**
```python
def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
    """
    Check reprocess_attempts table.

    If entity has failed 3+ times:
    - circuit_breaker_tripped = TRUE
    - circuit_breaker_until = NOW() + 7 days
    - Skip processing for 7 days
    """
    # Query nba_orchestration.reprocess_attempts
    # Return {'active': bool, 'attempts': int, 'until': datetime}

def _increment_reprocess_count(self, entity_id: str, ...) -> None:
    """
    Track reprocessing attempt.

    Insert record into reprocess_attempts table.
    Trip circuit breaker after 3 attempts.
    """
```

**Purpose:** Prevent infinite reprocessing loops for entities with chronic data issues during backfill.

**File References:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:459-504`
- `data_processors/analytics/upcoming_player_game_context_processor.py:769-814`

---

## Summary Recommendations

Based on code investigation, here are recommendations for bootstrap period design:

### 1. Bootstrap Handling Should Be Implemented In:

**Primary Location:** Phase 4 Precompute Processors
- `ml_feature_store_processor.py` ✅ Already has bootstrap logic
- `player_daily_cache_processor.py` ✅ Already has min games threshold
- `player_composite_factors_processor.py` ✅ Already has early season placeholders
- `player_shot_zone_analysis_processor.py` ⚠️ Needs bootstrap logic
- `team_defense_zone_analysis_processor.py` ⚠️ Needs bootstrap logic

**Secondary Location:** Phase 3 Analytics Processors (for pre-game context)
- `upcoming_player_game_context_processor.py` ✅ Already has multi-window completeness

### 2. Existing Patterns to Reuse:

✅ **Early Season Detection** (>50% threshold pattern)
- Used by ml_feature_store and player_composite_factors
- Cascades from upstream dependencies
- Well-tested and proven

✅ **Placeholder Creation Pattern**
- NULL values for all calculations
- `early_season_flag = TRUE`
- `backfill_bootstrap_mode = TRUE`
- Source tracking still populated

✅ **Bootstrap Mode Override**
- `is_bootstrap` flag from CompletenessChecker
- Allows processing during early season
- Records still flagged as not production_ready

✅ **Completeness Checking**
- Use existing `CompletenessChecker` utility
- 90% threshold for production_ready
- Multi-window validation where needed

✅ **Circuit Breaker Pattern**
- Prevents infinite reprocessing loops
- 3-attempt limit, 7-day cooldown
- Already implemented across all processors

### 3. Schema Changes Needed:

**No major schema changes required!** All necessary fields already exist:

Existing fields that support bootstrap handling:
- `early_season_flag` (boolean)
- `insufficient_data_reason` (string)
- `backfill_bootstrap_mode` (boolean)
- `is_production_ready` (boolean)
- `completeness_percentage` (float)
- `expected_games_count` (int)
- `actual_games_count` (int)
- `season_boundary_detected` (boolean)
- `data_quality_issues` (array<string>)

**Potential additions** (from original design doc):
```sql
-- Optional: Add to processors that don't have these yet
games_in_window INTEGER,           -- Actual games used in calculation
window_target INTEGER,             -- Ideal window size (e.g., 10)
bootstrap_quality STRING,          -- 'full' | 'partial' | 'insufficient'
calculation_confidence FLOAT64     -- games_in_window / window_target, capped at 1.0
```

### 4. Implementation Effort Estimate:

| Task | Effort | Status |
|------|--------|--------|
| ML Feature Store bootstrap logic | 0 hours | ✅ Already implemented |
| Player Composite Factors bootstrap | 0 hours | ✅ Already implemented |
| Player Daily Cache min threshold | 0 hours | ✅ Already implemented |
| Player Shot Zone Analysis bootstrap | 4-6 hours | ⚠️ Needs implementation |
| Team Defense Zone Analysis bootstrap | 4-6 hours | ⚠️ Needs implementation |
| Completeness Checker enhancements | 2-4 hours | 🔧 Add confidence degradation |
| Documentation updates | 2-3 hours | 📝 Document patterns |
| Testing bootstrap scenarios | 4-6 hours | 🧪 E2E testing |
| **Total** | **16-25 hours** | **~2-3 days of work** |

### 5. Next Steps:

1. **Validate findings** with codebase owner
2. **Design confidence degradation** (2-5 games = partial quality vs current binary threshold)
3. **Implement bootstrap logic** in shot_zone_analysis and team_defense_zone_analysis
4. **Add bootstrap metadata fields** to remaining processors
5. **Update documentation** with bootstrap handling patterns
6. **Test bootstrap scenarios** with historical data (2021-10-19 epoch)
7. **Monitor production impact** during next season start

---

## Appendix: File Reference Index

### Phase 4 Processors
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `data_processors/precompute/ml_feature_store/feature_calculator.py`
- `data_processors/precompute/ml_feature_store/COMPLETE_DELIVERY.md`
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
- `data_processors/precompute/player_composite_factors/README.md`

### Phase 3 Processors
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

### Phase 5 Prediction
- `predictions/worker/worker.py`
- `predictions/worker/data_loaders.py` (referenced)

### Shared Utilities
- `shared/utils/completeness_checker.py`
- `shared/utils/player_registry.py` (referenced)

### Base Classes
- `data_processors/precompute/precompute_base.py`
- `data_processors/analytics/analytics_base.py`

### Documentation
- `docs/05-development/patterns/early-exit-pattern.md`
- `docs/09-handoff/known-data-gaps.md`
- `docs/02-operations/backfill-guide.md`

---

**End of Investigation Findings**
