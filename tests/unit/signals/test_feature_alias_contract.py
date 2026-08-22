"""Contract: `feature_N_value AS <alias>` must name the feature it selects.

Why this exists
---------------
The feature store is a wide table of positional columns (feature_0_value ...
feature_59_value). Query code renames them to readable aliases. Nothing
connected the alias back to the position, so an alias could name one feature
while selecting another, and every downstream consumer would honour the alias.

Two live instances were found on 2026-08-22, both in the best-bets query paths:

  feature_18_value AS opponent_pace   -- f18 is pct_paint (0-1); pace is f14
  feature_53_value AS prop_over_streak -- f53 is line_vs_season_avg; streak is f51

The first is the instructive one. `slow_pace_under` disqualifies when
`opp_pace > 99.0`, which a 0-1 variable can never exceed, so the signal fired on
EVERY UNDER at a pinned 0.90 confidence and recorded the all-UNDER base rate as
its hit rate. `fast_pace_over` had its threshold *refitted* to the wrong column
(Session 387, 102 -> 0.75) rather than the alias being questioned. Both signals
sit behind live promotion gates, so a mis-aliased signal graduates on a record
that measures something else.

The rules
---------
1. IMPERSONATION (hard, repo-wide, no exceptions). An alias must never be the
   canonical name of a *different* feature index. This is the dangerous class:
   the alias is a lie that reads as truth, and every reader downstream believes
   it. It admits no legitimate exception, so it carries no allowlist.

2. EXACT MATCH (hard, live signal paths only). Under ml/signals/ an alias must
   equal its canonical name, or appear in SHORTHAND_ALIASES below. Shorthand is
   permitted but must be deliberate and reviewed, not accidental.

3. IN RANGE. Only features 0-59 exist as columns in BigQuery.

Kept dependency-thin on purpose: stdlib plus shared.ml.feature_contract (which
imports only typing and dataclasses), so it runs in the deploy gate's slim
image. See docs/09-handoff/2026-08-22-SESSION-7-START.md.
"""

import re
from pathlib import Path

import pytest

from shared.ml.feature_contract import (
    FEATURE_STORE_FEATURE_COUNT,
    FEATURE_STORE_NAMES,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# This file quotes real alias lines as examples; scanning itself is a false positive.
SELF_REL = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

# Directories that are not live code: vendored, archived, or agent scratch.
EXCLUDED_PATH_PARTS = ('.claude/', '.venv/', 'node_modules/', 'ml/archive/', '/archive/')

# `CAST(feature_2_value AS FLOAT64)` is a type cast, not an alias.
SQL_TYPE_KEYWORDS = frozenset({
    'FLOAT64', 'STRING', 'INT64', 'NUMERIC', 'BIGNUMERIC',
    'BOOL', 'BOOLEAN', 'DATE', 'DATETIME', 'TIMESTAMP', 'BYTES',
})

ALIAS_RE = re.compile(r'feature_(\d+)_(value|source)\s+AS\s+(\w+)', re.IGNORECASE)

# Deliberate abbreviations under ml/signals/. Keyed by (index, kind, alias) so a
# shorthand blessed for one feature cannot drift onto another.
SHORTHAND_ALIASES = frozenset({
    (29, 'value', 'avg_pts_vs_opp'),    # avg_points_vs_opponent
    (30, 'value', 'games_vs_opp'),      # games_vs_opponent
    (40, 'value', 'minutes_load_7d'),   # minutes_load_last_7d
    (43, 'value', 'pts_avg_last3'),     # points_avg_last_3
    (44, 'value', 'trend_slope'),       # scoring_trend_slope
    (48, 'value', 'usage_rate_l5'),     # usage_rate_last_5
    (57, 'value', 'blowout_risk'),      # blowout_minutes_risk
    (50, 'source', 'book_std_source'),  # multi_book_line_std_source
})

# Aliases outside the live signal path that resemble a different feature's name
# but are not exact impersonations. Each is UNVERIFIED: it may be a real bug or
# deliberate shorthand. None sits on the best-bets money path, so none was
# changed on 2026-08-22 alongside the ml/signals/ fixes.
#
# Frozen here so the set cannot grow unnoticed. Resolving one means deleting its
# entry (after verifying the intent) — not editing the expectation.
QUARANTINED_NEAR_MISSES = frozenset({
    # (path suffix, index, alias, what f<index> actually is)
    ('bin/backfill_experiment_features.py', 44, 'minutes_load', 'scoring_trend_slope'),
    ('bin/backfill_experiment_features.py', 6, 'pace', 'shot_zone_mismatch_score'),
    ('bin/backfill_experiment_features.py', 42, 'spread_mag', 'implied_team_total'),
    ('bin/backfill_experiment_features.py', 4, 'pts_std', 'games_in_last_7_days'),
    ('validation/validators/precompute/ml_feature_store_validator.py', 13,
     'opp_pace', 'opponent_def_rating'),
})

# Canonical name -> the single index that owns it.
_CANONICAL_OWNER = {}
for _i, _name in enumerate(FEATURE_STORE_NAMES[:FEATURE_STORE_FEATURE_COUNT]):
    _CANONICAL_OWNER.setdefault(_name, _i)


def _iter_aliases(root):
    """Yield (path, lineno, index, kind, alias) for every feature alias under root."""
    for path in sorted(root.rglob('*.py')):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == SELF_REL:
            continue
        if any(part in f'/{rel}' for part in EXCLUDED_PATH_PARTS):
            continue
        try:
            src = path.read_text(errors='ignore')
        except OSError:
            continue  # dangling symlink; see commit a5992db7
        if 'feature_' not in src:
            continue
        for m in ALIAS_RE.finditer(src):
            alias = m.group(3)
            if alias.upper() in SQL_TYPE_KEYWORDS:
                continue
            yield rel, src[:m.start()].count('\n') + 1, int(m.group(1)), m.group(2).lower(), alias


def test_no_alias_impersonates_another_feature():
    """An alias must never be the canonical name of a different feature index."""
    violations = []
    for rel, lineno, idx, kind, alias in _iter_aliases(REPO_ROOT):
        owner = _CANONICAL_OWNER.get(alias)
        if owner is not None and owner != idx:
            violations.append(
                f"{rel}:{lineno}: feature_{idx}_{kind} AS {alias} — "
                f"'{alias}' is canonically feature_{owner} "
                f"(feature_{idx} is '{FEATURE_STORE_NAMES[idx]}')"
            )
    assert not violations, (
        "Alias names a different feature than it selects:\n  "
        + "\n  ".join(violations)
        + "\n\nEvery downstream consumer trusts the alias. Either select the "
          "index the name promises, or rename the alias."
    )


def test_signal_query_aliases_match_canonical_names():
    """Under ml/signals/, aliases match canonical names or are blessed shorthand."""
    violations = []
    for rel, lineno, idx, kind, alias in _iter_aliases(REPO_ROOT / 'ml' / 'signals'):
        if idx >= FEATURE_STORE_FEATURE_COUNT:
            continue  # covered by test_alias_indexes_exist_in_the_feature_store
        expected = FEATURE_STORE_NAMES[idx]
        if kind == 'source':
            expected += '_source'
        if alias == expected or (idx, kind, alias) in SHORTHAND_ALIASES:
            continue
        violations.append(
            f"{rel}:{lineno}: feature_{idx}_{kind} AS {alias} "
            f"(canonical: {expected})"
        )
    assert not violations, (
        "Unrecognised feature alias in the live signal query paths:\n  "
        + "\n  ".join(violations)
        + "\n\nUse the canonical name, or add (index, kind, alias) to "
          "SHORTHAND_ALIASES with a comment naming the feature."
    )


def test_alias_indexes_exist_in_the_feature_store():
    """feature_N_value columns only exist for N < FEATURE_STORE_FEATURE_COUNT."""
    violations = [
        f"{rel}:{lineno}: feature_{idx}_{kind} (store has 0-{FEATURE_STORE_FEATURE_COUNT - 1})"
        for rel, lineno, idx, kind, _ in _iter_aliases(REPO_ROOT)
        if idx >= FEATURE_STORE_FEATURE_COUNT
    ]
    assert not violations, (
        "Query selects a feature column that does not exist in BigQuery:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize(
    'rel_suffix,idx,alias,actual_feature', sorted(QUARANTINED_NEAR_MISSES)
)
def test_quarantined_near_misses_are_unchanged(rel_suffix, idx, alias, actual_feature):
    """Known-unverified aliases outside the money path stay visible and frozen.

    Fails if one is silently removed OR quietly rewritten — either way the
    quarantine list has drifted from reality and needs a human decision.
    """
    path = REPO_ROOT / rel_suffix
    if not path.exists():
        pytest.skip(f'{rel_suffix} no longer exists')
    assert FEATURE_STORE_NAMES[idx] == actual_feature, (
        f"Feature map moved under the quarantine list: feature_{idx} is now "
        f"'{FEATURE_STORE_NAMES[idx]}', recorded as '{actual_feature}'."
    )
    found = any(
        rel == rel_suffix and i == idx and a == alias
        for rel, _lineno, i, _kind, a in _iter_aliases(path.parent)
    )
    assert found, (
        f"Quarantined alias `feature_{idx}_value AS {alias}` is gone from "
        f"{rel_suffix}. If it was resolved, delete its QUARANTINED_NEAR_MISSES entry."
    )
