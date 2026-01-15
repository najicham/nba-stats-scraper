#!/usr/bin/env python3
"""
Bookmaker-Level Hit Rate Analysis

Analyzes betting performance by bookmaker to identify:
- Which books have the most beatable lines
- Line comparison across books
- Best book for OVER vs UNDER bets

Usage:
    python scripts/mlb/historical_odds_backfill/analyze_by_bookmaker.py
"""

import argparse
import json
import logging
import math
import sys
from datetime import datetime
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
BREAKEVEN_RATE = 52.38


def calculate_wilson_ci(wins: int, n: int) -> tuple:
    """Calculate Wilson score 95% CI."""
    if n == 0:
        return (0.0, 0.0)

    z = 1.96
    p = wins / n

    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

    lower = max(0, center - spread) * 100
    upper = min(1, center + spread) * 100

    return (round(lower, 2), round(upper, 2))


def calculate_roi(hit_rate: float) -> float:
    """Calculate ROI at -110 odds."""
    ev = (hit_rate * 100) - ((1 - hit_rate) * 110)
    return round(ev / 110 * 100, 2)


class BookmakerAnalyzer:
    """Analyzes betting performance by bookmaker."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        self.start_date = start_date or '2024-04-09'
        self.end_date = end_date or '2025-09-28'
        self.bq_client = bigquery.Client(project=PROJECT_ID)

    def get_bookmaker_stats(self) -> List[Dict]:
        """Get hit rate statistics by bookmaker."""
        # This query joins odds data with prediction outcomes
        # to see if we perform differently vs different books
        query = f"""
        WITH book_lines AS (
            SELECT
                game_date,
                player_lookup,
                bookmaker,
                point as line,
                ROW_NUMBER() OVER (
                    PARTITION BY game_date, player_lookup, bookmaker
                    ORDER BY scraped_at DESC
                ) as rn
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE market_key = 'pitcher_strikeouts'
              AND game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND source_file_path LIKE '%pitcher-props-history%'
        ),
        latest_lines AS (
            SELECT game_date, player_lookup, bookmaker, line
            FROM book_lines
            WHERE rn = 1
        ),
        predictions AS (
            SELECT
                game_date,
                pitcher_lookup,
                predicted_strikeouts,
                actual_strikeouts,
                recommendation,
                is_correct
            FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND line_source = 'historical_odds_api'
              AND recommendation IN ('OVER', 'UNDER')
              AND is_correct IS NOT NULL
        )
        SELECT
            l.bookmaker,
            COUNT(*) as total_lines,
            SUM(CASE WHEN p.recommendation = 'OVER' AND p.actual_strikeouts > l.line THEN 1
                     WHEN p.recommendation = 'UNDER' AND p.actual_strikeouts < l.line THEN 1
                     ELSE 0 END) as wins,
            SUM(CASE WHEN p.recommendation = 'OVER' AND p.actual_strikeouts < l.line THEN 1
                     WHEN p.recommendation = 'UNDER' AND p.actual_strikeouts > l.line THEN 1
                     ELSE 0 END) as losses,
            AVG(l.line) as avg_line,
            AVG(CASE WHEN p.recommendation = 'OVER' THEN l.line END) as avg_over_line,
            AVG(CASE WHEN p.recommendation = 'UNDER' THEN l.line END) as avg_under_line
        FROM latest_lines l
        INNER JOIN predictions p
            ON l.game_date = p.game_date
            AND l.player_lookup = p.pitcher_lookup
        GROUP BY l.bookmaker
        HAVING COUNT(*) >= 50
        ORDER BY COUNT(*) DESC
        """

        results = list(self.bq_client.query(query).result())
        bookmakers = []

        for row in results:
            total = row.wins + row.losses
            hit_rate = row.wins / total * 100 if total > 0 else 0
            hit_rate_decimal = row.wins / total if total > 0 else 0

            ci = calculate_wilson_ci(row.wins, total)
            roi = calculate_roi(hit_rate_decimal)

            bookmakers.append({
                'bookmaker': row.bookmaker,
                'total_lines': row.total_lines,
                'wins': row.wins,
                'losses': row.losses,
                'hit_rate': round(hit_rate, 2),
                'ci': ci,
                'roi': roi,
                'avg_line': round(row.avg_line, 2) if row.avg_line else 0,
                'avg_over_line': round(row.avg_over_line, 2) if row.avg_over_line else 0,
                'avg_under_line': round(row.avg_under_line, 2) if row.avg_under_line else 0,
                'is_profitable': hit_rate > BREAKEVEN_RATE,
            })

        return bookmakers

    def get_line_spread_analysis(self) -> Dict:
        """Analyze line spread across bookmakers for same games."""
        query = f"""
        WITH book_lines AS (
            SELECT
                game_date,
                player_lookup,
                bookmaker,
                point as line
            FROM `{PROJECT_ID}.mlb_raw.oddsa_pitcher_props`
            WHERE market_key = 'pitcher_strikeouts'
              AND game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND source_file_path LIKE '%pitcher-props-history%'
        ),
        line_spreads AS (
            SELECT
                game_date,
                player_lookup,
                MAX(line) - MIN(line) as line_spread,
                COUNT(DISTINCT bookmaker) as num_books,
                MAX(line) as max_line,
                MIN(line) as min_line
            FROM book_lines
            GROUP BY game_date, player_lookup
            HAVING COUNT(DISTINCT bookmaker) >= 2
        )
        SELECT
            COUNT(*) as total_games,
            AVG(line_spread) as avg_spread,
            MAX(line_spread) as max_spread,
            AVG(num_books) as avg_books_per_game,
            SUM(CASE WHEN line_spread > 0.5 THEN 1 ELSE 0 END) as games_with_big_spread
        FROM line_spreads
        """

        result = list(self.bq_client.query(query).result())
        if not result:
            return {}

        row = result[0]
        return {
            'total_games': row.total_games,
            'avg_spread': round(row.avg_spread, 3) if row.avg_spread else 0,
            'max_spread': round(row.max_spread, 2) if row.max_spread else 0,
            'avg_books_per_game': round(row.avg_books_per_game, 1) if row.avg_books_per_game else 0,
            'games_with_big_spread': row.games_with_big_spread or 0,
        }

    def run(self, output_json: bool = False) -> Dict:
        """Run the bookmaker analysis."""
        logger.info("=" * 70)
        logger.info("BOOKMAKER-LEVEL HIT RATE ANALYSIS")
        logger.info("=" * 70)
        logger.info(f"Date range: {self.start_date} to {self.end_date}")
        logger.info("")

        # Get bookmaker stats
        bookmakers = self.get_bookmaker_stats()
        logger.info(f"Found {len(bookmakers)} bookmakers with >= 50 matched lines")

        # Get line spread analysis
        spread_analysis = self.get_line_spread_analysis()

        results = {
            'date_range': {'start': self.start_date, 'end': self.end_date},
            'analysis_timestamp': datetime.now().isoformat(),
            'bookmakers': bookmakers,
            'line_spread_analysis': spread_analysis,
        }

        if output_json:
            print(json.dumps(results, indent=2, default=str))
            return results

        if not bookmakers:
            logger.warning("No bookmaker data available yet.")
            logger.info("This analysis requires the backfill to complete first.")
            return results

        # Pretty print
        logger.info("\n" + "=" * 70)
        logger.info("HIT RATE BY BOOKMAKER")
        logger.info("=" * 70)
        logger.info("")
        logger.info(f"{'Bookmaker':<20} | {'Lines':>6} | {'Hit Rate':>10} | {'ROI':>8} | {'95% CI':>18}")
        logger.info("-" * 70)

        for b in sorted(bookmakers, key=lambda x: x['hit_rate'], reverse=True):
            ci_str = f"[{b['ci'][0]:.1f}%-{b['ci'][1]:.1f}%]"
            profitable = "★" if b['is_profitable'] else " "
            logger.info(
                f"{b['bookmaker']:<20} | {b['total_lines']:>6} | {b['hit_rate']:>9.2f}% | "
                f"{b['roi']:>+7.2f}% | {ci_str:>17} {profitable}"
            )

        # Line spread analysis
        if spread_analysis:
            logger.info("\n" + "=" * 70)
            logger.info("LINE SPREAD ANALYSIS")
            logger.info("=" * 70)
            logger.info(f"  Total games with multiple books: {spread_analysis['total_games']:,}")
            logger.info(f"  Avg books per game: {spread_analysis['avg_books_per_game']:.1f}")
            logger.info(f"  Avg line spread: {spread_analysis['avg_spread']:.3f}K")
            logger.info(f"  Max line spread: {spread_analysis['max_spread']:.2f}K")
            logger.info(f"  Games with spread > 0.5K: {spread_analysis['games_with_big_spread']:,}")

            if spread_analysis['games_with_big_spread'] > 0:
                pct = spread_analysis['games_with_big_spread'] / spread_analysis['total_games'] * 100
                logger.info(f"  Line shopping opportunity: {pct:.1f}% of games")

        # Recommendations
        logger.info("\n" + "=" * 70)
        logger.info("RECOMMENDATIONS")
        logger.info("=" * 70)

        best = max(bookmakers, key=lambda x: x['hit_rate']) if bookmakers else None
        worst = min(bookmakers, key=lambda x: x['hit_rate']) if bookmakers else None

        if best:
            logger.info(f"\n  Best book to bet against: {best['bookmaker']}")
            logger.info(f"    Hit rate: {best['hit_rate']:.2f}%")
            logger.info(f"    ROI: {best['roi']:+.2f}%")

        if worst:
            logger.info(f"\n  Toughest book to beat: {worst['bookmaker']}")
            logger.info(f"    Hit rate: {worst['hit_rate']:.2f}%")
            logger.info(f"    ROI: {worst['roi']:+.2f}%")

        # Save results
        output_dir = PROJECT_ROOT / 'docs/08-projects/current/mlb-pitcher-strikeouts'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / 'BOOKMAKER-ANALYSIS-RESULTS.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\nResults saved to: {output_file}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description='Analyze hit rate by bookmaker',
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
        '--json',
        action='store_true',
        help='Output as JSON'
    )

    args = parser.parse_args()

    analyzer = BookmakerAnalyzer(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    try:
        analyzer.run(output_json=args.json)
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
