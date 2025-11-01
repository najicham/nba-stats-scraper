#!/usr/bin/env python3
"""
Path: tests/processors/precompute/player_daily_cache/run_tests.py

Test Runner for Player Daily Cache Processor

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests
    python run_tests.py validation     # Run only validation tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit + integration)
    python run_tests.py --verbose      # Run with verbose output
    
Examples:
    python run_tests.py unit --coverage
    python run_tests.py quick --verbose
    python run_tests.py
"""

import sys
import subprocess
from pathlib import Path


def run_tests(test_type='all', coverage=False, verbose=False):
    """Run tests with specified options."""
    cmd = ['pytest']
    
    # Test selection
    if test_type == 'unit':
        cmd.append('test_unit.py')
        print("🧪 Running Unit Tests...")
        print("   35 tests, ~5-10 seconds")
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests...")
        print("   8 tests, ~10 seconds")
    elif test_type == 'validation':
        cmd.append('test_validation.py')
        print("✅ Running Validation Tests...")
        print("   15 tests, ~30 seconds (requires BigQuery)")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (Unit + Integration)...")
        print("   43 tests, ~15-20 seconds")
    else:
        print("🚀 Running All Tests...")
        print("   58 tests, ~45 seconds")
    
    # Options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    if coverage:
        cmd.extend([
            '--cov=data_processors.precompute.player_daily_cache',
            '--cov-report=html',
            '--cov-report=term',
            '--cov-report=term-missing'
        ])
        print("📊 Coverage report enabled")
    
    # Additional pytest options
    cmd.extend([
        '--tb=short',           # Short traceback format
        '--color=yes',          # Colored output
        '--durations=10',       # Show 10 slowest tests
    ])
    
    print()
    print("=" * 70)
    result = subprocess.run(cmd)
    print("=" * 70)
    
    if result.returncode == 0:
        print("\n✅ All tests passed!")
        if coverage:
            print("📊 Coverage report: htmlcov/index.html")
    else:
        print("\n❌ Some tests failed")
    
    return result.returncode


def print_help():
    """Print help message."""
    print(__doc__)


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    test_type = 'all'
    coverage = False
    verbose = False
    
    # Parse arguments
    for arg in args:
        if arg in ['-h', '--help']:
            print_help()
            return 0
        elif arg in ['unit', 'integration', 'validation', 'quick']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
        elif arg.startswith('-'):
            print(f"Unknown option: {arg}")
            print("Run with --help for usage information")
            return 1
    
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())
