# Path: tests/processors/analytics/team_defense_game_summary/test_validation.py

"""
Minimal validation tests for team_defense_game_summary processor.
Tests basic validation rules in actual processor.

Total: ~3 focused tests
"""

import pytest
import pandas as pd
from datetime import datetime, date, timezone
from unittest.mock import Mock, patch
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
    TeamDefenseGameSummaryProcessor
)


def test_validate_with_low_points_passes(mock_processor):
    """Test validation passes (base class doesn't check point ranges)."""
    # Note: The base class validate_extracted_data only checks for empty data,
    # not point value ranges. This test verifies it doesn't raise errors.
    data = pd.DataFrame([{
        'game_id': '20241021LAL_GSW',
        'game_date': date(2024, 10, 21),
        'defending_team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'points_allowed': 30,
        'steals': 8,
        'blocks_total': 5
    }])
    mock_processor.raw_data = data

    # Should not raise - validation only checks for empty data
    mock_processor.validate_extracted_data()


def test_validate_with_high_points_passes(mock_processor):
    """Test validation passes (base class doesn't check point ranges)."""
    # Note: The base class validate_extracted_data only checks for empty data,
    # not point value ranges. This test verifies it doesn't raise errors.
    data = pd.DataFrame([{
        'game_id': '20241021LAL_GSW',
        'game_date': date(2024, 10, 21),
        'defending_team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'points_allowed': 210,
        'steals': 8,
        'blocks_total': 5
    }])
    mock_processor.raw_data = data

    # Should not raise - validation only checks for empty data
    mock_processor.validate_extracted_data()


def test_validate_normal_points_pass(mock_processor, sample_raw_extracted_data):
    """Test validation passes for normal point totals."""
    mock_processor.raw_data = sample_raw_extracted_data
    
    # Should not raise
    mock_processor.validate_extracted_data()