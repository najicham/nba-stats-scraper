"""
Validation Configuration

Central configuration for pipeline validation.
Update this file when prediction systems, tables, or thresholds change.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

# =============================================================================
# PROJECT CONFIGURATION
# =============================================================================

PROJECT_ID = 'nba-props-platform'

# =============================================================================
# PREDICTION SYSTEMS
# =============================================================================

# If prediction systems are added/removed, update this list
# Validation will alert if actual systems differ from expected
EXPECTED_PREDICTION_SYSTEMS = [
    'moving_average',
    'zone_matchup_v1',
    'similarity_balanced_v1',
    'xgboost_v1',
    'ensemble_v1',
]

PREDICTIONS_PER_PLAYER = len(EXPECTED_PREDICTION_SYSTEMS)  # 5

# =============================================================================
# QUALITY TIERS
# =============================================================================

class QualityTier(Enum):
    GOLD = 'gold'
    SILVER = 'silver'
    BRONZE = 'bronze'
    POOR = 'poor'
    UNUSABLE = 'unusable'

QUALITY_TIERS = {
    'gold': {'min_score': 95, 'max_score': 100, 'production_ready': True, 'symbol': 'G'},
    'silver': {'min_score': 75, 'max_score': 94, 'production_ready': True, 'symbol': 'S'},
    'bronze': {'min_score': 50, 'max_score': 74, 'production_ready': True, 'symbol': 'B'},
    'poor': {'min_score': 25, 'max_score': 49, 'production_ready': False, 'symbol': 'P'},
    'unusable': {'min_score': 0, 'max_score': 24, 'production_ready': False, 'symbol': 'U'},
}

# Tiers that should trigger a warning in validation output
WARN_QUALITY_TIERS = ['bronze']
ERROR_QUALITY_TIERS = ['poor', 'unusable']

# =============================================================================
# PHASE 2: RAW DATA SOURCES
# =============================================================================

@dataclass
class Phase2Source:
    """Configuration for a Phase 2 raw data source."""
    table_name: str
    priority: str  # 'critical', 'important', 'fallback', 'optional'
    description: str
    date_column: str
    fallback_for: Optional[str] = None  # Table this is a fallback for
    has_game_id: bool = True

PHASE2_SOURCES = {
    'nbac_gamebook_player_stats': Phase2Source(
        table_name='nbac_gamebook_player_stats',
        priority='critical',
        description='Player boxscores (primary)',
        date_column='game_date',
    ),
    'nbac_team_boxscore': Phase2Source(
        table_name='nbac_team_boxscore',
        priority='critical',
        description='Team boxscores',
        date_column='game_date',
    ),
    'bdl_player_boxscores': Phase2Source(
        table_name='bdl_player_boxscores',
        priority='fallback',
        description='Player stats fallback',
        date_column='game_date',
        fallback_for='nbac_gamebook_player_stats',
    ),
    'bettingpros_player_points_props': Phase2Source(
        table_name='bettingpros_player_points_props',
        priority='important',
        description='Player prop lines (primary)',
        date_column='game_date',
        has_game_id=False,
    ),
    'odds_api_player_points_props': Phase2Source(
        table_name='odds_api_player_points_props',
        priority='fallback',
        description='Player prop lines (fallback)',
        date_column='game_date',
        fallback_for='bettingpros_player_points_props',
        has_game_id=False,
    ),
    'nbac_schedule': Phase2Source(
        table_name='nbac_schedule',
        priority='important',
        description='Game schedule',
        date_column='game_date',
    ),
    'odds_api_game_lines': Phase2Source(
        table_name='odds_api_game_lines',
        priority='optional',
        description='Team spreads/totals',
        date_column='game_date',
    ),
}

# =============================================================================
# PHASE 3: ANALYTICS TABLES
# =============================================================================

@dataclass
class Phase3Table:
    """Configuration for a Phase 3 analytics table."""
    table_name: str
    dataset: str
    date_column: str
    processor_name: str
    expected_scope: str  # 'all_rostered' (active+DNP+inactive), 'active_only', 'teams'
    has_quality_columns: bool = True

PHASE3_TABLES = {
    'player_game_summary': Phase3Table(
        table_name='player_game_summary',
        dataset='nba_analytics',
        date_column='game_date',
        processor_name='PlayerGameSummaryProcessor',
        expected_scope='active_only',  # Only players who actually played (have game stats)
    ),
    'team_defense_game_summary': Phase3Table(
        table_name='team_defense_game_summary',
        dataset='nba_analytics',
        date_column='game_date',
        processor_name='TeamDefenseGameSummaryProcessor',
        expected_scope='teams',
    ),
    'team_offense_game_summary': Phase3Table(
        table_name='team_offense_game_summary',
        dataset='nba_analytics',
        date_column='game_date',
        processor_name='TeamOffenseGameSummaryProcessor',
        expected_scope='teams',
    ),
    'upcoming_player_game_context': Phase3Table(
        table_name='upcoming_player_game_context',
        dataset='nba_analytics',
        date_column='game_date',
        processor_name='UpcomingPlayerGameContextProcessor',
        expected_scope='all_rostered',  # All players on game-day rosters (active+DNP+inactive)
    ),
    'upcoming_team_game_context': Phase3Table(
        table_name='upcoming_team_game_context',
        dataset='nba_analytics',
        date_column='game_date',
        processor_name='UpcomingTeamGameContextProcessor',
        expected_scope='teams',
    ),
}

# =============================================================================
# PHASE 4: PRECOMPUTE TABLES
# =============================================================================

@dataclass
class Phase4Table:
    """Configuration for a Phase 4 precompute table."""
    table_name: str
    dataset: str
    date_column: str
    processor_name: str
    expected_scope: str  # 'all_rostered' (active+DNP+inactive), 'teams'
    skips_bootstrap: bool = True

PHASE4_TABLES = {
    'team_defense_zone_analysis': Phase4Table(
        table_name='team_defense_zone_analysis',
        dataset='nba_precompute',
        date_column='analysis_date',
        processor_name='TeamDefenseZoneAnalysisProcessor',
        expected_scope='teams',
    ),
    'player_shot_zone_analysis': Phase4Table(
        table_name='player_shot_zone_analysis',
        dataset='nba_precompute',
        date_column='analysis_date',
        processor_name='PlayerShotZoneAnalysisProcessor',
        expected_scope='active_only',  # Only players with shot data
    ),
    'player_composite_factors': Phase4Table(
        table_name='player_composite_factors',
        dataset='nba_precompute',
        date_column='game_date',
        processor_name='PlayerCompositeFactorsProcessor',
        expected_scope='all_rostered',
    ),
    'player_daily_cache': Phase4Table(
        table_name='player_daily_cache',
        dataset='nba_precompute',
        date_column='cache_date',
        processor_name='PlayerDailyCacheProcessor',
        expected_scope='all_rostered',
    ),
    'ml_feature_store_v2': Phase4Table(
        table_name='ml_feature_store_v2',
        dataset='nba_predictions',
        date_column='game_date',
        processor_name='MLFeatureStoreProcessor',
        expected_scope='all_rostered',
    ),
}

# =============================================================================
# PHASE 5: PREDICTIONS
# =============================================================================

PREDICTIONS_TABLE = 'player_prop_predictions'
PREDICTIONS_DATASET = 'nba_predictions'
PREDICTIONS_DATE_COLUMN = 'game_date'

# =============================================================================
# ORCHESTRATION (Firestore)
# =============================================================================

FIRESTORE_COLLECTIONS = {
    'phase2_completion': {
        'expected_count': 21,
        'description': 'Phase 2 raw processor completions',
    },
    'phase3_completion': {
        'expected_count': 5,
        'description': 'Phase 3 analytics processor completions',
    },
}

# =============================================================================
# BOOTSTRAP PERIOD
# =============================================================================

BOOTSTRAP_DAYS = 7  # Days 0-6 of each season are bootstrap period

# =============================================================================
# TIME-AWARE MONITORING (All times in ET)
# =============================================================================

ORCHESTRATION_TIMELINE = {
    'phase1_start': 6,      # 6:00 AM ET - scrapers begin
    'phase2_expected': 1,   # 1:00 AM ET (next day) - should be complete
    'phase3_expected': 2,   # 2:00 AM ET (next day) - should be complete
    'phase4_cascade': 2,    # 2:00 AM ET (= 11 PM PT) - CASCADE runs
    'phase4_expected': 4,   # 4:00 AM ET - should be complete
    'phase5_scheduled': 6,  # 6:15 AM ET - predictions run
    'phase5_expected': 7,   # 7:00 AM ET - should be complete
}

# =============================================================================
# VALIDATION THRESHOLDS
# =============================================================================

# Minimum percentage for a table to be considered "complete"
COMPLETENESS_THRESHOLD = 95.0

# Minimum quality score to be production ready
MIN_PRODUCTION_QUALITY_SCORE = 50.0

# Maximum allowed stale hours for live monitoring
MAX_STALE_HOURS = 24
