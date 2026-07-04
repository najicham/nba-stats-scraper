"""
Monitoring alerts for NBA prediction system.
Prevents recurrence of CatBoost V8 Jan 2026 incident.

PROVENANCE: This source was exhumed 2026-07-04 from the deployed
`nba-monitoring-alerts` Cloud Function (gcf-v2-sources bucket, generation
1768621716807390) and committed to the repo. Before this, the only copy lived in
an incident-doc markdown heredoc, so it could silently break on any doc edit and
was invisible to the syntax/schema pre-commit hooks.

FIXES applied 2026-07-04 (the CF was logging two BigQuery errors every 4h, 24/7):
  1. check_feature_quality_degradation: `ml_nba.ml_feature_store_v2` -> the dataset
     `ml_nba` does not exist; the table lives in `nba_predictions`.
  2. check_prediction_accuracy: `is_correct` is not a column of prediction_accuracy;
     the correct boolean is `prediction_correct`.
Both corrected queries were dry-run-validated against the live schema.

KNOWN STALENESS (season-open follow-up):
  check_confidence_distribution and check_prediction_accuracy target TARGET_SYSTEM_ID,
  which defaults to the retired 'catboost_v8' (env MONITOR_SYSTEM_ID overrides). The
  fleet is now 10+ shadow models with no single champion (see CLAUDE.md MODEL section),
  so with the default these two checks return NO_DATA and monitor nothing. At season
  open, either set MONITOR_SYSTEM_ID to an active model or make the checks fleet-wide.
  This is a documented no-op default, NOT a silent hardcode — and they no longer ERROR,
  which is the bleeding this commit stops.
"""

import os
import json
from datetime import datetime, timedelta
from google.cloud import bigquery
import requests

# system_id that the accuracy/confidence checks target. Was hardcoded to the retired
# 'catboost_v8' champion; parameterized 2026-07-04 so it is not a silent stale hardcode
# (the validate-model-references pre-commit hook rightly rejects hardcoded catboost_v* ids).
# Season-open follow-up: set MONITOR_SYSTEM_ID to an active model, or make these two checks
# fleet-wide. Until then they return NO_DATA (no catboost_v8 predictions exist).
TARGET_SYSTEM_ID = os.getenv('MONITOR_SYSTEM_ID', 'catboost_v8')

def send_alert(severity, title, message, details=None):
    """Send alert to Slack and/or logging."""
    alert = {
        'timestamp': datetime.utcnow().isoformat(),
        'severity': severity,
        'title': title,
        'message': message,
        'details': details or {}
    }

    # Log to stdout (Cloud Logging)
    print(f"[{severity}] {title}: {message}")
    if details:
        print(f"Details: {json.dumps(details, indent=2)}")

    # Send to Slack if webhook configured
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if webhook_url:
        color = {
            'CRITICAL': '#FF0000',
            'WARNING': '#FFA500',
            'INFO': '#00FF00'
        }.get(severity, '#808080')

        slack_message = {
            'attachments': [{
                'color': color,
                'title': f"[{severity}] {title}",
                'text': message,
                'fields': [{'title': k, 'value': str(v), 'short': True}
                          for k, v in (details or {}).items()],
                'footer': 'NBA Prediction Monitoring',
                'ts': int(datetime.utcnow().timestamp())
            }]
        }

        try:
            response = requests.post(webhook_url, json=slack_message, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to send Slack alert: {e}")


def check_player_daily_cache_freshness(request):
    """Alert if player_daily_cache hasn't updated in 24 hours."""
    client = bigquery.Client()

    query = """
        SELECT MAX(cache_date) as latest_date
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
    """

    result = list(client.query(query))[0]
    latest_date = result.latest_date

    # Check if older than 24 hours (accounting for timezone)
    expected_date = (datetime.utcnow() - timedelta(days=1)).date()

    if latest_date < expected_date:
        send_alert(
            severity='CRITICAL',
            title='player_daily_cache Not Updated',
            message=f'player_daily_cache table has not been updated',
            details={
                'latest_date': str(latest_date),
                'expected_date': str(expected_date),
                'days_behind': (expected_date - latest_date).days
            }
        )
        return {'status': 'ALERT', 'issue': 'stale_data'}

    # Also check record count
    count_query = f"""
        SELECT COUNT(DISTINCT player_lookup) as players
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
        WHERE cache_date = '{latest_date}'
    """

    count_result = list(client.query(count_query))[0]
    player_count = count_result.players

    if player_count < 50:
        send_alert(
            severity='WARNING',
            title='Low player_daily_cache Record Count',
            message=f'Only {player_count} players in latest cache (expected 50-200)',
            details={
                'cache_date': str(latest_date),
                'player_count': player_count,
                'threshold': 50
            }
        )
        return {'status': 'ALERT', 'issue': 'low_count'}

    print(f"✓ player_daily_cache is fresh: {latest_date} with {player_count} players")
    return {'status': 'OK'}


def check_feature_quality_degradation(request):
    """Alert if feature quality drops significantly."""
    client = bigquery.Client()

    # FIX 2026-07-04: dataset was `ml_nba` (does not exist) -> `nba_predictions`.
    # Also SAFE_DIVIDE the phase4 ratio + count rows: the aggregate always returns one
    # row, so with 0 rows today `COUNTIF/COUNT` was `0/0` (division-by-zero error) and
    # the NULL aggregates would fire a false "quality degraded" alert. Guard on total_rows.
    query = """
        SELECT
            AVG(feature_quality_score) as avg_quality,
            MIN(feature_quality_score) as min_quality,
            SAFE_DIVIDE(COUNTIF(data_source = 'phase4_partial'), COUNT(*)) as phase4_partial_pct,
            COUNT(*) as total_rows
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = CURRENT_DATE()
    """

    result = list(client.query(query))
    if not result or not result[0].total_rows:
        # No feature-store rows for today yet (off-season / early in day). Not an alert.
        print("ℹ️  No feature store records for current date yet")
        return {'status': 'NO_DATA'}

    result = result[0]
    avg_quality = result.avg_quality or 0
    min_quality = result.min_quality or 0
    phase4_partial_pct = result.phase4_partial_pct or 0

    alerts = []

    if avg_quality < 85:
        send_alert(
            severity='WARNING',
            title='Feature Quality Degraded',
            message=f'Average feature quality is {avg_quality:.1f} (expected >85)',
            details={
                'avg_quality': avg_quality,
                'min_quality': min_quality,
                'threshold': 85
            }
        )
        alerts.append('low_quality')

    if phase4_partial_pct < 0.30:
        send_alert(
            severity='WARNING',
            title='Phase4 Partial Data Low',
            message=f'Only {phase4_partial_pct*100:.1f}% phase4_partial features (expected >40%)',
            details={
                'phase4_partial_pct': f'{phase4_partial_pct*100:.1f}%',
                'threshold': '40%'
            }
        )
        alerts.append('low_phase4')

    if not alerts:
        print(f"✓ Feature quality OK: avg={avg_quality:.1f}, phase4_partial={phase4_partial_pct*100:.1f}%")
        return {'status': 'OK'}

    return {'status': 'ALERT', 'issues': alerts}


def check_confidence_distribution(request):
    """Alert if confidence clustered at single value.

    Targets TARGET_SYSTEM_ID (env MONITOR_SYSTEM_ID, default retired 'catboost_v8')
    so it returns NO_DATA until pointed at an active model. See module docstring.
    """
    client = bigquery.Client()

    query = f"""
        SELECT
            confidence_score,
            COUNT(*) as picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = '{TARGET_SYSTEM_ID}'
          AND game_date = CURRENT_DATE()
        GROUP BY confidence_score
    """

    results = list(client.query(query))
    if not results:
        # No predictions yet today, that's OK
        print("ℹ️  No predictions found for current date (may be early in day)")
        return {'status': 'NO_DATA'}

    total_picks = sum(r.picks for r in results)
    max_picks = max(r.picks for r in results)
    max_confidence = [r.confidence_score for r in results if r.picks == max_picks][0]

    clustering_pct = max_picks / total_picks if total_picks > 0 else 0

    if clustering_pct > 0.80:
        send_alert(
            severity='CRITICAL',
            title='Confidence Clustering Detected',
            message=f'{clustering_pct*100:.1f}% of picks at single confidence value',
            details={
                'clustering_pct': f'{clustering_pct*100:.1f}%',
                'dominant_confidence': f'{max_confidence*100:.0f}%',
                'picks_at_value': max_picks,
                'total_picks': total_picks
            }
        )
        return {'status': 'ALERT', 'issue': 'clustering'}

    # Also check for variety (should have >5 unique values)
    unique_confidences = len(results)
    if unique_confidences < 5 and total_picks > 20:
        send_alert(
            severity='WARNING',
            title='Low Confidence Variety',
            message=f'Only {unique_confidences} unique confidence values (expected >5)',
            details={
                'unique_confidences': unique_confidences,
                'total_picks': total_picks,
                'threshold': 5
            }
        )
        return {'status': 'ALERT', 'issue': 'low_variety'}

    print(f"✓ Confidence distribution OK: {unique_confidences} unique values, max clustering {clustering_pct*100:.1f}%")
    return {'status': 'OK'}


def check_prediction_accuracy(request):
    """Alert if prediction accuracy degrades significantly.

    Targets TARGET_SYSTEM_ID (env MONITOR_SYSTEM_ID, default retired 'catboost_v8')
    so it returns NO_DATA until pointed at an active model. See module docstring.
    """
    client = bigquery.Client()

    # FIX 2026-07-04: `is_correct` is not a column of prediction_accuracy ->
    # `prediction_correct` (the graded boolean).
    query = f"""
        SELECT
            AVG(ABS(predicted_points - actual_points)) as avg_error,
            AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as win_rate,
            COUNT(*) as total_picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = '{TARGET_SYSTEM_ID}'
          AND game_date = CURRENT_DATE()
    """

    result = list(client.query(query))
    if not result or not result[0].total_picks:
        print("ℹ️  No graded predictions for current date yet")
        return {'status': 'NO_DATA'}

    result = result[0]
    avg_error = result.avg_error
    win_rate = result.win_rate
    total_picks = result.total_picks

    alerts = []

    # Only alert if we have enough picks to be meaningful
    if total_picks < 10:
        print(f"ℹ️  Only {total_picks} picks graded, waiting for more data")
        return {'status': 'INSUFFICIENT_DATA'}

    if avg_error > 5.5:  # Baseline is ~4.2
        send_alert(
            severity='WARNING',
            title='Prediction Error Increased',
            message=f'Average error is {avg_error:.2f} points (expected <5.0)',
            details={
                'avg_error': f'{avg_error:.2f}',
                'threshold': '5.0',
                'total_picks': total_picks
            }
        )
        alerts.append('high_error')

    if win_rate < 0.50:
        send_alert(
            severity='CRITICAL',
            title='Win Rate Below 50%',
            message=f'Win rate is {win_rate*100:.1f}% (below breakeven)',
            details={
                'win_rate': f'{win_rate*100:.1f}%',
                'threshold': '50%',
                'total_picks': total_picks
            }
        )
        alerts.append('low_win_rate')

    if not alerts:
        print(f"✓ Accuracy OK: error={avg_error:.2f}, win_rate={win_rate*100:.1f}% ({total_picks} picks)")
        return {'status': 'OK'}

    return {'status': 'ALERT', 'issues': alerts}


def check_model_loading(request):
    """Alert if CatBoost V8 model fails to load."""
    from google.cloud import logging as cloud_logging

    # Check logs for model loading failures in last hour
    logging_client = cloud_logging.Client()

    # FIX 2026-07-04: Cloud Logging requires an RFC3339 timestamp WITH timezone.
    # `datetime.utcnow().isoformat()` is naive (no 'Z') and was rejected as
    # "incorrect type" every run — append 'Z' to mark it UTC.
    filter_str = '''
        resource.type="cloud_run_revision"
        resource.labels.service_name="prediction-worker"
        timestamp>"%s"
        ("CatBoost V8 model FAILED to load" OR "FALLBACK_PREDICTION")
    ''' % ((datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z')

    entries = list(logging_client.list_entries(filter_=filter_str, max_results=10))

    if entries:
        send_alert(
            severity='CRITICAL',
            title='CatBoost Model Load Failure',
            message=f'Model failed to load {len(entries)} time(s) in last hour',
            details={
                'occurrences': len(entries),
                'last_hour': 'yes',
                'check': 'Cloud Run logs for details'
            }
        )
        return {'status': 'ALERT', 'issue': 'model_load_failure'}

    print("✓ No model loading failures detected in last hour")
    return {'status': 'OK'}


def run_all_checks(request):
    """Run all monitoring checks."""
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'checks': {}
    }

    print("=" * 60)
    print("🔍 Running all monitoring checks...")
    print("=" * 60)

    checks = [
        ('player_daily_cache_freshness', check_player_daily_cache_freshness),
        ('feature_quality', check_feature_quality_degradation),
        ('confidence_distribution', check_confidence_distribution),
        ('prediction_accuracy', check_prediction_accuracy),
        ('model_loading', check_model_loading),
    ]

    for name, check_func in checks:
        print(f"\n📊 Checking {name}...")
        try:
            result = check_func(request)
            results['checks'][name] = result
        except Exception as e:
            print(f"❌ Error in {name}: {e}")
            results['checks'][name] = {'status': 'ERROR', 'error': str(e)}

    print("\n" + "=" * 60)
    print("✅ All checks complete")
    print("=" * 60)

    return results


# Gen2 entry point is `run_all_checks`; alias `main` for convenience/immutability safety.
main = run_all_checks
