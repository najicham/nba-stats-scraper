#!/usr/bin/env python3
"""
Fast V1.6 MLB Pitcher Strikeout Grading Script

Uses BigQuery MERGE for bulk updates instead of individual UPDATEs.
This is orders of magnitude faster for large datasets.

Usage:
    PYTHONPATH=. python scripts/mlb/grade_v16_predictions_fast.py
    PYTHONPATH=. python scripts/mlb/grade_v16_predictions_fast.py --start-date 2024-04-09 --end-date 2025-09-28
"""

import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, List
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
PREDICTIONS_TABLE = "mlb_predictions.pitcher_strikeouts"
TEMP_TABLE = "mlb_predictions.pitcher_strikeouts_grading_temp"


class FastV16Grader:
    """Fast grading using BigQuery MERGE."""

    def __init__(self, model_version_filter: str = "v1_6"):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.model_version_filter = model_version_filter

    def grade_date_range(self, start_date: str, end_date: str) -> Dict:
        """Grade all V1.6 predictions using bulk MERGE."""
        logger.info(f"Grading V1.6 predictions from {start_date} to {end_date}")

        # Step 1: Create temp table with grading results
        logger.info("Creating temporary table with grading results...")
        self._create_grading_temp_table(start_date, end_date)

        # Step 2: Get count of records to update
        count = self._get_temp_table_count()
        logger.info(f"Prepared {count} predictions for grading")

        # Step 3: Merge temp table into main table
        logger.info("Merging grading results into main table...")
        updated_count = self._merge_grading_results()
        logger.info(f"Successfully updated {updated_count} predictions")

        # Step 4: Cleanup temp table
        logger.info("Cleaning up temporary table...")
        self._drop_temp_table()

        # Step 5: Get final stats
        stats = self._get_final_stats()

        return stats

    def _create_grading_temp_table(self, start_date: str, end_date: str):
        """Create temp table with grading results using a single query."""
        query = f"""
        CREATE OR REPLACE TABLE `{PROJECT_ID}.{TEMP_TABLE}` AS
        WITH predictions AS (
            SELECT
                prediction_id,
                game_date,
                pitcher_lookup,
                strikeouts_line,
                recommendation
            FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND model_version LIKE '%{self.model_version_filter}%'
              AND is_correct IS NULL  -- Only ungraded
        ),
        actuals AS (
            SELECT DISTINCT
                game_date,
                player_lookup,
                strikeouts
            FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND is_starter = TRUE
              AND strikeouts IS NOT NULL
        )
        SELECT
            p.prediction_id,
            a.strikeouts AS actual_strikeouts,
            CASE
                WHEN p.recommendation = 'OVER' AND a.strikeouts > p.strikeouts_line THEN TRUE
                WHEN p.recommendation = 'OVER' AND a.strikeouts < p.strikeouts_line THEN FALSE
                WHEN p.recommendation = 'UNDER' AND a.strikeouts < p.strikeouts_line THEN TRUE
                WHEN p.recommendation = 'UNDER' AND a.strikeouts > p.strikeouts_line THEN FALSE
                ELSE NULL  -- Push or no recommendation
            END AS is_correct,
            CURRENT_TIMESTAMP() AS graded_at
        FROM predictions p
        INNER JOIN actuals a
            ON p.game_date = a.game_date
            AND p.pitcher_lookup = a.player_lookup
        WHERE a.strikeouts IS NOT NULL
        """

        self.bq_client.query(query).result()
        logger.info("Temporary table created successfully")

    def _get_temp_table_count(self) -> int:
        """Get count of records in temp table."""
        query = f"SELECT COUNT(*) as cnt FROM `{PROJECT_ID}.{TEMP_TABLE}`"
        result = self.bq_client.query(query).result()
        for row in result:
            return row.cnt
        return 0

    def _merge_grading_results(self) -> int:
        """Merge grading results from temp table into main table."""
        query = f"""
        MERGE `{PROJECT_ID}.{PREDICTIONS_TABLE}` T
        USING `{PROJECT_ID}.{TEMP_TABLE}` S
        ON T.prediction_id = S.prediction_id
        WHEN MATCHED THEN
            UPDATE SET
                actual_strikeouts = S.actual_strikeouts,
                is_correct = S.is_correct,
                graded_at = S.graded_at
        """

        job = self.bq_client.query(query)
        result = job.result()

        # Get number of rows modified
        return job.num_dml_affected_rows

    def _drop_temp_table(self):
        """Drop the temporary table."""
        query = f"DROP TABLE IF EXISTS `{PROJECT_ID}.{TEMP_TABLE}`"
        self.bq_client.query(query).result()
        logger.info("Temporary table dropped")

    def _get_final_stats(self) -> Dict:
        """Get final grading statistics."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
            COUNTIF(is_correct IS NOT NULL) as graded,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            COUNTIF(is_correct IS NULL AND actual_strikeouts IS NOT NULL) as pushes,
            ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNTIF(is_correct IS NOT NULL)) * 100, 1) as win_rate,
            ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
        FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
        WHERE model_version LIKE '%{self.model_version_filter}%'
        """

        result = self.bq_client.query(query).result()
        for row in result:
            return {
                'total': row.total,
                'actionable': row.actionable,
                'graded': row.graded,
                'wins': row.wins,
                'losses': row.losses,
                'pushes': row.pushes,
                'win_rate': row.win_rate,
                'mae': row.mae,
            }
        return {}


def print_summary(stats: Dict):
    """Print grading summary."""
    print()
    print("=" * 80)
    print(" V1.6 GRADING SUMMARY")
    print("=" * 80)
    print(f"Total V1.6 predictions: {stats.get('total', 0)}")
    print(f"Actionable (OVER/UNDER): {stats.get('actionable', 0)}")
    print(f"Graded: {stats.get('graded', 0)}")
    print()
    print(f"Results:")
    print(f"  Wins: {stats.get('wins', 0)}")
    print(f"  Losses: {stats.get('losses', 0)}")
    print(f"  Pushes: {stats.get('pushes', 0)}")
    print()
    print(f"Win Rate: {stats.get('win_rate', 0)}%")
    print(f"MAE: {stats.get('mae', 0)}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='Fast grade V1.6 MLB predictions')
    parser.add_argument('--start-date', default='2024-04-09', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2025-09-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--model-version-filter', default='v1_6', help='Model version filter')
    args = parser.parse_args()

    print("=" * 80)
    print(" FAST GRADE V1.6 MLB PREDICTIONS")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Model filter: {args.model_version_filter}")
    print()

    # Create grader and run
    grader = FastV16Grader(model_version_filter=args.model_version_filter)
    stats = grader.grade_date_range(args.start_date, args.end_date)

    # Print summary
    print_summary(stats)

    print()
    print("Next steps:")
    print("  1. Verify V1 unchanged: PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py")
    print("  2. Compare V1 vs V1.6: PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py")
    print()


if __name__ == '__main__':
    main()
