#!/usr/bin/env python3
"""
Cross-Phase Consistency Check CLI

Validates data flows correctly across pipeline phases.

Usage:
    python bin/validation/cross_phase_consistency.py --date 2026-01-25

Created: 2026-01-25
Part of: Validation Framework Improvements - P0
"""

import sys
import os
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from validation.validators.consistency.cross_phase_validator import CrossPhaseValidator, ConsistencyResult


def main():
    parser = argparse.ArgumentParser(description='Check cross-phase consistency')
    parser.add_argument('--date', required=True, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Run validation
    validator = CrossPhaseValidator()
    results = validator.validate(args.date)

    # Print results
    print("\n" + "=" * 70)
    print(f"Cross-Phase Consistency Check: {args.date}")
    print("=" * 70)

    status = "✅ PASSED" if results['passed'] else "❌ FAILED"
    print(f"\nOverall Status: {status}")

    # Phase coverage details
    print("\n📊 PHASE TRANSITIONS:")
    for check in results['checks']:
        status_icon = "✅" if check.passed else "❌"
        print(f"\n  {status_icon} {check.check_name}:")
        print(f"     Coverage: {check.match_rate:.1%} ({check.target_count}/{check.source_count})")
        print(f"     Expected: {check.expected_rate:.0%}")
        print(f"     Missing: {check.missing_count} records")

        if not check.passed:
            print(f"     ⚠️  Below threshold - {check.message}")

    # Errors
    if results['errors']:
        print("\n❌ ERRORS:")
        for result in results['errors']:
            print(f"  • {result.message}")
            print(f"    Action needed: Investigate and reprocess downstream phase")

    # Warnings
    if results['warnings']:
        print("\n⚠️  WARNINGS:")
        for result in results['warnings']:
            if isinstance(result, ConsistencyResult):
                print(f"  • {result.message}")
            else:
                print(f"  • {result.get('check', 'unknown')}: {result.get('message', '')}")

    print("\n" + "=" * 70 + "\n")

    return 0 if results['passed'] else 1


if __name__ == "__main__":
    sys.exit(main())
