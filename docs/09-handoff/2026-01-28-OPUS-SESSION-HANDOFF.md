# Opus Session Handoff - 2026-01-28

**Session End**: ~4:30 PM PT
**Engineer**: Claude Opus 4.5
**Context**: Continued from validation coverage improvements session

---

## Critical Discovery: No NBA Odds Scheduler

**ROOT CAUSE OF has_prop_line ISSUES**: There is **no Cloud Scheduler job for NBA betting lines**!

MLB has schedulers:
- `mlb-props-morning` at 10:30 AM
- `mlb-props-pregame` at 12:30 PM

NBA has **NONE**. This explains why `has_prop_line = FALSE` for all players.

### Immediate Action Required

Create NBA odds scheduler jobs:

```bash
# Morning scrape (lines usually available by 10 AM ET / 7 AM PT)
gcloud scheduler jobs create http nba-props-morning \
  --location=us-west2 \
  --schedule="0 7 * * *" \
  --uri="https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "today"}' \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com

# Midday scrape (catch line movements)
gcloud scheduler jobs create http nba-props-midday \
  --location=us-west2 \
  --schedule="0 12 * * *" \
  --uri="https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "today"}' \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com

# Pre-game scrape (final lines before games)
gcloud scheduler jobs create http nba-props-pregame \
  --location=us-west2 \
  --schedule="0 16 * * *" \
  --uri="https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "today"}' \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com
```

**Note**: Verify the correct endpoint by checking:
```bash
# List endpoints on the scraper service
curl -s "https://nba-phase1-scrapers-756957797294.us-west2.run.app/" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

---

## Session Accomplishments

### Code Changes (All Committed, Need Push)

| Commit | Description |
|--------|-------------|
| `f012b1cc` | Add 22 missing symlinks to orchestrators |
| `021d9668` | Improve import validation (dynamic + runtime test) |
| `23a94dd2` | Add pre-commit hook for Cloud Function imports |
| `ca846bef` | Add CI pipeline step for import validation |
| `e3e945a5` | Create post-deployment health check script |
| `89967237` | Fix team stats duplicate game_ids (deduplication) |

### Infrastructure Changes (Done in GCP)

1. **Created Pub/Sub topic**: `nba-scraper-trigger`
2. **Deployed orchestrators**:
   - `phase3-to-phase4-orchestrator` revision 00022-toy
   - `phase4-to-phase5-orchestrator` revision 00029-dup
3. **Triggered Phase 3 backfill** for Jan 25-27 (completed)
4. **Triggered Phase 4 backfill** for Jan 25-27 (partial success)

---

## Current System Status

### What's Working
- ✅ Orchestrators deployed and healthy (fixed import errors)
- ✅ Phase 3 processors running
- ✅ Raw data collection working
- ✅ Prediction coordinator ready (no_active_batch)

### What's Broken
- ❌ **No NBA odds scheduler** - betting lines not being scraped
- ❌ **has_prop_line = FALSE** for Jan 28 (0/305 players)
- ❌ **Usage rate at 60%** (target 90%) - fix committed but not deployed
- ❌ **Phase 4 processors failing** - dependency check issues

### Data Status (Jan 27)

| Metric | Value | Target |
|--------|-------|--------|
| Box scores | 239 records | ✅ |
| Team stats | 26 records (14 after dedup) | ✅ |
| Usage rate coverage | 60.7% | 90% |
| has_prop_line | 107/236 (45%) | 90% |
| Predictions | 0 | 80-100 |

---

## Remaining Tasks

### P0 - Tonight's Games (Jan 28)

1. **Create NBA odds scheduler** (commands above)
2. **Manually trigger odds scrape** for Jan 28:
   ```bash
   curl -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-28"}'
   ```
3. **Update has_prop_line** after lines exist:
   ```sql
   UPDATE `nba-props-platform.nba_analytics.upcoming_player_game_context`
   SET has_prop_line = TRUE
   WHERE game_date = '2026-01-28'
     AND player_lookup IN (
       SELECT DISTINCT player_lookup
       FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
       WHERE game_date = '2026-01-28'
     )
   ```
4. **Trigger predictions**:
   ```bash
   curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-28"}'
   ```

### P1 - Deploy Code Fixes

1. **Push commits to remote**:
   ```bash
   git push origin main
   ```

2. **Deploy Phase 3 processor** with deduplication fix:
   ```bash
   # Check current deployment method
   ls bin/deploy/*phase3* || ls bin/deploy/*analytics*
   # Or use gcloud directly after finding Dockerfile location
   ```

3. **Reprocess Jan 25-27** after deployment to fix usage_rate

### P2 - Structural Improvements

1. **Fix Phase 3 timing race condition**
   - Phase 3 runs before betting lines are scraped
   - Need to add dependency check or adjust timing
   - See Task #7 in task list

2. **Improve prediction coordinator reliability**
   - Add batch timeout logic
   - Add cancel/reset API
   - See Task #8 in task list

---

## Key Files Modified This Session

```
orchestration/cloud_functions/phase3_to_phase4/shared/utils/*.py  (22 symlinks)
orchestration/cloud_functions/phase4_to_phase5/shared/utils/*.py  (22 symlinks)
bin/validation/validate_cloud_function_imports.py
bin/validation/post_deployment_health_check.py
.pre-commit-config.yaml
.github/workflows/deployment-validation.yml
data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py
data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
```

---

## Investigation Documents Created

- `docs/08-projects/current/2026-01-28-system-validation/VALIDATION-REPORT.md` (by Sonnet)
- This handoff document

---

## Commands Cheat Sheet

### Check System Status
```bash
# Orchestrator health
gcloud logging read "resource.labels.service_name=phase3-to-phase4-orchestrator" --limit=5

# Prediction coordinator status
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Betting lines status
bq query "SELECT game_date, COUNT(DISTINCT player_lookup) FROM nba_raw.odds_api_player_points_props WHERE game_date >= '2026-01-27' GROUP BY 1"

# has_prop_line status
bq query "SELECT game_date, COUNTIF(has_prop_line=TRUE) as with_lines, COUNT(*) as total FROM nba_analytics.upcoming_player_game_context WHERE game_date >= '2026-01-27' GROUP BY 1"
```

### Manual Triggers
```bash
# Phase 3 backfill
curl -X POST "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-27", "end_date": "2026-01-27", "backfill_mode": true}'

# Phase 4 backfill (with strict_mode=false to bypass dependency checks)
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-27", "trigger_source": "manual_backfill", "strict_mode": false}'
```

---

## Parallel Sonnet Tasks

You can start Sonnet chats for these independent tasks:

### Sonnet Task 1: Create NBA Odds Scheduler
```
Create Cloud Scheduler jobs for NBA betting lines scraping:
1. Find the correct endpoint for odds scraping on nba-phase1-scrapers
2. Create 3 scheduler jobs: morning (7 AM PT), midday (12 PM PT), pregame (4 PM PT)
3. Test by manually triggering one
4. Verify lines appear in nba_raw.odds_api_player_points_props
```

### Sonnet Task 2: Deploy Phase 3 Processor
```
Deploy the updated nba-phase3-analytics-processors with the team stats deduplication fix:
1. Find the deployment script or Dockerfile
2. Build and deploy to Cloud Run
3. Verify deployment succeeded
4. Reprocess Jan 25-27 data
5. Verify usage_rate coverage improved
```

### Sonnet Task 3: Fix Phase 3 Timing
```
Investigate and fix the Phase 3 timing race condition:
1. Phase 3 runs before betting lines are scraped
2. This causes has_prop_line = FALSE for all players
3. Options:
   a. Add dependency check in upcoming_player_game_context processor
   b. Reschedule Phase 3 to run after odds scraper
   c. Add retry logic if no betting lines found
4. Implement the best solution
```

---

## Git Status

```bash
# Local commits not pushed (6 commits ahead of origin/main)
git log --oneline origin/main..HEAD
```

**Important**: Push these commits before deploying:
```bash
git push origin main
```

---

## Contact Points

- Slack channels for alerts (from code):
  - `SLACK_WEBHOOK_URL` → #daily-orchestration
  - `SLACK_WEBHOOK_URL_ERROR` → #app-error-alerts
  - `SLACK_WEBHOOK_URL_WARNING` → #nba-alerts

---

**End of Handoff**
