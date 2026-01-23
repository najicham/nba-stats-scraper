# Session 38 Handoff: OIDC Authentication Fixes

**Date:** 2026-01-14
**Session:** 38 (Afternoon)
**Status:** Pipeline Restored - Multiple Auth Issues Fixed

---

## Critical Issues Found & Fixed

### 1. Phase 2 Pub/Sub Subscription Missing OIDC (ROOT CAUSE)

**Problem:** The `nba-phase2-raw-sub` subscription had no OIDC authentication configured, causing all Pub/Sub messages to fail with "401 Unauthorized".

**Impact:**
- Phase 1 → Phase 2 data flow completely broken
- No boxscore data processed for 2026-01-13 (6 games)
- Downstream Phase 3/4 blocked due to missing data

**Fix Applied:**
```bash
gcloud pubsub subscriptions modify-push-config nba-phase2-raw-sub \
  --push-endpoint="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  --push-auth-service-account="756957797294-compute@developer.gserviceaccount.com" \
  --push-auth-token-audience="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app"
```

### 2. Phase 3 Service Broken (Revision 00055)

**Problem:** Revision `nba-phase3-analytics-processors-00055-mgt` (deployed at 04:50 UTC from commit `129a5bf`) was returning 404 for `/process-date-range` endpoint.

**Fix Applied:** Rolled back to previous working revision:
```bash
gcloud run services update-traffic nba-phase3-analytics-processors --region=us-west2 \
  --to-revisions=nba-phase3-analytics-processors-00054-ltj=100
```

**TODO:** Investigate why revision 00055 broke the endpoint before redeploying.

### 3. Scheduler Jobs with Wrong Audiences

**Problem:** Multiple scheduler jobs had audiences that included the endpoint path (e.g., `/process-date-range`), which can cause authentication issues.

**Jobs Fixed:**
| Job | Service |
|-----|---------|
| daily-yesterday-analytics | Phase 3 |
| same-day-phase3 | Phase 3 |
| same-day-phase3-tomorrow | Phase 3 |
| ml-feature-store-daily | Phase 4 |
| overnight-phase4 | Phase 4 |
| player-composite-factors-daily | Phase 4 |
| player-daily-cache-daily | Phase 4 |
| same-day-phase4 | Phase 4 |
| same-day-phase4-tomorrow | Phase 4 |
| overnight-predictions | Phase 5 |
| same-day-predictions | Phase 5 |
| same-day-predictions-tomorrow | Phase 5 |

**Correct audience format:** `https://SERVICE-NAME-f7p3g7f6ya-wl.a.run.app` (no path)

---

## Data Recovery

### Reprocessed Data
After fixing auth issues, republished messages for 2026-01-13:

1. **BDL Boxscores:** 174 records now in `nba_raw.bdl_player_boxscores`
2. **Gamebooks:** 350 records now in `nba_raw.nbac_gamebook_player_stats`
3. **PlayerGameSummary:** 229 records processed for 2026-01-13

### Current Data Status
```sql
-- Raw data
SELECT game_date, COUNT(*) FROM nba_raw.bdl_player_boxscores WHERE game_date >= '2026-01-12' GROUP BY 1;
-- 2026-01-12: 140, 2026-01-13: 174

-- Gamebooks
SELECT game_date, COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date >= '2026-01-12' GROUP BY 1;
-- 2026-01-12: 210, 2026-01-13: 350

-- Predictions (already working via fallbacks)
SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date >= '2026-01-12' AND is_active = TRUE GROUP BY 1;
-- 2026-01-12: 82, 2026-01-13: 295, 2026-01-14: 348
```

---

## Root Cause Analysis

### Why Auth Broke
The Pub/Sub subscription `nba-phase2-raw-sub` was likely:
1. Created before OIDC was standard practice, OR
2. Had its push config modified without re-adding OIDC

The subscription `nba-processors-sub` (pointing to deleted topic) HAD OIDC configured, suggesting the original setup was correct but `nba-phase2-raw-sub` was misconfigured later.

### Why Phase 3 Revision 00055 Broke
Unknown. The revision was deployed via Cloud Run source deploy. The endpoint exists in the source code. Possible causes:
- Build process issue
- Different entrypoint being used
- Flask app not registering routes properly

**Action Item:** Before redeploying Phase 3, verify the `/process-date-range` endpoint is accessible.

---

## Verification Commands

### 1. Health Check
```bash
python scripts/system_health_check.py --hours=12
```

### 2. Verify Subscriptions Have OIDC
```bash
gcloud pubsub subscriptions describe nba-phase2-raw-sub --format="yaml(pushConfig)"
# Should show oidcToken with serviceAccountEmail AND audience
```

### 3. Verify Scheduler Job Audiences
```bash
gcloud scheduler jobs list --location=us-west2 --format="table(name,httpTarget.oidcToken.audience)" | grep -v "\.run\.app$"
# Should return empty (all audiences should end with .run.app, no paths)
```

### 4. Check for Auth Errors
```bash
gcloud logging read 'textPayload=~"not authenticated|not authorized|Unauthorized"' --limit=10 --freshness=1h
# Should return empty or minimal results
```

---

## Tonight's Monitoring

### Scheduled Jobs (ET)
| Time | Job | What to Check |
|------|-----|---------------|
| 11:00 AM | same-day-phase4 | Phase 4 precompute |
| 11:30 AM | same-day-predictions | Already ran this morning |
| 12:45 PM | self-heal-predictions | Auto-fix predictions |
| 5:30 PM | same-day-phase4-tomorrow | Tomorrow's precompute |
| 6:00 PM | same-day-predictions-tomorrow | Tomorrow's predictions |
| Games start ~7 PM | Live boxscores | bdl-live-boxscores-evening |

### After Games (11 PM+)
| Time | Job | What to Check |
|------|-----|---------------|
| 2:00 AM | overnight-predictions | Overnight predictions |
| 6:00 AM | overnight-phase4 | Overnight precompute |
| 6:30 AM | daily-yesterday-analytics | Yesterday's analytics |

---

## Summary

This session identified and fixed a critical authentication breakdown in the pipeline:

1. **Pub/Sub subscription** missing OIDC → Phase 2 completely broken
2. **Phase 3 revision** returning 404 → rolled back to working revision
3. **12 scheduler jobs** with incorrect audiences → all fixed

The prediction system was still generating predictions using fallbacks, masking the underlying data pipeline issues. After fixes, all phases are now processing correctly.

---

## Git Status

```
Uncommitted files:
- docs/09-handoff/2026-01-14-SESSION-38-OIDC-AUTH-FIXES.md (this file)
- data_processors/raw/mlb/mlb_pitcher_props_processor.py (MLB work - separate chat)
- MLB utilities in shared/utils/mlb_* (separate chat)
```
