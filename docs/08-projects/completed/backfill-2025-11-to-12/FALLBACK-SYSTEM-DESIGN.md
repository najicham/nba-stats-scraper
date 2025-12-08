# Data Fallback & Quality Tracking System - Design Document

**Created:** 2025-11-30
**Status:** DESIGN - Pending Review
**Author:** Claude (with human oversight)

---

## Executive Summary

This document defines the complete design for a robust data fallback and quality tracking system. The system will:

1. **Handle missing data gracefully** - No more hard fails; use fallbacks or create placeholders
2. **Track quality consistently** - Standardized columns across all Phase 3+ tables
3. **Log all fallback events** - Every fallback/failure logged to `source_coverage_log`
4. **Enable informed decisions** - Quality flows through pipeline to predictions

---

## Part 1: Configuration System

### 1.1 Config File Location

```
shared/config/data_sources/
├── __init__.py           # Exports config loader
├── fallback_config.yaml  # Main config file
└── loader.py             # Python config loader
```

### 1.2 Config File Structure

```yaml
# shared/config/data_sources/fallback_config.yaml

# =============================================================================
# DATA SOURCE DEFINITIONS
# =============================================================================
sources:
  # ----- Player Stats -----
  nbac_gamebook_player_stats:
    description: "NBA.com official gamebook player stats"
    table: nbac_gamebook_player_stats
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  bdl_player_boxscores:
    description: "Ball Don't Lie player boxscores"
    table: bdl_player_boxscores
    dataset: nba_raw
    is_primary: false
    quality:
      tier: silver
      score: 85

  # ----- Team Stats -----
  nbac_team_boxscore:
    description: "NBA.com official team boxscore"
    table: nbac_team_boxscore
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  reconstructed_team_from_players:
    description: "Team totals aggregated from player boxscores"
    is_primary: false
    is_virtual: true  # Not a real table
    reconstruction_method: aggregate_player_stats_to_team
    quality:
      tier: silver
      score: 85

  # ----- Player Props -----
  odds_api_player_points_props:
    description: "Odds API live player props"
    table: odds_api_player_points_props
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  bettingpros_player_points_props:
    description: "BettingPros historical player props"
    table: bettingpros_player_points_props
    dataset: nba_raw
    is_primary: false
    quality:
      tier: silver
      score: 90

  # ----- Schedule -----
  nbac_schedule:
    description: "NBA.com official schedule"
    table: nbac_schedule
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  # ----- Game Lines -----
  odds_api_game_lines:
    description: "Odds API game spreads/totals"
    table: odds_api_game_lines
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  # ----- Play by Play / Shot Zones -----
  bigdataball_play_by_play:
    description: "BigDataBall play-by-play for shot zones"
    table: bigdataball_play_by_play
    dataset: nba_raw
    is_primary: true
    quality:
      tier: gold
      score: 100

  nbac_play_by_play:
    description: "NBA.com play-by-play (partial)"
    table: nbac_play_by_play
    dataset: nba_raw
    is_primary: false
    quality:
      tier: silver
      score: 90


# =============================================================================
# FALLBACK CHAINS
# =============================================================================
# Each chain defines sources to try in order and what to do when all fail
#
# on_all_fail actions:
#   skip: Don't process this entity, log and continue to next
#   placeholder: Create a record with unusable quality tier
#   fail: Raise exception (for truly critical data)
#   continue_without: Process without this data, degrade quality

fallback_chains:
  player_boxscores:
    description: "Player game statistics"
    sources:
      - nbac_gamebook_player_stats
      - bdl_player_boxscores
    on_all_fail:
      action: skip
      severity: critical
      message: "No player boxscore data available"

  team_boxscores:
    description: "Team game statistics"
    sources:
      - nbac_team_boxscore
      - reconstructed_team_from_players
    on_all_fail:
      action: placeholder
      quality_tier: unusable
      quality_score: 0
      severity: critical
      message: "No team boxscore data available"

  player_props:
    description: "Player points prop lines"
    sources:
      - odds_api_player_points_props
      - bettingpros_player_points_props
    on_all_fail:
      action: skip
      severity: warning
      message: "No prop lines available for player"

  game_schedule:
    description: "Game schedule"
    sources:
      - nbac_schedule
    on_all_fail:
      action: fail
      severity: critical
      message: "No schedule data available - cannot proceed"

  game_lines:
    description: "Game spreads and totals"
    sources:
      - odds_api_game_lines
    on_all_fail:
      action: continue_without
      quality_impact: -10
      severity: info
      message: "No game lines available (likely All-Star weekend)"

  shot_zones:
    description: "Shot zone distribution from play-by-play"
    sources:
      - bigdataball_play_by_play
      - nbac_play_by_play
    on_all_fail:
      action: continue_without
      quality_impact: -15
      severity: info
      message: "No shot zone data available"


# =============================================================================
# QUALITY TIERS & THRESHOLDS
# =============================================================================
quality_tiers:
  gold:
    score_min: 95
    score_max: 100
    confidence_ceiling: 1.00
    description: "Primary sources, complete data"
    prediction_eligible: true

  silver:
    score_min: 75
    score_max: 94
    confidence_ceiling: 0.95
    description: "Fallback source used or minor gaps"
    prediction_eligible: true

  bronze:
    score_min: 50
    score_max: 74
    confidence_ceiling: 0.80
    description: "Significant gaps or thin sample"
    prediction_eligible: true

  poor:
    score_min: 25
    score_max: 49
    confidence_ceiling: 0.60
    description: "Major issues, flagged for review"
    prediction_eligible: true

  unusable:
    score_min: 0
    score_max: 24
    confidence_ceiling: 0.00
    description: "Cannot generate reliable output"
    prediction_eligible: false


# =============================================================================
# QUALITY PROPAGATION RULES
# =============================================================================
quality_propagation:
  # Phase 3 → Phase 4: How quality aggregates across multiple inputs
  aggregation_rule: worst_wins

  # When calculating rolling averages, how to handle low-quality games
  low_quality_in_lookback:
    action: flag  # Options: flag, exclude, weight
    flag_issue: "includes_low_quality_input"
    exclude_threshold: unusable  # Only exclude unusable tier

  # Phase 4 → Phase 5 threshold
  prediction_threshold:
    min_quality_score: 70
    require_production_ready: true


# =============================================================================
# RECONSTRUCTION METHODS
# =============================================================================
reconstruction_methods:
  aggregate_player_stats_to_team:
    description: "Sum player boxscore stats to derive team totals"
    input_chain: player_boxscores
    aggregation: sum
    fields:
      - points
      - rebounds
      - assists
      - steals
      - blocks
      - turnovers
      - field_goals_made
      - field_goals_attempted
      - three_pointers_made
      - three_pointers_attempted
      - free_throws_made
      - free_throws_attempted
      - offensive_rebounds
      - defensive_rebounds
      - personal_fouls
    notes: "Mathematically equivalent to team boxscore (verified)"
```

---

## Part 2: Schema Standardization

### 2.1 Standard Quality Columns

Every Phase 3+ table will have these columns:

```sql
-- ============================================================================
-- STANDARD QUALITY COLUMNS (Required on all Phase 3+ tables)
-- ============================================================================

-- Core Quality Tracking
quality_tier STRING,                  -- 'gold', 'silver', 'bronze', 'poor', 'unusable'
quality_score FLOAT64,                -- 0-100 numeric score
quality_issues ARRAY<STRING>,         -- ['backup_source_used', 'thin_sample:3/10']
data_sources ARRAY<STRING>,           -- ['nbac_gamebook', 'bdl_fallback']
is_production_ready BOOL,             -- Can be used for predictions?

-- Completeness Tracking
expected_games_count INT64,           -- How many games expected in lookback
actual_games_count INT64,             -- How many games actually found
completeness_percentage FLOAT64,      -- actual/expected * 100
missing_games_count INT64,            -- expected - actual

-- Circuit Breaker / Reprocessing
last_reprocess_attempt_at TIMESTAMP,
reprocess_attempt_count INT64,
circuit_breaker_active BOOL,
circuit_breaker_until TIMESTAMP,

-- Bootstrap / Remediation
backfill_bootstrap_mode BOOL,         -- Processing in early-season mode
season_boundary_detected BOOL,        -- Crossed season boundary
requires_remediation BOOL,            -- Needs manual review/fix
remediation_priority STRING,          -- 'critical', 'high', 'medium', 'low'
processing_decision_reason STRING,    -- Why processor made this decision
```

### 2.2 Migration Plan by Table

| Table | Current State | Changes Needed |
|-------|---------------|----------------|
| `player_game_summary` | Has `data_quality_tier` + new `quality_tier` | Remove `data_quality_tier`, keep `quality_tier` |
| `team_defense_game_summary` | Has `data_quality_tier` only | Add all standard columns |
| `team_offense_game_summary` | Has `data_quality_tier` only | Add all standard columns |
| `upcoming_player_game_context` | Has `data_quality_tier` + completeness | Rename to `quality_tier`, add missing |
| `upcoming_team_game_context` | Has completeness, NO quality tier | Add `quality_tier`, `quality_score`, `quality_issues` |
| `ml_feature_store_v2` | Has `feature_quality_score` | Add `quality_tier`, keep score |
| `player_daily_cache` | Has completeness only | Add `quality_tier`, `quality_score` |
| `team_defense_zone_analysis` | Has `data_quality_tier` + completeness | Rename to `quality_tier` |

### 2.3 Backward Compatibility

During migration:
1. Add new columns without removing old ones
2. Update processors to write BOTH old and new columns
3. After verification, deprecate old columns (can remove later)

---

## Part 3: Python Implementation

### 3.1 Config Loader

```python
# shared/config/data_sources/loader.py

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class SourceConfig:
    """Configuration for a single data source."""
    name: str
    description: str
    dataset: str
    table: Optional[str]
    is_primary: bool
    is_virtual: bool
    quality_tier: str
    quality_score: float
    reconstruction_method: Optional[str] = None

@dataclass
class FallbackChainConfig:
    """Configuration for a fallback chain."""
    name: str
    description: str
    sources: List[str]
    on_all_fail_action: str
    on_all_fail_severity: str
    on_all_fail_message: str
    on_all_fail_quality_tier: Optional[str] = None
    on_all_fail_quality_score: Optional[float] = None
    on_all_fail_quality_impact: Optional[float] = None

@dataclass
class QualityTierConfig:
    """Configuration for a quality tier."""
    name: str
    score_min: float
    score_max: float
    confidence_ceiling: float
    description: str
    prediction_eligible: bool

class DataSourceConfig:
    """
    Singleton config loader for data source configuration.

    Usage:
        config = DataSourceConfig()
        source = config.get_source('nbac_team_boxscore')
        chain = config.get_fallback_chain('team_boxscores')
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        config_path = Path(__file__).parent / 'fallback_config.yaml'
        with open(config_path) as f:
            self._config = yaml.safe_load(f)
        self._parse_config()

    def _parse_config(self):
        """Parse config into typed objects."""
        self._sources = {}
        for name, data in self._config.get('sources', {}).items():
            self._sources[name] = SourceConfig(
                name=name,
                description=data.get('description', ''),
                dataset=data.get('dataset', ''),
                table=data.get('table'),
                is_primary=data.get('is_primary', False),
                is_virtual=data.get('is_virtual', False),
                quality_tier=data.get('quality', {}).get('tier', 'gold'),
                quality_score=data.get('quality', {}).get('score', 100),
                reconstruction_method=data.get('reconstruction_method'),
            )

        self._chains = {}
        for name, data in self._config.get('fallback_chains', {}).items():
            on_fail = data.get('on_all_fail', {})
            self._chains[name] = FallbackChainConfig(
                name=name,
                description=data.get('description', ''),
                sources=data.get('sources', []),
                on_all_fail_action=on_fail.get('action', 'skip'),
                on_all_fail_severity=on_fail.get('severity', 'warning'),
                on_all_fail_message=on_fail.get('message', ''),
                on_all_fail_quality_tier=on_fail.get('quality_tier'),
                on_all_fail_quality_score=on_fail.get('quality_score'),
                on_all_fail_quality_impact=on_fail.get('quality_impact'),
            )

        self._tiers = {}
        for name, data in self._config.get('quality_tiers', {}).items():
            self._tiers[name] = QualityTierConfig(
                name=name,
                score_min=data.get('score_min', 0),
                score_max=data.get('score_max', 100),
                confidence_ceiling=data.get('confidence_ceiling', 1.0),
                description=data.get('description', ''),
                prediction_eligible=data.get('prediction_eligible', True),
            )

    def get_source(self, name: str) -> SourceConfig:
        """Get configuration for a data source."""
        if name not in self._sources:
            raise ValueError(f"Unknown source: {name}")
        return self._sources[name]

    def get_fallback_chain(self, name: str) -> FallbackChainConfig:
        """Get configuration for a fallback chain."""
        if name not in self._chains:
            raise ValueError(f"Unknown fallback chain: {name}")
        return self._chains[name]

    def get_tier(self, name: str) -> QualityTierConfig:
        """Get configuration for a quality tier."""
        if name not in self._tiers:
            raise ValueError(f"Unknown tier: {name}")
        return self._tiers[name]

    def get_tier_from_score(self, score: float) -> str:
        """Determine tier name from numeric score."""
        for name, tier in self._tiers.items():
            if tier.score_min <= score <= tier.score_max:
                return name
        return 'unusable'

    def get_propagation_rules(self) -> Dict:
        """Get quality propagation rules."""
        return self._config.get('quality_propagation', {})

    def get_reconstruction_method(self, name: str) -> Optional[Dict]:
        """Get reconstruction method configuration."""
        methods = self._config.get('reconstruction_methods', {})
        return methods.get(name)
```

### 3.2 FallbackSourceMixin

```python
# shared/processors/mixins/fallback_source_mixin.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
import pandas as pd
import logging

from shared.config.data_sources import DataSourceConfig
from shared.config.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity,
)

logger = logging.getLogger(__name__)


@dataclass
class FallbackResult:
    """Result of attempting a fallback chain."""
    success: bool
    data: Optional[pd.DataFrame]
    source_used: Optional[str]
    quality_tier: str
    quality_score: float
    sources_tried: List[str] = field(default_factory=list)
    is_primary: bool = True
    is_reconstructed: bool = False
    is_placeholder: bool = False
    should_skip: bool = False
    continued_without: bool = False
    quality_issues: List[str] = field(default_factory=list)


class FallbackSourceMixin:
    """
    Mixin providing fallback data source functionality.

    Reads fallback chains from config and tries sources in order.
    Logs events to source_coverage_log via QualityMixin.

    Usage:
        class MyProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):
            def extract_team_data(self, game_id, game_date):
                result = self.try_fallback_chain(
                    chain_name='team_boxscores',
                    extractors={
                        'nbac_team_boxscore': lambda: self._query_nbac(game_id),
                        'reconstructed_team_from_players': lambda: self._reconstruct(game_id),
                    },
                    context={'game_id': game_id, 'game_date': game_date},
                )

                if result.success:
                    return result.data, result.quality_tier, result.quality_score
                elif result.should_skip:
                    return None, None, None  # Skip this entity
                elif result.is_placeholder:
                    return self._create_placeholder(), 'unusable', 0
    """

    _ds_config: DataSourceConfig = None

    def _ensure_config(self):
        """Lazy-load config."""
        if self._ds_config is None:
            self._ds_config = DataSourceConfig()

    def try_fallback_chain(
        self,
        chain_name: str,
        extractors: Dict[str, Callable[[], pd.DataFrame]],
        context: Dict[str, Any] = None,
    ) -> FallbackResult:
        """
        Try sources in fallback chain order until one succeeds.

        Args:
            chain_name: Name of fallback chain from config
            extractors: Dict mapping source names to callables that return DataFrames
            context: Additional context for logging (game_id, game_date, etc.)

        Returns:
            FallbackResult with data and quality information
        """
        self._ensure_config()
        context = context or {}

        chain = self._ds_config.get_fallback_chain(chain_name)
        sources_tried = []
        quality_issues = []

        for source_name in chain.sources:
            if source_name not in extractors:
                logger.warning(f"No extractor provided for source '{source_name}', skipping")
                continue

            source_config = self._ds_config.get_source(source_name)
            extractor = extractors[source_name]

            try:
                logger.debug(f"Trying source: {source_name}")
                df = extractor()

                if df is not None and not df.empty:
                    # Success!
                    is_fallback = not source_config.is_primary
                    is_reconstructed = source_config.reconstruction_method is not None

                    if is_fallback:
                        quality_issues.append('backup_source_used')
                    if is_reconstructed:
                        quality_issues.append('reconstructed')

                    # Log fallback usage
                    if is_fallback and hasattr(self, 'log_quality_event'):
                        self.log_quality_event(
                            event_type=SourceCoverageEventType.FALLBACK_USED.value,
                            severity=SourceCoverageSeverity.INFO.value,
                            description=f"Used fallback '{source_name}' for {chain_name}",
                            game_id=context.get('game_id'),
                            game_date=context.get('game_date'),
                            primary_source=chain.sources[0] if chain.sources else None,
                            primary_source_status='missing',
                            fallback_sources_tried=sources_tried,
                            resolution='used_fallback',
                            quality_after={
                                'tier': source_config.quality_tier,
                                'score': source_config.quality_score,
                            },
                        )

                    return FallbackResult(
                        success=True,
                        data=df,
                        source_used=source_name,
                        quality_tier=source_config.quality_tier,
                        quality_score=source_config.quality_score,
                        sources_tried=sources_tried + [source_name],
                        is_primary=source_config.is_primary,
                        is_reconstructed=is_reconstructed,
                        quality_issues=quality_issues,
                    )

                # Source returned empty
                sources_tried.append(source_name)
                logger.info(f"Source '{source_name}' returned empty data")

            except Exception as e:
                sources_tried.append(source_name)
                logger.warning(f"Source '{source_name}' failed with error: {e}")

        # All sources failed
        return self._handle_all_failed(chain, sources_tried, context)

    def _handle_all_failed(
        self,
        chain,
        sources_tried: List[str],
        context: Dict[str, Any],
    ) -> FallbackResult:
        """Handle when all sources in a chain fail."""
        self._ensure_config()

        action = chain.on_all_fail_action
        game_id = context.get('game_id')
        game_date = context.get('game_date')

        # Log the failure
        if hasattr(self, 'log_quality_event'):
            severity_map = {
                'critical': SourceCoverageSeverity.CRITICAL.value,
                'warning': SourceCoverageSeverity.WARNING.value,
                'info': SourceCoverageSeverity.INFO.value,
            }
            self.log_quality_event(
                event_type=SourceCoverageEventType.SOURCE_MISSING.value,
                severity=severity_map.get(chain.on_all_fail_severity, 'warning'),
                description=chain.on_all_fail_message,
                game_id=game_id,
                game_date=game_date,
                primary_source=chain.sources[0] if chain.sources else None,
                primary_source_status='missing',
                fallback_sources_tried=sources_tried,
                resolution='failed' if action == 'fail' else 'skipped',
                downstream_impact='predictions_blocked' if action in ['fail', 'skip'] else 'confidence_reduced',
            )

        if action == 'fail':
            raise ValueError(chain.on_all_fail_message)

        elif action == 'skip':
            return FallbackResult(
                success=False,
                data=None,
                source_used=None,
                quality_tier='unusable',
                quality_score=0,
                sources_tried=sources_tried,
                should_skip=True,
                quality_issues=['all_sources_failed'],
            )

        elif action == 'placeholder':
            return FallbackResult(
                success=False,
                data=None,
                source_used=None,
                quality_tier=chain.on_all_fail_quality_tier or 'unusable',
                quality_score=chain.on_all_fail_quality_score or 0,
                sources_tried=sources_tried,
                is_placeholder=True,
                quality_issues=['all_sources_failed', 'placeholder_created'],
            )

        elif action == 'continue_without':
            # Calculate degraded score
            base_score = 100
            impact = chain.on_all_fail_quality_impact or -20
            degraded_score = max(0, base_score + impact)
            tier = self._ds_config.get_tier_from_score(degraded_score)

            return FallbackResult(
                success=True,  # Continue processing
                data=pd.DataFrame(),  # Empty but valid
                source_used=None,
                quality_tier=tier,
                quality_score=degraded_score,
                sources_tried=sources_tried,
                continued_without=True,
                quality_issues=['data_unavailable', f'quality_degraded:{impact}'],
            )

        else:
            raise ValueError(f"Unknown on_all_fail action: {action}")

    def build_standard_quality_columns(
        self,
        quality_tier: str,
        quality_score: float,
        quality_issues: List[str],
        data_sources: List[str],
        is_production_ready: bool = None,
        completeness: Dict = None,
    ) -> Dict:
        """
        Build standard quality columns dict for BigQuery insertion.

        Args:
            quality_tier: 'gold', 'silver', 'bronze', 'poor', 'unusable'
            quality_score: 0-100 numeric
            quality_issues: List of issue strings
            data_sources: List of source names used
            is_production_ready: Override production readiness
            completeness: Dict with completeness metrics

        Returns:
            Dict of column name -> value for quality columns
        """
        self._ensure_config()

        # Determine production readiness
        if is_production_ready is None:
            tier_config = self._ds_config.get_tier(quality_tier)
            is_production_ready = tier_config.prediction_eligible and quality_score >= 70

        columns = {
            'quality_tier': quality_tier,
            'quality_score': quality_score,
            'quality_issues': quality_issues,
            'data_sources': data_sources,
            'is_production_ready': is_production_ready,
        }

        # Add completeness if provided
        if completeness:
            columns.update({
                'expected_games_count': completeness.get('expected'),
                'actual_games_count': completeness.get('actual'),
                'completeness_percentage': completeness.get('percentage'),
                'missing_games_count': completeness.get('missing'),
            })

        return columns
```

---

## Part 4: Processor Changes

### 4.1 Fix Hard Fails

**team_defense_game_summary_processor.py (Line 192)**

Current:
```python
raise ValueError("Missing opponent offensive data from nbac_team_boxscore")
```

New:
```python
# Try fallback chain for team boxscores
result = self.try_fallback_chain(
    chain_name='team_boxscores',
    extractors={
        'nbac_team_boxscore': lambda: self._extract_opponent_offense(game_id),
        'reconstructed_team_from_players': lambda: self._reconstruct_team_from_players(game_id),
    },
    context={'game_id': game_id, 'game_date': game_date},
)

if result.should_skip or result.is_placeholder:
    # Create placeholder record with unusable quality
    return self._create_placeholder_record(game_id, game_date, result.quality_issues)

opponent_offense_df = result.data
quality_tier = result.quality_tier
quality_score = result.quality_score
```

**team_offense_game_summary_processor.py (Line 397)**

Similar pattern - convert hard fail to graceful handling.

### 4.2 Processor Inheritance Updates

All Phase 3 processors should inherit from:

```python
class TeamDefenseGameSummaryProcessor(
    FallbackSourceMixin,  # For fallback chains
    QualityMixin,         # For quality assessment & logging
    AnalyticsProcessorBase,
):
    PHASE = 'phase_3'
    OUTPUT_TABLE = 'nba_analytics.team_defense_game_summary'
    # ... rest of processor
```

---

## Part 5: Source Coverage Log Integration

### 5.1 When to Log Events

| Event Type | When to Log | Severity |
|------------|-------------|----------|
| `fallback_used` | Primary source missing, using fallback | info |
| `source_missing` | All sources in chain failed | warning/critical |
| `reconstruction_applied` | Using reconstructed/derived data | info |
| `quality_degradation` | Quality dropped from previous run | warning |
| `processing_skipped` | Entity skipped due to data issues | warning |

### 5.2 Automatic Logging via Mixins

The `FallbackSourceMixin.try_fallback_chain()` automatically logs:
- When a fallback source is used
- When all sources fail

The `QualityMixin` provides:
- `log_quality_event()` for manual logging
- `flush_events()` called automatically via context manager
- Alert deduplication (won't spam for same issue)

---

## Part 6: Implementation Plan

### Phase 1: Config & Infrastructure (Day 1)
- [ ] Create `shared/config/data_sources/` directory
- [ ] Create `fallback_config.yaml` with full source definitions
- [ ] Create `loader.py` config loader
- [ ] Create/update `FallbackSourceMixin`
- [ ] Unit tests for config loading

### Phase 2: Schema Updates (Day 1-2)
- [ ] Create migration SQL for each table
- [ ] Add new columns (don't remove old yet)
- [ ] Run migrations in BigQuery

### Phase 3: Fix Hard Fails (Day 2)
- [ ] Update `team_defense_game_summary_processor.py`
  - Add reconstruction method for team stats
  - Replace ValueError with fallback chain
- [ ] Update `team_offense_game_summary_processor.py`
  - Same pattern

### Phase 4: Update All Phase 3 Processors (Day 2-3)
- [ ] `player_game_summary_processor.py` - Standardize quality columns
- [ ] `team_defense_game_summary_processor.py` - Full integration
- [ ] `team_offense_game_summary_processor.py` - Full integration
- [ ] `upcoming_player_game_context_processor.py` - Rename columns
- [ ] `upcoming_team_game_context_processor.py` - Add missing quality columns

### Phase 5: Source Coverage Log (Day 3)
- [ ] Verify QualityMixin is inherited by all processors
- [ ] Add `with self:` context manager pattern to processors
- [ ] Test events are being logged
- [ ] Verify alert deduplication works

### Phase 6: Testing & Documentation (Day 4)
- [ ] Test with missing data scenarios
- [ ] Test fallback chains work correctly
- [ ] Verify quality propagates correctly
- [ ] Update documentation

---

## Part 7: Verification Queries

After implementation, run these queries to verify:

```sql
-- Check source_coverage_log is receiving events
SELECT
  DATE(event_timestamp) as date,
  event_type,
  COUNT(*) as count
FROM `nba-props-platform.nba_reference.source_coverage_log`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- Check quality distribution across tables
SELECT
  'player_game_summary' as table_name,
  quality_tier,
  COUNT(*) as count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-01-01'
GROUP BY 1, 2

UNION ALL

SELECT
  'team_defense_game_summary',
  quality_tier,
  COUNT(*)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date >= '2024-01-01'
GROUP BY 1, 2;

-- Check for any unusable records
SELECT
  table_name,
  game_date,
  quality_tier,
  quality_issues
FROM (
  SELECT 'player_game_summary' as table_name, game_date, quality_tier, quality_issues
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE quality_tier = 'unusable'

  UNION ALL

  SELECT 'team_defense_game_summary', game_date, quality_tier, quality_issues
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE quality_tier = 'unusable'
)
ORDER BY game_date DESC
LIMIT 100;
```

---

## Summary

This design provides:

1. **Declarative Config** - All source definitions and fallback chains in YAML
2. **Standardized Quality** - Same columns across all Phase 3+ tables
3. **Graceful Degradation** - No more hard fails; fallbacks or placeholders
4. **Full Audit Trail** - Every fallback/failure logged to source_coverage_log
5. **Informed Decisions** - Quality flows through to predictions

**Questions for Review:**

1. Does the YAML config structure make sense?
2. Are there any sources or fallback chains I missed?
3. Is the implementation plan timeline realistic?
4. Any concerns about the schema migration approach?
