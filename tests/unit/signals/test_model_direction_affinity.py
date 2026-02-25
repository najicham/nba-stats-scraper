"""Tests for model-direction affinity module.

Tests cover:
1. Affinity group mapping from family keys
2. Affinity group mapping from system_ids
3. Edge band classification
4. Block checking (O(1) set lookup)
5. Compute function with mock BQ client
6. Phase 1 observation mode (threshold=0.0 blocks nothing)
7. Phase 2 active blocking (threshold=45.0)
8. Query failure returns empty results (non-blocking)

Run with: pytest tests/unit/signals/test_model_direction_affinity.py -v
"""

import pytest
from unittest.mock import Mock

from ml.signals.model_direction_affinity import (
    get_affinity_group,
    _get_affinity_group_from_system_id,
    _classify_edge_band,
    check_model_direction_block,
    compute_model_direction_affinities,
    BLOCK_THRESHOLD_HR,
)


# ============================================================================
# AFFINITY GROUP MAPPING TESTS
# ============================================================================

class TestGetAffinityGroup:
    """Test mapping from source_model_family to affinity group."""

    def test_v9_mae(self):
        assert get_affinity_group('v9_mae') == 'v9'

    def test_v9_q43(self):
        assert get_affinity_group('v9_q43') == 'v9'

    def test_v9_q45(self):
        assert get_affinity_group('v9_q45') == 'v9'

    def test_v9_low_vegas(self):
        """Session 343: v9_low_vegas is its own group (62.5% UNDER vs 30.7% for v9)."""
        assert get_affinity_group('v9_low_vegas') == 'v9_low_vegas'

    def test_v12_q43_is_noveg(self):
        """v12_q43 uses noveg feature set → v12_noveg group."""
        assert get_affinity_group('v12_q43') == 'v12_noveg'

    def test_v12_q45_is_noveg(self):
        assert get_affinity_group('v12_q45') == 'v12_noveg'

    def test_v12_mae_is_vegas(self):
        """v12_mae uses full v12 feature set (includes vegas)."""
        assert get_affinity_group('v12_mae') == 'v12_vegas'

    def test_v12_vegas_q43(self):
        assert get_affinity_group('v12_vegas_q43') == 'v12_vegas'

    def test_v12_vegas_q45(self):
        assert get_affinity_group('v12_vegas_q45') == 'v12_vegas'

    def test_empty_string(self):
        assert get_affinity_group('') is None

    def test_none(self):
        assert get_affinity_group(None) is None

    def test_unrecognized(self):
        assert get_affinity_group('catboost_v99') is None


class TestGetAffinityGroupFromSystemId:
    """Test mapping from system_id to affinity group."""

    def test_v9_champion(self):
        assert _get_affinity_group_from_system_id('catboost_v9') == 'v9'

    def test_v9_variant(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v9_33f_train20260106_20260218'
        ) == 'v9'

    def test_v9_low_vegas(self):
        """Session 343: v9_low_vegas is its own affinity group."""
        assert _get_affinity_group_from_system_id(
            'catboost_v9_low_vegas_train0106_0205'
        ) == 'v9_low_vegas'

    def test_v9_q43(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v9_q43_train1102_0131'
        ) == 'v9'

    def test_v12_noveg(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v12_noveg_train20260106_20260218'
        ) == 'v12_noveg'

    def test_v12_noveg_q43(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v12_noveg_q43_train20260106'
        ) == 'v12_noveg'

    def test_v12_vegas(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v12_train20260106_20260218'
        ) == 'v12_vegas'

    def test_v12_vegas_q43(self):
        assert _get_affinity_group_from_system_id(
            'catboost_v12_q43_train20260106'
        ) == 'v12_vegas'

    def test_empty_string(self):
        assert _get_affinity_group_from_system_id('') is None

    def test_none(self):
        assert _get_affinity_group_from_system_id(None) is None


# ============================================================================
# EDGE BAND CLASSIFICATION TESTS
# ============================================================================

class TestClassifyEdgeBand:
    """Test edge band classification."""

    def test_edge_3(self):
        assert _classify_edge_band(3.0) == '3_5'

    def test_edge_4_9(self):
        assert _classify_edge_band(4.9) == '3_5'

    def test_edge_5(self):
        assert _classify_edge_band(5.0) == '5_7'

    def test_edge_6_9(self):
        assert _classify_edge_band(6.9) == '5_7'

    def test_edge_7(self):
        assert _classify_edge_band(7.0) == '7_plus'

    def test_edge_12(self):
        assert _classify_edge_band(12.0) == '7_plus'

    def test_edge_below_3(self):
        assert _classify_edge_band(2.9) is None

    def test_edge_0(self):
        assert _classify_edge_band(0.0) is None

    def test_negative_edge_uses_abs(self):
        assert _classify_edge_band(-5.5) == '5_7'


# ============================================================================
# BLOCK CHECKING TESTS
# ============================================================================

class TestCheckModelDirectionBlock:
    """Test O(1) block checking."""

    def test_blocked_combo_returns_reason(self):
        blocked = {('v9', 'UNDER', '7_plus')}
        result = check_model_direction_block('v9_mae', 'UNDER', 8.0, blocked)
        assert result is not None
        assert 'v9' in result
        assert 'UNDER' in result
        assert '7_plus' in result

    def test_non_blocked_combo_returns_none(self):
        blocked = {('v9', 'UNDER', '7_plus')}
        result = check_model_direction_block('v9_mae', 'OVER', 8.0, blocked)
        assert result is None

    def test_empty_blocked_set_returns_none(self):
        result = check_model_direction_block('v9_mae', 'UNDER', 8.0, set())
        assert result is None

    def test_none_blocked_set_returns_none(self):
        result = check_model_direction_block('v9_mae', 'UNDER', 8.0, None)
        assert result is None

    def test_unrecognized_family_returns_none(self):
        blocked = {('v9', 'UNDER', '7_plus')}
        result = check_model_direction_block('unknown_model', 'UNDER', 8.0, blocked)
        assert result is None

    def test_edge_below_3_returns_none(self):
        """Edge < 3 has no band classification → no block."""
        blocked = {('v9', 'UNDER', '3_5')}
        result = check_model_direction_block('v9_mae', 'UNDER', 2.5, blocked)
        assert result is None

    def test_v12_vegas_over_blocked(self):
        blocked = {('v12_vegas', 'OVER', '3_5')}
        result = check_model_direction_block('v12_mae', 'OVER', 4.0, blocked)
        assert result is not None
        assert 'v12_vegas' in result

    def test_v12_noveg_not_blocked_when_v12_vegas_is(self):
        """v12_noveg and v12_vegas are separate groups."""
        blocked = {('v12_vegas', 'OVER', '3_5')}
        result = check_model_direction_block('v12_q43', 'OVER', 4.0, blocked)
        assert result is None

    def test_negative_edge_uses_abs(self):
        blocked = {('v9', 'UNDER', '5_7')}
        result = check_model_direction_block('v9_mae', 'UNDER', -6.0, blocked)
        assert result is not None


# ============================================================================
# COMPUTE FUNCTION TESTS
# ============================================================================

def _make_bq_row(affinity_group, direction, edge_band, total_picks, wins, losses, hit_rate):
    """Create a dict mimicking a BigQuery row."""
    return {
        'affinity_group': affinity_group,
        'direction': direction,
        'edge_band': edge_band,
        'total_picks': total_picks,
        'wins': wins,
        'losses': losses,
        'hit_rate': hit_rate,
    }


def _mock_bq_client(rows):
    """Create a mock BQ client that returns the given rows."""
    client = Mock()
    result_mock = Mock()
    result_mock.result.return_value = [row for row in rows]
    client.query.return_value = result_mock
    return client


class TestComputeModelDirectionAffinities:
    """Test compute function with mock BQ data."""

    def test_phase1_observation_blocks_nothing(self):
        """Phase 1: threshold 0.0 means nothing is blocked even with bad HR."""
        rows = [
            _make_bq_row('v9', 'UNDER', '7_plus', 28, 11, 17, 39.3),
            _make_bq_row('v12_vegas', 'OVER', '3_5', 26, 8, 18, 30.8),
        ]
        client = _mock_bq_client(rows)

        affinities, blocked, stats = compute_model_direction_affinities(
            client, '2026-02-22', block_threshold_hr=0.0
        )

        assert len(blocked) == 0
        assert stats['combos_blocked'] == 0
        assert stats['observation_mode'] is True
        assert len(stats['would_block_at_45']) == 2

    def test_phase2_active_blocking(self):
        """Phase 2: threshold 45.0 blocks combos below breakeven."""
        rows = [
            _make_bq_row('v9', 'UNDER', '7_plus', 28, 11, 17, 39.3),
            _make_bq_row('v9', 'OVER', '5_7', 36, 23, 13, 63.9),
            _make_bq_row('v12_vegas', 'OVER', '3_5', 26, 8, 18, 30.8),
        ]
        client = _mock_bq_client(rows)

        affinities, blocked, stats = compute_model_direction_affinities(
            client, '2026-02-22', block_threshold_hr=45.0
        )

        # v9 UNDER 7+ (39.3%) and v12_vegas OVER 3_5 (30.8%) should be blocked
        assert ('v9', 'UNDER', '7_plus') in blocked
        assert ('v12_vegas', 'OVER', '3_5') in blocked
        # v9 OVER 5_7 (63.9%) should NOT be blocked
        assert ('v9', 'OVER', '5_7') not in blocked
        assert stats['combos_blocked'] == 2
        assert stats['observation_mode'] is False

    def test_affinities_dict_structure(self):
        """Verify nested dict structure: {group: {direction: {band: stats}}}."""
        rows = [
            _make_bq_row('v9', 'OVER', '5_7', 36, 23, 13, 63.9),
        ]
        client = _mock_bq_client(rows)

        affinities, _, _ = compute_model_direction_affinities(client, '2026-02-22')

        assert 'v9' in affinities
        assert 'OVER' in affinities['v9']
        assert '5_7' in affinities['v9']['OVER']
        combo = affinities['v9']['OVER']['5_7']
        assert combo['hit_rate'] == 63.9
        assert combo['total_picks'] == 36
        assert combo['wins'] == 23
        assert combo['losses'] == 13

    def test_empty_results(self):
        """No rows returned → empty affinities, no blocks."""
        client = _mock_bq_client([])

        affinities, blocked, stats = compute_model_direction_affinities(
            client, '2026-02-22'
        )

        assert affinities == {}
        assert blocked == set()
        assert stats['combos_evaluated'] == 0

    def test_query_failure_returns_empty(self):
        """BigQuery exception → empty results (non-blocking)."""
        client = Mock()
        client.query.side_effect = Exception("BQ timeout")

        affinities, blocked, stats = compute_model_direction_affinities(
            client, '2026-02-22'
        )

        assert affinities == {}
        assert blocked == set()
        assert stats['combos_evaluated'] == 0
        # observation_mode depends on BLOCK_THRESHOLD_HR (False when > 0)
        assert stats['observation_mode'] == (stats.get('block_threshold_hr', 0) <= 0)

    def test_stats_includes_would_block(self):
        """Stats should include would_block_at_45 list for observation mode."""
        rows = [
            _make_bq_row('v9', 'OVER', '5_7', 36, 23, 13, 63.9),   # Good
            _make_bq_row('v9', 'UNDER', '7_plus', 28, 11, 17, 39.3),  # Bad
        ]
        client = _mock_bq_client(rows)

        _, _, stats = compute_model_direction_affinities(
            client, '2026-02-22', block_threshold_hr=0.0
        )

        assert len(stats['would_block_at_45']) == 1
        assert stats['would_block_at_45'][0]['group'] == 'v9'
        assert stats['would_block_at_45'][0]['direction'] == 'UNDER'

    def test_boundary_exactly_45_not_blocked(self):
        """Exactly 45.0% HR should NOT be blocked (strict less-than)."""
        rows = [
            _make_bq_row('v9', 'UNDER', '5_7', 20, 9, 11, 45.0),
        ]
        client = _mock_bq_client(rows)

        _, blocked, _ = compute_model_direction_affinities(
            client, '2026-02-22', block_threshold_hr=45.0
        )

        assert len(blocked) == 0


class TestPhase1Default:
    """Verify Phase 1 defaults are set correctly."""

    def test_threshold_is_active(self):
        """Phase 2 (Session 343): BLOCK_THRESHOLD_HR = 45.0 to block losing combos."""
        assert BLOCK_THRESHOLD_HR == 45.0
