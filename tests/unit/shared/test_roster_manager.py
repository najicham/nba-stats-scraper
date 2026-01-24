#!/usr/bin/env python3
"""
Unit tests for RosterManager functionality.

Tests:
- RosterChangeTracker
- ActiveRosterCalculator
- RosterManager high-level interface
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock

from shared.utils.roster_manager import (
    RosterManager,
    RosterChangeTracker,
    ActiveRosterCalculator,
    RosterChange,
    PlayerAvailability,
    TeamRoster,
    TransactionType,
    AvailabilityStatus,
    get_roster_manager,
    get_active_roster,
    check_player_availability,
    get_roster_changes,
)


class TestTransactionTypeEnum:
    """Tests for TransactionType enum."""

    def test_transaction_types_exist(self):
        """Verify all expected transaction types exist."""
        assert TransactionType.TRADE.value == "trade"
        assert TransactionType.SIGNING.value == "signing"
        assert TransactionType.WAIVER.value == "waiver"
        assert TransactionType.TWO_WAY_CONTRACT.value == "two_way"
        assert TransactionType.TEN_DAY_CONTRACT.value == "10_day"
        assert TransactionType.G_LEAGUE_ASSIGNMENT.value == "g_league_assignment"
        assert TransactionType.G_LEAGUE_RECALL.value == "g_league_recall"
        assert TransactionType.RELEASE.value == "release"
        assert TransactionType.RETIREMENT.value == "retirement"
        assert TransactionType.SUSPENSION.value == "suspension"
        assert TransactionType.OTHER.value == "other"


class TestAvailabilityStatusEnum:
    """Tests for AvailabilityStatus enum."""

    def test_availability_statuses_exist(self):
        """Verify all expected availability statuses exist."""
        assert AvailabilityStatus.AVAILABLE.value == "available"
        assert AvailabilityStatus.QUESTIONABLE.value == "questionable"
        assert AvailabilityStatus.DOUBTFUL.value == "doubtful"
        assert AvailabilityStatus.OUT.value == "out"
        assert AvailabilityStatus.NOT_ON_ROSTER.value == "not_on_roster"
        assert AvailabilityStatus.SUSPENDED.value == "suspended"
        assert AvailabilityStatus.G_LEAGUE.value == "g_league"
        assert AvailabilityStatus.UNKNOWN.value == "unknown"


class TestRosterChangeDataclass:
    """Tests for RosterChange dataclass."""

    def test_roster_change_creation(self):
        """Test creating a roster change."""
        change = RosterChange(
            player_lookup="lebron-james",
            player_full_name="LeBron James",
            team_abbr="LAL",
            transaction_type=TransactionType.SIGNING,
            transaction_date=date(2026, 1, 15),
            description="Signed contract extension",
        )

        assert change.player_lookup == "lebron-james"
        assert change.player_full_name == "LeBron James"
        assert change.team_abbr == "LAL"
        assert change.transaction_type == TransactionType.SIGNING
        assert change.from_team is None
        assert change.to_team is None

    def test_roster_change_with_trade_details(self):
        """Test creating a trade roster change."""
        change = RosterChange(
            player_lookup="pascal-siakam",
            player_full_name="Pascal Siakam",
            team_abbr="IND",
            transaction_type=TransactionType.TRADE,
            transaction_date=date(2026, 1, 10),
            description="Traded from TOR to IND",
            from_team="TOR",
            to_team="IND",
        )

        assert change.transaction_type == TransactionType.TRADE
        assert change.from_team == "TOR"
        assert change.to_team == "IND"


class TestPlayerAvailabilityDataclass:
    """Tests for PlayerAvailability dataclass."""

    def test_available_player(self):
        """Test creating availability for available player."""
        avail = PlayerAvailability(
            player_lookup="stephen-curry",
            team_abbr="GSW",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.AVAILABLE,
            is_on_roster=True,
            message="Available",
        )

        assert avail.status == AvailabilityStatus.AVAILABLE
        assert avail.is_on_roster is True
        assert avail.injury_status is None

    def test_injured_player(self):
        """Test creating availability for injured player."""
        avail = PlayerAvailability(
            player_lookup="kawhi-leonard",
            team_abbr="LAC",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.OUT,
            is_on_roster=True,
            injury_status="out",
            injury_reason="Knee management",
            message="OUT: Knee management",
        )

        assert avail.status == AvailabilityStatus.OUT
        assert avail.injury_status == "out"
        assert "Knee" in avail.injury_reason


class TestTeamRosterDataclass:
    """Tests for TeamRoster dataclass."""

    def test_team_roster_creation(self):
        """Test creating a team roster."""
        roster = TeamRoster(
            team_abbr="BOS",
            roster_date=date(2026, 1, 23),
            season_year=2025,
            players=[
                {"player_lookup": "jayson-tatum", "is_active": True},
                {"player_lookup": "jaylen-brown", "is_active": True},
                {"player_lookup": "kristaps-porzingis", "is_active": False},
            ],
            active_count=2,
            injured_count=1,
            g_league_count=0,
            two_way_count=0,
        )

        assert roster.team_abbr == "BOS"
        assert len(roster.players) == 3
        assert roster.active_count == 2
        assert roster.injured_count == 1


class TestRosterChangeTracker:
    """Tests for RosterChangeTracker."""

    @pytest.fixture
    def tracker(self):
        """Create tracker with mocked client."""
        tracker = RosterChangeTracker()
        tracker._client = Mock()
        return tracker

    def test_classify_trade(self, tracker):
        """Test classifying a trade transaction."""
        result = tracker._classify_transaction("Trade", "Traded to LAL from BOS")
        assert result == TransactionType.TRADE

    def test_classify_signing(self, tracker):
        """Test classifying a signing transaction."""
        result = tracker._classify_transaction("Signed", "Signed to 10-day contract")
        assert result == TransactionType.SIGNING

    def test_classify_waiver(self, tracker):
        """Test classifying a waiver transaction."""
        result = tracker._classify_transaction("Waived", "Waived by team")
        assert result == TransactionType.WAIVER

    def test_classify_g_league_assignment(self, tracker):
        """Test classifying a G-League assignment."""
        result = tracker._classify_transaction("Other", "Assigned to G League affiliate")
        assert result == TransactionType.G_LEAGUE_ASSIGNMENT

    def test_classify_g_league_recall(self, tracker):
        """Test classifying a G-League recall."""
        result = tracker._classify_transaction("Other", "Recalled from G League")
        assert result == TransactionType.G_LEAGUE_RECALL

    def test_parse_trade_details_to_from(self, tracker):
        """Test parsing trade from/to teams."""
        from_team, to_team = tracker._parse_trade_details("Traded to LAL from BOS")
        assert from_team == "BOS"
        assert to_team == "LAL"

    def test_parse_trade_details_from_only(self, tracker):
        """Test parsing trade with only from team."""
        from_team, to_team = tracker._parse_trade_details("Acquired from PHI")
        assert from_team == "PHI"
        assert to_team is None

    def test_parse_trade_details_to_only(self, tracker):
        """Test parsing trade with only to team."""
        from_team, to_team = tracker._parse_trade_details("Sent to MIA")
        assert from_team is None
        assert to_team == "MIA"


class TestActiveRosterCalculator:
    """Tests for ActiveRosterCalculator."""

    @pytest.fixture
    def calculator(self):
        """Create calculator with mocked client."""
        calc = ActiveRosterCalculator()
        calc._client = Mock()
        return calc

    def test_is_player_active_healthy(self, calculator):
        """Test active status for healthy player."""
        result = calculator._is_player_active("healthy", "Active Roster")
        assert result is True

    def test_is_player_active_out(self, calculator):
        """Test active status for out player."""
        result = calculator._is_player_active("out", "Active Roster")
        assert result is False

    def test_is_player_active_questionable_included(self, calculator):
        """Test questionable player with include flag."""
        result = calculator._is_player_active("questionable", "Active Roster", include_questionable=True)
        assert result is True

    def test_is_player_active_questionable_excluded(self, calculator):
        """Test questionable player without include flag."""
        result = calculator._is_player_active("questionable", "Active Roster", include_questionable=False)
        assert result is False

    def test_is_player_active_g_league(self, calculator):
        """Test active status for G-League assigned player."""
        result = calculator._is_player_active("healthy", "G League - Austin Spurs")
        assert result is False

    def test_is_player_active_suspended(self, calculator):
        """Test active status for suspended player."""
        result = calculator._is_player_active("healthy", "Suspended")
        assert result is False

    def test_calculate_season_year_october(self, calculator):
        """Test season year calculation for October."""
        result = calculator._calculate_season_year(date(2025, 10, 15))
        assert result == 2025

    def test_calculate_season_year_january(self, calculator):
        """Test season year calculation for January."""
        result = calculator._calculate_season_year(date(2026, 1, 15))
        assert result == 2025


class TestRosterManager:
    """Tests for RosterManager high-level interface."""

    @pytest.fixture
    def manager(self):
        """Create manager with mocked components."""
        manager = RosterManager()
        manager.change_tracker._client = Mock()
        manager.roster_calculator._client = Mock()
        return manager

    def test_manager_initialization(self, manager):
        """Test manager initializes with components."""
        assert manager.change_tracker is not None
        assert manager.roster_calculator is not None
        assert manager._availability_cache == {}

    def test_should_skip_out_player(self, manager):
        """Test skip decision for OUT player."""
        # Mock the check_player_availability to return OUT status
        mock_avail = PlayerAvailability(
            player_lookup="test-player",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.OUT,
            is_on_roster=True,
            injury_status="out",
            injury_reason="Knee injury",
            message="OUT: Knee injury",
        )
        manager._availability_cache["test-player_2026-01-23_LAL"] = mock_avail

        should_skip, reason = manager.should_skip_prediction(
            "test-player", date(2026, 1, 23), "LAL"
        )

        assert should_skip is True
        assert "OUT" in reason or "SKIP" in reason

    def test_should_not_skip_available_player(self, manager):
        """Test skip decision for available player."""
        mock_avail = PlayerAvailability(
            player_lookup="test-player",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.AVAILABLE,
            is_on_roster=True,
            message="Available",
        )
        manager._availability_cache["test-player_2026-01-23_LAL"] = mock_avail

        should_skip, reason = manager.should_skip_prediction(
            "test-player", date(2026, 1, 23), "LAL"
        )

        assert should_skip is False
        assert "OK" in reason

    def test_should_warn_questionable_player(self, manager):
        """Test skip decision for questionable player."""
        mock_avail = PlayerAvailability(
            player_lookup="test-player",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.QUESTIONABLE,
            is_on_roster=True,
            injury_status="questionable",
            message="QUESTIONABLE: Ankle soreness",
        )
        manager._availability_cache["test-player_2026-01-23_LAL"] = mock_avail

        should_skip, reason = manager.should_skip_prediction(
            "test-player", date(2026, 1, 23), "LAL"
        )

        assert should_skip is False
        assert "WARNING" in reason

    def test_should_skip_g_league_player(self, manager):
        """Test skip decision for G-League assigned player."""
        mock_avail = PlayerAvailability(
            player_lookup="test-player",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.G_LEAGUE,
            is_on_roster=True,
            roster_status="G-League",
            message="On G-League assignment",
        )
        manager._availability_cache["test-player_2026-01-23_LAL"] = mock_avail

        should_skip, reason = manager.should_skip_prediction(
            "test-player", date(2026, 1, 23), "LAL"
        )

        assert should_skip is True
        assert "G-League" in reason or "SKIP" in reason

    def test_should_skip_not_on_roster(self, manager):
        """Test skip decision for player not on roster."""
        mock_avail = PlayerAvailability(
            player_lookup="test-player",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.NOT_ON_ROSTER,
            is_on_roster=False,
            message="Player not found on roster",
        )
        manager._availability_cache["test-player_2026-01-23_LAL"] = mock_avail

        should_skip, reason = manager.should_skip_prediction(
            "test-player", date(2026, 1, 23), "LAL"
        )

        assert should_skip is True
        assert "roster" in reason.lower() or "SKIP" in reason

    def test_clear_cache(self, manager):
        """Test cache clearing."""
        manager._availability_cache["test"] = "value"
        manager.clear_cache()
        assert manager._availability_cache == {}

    def test_get_stats_empty(self, manager):
        """Test stats with empty cache."""
        stats = manager.get_stats()
        assert stats["cached_checks"] == 0

    def test_get_stats_with_data(self, manager):
        """Test stats with cached data."""
        manager._availability_cache["p1_2026-01-23_LAL"] = PlayerAvailability(
            player_lookup="p1",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.AVAILABLE,
            is_on_roster=True,
            message="OK",
        )
        manager._availability_cache["p2_2026-01-23_LAL"] = PlayerAvailability(
            player_lookup="p2",
            team_abbr="LAL",
            game_date=date(2026, 1, 23),
            status=AvailabilityStatus.OUT,
            is_on_roster=True,
            message="OUT",
        )

        stats = manager.get_stats()
        assert stats["cached_checks"] == 2
        assert stats["available"] == 1
        assert stats["out"] == 1


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_roster_manager_singleton(self):
        """Test that get_roster_manager returns singleton."""
        # Clear any existing singleton
        import shared.utils.roster_manager as rm
        rm._default_manager = None

        manager1 = get_roster_manager()
        manager2 = get_roster_manager()

        assert manager1 is manager2

    def test_convenience_functions_exist(self):
        """Test that convenience functions are accessible."""
        assert callable(get_active_roster)
        assert callable(check_player_availability)
        assert callable(get_roster_changes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
