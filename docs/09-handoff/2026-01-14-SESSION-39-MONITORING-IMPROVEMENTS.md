# Session 39 Handoff: Monitoring Improvements & West Coast Boxscore Fix

**Date:** 2026-01-14
**Session:** 39 (Afternoon)
**Status:** Complete - Monitoring Enhanced, Scraper Gap Fixed

---

## Summary

This session continued from Session 38's OIDC auth fixes. We implemented monitoring improvements to prevent similar issues and discovered/fixed a gap in west coast game boxscore scraping.

---

## Changes Made

### 1. Monitoring Improvements (Committed)

**File: `scripts/system_health_check.py`** (+178 lines)
- Added OIDC configuration validation for Pub/Sub subscriptions
- Added scheduler job audience validation (detects paths in audiences)
- Added `--skip-infra` flag for faster runs without infrastructure checks
- Configurable list of subscriptions and jobs to check

**File: `scripts/cleanup_stuck_processors.py`** (NEW - 311 lines)
- Automated cleanup of processors stuck in 'running' state
- Dry-run and execute modes
- Configurable threshold (default 30 min)
- Slack notification support
- JSON output for automation

**File: `scripts/setup_auth_error_alert.sh`** (NEW - 115 lines)
- Creates Cloud Monitoring log-based metric for 401/403 errors
- Metric name: `cloud_run_auth_errors`
- Alert policy JSON for manual setup in Cloud Console

### 2. Additional Auth Fixes

- Fixed `nba-phase3-analytics-sub` - was missing OIDC audience
- Cleaned up 222 stuck processors from auth outage
- Fixed 5 more scheduler jobs with paths in audiences:
  - `bdl-injuries-hourly`
  - `bdl-live-boxscores-evening`
  - `bdl-live-boxscores-late`
  - `boxscore-completeness-check`
  - `nba-bdl-boxscores-late`

### 3. West Coast Boxscore Gap Fix

**Problem Discovered:**
- BDL boxscores missing 2 games from 2026-01-13 (LAL vs ATL, GSW vs POR)
- Both were west coast late games (10:30-11 PM ET start)
- Scraper at 10 PM ET captured games in progress, not final scores
- Later scrapes targeted wrong date

**Fix Applied:**
```bash
gcloud scheduler jobs create http bdl-boxscores-yesterday-catchup \
  --location=us-west2 \
  --schedule="0 9 * * *" \
  --time-zone="UTC" \
  --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  --message-body='{"scraper": "bdl_box_scores", "group": "gcs"}' \
  --oidc-service-account-email="scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --oidc-token-audience="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app" \
  --description="BDL boxscores catchup for west coast games (4 AM ET)"
```

**Note:** Data was NOT lost - live boxscores and gamebooks had all 7 games. Analytics were complete.

---

## Git Status

```bash
# Committed in this session:
5af9335 feat(monitoring): Add OIDC validation and stuck processor cleanup

# Uncommitted (from separate MLB work):
- data_processors/raw/mlb/mlb_pitcher_props_processor.py
- shared/utils/mlb_* files
- scripts/mlb/* files
- docs/08-projects/current/mlb-pitcher-strikeouts/*.md
```

---

## Current System State

### Pipeline Health (as of 1 PM ET)
| Phase | Status | Notes |
|-------|--------|-------|
| Phase 2 (Raw) | ✅ Working | OIDC fixed |
| Phase 3 (Analytics) | ✅ Working | All 7 games processed |
| Phase 4 (Precompute) | ✅ Working | ML features ready |
| Phase 5 (Predictions) | ✅ Working | 358 predictions for today |

### Today's Games (2026-01-14)
- 7 games starting at 7 PM ET
- Predictions ready (using estimated lines until props window opens at 1 PM ET)
- Betting lines workflow will start scraping at 1 PM ET (6h before games)

### Scheduler Jobs
All scheduler jobs now have correct OIDC audiences (no paths).

---

## Verification Commands

```bash
# Health check with infrastructure validation
python scripts/system_health_check.py --hours=12

# Fast health check (skip OIDC/scheduler checks)
python scripts/system_health_check.py --hours=12 --skip-infra

# Preview stuck processors
python scripts/cleanup_stuck_processors.py --threshold=30

# Clean up stuck processors
python scripts/cleanup_stuck_processors.py --execute --threshold=30

# Verify all scheduler audiences are correct
gcloud scheduler jobs list --location=us-west2 \
  --format="table(name,httpTarget.oidcToken.audience)" | grep -E "\.run\.app/"
# Should return empty

# Verify Pub/Sub OIDC
gcloud pubsub subscriptions describe nba-phase2-raw-sub --format="yaml(pushConfig)"
gcloud pubsub subscriptions describe nba-phase3-analytics-sub --format="yaml(pushConfig)"
```

---

## Tonight's Schedule (ET)

| Time | Event |
|------|-------|
| 1:00 PM | Betting lines window opens (props scraping starts) |
| 5:30 PM | same-day-phase4-tomorrow |
| 6:00 PM | same-day-predictions-tomorrow |
| 7:00 PM | Games start |
| 4:00 PM - 12:00 AM | Live boxscores every 3 min |
| 4:00 AM (tomorrow) | NEW: bdl-boxscores-yesterday-catchup |

---

## Open Items for Future Sessions

1. **Investigate Phase 3 revision 00055** - Why did it return 404? Currently rolled back to 00054.

2. **Consider adding automated stuck processor cleanup** - The `cleanup_stuck_processors.py` script exists but isn't scheduled. Could add:
   ```bash
   gcloud scheduler jobs create http cleanup-stuck-processors \
     --schedule="*/30 * * * *" ...
   ```

3. **Cloud Monitoring alert policy** - The log-based metric was created but alert policy needs manual setup in Cloud Console (CLI failed due to permissions).

4. **West coast scraper investigation** - The existing `nba-bdl-boxscores-late` (2 AM ET) was targeting wrong date. May need to investigate why the date calculation was off.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/system_health_check.py` | Daily health check with OIDC validation |
| `scripts/cleanup_stuck_processors.py` | Clean up stuck processors |
| `scripts/setup_auth_error_alert.sh` | Set up auth error monitoring |
| `docs/09-handoff/2026-01-14-SESSION-38-OIDC-AUTH-FIXES.md` | Previous session's auth fixes |

---

## Data Completeness Check (2026-01-13)

| Source | Games | Status |
|--------|-------|--------|
| Scheduled | 7 | - |
| BDL Boxscores | 5 | ⚠️ Missing LAL/GSW (west coast) |
| BDL Live Boxscores | 7 | ✅ Complete |
| Gamebook Stats | 7 | ✅ Complete |
| Player Game Summary | 7 | ✅ Complete |

**Analytics were NOT affected** - the system correctly used fallback sources.
