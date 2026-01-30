# Session 21 Handoff - January 29, 2026

## Session Summary

Continuing from Session 20. Ran comprehensive daily validation and discovered **5 significant issues**, investigated root causes, and implemented fixes.

## Critical Discovery

**The prediction-coordinator Cloud Run service is deployed with WRONG code!**
- Returns 404 for all `/start` requests
- Logs show `data_processors.analytics.main_analytics_service` loading instead of coordinator
- This explains why predictions haven't been generating properly
- Currently rebuilding with correct Dockerfile

## Issues Found and Root Cause Analysis

### Issue 1: MIA@CHI Missing from Feature Store (RECOVERED)

| Aspect | Details |
|--------|---------|
| **Symptom** | 7 games in feature store instead of 8; MIA@CHI missing |
| **Root Cause** | Phase 4 ran BEFORE Session 20's view fix was deployed |
| **Why Not Caught** | Handoff said "cannot recover" without verification |
| **Fix Applied** | Triggered `same-day-phase4` scheduler job |
| **Prevention** | Add game count validation comparing schedule vs feature store |

**Recovery Steps:**
```bash
gcloud scheduler jobs run same-day-phase4 --location=us-west2
# Verified: Feature store now has 8 games including 20260129_MIA_CHI
```

### Issue 2: Spot Check False Positives (kellyoubrejr - rolling avg)

| Aspect | Details |
|--------|---------|
| **Symptom** | 114.63% mismatch in points_avg_last_10 |
| **Root Cause** | Spot check includes DNP games; processor excludes them |
| **Processor Logic** | Filters `(minutes_played > 0 OR points > 0)` |
| **Spot Check Logic** | No DNP filter - includes all games |
| **Fix Needed** | Update `scripts/spot_check_data_accuracy.py` lines 160-168 |

**Correct Filter:**
```sql
WHERE player_lookup = @player_lookup
  AND game_date < @cache_date
  AND season_year = @season_year
  AND is_active = TRUE
  AND (minutes_played > 0 OR points > 0)  -- Exclude DNPs
```

### Issue 3: Spot Check False Positives (jordanmclaughlin - usage rate)

| Aspect | Details |
|--------|---------|
| **Symptom** | 5.85% mismatch in usage_rate |
| **Root Cause** | Processor uses `minutes_decimal` (3.78), stores rounded `minutes_played` (4) |
| **Spot Check Logic** | Uses stored `minutes_played` to recalculate |
| **Math** | 3.78 vs 4 = 5.8% difference, directly affects usage_rate |
| **Fix Options** | 1) Store minutes_decimal, 2) Wider tolerance for low-minute players |

### Issue 4: Scraper Parameter Errors

| Aspect | Details |
|--------|---------|
| **Symptom** | "Missing required option [gamedate]" errors in logs |
| **Root Cause** | Parameter resolver returns `'date'` instead of `'gamedate'` when no games |
| **Location** | `orchestration/parameter_resolver.py` line ~440 |
| **Severity** | Medium - doesn't block data collection, edge case for no-game days |
| **Fix** | Update fallback to return `'gamedate'` or skip scraper entirely |

### Issue 5: Prediction-Coordinator Wrong Code Deployed (CRITICAL)

| Aspect | Details |
|--------|---------|
| **Symptom** | All `/start` requests return 404 |
| **Evidence** | Logs show `data_processors.analytics.main_analytics_service` |
| **Root Cause** | Deployment used wrong source directory or Dockerfile |
| **Impact** | Predictions not generating for any games |
| **Fix** | Rebuilding with correct Dockerfile from repo root |

## Common Patterns Identified

1. **Timing Dependencies**: Data processing order matters; fixes deployed after processing don't retroactively fix data
2. **Validation Divergence**: Test/validation scripts use different logic than production
3. **Deployment Drift**: Services running wrong code without detection
4. **Inconsistent Parameters**: Same concept (date) has different parameter names

## Prevention Mechanisms Needed

### 1. Game Count Validation
```python
# Add to Phase 4 processor
scheduled_games = query_schedule_view()
processed_games = query_feature_store()
if len(processed_games) < len(scheduled_games):
    alert("Feature store missing games: expected {}, got {}")
```

### 2. Unified Calculation Module
```python
# shared/calculations/stats_calculator.py
def calculate_rolling_average(games, window=10):
    """Single source of truth used by both processor and validation"""
    valid_games = [g for g in games if g.minutes_played > 0 or g.points > 0]
    return sum(g.points for g in valid_games[:window]) / min(len(valid_games), window)
```

### 3. Deployment Verification
```bash
# Add to CI/CD pipeline
gcloud run services logs read $SERVICE --limit=5 | grep "Health check endpoints"
# Verify expected module name appears in startup logs
```

### 4. Parameter Standardization
```python
# orchestration/constants.py
DATE_PARAM = 'game_date'  # Single source of truth for all date parameters
```

## Current System State

| Component | Status | Notes |
|-----------|--------|-------|
| Feature Store (Jan 29) | 8 games | MIA@CHI recovered |
| Predictions (Jan 29) | 7 games | MIA@CHI pending coordinator fix |
| Phase 3 Completion | 5/5 | All processors complete |
| Spot Checks | 40% | False positives - validation needs fix |
| Prediction-Coordinator | BROKEN | Rebuilding now |
| Prediction-Worker | Drift | Build failed due to shared/ path |

## Actions Taken This Session

1. Ran comprehensive daily validation
2. Spawned 4 parallel agents to investigate issues
3. Recovered MIA@CHI feature store data
4. Identified prediction-coordinator deployment issue
5. Started coordinator rebuild

## Next Steps

### Immediate (This Session)
- [ ] Complete prediction-coordinator rebuild
- [ ] Deploy new coordinator image
- [ ] Trigger predictions for MIA@CHI
- [ ] Verify predictions generated for all 8 games

### Follow-up (Next Session)
- [ ] Fix spot check script DNP filtering
- [ ] Fix spot check decimal precision issue
- [ ] Fix prediction-worker build (shared/ path issue)
- [ ] Add game count validation to Phase 4
- [ ] Fix parameter resolver date fallback

## Key Files Modified

None yet - analysis session. Fixes pending.

## Key Commands Used

```bash
# Recover MIA@CHI feature store
gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Check coordinator logs
gcloud run services logs read prediction-coordinator --region=us-west2 --limit=30

# Build coordinator correctly
gcloud builds submit --config=/tmp/coordinator-build.yaml . --project=nba-props-platform
```

## Build Status

**Coordinator rebuild: COMPLETE and DEPLOYED**

New revision: `prediction-coordinator-00103-2gz`
Image: `us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-coordinator:latest`

The coordinator is now running correctly (no more 404s), but MIA@CHI predictions still not generating. Investigation ongoing.

## Outstanding Issue: MIA@CHI Predictions Still Missing

**Root Causes Identified:**

1. **Timezone Bug (CRITICAL)**
   - Scheduler job sends `{"force": true}` without game_date
   - Coordinator defaults to `date.today()` which uses UTC
   - At 6pm PST = 2am UTC Jan 30, so coordinator processes Jan 30 instead of Jan 29!
   - Fix: Update scheduler body to include `"game_date": "TODAY"` (uses America/New_York)

2. **Missing Module Error**
   - Coordinator tries to import `predictions.worker.data_loaders` but worker not in image
   - `ModuleNotFoundError: No module named 'predictions.worker'`
   - This is non-blocking (falls back to individual queries) but inefficient

3. **Missing Import Error**
   - `name 'bigquery' is not defined` in pre-flight filter
   - May cause quality score filtering to fail

**Data Verification (All Ready):**
- MIA@CHI in upcoming_player_game_context: ✅ 34 players (18 CHI + 16 MIA)
- MIA@CHI in ml_feature_store_v2: ✅ 34 players
- Players passing filters: ✅ 12 players (7 CHI + 5 MIA with 15+ min or prop line)
- All production_ready: ✅ 34/34

**Next session should:**
1. Update `same-day-predictions` scheduler to pass `"game_date": "TODAY"`
2. Add `predictions/worker/` to coordinator Dockerfile or refactor imports
3. Fix `bigquery` import in coordinator.py pre-flight filter
4. Manually trigger coordinator with `{"game_date": "2026-01-29"}` to generate MIA@CHI predictions

## Final Status Update (End of Session)

### Fixes Completed

| Fix | Status | Details |
|-----|--------|---------|
| Prediction-coordinator | ✅ Fixed | Rebuilt with correct code, deployed |
| Prediction-worker | ✅ Fixed | Rebuilt from repo root, deployed revision `00029-6vw` |
| Scheduler timezone | ✅ Fixed | Updated 4 jobs to use `"game_date": "TODAY"` |
| Prevention mechanisms | ✅ Created | `bin/deploy-service.sh`, startup verification |

### MIA@CHI Still Missing Predictions

Despite all fixes:
- Feature store has 34 MIA@CHI players ✅
- 12 players pass coordinator filters ✅
- Schedule shows 8 games for Jan 29 ✅
- Predictions only show 7 games ❌

**Possible remaining causes:**
1. Coordinator may be detecting postponement/reschedule for game_id `0022500529` (reused from Jan 8)
2. Pub/Sub messages may be going to wrong worker revision
3. Some other filter in coordinator excluding MIA@CHI specifically

**For next session:**
```bash
# Check postponement detection logs
gcloud run services logs read prediction-coordinator --region=us-west2 --limit=200 | grep -i "postpone\|reschedule\|0022500529"

# Manual prediction for specific player
curl -X POST "https://prediction-worker-756957797294.us-west2.run.app/predict" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"player_lookup": "nikolavucevic", "game_date": "2026-01-29"}'
```

---

*Session 21 started 2026-01-29 ~17:42 PST*
*Handoff finalized 2026-01-29 ~19:00 PST*
*Coordinator fixed, MIA@CHI data ready, worker deployment needed*
