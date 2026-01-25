#!/usr/bin/env python3
"""
Quality Trend Monitoring CLI

Runs quality trend validation and reports results.

Usage:
    python bin/validation/quality_trend_monitor.py --date 2026-01-25
    python bin/validation/quality_trend_monitor.py --date 2026-01-25 --lookback 14

Created: 2026-01-25
Part of: Validation Framework Improvements - P0
"""

import sys
import os
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from validation.validators.trends.quality_trend_validator import QualityTrendValidator


def main():
    parser = argparse.ArgumentParser(description='Monitor quality trends')
    parser.add_argument('--date', required=True, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--lookback', type=int, default=7, help='Lookback days (default: 7)')
    parser.add_argument('--baseline', type=int, default=14, help='Baseline days (default: 14)')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Run validation
    validator = QualityTrendValidator()
    results = validator.validate(args.date, args.lookback, args.baseline)

    # Print results
    print("\n" + "=" * 70)
    print(f"Quality Trend Monitoring: {args.date}")
    print(f"Lookback: {args.lookback} days, Baseline: {args.baseline} days")
    print("=" * 70)

    status = "✅ PASSED" if results['passed'] else "❌ FAILED"
    print(f"\nOverall Status: {status}")

    if results['critical']:
        print("\n🚨 CRITICAL ISSUES:")
        for check in results['critical']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change")
            print(f"    Baseline: {check.baseline_value:.1f} → Current: {check.current_value:.1f}")

    if results['errors']:
        print("\n❌ ERRORS:")
        for check in results['errors']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change")
            print(f"    Baseline: {check.baseline_value:.1f} → Current: {check.current_value:.1f}")

    if results['warnings']:
        print("\n⚠️  WARNINGS:")
        for check in results['warnings']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change")
            print(f"    Baseline: {check.baseline_value:.1f} → Current: {check.current_value:.1f}")

    # All checks summary
    print("\n📊 ALL CHECKS:")
    for check in results['checks']:
        status_icon = "✅" if check.passed else "❌"
        print(f"  {status_icon} {check.metric_name}: {check.pct_change:+.1f}% "
              f"({check.baseline_value:.1f} → {check.current_value:.1f})")

    print("\n" + "=" * 70 + "\n")

    return 0 if results['passed'] else 1


if __name__ == "__main__":
    sys.exit(main())
