"""
Admin Dashboard Exporter for Phase 6 Publishing

Consolidated single-file admin view that merges:
  - Model health (states, hit rates, training age)
  - Signal health (HOT/NORMAL/COLD regimes per signal)
  - Subset performance (rolling HR across all subsets)
  - Today's picks with full metadata + all candidates
  - Filter summary (what got rejected and why)

Output: v1/admin/dashboard.json
Replaces need to fetch 4+ separate admin endpoints.

Created: 2026-02-21 (Session 319)
"""

import json
import logging
from typing import Any, Dict, List

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int
from ml.signals.aggregator import ALGORITHM_VERSION
from ml.signals.signal_health import get_signal_health_summary
from shared.config.model_selection import get_best_bets_model_id
from shared.config.subset_public_names import SUBSET_PUBLIC_NAMES

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class AdminDashboardExporter(BaseExporter):
    """Export consolidated admin dashboard to a single GCS file."""

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate dashboard JSON with all admin data."""
        model_health = self._query_model_health(target_date)
        signal_health = self._query_signal_health(target_date)
        subset_performance = self._query_subset_performance(target_date)
        today_picks = self._query_today_picks(target_date)
        candidates = self._query_candidates(target_date)
        filter_summary = self._query_filter_summary(target_date)

        # Edge distribution from candidates
        edges = [abs(c.get('edge') or 0) for c in candidates]
        edge_distribution = {
            'total': len(candidates),
            'edge_3_plus': sum(1 for e in edges if e >= 3.0),
            'edge_5_plus': sum(1 for e in edges if e >= 5.0),
            'edge_7_plus': sum(1 for e in edges if e >= 7.0),
            'max_edge': round(max(edges), 1) if edges else None,
        }

        # Extract champion model state for status bar (2a: frontend request)
        champion_id = get_best_bets_model_id()
        champion_state = 'UNKNOWN'
        for m in model_health:
            if m.get('system_id') == champion_id:
                champion_state = m.get('state', 'UNKNOWN')
                break

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'algorithm_version': ALGORITHM_VERSION,
            'best_bets_model': champion_id,
            'champion_model_state': champion_state,
            'model_health': model_health,
            'signal_health': signal_health,
            'subset_performance': subset_performance,
            'picks': today_picks,
            'total_picks': len(today_picks),
            'candidates_summary': {
                'total': len(candidates),
                'edge_distribution': edge_distribution,
            },
            'filter_summary': filter_summary,
        }

    def export(self, target_date: str) -> str:
        """Generate and upload dashboard.json."""
        json_data = self.generate_json(target_date)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='admin/dashboard.json',
            cache_control='public, max-age=300',
        )

        logger.info(
            f"Exported admin/dashboard.json: "
            f"{json_data['total_picks']} picks, "
            f"{len(json_data['model_health'])} models, "
            f"{len(json_data['signal_health'])} signals, "
            f"{len(json_data['subset_performance'])} subsets"
        )
        return gcs_path

    # ── Queries ──────────────────────────────────────────────────────────

    def _query_model_health(self, target_date: str) -> List[Dict]:
        """Query model performance states from model_performance_daily."""
        query = """
        SELECT
          system_id,
          game_date,
          hr_7d,
          hr_14d,
          n_7d,
          n_14d,
          state,
          days_since_training
        FROM `nba-props-platform.nba_predictions.model_performance_daily`
        WHERE game_date >= DATE_SUB(@target_date, INTERVAL 1 DAY)
          AND game_date <= @target_date
        ORDER BY game_date DESC, system_id
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query model health: {e}")
            return []

        # Deduplicate — keep most recent per system_id
        seen = set()
        models = []
        for r in rows:
            sid = r.get('system_id')
            if sid in seen:
                continue
            seen.add(sid)
            models.append({
                'system_id': sid,
                'state': r.get('state'),
                'hr_7d': safe_float(r.get('hr_7d'), precision=1),
                'hr_14d': safe_float(r.get('hr_14d'), precision=1),
                'n_7d': safe_int(r.get('n_7d'), 0),
                'n_14d': safe_int(r.get('n_14d'), 0),
                'days_since_training': safe_int(r.get('days_since_training')),
            })

        return models

    def _query_signal_health(self, target_date: str) -> Dict[str, Any]:
        """Query signal health regimes."""
        try:
            return get_signal_health_summary(self.bq_client, target_date)
        except Exception as e:
            logger.warning(f"Failed to query signal health: {e}")
            return {}

    def _query_subset_performance(self, target_date: str) -> List[Dict]:
        """Query all subset rolling performance from the dynamic view."""
        query = """
        WITH recent AS (
          SELECT
            subset_id,
            game_date,
            wins,
            graded_picks
          FROM `nba-props-platform.nba_predictions.v_dynamic_subset_performance`
          WHERE game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
            AND game_date <= @target_date
        )
        SELECT
          subset_id,
          -- 7-day
          SUM(CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
              THEN wins ELSE 0 END) AS wins_7d,
          SUM(CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
              THEN graded_picks ELSE 0 END) AS total_7d,
          -- 14-day
          SUM(CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
              THEN wins ELSE 0 END) AS wins_14d,
          SUM(CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
              THEN graded_picks ELSE 0 END) AS total_14d,
          -- 30-day (season proxy)
          SUM(wins) AS wins_30d,
          SUM(graded_picks) AS total_30d
        FROM recent
        GROUP BY subset_id
        HAVING SUM(graded_picks) > 0
        ORDER BY
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) DESC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query subset performance: {e}")
            return []

        subsets = []
        for r in rows:
            def hr(w, t):
                return round(100.0 * w / t, 1) if t > 0 else None

            w7 = safe_int(r.get('wins_7d'), 0)
            t7 = safe_int(r.get('total_7d'), 0)
            w14 = safe_int(r.get('wins_14d'), 0)
            t14 = safe_int(r.get('total_14d'), 0)
            w30 = safe_int(r.get('wins_30d'), 0)
            t30 = safe_int(r.get('total_30d'), 0)

            sid = r.get('subset_id', '')
            pub = SUBSET_PUBLIC_NAMES.get(sid, {})

            subsets.append({
                'subset_id': sid,
                'label': pub.get('name', sid),
                '7d': {'wins': w7, 'losses': t7 - w7, 'total': t7, 'hr': hr(w7, t7)},
                '14d': {'wins': w14, 'losses': t14 - w14, 'total': t14, 'hr': hr(w14, t14)},
                '30d': {'wins': w30, 'losses': t30 - w30, 'total': t30, 'hr': hr(w30, t30)},
            })

        return subsets

    def _query_today_picks(self, target_date: str) -> List[Dict]:
        """Query today's signal best bets with full metadata."""
        query = """
        SELECT
          b.rank,
          b.player_name,
          b.player_lookup,
          b.team_abbr,
          b.opponent_team_abbr,
          b.recommendation,
          b.line_value,
          b.edge,
          b.predicted_points,
          b.confidence_score,
          b.composite_score,
          b.signal_tags,
          b.signal_count,
          b.pick_angles,
          b.warning_tags,
          b.matched_combo_id,
          b.combo_classification,
          b.combo_hit_rate,
          b.model_agreement_count,
          b.agreeing_model_ids,
          b.consensus_bonus,
          b.source_model_id,
          b.source_model_family,
          b.n_models_eligible,
          b.champion_edge,
          b.direction_conflict,
          b.algorithm_version,
          b.filter_summary,
          pa.actual_points,
          pa.prediction_correct
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
        LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
          ON b.player_lookup = pa.player_lookup
          AND b.game_date = pa.game_date
          AND b.system_id = pa.system_id
        WHERE b.game_date = @target_date
        ORDER BY b.rank ASC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query today's picks: {e}")
            return []

        picks = []
        for p in rows:
            signal_tags = p.get('signal_tags') or []
            pick_angles = p.get('pick_angles') or []
            warning_tags = p.get('warning_tags') or []
            agreeing = p.get('agreeing_model_ids') or []

            # Parse filter_summary JSON if present
            fs = p.get('filter_summary')
            if isinstance(fs, str):
                try:
                    fs = json.loads(fs)
                except (json.JSONDecodeError, TypeError):
                    pass

            picks.append({
                'rank': safe_int(p.get('rank')),
                'player': p.get('player_name') or '',
                'player_lookup': p.get('player_lookup') or '',
                'team': p.get('team_abbr') or '',
                'opponent': p.get('opponent_team_abbr') or '',
                'direction': p.get('recommendation') or '',
                'line': safe_float(p.get('line_value'), precision=1),
                'edge': safe_float(p.get('edge'), precision=1),
                'predicted': safe_float(p.get('predicted_points'), precision=1),
                'confidence': safe_float(p.get('confidence_score'), precision=3),
                'composite_score': safe_float(p.get('composite_score'), precision=4),
                'signals': list(signal_tags),
                'signal_count': safe_int(p.get('signal_count'), 0),
                'angles': list(pick_angles),
                'warnings': list(warning_tags),
                'combo': p.get('matched_combo_id'),
                'combo_class': p.get('combo_classification'),
                'combo_hr': safe_float(p.get('combo_hit_rate'), precision=1),
                'model_agreement': safe_int(p.get('model_agreement_count'), 0),
                'agreeing_models': list(agreeing),
                'consensus_bonus': safe_float(p.get('consensus_bonus'), precision=4),
                'source_model': p.get('source_model_id'),
                'source_family': p.get('source_model_family'),
                'n_models_eligible': safe_int(p.get('n_models_eligible'), 0),
                'champion_edge': safe_float(p.get('champion_edge'), precision=1),
                'direction_conflict': bool(p.get('direction_conflict')),
                'algorithm_version': p.get('algorithm_version'),
                'actual': safe_int(p.get('actual_points')),
                'result': (
                    'WIN' if p.get('prediction_correct') is True
                    else 'LOSS' if p.get('prediction_correct') is False
                    else None
                ),
            })

        return picks

    def _query_candidates(self, target_date: str) -> List[Dict]:
        """Query all predictions for candidate count and edge distribution."""
        query = """
        SELECT
          ROUND(predicted_points - line_value, 1) AS edge
        FROM `nba-props-platform.nba_predictions.player_prop_predictions`
        WHERE game_date = @target_date
          AND is_active = TRUE
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query candidates: {e}")
            return []

    def _query_filter_summary(self, target_date: str) -> Dict:
        """Get filter_summary from today's picks (same for all picks on a date)."""
        query = """
        SELECT filter_summary
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
        WHERE game_date = @target_date
          AND filter_summary IS NOT NULL
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
            if rows and rows[0].get('filter_summary'):
                return json.loads(rows[0]['filter_summary'])
        except Exception as e:
            logger.warning(f"Failed to query filter summary: {e}")

        return {}
