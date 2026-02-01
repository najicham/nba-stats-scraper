"""
Runtime Scraper Config Validation

Validates that enabled scrapers in config have valid table references.
Services should call this at startup to fail fast if config is invalid.

Created: Session 70 (2026-02-01)
Purpose: Prevent espn_roster-style bugs where queries reference non-existent tables

Usage:
    from shared.validation.scraper_config_validator import validate_enabled_scrapers

    # In service startup
    validate_enabled_scrapers()  # Raises ValueError if invalid
"""

import logging
from typing import List, Tuple
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from shared.config.scraper_retry_config import get_retry_config


logger = logging.getLogger(__name__)


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
    except NotFound:
        return False
    except Exception as e:
        logger.warning(f"Error checking table {table_id}: {e}")
        return False


def validate_enabled_scrapers(
    scrapers_to_check: List[str] = None,
    raise_on_error: bool = True
) -> Tuple[bool, List[str]]:
    """
    Validate that enabled scrapers have valid table references.

    Args:
        scrapers_to_check: List of scraper names to validate (or None for all)
        raise_on_error: If True, raise ValueError on validation failure

    Returns:
        (all_valid, error_messages) tuple

    Raises:
        ValueError: If raise_on_error=True and validation fails
    """
    logger.info("Validating enabled scraper configurations...")

    # Initialize BigQuery client
    try:
        client = bigquery.Client(project="nba-props-platform")
    except Exception as e:
        error_msg = f"Failed to initialize BigQuery client: {e}"
        logger.error(error_msg)
        if raise_on_error:
            raise ValueError(error_msg)
        return False, [error_msg]

    errors = []

    # Get enabled scrapers
    from shared.config.scraper_retry_config import (
        get_all_enabled_scrapers,
        get_comparison_config
    )

    enabled_scrapers = get_all_enabled_scrapers()

    # Filter to specific scrapers if requested
    if scrapers_to_check:
        enabled_scrapers = [s for s in enabled_scrapers if s in scrapers_to_check]

    enabled_count = len(enabled_scrapers)
    validated_count = 0

    for scraper_name in enabled_scrapers:
        comparison = get_comparison_config(scraper_name)

        if not comparison:
            logger.debug(f"Scraper '{scraper_name}' has no comparison config")
            validated_count += 1
            continue

        # Check target_table (the main table this scraper writes to)
        target_table = comparison.get("target_table")

        if not target_table or target_table == "null":
            # Some scrapers don't have target tables (freshness checks only)
            logger.debug(f"Scraper '{scraper_name}' has no target_table (OK for freshness checks)")
            validated_count += 1
            continue

        # Validate table exists
        if not check_table_exists(client, target_table):
            error_msg = (
                f"Enabled scraper '{scraper_name}' references missing table: {target_table}"
            )
            logger.error(error_msg)
            errors.append(error_msg)
        else:
            logger.debug(f"✓ Scraper '{scraper_name}' -> {target_table}")
            validated_count += 1

    # Summary
    if errors:
        logger.error(f"Validation FAILED: {len(errors)} enabled scrapers have invalid tables")
        for error in errors:
            logger.error(f"  - {error}")

        if raise_on_error:
            raise ValueError(
                f"Scraper config validation failed: {len(errors)} enabled scrapers "
                f"have missing tables. See logs for details."
            )

        return False, errors

    logger.info(
        f"✓ Scraper config validation passed: {validated_count}/{enabled_count} "
        f"enabled scrapers have valid tables"
    )
    return True, []


def get_enabled_scrapers() -> List[str]:
    """
    Get list of all enabled scraper names from config.

    Returns:
        List of enabled scraper names
    """
    from shared.config.scraper_retry_config import get_all_enabled_scrapers
    return get_all_enabled_scrapers()


def should_process_scraper(scraper_name: str) -> bool:
    """
    Check if a scraper should be processed based on enabled status.

    Use this in catchup/orchestrator services to skip disabled scrapers.

    Args:
        scraper_name: Name of the scraper to check

    Returns:
        True if scraper is enabled, False otherwise
    """
    from shared.config.scraper_retry_config import get_retry_config

    scraper_config = get_retry_config(scraper_name)
    if not scraper_config:
        return False

    return scraper_config.get("enabled", False)
