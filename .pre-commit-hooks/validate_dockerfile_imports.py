#!/usr/bin/env python3
"""
Validate that Dockerfiles copy all directories needed for imports.

This prevents the class of bugs where code changes imports but Dockerfile isn't
updated to copy the required directories.

Usage:
    python .pre-commit-hooks/validate_dockerfile_imports.py

Exit codes:
    0 - All imports are satisfiable
    1 - Missing COPY statements detected
"""

import ast
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# Service configurations: (dockerfile_path, python_sources)
SERVICE_CONFIGS = [
    (
        'predictions/coordinator/Dockerfile',
        ['predictions/coordinator/'],
    ),
    (
        'predictions/worker/Dockerfile',
        ['predictions/worker/'],
    ),
    (
        'data_processors/analytics/Dockerfile',
        ['data_processors/analytics/'],
    ),
    (
        'data_processors/precompute/Dockerfile',
        ['data_processors/precompute/'],
    ),
]


def parse_dockerfile_copies(dockerfile_path: str) -> Set[str]:
    """Extract directories that are COPYed in the Dockerfile."""
    if not os.path.exists(dockerfile_path):
        return set()

    copies = set()
    with open(dockerfile_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Match COPY source/ ./dest/ or COPY source/ dest/
            match = re.match(r'^COPY\s+(\S+)\s+', line)
            if match:
                source = match.group(1)
                # Normalize: remove trailing slash, get directory name
                source = source.rstrip('/')
                copies.add(source)

    return copies


def extract_imports_from_file(filepath: str) -> Set[str]:
    """Extract all import statements from a Python file."""
    imports = set()

    try:
        with open(filepath, 'r') as f:
            content = f.read()

        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except (SyntaxError, UnicodeDecodeError):
        # Skip files that can't be parsed
        pass

    return imports


def get_all_imports(source_dirs: List[str]) -> Set[str]:
    """Get all imports from Python files in the given directories."""
    imports = set()

    for source_dir in source_dirs:
        if not os.path.exists(source_dir):
            continue

        for root, dirs, files in os.walk(source_dir):
            # Skip test directories and __pycache__
            dirs[:] = [d for d in dirs if d not in ('__pycache__', 'tests', 'test')]

            for filename in files:
                if filename.endswith('.py'):
                    filepath = os.path.join(root, filename)
                    imports.update(extract_imports_from_file(filepath))

    return imports


def check_service(dockerfile_path: str, source_dirs: List[str]) -> List[str]:
    """Check if a service's Dockerfile copies all needed directories."""
    errors = []

    # Get what's copied
    copies = parse_dockerfile_copies(dockerfile_path)

    # Get what's imported
    imports = get_all_imports(source_dirs)

    # Local project packages that need to be copied
    local_packages = {'shared', 'predictions', 'data_processors', 'scrapers', 'orchestration'}

    # Check each local import
    for imp in imports:
        if imp in local_packages:
            # Check if it's copied
            # Handle both 'predictions' (top-level) and 'predictions/worker' (subdir)
            found = False
            for copy in copies:
                if copy == imp or copy.startswith(f'{imp}/') or copy == f'{imp}/__init__.py':
                    found = True
                    break

            if not found:
                # Check if any subdir of this package is copied
                subdirs_copied = [c for c in copies if c.startswith(f'{imp}/')]
                if not subdirs_copied:
                    errors.append(f"Import '{imp}' not satisfied - no COPY for '{imp}/' in {dockerfile_path}")

    return errors


def main():
    """Run validation on all service Dockerfiles."""
    all_errors = []

    for dockerfile_path, source_dirs in SERVICE_CONFIGS:
        if not os.path.exists(dockerfile_path):
            continue

        errors = check_service(dockerfile_path, source_dirs)
        all_errors.extend(errors)

    if all_errors:
        print("❌ Dockerfile import validation FAILED:")
        for error in all_errors:
            print(f"  - {error}")
        print("\nFix: Add COPY statements to the Dockerfile for the missing directories")
        return 1

    print("✅ Dockerfile imports validated")
    return 0


if __name__ == '__main__':
    sys.exit(main())
