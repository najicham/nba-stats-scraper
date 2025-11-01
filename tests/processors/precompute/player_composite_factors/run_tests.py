#!/usr/bin/env python3
"""
Path: tests/processors/precompute/player_composite_factors/run_tests.py

Test Runner for Player Composite Factors Processor
===================================================

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests
    python run_tests.py validation     # Run only validation tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit + integration)
    python run_tests.py --verbose      # Run with verbose output
    python run_tests.py --help         # Show this help

Examples:
    python run_tests.py unit -v        # Run unit tests with verbose output
    python run_tests.py quick --coverage   # Run quick tests with coverage
    python run_tests.py                # Run all tests (default)
"""

import sys
import subprocess
import os


def run_tests(test_type='all', coverage=False, verbose=False):
    """
    Run tests with specified options.
    
    Args:
        test_type: Type of tests to run ('all', 'unit', 'integration', 'validation', 'quick')
        coverage: Whether to generate coverage report
        verbose: Whether to use verbose output
        
    Returns:
        Exit code from pytest
    """
    cmd = ['pytest']
    
    # Test selection
    if test_type == 'unit':
        cmd.append('test_unit.py')
        print("🧪 Running Unit Tests...")
        print("   Target: 39 tests, <10 seconds")
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests...")
        print("   Target: 8 tests, <15 seconds")
    elif test_type == 'validation':
        cmd.append('test_validation.py')
        print("✅ Running Validation Tests...")
        print("   Target: 15 tests, ~30 seconds")
        print("   Note: Requires BigQuery access")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (Unit + Integration)...")
        print("   Target: 47 tests, <25 seconds")
    else:
        print("🚀 Running All Tests...")
        print("   Unit: 39 tests")
        print("   Integration: 8 tests")
        print("   Validation: 15 tests")
        print("   Total: 62 tests, ~45 seconds")
    
    # Verbosity options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    # Coverage options
    if coverage:
        cmd.extend([
            '--cov=data_processors.precompute.player_composite_factors',
            '--cov-report=html',
            '--cov-report=term',
            '--cov-report=term-missing'
        ])
        print("📊 Coverage report will be generated in htmlcov/")
    
    # Additional pytest options
    cmd.extend([
        '--tb=short',        # Short traceback format
        '--color=yes',       # Colorized output
        '-ra',               # Show summary of all test outcomes
        '--strict-markers',  # Strict marker checking
    ])
    
    print("\n" + "="*70)
    print(f"Command: {' '.join(cmd)}")
    print("="*70 + "\n")
    
    # Run tests
    result = subprocess.run(cmd)
    
    print("\n" + "="*70)
    if result.returncode == 0:
        print("✅ All tests passed!")
    else:
        print(f"❌ Tests failed with exit code {result.returncode}")
    print("="*70 + "\n")
    
    return result.returncode


def show_help():
    """Display help message."""
    print(__doc__)
    return 0


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    # Parse arguments
    test_type = 'all'
    coverage = False
    verbose = False
    
    if '-h' in args or '--help' in args:
        return show_help()
    
    # Parse test type
    for arg in args:
        if arg in ['unit', 'integration', 'validation', 'quick', 'all']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v', '-vv']:
            verbose = True
    
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())
