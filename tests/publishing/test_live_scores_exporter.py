"""
Unit tests for LiveScoresExporter

Tests the date filtering logic added to prevent date mismatch bugs.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone


class TestLiveScoresExporter:
    """Tests for LiveScoresExporter._transform_games date filtering."""

    def test_filters_games_from_different_date(self):
        """Games from a different date should be filtered out."""
        # Mock the exporter
        from data_processors.publishing.live_scores_exporter import LiveScoresExporter

        exporter = LiveScoresExporter()
        exporter._player_lookup_cache = {}
        exporter._player_name_cache = {}

        # Simulate BDL API returning games from yesterday
        live_data = [
            {
                "id": "12345",
                "date": "2025-12-27",  # Yesterday
                "status": "Final",
                "period": 4,
                "home_team": {"abbreviation": "LAL", "players": []},
                "visitor_team": {"abbreviation": "GSW", "players": []},
                "home_team_score": 110,
                "visitor_team_score": 105
            },
            {
                "id": "12346",
                "date": "2025-12-28",  # Today
                "status": "In Progress",
                "period": 2,
                "home_team": {"abbreviation": "BOS", "players": []},
                "visitor_team": {"abbreviation": "NYK", "players": []},
                "home_team_score": 55,
                "visitor_team_score": 52
            }
        ]

        target_date = "2025-12-28"
        result = exporter._transform_games(live_data, target_date)

        # Should only include today's game
        assert len(result) == 1
        assert result[0]["game_id"] == "12346"
        assert result[0]["home_team"] == "BOS"

    def test_includes_games_matching_target_date(self):
        """Games matching target date should be included."""
        from data_processors.publishing.live_scores_exporter import LiveScoresExporter

        exporter = LiveScoresExporter()
        exporter._player_lookup_cache = {}
        exporter._player_name_cache = {}

        live_data = [
            {
                "id": "12346",
                "date": "2025-12-28",
                "status": "In Progress",
                "period": 3,
                "home_team": {"abbreviation": "MIA", "players": []},
                "visitor_team": {"abbreviation": "CHI", "players": []},
                "home_team_score": 78,
                "visitor_team_score": 80
            },
            {
                "id": "12347",
                "date": "2025-12-28",
                "status": "Final",
                "period": 4,
                "home_team": {"abbreviation": "DEN", "players": []},
                "visitor_team": {"abbreviation": "PHX", "players": []},
                "home_team_score": 115,
                "visitor_team_score": 112
            }
        ]

        target_date = "2025-12-28"
        result = exporter._transform_games(live_data, target_date)

        # Should include both today's games
        assert len(result) == 2

    def test_handles_missing_date_field(self):
        """Games without date field should still be processed (legacy behavior)."""
        from data_processors.publishing.live_scores_exporter import LiveScoresExporter

        exporter = LiveScoresExporter()
        exporter._player_lookup_cache = {}
        exporter._player_name_cache = {}

        live_data = [
            {
                "id": "12346",
                # No date field
                "status": "In Progress",
                "period": 2,
                "home_team": {"abbreviation": "LAC", "players": []},
                "visitor_team": {"abbreviation": "SAC", "players": []},
                "home_team_score": 45,
                "visitor_team_score": 48
            }
        ]

        target_date = "2025-12-28"
        result = exporter._transform_games(live_data, target_date)

        # Should include game without date (can't filter it)
        assert len(result) == 1

    def test_status_determination(self):
        """Test correct status determination from BDL data."""
        from data_processors.publishing.live_scores_exporter import LiveScoresExporter

        exporter = LiveScoresExporter()
        exporter._player_lookup_cache = {}
        exporter._player_name_cache = {}

        live_data = [
            {
                "id": "1",
                "date": "2025-12-28",
                "status": "Final",
                "period": 4,
                "home_team": {"abbreviation": "LAL", "players": []},
                "visitor_team": {"abbreviation": "GSW", "players": []},
                "home_team_score": 110,
                "visitor_team_score": 105
            },
            {
                "id": "2",
                "date": "2025-12-28",
                "status": "3rd Qtr",
                "period": 3,
                "home_team": {"abbreviation": "BOS", "players": []},
                "visitor_team": {"abbreviation": "NYK", "players": []},
                "home_team_score": 78,
                "visitor_team_score": 75
            },
            {
                "id": "3",
                "date": "2025-12-28",
                "status": "",
                "period": 0,
                "home_team": {"abbreviation": "MIA", "players": []},
                "visitor_team": {"abbreviation": "CHI", "players": []},
                "home_team_score": 0,
                "visitor_team_score": 0
            }
        ]

        target_date = "2025-12-28"
        result = exporter._transform_games(live_data, target_date)

        # Check statuses
        statuses = {g["game_id"]: g["status"] for g in result}
        assert statuses["1"] == "final"
        assert statuses["2"] == "in_progress"
        assert statuses["3"] == "scheduled"


class TestDSTHandling:
    """Tests for DST-aware date handling."""

    def test_get_today_date_uses_zoneinfo(self):
        """get_today_date should use zoneinfo for DST-aware timezone."""
        from orchestration.cloud_functions.live_export.main import get_today_date

        result = get_today_date()

        # Should return a date string in YYYY-MM-DD format
        assert len(result) == 10
        assert result.count("-") == 2

        # Should match current ET date
        from zoneinfo import ZoneInfo
        expected = datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')
        assert result == expected

    @patch('orchestration.cloud_functions.live_export.main.datetime')
    def test_dst_transition_handling(self, mock_datetime):
        """Test that DST transitions are handled correctly."""
        from zoneinfo import ZoneInfo

        # Simulate March 10, 2024 2:30 AM ET (DST transition day)
        # At 2:00 AM, clocks spring forward to 3:00 AM
        et = ZoneInfo('America/New_York')

        # Mock the current time
        mock_now = datetime(2024, 3, 10, 7, 30, 0, tzinfo=timezone.utc)  # 2:30 AM ET
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        # The function should handle this correctly
        # (Test would need refactoring to work with the actual implementation)
        pass  # Placeholder for more thorough DST testing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
