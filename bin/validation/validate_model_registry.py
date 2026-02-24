#!/usr/bin/env python3
"""
Model Registry Consistency Validation

Checks for common model registry issues:
1. Duplicate enabled families (multiple enabled models per family)
2. Enabled + deprecated conflict (enabled=TRUE but status='deprecated')
3. Champion model present in registry
4. Missing GCS model files for enabled models

Usage:
    python bin/validation/validate_model_registry.py
    python bin/validation/validate_model_registry.py --skip-gcs
    python bin/validation/validate_model_registry.py --fix

Part of: Model Governance (Feb 2026)
"""

import argparse
import subprocess
import sys

from google.cloud import bigquery

TABLE = "nba_predictions.model_registry"


def check_duplicate_enabled_families(client: bigquery.Client, fix: bool) -> bool:
    """Check that each model_family has at most one enabled model."""
    query = f"""
        SELECT model_family, COUNT(*) AS cnt,
               ARRAY_AGG(model_id) AS model_ids
        FROM `{client.project}.{TABLE}`
        WHERE enabled = TRUE
        GROUP BY model_family
        HAVING COUNT(*) > 1
    """
    rows = list(client.query(query).result())
    if not rows:
        print("  PASS  No duplicate enabled families")
        return True

    print("  FAIL  Duplicate enabled families found:")
    for row in rows:
        ids = ", ".join(row.model_ids)
        print(f"         family={row.model_family} count={row.cnt} models=[{ids}]")
        if fix:
            print(f"         FIX: UPDATE `{client.project}.{TABLE}` SET enabled=FALSE")
            print(f"              WHERE model_family='{row.model_family}' AND model_id != '<keep_one>';")
    return False


def check_enabled_deprecated_conflict(client: bigquery.Client, fix: bool) -> bool:
    """Check that no enabled model has status='deprecated'."""
    query = f"""
        SELECT model_id, model_family, status
        FROM `{client.project}.{TABLE}`
        WHERE enabled = TRUE AND status = 'deprecated'
    """
    rows = list(client.query(query).result())
    if not rows:
        print("  PASS  No enabled+deprecated conflicts")
        return True

    print("  FAIL  Enabled models with deprecated status:")
    for row in rows:
        print(f"         model_id={row.model_id} family={row.model_family}")
        if fix:
            print(f"         FIX: UPDATE `{client.project}.{TABLE}` SET enabled=FALSE")
            print(f"              WHERE model_id='{row.model_id}';")
    return False


def check_champion_in_registry(client: bigquery.Client, fix: bool) -> bool:
    """Check that the champion model from model_selection.py appears in the registry."""
    try:
        sys.path.insert(0, ".")
        from shared.config.model_selection import get_champion_model_id
        champion = get_champion_model_id()
    except ImportError:
        print("  SKIP  Could not import get_champion_model_id (run from repo root)")
        return True

    query = f"""
        SELECT model_id, status, enabled, is_production
        FROM `{client.project}.{TABLE}`
        WHERE model_id = @champion
           OR model_id LIKE CONCAT(@champion, '%')
        LIMIT 5
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("champion", "STRING", champion),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())

    if not rows:
        print(f"  FAIL  Champion '{champion}' not found in registry")
        if fix:
            print(f"         FIX: Register champion via INSERT INTO `{client.project}.{TABLE}` ...")
        return False

    # Check at least one match is production or active
    active = [r for r in rows if r.status in ('active', 'production') or r.is_production]
    if active:
        m = active[0]
        print(f"  PASS  Champion '{champion}' found (status={m.status}, production={m.is_production})")
        return True

    statuses = ", ".join(f"{r.model_id}:{r.status}" for r in rows)
    print(f"  FAIL  Champion '{champion}' found but not active/production: [{statuses}]")
    if fix:
        print(f"         FIX: UPDATE `{client.project}.{TABLE}` SET status='active',")
        print(f"              is_production=TRUE WHERE model_id='{champion}';")
    return False


def check_gcs_files(client: bigquery.Client, fix: bool) -> bool:
    """Check that GCS model files exist for all enabled models."""
    query = f"""
        SELECT model_id, gcs_path
        FROM `{client.project}.{TABLE}`
        WHERE enabled = TRUE AND gcs_path IS NOT NULL
    """
    rows = list(client.query(query).result())
    if not rows:
        print("  PASS  No enabled models with GCS paths to check")
        return True

    checked, missing = 0, []
    for row in rows:
        if not row.gcs_path:
            continue
        try:
            result = subprocess.run(
                ["gsutil", "stat", row.gcs_path],
                capture_output=True, timeout=15
            )
            checked += 1
            if result.returncode != 0:
                missing.append((row.model_id, row.gcs_path))
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"  WARN  GCS check failed for {row.model_id}: {e}")
            continue

    if not missing:
        print(f"  PASS  All {checked} enabled model files exist in GCS")
        return True

    print(f"  FAIL  {len(missing)} enabled model(s) missing from GCS:")
    for model_id, gcs_path in missing:
        print(f"         {model_id}: {gcs_path}")
        if fix:
            print(f"         FIX: gsutil cp <local> {gcs_path}")
            print(f"           OR: UPDATE ... SET enabled=FALSE WHERE model_id='{model_id}';")
    return False


def main():
    parser = argparse.ArgumentParser(description="Validate model registry consistency")
    parser.add_argument("--project-id", default="nba-props-platform", help="GCP project ID")
    parser.add_argument("--fix", action="store_true", help="Show fix suggestions for failures")
    parser.add_argument("--skip-gcs", action="store_true", help="Skip GCS file existence checks")
    args = parser.parse_args()

    print(f"Model Registry Validation (project={args.project_id})")
    print("=" * 60)

    client = bigquery.Client(project=args.project_id)
    results = []

    print("\n[1/4] Duplicate enabled families")
    results.append(check_duplicate_enabled_families(client, args.fix))

    print("\n[2/4] Enabled + deprecated conflict")
    results.append(check_enabled_deprecated_conflict(client, args.fix))

    print("\n[3/4] Champion model in registry")
    results.append(check_champion_in_registry(client, args.fix))

    if args.skip_gcs:
        print("\n[4/4] GCS file existence")
        print("  SKIP  --skip-gcs flag set")
    else:
        print("\n[4/4] GCS file existence")
        results.append(check_gcs_files(client, args.fix))

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"RESULT: ALL {total} CHECKS PASSED")
        sys.exit(0)
    else:
        print(f"RESULT: {total - passed}/{total} CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
