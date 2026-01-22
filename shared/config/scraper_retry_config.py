"""
Scraper Retry Configuration Loader

Provides programmatic access to scraper retry configuration defined in
scraper_retry_config.yaml.

Usage:
    from shared.config.scraper_retry_config import (
        get_retry_config,
        get_all_enabled_scrapers,
        get_retry_windows,
        should_retry_now
    )

    # Get config for specific scraper
    config = get_retry_config('bdl_box_scores')

    # Get all enabled scrapers
    scrapers = get_all_enabled_scrapers()

    # Check if it's time to retry
    if should_retry_now('bdl_box_scores'):
        run_catchup_scrape('bdl_box_scores')

Created: January 22, 2026
"""

import logging
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Config file path (relative to this module)
CONFIG_PATH = Path(__file__).parent / "scraper_retry_config.yaml"

# Cache for loaded config
_config_cache: Optional[Dict] = None
_config_load_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # Reload config every 5 minutes


def _load_config(force_reload: bool = False) -> Dict[str, Any]:
    """Load configuration from YAML file with caching."""
    global _config_cache, _config_load_time

    now = datetime.now()

    # Return cached config if valid
    if not force_reload and _config_cache is not None and _config_load_time is not None:
        age = (now - _config_load_time).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return _config_cache

    # Load config
    if not CONFIG_PATH.exists():
        logger.warning(f"Scraper retry config not found: {CONFIG_PATH}")
        return {"scrapers": {}, "global": {}}

    try:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
            _config_load_time = now
            return _config_cache
    except Exception as e:
        logger.error(f"Failed to load scraper retry config: {e}")
        return {"scrapers": {}, "global": {}}


def get_retry_config(scraper_name: str) -> Optional[Dict[str, Any]]:
    """
    Get retry configuration for a specific scraper.

    Returns:
        Dict with scraper config, or None if not found
    """
    config = _load_config()
    return config.get("scrapers", {}).get(scraper_name)


def get_all_enabled_scrapers() -> List[str]:
    """
    Get list of all enabled scraper names.

    Returns:
        List of scraper names that have catch-up retries enabled
    """
    config = _load_config()
    return [
        name for name, cfg in config.get("scrapers", {}).items()
        if cfg.get("enabled", False)
    ]


def get_retry_windows(scraper_name: str) -> List[Dict[str, str]]:
    """
    Get retry windows for a specific scraper.

    Returns:
        List of dicts with 'time', 'name', 'description'
    """
    scraper_config = get_retry_config(scraper_name)
    if not scraper_config:
        return []
    return scraper_config.get("retry_windows", [])


def get_lookback_days(scraper_name: str) -> int:
    """
    Get lookback days for a specific scraper.

    Returns:
        Number of days to look back for missing data
    """
    config = _load_config()
    scraper_config = get_retry_config(scraper_name)

    if scraper_config:
        return scraper_config.get(
            "lookback_days",
            config.get("global", {}).get("default_lookback_days", 3)
        )
    return config.get("global", {}).get("default_lookback_days", 3)


def get_completeness_query(scraper_name: str, lookback_days: Optional[int] = None) -> Optional[str]:
    """
    Get the completeness check query for a scraper.

    Args:
        scraper_name: Name of the scraper
        lookback_days: Override for lookback days (uses config if not specified)

    Returns:
        Formatted SQL query string, or None if not configured
    """
    config = _load_config()
    queries = config.get("completeness_queries", {})
    query_template = queries.get(scraper_name)

    if not query_template:
        return None

    if lookback_days is None:
        lookback_days = get_lookback_days(scraper_name)

    return query_template.format(lookback_days=lookback_days)


def should_retry_now(
    scraper_name: str,
    current_time: Optional[datetime] = None,
    tolerance_minutes: int = 30
) -> Tuple[bool, Optional[str]]:
    """
    Check if it's currently a retry window for the given scraper.

    Args:
        scraper_name: Name of the scraper
        current_time: Time to check (defaults to now)
        tolerance_minutes: Minutes before/after window time to consider valid

    Returns:
        Tuple of (should_retry: bool, window_name: Optional[str])
    """
    if current_time is None:
        current_time = datetime.now()

    windows = get_retry_windows(scraper_name)
    if not windows:
        return False, None

    current_minutes = current_time.hour * 60 + current_time.minute

    for window in windows:
        window_time_str = window.get("time", "")
        try:
            parts = window_time_str.split(":")
            window_hour = int(parts[0])
            window_minute = int(parts[1]) if len(parts) > 1 else 0
            window_minutes = window_hour * 60 + window_minute

            # Check if current time is within tolerance of window
            diff = abs(current_minutes - window_minutes)
            if diff <= tolerance_minutes:
                return True, window.get("name")

        except (ValueError, IndexError):
            logger.warning(f"Invalid window time format: {window_time_str}")
            continue

    return False, None


def get_alert_severity(
    scraper_name: str,
    hours_since_game_end: float
) -> str:
    """
    Get the alert severity for a missing game based on time elapsed.

    Args:
        scraper_name: Name of the scraper
        hours_since_game_end: Hours since the game ended

    Returns:
        Severity level: 'INFO', 'WARNING', 'ERROR', or 'CRITICAL'
    """
    scraper_config = get_retry_config(scraper_name)
    if not scraper_config:
        return "WARNING"

    alerts = scraper_config.get("alerts", {})
    severity_rules = alerts.get("severity_by_hours", [])

    # Sort by hours descending to find the appropriate bucket
    severity_rules = sorted(severity_rules, key=lambda x: x.get("hours", 0), reverse=True)

    for rule in severity_rules:
        if hours_since_game_end >= rule.get("hours", 0):
            return rule.get("severity", "WARNING")

    return "INFO"


def get_comparison_config(scraper_name: str) -> Optional[Dict[str, Any]]:
    """
    Get the comparison configuration for completeness checks.

    Returns:
        Dict with source_table, target_table, join_keys, etc.
    """
    scraper_config = get_retry_config(scraper_name)
    if not scraper_config:
        return None
    return scraper_config.get("comparison")


# Convenience exports
__all__ = [
    'get_retry_config',
    'get_all_enabled_scrapers',
    'get_retry_windows',
    'get_lookback_days',
    'get_completeness_query',
    'should_retry_now',
    'get_alert_severity',
    'get_comparison_config',
]
