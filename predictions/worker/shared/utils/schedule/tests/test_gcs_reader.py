# ============================================================================
# FILE: shared/utils/schedule/tests/test_gcs_reader.py
# ============================================================================
"""Tests for GCS schedule reader."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from shared.utils.schedule.gcs_reader import ScheduleGCSReader
from shared.utils.schedule.models import NBAGame


class TestScheduleGCSReader:
    """Test GCS reader functionality."""
    
    @pytest.fixture
    def reader(self):
        """Create a GCS reader instance."""
        with patch('shared.utils.schedule.gcs_reader.storage.Client'):
            return ScheduleGCSReader(bucket_name='test-bucket')
    
    def test_initialization(self, reader):
        """Test reader initializes correctly."""
        assert reader.bucket_name == 'test-bucket'
        assert isinstance(reader._schedule_cache, dict)
        assert isinstance(reader._games_cache, dict)
    
    def test_nba_teams_mapping(self, reader):
        """Test NBA teams mapping is complete."""
        # Should have all 30 NBA teams
        assert len(reader.NBA_TEAMS) == 30
        assert reader.NBA_TEAMS['LAL'] == 'Los Angeles Lakers'
        assert reader.NBA_TEAMS['GSW'] == 'Golden State Warriors'
        assert reader.NBA_TEAMS['BOS'] == 'Boston Celtics'
    
    def test_exhibition_teams_defined(self, reader):
        """Test exhibition teams are defined."""
        assert 'WST' in reader.EXHIBITION_TEAMS  # All-Star West
        assert 'EST' in reader.EXHIBITION_TEAMS  # All-Star East
        assert 'RMD' in reader.EXHIBITION_TEAMS  # Real Madrid
    
    def test_extract_date_from_entry_mm_dd_yyyy(self, reader):
        """Test date extraction from MM/DD/YYYY format."""
        entry = {'gameDate': '01/15/2024 00:00:00'}
        result = reader._extract_date_from_entry(entry)
        assert result == '2024-01-15'
    
    def test_extract_date_from_entry_iso(self, reader):
        """Test date extraction from ISO format."""
        entry = {'gameDate': '2024-01-15T00:00:00Z'}
        result = reader._extract_date_from_entry(entry)
        assert result == '2024-01-15'
    
    def test_classify_game_type_regular_season(self, reader):
        """Test regular season game classification."""
        result = reader._classify_game_type(
            game_label="Regular Season",
            game_sub_label="",
            week_name="Week 12",
            week_number=12
        )
        assert result == "regular_season"
    
    def test_classify_game_type_playoff(self, reader):
        """Test playoff game classification."""
        result = reader._classify_game_type(
            game_label="First Round - Game 1",
            game_sub_label="",
            week_name="Playoffs",
            week_number=20
        )
        assert result == "playoff"
    
    def test_classify_game_type_play_in(self, reader):
        """Test play-in game classification."""
        result = reader._classify_game_type(
            game_label="Play-In Tournament",
            game_sub_label="",
            week_name="Play-In",
            week_number=19
        )
        assert result == "play_in"
    
    def test_classify_game_type_all_star(self, reader):
        """Test All-Star game classification."""
        result = reader._classify_game_type(
            game_label="All-Star Game",
            game_sub_label="",
            week_name="All-Star",
            week_number=18
        )
        assert result == "all_star_special"
    
    def test_classify_game_type_preseason(self, reader):
        """Test preseason game classification."""
        result = reader._classify_game_type(
            game_label="",
            game_sub_label="",
            week_name="Preseason",
            week_number=0
        )
        assert result == "preseason"
    
    def test_clear_cache(self, reader):
        """Test cache clearing."""
        reader._schedule_cache[2024] = {'data': 'test'}
        reader._games_cache[2024] = [Mock()]
        
        reader.clear_cache()
        
        assert len(reader._schedule_cache) == 0
        assert len(reader._games_cache) == 0