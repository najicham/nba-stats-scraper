# Pipeline Health Dashboard - Deployment Guide

Complete step-by-step guide for deploying the Pipeline Health Dashboard from scratch.

## Prerequisites

### Required Access
- [ ] GCP Project: `nba-props-platform`
- [ ] BigQuery Admin or Editor role
- [ ] Cloud Monitoring Editor role
- [ ] gcloud CLI installed and authenticated

### Required Services
- [ ] BigQuery API enabled
- [ ] Cloud Monitoring API enabled
- [ ] BigQuery Data Transfer API enabled (for scheduled queries)

### Verify Prerequisites

```bash
# Check authentication
gcloud auth list

# Set project
gcloud config set project nba-props-platform

# Verify BigQuery access
bq ls --project_id=nba-props-platform

# Enable required APIs
gcloud services enable bigquery.googleapis.com
gcloud services enable monitoring.googleapis.com
gcloud services enable bigquerydatatransfer.googleapis.com
```

## Step-by-Step Deployment

### Step 1: Deploy BigQuery Views (5 minutes)

Create the monitoring views that aggregate data from source tables.

```bash
cd /home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_health

# Deploy all views
./deploy_views.sh
```

**Expected Output**:
```
================================================================
Pipeline Health Dashboard - View Deployment
================================================================
Project: nba-props-platform
Dataset: nba_monitoring
Location: us-east1

Checking if dataset exists...
✓ Dataset nba_monitoring already exists

Deploying monitoring views...

Deploying view: pipeline_health_summary...
✓ View pipeline_health_summary deployed successfully

Deploying view: processor_error_summary...
✓ View processor_error_summary deployed successfully

Deploying view: prediction_coverage_metrics...
✓ View prediction_coverage_metrics deployed successfully

Deploying view: pipeline_latency_metrics...
✓ View pipeline_latency_metrics deployed successfully

================================================================
✓ All views deployed successfully!
```

**Verify Deployment**:
```bash
# List views
bq ls --project_id=nba-props-platform nba_monitoring

# Test query
bq query --use_legacy_sql=false \
  "SELECT * FROM \`nba-props-platform.nba_monitoring.pipeline_health_summary\` LIMIT 5"
```

### Step 2: Set Up Scheduled Queries (10 minutes)

Create hourly scheduled queries to materialize view results for faster dashboard loading.

```bash
# Run setup script
./scheduled_queries_setup.sh
```

**Expected Output**:
```
Setting up scheduled queries for pipeline health dashboard...
Creating scheduled query: pipeline_health_summary_materialized
✓ Pipeline health summary scheduled query created
...
✓ All scheduled queries created successfully!

Materialized tables:
  - nba-props-platform.nba_monitoring.pipeline_health_summary_materialized
  - nba-props-platform.nba_monitoring.processor_error_summary_materialized
  - nba-props-platform.nba_monitoring.prediction_coverage_metrics_materialized
  - nba-props-platform.nba_monitoring.pipeline_latency_metrics_materialized

Refresh schedule: Every 1 hour
Retention: 30 days
```

**Verify Scheduled Queries**:
```bash
# List scheduled queries
bq ls --transfer_config --project_id=nba-props-platform

# Check first run (wait 1 hour or manually trigger)
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_monitoring.pipeline_health_summary_materialized\`"
```

**Manual Trigger (Optional)**:
```bash
# Get transfer config ID
bq ls --transfer_config --project_id=nba-props-platform | grep "Pipeline Health"

# Trigger run
bq mk --transfer_run \
  --run_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  projects/nba-props-platform/locations/us-east1/transferConfigs/[TRANSFER_CONFIG_ID]
```

### Step 3: Import Cloud Monitoring Dashboard (5 minutes)

Import the pre-configured dashboard into Cloud Monitoring.

#### Option A: gcloud CLI (Recommended)

```bash
gcloud monitoring dashboards create \
  --config-from-file=pipeline_health_dashboard.json \
  --project=nba-props-platform
```

**Expected Output**:
```
Created dashboard [projects/nba-props-platform/dashboards/xxxxx-xxxx-xxxx].
```

#### Option B: GCP Console (Alternative)

1. Navigate to: https://console.cloud.google.com/monitoring/dashboards
2. Click "Create Dashboard"
3. Click on dashboard name → "JSON" editor icon
4. Copy contents of `pipeline_health_dashboard.json`
5. Paste into JSON editor
6. Click "Save"

**Verify Dashboard**:
1. Go to: https://console.cloud.google.com/monitoring/dashboards
2. Find "NBA Pipeline Health Dashboard"
3. Verify widgets load (may take a few minutes for first data)

### Step 4: Configure Cloud Monitoring Metrics (10 minutes)

The dashboard references custom metrics that need to be populated from BigQuery. Set up a Cloud Function or Cloud Run service to export metrics.

#### Create Metrics Export Script

```python
# scripts/export_metrics_to_monitoring.py
from google.cloud import bigquery, monitoring_v3
import time

def export_pipeline_health_metrics():
    """Export BigQuery metrics to Cloud Monitoring"""
    client = bigquery.Client()
    monitoring_client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/nba-props-platform"

    # Query pipeline health summary
    query = """
        SELECT
            phase_name,
            completion_percentage,
            failure_rate
        FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
        WHERE time_window = 'last_24h'
    """

    results = client.query(query).result()

    for row in results:
        # Create metric descriptor if needed
        metric_type = f"custom.googleapis.com/pipeline_health/{row.phase_name}_completion"

        # Create time series
        series = monitoring_v3.TimeSeries()
        series.metric.type = metric_type
        series.resource.type = "bigquery_project"
        series.resource.labels["project_id"] = "nba-props-platform"

        # Add data point
        point = monitoring_v3.Point()
        point.value.double_value = row.completion_percentage
        point.interval.end_time.seconds = int(time.time())
        series.points = [point]

        # Write to Cloud Monitoring
        monitoring_client.create_time_series(
            name=project_name,
            time_series=[series]
        )

    print("✓ Metrics exported to Cloud Monitoring")

if __name__ == "__main__":
    export_pipeline_health_metrics()
```

#### Deploy to Cloud Scheduler

```bash
# Create Cloud Function
gcloud functions deploy export-pipeline-metrics \
  --runtime=python311 \
  --trigger-http \
  --entry-point=export_pipeline_health_metrics \
  --source=scripts/ \
  --project=nba-props-platform

# Create scheduler job (runs every 5 minutes)
gcloud scheduler jobs create http export-pipeline-metrics \
  --schedule="*/5 * * * *" \
  --uri="https://us-east1-nba-props-platform.cloudfunctions.net/export-pipeline-metrics" \
  --http-method=POST \
  --project=nba-props-platform
```

### Step 5: Set Up Alert Policies (15 minutes)

Create alert policies for critical pipeline issues.

#### Alert 1: Low Phase Completion Rate

```bash
gcloud monitoring policies create \
  --notification-channels=[CHANNEL_ID] \
  --display-name="Pipeline Phase 3 Low Completion Rate" \
  --condition-display-name="Completion rate below 75%" \
  --condition-threshold-value=75 \
  --condition-threshold-duration=7200s \
  --condition-threshold-comparison=COMPARISON_LT \
  --condition-filter='resource.type="bigquery_project" AND metric.type="custom.googleapis.com/pipeline_health/phase3_completion"' \
  --project=nba-props-platform
```

#### Alert 2: High Error Count

```bash
gcloud monitoring policies create \
  --notification-channels=[CHANNEL_ID] \
  --display-name="High Pipeline Error Count" \
  --condition-display-name="More than 10 critical errors" \
  --condition-threshold-value=10 \
  --condition-threshold-duration=3600s \
  --condition-threshold-comparison=COMPARISON_GT \
  --condition-filter='resource.type="bigquery_project" AND metric.type="custom.googleapis.com/pipeline_health/critical_errors"' \
  --project=nba-props-platform
```

#### Alert 3: Coverage Degradation

```bash
gcloud monitoring policies create \
  --notification-channels=[CHANNEL_ID] \
  --display-name="Prediction Coverage Below 80%" \
  --condition-display-name="Coverage below threshold" \
  --condition-threshold-value=80 \
  --condition-threshold-duration=7200s \
  --condition-threshold-comparison=COMPARISON_LT \
  --condition-filter='resource.type="bigquery_project" AND metric.type="custom.googleapis.com/prediction_coverage/coverage_percentage"' \
  --project=nba-props-platform
```

**Get Notification Channel ID**:
```bash
gcloud monitoring channels list --project=nba-props-platform
```

### Step 6: Deploy HTML Dashboard (Optional, 10 minutes)

For quick access without GCP Console login, deploy standalone HTML dashboard to Cloud Run.

```bash
# Build and deploy
cd monitoring/dashboards/pipeline_health

# Create Dockerfile (if not exists)
cat > Dockerfile <<EOF
FROM python:3.11-slim
WORKDIR /app
COPY pipeline_health.html /app/
COPY server.py /app/
RUN pip install flask google-cloud-bigquery
CMD ["python", "server.py"]
EOF

# Create simple Flask server
cat > server.py <<EOF
from flask import Flask, render_template_string
from google.cloud import bigquery

app = Flask(__name__)
client = bigquery.Client()

@app.route('/')
def index():
    with open('pipeline_health.html', 'r') as f:
        return render_template_string(f.read())

@app.route('/api/health')
def health():
    # Add API endpoints for dashboard data
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
EOF

# Deploy to Cloud Run
gcloud run deploy pipeline-health-dashboard \
  --source=. \
  --platform=managed \
  --region=us-east1 \
  --allow-unauthenticated \
  --project=nba-props-platform
```

**Access Dashboard**:
```
https://pipeline-health-dashboard-[hash]-ue.a.run.app
```

## Verification Checklist

After deployment, verify each component:

### Views
- [ ] All 4 views exist in `nba_monitoring` dataset
- [ ] Views return data (not empty)
- [ ] Query execution time < 10 seconds

```bash
bq query --use_legacy_sql=false \
  "SELECT * FROM \`nba-props-platform.nba_monitoring.pipeline_health_summary\` LIMIT 1"
```

### Scheduled Queries
- [ ] 4 scheduled queries created
- [ ] Scheduled queries enabled
- [ ] Materialized tables populated
- [ ] No errors in transfer runs

```bash
bq ls --transfer_config --project_id=nba-props-platform
bq ls nba_monitoring | grep materialized
```

### Dashboard
- [ ] Dashboard visible in Cloud Monitoring
- [ ] All widgets load data
- [ ] No "No data available" errors
- [ ] Charts render correctly

### Alerts
- [ ] Alert policies created
- [ ] Notification channels configured
- [ ] Test alerts fire correctly

### HTML Dashboard (if deployed)
- [ ] Cloud Run service deployed
- [ ] URL accessible
- [ ] Metrics display correctly

## Troubleshooting

### Views Don't Return Data

**Problem**: Views return 0 rows

**Solutions**:
1. Check source tables have data:
   ```bash
   bq query "SELECT COUNT(*) FROM \`nba-props-platform.nba_reference.processor_run_history\` WHERE data_date >= CURRENT_DATE() - 7"
   ```
2. Verify date filters in views match your data
3. Check partitioning is working

### Scheduled Queries Fail

**Problem**: Transfer runs show errors

**Solutions**:
1. Check BigQuery Data Transfer API is enabled
2. Verify service account permissions
3. Review error logs:
   ```bash
   bq ls --transfer_run --transfer_config=[CONFIG_ID]
   ```

### Dashboard Shows "No Data"

**Problem**: Cloud Monitoring widgets empty

**Solutions**:
1. Verify custom metrics exist:
   ```bash
   gcloud monitoring metrics list --project=nba-props-platform | grep pipeline_health
   ```
2. Check metrics export script is running
3. Wait 5-10 minutes for first data points

### High BigQuery Costs

**Problem**: Unexpected BigQuery charges

**Solutions**:
1. Reduce scheduled query frequency (hourly → every 2 hours)
2. Add more aggressive date filters
3. Use materialized tables in dashboard queries
4. Set up cost alerts

## Maintenance Schedule

### Daily
- Review dashboard for critical alerts
- Check completion rates are >90%

### Weekly
- Review error trends
- Investigate persistent failures
- Update alert thresholds if needed

### Monthly
- Review BigQuery costs
- Optimize slow queries
- Update view logic if schemas change
- Clean up old materialized data

## Rollback Procedure

If deployment causes issues:

### Remove Scheduled Queries
```bash
# List transfers
bq ls --transfer_config --project_id=nba-props-platform

# Delete transfers
bq rm --transfer_config [TRANSFER_CONFIG_ID]
```

### Remove Dashboard
```bash
# List dashboards
gcloud monitoring dashboards list --project=nba-props-platform

# Delete dashboard
gcloud monitoring dashboards delete [DASHBOARD_ID]
```

### Remove Views
```bash
bq rm -f nba-props-platform:nba_monitoring.pipeline_health_summary
bq rm -f nba-props-platform:nba_monitoring.processor_error_summary
bq rm -f nba-props-platform:nba_monitoring.prediction_coverage_metrics
bq rm -f nba-props-platform:nba_monitoring.pipeline_latency_metrics
```

## Support

For deployment issues:
- Slack: #data-engineering
- Email: data-team@company.com
- GitHub Issues: Create issue with `deployment` label

## Next Steps

After successful deployment:
1. Share dashboard URL with team
2. Document alert response procedures
3. Set up weekly health reports
4. Create runbooks for common issues
5. Schedule dashboard review meetings
