#!/bin/bash
# monitoring/scripts/setup_monitoring.sh
# Set up monitoring and alerting for NBA analytics platform

set -e

PROJECT_ID=${1:-$(gcloud config get-value project)}
NOTIFICATION_EMAIL=${2:-"admin@example.com"}

echo "🏀 Setting up NBA Platform Monitoring"
echo "Project: $PROJECT_ID"
echo "Notification Email: $NOTIFICATION_EMAIL"

# Create notification channel for email alerts
echo "Creating notification channel..."
NOTIFICATION_CHANNEL=$(gcloud alpha monitoring channels create \
  --display-name="NBA Platform Alerts" \
  --type=email \
  --channel-labels=email_address=$NOTIFICATION_EMAIL \
  --format="value(name)")

echo "Created notification channel: $NOTIFICATION_CHANNEL"

# Create custom metric descriptors
echo "Creating custom metric descriptors..."

# Scraper metrics
gcloud monitoring metrics-descriptors create \
  --type="custom.googleapis.com/nba/scraper_records_scraped" \
  --description="Number of records scraped by NBA scrapers" \
  --metric-kind=GAUGE \
  --value-type=INT64 \
  --labels="scraper:Name of the scraper,status:Success or failure status"

gcloud monitoring metrics-descriptors create \
  --type="custom.googleapis.com/nba/scraper_execution_time_seconds" \
  --description="Execution time for NBA scrapers in seconds" \
  --metric-kind=GAUGE \
  --value-type=DOUBLE \
  --labels="scraper:Name of the scraper,status:Success or failure status"

# Processor metrics  
gcloud monitoring metrics-descriptors create \
  --type="custom.googleapis.com/nba/processor_records_processed" \
  --description="Number of records processed by NBA processors" \
  --metric-kind=GAUGE \
  --value-type=INT64 \
  --labels="processor:Name of the processor,status:Success or failure status"

# Report generation metrics
gcloud monitoring metrics-descriptors create \
  --type="custom.googleapis.com/nba/reports_generated" \
  --description="Number of reports generated" \
  --metric-kind=GAUGE \
  --value-type=INT64 \
  --labels="report_type:Type of report,status:Success or failure status"

echo "✅ Custom metrics created"

# Create alert policies
echo "Creating alert policies..."

# High error rate alert
cat << EOF > /tmp/high_error_rate_policy.yaml
displayName: "NBA Platform - High Error Rate"
documentation:
  content: "Error rate for NBA platform services is above 5%"
conditions:
  - displayName: "High error rate condition"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND resource.labels.service_name=~"nba-.*"'
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_RATE
          crossSeriesReducer: REDUCE_SUM
          groupByFields:
            - resource.labels.service_name
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 0.05
      duration: 300s
notificationChannels:
  - $NOTIFICATION_CHANNEL
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/high_error_rate_policy.yaml

# Scraper failure alert
cat << EOF > /tmp/scraper_failure_policy.yaml
displayName: "NBA Platform - Scraper Failures"
documentation:
  content: "NBA scraper has failed multiple times"
conditions:
  - displayName: "Scraper failure condition"
    conditionThreshold:
      filter: 'metric.type="custom.googleapis.com/nba/scraper_runs_total" AND metric.labels.status="failure"'
      aggregations:
        - alignmentPeriod: 600s
          perSeriesAligner: ALIGN_RATE
          crossSeriesReducer: REDUCE_SUM
          groupByFields:
            - metric.labels.scraper
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 2
      duration: 300s
notificationChannels:
  - $NOTIFICATION_CHANNEL
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/scraper_failure_policy.yaml

# High memory usage alert
cat << EOF > /tmp/high_memory_policy.yaml
displayName: "NBA Platform - High Memory Usage"
documentation:
  content: "Memory usage is above 80% for NBA services"
conditions:
  - displayName: "High memory condition"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND resource.labels.service_name=~"nba-.*" AND metric.type="run.googleapis.com/container/memory/utilizations"'
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_MEAN
          crossSeriesReducer: REDUCE_MEAN
          groupByFields:
            - resource.labels.service_name
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 0.8
      duration: 600s
notificationChannels:
  - $NOTIFICATION_CHANNEL
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/high_memory_policy.yaml

# High CPU usage alert (P1-15: Added infrastructure monitoring)
cat << EOF > /tmp/high_cpu_policy.yaml
displayName: "NBA Platform - High CPU Usage"
documentation:
  content: "CPU usage is above 80% for NBA services"
conditions:
  - displayName: "High CPU condition"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND resource.labels.service_name=~"nba-.*" AND metric.type="run.googleapis.com/container/cpu/utilizations"'
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_MEAN
          crossSeriesReducer: REDUCE_MEAN
          groupByFields:
            - resource.labels.service_name
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 0.8
      duration: 600s
notificationChannels:
  - $NOTIFICATION_CHANNEL
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/high_cpu_policy.yaml

# Instance count alert (track scaling issues)
cat << EOF > /tmp/instance_count_policy.yaml
displayName: "NBA Platform - High Instance Count"
documentation:
  content: "Instance count is unusually high, may indicate scaling issues or stuck requests"
conditions:
  - displayName: "High instance count condition"
    conditionThreshold:
      filter: 'resource.type="cloud_run_revision" AND resource.labels.service_name=~"nba-.*" AND metric.type="run.googleapis.com/container/instance_count"'
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_MAX
          crossSeriesReducer: REDUCE_SUM
          groupByFields:
            - resource.labels.service_name
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 20
      duration: 300s
notificationChannels:
  - $NOTIFICATION_CHANNEL
EOF

gcloud alpha monitoring policies create --policy-from-file=/tmp/instance_count_policy.yaml

echo "✅ Alert policies created"

# Import dashboard
echo "Creating dashboard..."
if [[ -f "monitoring/dashboards/nba_scrapers_dashboard.json" ]]; then
    gcloud monitoring dashboards create --config-from-file=monitoring/dashboards/nba_scrapers_dashboard.json
    echo "✅ Dashboard created"
else
    echo "⚠️ Dashboard file not found, skipping dashboard creation"
fi

# Create uptime checks
echo "Creating uptime checks..."

# Get service URLs
SCRAPERS_URL=$(gcloud run services describe nba-scraper-events --region=us-central1 --format="value(status.url)" 2>/dev/null || echo "")
PROCESSORS_URL=$(gcloud run services describe nba-processor-events --region=us-central1 --format="value(status.url)" 2>/dev/null || echo "")

if [[ -n "$SCRAPERS_URL" ]]; then
    gcloud monitoring uptime create \
      --display-name="NBA Scrapers Health Check" \
      --http-check-path="/health" \
      --hostname="$(echo $SCRAPERS_URL | sed 's|https://||')" \
      --port=443 \
      --use-ssl
    echo "✅ Scrapers uptime check created"
fi

if [[ -n "$PROCESSORS_URL" ]]; then
    gcloud monitoring uptime create \
      --display-name="NBA Processors Health Check" \
      --http-check-path="/health" \
      --hostname="$(echo $PROCESSORS_URL | sed 's|https://||')" \
      --port=443 \
      --use-ssl
    echo "✅ Processors uptime check created"
fi

# Clean up temp files
rm -f /tmp/*_policy.yaml

echo ""
echo "🎉 Monitoring setup complete!"
echo ""
echo "Dashboard: https://console.cloud.google.com/monitoring/dashboards"
echo "Alerts: https://console.cloud.google.com/monitoring/alerting"
echo "Uptime checks: https://console.cloud.google.com/monitoring/uptime"
echo ""
echo "You will receive email alerts at: $NOTIFICATION_EMAIL"
