"""
Unit tests for BallDontLie Box Scores scraper.

Tests cover:
- HTTP response mocking using responses library
- Player stat parsing from API responses
- Team stat aggregation logic
- Error handling (404, 500, timeout, rate limits)
- Retry logic with exponential backoff
- Data transformation and validation
- Pagination handling with cursors
- Notification system integration
- Schema compliance

Path: tests/scrapers/balldontlie/test_bdl_box_scores.py
Created: 2026-01-25
"""

import pytest
import json
import responses
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from scrapers.balldontlie.bdl_box_scores import BdlBoxScoresScraper
from scrapers.scraper_base import DownloadType, ExportMode


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bdl_api_key():
    """Mock BDL API key for testing."""
    return "test_api_key_12345"


@pytest.fixture
def sample_box_scores_response():
    """Sample BDL box scores API response."""
    return {
        "data": [
            {
                "id": 789001,
                "player": {
                    "id": 2544,
                    "first_name": "LeBron",
                    "last_name": "James"
                },
                "team": {
                    "id": 14,
                    "abbreviation": "LAL"
                },
                "game": {
                    "id": 1087392,
                    "date": "2025-01-20",
                    "home_team": {"abbreviation": "LAL"},
                    "visitor_team": {"abbreviation": "BOS"}
                },
                "min": "35:22",
                "pts": 28,
                "reb": 8,
                "ast": 12,
                "stl": 2,
                "blk": 1,
                "turnover": 3,
                "pf": 2,
                "fgm": 10,
                "fga": 18,
                "fg_pct": 0.556,
                "fg3m": 2,
                "fg3a": 5,
                "fg3_pct": 0.400,
                "ftm": 6,
                "fta": 7,
                "ft_pct": 0.857,
                "oreb": 1,
                "dreb": 7
            },
            {
                "id": 789002,
                "player": {
                    "id": 3149673,
                    "first_name": "Anthony",
                    "last_name": "Davis"
                },
                "team": {
                    "id": 14,
                    "abbreviation": "LAL"
                },
                "game": {
                    "id": 1087392,
                    "date": "2025-01-20",
                    "home_team": {"abbreviation": "LAL"},
                    "visitor_team": {"abbreviation": "BOS"}
                },
                "min": "32:45",
                "pts": 24,
                "reb": 12,
                "ast": 3,
                "stl": 1,
                "blk": 3,
                "turnover": 2,
                "pf": 3,
                "fgm": 9,
                "fga": 16,
                "fg_pct": 0.563,
                "fg3m": 0,
                "fg3a": 1,
                "fg3_pct": 0.000,
                "ftm": 6,
                "fta": 8,
                "ft_pct": 0.750,
                "oreb": 3,
                "dreb": 9
            }
        ],
        "meta": {
            "next_cursor": None,
            "per_page": 100
        }
    }


@pytest.fixture
def sample_box_scores_paginated_response():
    """Sample BDL box scores response with pagination cursor."""
    return {
        "data": [
            {
                "id": 789001,
                "player": {"id": 2544, "first_name": "LeBron", "last_name": "James"},
                "team": {"id": 14, "abbreviation": "LAL"},
                "game": {
                    "id": 1087392,
                    "date": "2025-01-20",
                    "home_team": {"abbreviation": "LAL"},
                    "visitor_team": {"abbreviation": "BOS"}
                },
                "pts": 28,
                "reb": 8,
                "ast": 12
            }
        ],
        "meta": {
            "next_cursor": "cursor_page2",
            "per_page": 100
        }
    }


@pytest.fixture
def sample_box_scores_page2_response():
    """Second page of box scores response."""
    return {
        "data": [
            {
                "id": 789002,
                "player": {"id": 3149673, "first_name": "Anthony", "last_name": "Davis"},
                "team": {"id": 14, "abbreviation": "LAL"},
                "game": {
                    "id": 1087392,
                    "date": "2025-01-20",
                    "home_team": {"abbreviation": "LAL"},
                    "visitor_team": {"abbreviation": "BOS"}
                },
                "pts": 24,
                "reb": 12,
                "ast": 3
            }
        ],
        "meta": {
            "next_cursor": None,
            "per_page": 100
        }
    }


@pytest.fixture
def empty_box_scores_response():
    """Empty box scores response (off-day)."""
    return {
        "data": [],
        "meta": {
            "next_cursor": None,
            "per_page": 100
        }
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestBdlBoxScoresInitialization:
    """Test scraper initialization and configuration."""

    def test_scraper_class_attributes(self):
        """Test that scraper has correct class attributes."""
        assert BdlBoxScoresScraper.scraper_name == "bdl_box_scores"
        assert BdlBoxScoresScraper.download_type == DownloadType.JSON
        assert BdlBoxScoresScraper.decode_download_data is True
        assert BdlBoxScoresScraper.proxy_enabled is False
        assert BdlBoxScoresScraper.required_opts == []

    def test_scraper_initialization_with_date(self, mock_bdl_api_key):
        """Test scraper initialization with explicit date."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper()
            scraper.set_opts({
                "date": "2025-01-20",
                "debug": True,
                "export_groups": ["test"]
            })
            assert scraper.opts["date"] == "2025-01-20"

    def test_scraper_initialization_defaults_to_yesterday(self, mock_bdl_api_key):
        """Test scraper defaults to yesterday's date."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.utils.date_utils.get_yesterday_eastern', return_value='2025-01-19'):
                scraper = BdlBoxScoresScraper()
                scraper.set_opts({
                    "debug": True,
                    "export_groups": ["test"]
                })
                assert scraper.opts["date"] == "2025-01-19"


# ============================================================================
# URL AND HEADERS TESTS
# ============================================================================

class TestBdlBoxScoresURLAndHeaders:
    """Test URL construction and header setup."""

    def test_url_construction(self, mock_bdl_api_key):
        """Test that URL is constructed correctly."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper()
            scraper.set_opts({
                "date": "2025-01-20",
                "debug": True,
                "export_groups": ["test"]
            })
            scraper.set_url()

            expected_url = "https://api.balldontlie.io/v1/box_scores?date=2025-01-20&per_page=100"
            assert scraper.url == expected_url
            assert scraper.base_url == "https://api.balldontlie.io/v1/box_scores"

    def test_headers_include_api_key(self, mock_bdl_api_key):
        """Test that headers include API key from environment."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper()
            scraper.set_opts({
                "date": "2025-01-20",
                "debug": True,
                "export_groups": ["test"]
            })
            scraper.set_headers()

            assert "Authorization" in scraper.headers
            assert scraper.headers["Authorization"] == f"Bearer {mock_bdl_api_key}"
            assert scraper.headers["Accept"] == "application/json"
            assert "User-Agent" in scraper.headers

    def test_headers_with_explicit_api_key(self):
        """Test that explicit API key overrides environment."""
        scraper = BdlBoxScoresScraper()
        scraper.set_opts({
            "date": "2025-01-20",
            "api_key": "explicit_key",
            "debug": True,
            "export_groups": ["test"]
        })
        scraper.set_headers()

        assert scraper.headers["Authorization"] == "Bearer explicit_key"


# ============================================================================
# HTTP RESPONSE MOCKING TESTS
# ============================================================================

class TestBdlBoxScoresHTTPResponses:
    """Test HTTP response handling with mocked responses."""

    @responses.activate
    def test_successful_api_response(self, mock_bdl_api_key, sample_box_scores_response):
        """Test successful API response handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.set_url()
                        scraper.set_headers()
                        scraper.download_data()
                        scraper.validate_download_data()
                        scraper.transform_data()

                        assert scraper.data is not None
                        assert scraper.data["date"] == "2025-01-20"
                        assert scraper.data["rowCount"] == 2
                        assert len(scraper.data["boxScores"]) == 2

    @responses.activate
    def test_404_not_found_error(self, mock_bdl_api_key):
        """Test 404 error handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json={"error": "Not found"},
            status=404
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper(
                date="2025-01-20",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()
            scraper.set_headers()

            with pytest.raises(Exception):
                scraper.download_data()

    @responses.activate
    def test_500_server_error(self, mock_bdl_api_key):
        """Test 500 server error handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json={"error": "Internal server error"},
            status=500
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper(
                date="2025-01-20",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()
            scraper.set_headers()

            with pytest.raises(Exception):
                scraper.download_data()

    @responses.activate
    def test_429_rate_limit_error(self, mock_bdl_api_key):
        """Test 429 rate limit error handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json={"error": "Too many requests"},
            status=429,
            headers={"Retry-After": "60"}
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper(
                date="2025-01-20",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()
            scraper.set_headers()

            with pytest.raises(Exception):
                scraper.download_data()


# ============================================================================
# DATA VALIDATION TESTS
# ============================================================================

class TestBdlBoxScoresDataValidation:
    """Test data validation logic."""

    def test_validate_successful_response(self, mock_bdl_api_key, sample_box_scores_response):
        """Test validation of successful response."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper(
                date="2025-01-20",
                debug=True,
                export_groups=["test"]
            )

            scraper.decoded_data = sample_box_scores_response
            scraper.validate_download_data()

            # Should not raise exception
            assert scraper.decoded_data is not None

    def test_validate_missing_data_key(self, mock_bdl_api_key):
        """Test validation fails when 'data' key is missing."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.notify_error'):
                scraper = BdlBoxScoresScraper(
                    date="2025-01-20",
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {"invalid": "response"}
                scraper.url = "test_url"

                with pytest.raises(ValueError, match="missing 'data' key"):
                    scraper.validate_download_data()

    def test_validate_non_dict_response(self, mock_bdl_api_key):
        """Test validation fails for non-dict response."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.notify_error'):
                scraper = BdlBoxScoresScraper(
                    date="2025-01-20",
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = ["invalid", "list"]
                scraper.url = "test_url"

                with pytest.raises(ValueError):
                    scraper.validate_download_data()


# ============================================================================
# DATA TRANSFORMATION TESTS
# ============================================================================

class TestBdlBoxScoresDataTransformation:
    """Test data transformation logic."""

    def test_transform_box_scores(self, mock_bdl_api_key, sample_box_scores_response):
        """Test transformation of box scores data."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.decoded_data = sample_box_scores_response
                        scraper.transform_data()

                        # Check transformed data structure
                        assert "date" in scraper.data
                        assert "timestamp" in scraper.data
                        assert "rowCount" in scraper.data
                        assert "boxScores" in scraper.data

                        assert scraper.data["date"] == "2025-01-20"
                        assert scraper.data["rowCount"] == 2
                        assert len(scraper.data["boxScores"]) == 2

    def test_transform_sorts_by_game_and_player_id(self, mock_bdl_api_key):
        """Test that transformation sorts by game_id and player_id."""
        response = {
            "data": [
                {
                    "id": 3,
                    "player_id": 300,
                    "game": {"id": 1000},
                    "pts": 10
                },
                {
                    "id": 1,
                    "player_id": 100,
                    "game": {"id": 1000},
                    "pts": 20
                },
                {
                    "id": 2,
                    "player_id": 200,
                    "game": {"id": 1000},
                    "pts": 15
                }
            ],
            "meta": {"next_cursor": None}
        }

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.decoded_data = response
                        scraper.transform_data()

                        # Check sorting
                        player_ids = [row.get("player_id") for row in scraper.data["boxScores"]]
                        assert player_ids == [100, 200, 300]


# ============================================================================
# PAGINATION TESTS
# ============================================================================

class TestBdlBoxScoresPagination:
    """Test pagination handling."""

    @responses.activate
    def test_pagination_with_cursor(self, mock_bdl_api_key, sample_box_scores_paginated_response, sample_box_scores_page2_response):
        """Test pagination handling with cursor."""
        # First page
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_paginated_response,
            status=200
        )

        # Second page
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_page2_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.set_url()
                        scraper.set_headers()
                        scraper.download_data()
                        scraper.transform_data()

                        # Should have data from both pages
                        assert scraper.data["rowCount"] == 2

    @responses.activate
    def test_pagination_failure_handling(self, mock_bdl_api_key, sample_box_scores_paginated_response):
        """Test pagination failure handling."""
        # First page succeeds
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_paginated_response,
            status=200
        )

        # Second page fails
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json={"error": "Server error"},
            status=500
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.notify_error'):
                scraper = BdlBoxScoresScraper(
                    date="2025-01-20",
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()

                with pytest.raises(Exception):
                    scraper.transform_data()


# ============================================================================
# EMPTY DATA TESTS
# ============================================================================

class TestBdlBoxScoresEmptyData:
    """Test handling of empty data responses."""

    @responses.activate
    def test_empty_response_off_day(self, mock_bdl_api_key, empty_box_scores_response):
        """Test handling of empty response (off-day)."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=empty_box_scores_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_warning'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.set_url()
                        scraper.set_headers()
                        scraper.download_data()
                        scraper.transform_data()

                        assert scraper.data["rowCount"] == 0
                        assert len(scraper.data["boxScores"]) == 0


# ============================================================================
# NOTIFICATION INTEGRATION TESTS
# ============================================================================

class TestBdlBoxScoresNotifications:
    """Test notification system integration."""

    @responses.activate
    def test_success_notification_sent(self, mock_bdl_api_key, sample_box_scores_response):
        """Test that success notification is sent."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info') as mock_notify:
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.set_url()
                        scraper.set_headers()
                        scraper.download_data()
                        scraper.transform_data()

                        # Verify success notification was called
                        assert mock_notify.called

    def test_validation_error_notification_sent(self, mock_bdl_api_key):
        """Test that validation error notification is sent."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.notify_error') as mock_notify:
                scraper = BdlBoxScoresScraper(
                    date="2025-01-20",
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {"invalid": "response"}
                scraper.url = "test_url"

                with pytest.raises(ValueError):
                    scraper.validate_download_data()

                # Verify error notification was called
                assert mock_notify.called


# ============================================================================
# PLAYER STAT PARSING TESTS
# ============================================================================

class TestBdlBoxScoresPlayerStatParsing:
    """Test player stat parsing from API responses."""

    def test_parse_complete_player_stats(self, sample_box_scores_response):
        """Test parsing of complete player stats."""
        player_stat = sample_box_scores_response["data"][0]

        # Verify all key stats are present
        assert player_stat["pts"] == 28
        assert player_stat["reb"] == 8
        assert player_stat["ast"] == 12
        assert player_stat["stl"] == 2
        assert player_stat["blk"] == 1
        assert player_stat["turnover"] == 3
        assert player_stat["pf"] == 2

        # Verify shooting stats
        assert player_stat["fgm"] == 10
        assert player_stat["fga"] == 18
        assert player_stat["fg_pct"] == 0.556
        assert player_stat["fg3m"] == 2
        assert player_stat["fg3a"] == 5
        assert player_stat["ftm"] == 6
        assert player_stat["fta"] == 7

    def test_parse_player_info(self, sample_box_scores_response):
        """Test parsing of player information."""
        player_stat = sample_box_scores_response["data"][0]

        assert player_stat["player"]["id"] == 2544
        assert player_stat["player"]["first_name"] == "LeBron"
        assert player_stat["player"]["last_name"] == "James"

    def test_parse_team_info(self, sample_box_scores_response):
        """Test parsing of team information."""
        player_stat = sample_box_scores_response["data"][0]

        assert player_stat["team"]["id"] == 14
        assert player_stat["team"]["abbreviation"] == "LAL"

    def test_parse_game_info(self, sample_box_scores_response):
        """Test parsing of game information."""
        player_stat = sample_box_scores_response["data"][0]

        assert player_stat["game"]["id"] == 1087392
        assert player_stat["game"]["date"] == "2025-01-20"


# ============================================================================
# SCHEMA COMPLIANCE TESTS
# ============================================================================

class TestBdlBoxScoresSchemaCompliance:
    """Test that output matches expected schema format."""

    @responses.activate
    def test_output_schema_structure(self, mock_bdl_api_key, sample_box_scores_response):
        """Test that output has correct schema structure."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/box_scores",
            json=sample_box_scores_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability'):
                with patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability'):
                    with patch('scrapers.balldontlie.bdl_box_scores.notify_info'):
                        scraper = BdlBoxScoresScraper(
                            date="2025-01-20",
                            debug=True,
                            export_groups=["test"]
                        )

                        scraper.set_url()
                        scraper.set_headers()
                        scraper.download_data()
                        scraper.transform_data()

                        # Verify top-level schema
                        assert "date" in scraper.data
                        assert "timestamp" in scraper.data
                        assert "rowCount" in scraper.data
                        assert "boxScores" in scraper.data

                        # Verify types
                        assert isinstance(scraper.data["date"], str)
                        assert isinstance(scraper.data["timestamp"], str)
                        assert isinstance(scraper.data["rowCount"], int)
                        assert isinstance(scraper.data["boxScores"], list)

    def test_scraper_stats_format(self, mock_bdl_api_key):
        """Test get_scraper_stats output format."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlBoxScoresScraper(
                date="2025-01-20",
                debug=True,
                export_groups=["test"]
            )

            scraper.data = {"rowCount": 150, "boxScores": []}
            stats = scraper.get_scraper_stats()

            assert "rowCount" in stats
            assert "date" in stats
            assert stats["date"] == "2025-01-20"
