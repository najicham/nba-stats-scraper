"""Tests for the CLV retraction split-brain fix (2026-07-03, P1.2).

Before this fix, a pick published in the morning and blocked by
clv_diverge_under_block at the 4:30 PM re-export silently stayed
signal_status='active' and graded as taken, while the SAME pick graded as
blocked in best_bets_filtered_picks — making the "drop a pick if the close
moved >= 0.5 against it" rule unmeasurable. These tests pin:

1. SignalBestBetsExporter._mark_clv_retractions — candidate selection
   (only clv_diverge_under_block reasons, current picks excluded, no-op
   without candidates, BQ failure non-fatal).
2. BestBetsAllExporter._merge_and_lock_picks — retracted rows are NOT
   "in signal", the published pick gets stamped retracted_clv (sticky,
   wins over game_started), and retracted-but-never-published picks stay
   in the record.
"""

from unittest.mock import Mock

from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter


def _bare_signal_exporter(bq_client=None):
    """Exporter instance without __init__ side effects (GCS/BQ clients)."""
    exp = object.__new__(SignalBestBetsExporter)
    exp.bq_client = bq_client if bq_client is not None else Mock()
    return exp


def _filtered(player, reason='clv_diverge_under_block'):
    return {'player_lookup': player, 'filter_reason': reason}


class TestMarkClvRetractions:
    def test_noop_without_clv_blocked_players(self):
        bq = Mock()
        exp = _bare_signal_exporter(bq)
        exp._mark_clv_retractions(
            '2026-11-01',
            [_filtered('playera', reason='over_edge_floor')],
            current_players=set(),
        )
        bq.query.assert_not_called()

    def test_noop_when_blocked_player_still_picked_via_other_model(self):
        bq = Mock()
        exp = _bare_signal_exporter(bq)
        exp._mark_clv_retractions(
            '2026-11-01',
            [_filtered('playera')],
            current_players={'playera'},
        )
        bq.query.assert_not_called()

    def test_updates_only_clv_blocked_players(self):
        bq = Mock()
        job = Mock()
        job.num_dml_affected_rows = 1
        bq.query.return_value = job
        exp = _bare_signal_exporter(bq)

        exp._mark_clv_retractions(
            '2026-11-01',
            [
                _filtered('playera'),
                _filtered('playera'),  # duplicate (multi-model) — deduped
                _filtered('playerb', reason='over_edge_floor'),
                _filtered('playerc'),
            ],
            current_players={'playerc'},
        )

        assert bq.query.call_count == 1
        query_sql = bq.query.call_args[0][0]
        assert "signal_status = 'retracted_clv'" in query_sql
        assert 'retracted_at' in query_sql
        # Guard rails: only active rows, never started games
        assert "signal_status IS NULL OR signal_status = 'active'" in query_sql
        assert 'game_status >= 2' in query_sql

        params = bq.query.call_args[1]['job_config'].query_parameters
        player_param = next(p for p in params if p.name == 'player_lookups')
        assert list(player_param.values) == ['playera']

    def test_bq_failure_is_nonfatal(self):
        bq = Mock()
        bq.query.side_effect = RuntimeError('boom')
        exp = _bare_signal_exporter(bq)
        # Must not raise — retraction is best-effort observability
        exp._mark_clv_retractions('2026-11-01', [_filtered('playera')],
                                  current_players=set())


def _bare_all_exporter():
    return object.__new__(BestBetsAllExporter)


def _pub(player, status='active', game_id='g1'):
    return {'player_lookup': player, 'game_id': game_id, 'recommendation': 'UNDER',
            'line_value': 20.5, 'edge': 4.0, 'rank': 1, 'pick_angles': [],
            'ultra_tier': None, 'source': 'algorithm', 'system_id': 'm1',
            'signal_status': status}


def _sig(player, status=None, game_id='g1', **extra):
    row = {'player_lookup': player, 'game_id': game_id, 'recommendation': 'UNDER',
           'line_value': 20.5, 'edge': 4.5, 'rank': 1, 'pick_angles': [],
           'ultra_tier': False, 'system_id': 'm1', 'signal_status': status,
           'prediction_correct': None, 'actual_points': None,
           'is_voided': False, 'void_reason': None}
    row.update(extra)
    return row


class TestMergeRetraction:
    def test_retracted_row_is_not_in_signal_and_stamps_published(self):
        exp = _bare_all_exporter()
        merged, stats = exp._merge_and_lock_picks(
            signal_picks=[_sig('playera', status='retracted_clv')],
            published_picks=[_pub('playera')],
            manual_picks=[],
        )
        assert len(merged) == 1
        pick = merged[0]
        assert pick['_signal_status'] == 'retracted_clv'
        assert pick['_in_signal'] is False
        assert stats.get('retracted_clv') == 1

    def test_retraction_wins_over_game_started(self):
        exp = _bare_all_exporter()
        merged, _ = exp._merge_and_lock_picks(
            signal_picks=[_sig('playera', status='retracted_clv')],
            published_picks=[_pub('playera')],
            manual_picks=[],
            started_game_ids={'g1'},
        )
        assert merged[0]['_signal_status'] == 'retracted_clv'

    def test_retraction_sticks_from_prior_published_status(self):
        # Signal table row gone entirely (e.g. later scoped DELETE) but the
        # published row already carries retracted_clv — must not revert.
        exp = _bare_all_exporter()
        merged, _ = exp._merge_and_lock_picks(
            signal_picks=[],
            published_picks=[_pub('playera', status='retracted_clv')],
            manual_picks=[],
        )
        assert merged[0]['_signal_status'] == 'retracted_clv'

    def test_retracted_never_published_pick_stays_in_record(self):
        exp = _bare_all_exporter()
        merged, stats = exp._merge_and_lock_picks(
            signal_picks=[_sig('playera', status='retracted_clv')],
            published_picks=[],
            manual_picks=[],
        )
        assert len(merged) == 1
        assert merged[0]['_signal_status'] == 'retracted_clv'
        assert merged[0]['_in_signal'] is False

    def test_active_pick_unaffected(self):
        exp = _bare_all_exporter()
        merged, stats = exp._merge_and_lock_picks(
            signal_picks=[_sig('playera', status='active')],
            published_picks=[_pub('playera')],
            manual_picks=[],
        )
        assert merged[0].get('_signal_status') != 'retracted_clv'
        assert merged[0]['_in_signal'] is True
        assert stats.get('retracted_clv') is None

    def test_grading_fields_refresh_from_retracted_row(self):
        exp = _bare_all_exporter()
        merged, _ = exp._merge_and_lock_picks(
            signal_picks=[_sig('playera', status='retracted_clv',
                               prediction_correct=False, actual_points=25)],
            published_picks=[_pub('playera')],
            manual_picks=[],
        )
        assert merged[0]['prediction_correct'] is False
        assert merged[0]['actual_points'] == 25
