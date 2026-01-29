# Sonnet Task 2: Implement Real-Time Error Alerting

## Task Summary
Create a Cloud Scheduler job that runs pipeline health monitoring every 30 minutes during game hours, with Slack alerting when issues are detected.

## Context
- Currently, failures are only discovered the next morning
- We need real-time alerts to catch issues immediately
- Game hours are 5 PM - 1 AM ET (22:00 - 06:00 UTC)
- The monitoring script already exists: `bin/monitoring/phase_success_monitor.py`

## Steps

### 1. First, Check Existing Scheduler Jobs
```bash
gcloud scheduler jobs list --location=us-west2
```

### 2. Create Cloud Scheduler Job

Create a job that triggers during game hours:
```bash
# Create a Pub/Sub topic for the scheduler (if not exists)
gcloud pubsub topics create pipeline-health-check --project=nba-props-platform 2>/dev/null || true

# Create the scheduler job
# Runs every 30 minutes from 5 PM to 1 AM ET (22:00-06:00 UTC)
gcloud scheduler jobs create http pipeline-health-monitor \
  --location=us-west2 \
  --schedule="*/30 22-23,0-6 * * *" \
  --uri="https://nba-phase1-scrapers-756957797294.us-west2.run.app/run-health-check" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"hours": 2, "alert_on_failure": true}' \
  --time-zone="UTC" \
  --attempt-deadline="300s"
```

**Note**: If the endpoint doesn't exist, we need to create it first (see Step 3).

### 3. Add Health Check Endpoint (if needed)

Check if the endpoint exists in the Phase 1 service:
```bash
grep -r "run-health-check\|health-check" /home/naji/code/nba-stats-scraper/scrapers/
```

If it doesn't exist, we need to add it. Create or modify the appropriate file to add:

```python
@app.route('/run-health-check', methods=['POST'])
def run_health_check():
    """Run pipeline health check and send alerts if needed."""
    import subprocess
    import json

    data = request.get_json() or {}
    hours = data.get('hours', 2)

    # Run the monitor script
    result = subprocess.run(
        ['python', 'bin/monitoring/phase_success_monitor.py', '--hours', str(hours)],
        capture_output=True,
        text=True,
        timeout=120
    )

    # Check for failures in output
    if '[FAIL]' in result.stdout or result.returncode != 0:
        # Send Slack alert
        send_slack_alert(result.stdout)

    return jsonify({
        'status': 'completed',
        'output': result.stdout[:1000]
    })
```

### 4. Alternative: Use Cloud Function Instead

If modifying the service is complex, create a standalone Cloud Function:

```bash
# Create a simple Cloud Function for health monitoring
mkdir -p /tmp/health-monitor-function
cat > /tmp/health-monitor-function/main.py << 'EOF'
import functions_framework
from google.cloud import bigquery
import requests
import os

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

@functions_framework.http
def check_pipeline_health(request):
    """Check pipeline health and alert on failures."""
    client = bigquery.Client()

    # Query for recent errors
    query = """
    SELECT
        COUNT(*) as error_count,
        COUNTIF(event_type = 'processor_complete') as success_count
    FROM `nba-props-platform.nba_orchestration.pipeline_event_log`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
      AND phase IN ('phase_3', 'phase_4')
    """

    result = list(client.query(query).result())[0]
    error_count = result.error_count
    success_count = result.success_count

    total = error_count + success_count
    success_rate = (success_count / total * 100) if total > 0 else 100

    if success_rate < 90:
        # Send Slack alert
        if SLACK_WEBHOOK:
            requests.post(SLACK_WEBHOOK, json={
                'text': f'⚠️ Pipeline Health Alert: Success rate {success_rate:.1f}% (threshold: 90%)\nErrors: {error_count}, Successes: {success_count}'
            })
        return f'ALERT: Success rate {success_rate:.1f}%', 500

    return f'OK: Success rate {success_rate:.1f}%', 200
EOF

cat > /tmp/health-monitor-function/requirements.txt << 'EOF'
functions-framework==3.*
google-cloud-bigquery>=3.0.0
requests>=2.28.0
EOF
```

Then deploy:
```bash
gcloud functions deploy pipeline-health-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=/tmp/health-monitor-function \
  --entry-point=check_pipeline_health \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars=SLACK_WEBHOOK_URL=<your-slack-webhook>
```

### 5. Create Scheduler for Cloud Function
```bash
# Get the function URL
FUNCTION_URL=$(gcloud functions describe pipeline-health-monitor --gen2 --region=us-west2 --format="value(serviceConfig.uri)")

# Create scheduler
gcloud scheduler jobs create http pipeline-health-monitor-job \
  --location=us-west2 \
  --schedule="*/30 22-23,0-6 * * *" \
  --uri="$FUNCTION_URL" \
  --http-method=GET \
  --time-zone="UTC" \
  --attempt-deadline="120s"
```

### 6. Test the Setup
```bash
# Manually trigger the job
gcloud scheduler jobs run pipeline-health-monitor-job --location=us-west2

# Check execution
gcloud scheduler jobs describe pipeline-health-monitor-job --location=us-west2
```

## Success Criteria
- [ ] Scheduler job created and running
- [ ] Health check executes successfully
- [ ] Slack alert fires when success rate < 90% (test by temporarily lowering threshold)

## Files to Check/Modify
- `bin/monitoring/phase_success_monitor.py` - existing monitor script
- `shared/utils/notification_system.py` - existing Slack notification code

## Slack Webhook
The project likely already has a Slack webhook configured. Check:
```bash
gcloud secrets list | grep -i slack
gcloud secrets versions access latest --secret=slack-webhook-url 2>/dev/null || echo "Secret not found"
```

## Time Estimate
30-45 minutes
