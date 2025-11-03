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


def test_validate_detects_unrealistic_points_low(mock_processor):
    """Test validation detects unrealistically low points."""
    data = pd.DataFrame([{
        'game_id': '20241021LAL_GSW',
        'game_date': date(2024, 10, 21),
        'defending_team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'points_allowed': 30,  # Too low
        'steals': 8,
        'blocks_total': 5
    }])
    mock_processor.raw_data = data
    mock_processor.log_quality_issue = Mock()
    
    mock_processor.validate_extracted_data()
    
    assert mock_processor.log_quality_issue.called
    call_args = mock_processor.log_quality_issue.call_args[1]
    assert call_args['issue_type'] == 'unrealistic_points_allowed'


def test_validate_detects_unrealistic_points_high(mock_processor):
    """Test validation detects unrealistically high points."""
    data = pd.DataFrame([{
        'game_id': '20241021LAL_GSW',
        'game_date': date(2024, 10, 21),
        'defending_team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'points_allowed': 210,  # Too high
        'steals': 8,
        'blocks_total': 5
    }])
    mock_processor.raw_data = data
    mock_processor.log_quality_issue = Mock()
    
    mock_processor.validate_extracted_data()
    
    assert mock_processor.log_quality_issue.called


def test_validate_normal_points_pass(mock_processor, sample_raw_extracted_data):
    """Test validation passes for normal point totals."""
    mock_processor.raw_data = sample_raw_extracted_data
    
    # Should not raise
    mock_processor.validate_extracted_data()