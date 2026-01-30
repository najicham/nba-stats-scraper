#!/usr/bin/env python3
"""
Pre-Deployment Validation Script

Validates infrastructure and code before deploying Cloud Functions.
Catches common issues early to prevent deployment failures.

Checks:
1. Old import patterns (shared.utils → orchestration.shared.utils)
2. Required BigQuery tables exist
3. Required Pub/Sub topics exist
4. Python syntax is valid
5. Required dependencies are met

Usage:
    python bin/validation/pre_deployment_check.py
    python bin/validation/pre_deployment_check.py --function phase2_to_phase3
    python bin/validation/pre_deployment_check.py --strict  # Fail on warnings

Exit codes:
    0 - All checks passed
    1 - Critical errors found (must fix before deploying)
    2 - Warnings found (can deploy but should review)
"""

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import List, Tuple, Set

try:
    from google.cloud import bigquery, pubsub_v1
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

# Modules that should use orchestration.shared.utils (consolidated)
CONSOLIDATED_MODULES = [
    'completion_tracker',
    'phase_execution_logger',
    'bigquery_utils',
    'notification_system',
    'proxy_manager',
    'player_name_resolver',
    'roster_manager',
    'nba_team_mapper',
    'email_alerting_ses',
    'schedule',
]

# Required BigQuery tables
REQUIRED_TABLES = [
    'nba_orchestration.phase_completions',
    'nba_orchestration.phase_execution_log',
    'nba_orchestration.processor_completions',
]

# Required Pub/Sub topics for orchestration
REQUIRED_TOPICS = [
    'nba-phase2-raw-complete',
    'nba-phase3-analytics-complete',
    'nba-phase4-precompute-complete',  # Fixed: was nba-phase4-features-complete
    'nba-phase5-predictions-complete',
]


class ValidationResult:
    """Stores validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, message: str):
        self.errors.append(message)

    def add_warning(self, message: str):
        self.warnings.append(message)

    def add_info(self, message: str):
        self.info.append(message)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def print_results(self):
        """Print all validation results."""
        if self.errors:
            print("\n" + "=" * 80)
            print("❌ CRITICAL ERRORS (must fix before deploying):")
            print("=" * 80)
            for error in self.errors:
                print(f"  ❌ {error}")

        if self.warnings:
            print("\n" + "=" * 80)
            print("⚠️  WARNINGS (review recommended):")
            print("=" * 80)
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")

        if self.info:
            print("\n" + "=" * 80)
            print("ℹ️  INFO:")
            print("=" * 80)
            for info_msg in self.info:
                print(f"  ℹ️  {info_msg}")

        # Summary
        print("\n" + "=" * 80)
        if not self.errors and not self.warnings:
            print("✅ ALL CHECKS PASSED - Safe to deploy!")
        elif self.errors:
            print(f"❌ {len(self.errors)} critical error(s) found - DO NOT DEPLOY")
        else:
            print(f"⚠️  {len(self.warnings)} warning(s) found - Review before deploying")
        print("=" * 80)


def check_import_patterns(function_dir: Path, result: ValidationResult):
    """Check for old import patterns in Cloud Function code."""
    print(f"Checking import patterns in {function_dir.name}...")

    files_checked = 0
    for py_file in function_dir.rglob('*.py'):
        files_checked += 1
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for old imports of consolidated modules
        for module in CONSOLIDATED_MODULES:
            pattern = f"from shared\\.utils\\.{module}"
            if re.search(pattern, content):
                result.add_error(
                    f"{py_file.relative_to(function_dir)}: Uses old import 'from shared.utils.{module}' "
                    f"(should be 'from shared.utils.{module}')"
                )

    result.add_info(f"Checked {files_checked} Python files for import patterns")


def check_syntax(function_dir: Path, result: ValidationResult):
    """Check Python syntax is valid."""
    print(f"Checking Python syntax in {function_dir.name}...")

    files_checked = 0
    for py_file in function_dir.rglob('*.py'):
        files_checked += 1
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                ast.parse(f.read(), filename=str(py_file))
        except SyntaxError as e:
            result.add_error(f"{py_file.relative_to(function_dir)}: Syntax error at line {e.lineno}: {e.msg}")

    result.add_info(f"Checked {files_checked} Python files for syntax errors")


def check_bigquery_tables(project_id: str, result: ValidationResult):
    """Check required BigQuery tables exist."""
    if not GCP_AVAILABLE:
        result.add_warning("google-cloud-bigquery not installed - skipping BigQuery table checks")
        return

    print("Checking required BigQuery tables...")

    try:
        client = bigquery.Client(project=project_id)

        for table_id in REQUIRED_TABLES:
            full_table_id = f"{project_id}.{table_id}"
            try:
                client.get_table(full_table_id)
                result.add_info(f"✓ Table exists: {table_id}")
            except Exception:
                result.add_error(f"Required table missing: {table_id}")

    except Exception as e:
        result.add_warning(f"Could not check BigQuery tables: {e}")


def check_pubsub_topics(project_id: str, result: ValidationResult):
    """Check required Pub/Sub topics exist."""
    if not GCP_AVAILABLE:
        result.add_warning("google-cloud-pubsub not installed - skipping Pub/Sub topic checks")
        return

    print("Checking required Pub/Sub topics...")

    try:
        publisher = pubsub_v1.PublisherClient()

        for topic_name in REQUIRED_TOPICS:
            topic_path = f"projects/{project_id}/topics/{topic_name}"
            try:
                publisher.get_topic(request={"topic": topic_path})
                result.add_info(f"✓ Topic exists: {topic_name}")
            except Exception:
                result.add_warning(f"Topic not found (will be created if needed): {topic_name}")

    except Exception as e:
        result.add_warning(f"Could not check Pub/Sub topics: {e}")


def check_requirements_txt(function_dir: Path, result: ValidationResult):
    """Check requirements.txt exists and has required packages."""
    print(f"Checking requirements.txt in {function_dir.name}...")

    req_file = function_dir / "requirements.txt"
    if not req_file.exists():
        result.add_error(f"requirements.txt not found in {function_dir.name}")
        return

    with open(req_file, 'r') as f:
        requirements = f.read()

    # Check for essential packages
    if 'functions-framework' not in requirements:
        result.add_error("requirements.txt missing functions-framework")
    if 'google-cloud-bigquery' not in requirements:
        result.add_warning("requirements.txt missing google-cloud-bigquery")
    if 'google-cloud-firestore' not in requirements:
        result.add_warning("requirements.txt missing google-cloud-firestore")

    result.add_info("requirements.txt found with required packages")


def main():
    parser = argparse.ArgumentParser(description='Pre-deployment validation')
    parser.add_argument('--function', help='Specific Cloud Function to check (e.g., phase2_to_phase3)')
    parser.add_argument('--project', default='nba-props-platform', help='GCP project ID')
    parser.add_argument('--strict', action='store_true', help='Treat warnings as errors')
    args = parser.parse_args()

    result = ValidationResult()

    print("=" * 80)
    print("PRE-DEPLOYMENT VALIDATION")
    print("=" * 80)

    # Determine which functions to check
    if args.function:
        function_dirs = [Path(f"orchestration/cloud_functions/{args.function}")]
        if not function_dirs[0].exists():
            print(f"❌ Error: Function directory not found: {args.function}")
            return 1
    else:
        # Check all phase orchestrators
        function_dirs = [
            Path("orchestration/cloud_functions/phase2_to_phase3"),
            Path("orchestration/cloud_functions/phase3_to_phase4"),
            Path("orchestration/cloud_functions/phase4_to_phase5"),
            Path("orchestration/cloud_functions/phase5_to_phase6"),
        ]

    # Run checks on each function
    for func_dir in function_dirs:
        if func_dir.exists():
            print(f"\n{'─' * 80}")
            print(f"Validating: {func_dir.name}")
            print(f"{'─' * 80}")
            check_import_patterns(func_dir, result)
            check_syntax(func_dir, result)
            check_requirements_txt(func_dir, result)

    # Run infrastructure checks (once for all functions)
    print(f"\n{'─' * 80}")
    print("Validating infrastructure...")
    print(f"{'─' * 80}")
    check_bigquery_tables(args.project, result)
    check_pubsub_topics(args.project, result)

    # Print results
    result.print_results()

    # Determine exit code
    if result.has_errors():
        return 1
    elif args.strict and result.has_warnings():
        print("\n⚠️  Running in strict mode - treating warnings as errors")
        return 2
    elif result.has_warnings():
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
