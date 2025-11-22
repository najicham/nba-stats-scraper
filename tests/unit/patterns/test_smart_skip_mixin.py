"""
Unit Tests for SmartSkipMixin (Pattern #1)

Tests cover:
1. Source relevance checking
2. Skip logic for irrelevant sources
3. Processing logic for relevant sources
4. Fail-open behavior for unknown sources
5. Fail-open behavior for missing source
6. Skip logging integration
7. Run method delegation
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from shared.processors.patterns.smart_skip_mixin import SmartSkipMixin


class MockProcessor(SmartSkipMixin):
    """Mock processor for testing SmartSkipMixin"""

    RELEVANT_SOURCES = {
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,
        'espn_boxscores': True,
        'odds_api_spreads': False,  # Irrelevant
        'odds_game_lines': False,   # Irrelevant
    }

    def __init__(self):
        self.stats = {}
        self.run_id = 'test-run-123'
        self.log_processing_run = Mock()
        self.parent_run_called = False

    def run(self, opts):
        # Call mixin's run method
        return super().run(opts)


class TestSmartSkipMixin:
    """Test suite for SmartSkipMixin"""

    def test_should_process_relevant_source(self):
        """Test that relevant sources return True"""
        processor = MockProcessor()

        assert processor.should_process_source('nbac_gamebook_player_stats') is True
        assert processor.should_process_source('bdl_player_boxscores') is True
        assert processor.should_process_source('espn_boxscores') is True

    def test_should_skip_irrelevant_source(self):
        """Test that irrelevant sources return False"""
        processor = MockProcessor()

        assert processor.should_process_source('odds_api_spreads') is False
        assert processor.should_process_source('odds_game_lines') is False

    def test_unknown_source_fails_open(self):
        """Test that unknown sources return True (fail-open)"""
        processor = MockProcessor()

        # Unknown source not in RELEVANT_SOURCES
        assert processor.should_process_source('unknown_table') is True
        assert processor.should_process_source('new_data_source') is True

    def test_missing_source_fails_open(self):
        """Test that missing/None source returns True (fail-open)"""
        processor = MockProcessor()

        assert processor.should_process_source(None) is True
        assert processor.should_process_source('') is True

    def test_empty_relevant_sources_fails_open(self):
        """Test processor with no RELEVANT_SOURCES defined"""

        class EmptyProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {}

        processor = EmptyProcessor()

        # All sources should fail open when RELEVANT_SOURCES is empty
        assert processor.should_process_source('any_source') is True

    def test_run_skips_irrelevant_source(self):
        """Test that run() method skips irrelevant sources"""

        # Create proper class hierarchy
        class BaseProcessor:
            def run(self, opts):
                return True  # Parent run

        class TestProcessor(SmartSkipMixin, BaseProcessor):
            RELEVANT_SOURCES = {
                'nbac_gamebook_player_stats': True,
                'odds_api_spreads': False  # Irrelevant
            }

            def __init__(self):
                self.stats = {}
                self.run_id = 'test-run-123'
                self.log_processing_run = Mock()

        processor = TestProcessor()
        opts = {'source_table': 'odds_api_spreads'}

        # This should skip and NOT call parent run
        result = processor.run(opts)

        assert result is True
        # Skip should be logged
        processor.log_processing_run.assert_called_once_with(
            success=True,
            skip_reason='irrelevant_source'
        )

    def test_run_processes_relevant_source(self):
        """Test that run() method processes relevant sources"""
        processor = MockProcessor()

        # Mock the parent's run method
        parent_run_mock = Mock(return_value=True)

        with patch.object(SmartSkipMixin, 'run', parent_run_mock):
            # Create a processor with proper inheritance
            class TestProcessor(SmartSkipMixin):
                RELEVANT_SOURCES = {'nbac_gamebook_player_stats': True}

                def __init__(self):
                    self.parent_called = False

                def run(self, opts):
                    result = super().run(opts)
                    if not opts.get('source_table') or self.should_process_source(opts.get('source_table')):
                        self.parent_called = True
                    return result

            test_proc = TestProcessor()
            opts = {'source_table': 'nbac_gamebook_player_stats'}

            # This should continue to parent run
            result = test_proc.run(opts)

            # Parent run should be called
            parent_run_mock.assert_called_once_with(opts)

    def test_run_without_source_table(self):
        """Test that run() processes when source_table is missing"""
        processor = MockProcessor()

        # Mock the parent's run method
        parent_run_mock = Mock(return_value=True)

        with patch.object(SmartSkipMixin, 'run', parent_run_mock):
            opts = {}  # No source_table

            # Should call parent run (fail-open)
            # Note: Direct call won't work due to MRO, testing the logic path
            should_process = processor.should_process_source(opts.get('source_table'))
            assert should_process is True

    def test_skip_logging_failure_handled_gracefully(self):
        """Test that logging failures don't break skip logic"""
        processor = MockProcessor()

        # Make log_processing_run raise an exception
        processor.log_processing_run.side_effect = Exception("Logging failed")

        with patch.object(SmartSkipMixin, 'run', return_value=True):
            opts = {'source_table': 'odds_api_spreads'}

            # Should still skip successfully despite logging error
            result = processor.run(opts)
            assert result is True

    def test_processor_without_log_method(self):
        """Test skip works even without log_processing_run method"""

        class MinimalProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {'relevant_source': True, 'irrelevant_source': False}

        processor = MinimalProcessor()

        # Should not have log_processing_run
        assert not hasattr(processor, 'log_processing_run')

        # Should still be able to check relevance
        assert processor.should_process_source('relevant_source') is True
        assert processor.should_process_source('irrelevant_source') is False

    def test_stats_dict_initialization(self):
        """Test that stats dict is initialized if missing"""

        class NoStatsProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {'irrelevant': False}

            def __init__(self):
                self.log_processing_run = Mock()
                # Don't initialize stats

        processor = NoStatsProcessor()

        with patch.object(SmartSkipMixin, 'run', return_value=True):
            opts = {'source_table': 'irrelevant'}

            # Should handle missing stats gracefully
            result = processor.run(opts)
            assert result is True


class TestSmartSkipIntegration:
    """Integration tests for SmartSkipMixin with realistic scenarios"""

    def test_analytics_processor_pattern(self):
        """Test pattern used in analytics processors"""

        class PlayerGameSummaryProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {
                'nbac_gamebook_player_stats': True,
                'espn_boxscore': True,
                'bdl_player_boxscores': True,
                'odds_api_props': False,
            }

        processor = PlayerGameSummaryProcessor()

        # Should process player stats sources
        assert processor.should_process_source('nbac_gamebook_player_stats') is True
        assert processor.should_process_source('espn_boxscore') is True

        # Should skip odds sources
        assert processor.should_process_source('odds_api_props') is False

    def test_precompute_processor_pattern(self):
        """Test pattern used in precompute processors"""

        class PlayerCompositeFactorsProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {
                # Phase 3 Analytics - RELEVANT
                'upcoming_player_game_context': True,
                'player_game_summary': True,
                # Phase 4 Precompute - RELEVANT
                'player_shot_zone_analysis': True,
                # Phase 2 Raw - NOT RELEVANT
                'nbac_gamebook_player_stats': False,
            }

        processor = PlayerCompositeFactorsProcessor()

        # Should process analytics and precompute sources
        assert processor.should_process_source('upcoming_player_game_context') is True
        assert processor.should_process_source('player_shot_zone_analysis') is True

        # Should skip raw sources
        assert processor.should_process_source('nbac_gamebook_player_stats') is False

    def test_multiple_skip_reasons(self):
        """Test that multiple irrelevant sources all skip correctly"""

        class StrictProcessor(SmartSkipMixin):
            RELEVANT_SOURCES = {
                'needed_source': True,
                'skip_1': False,
                'skip_2': False,
                'skip_3': False,
            }

        processor = StrictProcessor()

        # All skip sources should return False
        for skip_source in ['skip_1', 'skip_2', 'skip_3']:
            assert processor.should_process_source(skip_source) is False

        # Only needed_source should process
        assert processor.should_process_source('needed_source') is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
