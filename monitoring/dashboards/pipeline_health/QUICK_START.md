# Pipeline Health Dashboard - Quick Start Guide

## 🚀 Deploy in 3 Steps (10 minutes)

### Step 1: Deploy Views
```bash
cd /home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_health
./deploy_views.sh
```

### Step 2: Set Up Scheduled Queries
```bash
./scheduled_queries_setup.sh
```

### Step 3: Import Dashboard
```bash
gcloud monitoring dashboards create \
  --config-from-file=pipeline_health_dashboard.json \
  --project=nba-props-platform
```

## ✅ Verify Deployment

```bash
# Check views exist
bq ls nba-props-platform:nba_monitoring

# Test query
bq query --use_legacy_sql=false \
  "SELECT * FROM \`nba-props-platform.nba_monitoring.pipeline_health_summary\` LIMIT 5"

# View dashboard
# Go to: https://console.cloud.google.com/monitoring/dashboards
```

## 📊 Dashboard URL

After deployment:
1. Go to: https://console.cloud.google.com/monitoring/dashboards
2. Find: "NBA Pipeline Health Dashboard"
3. Bookmark for easy access

## 🔍 Key Metrics to Monitor

### Phase Completion Rates
- **Green (≥90%)**: Healthy
- **Yellow (75-89%)**: Warning
- **Red (<75%)**: Critical

### Error Counts
- Watch for CRITICAL priority errors
- Check retry success rates
- Monitor persistent failures

### Prediction Coverage
- Target: ≥90% coverage
- Track 7-day trends
- Investigate gaps

### Pipeline Latency
- Target: <3 hours total
- Identify bottleneck phases
- Monitor degradation

## 🚨 Common Alerts

### Low Completion Rate
```
Phase 3 completion < 75% for 2 hours
→ Check processor_error_summary for failing processors
```

### Coverage Degradation
```
Coverage < 80% for 2 days
→ Check prediction_coverage_metrics for gap reasons
```

### High Latency
```
Total latency > 6 hours
→ Check pipeline_latency_metrics for bottleneck phase
```

## 📖 Documentation

- **Full README**: `README.md`
- **Deployment Guide**: `DEPLOYMENT_GUIDE.md`
- **Implementation Summary**: `SUMMARY.md`

## 💡 Quick Queries

### Current Health Status
```sql
SELECT phase_name, completion_percentage, failure_rate
FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
WHERE time_window = 'last_24h'
ORDER BY completion_percentage;
```

### Critical Errors
```sql
SELECT processor_name, error_count, top_error_message
FROM `nba-props-platform.nba_monitoring.processor_error_summary`
WHERE time_window = 'last_24h' AND alert_priority = 'CRITICAL'
ORDER BY error_count DESC;
```

### Today's Coverage
```sql
SELECT coverage_percentage, coverage_gap_count, health_status
FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
WHERE game_date = CURRENT_DATE();
```

## 🛠️ Troubleshooting

### No Data in Views?
```bash
# Check source tables
bq query "SELECT COUNT(*) FROM \`nba-props-platform.nba_reference.processor_run_history\` WHERE data_date >= CURRENT_DATE() - 7"
```

### Scheduled Queries Not Running?
```bash
# List and check status
bq ls --transfer_config --project_id=nba-props-platform
```

### Dashboard Shows Errors?
- Wait 5-10 minutes for first data points
- Verify views return data
- Check custom metrics are being exported

## 📧 Support

- **Slack**: #data-engineering
- **Email**: data-team@company.com
- **Docs**: See README.md for full documentation

## ⚡ Pro Tips

1. **Bookmark the dashboard** for daily monitoring
2. **Set up Slack alerts** for critical errors
3. **Review weekly** to identify trends
4. **Use materialized tables** for faster queries
5. **Monitor costs** in BigQuery console

---

**Ready to deploy?** → Start with Step 1 above!
