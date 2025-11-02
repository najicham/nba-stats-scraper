#!/usr/bin/env python3
"""
Path: tests/processors/raw/nbacom/nbac_team_boxscore/run_tests.py

Test Runner for NBA.com Team Boxscore Processor

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit only for now)
    python run_tests.py --verbose      # Run with verbose output
    
Examples:
    python run_tests.py unit --coverage
    python run_tests.py --quick --verbose
    python run_tests.py unit
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
    elif test_type == 'quick':
        cmd.append('test_unit.py')
        print("⚡ Running Quick Tests (Unit)...")
    else:
        print("🚀 Running All Tests...")
    
    # Options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    if coverage:
        cmd.extend([
            '--cov=data_processors.raw.nbacom.nbac_team_boxscore_processor',
            '--cov-report=html',
            '--cov-report=term'
        ])
    
    cmd.extend(['--tb=short', '--color=yes'])
    
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
