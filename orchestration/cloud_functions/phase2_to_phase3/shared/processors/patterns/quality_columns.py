"""
Standard Quality Column Builder

Single source of truth for building quality columns across all processors.
Both QualityMixin and FallbackSourceMixin delegate to these helpers.

This module provides:
- build_standard_quality_columns(): The authoritative function for quality column output
- determine_production_ready(): Centralized logic for production readiness
- build_completeness_columns(): For Phase 4 precompute tables only
- build_quality_columns_with_legacy(): Backward-compatible output during migration

Usage:
    from shared.processors.patterns.quality_columns import (
        build_standard_quality_columns,
        build_completeness_columns,
    )

    # In your processor's calculate_analytics():
    quality_cols = build_standard_quality_columns(
        tier='silver',
        score=85.0,
        issues=['backup_source_used'],
        sources=['bdl_player_boxscores'],
    )
    record.update(quality_cols)

Version: 1.0
Created: 2025-11-30
"""

from typing import Dict, List, Any, Optional

# Import from source_coverage - the canonical source for tier definitions
from shared.config.source_coverage import QualityTier


# =============================================================================
# STANDARD QUALITY COLUMNS
# =============================================================================

def build_standard_quality_columns(
    tier: str,
    score: float,
    issues: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    is_production_ready: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Build the standard quality columns for BigQuery output.

    This is THE authoritative function for quality column output.
    All processors should use this to ensure consistency across tables.

    Standard columns produced:
    - quality_tier: STRING ('gold', 'silver', 'bronze', 'poor', 'unusable')
    - quality_score: FLOAT64 (0-100)
    - quality_issues: ARRAY<STRING> (list of detected issues)
    - is_production_ready: BOOL (safe for predictions?)
    - data_sources: ARRAY<STRING> (which sources contributed)

    Args:
        tier: Quality tier name ('gold', 'silver', 'bronze', 'poor', 'unusable')
        score: Quality score 0-100
        issues: List of quality issues (e.g., ['backup_source_used', 'reconstructed'])
        sources: List of data sources used (e.g., ['nbac_team_boxscore'])
        is_production_ready: Override for production ready flag. If None, auto-calculated.

    Returns:
        Dict with standard quality columns ready for BigQuery insertion.

    Example:
        >>> cols = build_standard_quality_columns('silver', 85.0, ['backup_source_used'])
        >>> cols
        {
            'quality_tier': 'silver',
            'quality_score': 85.0,
            'quality_issues': ['backup_source_used'],
            'data_sources': [],
            'is_production_ready': True
        }
    """
    issues = issues or []
    sources = sources or []

    # Ensure score is float
    score = float(score) if score is not None else 0.0

    # Determine production readiness if not explicitly set
    if is_production_ready is None:
        is_production_ready = determine_production_ready(tier, score, issues)

    return {
        'quality_tier': tier,
        'quality_score': score,
        'quality_issues': issues,
        'data_sources': sources,
        'is_production_ready': is_production_ready,
    }


def determine_production_ready(
    tier: str,
    score: float,
    issues: List[str],
) -> bool:
    """
    Determine if data is production ready (safe for predictions).

    This is the SINGLE source of truth for production readiness logic.
    All processors should use this function rather than implementing their own.

    Criteria:
    1. Tier must be gold, silver, or bronze (not poor/unusable)
    2. Score must be >= 50.0
    3. No critical blocking issues present

    Blocking issues that make data NOT production ready:
    - 'all_sources_failed': No data sources returned data
    - 'missing_required': Required fields are missing
    - 'placeholder_created': Record is a placeholder, not real data

    Args:
        tier: Quality tier name
        score: Quality score 0-100
        issues: List of quality issues

    Returns:
        True if data can be safely used for predictions, False otherwise.

    Example:
        >>> determine_production_ready('silver', 85.0, ['backup_source_used'])
        True
        >>> determine_production_ready('unusable', 0.0, ['all_sources_failed'])
        False
    """
    # Tiers eligible for production
    eligible_tiers = {
        QualityTier.GOLD.value,
        QualityTier.SILVER.value,
        QualityTier.BRONZE.value,
    }

    # Issues that block production readiness
    blocking_issues = {
        'all_sources_failed',
        'missing_required',
        'placeholder_created',
    }

    # Check all criteria
    tier_ok = tier in eligible_tiers
    score_ok = score >= 50.0
    no_blockers = not any(issue in blocking_issues for issue in issues)

    return tier_ok and score_ok and no_blockers


# =============================================================================
# COMPLETENESS COLUMNS (Phase 4 Precompute Only)
# =============================================================================

def build_completeness_columns(
    expected: int,
    actual: int,
) -> Dict[str, Any]:
    """
    Build completeness tracking columns for Phase 4 precompute tables.

    These columns track how complete a lookback/aggregation window is.
    For example, a "10-game rolling average" might only have 7 games available.

    Note: These columns are ONLY for Phase 4 precompute tables that aggregate
    multiple games. Phase 3 analytics tables (one record per game) should NOT
    use these columns - they use quality_issues to track data gaps instead.

    Args:
        expected: Expected number of games/records in the lookback window
        actual: Actual number of games/records found

    Returns:
        Dict with completeness columns:
        - expected_games_count: INT64
        - actual_games_count: INT64
        - completeness_percentage: FLOAT64 (0-100)
        - missing_games_count: INT64

    Example:
        >>> cols = build_completeness_columns(expected=10, actual=7)
        >>> cols
        {
            'expected_games_count': 10,
            'actual_games_count': 7,
            'completeness_percentage': 70.0,
            'missing_games_count': 3
        }
    """
    percentage = (actual / expected * 100) if expected > 0 else 0.0

    return {
        'expected_games_count': expected,
        'actual_games_count': actual,
        'completeness_percentage': round(percentage, 2),
        'missing_games_count': max(0, expected - actual),
    }


# =============================================================================
# LEGACY COMPATIBILITY (Deprecated - use during migration only)
# =============================================================================

def build_quality_columns_with_legacy(
    tier: str,
    score: float,
    issues: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    is_production_ready: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Build quality columns with legacy backward compatibility columns.

    DEPRECATED: Use this only during the migration period while downstream
    consumers are being updated to use the new column names.

    This function outputs BOTH new and legacy columns:
    - New: quality_tier, quality_score, quality_issues, is_production_ready, data_sources
    - Legacy: data_quality_tier, data_quality_issues

    Migration timeline:
    - Phase 1 (now): Use this function, populate both old and new
    - Phase 2 (2 weeks): Update downstream consumers to use new columns
    - Phase 3 (1 month): Switch to build_standard_quality_columns()
    - Phase 4 (3 months): Drop legacy columns from BigQuery

    Args:
        tier: Quality tier name
        score: Quality score 0-100
        issues: List of quality issues
        sources: List of data sources used
        is_production_ready: Override for production ready flag

    Returns:
        Dict with both new standard columns AND legacy columns.
    """
    # Get standard columns
    standard = build_standard_quality_columns(
        tier=tier,
        score=score,
        issues=issues,
        sources=sources,
        is_production_ready=is_production_ready,
    )

    # Add legacy columns (deprecated)
    standard['data_quality_tier'] = tier
    standard['data_quality_issues'] = issues or []

    return standard


# =============================================================================
# QUALITY ISSUE HELPERS
# =============================================================================

# Standard quality issue strings for consistency
ISSUE_BACKUP_SOURCE_USED = 'backup_source_used'
ISSUE_RECONSTRUCTED = 'reconstructed'
ISSUE_ALL_SOURCES_FAILED = 'all_sources_failed'
ISSUE_PLACEHOLDER_CREATED = 'placeholder_created'
ISSUE_MISSING_REQUIRED = 'missing_required'
ISSUE_THIN_SAMPLE = 'thin_sample'
ISSUE_HIGH_NULL_RATE = 'high_null_rate'
ISSUE_STALE_DATA = 'stale_data'
ISSUE_EARLY_SEASON = 'early_season'


def format_issue_with_detail(issue: str, detail: str) -> str:
    """
    Format a quality issue with additional detail.

    Args:
        issue: Base issue name (e.g., 'thin_sample')
        detail: Additional detail (e.g., '3/10')

    Returns:
        Formatted issue string (e.g., 'thin_sample:3/10')

    Example:
        >>> format_issue_with_detail('thin_sample', '3/10')
        'thin_sample:3/10'
    """
    return f"{issue}:{detail}" if detail else issue


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Main functions
    'build_standard_quality_columns',
    'determine_production_ready',
    'build_completeness_columns',
    'build_quality_columns_with_legacy',

    # Issue constants
    'ISSUE_BACKUP_SOURCE_USED',
    'ISSUE_RECONSTRUCTED',
    'ISSUE_ALL_SOURCES_FAILED',
    'ISSUE_PLACEHOLDER_CREATED',
    'ISSUE_MISSING_REQUIRED',
    'ISSUE_THIN_SAMPLE',
    'ISSUE_HIGH_NULL_RATE',
    'ISSUE_STALE_DATA',
    'ISSUE_EARLY_SEASON',

    # Helpers
    'format_issue_with_detail',
]
