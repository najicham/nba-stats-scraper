# Daily Orchestration Validation - Continued
**Date:** January 22, 2026
**Purpose:** Continue validating daily pipeline after backfill is complete
**Priority:** HIGH - Operational

---

## Your Mission

After the team boxscore backfill is complete, validate that:
1. Today's (Jan 22) pipeline can run successfully
2. All services are healthy
3. Predictions are generating correctly
4. No new issues have emerged

---

## Pre-Requisites

**Before starting this validation, confirm:**
- [ ] Team boxscore backfill completed (100 games)
- [ ] Phase 3-5 reprocessed for Jan 21
- [ ] Jan 21 predictions generated (850+ predictions)

Check with:
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21' AND is_active = TRUE
GROUP BY game_date;
"
```

---

## Context: What Was Wrong

### Issues Found on Jan 22 Validation

1. **Team boxscore data gap** - 4 weeks missing (Dec 27 - Jan 21)
   - Status: Being backfilled in separate session

2. **prediction-worker returning 503** - Deep health check failing
   - Status: Needs investigation if still occurring

3. **Phase 3 tables empty** - `upcoming_team_game_context` = 0 rows
   - Status: Should be fixed after backfill

4. **0 predictions for Jan 21**
   - Status: Should be fixed after backfill + reprocess

### Recent Fixes Deployed (Jan 21-22)

These fixes are in the codebase but may not all be deployed:
1. Prediction Coordinator Dockerfile fix (ModuleNotFoundError)
2. Phase 3 Analytics BDL threshold (36h → 72h)
3. BDL table name mismatch (cleanup processor)
4. Injury discovery pdfplumber dependency

See: `/docs/08-projects/current/jan-21-critical-fixes/`

---

## Step 1: Quick Health Check

```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 bin/validate_pipeline.py 2026-01-22 --legacy-view
```

**Expected for Jan 22 (today):**
- Games: 6-8 scheduled
- Phase 1-2: Should show data arriving
- Phase 3-4: May be in progress depending on time
- Phase 5: May not have predictions yet (depends on time)

---

## Step 2: Service Health Check

```bash
for svc in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator prediction-worker; do
  echo -n "$svc: "
  curl -s "https://${svc}-756957797294.us-west2.run.app/health" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "ERROR"
done
```

**Expected:** All return "healthy"

**If prediction-worker returns 503:**
- Check logs: `gcloud logging read 'resource.labels.service_name="prediction-worker"' --limit=20 --freshness=1h --project=nba-props-platform`
- May need redeployment or environment variable fix
- See investigation notes in `/docs/08-projects/current/team-boxscore-data-gap-incident/INCIDENT-REPORT-JAN-22-2026.md`

---

## Step 3: Verify Team Boxscore Now Available

```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_raw.nbac_team_boxscore
WHERE game_date >= '2025-12-27'
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30;
"
```

**Expected:** Records for all dates from Dec 27 onward

---

## Step 4: Check Today's Upstream Data

```bash
bq query --use_legacy_sql=false "
-- Today's schedule
SELECT game_date, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Today's props
SELECT game_date, COUNT(*) as lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Today's player context
SELECT game_date, COUNT(*) as records
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Today's team context
SELECT game_date, COUNT(*) as records
FROM nba_analytics.upcoming_team_game_context
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;
"
```

**Expected:**
- Schedule: 6-8 games
- Props: 20,000+ lines (if after 10:30 AM ET)
- Player context: 100+ records
- Team context: 10+ records (THIS WAS 0 YESTERDAY - should be fixed now)

---

## Step 5: Check for R-009 Regression

```bash
bq query --use_legacy_sql=false "
SELECT game_date, game_id, COUNTIF(is_active = TRUE) as active
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-21'
GROUP BY game_date, game_id
HAVING active = 0;
"
```

**Expected:** 0 rows (no R-009 regression)

---

## Step 6: Verify Jan 21 Predictions (After Backfill)

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT system_id) as systems,
  COUNT(DISTINCT universal_player_id) as players,
  ROUND(AVG(confidence_score), 2) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21'
  AND is_active = TRUE
GROUP BY game_date;
"
```

**Expected:**
- Predictions: 850-900
- Systems: 7
- Players: 25-30
- Avg confidence: 0.50-0.80

---

## Step 7: Monitor Today's Pipeline

If it's after 10:30 AM ET, the daily pipeline should be running:

```bash
# Check workflow executions
bq query --use_legacy_sql=false "
SELECT execution_time, workflow_name, status
FROM nba_orchestration.workflow_executions
WHERE DATE(execution_time) = CURRENT_DATE()
ORDER BY execution_time DESC
LIMIT 10;
"

# Check for errors
gcloud logging read 'resource.type=\"cloud_run_revision\" AND severity>=ERROR' \
  --limit=20 --freshness=2h --project=nba-props-platform \
  --format="table(timestamp,resource.labels.service_name,textPayload)"
```

---

## Known Issues to Watch

1. **prediction-worker 503** - May still be an issue
   - Root cause unclear (deep health check failing)
   - Model file exists in GCS
   - All env vars set correctly
   - May need verbose logging to diagnose

2. **Injury discovery workflow** - Showed repeated failures
   - May be related to pdfplumber fix not deployed

3. **Historical data completeness** - NEW ISSUE IDENTIFIED
   - Completeness checks don't validate historical windows
   - Rolling averages may still be degraded for ~3 weeks
   - See: `/docs/08-projects/current/team-boxscore-data-gap-incident/`

---

## Validation Report Template

After completing validation, document results:

```
DAILY VALIDATION REPORT - January 22, 2026
===========================================

OVERALL STATUS: [HEALTHY / DEGRADED / FAILED]

Pre-Requisite Checks:
- Jan 21 backfill complete: [YES/NO]
- Jan 21 predictions: [count]

Service Health:
- Phase 3 Analytics: [healthy/unhealthy]
- Phase 4 Precompute: [healthy/unhealthy]
- Prediction Coordinator: [healthy/unhealthy]
- Prediction Worker: [healthy/unhealthy]

Today's Data (Jan 22):
- Schedule: [count] games
- Props: [count] lines
- Player Context: [count] records
- Team Context: [count] records

Issues Found:
- [List any issues]

Recommendations:
- [List any actions needed]
```

---

## Reference Documents

- `/docs/02-operations/daily-validation-checklist.md` - Standard validation guide
- `/docs/08-projects/current/team-boxscore-data-gap-incident/` - Incident analysis
- `/docs/08-projects/current/jan-21-critical-fixes/` - Recent fixes

---

## Next Steps After Validation

If validation passes:
1. Document in validation report
2. Update handoff doc with current status
3. Monitor evening pipeline (if games today)

If validation fails:
1. Identify specific failure point
2. Check if related to known issues
3. Escalate if new issue discovered

---

**Document Status:** Ready for Execution
**Depends On:** Team boxscore backfill completion
