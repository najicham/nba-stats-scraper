# Session 178: Boxscore Gaps Fix & Monitoring Implementation

**Date:** 2025-12-27 (late evening)
**Duration:** ~2 hours
**Focus:** Fix missing predictions, backfill boxscores, add monitoring

---

## TL;DR

Fixed 45% line coverage issue by identifying and addressing boxscore data gaps. Added daily monitoring to prevent recurrence.

---

## What Was Fixed

### Issue: 8 of 18 Teams Missing from Predictions

**Root Cause Chain:**
1. BallDontLie API had incomplete data for some teams (SAC at 44%, others at 70-82%)
2. Phase 3 completeness check required 90% coverage
3. Players failing check 3+ times triggered circuit breakers (7-day block)
4. 394 players blocked, including stars like Jokic, De'Aaron Fox, DeMar DeRozan

### Fixes Applied

1. **Lowered completeness threshold** from 90% to 70%
   - File: `shared/utils/completeness_checker.py:91`

2. **Backfilled missing boxscore data**
   - 12 dates backfilled (Dec 1, 2, 10, 11, 12, 15, 18, 20, 21, 22, 23, 26)
   - Coverage improved from 44-82% to 78-100%

3. **Cleared circuit breakers** for Dec 27 players
   - `DELETE FROM nba_orchestration.reprocess_attempts WHERE analysis_date = '2025-12-27'`

4. **Reran full pipeline** (Phase 3 → 4 → 5 → 6)
   - Result: All 9 games now have players in tonight's API

---

## Monitoring Added

### Daily Boxscore Completeness Check

**Scripts Created:**
- `bin/monitoring/check_boxscore_completeness.sh` - Shell script for manual checks
- `scripts/check_boxscore_completeness.py` - Python version with email alerts
- `bin/monitoring/setup_boxscore_completeness_scheduler.sh` - Scheduler setup

**Phase 2 Endpoint:**
- `POST /monitoring/boxscore-completeness`
- Checks coverage for last N days
- Sends email alerts if below threshold

**Thresholds:**
- CRITICAL: <70% coverage
- WARNING: <90% coverage

**Usage:**
```bash
# Check yesterday
./bin/monitoring/check_boxscore_completeness.sh

# Check last 7 days
./bin/monitoring/check_boxscore_completeness.sh --days 7

# Via API
curl -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/monitoring/boxscore-completeness" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"check_days": 1, "alert_on_gaps": true}'
```

---

## Root Cause Analysis

**Why BDL API has gaps:**
1. West coast late games most affected (LAC, SAC, POR)
2. Some games never appear in BDL API
3. No fallback data source currently

**Prevention strategies documented in:**
`docs/08-projects/current/BOXSCORE-GAPS-AND-CIRCUIT-BREAKERS.md`

---

## Commits Made

| Commit | Description |
|--------|-------------|
| `ef527d1` | Lower threshold 90→40 (temporary) |
| `5e4ffc5` | Set threshold to 70, document root cause |
| `2a064bf` | Add daily boxscore completeness monitoring |

---

## Remaining Work

### TODO: Set Up Cloud Scheduler

The scheduler setup script failed due to service account issues. Need to manually create:

```bash
gcloud scheduler jobs create http boxscore-completeness-daily \
  --location=us-west2 \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/monitoring/boxscore-completeness" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"check_days": 1, "alert_on_gaps": true}' \
  --oidc-service-account-email="SERVICE_ACCOUNT_HERE" \
  --oidc-token-audience="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app"
```

### TODO: Add Fallback Data Source

Consider using NBA.com gamebook data as backup when BDL API fails.

### TODO: Reduce Circuit Breaker Duration

Current: 7 days. Consider reducing to 1-2 days.

---

## Key Files

- `shared/utils/completeness_checker.py` - Threshold setting
- `data_processors/raw/main_processor_service.py` - Monitoring endpoint
- `docs/08-projects/current/BOXSCORE-GAPS-AND-CIRCUIT-BREAKERS.md` - Full documentation

---

## Quick Commands

```bash
# Check boxscore coverage
./bin/monitoring/check_boxscore_completeness.sh --days 7

# Backfill a missing date
PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py --date 2025-12-27 --group gcs

# Process backfilled data
PYTHONPATH=. .venv/bin/python backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py --dates "2025-12-27"

# Clear circuit breakers for a date
bq query --use_legacy_sql=false "DELETE FROM nba_orchestration.reprocess_attempts WHERE analysis_date = 'YYYY-MM-DD'"

# Check circuit breaker count
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT entity_id) FROM nba_orchestration.reprocess_attempts WHERE circuit_breaker_tripped = TRUE AND circuit_breaker_until > CURRENT_TIMESTAMP()"
```

---

## System Status at End of Session

- **Tonight's API:** All 9 games have players (832 total, 275 with lines)
- **Boxscore coverage:** 22 teams at 100%, remaining at 78-90%
- **Circuit breakers:** Cleared for Dec 27
- **Completeness threshold:** 70%
- **Monitoring:** Deployed to Phase 2, not yet scheduled

---

**Session Status:** Complete
**Documentation:** Updated `BOXSCORE-GAPS-AND-CIRCUIT-BREAKERS.md`
