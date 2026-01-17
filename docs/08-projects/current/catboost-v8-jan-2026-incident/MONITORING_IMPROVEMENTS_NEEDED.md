# Monitoring Improvements Needed

**Date**: 2026-01-17
**Priority**: P1 (Important - Next 1-2 Days)

---

## 🐛 **Bugs Found in Deployed Monitoring**

The monitoring function deployed successfully but has query bugs that need fixing:

### 1. BigQuery Region Mismatch
**Error**: `Dataset nba-props-platform:ml_nba was not found in location US`
**Cause**: Queries default to US region, but data is in us-west2
**Fix**: Add `location='us-west2'` to BigQuery client
**Affected Checks**: feature_quality, prediction_accuracy

```python
# Before
client = bigquery.Client()

# After
client = bigquery.Client(location='us-west2')
```

### 2. Timestamp Format Issue
**Error**: `The value '2026-01-17t02:50:04.274891' is of incorrect type`
**Cause**: Lowercase 't' in ISO timestamp (should be 'T')
**Fix**: Use proper timestamp formatting
**Affected Checks**: model_loading

```python
# Before
filter_str = '''timestamp>"%s"''' % (datetime.utcnow() - timedelta(hours=1)).isoformat()

# After
filter_str = '''timestamp>"%sZ"''' % (datetime.utcnow() - timedelta(hours=1)).isoformat().replace('t', 'T')
```

### 3. Wrong Column Name
**Error**: `Unrecognized name: is_correct at [4:27]`
**Cause**: Column doesn't exist in prediction_accuracy table
**Fix**: Determine correct column name
**Affected Checks**: prediction_accuracy

**Action Required**: Check schema of prediction_accuracy table
```bash
bq show --schema nba-props-platform:nba_predictions.prediction_accuracy
```

---

## 🚀 **Additional Monitoring to Add**

### Priority 1: Critical Alerts

#### 1. **Prediction Volume Drop**
**Why**: Detect system failures early
**Trigger**: <100 predictions when normally 200-500
**Check Frequency**: Every 4 hours

```python
def check_prediction_volume(request):
    query = """
        SELECT COUNT(*) as prediction_count
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
          AND game_date = CURRENT_DATE()
    """
    result = client.query(query).result()
    count = list(result)[0].prediction_count

    # Only alert after 2 PM PT (when most predictions should be in)
    if datetime.now().hour >= 22:  # UTC
        if count < 100:
            send_alert('WARNING', 'Low Prediction Volume',
                      f'Only {count} predictions today (expected 200-500)')
```

#### 2. **Environment Variable Check**
**Why**: Detect if CATBOOST_V8_MODEL_PATH gets accidentally removed
**Trigger**: Environment variable missing or changed
**Check Frequency**: Every 4 hours

```python
def check_catboost_config(request):
    from google.cloud import run_v2

    client = run_v2.ServicesClient()
    service = client.get_service(
        name='projects/nba-props-platform/locations/us-west2/services/prediction-worker'
    )

    env_vars = {env.name: env.value for env in service.template.containers[0].env}

    if 'CATBOOST_V8_MODEL_PATH' not in env_vars:
        send_alert('CRITICAL', 'CatBoost Model Path Missing',
                  'CATBOOST_V8_MODEL_PATH environment variable not set!')
        return {'status': 'ALERT', 'issue': 'missing_env_var'}

    expected_path = 'gs://nba-props-platform-models/catboost/v8/'
    if not env_vars['CATBOOST_V8_MODEL_PATH'].startswith(expected_path):
        send_alert('WARNING', 'CatBoost Model Path Changed',
                  f'Path changed to: {env_vars["CATBOOST_V8_MODEL_PATH"]}')
```

#### 3. **GCS Model File Existence**
**Why**: Detect if model file gets accidentally deleted
**Trigger**: Model file missing from GCS
**Check Frequency**: Daily

```python
def check_model_file_exists(request):
    from google.cloud import storage

    bucket_name = 'nba-props-platform-models'
    blob_name = 'catboost/v8/catboost_v8_33features_20260108_211817.cbm'

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    if not blob.exists():
        send_alert('CRITICAL', 'CatBoost Model File Missing',
                  f'Model file {blob_name} not found in GCS!')
        return {'status': 'ALERT', 'issue': 'missing_model'}
```

#### 4. **Cloud Scheduler Job Status**
**Why**: Detect if player_daily_cache scheduler gets disabled
**Trigger**: Scheduler job disabled or missing
**Check Frequency**: Daily

```python
def check_scheduler_health(request):
    from google.cloud import scheduler_v1

    client = scheduler_v1.CloudSchedulerClient()
    job_name = 'projects/nba-props-platform/locations/us-west2/jobs/player-daily-cache-trigger'

    try:
        job = client.get_job(name=job_name)
        if job.state != scheduler_v1.Job.State.ENABLED:
            send_alert('CRITICAL', 'Scheduler Job Disabled',
                      f'player_daily_cache scheduler is {job.state.name}')
    except Exception as e:
        send_alert('CRITICAL', 'Scheduler Job Missing',
                  f'player_daily_cache scheduler not found: {e}')
```

### Priority 2: Quality of Life Improvements

#### 5. **Slack Integration**
**Status**: ⚠️ Currently logs only (SLACK_WEBHOOK_URL not set)
**Action**: Get Slack webhook URL and set environment variable

```bash
# Set Slack webhook (get URL from Slack workspace settings)
gcloud functions update nba-monitoring-alerts \
  --region=us-west2 \
  --set-env-vars SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL" \
  --project=nba-props-platform
```

#### 6. **Email Alerts for CRITICAL Issues**
**Why**: Ensure critical alerts reach you even if Slack is down
**Implementation**: Use existing AWS SES integration

```python
def send_alert(severity, title, message, details=None):
    # ... existing Slack code ...

    # Add email for CRITICAL alerts
    if severity == 'CRITICAL':
        from shared.utils.email_alerting_ses import EmailAlertingSES
        emailer = EmailAlertingSES()
        emailer.send_alert(
            subject=f'[CRITICAL] {title}',
            body=f'{message}\n\nDetails: {json.dumps(details, indent=2)}',
            alert_type='critical'
        )
```

#### 7. **Dashboard/Visualization**
**Why**: See health at a glance
**Options**:
- Cloud Monitoring dashboard (native GCP)
- Grafana (more flexible)
- BigQuery + Data Studio (existing stack)

**Quick Win**: Create Data Studio dashboard
```sql
-- Query for dashboard
SELECT
  DATE(timestamp) as date,
  checks.player_daily_cache_freshness.status as cache_status,
  checks.model_loading.status as model_status,
  checks.confidence_distribution.status as confidence_status
FROM `nba-props-platform.monitoring.health_checks`
ORDER BY date DESC
LIMIT 30
```

---

## 🔧 **Immediate Action Items**

### Today/Tomorrow (P1)
1. [ ] Fix BigQuery region mismatch (add `location='us-west2'`)
2. [ ] Fix timestamp format in model_loading check
3. [ ] Investigate prediction_accuracy column name issue
4. [ ] Redeploy monitoring function with fixes

### Next Week (P1-P2)
5. [ ] Add prediction volume drop alert
6. [ ] Add environment variable check
7. [ ] Add GCS model file existence check
8. [ ] Add Cloud Scheduler health check
9. [ ] Set Slack webhook URL
10. [ ] Add email alerts for CRITICAL issues

### Nice to Have (P2)
11. [ ] Create Cloud Monitoring dashboard
12. [ ] Set up Data Studio visualization
13. [ ] Add trend detection (degrading over time)
14. [ ] Add anomaly detection (ML-based)

---

## 📋 **Deployment Script with Fixes**

Save this as `deploy_monitoring_alerts_v2.sh`:

```bash
#!/bin/bash
# Fixed version of monitoring alerts deployment

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SLACK_WEBHOOK_URL="${SLACK_ALERT_WEBHOOK_URL:-}"

echo "🔔 Deploying FIXED monitoring alerts..."

mkdir -p /tmp/monitoring_alerts_v2

cat > /tmp/monitoring_alerts_v2/main.py << 'EOF'
"""
Monitoring alerts for NBA prediction system (FIXED VERSION).
"""

import os
import json
from datetime import datetime, timedelta
from google.cloud import bigquery
from google.cloud import logging as cloud_logging
from google.cloud import storage
from google.cloud import run_v2
from google.cloud import scheduler_v1
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

    print(f"[{severity}] {title}: {message}")
    if details:
        print(f"Details: {json.dumps(details, indent=2)}")

    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if webhook_url:
        color = {'CRITICAL': '#FF0000', 'WARNING': '#FFA500', 'INFO': '#00FF00'}.get(severity, '#808080')
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
    client = bigquery.Client(location='us-west2')  # FIXED: Added location

    query = """
        SELECT MAX(cache_date) as latest_date
        FROM `nba-props-platform.nba_precompute.player_daily_cache`
    """

    result = list(client.query(query))[0]
    latest_date = result.latest_date
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
            details={'cache_date': str(latest_date), 'player_count': player_count}
        )
        return {'status': 'ALERT', 'issue': 'low_count'}

    print(f"✓ player_daily_cache is fresh: {latest_date} with {player_count} players")
    return {'status': 'OK'}

def check_confidence_distribution(request):
    """Alert if confidence clustered at single value."""
    client = bigquery.Client(location='us-west2')  # FIXED: Added location

    query = """
        SELECT confidence_score, COUNT(*) as picks
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8' AND game_date = CURRENT_DATE()
        GROUP BY confidence_score
    """

    results = list(client.query(query))
    if not results:
        print("ℹ️  No predictions found for current date")
        return {'status': 'NO_DATA'}

    total_picks = sum(r.picks for r in results)
    max_picks = max(r.picks for r in results)
    clustering_pct = max_picks / total_picks if total_picks > 0 else 0

    if clustering_pct > 0.80:
        max_confidence = [r.confidence_score for r in results if r.picks == max_picks][0]
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

    print(f"✓ Confidence distribution OK: {len(results)} unique values")
    return {'status': 'OK'}

def check_model_loading(request):
    """Alert if CatBoost V8 model fails to load."""
    logging_client = cloud_logging.Client()

    # FIXED: Proper timestamp formatting
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat().replace('+00:00', 'Z')

    filter_str = f'''
        resource.type="cloud_run_revision"
        resource.labels.service_name="prediction-worker"
        timestamp>="{one_hour_ago}"
        ("CatBoost V8 model FAILED to load" OR "FALLBACK_PREDICTION")
    '''

    entries = list(logging_client.list_entries(filter_=filter_str, max_results=10))

    if entries:
        send_alert(
            severity='CRITICAL',
            title='CatBoost Model Load Failure',
            message=f'Model failed to load {len(entries)} time(s) in last hour',
            details={'occurrences': len(entries)}
        )
        return {'status': 'ALERT', 'issue': 'model_load_failure'}

    print("✓ No model loading failures detected")
    return {'status': 'OK'}

def check_catboost_config(request):
    """Alert if CATBOOST_V8_MODEL_PATH environment variable missing."""
    try:
        client = run_v2.ServicesClient()
        service = client.get_service(
            name='projects/nba-props-platform/locations/us-west2/services/prediction-worker'
        )

        env_vars = {env.name: env.value for env in service.template.containers[0].env}

        if 'CATBOOST_V8_MODEL_PATH' not in env_vars:
            send_alert(
                severity='CRITICAL',
                title='CatBoost Model Path Missing',
                message='CATBOOST_V8_MODEL_PATH environment variable not set!'
            )
            return {'status': 'ALERT', 'issue': 'missing_env_var'}

        expected_path = 'gs://nba-props-platform-models/catboost/v8/'
        if not env_vars['CATBOOST_V8_MODEL_PATH'].startswith(expected_path):
            send_alert(
                severity='WARNING',
                title='CatBoost Model Path Changed',
                message=f'Path: {env_vars["CATBOOST_V8_MODEL_PATH"]}'
            )
            return {'status': 'ALERT', 'issue': 'path_changed'}

        print(f"✓ CatBoost config OK: {env_vars['CATBOOST_V8_MODEL_PATH']}")
        return {'status': 'OK'}
    except Exception as e:
        print(f"❌ Error checking config: {e}")
        return {'status': 'ERROR', 'error': str(e)}

def check_model_file_exists(request):
    """Alert if model file missing from GCS."""
    try:
        client = storage.Client()
        bucket = client.bucket('nba-props-platform-models')
        blob = bucket.blob('catboost/v8/catboost_v8_33features_20260108_211817.cbm')

        if not blob.exists():
            send_alert(
                severity='CRITICAL',
                title='CatBoost Model File Missing',
                message='Model file not found in GCS!'
            )
            return {'status': 'ALERT', 'issue': 'missing_model'}

        print(f"✓ Model file exists: {blob.size} bytes")
        return {'status': 'OK'}
    except Exception as e:
        print(f"❌ Error checking model file: {e}")
        return {'status': 'ERROR', 'error': str(e)}

def run_all_checks(request):
    """Run all monitoring checks."""
    results = {'timestamp': datetime.utcnow().isoformat(), 'checks': {}}

    print("=" * 60)
    print("🔍 Running all monitoring checks...")
    print("=" * 60)

    checks = [
        ('player_daily_cache_freshness', check_player_daily_cache_freshness),
        ('confidence_distribution', check_confidence_distribution),
        ('model_loading', check_model_loading),
        ('catboost_config', check_catboost_config),
        ('model_file_exists', check_model_file_exists),
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

cat > /tmp/monitoring_alerts_v2/requirements.txt << 'EOF'
google-cloud-bigquery>=3.0.0
google-cloud-logging>=3.0.0
google-cloud-storage>=2.0.0
google-cloud-run>=0.10.0
google-cloud-scheduler>=2.0.0
requests>=2.28.0
EOF

# Deploy/update function
gcloud functions deploy nba-monitoring-alerts \
    --gen2 \
    --region=$REGION \
    --project=$PROJECT_ID \
    --runtime=python310 \
    --source=/tmp/monitoring_alerts_v2 \
    --entry-point=run_all_checks \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL}" \
    --timeout=540s \
    --memory=512MB

echo "✅ Fixed monitoring function deployed!"
```

---

## 📊 **Testing the Fixes**

After redeploying with fixes:

```bash
# Get function URL
FUNCTION_URL=$(gcloud functions describe nba-monitoring-alerts \
    --region=us-west2 \
    --project=nba-props-platform \
    --format='value(serviceConfig.uri)')

# Test the function
curl -X POST "$FUNCTION_URL" -H "Content-Type: application/json"

# Check logs for errors
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=nba-monitoring-alerts" --limit=50 --format=json | jq '.[] | select(.severity == "ERROR")'
```

---

**Priority Order**:
1. **P1 (This week)**: Fix the 3 bugs in deployed monitoring
2. **P1 (This week)**: Add environment variable + GCS file checks
3. **P1 (Next week)**: Set Slack webhook for real-time alerts
4. **P2 (Nice to have)**: Add email alerts, dashboard, volume checks

