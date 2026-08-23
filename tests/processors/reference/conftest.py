# tests/processors/reference/conftest.py
"""
Shared pytest configuration for reference processor tests.

Provides fixtures and mocking patterns for registry processor testing.
"""

import pytest
import sys
from unittest.mock import MagicMock


# NOTE (2026-08-23): the pytest_configure hook here used to replace the entire
# `google` namespace in sys.modules with MagicMocks. It was removed because:
#
#   1. The real libraries ARE installed, so the stub bought nothing.
#   2. It made `except GoogleAPIError` raise
#      "TypeError: catching classes that do not inherit from BaseException",
#      so every error-path test under this directory was structurally impossible.
#   3. pytest_configure is a session hook. Replacing sys.modules there leaks into
#      every test collected afterwards — a strong candidate for this repo's
#      documented "cross-suite pollution" (full-run failures that vanish per-dir).
#
# Measured before removal: identical pass/fail sets for tests/processors/reference/.
# If you need a Google module mocked, mock it in the test that needs it.
