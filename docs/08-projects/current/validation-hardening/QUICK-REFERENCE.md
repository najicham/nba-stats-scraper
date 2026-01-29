# Validation Hardening - Quick Reference

Fast reference guide for the new validation tools added in Session 8.

## Commands

### Morning Health Check (NEW)
```bash
# Run for yesterday's games (default)
./bin/monitoring/morning_health_check.sh

# Run for specific date
./bin/monitoring/morning_health_check.sh 2026-01-27
```

**When to use:** Every morning to quickly check overnight processing health
**Time:** < 30 seconds
**Output:** Color-coded summary with clear action items

### Pre-Flight Checks (NEW)
```bash
# Check if tonight's data is ready
python scripts/validate_tonight_data.py --pre-flight

# Check specific future date
python scripts/validate_tonight_data.py --pre-flight --date 2026-01-29
```

**When to use:** At 5 PM ET before games start
**Time:** ~30-45 seconds
**Checks:** Betting data, game context, ML features, worker health

### Full Validation
```bash
# Validate tonight's data
python scripts/validate_tonight_data.py

# Validate specific date
python scripts/validate_tonight_data.py --date 2026-01-27
```

**When to use:** When morning dashboard shows issues or comprehensive check needed
**Time:** ~60-90 seconds
**Checks:** All phases, data quality, spot checks

## Daily Workflow

### Morning (6-8 AM ET)
```bash
# 1. Quick health check
./bin/monitoring/morning_health_check.sh

# 2. If issues found, investigate
python scripts/validate_tonight_data.py --date $(date -d "yesterday" +%Y-%m-%d)

# 3. Check logs if needed
gcloud run services logs read SERVICE_NAME --limit=50
```

### Pre-Game (5 PM ET)
```bash
# Verify readiness for tonight
python scripts/validate_tonight_data.py --pre-flight
```

## Interpreting Results

### Morning Health Check Output

**✅ Green = OK**
- Metrics within acceptable range
- Phases completed successfully
- No action needed

**⚠️ Yellow = WARNING**
- Metrics below optimal but acceptable
- Some processors incomplete
- Monitor but not critical

**❌ Red = CRITICAL**
- Metrics below minimum threshold
- Major processing failures
- Immediate action required

### Threshold Quick Reference

| Metric | OK | WARNING | CRITICAL |
|--------|------|---------|----------|
| Minutes Coverage | ≥90% | 80-89% | <80% |
| Usage Rate | ≥90% | 80-89% | <80% |
| Phase 3 Processors | 5/5 | 3-4/5 | 0-2/5 |
| Predictions | > 0 | 0 (off-day) | 0 (game day) |

## Slack Alerts

### Channels
- **#app-error-alerts** - CRITICAL issues only (red alert)
- **#nba-alerts** - Warnings (yellow alert)
- **#daily-orchestration** - Daily summary (all statuses)

### Alert Response
When you receive a critical alert:

1. **Check Slack message** - shows specific issue
2. **Run morning dashboard** - full context
3. **Read recent handoff docs** - check for known issues
4. **Fix root cause** - don't just restart
5. **Verify fix** - re-run validation

## Common Issues

### 1. Low Minutes Coverage (<80%)
**Symptom:** Minutes coverage 63.2% CRITICAL
**Likely Cause:** BDL scraper extraction bug or source data issue
**Action:**
```bash
# Check raw data
bq query "SELECT minutes, COUNT(*) FROM nba_raw.bdl_player_boxscores WHERE game_date = 'YYYY-MM-DD' GROUP BY 1"

# Check processor logs
gcloud run services logs read nba-phase3-analytics-processors --limit=100
```

### 2. Phase 3 Incomplete (2/5)
**Symptom:** Processors complete: 2/5 CRITICAL
**Likely Cause:** Processor failure or timeout
**Action:**
```bash
# Check Firestore
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('YYYY-MM-DD').get()
print(doc.to_dict())
EOF

# Check which processors failed
gcloud run services logs read nba-phase3-analytics-processors --limit=50 | grep ERROR
```

### 3. No Predictions
**Symptom:** Phase 5: ❌ No predictions
**Likely Cause:** Phase 4 didn't complete or prediction worker down
**Action:**
```bash
# Check Phase 4 features
bq query "SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = 'YYYY-MM-DD'"

# Check prediction worker
curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health
```

## Exit Codes

All scripts follow standard exit code convention:
- **0** = Success, all checks passed
- **1** = Issues found (check output for details)

**Example usage in automation:**
```bash
#!/bin/bash
if ./bin/monitoring/morning_health_check.sh; then
    echo "All systems healthy"
else
    echo "Issues detected - check Slack"
    # Send additional alerts or trigger fixes
fi
```

## Environment Setup

### Required Environment Variables
```bash
# For Slack alerting
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."  # #daily-orchestration
export SLACK_WEBHOOK_URL_ERROR="https://hooks.slack.com/..."  # #app-error-alerts
export SLACK_WEBHOOK_URL_WARNING="https://hooks.slack.com/..."  # #nba-alerts

# For BigQuery
export GOOGLE_CLOUD_PROJECT="nba-props-platform"
```

### Required Permissions
- BigQuery Data Viewer (for queries)
- Cloud Run Viewer (for health checks)
- Firestore Viewer (for phase completion)
- Logging Viewer (for error checks)

## Automation

### Cloud Scheduler (Recommended)
```bash
# Schedule morning health check
gcloud scheduler jobs create http morning-health-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://daily-health-check-XXXXX.cloudfunctions.net/daily_health_check" \
  --http-method=POST

# Schedule pre-flight check
gcloud scheduler jobs create http pre-flight-check \
  --schedule="0 17 * * *" \
  --time-zone="America/New_York" \
  --uri="https://pre-flight-check-XXXXX.cloudfunctions.net/check" \
  --http-method=POST
```

### Cron (Alternative)
```cron
# Morning health check at 8 AM ET
0 13 * * * cd /path/to/nba-stats-scraper && ./bin/monitoring/morning_health_check.sh

# Pre-flight check at 5 PM ET
0 22 * * * cd /path/to/nba-stats-scraper && python scripts/validate_tonight_data.py --pre-flight
```

## Troubleshooting

### Script Won't Run
```bash
# Make executable
chmod +x bin/monitoring/morning_health_check.sh

# Check Python path
which python3

# Verify BigQuery access
bq ls nba_analytics
```

### No Output
```bash
# Run with debug
bash -x ./bin/monitoring/morning_health_check.sh

# Check for errors
./bin/monitoring/morning_health_check.sh 2>&1 | tee health_check.log
```

### Slow Performance
- Check BigQuery quota usage
- Verify network connectivity to GCP
- Consider caching results locally

## Related Documentation

- **Full Documentation:** `docs/08-projects/current/validation-hardening/README.md`
- **Handoff Document:** `docs/09-handoff/2026-01-28-SESSION-8-WORKSTREAM-1-VALIDATION.md`
- **SKILL Guide:** `.claude/skills/validate-daily/SKILL.md`
- **Slack Setup:** `shared/utils/slack_channels.py`

---

**Last Updated:** 2026-01-28
