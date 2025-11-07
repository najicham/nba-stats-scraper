#!/usr/bin/env python3
"""
Test Runner for ML Feature Store V2 Processor

Convenient script to run tests with various options.
File: tests/processors/precompute/ml_feature_store/run_tests.py

Usage:
    python run_tests.py                  # Run all tests
    python run_tests.py --unit          # Run unit tests only
    python run_tests.py --integration   # Run integration tests only
    python run_tests.py --coverage      # Run with coverage report
    python run_tests.py -v              # Verbose output
    
Examples:
    # Quick unit test run
    python run_tests.py --unit
    
    # Full test suite with coverage
    python run_tests.py --coverage
    
    # Integration tests only (verbose)
    python run_tests.py --integration -v
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_tests(test_type='all', coverage=False, verbose=False):
    """
    Run pytest with specified options.
    
    Args:
        test_type: 'all', 'unit', 'integration'
        coverage: Whether to generate coverage report
        verbose: Whether to use extra verbose output
    """
    # Base command
    cmd = ['pytest']
    
    # Determine test path
    test_dir = Path(__file__).parent
    
    if test_type == 'unit':
        cmd.append(str(test_dir / 'test_unit.py'))
        print("🧪 Running UNIT tests...")
    elif test_type == 'integration':
        cmd.append(str(test_dir / 'test_integration.py'))
        print("🔗 Running INTEGRATION tests...")
    else:
        cmd.append(str(test_dir))
        print("🧪 Running ALL tests...")
    
    # Add coverage options
    if coverage:
        cmd.extend([
            '--cov=data_processors/precompute/ml_feature_store',
            '--cov-report=html',
            '--cov-report=term-missing',
            '--cov-report=term:skip-covered'
        ])
    
    # Add verbosity
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    # Additional options
    cmd.extend([
        '--color=yes',           # Colored output
        '--tb=short',            # Short traceback format
        '--strict-markers',      # Strict marker checking
        '-ra',                   # Show all test outcomes
    ])
    
    print(f"Command: {' '.join(cmd)}\n")
    
    # Run tests
    result = subprocess.run(cmd)
    
    return result.returncode


def main():
    """Parse arguments and run tests."""
    parser = argparse.ArgumentParser(
        description='Run ML Feature Store V2 tests',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Test type selection
    test_group = parser.add_mutually_exclusive_group()
    test_group.add_argument(
        '--unit',
        action='store_true',
        help='Run unit tests only (test_unit.py)'
    )
    test_group.add_argument(
        '--integration',
        action='store_true',
        help='Run integration tests only (test_integration.py)'
    )
    test_group.add_argument(
        '--all',
        action='store_true',
        help='Run all tests (default)'
    )
    
    # Options
    parser.add_argument(
        '--coverage',
        action='store_true',
        help='Generate coverage report (HTML + terminal)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Extra verbose output (-vv)'
    )
    
    args = parser.parse_args()
    
    # Determine test type
    if args.unit:
        test_type = 'unit'
    elif args.integration:
        test_type = 'integration'
    else:
        test_type = 'all'
    
    # Print configuration
    print("="*70)
    print("ML FEATURE STORE V2 - TEST RUNNER")
    print("="*70)
    print(f"Test Type: {test_type.upper()}")
    print(f"Coverage:  {'ON' if args.coverage else 'OFF'}")
    print(f"Verbose:   {'ON' if args.verbose else 'OFF'}")
    print("="*70 + "\n")
    
    # Run tests
    exit_code = run_tests(test_type, args.coverage, args.verbose)
    
    # Print summary
    print("\n" + "="*70)
    if exit_code == 0:
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        if args.coverage:
            print("\n📊 Coverage report: htmlcov/index.html")
    else:
        print(f"❌ TESTS FAILED (exit code: {exit_code})")
        print("="*70)
    print()
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()