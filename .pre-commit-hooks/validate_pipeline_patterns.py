#!/usr/bin/env python3
"""
Pipeline Pattern Validator — Catches bug classes from Session 184

Prevents three categories of production bugs:
1. Invalid enum member usage (e.g., SourceCoverageSeverity.ERROR doesn't exist)
2. Processor name mapping gaps (Phase 2→3 orchestrator won't match)
3. Unsafe request.get_json() calls in Cloud Scheduler endpoints

Created: 2026-02-10 (Session 185)
"""

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'


class PipelinePatternValidator:
    """Validates pipeline patterns to prevent Session 184-class bugs."""

    def __init__(self, base_path: str = '.'):
        self.base_path = Path(base_path)
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []

    def validate_all(self) -> Tuple[int, int]:
        """Run all validations. Returns (error_count, warning_count)."""
        print("=" * 60)
        print("PIPELINE PATTERN VALIDATOR (Session 185)")
        print("=" * 60)

        self.check_enum_member_usage()
        self.check_processor_name_mapping()
        self.check_flask_get_json_safety()

        print("\n" + "=" * 60)
        if self.errors:
            print(f"{RED}ERRORS FOUND: {len(self.errors)}{RESET}")
            for err in self.errors:
                print(f"\n{RED}[ERROR]{RESET} {err['file']}:{err['line']}")
                print(f"  {err['message']}")
                if err.get('suggestion'):
                    print(f"  {YELLOW}Fix:{RESET} {err['suggestion']}")
        else:
            print(f"{GREEN}No errors found{RESET}")

        if self.warnings:
            print(f"\n{YELLOW}WARNINGS: {len(self.warnings)}{RESET}")
            for warn in self.warnings:
                print(f"\n{YELLOW}[WARNING]{RESET} {warn['file']}:{warn['line']}")
                print(f"  {warn['message']}")

        print("=" * 60)
        return len(self.errors), len(self.warnings)

    # ----------------------------------------------------------------
    # Check 1: Enum member validation
    # ----------------------------------------------------------------
    def check_enum_member_usage(self):
        """Validate that all enum member references use valid members."""
        print("\n[1/3] Checking enum member usage...")

        # Known enums and their valid members
        ENUM_REGISTRY = {
            'SourceCoverageSeverity': {'INFO', 'WARNING', 'CRITICAL'},
            'SourceCoverageEventType': {
                'DEPENDENCY_STALE', 'DEPENDENCY_MISSING',
                'SOURCE_BLOCKED', 'SOURCE_TIMEOUT',
                'SOURCE_UNAVAILABLE', 'SOURCE_MISMATCH',
                'FALLBACK_USED', 'QUALITY_CHECK',
            },
            'SourceStatus': {
                'AVAILABLE', 'UNAVAILABLE', 'BLOCKED',
                'STALE', 'ERROR', 'PARTIAL',
            },
        }

        # Also try to dynamically load enums for accuracy
        enum_registry = self._load_enum_members(ENUM_REGISTRY)

        # Skip directories that aren't our source code
        skip_dirs = {'.venv', '__pycache__', 'node_modules', '.git', 'docs'}

        found = 0
        for py_file in self.base_path.rglob('*.py'):
            if any(d in py_file.parts for d in skip_dirs):
                continue
            try:
                content = py_file.read_text()
                lines = content.split('\n')
                in_docstring = False
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    # Track docstrings (triple quotes)
                    if '"""' in stripped or "'''" in stripped:
                        count = stripped.count('"""') + stripped.count("'''")
                        if count == 1:
                            in_docstring = not in_docstring
                            continue
                        # Opening and closing on same line — skip
                        continue
                    if in_docstring:
                        continue
                    # Skip comments
                    if stripped.startswith('#'):
                        continue
                    # Skip string literals containing enum references (documentation)
                    if stripped.startswith(("'", '"')):
                        continue
                    for enum_name, valid_members in enum_registry.items():
                        # Only match actual code usage: EnumName.MEMBER
                        pattern = re.findall(
                            rf'(?<!["\'])(?:severity\s*=\s*)?{enum_name}\.([A-Z_]+)', line
                        )
                        for member in pattern:
                            if member not in valid_members:
                                self.errors.append({
                                    'file': str(py_file.relative_to(self.base_path)),
                                    'line': line_num,
                                    'message': (
                                        f'{enum_name}.{member} does not exist. '
                                        f'Valid members: {sorted(valid_members)}'
                                    ),
                                    'suggestion': (
                                        f'Use one of: {", ".join(sorted(valid_members))}'
                                    ),
                                })
                                found += 1
            except Exception:
                pass

        print(f"  Checked {len(enum_registry)} enum types, found {found} issues")

    def _load_enum_members(self, fallback: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
        """Try to dynamically load enum definitions for accuracy."""
        result = dict(fallback)

        # Try loading SourceCoverageSeverity
        try:
            spec = importlib.util.spec_from_file_location(
                'source_coverage',
                self.base_path / 'shared' / 'config' / 'source_coverage' / '__init__.py',
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, 'SourceCoverageSeverity'):
                    result['SourceCoverageSeverity'] = {
                        m.name for m in mod.SourceCoverageSeverity
                    }
                if hasattr(mod, 'SourceCoverageEventType'):
                    result['SourceCoverageEventType'] = {
                        m.name for m in mod.SourceCoverageEventType
                    }
                if hasattr(mod, 'SourceStatus'):
                    result['SourceStatus'] = {
                        m.name for m in mod.SourceStatus
                    }
        except Exception:
            pass  # Fall back to hardcoded values

        return result

    # ----------------------------------------------------------------
    # Check 2: Processor name mapping completeness
    # ----------------------------------------------------------------
    def check_processor_name_mapping(self):
        """Validate that CLASS_TO_CONFIG_MAP covers all known processor classes.

        Catches typos like NbacGambookProcessor (missing 'e') that prevent
        the Phase 2→3 orchestrator from matching processor completions.
        """
        print("\n[2/3] Checking processor name mappings...")

        orchestrator_path = (
            self.base_path / 'orchestration' / 'cloud_functions'
            / 'phase2_to_phase3' / 'main.py'
        )
        if not orchestrator_path.exists():
            print("  Skipped (orchestrator file not found)")
            return

        content = orchestrator_path.read_text()

        # Extract CLASS_TO_CONFIG_MAP keys
        map_keys: Set[str] = set()
        in_map = False
        for line in content.split('\n'):
            if 'CLASS_TO_CONFIG_MAP' in line and '{' in line:
                in_map = True
                continue
            if in_map:
                if '}' in line:
                    break
                match = re.search(r"'([A-Za-z\u00e9]+)'", line)
                if match:
                    map_keys.add(match.group(1))

        # Only flag processors that actually publish to nba-phase2-raw-complete
        # (not every raw processor participates in Phase 2→3 triggering)
        # The EXPECTED_PROCESSORS list in the orchestrator defines what's needed.
        expected_configs = set()
        in_expected = False
        for line in content.split('\n'):
            if 'EXPECTED_PROCESSORS' in line and '[' in line:
                in_expected = True
                continue
            if in_expected:
                if ']' in line:
                    break
                match = re.search(r"'([^']+)'", line)
                if match:
                    expected_configs.add(match.group(1))

        # Check that every expected config has at least one map key pointing to it
        mapped_configs = set()
        in_map = False
        for line in content.split('\n'):
            if 'CLASS_TO_CONFIG_MAP' in line and '{' in line:
                in_map = True
                continue
            if in_map:
                if '}' in line:
                    break
                match = re.search(r":\s*'([^']+)'", line)
                if match:
                    mapped_configs.add(match.group(1))

        unmapped_configs = expected_configs - mapped_configs
        for config in sorted(unmapped_configs):
            self.errors.append({
                'file': str(orchestrator_path.relative_to(self.base_path)),
                'line': 0,
                'message': (
                    f'Expected processor config "{config}" has no entry '
                    f'in CLASS_TO_CONFIG_MAP. Phase 2→3 trigger can\'t '
                    f'track this processor.'
                ),
                'suggestion': (
                    f'Add the processor class name → "{config}" '
                    f'mapping to CLASS_TO_CONFIG_MAP'
                ),
            })

        # Check for suspicious typo patterns in map keys
        for key in map_keys:
            # Check for non-ASCII characters (like accented é)
            if any(ord(c) > 127 for c in key):
                self.warnings.append({
                    'file': str(orchestrator_path.relative_to(self.base_path)),
                    'line': 0,
                    'message': (
                        f'Map key "{key}" contains non-ASCII characters. '
                        f'This may be a typo from copy-paste.'
                    ),
                })

        print(f"  Map has {len(map_keys)} entries, "
              f"{len(expected_configs)} expected configs, "
              f"{len(unmapped_configs)} unmapped")

    # ----------------------------------------------------------------
    # Check 3: Flask get_json() safety for Cloud Scheduler
    # ----------------------------------------------------------------
    def check_flask_get_json_safety(self):
        """Validate that HTTP endpoints use safe get_json(force=True, silent=True).

        Cloud Scheduler sends requests without Content-Type: application/json.
        Flask's get_json() returns None or raises 415 without force=True.

        Pub/Sub handlers are exempt — they receive valid JSON envelopes.
        """
        print("\n[3/3] Checking Flask get_json() safety...")

        # Patterns
        safe_pattern = re.compile(r'get_json\s*\(\s*force\s*=\s*True')
        unsafe_pattern = re.compile(r'request\.get_json\s*\(\s*\)')
        pubsub_indicators = [
            'envelope', 'pubsub', 'pub_sub', 'message',
            'subscription', 'Pub/Sub',
        ]

        # Only check source directories that serve Cloud Scheduler endpoints
        check_dirs = [
            'predictions', 'data_processors', 'orchestration',
            'scrapers', 'services',
        ]
        skip_dirs = {'.venv', '__pycache__', 'node_modules', '.git',
                     'docs', 'examples', '.pre-commit-hooks'}

        found = 0
        for py_file in self.base_path.rglob('*.py'):
            if any(d in py_file.parts for d in skip_dirs):
                continue
            if not any(py_file.parts[1] == d if len(py_file.parts) > 1
                       else False for d in check_dirs):
                continue
            try:
                content = py_file.read_text()
                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    if unsafe_pattern.search(line):
                        # Check if this is a Pub/Sub handler (exempt)
                        context_start = max(0, line_num - 15)
                        context = '\n'.join(lines[context_start:line_num + 3]).lower()
                        is_pubsub = any(
                            indicator in context for indicator in pubsub_indicators
                        )
                        if not is_pubsub:
                            self.warnings.append({
                                'file': str(py_file.relative_to(self.base_path)),
                                'line': line_num,
                                'message': (
                                    'Bare request.get_json() without force=True. '
                                    'Cloud Scheduler calls will fail with 415.'
                                ),
                            })
                            found += 1
            except Exception:
                pass

        print(f"  Found {found} potentially unsafe get_json() calls")


def main():
    """Run validation and exit with appropriate code."""
    validator = PipelinePatternValidator()
    errors, warnings = validator.validate_all()

    if errors > 0:
        print(f"\n{RED}Validation FAILED with {errors} errors{RESET}")
        sys.exit(1)
    elif warnings > 0:
        print(f"\n{YELLOW}Validation passed with {warnings} warnings{RESET}")
        sys.exit(0)
    else:
        print(f"\n{GREEN}All pipeline pattern checks passed!{RESET}")
        sys.exit(0)


if __name__ == '__main__':
    main()
