#!/usr/bin/env python3
"""
Path: tests/processors/analytics/team_defense_game_summary/verify_mocking.py

Quick verification that Google Cloud mocking is working correctly.
Run this before running the full test suite.

Usage:
    python verify_mocking.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

print("="*70)
print("Google Cloud Mocking Verification")
print("="*70)

# Step 1: Import conftest to trigger mocking
print("\n1. Importing conftest.py to trigger Google Cloud mocking...")
try:
    import conftest
    print("   ✅ conftest.py imported successfully")
except Exception as e:
    print(f"   ❌ Failed to import conftest.py: {e}")
    sys.exit(1)

# Step 2: Verify Google modules are mocked
print("\n2. Checking if Google modules are mocked...")
google_modules_to_check = [
    'google',
    'google.auth',
    'google.cloud',
    'google.cloud.bigquery',
    'google.cloud.exceptions',
]

all_mocked = True
for module_name in google_modules_to_check:
    if module_name in sys.modules:
        print(f"   ✅ {module_name} is mocked")
    else:
        print(f"   ❌ {module_name} is NOT mocked")
        all_mocked = False

if not all_mocked:
    print("\n❌ Some Google modules are not mocked. Check conftest.py.")
    sys.exit(1)

# Step 3: Test importing Google modules
print("\n3. Testing imports from mocked Google modules...")
try:
    from google.cloud import bigquery
    print("   ✅ Can import google.cloud.bigquery")
except Exception as e:
    print(f"   ❌ Failed to import google.cloud.bigquery: {e}")
    sys.exit(1)

try:
    from google.auth import default
    print("   ✅ Can import google.auth.default")
except Exception as e:
    print(f"   ❌ Failed to import google.auth.default: {e}")
    sys.exit(1)

try:
    from google.cloud.exceptions import NotFound
    print("   ✅ Can import google.cloud.exceptions.NotFound")
except Exception as e:
    print(f"   ❌ Failed to import google.cloud.exceptions.NotFound: {e}")
    sys.exit(1)

# Step 4: Test processor import
print("\n4. Testing processor import...")
try:
    from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
        TeamDefenseGameSummaryProcessor
    )
    print("   ✅ Can import TeamDefenseGameSummaryProcessor")
except Exception as e:
    print(f"   ❌ Failed to import processor: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 5: Test processor instantiation
print("\n5. Testing processor instantiation...")
try:
    processor = TeamDefenseGameSummaryProcessor()
    print("   ✅ Can instantiate TeamDefenseGameSummaryProcessor")
except Exception as e:
    print(f"   ❌ Failed to instantiate processor: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Success!
print("\n" + "="*70)
print("✅ All verification checks passed!")
print("="*70)
print("\nYou can now run the tests:")
print("  python run_tests.py unit")
print("  python run_tests.py unit --coverage")
print("="*70)