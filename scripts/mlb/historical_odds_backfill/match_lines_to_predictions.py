#!/usr/bin/env python3
"""
Phase 3: Match Betting Lines to Predictions

Updates the pitcher_strikeouts predictions table with consensus betting lines
from the historical odds data.

Matching Logic:
1. Group betting lines by player_lookup + game_date
2. Calculate consensus line as median across bookmakers
3. Update predictions that have NULL strikeouts_line

Usage:
    # Dry-run to see what would be matched
    python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py --dry-run

    # Execute the match
    python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py

    # Match specific date range
    python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py \
        --start-date 2024-06-01 --end-date 2024-06-30
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Dict

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

# SQL function to normalize player names for matching
# Handles: underscores, hyphens, and common accented characters
NORMALIZE_SQL = """
LOWER(
    TRANSLATE(
        REPLACE(REPLACE({col}, '_', ''), '-', ''),
        'áàâäãåéèêëíìîïóòôöõúùûüñç',
        'aaaaaaeeeeiiiiooooouuuunc'
    )
)
"""


def normalize_sql(column_name: str) -> str:
    """Generate SQL to normalize a player name column."""
    return NORMALIZE_SQL.format(col=column_name)


class LineMatcher:
    """Matches betting lines to predictions."""

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

    def get_coverage_stats(self) -> Dict:
        """Get statistics on prediction coverage."""
        pred_norm = normalize_sql('pitcher_lookup')
        odds_norm = normalize_sql('player_lookup')

        query = f"""
        -- NOTE: predictions use underscore format (logan_webb) while odds use no-underscore (loganwebb)
        -- Also handles: hyphens (smith-shawver) and accents (rodón)
        -- We normalize both using TRANSLATE to remove accents and special chars
        WITH predictions AS (
            SELECT
                game_date,
                pitcher_lookup,
                {pred_norm} as pitcher_lookup_normalized,
                strikeouts_line,
                line_source
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        ),
        odds AS (
            SELECT DISTINCT
                game_date,
                player_lookup,
                {odds_norm} as player_lookup_normalized
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE market_key = 'pitcher_strikeouts'
              AND game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND source_file_path LIKE '%pitcher-props-history%'
        )
        SELECT
            COUNT(*) as total_predictions,
            SUM(CASE WHEN p.strikeouts_line IS NOT NULL THEN 1 ELSE 0 END) as has_line,
            SUM(CASE WHEN p.strikeouts_line IS NULL THEN 1 ELSE 0 END) as missing_line,
            SUM(CASE WHEN o.player_lookup_normalized IS NOT NULL THEN 1 ELSE 0 END) as matchable,
            SUM(CASE WHEN p.strikeouts_line IS NULL AND o.player_lookup_normalized IS NOT NULL THEN 1 ELSE 0 END) as will_update
        FROM predictions p
        LEFT JOIN odds o ON p.game_date = o.game_date AND p.pitcher_lookup_normalized = o.player_lookup_normalized
        """

        result = list(self.bq_client.query(query).result())[0]

        return {
            'total_predictions': result.total_predictions,
            'has_line': result.has_line,
            'missing_line': result.missing_line,
            'matchable': result.matchable,
            'will_update': result.will_update,
        }

    def get_sample_matches(self, limit: int = 10) -> list:
        """Get sample of matches for review."""
        pred_norm = normalize_sql('p.pitcher_lookup')
        odds_norm = normalize_sql('player_lookup')

        query = f"""
        -- Normalize player names: remove underscores, hyphens, and accents
        WITH consensus_lines AS (
            SELECT
                game_date,
                player_lookup,
                {odds_norm} as player_lookup_normalized,
                APPROX_QUANTILES(point, 2)[OFFSET(1)] as consensus_line,
                COUNT(DISTINCT bookmaker) as bookmaker_count,
                MIN(point) as min_line,
                MAX(point) as max_line
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE market_key = 'pitcher_strikeouts'
              AND game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND source_file_path LIKE '%pitcher-props-history%'
            GROUP BY game_date, player_lookup
        )
        SELECT
            p.game_date,
            p.pitcher_lookup,
            p.predicted_strikeouts,
            p.strikeouts_line as current_line,
            o.consensus_line as new_line,
            o.bookmaker_count,
            o.min_line,
            o.max_line
        FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
        JOIN consensus_lines o
            ON p.game_date = o.game_date
            AND {pred_norm} = o.player_lookup_normalized
        WHERE p.strikeouts_line IS NULL
        ORDER BY p.game_date DESC
        LIMIT {limit}
        """

        return [dict(row) for row in self.bq_client.query(query).result()]

    def execute_match(self) -> int:
        """Execute the UPDATE to match lines to predictions."""
        # Normalization for matching: removes underscores, hyphens, and accents
        odds_norm = normalize_sql('player_lookup')
        pred_norm = normalize_sql('p.pitcher_lookup')

        # First, create a temp table with consensus lines
        # Include normalized player_lookup for matching
        create_temp_query = f"""
        CREATE OR REPLACE TEMP TABLE consensus_lines AS
        SELECT
            game_date,
            player_lookup,
            {odds_norm} as player_lookup_normalized,
            APPROX_QUANTILES(point, 2)[OFFSET(1)] as consensus_line
        FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
        WHERE market_key = 'pitcher_strikeouts'
          AND game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND source_file_path LIKE '%pitcher-props-history%'
        GROUP BY game_date, player_lookup
        """

        # Then update predictions - match using normalized lookup
        update_query = f"""
        UPDATE `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts` p
        SET
            strikeouts_line = o.consensus_line,
            line_source = 'historical_odds_api'
        FROM consensus_lines o
        WHERE {pred_norm} = o.player_lookup_normalized
          AND p.game_date = o.game_date
          AND p.game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND p.strikeouts_line IS NULL
        """

        # Execute as a script
        full_script = f"{create_temp_query};\n{update_query}"

        logger.info("Executing line matching...")

        job = self.bq_client.query(full_script)
        result = job.result()

        # Get rows affected (from the UPDATE statement)
        rows_updated = job.num_dml_affected_rows or 0

        return rows_updated

    def run(self) -> Dict:
        """Execute the matching process."""
        logger.info("=" * 70)
        logger.info("PHASE 3: MATCH BETTING LINES TO PREDICTIONS")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("")

        # Get coverage stats
        logger.info("Checking coverage...")
        stats = self.get_coverage_stats()

        logger.info(f"\nPrediction Coverage:")
        logger.info(f"  Total predictions: {stats['total_predictions']:,}")
        logger.info(f"  Already have line: {stats['has_line']:,}")
        logger.info(f"  Missing line: {stats['missing_line']:,}")
        logger.info(f"  Matchable from odds: {stats['matchable']:,}")
        logger.info(f"  Will be updated: {stats['will_update']:,}")

        coverage_pct = (stats['matchable'] / stats['total_predictions'] * 100) if stats['total_predictions'] > 0 else 0
        logger.info(f"  Coverage: {coverage_pct:.1f}%")

        if self.dry_run:
            logger.info("\n" + "-" * 70)
            logger.info("DRY RUN - Sample matches:")
            logger.info("-" * 70)

            samples = self.get_sample_matches(10)
            for s in samples:
                logger.info(
                    f"  {s['game_date']} | {s['pitcher_lookup'][:20]:<20} | "
                    f"pred={s['predicted_strikeouts']:.1f} → line={s['new_line']:.1f} "
                    f"({s['bookmaker_count']} books)"
                )

            logger.info("\nRun without --dry-run to execute the update")
            return stats

        # Execute the match
        logger.info("\nExecuting match...")
        rows_updated = self.execute_match()

        logger.info("\n" + "=" * 70)
        logger.info("PHASE 3 COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Predictions updated: {rows_updated:,}")

        # Verify update
        post_stats = self.get_coverage_stats()
        logger.info(f"Predictions with lines now: {post_stats['has_line']:,}")
        logger.info(f"Predictions still missing: {post_stats['missing_line']:,}")

        logger.info("\n" + "-" * 70)
        logger.info("NEXT STEPS:")
        logger.info("-" * 70)
        logger.info("1. Run Phase 4 - Grade predictions:")
        logger.info("   python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py")
        logger.info("")
        logger.info("2. Run Phase 5 - Calculate hit rate:")
        logger.info("   python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py")

        return {**stats, 'rows_updated': rows_updated}


def main():
    parser = argparse.ArgumentParser(
        description='Match betting lines to predictions',
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
        help='Show what would be matched without updating'
    )

    args = parser.parse_args()

    matcher = LineMatcher(
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
    )

    try:
        matcher.run()
    except Exception as e:
        logger.exception(f"Matching failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
