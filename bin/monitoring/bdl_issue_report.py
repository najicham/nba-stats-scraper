#!/usr/bin/env python3
"""
BDL (Ball Don't Lie) Service Issue Report Generator

Generates a formatted report of BDL service issues for vendor communication.
Queries the bdl_service_issues view and groups consecutive days into issue periods.

Usage:
    python bin/monitoring/bdl_issue_report.py
    python bin/monitoring/bdl_issue_report.py --format markdown
    python bin/monitoring/bdl_issue_report.py --format text
    python bin/monitoring/bdl_issue_report.py --days 60
    python bin/monitoring/bdl_issue_report.py --output report.md
"""

import argparse
import sys
from datetime import date, timedelta
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"


def query_daily_issues(client: bigquery.Client, days: int) -> list:
    """Query bdl_service_issues view for the given date range."""
    query = f"""
    SELECT
        game_date,
        games_expected,
        games_available,
        games_missing,
        availability_pct,
        major_issues,
        minor_issues,
        issue_type,
        issue_summary
    FROM `{PROJECT_ID}.nba_orchestration.bdl_service_issues`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    ORDER BY game_date ASC
    """
    return list(client.query(query).result())


def group_into_periods(rows: list) -> list:
    """Group consecutive days with the same issue_type into periods."""
    if not rows:
        return []

    periods = []
    current = {
        "issue_type": rows[0].issue_type,
        "start_date": rows[0].game_date,
        "end_date": rows[0].game_date,
        "days": 1,
        "total_games_expected": rows[0].games_expected,
        "total_games_missing": rows[0].games_missing,
        "total_major_issues": rows[0].major_issues,
        "total_minor_issues": rows[0].minor_issues,
        "sample_summary": rows[0].issue_summary,
    }

    for row in rows[1:]:
        if row.issue_type == current["issue_type"]:
            current["end_date"] = row.game_date
            current["days"] += 1
            current["total_games_expected"] += row.games_expected
            current["total_games_missing"] += row.games_missing
            current["total_major_issues"] += row.major_issues
            current["total_minor_issues"] += row.minor_issues
        else:
            periods.append(current)
            current = {
                "issue_type": row.issue_type,
                "start_date": row.game_date,
                "end_date": row.game_date,
                "days": 1,
                "total_games_expected": row.games_expected,
                "total_games_missing": row.games_missing,
                "total_major_issues": row.major_issues,
                "total_minor_issues": row.minor_issues,
                "sample_summary": row.issue_summary,
            }

    periods.append(current)
    return periods


def calc_overall_stats(rows: list) -> dict:
    """Calculate overall service statistics."""
    if not rows:
        return {}

    total_days = len(rows)
    outage_days = sum(1 for r in rows if r.issue_type in ("FULL_OUTAGE", "MAJOR_OUTAGE"))
    quality_days = sum(1 for r in rows if "QUALITY" in r.issue_type)
    operational_days = sum(1 for r in rows if r.issue_type == "OPERATIONAL")
    total_games = sum(r.games_expected for r in rows)
    total_available = sum(r.games_available for r in rows)
    total_major = sum(r.major_issues for r in rows)

    return {
        "date_range": f"{rows[0].game_date} to {rows[-1].game_date}",
        "total_days": total_days,
        "outage_days": outage_days,
        "quality_issue_days": quality_days,
        "operational_days": operational_days,
        "uptime_pct": round((total_days - outage_days) / total_days * 100, 1) if total_days > 0 else 0,
        "total_games_expected": total_games,
        "total_games_available": total_available,
        "total_major_mismatches": total_major,
        "data_delivery_pct": round(total_available / total_games * 100, 1) if total_games > 0 else 0,
    }


def format_markdown(rows: list, periods: list, stats: dict) -> str:
    """Format report as markdown."""
    lines = []
    lines.append("# Ball Don't Lie (BDL) API - Service Issue Report")
    lines.append("")
    lines.append(f"**Report Date:** {date.today()}")
    lines.append(f"**Period:** {stats['date_range']}")
    lines.append(f"**Customer:** NBA Props Platform")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"Over the past **{stats['total_days']} days**, the BDL API has experienced significant service issues:")
    lines.append("")
    lines.append(f"- **{stats['outage_days']} days of complete outage** (0% data returned)")
    lines.append(f"- **{stats['quality_issue_days']} days of data quality issues** (incorrect stats returned)")
    lines.append(f"- **{stats['operational_days']} days operational**")
    lines.append(f"- **Overall data delivery rate: {stats['data_delivery_pct']}%** ({stats['total_games_available']}/{stats['total_games_expected']} games)")
    if stats['total_major_mismatches'] > 0:
        lines.append(f"- **{stats['total_major_mismatches']} major data mismatches** (wrong minutes/points vs official NBA.com data)")
    lines.append("")

    # Issue timeline
    lines.append("## Issue Timeline")
    lines.append("")
    lines.append("| Period | Duration | Issue Type | Details |")
    lines.append("|--------|----------|------------|---------|")
    for p in reversed(periods):
        date_str = str(p["start_date"])
        if p["start_date"] != p["end_date"]:
            date_str = f"{p['start_date']} to {p['end_date']}"
        duration = f"{p['days']} day{'s' if p['days'] != 1 else ''}"

        if p["issue_type"] == "FULL_OUTAGE":
            details = f"{p['total_games_missing']} games returned no data"
        elif p["issue_type"] == "MAJOR_OUTAGE":
            details = f"Only {p['total_games_expected'] - p['total_games_missing']}/{p['total_games_expected']} games returned"
        elif "QUALITY" in p["issue_type"]:
            details = f"{p['total_major_issues']} major + {p['total_minor_issues']} minor data mismatches"
        elif p["issue_type"] == "OPERATIONAL":
            details = "Service operational"
        else:
            details = p["sample_summary"]

        lines.append(f"| {date_str} | {duration} | {p['issue_type']} | {details} |")
    lines.append("")

    # Daily detail
    lines.append("## Daily Detail")
    lines.append("")
    lines.append("| Date | Games Expected | Available | Missing | Major Issues | Status |")
    lines.append("|------|---------------|-----------|---------|-------------|--------|")
    for row in reversed(list(rows)):
        status_icon = {
            "FULL_OUTAGE": "OUTAGE",
            "MAJOR_OUTAGE": "MAJOR OUTAGE",
            "PARTIAL_OUTAGE": "PARTIAL",
            "QUALITY_DEGRADATION": "QUALITY",
            "MINOR_QUALITY_ISSUES": "MINOR",
            "OPERATIONAL": "OK",
        }.get(row.issue_type, row.issue_type)
        lines.append(
            f"| {row.game_date} | {row.games_expected} | {row.games_available} | "
            f"{row.games_missing} | {row.major_issues} | {status_icon} |"
        )
    lines.append("")

    # Impact statement
    lines.append("## Impact")
    lines.append("")
    lines.append("Due to these ongoing service issues, we have been forced to:")
    lines.append("")
    lines.append("1. **Disable BDL as a data source** (since January 28, 2026)")
    lines.append("2. **Migrate all queries** to alternative sources (NBA.com official API)")
    lines.append("3. **Rebuild data pipelines** that depended on BDL data")
    lines.append("")
    lines.append("We are requesting resolution of these issues or cancellation of service.")
    lines.append("")

    return "\n".join(lines)


def format_text(rows: list, periods: list, stats: dict) -> str:
    """Format report as plain text."""
    lines = []
    lines.append("=" * 60)
    lines.append("BDL (Ball Don't Lie) API - Service Issue Report")
    lines.append("=" * 60)
    lines.append(f"Report Date: {date.today()}")
    lines.append(f"Period: {stats['date_range']}")
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total days monitored:    {stats['total_days']}")
    lines.append(f"  Days with full outage:   {stats['outage_days']}")
    lines.append(f"  Days with quality issues:{stats['quality_issue_days']}")
    lines.append(f"  Days operational:        {stats['operational_days']}")
    lines.append(f"  Data delivery rate:      {stats['data_delivery_pct']}%")
    lines.append(f"  Games missing data:      {stats['total_games_missing']}/{stats['total_games_expected']}")
    lines.append(f"  Major data mismatches:   {stats['total_major_mismatches']}")
    lines.append("")
    lines.append("ISSUE PERIODS")
    lines.append("-" * 40)
    for p in reversed(periods):
        date_str = str(p["start_date"])
        if p["start_date"] != p["end_date"]:
            date_str = f"{p['start_date']} to {p['end_date']}"
        lines.append(f"  [{p['issue_type']}] {date_str} ({p['days']} days)")
        if p["issue_type"] == "FULL_OUTAGE":
            lines.append(f"    -> {p['total_games_missing']} games returned no data")
        elif p["total_major_issues"] > 0:
            lines.append(f"    -> {p['total_major_issues']} major data mismatches")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate BDL service issue report")
    parser.add_argument("--format", choices=["markdown", "text"], default="markdown")
    parser.add_argument("--days", type=int, default=45, help="Days to look back")
    parser.add_argument("--output", type=str, help="Output file path (default: stdout)")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    rows = query_daily_issues(client, args.days)

    if not rows:
        print("No BDL monitoring data found in the specified date range.")
        sys.exit(0)

    periods = group_into_periods(rows)
    stats = calc_overall_stats(rows)

    if args.format == "markdown":
        report = format_markdown(rows, periods, stats)
    else:
        report = format_text(rows, periods, stats)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
