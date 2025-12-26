# Session 168: Deployment Fixes, Email Alerting & Monitoring
**Date:** December 25, 2025 (10:30 PM ET)
**Status:** All P1 Issues Resolved

---

## Executive Summary

This session completed all P1 action items from Session 167:
1. Deployed Phase 2 with skip path fix (stops spurious emails)
2. Fixed Phase 1 email alerting (env vars were missing despite deploy)
3. Created monitoring tools and documentation
4. Verified Christmas Day data collection

---

## Deployments Completed

### 1. Phase 2 Raw Processors (`6493785`)
- **Revision:** `nba-phase2-raw-processors-00039-njk`
- **Fix:** Added `SKIP_PROCESSING_PATHS` for `odds-api/events` and `bettingpros/events`
- **Result:** No more spurious "No processor found" emails (~22/workflow eliminated)

### 2. Phase 1 Scrapers - Email Alerting Fix
- **Issue Found:** Deploy script showed "ENABLED" but env vars weren't actually set
- **Revisions:** 00044 (partial) → 00045 (complete)
- **Fix:** Manually added email env vars via `gcloud run services update`
- **Email Config Now Active:**
  - BREVO_SMTP_HOST: smtp-relay.brevo.com
  - BREVO_SMTP_PORT: 587
  - BREVO_SMTP_USERNAME: 98104d001@smtp-brevo.com
  - BREVO_SMTP_PASSWORD: (set)
  - BREVO_FROM_EMAIL: alert@989.ninja
  - EMAIL_ALERTS_TO: nchammas@gmail.com
  - EMAIL_CRITICAL_TO: nchammas@gmail.com

---

## Issues Found During Investigation

### Active Issues (Non-Blocking)

| Issue | Severity | Status |
|-------|----------|--------|
| **403 Proxy Errors** | Warning | Intermittent, auto-retries work |
| **`is_active` hash field missing** | Warning | BDL Active Players processor schema mismatch |
| **`bdl_box_scores` table not found** | Warning | Wrong table name in cleanup processor |
| **datetime JSON serialization** | Warning | Bug in cleanup BQ insert |

### Resolved Issues

| Issue | Fix |
|-------|-----|
| Spurious "No processor found" emails | Added SKIP_PROCESSING_PATHS |
| "No recipients for CRITICAL alert" | Added email env vars to Phase 1 |

---

## Christmas Day Data Status (10:30 PM ET)

### Games Completed
| Game | Status | Boxscores |
|------|--------|-----------|
| CLE @ NYK | Final (126-124 NYK) | ✅ |
| SAS @ OKC | Final (113-126 OKC) | ✅ |
| DAL @ GSW | Final | ✅ |
| HOU @ LAL | In Progress | ⏳ |
| MIN @ DEN | Upcoming | ⏳ |

### Data Collected
- **BDL Boxscores:** 3 games, 106 player rows
- **BettingPros Props:** 16,237 rows
- **Gamebooks:** Dec 25 data now showing ✅
- **Injury Report:** Stale (expected - PDF unavailable Christmas Day)

---

## Monitoring Improvements Created

### 1. Quick Health Check Script
**File:** `bin/monitoring/quick_pipeline_check.sh`

```bash
# Run anytime to see pipeline status
bin/monitoring/quick_pipeline_check.sh
```

Checks:
- Recent errors (last hour)
- Today's data counts
- Service health
- Data freshness

### 2. Daily Monitoring Guide
**File:** `docs/02-operations/daily-monitoring.md`

Comprehensive guide covering:
- Manual health check commands
- Common issues and fixes
- Deployment commands
- When to escalate

---

## Service Status Summary

| Service | Revision | Email Alerting | Verified |
|---------|----------|---------------|----------|
| Phase 1 Scrapers | 00045-8j4 | ✅ ENABLED | ✅ |
| Phase 2 Processors | 00039-njk | ✅ ENABLED | ✅ |
| Phase 3 Analytics | Current | ✅ ENABLED | - |
| Phase 4 Precompute | Current | ✅ ENABLED | - |

---

## Quick Commands

```bash
# Quick health check
bin/monitoring/quick_pipeline_check.sh

# Data freshness
PYTHONPATH=. python scripts/check_data_freshness.py --json | jq '.'

# Check for errors
gcloud logging read 'severity>=ERROR' --limit=10 --freshness=1h

# Verify email config
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep -i email

# Check game status
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | jq '.scoreboard.games | length'
```

---

## Known Issues (Deferred)

### P3 - Future Improvements
- [ ] Fix `is_active` hash field in BDL Active Players processor
- [ ] Fix `bdl_box_scores` table reference in cleanup processor
- [ ] Fix datetime serialization in cleanup BQ insert
- [ ] Add backup proxies to proxy pool
- [ ] Investigate deploy script env var issue (why vars weren't set)

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `446b3fc` | docs: Session 168 - deployment fixes and email alerting |
| `672bb3d` | feat: Add quick pipeline health check script |

---

## Files Created/Modified

### New Files
- `bin/monitoring/quick_pipeline_check.sh` - Quick health check script
- `docs/02-operations/daily-monitoring.md` - Daily monitoring guide

### Updated Files
- `docs/09-handoff/2025-12-25-SESSION168-DEPLOYMENT-FIXES.md` - This document

---

## Next Session Recommendations

1. **Fix BDL Active Players processor** - Remove `is_active` from HASH_FIELDS
2. **Fix cleanup processor table reference** - Change `bdl_box_scores` to `bdl_player_boxscores`
3. **Investigate deploy script** - Why env vars weren't being set
4. **Monitor late games** - Verify HOU@LAL and MIN@DEN data collected

---

*Session 168 Complete - December 25, 2025 10:30 PM ET*
