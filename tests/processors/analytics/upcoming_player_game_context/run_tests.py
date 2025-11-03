#!/usr/bin/env python3
"""
Test Runner for UpcomingPlayerGameContext Processor

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py integration    # Run only integration tests  
    python run_tests.py validation     # Run only validation tests
    python run_tests.py --coverage     # Run with coverage report
    python run_tests.py --quick        # Run fast tests (unit + integration)
    python run_tests.py --verbose      # Run with verbose output
"""

import sys
import subprocess
import os

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
            '--cov=data_processors.analytics.upcoming_player_game_context',
            '--cov-report=html',
            '--cov-report=term'
        ])
    
    cmd.extend(['--tb=short', '--color=yes'])
    
    # Change to test directory
    test_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(test_dir)
    
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
        if arg in ['unit', 'integration', 'validation', 'quick']:
            test_type = arg
        elif arg in ['--coverage', '-c']:
            coverage = True
        elif arg in ['--verbose', '-v']:
            verbose = True
    
    return run_tests(test_type, coverage, verbose)


if __name__ == '__main__':
    sys.exit(main())
