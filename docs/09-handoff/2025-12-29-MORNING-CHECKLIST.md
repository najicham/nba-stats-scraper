# Morning Checklist - December 29, 2025

**Last Session**: Session 184 (late night Dec 28)
**Last Commit**: `cbe162e` - fix: Add storage import for ESPN roster folder handling

---

## CRITICAL: Deploy Needed

The ESPN roster storage import fix was committed but **NOT YET DEPLOYED**. Run this first thing:

```bash
./bin/raw/deploy/deploy_processors_simple.sh
```

---

## Morning Verification Checklist

### 1. ESPN Roster Processing
**Issue**: Scraper publishes folder path, processor expected file path
**Fix**: Added special handling for ESPN roster folders in orchestration

```bash
# Verify deployment
gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="get(status.latestCreatedRevisionName)"

# Test ESPN roster processing (after deploy)
curl -s -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper_name": "espn_team_roster_api",
    "gcs_path": "gs://nba-scraped-data/espn/rosters/2025-12-28/",
    "status": "success"
  }' | jq '.processed, .failed'

# Expected: processed=30, failed=0 (all 30 teams)
```

### 2. Live Grading - game_id Fix
**Issue**: Players had null home_team/away_team due to game_id format mismatch
**Fix**: Added dual-format JOIN in live_grading_exporter.py

```bash
# Check Dec 28 live grading for null teams
gsutil cat "gs://nba-props-platform-api/v1/live-grading/2025-12-28.json" | jq '[.predictions[] | select(.home_team == null)] | length'

# Expected: 0 (was 3 before)
```

### 3. Tonight's Predictions (Dec 29)
```bash
# Check if predictions exist for today
bq query --use_legacy_sql=false --format=pretty "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE('America/New_York') AND is_active = TRUE"

# If 0, trigger same-day predictions:
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

### 4. Live Data Pipeline
```bash
# Check live scores API
gsutil cat "gs://nba-props-platform-api/v1/live/latest.json" | jq '.summary'

# Check tonight's API
gsutil cat "gs://nba-props-platform-api/v1/tonight/all-players.json" | jq '.metadata'
```

### 5. Check for Error Alerts
Look for any new error emails about:
- ESPN roster processing (should be fixed after deploy)
- BDL player-box-scores (fixed with gcs_path-only handling)
- Any other processor failures

---

## Summary of Session 184 Fixes

| Fix | Status | Details |
|-----|--------|---------|
| game_id format in gamebook/Odds API | ✅ Deployed | Uses official NBA format now |
| Live grading dual-format JOIN | ✅ Deployed | Handles both old and new formats |
| gcs_path-only message handling | ✅ Deployed | Fallback for incomplete messages |
| ESPN roster folder handling | ⚠️ NEEDS DEPLOY | Iterates over files in folder |

---

## Commits from Session 184
```
cbe162e fix: Add storage import for ESPN roster folder handling
e1d8401 fix: Handle ESPN roster folder paths in processor orchestration  
ba5bb8c docs: Update Session 184 handoff with verification results
d59d596 fix: Handle gcs_path-only messages in processor orchestration
68cf293 docs: Add Session 184 handoff - game_id format fix
176df39 fix: Use official NBA game_id format in gamebook and Odds API processors
```

---

## If Something Breaks

### ESPN Roster Still Failing
Check logs:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase2-raw-processors" AND "espn"' --limit=20 --format="table(timestamp,textPayload)" --freshness=30m
```

### Live Grading Shows Wrong Data
Re-export for specific date:
```bash
curl -X POST 'https://us-west2-nba-props-platform.cloudfunctions.net/live-export' \
  -H 'Content-Type: application/json' \
  -d '{"target_date": "2025-12-29"}'
```

### No Predictions for Today
1. Check Phase 4 ran: `gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors"' --limit=10`
2. Trigger manually: `gcloud scheduler jobs run same-day-predictions --location=us-west2`
