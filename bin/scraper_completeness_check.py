#!/usr/bin/env python3
"""
Generalized Scraper Completeness Checker

Checks any configured scraper for missing data by comparing against a reference source.
Uses configuration from shared/config/scraper_retry_config.yaml.

Usage:
    # Check specific scraper
    python bin/scraper_completeness_check.py bdl_box_scores

    # Check all enabled scrapers
    python bin/scraper_completeness_check.py --all

    # Custom lookback days
    python bin/scraper_completeness_check.py bdl_box_scores --days 7

    # Output dates only (for scripting)
    python bin/scraper_completeness_check.py bdl_box_scores --dates-only

    # Output as JSON
    python bin/scraper_completeness_check.py bdl_box_scores --json

    # List available scrapers
    python bin/scraper_completeness_check.py --list

Created: January 22, 2026
Purpose: Generalized completeness checking for catch-up retry workflows
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Config file path
CONFIG_PATH = Path(__file__).parent.parent / "shared" / "config" / "scraper_retry_config.yaml"


def load_config() -> Dict[str, Any]:
    """Load the scraper retry configuration."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_scraper_config(config: Dict, scraper_name: str) -> Optional[Dict]:
    """Get configuration for a specific scraper."""
    scrapers = config.get("scrapers", {})
    return scrapers.get(scraper_name)


def check_completeness(scraper_name: str, lookback_days: Optional[int] = None) -> Dict:
    """
    Check completeness for a specific scraper.

    Returns:
        Dict with:
        - scraper: scraper name
        - lookback_days: days checked
        - missing_games: list of missing game info
        - summary: stats about gaps
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client()
    except Exception as e:
        logger.error(f"Failed to initialize BigQuery client: {e}", exc_info=True)
        raise

    config = load_config()
    scraper_config = get_scraper_config(config, scraper_name)

    if not scraper_config:
        raise ValueError(f"Unknown scraper: {scraper_name}. Use --list to see available scrapers.")

    # Use provided lookback or config default
    if lookback_days is None:
        lookback_days = scraper_config.get(
            "lookback_days",
            config.get("global", {}).get("default_lookback_days", 3)
        )

    # Get the completeness query template
    queries = config.get("completeness_queries", {})
    query_template = queries.get(scraper_name)

    if not query_template:
        # Build a generic query from comparison config
        comparison = scraper_config.get("comparison", {})
        source_table = comparison.get("source_table")
        target_table = comparison.get("target_table")

        if not source_table or not target_table:
            raise ValueError(f"No completeness query or comparison config for {scraper_name}")

        logger.warning(f"Using generic completeness check for {scraper_name}")
        query_template = _build_generic_query(comparison)

    # Format query with lookback days
    query = query_template.format(lookback_days=lookback_days)

    logger.info(f"Checking completeness for {scraper_name} (last {lookback_days} days)...")

    try:
        results = client.query(query).result(timeout=60)

        missing_games = []
        for row in results:
            game_info = {
                "game_date": str(row.game_date) if hasattr(row, 'game_date') else None,
            }
            # Add any other available fields
            for field in ['home_team', 'away_team', 'matchup', 'status',
                         'reference_count', 'target_count', 'missing_games']:
                if hasattr(row, field):
                    value = getattr(row, field)
                    game_info[field] = str(value) if value is not None else None
            missing_games.append(game_info)

        # Build summary
        dates_with_gaps = sorted(set(g.get("game_date") for g in missing_games if g.get("game_date")))

        summary = {
            "total_missing": len(missing_games),
            "dates_with_gaps": dates_with_gaps,
            "dates_count": len(dates_with_gaps),
        }

        return {
            "scraper": scraper_name,
            "lookback_days": lookback_days,
            "checked_at": datetime.now().isoformat(),
            "missing_games": missing_games,
            "summary": summary,
            "config": {
                "enabled": scraper_config.get("enabled", False),
                "priority": scraper_config.get("priority", "UNKNOWN"),
            }
        }

    except Exception as e:
        logger.error(f"Query failed for {scraper_name}: {e}", exc_info=True)
        raise


def _build_generic_query(comparison: Dict) -> str:
    """Build a generic completeness query from comparison config."""
    source = comparison.get("source_table")
    target = comparison.get("target_table")
    join_keys = comparison.get("join_keys", ["game_date"])
    filter_clause = comparison.get("filter", "1=1")

    join_condition = " AND ".join([f"s.{k} = t.{k}" for k in join_keys])
    select_keys = ", ".join([f"s.{k}" for k in join_keys])

    return f"""
    WITH source AS (
        SELECT {", ".join(join_keys)}, COUNT(*) as row_count
        FROM {source}
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {{lookback_days}} DAY)
          AND {filter_clause}
        GROUP BY {", ".join(join_keys)}
    ),
    target AS (
        SELECT {", ".join(join_keys)}, COUNT(*) as row_count
        FROM {target}
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {{lookback_days}} DAY)
        GROUP BY {", ".join(join_keys)}
    )
    SELECT {select_keys},
           COALESCE(s.row_count, 0) AS reference_count,
           COALESCE(t.row_count, 0) AS target_count
    FROM source s
    LEFT JOIN target t ON {join_condition}
    WHERE t.row_count IS NULL OR t.row_count = 0
    ORDER BY s.game_date DESC
    """


def check_all_enabled_scrapers(lookback_days: Optional[int] = None) -> List[Dict]:
    """Check completeness for all enabled scrapers."""
    config = load_config()
    results = []

    for scraper_name, scraper_config in config.get("scrapers", {}).items():
        if not scraper_config.get("enabled", False):
            logger.info(f"Skipping disabled scraper: {scraper_name}")
            continue

        try:
            result = check_completeness(scraper_name, lookback_days)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to check {scraper_name}: {e}", exc_info=True)
            results.append({
                "scraper": scraper_name,
                "error": str(e),
                "summary": {"total_missing": -1}
            })

    return results


def list_scrapers() -> None:
    """List all configured scrapers."""
    config = load_config()

    print("\nConfigured Scrapers:")
    print("-" * 60)
    print(f"{'Name':<25} {'Enabled':<10} {'Priority':<10} {'Lookback'}")
    print("-" * 60)

    for name, cfg in config.get("scrapers", {}).items():
        enabled = "✅" if cfg.get("enabled", False) else "❌"
        priority = cfg.get("priority", "N/A")
        lookback = cfg.get("lookback_days", config.get("global", {}).get("default_lookback_days", 3))
        print(f"{name:<25} {enabled:<10} {priority:<10} {lookback} days")

    print()


def format_output(results: List[Dict], output_format: str, dates_only: bool = False) -> str:
    """Format results for output."""
    if dates_only:
        all_dates = set()
        for r in results:
            all_dates.update(r.get("summary", {}).get("dates_with_gaps", []))
        return "\n".join(sorted(all_dates))

    if output_format == "json":
        return json.dumps(results, indent=2)

    # Text format
    lines = []
    lines.append("\n" + "=" * 60)
    lines.append("SCRAPER COMPLETENESS CHECK")
    lines.append("=" * 60)
    lines.append(f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    total_missing = 0
    for result in results:
        scraper = result.get("scraper", "unknown")
        summary = result.get("summary", {})
        missing = summary.get("total_missing", 0)
        total_missing += max(0, missing)

        if "error" in result:
            lines.append(f"❌ {scraper}: ERROR - {result['error']}")
            continue

        enabled = result.get("config", {}).get("enabled", False)
        priority = result.get("config", {}).get("priority", "N/A")
        lookback = result.get("lookback_days", "?")

        if missing == 0:
            lines.append(f"✅ {scraper}: No gaps found (last {lookback} days)")
        else:
            lines.append(f"⚠️  {scraper}: {missing} missing games ({priority} priority)")
            lines.append(f"   Lookback: {lookback} days")
            lines.append(f"   Dates: {', '.join(summary.get('dates_with_gaps', []))}")

            # Show details for first few games
            for g in result.get("missing_games", [])[:5]:
                game_date = g.get("game_date", "?")
                matchup = g.get("matchup") or f"{g.get('away_team', '?')} @ {g.get('home_team', '?')}"
                lines.append(f"   - {game_date}: {matchup}")

            if len(result.get("missing_games", [])) > 5:
                lines.append(f"   ... and {len(result['missing_games']) - 5} more")

        lines.append("")

    lines.append("=" * 60)
    if total_missing == 0:
        lines.append("✅ All scrapers have complete data!")
    else:
        lines.append(f"⚠️  Total missing across all scrapers: {total_missing} games")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check scraper completeness by comparing against reference sources"
    )
    parser.add_argument(
        "scraper",
        nargs="?",
        help="Scraper name to check (e.g., bdl_box_scores)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Check all enabled scrapers"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        help="Number of days to look back (overrides config)"
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
        "--list", "-l",
        action="store_true",
        help="List available scrapers"
    )

    args = parser.parse_args()

    if args.list:
        list_scrapers()
        return 0

    if not args.scraper and not args.all:
        parser.print_help()
        print("\nError: Specify a scraper name or use --all")
        return 1

    try:
        if args.all:
            results = check_all_enabled_scrapers(args.days)
        else:
            result = check_completeness(args.scraper, args.days)
            results = [result]

        output_format = "json" if args.json else "text"
        output = format_output(results, output_format, args.dates_only)
        print(output)

        # Return exit code based on gaps found
        total_missing = sum(
            r.get("summary", {}).get("total_missing", 0)
            for r in results
            if r.get("summary", {}).get("total_missing", 0) > 0
        )
        return 1 if total_missing > 0 else 0

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
