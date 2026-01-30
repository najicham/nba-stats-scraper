# Session 30 Takeover Prompt

Copy this entire prompt to a new Claude Code chat:

---

## Context

Continue work on NBA stats scraper pipeline. Session 29 just completed critical bug fixes that were deployed but NOT YET TESTED.

**Read the handoff documents first:**
```bash
cat docs/09-handoff/2026-01-30-SESSION-29-HANDOFF.md
cat CLAUDE.md
```

## What Was Fixed (Session 29)

Two critical bugs were fixed and deployed to `nba-scrapers` service:

1. **workflow_executor.py line 252**: Missing `f` prefix on query string caused literal `{self.project_id}` to be passed to BigQuery, breaking all scraper orchestration with "Invalid project ID '{self'" errors

2. **change_detector.py lines 240, 265**: Wrong table name `nbac_player_boxscore` changed to `bdl_player_boxscores`

**Deployment:** `nba-scrapers-00109-ghp` (commit `f08a5f0c`) deployed at 08:34 UTC

## PRIORITY 1: Validate the Fix Works

The fix has NOT been tested yet. The `execute-workflows` job runs at :05 each hour.

**Run these checks after 9:10 AM ET:**

```bash
# 1. Check for the old error (should be GONE)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload:"Invalid project ID"' --limit=5 --format="table(timestamp,textPayload)"

# 2. Check workflow executions are succeeding
bq query --use_legacy_sql=false "
SELECT workflow_name, status, scrapers_succeeded, scrapers_failed, execution_time
FROM nba_orchestration.workflow_executions
WHERE DATE(execution_time) = CURRENT_DATE()
ORDER BY execution_time DESC LIMIT 10"

# 3. Run full daily validation
/validate-daily
```

**Expected results:**
- ✅ No "Invalid project ID '{self'" errors after 9:05 AM
- ✅ Workflow executions showing `status = 'completed'`
- ✅ Scrapers collecting data

## PRIORITY 2: Backfill Missing Data

**Jan 29 has NO box score data** because the scraper was broken. Once you verify scrapers work:

```bash
# Check if Jan 29 data exists now
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2026-01-29'
GROUP BY 1 ORDER BY 1"

# If Jan 29 still missing, trigger manual backfill
# (find the appropriate backfill script or manually trigger scraper)
```

## PRIORITY 3: Verify Today's Pipeline Completes

| Time (ET) | Event | Expected |
|-----------|-------|----------|
| 10:30 AM | same-day-phase3 | 5/5 processors complete |
| 11:00 AM | same-day-phase4 | Feature store populated |
| 11:30 AM | same-day-predictions | ~200-300 predictions for 8 games |

```bash
# Check Phase 3 completion
python3 -c "
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
doc = db.collection('phase3_completion').document(datetime.now().strftime('%Y-%m-%d')).get()
if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    print(f'Phase 3: {len(completed)}/5')
    for p in sorted(completed): print(f'  ✅ {p}')
"

# Check predictions
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

## PRIORITY 4: Monitoring Improvements

Session 29 identified these monitoring gaps:

### 4A. Enable Slack Alerts
Currently `SLACK_ALERTS_ENABLED=false` by default. To enable:
```bash
# Check current env vars
gcloud run services describe nba-scrapers --region=us-west2 --format="yaml" | grep -A50 "env:"

# Add SLACK_ALERTS_ENABLED=true (requires redeploy or env update)
```

### 4B. Add "Zero Workflows" Alert
No alert fires when `execute-workflows` finds no pending decisions. This could mask issues.

**Recommended:** Add a check in `workflow_executor.py` to send a warning if 0 workflows executed during expected game hours.

### 4C. Add Morning Health Check Job
There's a 7 AM Slack summary but no automated 8 AM health check. Consider scheduling:
```bash
gcloud scheduler jobs create http morning-health-check-8am \
  --location=us-west2 \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-scrapers-xxx.run.app/health-check-full" \
  --http-method=POST
```

## PRIORITY 5: Other Known Issues

### 5A. Player Name Normalization (P2)
15-20% gap between analytics and cache due to lookup inconsistencies.
- Examples: `boneshyland` vs `nahshonhyland`
- Need canonical lookup table

### 5B. Another Chat Handling Prediction Regeneration
Jan 9-28 predictions need regeneration due to feature store bug that was fixed.
- Don't duplicate this work
- Check if it's complete

## Key Files Reference

| File | Purpose |
|------|---------|
| `orchestration/workflow_executor.py` | Scraper execution orchestration (FIXED) |
| `shared/change_detection/change_detector.py` | Smart reprocessing detection (FIXED) |
| `docs/09-handoff/2026-01-30-SESSION-29-HANDOFF.md` | Full session 29 details |
| `bin/monitoring/daily_health_check.sh` | Manual health check script |

## Quick Commands

```bash
# Daily validation skill
/validate-daily

# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Trigger Phase 3 manually
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Check recent errors
gcloud logging read 'severity>=ERROR AND resource.labels.service_name="nba-scrapers"' --limit=20

# Check workflow decisions
bq query --use_legacy_sql=false "
SELECT workflow_name, action, decision_time
FROM nba_orchestration.workflow_decisions
WHERE DATE(decision_time) = CURRENT_DATE()
ORDER BY decision_time DESC LIMIT 10"
```

## Success Criteria

By end of session, confirm:
- [ ] No more "Invalid project ID" errors in logs
- [ ] Workflow executions completing successfully
- [ ] Phase 3 reaching 5/5 completion
- [ ] Today's predictions generated (if after 12 PM ET)
- [ ] Jan 29 data backfilled or plan in place
- [ ] At least one monitoring improvement implemented

---

**Start by running `/validate-daily` to check current pipeline health.**
