"""
Unit tests for BallDontLie Player Averages scraper.

Tests cover:
- Season stats scraping with various parameters
- Player filtering (by ID, date range, season)
- Data normalization across stat categories
- Category validation (general, clutch, defense, shooting)
- Season type validation (regular, playoffs, IST, playin)
- Stat type validation (base, advanced, misc, etc.)
- Chunking of player IDs (max 100 per request)
- Error handling (503 service unavailable, validation errors)
- Multi-chunk request handling
- Notification system integration

Path: tests/scrapers/balldontlie/test_bdl_player_averages.py
Created: 2026-01-25
"""

import pytest
import json
import responses
from unittest.mock import Mock, patch
from datetime import datetime, timezone
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from scrapers.balldontlie.bdl_player_averages import BdlPlayerAveragesScraper
from scrapers.scraper_base import DownloadType, ExportMode


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bdl_api_key():
    """Mock BDL API key for testing."""
    return "test_api_key_12345"


@pytest.fixture
def sample_player_averages_response():
    """Sample BDL player averages API response."""
    return {
        "data": [
            {
                "player_id": 237,
                "season": 2024,
                "games_played": 45,
                "minutes": "35.2",
                "points": 27.8,
                "rebounds": 8.2,
                "assists": 7.5,
                "steals": 1.3,
                "blocks": 0.8,
                "turnovers": 3.1,
                "field_goals_made": 10.2,
                "field_goals_attempted": 20.5,
                "field_goal_percentage": 0.498,
                "three_pointers_made": 2.5,
                "three_pointers_attempted": 7.1,
                "three_point_percentage": 0.352,
                "free_throws_made": 4.9,
                "free_throws_attempted": 6.2,
                "free_throw_percentage": 0.790
            },
            {
                "player_id": 115,
                "season": 2024,
                "games_played": 50,
                "minutes": "33.8",
                "points": 24.5,
                "rebounds": 11.3,
                "assists": 3.8,
                "steals": 1.1,
                "blocks": 2.4,
                "turnovers": 2.0,
                "field_goals_made": 9.5,
                "field_goals_attempted": 17.2,
                "field_goal_percentage": 0.552,
                "three_pointers_made": 0.3,
                "three_pointers_attempted": 1.1,
                "three_point_percentage": 0.273,
                "free_throws_made": 5.2,
                "free_throws_attempted": 7.1,
                "free_throw_percentage": 0.732
            }
        ]
    }


@pytest.fixture
def sample_clutch_averages_response():
    """Sample BDL clutch averages response."""
    return {
        "data": [
            {
                "player_id": 237,
                "season": 2024,
                "games_played": 45,
                "points": 5.2,
                "rebounds": 1.5,
                "assists": 1.8,
                "field_goal_percentage": 0.455,
                "three_point_percentage": 0.380
            }
        ]
    }


@pytest.fixture
def empty_player_averages_response():
    """Empty player averages response."""
    return {"data": []}


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestBdlPlayerAveragesInitialization:
    """Test scraper initialization and configuration."""

    def test_scraper_class_attributes(self):
        """Test that scraper has correct class attributes."""
        assert BdlPlayerAveragesScraper.scraper_name == "bdl_player_averages"
        assert BdlPlayerAveragesScraper.download_type == DownloadType.JSON
        assert BdlPlayerAveragesScraper.decode_download_data is True
        assert BdlPlayerAveragesScraper.proxy_enabled is False
        assert BdlPlayerAveragesScraper.required_opts == []

    def test_scraper_initialization_with_player_ids(self, mock_bdl_api_key):
        """Test scraper initialization with player IDs."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237,115,140",
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            assert len(scraper._player_ids) == 3
            assert 237 in scraper._player_ids
            assert 115 in scraper._player_ids
            assert 140 in scraper._player_ids

    def test_scraper_initialization_defaults_to_current_season(self, mock_bdl_api_key):
        """Test scraper defaults to current NBA season."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages._current_nba_season', return_value=2024):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    debug=True,
                    export_groups=["test"]
                )

                assert scraper.opts["season"] == 2024

    def test_scraper_initialization_with_category(self, mock_bdl_api_key):
        """Test scraper initialization with different categories."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                category="clutch",
                debug=True,
                export_groups=["test"]
            )

            assert scraper.opts["category"] == "clutch"


# ============================================================================
# PARAMETER VALIDATION TESTS
# ============================================================================

class TestBdlPlayerAveragesParameterValidation:
    """Test parameter validation logic."""

    def test_valid_categories(self, mock_bdl_api_key):
        """Test that valid categories are accepted."""
        valid_categories = ["general", "clutch", "defense", "shooting"]

        for category in valid_categories:
            with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    category=category,
                    debug=True,
                    export_groups=["test"]
                )

                assert scraper.opts["category"] == category

    def test_invalid_category_raises_error(self, mock_bdl_api_key):
        """Test that invalid category raises error."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                with pytest.raises(ValueError, match="Invalid category"):
                    BdlPlayerAveragesScraper(
                        playerIds="237",
                        season=2024,
                        category="invalid_category",
                        debug=True,
                        export_groups=["test"]
                    )

    def test_valid_season_types(self, mock_bdl_api_key):
        """Test that valid season types are accepted."""
        valid_season_types = ["regular", "playoffs", "ist", "playin"]

        for season_type in valid_season_types:
            with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    seasonType=season_type,
                    debug=True,
                    export_groups=["test"]
                )

                assert scraper.opts["seasonType"] == season_type

    def test_invalid_season_type_raises_error(self, mock_bdl_api_key):
        """Test that invalid season type raises error."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                with pytest.raises(ValueError, match="Invalid season_type"):
                    BdlPlayerAveragesScraper(
                        playerIds="237",
                        season=2024,
                        seasonType="invalid_type",
                        debug=True,
                        export_groups=["test"]
                    )

    def test_valid_stat_types(self, mock_bdl_api_key):
        """Test that valid stat types are accepted."""
        valid_types = ["base", "advanced", "misc", "scoring", "usage"]

        for stat_type in valid_types:
            with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    type=stat_type,
                    debug=True,
                    export_groups=["test"]
                )

                assert scraper.opts["statType"] == stat_type

    def test_invalid_stat_type_raises_error(self, mock_bdl_api_key):
        """Test that invalid stat type raises error."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                with pytest.raises(ValueError, match="Invalid type"):
                    BdlPlayerAveragesScraper(
                        playerIds="237",
                        season=2024,
                        type="invalid_type",
                        debug=True,
                        export_groups=["test"]
                    )


# ============================================================================
# URL CONSTRUCTION TESTS
# ============================================================================

class TestBdlPlayerAveragesURLConstruction:
    """Test URL construction for different parameter combinations."""

    def test_url_construction_basic(self, mock_bdl_api_key):
        """Test basic URL construction."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            assert "https://api.balldontlie.io/v1/season_averages/general" in scraper.url
            assert "season_type=regular" in scraper.url
            assert "type=base" in scraper.url
            assert "season=2024" in scraper.url
            assert "player_ids[]=237" in scraper.url

    def test_url_construction_with_category(self, mock_bdl_api_key):
        """Test URL construction with different category."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                category="clutch",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            assert "/season_averages/clutch" in scraper.url

    def test_url_construction_with_multiple_players(self, mock_bdl_api_key):
        """Test URL construction with multiple player IDs."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237,115,140",
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            assert "player_ids[]=237" in scraper.url
            assert "player_ids[]=115" in scraper.url
            assert "player_ids[]=140" in scraper.url

    def test_url_construction_with_date_range(self, mock_bdl_api_key):
        """Test URL construction with date range."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                startDate="2024-10-01",
                endDate="2024-12-31",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            assert "start_date=2024-10-01" in scraper.url
            assert "end_date=2024-12-31" in scraper.url


# ============================================================================
# PLAYER ID CHUNKING TESTS
# ============================================================================

class TestBdlPlayerAveragesChunking:
    """Test player ID chunking logic (max 100 per request)."""

    def test_chunking_under_limit(self, mock_bdl_api_key):
        """Test that under 100 IDs creates single chunk."""
        player_ids = ",".join(str(i) for i in range(50))

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds=player_ids,
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            assert len(scraper._id_chunks) == 1
            assert len(scraper._id_chunks[0]) == 50

    def test_chunking_at_limit(self, mock_bdl_api_key):
        """Test that exactly 100 IDs creates single chunk."""
        player_ids = ",".join(str(i) for i in range(100))

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds=player_ids,
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            assert len(scraper._id_chunks) == 1
            assert len(scraper._id_chunks[0]) == 100

    def test_chunking_over_limit(self, mock_bdl_api_key):
        """Test that over 100 IDs creates multiple chunks."""
        player_ids = ",".join(str(i) for i in range(250))

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds=player_ids,
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            assert len(scraper._id_chunks) == 3
            assert len(scraper._id_chunks[0]) == 100
            assert len(scraper._id_chunks[1]) == 100
            assert len(scraper._id_chunks[2]) == 50

    def test_empty_player_ids_single_chunk(self, mock_bdl_api_key):
        """Test that no player IDs creates single empty chunk for league-wide query."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            assert len(scraper._id_chunks) == 1
            assert len(scraper._id_chunks[0]) == 0


# ============================================================================
# HTTP RESPONSE TESTS
# ============================================================================

class TestBdlPlayerAveragesHTTPResponses:
    """Test HTTP response handling."""

    @responses.activate
    def test_successful_api_response(self, mock_bdl_api_key, sample_player_averages_response):
        """Test successful API response handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=sample_player_averages_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237,115",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                assert scraper.data is not None
                assert scraper.data["season"] == 2024
                assert scraper.data["rowCount"] == 2

    @responses.activate
    def test_503_service_unavailable_error(self, mock_bdl_api_key):
        """Test 503 service unavailable error handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json={"message": "Service temporarily unavailable"},
            status=503
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()

                with pytest.raises(Exception):
                    scraper.download_data()
                    scraper.check_download_status()

    @responses.activate
    def test_404_not_found_error(self, mock_bdl_api_key):
        """Test 404 error handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json={"error": "Not found"},
            status=404
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="999999",
                season=2024,
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

class TestBdlPlayerAveragesDataValidation:
    """Test data validation logic."""

    def test_validate_successful_response(self, mock_bdl_api_key, sample_player_averages_response):
        """Test validation of successful response."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            scraper.decoded_data = sample_player_averages_response
            scraper.validate_download_data()

            # Should not raise exception
            assert scraper.decoded_data is not None

    def test_validate_missing_data_key(self, mock_bdl_api_key):
        """Test validation fails when 'data' key is missing."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {"invalid": "response"}
                scraper.url = "test_url"

                with pytest.raises(ValueError, match="missing 'data' key"):
                    scraper.validate_download_data()


# ============================================================================
# DATA TRANSFORMATION TESTS
# ============================================================================

class TestBdlPlayerAveragesDataTransformation:
    """Test data transformation logic."""

    @responses.activate
    def test_transform_player_averages(self, mock_bdl_api_key, sample_player_averages_response):
        """Test transformation of player averages data."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=sample_player_averages_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237,115",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.transform_data()

                # Check transformed data structure
                assert "ident" in scraper.data
                assert "timestamp" in scraper.data
                assert "season" in scraper.data
                assert "category" in scraper.data
                assert "seasonType" in scraper.data
                assert "statType" in scraper.data
                assert "playerCountRequested" in scraper.data
                assert "rowCount" in scraper.data
                assert "playerAverages" in scraper.data

                assert scraper.data["season"] == 2024
                assert scraper.data["category"] == "general"
                assert scraper.data["rowCount"] == 2

    def test_transform_sorts_by_player_id(self, mock_bdl_api_key):
        """Test that transformation sorts by player_id."""
        response = {
            "data": [
                {"player_id": 300, "points": 10},
                {"player_id": 100, "points": 20},
                {"player_id": 200, "points": 15}
            ]
        }

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="300,100,200",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = response
                scraper.transform_data()

                # Check sorting
                player_ids = [row["player_id"] for row in scraper.data["playerAverages"]]
                assert player_ids == [100, 200, 300]


# ============================================================================
# MULTI-CHUNK REQUEST TESTS
# ============================================================================

class TestBdlPlayerAveragesMultiChunk:
    """Test multi-chunk request handling."""

    @responses.activate
    def test_multi_chunk_requests(self, mock_bdl_api_key):
        """Test handling of multi-chunk requests."""
        # Create response for first chunk (IDs 0-99)
        chunk1_response = {
            "data": [{"player_id": i, "points": 20.0} for i in range(100)]
        }

        # Create response for second chunk (IDs 100-149)
        chunk2_response = {
            "data": [{"player_id": i, "points": 18.0} for i in range(100, 150)]
        }

        # Mock both requests
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=chunk1_response,
            status=200
        )

        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=chunk2_response,
            status=200
        )

        player_ids = ",".join(str(i) for i in range(150))

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds=player_ids,
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.transform_data()

                # Should have data from both chunks
                assert scraper.data["rowCount"] == 150

    @responses.activate
    def test_chunk_failure_handling(self, mock_bdl_api_key):
        """Test handling of chunk request failure."""
        chunk1_response = {
            "data": [{"player_id": i, "points": 20.0} for i in range(100)]
        }

        # First chunk succeeds
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=chunk1_response,
            status=200
        )

        # Second chunk fails
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json={"error": "Server error"},
            status=500
        )

        player_ids = ",".join(str(i) for i in range(150))

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds=player_ids,
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()

                with pytest.raises(Exception):
                    scraper.transform_data()


# ============================================================================
# NOTIFICATION INTEGRATION TESTS
# ============================================================================

class TestBdlPlayerAveragesNotifications:
    """Test notification system integration."""

    @responses.activate
    def test_success_notification_sent(self, mock_bdl_api_key, sample_player_averages_response):
        """Test that success notification is sent."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=sample_player_averages_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info') as mock_notify:
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.transform_data()

                # Verify success notification was called
                assert mock_notify.called

    def test_parameter_validation_error_notification(self, mock_bdl_api_key):
        """Test that parameter validation error notification is sent."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_error') as mock_notify:
                with pytest.raises(ValueError):
                    BdlPlayerAveragesScraper(
                        playerIds="237",
                        season=2024,
                        category="invalid_category",
                        debug=True,
                        export_groups=["test"]
                    )

                # Verify error notification was called
                assert mock_notify.called


# ============================================================================
# STAT NORMALIZATION TESTS
# ============================================================================

class TestBdlPlayerAveragesStatNormalization:
    """Test stat normalization across different categories."""

    def test_general_stats_structure(self, sample_player_averages_response):
        """Test structure of general stats."""
        player_stat = sample_player_averages_response["data"][0]

        # Core stats
        assert "points" in player_stat
        assert "rebounds" in player_stat
        assert "assists" in player_stat

        # Shooting stats
        assert "field_goal_percentage" in player_stat
        assert "three_point_percentage" in player_stat
        assert "free_throw_percentage" in player_stat

    def test_clutch_stats_structure(self, sample_clutch_averages_response):
        """Test structure of clutch stats."""
        player_stat = sample_clutch_averages_response["data"][0]

        assert "player_id" in player_stat
        assert "season" in player_stat
        assert "points" in player_stat
        assert "field_goal_percentage" in player_stat


# ============================================================================
# SCHEMA COMPLIANCE TESTS
# ============================================================================

class TestBdlPlayerAveragesSchemaCompliance:
    """Test that output matches expected schema format."""

    @responses.activate
    def test_output_schema_structure(self, mock_bdl_api_key, sample_player_averages_response):
        """Test that output has correct schema structure."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/season_averages/general",
            json=sample_player_averages_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_averages.notify_info'):
                scraper = BdlPlayerAveragesScraper(
                    playerIds="237,115",
                    season=2024,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.transform_data()

                # Verify types
                assert isinstance(scraper.data["ident"], str)
                assert isinstance(scraper.data["timestamp"], str)
                assert isinstance(scraper.data["season"], int)
                assert isinstance(scraper.data["rowCount"], int)
                assert isinstance(scraper.data["playerAverages"], list)

    def test_scraper_stats_format(self, mock_bdl_api_key):
        """Test get_scraper_stats output format."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerAveragesScraper(
                playerIds="237",
                season=2024,
                debug=True,
                export_groups=["test"]
            )

            scraper.data = {
                "rowCount": 50,
                "ident": "2024_general_regular_base_1p_237"
            }
            stats = scraper.get_scraper_stats()

            assert "rowCount" in stats
            assert "ident" in stats
            assert stats["rowCount"] == 50
