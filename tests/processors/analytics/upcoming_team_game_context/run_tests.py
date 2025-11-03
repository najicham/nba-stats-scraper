#!/usr/bin/env python3
"""
Path: tests/processors/analytics/upcoming_team_game_context/run_tests.py

Test Runner for Upcoming Team Game Context Processor

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
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests...")
    elif test_type == 'validation':
        cmd.append('test_validation.py')
        print("✅ Running Validation Tests...")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (Unit + Integration)...")
    else:
        print("🚀 Running All Tests...")
    
    # Options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    if coverage:
        cmd.extend([
            '--cov=data_processors.analytics.upcoming_team_game_context',
            '--cov-report=html',
            '--cov-report=term-missing'
        ])
        print("📊 Coverage report will be generated")
    
    # Additional pytest options
    cmd.extend([
        '--tb=short',           # Short traceback format
        '--color=yes',          # Colored output
        '-ra'                   # Show summary of all test outcomes
    ])
    
    print(f"\n{'='*80}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*80}\n")
    
    result = subprocess.run(cmd)
    return result.returncode


def print_help():
    """Print help message."""
    print(__doc__)
    print("\nTest Types:")
    print("  unit         - Fast unit tests (~10s, 35+ tests)")
    print("  integration  - Integration tests (~15s, 8 tests)")
    print("  validation   - Validation tests (~30s, 15 tests)")
    print("  quick        - Unit + Integration (~25s)")
    print("  all          - All tests (~55s)")
    print("\nOptions:")
    print("  --coverage   - Generate coverage report")
    print("  --verbose    - Verbose output with details")
    print("  --help, -h   - Show this help message")


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    test_type = 'all'
    coverage = False
    verbose = False
    
    # Parse arguments
    if '-h' in args or '--help' in args:
        print_help()
        return 0
    
    for arg in args:
        if arg in ['unit', 'integration', 'validation', 'quick', 'all']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
        else:
            print(f"⚠️  Unknown argument: {arg}")
            print("Use --help for usage information")
            return 1
    
    # Run tests
    exit_code = run_tests(test_type, coverage, verbose)
    
    # Print summary
    print(f"\n{'='*80}")
    if exit_code == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print(f"{'='*80}\n")
    
    return exit_code


if __name__ == '__main__':
    sys.exit(main())