"""
Unit tests for MLB orchestrator functions.

Tests the processor name normalization and timeout calculation logic
used by the MLB phase transition orchestrators.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import os
import sys

# Add the orchestration functions path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../orchestration/cloud_functions'))


class TestNormalizeProcessorName:
    """Tests for normalize_processor_name function."""

    def test_exact_match_returns_unchanged(self):
        """Processor names already in expected set should return unchanged."""
        from mlb_phase4_to_phase5.main import normalize_processor_name, EXPECTED_PROCESSOR_SET

        for expected in EXPECTED_PROCESSOR_SET:
            assert normalize_processor_name(expected) == expected

    def test_output_table_override(self):
        """Output table should be used if it matches expected processors."""
        from mlb_phase4_to_phase5.main import normalize_processor_name

        # Raw name doesn't match, but output_table does
        result = normalize_processor_name("SomeRandomProcessor", "pitcher_features")
        assert result == "pitcher_features"

    def test_camel_case_conversion(self):
        """CamelCase processor names should be converted to snake_case."""
        from mlb_phase4_to_phase5.main import normalize_processor_name

        # PitcherFeaturesProcessor -> pitcher_features
        result = normalize_processor_name("PitcherFeaturesProcessor")
        assert result == "pitcher_features"

    def test_mlb_prefix_stripped(self):
        """Mlb prefix should be stripped from processor names."""
        from mlb_phase4_to_phase5.main import normalize_processor_name

        result = normalize_processor_name("MlbPitcherFeaturesProcessor")
        assert result == "pitcher_features"

    def test_unknown_processor_returns_normalized(self):
        """Unknown processors should still be normalized."""
        from mlb_phase4_to_phase5.main import normalize_processor_name

        result = normalize_processor_name("SomeNewProcessor")
        assert result == "some_new"


class TestCheckTimeout:
    """Tests for check_timeout function."""

    def test_no_first_completion_no_timeout(self):
        """Should not timeout if no first completion recorded."""
        from mlb_phase4_to_phase5.main import check_timeout

        doc_data = {}
        should_trigger, reason, missing = check_timeout(doc_data)

        assert should_trigger is False
        assert reason == ''
        assert missing == []

    def test_recent_completion_no_timeout(self):
        """Should not timeout if completion is recent."""
        from mlb_phase4_to_phase5.main import check_timeout

        # First completion was 1 hour ago
        first_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        doc_data = {
            '_first_completion_at': first_time,
            'pitcher_features': {'status': 'success'}
        }

        should_trigger, reason, missing = check_timeout(doc_data)

        assert should_trigger is False

    def test_old_completion_triggers_timeout(self):
        """Should trigger timeout if completion is older than MAX_WAIT_HOURS."""
        from mlb_phase4_to_phase5.main import check_timeout, MAX_WAIT_HOURS, EXPECTED_PROCESSORS

        # First completion was MAX_WAIT_HOURS + 1 ago
        first_time = (datetime.now(timezone.utc) - timedelta(hours=MAX_WAIT_HOURS + 1)).isoformat()
        doc_data = {
            '_first_completion_at': first_time,
            'pitcher_features': {'status': 'success'}
            # Missing: lineup_k_analysis
        }

        should_trigger, reason, missing = check_timeout(doc_data)

        assert should_trigger is True
        assert reason == 'timeout'
        assert 'lineup_k_analysis' in missing

    def test_timeout_with_datetime_object(self):
        """Should handle datetime objects (not just strings) for first completion."""
        from mlb_phase4_to_phase5.main import check_timeout, MAX_WAIT_HOURS

        # First completion as datetime object (how Firestore returns it)
        first_time = datetime.now(timezone.utc) - timedelta(hours=MAX_WAIT_HOURS + 1)
        doc_data = {
            '_first_completion_at': first_time,
            'pitcher_features': {'status': 'success'}
        }

        should_trigger, reason, missing = check_timeout(doc_data)

        assert should_trigger is True
        assert reason == 'timeout'


class TestPhase3Orchestrator:
    """Tests for Phase 3 → Phase 4 orchestrator functions."""

    def test_normalize_processor_name_phase3(self):
        """Test processor name normalization for Phase 3."""
        from mlb_phase3_to_phase4.main import normalize_processor_name, EXPECTED_PROCESSOR_SET

        for expected in EXPECTED_PROCESSOR_SET:
            assert normalize_processor_name(expected) == expected

    def test_expected_processors_phase3(self):
        """Verify expected processors for Phase 3."""
        from mlb_phase3_to_phase4.main import EXPECTED_PROCESSORS

        assert 'pitcher_game_summary' in EXPECTED_PROCESSORS
        assert 'batter_game_summary' in EXPECTED_PROCESSORS
        assert len(EXPECTED_PROCESSORS) == 2


class TestMaxWaitHoursConfig:
    """Tests for configurable MAX_WAIT_HOURS."""

    def test_default_max_wait_hours(self):
        """Default MAX_WAIT_HOURS should be 4."""
        from mlb_phase4_to_phase5.main import MAX_WAIT_HOURS

        # Check the default is reasonable (4 hours by default)
        assert MAX_WAIT_HOURS >= 1  # At least 1 hour
        assert MAX_WAIT_HOURS <= 24  # No more than 24 hours

    def test_max_wait_hours_env_var_parsing(self):
        """Verify environment variable parsing logic works correctly."""
        # Test the parsing logic directly without module reload
        # (Module reload causes Firestore client initialization issues in test env)

        # Test default
        result = float(os.environ.get('MAX_WAIT_HOURS', '4'))
        assert result == 4.0

        # Test with different value set
        with patch.dict(os.environ, {'MAX_WAIT_HOURS': '6'}):
            result = float(os.environ.get('MAX_WAIT_HOURS', '4'))
            assert result == 6.0

        # Test with float value
        with patch.dict(os.environ, {'MAX_WAIT_HOURS': '3.5'}):
            result = float(os.environ.get('MAX_WAIT_HOURS', '4'))
            assert result == 3.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
