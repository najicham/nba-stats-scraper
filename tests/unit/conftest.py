# tests/unit/conftest.py
"""
Shared pytest configuration for unit tests.

This file ensures the project root is at the front of sys.path
to avoid namespace conflicts with test directories (e.g., tests/unit/predictions
conflicting with the predictions package).
"""
import sys
import os

# Add project root to path FIRST to ensure proper import resolution
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root in sys.path:
    sys.path.remove(project_root)
sys.path.insert(0, project_root)
