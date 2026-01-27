# Data Quality Monitoring - Quick Reference

**Last Updated:** 2026-01-27

## Alert Types

| Alert | Severity | Trigger | Channel |
|-------|----------|---------|---------|
| Zero Predictions | P0 | 0 predictions when games scheduled | #app-error-alerts |
| Low Usage Rate | P1 | < 80% coverage after games complete | #nba-alerts |
| Missing Prop Lines | P1 | < 50% players have betting lines | #nba-alerts |
| Duplicates | P2 | > 20 duplicate (player, game) records | #nba-alerts |

## Quick Commands

### Deploy Cloud Function
```bash
cd orchestration/cloud_functions/data_quality_alerts
./deploy.sh prod
```

### Test with Known Issues (2026-01-26)
```bash
# Dry run (no alerts)
curl "$FUNCTION_URL?game_date=2026-01-26&dry_run=true"

# Real alerts
curl "$FUNCTION_URL?game_date=2026-01-26"
```

### Test SQL Queries
```bash
cd monitoring/queries
./test_queries.sh 2026-01-26
```

### Check Function Status
```bash
# View logs
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 20

# Describe function
gcloud functions describe data-quality-alerts --gen2 --region us-west2
```

### Trigger Scheduler Manually
```bash
gcloud scheduler jobs run data-quality-alerts-job --location=us-west2
```

## When You Receive an Alert

### CRITICAL: Zero Predictions
1. Check coordinator logs:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-coordinator-prod" --limit 50
   ```
2. Verify Phase 3 timing vs props scraper
3. Check upcoming_player_game_context for has_prop_line values
4. Manual fix: Re-run Phase 3, then trigger coordinator

### WARNING: Low Usage Rate
1. Check if games recently finished (< 2 hours ago) - may be acceptable
2. If > 2 hours, check BDL boxscore processor logs
3. Verify boxscores are complete in GCS: `gs://nba-scraped-data/balldontlie/box-scores/`
4. Re-run Phase 2 if boxscores were incomplete

### WARNING: Duplicates
1. Check processor logs for multiple runs
2. Review deduplication logic
3. Check Pub/Sub for duplicate messages
4. If CRITICAL: Run deduplication script

### CRITICAL: Missing Prop Lines
1. Check timing: Did props scraper run before Phase 3?
2. If props arrived late:
   ```bash
   gcloud scheduler jobs run phase3-trigger --location=us-west2
   ```
3. Monitor Phase 3 completion
4. Verify has_prop_line = TRUE in upcoming_player_game_context

## File Locations

- **Queries:** `/home/naji/code/nba-stats-scraper/monitoring/queries/`
- **Function:** `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/`
- **Docs:** `/home/naji/code/nba-stats-scraper/docs/08-projects/current/2026-01-27-data-quality-investigation/`

## Key Metrics

- **Detection Time:** < 1 hour (target)
- **False Positive Rate:** < 10% (target)
- **Cost:** ~$2/year
- **Schedule:** Daily at 7 PM ET

## Environment Variables

Required for deployment:
- `SLACK_WEBHOOK_URL_ERROR` - #app-error-alerts webhook
- `SLACK_WEBHOOK_URL_WARNING` - #nba-alerts webhook
- `GCP_PROJECT_ID` - nba-props-platform

## Function URL

Get URL:
```bash
gcloud functions describe data-quality-alerts --gen2 --region us-west2 --format="value(serviceConfig.uri)"
```

## Related Systems

- **Existing Prediction Health Alert:** `orchestration/cloud_functions/prediction_health_alert/`
- **Existing Daily Health Summary:** `orchestration/cloud_functions/daily_health_summary/`
- **Notification System:** `shared/utils/notification_system.py`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Queries timeout | Check BigQuery quota, optimize queries |
| Alerts not sent | Verify Slack webhooks in env vars |
| False positives | Adjust thresholds in main.py |
| Function errors | Check logs, verify BigQuery permissions |

## Support

- **Documentation:** See MONITORING-PLAN.md for full details
- **Logs:** `gcloud functions logs read data-quality-alerts --gen2 --region us-west2`
- **Monitoring Dashboard:** (TBD - future enhancement)

---

**This is a living document. Update as system evolves.**
