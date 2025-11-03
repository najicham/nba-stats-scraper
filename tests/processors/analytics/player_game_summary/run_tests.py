#!/usr/bin/env python3
"""
Test Runner for Player Game Summary Processor

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests
    python run_tests.py validation     # Run only validation tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit + integration)
    python run_tests.py --verbose      # Run with verbose output
    
Examples:
    python run_tests.py unit --verbose
    python run_tests.py --coverage
    python run_tests.py quick
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
        print("   51 tests covering:")
        print("   - Dependency configuration")
        print("   - Minutes/plus-minus parsing")
        print("   - Numeric cleaning")
        print("   - Validation methods")
        print("   - Analytics calculation")
        print("   - Source tracking fields")
        print()
        
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
        print()
    
    # Options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    if coverage:
        cmd.extend([
            '--cov=data_processors.analytics.player_game_summary',
            '--cov-report=html',
            '--cov-report=term',
            '--cov-report=term-missing'
        ])
        print("📊 Coverage report will be generated in htmlcov/")
        print()
    
    cmd.extend([
        '--tb=short',
        '--color=yes',
        '-W', 'ignore::DeprecationWarning'
    ])
    
    # Run tests
    print(f"Command: {' '.join(cmd)}")
    print("=" * 70)
    print()
    
    result = subprocess.run(cmd)
    
    print()
    print("=" * 70)
    
    if result.returncode == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    
    if coverage:
        print()
        print("📊 Open htmlcov/index.html to view detailed coverage report")
    
    return result.returncode


def print_help():
    """Print help message."""
    print(__doc__)
    print("\nTest File Structure:")
    print("  test_unit.py         - 51 unit tests (~5s)")
    print("  test_integration.py  - Integration tests (~10s)")
    print("  test_validation.py   - Validation tests (~30s)")
    print()
    print("Quick Start:")
    print("  1. Run unit tests:       python run_tests.py unit")
    print("  2. Check coverage:       python run_tests.py unit --coverage")
    print("  3. Run all fast tests:   python run_tests.py quick")
    print()


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    # Check if in correct directory
    if not Path('test_unit.py').exists():
        print("❌ Error: test_unit.py not found")
        print("   Run this script from: tests/processors/analytics/player_game_summary/")
        return 1
    
    # Parse arguments
    test_type = 'all'
    coverage = False
    verbose = False
    
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
            print(f"   Use --help to see available options")
            return 1
    
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())