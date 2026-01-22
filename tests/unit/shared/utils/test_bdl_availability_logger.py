"""
Unit tests for BdlAvailabilityLogger

Tests the BDL game availability logging functionality including:
- Extracting games from BDL box score responses
- Handling empty or malformed responses
- West Coast game identification
- BigQuery write operations (mocked)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch

from shared.utils.bdl_availability_logger import (
    BdlAvailabilityLogger,
    GameAvailability,
    log_bdl_game_availability
)


class TestBdlAvailabilityLogger:
    """Test BdlAvailabilityLogger functionality"""

    # ========== Fixtures ==========

    @pytest.fixture
    def sample_box_scores(self):
        """Sample BDL box scores response with multiple games"""
        return [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                },
                "player": {"first_name": "Stephen", "last_name": "Curry"}
            },
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                },
                "player": {"first_name": "LeBron", "last_name": "James"}
            },
            {
                "game": {
                    "id": 12346,
                    "status": "Final",
                    "home_team": {"abbreviation": "BOS"},
                    "visitor_team": {"abbreviation": "NYK"}
                },
                "player": {"first_name": "Jayson", "last_name": "Tatum"}
            }
        ]

    @pytest.fixture
    def empty_box_scores(self):
        """Empty BDL box scores response"""
        return []

    @pytest.fixture
    def malformed_box_scores(self):
        """Malformed BDL box scores with missing data"""
        return [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {},  # Missing abbreviation
                    "visitor_team": {"abbreviation": "LAL"}
                }
            },
            {
                "game": None  # Null game
            },
            {
                # Missing game key entirely
                "player": {"first_name": "John", "last_name": "Doe"}
            }
        ]

    @pytest.fixture
    def expected_games(self):
        """Sample expected games from schedule"""
        return [
            ("GSW", "LAL", datetime(2026, 1, 21, 22, 30, 0, tzinfo=timezone.utc)),
            ("BOS", "NYK", datetime(2026, 1, 21, 19, 0, 0, tzinfo=timezone.utc)),
            ("MIA", "CHI", datetime(2026, 1, 21, 20, 0, 0, tzinfo=timezone.utc))
        ]

    @pytest.fixture
    def logger(self):
        """BdlAvailabilityLogger instance"""
        return BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

    # ========== Extract Games Tests ==========

    def test_extract_games_from_response_with_valid_data(self, logger, sample_box_scores):
        """Test parsing valid BDL box scores response"""
        games = logger.extract_games_from_response(sample_box_scores)

        # Should extract 2 unique games
        assert len(games) == 2

        # Check GSW vs LAL game
        gsw_lal_key = ("GSW", "LAL")
        assert gsw_lal_key in games
        assert games[gsw_lal_key]["bdl_game_id"] == 12345
        assert games[gsw_lal_key]["game_status"] == "Final"
        assert games[gsw_lal_key]["player_count"] == 2

        # Check BOS vs NYK game
        bos_nyk_key = ("BOS", "NYK")
        assert bos_nyk_key in games
        assert games[bos_nyk_key]["bdl_game_id"] == 12346
        assert games[bos_nyk_key]["game_status"] == "Final"
        assert games[bos_nyk_key]["player_count"] == 1

    def test_extract_games_handles_empty_response(self, logger, empty_box_scores):
        """Test handling empty BDL response gracefully"""
        games = logger.extract_games_from_response(empty_box_scores)

        assert len(games) == 0
        assert isinstance(games, dict)

    def test_extract_games_handles_malformed_data(self, logger, malformed_box_scores):
        """Test handling malformed BDL response gracefully"""
        games = logger.extract_games_from_response(malformed_box_scores)

        # Should skip all malformed entries
        assert len(games) == 0

    def test_extract_games_aggregates_player_count(self, logger):
        """Test player count aggregation for same game"""
        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ] * 10  # 10 players in same game

        games = logger.extract_games_from_response(box_scores)

        assert len(games) == 1
        assert games[("GSW", "LAL")]["player_count"] == 10

    def test_extract_games_handles_missing_game_id(self, logger):
        """Test handling box scores with missing game ID"""
        box_scores = [
            {
                "game": {
                    # No id field
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ]

        games = logger.extract_games_from_response(box_scores)

        # Should still extract the game, just with None for bdl_game_id
        assert len(games) == 1
        assert games[("GSW", "LAL")]["bdl_game_id"] is None

    # ========== West Coast Game Tests ==========

    def test_identifies_west_coast_games(self, logger):
        """Test identification of West Coast games"""
        # GSW is a West Coast team
        assert "GSW" in BdlAvailabilityLogger.WEST_COAST_TEAMS

        # Test with West Coast home team
        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "BOS"}
                }
            }
        ]

        games = logger.extract_games_from_response(box_scores)
        assert ("GSW", "BOS") in games

    def test_west_coast_teams_complete_list(self):
        """Test West Coast teams list contains expected teams"""
        west_coast = BdlAvailabilityLogger.WEST_COAST_TEAMS

        # Verify Pacific timezone teams
        assert "GSW" in west_coast  # Golden State Warriors
        assert "LAL" in west_coast  # Los Angeles Lakers
        assert "LAC" in west_coast  # Los Angeles Clippers
        assert "SAC" in west_coast  # Sacramento Kings
        assert "POR" in west_coast  # Portland Trail Blazers
        assert "PHX" in west_coast  # Phoenix Suns

        # Verify count
        assert len(west_coast) == 6

    def test_non_west_coast_teams(self):
        """Test that East Coast teams are not in West Coast set"""
        west_coast = BdlAvailabilityLogger.WEST_COAST_TEAMS

        # East Coast teams should not be in the set
        assert "BOS" not in west_coast  # Boston
        assert "NYK" not in west_coast  # New York
        assert "MIA" not in west_coast  # Miami
        assert "ATL" not in west_coast  # Atlanta

    # ========== BigQuery Write Tests ==========

    @patch('google.cloud.bigquery.Client')
    def test_log_bdl_game_availability_writes_to_bigquery(self, mock_bq_client):
        """Test that availability logging writes to BigQuery"""
        mock_client_instance = Mock()
        mock_bq_client.return_value = mock_client_instance
        mock_client_instance.insert_rows_json.return_value = []

        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        # Mock expected games to return empty (so we don't hit BigQuery for schedule)
        logger._expected_games = []

        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ]

        games = logger.extract_games_from_response(box_scores)
        records = logger.log_availability(games, dry_run=False)

        # Verify BigQuery write was called
        mock_client_instance.insert_rows_json.assert_called_once()

        # Verify call arguments
        call_args = mock_client_instance.insert_rows_json.call_args
        table_id = call_args[0][0]
        rows = call_args[0][1]

        assert "bdl_game_scrape_attempts" in table_id
        assert len(rows) == 1
        assert rows[0]["home_team"] == "GSW"
        assert rows[0]["away_team"] == "LAL"

    @patch('google.cloud.bigquery.Client')
    def test_dry_run_mode_does_not_write_to_bigquery(self, mock_bq_client):
        """Test dry_run mode prevents BigQuery writes"""
        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        # Mock expected games
        logger._expected_games = []

        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ]

        games = logger.extract_games_from_response(box_scores)
        records = logger.log_availability(games, dry_run=True)

        # Verify BigQuery client was not created
        mock_bq_client.assert_not_called()

        # But records should still be returned
        assert len(records) == 1

    @patch('google.cloud.bigquery.Client')
    def test_bigquery_write_failure_does_not_crash(self, mock_bq_client):
        """Test that BigQuery write failures are handled gracefully"""
        mock_client_instance = Mock()
        mock_bq_client.return_value = mock_client_instance
        mock_client_instance.insert_rows_json.side_effect = Exception("BigQuery error")

        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        logger._expected_games = []

        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ]

        games = logger.extract_games_from_response(box_scores)

        # Should not raise exception
        records = logger.log_availability(games, dry_run=False)

        # Records should still be returned despite write failure
        assert len(records) == 1

    # ========== Convenience Function Tests ==========

    @patch('google.cloud.bigquery.Client')
    def test_log_bdl_game_availability_convenience_function(self, mock_bq_client):
        """Test convenience function creates logger and logs availability"""
        mock_client_instance = Mock()
        mock_bq_client.return_value = mock_client_instance
        mock_client_instance.insert_rows_json.return_value = []

        box_scores = [
            {
                "game": {
                    "id": 12345,
                    "status": "Final",
                    "home_team": {"abbreviation": "GSW"},
                    "visitor_team": {"abbreviation": "LAL"}
                }
            }
        ]

        # Use dry_run to avoid BigQuery schedule query
        records = log_bdl_game_availability(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            box_scores=box_scores,
            workflow="post_game_window_2",
            dry_run=True
        )

        # Should return records
        assert len(records) == 1
        assert records[0].home_team == "GSW"
        assert records[0].away_team == "LAL"
        assert records[0].was_available is True

    # ========== Game Availability Dataclass Tests ==========

    def test_game_availability_dataclass(self):
        """Test GameAvailability dataclass creation"""
        game = GameAvailability(
            game_date="2026-01-21",
            home_team="GSW",
            away_team="LAL",
            was_available=True,
            player_count=10,
            game_status="Final",
            bdl_game_id=12345,
            expected_start_time=datetime(2026, 1, 21, 22, 30, 0, tzinfo=timezone.utc),
            is_west_coast=True
        )

        assert game.game_date == "2026-01-21"
        assert game.home_team == "GSW"
        assert game.away_team == "LAL"
        assert game.was_available is True
        assert game.player_count == 10
        assert game.game_status == "Final"
        assert game.bdl_game_id == 12345
        assert game.is_west_coast is True

    def test_game_availability_defaults(self):
        """Test GameAvailability dataclass with default values"""
        game = GameAvailability(
            game_date="2026-01-21",
            home_team="BOS",
            away_team="NYK",
            was_available=False
        )

        assert game.player_count is None
        assert game.game_status is None
        assert game.bdl_game_id is None
        assert game.expected_start_time is None
        assert game.is_west_coast is False

    # ========== Logger Initialization Tests ==========

    def test_logger_initialization(self):
        """Test BdlAvailabilityLogger initialization"""
        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        assert logger.game_date == "2026-01-21"
        assert logger.execution_id == "test-execution-123"
        assert logger.workflow == "post_game_window_2"
        assert logger._expected_games is None
        assert logger.scrape_timestamp is not None

    def test_logger_custom_timestamp(self):
        """Test BdlAvailabilityLogger with custom timestamp"""
        custom_time = datetime(2026, 1, 21, 10, 30, 0, tzinfo=timezone.utc)
        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2",
            scrape_timestamp=custom_time
        )

        assert logger.scrape_timestamp == custom_time

    # ========== Log Availability Tests ==========

    @patch('google.cloud.bigquery.Client')
    def test_log_availability_marks_available_games(self, mock_bq_client):
        """Test log_availability correctly marks games as available"""
        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        # Mock expected games
        logger._expected_games = [
            ("GSW", "LAL", datetime(2026, 1, 21, 22, 30, 0, tzinfo=timezone.utc)),
            ("BOS", "NYK", datetime(2026, 1, 21, 19, 0, 0, tzinfo=timezone.utc))
        ]

        # Only GSW vs LAL is available
        returned_games = {
            ("GSW", "LAL"): {
                "bdl_game_id": 12345,
                "game_status": "Final",
                "player_count": 10
            }
        }

        records = logger.log_availability(returned_games, dry_run=True)

        # Should have 2 records (both expected games)
        assert len(records) == 2

        # GSW vs LAL should be marked available
        gsw_lal = next(r for r in records if r.home_team == "GSW")
        assert gsw_lal.was_available is True
        assert gsw_lal.player_count == 10

        # BOS vs NYK should be marked not available
        bos_nyk = next(r for r in records if r.home_team == "BOS")
        assert bos_nyk.was_available is False
        assert bos_nyk.player_count is None

    @patch('google.cloud.bigquery.Client')
    def test_log_availability_handles_unexpected_games(self, mock_bq_client):
        """Test log_availability logs unexpected games from BDL"""
        logger = BdlAvailabilityLogger(
            game_date="2026-01-21",
            execution_id="test-execution-123",
            workflow="post_game_window_2"
        )

        # Expected only GSW vs LAL
        logger._expected_games = [
            ("GSW", "LAL", datetime(2026, 1, 21, 22, 30, 0, tzinfo=timezone.utc))
        ]

        # But BDL returned an additional game
        returned_games = {
            ("GSW", "LAL"): {
                "bdl_game_id": 12345,
                "game_status": "Final",
                "player_count": 10
            },
            ("BOS", "NYK"): {
                "bdl_game_id": 12346,
                "game_status": "Final",
                "player_count": 10
            }
        }

        records = logger.log_availability(returned_games, dry_run=True)

        # Should have 2 records
        assert len(records) == 2

        # Both should be marked as available
        assert all(r.was_available for r in records)

        # BOS vs NYK should have None for expected_start_time (unexpected)
        bos_nyk = next(r for r in records if r.home_team == "BOS")
        assert bos_nyk.expected_start_time is None
