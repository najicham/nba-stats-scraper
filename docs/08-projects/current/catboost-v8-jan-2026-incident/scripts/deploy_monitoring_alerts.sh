#!/bin/bash
# Deploy Monitoring Alerts for CatBoost V8 Incident Prevention
# Date: 2026-01-16
# Purpose: Prevent recurrence of Jan 2026 incident

set -e  # Exit on error

echo "🔔 Deploying monitoring alerts for CatBoost V8 incident prevention..."

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SLACK_WEBHOOK_URL="${SLACK_ALERT_WEBHOOK_URL}"  # Set this env var

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "📋 Checking prerequisites..."

if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo -e "${YELLOW}⚠️  SLACK_ALERT_WEBHOOK_URL not set. Alerts will log only (no Slack notifications)${NC}"
fi

# Create monitoring function if it doesn't exist
echo "📦 Creating monitoring Cloud Function..."

cat > /tmp/monitoring_alerts/main.py << 'EOF'
"""
Monitoring alerts for NBA prediction system.
Prevents recurrence of CatBoost V8 Jan 2026 incident.
"""

import os
import json
from datetime import datetime, timedelta
from google.cloud import bigquery
import requests

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

    query = """
        SELECT
            AVG(feature_quality_score) as avg_quality,
            MIN(feature_quality_score) as min_quality,
            COUNTIF(data_source = 'phase4_partial') / COUNT(*) as phase4_partial_pct
        FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
        WHERE game_date = CURRENT_DATE()
    """

    result = list(client.query(query))
    if not result:
        send_alert(
            severity='WARNING',
            title='No ML Feature Store Data',
            message='No feature store records found for current date'
        )
        return {'status': 'ALERT', 'issue': 'no_data'}

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
    """Alert if confidence clustered at single value."""
    client = bigquery.Client()

    query = """
        SELECT
            confidence_score,
            COUNT(*) as picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
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
    """Alert if prediction accuracy degrades significantly."""
    client = bigquery.Client()

    query = """
        SELECT
            AVG(ABS(predicted_points - actual_points)) as avg_error,
            AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as win_rate,
            COUNT(*) as total_picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
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

    filter_str = '''
        resource.type="cloud_run_revision"
        resource.labels.service_name="prediction-worker"
        timestamp>"%s"
        ("CatBoost V8 model FAILED to load" OR "FALLBACK_PREDICTION")
    ''' % (datetime.utcnow() - timedelta(hours=1)).isoformat()

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
EOF

cat > /tmp/monitoring_alerts/requirements.txt << 'EOF'
google-cloud-bigquery>=3.0.0
google-cloud-logging>=3.0.0
requests>=2.28.0
EOF

# Deploy function
if gcloud functions describe nba-monitoring-alerts --region=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "Updating existing function..."
    ACTION="update"
else
    echo "Creating new function..."
    ACTION="deploy"
fi

gcloud functions $ACTION nba-monitoring-alerts \
    --region=$REGION \
    --project=$PROJECT_ID \
    --runtime=python310 \
    --source=/tmp/monitoring_alerts \
    --entry-point=run_all_checks \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL}" \
    --timeout=540s \
    --memory=512MB

echo -e "${GREEN}✅ Monitoring function deployed${NC}"

# Create Cloud Scheduler job
echo "⏰ Creating Cloud Scheduler job..."

if gcloud scheduler jobs describe nba-monitoring-alerts --location=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "Updating existing scheduler job..."
    gcloud scheduler jobs delete nba-monitoring-alerts \
        --location=$REGION \
        --project=$PROJECT_ID \
        --quiet
fi

# Get function URL
FUNCTION_URL=$(gcloud functions describe nba-monitoring-alerts \
    --region=$REGION \
    --project=$PROJECT_ID \
    --format='value(serviceConfig.uri)')

gcloud scheduler jobs create http nba-monitoring-alerts \
    --location=$REGION \
    --project=$PROJECT_ID \
    --schedule="0 */4 * * *" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --time-zone="America/Los_Angeles" \
    --description="Monitor CatBoost V8 system health (every 4 hours)"

echo -e "${GREEN}✅ Scheduler job created (runs every 4 hours)${NC}"

# Test the alerts
echo "🧪 Testing alerts..."
curl -X POST "$FUNCTION_URL" -H "Content-Type: application/json"

echo ""
echo "=" * 60
echo -e "${GREEN}✅ Monitoring alerts deployed successfully!${NC}"
echo "=" * 60
echo ""
echo "Next steps:"
echo "1. Check Cloud Scheduler: https://console.cloud.google.com/cloudscheduler?project=$PROJECT_ID"
echo "2. Check Cloud Function: https://console.cloud.google.com/functions/details/$REGION/nba-monitoring-alerts?project=$PROJECT_ID"
echo "3. Monitor Slack channel for alerts (if webhook configured)"
echo ""
echo "Schedule: Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 PT)"
echo ""
