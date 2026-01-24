"""
Sport Configuration - Central abstraction layer for multi-sport support.

This module provides sport-agnostic access to:
- Dataset names (nba_raw, mlb_raw, etc.)
- GCS bucket names
- Pub/Sub topic prefixes
- Project configuration

Usage:
    from shared.config.sport_config import SportConfig

    config = SportConfig.get_current()
    dataset = config.raw_dataset  # Returns 'nba_raw' or 'mlb_raw'

Or use the convenience functions:
    from shared.config.sport_config import get_raw_dataset, get_bucket

    dataset = get_raw_dataset()  # Returns current sport's raw dataset

Environment Variable:
    SPORT: Set to 'nba' or 'mlb' (defaults to 'nba')

Created: 2026-01-06
Version: 1.0
"""

import os
from dataclasses import dataclass, field
from typing import Optional
import importlib


# Get current sport from environment (default to NBA for backward compatibility)
CURRENT_SPORT = os.environ.get('SPORT', 'nba').lower()

# Default project ID from environment
DEFAULT_PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')


def _get_default_project() -> str:
    """Get default project ID from environment."""
    return DEFAULT_PROJECT_ID


@dataclass
class SportConfig:
    """Configuration for a specific sport."""

    # Sport identifier
    sport: str

    # GCP Project (reads from environment with fallback)
    project_id: str = field(default_factory=_get_default_project)

    # GCS Bucket
    bucket: str = ''

    # BigQuery Datasets
    raw_dataset: str = ''
    analytics_dataset: str = ''
    precompute_dataset: str = ''
    predictions_dataset: str = ''
    reference_dataset: str = ''
    orchestration_dataset: str = ''

    # Pub/Sub topic prefix
    topic_prefix: str = ''

    def __post_init__(self):
        """Set derived values based on sport."""
        if not self.bucket:
            self.bucket = f'{self.sport}-scraped-data'
        if not self.raw_dataset:
            self.raw_dataset = f'{self.sport}_raw'
        if not self.analytics_dataset:
            self.analytics_dataset = f'{self.sport}_analytics'
        if not self.precompute_dataset:
            self.precompute_dataset = f'{self.sport}_precompute'
        if not self.predictions_dataset:
            self.predictions_dataset = f'{self.sport}_predictions'
        if not self.reference_dataset:
            self.reference_dataset = f'{self.sport}_reference'
        if not self.orchestration_dataset:
            self.orchestration_dataset = f'{self.sport}_orchestration'
        if not self.topic_prefix:
            self.topic_prefix = self.sport

    def topic(self, phase: str) -> str:
        """
        Get full topic name for a phase.

        Args:
            phase: Phase identifier (e.g., 'phase1-scrapers-complete')

        Returns:
            Full topic name (e.g., 'nba-phase1-scrapers-complete')
        """
        return f'{self.topic_prefix}-{phase}'

    def get_teams_module(self):
        """
        Dynamically load the teams module for this sport.

        Returns:
            Module containing team data (e.g., shared.config.sports.nba.teams)
        """
        return importlib.import_module(f'shared.config.sports.{self.sport}.teams')

    def get_teams(self) -> list:
        """
        Get list of teams for this sport.

        Returns:
            List of team dictionaries
        """
        module = self.get_teams_module()
        # Look for TEAMS, {SPORT}_TEAMS, or teams variable
        for attr_name in ['TEAMS', f'{self.sport.upper()}_TEAMS', 'teams']:
            if hasattr(module, attr_name):
                return getattr(module, attr_name)
        return []

    @classmethod
    def get_current(cls) -> 'SportConfig':
        """
        Get configuration for the current sport (from SPORT env var).

        Returns:
            SportConfig instance for current sport
        """
        return cls(sport=CURRENT_SPORT)

    @classmethod
    def for_sport(cls, sport: str) -> 'SportConfig':
        """
        Get configuration for a specific sport.

        Args:
            sport: Sport identifier ('nba', 'mlb', etc.)

        Returns:
            SportConfig instance for specified sport
        """
        return cls(sport=sport.lower())


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_current_sport() -> str:
    """Get the current sport identifier."""
    return CURRENT_SPORT


def get_config() -> SportConfig:
    """Get SportConfig for current sport."""
    return SportConfig.get_current()


def get_project_id() -> str:
    """Get the GCP project ID."""
    return SportConfig.get_current().project_id


def get_bucket() -> str:
    """Get the GCS bucket name for current sport."""
    return SportConfig.get_current().bucket


def get_raw_dataset() -> str:
    """Get the raw BigQuery dataset name for current sport."""
    return SportConfig.get_current().raw_dataset


def get_analytics_dataset() -> str:
    """Get the analytics BigQuery dataset name for current sport."""
    return SportConfig.get_current().analytics_dataset


def get_precompute_dataset() -> str:
    """Get the precompute BigQuery dataset name for current sport."""
    return SportConfig.get_current().precompute_dataset


def get_predictions_dataset() -> str:
    """Get the predictions BigQuery dataset name for current sport."""
    return SportConfig.get_current().predictions_dataset


def get_reference_dataset() -> str:
    """Get the reference BigQuery dataset name for current sport."""
    return SportConfig.get_current().reference_dataset


def get_orchestration_dataset() -> str:
    """Get the orchestration BigQuery dataset name for current sport."""
    return SportConfig.get_current().orchestration_dataset


def get_topic(phase: str) -> str:
    """
    Get full Pub/Sub topic name for a phase.

    Args:
        phase: Phase identifier (e.g., 'phase1-scrapers-complete')

    Returns:
        Full topic name (e.g., 'nba-phase1-scrapers-complete')
    """
    return SportConfig.get_current().topic(phase)


# ============================================================================
# BACKWARD COMPATIBILITY
# ============================================================================

# These constants provide backward compatibility with existing code
# that uses hardcoded dataset names. They resolve to the current sport's
# datasets at import time.

# WARNING: These are evaluated at import time. If you change SPORT env var
# after import, these won't update. Use the functions above for dynamic access.

PROJECT_ID = get_project_id()
GCS_BUCKET = get_bucket()
RAW_DATASET = get_raw_dataset()
ANALYTICS_DATASET = get_analytics_dataset()
PRECOMPUTE_DATASET = get_precompute_dataset()
PREDICTIONS_DATASET = get_predictions_dataset()
REFERENCE_DATASET = get_reference_dataset()
ORCHESTRATION_DATASET = get_orchestration_dataset()
