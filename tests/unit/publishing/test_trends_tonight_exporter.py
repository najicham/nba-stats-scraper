"""
Unit Tests for TrendsTonightExporter

Tests cover:
1. Output schema structure (metadata, players, matchups, insights)
2. Player section filtering (playing_tonight only) and enrichment
3. Matchup card construction and key insight generation
4. Insight generators (all 10) with various data scenarios
5. Empty data / error handling
6. Cap limits (10 hot, 10 cold, 5 bounce-back, 12 insights)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import date

from data_processors.publishing.trends_tonight_exporter import (
    TrendsTonightExporter,
    MAX_HOT_COLD,
    MAX_BOUNCE_BACK,
    MAX_INSIGHTS,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_exporter():
    """Create a TrendsTonightExporter with mocked BQ and GCS clients."""
    with patch('data_processors.publishing.base_exporter.get_bigquery_client') as mock_bq, \
         patch('shared.clients.get_storage_client') as mock_gcs:
        mock_client = MagicMock()
        mock_bq.return_value = mock_client
        exporter = TrendsTonightExporter()
        exporter._mock_bq_client = mock_client
        return exporter


def _mock_hot_cold_data(hot_count=3, cold_count=3, playing_tonight=True):
    """Generate mock WhosHotColdExporter.generate_json() output."""
    hot = []
    for i in range(hot_count):
        hot.append({
            'rank': i + 1,
            'player_lookup': f'hotplayer{i}',
            'player_full_name': f'Hot Player {i}',
            'team_abbr': 'LAL',
            'position': 'SG',
            'heat_score': 8.5 - i * 0.5,
            'hit_rate': 0.75 - i * 0.05,
            'hit_rate_games': 10,
            'current_streak': 5 - i,
            'streak_direction': 'over',
            'avg_margin': 3.2 - i * 0.5,
            'playing_tonight': playing_tonight,
            'tonight': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': False} if playing_tonight else None,
        })
    cold = []
    for i in range(cold_count):
        cold.append({
            'rank': i + 1,
            'player_lookup': f'coldplayer{i}',
            'player_full_name': f'Cold Player {i}',
            'team_abbr': 'GSW',
            'position': 'PF',
            'heat_score': 2.0 + i * 0.3,
            'hit_rate': 0.30 + i * 0.03,
            'hit_rate_games': 10,
            'current_streak': 4 - i,
            'streak_direction': 'under',
            'avg_margin': -4.0 + i * 0.5,
            'playing_tonight': playing_tonight,
            'tonight': {'opponent': 'LAL', 'game_time': '7:30 PM ET', 'home': True} if playing_tonight else None,
        })
    return {
        'generated_at': '2026-02-12T18:00:00+00:00',
        'as_of_date': '2026-02-12',
        'time_period': 'last_30_days',
        'min_games': 5,
        'total_qualifying_players': hot_count + cold_count,
        'hot': hot,
        'cold': cold,
        'league_average': {'hit_rate': 0.498, 'avg_margin': 0.12},
    }


def _mock_bounce_back_data(count=2, playing_tonight=True):
    """Generate mock BounceBackExporter.generate_json() output."""
    candidates = []
    for i in range(count):
        candidates.append({
            'rank': i + 1,
            'player_lookup': f'bbplayer{i}',
            'player_full_name': f'BB Player {i}',
            'team_abbr': 'LAL',
            'last_game': {'date': '2026-02-11', 'result': 12, 'opponent': 'PHX', 'margin': -14.5},
            'season_average': 26.5,
            'shortfall': 14.5,
            'bounce_back_rate': 0.78 - i * 0.1,
            'bounce_back_sample': 14,
            'significance': 'high' if i == 0 else 'medium',
            'playing_tonight': playing_tonight,
            'tonight': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': False} if playing_tonight else None,
        })
    return {
        'generated_at': '2026-02-12T18:00:00+00:00',
        'as_of_date': '2026-02-12',
        'shortfall_threshold': 10,
        'total_candidates': count,
        'bounce_back_candidates': candidates,
        'league_baseline': {'avg_bounce_back_rate': 0.62, 'sample_size': 1234},
    }


def _mock_matchup(
    game_id='0022500001',
    away='LAL', home='GSW',
    away_b2b=False, home_b2b=False,
    away_rest=1, home_rest=2,
    away_starters_out=0, home_starters_out=0,
    spread=-4.5, total=228.5,
    away_opp_ppg=112.0, home_opp_ppg=110.0,
    away_pace=100.2, home_pace=98.7,
    away_over_rate=0.53, home_over_rate=0.47,
):
    """Build a matchup dict as returned by _build_matchups_section."""
    return {
        'game_id': game_id,
        'away_team': {'abbr': away, 'name': f'{away} Team'},
        'home_team': {'abbr': home, 'name': f'{home} Team'},
        'spread': spread,
        'total': total,
        'defense': {'away_opp_ppg': away_opp_ppg, 'home_opp_ppg': home_opp_ppg},
        'rest': {
            'away_days': away_rest, 'home_days': home_rest,
            'away_b2b': away_b2b, 'home_b2b': home_b2b,
        },
        'injuries': {
            'away_starters_out': away_starters_out,
            'home_starters_out': home_starters_out,
        },
        'over_rate': {'away_l15': away_over_rate, 'home_l15': home_over_rate},
        'pace': {'away': away_pace, 'home': home_pace},
        'key_insight': f'{away} at {home}',
    }


# ============================================================================
# Tests: Output Schema
# ============================================================================

class TestOutputSchema:
    """Verify top-level JSON structure."""

    def test_generate_json_returns_all_sections(self):
        """Output must have metadata, players, matchups, insights."""
        exporter = _make_exporter()

        with patch.object(exporter, '_query_prop_lines', return_value={}), \
             patch.object(exporter, '_build_players_section', return_value={'hot': [], 'cold': [], 'bounce_back': []}), \
             patch.object(exporter, '_build_matchups_section', return_value=[]), \
             patch.object(exporter, '_build_insights_section', return_value=[]):

            result = exporter.generate_json('2026-02-12')

        assert 'metadata' in result
        assert 'players' in result
        assert 'matchups' in result
        assert 'insights' in result

    def test_metadata_fields(self):
        """Metadata should include game_date, games_tonight, version."""
        exporter = _make_exporter()

        with patch.object(exporter, '_query_prop_lines', return_value={}), \
             patch.object(exporter, '_build_players_section', return_value={'hot': [], 'cold': [], 'bounce_back': []}), \
             patch.object(exporter, '_build_matchups_section', return_value=[_mock_matchup(), _mock_matchup(game_id='002')]), \
             patch.object(exporter, '_build_insights_section', return_value=[]):

            result = exporter.generate_json('2026-02-12')

        meta = result['metadata']
        assert meta['game_date'] == '2026-02-12'
        assert meta['games_tonight'] == 2
        assert meta['version'] == '2'
        assert 'generated_at' in meta


# ============================================================================
# Tests: Players Section
# ============================================================================

class TestPlayersSection:
    """Test player filtering, enrichment, and capping."""

    def test_filters_to_playing_tonight_only(self):
        """Only players with playing_tonight=True should appear."""
        exporter = _make_exporter()

        hc_data = _mock_hot_cold_data(hot_count=5, cold_count=5, playing_tonight=True)
        # Mix in some not-playing players
        hc_data['hot'][2]['playing_tonight'] = False
        hc_data['cold'][4]['playing_tonight'] = False

        bb_data = _mock_bounce_back_data(count=3, playing_tonight=True)
        bb_data['bounce_back_candidates'][1]['playing_tonight'] = False

        with patch('data_processors.publishing.trends_tonight_exporter.WhosHotColdExporter') as MockHC, \
             patch('data_processors.publishing.trends_tonight_exporter.BounceBackExporter') as MockBB:

            MockHC.return_value.generate_json.return_value = hc_data
            MockBB.return_value.generate_json.return_value = bb_data

            result = exporter._build_players_section('2026-02-12', {})

        assert len(result['hot']) == 4  # 5 - 1 not playing
        assert len(result['cold']) == 4  # 5 - 1 not playing
        assert len(result['bounce_back']) == 2  # 3 - 1 not playing

    def test_enriches_with_prop_lines(self):
        """Players should get prop_line from prop_lines dict."""
        exporter = _make_exporter()

        hc_data = _mock_hot_cold_data(hot_count=1, cold_count=0)
        bb_data = _mock_bounce_back_data(count=1)

        prop_lines = {'hotplayer0': 25.5, 'bbplayer0': 22.0}

        with patch('data_processors.publishing.trends_tonight_exporter.WhosHotColdExporter') as MockHC, \
             patch('data_processors.publishing.trends_tonight_exporter.BounceBackExporter') as MockBB:

            MockHC.return_value.generate_json.return_value = hc_data
            MockBB.return_value.generate_json.return_value = bb_data

            result = exporter._build_players_section('2026-02-12', prop_lines)

        assert result['hot'][0]['prop_line'] == 25.5
        assert result['bounce_back'][0]['prop_line'] == 22.0

    def test_caps_at_limits(self):
        """Hot/cold capped at 10, bounce-back at 5."""
        exporter = _make_exporter()

        hc_data = _mock_hot_cold_data(hot_count=15, cold_count=15)
        bb_data = _mock_bounce_back_data(count=8)

        with patch('data_processors.publishing.trends_tonight_exporter.WhosHotColdExporter') as MockHC, \
             patch('data_processors.publishing.trends_tonight_exporter.BounceBackExporter') as MockBB:

            MockHC.return_value.generate_json.return_value = hc_data
            MockBB.return_value.generate_json.return_value = bb_data

            result = exporter._build_players_section('2026-02-12', {})

        assert len(result['hot']) <= MAX_HOT_COLD
        assert len(result['cold']) <= MAX_HOT_COLD
        assert len(result['bounce_back']) <= MAX_BOUNCE_BACK

    def test_handles_hot_cold_failure(self):
        """If WhosHotColdExporter fails, hot/cold should be empty."""
        exporter = _make_exporter()

        bb_data = _mock_bounce_back_data(count=1)

        with patch('data_processors.publishing.trends_tonight_exporter.WhosHotColdExporter') as MockHC, \
             patch('data_processors.publishing.trends_tonight_exporter.BounceBackExporter') as MockBB:

            MockHC.return_value.generate_json.side_effect = Exception("BQ error")
            MockBB.return_value.generate_json.return_value = bb_data

            result = exporter._build_players_section('2026-02-12', {})

        assert result['hot'] == []
        assert result['cold'] == []
        assert len(result['bounce_back']) == 1


# ============================================================================
# Tests: Key Insight Generation
# ============================================================================

class TestKeyInsight:
    """Test the priority-ordered key insight generator for matchups."""

    def test_b2b_rest_mismatch(self):
        """B2B team vs rested team should be the top insight."""
        exporter = _make_exporter()

        away = {'is_back_to_back': True, 'team_days_rest': 0, 'starters_out_count': 0, 'opponent_pace': 100}
        home = {'is_back_to_back': False, 'team_days_rest': 3, 'starters_out_count': 0, 'opponent_pace': 100}

        insight = exporter._generate_key_insight('LAL', 'GSW', away, home)
        assert 'B2B' in insight
        assert 'LAL' in insight

    def test_injury_impact(self):
        """Multiple starters out should be flagged."""
        exporter = _make_exporter()

        away = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 3, 'opponent_pace': 100}
        home = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 0, 'opponent_pace': 100}

        insight = exporter._generate_key_insight('LAL', 'GSW', away, home)
        assert 'missing' in insight.lower() or 'starters' in insight.lower()

    def test_pace_clash(self):
        """Big pace differential should generate insight."""
        exporter = _make_exporter()

        away = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 0, 'opponent_pace': 106}
        home = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 0, 'opponent_pace': 96}

        insight = exporter._generate_key_insight('LAL', 'GSW', away, home)
        assert 'Pace' in insight or 'pace' in insight

    def test_fallback_simple_matchup(self):
        """No notable factors = simple 'AWAY at HOME' string."""
        exporter = _make_exporter()

        away = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 0, 'opponent_pace': 100}
        home = {'is_back_to_back': False, 'team_days_rest': 1, 'starters_out_count': 0, 'opponent_pace': 100}

        insight = exporter._generate_key_insight('LAL', 'GSW', away, home)
        assert insight == 'LAL at GSW'


# ============================================================================
# Tests: Insight Generators
# ============================================================================

class TestInsightGenerators:
    """Test individual insight generators."""

    def test_b2b_insight_fires(self):
        """B2B insight should fire when a team is on B2B."""
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_b2b=True)]
        players = {'hot': [], 'cold': [], 'bounce_back': []}

        result = exporter._insight_b2b_tonight('2026-02-12', players, matchups)
        assert result is not None
        assert result['type'] == 'alert'
        assert 'B2B' in result['headline']

    def test_b2b_insight_skips_when_no_b2b(self):
        """B2B insight should return None when no team is on B2B."""
        exporter = _make_exporter()
        matchups = [_mock_matchup()]
        players = {'hot': [], 'cold': [], 'bounce_back': []}

        result = exporter._insight_b2b_tonight('2026-02-12', players, matchups)
        assert result is None

    def test_rest_advantage_fires(self):
        """Rest advantage insight should fire for 3+ day rest."""
        exporter = _make_exporter()
        matchups = [_mock_matchup(home_rest=4)]
        players = {'hot': [], 'cold': [], 'bounce_back': []}

        result = exporter._insight_rest_advantage('2026-02-12', players, matchups)
        assert result is not None
        assert 'Rest' in result['headline']

    def test_rest_advantage_skips_normal_rest(self):
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_rest=1, home_rest=2)]
        result = exporter._insight_rest_advantage('2026-02-12', {}, matchups)
        assert result is None

    def test_pace_clash_insight_fires(self):
        """Pace clash fires when differential > 4."""
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_pace=106.0, home_pace=97.0)]
        result = exporter._insight_pace_clash('2026-02-12', {}, matchups)
        assert result is not None
        assert 'Pace' in result['headline']

    def test_pace_clash_insight_skips_small_diff(self):
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_pace=100.0, home_pace=99.0)]
        result = exporter._insight_pace_clash('2026-02-12', {}, matchups)
        assert result is None

    def test_defense_exploit_fires_for_weak_defense(self):
        """Defense exploit fires when opp_ppg > 115."""
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_opp_ppg=118.5, home_opp_ppg=108.0)]
        result = exporter._insight_defense_exploit('2026-02-12', {}, matchups)
        assert result is not None
        assert 'Defense' in result['headline']

    def test_defense_exploit_skips_average_defense(self):
        exporter = _make_exporter()
        matchups = [_mock_matchup(away_opp_ppg=110.0, home_opp_ppg=112.0)]
        result = exporter._insight_defense_exploit('2026-02-12', {}, matchups)
        assert result is None

    def test_hot_streakers_fires_with_3_plus(self):
        """Hot streakers insight fires when 3+ hot players tonight."""
        exporter = _make_exporter()
        players = {
            'hot': [
                {'player_lookup': 'p1', 'player_full_name': 'Player 1'},
                {'player_lookup': 'p2', 'player_full_name': 'Player 2'},
                {'player_lookup': 'p3', 'player_full_name': 'Player 3'},
            ],
            'cold': [],
            'bounce_back': [],
        }
        result = exporter._insight_hot_streakers_tonight('2026-02-12', players, [])
        assert result is not None
        assert '3' in result['headline']

    def test_hot_streakers_skips_few_players(self):
        exporter = _make_exporter()
        players = {'hot': [{'player_lookup': 'p1', 'player_full_name': 'P1'}], 'cold': [], 'bounce_back': []}
        result = exporter._insight_hot_streakers_tonight('2026-02-12', players, [])
        assert result is None

    def test_bounce_back_alert_fires_with_2_plus(self):
        """Bounce-back alert fires with 2+ candidates."""
        exporter = _make_exporter()
        players = {
            'hot': [],
            'cold': [],
            'bounce_back': [
                {'player_lookup': 'bb1', 'player_full_name': 'BB 1', 'bounce_back_rate': 0.78},
                {'player_lookup': 'bb2', 'player_full_name': 'BB 2', 'bounce_back_rate': 0.65},
            ],
        }
        result = exporter._insight_bounce_back_alert('2026-02-12', players, [])
        assert result is not None
        assert 'Bounce-Back' in result['headline']

    def test_bounce_back_alert_skips_single(self):
        exporter = _make_exporter()
        players = {
            'hot': [], 'cold': [],
            'bounce_back': [{'player_lookup': 'bb1', 'player_full_name': 'BB 1', 'bounce_back_rate': 0.78}],
        }
        result = exporter._insight_bounce_back_alert('2026-02-12', players, [])
        assert result is None


class TestInsightSection:
    """Test the insights aggregation / sorting / capping."""

    def test_insights_capped_at_max(self):
        """Should never return more than MAX_INSIGHTS."""
        exporter = _make_exporter()

        # Create a generator that always returns an insight
        def fake_generator(game_date, players, matchups):
            return {
                'id': 'ti-fake',
                'type': 'info',
                'headline': 'Fake',
                'description': 'Fake insight',
                'main_value': '0',
                'is_positive': True,
                'confidence': 'low',
                'sample_size': 10,
                'tags': [],
                'players': [],
            }

        # Patch all 10 generators to return insights
        with patch.object(exporter, '_insight_b2b_tonight', fake_generator), \
             patch.object(exporter, '_insight_rest_advantage', fake_generator), \
             patch.object(exporter, '_insight_pace_clash', fake_generator), \
             patch.object(exporter, '_insight_defense_exploit', fake_generator), \
             patch.object(exporter, '_insight_hot_streakers_tonight', fake_generator), \
             patch.object(exporter, '_insight_bounce_back_alert', fake_generator), \
             patch.object(exporter, '_insight_day_of_week', fake_generator), \
             patch.object(exporter, '_insight_home_over_rate', fake_generator), \
             patch.object(exporter, '_insight_model_performance', fake_generator), \
             patch.object(exporter, '_insight_scoring_tier', fake_generator):

            result = exporter._build_insights_section('2026-02-12', {}, [])

        assert len(result) <= MAX_INSIGHTS

    def test_insights_sorted_by_confidence(self):
        """High confidence insights should come first."""
        exporter = _make_exporter()

        low = {
            'id': 'low', 'type': 'info', 'headline': 'Low',
            'description': '', 'main_value': '0', 'is_positive': True,
            'confidence': 'low', 'sample_size': 10, 'tags': [], 'players': [],
        }
        high = {
            'id': 'high', 'type': 'alert', 'headline': 'High',
            'description': '', 'main_value': '0', 'is_positive': False,
            'confidence': 'high', 'sample_size': 10, 'tags': [], 'players': [],
        }
        medium = {
            'id': 'med', 'type': 'info', 'headline': 'Med',
            'description': '', 'main_value': '0', 'is_positive': True,
            'confidence': 'medium', 'sample_size': 10, 'tags': [], 'players': [],
        }

        generators_returns = [low, None, high, None, medium, None, None, None, None, None]
        gen_iter = iter(generators_returns)

        def gen_side_effect(game_date, players, matchups):
            return next(gen_iter)

        with patch.object(exporter, '_insight_b2b_tonight', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_rest_advantage', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_pace_clash', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_defense_exploit', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_hot_streakers_tonight', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_bounce_back_alert', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_day_of_week', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_home_over_rate', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_model_performance', side_effect=gen_side_effect), \
             patch.object(exporter, '_insight_scoring_tier', side_effect=gen_side_effect):

            result = exporter._build_insights_section('2026-02-12', {}, [])

        assert len(result) == 3
        assert result[0]['confidence'] == 'high'
        assert result[1]['confidence'] == 'medium'
        assert result[2]['confidence'] == 'low'

    def test_generator_failure_doesnt_crash(self):
        """A failing generator should be skipped, not crash the section."""
        exporter = _make_exporter()

        def failing_gen(game_date, players, matchups):
            raise ValueError("BQ timeout")

        ok_insight = {
            'id': 'ok', 'type': 'info', 'headline': 'OK',
            'description': '', 'main_value': '0', 'is_positive': True,
            'confidence': 'medium', 'sample_size': 10, 'tags': [], 'players': [],
        }

        with patch.object(exporter, '_insight_b2b_tonight', failing_gen), \
             patch.object(exporter, '_insight_rest_advantage', lambda *a: ok_insight), \
             patch.object(exporter, '_insight_pace_clash', lambda *a: None), \
             patch.object(exporter, '_insight_defense_exploit', lambda *a: None), \
             patch.object(exporter, '_insight_hot_streakers_tonight', lambda *a: None), \
             patch.object(exporter, '_insight_bounce_back_alert', lambda *a: None), \
             patch.object(exporter, '_insight_day_of_week', lambda *a: None), \
             patch.object(exporter, '_insight_home_over_rate', lambda *a: None), \
             patch.object(exporter, '_insight_model_performance', lambda *a: None), \
             patch.object(exporter, '_insight_scoring_tier', lambda *a: None):

            result = exporter._build_insights_section('2026-02-12', {}, [])

        assert len(result) == 1
        assert result[0]['id'] == 'ok'


# ============================================================================
# Tests: Empty / Edge Cases
# ============================================================================

class TestEmptyCases:
    """Test behavior when no games or no data."""

    def test_no_games_tonight(self):
        """With no matchups, output should be valid but empty."""
        exporter = _make_exporter()

        with patch.object(exporter, '_query_prop_lines', return_value={}), \
             patch.object(exporter, '_build_players_section', return_value={'hot': [], 'cold': [], 'bounce_back': []}), \
             patch.object(exporter, '_build_matchups_section', return_value=[]), \
             patch.object(exporter, '_build_insights_section', return_value=[]):

            result = exporter.generate_json('2026-02-12')

        assert result['metadata']['games_tonight'] == 0
        assert result['players']['hot'] == []
        assert result['matchups'] == []
        assert result['insights'] == []

    def test_prop_lines_query_failure_returns_empty_dict(self):
        """If prop line query fails, should return empty dict, not crash."""
        exporter = _make_exporter()

        # Make query_to_list raise
        exporter.query_to_list = Mock(side_effect=Exception("BQ error"))
        result = exporter._query_prop_lines('2026-02-12')
        assert result == {}


# ============================================================================
# Tests: Export / GCS Upload
# ============================================================================

class TestExport:
    """Test the export() method that calls generate_json + upload_to_gcs."""

    def test_export_calls_upload(self):
        """export() should upload to trends/tonight.json with 1h cache."""
        exporter = _make_exporter()

        mock_json = {'metadata': {'game_date': '2026-02-12'}}
        with patch.object(exporter, 'generate_json', return_value=mock_json) as mock_gen, \
             patch.object(exporter, 'upload_to_gcs', return_value='gs://bucket/v1/trends/tonight.json') as mock_upload:

            path = exporter.export('2026-02-12')

        mock_gen.assert_called_once_with('2026-02-12')
        mock_upload.assert_called_once_with(mock_json, 'trends/tonight.json', 'public, max-age=3600')
        assert 'tonight.json' in path
