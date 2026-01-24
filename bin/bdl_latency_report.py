#!/usr/bin/env python3
"""
BDL Latency Report Generator

Generates a comprehensive report of BDL data availability and latency patterns.
This report can be shared with BDL support to document issues with late data.

Usage:
    # Generate report for last 30 days (default)
    python bin/bdl_latency_report.py

    # Generate report for specific date range
    python bin/bdl_latency_report.py --start 2026-01-01 --end 2026-01-21

    # Output as markdown (for sharing)
    python bin/bdl_latency_report.py --format markdown > bdl_report.md

    # Output as JSON
    python bin/bdl_latency_report.py --format json

Created: January 22, 2026
Purpose: Generate evidence of BDL late data for support contact
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_latency_data(start_date: str, end_date: str) -> Tuple[List[Dict], Dict]:
    """
    Get latency data for the specified date range.

    Returns:
        Tuple of (games_list, summary_stats)
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client()

        # Query 1: Per-game latency analysis
        games_query = """
        WITH
        schedule AS (
            SELECT
                game_id,
                game_date,
                home_team_tricode,
                away_team_tricode,
                CONCAT(away_team_tricode, ' @ ', home_team_tricode) AS matchup,
                game_date_est AS game_start_time,
                TIMESTAMP_ADD(game_date_est, INTERVAL 150 MINUTE) AS estimated_game_end,
                arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') AS is_west_coast,
                EXTRACT(DAYOFWEEK FROM game_date) AS day_of_week
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date BETWEEN @start_date AND @end_date
              AND season_year = 2025
              AND game_status = 3
        ),

        nbac_availability AS (
            SELECT
                game_date,
                home_team_abbr,
                away_team_abbr,
                MIN(created_at) AS nbac_first_available,
                COUNT(*) AS nbac_player_count
            FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date BETWEEN @start_date AND @end_date
            GROUP BY game_date, home_team_abbr, away_team_abbr
        ),

        bdl_availability AS (
            SELECT
                game_date,
                home_team_abbr,
                away_team_abbr,
                MIN(created_at) AS bdl_first_available,
                COUNT(*) AS bdl_player_count
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN @start_date AND @end_date
            GROUP BY game_date, home_team_abbr, away_team_abbr
        )

        SELECT
            s.game_date,
            s.matchup,
            s.home_team_tricode AS home_team,
            s.away_team_tricode AS away_team,
            s.is_west_coast,
            s.day_of_week,
            s.game_start_time,
            s.estimated_game_end,

            -- NBAC (fallback) data
            n.nbac_first_available,
            n.nbac_player_count,
            TIMESTAMP_DIFF(n.nbac_first_available, s.estimated_game_end, MINUTE) AS nbac_latency_minutes,

            -- BDL data
            b.bdl_first_available,
            b.bdl_player_count,
            TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) AS bdl_latency_minutes,

            -- Status
            CASE
                WHEN b.bdl_first_available IS NOT NULL THEN 'AVAILABLE'
                WHEN n.nbac_first_available IS NOT NULL THEN 'NBAC_FALLBACK'
                ELSE 'MISSING_BOTH'
            END AS status,

            -- Latency category
            CASE
                WHEN b.bdl_first_available IS NULL THEN 'NEVER_AVAILABLE'
                WHEN TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) <= 60 THEN 'FAST_0_1H'
                WHEN TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) <= 180 THEN 'NORMAL_1_3H'
                WHEN TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) <= 360 THEN 'SLOW_3_6H'
                WHEN TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) <= 720 THEN 'DELAYED_6_12H'
                WHEN TIMESTAMP_DIFF(b.bdl_first_available, s.estimated_game_end, MINUTE) <= 1440 THEN 'VERY_DELAYED_12_24H'
                ELSE 'EXTREMELY_DELAYED_24H_PLUS'
            END AS latency_category

        FROM schedule s
        LEFT JOIN nbac_availability n
            ON s.game_date = n.game_date
            AND s.home_team_tricode = n.home_team_abbr
            AND s.away_team_tricode = n.away_team_abbr
        LEFT JOIN bdl_availability b
            ON s.game_date = b.game_date
            AND s.home_team_tricode = b.home_team_abbr
            AND s.away_team_tricode = b.away_team_abbr
        ORDER BY s.game_date DESC, s.game_start_time DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        results = client.query(games_query, job_config=job_config).result(timeout=60)

        games = []
        for row in results:
            games.append({
                "game_date": str(row.game_date),
                "matchup": row.matchup,
                "home_team": row.home_team,
                "away_team": row.away_team,
                "is_west_coast": row.is_west_coast,
                "day_of_week": row.day_of_week,
                "game_start_time": row.game_start_time.isoformat() if row.game_start_time else None,
                "estimated_game_end": row.estimated_game_end.isoformat() if row.estimated_game_end else None,
                "nbac_first_available": row.nbac_first_available.isoformat() if row.nbac_first_available else None,
                "nbac_player_count": row.nbac_player_count,
                "nbac_latency_minutes": row.nbac_latency_minutes,
                "bdl_first_available": row.bdl_first_available.isoformat() if row.bdl_first_available else None,
                "bdl_player_count": row.bdl_player_count,
                "bdl_latency_minutes": row.bdl_latency_minutes,
                "status": row.status,
                "latency_category": row.latency_category,
            })

        # Calculate summary stats
        total_games = len(games)
        games_with_bdl = sum(1 for g in games if g["status"] == "AVAILABLE")
        games_missing_bdl = total_games - games_with_bdl
        west_coast_games = sum(1 for g in games if g["is_west_coast"])
        west_coast_missing = sum(1 for g in games if g["is_west_coast"] and g["status"] != "AVAILABLE")

        # Latency percentiles (only for games with BDL data)
        bdl_latencies = [g["bdl_latency_minutes"] for g in games if g["bdl_latency_minutes"] is not None]
        bdl_latencies.sort()

        def percentile(data, p):
            if not data:
                return None
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1 if f < len(data) - 1 else f
            return data[f] + (data[c] - data[f]) * (k - f) if c < len(data) else data[f]

        # Category breakdown
        categories = {}
        for g in games:
            cat = g["latency_category"]
            categories[cat] = categories.get(cat, 0) + 1

        summary = {
            "date_range": {"start": start_date, "end": end_date},
            "total_games": total_games,
            "games_with_bdl": games_with_bdl,
            "games_missing_bdl": games_missing_bdl,
            "bdl_coverage_pct": round(100 * games_with_bdl / total_games, 1) if total_games else 0,
            "west_coast": {
                "total_games": west_coast_games,
                "missing_bdl": west_coast_missing,
                "pct_of_missing": round(100 * west_coast_missing / games_missing_bdl, 1) if games_missing_bdl else 0,
            },
            "latency_stats": {
                "min_minutes": min(bdl_latencies) if bdl_latencies else None,
                "p50_minutes": percentile(bdl_latencies, 50),
                "p90_minutes": percentile(bdl_latencies, 90),
                "p95_minutes": percentile(bdl_latencies, 95),
                "max_minutes": max(bdl_latencies) if bdl_latencies else None,
                "p50_hours": round(percentile(bdl_latencies, 50) / 60, 1) if bdl_latencies else None,
                "p90_hours": round(percentile(bdl_latencies, 90) / 60, 1) if bdl_latencies else None,
            },
            "latency_breakdown": categories,
        }

        return games, summary

    except Exception as e:
        logger.error(f"Failed to query latency data: {e}")
        raise


def format_markdown(games: List[Dict], summary: Dict) -> str:
    """Format report as markdown for sharing."""
    lines = []

    lines.append("# BDL Data Availability & Latency Report")
    lines.append("")
    lines.append(f"**Date Range:** {summary['date_range']['start']} to {summary['date_range']['end']}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **Total Games:** {summary['total_games']}")
    lines.append(f"- **Games with BDL Data:** {summary['games_with_bdl']} ({summary['bdl_coverage_pct']}%)")
    lines.append(f"- **Games Missing BDL Data:** {summary['games_missing_bdl']}")
    lines.append("")

    lines.append("## Key Findings")
    lines.append("")
    lines.append("### Coverage Issues")
    lines.append("")
    if summary['games_missing_bdl'] > 0:
        lines.append(f"⚠️ **{summary['games_missing_bdl']} games** are missing BDL data entirely.")
        lines.append("")
        wc = summary['west_coast']
        lines.append(f"- **{wc['missing_bdl']} of {wc['total_games']}** West Coast games are missing BDL data")
        lines.append(f"- West Coast games represent **{wc['pct_of_missing']}%** of all missing games")
        lines.append("")
    else:
        lines.append("✅ All games have BDL data.")
        lines.append("")

    lines.append("### Latency Analysis")
    lines.append("")
    ls = summary['latency_stats']
    if ls['p50_minutes']:
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Median Latency | {ls['p50_hours']} hours ({int(ls['p50_minutes'])} min) |")
        lines.append(f"| P90 Latency | {ls['p90_hours']} hours ({int(ls['p90_minutes'])} min) |")
        lines.append(f"| Max Latency | {int(ls['max_minutes'])} min ({round(ls['max_minutes']/60, 1)} hours) |")
        lines.append("")
    else:
        lines.append("No latency data available (no games with BDL data).")
        lines.append("")

    lines.append("### Latency Distribution")
    lines.append("")
    lines.append("| Category | Count | % |")
    lines.append("|----------|-------|---|")
    for cat, count in sorted(summary['latency_breakdown'].items()):
        pct = round(100 * count / summary['total_games'], 1)
        lines.append(f"| {cat} | {count} | {pct}% |")
    lines.append("")

    # List games missing BDL data
    missing_games = [g for g in games if g["status"] != "AVAILABLE"]
    if missing_games:
        lines.append("## Games Missing BDL Data")
        lines.append("")
        lines.append("| Date | Matchup | West Coast | Hours Since End |")
        lines.append("|------|---------|------------|-----------------|")
        for g in missing_games[:50]:  # Limit to 50 for readability
            wc = "Yes" if g["is_west_coast"] else "No"
            if g["estimated_game_end"]:
                end_dt = datetime.fromisoformat(g["estimated_game_end"].replace("Z", "+00:00"))
                hours = round((datetime.now(end_dt.tzinfo) - end_dt).total_seconds() / 3600, 1)
            else:
                hours = "N/A"
            lines.append(f"| {g['game_date']} | {g['matchup']} | {wc} | {hours} |")

        if len(missing_games) > 50:
            lines.append(f"... and {len(missing_games) - 50} more games")
        lines.append("")

    # List games with very delayed BDL data
    delayed_games = [g for g in games if g["bdl_latency_minutes"] and g["bdl_latency_minutes"] > 360]
    if delayed_games:
        lines.append("## Games with Significantly Delayed BDL Data (>6 hours)")
        lines.append("")
        lines.append("| Date | Matchup | West Coast | Latency (hours) |")
        lines.append("|------|---------|------------|-----------------|")
        for g in sorted(delayed_games, key=lambda x: -x["bdl_latency_minutes"])[:30]:
            wc = "Yes" if g["is_west_coast"] else "No"
            hours = round(g["bdl_latency_minutes"] / 60, 1)
            lines.append(f"| {g['game_date']} | {g['matchup']} | {wc} | {hours} |")
        lines.append("")

    lines.append("## Recommendations for BDL Support")
    lines.append("")
    lines.append("Based on this data, we request BDL investigate:")
    lines.append("")
    if summary['games_missing_bdl'] > 0:
        lines.append(f"1. **{summary['games_missing_bdl']} games with no data** - These games never received box score data")
    lines.append(f"2. **West Coast game delays** - {summary['west_coast']['pct_of_missing']}% of missing games are West Coast")
    if ls['p90_hours'] and ls['p90_hours'] > 6:
        lines.append(f"3. **High P90 latency ({ls['p90_hours']} hours)** - 10% of games take over {ls['p90_hours']} hours")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate BDL latency and availability report"
    )
    parser.add_argument(
        "--start", "-s",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Default: 30 days ago"
    )
    parser.add_argument(
        "--end", "-e",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: yesterday"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=30,
        help="Days to look back (if --start not specified). Default: 30"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text)"
    )

    args = parser.parse_args()

    # Set date range
    if args.end:
        end_date = args.end
    else:
        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    if args.start:
        start_date = args.start
    else:
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    logger.info(f"Generating BDL latency report for {start_date} to {end_date}...")

    try:
        games, summary = get_latency_data(start_date, end_date)

        if args.format == "json":
            output = {
                "summary": summary,
                "games": games,
                "generated_at": datetime.now().isoformat(),
            }
            print(json.dumps(output, indent=2))

        elif args.format == "markdown":
            print(format_markdown(games, summary))

        else:  # text
            print("\n" + "=" * 70)
            print("BDL DATA AVAILABILITY & LATENCY REPORT")
            print("=" * 70)
            print(f"Date Range: {start_date} to {end_date}")
            print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()

            print("SUMMARY")
            print("-" * 40)
            print(f"Total Games:        {summary['total_games']}")
            print(f"Games with BDL:     {summary['games_with_bdl']} ({summary['bdl_coverage_pct']}%)")
            print(f"Games Missing BDL:  {summary['games_missing_bdl']}")
            print()

            wc = summary['west_coast']
            print("WEST COAST ANALYSIS")
            print("-" * 40)
            print(f"West Coast Games:   {wc['total_games']}")
            print(f"Missing BDL:        {wc['missing_bdl']}")
            print(f"% of All Missing:   {wc['pct_of_missing']}%")
            print()

            ls = summary['latency_stats']
            if ls['p50_minutes']:
                print("LATENCY STATS (for games with BDL data)")
                print("-" * 40)
                print(f"Median (P50):       {ls['p50_hours']} hours")
                print(f"P90:                {ls['p90_hours']} hours")
                print(f"Max:                {round(ls['max_minutes']/60, 1)} hours")
                print()

            print("LATENCY BREAKDOWN")
            print("-" * 40)
            for cat, count in sorted(summary['latency_breakdown'].items()):
                pct = round(100 * count / summary['total_games'], 1)
                print(f"{cat:30} {count:5} ({pct}%)")
            print()

            if summary['games_missing_bdl'] > 0:
                print("GAMES MISSING BDL DATA")
                print("-" * 40)
                missing = [g for g in games if g["status"] != "AVAILABLE"]
                for g in missing[:20]:
                    wc_flag = " [WC]" if g["is_west_coast"] else ""
                    print(f"  {g['game_date']} {g['matchup']}{wc_flag}")
                if len(missing) > 20:
                    print(f"  ... and {len(missing) - 20} more")
                print()

            print("=" * 70)

        return 0 if summary['games_missing_bdl'] == 0 else 1

    except Exception as e:
        logger.error(f"Error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
