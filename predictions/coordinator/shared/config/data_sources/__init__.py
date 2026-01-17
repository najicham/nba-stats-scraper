"""
Data Source Configuration Module

Provides configuration for the data fallback and quality tracking system.

Usage:
    from shared.config.data_sources import DataSourceConfig, get_config

    # Get singleton instance
    config = DataSourceConfig()
    # or
    config = get_config()

    # Get source info
    source = config.get_source('nbac_team_boxscore')
    print(f"Quality: {source.quality_tier} ({source.quality_score})")

    # Get fallback chain
    chain = config.get_fallback_chain('team_boxscores')
    print(f"Sources: {chain.sources}")
    print(f"On fail: {chain.on_all_fail_action}")

    # Convert score to tier
    tier = config.get_tier_from_score(85)  # 'silver'

    # Check prediction eligibility
    eligible = config.is_prediction_eligible('bronze')  # True

Version: 1.0
Created: 2025-11-30
"""

from .loader import (
    DataSourceConfig,
    get_config,
    SourceConfig,
    FallbackChainConfig,
    QualityTierConfig,
    ReconstructionMethod,
    RemediationOption,
)

__all__ = [
    'DataSourceConfig',
    'get_config',
    'SourceConfig',
    'FallbackChainConfig',
    'QualityTierConfig',
    'ReconstructionMethod',
    'RemediationOption',
]
