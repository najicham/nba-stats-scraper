# Session 13C Deployment Guide

**Date:** January 12, 2026
**Session:** 13C - Reliability Improvements

---

## Summary of Changes

Three reliability improvements were implemented:

| Component | Change | Impact |
|-----------|--------|--------|
| `grading_alert/` | **New Function** | Alerts if no grading by 10 AM ET |
| `self_heal/main.py` | **Extended** | Now checks Phase 3 data exists |
| `live_freshness_monitor/main.py` | **Enhanced** | Added 4-hour critical alert |

---

## Deployment Commands

### 1. Grading Delay Alert (NEW)

```bash
# Deploy the function
gcloud functions deploy grading-delay-alert \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source orchestration/cloud_functions/grading_alert \
    --entry-point check_grading_status \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<YOUR_WEBHOOK>

# Create scheduler job (10 AM ET daily)
gcloud scheduler jobs create http grading-delay-alert-job \
    --schedule "0 10 * * *" \
    --time-zone "America/New_York" \
    --uri "https://us-west2-nba-props-platform.cloudfunctions.net/grading-delay-alert" \
    --http-method GET \
    --location us-west2
```

### 2. Self-Heal with Phase 3 Checking (REDEPLOY)

```bash
gcloud functions deploy self-heal-check \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source orchestration/cloud_functions/self_heal \
    --entry-point self_heal_check \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT=nba-props-platform
```

### 3. Live Freshness Monitor with 4-Hour Alert (REDEPLOY)

```bash
gcloud functions deploy live-freshness-monitor \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source orchestration/cloud_functions/live_freshness_monitor \
    --entry-point main \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<YOUR_WEBHOOK>
```

---

## Testing Commands

### Test Grading Alert (dry run)
```bash
curl "https://us-west2-nba-props-platform.cloudfunctions.net/grading-delay-alert?dry_run=true"
```

### Test Self-Heal
```bash
curl "https://us-west2-nba-props-platform.cloudfunctions.net/self-heal-check"
```

### Test Live Freshness Monitor
```bash
curl "https://us-west2-nba-props-platform.cloudfunctions.net/live-freshness-monitor"
```

---

## Files Modified/Created

| File | Type | Description |
|------|------|-------------|
| `orchestration/cloud_functions/grading_alert/main.py` | NEW | Grading delay alert function |
| `orchestration/cloud_functions/grading_alert/requirements.txt` | NEW | Dependencies |
| `orchestration/cloud_functions/self_heal/main.py` | MODIFIED | Added Phase 3 checking |
| `orchestration/cloud_functions/live_freshness_monitor/main.py` | MODIFIED | Added 4-hour critical alert |
| `docs/08-projects/.../MASTER-TODO.md` | MODIFIED | Session 13C progress |
| `docs/08-projects/.../TODO.md` | MODIFIED | Session 13C completed |

---

## Alert Behavior

### Grading Delay Alert (10 AM ET)
- **CRITICAL**: Games played + predictions existed + 0 grading records
- **WARNING**: Games played + 0 predictions existed
- **OK**: No games, or grading records exist

### Self-Heal Phase 3 Check (12:45 PM ET)
- Checks if `player_game_summary` exists for yesterday
- If missing but games were played, triggers Phase 3
- Then continues with normal predictions check

### Live Freshness Monitor (every 5 min during games)
- **WARNING**: Data > 10 minutes old (triggers auto-refresh)
- **CRITICAL**: Data > 4 hours old (sends Slack alert immediately)
- Only checks during game hours (4 PM - 1 AM ET)

---

## Slack Webhook Setup

All functions need `SLACK_WEBHOOK_URL` environment variable for alerting:

1. Create webhook in Slack workspace settings
2. Set as environment variable during deployment
3. Or add to Secret Manager and reference

---

## Verification Checklist

After deployment, verify:

- [ ] Grading alert function responds to health check
- [ ] Grading alert scheduler job created and enabled
- [ ] Self-heal shows Phase 3 check in response JSON
- [ ] Live freshness monitor includes `critical_alert` field when stale

---

## Rollback

If issues occur, redeploy from previous version:

```bash
# List revisions
gcloud run revisions list --service=<service-name> --region=us-west2

# Route traffic to previous revision
gcloud run services update-traffic <service-name> \
    --to-revisions=<previous-revision>=100 \
    --region=us-west2
```
