"""
Admin Picks Exporter for Phase 6 Publishing

Exports full-metadata daily picks for the admin dashboard. Includes everything
from signal_best_bets_picks plus filter_summary and all candidates with
rejection reasons.

Output: v1/admin/picks/{date}.json
Source: signal_best_bets_picks + player_prop_predictions

Created: 2026-02-21 (Session 319)
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List


def _compute_season_label(d: date) -> str:
    """Compute NBA season label from a date (e.g. Feb 2026 -> '2025-26')."""
    if d.month >= 10:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    return f"{d.year - 1}-{str(d.year)[-2:]}"

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int
from ml.signals.ultra_bets import compute_ultra_live_hrs

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def _parse_ultra_criteria(raw) -> list:
    """Parse ultra_criteria from BQ (stored as JSON string) into a list."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


class AdminPicksExporter(BaseExporter):
    """Export full-metadata picks for admin debugging."""

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate admin picks JSON with full metadata."""
        selected_picks = self._query_selected_picks(target_date)
        all_candidates = self._query_all_candidates(target_date)
        filter_summary = self._query_filter_summary(target_date)

        # Build selected player_lookups set for marking rejection
        selected_lookups = {
            p.get('player_lookup') for p in selected_picks
        }

        # Format selected picks with full metadata
        picks = []
        for p in selected_picks:
            signal_tags = p.get('signal_tags') or []
            pick_angles = p.get('pick_angles') or []
            warning_tags = p.get('warning_tags') or []
            agreeing_models = p.get('agreeing_model_ids') or []

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
                'matched_combo': p.get('matched_combo_id'),
                'combo_classification': p.get('combo_classification'),
                'combo_hit_rate': safe_float(p.get('combo_hit_rate'), precision=1),
                'model_agreement': safe_int(p.get('model_agreement_count'), 0),
                'agreeing_models': list(agreeing_models),
                'consensus_bonus': safe_float(p.get('consensus_bonus'), precision=4),
                'source_model': p.get('source_model_id'),
                'source_family': p.get('source_model_family'),
                'n_models_eligible': safe_int(p.get('n_models_eligible'), 0),
                'champion_edge': safe_float(p.get('champion_edge'), precision=1),
                'direction_conflict': bool(p.get('direction_conflict')),
                'algorithm_version': p.get('algorithm_version'),
                'filter_summary': p.get('filter_summary'),
                # Ultra Bets (Session 327 — admin-only visibility)
                'ultra_tier': bool(p.get('ultra_tier')),
                'ultra_criteria': _parse_ultra_criteria(p.get('ultra_criteria')),
                'actual': safe_int(p.get('actual_points')),
                'result': (
                    'WIN' if p.get('prediction_correct') is True
                    else 'LOSS' if p.get('prediction_correct') is False
                    else None
                ),
            })

        # Format candidates (all predictions for that date with edge info)
        candidates = []
        for c in all_candidates:
            candidates.append({
                'player': c.get('player_name') or '',
                'player_lookup': c.get('player_lookup') or '',
                'team': c.get('team_abbr') or '',
                'direction': c.get('recommendation') or '',
                'line': safe_float(c.get('line_value'), precision=1),
                'edge': safe_float(c.get('edge'), precision=1),
                'quality_score': safe_float(
                    c.get('feature_quality_score'), precision=1
                ),
                'selected': c.get('player_lookup') in selected_lookups,
            })

        # Edge distribution from candidates
        edges = [abs(c.get('edge') or 0) for c in candidates]
        edge_distribution = {
            'total': len(candidates),
            'edge_3_plus': sum(1 for e in edges if e >= 3.0),
            'edge_5_plus': sum(1 for e in edges if e >= 5.0),
            'edge_7_plus': sum(1 for e in edges if e >= 7.0),
            'max_edge': round(max(edges), 1) if edges else None,
        }

        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )

        # Ultra Bets summary — admin-only (Session 327)
        # Per-pick ultra_tier + ultra_criteria already on each pick above.
        # Top-level summary provides aggregate stats for the status bar.
        ultra_count = sum(1 for p in picks if p.get('ultra_tier'))
        ultra_live_hrs = {}
        try:
            raw_live = compute_ultra_live_hrs(self.bq_client, PROJECT_ID)
            # Add backtest_date for freshness visibility (frontend request)
            from ml.signals.ultra_bets import ULTRA_CRITERIA
            criteria_dates = {
                c['id']: c['backtest_date'] for c in ULTRA_CRITERIA
            }
            for cid, stats in raw_live.items():
                ultra_live_hrs[cid] = {
                    **stats,
                    'backtest_date': criteria_dates.get(cid),
                }
        except Exception as e:
            logger.warning(f"Ultra live HR query failed (non-fatal): {e}")

        ultra_summary = {
            'ultra_count': ultra_count,
            'live_hrs': ultra_live_hrs,
        }

        return {
            'date': target_date,
            'season': _compute_season_label(target),
            'generated_at': self.get_generated_at(),
            'picks': picks,
            'total_picks': len(picks),
            'ultra': ultra_summary,
            'candidates': candidates,
            'total_candidates': len(candidates),
            'candidates_summary': {
                'total': len(candidates),
                'edge_distribution': edge_distribution,
            },
            'filter_summary': filter_summary,
        }

    def export(self, target_date: str) -> str:
        """Generate and upload admin picks JSON.

        Returns:
            GCS path where file was uploaded.
        """
        json_data = self.generate_json(target_date)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path=f'admin/picks/{target_date}.json',
            cache_control='public, max-age=3600',
        )

        logger.info(
            f"Exported admin/picks/{target_date}.json: "
            f"{json_data['total_picks']} picks, "
            f"{json_data['total_candidates']} candidates"
        )
        return gcs_path

    def _query_selected_picks(self, target_date: str) -> List[Dict]:
        """Query signal best bets picks with full metadata."""
        query = """
        SELECT
          b.*,
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
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query selected picks: {e}")
            return []

    def _query_all_candidates(self, target_date: str) -> List[Dict]:
        """Query all predictions for the date (candidates before filtering)."""
        query = """
        SELECT
          player_lookup,
          player_lookup AS player_name,
          recommendation,
          current_points_line AS line_value,
          ROUND(predicted_points - current_points_line, 1) AS edge,
          feature_quality_score
        FROM `nba-props-platform.nba_predictions.player_prop_predictions`
        WHERE game_date = @target_date
          AND is_active = TRUE
          AND current_points_line IS NOT NULL
        ORDER BY ABS(predicted_points - current_points_line) DESC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query all candidates: {e}")
            return []

    def _query_filter_summary(self, target_date: str) -> Dict:
        """Get filter_summary from that date's picks (same for all picks on a date)."""
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
