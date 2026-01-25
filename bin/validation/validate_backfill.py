#!/usr/bin/env python3
"""
Post-Backfill Validation CLI

Validates that a backfill successfully recovered data.

Usage:
    python bin/validation/validate_backfill.py --phase raw --date 2026-01-24
    python bin/validation/validate_backfill.py --phase raw --date 2026-01-24 --expected 7

Created: 2026-01-25
Part of: Validation Framework Improvements - P1
"""

import sys
import os
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from validation.validators.recovery.post_backfill_validator import PostBackfillValidator


def main():
    parser = argparse.ArgumentParser(description='Validate backfill results')
    parser.add_argument('--phase', required=True,
                        choices=['raw', 'analytics', 'precompute', 'predictions'],
                        help='Phase that was backfilled')
    parser.add_argument('--date', required=True, help='Date that was backfilled (YYYY-MM-DD)')
    parser.add_argument('--expected', type=int, help='Expected record count')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Run validation
    validator = PostBackfillValidator()
    result = validator.validate(args.phase, args.date, args.expected)

    # Print results
    print("\n" + "=" * 70)
    print(f"Post-Backfill Validation: {args.phase} - {args.date}")
    print("=" * 70)

    status = "✅ PASSED" if result.passed else "❌ FAILED"
    print(f"\nOverall Status: {status}")

    # Check details
    print("\n📋 VALIDATION CHECKS:")
    gap_icon = "✅" if result.gap_filled else "❌"
    quality_icon = "✅" if result.quality_acceptable else "❌"
    downstream_icon = "✅" if result.downstream_reprocessed else "❌"

    print(f"  {gap_icon} Gap Filled: {'Yes' if result.gap_filled else 'No'}")
    print(f"  {quality_icon} Quality Acceptable: {'Yes' if result.quality_acceptable else 'No'}")
    print(f"  {downstream_icon} Downstream Reprocessed: {'Yes' if result.downstream_reprocessed else 'No'}")

    # Issues
    if result.issues:
        print("\n⚠️  ISSUES FOUND:")
        for issue in result.issues:
            print(f"  • {issue}")

    # Recommendations
    if result.recommendations:
        print("\n💡 RECOMMENDED ACTIONS:")
        for rec in result.recommendations:
            print(f"  • {rec}")

    # Metrics
    print("\n📊 METRICS:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 70 + "\n")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
