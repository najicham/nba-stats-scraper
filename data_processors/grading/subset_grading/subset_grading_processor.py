"""
Subset Grading Processor

Grades subsets using materialized membership from current_subset_picks.
This grades what was ACTUALLY in each subset at game time, not retroactive
recomputation.

Runs after PredictionAccuracyProcessor in the grading pipeline.

Version selection for grading:
  Uses the latest version computed BEFORE the first game tip time.
  This ensures we grade the subset that was "locked in" before games started,
  not a version created after some games were already in progress.
  Falls back to MAX(version_id) if no schedule data is available.

Reads from:
- nba_predictions.current_subset_picks (materialized subset membership)
- nba_analytics.player_game_summary (actual game results)
- nba_reference.nba_schedule (game tip times for version selection)

Writes to:
- nba_predictions.subset_grading_results

Session 153: Created for proper subset grading using materialized data.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()
SUBSET_PICKS_TABLE = f'{PROJECT_ID}.nba_predictions.current_subset_picks'
GRADING_RESULTS_TABLE = f'{PROJECT_ID}.nba_predictions.subset_grading_results'
PLAYER_GAME_SUMMARY_TABLE = f'{PROJECT_ID}.nba_analytics.player_game_summary'


class SubsetGradingProcessor:
    """
    Grade subsets using materialized subset membership.

    For each subset on a game date, computes:
    - Win/loss/push counts and hit rate
    - ROI at -110 odds
    - Mean absolute error
    - Over/under breakdown
    - DNP voiding

    Uses the subset version that was locked in before the first game tip.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = get_bigquery_client(project_id=project_id)

    def process_date(self, game_date: date) -> Dict[str, Any]:
        """
        Grade all subsets for a specific date.

        Args:
            game_date: Date to grade

        Returns:
            Dict with grading results summary
        """
        game_date_str = game_date.isoformat()
        logger.info(f"Grading subsets for {game_date_str}")

        # 1. Select the right version to grade
        version_id = self._select_grading_version(game_date_str)
        if not version_id:
            logger.info(f"No materialized subset picks for {game_date_str}")
            return {
                'status': 'no_data',
                'date': game_date_str,
                'subsets_graded': 0,
            }

        logger.info(f"Grading version {version_id} for {game_date_str}")

        # 2. Load picks for that version
        subset_picks = self._load_subset_picks(game_date_str, version_id)
        if not subset_picks:
            logger.info(f"No picks in version {version_id} for {game_date_str}")
            return {
                'status': 'no_data',
                'date': game_date_str,
                'version_id': version_id,
                'subsets_graded': 0,
            }

        # 3. Load actuals
        actuals = self._load_actuals(game_date_str)
        if not actuals:
            logger.warning(f"No actuals found for {game_date_str}")
            return {
                'status': 'no_actuals',
                'date': game_date_str,
                'version_id': version_id,
                'subsets_graded': 0,
            }

        # Build actuals lookup
        actuals_map = {a['player_lookup']: a for a in actuals}

        # 4. Group picks by subset
        picks_by_subset = {}
        for pick in subset_picks:
            sid = pick['subset_id']
            if sid not in picks_by_subset:
                picks_by_subset[sid] = {
                    'subset_name': pick.get('subset_name'),
                    'picks': [],
                }
            picks_by_subset[sid]['picks'].append(pick)

        # 5. Grade each subset
        graded_at = datetime.now(timezone.utc)
        results = []

        for subset_id, data in picks_by_subset.items():
            grade = self._grade_subset(
                subset_id=subset_id,
                subset_name=data['subset_name'],
                picks=data['picks'],
                actuals_map=actuals_map,
                game_date_str=game_date_str,
                version_id=version_id,
                graded_at=graded_at,
            )
            results.append(grade)

        # 6. Write results (DELETE + INSERT for idempotency)
        if results:
            self._write_results(game_date_str, results)

        logger.info(
            f"Graded {len(results)} subsets for {game_date_str} "
            f"(version={version_id}): "
            f"{sum(r['graded_picks'] for r in results)} total graded picks"
        )

        return {
            'status': 'success',
            'date': game_date_str,
            'version_id': version_id,
            'subsets_graded': len(results),
            'results': [
                {
                    'subset_id': r['subset_id'],
                    'total_picks': r['total_picks'],
                    'graded_picks': r['graded_picks'],
                    'wins': r['wins'],
                    'hit_rate': r['hit_rate'],
                    'roi': r['roi'],
                }
                for r in results
            ],
        }

    def _select_grading_version(self, game_date_str: str) -> Optional[str]:
        """
        Select the version_id to use for grading.

        Strategy: Use the latest version computed BEFORE the first game tip time.
        This ensures we grade what was "locked in" before games started.
        Falls back to MAX(version_id) if no schedule data is available.

        Args:
            game_date_str: Date string YYYY-MM-DD

        Returns:
            version_id string, or None if no versions exist
        """
        # Try to find first tip time from schedule
        tip_time = self._get_first_tip_time(game_date_str)

        if tip_time:
            # Get latest version computed before first tip
            query = f"""
            SELECT MAX(version_id) as version_id
            FROM `{SUBSET_PICKS_TABLE}`
            WHERE game_date = @game_date
              AND computed_at < @tip_time
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
                    bigquery.ScalarQueryParameter('tip_time', 'TIMESTAMP', tip_time.isoformat()),
                ]
            )
            result = self.bq_client.query(query, job_config=job_config).result(timeout=30)
            rows = [dict(row) for row in result]
            version = rows[0]['version_id'] if rows and rows[0]['version_id'] else None

            if version:
                logger.info(
                    f"Selected pre-tip version {version} "
                    f"(first tip: {tip_time.isoformat()})"
                )
                return version

            # No version before tip — fall through to latest
            logger.warning(
                f"No version before first tip ({tip_time.isoformat()}) "
                f"for {game_date_str}, falling back to latest version"
            )

        # Fallback: latest version for this date
        query = f"""
        SELECT MAX(version_id) as version_id
        FROM `{SUBSET_PICKS_TABLE}`
        WHERE game_date = @game_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=30)
        rows = [dict(row) for row in result]
        return rows[0]['version_id'] if rows and rows[0]['version_id'] else None

    def _get_first_tip_time(self, game_date_str: str) -> Optional[datetime]:
        """
        Get the first game tip-off time for a date.

        Args:
            game_date_str: Date string YYYY-MM-DD

        Returns:
            datetime of first tip, or None if not available
        """
        query = f"""
        SELECT MIN(game_datetime_utc) as first_tip
        FROM `{self.project_id}.nba_reference.nba_schedule`
        WHERE game_date = @game_date
          AND game_status IN (2, 3)  -- In Progress or Final (game actually happened)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
            ]
        )
        try:
            result = self.bq_client.query(query, job_config=job_config).result(timeout=30)
            rows = [dict(row) for row in result]
            if rows and rows[0].get('first_tip'):
                return rows[0]['first_tip']
        except Exception as e:
            logger.warning(f"Could not get tip time for {game_date_str}: {e}")

        return None

    def _load_subset_picks(self, game_date_str: str, version_id: str) -> List[Dict[str, Any]]:
        """
        Load materialized subset picks for a specific version.

        Args:
            game_date_str: Date string YYYY-MM-DD
            version_id: Version to load

        Returns:
            List of pick dictionaries
        """
        query = f"""
        SELECT
          subset_id,
          subset_name,
          player_lookup,
          player_name,
          team,
          opponent,
          predicted_points,
          current_points_line,
          recommendation,
          confidence_score,
          edge
        FROM `{SUBSET_PICKS_TABLE}`
        WHERE game_date = @game_date
          AND version_id = @version_id
        ORDER BY subset_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
                bigquery.ScalarQueryParameter('version_id', 'STRING', version_id),
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in result]

    def _load_actuals(self, game_date_str: str) -> List[Dict[str, Any]]:
        """
        Load actual game results for grading.

        Args:
            game_date_str: Date string YYYY-MM-DD

        Returns:
            List of actual result dictionaries
        """
        query = f"""
        SELECT
          player_lookup,
          points,
          minutes_played
        FROM `{PLAYER_GAME_SUMMARY_TABLE}`
        WHERE game_date = @game_date
          AND points IS NOT NULL
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in result]

    def _grade_subset(
        self,
        subset_id: str,
        subset_name: str,
        picks: List[Dict[str, Any]],
        actuals_map: Dict[str, Dict[str, Any]],
        game_date_str: str,
        version_id: str,
        graded_at: datetime,
    ) -> Dict[str, Any]:
        """
        Grade a single subset's picks against actuals.

        Uses same win/loss/push/DNP logic as PredictionAccuracyProcessor.
        """
        total_picks = len(picks)
        wins = 0
        losses = 0
        pushes = 0
        voided = 0
        absolute_errors = []
        over_picks = 0
        over_wins = 0
        under_picks = 0
        under_wins = 0
        edges = []
        confidences = []

        for pick in picks:
            player_lookup = pick['player_lookup']
            actual = actuals_map.get(player_lookup)

            if actual is None:
                voided += 1
                continue

            actual_points = actual['points']
            minutes_played = actual.get('minutes_played')
            line = pick['current_points_line']
            recommendation = pick['recommendation']

            # DNP voiding: 0 points and 0/None minutes
            if actual_points == 0 and (minutes_played is None or minutes_played == 0):
                voided += 1
                continue

            if pick.get('edge') is not None:
                edges.append(pick['edge'])
            if pick.get('confidence_score') is not None:
                confidences.append(pick['confidence_score'])

            if pick.get('predicted_points') is not None:
                absolute_errors.append(abs(pick['predicted_points'] - actual_points))

            # Push: actual equals line
            if actual_points == line:
                pushes += 1
                continue

            # Win/loss
            if recommendation == 'OVER':
                over_picks += 1
                if actual_points > line:
                    wins += 1
                    over_wins += 1
                else:
                    losses += 1
            elif recommendation == 'UNDER':
                under_picks += 1
                if actual_points < line:
                    wins += 1
                    under_wins += 1
                else:
                    losses += 1

        graded_picks = wins + losses
        hit_rate = (wins / graded_picks * 100) if graded_picks > 0 else None
        units_won = (wins * 0.909 - losses) if graded_picks > 0 else 0.0
        roi = (units_won / graded_picks * 100) if graded_picks > 0 else None
        mae = (sum(absolute_errors) / len(absolute_errors)) if absolute_errors else None
        avg_edge = (sum(edges) / len(edges)) if edges else None
        avg_confidence = (sum(confidences) / len(confidences)) if confidences else None

        return {
            'game_date': game_date_str,
            'subset_id': subset_id,
            'subset_name': subset_name,
            'graded_at': graded_at.isoformat(),
            'version_id': version_id,
            'total_picks': total_picks,
            'graded_picks': graded_picks,
            'voided_picks': voided,
            'wins': wins,
            'losses': losses,
            'pushes': pushes,
            'hit_rate': round(hit_rate, 1) if hit_rate is not None else None,
            'roi': round(roi, 1) if roi is not None else None,
            'units_won': round(units_won, 3) if units_won else 0.0,
            'avg_edge': round(avg_edge, 2) if avg_edge is not None else None,
            'avg_confidence': round(avg_confidence, 3) if avg_confidence is not None else None,
            'mae': round(mae, 2) if mae is not None else None,
            'over_picks': over_picks,
            'over_wins': over_wins,
            'under_picks': under_picks,
            'under_wins': under_wins,
        }

    def _write_results(self, game_date_str: str, results: List[Dict[str, Any]]) -> None:
        """
        Write grading results using DELETE + INSERT for idempotency.

        Args:
            game_date_str: Date string YYYY-MM-DD
            results: List of grading result dictionaries
        """
        # Delete existing results for this date
        delete_query = f"""
        DELETE FROM `{GRADING_RESULTS_TABLE}`
        WHERE game_date = @game_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date_str),
            ]
        )
        try:
            self.bq_client.query(delete_query, job_config=job_config).result(timeout=30)
        except Exception as e:
            logger.warning(f"Delete failed (table may not exist yet): {e}")

        # Insert new results
        errors = self.bq_client.insert_rows_json(GRADING_RESULTS_TABLE, results)
        if errors:
            logger.error(f"Errors inserting subset grading results: {errors}")
            raise RuntimeError(f"BigQuery insert errors: {errors}")

        logger.info(
            f"Wrote {len(results)} subset grading results for {game_date_str}"
        )
