"""
NBA Stats Scraper Test Suite.

This package contains all tests for the NBA Stats Scraper platform.
"""
import sys
from pathlib import Path

# Ensure project root is at the beginning of sys.path to avoid
# namespace conflicts with test directories (e.g., tests/unit/predictions
# shadowing the project's predictions package)
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
