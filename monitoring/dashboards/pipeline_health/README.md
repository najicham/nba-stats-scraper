# Pipeline Health Dashboard

A comprehensive monitoring dashboard providing real-time visibility into NBA pipeline health across all phases (3, 4, 5).

## Overview

The Pipeline Health Dashboard consolidates metrics from across the entire data pipeline into a single view, enabling immediate identification of issues and bottlenecks.

### Key Features

1. **Phase Completion Tracking**: Real-time completion rates for Phase 3 (Analytics), Phase 4 (Precompute), and Phase 5 (Predictions)
2. **Error Analysis**: Detailed processor error tracking with transient vs permanent classification
3. **Coverage Monitoring**: Prediction coverage rates and gap analysis
4. **Latency Metrics**: End-to-end pipeline timing from game start to predictions ready
5. **Historical Trends**: 7-day rolling averages and trend analysis

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Sources                             │
├─────────────────────────────────────────────────────────────┤
│  • processor_run_history      (Phase 3)                     │
│  • precompute_processor_runs  (Phase 4)                     │
│  • player_prop_predictions    (Phase 5)                     │
│  • phase_execution_log        (Orchestration)               │
│  • scraper_execution_log      (Phase 2)                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│              BigQuery Views (Real-time)                     │
├─────────────────────────────────────────────────────────────┤
│  1. pipeline_health_summary                                 │
│  2. processor_error_summary                                 │
│  3. prediction_coverage_metrics                             │
│  4. pipeline_latency_metrics                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│       Scheduled Queries (Hourly Materialization)            │
├─────────────────────────────────────────────────────────────┤
│  • pipeline_health_summary_materialized                     │
│  • processor_error_summary_materialized                     │
│  • prediction_coverage_metrics_materialized                 │
│  • pipeline_latency_metrics_materialized                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Dashboard Layer                          │
├─────────────────────────────────────────────────────────────┤
│  • Cloud Monitoring Dashboard (GCP Console)                 │
│  • HTML Dashboard (Standalone)                              │
│  • Alert Policies (Automated Notifications)                 │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Deploy BigQuery Views

```bash
cd monitoring/dashboards/pipeline_health
./deploy_views.sh
```

This creates the `nba_monitoring` dataset and deploys all four monitoring views.

### 2. Set Up Scheduled Queries (Optional but Recommended)

```bash
./scheduled_queries_setup.sh
```

This creates hourly scheduled queries that materialize the views for faster dashboard loading and historical tracking.

### 3. Import Cloud Monitoring Dashboard

```bash
gcloud monitoring dashboards create \
  --config-from-file=pipeline_health_dashboard.json \
  --project=nba-props-platform
```

Or manually import via GCP Console:
1. Go to Cloud Monitoring > Dashboards
2. Click "Create Dashboard"
3. Click "JSON" tab
4. Paste contents of `pipeline_health_dashboard.json`
5. Click "Save"

### 4. Configure Alerts (Recommended)

See [Alert Policies](#alert-policies) section below.

## Dashboard Widgets

### Row 1: Phase Completion Gauges
- **Phase 3 Completion Rate**: Analytics processing success rate (24h)
- **Phase 4 Completion Rate**: Precompute processing success rate (24h)
- **Phase 5 Completion Rate**: Prediction generation success rate (24h)

**Thresholds**:
- Green: ≥90% (Healthy)
- Yellow: 75-89% (Warning)
- Red: <75% (Critical)

### Row 2: Error and Coverage Charts
- **Error Rate by Phase**: Time-series showing error rates across all phases (7d)
- **Prediction Coverage Trend**: Line chart showing % of players with predictions (7d)

### Row 3: Latency Distribution
- **Pipeline Latency Distribution**: Stacked bar chart showing time spent in each phase (7d)
  - Phase 3 (Analytics): Blue
  - Phase 4 (Precompute): Green
  - Phase 5 (Predictions): Orange

### Row 4: Detailed Analysis
- **Top 5 Failing Processors**: Table showing most frequent failures (24h)
- **Coverage Gap Breakdown**: Pie chart showing reasons for coverage gaps

## Metrics Reference

### Pipeline Health Summary
```sql
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
WHERE time_window = 'last_24h';
```

**Key Columns**:
- `completion_percentage`: Success rate (0-100)
- `failure_rate`: Failure rate (0-100)
- `date_coverage_percentage`: % of dates with at least one success

### Processor Error Summary
```sql
SELECT * FROM `nba-props-platform.nba_monitoring.processor_error_summary`
WHERE time_window = 'last_24h'
  AND alert_priority IN ('CRITICAL', 'HIGH')
ORDER BY error_count DESC;
```

**Key Columns**:
- `error_count`: Total errors in time window
- `error_type`: 'transient' or 'permanent'
- `retry_success_rate`: % of retries that succeeded
- `alert_priority`: CRITICAL, HIGH, MEDIUM, LOW

### Prediction Coverage Metrics
```sql
SELECT * FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;
```

**Key Columns**:
- `coverage_percentage`: % of players with lines that have predictions
- `coverage_7d_avg`: 7-day rolling average
- `health_status`: HEALTHY, WARNING, DEGRADED, CRITICAL
- `gap_*`: Counts by gap reason

### Pipeline Latency Metrics
```sql
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
WHERE game_date = CURRENT_DATE();
```

**Key Columns**:
- `phase*_latency_minutes`: Time spent in each phase
- `total_latency_minutes`: Game start to predictions ready
- `pipeline_health`: HEALTHY (<3h), DEGRADED (<6h), SLOW (>6h)

## Alert Policies

### Recommended Alerts

#### 1. Low Phase Completion Rate
```yaml
Condition: completion_percentage < 75 for 2 consecutive hours
Severity: Critical
Notification: #data-engineering, PagerDuty
```

#### 2. High Error Rate
```yaml
Condition: alert_priority = 'CRITICAL' AND error_count > 10
Severity: High
Notification: #data-engineering
```

#### 3. Coverage Degradation
```yaml
Condition: coverage_percentage < 80 for 2 consecutive days
Severity: High
Notification: #predictions-team
```

#### 4. Excessive Pipeline Latency
```yaml
Condition: total_latency_minutes > 360 (6 hours)
Severity: Medium
Notification: #data-engineering
```

### Create Alert Policies

```bash
# Example: Low completion rate alert
gcloud monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Pipeline Phase 3 Low Completion Rate" \
  --condition-display-name="Completion rate below 75%" \
  --condition-threshold-value=75 \
  --condition-threshold-duration=7200s \
  --condition-filter='resource.type="bigquery_project" AND metric.type="custom.googleapis.com/pipeline_health/phase3_completion"'
```

## HTML Dashboard (Optional)

For quick access without GCP Console login, deploy the standalone HTML dashboard:

```bash
# Build and deploy to Cloud Run
cd monitoring/dashboards/pipeline_health
./deploy_html_dashboard.sh
```

Access at: `https://pipeline-health-dashboard-[hash]-ue.a.run.app`

The HTML dashboard:
- Auto-refreshes every 5 minutes
- Shows same metrics as Cloud Monitoring dashboard
- No authentication required (configure IAP for production)
- Lightweight and fast

## Maintenance

### View Updates

When source schemas change, update and redeploy views:

```bash
# Edit view files in monitoring/bigquery_views/
# Then redeploy
cd monitoring/dashboards/pipeline_health
./deploy_views.sh
```

### Scheduled Query Management

List scheduled queries:
```bash
bq ls --transfer_config --project_id=nba-props-platform
```

Update schedule:
```bash
bq update --transfer_config \
  --schedule="every 30 minutes" \
  [TRANSFER_CONFIG_ID]
```

Disable scheduled query:
```bash
bq update --transfer_config \
  --disable \
  [TRANSFER_CONFIG_ID]
```

### Dashboard Updates

Update Cloud Monitoring dashboard:
```bash
# Get dashboard ID
gcloud monitoring dashboards list --project=nba-props-platform

# Update dashboard
gcloud monitoring dashboards update [DASHBOARD_ID] \
  --config-from-file=pipeline_health_dashboard.json
```

## Troubleshooting

### No Data in Dashboard

**Symptom**: Widgets show "No data available"

**Solutions**:
1. Verify views exist and return data:
   ```bash
   bq query "SELECT * FROM nba-props-platform.nba_monitoring.pipeline_health_summary LIMIT 10"
   ```
2. Check scheduled queries are running:
   ```bash
   bq ls --transfer_config --project_id=nba-props-platform
   ```
3. Verify source tables have recent data:
   ```bash
   bq query "SELECT MAX(data_date) FROM nba-props-platform.nba_reference.processor_run_history"
   ```

### Slow Dashboard Loading

**Symptom**: Dashboard takes >5 seconds to load

**Solutions**:
1. Ensure scheduled queries are enabled and running
2. Use materialized tables instead of views:
   ```json
   "filter": "resource.table_id=\"pipeline_health_summary_materialized\""
   ```
3. Reduce time window in queries (e.g., 7d → 3d)

### Missing Metrics

**Symptom**: Some phases show no data

**Solutions**:
1. Verify phase is actually running (check processor_run_history)
2. Check date filters in views match your data
3. Ensure partitioning is working correctly

### Alert Fatigue

**Symptom**: Too many alerts firing

**Solutions**:
1. Increase thresholds (75% → 70%)
2. Add longer duration requirements (1h → 2h)
3. Use alert suppression during known maintenance windows
4. Filter out expected failures using `failure_category`

## Cost Optimization

### Query Costs
- Views: ~$0.10-0.50 per dashboard load
- Materialized tables: ~$0.50-1.00 per hour (scheduled queries)
- Estimated monthly cost: $50-100 (with hourly refresh)

### Optimization Tips
1. Use materialized tables for frequently accessed metrics
2. Reduce scheduled query frequency during off-season
3. Set partition expiration on materialized tables (30 days)
4. Monitor BigQuery costs in Cloud Monitoring

## Related Documentation

- [BigQuery Views](../../bigquery_views/README.md): View schemas and queries
- [Alert Policies](../../../alert-policies/README.md): Alert configuration
- [Processor Monitoring](../../../processors/README.md): Individual processor health
- [Phase Orchestration](../../../../orchestration/README.md): Phase transition logic

## Support

For issues or questions:
- Slack: #data-engineering
- Email: data-team@company.com
- GitHub Issues: [repo]/issues

## Changelog

### v1.0.0 (2026-01-26)
- Initial release
- Four core monitoring views
- Cloud Monitoring dashboard configuration
- Scheduled query setup
- Documentation and deployment scripts
