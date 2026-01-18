# First Automatic Run - Checklist

**Date:** 2026-01-18 (Tonight at 7 PM ET)
**Purpose:** Verify new monitoring system works correctly

---

## Tonight at 7:00 PM ET

### What Will Happen Automatically

1. Cloud Scheduler triggers `missing-prediction-check`
2. Calls `check-missing` Cloud Function
3. Analyzes prediction coverage for tomorrow's games
4. Sends Slack alert if ANY players missing

---

## Quick Verification (2 minutes)

### 1. Check Slack Channel
- Look in channel configured via `slack-webhook-monitoring-error` secret
- Alert starts with: **"🚨 MISSING PREDICTIONS ALERT"**
- Should include player names if any missing

### 2. Check Scheduler Executed
```bash
gcloud logging read 'resource.type="cloud_scheduler_job" AND
  resource.labels.job_id="missing-prediction-check"' \
  --limit=1 --format=json | jq -r '.[0].timestamp'
```
**Expected:** Timestamp around 7:00 PM ET (00:00 UTC)

### 3. Test Function Response
```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date -d tomorrow +%Y-%m-%d)" | jq .
```
**Expected:** JSON with `missing_count`, `alert_sent`, `coverage_percent`

---

## Expected Results

### ✅ All Good (≥95% coverage)
- **Slack:** No alert OR small alert (0-3 missing)
- **Scheduler:** HTTP 200 (success)
- **Function:** `{"missing_count": 0-3, "alert_sent": true/false}`

### ⚠️ Issues Found (>5% missing)
- **Slack:** CRITICAL alert with player names
- **Scheduler:** HTTP 200 (success)
- **Function:** `{"missing_count": >3, "alert_sent": true}`
- **Action:** Investigate using commands below

---

## If Alert Triggered

### 1. View Missing Players
```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date -d tomorrow +%Y-%m-%d)" | \
  jq '.missing_players[] | {player: .player_lookup, line: .current_points_line, team: .team_abbr}'
```

### 2. Check Phase 3 Data Freshness
```bash
bq query --nouse_legacy_sql "
SELECT
  MAX(created_at) as last_run,
  COUNT(*) as total_players,
  COUNTIF(current_points_line IS NOT NULL) as players_with_lines
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
"
```

### 3. Check Predictions Generated
```bash
bq query --nouse_legacy_sql "
SELECT
  COUNT(DISTINCT player_lookup) as predicted_players,
  MIN(created_at) as first_prediction,
  MAX(created_at) as last_prediction
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE DATE(game_date) = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
"
```

### 4. Review Troubleshooting Guide
```bash
cat docs/09-handoff/MONITORING-VALIDATION-GUIDE.md
```

---

## What to Document

Record the following:
- [ ] **Coverage %:** _____
- [ ] **Missing count:** _____
- [ ] **Alert sent:** Yes / No
- [ ] **Slack channel received:** Yes / No
- [ ] **Any issues:** _____________________

**Save to:** Session notes or create follow-up issue

---

## Important Notes

### This is the FIRST automatic run!

**If you get an alert:**
- ✅ System is working correctly
- Check if it's expected (Phase 3 timing issue from today)

**If you DON'T get an alert by 7:05 PM ET:**
- Either coverage is perfect (great!)
- OR system isn't working (check logs)
- Run manual verification above

---

## Next Checks

**Tomorrow 9:00 AM ET:**
- `daily-reconciliation` runs
- Full pipeline validation
- Reports PASS/FAIL status

**Tomorrow 5:45 PM ET:**
- `validate-freshness-check` runs
- Validates data before predictions
- Blocks if stale

---

## Quick Health Check Command

Copy-paste this for instant status:

```bash
echo "=== Monitoring System Status ===" && \
echo "" && \
echo "1. Schedulers:" && \
gcloud scheduler jobs list --location=us-west2 --format="table(name,state)" | grep -E "validate-freshness|missing-prediction|daily-reconciliation" && \
echo "" && \
echo "2. Tonight's Coverage:" && \
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date -d tomorrow +%Y-%m-%d)" | jq '{missing: .missing_count, coverage: .summary.coverage_percent, alert_sent: .alert_sent}' && \
echo "" && \
echo "=== Status Check Complete ==="
```

---

**Good luck with the first run!** 🚀

The monitoring system you built today will help catch issues before they become problems.
