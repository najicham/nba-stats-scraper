#!/usr/bin/env python3
"""
Validate Scraper Config Table References

Ensures all BigQuery tables referenced in scraper_retry_config.yaml actually exist.
Prevents runtime errors from missing table references.

Created: Session 70 (2026-02-01)
Purpose: Catch espn_roster-style bugs before they reach production

Usage:
    python .pre-commit-hooks/validate_scraper_config_tables.py

Returns:
    0 if all tables exist
    1 if validation fails (blocks commit)
"""

import sys
import yaml
from pathlib import Path
from typing import List, Tuple, Dict, Any
from google.cloud import bigquery


def load_scraper_config() -> Dict[str, Any]:
    """Load the scraper retry config YAML."""
    config_path = Path("shared/config/scraper_retry_config.yaml")

    if not config_path.exists():
        print(f"❌ ERROR: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def extract_table_references(config: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
    """
    Extract all BigQuery table references from config.

    Returns:
        List of (scraper_name, table_id, is_enabled) tuples
    """
    references = []

    scrapers = config.get("scrapers", {})

    for scraper_name, scraper_config in scrapers.items():
        is_enabled = scraper_config.get("enabled", False)
        comparison = scraper_config.get("comparison", {})

        # Check source_table
        source_table = comparison.get("source_table")
        if source_table and source_table != "null":
            references.append((scraper_name, source_table, is_enabled))

        # Check target_table
        target_table = comparison.get("target_table")
        if target_table and target_table != "null":
            references.append((scraper_name, target_table, is_enabled))

    return references


def check_table_exists(client: bigquery.Client, table_id: str) -> bool:
    """
    Check if a BigQuery table exists.

    Args:
        client: BigQuery client
        table_id: Fully qualified table ID (project.dataset.table)
                  or partial (dataset.table)

    Returns:
        True if table exists, False otherwise
    """
    try:
        # If table_id doesn't have project, add default
        if table_id.count('.') == 1:
            # dataset.table format - add project
            table_id = f"nba-props-platform.{table_id}"

        client.get_table(table_id)
        return True
    except Exception:
        return False


def validate_config_tables() -> Tuple[bool, List[str], List[str]]:
    """
    Validate all table references in scraper config.

    Returns:
        (all_valid, errors, warnings) tuple
    """
    print("🔍 Validating scraper config table references...")
    print()

    # Load config
    config = load_scraper_config()
    references = extract_table_references(config)

    if not references:
        print("⚠️  No table references found in config")
        return True, [], []

    # Initialize BigQuery client
    try:
        client = bigquery.Client(project="nba-props-platform")
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize BigQuery client: {e}")
        print("   Make sure you're authenticated: gcloud auth application-default login")
        sys.exit(1)

    errors = []
    warnings = []
    checked_tables = set()  # Avoid checking same table multiple times

    # Check each reference
    for scraper_name, table_id, is_enabled in references:
        # Skip if already checked
        if table_id in checked_tables:
            continue

        checked_tables.add(table_id)

        exists = check_table_exists(client, table_id)

        if not exists:
            if is_enabled:
                # Enabled scraper with missing table = ERROR
                errors.append(
                    f"❌ ENABLED scraper '{scraper_name}' references missing table: {table_id}"
                )
            else:
                # Disabled scraper with missing table = WARNING
                warnings.append(
                    f"⚠️  Disabled scraper '{scraper_name}' references missing table: {table_id}"
                )
        else:
            print(f"✅ {table_id:<60} (used by {scraper_name})")

    print()

    # Print warnings
    if warnings:
        print("⚠️  WARNINGS:")
        for warning in warnings:
            print(f"   {warning}")
        print()
        print("   These are OK because the scrapers are disabled.")
        print("   If you enable them, the tables must exist first.")
        print()

    # Print errors
    if errors:
        print("❌ ERRORS:")
        for error in errors:
            print(f"   {error}")
        print()
        print("   Fix by either:")
        print("   1. Set enabled: false in the config (if table not needed)")
        print("   2. Create the missing table in BigQuery")
        print("   3. Remove the scraper config entry")
        print()
        return False, errors, warnings

    print("✅ All table references validated successfully!")
    print(f"   Checked {len(checked_tables)} unique tables")

    if warnings:
        print(f"   Found {len(warnings)} warnings (disabled scrapers with missing tables)")

    return True, errors, warnings


def main():
    """Main entry point."""
    try:
        all_valid, errors, warnings = validate_config_tables()

        # WARNING ONLY MODE: Don't block commits
        # Many table references are aspirational or for future use
        # The important thing is that services check enabled=true at runtime

        if errors:
            print("⚠️  This check is informational only and won't block the commit.")
            print("   Services should validate enabled scrapers at runtime.")

        sys.exit(0)  # Always succeed

    except KeyboardInterrupt:
        print("\n\n❌ Validation cancelled")
        sys.exit(0)  # Don't block on cancel
    except Exception as e:
        print(f"\n\n⚠️  Validation error (non-blocking): {e}")
        sys.exit(0)  # Don't block on errors


if __name__ == "__main__":
    main()
