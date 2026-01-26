"""
Flask route blueprints for the NBA Stats Scraper service.

This module provides route blueprints that separate endpoint handlers
into focused, maintainable modules.
"""

from .health import health
from .scraper import scraper
from .orchestration import orchestration
from .cleanup import cleanup_bp
from .catchup import catchup
from .schedule_fix import schedule_fix

__all__ = [
    "health",
    "scraper",
    "orchestration",
    "cleanup_bp",
    "catchup",
    "schedule_fix",
]
