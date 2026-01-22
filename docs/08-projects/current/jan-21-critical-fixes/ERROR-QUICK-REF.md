# 🚨 Error Investigation Quick Reference

**For detailed guide:** See `/docs/ERROR-LOGGING-GUIDE.md`

---

## 🎯 Start Here

| I need to... | Command |
|--------------|---------|
| **Check recent errors** | `gcloud logging read 'severity>=ERROR' --limit=50 --freshness=24h` |
| **Check yesterday's data** | `python scripts/check_30day_completeness.py --days 1` |
| **Check scraper failures** | `bq query --use_legacy_sql=false 'SELECT scraper_name, error_type, COUNT(*) as count FROM nba_orchestration.scraper_execution_log WHERE status = "failed" AND DATE(created_at) >= CURRENT_DATE() - 7 GROUP BY scraper_name, error_type ORDER BY count DESC'` |
| **Check service health** | `gcloud run services list --region us-west2 --filter="metadata.name:nba-phase"` |
| **Check API errors** | `python bin/operations/query_api_errors.py --days 7` (once deployed) |
| **Run daily health check** | `./bin/validation/daily_data_quality_check.sh` |

---

## 📍 Where Errors Are Logged

| Error Type | Location | Access Method |
|------------|----------|---------------|
| **API/Scraper Errors** | `nba_orchestration.api_errors` | `python bin/operations/query_api_errors.py` |
| **Pipeline Failures** | `nba_orchestration.scraper_execution_log` | BigQuery query |
| **Data Validation** | `nba_orchestration.scraper_output_validation` | BigQuery query |
| **Cloud Function Errors** | Google Cloud Logging | `gcloud logging read` |
| **Service Crashes** | Cloud Run logs | `gcloud logging read 'resource.type=cloud_run_revision'` |
| **Orchestration State** | Firestore `phase*_completion` | Python Firestore client |
| **Pub/Sub Failures** | Dead Letter Queues | `gcloud pubsub subscriptions pull *-dlq` |
| **Exceptions** | Sentry.io | Web dashboard |

---

## 🔥 Common Issues & Quick Fixes

### "Data missing for yesterday"
```bash
# 1. Check if scrapers ran
bq query --use_legacy_sql=false "SELECT scraper_name, status, COUNT(*) FROM nba_orchestration.scraper_execution_log WHERE DATE(created_at) = CURRENT_DATE() - 1 GROUP BY scraper_name, status"

# 2. Check for errors
gcloud logging read 'severity>=ERROR timestamp>="'$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)'"' --limit=100

# 3. Run backfill if needed
./bin/run_backfill.sh raw/bdl_boxscores --dates=$(date -d '1 day ago' +%Y-%m-%d)
```

### "Predictions not generating"
```bash
# Check prediction pipeline
gcloud logging read 'resource.labels.service_name=~"prediction" severity>=ERROR' --limit=50 --freshness=24h

# Check recent predictions
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 7 AND is_active = TRUE GROUP BY game_date ORDER BY game_date DESC"
```

### "Service crashing"
```bash
# Check service errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" severity>=ERROR' --limit=50 --freshness=24h

# Check recent deployments
gcloud run services describe nba-phase3-analytics-processors --region us-west2 --format="value(status.latestReadyRevisionName,metadata.labels)"
```

---

## 📚 Documentation

- **Full Error Guide:** `/docs/ERROR-LOGGING-GUIDE.md`
- **API Error Logging:** `/docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md`
- **Recent Root Cause Analysis:** `/docs/08-projects/current/week-1-improvements/ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md`
- **Validation Guide:** `/validation/VALIDATOR_QUICK_REFERENCE.md`
- **Data Completeness Reports:** `/COMPLETENESS-CHECK-SUMMARY.txt`, `/DATA-COMPLETENESS-REPORT-JAN-21-2026.md`

---

## 🆘 Emergency Contacts

**Investigation Reports Location:** `/docs/08-projects/current/week-1-improvements/`

**Recent Investigation Files:**
- `ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md` - Comprehensive analysis of Jan 15-21 data gaps
- `ERROR-SCAN-JAN-15-21-2026.md` - Detailed error scan results
- `API-ERROR-LOGGING-PROPOSAL.md` - Proposed structured error logging system

---

**Last Updated:** January 21, 2026
