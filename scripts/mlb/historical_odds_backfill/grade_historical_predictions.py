#!/usr/bin/env python3
"""
Phase 4: Grade Historical Predictions

Grades MLB pitcher strikeout predictions against actual game results.
Uses the MlbPredictionGradingProcessor to update is_correct and actual_strikeouts.

Usage:
    # Grade all predictions with lines
    python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py

    # Grade specific date range
    python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py \
        --start-date 2024-06-01 --end-date 2024-06-30

    # Dry-run to see what would be graded
    python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class HistoricalGrader:
    """Grades historical predictions in batch."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.dry_run = dry_run
        self.bq_client = bigquery.Client(project=PROJECT_ID)

        # Stats
        self.stats = {
            'predictions_checked': 0,
            'predictions_graded': 0,
            'correct': 0,
            'incorrect': 0,
            'push': 0,
            'no_actual': 0,
        }

    def get_ungraded_dates(self) -> List[str]:
        """Get dates with ungraded predictions that have lines."""
        query = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND strikeouts_line IS NOT NULL
          AND is_correct IS NULL
        ORDER BY game_date
        """

        return [row.game_date.strftime('%Y-%m-%d')
                for row in self.bq_client.query(query).result()]

    def get_grading_preview(self) -> Dict:
        """Get preview of grading stats."""
        query = f"""
        WITH predictions AS (
            SELECT
                p.game_date,
                p.pitcher_lookup,
                p.strikeouts_line,
                p.recommendation,
                p.is_correct,
                a.strikeouts as actual_k
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
            LEFT JOIN `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` a
                ON p.game_date = a.game_date
                AND p.pitcher_lookup = a.player_lookup
                AND a.is_starter = TRUE
            WHERE p.game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND p.strikeouts_line IS NOT NULL
              AND p.line_source = 'historical_odds_api'
        )
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) as already_graded,
            SUM(CASE WHEN is_correct IS NULL AND actual_k IS NOT NULL THEN 1 ELSE 0 END) as can_grade,
            SUM(CASE WHEN is_correct IS NULL AND actual_k IS NULL THEN 1 ELSE 0 END) as no_actual,
            -- Preview grading
            SUM(CASE
                WHEN is_correct IS NULL AND actual_k IS NOT NULL AND recommendation = 'OVER' AND actual_k > strikeouts_line THEN 1
                WHEN is_correct IS NULL AND actual_k IS NOT NULL AND recommendation = 'UNDER' AND actual_k < strikeouts_line THEN 1
                ELSE 0
            END) as would_be_correct,
            SUM(CASE
                WHEN is_correct IS NULL AND actual_k IS NOT NULL AND recommendation = 'OVER' AND actual_k < strikeouts_line THEN 1
                WHEN is_correct IS NULL AND actual_k IS NOT NULL AND recommendation = 'UNDER' AND actual_k > strikeouts_line THEN 1
                ELSE 0
            END) as would_be_incorrect,
            SUM(CASE
                WHEN is_correct IS NULL AND actual_k IS NOT NULL AND actual_k = strikeouts_line THEN 1
                ELSE 0
            END) as would_be_push
        FROM predictions
        """

        result = list(self.bq_client.query(query).result())[0]

        return {
            'total': result.total,
            'already_graded': result.already_graded,
            'can_grade': result.can_grade,
            'no_actual': result.no_actual,
            'would_be_correct': result.would_be_correct,
            'would_be_incorrect': result.would_be_incorrect,
            'would_be_push': result.would_be_push,
        }

    def execute_grading(self) -> int:
        """Execute batch grading update."""
        # Grade OVER predictions
        over_query = f"""
        UPDATE `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
        SET
            actual_strikeouts = a.strikeouts,
            is_correct = CASE
                WHEN a.strikeouts > p.strikeouts_line THEN TRUE
                WHEN a.strikeouts < p.strikeouts_line THEN FALSE
                ELSE NULL  -- Push
            END,
            graded_at = CURRENT_TIMESTAMP()
        FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` a
        WHERE p.pitcher_lookup = a.player_lookup
          AND p.game_date = a.game_date
          AND a.is_starter = TRUE
          AND p.game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND p.strikeouts_line IS NOT NULL
          AND p.line_source = 'historical_odds_api'
          AND p.recommendation = 'OVER'
          AND p.is_correct IS NULL
        """

        # Grade UNDER predictions
        under_query = f"""
        UPDATE `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
        SET
            actual_strikeouts = a.strikeouts,
            is_correct = CASE
                WHEN a.strikeouts < p.strikeouts_line THEN TRUE
                WHEN a.strikeouts > p.strikeouts_line THEN FALSE
                ELSE NULL  -- Push
            END,
            graded_at = CURRENT_TIMESTAMP()
        FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` a
        WHERE p.pitcher_lookup = a.player_lookup
          AND p.game_date = a.game_date
          AND a.is_starter = TRUE
          AND p.game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND p.strikeouts_line IS NOT NULL
          AND p.line_source = 'historical_odds_api'
          AND p.recommendation = 'UNDER'
          AND p.is_correct IS NULL
        """

        logger.info("Grading OVER predictions...")
        over_job = self.bq_client.query(over_query)
        over_job.result()
        over_updated = over_job.num_dml_affected_rows or 0
        logger.info(f"  Updated {over_updated} OVER predictions")

        logger.info("Grading UNDER predictions...")
        under_job = self.bq_client.query(under_query)
        under_job.result()
        under_updated = under_job.num_dml_affected_rows or 0
        logger.info(f"  Updated {under_updated} UNDER predictions")

        return over_updated + under_updated

    def get_grading_results(self) -> Dict:
        """Get final grading results."""
        query = f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as incorrect,
            SUM(CASE WHEN actual_strikeouts = strikeouts_line AND recommendation IN ('OVER', 'UNDER') THEN 1 ELSE 0 END) as push,
            SUM(CASE WHEN recommendation = 'PASS' THEN 1 ELSE 0 END) as pass_recs
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND line_source = 'historical_odds_api'
        """

        result = list(self.bq_client.query(query).result())[0]

        return {
            'total': result.total,
            'correct': result.correct,
            'incorrect': result.incorrect,
            'push': result.push,
            'pass_recs': result.pass_recs,
        }

    def run(self) -> Dict:
        """Execute the grading process."""
        logger.info("=" * 70)
        logger.info("PHASE 4: GRADE HISTORICAL PREDICTIONS")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("")

        # Get preview
        logger.info("Checking predictions to grade...")
        preview = self.get_grading_preview()

        logger.info(f"\nGrading Preview:")
        logger.info(f"  Total with historical lines: {preview['total']:,}")
        logger.info(f"  Already graded: {preview['already_graded']:,}")
        logger.info(f"  Can be graded now: {preview['can_grade']:,}")
        logger.info(f"  Missing actuals: {preview['no_actual']:,}")
        logger.info("")
        logger.info(f"  Would be correct: {preview['would_be_correct']:,}")
        logger.info(f"  Would be incorrect: {preview['would_be_incorrect']:,}")
        logger.info(f"  Would be push: {preview['would_be_push']:,}")

        if preview['can_grade'] > 0:
            preview_rate = preview['would_be_correct'] / (preview['would_be_correct'] + preview['would_be_incorrect']) * 100
            logger.info(f"  Preview hit rate: {preview_rate:.1f}%")

        if self.dry_run:
            logger.info("\nRun without --dry-run to execute grading")
            return preview

        # Execute grading
        logger.info("\nExecuting grading...")
        rows_updated = self.execute_grading()

        # Get final results
        results = self.get_grading_results()

        logger.info("\n" + "=" * 70)
        logger.info("PHASE 4 COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Predictions graded: {rows_updated:,}")
        logger.info(f"  Correct: {results['correct']:,}")
        logger.info(f"  Incorrect: {results['incorrect']:,}")
        logger.info(f"  Push: {results['push']:,}")

        if results['correct'] + results['incorrect'] > 0:
            hit_rate = results['correct'] / (results['correct'] + results['incorrect']) * 100
            logger.info(f"\nHit Rate: {hit_rate:.2f}%")

        logger.info("\n" + "-" * 70)
        logger.info("NEXT STEPS:")
        logger.info("-" * 70)
        logger.info("Run Phase 5 - Calculate comprehensive hit rate:")
        logger.info("  python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py")

        return results


def main():
    parser = argparse.ArgumentParser(
        description='Grade historical predictions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD). Default: 2024-04-09'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD). Default: 2025-09-28'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be graded without updating'
    )

    args = parser.parse_args()

    grader = HistoricalGrader(
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
    )

    try:
        grader.run()
    except Exception as e:
        logger.exception(f"Grading failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
