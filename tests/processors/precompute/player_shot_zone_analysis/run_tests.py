#!/usr/bin/env python3
"""
Test Runner for Player Shot Zone Analysis Processor

Runs unit, integration, and validation tests with various options.

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py unit               # Run only unit tests
    python run_tests.py integration        # Run only integration tests
    python run_tests.py validation         # Run only validation tests
    python run_tests.py --coverage         # Run with coverage report
    python run_tests.py --quick            # Run fast tests only (unit + integration)
    python run_tests.py --verbose          # Run with verbose output
"""

import sys
import subprocess
from pathlib import Path


def run_tests(test_type='all', coverage=False, verbose=False):
    """
    Run tests with specified options.
    
    Args:
        test_type: 'all', 'unit', 'integration', 'validation', or 'quick'
        coverage: Generate coverage report
        verbose: Verbose output
    """
    # Base pytest command
    cmd = ['pytest']
    
    # Test selection
    if test_type == 'unit':
        cmd.append('test_unit.py')
        print("🧪 Running Unit Tests (fast, isolated)...")
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests (end-to-end)...")
    elif test_type == 'validation':
        cmd.append('test_validation.py')
        print("✅ Running Validation Tests (real BigQuery)...")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (unit + integration)...")
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
            '--cov=data_processors.precompute.player_shot_zone_analysis',
            '--cov-report=html',
            '--cov-report=term'
        ])
        print("📊 Coverage report will be generated...")
    
    # Output formatting
    cmd.extend([
        '--tb=short',           # Short traceback format
        '--color=yes',          # Colored output
    ])
    
    # Run tests
    print(f"\n💻 Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    
    # Summary
    print("\n" + "="*60)
    if result.returncode == 0:
        print("✅ All tests passed!")
        if coverage:
            print("📊 Coverage report: htmlcov/index.html")
    else:
        print("❌ Some tests failed")
        print("💡 Run with --verbose for more details")
    print("="*60 + "\n")
    
    return result.returncode


def print_usage():
    """Print usage information."""
    print(__doc__)


def main():
    """Main entry point."""
    # Parse arguments
    args = sys.argv[1:]
    
    test_type = 'all'
    coverage = False
    verbose = False
    
    # Show help
    if '-h' in args or '--help' in args:
        print_usage()
        return 0
    
    # Parse options
    for arg in args:
        if arg in ['unit', 'integration', 'validation', 'quick']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
        else:
            print(f"❌ Unknown argument: {arg}")
            print_usage()
            return 1
    
    # Run tests
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())
