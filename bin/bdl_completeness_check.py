#!/usr/bin/env python3
"""
BDL Completeness Checker

Finds games that have NBAC (NBA.com) data but are missing BDL data.
This is used to determine which dates need BDL retry scrapes.

Usage:
    # Check last 3 days (default)
    python bin/bdl_completeness_check.py

    # Check last 7 days
    python bin/bdl_completeness_check.py --days 7

    # Output as JSON (for automation)
    python bin/bdl_completeness_check.py --json

    # Only show dates with missing games
    python bin/bdl_completeness_check.py --dates-only

Created: January 22, 2026
Purpose: Support BDL catch-up workflow by identifying gaps
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_bdl_gaps(lookback_days: int = 3) -> List[Dict]:
    """
    Find games that have NBAC data but missing BDL data.

    Returns a list of dicts with:
    - game_date: The date with missing data
    - matchup: "AWAY @ HOME"
    - home_team, away_team: Team abbreviations
    - has_nbac: True (always, since we're filtering for NBAC present)
    - has_bdl: False (always, since we're finding gaps)
    - nbac_player_count: Number of player rows in NBAC
    - hours_since_game_end: How long ago the game ended
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        query = """
        WITH
        -- Get schedule for last N days
        schedule AS (
            SELECT
                game_id,
                game_date,
                home_team_tricode,
                away_team_tricode,
                game_date_est AS game_start_time,
                TIMESTAMP_ADD(game_date_est, INTERVAL 150 MINUTE) AS estimated_game_end,
                arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') AS is_west_coast
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
              AND game_date < CURRENT_DATE()  -- Exclude today (games may not have finished)
              AND season_year = 2025
              AND game_status = 3  -- Final games only
        ),

        -- Check which games have NBAC player data
        nbac_games AS (
            SELECT
                game_date,
                home_team_abbr,
                away_team_abbr,
                COUNT(*) AS nbac_player_count
            FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
            GROUP BY game_date, home_team_abbr, away_team_abbr
        ),

        -- Check which games have BDL player data
        bdl_games AS (
            SELECT
                game_date,
                home_team_abbr,
                away_team_abbr,
                COUNT(*) AS bdl_player_count
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
            GROUP BY game_date, home_team_abbr, away_team_abbr
        )

        -- Find games with NBAC but missing BDL
        SELECT
            s.game_date,
            CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) AS matchup,
            s.home_team_tricode AS home_team,
            s.away_team_tricode AS away_team,
            s.is_west_coast,
            s.estimated_game_end,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.estimated_game_end, HOUR) AS hours_since_game_end,
            TRUE AS has_nbac,
            COALESCE(n.nbac_player_count, 0) AS nbac_player_count,
            CASE WHEN b.bdl_player_count IS NOT NULL THEN TRUE ELSE FALSE END AS has_bdl,
            COALESCE(b.bdl_player_count, 0) AS bdl_player_count
        FROM schedule s
        LEFT JOIN nbac_games n
            ON s.game_date = n.game_date
            AND s.home_team_tricode = n.home_team_abbr
            AND s.away_team_tricode = n.away_team_abbr
        LEFT JOIN bdl_games b
            ON s.game_date = b.game_date
            AND s.home_team_tricode = b.home_team_abbr
            AND s.away_team_tricode = b.away_team_abbr
        WHERE n.nbac_player_count > 0  -- Has NBAC data
          AND (b.bdl_player_count IS NULL OR b.bdl_player_count = 0)  -- Missing BDL data
        ORDER BY s.game_date DESC, s.home_team_tricode
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days)
            ]
        )

        results = client.query(query, job_config=job_config).result()

        gaps = []
        for row in results:
            gaps.append({
                "game_date": str(row.game_date),
                "matchup": row.matchup,
                "home_team": row.home_team,
                "away_team": row.away_team,
                "is_west_coast": row.is_west_coast,
                "hours_since_game_end": row.hours_since_game_end,
                "nbac_player_count": row.nbac_player_count,
                "has_bdl": row.has_bdl,
                "bdl_player_count": row.bdl_player_count,
            })

        return gaps

    except Exception as e:
        logger.error(f"Failed to query BDL gaps: {e}", exc_info=True)
        raise


def get_summary(gaps: List[Dict]) -> Dict:
    """Generate summary statistics from gaps."""
    if not gaps:
        return {
            "total_missing_games": 0,
            "dates_with_gaps": [],
            "west_coast_count": 0,
            "west_coast_pct": 0,
        }

    dates_with_gaps = sorted(set(g["game_date"] for g in gaps))
    west_coast_count = sum(1 for g in gaps if g["is_west_coast"])

    return {
        "total_missing_games": len(gaps),
        "dates_with_gaps": dates_with_gaps,
        "dates_count": len(dates_with_gaps),
        "west_coast_count": west_coast_count,
        "west_coast_pct": round(100 * west_coast_count / len(gaps), 1) if gaps else 0,
        "avg_hours_since_game": round(
            sum(g["hours_since_game_end"] for g in gaps) / len(gaps), 1
        ) if gaps else 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Find games with NBAC data but missing BDL data"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=3,
        help="Number of days to look back (default: 3)"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--dates-only",
        action="store_true",
        help="Only output dates with missing games (one per line)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output with details"
    )

    args = parser.parse_args()

    logger.info(f"Checking BDL completeness for last {args.days} days...")

    try:
        gaps = get_bdl_gaps(args.days)
        summary = get_summary(gaps)

        if args.dates_only:
            # Just output dates, one per line (for scripting)
            for date in summary["dates_with_gaps"]:
                print(date)
            return 0 if not gaps else 1

        if args.json:
            output = {
                "summary": summary,
                "gaps": gaps,
                "checked_at": datetime.now().isoformat(),
                "lookback_days": args.days,
            }
            print(json.dumps(output, indent=2))
            return 0 if not gaps else 1

        # Human-readable output
        print("\n" + "=" * 60)
        print("BDL COMPLETENESS CHECK")
        print("=" * 60)
        print(f"Lookback: {args.days} days")
        print(f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        if not gaps:
            print("✅ No BDL gaps found! All games have both NBAC and BDL data.")
            return 0

        print(f"⚠️  Found {summary['total_missing_games']} games missing BDL data")
        print(f"   Dates affected: {summary['dates_count']}")
        print(f"   West Coast games: {summary['west_coast_count']} ({summary['west_coast_pct']}%)")
        print(f"   Avg hours since game end: {summary['avg_hours_since_game']}")
        print()

        print("DATES WITH GAPS:")
        print("-" * 40)
        for date in summary["dates_with_gaps"]:
            date_gaps = [g for g in gaps if g["game_date"] == date]
            print(f"\n{date} ({len(date_gaps)} games):")
            for g in date_gaps:
                wc = " [WEST COAST]" if g["is_west_coast"] else ""
                print(f"  - {g['matchup']}{wc}")
                if args.verbose:
                    print(f"    NBAC: {g['nbac_player_count']} players, "
                          f"Hours since end: {g['hours_since_game_end']}")

        print()
        print("=" * 60)
        print("RECOMMENDED ACTION:")
        print(f"Run BDL scraper for dates: {', '.join(summary['dates_with_gaps'])}")
        print()
        print("Commands:")
        for date in summary["dates_with_gaps"]:
            print(f"  PYTHONPATH=. python -m scrapers.balldontlie.bdl_box_scores --date {date}")
        print()

        return 1  # Exit code 1 = gaps found

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
