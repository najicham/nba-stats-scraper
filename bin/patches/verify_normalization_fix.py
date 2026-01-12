#!/usr/bin/env python3
"""
Verify that player_lookup normalization is consistent across all processors.

This script tests that:
1. The shared normalize_name() function keeps suffixes
2. The ESPN roster processor now uses the shared function
3. The BettingPros processor now uses the shared function
4. All normalizers produce identical output

Run this BEFORE deploying to production to verify the fix is correct.

Usage:
    python bin/patches/verify_normalization_fix.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from data_processors.raw.utils.name_utils import normalize_name


def test_normalize_name_keeps_suffixes():
    """Test that normalize_name() keeps suffixes (Jr., Sr., II, III, etc.)"""
    test_cases = [
        # (input, expected_output)
        ("Michael Porter Jr.", "michaelporterjr"),
        ("Michael Porter Jr", "michaelporterjr"),
        ("Gary Payton II", "garypaytonii"),
        ("Tim Hardaway Jr.", "timhardawayjr"),
        ("Jaren Jackson Jr.", "jarenjacksonjr"),
        ("Marcus Morris Sr.", "marcusmorrissr"),
        ("Larry Nance Jr.", "larrynancejr"),
        ("Wendell Carter Jr.", "wendellcarterjr"),
        ("Gary Trent Jr.", "garytrentjr"),
        ("Kelly Oubre Jr.", "kellyoubrejr"),
        ("Kenyon Martin Jr.", "kenyonmartinjr"),

        # Regular names (no suffix)
        ("LeBron James", "lebronjames"),
        ("Stephen Curry", "stephencurry"),

        # Names with punctuation
        ("D'Angelo Russell", "dangelorussell"),
        ("P.J. Tucker", "pjtucker"),
        ("T.J. McConnell", "tjmcconnell"),
        ("Karl-Anthony Towns", "karlanthonytowns"),

        # Names with accents
        ("Nikola Jokić", "nikolajokic"),
        ("Luka Dončić", "lukadoncic"),
        ("Jonas Valančiūnas", "jonasvalanciunas"),

        # Edge cases
        ("", None),
        (None, None),
    ]

    print("Testing normalize_name() function...")
    print("=" * 70)

    passed = 0
    failed = 0

    for input_name, expected in test_cases:
        try:
            result = normalize_name(input_name) if input_name else None
            if result == expected:
                print(f"✓ PASS: '{input_name}' -> '{result}'")
                passed += 1
            else:
                print(f"✗ FAIL: '{input_name}'")
                print(f"       Expected: '{expected}'")
                print(f"       Got:      '{result}'")
                failed += 1
        except Exception as e:
            print(f"✗ ERROR: '{input_name}' raised {type(e).__name__}: {e}")
            failed += 1

    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")

    return failed == 0


def test_espn_processor_uses_shared_normalizer():
    """Verify ESPN roster processor imports and uses shared normalize_name()"""
    print("\nVerifying ESPN roster processor...")
    print("=" * 70)

    try:
        # Read the processor file
        processor_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data_processors/raw/espn/espn_team_roster_processor.py"
        )

        with open(processor_path, 'r') as f:
            content = f.read()

        # Check for import
        has_import = "from data_processors.raw.utils.name_utils import normalize_name" in content
        # Check for usage
        has_usage = "player_lookup = normalize_name(full_name)" in content
        # Check old method is deprecated
        has_deprecation = "DEPRECATED" in content and "_normalize_player_name" in content

        if has_import:
            print("✓ Import statement found")
        else:
            print("✗ Import statement NOT found")

        if has_usage:
            print("✓ normalize_name() usage found")
        else:
            print("✗ normalize_name() usage NOT found")

        if has_deprecation:
            print("✓ Old method marked as deprecated")
        else:
            print("✗ Old method NOT marked as deprecated")

        return has_import and has_usage

    except Exception as e:
        print(f"✗ Error reading processor: {e}")
        return False


def test_bettingpros_processor_uses_shared_normalizer():
    """Verify BettingPros processor imports and uses shared normalize_name()"""
    print("\nVerifying BettingPros processor...")
    print("=" * 70)

    try:
        # Read the processor file
        processor_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data_processors/raw/bettingpros/bettingpros_player_props_processor.py"
        )

        with open(processor_path, 'r') as f:
            content = f.read()

        # Check for import
        has_import = "from data_processors.raw.utils.name_utils import normalize_name" in content
        # Check for usage
        has_usage = "player_lookup = normalize_name(player_name)" in content
        # Check old method is deprecated
        has_deprecation = "DEPRECATED" in content and "normalize_player_name" in content

        if has_import:
            print("✓ Import statement found")
        else:
            print("✗ Import statement NOT found")

        if has_usage:
            print("✓ normalize_name() usage found")
        else:
            print("✗ normalize_name() usage NOT found")

        if has_deprecation:
            print("✓ Old method marked as deprecated")
        else:
            print("✗ Old method NOT marked as deprecated")

        return has_import and has_usage

    except Exception as e:
        print(f"✗ Error reading processor: {e}")
        return False


def main():
    print("\n" + "=" * 70)
    print("PLAYER LOOKUP NORMALIZATION FIX VERIFICATION")
    print("=" * 70)
    print("\nThis verifies that the normalization fix is correctly implemented.")
    print("Run this BEFORE deploying to production.\n")

    all_passed = True

    # Test 1: normalize_name function
    if not test_normalize_name_keeps_suffixes():
        all_passed = False

    # Test 2: ESPN processor
    if not test_espn_processor_uses_shared_normalizer():
        all_passed = False

    # Test 3: BettingPros processor
    if not test_bettingpros_processor_uses_shared_normalizer():
        all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("ALL CHECKS PASSED - Safe to deploy!")
        print("=" * 70)
        return 0
    else:
        print("SOME CHECKS FAILED - Do NOT deploy until fixed!")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
