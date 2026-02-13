# File: data_processors/precompute/ml_feature_store/quality_scorer.py
"""
Quality Scorer - Feature Quality Visibility System

Calculates per-feature and aggregate quality metrics for ml_feature_store_v2.
Part of Session 134/137 Feature Quality Visibility project.

Quality scoring is based on data source weights:
- Phase 4 data: 100 points (highest quality, precomputed)
- Phase 3 data: 87 points (good quality, analytics-derived)
- Calculated: 100 points (on-the-fly, always available)
- Default: 40 points (using fallback/default values)
- Vegas: 100 points (high quality when available)
- Opponent history: 90 points (Phase 4 opponent data)
- Minutes/PPM: 95 points (Phase 4 daily cache)
- Fallback: 40 points (same as default)
- Missing: 0 points (no data at all)

Source types from the processor are mapped to 4 canonical types:
- phase4, phase3, calculated, default

Feature quality tiers (specific to ML feature store):
- gold (>= 95): All features from high-quality sources
- silver (85-94): Minor gaps, mostly high quality
- bronze (70-84): Some Phase 3 fallback or defaults
- poor (50-69): Significant defaults, needs investigation
- critical (< 50): Feature vector unreliable
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Source weights for quality scoring
# Maps raw source types from the processor to quality scores (0-100)
SOURCE_WEIGHTS = {
    'phase4': 100,
    'phase3': 87,           # Increased from 75 based on Agent Findings (Jan 19, 2026)
    'calculated': 100,      # Calculated features always high quality
    'default': 40,
    'vegas': 100,           # Vegas data is high quality when available
    'opponent_history': 90, # Opponent history from Phase 4
    'minutes_ppm': 95,      # Minutes/PPM from Phase 4 daily cache
    'fallback': 40,         # Fallback = using default value
    'missing': 0,           # Missing = no data at all
}

# Map raw source types to 4 canonical types for per-feature columns
SOURCE_TYPE_CANONICAL = {
    'phase4': 'phase4',
    'phase3': 'phase3',
    'calculated': 'calculated',
    'default': 'default',
    'vegas': 'phase4',
    'opponent_history': 'phase4',
    'minutes_ppm': 'phase4',
    'fallback': 'default',
    'missing': 'default',
}

# Feature categories for quality grouping
# Total: 6 + 20 + 3 + 4 + 21 = 54
FEATURE_CATEGORIES = {
    'matchup': [5, 6, 7, 8, 13, 14],
    'player_history': [0, 1, 2, 3, 4, 29, 30, 31, 32, 33, 34, 35, 36, 37, 43, 44, 45, 46, 48, 49],
    'team_context': [22, 23, 24],
    'vegas': [25, 26, 27, 28],
    'game_context': [9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 21, 38, 39, 40, 41, 42, 47, 50, 51, 52, 53],
}

# Critical features - Session 132 issue area
CRITICAL_FEATURES = [5, 6, 7, 8, 13, 14]

# Composite factor features (subset of critical)
COMPOSITE_FACTOR_FEATURES = [5, 6, 7, 8]

# Opponent defense features (subset of critical)
OPPONENT_DEFENSE_FEATURES = [13, 14]

# Upstream table mapping per feature
FEATURE_UPSTREAM_TABLES = {
    0: 'player_daily_cache', 1: 'player_daily_cache',
    2: 'player_daily_cache', 3: 'player_daily_cache',
    4: 'player_daily_cache',
    5: 'player_composite_factors', 6: 'player_composite_factors',
    7: 'player_composite_factors', 8: 'player_composite_factors',
    9: 'calculated', 10: 'calculated', 11: 'calculated', 12: 'calculated',
    13: 'team_defense_zone_analysis', 14: 'team_defense_zone_analysis',
    15: 'upcoming_player_game_context', 16: 'upcoming_player_game_context',
    17: 'upcoming_player_game_context',
    18: 'player_shot_zone_analysis', 19: 'player_shot_zone_analysis',
    20: 'player_shot_zone_analysis', 21: 'calculated',
    22: 'team_offense_game_summary', 23: 'team_offense_game_summary',
    24: 'calculated',
    25: 'odds_api', 26: 'odds_api', 27: 'calculated', 28: 'calculated',
    29: 'player_game_summary', 30: 'player_game_summary',
    31: 'player_daily_cache', 32: 'player_daily_cache',
    33: 'calculated', 34: 'calculated', 35: 'calculated', 36: 'calculated',
    37: 'upcoming_player_game_context', 38: 'upcoming_player_game_context',
    # V12 features (39-53)
    39: 'upcoming_player_game_context', 40: 'upcoming_player_game_context',
    41: 'upcoming_player_game_context', 42: 'calculated',
    43: 'calculated', 44: 'calculated', 45: 'calculated', 46: 'calculated',
    47: 'default', 48: 'calculated', 49: 'calculated',
    50: 'default', 51: 'upcoming_player_game_context', 52: 'upcoming_player_game_context',
    53: 'calculated',
}

# Default fallback reasons per feature (when source is default/fallback/missing)
DEFAULT_FALLBACK_REASONS = {
    5: 'composite_factors_missing', 6: 'composite_factors_missing',
    7: 'composite_factors_missing', 8: 'composite_factors_missing',
    13: 'opponent_defense_missing', 14: 'opponent_defense_missing',
    18: 'shot_zone_data_missing', 19: 'shot_zone_data_missing',
    20: 'shot_zone_data_missing',
    25: 'vegas_line_unavailable', 26: 'vegas_line_unavailable',
    27: 'vegas_line_unavailable',
    29: 'no_opponent_history', 30: 'no_opponent_history',
    31: 'minutes_ppm_unavailable', 32: 'minutes_ppm_unavailable',
    37: 'star_teammates_out_unavailable', 38: 'game_total_line_unavailable',
    # V12 features (39-53)
    39: 'days_rest_unavailable', 40: 'minutes_load_unavailable',
    41: 'spread_unavailable', 42: 'implied_team_total_unavailable',
    43: 'rolling_stats_unavailable', 44: 'rolling_stats_unavailable',
    45: 'rolling_stats_unavailable', 46: 'rolling_stats_unavailable',
    47: 'dead_feature', 48: 'rolling_stats_unavailable',
    49: 'rolling_stats_unavailable', 50: 'dead_feature',
    51: 'prop_streaks_unavailable', 52: 'prop_streaks_unavailable',
    53: 'line_vs_season_unavailable',
}

# Session 145: Optional features - not counted in zero-tolerance gating
# Vegas lines unavailable for ~60% of players (bench players without published lines)
# Still tracked as defaults for visibility, but don't block predictions
OPTIONAL_FEATURES = {25, 26, 27, 38, 41, 42, 47, 50, 51, 52, 53}  # Vegas, game_total, dead features, streaks, line_vs_avg

# Training quality threshold per feature
TRAINING_QUALITY_THRESHOLD = 85.0

# Quality schema version
QUALITY_SCHEMA_VERSION = 'v1_hybrid_20260205'

# Total feature count
FEATURE_COUNT = 54


# ============================================================================
# TIER FUNCTIONS
# ============================================================================

def get_feature_quality_tier(score: float) -> str:
    """
    Classify feature quality score into visibility tier.

    These thresholds are specific to ML feature store quality assessment.
    For source-level quality tiers, use shared.config.source_coverage.get_tier_from_score().

    Args:
        score: Quality score [0, 100]

    Returns:
        str: 'gold', 'silver', 'bronze', 'poor', or 'critical'
    """
    if score >= 95.0:
        return 'gold'
    elif score >= 85.0:
        return 'silver'
    elif score >= 70.0:
        return 'bronze'
    elif score >= 50.0:
        return 'poor'
    else:
        return 'critical'


# ============================================================================
# QUALITY SCORER CLASS
# ============================================================================

class QualityScorer:
    """Calculate feature quality scores and build quality visibility fields."""

    # Class-level reference to module constant for backward compatibility
    SOURCE_WEIGHTS = SOURCE_WEIGHTS

    def __init__(self):
        """Initialize quality scorer."""
        pass

    def calculate_quality_score(self, feature_sources: Dict[int, str]) -> float:
        """
        Calculate overall feature quality score.

        Quality = weighted average of source quality across all features,
        CAPPED when required (non-vegas) defaults exist.

        Session 157: Added default penalty cap. Previously, 5 defaulted features
        could still produce a 91.9 score (because 32 good features carried the
        average). This masked the contamination bug that allowed 33% of V9 training
        data to have garbage default values. Now:
        - 1+ required defaults → score capped at 69 (below bronze threshold)
        - 5+ required defaults → score capped at 49 (critical tier)
        This makes the score honest: any record with defaults is visibly degraded.

        Args:
            feature_sources: Dict mapping feature index to source type.
                Supports all 9 source types (phase4, phase3, calculated,
                default, vegas, opponent_history, minutes_ppm, fallback, missing).

        Returns:
            float: Quality score [0.0, 100.0]
        """
        if not feature_sources:
            logger.warning("No feature sources provided, returning 0")
            return 0.0

        num_features = len(feature_sources)

        total_weight = 0.0
        for feature_idx in range(num_features):
            source = feature_sources.get(feature_idx, 'default')
            weight = SOURCE_WEIGHTS.get(source, 40)
            total_weight += weight

        quality_score = total_weight / float(num_features)

        # Session 157: Cap score when required (non-vegas) defaults exist.
        # The weighted average masks individual defaults — a record with 5 defaults
        # could score 91.9, which is misleading. Cap ensures the score reflects
        # that the record contains garbage data and shouldn't be used for training.
        required_defaults = sum(
            1 for idx in range(num_features)
            if feature_sources.get(idx, 'default') in ('default', 'fallback', 'missing')
            and idx not in OPTIONAL_FEATURES
        )
        if required_defaults >= 5:
            quality_score = min(quality_score, 49.0)  # Critical tier
        elif required_defaults >= 1:
            quality_score = min(quality_score, 69.0)  # Below bronze threshold

        logger.debug(
            f"Quality score: {quality_score:.1f} for {num_features} features "
            f"(sources: {self._summarize_sources(feature_sources)}"
            f"{f', capped due to {required_defaults} required defaults' if required_defaults > 0 else ''})"
        )

        return round(quality_score, 2)

    def determine_primary_source(self, feature_sources: Dict[int, str]) -> str:
        """
        Determine primary data source used.

        Rules:
        - If >90% Phase 4: 'phase4'
        - If >50% Phase 4: 'phase4_partial'
        - If >50% Phase 3: 'phase3'
        - Otherwise: 'mixed'

        Args:
            feature_sources: Dict mapping feature index to source

        Returns:
            str: Primary source identifier
        """
        phase4_count = sum(1 for s in feature_sources.values() if s == 'phase4')
        phase3_count = sum(1 for s in feature_sources.values() if s == 'phase3')
        total = len(feature_sources)

        if total == 0:
            return 'unknown'

        phase4_pct = phase4_count / total
        phase3_pct = phase3_count / total

        if phase4_pct >= 0.90:
            return 'phase4'
        elif phase4_pct >= 0.50:
            return 'phase4_partial'
        elif phase3_pct >= 0.50:
            return 'phase3'
        else:
            return 'mixed'

    def identify_data_tier(self, quality_score: float) -> str:
        """
        DEPRECATED: Use get_feature_quality_tier() for new code.
        Kept for backward compatibility with existing tests.

        Classify quality score into tier.

        Args:
            quality_score: Quality score [0, 100]

        Returns:
            str: 'high', 'medium', or 'low'
        """
        if quality_score >= 95:
            return 'high'
        elif quality_score >= 70:
            return 'medium'
        else:
            return 'low'

    def build_quality_visibility_fields(
        self,
        feature_sources: Dict[int, str],
        feature_values: list,
        feature_names: list,
        quality_score: float,
    ) -> Dict:
        """
        Build all quality visibility fields for ml_feature_store_v2.

        Returns a dict with ~120 fields ready to merge into the record.
        Does NOT include feature_quality_score or is_production_ready (set separately).

        Args:
            feature_sources: Dict mapping feature index to source type
            feature_values: List of feature float values
            feature_names: List of feature names
            quality_score: Pre-computed aggregate quality score

        Returns:
            Dict with all quality visibility fields
        """
        num_features = min(len(feature_values), len(feature_names), FEATURE_COUNT)

        # ================================================================
        # Per-feature quality scores and canonical sources
        # ================================================================
        per_feature_quality = {}
        per_feature_source = {}
        is_default = {}

        for idx in range(num_features):
            source = feature_sources.get(idx, 'default')
            weight = SOURCE_WEIGHTS.get(source, 40)
            per_feature_quality[idx] = float(weight)
            per_feature_source[idx] = SOURCE_TYPE_CANONICAL.get(source, 'default')
            is_default[idx] = source in ('default', 'fallback', 'missing')

        # ================================================================
        # Source distribution counts
        # ================================================================
        canonical_counts = {'phase4': 0, 'phase3': 0, 'calculated': 0, 'default': 0}
        for idx in range(num_features):
            canonical = per_feature_source.get(idx, 'default')
            canonical_counts[canonical] = canonical_counts.get(canonical, 0) + 1

        default_count = sum(1 for idx in range(num_features) if is_default.get(idx, True))

        # Session 145: Required defaults exclude optional features (vegas)
        # Used for is_quality_ready gating - vegas absence doesn't block predictions
        required_default_count = sum(
            1 for idx in range(num_features)
            if is_default.get(idx, True) and idx not in OPTIONAL_FEATURES
        )

        # ================================================================
        # Category quality
        # ================================================================
        category_quality = {}
        category_defaults = {}
        for cat_name, cat_indices in FEATURE_CATEGORIES.items():
            cat_scores = [
                per_feature_quality.get(idx, 0.0)
                for idx in cat_indices if idx < num_features
            ]
            cat_def_count = sum(
                1 for idx in cat_indices
                if idx < num_features and is_default.get(idx, True)
            )

            if cat_scores:
                category_quality[cat_name] = round(sum(cat_scores) / len(cat_scores), 1)
            else:
                category_quality[cat_name] = 0.0
            category_defaults[cat_name] = cat_def_count

        # ================================================================
        # Critical feature checks
        # ================================================================
        has_composite = not any(
            is_default.get(idx, True)
            for idx in COMPOSITE_FACTOR_FEATURES if idx < num_features
        )
        has_opponent_defense = not any(
            is_default.get(idx, True)
            for idx in OPPONENT_DEFENSE_FEATURES if idx < num_features
        )
        has_vegas = not is_default.get(28, True)  # has_vegas_line feature

        critical_quality = [
            per_feature_quality.get(idx, 0.0)
            for idx in CRITICAL_FEATURES if idx < num_features
        ]
        critical_high_quality = sum(
            1 for q in critical_quality if q >= TRAINING_QUALITY_THRESHOLD
        )
        critical_all_training = (
            all(q >= TRAINING_QUALITY_THRESHOLD for q in critical_quality)
            if critical_quality else False
        )

        # ================================================================
        # Tier and alert calculations
        # ================================================================
        quality_tier = get_feature_quality_tier(quality_score)
        matchup_pct = category_quality.get('matchup', 0.0)

        # Alert level
        # Session 141: Changed default_count threshold from >10 to >0 (zero tolerance)
        # Session 145: Use required_default_count for alert level (vegas-only defaults = green)
        if matchup_pct < 50 or quality_score < 50:
            alert_level = 'red'
        elif required_default_count > 0 or quality_score < 70 or matchup_pct < 70:
            alert_level = 'yellow'
        else:
            alert_level = 'green'

        # Specific alerts
        alerts = []
        matchup_cat_size = len(FEATURE_CATEGORIES['matchup'])
        if category_defaults.get('matchup', 0) == matchup_cat_size:
            alerts.append('all_matchup_features_defaulted')
        if not has_composite:
            alerts.append('composite_factors_missing')
        if not has_opponent_defense:
            alerts.append('opponent_defense_missing')
        if num_features > 0 and default_count / num_features > 0.20:
            alerts.append(
                f'high_default_rate_{round(default_count / num_features * 100)}pct'
            )
        if matchup_pct < 50:
            alerts.append('matchup_quality_critical')
        if category_quality.get('game_context', 100) < 50:
            alerts.append('game_context_quality_critical')

        # ================================================================
        # Training readiness
        # ================================================================
        training_quality_count = sum(
            1 for idx in range(num_features)
            if per_feature_quality.get(idx, 0) >= TRAINING_QUALITY_THRESHOLD
        )

        is_training_ready = (
            quality_tier in ('gold', 'silver')
            and matchup_pct >= 70
            and category_quality.get('player_history', 0) >= 80
        )

        # Quality-based production readiness (NEW field, separate from is_production_ready)
        # Session 141: Zero tolerance for default features
        # Session 145: Use required_default_count (excludes optional vegas features)
        # Vegas lines are unavailable for ~60% of players (bench players) - this is normal.
        # Scraper health monitoring separately detects when star players lack lines.
        is_quality_ready = (
            quality_tier in ('gold', 'silver', 'bronze')
            and quality_score >= 70
            and matchup_pct >= 50
            and required_default_count == 0
        )

        # Optional feature count (non-critical features present)
        optional_indices = set(range(num_features)) - set(CRITICAL_FEATURES)
        optional_count = sum(
            1 for idx in optional_indices if not is_default.get(idx, True)
        )

        # ================================================================
        # JSON detail fields
        # ================================================================
        fallback_reasons = {}
        for idx in range(num_features):
            if is_default.get(idx, False):
                reason = DEFAULT_FALLBACK_REASONS.get(idx, 'data_unavailable')
                fallback_reasons[str(idx)] = reason

        upstream_tables = {
            str(idx): FEATURE_UPSTREAM_TABLES.get(idx, 'unknown')
            for idx in range(num_features)
        }

        # ================================================================
        # Build the complete fields dict
        # ================================================================
        fields = {}

        # --- Session 142: Default feature indices for per-feature audit trail ---
        default_indices = [idx for idx in range(num_features) if is_default.get(idx, False)]
        fields['default_feature_indices'] = default_indices

        # --- Section 1: Aggregate Quality (9 new fields) ---
        fields['quality_tier'] = quality_tier
        fields['quality_alert_level'] = alert_level
        fields['quality_alerts'] = alerts if alerts else []
        fields['default_feature_count'] = default_count
        fields['required_default_count'] = required_default_count  # Session 145: excludes optional (vegas)
        fields['phase4_feature_count'] = canonical_counts['phase4']
        fields['phase3_feature_count'] = canonical_counts['phase3']
        fields['calculated_feature_count'] = canonical_counts['calculated']
        fields['is_training_ready'] = is_training_ready
        fields['training_quality_feature_count'] = training_quality_count

        # --- Section 2: Category Quality (18 fields) ---
        fields['matchup_quality_pct'] = category_quality.get('matchup', 0.0)
        fields['player_history_quality_pct'] = category_quality.get('player_history', 0.0)
        fields['team_context_quality_pct'] = category_quality.get('team_context', 0.0)
        fields['vegas_quality_pct'] = category_quality.get('vegas', 0.0)
        fields['game_context_quality_pct'] = category_quality.get('game_context', 0.0)
        fields['matchup_default_count'] = category_defaults.get('matchup', 0)
        fields['player_history_default_count'] = category_defaults.get('player_history', 0)
        fields['team_context_default_count'] = category_defaults.get('team_context', 0)
        fields['vegas_default_count'] = category_defaults.get('vegas', 0)
        fields['game_context_default_count'] = category_defaults.get('game_context', 0)
        fields['has_composite_factors'] = has_composite
        fields['has_opponent_defense'] = has_opponent_defense
        fields['has_vegas_line'] = has_vegas
        fields['critical_features_training_quality'] = critical_all_training
        fields['critical_feature_count'] = critical_high_quality
        fields['optional_feature_count'] = optional_count
        fields['matchup_quality_tier'] = get_feature_quality_tier(matchup_pct)
        fields['game_context_quality_tier'] = get_feature_quality_tier(
            category_quality.get('game_context', 0.0)
        )

        # --- Section 3: Per-Feature Quality (37 fields) ---
        for idx in range(num_features):
            fields[f'feature_{idx}_quality'] = per_feature_quality.get(idx, 0.0)

        # --- Section 4: Per-Feature Source (37 fields) ---
        for idx in range(num_features):
            fields[f'feature_{idx}_source'] = per_feature_source.get(idx, 'default')

        # --- Section 5: Per-Feature Details JSON (6 fields) ---
        fields['feature_fallback_reasons_json'] = (
            json.dumps(fallback_reasons) if fallback_reasons else '{}'
        )
        fields['feature_sample_sizes_json'] = '{}'
        fields['feature_expected_values_json'] = '{}'
        fields['feature_value_ranges_valid_json'] = '{}'
        fields['feature_upstream_tables_json'] = json.dumps(upstream_tables)
        fields['feature_last_updated_json'] = '{}'

        # --- Section 6: Model Compatibility (4 fields) ---
        fields['feature_schema_version'] = f'v2_{num_features}features'
        fields['available_feature_names'] = list(feature_names[:num_features])
        fields['breakout_model_compatible'] = ['v2_14features']
        fields['breakout_v3_features_available'] = False

        # --- Section 7: Traceability (6 fields) ---
        # upstream_processors_ran and missing_processors set by processor
        fields['upstream_processors_ran'] = None
        fields['missing_processors'] = None
        fields['feature_store_age_hours'] = 0.0
        fields['upstream_data_freshness_hours'] = None
        fields['quality_computed_at'] = datetime.now(timezone.utc).isoformat()
        fields['quality_schema_version'] = QUALITY_SCHEMA_VERSION

        # --- Section 8: Legacy (3 fields) ---
        # feature_sources handled separately by processor (dict -> JSON rename)
        fields['primary_data_source'] = self.determine_primary_source(feature_sources)
        fields['matchup_data_status'] = (
            'MATCHUP_UNAVAILABLE' if matchup_pct < 50 else 'COMPLETE'
        )

        # --- NEW: Quality-based readiness (separate from is_production_ready) ---
        fields['is_quality_ready'] = is_quality_ready

        return fields

    def _summarize_sources(self, feature_sources: Dict[int, str]) -> str:
        """Generate human-readable summary of sources."""
        phase4 = sum(1 for s in feature_sources.values() if s == 'phase4')
        phase3 = sum(1 for s in feature_sources.values() if s == 'phase3')
        calculated = sum(1 for s in feature_sources.values() if s == 'calculated')
        default = sum(1 for s in feature_sources.values() if s == 'default')
        other = len(feature_sources) - phase4 - phase3 - calculated - default
        return (
            f"phase4={phase4}, phase3={phase3}, calc={calculated}, "
            f"default={default}, other={other}"
        )
