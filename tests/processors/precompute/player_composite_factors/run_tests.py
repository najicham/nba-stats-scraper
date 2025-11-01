#!/usr/bin/env python3
"""
Path: tests/processors/precompute/player_composite_factors/run_tests.py

Test Runner for Player Composite Factors Processor
===================================================

Usage:
    python run_tests.py                # Run all tests
    python run_tests.py unit           # Run only unit tests
    python run_tests.py --verbose      # Run with verbose output
"""

import sys
import subprocess


def run_tests(test_type='unit', verbose=False):
    """Run tests with specified options."""
    cmd = ['pytest']
    
    # Test selection
    if test_type == 'unit':
        cmd.append('test_unit.py')
        print("🧪 Running Unit Tests...")
        print("   Target: 25 tests, <10 seconds")
    elif test_type == 'integration':
        cmd.append('test_integration.py')
        print("🔗 Running Integration Tests...")
        print("   Target: 8 tests, ~15 seconds")
    elif test_type == 'quick':
        cmd.extend(['test_unit.py', 'test_integration.py'])
        print("⚡ Running Quick Tests (Unit + Integration)...")
        print("   Target: 33 tests, ~20 seconds")
    elif test_type == 'all':
        print("🚀 Running All Tests...")
        print("   Unit: 25 tests")
        print("   Integration: 8 tests")
        print("   Total: 33 tests")
    
    # Verbosity options
    if verbose:
        cmd.append('-vv')
    else:
        cmd.append('-v')
    
    # Additional pytest options
    cmd.extend([
        '--tb=short',        # Short traceback format
        '--color=yes',       # Colorized output
        '-ra',               # Show summary of all test outcomes
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


def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    # Parse arguments
    test_type = 'unit'
    verbose = False
    
    for arg in args:
        if arg in ['unit', 'integration', 'quick', 'all']:
            test_type = arg
        elif arg in ['--verbose', '-v', '-vv']:
            verbose = True
    
    return run_tests(test_type, verbose)


if __name__ == '__main__':
    sys.exit(main())