#!/usr/bin/env python3
"""
Test Runner for Team Defense Game Summary Processor v2.0

Convenient wrapper for running different test suites.

Usage:
    python run_tests.py                 # Run all tests
    python run_tests.py unit            # Run only unit tests
    python run_tests.py integration     # Run only integration tests
    python run_tests.py validation      # Run only validation tests
    python run_tests.py --coverage      # Run with coverage report
    python run_tests.py --quick         # Run fast tests only (unit + integration)
    python run_tests.py --verbose       # Run with verbose output
    python run_tests.py --failed        # Run only previously failed tests

Examples:
    python run_tests.py unit --coverage
    python run_tests.py integration --verbose
    python run_tests.py validation
    python run_tests.py --quick --coverage

Directory: tests/processors/analytics/team_defense_game_summary/
"""

import sys
import subprocess
from pathlib import Path


def run_tests(test_type='all', coverage=False, verbose=False, failed_only=False):
    """
    Run tests with specified options.
    
    Args:
        test_type: 'all', 'unit', 'integration', 'validation', or 'quick'
        coverage: Whether to generate coverage report
        verbose: Whether to run with verbose output
        failed_only: Whether to run only previously failed tests
    
    Returns:
        int: Exit code (0 = success, non-zero = failure)
    """
    cmd = ['pytest']
    
    # Test selection
    if test_type == 'unit':
        cmd.append('test_unit.py')
        print("🧪 Running Unit Tests (Phase 2 Architecture v2.0)...")
        print("   Testing: Perspective flip, multi-source fallback, calculations")
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests...")
        print("   Testing: End-to-end flow with mocked BigQuery")
    elif test_type == 'validation':
        cmd.append('test_validation.py')
        print("✅ Running Validation Tests...")
        print("   Testing: Real BigQuery data quality")
        print("   ⚠️  WARNING: These tests query production BigQuery!")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (Unit + Integration)...")
    else:
        print("🚀 Running All Tests...")
    
    # Verbosity
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    # Coverage
    if coverage:
        cmd.extend([
            '--cov=data_processors.analytics.team_defense_game_summary',
            '--cov-report=html',
            '--cov-report=term-missing',
            '--cov-report=term:skip-covered'
        ])
        print("📊 Coverage reports will be generated in htmlcov/")
    
    # Failed only
    if failed_only:
        cmd.append('--lf')  # Last failed
        print("🔄 Running only previously failed tests...")
    
    # Additional options
    cmd.extend([
        '--tb=short',           # Short traceback format
        '--color=yes',          # Colored output
        '--strict-markers',     # Fail on unknown markers
        '-ra',                  # Show summary of all test outcomes
    ])
    
    # Run tests
    print(f"\n💻 Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    
    # Summary
    print("\n" + "="*70)
    if result.returncode == 0:
        print("✅ All tests passed!")
        if coverage:
            print("📊 Coverage report: htmlcov/index.html")
    else:
        print("❌ Some tests failed!")
        print("💡 Run with --verbose for more details")
        print("💡 Run with --failed to re-run only failed tests")
    print("="*70 + "\n")
    
    return result.returncode


def show_help():
    """Display help message."""
    print(__doc__)
    print("\nTest Suite Overview:")
    print("  Unit Tests:        ~30 tests, ~5 seconds  (test_unit.py)")
    print("  Integration Tests: ~8 tests,  ~10 seconds (test_integration.py)")
    print("  Validation Tests:  ~15 tests, ~30 seconds (test_validation.py)")
    print()
    print("Key Changes in v2.0:")
    print("  ✅ Tests Phase 2 → Phase 3 architecture (not Phase 3 → Phase 3)")
    print("  ✅ Tests perspective flip logic (opponent offense → team defense)")
    print("  ✅ Tests multi-source fallback (gamebook → BDL → NBA.com)")
    print("  ✅ Tests defensive rating calculations")
    print("  ✅ Tests data quality tier assignment")
    print()


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    # Parse arguments
    test_type = 'all'
    coverage = False
    verbose = False
    failed_only = False
    
    if '-h' in args or '--help' in args:
        show_help()
        return 0
    
    for arg in args:
        if arg in ['unit', 'integration', 'validation', 'quick']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
        elif arg in ['--failed', '-f', '--lf']:
            failed_only = True
    
    return run_tests(test_type, coverage, verbose, failed_only)


if __name__ == '__main__':
    sys.exit(main())