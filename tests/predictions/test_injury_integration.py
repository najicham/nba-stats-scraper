# tests/predictions/test_injury_integration.py

"""
Tests for Injury Integration Module

Tests cover:
- Player injury status checking
- Multi-source data loading (NBA.com + BDL)
- Teammate impact calculation
- Usage projection adjustments
- Filtering of injured players
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List

# Import the modules we're testing
from predictions.shared.injury_integration import (
    InjuryIntegration,
    PlayerInjuryInfo,
    TeammateImpact,
    InjuryFilterResult,
    get_injury_integration,
    check_player_injury,
    get_teammate_impact,
    filter_out_injured
)
from predictions.shared.injury_filter import (
    InjuryFilter,
    InjuryStatus,
    TeammateImpact as FilterTeammateImpact,
    get_injury_filter,
    check_injury_status
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Create a mock BigQuery client"""
    with patch('predictions.shared.injury_integration.bigquery.Client') as mock:
        yield mock


@pytest.fixture
def sample_injury_data() -> Dict[str, PlayerInjuryInfo]:
    """Sample injury data for testing"""
    test_date = date(2026, 1, 23)
    return {
        'anthonydavis': PlayerInjuryInfo(
            player_lookup='anthonydavis',
            status='out',
            reason='Left knee; injury recovery',
            reason_category='injury',
            team_abbr='LAL',
            game_date=test_date,
            source='nba_com',
            confidence=0.95,
            report_hour=16
        ),
        'dangelorussell': PlayerInjuryInfo(
            player_lookup='dangelorussell',
            status='questionable',
            reason='Back; soreness',
            reason_category='injury',
            team_abbr='LAL',
            game_date=test_date,
            source='nba_com',
            confidence=0.9,
            report_hour=16
        ),
        'austinreaves': PlayerInjuryInfo(
            player_lookup='austinreaves',
            status='probable',
            reason='Ankle; sprain',
            reason_category='injury',
            team_abbr='LAL',
            game_date=test_date,
            source='nba_com',
            confidence=0.92,
            report_hour=14
        ),
    }


@pytest.fixture
def integration_with_mock_data(sample_injury_data):
    """Create InjuryIntegration with pre-populated cache"""
    integration = InjuryIntegration(project_id="test-project")
    test_date = date(2026, 1, 23)
    integration._injury_cache[test_date] = sample_injury_data
    return integration


# =============================================================================
# PLAYER INJURY INFO TESTS
# =============================================================================

class TestPlayerInjuryInfo:
    """Tests for PlayerInjuryInfo dataclass"""

    def test_should_skip_for_out_status(self):
        """Player with OUT status should be skipped"""
        info = PlayerInjuryInfo(
            player_lookup='test',
            status='out',
            reason='Injury',
            reason_category='injury',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            source='nba_com',
            confidence=0.9,
            report_hour=16
        )
        assert info.should_skip is True
        assert info.has_warning is False

    def test_has_warning_for_questionable(self):
        """Player with QUESTIONABLE status should have warning"""
        info = PlayerInjuryInfo(
            player_lookup='test',
            status='questionable',
            reason='Injury',
            reason_category='injury',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            source='nba_com',
            confidence=0.9,
            report_hour=16
        )
        assert info.should_skip is False
        assert info.has_warning is True

    def test_has_warning_for_doubtful(self):
        """Player with DOUBTFUL status should have warning"""
        info = PlayerInjuryInfo(
            player_lookup='test',
            status='doubtful',
            reason='Injury',
            reason_category='injury',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            source='nba_com',
            confidence=0.9,
            report_hour=16
        )
        assert info.should_skip is False
        assert info.has_warning is True

    def test_no_flags_for_probable(self):
        """Player with PROBABLE status should have no flags"""
        info = PlayerInjuryInfo(
            player_lookup='test',
            status='probable',
            reason='Minor issue',
            reason_category='injury',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            source='nba_com',
            confidence=0.9,
            report_hour=16
        )
        assert info.should_skip is False
        assert info.has_warning is False

    def test_is_risky_property(self):
        """is_risky should be True for out, doubtful, questionable"""
        for status in ['out', 'doubtful', 'questionable']:
            info = PlayerInjuryInfo(
                player_lookup='test',
                status=status,
                reason='Injury',
                reason_category='injury',
                team_abbr='LAL',
                game_date=date(2026, 1, 23),
                source='nba_com',
                confidence=0.9,
                report_hour=16
            )
            assert info.is_risky is True

        for status in ['probable', 'available']:
            info = PlayerInjuryInfo(
                player_lookup='test',
                status=status,
                reason='Minor',
                reason_category='injury',
                team_abbr='LAL',
                game_date=date(2026, 1, 23),
                source='nba_com',
                confidence=0.9,
                report_hour=16
            )
            assert info.is_risky is False


# =============================================================================
# INJURY INTEGRATION TESTS
# =============================================================================

class TestInjuryIntegration:
    """Tests for InjuryIntegration class"""

    def test_check_player_from_cache(self, integration_with_mock_data):
        """Should return cached injury info"""
        test_date = date(2026, 1, 23)
        result = integration_with_mock_data.check_player('anthonydavis', test_date)

        assert result.status == 'out'
        assert result.should_skip is True
        assert result.team_abbr == 'LAL'

    def test_check_player_not_injured(self, integration_with_mock_data):
        """Should return available status for player not in injury list"""
        test_date = date(2026, 1, 23)
        result = integration_with_mock_data.check_player('lebronjames', test_date)

        assert result.status == 'available'
        assert result.should_skip is False
        assert result.has_warning is False

    def test_check_players_batch(self, integration_with_mock_data):
        """Should return injury info for multiple players"""
        test_date = date(2026, 1, 23)
        players = ['anthonydavis', 'dangelorussell', 'lebronjames']

        result = integration_with_mock_data.check_players_batch(players, test_date)

        assert len(result) == 3
        assert result['anthonydavis'].status == 'out'
        assert result['dangelorussell'].status == 'questionable'
        assert result['lebronjames'].status == 'available'

    def test_filter_injured_players(self, integration_with_mock_data):
        """Should correctly filter out injured players"""
        test_date = date(2026, 1, 23)
        players = ['anthonydavis', 'dangelorussell', 'austinreaves', 'lebronjames']

        result = integration_with_mock_data.filter_injured_players(players, test_date)

        assert result.players_checked == 4
        assert result.players_skipped == 1  # anthonydavis (OUT)
        assert result.players_warned == 1   # dangelorussell (QUESTIONABLE)
        assert result.players_ok == 2       # austinreaves (PROBABLE), lebronjames (not injured)
        assert 'anthonydavis' in result.skipped_players
        assert 'dangelorussell' in result.warned_players

    def test_filter_injured_with_skip_doubtful(self, integration_with_mock_data):
        """Should skip DOUBTFUL players when flag is set"""
        test_date = date(2026, 1, 23)
        # Add a doubtful player
        integration_with_mock_data._injury_cache[test_date]['jadenjackson'] = PlayerInjuryInfo(
            player_lookup='jadenjackson',
            status='doubtful',
            reason='Illness',
            reason_category='illness',
            team_abbr='LAL',
            game_date=test_date,
            source='nba_com',
            confidence=0.9,
            report_hour=16
        )

        players = ['anthonydavis', 'jadenjackson', 'lebronjames']
        result = integration_with_mock_data.filter_injured_players(
            players, test_date, skip_doubtful=True
        )

        assert result.players_skipped == 2  # Both OUT and DOUBTFUL


# =============================================================================
# TEAMMATE IMPACT TESTS
# =============================================================================

class TestTeammateImpact:
    """Tests for teammate impact calculation"""

    def test_teammate_impact_has_significant_impact(self):
        """Impact should be significant when starters are out"""
        impact = TeammateImpact(
            player_lookup='lebronjames',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            out_teammates=['anthonydavis'],
            out_starters=['anthonydavis'],
            out_star_players=['anthonydavis'],
            usage_boost_factor=1.15,
            opportunity_score=40.0
        )

        assert impact.has_significant_impact is True
        assert impact.total_injured == 1

    def test_teammate_impact_no_significant_when_bench_out(self):
        """Impact should not be significant when only bench players are out"""
        impact = TeammateImpact(
            player_lookup='lebronjames',
            team_abbr='LAL',
            game_date=date(2026, 1, 23),
            out_teammates=['benchplayer1'],
            out_starters=[],
            out_star_players=[],
            usage_boost_factor=1.02,
            opportunity_score=5.0
        )

        assert impact.has_significant_impact is False

    def test_calculate_teammate_impact_with_mock(self, integration_with_mock_data):
        """Should calculate correct impact when teammate is out"""
        test_date = date(2026, 1, 23)

        # Mock the helper methods to avoid BigQuery calls
        integration_with_mock_data._is_starter = Mock(return_value=True)
        integration_with_mock_data._is_star_player = Mock(return_value=True)
        integration_with_mock_data._get_player_usage = Mock(return_value=0.25)

        result = integration_with_mock_data.calculate_teammate_impact(
            'lebronjames', 'LAL', test_date
        )

        assert 'anthonydavis' in result.out_teammates
        assert result.usage_boost_factor >= 1.0


# =============================================================================
# USAGE ADJUSTMENT TESTS
# =============================================================================

class TestUsageAdjustments:
    """Tests for usage and points projection adjustments"""

    def test_adjust_usage_no_impact(self, integration_with_mock_data):
        """Should return base usage when no significant injuries"""
        test_date = date(2026, 1, 23)
        # Clear injury cache to test no-impact scenario
        integration_with_mock_data._injury_cache[test_date] = {}

        adjusted, confidence, reason = integration_with_mock_data.adjust_usage_projection(
            'lebronjames', 0.28, 'GSW', test_date  # Different team - no LAL injuries
        )

        assert adjusted == 0.28  # No change
        assert confidence >= 0.8
        assert 'no_significant' in reason

    def test_adjust_points_capped_boost(self, integration_with_mock_data):
        """Points adjustment should be capped at reasonable levels"""
        test_date = date(2026, 1, 23)

        # Add high opportunity scenario
        integration_with_mock_data._is_starter = Mock(return_value=True)
        integration_with_mock_data._is_star_player = Mock(return_value=True)
        integration_with_mock_data._get_player_usage = Mock(return_value=0.28)

        adjusted, confidence, reason = integration_with_mock_data.adjust_points_projection(
            'lebronjames', 25.0, 'LAL', test_date
        )

        # Should have some boost (AD is out)
        assert adjusted >= 25.0
        # But not unreasonably high
        assert adjusted <= 35.0


# =============================================================================
# INJURY FILTER COMPATIBILITY TESTS
# =============================================================================

class TestInjuryFilterCompatibility:
    """Tests for backward compatibility with InjuryFilter"""

    def test_injury_filter_check_player(self, mock_bq_client):
        """InjuryFilter should still work for basic checks"""
        filter_instance = InjuryFilter(project_id="test-project")

        # Mock the query result
        mock_result = Mock()
        mock_result.result.return_value = []  # No injury data
        filter_instance._client = Mock()
        filter_instance._client.query.return_value = mock_result

        result = filter_instance.check_player('testplayer', date(2026, 1, 23))

        assert result.should_skip is False
        assert result.has_warning is False
        assert "No injury report entry" in result.message

    def test_injury_filter_teammate_impact_method(self):
        """InjuryFilter should have get_teammate_impact method (v2.0)"""
        filter_instance = InjuryFilter(project_id="test-project")

        # This should not raise - method should exist
        assert hasattr(filter_instance, 'get_teammate_impact')
        assert hasattr(filter_instance, 'adjust_usage_for_injuries')
        assert hasattr(filter_instance, 'adjust_points_for_injuries')

    def test_teammate_impact_dataclass_from_filter(self):
        """TeammateImpact from injury_filter should have correct defaults"""
        impact = FilterTeammateImpact(
            player_lookup='test',
            team_abbr='LAL',
            game_date=date(2026, 1, 23)
        )

        assert impact.usage_boost_factor == 1.0
        assert impact.minutes_boost_factor == 1.0
        assert impact.opportunity_score == 0.0
        assert impact.has_significant_impact is False
        assert impact.total_injured == 0


# =============================================================================
# CACHE TESTS
# =============================================================================

class TestCaching:
    """Tests for caching behavior"""

    def test_clear_cache_all(self, integration_with_mock_data):
        """Should clear all cached data"""
        integration_with_mock_data._player_usage_cache['test'] = 0.25
        integration_with_mock_data._player_starter_cache['test_LAL'] = True

        integration_with_mock_data.clear_cache()

        assert len(integration_with_mock_data._injury_cache) == 0
        assert len(integration_with_mock_data._player_usage_cache) == 0
        assert len(integration_with_mock_data._player_starter_cache) == 0

    def test_clear_cache_single_date(self, integration_with_mock_data):
        """Should clear cache for specific date only"""
        test_date = date(2026, 1, 23)
        other_date = date(2026, 1, 24)

        # Add data for another date
        integration_with_mock_data._injury_cache[other_date] = {'player': Mock()}

        integration_with_mock_data.clear_cache(game_date=test_date)

        assert test_date not in integration_with_mock_data._injury_cache
        assert other_date in integration_with_mock_data._injury_cache

    def test_get_stats(self, integration_with_mock_data):
        """Should return correct statistics"""
        integration_with_mock_data._player_usage_cache['p1'] = 0.25
        integration_with_mock_data._player_usage_cache['p2'] = 0.28

        stats = integration_with_mock_data.get_stats()

        assert stats['cached_dates'] == 1
        assert stats['cached_players_usage'] == 2


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions"""

    def test_get_injury_integration_singleton(self):
        """Should return same instance on multiple calls"""
        # Clear any existing singleton
        import predictions.shared.injury_integration as module
        module._default_integration = None

        integration1 = get_injury_integration()
        integration2 = get_injury_integration()

        assert integration1 is integration2

    def test_get_injury_filter_singleton(self):
        """Should return same instance on multiple calls"""
        import predictions.shared.injury_filter as module
        module._default_filter = None

        filter1 = get_injury_filter()
        filter2 = get_injury_filter()

        assert filter1 is filter2


# =============================================================================
# STAR PLAYER DETECTION TESTS
# =============================================================================

class TestStarPlayerDetection:
    """Tests for star player detection"""

    def test_known_star_players(self):
        """Should correctly identify known star players"""
        integration = InjuryIntegration(project_id="test-project")

        # Known stars (normalized)
        assert integration._is_star_player('lebron-james') is True
        assert integration._is_star_player('stephencurry') is True
        assert integration._is_star_player('kevin-durant') is True

    def test_non_star_players(self):
        """Should correctly identify non-star players"""
        integration = InjuryIntegration(project_id="test-project")

        # Not in the star list
        assert integration._is_star_player('benchplayer') is False
        assert integration._is_star_player('unknown-player') is False
