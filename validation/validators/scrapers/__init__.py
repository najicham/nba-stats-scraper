# File: validation/validators/scrapers/__init__.py
# Description: Scraper-level validation module
"""
Scraper-level validators for immediate validation after scraping.

This module provides validation at the scraper output level before
data is exported to GCS or processed further.
"""

from .scraper_output_validator import ScraperOutputValidator

__all__ = ['ScraperOutputValidator']
