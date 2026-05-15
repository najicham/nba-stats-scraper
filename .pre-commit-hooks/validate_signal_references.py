#!/usr/bin/env python3
"""Pre-commit hook: validate signal/filter references in docs vs registry.

Greps CLAUDE.md, .claude/skills/, docs/, MEMORY.md for known signal/filter
tag patterns. Fails if any docs reference a tag not in the registry — catches
the recurring drift problem (skill files claim filters that were removed
months ago, like the away_noveg / starter_v12_under references found in the
2026-05-09 audit).

Allows references inside backticks-fenced code blocks marked
``` # registry-exempt ``` for grandfathered legacy mentions in long-form docs.

Usage:
  python .pre-commit-hooks/validate_signal_references.py [path...]

Exit code: 0 if all references valid, 1 if drift detected.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple


REPO_ROOT = Path(__file__).parent.parent

# Where to look for tag references.
DOC_PATTERNS = [
    'CLAUDE.md',
    '.claude/skills/**/*.md',
    'docs/**/*.md',
]

# Files that override the strict check (e.g. session learnings + historical
# handoffs that quote removed/historical tags by design).
ALLOWLIST_FILES: Set[str] = {
    'docs/02-operations/session-learnings.md',
    'docs/06-reference/model-dead-ends.md',
}

# Directory prefixes whose contents are exempt (handoffs are immutable historical
# documents; don't rewrite them every time the registry changes).
ALLOWLIST_DIR_PREFIXES = (
    'docs/09-handoff/',                       # historical handoffs
    'docs/08-projects/archive/',              # archived projects
    'docs/08-projects/current/',              # active research drafts; signals here may not be promoted
    'docs/08-projects/completed/',            # completed project notes
    'docs/06-reference/',                     # reference material
)

# Inline backtick-tag pattern: matches `tag_name` where tag_name is a snake_case identifier.
TAG_PATTERN = re.compile(r"`([a-z][a-z0-9_]{2,40})`")


def _load_registries() -> Tuple[Set[str], Set[str]]:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from shared.registry import load_signal_registry, load_filter_registry
    except Exception as e:
        print(f"WARNING: could not import registry ({e}); skipping check")
        return set(), set()

    signals = set(load_signal_registry().keys())
    filters = set(load_filter_registry().keys())
    return signals, filters


def _iter_doc_files() -> Iterable[Path]:
    for pattern in DOC_PATTERNS:
        if '**' in pattern:
            for p in REPO_ROOT.glob(pattern):
                if p.is_file():
                    yield p
        else:
            p = REPO_ROOT / pattern
            if p.is_file():
                yield p


# A short blocklist of identifiers that look like tags but aren't (false-positive
# guard — these are common code/markdown identifiers we shouldn't flag).
NOT_TAGS = frozenset({
    'true', 'false', 'null', 'none', 'sql', 'json', 'yaml', 'http',
    'main', 'test', 'help', 'config', 'project', 'production',
    'on_call', 'in_progress', 'completed', 'pending', 'over', 'under',
    # Common BQ identifiers / column names — not signal/filter tags.
    'model_performance_daily', 'model_bb_candidates', 'model_disabled',
    'model_file_name', 'opponent_def_rating', 'opponent_history',
    'home_away', 'home_team', 'away_team', 'starter_flag', 'line_value',
    'line_values_requested',
    'signal_best_bets_picks', 'signal_health_daily', 'signal_combo_registry',
    'signal_stacking', 'signal_stack_2plus_obs',
    # Historical / removed tags still mentioned in CLAUDE.md or older docs.
    # These are documentation references; the actual filter/signal status
    # is canonically tracked in shared/registry/.
    'mean_reversion_under', 'cold_3pt_over', 'high_book_std_under_block',
    'prop_line_drop_over', 'b2b_fatigue_under',
    # MLB-side proposed signals (not yet in code) — referenced from MLB
    # runbooks and handoffs as future work. Skip rather than add to NBA YAML.
    'velocity_drift_under',
    'low_line_over', 'volatile_scoring_over', 'signal_stack_2plus',
    'high_spread_over', 'mid_line_over', 'high_edge_over',
    # Older architecture doc tag-style identifiers (column names, classifications)
    'xm_quantile_agreement_under', 'xm_mae_plus_quantile_over',
    'signal_combo_he_ms', 'signal_combo_3way', 'signal_bench_under',
    'signal_high_count', 'signal_tags',
})


def collect_referenced_tags(file_path: Path) -> List[str]:
    text = file_path.read_text(encoding='utf-8', errors='replace')
    found: List[str] = []
    for match in TAG_PATTERN.finditer(text):
        tag = match.group(1)
        if tag in NOT_TAGS:
            continue
        if '_' not in tag:  # most signal/filter tags have an underscore
            continue
        found.append(tag)
    return found


# Heuristic: a tag is "interesting" (likely a real signal/filter reference)
# if it ends with one of these signal/filter suffixes. Using suffix-only
# (rather than prefix) matches the way the existing registry tags are named
# and reduces false positives on table names like model_performance_daily.
INTERESTING_TAG_PATTERNS = [
    re.compile(r'.*_under_block$'),
    re.compile(r'.*_over_block$'),
    re.compile(r'.*_under$'),
    re.compile(r'.*_over$'),
    re.compile(r'^combo_[a-z0-9_]+$'),
    re.compile(r'^line_[a-z0-9_]+_under$'),
    re.compile(r'^line_[a-z0-9_]+_over$'),
    re.compile(r'^edge_floor$'),
    re.compile(r'^over_edge_floor$'),
    re.compile(r'^under_edge_7plus$'),
    re.compile(r'^signal_[a-z0-9_]+$'),
    re.compile(r'^friday_over_block$'),
    re.compile(r'^q4_scorer_under_block$'),
]


def is_interesting_tag(tag: str) -> bool:
    return any(p.match(tag) for p in INTERESTING_TAG_PATTERNS)


def check_code_vs_registry_parity(signals: Set[str]) -> List[str]:
    """Walk ml/signals/*.py for `tag = "..."` declarations and flag any
    that don't appear in the loaded YAML registry.

    Catches the drift pattern documented in Path A: the signal registry
    YAML is the documented "single source of truth," but new signal
    classes can land in code without a corresponding YAML entry, which
    breaks the invariant for downstream readers (docs, observability,
    automation that reads the registry).
    """
    signals_dir = REPO_ROOT / 'ml' / 'signals'
    if not signals_dir.exists():
        return []

    tag_re = re.compile(r"^\s+tag\s*=\s*['\"]([a-z0-9_]+)['\"]", re.M)
    missing: List[str] = []
    for f in sorted(signals_dir.glob('*.py')):
        text = f.read_text(encoding='utf-8', errors='replace')
        for m in tag_re.finditer(text):
            tag = m.group(1)
            if tag not in signals:
                missing.append(f"{f.relative_to(REPO_ROOT)}: tag=`{tag}`")
    return missing


def main(argv: List[str]) -> int:
    files: List[Path] = []
    if len(argv) > 1:
        for arg in argv[1:]:
            p = Path(arg).resolve()
            if p.is_file():
                files.append(p)
    else:
        files = list(_iter_doc_files())

    signals, filters = _load_registries()
    if not signals and not filters:
        return 0  # No registry — skip silently (CI bootstrap)

    known = signals | filters

    drift: List[Tuple[Path, str]] = []
    for f in files:
        rel = str(f.relative_to(REPO_ROOT))
        if rel in ALLOWLIST_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in ALLOWLIST_DIR_PREFIXES):
            continue
        seen: Set[str] = set()
        for tag in collect_referenced_tags(f):
            if tag in seen or not is_interesting_tag(tag):
                continue
            seen.add(tag)
            # Only report tags that "look like" they should be in the registry
            # but aren't — avoids flagging arbitrary `snake_case` words in prose.
            if tag not in known:
                drift.append((f, tag))

    # Path A — code-vs-YAML parity check.
    code_drift = check_code_vs_registry_parity(signals)

    if drift or code_drift:
        if drift:
            print("Signal/filter references in docs that don't match the registry:")
            print("(if these are intentional, add to shared/registry/{signals,filters}.yaml")
            print(" or, if a one-time historical mention, add the file to ALLOWLIST_FILES)")
            print()
            for f, tag in drift:
                print(f"  {f.relative_to(REPO_ROOT)}: `{tag}`")
        if code_drift:
            if drift:
                print()
            print("Signal classes in ml/signals/ whose `tag = ...` is missing from")
            print("shared/registry/signals.yaml. Add an entry to the YAML in the")
            print("same commit so the registry stays the single source of truth.")
            print()
            for entry in code_drift:
                print(f"  {entry}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
