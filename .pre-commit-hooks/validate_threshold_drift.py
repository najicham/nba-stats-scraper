#!/usr/bin/env python3
"""Pre-commit hook: detect duplicated module-level threshold constants.

When the SAME ALL_CAPS constant name (matching common threshold suffixes)
appears at module scope in two or more Python files, the values must match.
Mismatched values are a drift bug waiting to fire.

2026-05-14 to 2026-05-16 incident: TIGHT_VEGAS_MAE_THRESHOLD lived in both
`ml/signals/mlb/config.py` and `ml/signals/mlb/regime_context.py` and drifted
to two different values during the floor-cap collision diagnosis. The
exporter and the regime detector disagreed on the threshold, producing zero
picks for three days.

Rule: a single canonical definition. Other modules must IMPORT it, not
re-declare it.

Detection scope (suffix allowlist to control false positives):
  *_THRESHOLD, *_FLOOR, *_CAP, *_LIMIT, *_FLAG_THRESHOLD, *_GATE

Numeric literals only (int / float / None). String / list / dict constants
are excluded because they're commonly re-declared by design.
"""
import ast
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

ROOTS = ['ml', 'shared', 'data_processors', 'predictions', 'orchestration']

SUFFIX_ALLOWLIST = (
    '_THRESHOLD',
    '_FLOOR',
    '_CAP',
    '_LIMIT',
    '_MAX',
    '_MIN',
    '_GATE',
)

# Names that are widely defined as constants in many contexts — exempt.
NAME_EXEMPT = {
    'MAX_RETRIES',
    'MAX_WORKERS',
    'MIN_BATCH_SIZE',
    'MAX_BATCH_SIZE',
    'CACHE_TTL',
    'DEFAULT_TIMEOUT',
    'TIMEOUT',
    # Cross-sport namespaces — same name, intentionally different values.
    # These should ideally carry an `MLB_`/`NBA_` prefix or live in
    # sport-scoped subpackages, but the names predate this hook.
    'LOOSE_THRESHOLD',          # ml/analysis/mlb_league_macro.py vs league_macro.py
    'BUFFER_FLUSH_THRESHOLD',   # env_monitor.py vs execution_logger.py — different buffers
}

EXCLUDE_DIRS = {
    '__pycache__',
    'tests',  # tests intentionally duplicate constants
    'archive',
    'venv',
    '.venv',
    'node_modules',
}


def name_in_scope(name: str) -> bool:
    if name in NAME_EXEMPT:
        return False
    return any(name.endswith(s) for s in SUFFIX_ALLOWLIST)


def extract_numeric(node: ast.AST):
    """Return the numeric value if this node is a constant int/float, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = extract_numeric(node.operand)
        if inner is not None:
            return -inner
    return None


def scan_file(filepath: str) -> Dict[str, Tuple[float, int]]:
    """Return {name: (value, lineno)} for module-level numeric constants.

    Silently skips unreadable files (broken symlinks, encoding errors,
    permission errors). The orchestration/cloud_functions tree contains
    symlinks back into shared/ that can dangle if shared/ has been
    refactored — we don't want a broken symlink to fail the whole hook.
    """
    try:
        with open(filepath, 'r') as fh:
            source = fh.read()
    except (UnicodeDecodeError, PermissionError, FileNotFoundError, IsADirectoryError, OSError):
        return {}
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return {}

    out: Dict[str, Tuple[float, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = extract_numeric(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and name_in_scope(target.id):
                    out[target.id] = (value, node.lineno)
        elif isinstance(node, ast.AnnAssign):
            if node.value is None:
                continue
            value = extract_numeric(node.value)
            if value is None:
                continue
            if isinstance(node.target, ast.Name) and name_in_scope(node.target.id):
                out[node.target.id] = (value, node.lineno)
    return out


def should_skip_dir(dirname: str) -> bool:
    return dirname in EXCLUDE_DIRS or dirname.startswith('.')


def main() -> int:
    print("Checking for duplicated threshold constants across files...")
    name_to_defs: Dict[str, List[Tuple[str, float, int]]] = defaultdict(list)
    checked = 0

    for root in ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
            for f in filenames:
                if not f.endswith('.py'):
                    continue
                filepath = os.path.join(dirpath, f)
                checked += 1
                for name, (value, lineno) in scan_file(filepath).items():
                    name_to_defs[name].append((filepath, value, lineno))

    drift_errors: List[str] = []
    duplicate_warnings: List[str] = []
    for name, defs in name_to_defs.items():
        if len(defs) < 2:
            continue
        # Check value drift first — that's the failure mode that bit us.
        unique_values = {d[1] for d in defs}
        if len(unique_values) > 1:
            lines = [f"    {d[0]}:{d[2]} = {d[1]}" for d in defs]
            drift_errors.append(
                f"  {name} DRIFTED across files (values: {sorted(unique_values)}):\n"
                + "\n".join(lines)
            )
        else:
            # Same value in multiple files — duplication, not drift. Warn only.
            lines = [f"    {d[0]}:{d[2]}" for d in defs]
            duplicate_warnings.append(
                f"  {name} = {defs[0][1]} (duplicated across files):\n"
                + "\n".join(lines)
            )

    if drift_errors:
        print(f"\n{'='*60}")
        print(f"FAILED: Threshold constant values DRIFTED across files")
        print(f"{'='*60}")
        for err in drift_errors:
            print(err)
        print(f"\nDeclare the constant ONCE (canonical location) and IMPORT it")
        print(f"elsewhere. See TIGHT_VEGAS_MAE_THRESHOLD post-mortem 2026-05-14.")
        return 1

    if duplicate_warnings:
        print(f"\nWARNING (non-blocking): identical constants duplicated across files:")
        for warn in duplicate_warnings:
            print(warn)
        print(f"\nConsider centralizing — drift is one edit away.")

    print(f"  Checked {checked} Python files — no value drift detected")
    return 0


if __name__ == '__main__':
    sys.exit(main())
