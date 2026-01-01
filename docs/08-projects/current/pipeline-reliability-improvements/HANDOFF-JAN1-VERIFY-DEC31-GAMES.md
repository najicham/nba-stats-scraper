# New Chat Handoff: Verify December 31st Live Game Processing

**Date Created:** December 31, 2025, 8:30 PM ET
**For:** Next chat session (January 1, 2026 morning)
**Task:** Verify that tonight's 9 games (Dec 31) processed correctly after orchestration fix
**Priority:** High - Verification of critical bug fix
**Estimated Time:** 15 minutes

---

## Context: What Happened

On December 31st evening, we fixed a **critical orchestration bug** that caused all December 30th gamebooks to fail:

- **Bug:** Deployment script configured orchestrator to call itself instead of scraper service
- **Impact:** All gamebook scraping failed with HTTP 403 errors
- **Fix Applied:** Updated SERVICE_URL to point to correct scraper service
- **New Revision:** `nba-phase1-scrapers-00058-59j` (deployed ~7:00 PM ET)

**Your Job:** Verify that tonight's 9 games (Dec 31, 2025) processed correctly with the fix in place.

---

## Background: December 31st Games

**Total Games:** 9 scheduled
- GSW@CHA (started 7:00 PM ET)
- MIN@ATL, ORL@IND, PHX@CLE, NOP@CHI, NYK@SAS, DEN@TOR, WAS@MIL, POR@OKC (7:30-10:00 PM ET)

**Expected Timeline:**
- Games finish: ~9:30-11:30 PM ET (Dec 31)
- Gamebook scraping: ~11:00 PM - 12:30 AM ET (post_game_window_3 workflow)
- Processing complete: By 1:00 AM ET (Jan 1)

**You should verify this on January 1st morning** (after 8:00 AM ET to ensure all processing is complete).

---

## Verification Steps

### Step 1: Check Gamebook Files in GCS

**Command:**
```bash
# Check if all 9 gamebook folders exist
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/" | wc -l

# List all gamebook files with timestamps
gsutil ls -l "gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/*/20*.json"
```

**Expected Output:**
- **9 folders** (one per game)
- **9 JSON files** with timestamps between 11:00 PM Dec 31 and 1:00 AM Jan 1

**If fewer than 9 files:**
- Missing gamebooks indicate scraping failure
- Check Step 4 (orchestrator logs) for errors
- See "Troubleshooting" section below

---

### Step 2: Check Gamebook Data in BigQuery

**Command:**
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(*) as total_rows
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2025-12-31'
GROUP BY game_date"
```

**Expected Output:**
```
+------------+-------+----------------+------------+
| game_date  | games | unique_players | total_rows |
+------------+-------+----------------+------------+
| 2025-12-31 |     9 |      280-320   |   280-320  |
+------------+-------+----------------+------------+
```

**Notes:**
- **9 games** is critical (one per scheduled game)
- **280-320 unique players** is typical for 9 games (~31-36 players per game)
- If `total_rows` >> `unique_players`, there might be duplicates (not critical, but note it)

**If fewer than 9 games:**
- Some gamebooks failed to process
- Check Step 3 (scheduler logs) and Step 4 (orchestrator logs)

---

### Step 3: Check Scheduler Execution

**Command:**
```bash
# Check if post_game_window_3 scheduler ran
gcloud scheduler jobs describe post-game-window-3 --location=us-west2 --format="value(state,lastAttemptTime)"

# Check scheduler execution logs
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="post-game-window-3" AND timestamp>="2025-12-31T23:00:00Z"' \
  --limit=5 --format="table(timestamp,httpRequest.status,textPayload)"
```

**Expected Output:**
- State: `ENABLED`
- Last attempt time: Between 11:00 PM Dec 31 and 12:30 AM Jan 1
- HTTP status: `200` (successful trigger)

**If scheduler didn't run or failed:**
- Check scheduler configuration
- Manually trigger: `gcloud scheduler jobs run post-game-window-3 --location=us-west2`

---

### Step 4: Check Orchestrator Logs (Critical!)

**This is the most important check - verifies the fix is working.**

**Command:**
```bash
# Check for HTTP 403 errors (the bug we fixed)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"403" AND timestamp>="2025-12-31T23:00:00Z"' \
  --limit=20 --format="table(timestamp,textPayload)" --freshness=12h

# Check workflow executions
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"post_game_window" AND timestamp>="2025-12-31T23:00:00Z"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=12h

# Check gamebook scraper calls
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"nbac_gamebook_pdf" AND timestamp>="2025-12-31T23:00:00Z"' \
  --limit=20 --format="table(timestamp,textPayload)" --freshness=12h
```

**Expected Output:**
- **Zero HTTP 403 errors** from orchestrator → scraper communication (the bug we fixed!)
- **post_game_window_3 workflow executed** (may run multiple times as games finish)
- **9 successful gamebook scraper calls** (one per game)

**If you see HTTP 403 errors:**
- 🚨 **CRITICAL:** The fix didn't work or was overwritten
- Check SERVICE_URL configuration immediately (see "Emergency Fix" below)

**If you see HTTP 500 errors:**
- ⚠️ Individual scraper failures (not the orchestration bug)
- Check scraper service logs: `gcloud logging read 'resource.labels.service_name="nba-scrapers" AND severity>=ERROR' --freshness=12h`

---

### Step 5: Verify SERVICE_URL Configuration

**Command:**
```bash
# Verify SERVICE_URL is still correct
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep -E "SERVICE_URL|revisionName" | head -5
```

**Expected Output:**
```yaml
    revisionName: nba-phase1-scrapers-00058-59j  # Or newer (00059+)
        - name: SERVICE_URL
          value: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app  # ✅ CORRECT
```

**If SERVICE_URL is wrong:**
- Shows: `https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app` ❌
- Apply emergency fix (see below)

---

### Step 6: Compare with December 30th (Before Fix)

**Command:**
```bash
# Dec 30 (with bug): Should show 4 games
# Dec 31 (with fix): Should show 9 games
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_name) as unique_players
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= '2025-12-30'
GROUP BY game_date
ORDER BY game_date DESC"
```

**Expected Output:**
```
+------------+-------+----------------+
| game_date  | games | unique_players |
+------------+-------+----------------+
| 2025-12-31 |     9 |      280-320   |  ✅ All games processed
| 2025-12-30 |     4 |      141       |  ✅ Manually recovered
+------------+-------+----------------+
```

---

## Success Criteria

✅ **All checks pass if:**
1. All 9 gamebook files exist in GCS
2. All 9 games in BigQuery (`nba_raw.nbac_gamebook_player_stats`)
3. ~280-320 unique players for Dec 31
4. **Zero HTTP 403 errors** in orchestrator logs
5. SERVICE_URL correctly points to `https://nba-scrapers-f7p3g7f6ya-wl.a.run.app`

**If all criteria met:** The orchestration fix is working correctly! ✅

---

## Troubleshooting

### Issue 1: Missing Gamebooks (< 9 games)

**Diagnosis:**
```bash
# Check which games are missing
bq query --use_legacy_sql=false "
SELECT game_id, game_code, home_team_tricode, away_team_tricode, game_status
FROM nba_raw.nbac_schedule
WHERE game_date = '2025-12-31'
ORDER BY game_id"

# Check GCS for which games were scraped
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/"
```

**Resolution:**
```bash
# Manually scrape missing games (replace GAME_CODE)
curl -s -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_gamebook_pdf", "game_code": "20251231/GSWCHA"}'

# Trigger cleanup to republish
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup"
```

---

### Issue 2: HTTP 403 Errors Found (Critical!)

**This means the bug is back!**

**Emergency Fix:**
```bash
# Apply immediate fix
gcloud run services update nba-phase1-scrapers \
    --region=us-west2 \
    --set-env-vars="SERVICE_URL=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

# Verify fix
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep SERVICE_URL

# Re-trigger workflow
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
  -H "Content-Type: application/json" \
  -d '{"workflow": "post_game_window_3"}'
```

**Then:**
1. Investigate why SERVICE_URL was overwritten
2. Check if deployment script was run and reverted the fix
3. Report this as a critical issue

---

### Issue 3: Workflow Didn't Run

**Diagnosis:**
```bash
# Check scheduler state
gcloud scheduler jobs describe post-game-window-3 --location=us-west2

# Check recent scheduler logs
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="post-game-window-3"' --limit=10 --freshness=24h
```

**Resolution:**
```bash
# Manually trigger workflow
gcloud scheduler jobs run post-game-window-3 --location=us-west2

# Or call orchestrator directly
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
  -H "Content-Type: application/json" \
  -d '{"workflow": "post_game_window_3"}'
```

---

## Quick Commands (Copy-Paste Ready)

**One-line full check:**
```bash
echo "=== GCS Files ===" && \
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/" | wc -l && \
echo "Expected: 9" && \
echo "" && \
echo "=== BigQuery ===" && \
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_id) as games FROM nba_raw.nbac_gamebook_player_stats WHERE game_date='2025-12-31'" && \
echo "Expected: 9" && \
echo "" && \
echo "=== HTTP 403 Check ===" && \
gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"403"' --limit=5 --freshness=12h && \
echo "Expected: No results (or only proxy 403s)" && \
echo "" && \
echo "=== SERVICE_URL ===" && \
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep SERVICE_URL -A 1
```

---

## References

**Related Documents:**
- Incident Report: `docs/08-projects/current/pipeline-reliability-improvements/INCIDENT-2025-12-30-GAMEBOOK-FAILURE.md`
- Evening Session Handoff: `docs/08-projects/current/pipeline-reliability-improvements/HANDOFF-2025-12-31-EVENING-ORCHESTRATION-FIX.md`
- Operations Guide: `docs/02-operations/orchestrator-monitoring.md`
- Daily Monitoring: `docs/02-operations/daily-monitoring.md`

**Key Architecture:**
- Orchestrator: `nba-phase1-scrapers` (calls scrapers via HTTP)
- Scraper Service: `nba-scrapers` (executes individual scrapers)
- Critical Config: `SERVICE_URL` must point to scraper service, not orchestrator

---

## Report Back

After verification, please report:

✅ **Success Report:**
```
Dec 31 Verification Results:
✅ All 9 gamebook files in GCS
✅ All 9 games in BigQuery (XXX unique players)
✅ Zero HTTP 403 errors in orchestrator logs
✅ SERVICE_URL correctly configured
✅ Orchestration fix working perfectly

No action needed.
```

⚠️ **Issue Report:**
```
Dec 31 Verification Results:
⚠️ Found X/9 games in BigQuery
⚠️ Missing games: [list game codes]
⚠️ [Other issues found]

Actions taken:
- [What you did to fix]

Current status: [Resolved / Needs attention]
```

🚨 **Critical Report:**
```
Dec 31 Verification Results:
🚨 HTTP 403 ERRORS FOUND - BUG IS BACK
🚨 SERVICE_URL misconfigured (pointing to: XXX)

Emergency fix applied: [Yes/No]
Current status: [Details]
```

---

**Next Chat: Run verification steps above on January 1st morning (after 8 AM ET)**
**Priority: High - This verifies our critical bug fix is working in production**
**Estimated Time: 15 minutes**

Good luck! 🚀
