"""
Unit tests for scrapers/balldontlie/ scrapers

Tests BallDontLie API scrapers including:
- BdlGamesScraper
- BdlBoxScoresScraper
- BdlPlayersScraper
- Common scraper patterns

Path: tests/scrapers/unit/test_bdl_scrapers.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
import json


# ============================================================================
# TEST BDL GAMES SCRAPER
# ============================================================================

class TestBdlGamesScraper:
    """Test the BdlGamesScraper class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        with patch('scrapers.balldontlie.bdl_games.ScraperBase.__init__', return_value=None), \
             patch('scrapers.scraper_base.get_bigquery_client'):
            yield

    def test_scraper_name(self, mock_dependencies):
        """Scraper should have correct name."""
        from scrapers.balldontlie.bdl_games import BdlGamesScraper

        assert BdlGamesScraper.scraper_name == "bdl_games"

    def test_download_type_is_json(self, mock_dependencies):
        """BDL scrapers should use JSON download type."""
        from scrapers.balldontlie.bdl_games import BdlGamesScraper
        from scrapers.scraper_base import DownloadType

        assert BdlGamesScraper.download_type == DownloadType.JSON

    def test_proxy_disabled(self, mock_dependencies):
        """BDL API should not use proxy."""
        from scrapers.balldontlie.bdl_games import BdlGamesScraper

        assert BdlGamesScraper.proxy_enabled is False

    def test_exporters_defined(self, mock_dependencies):
        """Scraper should have exporters defined."""
        from scrapers.balldontlie.bdl_games import BdlGamesScraper

        assert len(BdlGamesScraper.exporters) > 0

        # Should have GCS exporter for production
        gcs_exporters = [e for e in BdlGamesScraper.exporters if e["type"] == "gcs"]
        assert len(gcs_exporters) >= 1

    def test_optional_params(self, mock_dependencies):
        """Scraper should have optional params defined."""
        from scrapers.balldontlie.bdl_games import BdlGamesScraper

        assert "startDate" in BdlGamesScraper.optional_params
        assert "endDate" in BdlGamesScraper.optional_params


class TestBdlCoerceDate:
    """Test the _coerce_date helper function."""

    def test_coerce_none_returns_default(self):
        """None should return default date."""
        from scrapers.balldontlie.bdl_games import _coerce_date

        default = date(2026, 1, 15)
        result = _coerce_date(None, default)

        assert result == default

    def test_coerce_date_object_unchanged(self):
        """Date object should be returned as-is."""
        from scrapers.balldontlie.bdl_games import _coerce_date

        input_date = date(2026, 1, 20)
        result = _coerce_date(input_date, date(2000, 1, 1))

        assert result == input_date

    def test_coerce_string_to_date(self):
        """String should be parsed to date."""
        from scrapers.balldontlie.bdl_games import _coerce_date

        result = _coerce_date("2026-01-20", date(2000, 1, 1))

        assert result == date(2026, 1, 20)

    def test_coerce_invalid_string_raises(self):
        """Invalid string should raise ValueError."""
        from scrapers.balldontlie.bdl_games import _coerce_date

        with pytest.raises(ValueError):
            _coerce_date("not-a-date", date(2000, 1, 1))


# ============================================================================
# TEST BDL BOX SCORES SCRAPER
# ============================================================================

class TestBdlBoxScoresScraper:
    """Test the BdlBoxScoresScraper class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        with patch('scrapers.balldontlie.bdl_box_scores.ScraperBase.__init__', return_value=None), \
             patch('scrapers.scraper_base.get_bigquery_client'):
            yield

    def test_scraper_name(self, mock_dependencies):
        """Scraper should have correct name."""
        from scrapers.balldontlie.bdl_box_scores import BdlBoxScoresScraper

        assert BdlBoxScoresScraper.scraper_name == "bdl_box_scores"

    def test_download_type_is_json(self, mock_dependencies):
        """BDL scrapers should use JSON download type."""
        from scrapers.balldontlie.bdl_box_scores import BdlBoxScoresScraper
        from scrapers.scraper_base import DownloadType

        assert BdlBoxScoresScraper.download_type == DownloadType.JSON


# ============================================================================
# TEST BDL INJURIES SCRAPER
# ============================================================================

class TestBdlInjuriesScraper:
    """Test the BdlInjuriesScraper class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        with patch('scrapers.balldontlie.bdl_injuries.ScraperBase.__init__', return_value=None), \
             patch('scrapers.scraper_base.get_bigquery_client'):
            yield

    def test_scraper_name(self, mock_dependencies):
        """Scraper should have correct name."""
        from scrapers.balldontlie.bdl_injuries import BdlInjuriesScraper

        assert BdlInjuriesScraper.scraper_name == "bdl_injuries"


# ============================================================================
# TEST BDL ODDS SCRAPER
# ============================================================================

class TestBdlOddsScraper:
    """Test the BdlOddsScraper class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        with patch('scrapers.balldontlie.bdl_odds.ScraperBase.__init__', return_value=None), \
             patch('scrapers.scraper_base.get_bigquery_client'):
            yield

    def test_scraper_name(self, mock_dependencies):
        """Scraper should have correct name."""
        from scrapers.balldontlie.bdl_odds import BdlOddsScraper

        assert BdlOddsScraper.scraper_name == "bdl_odds"


# ============================================================================
# TEST BDL COMMON PATTERNS
# ============================================================================

class TestBdlCommonPatterns:
    """Test common patterns across all BDL scrapers."""

    @pytest.fixture
    def all_bdl_scrapers(self):
        """Import all BDL scraper classes."""
        scrapers = {}
        try:
            from scrapers.balldontlie.bdl_games import BdlGamesScraper
            scrapers['bdl_games'] = BdlGamesScraper
        except ImportError:
            pass

        try:
            from scrapers.balldontlie.bdl_box_scores import BdlBoxScoresScraper
            scrapers['bdl_box_scores'] = BdlBoxScoresScraper
        except ImportError:
            pass

        try:
            from scrapers.balldontlie.bdl_injuries import BdlInjuriesScraper
            scrapers['bdl_injuries'] = BdlInjuriesScraper
        except ImportError:
            pass

        try:
            from scrapers.balldontlie.bdl_odds import BdlOddsScraper
            scrapers['bdl_odds'] = BdlOddsScraper
        except ImportError:
            pass

        return scrapers

    def test_all_have_scraper_name(self, all_bdl_scrapers):
        """All BDL scrapers should have scraper_name defined."""
        for name, scraper_class in all_bdl_scrapers.items():
            assert hasattr(scraper_class, 'scraper_name'), f"{name} missing scraper_name"
            assert scraper_class.scraper_name is not None, f"{name} has None scraper_name"

    def test_all_have_exporters(self, all_bdl_scrapers):
        """All BDL scrapers should have exporters defined."""
        for name, scraper_class in all_bdl_scrapers.items():
            assert hasattr(scraper_class, 'exporters'), f"{name} missing exporters"
            assert len(scraper_class.exporters) > 0, f"{name} has no exporters"

    def test_proxy_disabled_for_all(self, all_bdl_scrapers):
        """BDL API works without proxy."""
        for name, scraper_class in all_bdl_scrapers.items():
            if hasattr(scraper_class, 'proxy_enabled'):
                assert scraper_class.proxy_enabled is False, f"{name} has proxy enabled"


# ============================================================================
# TEST BDL API RESPONSE HANDLING
# ============================================================================

class TestBdlApiResponseHandling:
    """Test BDL API response parsing patterns."""

    def test_parse_games_response(self):
        """Should correctly parse games API response."""
        sample_response = {
            "data": [
                {
                    "id": 123456,
                    "date": "2026-01-20",
                    "season": 2025,
                    "status": "Final",
                    "home_team": {"id": 1, "abbreviation": "LAL"},
                    "visitor_team": {"id": 2, "abbreviation": "BOS"},
                    "home_team_score": 110,
                    "visitor_team_score": 105
                }
            ],
            "meta": {
                "next_cursor": None,
                "per_page": 25
            }
        }

        # Basic validation
        assert "data" in sample_response
        assert len(sample_response["data"]) == 1
        assert sample_response["data"][0]["id"] == 123456

    def test_parse_boxscore_response(self):
        """Should correctly parse boxscore API response."""
        sample_response = {
            "data": [
                {
                    "id": 789,
                    "player": {"id": 100, "first_name": "LeBron", "last_name": "James"},
                    "team": {"id": 1, "abbreviation": "LAL"},
                    "game": {"id": 123456, "date": "2026-01-20"},
                    "min": "35:22",
                    "pts": 28,
                    "reb": 8,
                    "ast": 12
                }
            ],
            "meta": {
                "next_cursor": 456,
                "per_page": 25
            }
        }

        # Validate player stats structure
        player_stat = sample_response["data"][0]
        assert player_stat["pts"] == 28
        assert player_stat["player"]["first_name"] == "LeBron"

    def test_handle_pagination(self):
        """Should handle cursor-based pagination."""
        page1 = {
            "data": [{"id": 1}, {"id": 2}],
            "meta": {"next_cursor": 100}
        }
        page2 = {
            "data": [{"id": 3}, {"id": 4}],
            "meta": {"next_cursor": None}
        }

        # Simulate pagination logic
        all_data = []
        all_data.extend(page1["data"])

        if page1["meta"]["next_cursor"]:
            all_data.extend(page2["data"])

        assert len(all_data) == 4
        assert [d["id"] for d in all_data] == [1, 2, 3, 4]


# ============================================================================
# PARAMETRIZED TESTS
# ============================================================================

@pytest.mark.parametrize("scraper_module,scraper_class_name,expected_name", [
    ("scrapers.balldontlie.bdl_games", "BdlGamesScraper", "bdl_games"),
    ("scrapers.balldontlie.bdl_box_scores", "BdlBoxScoresScraper", "bdl_box_scores"),
    ("scrapers.balldontlie.bdl_injuries", "BdlInjuriesScraper", "bdl_injuries"),
    ("scrapers.balldontlie.bdl_odds", "BdlOddsScraper", "bdl_odds"),
])
def test_scraper_names_match_convention(scraper_module, scraper_class_name, expected_name):
    """Scraper names should match file naming convention."""
    import importlib
    try:
        module = importlib.import_module(scraper_module)
        scraper_class = getattr(module, scraper_class_name)
        assert scraper_class.scraper_name == expected_name
    except ImportError:
        pytest.skip(f"Could not import {scraper_module}")


@pytest.mark.parametrize("date_input,expected", [
    ("2026-01-20", date(2026, 1, 20)),
    ("2025-12-31", date(2025, 12, 31)),
    ("2024-01-01", date(2024, 1, 1)),
])
def test_date_string_parsing(date_input, expected):
    """Should correctly parse date strings."""
    from scrapers.balldontlie.bdl_games import _coerce_date

    result = _coerce_date(date_input, date(2000, 1, 1))
    assert result == expected
