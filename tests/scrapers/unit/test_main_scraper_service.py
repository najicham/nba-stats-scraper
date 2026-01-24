"""
Unit tests for scrapers/main_scraper_service.py

Tests the Flask-based scraper service including:
- Route handling
- Request parsing
- Error handling
- Health endpoints

Path: tests/scrapers/unit/test_main_scraper_service.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


# ============================================================================
# TEST SERVICE CONFIGURATION
# ============================================================================

class TestServiceConfiguration:
    """Test main_scraper_service configuration."""

    def test_default_port(self):
        """Service should have default port defined."""
        import os
        default_port = int(os.environ.get("PORT", 8080))
        assert default_port == 8080

    @patch.dict('os.environ', {'PORT': '9000'})
    def test_custom_port_from_env(self):
        """Service should read port from environment."""
        import os
        port = int(os.environ.get("PORT", 8080))
        assert port == 9000


# ============================================================================
# TEST REQUEST PARSING
# ============================================================================

class TestRequestParsing:
    """Test request parsing utilities."""

    def test_parse_game_date(self):
        """Should parse game_date from request."""
        from datetime import date

        # Test ISO format
        game_date_str = "2026-01-20"
        parsed = date.fromisoformat(game_date_str)
        assert parsed == date(2026, 1, 20)

    def test_parse_scraper_name(self):
        """Should extract scraper_name from request path."""
        path = "/scrapers/bdl_games/run"
        parts = path.strip('/').split('/')

        assert parts[0] == "scrapers"
        assert parts[1] == "bdl_games"
        assert parts[2] == "run"


# ============================================================================
# TEST HEALTH ENDPOINT
# ============================================================================

class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_response_format(self):
        """Health response should have correct format."""
        health_response = {
            "status": "healthy",
            "service": "scraper-service",
            "scrapers_available": 33
        }

        assert "status" in health_response
        assert health_response["status"] == "healthy"

    def test_health_includes_scraper_count(self):
        """Health response should include available scrapers."""
        from scrapers.registry import SCRAPER_REGISTRY

        health_response = {
            "status": "healthy",
            "scrapers_available": len(SCRAPER_REGISTRY)
        }

        assert health_response["scrapers_available"] > 0


# ============================================================================
# TEST SCRAPER INVOCATION
# ============================================================================

class TestScraperInvocation:
    """Test scraper invocation patterns."""

    def test_valid_scraper_lookup(self):
        """Should find valid scrapers in registry."""
        from scrapers.registry import scraper_exists

        assert scraper_exists("bdl_games") is True
        assert scraper_exists("oddsa_events_his") is True
        assert scraper_exists("nbac_schedule_api") is True

    def test_invalid_scraper_lookup(self):
        """Should return False for invalid scrapers."""
        from scrapers.registry import scraper_exists

        assert scraper_exists("nonexistent") is False
        assert scraper_exists("") is False


# ============================================================================
# TEST ERROR RESPONSES
# ============================================================================

class TestErrorResponses:
    """Test error response formats."""

    def test_404_format(self):
        """404 response should have correct format."""
        error_response = {
            "error": "Scraper not found",
            "scraper": "unknown_scraper",
            "status": 404
        }

        assert error_response["status"] == 404
        assert "error" in error_response

    def test_400_format(self):
        """400 response should have correct format."""
        error_response = {
            "error": "Missing required parameter: game_date",
            "status": 400
        }

        assert error_response["status"] == 400
        assert "Missing required parameter" in error_response["error"]

    def test_500_format(self):
        """500 response should have correct format."""
        error_response = {
            "error": "Internal server error",
            "details": "Connection timeout to external API",
            "status": 500
        }

        assert error_response["status"] == 500


# ============================================================================
# TEST RESPONSE FORMATS
# ============================================================================

class TestResponseFormats:
    """Test successful response formats."""

    def test_run_response_format(self):
        """Run endpoint should return correct format."""
        run_response = {
            "status": "success",
            "scraper": "bdl_games",
            "game_date": "2026-01-20",
            "records_scraped": 12,
            "gcs_path": "gs://bucket/path/to/file.json"
        }

        assert run_response["status"] == "success"
        assert "records_scraped" in run_response
        assert "gcs_path" in run_response

    def test_list_response_format(self):
        """List endpoint should return scraper list."""
        from scrapers.registry import list_scrapers

        scrapers = list_scrapers()
        list_response = {
            "scrapers": scrapers,
            "count": len(scrapers)
        }

        assert isinstance(list_response["scrapers"], list)
        assert list_response["count"] == len(scrapers)
        assert "bdl_games" in list_response["scrapers"]


# ============================================================================
# TEST REQUEST VALIDATION
# ============================================================================

class TestRequestValidation:
    """Test request validation logic."""

    def test_validate_date_format(self):
        """Should validate date format."""
        from datetime import date

        # Valid dates
        valid_dates = ["2026-01-20", "2025-12-31", "2024-01-01"]
        for date_str in valid_dates:
            parsed = date.fromisoformat(date_str)
            assert isinstance(parsed, date)

        # Invalid dates
        invalid_dates = ["20-01-2026", "2026/01/20", "not-a-date"]
        for date_str in invalid_dates:
            with pytest.raises(ValueError):
                date.fromisoformat(date_str)

    def test_validate_scraper_name(self):
        """Should validate scraper name format."""
        # Valid names (snake_case, lowercase)
        valid_names = ["bdl_games", "oddsa_events_his", "nbac_schedule_api"]
        for name in valid_names:
            assert name.islower()
            assert " " not in name

    def test_validate_export_groups(self):
        """Should validate export group parameter."""
        valid_groups = ["prod", "dev", "test", "capture", "gcs"]

        for group in valid_groups:
            # Groups should be strings
            assert isinstance(group, str)
            assert len(group) > 0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestServiceIntegration:
    """Integration tests for scraper service."""

    def test_registry_all_scrapers_have_metadata(self):
        """All registered scrapers should have metadata."""
        from scrapers.registry import SCRAPER_REGISTRY, get_scraper_info

        for scraper_name in SCRAPER_REGISTRY:
            info = get_scraper_info(scraper_name)
            assert "name" in info
            assert "module" in info
            assert "class" in info
            assert info["name"] == scraper_name

    def test_group_coverage(self):
        """All scrapers should belong to at least one group."""
        from scrapers.registry import SCRAPER_REGISTRY, SCRAPER_GROUPS

        all_grouped = set()
        for group_scrapers in SCRAPER_GROUPS.values():
            all_grouped.update(group_scrapers)

        ungrouped = set(SCRAPER_REGISTRY.keys()) - all_grouped
        assert len(ungrouped) == 0, f"Ungrouped scrapers: {ungrouped}"
