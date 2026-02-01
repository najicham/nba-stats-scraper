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


def check_validation_symlinks(cf_dir: Path) -> list[dict]:
    """
    Check for missing symlinks in shared/validation/ directory.

    Added after Feb 1, 2026 incident where phase3_data_quality_check.py was missing,
    causing orchestrator to crash on startup.
    """
    issues = []

    validation_dir = cf_dir / "shared" / "validation"
    if not validation_dir.exists():
        return issues  # Directory doesn't exist, will be caught by other checks

    # Check shared/validation/__init__.py for imports that need symlinks
    init_file = validation_dir / "__init__.py"
    if not init_file.exists():
        return issues

    try:
        with open(init_file) as f:
            tree = ast.parse(f.read())

        # Find all modules imported from shared.validation
        required_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and node.module.startswith("shared.validation."):
                    # from shared.validation.X import ...
                    module_name = node.module.replace("shared.validation.", "")
                    required_modules.add(module_name)

        # Check each required module exists as a symlink or file
        for module_name in required_modules:
            module_file = validation_dir / f"{module_name}.py"

            if not module_file.exists():
                issues.append({
                    "type": "MISSING_VALIDATION_MODULE",
                    "path": f"shared/validation/{module_name}.py",
                    "message": f"Module imported in __init__.py but file/symlink missing",
                    "fix": f"cd {validation_dir} && ln -s ../../../../../shared/validation/{module_name}.py {module_name}.py"
                })

    except SyntaxError as e:
        issues.append({
            "type": "SYNTAX_ERROR",
            "path": "shared/validation/__init__.py",
            "message": f"Could not parse __init__.py: {e}"
        })

    return issues


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

    # Check validation symlinks first (Feb 1, 2026 fix)
    validation_issues = check_validation_symlinks(cf_dir)
    issues.extend(validation_issues)

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

    # Dynamically extract ALL imports from shared/utils/__init__.py
    # This catches any module imported at load time or via lazy loading
    utils_init = cf_shared / "utils" / "__init__.py"
    if utils_init.exists():
        try:
            with open(utils_init) as f:
                tree = ast.parse(f.read())

            # Extract all relative imports (from .module import ...)
            required_modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # Check for relative imports like "from .bigquery_client import ..."
                    if node.level == 1 and node.module:  # level=1 means "from ."
                        required_modules.add(node.module)
                    # Also check for "from . import X" style imports
                    elif node.level == 1 and node.module is None:
                        for alias in node.names:
                            required_modules.add(alias.name)

            # Also check __getattr__ lazy loading for modules that are loaded on access
            with open(utils_init) as f:
                content = f.read()

            # Look for lazy import patterns like: from .rate_limiter import ...
            import re
            lazy_patterns = re.findall(r"from\s+\.(\w+)\s+import", content)
            required_modules.update(lazy_patterns)

            # Check each required module exists
            for module_name in required_modules:
                module_file = cf_shared / "utils" / f"{module_name}.py"
                module_dir = cf_shared / "utils" / module_name

                if not module_file.exists() and not module_dir.exists():
                    issues.append({
                        "type": "MISSING_MODULE",
                        "path": f"shared/utils/{module_name}.py",
                        "message": f"Module imported in __init__.py but file missing",
                        "fix": f"ln -sf ../../../../../shared/utils/{module_name}.py {cf_dir}/shared/utils/{module_name}.py"
                    })
        except SyntaxError as e:
            issues.append({
                "type": "SYNTAX_ERROR",
                "path": "shared/utils/__init__.py",
                "message": f"Could not parse __init__.py: {e}"
            })

    return issues


def test_actual_import(cf_dir: Path) -> list[dict]:
    """
    Actually try to import the shared.utils module to catch any missing dependencies.

    This is the most reliable check - if Python can import it, it will work in production.
    """
    import subprocess
    import tempfile

    issues = []

    # Create a test script that imports shared.utils
    test_code = '''
import sys
sys.path.insert(0, "{cf_dir}")
try:
    # This will trigger __init__.py which imports all modules
    import shared.utils
    print("SUCCESS: shared.utils imported successfully")
    sys.exit(0)
except ModuleNotFoundError as e:
    print(f"IMPORT_ERROR: {{e}}")
    sys.exit(1)
except Exception as e:
    print(f"OTHER_ERROR: {{e}}")
    sys.exit(2)
'''.format(cf_dir=cf_dir)

    # Run in subprocess to isolate from current Python environment
    try:
        result = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(cf_dir)
        )

        if result.returncode != 0:
            error_output = result.stdout + result.stderr
            if "IMPORT_ERROR:" in error_output:
                # Extract the module that failed
                for line in error_output.split('\n'):
                    if "IMPORT_ERROR:" in line:
                        issues.append({
                            "type": "IMPORT_FAILURE",
                            "path": "shared/utils",
                            "message": line.replace("IMPORT_ERROR: ", "")
                        })
            elif "OTHER_ERROR:" in error_output:
                issues.append({
                    "type": "IMPORT_ERROR",
                    "path": "shared/utils",
                    "message": error_output.strip()
                })
            else:
                issues.append({
                    "type": "IMPORT_ERROR",
                    "path": "shared/utils",
                    "message": f"Import failed: {error_output.strip()}"
                })
    except subprocess.TimeoutExpired:
        issues.append({
            "type": "TIMEOUT",
            "path": "shared/utils",
            "message": "Import test timed out after 30 seconds"
        })
    except Exception as e:
        issues.append({
            "type": "TEST_ERROR",
            "path": "shared/utils",
            "message": f"Could not run import test: {e}"
        })

    return issues


def validate_cloud_function(cf_name: str, cf_dir: Path, run_import_test: bool = True) -> bool:
    """Validate a single Cloud Function."""
    print(f"\nValidating: {cf_name}")
    print("-" * 40)

    if not cf_dir.exists():
        print(f"  ERROR: Directory not found: {cf_dir}")
        return False

    # Static analysis check
    issues = check_shared_modules(cf_dir)

    # Runtime import test (most reliable)
    if run_import_test and not issues:
        print("  Running import test...")
        import_issues = test_actual_import(cf_dir)
        issues.extend(import_issues)

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
        ("daily_health_summary", cf_base / "daily_health_summary"),
        ("self_heal", cf_base / "self_heal"),
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
