"""Tests for MLB Supplemental Data Loader."""

import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from predictions.mlb.supplemental_loader import (
    load_supplemental_by_pitcher,
    _load_umpire_k_rates,
    _load_weather,
    _load_schedule,
    K_ZONE_TENDENCY_MAP,
    DEFAULT_K_RATE,
)


class TestKZoneTendencyMap:
    """Test umpire K-zone tendency → K-rate mapping."""

    def test_wide_zone_highest_k_rate(self):
        assert K_ZONE_TENDENCY_MAP['wide'] == 0.245

    def test_tight_zone_lowest_k_rate(self):
        assert K_ZONE_TENDENCY_MAP['tight'] == 0.190

    def test_average_matches_default(self):
        assert K_ZONE_TENDENCY_MAP['average'] == DEFAULT_K_RATE

    def test_all_values_between_0_and_1(self):
        for tendency, rate in K_ZONE_TENDENCY_MAP.items():
            assert 0 < rate < 1, f"{tendency} k_rate {rate} out of range"


class TestLoadUmpireKRates:
    """Test umpire K-rate loading from BQ."""

    def test_returns_empty_on_no_data(self):
        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []
        result = _load_umpire_k_rates(mock_client, date(2026, 6, 15), 'test-project')
        assert result == {}

    def test_maps_k_zone_tendency_to_k_rate(self):
        mock_client = MagicMock()
        mock_row = {
            'game_pk': 12345,
            'umpire_name': 'Joe West',
            'k_zone_tendency': 'wide',
            'accuracy': 0.94,
        }
        mock_client.query.return_value.result.return_value = [mock_row]
        result = _load_umpire_k_rates(mock_client, date(2026, 6, 15), 'test-project')
        assert 12345 in result
        assert result[12345]['umpire_k_rate'] == 0.245
        assert result[12345]['umpire_name'] == 'Joe West'

    def test_unknown_tendency_uses_default(self):
        mock_client = MagicMock()
        mock_row = {
            'game_pk': 99999,
            'umpire_name': 'Unknown Ump',
            'k_zone_tendency': None,
            'accuracy': None,
        }
        mock_client.query.return_value.result.return_value = [mock_row]
        result = _load_umpire_k_rates(mock_client, date(2026, 6, 15), 'test-project')
        assert result[99999]['umpire_k_rate'] == DEFAULT_K_RATE

    def test_handles_query_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("BQ timeout")
        result = _load_umpire_k_rates(mock_client, date(2026, 6, 15), 'test-project')
        assert result == {}


class TestLoadWeather:
    """Test weather loading from BQ."""

    def test_returns_empty_on_no_data(self):
        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []
        result = _load_weather(mock_client, date(2026, 6, 15), 'test-project')
        assert result == {}

    def test_maps_weather_by_team(self):
        mock_client = MagicMock()
        mock_row = {
            'team_abbr': 'NYY',
            'temperature_f': 68.5,
            'is_dome': False,
            'k_weather_factor': 1.01,
            'humidity_pct': 72,
            'wind_speed_mph': 8.0,
        }
        mock_client.query.return_value.result.return_value = [mock_row]
        result = _load_weather(mock_client, date(2026, 6, 15), 'test-project')
        assert 'NYY' in result
        assert result['NYY']['temperature_f'] == 68.5
        assert result['NYY']['is_dome'] is False

    def test_handles_dome_stadium(self):
        mock_client = MagicMock()
        mock_row = {
            'team_abbr': 'HOU',
            'temperature_f': 72.0,
            'is_dome': True,
            'k_weather_factor': 1.0,
            'humidity_pct': 50,
            'wind_speed_mph': 0.0,
        }
        mock_client.query.return_value.result.return_value = [mock_row]
        result = _load_weather(mock_client, date(2026, 6, 15), 'test-project')
        assert result['HOU']['is_dome'] is True

    def test_handles_query_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("BQ timeout")
        result = _load_weather(mock_client, date(2026, 6, 15), 'test-project')
        assert result == {}


class TestLoadSchedule:
    """Test schedule loading from BQ."""

    def test_returns_empty_on_no_games(self):
        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []
        result = _load_schedule(mock_client, date(2026, 6, 15), 'test-project')
        assert result == []

    def test_returns_game_with_pitchers(self):
        mock_client = MagicMock()
        mock_row = {
            'game_pk': 12345,
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS',
            'home_probable_pitcher_name': 'Gerrit Cole',
            'away_probable_pitcher_name': 'Chris Sale',
            'home_pitcher_lookup': 'gerritcole',
            'away_pitcher_lookup': 'chrissale',
        }
        mock_client.query.return_value.result.return_value = [mock_row]
        result = _load_schedule(mock_client, date(2026, 6, 15), 'test-project')
        assert len(result) == 1
        assert result[0]['game_pk'] == 12345

    def test_handles_query_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("BQ timeout")
        result = _load_schedule(mock_client, date(2026, 6, 15), 'test-project')
        assert result == []


class TestLoadSupplementalByPitcher:
    """Integration tests for the main supplemental loader function."""

    @patch('predictions.mlb.supplemental_loader._load_schedule')
    @patch('predictions.mlb.supplemental_loader._load_weather')
    @patch('predictions.mlb.supplemental_loader._load_umpire_k_rates')
    @patch('predictions.mlb.supplemental_loader.bigquery')
    def test_full_pipeline_maps_game_data_to_pitchers(
        self, mock_bq, mock_umpire, mock_weather, mock_schedule
    ):
        """Verify game-level data maps correctly to pitcher-level."""
        mock_umpire.return_value = {
            12345: {'umpire_name': 'Joe West', 'umpire_k_rate': 0.245}
        }
        mock_weather.return_value = {
            'NYY': {'temperature_f': 68.5, 'is_dome': False, 'k_weather_factor': 1.01}
        }
        mock_schedule.return_value = [
            {
                'game_pk': 12345,
                'home_team_abbr': 'NYY',
                'away_team_abbr': 'BOS',
                'home_pitcher_lookup': 'gerritcole',
                'away_pitcher_lookup': 'chrissale',
            }
        ]

        result = load_supplemental_by_pitcher(date(2026, 6, 15))

        # Both pitchers should have same game-level data
        assert 'gerritcole' in result
        assert 'chrissale' in result
        assert result['gerritcole']['umpire_k_rate'] == 0.245
        assert result['gerritcole']['temperature'] == 68.5
        assert result['chrissale']['umpire_k_rate'] == 0.245

    @patch('predictions.mlb.supplemental_loader._load_schedule')
    @patch('predictions.mlb.supplemental_loader._load_weather')
    @patch('predictions.mlb.supplemental_loader._load_umpire_k_rates')
    @patch('predictions.mlb.supplemental_loader.bigquery')
    def test_returns_empty_when_no_schedule(
        self, mock_bq, mock_umpire, mock_weather, mock_schedule
    ):
        mock_schedule.return_value = []
        result = load_supplemental_by_pitcher(date(2026, 1, 15))
        assert result == {}

    @patch('predictions.mlb.supplemental_loader._load_schedule')
    @patch('predictions.mlb.supplemental_loader._load_weather')
    @patch('predictions.mlb.supplemental_loader._load_umpire_k_rates')
    @patch('predictions.mlb.supplemental_loader.bigquery')
    def test_partial_data_still_returns_available_fields(
        self, mock_bq, mock_umpire, mock_weather, mock_schedule
    ):
        """If umpire data missing but weather exists, return weather only."""
        mock_umpire.return_value = {}  # No umpire data
        mock_weather.return_value = {
            'NYY': {'temperature_f': 45.0, 'is_dome': False, 'k_weather_factor': 1.02}
        }
        mock_schedule.return_value = [
            {
                'game_pk': 12345,
                'home_team_abbr': 'NYY',
                'away_team_abbr': 'BOS',
                'home_pitcher_lookup': 'gerritcole',
                'away_pitcher_lookup': 'chrissale',
            }
        ]

        result = load_supplemental_by_pitcher(date(2026, 4, 1))
        assert 'gerritcole' in result
        assert 'umpire_k_rate' not in result['gerritcole']
        assert result['gerritcole']['temperature'] == 45.0

    @patch('predictions.mlb.supplemental_loader._load_schedule')
    @patch('predictions.mlb.supplemental_loader._load_weather')
    @patch('predictions.mlb.supplemental_loader._load_umpire_k_rates')
    @patch('predictions.mlb.supplemental_loader.bigquery')
    def test_pitcher_lookups_filter(
        self, mock_bq, mock_umpire, mock_weather, mock_schedule
    ):
        """Only return data for requested pitchers."""
        mock_umpire.return_value = {
            12345: {'umpire_name': 'Joe West', 'umpire_k_rate': 0.245}
        }
        mock_weather.return_value = {
            'NYY': {'temperature_f': 68.5, 'is_dome': False, 'k_weather_factor': 1.01}
        }
        mock_schedule.return_value = [
            {
                'game_pk': 12345,
                'home_team_abbr': 'NYY',
                'away_team_abbr': 'BOS',
                'home_pitcher_lookup': 'gerritcole',
                'away_pitcher_lookup': 'chrissale',
            }
        ]

        result = load_supplemental_by_pitcher(
            date(2026, 6, 15),
            pitcher_lookups=['gerritcole']
        )
        assert 'gerritcole' in result
        assert 'chrissale' not in result
