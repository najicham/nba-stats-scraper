# Session Handoff: Scheduler Fix & System Investigation (2026-01-23)

**Session Time:** ~8:30 PM - 9:15 PM PST
**Next Milestone:** 10:00 PM PST (01:00 AM ET) - MERGE fix verification

---

## Completed Tonight

### 1. Fixed 9 Scheduler Jobs Pointing to Wrong Service

**Problem:** 9 Cloud Scheduler jobs were pointing to `nba-phase1-scrapers` which was misconfigured (returning `analytics-processor` health instead of scraper endpoints).

**Fix Applied:**
- Updated all 9 jobs to point to `nba-scrapers`
- Redeployed `nba-scrapers` with commit `2de48c04` to enable `/catchup` endpoint

| Job | Endpoint | Status |
|-----|----------|--------|
| bdl-boxscores-yesterday-catchup | /scrape | ✓ ENABLED |
| bdl-live-boxscores-evening | /scrape | ✓ ENABLED |
| bdl-live-boxscores-late | /scrape | ✓ ENABLED |
| cleanup-processor | /cleanup | ✓ ENABLED |
| daily-schedule-locker | /generate-daily-schedule | ✓ ENABLED |
| nba-bdl-boxscores-late | /scrape | ✓ ENABLED |
| bdl-catchup-afternoon | /catchup | ✓ ENABLED |
| bdl-catchup-evening | /catchup | ✓ ENABLED |
| bdl-catchup-midday | /catchup | ✓ ENABLED |

**Commands used:**
```bash
gcloud scheduler jobs update http JOB_NAME \
  --location=us-west2 \
  --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/ENDPOINT" \
  --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --oidc-token-audience="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
```

### 2. Redeployed nba-scrapers

**Revision:** `nba-scrapers-00091-942`
**Commit:** `2de48c04`
**New endpoint enabled:** `/catchup` (was returning 404 before)

---

## Investigation Findings

### nba-phase1-scrapers Service
- **Status:** Can be DELETED - no scheduler jobs point to it anymore
- **Only dependency:** `nba-phase1-scrapers-complete-dlq-monitor` Pub/Sub subscription
- **Returns:** `{"service":"analytics-processor"}` - clearly misconfigured
- **Action needed:** Delete service or fix later (low priority)

### Unresolved Players (2,861)
- **Actually pending:** Only 2 players
- **Resolved:** 2,857 (by ai_resolver)
- **Pending players:**
  - `alexantetokounmpo` (MIL) - Alex Antetokounmpo
  - `kylemangas` (SAS) - Kyle Mangas
- **Action needed:** Add these 2 players to registry (low priority)

### prediction-coordinator Misconfiguration
- **Issue:** Returns `{"service":"analytics-processor"}` instead of `{"service":"prediction-coordinator"}`
- **Deployed:** Dec 20, 2025
- **Action needed:** Investigate and redeploy (medium priority, not blocking predictions)

### MERGE Fix Verification
- **Fix commit:** `5f45fea3` (Jan 22, 2026)
- **Deployed commit:** `0718f2bd` (Jan 23, 2026 03:12 UTC)
- **Verified:** MERGE fix IS included in deployed code
- **Test time:** 10:00 PM PST (01:00 AM ET) - post_game_window_2

---

## Monitoring Commands for 10 PM Verification

```bash
# 1. Check for MERGE success
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"MERGE"' --limit=20 --freshness=2h --format="table(timestamp,textPayload)"

# 2. Check workflow decisions
bq query --use_legacy_sql=false 'SELECT workflow_name, action, reason, decision_time FROM `nba_orchestration.workflow_decisions` WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR) ORDER BY decision_time DESC LIMIT 20'

# 3. Check boxscore scraping
gcloud logging read 'resource.labels.service_name="nba-scrapers" AND textPayload=~"boxscore"' --limit=20 --freshness=2h --format="table(timestamp,textPayload)"

# 4. Validate pipeline
PYTHONPATH=. python bin/validate_pipeline.py 2026-01-22
```

---

## Remaining Items

### Tonight (after 10 PM PST)
- [ ] Verify MERGE fix works at 01:00 AM ET window
- [ ] Verify boxscores collected for Jan 22

### Future Sessions
- [ ] Delete or fix `nba-phase1-scrapers` service
- [ ] Add 2 pending players to registry (alexantetokounmpo, kylemangas)
- [ ] Investigate/fix `prediction-coordinator` health check
- [ ] Historical completeness backfill decision (see TODO-historical-completeness-backfill.md)

---

## Session Summary

Fixed critical scheduler misconfiguration that was causing 9 jobs to fail silently. Redeployed `nba-scrapers` to enable `/catchup` endpoint. All scheduled jobs now point to correct service. MERGE fix verified to be in deployed code - awaiting 10 PM test.
