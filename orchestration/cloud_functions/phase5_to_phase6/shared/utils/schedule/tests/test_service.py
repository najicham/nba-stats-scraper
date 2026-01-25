# ============================================================================
# FILE: shared/utils/schedule/tests/test_service.py
# ============================================================================
"""Tests for NBA Schedule Service."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date

from shared.utils.schedule import NBAScheduleService, GameType, NBAGame


class TestNBAScheduleService:
    """Test schedule service functionality."""
    
    @pytest.fixture
    def mock_gcs_reader(self):
        """Create mock GCS reader."""
        with patch('shared.utils.schedule.service.ScheduleGCSReader') as mock:
            yield mock
    
    @pytest.fixture
    def mock_db_reader(self):
        """Create mock database reader."""
        with patch('shared.utils.schedule.service.ScheduleDatabaseReader') as mock:
            yield mock
    
    def test_initialization_database_mode(self, mock_gcs_reader, mock_db_reader):
        """Test service initializes with database mode by default."""
        service = NBAScheduleService()
        
        assert service.use_database is True
        assert service.gcs_reader is not None
        assert service.db_reader is not None
    
    def test_initialization_gcs_only_mode(self, mock_gcs_reader, mock_db_reader):
        """Test service initializes in GCS-only mode."""
        service = NBAScheduleService(use_database=False)
        
        assert service.use_database is False
        assert service.gcs_reader is not None
        assert service.db_reader is None
    
    def test_from_gcs_only_classmethod(self, mock_gcs_reader, mock_db_reader):
        """Test from_gcs_only creates GCS-only instance."""
        service = NBAScheduleService.from_gcs_only()
        
        assert service.use_database is False
        assert service.db_reader is None
    
    def test_team_name_mapping(self, mock_gcs_reader, mock_db_reader):
        """Test team name mapping works."""
        service = NBAScheduleService()
        
        assert service.get_team_full_name('LAL') == 'Los Angeles Lakers'
        assert service.get_team_full_name('GSW') == 'Golden State Warriors'
        assert service.get_team_full_name('XXX') is None
    
    def test_game_type_to_list_all(self, mock_gcs_reader, mock_db_reader):
        """Test game type conversion for ALL."""
        service = NBAScheduleService()
        result = service._game_type_to_list(GameType.ALL)
        assert result is None  # No filter
    
    def test_game_type_to_list_playoff_only(self, mock_gcs_reader, mock_db_reader):
        """Test game type conversion for PLAYOFF_ONLY."""
        service = NBAScheduleService()
        result = service._game_type_to_list(GameType.PLAYOFF_ONLY)
        assert result == ['playoff', 'play_in']
    
    def test_game_type_to_list_regular_only(self, mock_gcs_reader, mock_db_reader):
        """Test game type conversion for REGULAR_ONLY."""
        service = NBAScheduleService()
        result = service._game_type_to_list(GameType.REGULAR_ONLY)
        assert result == ['regular_season']
    
    def test_game_type_to_list_regular_playoff(self, mock_gcs_reader, mock_db_reader):
        """Test game type conversion for REGULAR_PLAYOFF."""
        service = NBAScheduleService()
        result = service._game_type_to_list(GameType.REGULAR_PLAYOFF)
        assert result == ['regular_season', 'playoff', 'play_in']
    
    def test_matches_game_type_all(self, mock_gcs_reader, mock_db_reader):
        """Test game type matching for ALL."""
        service = NBAScheduleService()
        game = Mock()
        game.game_type = 'regular_season'
        
        assert service._matches_game_type(game, GameType.ALL) is True
    
    def test_matches_game_type_playoff_only(self, mock_gcs_reader, mock_db_reader):
        """Test game type matching for PLAYOFF_ONLY."""
        service = NBAScheduleService()
        
        playoff_game = Mock()
        playoff_game.game_type = 'playoff'
        assert service._matches_game_type(playoff_game, GameType.PLAYOFF_ONLY) is True
        
        regular_game = Mock()
        regular_game.game_type = 'regular_season'
        assert service._matches_game_type(regular_game, GameType.PLAYOFF_ONLY) is False
    
    def test_get_season_for_date_october(self, mock_gcs_reader, mock_db_reader):
        """Test season determination for October date."""
        service = NBAScheduleService()
        test_date = date(2024, 10, 15)
        
        result = service._get_season_for_date(test_date)
        assert result == 2024  # Oct 2024 → 2024-25 season
    
    def test_get_season_for_date_june(self, mock_gcs_reader, mock_db_reader):
        """Test season determination for June date."""
        service = NBAScheduleService()
        test_date = date(2024, 6, 15)
        
        result = service._get_season_for_date(test_date)
        assert result == 2023  # June 2024 → 2023-24 season
    
    def test_clear_cache(self, mock_gcs_reader, mock_db_reader):
        """Test cache clearing delegates to GCS reader."""
        mock_gcs = Mock()
        mock_gcs_reader.return_value = mock_gcs
        
        service = NBAScheduleService()
        service.clear_cache()
        
        mock_gcs.clear_cache.assert_called_once()