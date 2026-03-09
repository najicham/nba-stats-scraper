# tests/mlb/test_exporter_with_regressor.py
"""
Tests for MLB Best Bets Exporter with CatBoost V2 Regressor predictions.

Tests the full export pipeline: overconfidence cap, edge floor, negative filters
(pitcher_blacklist, bad_opponent, bad_venue), positive signals
(projection_agrees, home_pitcher), and end-to-end integration.

Uses dry_run=True + mocked BQ client to avoid real writes.
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from ml.signals.mlb.best_bets_exporter import (
    MLBBestBetsExporter,
    MAX_EDGE,
    DEFAULT_EDGE_FLOOR,
)


def _make_prediction(
    pitcher_lookup: str = 'gerrit_cole',
    predicted_strikeouts: float = 6.5,
    strikeouts_line: float = 5.5,
    edge: float = 1.0,
    recommendation: str = 'OVER',
    system_id: str = 'catboost_v2_regressor',
    p_over: float = 0.668,
    confidence: float = 35.0,
    **overrides,
) -> dict:
    """Build a minimal regressor prediction dict."""
    pred = {
        'pitcher_lookup': pitcher_lookup,
        'predicted_strikeouts': predicted_strikeouts,
        'strikeouts_line': strikeouts_line,
        'edge': edge,
        'recommendation': recommendation,
        'system_id': system_id,
        'p_over': p_over,
        'confidence': confidence,
        'model_version': 'catboost_v2_regressor',
        'default_feature_count': 0,
    }
    pred.update(overrides)
    return pred


def _make_features_for_signals(**overrides):
    """Build feature dict that triggers enough signals to pass the signal gate."""
    base = {
        'season_k_per_9': 10.5,       # ace_pitcher_over fires (shadow)
        'k_avg_last_3': 8.0,
        'k_avg_last_5': 7.0,
        'k_avg_last_10': 6.0,         # k_trending_over: 8.0 - 6.0 = 2.0 >= 1.0
        'k_avg_vs_line': 1.5,         # recent_k_above_line fires
        'k_std_last_10': 2.0,
        'ip_avg_last_5': 6.0,
        'season_games_started': 15,
        'rolling_stats_games': 10,
        'is_home': True,              # home_pitcher_over fires
        'opponent_team_k_rate': 0.25,  # opponent_k_prone fires
        'ballpark_k_factor': 1.06,    # ballpark_k_boost fires
        'bp_projection': 7.0,
        'projection_diff': 1.5,       # projection_agrees_over fires
        'days_rest': 7,               # long_rest_over fires
        'swstr_pct_last_3': 0.14,
        'season_swstr_pct': 0.11,     # swstr_surge: 0.14 - 0.11 = 0.03 >= 0.02
    }
    base.update(overrides)
    return base


class TestExporterOverconfidenceCap:
    """Test the overconfidence cap (edge > MAX_EDGE blocked)."""

    def test_overconfidence_cap_blocks_high_edge(self):
        """Prediction with edge=2.5 should be blocked (MAX_EDGE=2.0)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        pred = _make_prediction(
            pitcher_lookup='high_edge_pitcher',
            edge=2.5,
            predicted_strikeouts=8.0,
            strikeouts_line=5.5,
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            dry_run=True,
        )

        # Should be blocked by overconfidence cap — no picks
        assert len(result) == 0

        # Verify filter audit recorded the block
        overconfidence_audits = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'overconfidence_cap'
        ]
        assert len(overconfidence_audits) == 1
        assert overconfidence_audits[0]['filter_result'] == 'BLOCKED'


class TestExporterEdgeFloor:
    """Test the edge floor gate."""

    @patch.dict(os.environ, {'MLB_EDGE_FLOOR': '0.75'})
    def test_edge_floor_passes(self):
        """Prediction with edge=0.8 should pass edge floor (>= 0.75)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        features = _make_features_for_signals()
        pred = _make_prediction(
            pitcher_lookup='edge_pitcher',
            edge=0.8,
            predicted_strikeouts=6.3,
            strikeouts_line=5.5,
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'edge_pitcher': features},
            dry_run=True,
        )

        # Should pass edge floor (0.8 >= 0.75)
        # May or may not pass signal gate depending on how many signals fire
        # But should NOT be blocked by edge_floor filter
        edge_floor_blocks = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'edge_floor' and a.get('filter_result') == 'BLOCKED'
        ]
        assert len(edge_floor_blocks) == 0


class TestExporterNegativeFilters:
    """Test the negative filter pipeline."""

    def test_pitcher_blacklist_blocks(self):
        """Prediction for freddy_peralta should be blocked by pitcher_blacklist."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        pred = _make_prediction(
            pitcher_lookup='tanner_bibee',
            edge=1.2,
            predicted_strikeouts=6.7,
            strikeouts_line=5.5,
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'tanner_bibee': _make_features_for_signals()},
            dry_run=True,
        )

        # Should be blocked by pitcher_blacklist filter
        assert len(result) == 0

        blacklist_audits = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'pitcher_blacklist'
               and a.get('filter_result') == 'BLOCKED'
        ]
        assert len(blacklist_audits) == 1

    def test_whole_line_blocks(self):
        """OVER prediction on whole-number line (5.0) should be blocked.
        Session 443: Whole lines have 17.3% push rate, 49% OVER HR (p<0.001)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        pred = _make_prediction(
            pitcher_lookup='good_pitcher',
            edge=1.2,
            predicted_strikeouts=6.2,
            strikeouts_line=5.0,  # Whole number line
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'good_pitcher': _make_features_for_signals()},
            dry_run=True,
        )

        # Should be blocked by whole_line_over filter
        assert len(result) == 0

        whole_line_audits = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'whole_line_over'
               and a.get('filter_result') == 'BLOCKED'
        ]
        assert len(whole_line_audits) == 1

    def test_half_line_passes(self):
        """OVER prediction on half-line (5.5) should NOT be blocked by whole-line filter."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        pred = _make_prediction(
            pitcher_lookup='good_pitcher',
            edge=1.2,
            predicted_strikeouts=6.7,
            strikeouts_line=5.5,  # Half-line — no push risk
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'good_pitcher': _make_features_for_signals()},
            dry_run=True,
        )

        # Half-line should pass through (may still be blocked by signal gate)
        whole_line_blocks = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'whole_line_over'
               and a.get('filter_result') == 'BLOCKED'
        ]
        assert len(whole_line_blocks) == 0


class TestExporterPositiveSignals:
    """Test positive signal firing."""

    def test_projection_agrees_signal_fires(self):
        """Projection > line + 0.5 should trigger projection_agrees_over signal."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        features = _make_features_for_signals(
            bp_projection=7.0,
            projection_diff=1.5,  # 7.0 - 5.5 = 1.5 >= 0.5
        )

        pred = _make_prediction(
            pitcher_lookup='proj_pitcher',
            edge=1.0,
            predicted_strikeouts=6.5,
            strikeouts_line=5.5,
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'proj_pitcher': features},
            dry_run=True,
        )

        # If the pick made it through, check signal_tags
        if result:
            assert 'projection_agrees_over' in result[0].get('signal_tags', [])
        else:
            # Even if gated, we can check by directly evaluating the signal
            from ml.signals.mlb.signals import ProjectionAgreesOverSignal
            signal = ProjectionAgreesOverSignal()
            sig_result = signal.evaluate(pred, features)
            assert sig_result.qualifies is True

    def test_home_pitcher_signal_fires(self):
        """is_home=True should trigger home_pitcher_over signal."""
        from ml.signals.mlb.signals import HomePitcherSignal

        signal = HomePitcherSignal()
        pred = _make_prediction(recommendation='OVER', is_home=True)
        features = {'is_home': True}

        result = signal.evaluate(pred, features)
        assert result.qualifies is True
        assert result.confidence == 0.6


class TestExporterIntegration:
    """End-to-end integration test for the export pipeline."""

    def test_full_pipeline_integration(self):
        """Create 5 mock predictions, run through export(), verify best bets come out.

        Setup:
        - 5 pitchers with varying edge, features, opponents
        - Pitcher 1: good pick (high edge, good signals) -> should make it
        - Pitcher 2: blacklisted -> blocked
        - Pitcher 3: vs KC (bad opponent) -> blocked
        - Pitcher 4: good pick (moderate edge, home, signals) -> should make it
        - Pitcher 5: edge too high (overconfident) -> blocked
        """
        mock_bq = MagicMock()
        mock_bq.query.return_value.result.return_value = None
        mock_bq.insert_rows_json.return_value = []

        exporter = MLBBestBetsExporter(bq_client=mock_bq)

        predictions = [
            # Pitcher 1: Clean pick — should survive pipeline
            _make_prediction(
                pitcher_lookup='ace_pitcher',
                edge=1.2,
                predicted_strikeouts=6.7,
                strikeouts_line=5.5,
                p_over=0.70,
            ),
            # Pitcher 2: Blacklisted — should be blocked
            _make_prediction(
                pitcher_lookup='tanner_bibee',
                edge=1.5,
                predicted_strikeouts=7.0,
                strikeouts_line=5.5,
                p_over=0.72,
            ),
            # Pitcher 3: Whole-number line — should be blocked by whole_line_over
            _make_prediction(
                pitcher_lookup='unlucky_pitcher',
                edge=1.3,
                predicted_strikeouts=6.8,
                strikeouts_line=5.0,  # Whole number = push risk
                p_over=0.69,
            ),
            # Pitcher 4: Home pitcher, good signals — should survive
            _make_prediction(
                pitcher_lookup='home_ace',
                edge=1.0,
                predicted_strikeouts=6.5,
                strikeouts_line=5.5,
                p_over=0.67,
            ),
            # Pitcher 5: Overconfident edge — should be blocked
            _make_prediction(
                pitcher_lookup='overconfident_pitcher',
                edge=2.5,
                predicted_strikeouts=8.0,
                strikeouts_line=5.5,
                p_over=0.82,
            ),
        ]

        # Features for signal-firing pitchers (enough signals to pass gate)
        features_by_pitcher = {
            'ace_pitcher': _make_features_for_signals(),
            'tanner_bibee': _make_features_for_signals(),
            'unlucky_pitcher': _make_features_for_signals(),
            'home_ace': _make_features_for_signals(),
            'overconfident_pitcher': _make_features_for_signals(),
        }

        result = exporter.export(
            predictions=predictions,
            game_date='2026-06-15',
            features_by_pitcher=features_by_pitcher,
            dry_run=True,
        )

        # At least 1-2 picks should survive (ace_pitcher and/or home_ace)
        assert len(result) >= 1
        # At most 3 (the daily limit)
        assert len(result) <= 3

        # Verify blocked pitchers are NOT in result
        result_pitchers = {p['pitcher_lookup'] for p in result}
        assert 'tanner_bibee' not in result_pitchers, "Blacklisted pitcher should be blocked"
        assert 'unlucky_pitcher' not in result_pitchers, "Whole-line pitcher should be blocked"
        assert 'overconfident_pitcher' not in result_pitchers, "Overconfident pitcher should be blocked"

        # Verify surviving picks have required fields
        for pick in result:
            assert 'signal_tags' in pick
            assert 'rank' in pick
            assert 'pick_angles' in pick
            assert 'algorithm_version' in pick
            assert pick['system_id'] == 'catboost_v2_regressor'

        # Verify filter audit has entries
        assert len(exporter.filter_audit) > 0

        # Verify at least one overconfidence block was recorded
        overconf_blocks = [
            a for a in exporter.filter_audit
            if a.get('filter_name') == 'overconfidence_cap'
        ]
        assert len(overconf_blocks) >= 1


class TestUltraTier:
    """Test ultra tier tagging (Session 444 — 81.4% HR, N=70)."""

    def _make_ultra_eligible_prediction(self, **overrides):
        """Build a prediction that meets all ultra criteria."""
        defaults = dict(
            pitcher_lookup='ace_pitcher',
            edge=1.2,
            predicted_strikeouts=6.7,
            strikeouts_line=5.5,  # half-line
            projection_value=6.2,  # > line
            is_home=True,
        )
        defaults.update(overrides)
        return _make_prediction(**defaults)

    def _make_ultra_features(self, **overrides):
        """Build features that trigger enough signals including ultra requirements."""
        return _make_features_for_signals(is_home=True, **overrides)

    def test_ultra_pick_tagged(self):
        """Pick meeting all ultra criteria should be tagged ultra_tier=True."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction()
        features = self._make_ultra_features()

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        assert len(result) >= 1
        pick = result[0]
        assert pick['ultra_tier'] is True
        assert 'half_line' in pick['ultra_criteria']
        assert 'is_home' in pick['ultra_criteria']
        assert 'projection_agrees' in pick['ultra_criteria']
        assert pick['staking_multiplier'] == 2

    def test_non_ultra_pick_has_1u(self):
        """Pick that doesn't meet ultra criteria should have staking_multiplier=1."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        # Away pitcher — fails home requirement
        pred = _make_prediction(
            pitcher_lookup='away_pitcher',
            edge=1.2,
            predicted_strikeouts=6.7,
            strikeouts_line=5.5,
        )
        features = _make_features_for_signals(is_home=False)

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'away_pitcher': features},
            dry_run=True,
        )

        if result:
            assert result[0]['ultra_tier'] is False
            assert result[0]['staking_multiplier'] == 1

    def test_ultra_requires_edge_1_1(self):
        """Edge 1.0 should NOT qualify for ultra (threshold is 1.1)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction(edge=1.0)
        features = self._make_ultra_features()

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        if result:
            assert result[0]['ultra_tier'] is False

    def test_ultra_requires_home(self):
        """Away pitcher should NOT qualify for ultra."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction(is_home=False)
        features = _make_features_for_signals(is_home=False)

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        if result:
            assert result[0]['ultra_tier'] is False

    def test_ultra_requires_half_line(self):
        """Whole-number line should NOT qualify for ultra (also blocked by filter)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction(strikeouts_line=6.0)
        features = self._make_ultra_features()

        # Whole-line is blocked by the whole_line_over filter before ultra check
        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )
        assert len(result) == 0  # Blocked by whole_line filter

    def test_ultra_requires_projection_agrees(self):
        """No projection agreement should NOT qualify for ultra."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction(projection_value=None)
        features = _make_features_for_signals(
            is_home=True,
            bp_projection=4.0,    # projection < line
            projection_diff=-1.5, # fails projection_agrees_over
        )

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        if result:
            assert result[0]['ultra_tier'] is False

    def test_blacklisted_pitcher_not_ultra(self):
        """Blacklisted pitcher should not qualify for ultra (also blocked by filter)."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction(pitcher_lookup='tanner_bibee')
        features = self._make_ultra_features()

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'tanner_bibee': features},
            dry_run=True,
        )
        assert len(result) == 0  # Blocked by blacklist filter

    def test_ultra_overlay_outside_top3(self):
        """Ultra pick outside top-3 should still be published via overlay."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())

        # 4 picks: first 3 non-ultra (away), 4th is ultra (home)
        preds = [
            _make_prediction(
                pitcher_lookup=f'pitcher_{i}',
                edge=2.0 - i * 0.3,
                predicted_strikeouts=6.5,
                strikeouts_line=5.5,
            )
            for i in range(3)
        ]
        # 4th pick: lower edge but ultra-eligible
        preds.append(self._make_ultra_eligible_prediction(
            pitcher_lookup='ultra_overlay_pitcher',
            edge=1.1,
            predicted_strikeouts=6.6,
        ))

        features_map = {
            f'pitcher_{i}': _make_features_for_signals(is_home=False)
            for i in range(3)
        }
        features_map['ultra_overlay_pitcher'] = self._make_ultra_features()

        result = exporter.export(
            predictions=preds,
            game_date='2026-06-15',
            features_by_pitcher=features_map,
            dry_run=True,
        )

        # Should have 4 picks (3 regular + 1 ultra overlay)
        result_pitchers = {p['pitcher_lookup'] for p in result}
        assert 'ultra_overlay_pitcher' in result_pitchers

        ultra_pick = [p for p in result if p['pitcher_lookup'] == 'ultra_overlay_pitcher'][0]
        assert ultra_pick['ultra_tier'] is True
        assert ultra_pick['staking_multiplier'] == 2

    def test_ultra_angle_in_pick_angles(self):
        """Ultra picks should have 'ULTRA:' in their pick angles."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction()
        features = self._make_ultra_features()

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        if result and result[0].get('ultra_tier'):
            ultra_angles = [a for a in result[0]['pick_angles'] if 'ULTRA' in a]
            assert len(ultra_angles) == 1
            assert '2u stake' in ultra_angles[0]

    def test_algorithm_version_updated(self):
        """Algorithm version should be mlb_v6_season_replay_validated."""
        exporter = MLBBestBetsExporter(bq_client=MagicMock())
        pred = self._make_ultra_eligible_prediction()
        features = self._make_ultra_features()

        result = exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=True,
        )

        assert len(result) >= 1
        assert result[0]['algorithm_version'] == 'mlb_v6_season_replay_validated'

    def test_bq_row_includes_ultra_fields(self):
        """BQ row should include ultra_tier, ultra_criteria, staking_multiplier."""
        mock_bq = MagicMock()
        mock_bq.query.return_value.result.return_value = None
        mock_bq.insert_rows_json.return_value = []

        exporter = MLBBestBetsExporter(bq_client=mock_bq)
        pred = self._make_ultra_eligible_prediction()
        features = self._make_ultra_features()

        exporter.export(
            predictions=[pred],
            game_date='2026-06-15',
            features_by_pitcher={'ace_pitcher': features},
            dry_run=False,
        )

        # Check insert_rows_json was called
        calls = mock_bq.insert_rows_json.call_args_list
        bb_call = [c for c in calls if 'signal_best_bets_picks' in str(c)]
        assert len(bb_call) >= 1

        rows = bb_call[0][0][1]  # Second arg is rows list
        assert 'ultra_tier' in rows[0]
        assert 'ultra_criteria' in rows[0]
        assert 'staking_multiplier' in rows[0]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
