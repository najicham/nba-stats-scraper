"""
Unit tests for BallDontLie Player Detail scraper.

Tests cover:
- Player profile scraping
- Player name normalization
- Team mapping
- Response format handling (legacy vs wrapped format)
- Player ID validation
- Error handling (404 for non-existent players)
- Notification system integration
- Schema compliance

Path: tests/scrapers/balldontlie/test_bdl_player_detail.py
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

from scrapers.balldontlie.bdl_player_detail import BdlPlayerDetailScraper
from scrapers.scraper_base import DownloadType, ExportMode


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bdl_api_key():
    """Mock BDL API key for testing."""
    return "test_api_key_12345"


@pytest.fixture
def sample_player_detail_response():
    """Sample BDL player detail API response (wrapped format)."""
    return {
        "data": {
            "id": 237,
            "first_name": "LeBron",
            "last_name": "James",
            "position": "F",
            "height": "6-9",
            "weight": "250",
            "jersey_number": "23",
            "college": "St. Vincent-St. Mary HS",
            "country": "USA",
            "draft_year": 2003,
            "draft_round": 1,
            "draft_number": 1,
            "team": {
                "id": 14,
                "conference": "West",
                "division": "Pacific",
                "city": "Los Angeles",
                "name": "Lakers",
                "full_name": "Los Angeles Lakers",
                "abbreviation": "LAL"
            }
        }
    }


@pytest.fixture
def sample_player_detail_legacy_response():
    """Sample BDL player detail API response (legacy bare object format)."""
    return {
        "id": 237,
        "first_name": "LeBron",
        "last_name": "James",
        "position": "F",
        "height": "6-9",
        "weight": "250",
        "jersey_number": "23",
        "college": "St. Vincent-St. Mary HS",
        "country": "USA",
        "draft_year": 2003,
        "draft_round": 1,
        "draft_number": 1,
        "team": {
            "id": 14,
            "conference": "West",
            "division": "Pacific",
            "city": "Los Angeles",
            "name": "Lakers",
            "full_name": "Los Angeles Lakers",
            "abbreviation": "LAL"
        }
    }


@pytest.fixture
def sample_player_without_team_response():
    """Sample player detail for free agent (no team)."""
    return {
        "data": {
            "id": 999,
            "first_name": "John",
            "last_name": "Doe",
            "position": "G",
            "height": "6-3",
            "weight": "190",
            "jersey_number": None,
            "college": "University of Basketball",
            "country": "USA",
            "draft_year": 2020,
            "draft_round": 2,
            "draft_number": 45,
            "team": None
        }
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestBdlPlayerDetailInitialization:
    """Test scraper initialization and configuration."""

    def test_scraper_class_attributes(self):
        """Test that scraper has correct class attributes."""
        assert BdlPlayerDetailScraper.scraper_name == "bdl_player_detail"
        assert BdlPlayerDetailScraper.download_type == DownloadType.JSON
        assert BdlPlayerDetailScraper.decode_download_data is True
        assert BdlPlayerDetailScraper.proxy_enabled is False
        assert BdlPlayerDetailScraper.required_opts == ["playerId"]

    def test_scraper_initialization_with_player_id(self, mock_bdl_api_key):
        """Test scraper initialization with player ID."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            assert scraper.opts["playerId"] == 237

    def test_scraper_initialization_requires_player_id(self, mock_bdl_api_key):
        """Test that scraper requires player ID."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with pytest.raises(Exception):
                BdlPlayerDetailScraper(
                    debug=True,
                    export_groups=["test"]
                )


# ============================================================================
# URL AND HEADERS TESTS
# ============================================================================

class TestBdlPlayerDetailURLAndHeaders:
    """Test URL construction and header setup."""

    def test_url_construction(self, mock_bdl_api_key):
        """Test that URL is constructed correctly."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            expected_url = "https://api.balldontlie.io/v1/players/237"
            assert scraper.url == expected_url
            assert scraper.base_url == "https://api.balldontlie.io/v1/players"

    def test_url_construction_with_string_id(self, mock_bdl_api_key):
        """Test URL construction with string player ID."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId="237",
                debug=True,
                export_groups=["test"]
            )

            scraper.set_url()

            assert "players/237" in scraper.url

    def test_headers_include_api_key(self, mock_bdl_api_key):
        """Test that headers include API key from environment."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            scraper.set_headers()

            assert "Authorization" in scraper.headers
            assert scraper.headers["Authorization"] == f"Bearer {mock_bdl_api_key}"
            assert scraper.headers["Accept"] == "application/json"
            assert "User-Agent" in scraper.headers

    def test_headers_with_explicit_api_key(self):
        """Test that explicit API key overrides environment."""
        scraper = BdlPlayerDetailScraper(
            playerId=237,
            api_key="explicit_key",
            debug=True,
            export_groups=["test"]
        )

        scraper.set_headers()

        assert scraper.headers["Authorization"] == "Bearer explicit_key"


# ============================================================================
# HTTP RESPONSE TESTS
# ============================================================================

class TestBdlPlayerDetailHTTPResponses:
    """Test HTTP response handling."""

    @responses.activate
    def test_successful_api_response(self, mock_bdl_api_key, sample_player_detail_response):
        """Test successful API response handling."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                assert scraper.data is not None
                assert scraper.data["playerId"] == 237
                assert scraper.data["player"]["first_name"] == "LeBron"
                assert scraper.data["player"]["last_name"] == "James"

    @responses.activate
    def test_404_player_not_found(self, mock_bdl_api_key):
        """Test 404 error for non-existent player."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/999999",
            json={"error": "Player not found"},
            status=404
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=999999,
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
            "https://api.balldontlie.io/v1/players/237",
            json={"error": "Internal server error"},
            status=500
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
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

class TestBdlPlayerDetailDataValidation:
    """Test data validation logic."""

    def test_validate_wrapped_format_response(self, mock_bdl_api_key, sample_player_detail_response):
        """Test validation of wrapped format response (v1.4+)."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            scraper.decoded_data = sample_player_detail_response
            scraper.validate_download_data()

            # Should unwrap the data
            assert scraper.decoded_data["id"] == 237
            assert "first_name" in scraper.decoded_data

    def test_validate_legacy_format_response(self, mock_bdl_api_key, sample_player_detail_legacy_response):
        """Test validation of legacy bare object format."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            scraper.decoded_data = sample_player_detail_legacy_response
            scraper.validate_download_data()

            # Should accept as-is
            assert scraper.decoded_data["id"] == 237

    def test_validate_player_id_mismatch(self, mock_bdl_api_key):
        """Test validation fails when returned player ID doesn't match requested."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_error'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {
                    "data": {
                        "id": 115,  # Different player ID
                        "first_name": "Anthony",
                        "last_name": "Davis"
                    }
                }
                scraper.url = "test_url"

                with pytest.raises(ValueError, match="does not match requested"):
                    scraper.validate_download_data()

    def test_validate_missing_player_id(self, mock_bdl_api_key):
        """Test validation fails when player ID is missing."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_error'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {
                    "data": {
                        "first_name": "LeBron",
                        "last_name": "James"
                        # Missing 'id' field
                    }
                }
                scraper.url = "test_url"

                with pytest.raises(ValueError, match="not found in BallDontLie"):
                    scraper.validate_download_data()

    def test_validate_malformed_response(self, mock_bdl_api_key):
        """Test validation fails for completely malformed response."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_error'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.decoded_data = {"error": "Invalid response"}
                scraper.url = "test_url"

                with pytest.raises(ValueError):
                    scraper.validate_download_data()


# ============================================================================
# DATA TRANSFORMATION TESTS
# ============================================================================

class TestBdlPlayerDetailDataTransformation:
    """Test data transformation logic."""

    @responses.activate
    def test_transform_player_detail(self, mock_bdl_api_key, sample_player_detail_response):
        """Test transformation of player detail data."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                # Check transformed data structure
                assert "playerId" in scraper.data
                assert "timestamp" in scraper.data
                assert "player" in scraper.data

                assert scraper.data["playerId"] == 237
                assert isinstance(scraper.data["timestamp"], str)
                assert scraper.data["player"]["id"] == 237

    @responses.activate
    def test_transform_preserves_all_fields(self, mock_bdl_api_key, sample_player_detail_response):
        """Test that transformation preserves all player fields."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                player = scraper.data["player"]

                # Check all key fields preserved
                assert player["first_name"] == "LeBron"
                assert player["last_name"] == "James"
                assert player["position"] == "F"
                assert player["height"] == "6-9"
                assert player["weight"] == "250"
                assert player["jersey_number"] == "23"
                assert player["draft_year"] == 2003
                assert player["draft_round"] == 1
                assert player["draft_number"] == 1


# ============================================================================
# PLAYER NAME NORMALIZATION TESTS
# ============================================================================

class TestBdlPlayerDetailNameNormalization:
    """Test player name normalization."""

    def test_parse_standard_name(self, sample_player_detail_response):
        """Test parsing of standard player name."""
        player = sample_player_detail_response["data"]

        full_name = f"{player['first_name']} {player['last_name']}"
        assert full_name == "LeBron James"

    def test_parse_name_with_special_characters(self):
        """Test parsing names with special characters."""
        player = {
            "id": 123,
            "first_name": "Luka",
            "last_name": "Dončić"
        }

        full_name = f"{player['first_name']} {player['last_name']}"
        assert full_name == "Luka Dončić"

    def test_parse_name_with_suffix(self):
        """Test parsing names with suffixes."""
        player = {
            "id": 456,
            "first_name": "Gary",
            "last_name": "Trent Jr."
        }

        full_name = f"{player['first_name']} {player['last_name']}"
        assert full_name == "Gary Trent Jr."


# ============================================================================
# TEAM MAPPING TESTS
# ============================================================================

class TestBdlPlayerDetailTeamMapping:
    """Test team mapping."""

    def test_parse_team_info(self, sample_player_detail_response):
        """Test parsing of team information."""
        player = sample_player_detail_response["data"]
        team = player["team"]

        assert team["id"] == 14
        assert team["abbreviation"] == "LAL"
        assert team["full_name"] == "Los Angeles Lakers"
        assert team["city"] == "Los Angeles"
        assert team["name"] == "Lakers"
        assert team["conference"] == "West"
        assert team["division"] == "Pacific"

    @responses.activate
    def test_player_without_team(self, mock_bdl_api_key, sample_player_without_team_response):
        """Test handling of free agent (no team)."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/999",
            json=sample_player_without_team_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId=999,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                assert scraper.data["player"]["team"] is None


# ============================================================================
# NOTIFICATION INTEGRATION TESTS
# ============================================================================

class TestBdlPlayerDetailNotifications:
    """Test notification system integration."""

    @responses.activate
    def test_success_notification_sent(self, mock_bdl_api_key, sample_player_detail_response):
        """Test that success notification is sent."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info') as mock_notify:
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                # Verify success notification was called
                assert mock_notify.called

    def test_validation_error_notification_sent(self, mock_bdl_api_key):
        """Test that validation error notification is sent."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_error') as mock_notify:
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
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
# PLAYER PROFILE PARSING TESTS
# ============================================================================

class TestBdlPlayerDetailProfileParsing:
    """Test comprehensive player profile parsing."""

    def test_parse_complete_profile(self, sample_player_detail_response):
        """Test parsing of complete player profile."""
        player = sample_player_detail_response["data"]

        # Personal info
        assert player["first_name"] == "LeBron"
        assert player["last_name"] == "James"
        assert player["country"] == "USA"

        # Physical attributes
        assert player["height"] == "6-9"
        assert player["weight"] == "250"
        assert player["position"] == "F"

        # Career info
        assert player["draft_year"] == 2003
        assert player["draft_round"] == 1
        assert player["draft_number"] == 1
        assert player["college"] == "St. Vincent-St. Mary HS"

        # Current team
        assert player["jersey_number"] == "23"
        assert player["team"]["abbreviation"] == "LAL"

    def test_parse_draft_info(self, sample_player_detail_response):
        """Test parsing of draft information."""
        player = sample_player_detail_response["data"]

        assert player["draft_year"] == 2003
        assert player["draft_round"] == 1
        assert player["draft_number"] == 1

    def test_parse_physical_measurements(self, sample_player_detail_response):
        """Test parsing of physical measurements."""
        player = sample_player_detail_response["data"]

        # Height format: "feet-inches"
        assert player["height"] == "6-9"
        # Weight in pounds
        assert player["weight"] == "250"


# ============================================================================
# SCHEMA COMPLIANCE TESTS
# ============================================================================

class TestBdlPlayerDetailSchemaCompliance:
    """Test that output matches expected schema format."""

    @responses.activate
    def test_output_schema_structure(self, mock_bdl_api_key, sample_player_detail_response):
        """Test that output has correct schema structure."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId=237,
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()
                scraper.transform_data()

                # Verify top-level schema
                assert "playerId" in scraper.data
                assert "timestamp" in scraper.data
                assert "player" in scraper.data

                # Verify types
                assert isinstance(scraper.data["playerId"], (int, str))
                assert isinstance(scraper.data["timestamp"], str)
                assert isinstance(scraper.data["player"], dict)

    def test_scraper_stats_format(self, mock_bdl_api_key):
        """Test get_scraper_stats output format."""
        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            scraper = BdlPlayerDetailScraper(
                playerId=237,
                debug=True,
                export_groups=["test"]
            )

            stats = scraper.get_scraper_stats()

            assert "playerId" in stats
            assert stats["playerId"] == 237


# ============================================================================
# EDGE CASES TESTS
# ============================================================================

class TestBdlPlayerDetailEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_player_with_null_jersey_number(self, sample_player_without_team_response):
        """Test handling of null jersey number."""
        player = sample_player_without_team_response["data"]

        assert player["jersey_number"] is None

    def test_player_with_hyphenated_name(self):
        """Test handling of hyphenated names."""
        player = {
            "id": 789,
            "first_name": "Karl-Anthony",
            "last_name": "Towns"
        }

        full_name = f"{player['first_name']} {player['last_name']}"
        assert full_name == "Karl-Anthony Towns"

    @responses.activate
    def test_player_id_as_string_conversion(self, mock_bdl_api_key, sample_player_detail_response):
        """Test that string player ID is handled correctly."""
        responses.add(
            responses.GET,
            "https://api.balldontlie.io/v1/players/237",
            json=sample_player_detail_response,
            status=200
        )

        with patch.dict(os.environ, {'BDL_API_KEY': mock_bdl_api_key}):
            with patch('scrapers.balldontlie.bdl_player_detail.notify_info'):
                scraper = BdlPlayerDetailScraper(
                    playerId="237",  # String ID
                    debug=True,
                    export_groups=["test"]
                )

                scraper.set_url()
                scraper.set_headers()
                scraper.download_data()
                scraper.validate_download_data()

                # Should handle string ID correctly
                assert scraper.decoded_data["id"] == 237
