"""Replay Engine — simulate model selection strategies against historical data.

Iterates over a date range, computes rolling metrics for each model,
applies a pluggable decision strategy, and computes daily P&L.

Usage:
    from ml.analysis.replay_engine import ReplayEngine
    from ml.analysis.replay_strategies import ThresholdStrategy

    engine = ReplayEngine(bq_client)
    strategy = ThresholdStrategy('catboost_v9', ['catboost_v12'])
    results = engine.run(strategy, '2025-11-15', '2026-02-12',
                         ['catboost_v9', 'catboost_v12'])

Created: 2026-02-15 (Session 262)
"""

import logging
from dataclasses import asdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

from ml.analysis.replay_strategies import Decision, DecisionStrategy, ModelMetrics

logger = logging.getLogger(__name__)

# Standard bet: $110 to win $100 (-110 odds)
STAKE = 110
WIN_PAYOUT = 100


class ReplayEngine:
    """Core replay simulation engine."""

    def __init__(self, bq_client: bigquery.Client, min_edge: float = 3.0,
                 min_confidence: Optional[float] = None):
        self.bq_client = bq_client
        self.min_edge = min_edge
        self.min_confidence = min_confidence
        self._data_cache: Optional[Dict] = None

    def run(self, strategy: DecisionStrategy,
            start_date: str, end_date: str,
            model_ids: List[str],
            max_picks_per_day: int = 5) -> dict:
        """Run a full replay simulation.

        Args:
            strategy: Decision strategy to apply.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            model_ids: Model IDs to include.
            max_picks_per_day: Max picks per day per model.

        Returns:
            Dict with keys: decisions, daily_pnl, summary, strategy_name.
        """
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        # Load all data upfront for efficiency
        daily_data = self._load_daily_data(start, end, model_ids)

        decisions = []
        daily_pnl = []
        current_model = None
        cumulative_pnl = 0.0
        total_wins = 0
        total_losses = 0
        total_picks = 0
        switches = 0
        blocked_days = 0

        game_dates = sorted(daily_data.keys())

        for d in game_dates:
            if d < start or d > end:
                continue

            # Build metrics for all models on this date
            model_metrics = self._compute_metrics(d, model_ids, daily_data)

            # Apply strategy
            decision = strategy.decide(d, model_metrics, current_model)
            decisions.append({
                'date': d.isoformat(),
                'selected_model': decision.selected_model,
                'action': decision.action,
                'reason': decision.reason,
                'state': decision.state,
                'previous_model': current_model,
            })

            # Track switches
            if decision.action == 'SWITCHED':
                switches += 1
            if decision.selected_model is None:
                blocked_days += 1

            # Compute P&L for today using selected model's picks
            day_stats = self._compute_daily_pnl(
                d, decision.selected_model, daily_data, max_picks_per_day)
            day_stats['date'] = d.isoformat()
            day_stats['selected_model'] = decision.selected_model
            day_stats['state'] = decision.state

            cumulative_pnl += day_stats['daily_pnl_dollars']
            day_stats['cumulative_pnl'] = round(cumulative_pnl, 2)
            total_wins += day_stats['wins']
            total_losses += day_stats['losses']
            total_picks += day_stats['picks']

            daily_pnl.append(day_stats)
            current_model = decision.selected_model

        # Build summary
        total_hr = round(100.0 * total_wins / total_picks, 1) if total_picks > 0 else 0.0
        total_roi = round(100.0 * cumulative_pnl / (total_picks * STAKE), 1) if total_picks > 0 else 0.0

        summary = {
            'strategy': strategy.name,
            'date_range': f"{start_date} to {end_date}",
            'game_days': len(game_dates),
            'total_picks': total_picks,
            'total_wins': total_wins,
            'total_losses': total_losses,
            'hit_rate': total_hr,
            'cumulative_pnl': round(cumulative_pnl, 2),
            'roi': total_roi,
            'switches': switches,
            'blocked_days': blocked_days,
            'models_used': list(set(
                d['selected_model'] for d in decisions
                if d['selected_model'] is not None
            )),
        }

        return {
            'decisions': decisions,
            'daily_pnl': daily_pnl,
            'summary': summary,
            'strategy_name': strategy.name,
        }

    def compare_strategies(self, strategies: List[DecisionStrategy],
                           start_date: str, end_date: str,
                           model_ids: List[str]) -> List[dict]:
        """Run multiple strategies and return comparison summaries."""
        results = []
        for strat in strategies:
            result = self.run(strat, start_date, end_date, model_ids)
            results.append(result['summary'])
        return results

    def _load_daily_data(self, start: date, end: date,
                         model_ids: List[str]) -> Dict:
        """Load all prediction_accuracy data for the date range.

        Returns:
            Dict keyed by game_date -> model_id -> list of pick dicts.
        """
        # Need 30 days of lookback for rolling metrics
        window_start = start - timedelta(days=30)

        confidence_filter = ""
        if self.min_confidence is not None:
            confidence_filter = "AND confidence_score >= @min_confidence"

        query = f"""
        SELECT
          game_date,
          system_id AS model_id,
          prediction_correct AS is_correct,
          ABS(predicted_points - line_value) AS edge,
          predicted_points,
          line_value,
          actual_points,
          player_lookup,
          recommendation,
          confidence_score
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date BETWEEN @window_start AND @end_date
          AND ABS(predicted_points - line_value) >= @min_edge
          AND system_id IN UNNEST(@model_ids)
          {confidence_filter}
        ORDER BY game_date, system_id
        """

        params = [
            bigquery.ScalarQueryParameter('window_start', 'DATE', window_start),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end),
            bigquery.ScalarQueryParameter('min_edge', 'FLOAT64', self.min_edge),
            bigquery.ArrayQueryParameter('model_ids', 'STRING', model_ids),
        ]
        if self.min_confidence is not None:
            params.append(
                bigquery.ScalarQueryParameter('min_confidence', 'FLOAT64', self.min_confidence)
            )

        job_config = bigquery.QueryJobConfig(query_parameters=params)

        rows = list(self.bq_client.query(query, job_config=job_config).result())
        logger.info(f"Loaded {len(rows)} edge 3+ picks across {len(model_ids)} models")

        # Organize by date -> model -> picks
        data: Dict = {}
        for row in rows:
            d = row.game_date
            mid = row.model_id
            if d not in data:
                data[d] = {}
            if mid not in data[d]:
                data[d][mid] = []
            data[d][mid].append({
                'is_correct': row.is_correct,
                'edge': row.edge,
                'predicted_points': row.predicted_points,
                'line_value': row.line_value,
                'actual_points': row.actual_points,
                'player_lookup': row.player_lookup,
                'recommendation': row.recommendation,
            })

        self._data_cache = data
        return data

    def _compute_metrics(self, target_date: date,
                         model_ids: List[str],
                         daily_data: Dict) -> Dict[str, ModelMetrics]:
        """Compute rolling metrics for all models on a given date."""
        metrics = {}

        for mid in model_ids:
            # Collect picks over rolling windows
            picks_7d = []
            picks_14d = []
            picks_30d = []
            picks_today = []

            for d in sorted(daily_data.keys()):
                model_picks = daily_data.get(d, {}).get(mid, [])
                days_ago = (target_date - d).days

                if days_ago == 0:
                    picks_today = model_picks
                if 0 <= days_ago < 7:
                    picks_7d.extend(model_picks)
                if 0 <= days_ago < 14:
                    picks_14d.extend(model_picks)
                if 0 <= days_ago < 30:
                    picks_30d.extend(model_picks)

            def hr(picks):
                if not picks:
                    return None
                return round(100.0 * sum(1 for p in picks if p['is_correct']) / len(picks), 1)

            daily_wins = sum(1 for p in picks_today if p['is_correct'])
            daily_hr_val = round(100.0 * daily_wins / len(picks_today), 1) if picks_today else None

            metrics[mid] = ModelMetrics(
                model_id=mid,
                rolling_hr_7d=hr(picks_7d),
                rolling_hr_14d=hr(picks_14d),
                rolling_hr_30d=hr(picks_30d),
                rolling_n_7d=len(picks_7d),
                rolling_n_14d=len(picks_14d),
                rolling_n_30d=len(picks_30d),
                daily_picks=len(picks_today),
                daily_wins=daily_wins,
                daily_hr=daily_hr_val,
            )

        return metrics

    def _compute_daily_pnl(self, target_date: date,
                           selected_model: Optional[str],
                           daily_data: Dict,
                           max_picks: int) -> dict:
        """Compute P&L for today using the selected model's picks."""
        if selected_model is None:
            return {'picks': 0, 'wins': 0, 'losses': 0,
                    'daily_hr': 0.0, 'daily_pnl_dollars': 0.0}

        day_picks = daily_data.get(target_date, {}).get(selected_model, [])

        # Sort by edge descending, take top N
        day_picks = sorted(day_picks, key=lambda p: p['edge'], reverse=True)
        day_picks = day_picks[:max_picks]

        wins = sum(1 for p in day_picks if p['is_correct'])
        losses = len(day_picks) - wins
        pnl = (wins * WIN_PAYOUT) - (losses * STAKE)
        hr = round(100.0 * wins / len(day_picks), 1) if day_picks else 0.0

        return {
            'picks': len(day_picks),
            'wins': wins,
            'losses': losses,
            'daily_hr': hr,
            'daily_pnl_dollars': round(pnl, 2),
        }
