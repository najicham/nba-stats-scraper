# Session 94 Start Prompt

## Context

Session 93 (Opus) investigated Slack alerts about "Auth Errors" and HTTP 400s. Found they were actually instance availability issues and transient scraper errors during late-night game processing. Applied fixes.

## What Was Done (Session 93)

1. **Increased Phase 2 max instances** from 5 to 10
2. **Created late-night schedule fix scheduler** (hourly 1-6 AM ET)
3. **Fixed execution logger NULL bug** in prediction-worker (deployed)
4. **Documented everything** in handoff doc

## Commits

```
b3e4a53b - docs: Add Session 93 handoff - alert investigation
41bc42f4 - fix: Prevent BigQuery NULL errors in execution logger and add overnight schedule fix
```

## What Needs Verification

### 1. Game Statuses Should Be Fixed Now

The new hourly scheduler (`fix-stale-schedule-late-night`) should have run at 1 AM ET. Verify Feb 2 games are now Final:

```bash
bq query --use_legacy_sql=false "
SELECT game_id,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END as status
FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-02'"
```

**Expected:** All 4 games should show `Final`

### 2. Check for Recurring Alerts

Monitor Slack for any new "Auth Errors" alerts. They should be less frequent now with increased instance capacity.

### 3. Verify Prediction Worker Fix

Check that no NULL-related BigQuery errors appear in prediction-worker logs:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"NULL|line_values_requested"' --limit=10 --freshness=6h
```

**Expected:** No errors (or only old ones from before deployment)

## Known Issues (Not Bugs)

- **Email alerting warnings** in logs - Intentional, using Slack instead
- **"Auth Errors" metric name** is misleading - counts all stderr, not just auth

## Handoff Doc

Full details: `docs/09-handoff/2026-02-03-SESSION-93-ALERT-INVESTIGATION-HANDOFF.md`

## Standard Daily Check

Run `/validate-daily` to check overall system health.
