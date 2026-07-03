#!/usr/bin/env python3
"""Fleet Diversity Gate — correlation-budget enforcement for the enabled model fleet.

WHY THIS EXISTS
---------------
The best-bets cross-model consensus signals (`book_disagreement`, `xm_diverse_agreement`,
and the `xm_consensus_*` subsets in shared/config/cross_model_subsets.py) only fire when
the enabled fleet contains DECORRELATED model families. If every enabled model outputs
near-identical predictions (Session 487: all enabled models became r>=0.95 LGBM clones),
those signals silently produce ZERO picks — the fleet looks healthy but a whole class of
high-HR signals is dead.

  NOTE: `combo_3way` is single-MODEL (verified) and does NOT depend on fleet diversity.
  This gate protects the genuinely cross-MODEL consensus signals listed above.

Diversity is already MONITORED (bin/analysis/model_correlation.py, and the
check_fleet_diversity canary in bin/monitoring/pipeline_canary_queries.py) but was never
ENFORCED at enable-time / in CI. This validator is that enforcement point. It is a
VALIDATION — it prints WARNING/FAIL and returns non-zero. It never auto-disables a model.

THE CORRELATION BUDGET (a fleet FAILS if any of these are violated)
-------------------------------------------------------------------
  (A) Pairwise-clone budget: NO pair of enabled models may have prediction-vector
      Pearson r >= 0.95 on a recent held-out slate. (Skipped gracefully when no recent
      prediction data exists, e.g. off-season.)
  (B) Family-diversity floor (registry metadata — always runs):
        - at least 1 enabled model whose ML framework is NOT catboost, AND
        - at least 2 distinct feature-sets among enabled models.

Run pre-enable or in CI:
    PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py
    PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py --days 21
    PYTHONPATH=. .venv/bin/python bin/validation/validate_fleet_diversity.py --skip-correlation

Exit code 0 = budget satisfied, 1 = budget violated (or hard error).

Part of: Fleet Diversity Gate (docs/08-projects/current/fleet-diversity-gate/00-SCOPE.md)
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

TABLE = "nba_predictions.model_registry"

# Correlation-budget thresholds
CLONE_R = 0.95              # pairwise Pearson r at/above this = clone
MIN_OVERLAP = 10            # minimum overlapping player-dates to trust a pair correlation
MIN_NON_CATBOOST = 1        # require >= this many enabled non-catboost models
MIN_FEATURE_SETS = 2        # require >= this many distinct feature-sets among enabled models

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _framework_family(model_id: str) -> str:
    """ML framework family from a model_id (mirrors the canary classifier)."""
    m = model_id.lower()
    if "lgbm" in m or "lightgbm" in m:
        return "lgbm"
    if "xgb" in m or "xgboost" in m:
        return "xgb"
    if "catboost" in m or m.startswith("cb_") or "_cb_" in m:
        return "catboost"
    return "other"


def _feature_set(model_id: str, registry_feature_set) -> str:
    """Resolve a model's feature-set.

    Prefer the registry column when populated; otherwise derive it from the
    system_id via the shared cross_model_subsets classifier.
    """
    if registry_feature_set:
        return str(registry_feature_set)
    try:
        from shared.config.cross_model_subsets import (
            classify_system_id,
            MODEL_FAMILIES,
        )
        fam = classify_system_id(model_id)
        if fam and fam in MODEL_FAMILIES:
            fs = MODEL_FAMILIES[fam].get("feature_set")
            if fs:
                return fs
    except Exception:
        pass
    return "unknown"


def load_enabled_fleet(client):
    """Return list of dicts for enabled+active models: model_id, framework, feature_set."""
    # Only select columns guaranteed to exist. feature_set may be NULL in the
    # production table (sync script doesn't populate it), so we tolerate that.
    query = f"""
        SELECT model_id,
               SAFE_CAST(feature_set AS STRING) AS feature_set
        FROM `{client.project}.{TABLE}`
        WHERE enabled = TRUE AND status = 'active'
        ORDER BY model_id
    """
    fleet = []
    for row in client.query(query).result(timeout=60):
        mid = row.model_id
        fleet.append({
            "model_id": mid,
            "framework": _framework_family(mid),
            "feature_set": _feature_set(mid, row.feature_set),
        })
    return fleet


def check_family_diversity(fleet) -> bool:
    """Budget (B): registry-metadata family-diversity floor. Always runs."""
    print("\n[1/2] Family diversity floor (registry metadata)")

    if not fleet:
        print("  SKIP  No enabled+active models in registry — nothing to check")
        return True

    frameworks = defaultdict(list)
    feature_sets = defaultdict(list)
    for m in fleet:
        frameworks[m["framework"]].append(m["model_id"])
        feature_sets[m["feature_set"]].append(m["model_id"])

    print(f"        Enabled+active models : {len(fleet)}")
    print(f"        Framework families    : {len(frameworks)} "
          f"({', '.join(sorted(frameworks))})")
    for fam in sorted(frameworks):
        print(f"          - {fam:9s}: {len(frameworks[fam])}")
    print(f"        Distinct feature-sets : {len(feature_sets)} "
          f"({', '.join(sorted(feature_sets))})")

    non_catboost = sum(len(v) for k, v in frameworks.items() if k != "catboost")
    distinct_fs = len(feature_sets)

    failures = []
    if non_catboost < MIN_NON_CATBOOST:
        failures.append(
            f"only {non_catboost} enabled non-CatBoost model(s); "
            f"require >= {MIN_NON_CATBOOST}"
        )
    if distinct_fs < MIN_FEATURE_SETS:
        failures.append(
            f"only {distinct_fs} distinct feature-set(s) among enabled models; "
            f"require >= {MIN_FEATURE_SETS}"
        )

    if not failures:
        print(f"  {GREEN}PASS  Family diversity floor satisfied "
              f"(non-catboost={non_catboost}, feature_sets={distinct_fs}){RESET}")
        return True

    print(f"  {RED}FAIL  Family diversity floor violated:{RESET}")
    for f in failures:
        print(f"         - {f}")
    print(f"  {RED}         Cross-model consensus signals (book_disagreement, "
          f"xm_diverse_agreement) may not fire.{RESET}")
    print(f"         Fix: enable a non-CatBoost model (LGBM/XGBoost) and/or a model "
          f"with a distinct feature-set.")
    return False


def check_pairwise_correlation(client, fleet, days: int, skip: bool) -> bool:
    """Budget (A): no enabled pair with prediction-vector r >= CLONE_R.

    Degrades gracefully off-season: if no recent prediction slate exists, skips
    with a clear message (returns PASS so the metadata check still governs).
    """
    print(f"\n[2/2] Pairwise prediction correlation (r >= {CLONE_R} clone budget)")

    if skip:
        print("  SKIP  --skip-correlation flag set")
        return True

    enabled_ids = {m["model_id"] for m in fleet}
    if len(enabled_ids) < 2:
        print("  SKIP  Fewer than 2 enabled models — no pairs to correlate")
        return True

    try:
        import numpy as np
    except ImportError:
        print("  SKIP  numpy not available")
        return True

    query = f"""
        SELECT player_lookup, game_date, system_id, predicted_points
        FROM `{client.project}.nba_predictions.player_prop_predictions`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND is_active = TRUE
          AND predicted_points IS NOT NULL
        ORDER BY game_date, player_lookup, system_id
    """
    try:
        rows = list(client.query(query).result(timeout=120))
    except Exception as e:
        print(f"  SKIP  Could not query recent predictions ({e}) — "
              f"correlation budget not evaluated")
        return True

    # Restrict to enabled models only.
    pivot = defaultdict(dict)
    seen_models = set()
    for r in rows:
        if r.system_id not in enabled_ids:
            continue
        key = (r.player_lookup, str(r.game_date))
        pivot[key][r.system_id] = float(r.predicted_points)
        seen_models.add(r.system_id)

    if not pivot or len(seen_models) < 2:
        print(f"  SKIP  No recent slate with >= 2 enabled models in the last {days} "
              f"days (off-season / break) — correlation budget not evaluated")
        print(f"        Family-diversity floor above still governs enable-time safety.")
        return True

    models = sorted(seen_models)
    print(f"        Slate: {len(pivot)} player-date pairs across {len(models)} "
          f"enabled models (last {days} days)")

    clones = []
    computed = 0
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m_i, m_j = models[i], models[j]
            vi, vj = [], []
            for preds in pivot.values():
                if m_i in preds and m_j in preds:
                    vi.append(preds[m_i])
                    vj.append(preds[m_j])
            if len(vi) < MIN_OVERLAP:
                continue
            r = float(np.corrcoef(np.array(vi), np.array(vj))[0, 1])
            if np.isnan(r):
                continue
            computed += 1
            if r >= CLONE_R:
                clones.append((m_i, m_j, r, len(vi)))

    if computed == 0:
        print(f"  SKIP  No enabled pair had >= {MIN_OVERLAP} overlapping predictions — "
              f"correlation budget not evaluated")
        return True

    if not clones:
        print(f"  {GREEN}PASS  No enabled pair >= r{CLONE_R} "
              f"({computed} pair(s) evaluated){RESET}")
        return True

    print(f"  {RED}FAIL  {len(clones)} enabled pair(s) are r >= {CLONE_R} clones "
          f"(of {computed} evaluated):{RESET}")
    for a, b, r, n in sorted(clones, key=lambda x: -x[2]):
        print(f"         {a} <-> {b}  r={r:.4f}  (n={n})")
    print(f"  {RED}         Clone fleet — cross-model consensus signals collapse to a "
          f"single effective model.{RESET}")
    print(f"         Fix: disable one model from each clone pair, or enable a "
          f"decorrelated family.")
    return False


def print_fleet_snapshot(fleet):
    """Print today's enabled-fleet state up front."""
    print("Fleet Diversity Gate")
    print("=" * 70)
    print("TODAY'S ENABLED FLEET (enabled=TRUE AND status='active')")
    if not fleet:
        print("  (none)")
        return
    print(f"  {'model_id':<45} {'framework':<10} feature_set")
    print(f"  {'-'*45} {'-'*10} {'-'*12}")
    for m in fleet:
        print(f"  {m['model_id']:<45} {m['framework']:<10} {m['feature_set']}")


def main():
    parser = argparse.ArgumentParser(
        description="Fleet diversity gate — correlation-budget enforcement")
    parser.add_argument("--project-id", default="nba-props-platform",
                        help="GCP project ID")
    parser.add_argument("--days", type=int, default=14,
                        help="Look back N days for correlation slate (default: 14)")
    parser.add_argument("--skip-correlation", action="store_true",
                        help="Skip the prediction-vector correlation check (metadata only)")
    args = parser.parse_args()

    try:
        from google.cloud import bigquery
    except ImportError:
        print("ERROR: google-cloud-bigquery not installed", file=sys.stderr)
        sys.exit(1)

    client = bigquery.Client(project=args.project_id)

    try:
        fleet = load_enabled_fleet(client)
    except Exception as e:
        print(f"ERROR: could not load enabled fleet from {TABLE}: {e}", file=sys.stderr)
        sys.exit(1)

    print_fleet_snapshot(fleet)

    results = []
    results.append(check_family_diversity(fleet))
    results.append(check_pairwise_correlation(client, fleet, args.days,
                                              args.skip_correlation))

    print("\n" + "=" * 70)
    if all(results):
        print(f"{GREEN}RESULT: FLEET DIVERSITY BUDGET SATISFIED{RESET}")
        sys.exit(0)
    print(f"{RED}RESULT: FLEET DIVERSITY BUDGET VIOLATED{RESET}")
    print("This is a WARNING+FAIL gate. It does NOT auto-disable models — "
          "resolve manually before enabling.")
    sys.exit(1)


if __name__ == "__main__":
    main()
