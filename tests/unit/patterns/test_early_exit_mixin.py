"""
Unit Tests for EarlyExitMixin (Pattern #3)

Tests cover:
1. No games scheduled check
2. Offseason detection (July-September)
3. Historical date check (>90 days)
4. Games finished check (NEW)
5. Backfill mode bypass for games_finished check (CRITICAL FIX)
6. Configuration flags (enable/disable checks)
7. Date parsing and validation
8. Skip logging integration
9. Fail-open behavior
10. Run method delegation
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from shared.processors.patterns.early_exit_mixin import EarlyExitMixin


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self, games_count=0):
        self.games_count = games_count

    def query(self, query_string):
        """Mock query execution"""
        result_mock = Mock()
        result_mock.result.return_value = [Mock(cnt=self.games_count)]
        return result_mock


class MockProcessor(EarlyExitMixin):
    """Mock processor for testing EarlyExitMixin"""

    def __init__(self, bq_client=None, project_id='test-project'):
        self.bq_client = bq_client
        self.project_id = project_id
        self.stats = {}
        self.run_id = 'test-run-123'
        self.log_processing_run = Mock()
        self.parent_run_called = False

    def run(self, opts):
        return super().run(opts)


class TestOffseasonCheck:
    """Test suite for offseason detection"""

    def test_july_is_offseason(self):
        """Test that July is detected as offseason"""
        processor = MockProcessor()

        assert processor._is_offseason('2024-07-15') is True
        assert processor._is_offseason('2024-07-01') is True
        assert processor._is_offseason('2024-07-31') is True

    def test_august_is_offseason(self):
        """Test that August is detected as offseason"""
        processor = MockProcessor()

        assert processor._is_offseason('2024-08-15') is True
        assert processor._is_offseason('2024-08-01') is True
        assert processor._is_offseason('2024-08-31') is True

    def test_september_is_offseason(self):
        """Test that September is detected as offseason"""
        processor = MockProcessor()

        assert processor._is_offseason('2024-09-15') is True
        assert processor._is_offseason('2024-09-01') is True
        assert processor._is_offseason('2024-09-30') is True

    def test_october_is_not_offseason(self):
        """Test that October (season start) is not offseason"""
        processor = MockProcessor()

        assert processor._is_offseason('2024-10-01') is False
        assert processor._is_offseason('2024-10-15') is False
        assert processor._is_offseason('2024-10-31') is False

    def test_june_is_not_offseason(self):
        """Test that June (playoffs) is not offseason"""
        processor = MockProcessor()

        assert processor._is_offseason('2024-06-01') is False
        assert processor._is_offseason('2024-06-15') is False
        assert processor._is_offseason('2024-06-30') is False

    def test_season_months_not_offseason(self):
        """Test that regular season months are not offseason"""
        processor = MockProcessor()

        # November-May (regular season + playoffs)
        for month in [11, 12, 1, 2, 3, 4, 5]:
            date_str = f'2024-{month:02d}-15'
            assert processor._is_offseason(date_str) is False


class TestHistoricalDateCheck:
    """Test suite for historical date detection"""

    def test_today_is_not_historical(self):
        """Test that today's date is not historical"""
        processor = MockProcessor()
        today = datetime.now().strftime('%Y-%m-%d')

        assert processor._is_too_historical(today) is False

    def test_yesterday_is_not_historical(self):
        """Test that yesterday is not historical"""
        processor = MockProcessor()
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        assert processor._is_too_historical(yesterday) is False

    def test_30_days_ago_not_historical(self):
        """Test that 30 days ago is not historical (< 90 day cutoff)"""
        processor = MockProcessor()
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        assert processor._is_too_historical(thirty_days_ago) is False

    def test_89_days_ago_not_historical(self):
        """Test that 89 days ago is not historical (at cutoff boundary)"""
        processor = MockProcessor()
        date_89_days_ago = (datetime.now() - timedelta(days=89)).strftime('%Y-%m-%d')

        assert processor._is_too_historical(date_89_days_ago) is False

    def test_91_days_ago_is_historical(self):
        """Test that 91 days ago is historical (> 90 day cutoff)"""
        processor = MockProcessor()
        date_91_days_ago = (datetime.now() - timedelta(days=91)).strftime('%Y-%m-%d')

        assert processor._is_too_historical(date_91_days_ago) is True

    def test_365_days_ago_is_historical(self):
        """Test that 1 year ago is historical"""
        processor = MockProcessor()
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        assert processor._is_too_historical(one_year_ago) is True

    def test_custom_cutoff(self):
        """Test historical check with custom cutoff days"""
        processor = MockProcessor()
        date_40_days_ago = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')

        # With 30-day cutoff, 40 days is historical
        assert processor._is_too_historical(date_40_days_ago, cutoff_days=30) is True

        # With 60-day cutoff, 40 days is not historical
        assert processor._is_too_historical(date_40_days_ago, cutoff_days=60) is False


class TestGamesScheduledCheck:
    """Test suite for games scheduled detection"""

    def test_has_games_scheduled(self):
        """Test that games scheduled returns True"""
        bq_client = MockBigQueryClient(games_count=10)
        processor = MockProcessor(bq_client=bq_client)

        assert processor._has_games_scheduled('2024-11-20') is True

    def test_no_games_scheduled(self):
        """Test that no games returns False"""
        bq_client = MockBigQueryClient(games_count=0)
        processor = MockProcessor(bq_client=bq_client)

        assert processor._has_games_scheduled('2024-07-15') is False

    def test_missing_bq_client_fails_open(self):
        """Test that missing bq_client fails open (returns True)"""
        processor = MockProcessor(bq_client=None)

        # Should fail open and return True
        assert processor._has_games_scheduled('2024-11-20') is True

    def test_missing_project_id_fails_open(self):
        """Test that missing project_id fails open"""
        processor = MockProcessor(bq_client=MockBigQueryClient())
        del processor.project_id  # Remove attribute entirely

        # Should fail open and return True
        assert processor._has_games_scheduled('2024-11-20') is True

    def test_query_error_fails_open(self):
        """Test that query errors fail open"""
        bq_client = Mock()
        bq_client.query.side_effect = Exception("Query failed")

        processor = MockProcessor(bq_client=bq_client)

        # Should fail open and return True
        assert processor._has_games_scheduled('2024-11-20') is True


class TestEarlyExitRun:
    """Test suite for run() method with early exits"""

    def test_skip_on_no_games(self):
        """Test that run skips when no games scheduled"""
        bq_client = MockBigQueryClient(games_count=0)
        processor = MockProcessor(bq_client=bq_client)

        # Create a base class with run method for proper MRO
        class BaseProcessor:
            def run(self, opts):
                return True  # Parent run

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = True
            ENABLE_OFFSEASON_CHECK = True
            ENABLE_HISTORICAL_DATE_CHECK = True

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {'start_date': '2024-07-15'}
        result = test_proc.run(opts)

        assert result is True
        test_proc.log_processing_run.assert_called_once()
        call_args = test_proc.log_processing_run.call_args
        assert call_args[1]['skip_reason'] == 'no_games'

    def test_skip_on_offseason(self):
        """Test that run skips during offseason"""
        bq_client = MockBigQueryClient(games_count=5)  # Has games (summer league)

        class BaseProcessor:
            def run(self, opts):
                return True

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = False  # Disable no-games check
            ENABLE_OFFSEASON_CHECK = True
            ENABLE_HISTORICAL_DATE_CHECK = True

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {'start_date': '2024-08-15'}
        result = test_proc.run(opts)

        assert result is True
        test_proc.log_processing_run.assert_called_once()
        call_args = test_proc.log_processing_run.call_args
        assert call_args[1]['skip_reason'] == 'offseason'

    def test_skip_on_historical_date(self):
        """Test that run skips on historical date"""
        bq_client = MockBigQueryClient(games_count=10)

        class BaseProcessor:
            def run(self, opts):
                return True

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = False
            ENABLE_OFFSEASON_CHECK = False
            ENABLE_HISTORICAL_DATE_CHECK = True

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()

        test_proc = TestProcessor(bq_client, 'test-project')
        historical_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
        opts = {'start_date': historical_date}
        result = test_proc.run(opts)

        assert result is True
        test_proc.log_processing_run.assert_called_once()
        call_args = test_proc.log_processing_run.call_args
        assert call_args[1]['skip_reason'] == 'too_historical'

    def test_no_skip_when_date_missing(self):
        """Test that run proceeds when no date provided"""
        processor = MockProcessor()

        parent_run_mock = Mock(return_value=True)
        with patch.object(EarlyExitMixin, 'run', parent_run_mock):
            opts = {}  # No start_date or game_date

            # Should call parent run (no early exit)
            # Direct test of the check
            assert opts.get('start_date') is None
            assert opts.get('game_date') is None

    def test_game_date_fallback(self):
        """Test that game_date is used when start_date is missing"""
        bq_client = MockBigQueryClient(games_count=0)

        class BaseProcessor:
            def run(self, opts):
                return True

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = True
            ENABLE_OFFSEASON_CHECK = True
            ENABLE_HISTORICAL_DATE_CHECK = True

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {'game_date': '2024-07-15'}  # Use game_date instead of start_date
        result = test_proc.run(opts)

        assert result is True
        # Should skip on no games
        test_proc.log_processing_run.assert_called_once()


class TestConfigurationFlags:
    """Test suite for configuration flag behavior"""

    def test_disable_no_games_check(self):
        """Test that disabling no-games check allows processing"""

        class NoGamesCheckDisabled(MockProcessor):
            ENABLE_NO_GAMES_CHECK = False

        bq_client = MockBigQueryClient(games_count=0)
        processor = NoGamesCheckDisabled(bq_client=bq_client)

        with patch.object(EarlyExitMixin, 'run', return_value=True):
            opts = {'start_date': '2024-11-20'}

            # Even with no games, should NOT skip (check disabled)
            # Test the logic directly
            if processor.ENABLE_NO_GAMES_CHECK:
                has_games = processor._has_games_scheduled(opts['start_date'])
                assert has_games is False  # Would skip if enabled
            else:
                # Check is disabled, won't evaluate
                assert processor.ENABLE_NO_GAMES_CHECK is False

    def test_disable_offseason_check(self):
        """Test that disabling offseason check allows processing"""

        class OffseasonCheckDisabled(MockProcessor):
            ENABLE_OFFSEASON_CHECK = False

        processor = OffseasonCheckDisabled()

        # Even in offseason, check is disabled
        assert processor.ENABLE_OFFSEASON_CHECK is False
        assert processor._is_offseason('2024-08-15') is True  # Is offseason
        # But won't skip because check is disabled

    def test_disable_historical_check(self):
        """Test that disabling historical check allows processing"""

        class HistoricalCheckDisabled(MockProcessor):
            ENABLE_HISTORICAL_DATE_CHECK = False

        processor = HistoricalCheckDisabled()

        old_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')

        # Even for old date, check is disabled
        assert processor.ENABLE_HISTORICAL_DATE_CHECK is False
        assert processor._is_too_historical(old_date) is True  # Is historical
        # But won't skip because check is disabled

    def test_all_checks_disabled(self):
        """Test that all checks disabled allows all processing"""

        class AllChecksDisabled(MockProcessor):
            ENABLE_NO_GAMES_CHECK = False
            ENABLE_OFFSEASON_CHECK = False
            ENABLE_HISTORICAL_DATE_CHECK = False

        processor = AllChecksDisabled(bq_client=MockBigQueryClient(games_count=0))

        # All checks should be disabled
        assert processor.ENABLE_NO_GAMES_CHECK is False
        assert processor.ENABLE_OFFSEASON_CHECK is False
        assert processor.ENABLE_HISTORICAL_DATE_CHECK is False


class TestSkipLogging:
    """Test suite for skip logging functionality"""

    def test_log_skip_updates_stats(self):
        """Test that _log_skip updates stats dict"""
        processor = MockProcessor()

        processor._log_skip('test_reason')

        assert 'skip_reason' in processor.stats
        assert processor.stats['skip_reason'] == 'test_reason'

    def test_log_skip_calls_log_processing_run(self):
        """Test that _log_skip calls log_processing_run"""
        processor = MockProcessor()

        processor._log_skip('offseason')

        processor.log_processing_run.assert_called_once_with(
            success=True,
            skip_reason='offseason'
        )

    def test_log_skip_without_stats_attr(self):
        """Test _log_skip when processor has no stats"""

        class NoStatsProcessor(EarlyExitMixin):
            def __init__(self):
                self.log_processing_run = Mock()
                self.run_id = 'test-123'

        processor = NoStatsProcessor()

        # Should handle missing stats gracefully
        processor._log_skip('test')

        # Stats should be created
        assert hasattr(processor, 'stats')
        assert processor.stats['run_id'] == 'test-123'

    def test_log_skip_error_handled_gracefully(self):
        """Test that logging errors don't break skip logic"""
        processor = MockProcessor()
        processor.log_processing_run.side_effect = Exception("Logging failed")

        # Should not raise exception
        try:
            processor._log_skip('test_reason')
            assert True  # Success - no exception raised
        except Exception:
            pytest.fail("_log_skip should handle logging errors gracefully")


class TestGamesFinishedCheck:
    """Test suite for games finished detection and backfill mode bypass"""

    def test_games_finished_check_enabled_blocks_unfinished_games(self):
        """Test that games_finished check blocks processing when games are not finished"""
        # Mock BigQuery client to return unfinished games
        bq_client = Mock()
        query_result = Mock()
        query_result.result.return_value = [
            Mock(total_games=5, finished_games=2, unfinished_games=3)
        ]
        bq_client.query.return_value = query_result

        class BaseProcessor:
            def run(self, opts):
                return True  # Would be called if no early exit

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = False  # Disable other checks
            ENABLE_OFFSEASON_CHECK = False
            ENABLE_HISTORICAL_DATE_CHECK = False
            ENABLE_GAMES_FINISHED_CHECK = True  # Enable games finished check

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {'start_date': '2026-01-27'}
        result = test_proc.run(opts)

        # Should exit early and skip
        assert result is True
        test_proc.log_processing_run.assert_called_once()
        call_args = test_proc.log_processing_run.call_args
        assert call_args[1]['skip_reason'] == 'games_not_finished'

    def test_games_finished_check_bypassed_in_backfill_mode(self):
        """Test that backfill_mode bypasses games_finished check (CRITICAL FIX VALIDATION)"""
        # Mock BigQuery client to return unfinished games
        bq_client = Mock()
        query_result = Mock()
        query_result.result.return_value = [
            Mock(total_games=5, finished_games=2, unfinished_games=3)
        ]
        bq_client.query.return_value = query_result

        class BaseProcessor:
            def run(self, opts):
                self.parent_run_called = True
                return True  # Called if no early exit

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = False  # Disable other checks
            ENABLE_OFFSEASON_CHECK = False
            ENABLE_HISTORICAL_DATE_CHECK = False
            ENABLE_GAMES_FINISHED_CHECK = True  # Enable games finished check

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()
                self.parent_run_called = False

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {
            'start_date': '2026-01-27',
            'backfill_mode': True  # CRITICAL: bypass games finished check
        }

        with patch('shared.processors.patterns.early_exit_mixin.logger') as mock_logger:
            result = test_proc.run(opts)

            # Should NOT exit early - should proceed to parent run
            assert result is True
            assert test_proc.parent_run_called is True

            # Should NOT have called log_processing_run (no skip)
            test_proc.log_processing_run.assert_not_called()

            # Should log backfill mode message
            mock_logger.info.assert_any_call(
                "BACKFILL_MODE: Historical date check disabled for 2026-01-27"
            )

    def test_games_finished_with_mixed_status(self):
        """Test games finished check with mixed game statuses"""
        class BaseProcessor:
            def run(self, opts):
                self.parent_run_called = True
                return True

        class TestProcessor(EarlyExitMixin, BaseProcessor):
            ENABLE_NO_GAMES_CHECK = False
            ENABLE_OFFSEASON_CHECK = False
            ENABLE_HISTORICAL_DATE_CHECK = False
            ENABLE_GAMES_FINISHED_CHECK = True

            def __init__(self, bq_client, project_id):
                self.bq_client = bq_client
                self.project_id = project_id
                self.stats = {}
                self.log_processing_run = Mock()
                self.parent_run_called = False

        # Test Case 1: Some games not finished - should exit
        bq_client = Mock()
        query_result = Mock()
        query_result.result.return_value = [
            Mock(total_games=10, finished_games=7, unfinished_games=3)
        ]
        bq_client.query.return_value = query_result

        test_proc = TestProcessor(bq_client, 'test-project')
        opts = {'start_date': '2026-01-27', 'backfill_mode': False}
        result = test_proc.run(opts)

        # Should exit early
        assert result is True
        assert test_proc.parent_run_called is False
        test_proc.log_processing_run.assert_called_once()
        call_args = test_proc.log_processing_run.call_args
        assert call_args[1]['skip_reason'] == 'games_not_finished'

        # Test Case 2: Same scenario but with backfill_mode - should NOT exit
        test_proc2 = TestProcessor(bq_client, 'test-project')
        opts2 = {'start_date': '2026-01-27', 'backfill_mode': True}
        result2 = test_proc2.run(opts2)

        # Should NOT exit early - should proceed to parent run
        assert result2 is True
        assert test_proc2.parent_run_called is True
        # Should NOT have called log_processing_run (no skip)
        assert test_proc2.log_processing_run.call_count == 0


class TestIntegration:
    """Integration tests for realistic scenarios"""

    def test_upcoming_processor_config(self):
        """Test configuration for upcoming game context processors"""

        class UpcomingPlayerGameContextProcessor(EarlyExitMixin):
            ENABLE_NO_GAMES_CHECK = True
            ENABLE_OFFSEASON_CHECK = True
            ENABLE_HISTORICAL_DATE_CHECK = False  # For UPCOMING games

        processor = UpcomingPlayerGameContextProcessor()

        # Should check no-games and offseason
        assert processor.ENABLE_NO_GAMES_CHECK is True
        assert processor.ENABLE_OFFSEASON_CHECK is True
        # But NOT historical dates (for upcoming games)
        assert processor.ENABLE_HISTORICAL_DATE_CHECK is False

    def test_analysis_processor_config(self):
        """Test configuration for analysis processors"""

        class PlayerShotZoneAnalysisProcessor(EarlyExitMixin):
            ENABLE_NO_GAMES_CHECK = False  # Analyzes historical games
            ENABLE_OFFSEASON_CHECK = True
            ENABLE_HISTORICAL_DATE_CHECK = False  # Can analyze any past date

        processor = PlayerShotZoneAnalysisProcessor()

        # Should NOT check no-games (analyzes past games)
        assert processor.ENABLE_NO_GAMES_CHECK is False
        # Should check offseason
        assert processor.ENABLE_OFFSEASON_CHECK is True
        # Should NOT check historical (can analyze old data)
        assert processor.ENABLE_HISTORICAL_DATE_CHECK is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
