# Quick Start: NBA Grading Enhancements

**Goal**: Get Slack alerts + dashboard updates working in ~4 hours

---

## Prerequisites

### 1. Activate Scheduled Query (5 minutes)

**If not already done**:
```bash
# Follow the setup guide
cat schemas/bigquery/nba_predictions/SETUP_SCHEDULED_QUERY.md

# Or use BigQuery UI:
# 1. Go to https://console.cloud.google.com/bigquery
# 2. Click "Scheduled queries" → "CREATE SCHEDULED QUERY"
# 3. Copy query from SETUP_SCHEDULED_QUERY.md
# 4. Set schedule: Daily at 12:00 PM PT
# 5. Save
```

### 2. Create Slack Webhook (5 minutes)

**Steps**:
1. Go to your Slack workspace
2. Create channel: `#nba-grading-alerts`
3. Add incoming webhook:
   - Go to https://api.slack.com/apps
   - Create new app or use existing
   - Enable "Incoming Webhooks"
   - Add webhook to `#nba-grading-alerts`
   - Copy webhook URL

**Webhook URL format**:
```
https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
```

---

## Phase 1: Slack Alerting (2 hours)

### Step 1: Create Alert Service

**File**: `services/nba_grading_alerts/main.py`

```python
"""
NBA Grading Alerting Service

Monitors prediction grading and sends Slack alerts for:
- Grading failures (no grades generated)
- Accuracy drops (<55% threshold)
- High ungradeable rate (>20%)
"""

import os
import json
from datetime import datetime, timedelta
from google.cloud import bigquery
import requests


def send_slack_alert(webhook_url: str, message: dict):
    """Send alert to Slack."""
    response = requests.post(webhook_url, json=message, timeout=10)
    response.raise_for_status()
    return response.status_code


def check_grading_health(client: bigquery.Client, game_date: str) -> dict:
    """Check if grading ran successfully for a date."""
    query = f"""
    SELECT
        COUNT(*) as total_grades,
        COUNTIF(has_issues) as issue_count,
        ROUND(100.0 * COUNTIF(has_issues) / COUNT(*), 1) as issue_pct
    FROM `nba-props-platform.nba_predictions.prediction_grades`
    WHERE game_date = '{game_date}'
    """
    result = list(client.query(query).result())[0]
    return {
        'total_grades': result.total_grades,
        'issue_count': result.issue_count,
        'issue_pct': result.issue_pct
    }


def check_accuracy_health(client: bigquery.Client, days: int = 7) -> list:
    """Check if any system's accuracy dropped below threshold."""
    query = f"""
    SELECT
        system_id,
        ROUND(AVG(accuracy_pct), 1) as avg_accuracy,
        MIN(accuracy_pct) as min_accuracy,
        MAX(accuracy_pct) as max_accuracy,
        COUNT(*) as days_tracked
    FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    GROUP BY system_id
    HAVING avg_accuracy < 55  -- Alert threshold
    ORDER BY avg_accuracy ASC
    """
    return [dict(row) for row in client.query(query).result()]


def build_alert_message(alert_type: str, data: dict) -> dict:
    """Build Slack message payload."""
    if alert_type == 'grading_failure':
        return {
            "text": f"🚨 NBA Grading Alert: No grades generated for {data['game_date']}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🚨 Grading Failure Detected"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Date:*\n{data['game_date']}"},
                        {"type": "mrkdwn", "text": f"*Grades:*\n{data['total_grades']}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Action Required:*\nCheck scheduled query execution history"}
                }
            ]
        }

    elif alert_type == 'accuracy_drop':
        systems_text = "\n".join([
            f"• {s['system_id']}: {s['avg_accuracy']}% (min: {s['min_accuracy']}%)"
            for s in data['systems']
        ])
        return {
            "text": f"⚠️ NBA Grading Alert: Accuracy drop detected",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "⚠️ Accuracy Drop Detected"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Systems below 55% threshold:*\n{systems_text}"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Period:*\nLast {data['days']} days"},
                        {"type": "mrkdwn", "text": f"*Count:*\n{len(data['systems'])} system(s)"}
                    ]
                }
            ]
        }

    elif alert_type == 'data_quality':
        return {
            "text": f"⚠️ NBA Grading Alert: High ungradeable rate",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "⚠️ Data Quality Issue"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Date:*\n{data['game_date']}"},
                        {"type": "mrkdwn", "text": f"*Issue Rate:*\n{data['issue_pct']}%"}
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Details:*\n{data['issue_count']} of {data['total_grades']} predictions have issues"}
                }
            ]
        }

    return {"text": f"NBA Grading Alert: {alert_type}"}


def main(request):
    """Cloud Function entry point."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return {"error": "SLACK_WEBHOOK_URL not configured"}, 500

    client = bigquery.Client()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()

    alerts = []

    # Check 1: Grading ran
    health = check_grading_health(client, yesterday)
    if health['total_grades'] == 0:
        alerts.append(('grading_failure', {'game_date': yesterday, **health}))
    elif health['issue_pct'] > 20:
        alerts.append(('data_quality', {'game_date': yesterday, **health}))

    # Check 2: Accuracy drop
    low_accuracy_systems = check_accuracy_health(client, days=7)
    if low_accuracy_systems:
        alerts.append(('accuracy_drop', {'systems': low_accuracy_systems, 'days': 7}))

    # Send alerts
    for alert_type, data in alerts:
        message = build_alert_message(alert_type, data)
        send_slack_alert(webhook_url, message)

    return {
        "status": "success",
        "alerts_sent": len(alerts),
        "alert_types": [a[0] for a in alerts]
    }


if __name__ == '__main__':
    # For local testing
    class MockRequest:
        pass
    print(main(MockRequest()))
```

**File**: `services/nba_grading_alerts/requirements.txt`

```txt
google-cloud-bigquery==3.11.4
requests==2.31.0
```

**File**: `services/nba_grading_alerts/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# For Cloud Run
ENV PORT=8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "60", "main:app"]

# For Cloud Function, this Dockerfile isn't needed
```

### Step 2: Deploy to Cloud Function

**File**: `bin/alerts/deploy_nba_grading_alerts.sh`

```bash
#!/bin/bash
set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="nba-grading-alerts"

# Get Slack webhook from Secret Manager (you'll need to store it first)
SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret="nba-grading-slack-webhook")

echo "Deploying NBA Grading Alerts Cloud Function..."

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=services/nba_grading_alerts \
    --entry-point=main \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars="SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL" \
    --timeout=60s \
    --memory=256Mi \
    --project=$PROJECT_ID

echo "✅ Deployed successfully!"

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --format='value(serviceConfig.uri)')
echo "Function URL: $FUNCTION_URL"

# Create Cloud Scheduler job to trigger daily
gcloud scheduler jobs create http nba-grading-alerts-daily \
    --location=$REGION \
    --schedule="30 20 * * *" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --time-zone="America/Los_Angeles" \
    --project=$PROJECT_ID \
    || echo "Scheduler job already exists"

echo "✅ Scheduler configured to run daily at 12:30 PM PT"
```

### Step 3: Store Slack Webhook in Secret Manager

```bash
# Store webhook URL securely
echo "YOUR_WEBHOOK_URL" | gcloud secrets create nba-grading-slack-webhook \
    --data-file=- \
    --replication-policy="automatic"

# Grant Cloud Function access
gcloud secrets add-iam-policy-binding nba-grading-slack-webhook \
    --member="serviceAccount:nba-props-platform@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Step 4: Deploy

```bash
chmod +x bin/alerts/deploy_nba_grading_alerts.sh
./bin/alerts/deploy_nba_grading_alerts.sh
```

### Step 5: Test

```bash
# Manually trigger to test
FUNCTION_URL=$(gcloud functions describe nba-grading-alerts --region=us-west2 --format='value(serviceConfig.uri)')
curl -X POST $FUNCTION_URL

# Check Slack channel for alerts
```

---

## Phase 2: Dashboard Updates (2 hours)

### Step 1: Fix Schema Mismatch

**File**: `services/admin_dashboard/services/bigquery_service.py`

**Find** (around line 500):
```python
def get_grading_status(self, days: int = 7):
    query = f"""
    WITH predictions AS (
        SELECT game_date, COUNT(*) as prediction_count
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        ...
```

**Replace with**:
```python
def get_grading_status(self, days: int = 7):
    """Get grading status from prediction_grades table."""
    query = f"""
    WITH predictions AS (
        SELECT
            game_date,
            COUNT(*) as prediction_count
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE is_active = TRUE
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY game_date
    ),
    graded AS (
        SELECT
            game_date,
            COUNT(*) as graded_count,
            ROUND(AVG(margin_of_error), 1) as mae,
            COUNTIF(prediction_correct) as correct,
            COUNTIF(NOT prediction_correct) as incorrect,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 1) as accuracy_pct
        FROM `{self.project_id}.nba_predictions.prediction_grades`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY game_date
    )
    SELECT
        p.game_date,
        p.prediction_count,
        COALESCE(g.graded_count, 0) as graded_count,
        g.mae,
        g.accuracy_pct,
        CASE
            WHEN g.graded_count IS NULL THEN 'NOT_GRADED'
            WHEN g.graded_count < p.prediction_count * 0.8 THEN 'PARTIAL'
            ELSE 'COMPLETE'
        END as grading_status
    FROM predictions p
    LEFT JOIN graded g USING (game_date)
    ORDER BY p.game_date DESC
    """
    try:
        results = self.client.query(query).result()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error getting grading status: {e}")
        return []
```

### Step 2: Add System Breakdown Method

**Add to** `bigquery_service.py`:

```python
def get_grading_by_system(self, days: int = 7):
    """Get grading breakdown by system."""
    query = f"""
    SELECT
        system_id,
        total_predictions,
        correct_predictions,
        incorrect_predictions,
        accuracy_pct,
        avg_margin_of_error,
        avg_confidence
    FROM `{self.project_id}.nba_predictions.prediction_accuracy_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    ORDER BY accuracy_pct DESC
    """
    try:
        results = self.client.query(query).result()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error getting system breakdown: {e}")
        return []
```

### Step 3: Add API Endpoint

**File**: `services/admin_dashboard/main.py`

**Add route** (around line 400):

```python
@app.route('/api/<sport>/grading-by-system')
@rate_limit
def api_grading_by_system(sport):
    """Get grading breakdown by system."""
    validate_sport(sport)
    bq_svc = BigQueryService(sport=sport)
    days = clamp_param(request.args.get('days', 7, type=int), *PARAM_BOUNDS['days'])
    data = bq_svc.get_grading_by_system(days=days)
    return jsonify({'grading_by_system': data})
```

### Step 4: Update Template

**File**: `services/admin_dashboard/templates/components/coverage_metrics.html`

**Add after existing grading table** (around line 80):

```html
<!-- System Breakdown Section -->
<div class="mt-8">
    <h3 class="text-lg font-semibold mb-4">Grading by System (Last 7 Days)</h3>
    <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">System</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Predictions</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Correct</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Accuracy</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Margin</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Confidence</th>
                </tr>
            </thead>
            <tbody id="system-grading-tbody" class="bg-white divide-y divide-gray-200">
                <!-- Populated by JavaScript -->
            </tbody>
        </table>
    </div>
</div>

<script>
// Fetch and render system breakdown
async function loadSystemGrading() {
    const sport = '{{ sport }}';
    const response = await fetch(`/api/${sport}/grading-by-system?days=7`);
    const data = await response.json();

    const tbody = document.getElementById('system-grading-tbody');
    tbody.innerHTML = data.grading_by_system.map(row => `
        <tr>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${row.system_id}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.total_predictions}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.correct_predictions}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm ${row.accuracy_pct >= 60 ? 'text-green-600 font-semibold' : 'text-gray-900'}">${row.accuracy_pct}%</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.avg_margin_of_error} pts</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${row.avg_confidence}%</td>
        </tr>
    `).join('');
}

// Load on page load
loadSystemGrading();
</script>
```

### Step 5: Deploy Dashboard Updates

```bash
cd services/admin_dashboard
./deploy.sh
```

---

## Verification

### Test Slack Alerts

1. Trigger function manually:
   ```bash
   gcloud scheduler jobs run nba-grading-alerts-daily --location=us-west2
   ```

2. Check Slack channel for alerts

3. Verify alert formatting and content

### Test Dashboard

1. Open admin dashboard: https://admin.nba-props.com/dashboard
2. Navigate to "Coverage Metrics" tab
3. Verify:
   - Grading status shows accuracy_pct
   - System breakdown table appears
   - Data matches BigQuery views

---

## Troubleshooting

**Slack alerts not appearing**:
- Check Cloud Function logs: `gcloud functions logs read nba-grading-alerts --region=us-west2`
- Verify webhook URL is correct
- Test webhook with curl:
  ```bash
  curl -X POST -H 'Content-type: application/json' \
      --data '{"text":"Test alert"}' \
      YOUR_WEBHOOK_URL
  ```

**Dashboard showing old data**:
- Check BigQuery: `SELECT * FROM nba_predictions.prediction_accuracy_summary ORDER BY game_date DESC LIMIT 5`
- Verify scheduled query is running
- Clear browser cache

**"Table not found" errors**:
- Verify tables exist: `bq ls nba_predictions`
- Check query references correct table names
- Ensure views are created

---

## Next Steps After Phase 1+2

Once alerts and dashboard are working:

1. **Monitor for 1 week**:
   - Ensure alerts fire correctly
   - Verify dashboard accuracy
   - Tune alert thresholds if needed

2. **Backfill historical data**:
   - Run grading for all dates since Jan 1

3. **Plan Phase 3 enhancements**:
   - ROI calculator
   - Grading analysis tab
   - Looker Studio dashboard

---

**Estimated Time**: 4 hours total
- Slack alerts: 2 hours
- Dashboard updates: 2 hours

**Cost**: ~$0.10/day (Cloud Function + Scheduler)
