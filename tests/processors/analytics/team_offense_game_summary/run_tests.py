#!/usr/bin/env python3
"""
Test Runner for Team Offense Game Summary Processor

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit + integration)
    python run_tests.py --verbose      # Run with verbose output

Path: tests/processors/analytics/team_offense_game_summary/run_tests.py
"""

import sys
import subprocess


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
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests...")
    else:
        print("🚀 Running All Tests...")
    
    # Options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    if coverage:
        cmd.extend([
            '--cov=analytics_processors.team_offense_game_summary',
            '--cov-report=html',
            '--cov-report=term'
        ])
        print("📊 Coverage report will be generated")
    
    cmd.extend(['--tb=short', '--color=yes'])
    
    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    return result.returncode


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    test_type = 'all'
    coverage = False
    verbose = False
    
    if '-h' in args or '--help' in args:
        print(__doc__)
        return 0
    
    for arg in args:
        if arg in ['unit', 'integration', 'quick']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
    
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())
