#!/usr/bin/env python3
"""
bin/monitoring/get_thresholds.py

Outputs validation thresholds as shell-compatible variable assignments.
Used by shell scripts (morning_health_check.sh, daily_health_check.sh) to
source thresholds from the centralized config.

Usage in shell scripts:
    # Source all thresholds
    eval "$(python3 bin/monitoring/get_thresholds.py)"

    # Or source specific thresholds
    eval "$(python3 bin/monitoring/get_thresholds.py --section coverage)"

This ensures shell scripts use the same thresholds as Python validation scripts.
"""

import sys
import os
import argparse

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from config.validation_config import (
    get_minutes_coverage_threshold,
    get_usage_rate_coverage_threshold,
    get_spot_check_threshold,
    get_phase_processors,
    get_threshold,
)


def output_coverage_thresholds():
    """Output coverage thresholds."""
    print(f"MINUTES_WARNING={get_minutes_coverage_threshold('warning')}")
    print(f"MINUTES_CRITICAL={get_minutes_coverage_threshold('critical')}")
    print(f"USAGE_WARNING={get_usage_rate_coverage_threshold('warning')}")
    print(f"USAGE_CRITICAL={get_usage_rate_coverage_threshold('critical')}")


def output_phase_thresholds():
    """Output phase processing thresholds."""
    print(f"EXPECTED_PHASE3_PROCESSORS={get_phase_processors('phase3')}")
    print(f"EXPECTED_PHASE4_PROCESSORS={get_phase_processors('phase4')}")
    print(f"EXPECTED_PHASE5_SYSTEMS={get_phase_processors('phase5')}")


def output_accuracy_thresholds():
    """Output accuracy/spot check thresholds."""
    print(f"SPOT_CHECK_PASS={get_spot_check_threshold('pass')}")
    print(f"SPOT_CHECK_WARNING={get_spot_check_threshold('warning')}")
    print(f"SPOT_CHECK_CRITICAL={get_spot_check_threshold('critical')}")


def output_field_completeness_thresholds():
    """Output field completeness thresholds."""
    print(f"FG_THRESHOLD={get_threshold('fg_attempts', 'pass', section='field_completeness', default=90)}")
    print(f"FT_THRESHOLD={get_threshold('ft_attempts', 'pass', section='field_completeness', default=90)}")
    print(f"THREE_THRESHOLD={get_threshold('three_pt_attempts', 'pass', section='field_completeness', default=90)}")


def output_all_thresholds():
    """Output all thresholds."""
    print("# Coverage thresholds")
    output_coverage_thresholds()
    print("")
    print("# Phase processing thresholds")
    output_phase_thresholds()
    print("")
    print("# Accuracy thresholds")
    output_accuracy_thresholds()
    print("")
    print("# Field completeness thresholds")
    output_field_completeness_thresholds()


def main():
    parser = argparse.ArgumentParser(
        description='Output validation thresholds as shell variables'
    )
    parser.add_argument(
        '--section',
        choices=['all', 'coverage', 'phase', 'accuracy', 'field_completeness'],
        default='all',
        help='Which section of thresholds to output (default: all)'
    )
    args = parser.parse_args()

    if args.section == 'all':
        output_all_thresholds()
    elif args.section == 'coverage':
        output_coverage_thresholds()
    elif args.section == 'phase':
        output_phase_thresholds()
    elif args.section == 'accuracy':
        output_accuracy_thresholds()
    elif args.section == 'field_completeness':
        output_field_completeness_thresholds()


if __name__ == '__main__':
    main()
