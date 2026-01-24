"""
System Performance Tracker

Tracks prediction success rates per prediction system (CatBoost V8, etc.)
with breakdowns by prop type (points, assists, rebounds).

Reads from:
- nba_predictions.prediction_accuracy (Phase 5B graded predictions)

Writes to:
- nba_grading.system_performance_summary (aggregated performance metrics)

Key Features:
- Success rate tracking per system_id
- Breakdown by prop_type (points, assists, rebounds - future expansion)
- Rolling window metrics (7-day, 30-day, season)
- High-confidence subset analysis
- Designed for dashboard consumption
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any

from google.cloud import bigquery
from google.api_core import exceptions as gcp_exceptions
from google.cloud.exceptions import GoogleCloudError
from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()


class SystemPerformanceTracker:
    """
    Tracks and aggregates prediction success rates per system.

    Computes:
    - Win rate (prediction_correct == True)
    - MAE (mean absolute error)
    - Bias (signed error, positive = over-predict)
    - Over/Under breakdown
    - High-confidence subset performance
    - Rolling window stats (7d, 30d, season)
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = get_bigquery_client(project_id=project_id)

        # Table references
        self.accuracy_table = f'{project_id}.nba_predictions.prediction_accuracy'
        self.summary_table = f'{project_id}.nba_grading.system_performance_summary'

        logger.info(f"Initialized SystemPerformanceTracker (project: {project_id})")

    def compute_system_performance(
        self,
        start_date: date,
        end_date: date,
        prop_type: str = 'points'
    ) -> List[Dict]:
        """
        Compute performance metrics for all systems over a date range.

        Args:
            start_date: Start of analysis window
            end_date: End of analysis window
            prop_type: Type of prop (points, assists, rebounds) - defaults to points

        Returns:
            List of dicts with performance metrics per system
        """
        query = f"""
        SELECT
            system_id,
            '{prop_type}' as prop_type,
            '{start_date}' as period_start,
            '{end_date}' as period_end,

            -- Volume metrics
            COUNT(*) as total_predictions,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as total_recommendations,
            COUNTIF(recommendation = 'PASS') as pass_count,

            -- Win/Loss
            COUNTIF(prediction_correct = TRUE) as wins,
            COUNTIF(prediction_correct = FALSE) as losses,
            COUNTIF(prediction_correct IS NULL) as pushes,

            -- Success rate
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                COUNTIF(recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as success_rate_pct,

            -- MAE and bias
            ROUND(AVG(absolute_error), 2) as mae,
            ROUND(AVG(signed_error), 2) as avg_bias,
            ROUND(STDDEV(absolute_error), 2) as error_stddev,

            -- Over performance
            COUNTIF(recommendation = 'OVER') as over_count,
            COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE) as over_wins,
            ROUND(SAFE_DIVIDE(
                COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE),
                COUNTIF(recommendation = 'OVER')
            ) * 100, 2) as over_success_rate_pct,

            -- Under performance
            COUNTIF(recommendation = 'UNDER') as under_count,
            COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE) as under_wins,
            ROUND(SAFE_DIVIDE(
                COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE),
                COUNTIF(recommendation = 'UNDER')
            ) * 100, 2) as under_success_rate_pct,

            -- Threshold accuracy
            COUNTIF(within_3_points = TRUE) as within_3_count,
            ROUND(SAFE_DIVIDE(COUNTIF(within_3_points = TRUE), COUNT(*)) * 100, 2) as within_3_pct,
            COUNTIF(within_5_points = TRUE) as within_5_count,
            ROUND(SAFE_DIVIDE(COUNTIF(within_5_points = TRUE), COUNT(*)) * 100, 2) as within_5_pct,

            -- High confidence analysis (confidence >= 0.70 normalized)
            COUNTIF(confidence_score >= 0.70) as high_conf_count,
            COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE) as high_conf_wins,
            ROUND(SAFE_DIVIDE(
                COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE),
                COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as high_conf_success_rate_pct,

            -- Very high confidence (>= 0.80)
            COUNTIF(confidence_score >= 0.80) as very_high_conf_count,
            COUNTIF(confidence_score >= 0.80 AND prediction_correct = TRUE) as very_high_conf_wins,
            ROUND(SAFE_DIVIDE(
                COUNTIF(confidence_score >= 0.80 AND prediction_correct = TRUE),
                COUNTIF(confidence_score >= 0.80 AND recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as very_high_conf_success_rate_pct,

            -- Average confidence
            ROUND(AVG(confidence_score), 3) as avg_confidence,

            -- Voided stats
            COUNTIF(is_voided = TRUE) as voided_count,

            -- Unique coverage
            COUNT(DISTINCT player_lookup) as unique_players,
            COUNT(DISTINCT game_id) as unique_games,
            COUNT(DISTINCT game_date) as days_with_data

        FROM `{self.accuracy_table}`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND is_voided = FALSE  -- Exclude voided predictions
        GROUP BY system_id
        ORDER BY success_rate_pct DESC
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=120))

            summaries = []
            for row in result:
                summary = {
                    'system_id': row.system_id,
                    'prop_type': row.prop_type,
                    'period_start': row.period_start,
                    'period_end': row.period_end,

                    # Volume
                    'total_predictions': row.total_predictions,
                    'total_recommendations': row.total_recommendations,
                    'pass_count': row.pass_count,

                    # Win/Loss
                    'wins': row.wins,
                    'losses': row.losses,
                    'pushes': row.pushes,
                    'success_rate_pct': float(row.success_rate_pct) if row.success_rate_pct else None,

                    # Error metrics
                    'mae': float(row.mae) if row.mae else None,
                    'avg_bias': float(row.avg_bias) if row.avg_bias else None,
                    'error_stddev': float(row.error_stddev) if row.error_stddev else None,

                    # Over performance
                    'over_count': row.over_count,
                    'over_wins': row.over_wins,
                    'over_success_rate_pct': float(row.over_success_rate_pct) if row.over_success_rate_pct else None,

                    # Under performance
                    'under_count': row.under_count,
                    'under_wins': row.under_wins,
                    'under_success_rate_pct': float(row.under_success_rate_pct) if row.under_success_rate_pct else None,

                    # Threshold accuracy
                    'within_3_count': row.within_3_count,
                    'within_3_pct': float(row.within_3_pct) if row.within_3_pct else None,
                    'within_5_count': row.within_5_count,
                    'within_5_pct': float(row.within_5_pct) if row.within_5_pct else None,

                    # High confidence
                    'high_conf_count': row.high_conf_count,
                    'high_conf_wins': row.high_conf_wins,
                    'high_conf_success_rate_pct': float(row.high_conf_success_rate_pct) if row.high_conf_success_rate_pct else None,

                    # Very high confidence
                    'very_high_conf_count': row.very_high_conf_count,
                    'very_high_conf_wins': row.very_high_conf_wins,
                    'very_high_conf_success_rate_pct': float(row.very_high_conf_success_rate_pct) if row.very_high_conf_success_rate_pct else None,

                    # Averages
                    'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,

                    # Coverage
                    'voided_count': row.voided_count,
                    'unique_players': row.unique_players,
                    'unique_games': row.unique_games,
                    'days_with_data': row.days_with_data,

                    # Metadata
                    'computed_at': datetime.now(timezone.utc).isoformat()
                }
                summaries.append(summary)

            return summaries

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error computing system performance: {e}")
            return []
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found computing system performance: {e}")
            return []
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable computing system performance: {e}")
            return []
        except GoogleCloudError as e:
            logger.error(f"GCP error computing system performance: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error computing system performance: {type(e).__name__}: {e}", exc_info=True)
            return []

    def compute_rolling_performance(
        self,
        as_of_date: Optional[date] = None
    ) -> Dict[str, List[Dict]]:
        """
        Compute performance for multiple rolling windows (7d, 30d, season).

        Args:
            as_of_date: Date to compute from (defaults to yesterday)

        Returns:
            Dict with keys 'rolling_7d', 'rolling_30d', 'season', each containing
            a list of system performance dicts
        """
        if as_of_date is None:
            as_of_date = date.today() - timedelta(days=1)

        results = {}

        # 7-day rolling
        start_7d = as_of_date - timedelta(days=7)
        results['rolling_7d'] = self.compute_system_performance(start_7d, as_of_date)

        # 30-day rolling
        start_30d = as_of_date - timedelta(days=30)
        results['rolling_30d'] = self.compute_system_performance(start_30d, as_of_date)

        # Season (Oct 2024 - present for 2024-25 season)
        if as_of_date.month >= 10:
            season_start = date(as_of_date.year, 10, 1)
        else:
            season_start = date(as_of_date.year - 1, 10, 1)
        results['season'] = self.compute_system_performance(season_start, as_of_date)

        return results

    def get_daily_trend(
        self,
        system_id: str,
        days: int = 30,
        prop_type: str = 'points'
    ) -> List[Dict]:
        """
        Get daily success rate trend for a specific system.

        Args:
            system_id: System to analyze
            days: Number of days to look back
            prop_type: Prop type to analyze

        Returns:
            List of daily metrics ordered by date
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        query = f"""
        SELECT
            game_date,
            '{system_id}' as system_id,
            '{prop_type}' as prop_type,

            COUNT(*) as total_predictions,
            COUNTIF(prediction_correct = TRUE) as wins,
            COUNTIF(prediction_correct = FALSE) as losses,
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                COUNTIF(recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as success_rate_pct,
            ROUND(AVG(absolute_error), 2) as mae,

            -- High confidence
            COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE) as high_conf_wins,
            COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER')) as high_conf_total,
            ROUND(SAFE_DIVIDE(
                COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE),
                COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER'))
            ) * 100, 2) as high_conf_success_rate_pct

        FROM `{self.accuracy_table}`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND system_id = '{system_id}'
          AND is_voided = FALSE
        GROUP BY game_date
        ORDER BY game_date DESC
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=60))

            return [
                {
                    'game_date': str(row.game_date),
                    'system_id': row.system_id,
                    'prop_type': row.prop_type,
                    'total_predictions': row.total_predictions,
                    'wins': row.wins,
                    'losses': row.losses,
                    'success_rate_pct': float(row.success_rate_pct) if row.success_rate_pct else None,
                    'mae': float(row.mae) if row.mae else None,
                    'high_conf_wins': row.high_conf_wins,
                    'high_conf_total': row.high_conf_total,
                    'high_conf_success_rate_pct': float(row.high_conf_success_rate_pct) if row.high_conf_success_rate_pct else None
                }
                for row in result
            ]

        except Exception as e:
            logger.error(f"Error getting daily trend for {system_id}: {e}")
            return []

    def write_summary_to_bigquery(
        self,
        summaries: List[Dict],
        period_type: str
    ) -> int:
        """
        Write performance summaries to BigQuery for dashboard access.

        Args:
            summaries: List of performance summary dicts
            period_type: 'rolling_7d', 'rolling_30d', 'season', or 'daily'

        Returns:
            Number of rows written
        """
        if not summaries:
            return 0

        # Add period_type to each summary
        for summary in summaries:
            summary['period_type'] = period_type

        try:
            # Delete existing records for this period type
            delete_query = f"""
            DELETE FROM `{self.summary_table}`
            WHERE period_type = '{period_type}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result(timeout=60)
            deleted = delete_job.num_dml_affected_rows or 0
            if deleted > 0:
                logger.info(f"Deleted {deleted} existing {period_type} records")

            # Insert new records
            table_ref = self.bq_client.get_table(self.summary_table)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                summaries,
                self.summary_table,
                job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            rows_written = load_job.output_rows or len(summaries)
            logger.info(f"Wrote {rows_written} {period_type} performance records")

            return rows_written

        except gcp_exceptions.NotFound as e:
            logger.warning(f"Summary table not found (may need to be created): {e}")
            return 0
        except Exception as e:
            logger.error(f"Error writing summaries to BigQuery: {e}")
            return 0

    def process(self, as_of_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Main processing method - compute and store all performance metrics.

        Args:
            as_of_date: Date to compute from (defaults to yesterday)

        Returns:
            Dict with processing statistics
        """
        if as_of_date is None:
            as_of_date = date.today() - timedelta(days=1)

        logger.info(f"Computing system performance as of {as_of_date}")

        # Compute rolling window performance
        rolling_data = self.compute_rolling_performance(as_of_date)

        total_written = 0

        # Write each period type
        for period_type, summaries in rolling_data.items():
            if summaries:
                written = self.write_summary_to_bigquery(summaries, period_type)
                total_written += written
                logger.info(f"  {period_type}: {len(summaries)} systems, {written} records written")

        return {
            'status': 'success' if total_written > 0 else 'no_data',
            'as_of_date': as_of_date.isoformat(),
            'periods_computed': list(rolling_data.keys()),
            'systems_tracked': {
                period: len(summaries)
                for period, summaries in rolling_data.items()
            },
            'total_records_written': total_written
        }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Compute system performance metrics')
    parser.add_argument('--date', type=str, help='Date to compute from (YYYY-MM-DD)')
    parser.add_argument('--system', type=str, help='Get daily trend for specific system')
    parser.add_argument('--days', type=int, default=30, help='Days for trend (default: 30)')

    args = parser.parse_args()

    tracker = SystemPerformanceTracker()

    if args.system:
        # Get daily trend for specific system
        trend = tracker.get_daily_trend(args.system, days=args.days)
        print(f"\nDaily trend for {args.system} (last {args.days} days):")
        for day in trend[:10]:  # Show first 10
            print(f"  {day['game_date']}: {day['success_rate_pct']}% ({day['wins']}/{day['wins'] + day['losses']})")
        return trend

    # Full processing
    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    result = tracker.process(target_date)
    print(f"Result: {result}")
    return result


if __name__ == '__main__':
    main()
