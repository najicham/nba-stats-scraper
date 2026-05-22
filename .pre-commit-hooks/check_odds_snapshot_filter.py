#!/usr/bin/env python3
"""
Pre-commit hook: odds-snapshot look-ahead leak guard.

Any query that selects the LATEST snapshot from
`nba_raw.odds_api_player_points_props` (ORDER BY snapshot_timestamp DESC) MUST
also filter `minutes_before_tipoff >= 0`. The raw table contains post-tipoff /
in-game snapshots; without the bound, a `DESC` sort can pick a line that was
set while the game was already being played — leaking how the game is going
into a supposedly pre-game feature.

Background:
- 2026-05-22 audit found feature_25 (vegas line) contaminated with in-game
  odds because the odds-snapshot queries in feature_extractor.py sorted
  snapshot_timestamp DESC with no minutes_before_tipoff bound. Five queries
  had the same defect; fixed by adding `AND minutes_before_tipoff >= 0`.
- Reference correct pattern: the feature-63 `late_moves` query, which already
  filters `minutes_before_tipoff IS NOT NULL AND minutes_before_tipoff <= 240`.
- ASC sorts (opening line) are safe — the earliest snapshot is always pre-game.

Scope: each `FROM ... odds_api_player_points_props` is attributed to its
enclosing parenthesized block (CTE / subquery) via paren matching, so an
adjacent safe CTE cannot mask a leaky one.

If a DESC odds-snapshot query is intentionally exempt, add the bound or a
comment containing `pre-tipoff-exempt` inside the query block.

Exit codes:
- 0: clean
- 1: a latest-snapshot odds query is missing the minutes_before_tipoff bound

Usage:
  python .pre-commit-hooks/check_odds_snapshot_filter.py [files...]
"""

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

TABLE = "odds_api_player_points_props"
FROM_RE = re.compile(r"FROM\s+`?[^`\n]*" + re.escape(TABLE), re.IGNORECASE)
DESC_RE = re.compile(r"snapshot_timestamp\s+DESC", re.IGNORECASE)
BOUND_RE = re.compile(r"minutes_before_tipoff", re.IGNORECASE)
EXEMPT_RE = re.compile(r"pre-tipoff-exempt", re.IGNORECASE)

# Fallback span (lines each side) when the FROM is not inside a paren block.
FALLBACK_WINDOW = 20

INCLUDE_SUFFIXES = {".py", ".sql"}
EXCLUDE_PARTS = ("/migrations/", "/.pre-commit-hooks/")
EXCLUDE_NAME_HINTS = ("test_", "_test.", "conftest.py")


def should_check_file(path: Path) -> bool:
    if path.suffix not in INCLUDE_SUFFIXES:
        return False
    posix = path.as_posix()
    if any(part in posix for part in EXCLUDE_PARTS):
        return False
    if any(hint in path.name for hint in EXCLUDE_NAME_HINTS):
        return False
    return True


def enclosing_block(lines: List[str], from_idx: int) -> Optional[Tuple[int, int]]:
    """Line range of the parenthesized block enclosing `from_idx`, or None."""
    depth = 0
    start = None
    for j in range(from_idx, -1, -1):
        depth += lines[j].count(")") - lines[j].count("(")
        if depth < 0:  # an unmatched '(' on this line encloses the FROM
            start = j
            break
    if start is None:
        return None
    depth = 0
    for j in range(start, len(lines)):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth == 0:
            return (start, j)
    return (start, len(lines) - 1)


def check_file(path: Path) -> List[Tuple[int, str]]:
    """Return (line_number, message) for each leaky odds-snapshot query."""
    try:
        lines = path.read_text().split("\n")
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        # Broken symlinks (e.g. dangling shared/ copies) and unreadable
        # paths are not leaks — just skip them.
        return []
    except UnicodeDecodeError:
        return []

    issues: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if not FROM_RE.search(line):
            continue
        block = enclosing_block(lines, idx)
        if block is None:
            lo = max(0, idx - FALLBACK_WINDOW)
            hi = min(len(lines), idx + FALLBACK_WINDOW + 1)
        else:
            lo, hi = block[0], block[1] + 1
        text = "\n".join(lines[lo:hi])
        if not DESC_RE.search(text):
            continue  # not selecting the latest snapshot — safe
        if BOUND_RE.search(text) or EXEMPT_RE.search(text):
            continue  # bounded to pre-tipoff, or explicitly exempt
        issues.append((
            idx + 1,
            "Latest-snapshot query on odds_api_player_points_props "
            "(ORDER BY snapshot_timestamp DESC) is missing a "
            "`minutes_before_tipoff >= 0` bound — can leak in-game odds.",
        ))
    return issues


def main() -> int:
    args = sys.argv[1:]
    if args:
        files = [Path(f) for f in args]
    else:
        files = list(Path(".").rglob("*.py")) + list(Path(".").rglob("*.sql"))

    files = [f for f in files if should_check_file(f)]

    all_issues = []
    for path in files:
        for line_num, message in check_file(path):
            all_issues.append((path, line_num, message))

    if not all_issues:
        print("Odds-snapshot leak guard: OK")
        return 0

    print("=" * 70)
    print("ODDS-SNAPSHOT LEAK GUARD: potential look-ahead leak")
    print("=" * 70)
    print()
    for path, line_num, message in all_issues:
        print(f"File: {path}:{line_num}")
        print(f"  {message}")
        print()
    print("Fix: add `AND minutes_before_tipoff >= 0` to the query's WHERE,")
    print("or add a `pre-tipoff-exempt` comment if the DESC sort is safe.")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
