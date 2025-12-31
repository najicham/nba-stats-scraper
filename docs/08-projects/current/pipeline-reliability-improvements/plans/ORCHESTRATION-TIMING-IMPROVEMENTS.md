# Orchestration Timing Improvements

**Created:** December 29, 2025
**Status:** Planning
**Priority:** P1 - Important
**Author:** Analysis based on Dec 29 investigation

---

## Executive Summary

Analysis of the current orchestration shows **critical timing issues** that need to be addressed:

1. **Phase 6 export runs BEFORE predictions are generated** (1:00 PM vs 1:30 PM)
2. **Same-day pipeline runs too late** (12:30 PM start vs recommended 10:30 AM)
3. **Tomorrow's predictions not generated** until overnight (Dec 30 has 0 predictions)
4. **Self-heal is the actual trigger** - schedulers aren't completing the pipeline

---

## Current State Analysis

### Scheduler Configuration (Actual)

| Scheduler | Cron | Time (ET) | Purpose |
|-----------|------|-----------|---------|
| `same-day-phase3` | `30 12 * * *` | 12:30 PM | Phase 3 analytics |
| `same-day-phase4` | `0 13 * * *` | 1:00 PM | Phase 4 features |
| `same-day-predictions` | `30 13 * * *` | 1:30 PM | Predictions |
| `phase6-tonight-picks` | `0 13 * * *` | 1:00 PM | Website export |
| `self-heal-predictions` | `15 14 * * *` | 2:15 PM | Self-healing |

### Critical Timing Problem

```
Timeline (Current - BROKEN):

12:30 PM ─────► Phase 3 starts
              │
1:00 PM  ─────► Phase 4 starts
              │
1:00 PM  ─────► Phase 6 EXPORT runs (NO PREDICTIONS YET!)
              │
1:30 PM  ─────► Predictions scheduler starts
              │
2:15 PM  ─────► Self-heal triggers (catches missing predictions)
              │
~2:45 PM ─────► Predictions actually generated (via self-heal)
              │
?:?? PM  ─────► Phase 6 hourly export finally catches predictions
```

### Evidence from Today (Dec 29)

- Games start: **7:00 PM ET** (earliest)
- Predictions generated at: **2:48 PM ET** (via self-heal, not scheduler)
- Phase 6 export at 1:00 PM: **Had no predictions to export**
- Tomorrow (Dec 30): **0 predictions** (4 games scheduled)

---

## Root Cause Analysis

### Issue 1: Phase 6 Runs Before Predictions

The `phase6-tonight-picks` scheduler runs at **1:00 PM ET**, but `same-day-predictions` doesn't run until **1:30 PM ET**. This means:
- Website export runs with stale/no predictions
- Users don't see today's picks until hourly export catches up (6+ PM)

### Issue 2: Pipeline Runs Too Late

Current start time (12:30 PM) doesn't leave enough buffer for:
- Early games (rare 1:00 PM starts on holidays)
- Pipeline failures requiring retry
- Website publication before users check

### Issue 3: No Tomorrow Predictions

The pipeline only generates same-day predictions. Tomorrow's games don't get predictions until the next day's scheduler runs. This means:
- Users can't see tomorrow's picks in advance
- No preview for planning

### Issue 4: Reliance on Self-Heal

Self-heal at 2:15 PM is currently doing the heavy lifting because:
- Schedulers don't wait for dependencies
- Phase 3→4→5 orchestrators aren't coordinating same-day flow
- Self-heal catches the gap and triggers the full pipeline

---

## Recommended Timeline

```
Proposed Timeline (FIXED):

10:30 AM ─────► Phase 3 starts (same-day analytics)
              │ [30 min buffer]
11:00 AM ─────► Phase 4 starts (ML features)
              │ [30 min buffer]
11:30 AM ─────► Predictions start
              │ [60 min to complete]
12:30 PM ─────► Predictions complete
              │ [30 min buffer]
1:00 PM  ─────► Phase 6 export (predictions ready!)
              │
2:15 PM  ─────► Self-heal check (should find everything healthy)
              │
7:00 PM  ─────► First game starts (6.5 hour cushion!)
```

---

## Implementation Plan

### Phase 1: Fix Scheduler Timing (P0 - Do Now)

Update Cloud Scheduler jobs:

```bash
# Phase 3: Move from 12:30 PM to 10:30 AM
gcloud scheduler jobs update http same-day-phase3 \
  --location=us-west2 \
  --schedule="30 10 * * *"

# Phase 4: Move from 1:00 PM to 11:00 AM
gcloud scheduler jobs update http same-day-phase4 \
  --location=us-west2 \
  --schedule="0 11 * * *"

# Predictions: Move from 1:30 PM to 11:30 AM
gcloud scheduler jobs update http same-day-predictions \
  --location=us-west2 \
  --schedule="30 11 * * *"

# Phase 6 export: Keep at 1:00 PM (now runs AFTER predictions)
# No change needed
```

### Phase 2: Add Tomorrow Predictions (P1 - This Week)

Option A: Add separate scheduler for tomorrow
```bash
gcloud scheduler jobs create http same-day-predictions-tomorrow \
  --location=us-west2 \
  --schedule="0 12 * * *" \
  --time-zone="America/New_York" \
  --uri="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  --http-method=POST \
  --message-body='{"game_date": "tomorrow"}' \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com
```

Option B: Update prediction coordinator to generate today + tomorrow

### Phase 3: Add Early Game Detection (P2 - Nice to Have)

Create a scheduler that checks for early games and alerts:
- Run at 9:00 AM ET
- Check if any games start before 4:00 PM
- If so, trigger immediate pipeline run

### Phase 4: Improve Self-Heal (P2 - Enhancement)

- Add alerting when self-heal has to intervene
- Track how often self-heal saves the day
- Consider making self-heal run at 12:00 PM (earlier check)

---

## Quick Fix Commands

Run these to fix the timing immediately:

```bash
# Fix Phase 3 timing (10:30 AM ET)
gcloud scheduler jobs update http same-day-phase3 \
  --location=us-west2 \
  --schedule="30 10 * * *" \
  --time-zone="America/New_York"

# Fix Phase 4 timing (11:00 AM ET)
gcloud scheduler jobs update http same-day-phase4 \
  --location=us-west2 \
  --schedule="0 11 * * *" \
  --time-zone="America/New_York"

# Fix Predictions timing (11:30 AM ET)
gcloud scheduler jobs update http same-day-predictions \
  --location=us-west2 \
  --schedule="30 11 * * *" \
  --time-zone="America/New_York"

# Move self-heal earlier (12:30 PM ET instead of 2:15 PM)
gcloud scheduler jobs update http self-heal-predictions \
  --location=us-west2 \
  --schedule="30 12 * * *" \
  --time-zone="America/New_York"
```

---

## Verification Plan

After making changes:

1. **Next day morning:** Check that schedulers fire at new times
2. **By 12:00 PM ET:** Predictions should be generated
3. **At 1:00 PM ET:** Phase 6 export should have predictions
4. **At 12:30 PM ET:** Self-heal should report "healthy"

```bash
# Verify scheduler updates
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule)"

# Check predictions timing
bq query --use_legacy_sql=false "
SELECT game_date, MIN(created_at) as first_prediction, MAX(created_at) as last_prediction
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE('America/New_York')
AND is_active = TRUE
GROUP BY game_date"
```

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Earlier schedulers | Low | Self-heal still backs up |
| Adding tomorrow predictions | Medium | Test coordinator handles "tomorrow" |
| Moving self-heal earlier | Low | Can still run at 2:15 PM too |

---

## Decision Required

**Option A: Conservative Fix**
- Only fix scheduler timing (Phase 1)
- Keep self-heal as backup
- Monitor for a week before further changes

**Option B: Full Fix**
- Fix scheduler timing
- Add tomorrow predictions
- Move self-heal earlier
- All changes at once

**Recommendation:** Option A first, then Option B after validation.

---

## Current vs Proposed Summary

| Component | Current | Proposed | Impact |
|-----------|---------|----------|--------|
| Phase 3 | 12:30 PM | 10:30 AM | 2hr earlier |
| Phase 4 | 1:00 PM | 11:00 AM | 2hr earlier |
| Predictions | 1:30 PM | 11:30 AM | 2hr earlier |
| Phase 6 Export | 1:00 PM | 1:00 PM | No change (now works!) |
| Self-heal | 2:15 PM | 12:30 PM | Catches issues earlier |

**Net Result:** Predictions ready by ~12:30 PM instead of ~3:00 PM (2.5 hour improvement)

---

## Execution Log (December 29, 2025)

### Changes Made

1. **Scheduler Timing Updated (4 schedulers)**
   - `same-day-phase3`: 12:30 PM → 10:30 AM ET
   - `same-day-phase4`: 1:00 PM → 11:00 AM ET
   - `same-day-predictions`: 1:30 PM → 11:30 AM ET
   - `self-heal-predictions`: 2:15 PM → 12:30 PM ET

2. **TOMORROW Support Added**
   - Phase 3: `data_processors/analytics/main_analytics_service.py`
   - Phase 4: `data_processors/precompute/main_precompute_service.py`
   - Coordinator: `predictions/coordinator/coordinator.py`

3. **Tomorrow Schedulers Created**
   - `same-day-phase3-tomorrow`: 5:00 PM ET
   - `same-day-phase4-tomorrow`: 5:30 PM ET
   - `same-day-predictions-tomorrow`: 6:00 PM ET

4. **Services Deployed**
   - Phase 3 (nba-phase3-analytics-processors)
   - Phase 4 (nba-phase4-precompute-processors)
   - Prediction Coordinator (prediction-coordinator)

### Results

| Date | Context | Features | Predictions | Games |
|------|---------|----------|-------------|-------|
| Dec 29 | 352 | 352 | 1700 | 11 |
| Dec 30 | 60 | 60 | 700 | 2/4 |

**Note:** Dec 30 only has predictions for 2/4 games (Grizzlies vs 76ers, Jazz vs Celtics).
Lakers vs Pistons and Clippers vs Kings are missing context data.

### Remaining Issues

1. **Dec 30 incomplete predictions** - Only 2/4 games have context
   - Roster data exists for all teams (latest: Dec 28)
   - Possible player matching issue in UpcomingPlayerGameContext

2. **Game start time awareness** - No scheduler checks for early games
   - Should add alert if games start before noon

### Quick Verification Commands

```bash
# Check scheduler timing
gcloud scheduler jobs list --location=us-west2 --filter="name~same-day" --format="table(name,schedule)"

# Check pipeline status
bq query --use_legacy_sql=false "SELECT * FROM nba_orchestration.daily_phase_status WHERE game_date >= CURRENT_DATE() - 1"

# Check predictions
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as predictions FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() AND is_active = TRUE GROUP BY 1"

# Run health check
./bin/monitoring/daily_health_check.sh
```

### Current Scheduler Summary

| Scheduler | Time (ET) | Purpose |
|-----------|-----------|---------|
| same-day-phase3 | 10:30 AM | Today's game context |
| same-day-phase4 | 11:00 AM | Today's ML features |
| same-day-predictions | 11:30 AM | Today's predictions |
| self-heal-predictions | 12:30 PM | Catch missing predictions |
| phase6-tonight-picks | 1:00 PM | Website export |
| same-day-phase3-tomorrow | 5:00 PM | Tomorrow's game context |
| same-day-phase4-tomorrow | 5:30 PM | Tomorrow's ML features |
| same-day-predictions-tomorrow | 6:00 PM | Tomorrow's predictions |

---

*Created: December 29, 2025*
*Updated: December 29, 2025 - Execution complete*
