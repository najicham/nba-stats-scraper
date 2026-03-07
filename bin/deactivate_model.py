#!/usr/bin/env python3
"""Model Deactivation Cascade CLI

Properly deactivate a model: disable in registry, deactivate predictions,
log audit trail. Prevents poisoned picks from persisting in best bets.

Usage:
    python bin/deactivate_model.py MODEL_ID [--date YYYY-MM-DD] [--dry-run] [--re-export]

Examples:
    python bin/deactivate_model.py xgb_v12_noveg_train1221_0208 --dry-run
    python bin/deactivate_model.py xgb_v12_noveg_train1221_0208 --date 2026-03-01
    python bin/deactivate_model.py xgb_v12_noveg_train1221_0208 --re-export

Created: 2026-03-02 (Session 386)
"""

import argparse
import hashlib
import sys
from datetime import date, datetime, timezone

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'


def main():
    parser = argparse.ArgumentParser(
        description='Deactivate a model: disable in registry + deactivate predictions'
    )
    parser.add_argument('model_id', help='Model ID to deactivate (e.g. xgb_v12_noveg_train1221_0208)')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD). Default: today', default=None)
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without executing')
    parser.add_argument('--re-export', action='store_true', help='Re-export all.json after deactivation')
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    model_id = args.model_id
    dry_run = args.dry_run

    bq = bigquery.Client(project=PROJECT_ID)

    print(f"{'[DRY RUN] ' if dry_run else ''}Deactivating model: {model_id}")
    print(f"Target date: {target_date}")
    print()

    # Step 1: Verify model exists and check current state
    check_query = f"""
    SELECT model_id, enabled, status, model_family, feature_set
    FROM `{PROJECT_ID}.nba_predictions.model_registry`
    WHERE model_id = @model_id
    """
    check_params = [bigquery.ScalarQueryParameter('model_id', 'STRING', model_id)]
    rows = list(bq.query(
        check_query,
        job_config=bigquery.QueryJobConfig(query_parameters=check_params),
    ).result(timeout=15))

    if not rows:
        print(f"ERROR: Model '{model_id}' not found in model_registry")
        sys.exit(1)

    row = rows[0]
    print(f"  Found: {row.model_id}")
    print(f"  Family: {row.model_family}, Feature set: {row.feature_set}")
    print(f"  Current state: enabled={row.enabled}, status={row.status}")

    if not row.enabled and row.status == 'blocked':
        print(f"\n  Model already disabled and blocked.")
    print()

    # Step 2: Count affected predictions
    count_query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE system_id = @model_id
      AND game_date = @target_date
      AND is_active = TRUE
    """
    count_params = [
        bigquery.ScalarQueryParameter('model_id', 'STRING', model_id),
        bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
    ]
    count_row = list(bq.query(
        count_query,
        job_config=bigquery.QueryJobConfig(query_parameters=count_params),
    ).result(timeout=15))[0]
    active_preds = count_row.cnt

    # Count signal best bets from this model
    signal_count_query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
    WHERE system_id = @model_id
      AND game_date = @target_date
    """
    signal_count_row = list(bq.query(
        signal_count_query,
        job_config=bigquery.QueryJobConfig(query_parameters=count_params),
    ).result(timeout=15))[0]
    signal_preds = signal_count_row.cnt

    print(f"  Active predictions on {target_date}: {active_preds}")
    print(f"  Signal best bets on {target_date}: {signal_preds}")
    print()

    if dry_run:
        print("[DRY RUN] Would perform:")
        print(f"  1. SET enabled=FALSE, status='blocked' in model_registry")
        print(f"  2. SET is_active=FALSE for {active_preds} predictions on {target_date}")
        if signal_preds > 0:
            print(f"  3. DELETE {signal_preds} signal best bets on {target_date}")
        print(f"  4. Log to service_errors for audit trail")
        if args.re_export:
            print(f"  5. Re-export all.json for {target_date}")
        return

    # Step 3: Disable in model_registry
    if row.enabled or row.status != 'blocked':
        disable_query = f"""
        UPDATE `{PROJECT_ID}.nba_predictions.model_registry`
        SET enabled = FALSE, status = 'blocked'
        WHERE model_id = @model_id
        """
        job = bq.query(
            disable_query,
            job_config=bigquery.QueryJobConfig(query_parameters=check_params),
        )
        job.result(timeout=15)
        print(f"  [OK] Disabled in model_registry ({job.num_dml_affected_rows} rows)")
    else:
        print(f"  [SKIP] Already disabled in model_registry")

    # Step 4: Deactivate predictions
    if active_preds > 0:
        deactivate_query = f"""
        UPDATE `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP()
        WHERE system_id = @model_id
          AND game_date = @target_date
          AND is_active = TRUE
        """
        job = bq.query(
            deactivate_query,
            job_config=bigquery.QueryJobConfig(query_parameters=count_params),
        )
        job.result(timeout=30)
        print(f"  [OK] Deactivated {job.num_dml_affected_rows} predictions")
    else:
        print(f"  [SKIP] No active predictions to deactivate")

    # Step 5: Remove from signal best bets
    if signal_preds > 0:
        signal_delete_query = f"""
        DELETE FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
        WHERE system_id = @model_id
          AND game_date = @target_date
        """
        job = bq.query(
            signal_delete_query,
            job_config=bigquery.QueryJobConfig(query_parameters=count_params),
        )
        job.result(timeout=30)
        print(f"  [OK] Removed {job.num_dml_affected_rows} signal best bets")

    # Step 6: Audit trail — write to nba_orchestration.service_errors
    now = datetime.now(timezone.utc)
    error_msg = f'Deactivated model {model_id}: {active_preds} predictions, {signal_preds} signal picks'
    error_id = hashlib.md5(
        f'deactivate_model_cli:model_deactivation:{error_msg}:{now.strftime("%Y%m%d%H%M")}'.encode()
    ).hexdigest()
    audit_query = f"""
    INSERT INTO `{PROJECT_ID}.nba_orchestration.service_errors`
    (error_id, service_name, error_timestamp, error_type, error_category,
     severity, error_message, game_date, phase, recovery_attempted, recovery_successful)
    VALUES (
      @error_id,
      'deactivate_model_cli',
      @error_timestamp,
      'model_deactivation',
      'model_lifecycle',
      'info',
      @message,
      @game_date,
      'phase_5_predictions',
      FALSE,
      FALSE
    )
    """
    audit_params = [
        bigquery.ScalarQueryParameter('error_id', 'STRING', error_id),
        bigquery.ScalarQueryParameter('error_timestamp', 'TIMESTAMP', now.isoformat()),
        bigquery.ScalarQueryParameter('message', 'STRING', error_msg),
        bigquery.ScalarQueryParameter('game_date', 'DATE', str(target_date)),
    ]
    try:
        bq.query(
            audit_query,
            job_config=bigquery.QueryJobConfig(query_parameters=audit_params),
        ).result(timeout=15)
        print(f"  [OK] Logged audit trail to service_errors")
    except Exception as e:
        print(f"  [WARN] Failed to log audit (non-fatal): {e}")

    print()
    print(f"Deactivation complete for {model_id}")

    # Step 7: Re-export if requested
    if args.re_export:
        print(f"\nRe-exporting all.json for {target_date}...")
        try:
            from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter
            exporter = BestBetsAllExporter()
            path = exporter.export(target_date, trigger_source='manual')
            print(f"  [OK] Exported to: {path}")
        except Exception as e:
            print(f"  [ERROR] Re-export failed: {e}")
            print(f"  Run manually: python -c \"from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter; BestBetsAllExporter().export('{target_date}', trigger_source='manual')\"")


if __name__ == '__main__':
    main()
