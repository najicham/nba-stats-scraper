#!/usr/bin/env python3
"""
Validate Cloud Function Import Dependencies

This script checks that all Cloud Functions have the required shared modules
before deployment, preventing "ModuleNotFoundError" startup failures.

Usage:
    python bin/validation/validate_cloud_function_imports.py
    python bin/validation/validate_cloud_function_imports.py --function phase2_to_phase3

Run this:
- Before deploying Cloud Functions
- After modifying shared/ modules
- After running sync_shared_utils.py

Created: 2026-01-24
Reason: Cloud Function failed to start due to missing shared.utils.rate_limiter
"""

import ast
import sys
from pathlib import Path
from typing import Set

# Add project root to path
project_root = Path(__file__).parent.parent.parent


def get_imports_from_file(file_path: Path) -> Set[str]:
    """Extract all imports from a Python file."""
    imports = set()

    try:
        with open(file_path) as f:
            tree = ast.parse(f.read())
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {file_path}: {e}")
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])

    return imports


def get_all_imports_recursive(directory: Path, prefix: str = "") -> Set[str]:
    """Get all imports from all Python files in a directory."""
    all_imports = set()

    for py_file in directory.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        imports = get_imports_from_file(py_file)
        all_imports.update(imports)

    return all_imports


def check_shared_modules(cf_dir: Path) -> list[dict]:
    """Check if all shared module imports can be resolved."""
    issues = []

    cf_shared = cf_dir / "shared"
    if not cf_shared.exists():
        issues.append({
            "type": "MISSING_DIR",
            "path": "shared/",
            "message": "shared/ directory missing from Cloud Function"
        })
        return issues

    # Get all imports from main.py and check shared modules
    main_py = cf_dir / "main.py"
    if not main_py.exists():
        issues.append({
            "type": "MISSING_FILE",
            "path": "main.py",
            "message": "main.py not found"
        })
        return issues

    # Check the __init__.py files for imports that need to resolve
    for init_file in cf_shared.rglob("__init__.py"):
        relative_path = init_file.relative_to(cf_dir)
        imports = get_imports_from_file(init_file)

        for imp in imports:
            if imp.startswith("shared") or imp == ".":
                continue

            # Check if local relative import exists
            parent_dir = init_file.parent
            module_name = imp.split(".")[-1] if "." in imp else imp

            # Check for module file
            module_file = parent_dir / f"{module_name}.py"
            module_dir = parent_dir / module_name

            if not module_file.exists() and not module_dir.exists():
                # Check if it's a from . import
                pass  # These are harder to validate without running

    # Check specific known problematic imports
    utils_init = cf_shared / "utils" / "__init__.py"
    if utils_init.exists():
        with open(utils_init) as f:
            content = f.read()

        # Check for imports that might fail
        problematic_imports = [
            ("rate_limiter", "shared/utils/rate_limiter.py"),
            ("prometheus_metrics", "shared/utils/prometheus_metrics.py"),
            ("roster_manager", "shared/utils/roster_manager.py"),
            ("completion_tracker", "shared/utils/completion_tracker.py"),
            ("proxy_manager", "shared/utils/proxy_manager.py"),
        ]

        for module_name, expected_path in problematic_imports:
            if f"from .{module_name}" in content or f"import {module_name}" in content:
                module_file = cf_shared / "utils" / f"{module_name}.py"
                if not module_file.exists():
                    issues.append({
                        "type": "MISSING_MODULE",
                        "path": f"shared/utils/{module_name}.py",
                        "message": f"Module imported in __init__.py but file missing",
                        "fix": f"cp shared/utils/{module_name}.py {cf_dir}/shared/utils/"
                    })

    return issues


def validate_cloud_function(cf_name: str, cf_dir: Path) -> bool:
    """Validate a single Cloud Function."""
    print(f"\nValidating: {cf_name}")
    print("-" * 40)

    if not cf_dir.exists():
        print(f"  ERROR: Directory not found: {cf_dir}")
        return False

    issues = check_shared_modules(cf_dir)

    if issues:
        print(f"  FAILED - {len(issues)} issues found:")
        for issue in issues:
            print(f"    - [{issue['type']}] {issue['path']}: {issue['message']}")
            if "fix" in issue:
                print(f"      FIX: {issue['fix']}")
        return False
    else:
        print("  PASSED")
        return True


def main():
    # Define Cloud Functions to check
    cf_base = project_root / "orchestration" / "cloud_functions"

    cloud_functions = [
        ("phase2_to_phase3", cf_base / "phase2_to_phase3"),
        ("phase3_to_phase4", cf_base / "phase3_to_phase4"),
        ("phase4_to_phase5", cf_base / "phase4_to_phase5"),
        ("phase5_to_phase6", cf_base / "phase5_to_phase6"),
        ("auto_backfill_orchestrator", cf_base / "auto_backfill_orchestrator"),
    ]

    # Filter if specific function requested
    if len(sys.argv) > 1 and sys.argv[1] == "--function":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        cloud_functions = [(name, path) for name, path in cloud_functions if name == target]

    print("=" * 60)
    print("Cloud Function Import Validation")
    print("=" * 60)

    all_passed = True
    for cf_name, cf_dir in cloud_functions:
        if not validate_cloud_function(cf_name, cf_dir):
            all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("ALL VALIDATIONS PASSED")
    else:
        print("VALIDATION FAILED - Fix issues before deploying")
        print()
        print("Quick fix: python bin/maintenance/sync_shared_utils.py --all")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
