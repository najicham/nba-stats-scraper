# Path: tests/processors/analytics/team_defense_game_summary/test_mocking_verification.py

"""
Minimal test to verify Google Cloud mocking is working.
This test should pass if conftest.py is configured correctly.

Run with: pytest test_mocking_verification.py -v
"""

import pytest
import sys


def test_google_modules_are_mocked():
    """Verify that Google Cloud modules are mocked in sys.modules."""
    google_modules = [
        'google',
        'google.auth',
        'google.cloud',
        'google.cloud.bigquery',
        'google.cloud.exceptions',
    ]
    
    for module_name in google_modules:
        assert module_name in sys.modules, f"{module_name} should be mocked but is not in sys.modules"


def test_can_import_google_cloud():
    """Verify we can import Google Cloud modules without errors."""
    from google.cloud import bigquery
    from google.auth import default
    from google.cloud.exceptions import NotFound
    
    # Should not raise - all modules are mocked
    assert bigquery is not None
    assert default is not None
    assert NotFound is not None


def test_can_import_processor():
    """Verify we can import the processor without Google Cloud SDK."""
    from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
        TeamDefenseGameSummaryProcessor
    )
    
    assert TeamDefenseGameSummaryProcessor is not None


def test_can_instantiate_processor():
    """Verify we can instantiate the processor."""
    from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
        TeamDefenseGameSummaryProcessor
    )
    
    processor = TeamDefenseGameSummaryProcessor()
    assert processor is not None
    assert hasattr(processor, 'table_name')
    assert processor.table_name == 'team_defense_game_summary'


def test_processor_has_required_methods():
    """Verify processor has all required methods."""
    from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
        TeamDefenseGameSummaryProcessor
    )
    
    processor = TeamDefenseGameSummaryProcessor()
    
    required_methods = [
        'get_dependencies',
        'extract_raw_data',
        'calculate_analytics',
        '_extract_opponent_offense',
        '_extract_defensive_actions',
        '_merge_defense_data',
    ]
    
    for method_name in required_methods:
        assert hasattr(processor, method_name), f"Processor missing method: {method_name}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])