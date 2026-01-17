"""
Feature Coverage Thresholds for Validation

Defines minimum coverage percentages for key features in player_game_summary.
These thresholds are used for backfill validation and data quality checks.
"""

# Feature coverage thresholds (minimum % of non-NULL values required)
FEATURE_THRESHOLDS = {
    # CRITICAL features (block if below threshold)
    'minutes_played': {
        'threshold': 99.0,
        'critical': True,
        'description': 'Player minutes played (critical for all analysis)',
    },
    'usage_rate': {
        'threshold': 95.0,
        'critical': True,
        'description': 'Player usage rate (critical for ML features)',
    },

    # Shot distribution features (lower for 2024-25 season due to BDL format change)
    'paint_attempts': {
        'threshold': 40.0,
        'critical': False,
        'description': 'Paint shot attempts (BigDataBall PBP)',
    },
    'mid_range_attempts': {
        'threshold': 40.0,
        'critical': False,
        'description': 'Mid-range shot attempts (BigDataBall PBP)',
    },
    'three_pt_attempts': {
        'threshold': 99.0,
        'critical': True,
        'description': '3-point attempts (core stat)',
    },
    'assisted_fg_makes': {
        'threshold': 40.0,
        'critical': False,
        'description': 'Assisted field goals (BigDataBall PBP)',
    },

    # Core stats (should always be present)
    'points': {
        'threshold': 99.5,
        'critical': True,
        'description': 'Points scored (core stat)',
    },
    'fg_attempts': {
        'threshold': 99.0,
        'critical': True,
        'description': 'Field goal attempts (core stat)',
    },
    'rebounds': {
        'threshold': 99.0,
        'critical': True,
        'description': 'Total rebounds (core stat)',
    },
    'assists': {
        'threshold': 99.0,
        'critical': True,
        'description': 'Assists (core stat)',
    },
}


def get_feature_threshold(feature: str) -> float:
    """Get threshold for a feature, default to 95% if not specified."""
    return FEATURE_THRESHOLDS.get(feature, {}).get('threshold', 95.0)


def is_critical_feature(feature: str) -> bool:
    """Check if a feature is critical (blocks validation if below threshold)."""
    return FEATURE_THRESHOLDS.get(feature, {}).get('critical', False)


def get_feature_description(feature: str) -> str:
    """Get description for a feature."""
    return FEATURE_THRESHOLDS.get(feature, {}).get('description', 'No description')


def get_default_validation_features() -> list:
    """Get list of default features to validate for backfills."""
    return ['minutes_played', 'usage_rate', 'paint_attempts']
