# ============================================================================
# FILE: shared/utils/schedule/tests/test_models.py
# ============================================================================
"""Tests for schedule data models."""

import pytest
from shared.utils.schedule.models import NBAGame, GameType


class TestGameType:
    """Test GameType enum."""
    
    def test_game_type_values(self):
        """Test that all game types are defined."""
        assert GameType.ALL.value == "all"
        assert GameType.REGULAR_PLAYOFF.value == "regular_playoff"
        assert GameType.PLAYOFF_ONLY.value == "playoff_only"
        assert GameType.REGULAR_ONLY.value == "regular_only"


class TestNBAGame:
    """Test NBAGame dataclass."""
    
    @pytest.fixture
    def sample_game(self):
        """Create a sample game for testing."""
        return NBAGame(
            game_id="0022400123",
            game_code="20240115/LALGSW",
            game_date="2024-01-15",
            away_team="LAL",
            home_team="GSW",
            away_team_full="Los Angeles Lakers",
            home_team_full="Golden State Warriors",
            game_status=3,
            completed=True,
            game_label="Regular Season",
            game_sub_label="",
            week_name="Week 12",
            week_number=12,
            game_type="regular_season",
            commence_time="2024-01-15T23:00:00Z",
            season_year=2024
        )
    
    def test_matchup_property(self, sample_game):
        """Test matchup property generates correct format."""
        assert sample_game.matchup == "LAL@GSW"
    
    def test_is_playoff_regular_season(self, sample_game):
        """Test is_playoff returns False for regular season."""
        assert sample_game.is_playoff is False
    
    def test_is_playoff_playoff_game(self, sample_game):
        """Test is_playoff returns True for playoff game."""
        sample_game.game_type = "playoff"
        assert sample_game.is_playoff is True
    
    def test_is_playoff_play_in(self, sample_game):
        """Test is_playoff returns True for play-in game."""
        sample_game.game_type = "play_in"
        assert sample_game.is_playoff is True
    
    def test_is_regular_season(self, sample_game):
        """Test is_regular_season returns True for regular season."""
        assert sample_game.is_regular_season is True
    
    def test_is_regular_season_playoff(self, sample_game):
        """Test is_regular_season returns False for playoff."""
        sample_game.game_type = "playoff"
        assert sample_game.is_regular_season is False
    
    def test_to_dict(self, sample_game):
        """Test to_dict conversion."""
        result = sample_game.to_dict()
        
        assert isinstance(result, dict)
        assert result['game_id'] == "0022400123"
        assert result['matchup'] == "LAL@GSW"
        assert result['game_date'] == "2024-01-15"
        assert result['away_team'] == "LAL"
        assert result['home_team'] == "GSW"
        assert result['completed'] is True
