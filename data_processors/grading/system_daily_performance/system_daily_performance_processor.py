"""
System Daily Performance Aggregation Processor

Aggregates prediction_accuracy data into daily system-level summaries.
This enables efficient queries for the Phase 6 SystemPerformanceExporter.

Reads from:
- nba_predictions.prediction_accuracy (Phase 5B)

Writes to:
- nba_predictions.system_daily_performance

Key Features:
- Aggregates by (game_date, system_id)
- Computes win rates, MAE, bias, OVER/UNDER splits
- Tracks high-confidence prediction performance
- Idempotent writes (DELETE + INSERT pattern)
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
ACCURACY_TABLE = f'{PROJECT_ID}.nba_predictions.prediction_accuracy'
DAILY_PERF_TABLE = f'{PROJECT_ID}.nba_predictions.system_daily_performance'


class SystemDailyPerformanceProcessor:
    """
    Aggregates prediction accuracy into daily system-level metrics.

    For each (game_date, system_id) pair, computes:
    - Volume: predictions, recommendations, correct/incorrect, pass
    - Accuracy: win_rate, MAE, bias
    - OVER/UNDER: separate win rates
    - Thresholds: within_3, within_5 percentages
    - Confidence: high-confidence (>=0.70) performance
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def process(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate daily performance summaries for a specific date.

        Args:
            target_date: Date to compute summaries for (defaults to yesterday)

        Returns:
            Dict with processing statistics
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        logger.info(f"Computing system daily performance for {target_date}")

        # Check if data exists for this date
        if not self._check_accuracy_data_exists(target_date):
            logger.warning(f"No prediction_accuracy data found for {target_date}")
            return {
                'status': 'no_data',
                'date': target_date.isoformat(),
                'systems': 0,
                'records_written': 0
            }

        # Compute aggregations
        summaries = self._compute_daily_summaries(target_date)

        if not summaries:
            logger.warning(f"No summaries computed for {target_date}")
            return {
                'status': 'no_summaries',
                'date': target_date.isoformat(),
                'systems': 0,
                'records_written': 0
            }

        # Write to BigQuery
        written = self._write_summaries(summaries, target_date)

        logger.info(f"Wrote {written} system daily performance records for {target_date}")

        return {
            'status': 'success' if written > 0 else 'write_failed',
            'date': target_date.isoformat(),
            'systems': len(summaries),
            'records_written': written
        }

    def process_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """
        Process a range of dates (for backfill).

        Args:
            start_date: First date to process
            end_date: Last date to process

        Returns:
            Dict with overall statistics
        """
        logger.info(f"Processing system daily performance from {start_date} to {end_date}")

        current = start_date
        total_written = 0
        dates_processed = 0
        dates_skipped = 0

        while current <= end_date:
            result = self.process(current)

            if result['status'] == 'success':
                total_written += result['records_written']
                dates_processed += 1
            else:
                dates_skipped += 1

            current += timedelta(days=1)

        return {
            'status': 'success',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'dates_processed': dates_processed,
            'dates_skipped': dates_skipped,
            'total_records_written': total_written
        }

    def _check_accuracy_data_exists(self, target_date: date) -> bool:
        """Check if prediction_accuracy has data for the date."""
        query = f"""
        SELECT COUNT(*) as count
        FROM `{ACCURACY_TABLE}`
        WHERE game_date = '{target_date}'
        """

        try:
            result = list(self.bq_client.query(query).result())
            return result[0].count > 0 if result else False
        except Exception as e:
            logger.error(f"Error checking accuracy data: {e}")
            return False

    def _compute_daily_summaries(self, target_date: date) -> List[Dict]:
        """
        Compute aggregated metrics for each system on the given date.
        """
        query = f"""
        SELECT
            game_date,
            system_id,

            -- Volume metrics
            COUNT(*) as predictions_count,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations_count,
            COUNTIF(prediction_correct = TRUE) as correct_count,
            COUNTIF(prediction_correct = FALSE) as incorrect_count,
            COUNTIF(recommendation = 'PASS') as pass_count,

            -- Core accuracy metrics
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                COUNTIF(recommendation IN ('OVER', 'UNDER'))
            ), 3) as win_rate,
            ROUND(AVG(absolute_error), 2) as mae,
            ROUND(AVG(signed_error), 2) as avg_bias,

            -- OVER breakdown
            COUNTIF(recommendation = 'OVER') as over_count,
            COUNTIF(prediction_correct = TRUE AND recommendation = 'OVER') as over_correct,
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE AND recommendation = 'OVER'),
                COUNTIF(recommendation = 'OVER')
            ), 3) as over_win_rate,

            -- UNDER breakdown
            COUNTIF(recommendation = 'UNDER') as under_count,
            COUNTIF(prediction_correct = TRUE AND recommendation = 'UNDER') as under_correct,
            ROUND(SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE AND recommendation = 'UNDER'),
                COUNTIF(recommendation = 'UNDER')
            ), 3) as under_win_rate,

            -- Threshold accuracy
            COUNTIF(within_3_points = TRUE) as within_3_count,
            ROUND(SAFE_DIVIDE(COUNTIF(within_3_points = TRUE), COUNT(*)), 3) as within_3_pct,
            COUNTIF(within_5_points = TRUE) as within_5_count,
            ROUND(SAFE_DIVIDE(COUNTIF(within_5_points = TRUE), COUNT(*)), 3) as within_5_pct,

            -- Confidence analysis (high = >= 0.70)
            ROUND(AVG(confidence_score), 3) as avg_confidence,
            COUNTIF(confidence_score >= 0.70) as high_confidence_count,
            COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE) as high_confidence_correct,
            ROUND(SAFE_DIVIDE(
                COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE),
                COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER'))
            ), 3) as high_confidence_win_rate

        FROM `{ACCURACY_TABLE}`
        WHERE game_date = '{target_date}'
        GROUP BY game_date, system_id
        ORDER BY system_id
        """

        try:
            result = list(self.bq_client.query(query).result())
            summaries = []

            for row in result:
                summary = {
                    'game_date': row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date),
                    'system_id': row.system_id,

                    # Volume
                    'predictions_count': row.predictions_count,
                    'recommendations_count': row.recommendations_count,
                    'correct_count': row.correct_count,
                    'incorrect_count': row.incorrect_count,
                    'pass_count': row.pass_count,

                    # Core accuracy
                    'win_rate': float(row.win_rate) if row.win_rate is not None else None,
                    'mae': float(row.mae) if row.mae is not None else None,
                    'avg_bias': float(row.avg_bias) if row.avg_bias is not None else None,

                    # OVER breakdown
                    'over_count': row.over_count,
                    'over_correct': row.over_correct,
                    'over_win_rate': float(row.over_win_rate) if row.over_win_rate is not None else None,

                    # UNDER breakdown
                    'under_count': row.under_count,
                    'under_correct': row.under_correct,
                    'under_win_rate': float(row.under_win_rate) if row.under_win_rate is not None else None,

                    # Threshold accuracy
                    'within_3_count': row.within_3_count,
                    'within_3_pct': float(row.within_3_pct) if row.within_3_pct is not None else None,
                    'within_5_count': row.within_5_count,
                    'within_5_pct': float(row.within_5_pct) if row.within_5_pct is not None else None,

                    # Confidence
                    'avg_confidence': float(row.avg_confidence) if row.avg_confidence is not None else None,
                    'high_confidence_count': row.high_confidence_count,
                    'high_confidence_correct': row.high_confidence_correct,
                    'high_confidence_win_rate': float(row.high_confidence_win_rate) if row.high_confidence_win_rate is not None else None,

                    # Metadata
                    'computed_at': datetime.now(timezone.utc).isoformat()
                }
                summaries.append(summary)

            return summaries

        except Exception as e:
            logger.error(f"Error computing daily summaries: {e}")
            return []

    def _write_summaries(self, summaries: List[Dict], target_date: date) -> int:
        """
        Write summaries to BigQuery with idempotency (DELETE + INSERT).

        Args:
            summaries: List of summary dicts to write
            target_date: Date being processed

        Returns:
            Number of records written
        """
        if not summaries:
            return 0

        try:
            # IDEMPOTENCY: Delete existing records for this date
            delete_query = f"""
            DELETE FROM `{DAILY_PERF_TABLE}`
            WHERE game_date = '{target_date}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result()
            deleted = delete_job.num_dml_affected_rows or 0
            if deleted > 0:
                logger.info(f"  Deleted {deleted} existing records for {target_date}")

            # Insert using batch loading
            table_ref = self.bq_client.get_table(DAILY_PERF_TABLE)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                summaries,
                DAILY_PERF_TABLE,
                job_config=job_config
            )
            load_job.result()

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            return load_job.output_rows or len(summaries)

        except Exception as e:
            logger.error(f"Error writing summaries: {e}")
            return 0

    def get_dates_with_accuracy_data(
        self,
        start_date: date,
        end_date: date
    ) -> List[date]:
        """
        Get list of dates that have prediction_accuracy data.

        Useful for backfill to skip dates without data.
        """
        query = f"""
        SELECT DISTINCT game_date
        FROM `{ACCURACY_TABLE}`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ORDER BY game_date
        """

        try:
            result = list(self.bq_client.query(query).result())
            return [
                row.game_date if isinstance(row.game_date, date) else row.game_date.date()
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error getting dates with accuracy data: {e}")
            return []


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Aggregate prediction accuracy into system daily performance'
    )
    parser.add_argument(
        '--date', type=str,
        help='Date to process (YYYY-MM-DD). Defaults to yesterday.'
    )
    parser.add_argument(
        '--start-date', type=str,
        help='Start date for range processing (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date', type=str,
        help='End date for range processing (YYYY-MM-DD)'
    )

    args = parser.parse_args()
    processor = SystemDailyPerformanceProcessor()

    # Range processing
    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        result = processor.process_date_range(start, end)
        print(f"Result: {result}")
        return result

    # Single date processing
    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    result = processor.process(target_date)
    print(f"Result: {result}")
    return result


if __name__ == '__main__':
    main()
