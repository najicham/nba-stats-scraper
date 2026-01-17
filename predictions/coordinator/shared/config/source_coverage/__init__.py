"""
Source Coverage Constants and Configuration

This module provides constants and enums for the source coverage system.
"""

from enum import Enum
from typing import Dict


class QualityTier(str, Enum):
    """Quality tier levels for data quality assessment."""
    GOLD = 'gold'          # All data from primary sources, complete
    SILVER = 'silver'      # Minor gaps or backup sources used
    BRONZE = 'bronze'      # Significant gaps or thin sample
    POOR = 'poor'          # Major quality issues
    UNUSABLE = 'unusable'  # Cannot generate reliable output


class SourceCoverageEventType(str, Enum):
    """Types of source coverage events."""
    SOURCE_MISSING = 'source_missing'
    FALLBACK_USED = 'fallback_used'
    RECONSTRUCTION_APPLIED = 'reconstruction_applied'
    QUALITY_DEGRADATION = 'quality_degradation'
    PROCESSING_SKIPPED = 'processing_skipped'
    MANUAL_OVERRIDE = 'manual_override'
    INSUFFICIENT_SAMPLE = 'insufficient_sample'
    AUDIT_DETECTED = 'audit_detected'


class SourceCoverageSeverity(str, Enum):
    """Severity levels for source coverage events."""
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'


class SourceStatus(str, Enum):
    """Status of a data source."""
    AVAILABLE = 'available'
    MISSING = 'missing'
    STALE = 'stale'
    ERROR = 'error'


class Resolution(str, Enum):
    """Resolution outcome for source coverage issues."""
    USED_PRIMARY = 'used_primary'
    USED_FALLBACK = 'used_fallback'
    RECONSTRUCTED = 'reconstructed'
    SKIPPED = 'skipped'
    FAILED = 'failed'


# Quality tier ranking for comparison
TIER_RANK: Dict[str, int] = {
    QualityTier.UNUSABLE.value: 0,
    QualityTier.POOR.value: 1,
    QualityTier.BRONZE.value: 2,
    QualityTier.SILVER.value: 3,
    QualityTier.GOLD.value: 4,
}


# Quality score thresholds
QUALITY_THRESHOLDS = {
    'gold_min': 95.0,
    'silver_min': 75.0,
    'bronze_min': 50.0,
    'poor_min': 25.0,
}


# Confidence ceilings by quality tier
QUALITY_CONFIDENCE_CEILING = {
    QualityTier.GOLD.value: 1.00,
    QualityTier.SILVER.value: 0.95,
    QualityTier.BRONZE.value: 0.80,
    QualityTier.POOR.value: 0.60,
    QualityTier.UNUSABLE.value: 0.00,
}


# Season-aware sample thresholds
SAMPLE_THRESHOLDS = {
    'early_season': 3,   # First 10 games of season
    'mid_season': 5,     # Games 11-30
    'full_season': 8,    # After game 30
}


# Standard quality issue prefixes
QUALITY_ISSUE_PREFIXES = {
    'thin_sample',
    'missing_required',
    'missing_optional',
    'high_null_rate',
    'backup_source_used',
    'reconstructed',
    'early_season',
    'stale_data',
    'historical_data',
}


def get_tier_from_score(score: float) -> QualityTier:
    """Convert numeric score to quality tier."""
    if score >= QUALITY_THRESHOLDS['gold_min']:
        return QualityTier.GOLD
    elif score >= QUALITY_THRESHOLDS['silver_min']:
        return QualityTier.SILVER
    elif score >= QUALITY_THRESHOLDS['bronze_min']:
        return QualityTier.BRONZE
    elif score >= QUALITY_THRESHOLDS['poor_min']:
        return QualityTier.POOR
    else:
        return QualityTier.UNUSABLE


def aggregate_quality_tiers(tiers: list) -> str:
    """
    Determine overall quality tier from multiple input tiers.
    Worst quality wins (used for Phase 4 inheritance).
    """
    if not tiers:
        return QualityTier.UNUSABLE.value

    worst_rank = min(TIER_RANK.get(t, 0) for t in tiers)

    for tier, rank in TIER_RANK.items():
        if rank == worst_rank:
            return tier

    return QualityTier.UNUSABLE.value


def format_quality_issue(prefix: str, detail: str = None) -> str:
    """
    Create standardized quality issue string.

    Examples:
        format_quality_issue('thin_sample', '3/10') -> 'thin_sample:3/10'
        format_quality_issue('backup_source_used') -> 'backup_source_used'
    """
    if detail:
        return f"{prefix}:{detail}"
    return prefix


__all__ = [
    'QualityTier',
    'SourceCoverageEventType',
    'SourceCoverageSeverity',
    'SourceStatus',
    'Resolution',
    'TIER_RANK',
    'QUALITY_THRESHOLDS',
    'QUALITY_CONFIDENCE_CEILING',
    'SAMPLE_THRESHOLDS',
    'QUALITY_ISSUE_PREFIXES',
    'get_tier_from_score',
    'aggregate_quality_tiers',
    'format_quality_issue',
]
