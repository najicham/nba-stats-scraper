# Phase 5 Predictions Not Running

**Created:** December 25, 2025
**Priority:** HIGH
**Status:** RESOLVED (December 26, 2025)
**Last Predictions:** December 20, 2025 (Gap: Dec 21-25)

---

## Resolution Summary (Session 171)

**Root Cause Identified:** The overnight schedulers process YESTERDAY's games (post-game processing), not TODAY's games. There was **no scheduler for same-day pre-game predictions**.

**Fixes Applied:**
1. Added `TODAY` date support to Phase 3 and Phase 4 services
2. Created 3 new morning schedulers for same-day predictions:
   - `same-day-phase3` (10:30 AM ET) - UpcomingPlayerGameContextProcessor
   - `same-day-phase4` (11:00 AM ET) - MLFeatureStoreProcessor with same-day mode
   - `same-day-predictions` (11:30 AM ET) - Prediction coordinator

**Key Changes:**
- `data_processors/precompute/main_precompute_service.py` - Added TODAY date handling
- `data_processors/analytics/main_analytics_service.py` - Added TODAY date handling
- `bin/orchestrators/setup_same_day_schedulers.sh` - New script to create schedulers

**Same-Day Prediction Flow (new):**
```
10:30 AM ET - Phase 3: UpcomingPlayerGameContextProcessor for TODAY
11:00 AM ET - Phase 4: MLFeatureStoreProcessor for TODAY (same-day mode)
11:30 AM ET - Phase 5: Prediction coordinator for TODAY
1:00 PM ET  - Phase 6: Export predictions (existing phase6-tonight-picks)
```

**Overnight Post-Game Flow (existing, unchanged):**
```
11:00 PM PT - player-composite-factors-daily (processes YESTERDAY)
11:15 PM PT - player-daily-cache-daily (processes YESTERDAY)
11:30 PM PT - ml-feature-store-daily (processes YESTERDAY)
```

---

## Original Issue (for reference)

The Phase 5 prediction system stopped generating predictions. The last predictions in the database were from **December 20, 2025**.

### What Was Broken

The overnight Phase 4 schedulers use `analysis_date: "AUTO"`, which resolves to **YESTERDAY**:

```python
if analysis_date == "AUTO":
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
```

This means the overnight run processes post-game data, not pre-game predictions for today's games.

### Additional Issues Fixed (Session 170)

1. **Phase 3 Wrong Docker Image**: Phase 3 was running Phase 4 (precompute) code. Redeployed with correct `analytics-processor.Dockerfile`.

2. **Same-Day Prediction Mode**: MLFeatureStoreProcessor couldn't process today's games due to defensive checks. Added `strict_mode` and `skip_dependency_check` parameters.

3. **Stale Run History**: Deleted 114,434 stuck "running" entries from `processor_run_history`.

---

## Verification Commands

### Check Schedulers
```bash
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state)"
```

### Check Predictions Exist
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'ensemble_v1' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date DESC LIMIT 5"
```

### Manually Trigger Same-Day Predictions
```bash
# Step 1: Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Step 2: Phase 4 (wait 30 seconds)
gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Step 3: Predictions (wait 60 seconds)
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/main_precompute_service.py` | Added TODAY date handling |
| `data_processors/analytics/main_analytics_service.py` | Added TODAY date handling |
| `bin/orchestrators/setup_same_day_schedulers.sh` | New scheduler setup script |

---

## Update Log

| Date | Update |
|------|--------|
| 2025-12-25 | Document created - Phase 5 not running since Dec 20 |
| 2025-12-26 | Session 170 - Fixed Phase 3 deployment, same-day prediction mode |
| 2025-12-26 | Session 171 - Root cause identified: no same-day schedulers. Created morning schedulers. |
