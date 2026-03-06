"""
Validation utilities for config and data validation.

Created: Session 70 (2026-02-01)
"""

# Lazy imports to avoid pulling in pyyaml dependency in environments
# that only need specific validators (e.g., grading functions).
# Session 418: scraper_config_validator requires yaml which is not
# available in all Cloud Function runtimes.


def __getattr__(name):
    if name in ('validate_enabled_scrapers', 'should_process_scraper',
                'get_enabled_scrapers', 'check_table_exists'):
        from .scraper_config_validator import (
            validate_enabled_scrapers,
            should_process_scraper,
            get_enabled_scrapers,
            check_table_exists,
        )
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'validate_enabled_scrapers',
    'should_process_scraper',
    'get_enabled_scrapers',
    'check_table_exists',
]
