# Session 195: Historical Analysis of Scheduler Bug

**Analysis Date:** 2026-02-11 8:15 AM PST
**Scope:** Last 2 weeks (Jan 28 - Feb 11)
**Finding:** Bug has existed since at least Feb 7, causing 1-day lag in refreshes

## Executive Summary

The `ml-feature-store-7am-et` scheduler bug is **NOT new** - it's been causing issues for at least 4-5 days. The bug creates a **1-day lag** where:
- Features for date X are created night before (X-1)
- Morning refresh at 7 AM processes **date X-1** instead of **date X**
- Features for date X aren't refreshed until date X+1

**Impact Timeline:**
- **Feb 7:** Last good day (176 players) - benefited from Feb 6 refresh
- **Feb 8-9:** Degraded (65-84 players) - 1-day lag starting
- **Feb 10:** Broken (20 players) - lag worsening
- **Feb 11:** Broken (18 players) - no refresh at all

## Historical Data - Feature Store Creation Patterns

| Game Date | Night Before Creation | Morning Refresh | Span | Records | Status |
|-----------|----------------------|-----------------|------|---------|--------|
| **Feb 11** | Feb 10 10:30 PM | ❌ **None** | 0 hrs | 192 | 🔴 No refresh |
| Feb 10 | Feb 9 10:30 PM | Feb 11 12:00 PM | 37 hrs | 137 | 🟡 Next-day lag |
| Feb 9 | Feb 8 10:30 PM | Feb 10 12:00 PM | 37 hrs | 341 | 🟡 Next-day lag |
| Feb 8 | Feb 7 10:30 PM | Feb 9 12:00 PM | 37 hrs | 145 | 🟡 Next-day lag |
| Feb 7 | Feb 6 10:30 PM | Feb 8 12:00 PM | 37 hrs | 359 | 🟡 Next-day lag |
| Feb 6 | Feb 6 12:41 AM | Feb 7 12:02 PM | 35 hrs | 208 | 🟢 Good |
| Feb 5 | Feb 5 7:19 PM | Feb 6 8:11 PM | 24 hrs | 286 | 🟢 Good |
| Feb 1-4 | Mixed | Mixed | 42-141 hrs | 151-374 | 🟢 Multiple refreshes |

### Record Creation Detail (Feb 7-10)

**Feb 10 data created:**
- Feb 9 at 22:00 UTC (79 records) ← Night before
- Feb 11 at 12:00 UTC (58 records) ← **Next day** refresh (should be same day!)

**Feb 9 data created:**
- Feb 8 at 22:00 UTC (226 records) ← Night before
- Feb 10 at 12:00 UTC (115 records) ← **Next day** refresh

**Feb 8 data created:**
- Feb 7 at 22:00 UTC (129 records) ← Night before
- Feb 9 at 12:00 UTC (7 records) ← **Next day** refresh (very few!)

## Prediction Coverage Trend

| Date | Players | Predictions | Pattern |
|------|---------|-------------|---------|
| **Feb 11** | **18** | 18 | 🔴 **CRITICAL - No refresh** |
| **Feb 10** | **20** | 20 | 🔴 **BROKEN - 1 day lag** |
| **Feb 9** | **84** | 220 | 🟡 **DEGRADED - Partial stale data** |
| **Feb 8** | **65** | 110 | 🟡 **DEGRADED - Partial stale data** |
| **Feb 7** | **176** | 509 | 🟢 **GOOD - Benefited from Feb 6** |
| Feb 6 | 103 | 157 | 🟢 Early predictions worked |
| Feb 5 | 133 | 192 | 🟢 Normal |
| Feb 1-4 | 122-171 | 143-259 | 🟢 Normal |
| Jan 28-31 | 209-351 | 209-351 | 🟢 **EXCELLENT - Before bug** |

**Coverage drop:** 351 players (Jan 30) → 18 players (Feb 11) = **95% loss**

## When Did It Break?

### Scheduler Last Modified
```
ml-feature-store-7am-et
Last update: 2026-02-03T17:10:07Z (Feb 3 at 5:10 PM ET)
```

**Feb 3 changes:**
- Scheduler was reconfigured
- DNP filtering improvements deployed (`dd225120`)
- No obvious date logic changes in code

**Hypothesis:** Scheduler configuration change on Feb 3 introduced the bug, but it didn't manifest until Feb 7-8 when coverage started dropping.

### Deployment History (Phase 4)

Recent deploys around the time coverage dropped:
- **Feb 8-9:** Multiple deploys (commits f4fcb6a, b3dd558, 344b037)
- **Feb 9:** Session 159 robustness improvements (5e499316)
- **Feb 10-11:** Recent fixes (6dfc2b4, b2e9e54, afa7170, dc6a63a)

None of these touched date resolution logic directly.

## What's Actually Happening

### Configured Schedulers (All use America/New_York TZ)
```
ml-feature-store-7am-et     0 7 * * *   (7:00 AM ET = 12:00 UTC)
ml-feature-store-10am-et    0 10 * * *  (10:00 AM ET = 15:00 UTC)
ml-feature-store-1pm-et     0 13 * * *  (1:00 PM ET = 18:00 UTC)
ml-feature-store-daily      30 23 * * * (11:30 PM PT = 7:30 AM ET next day)
overnight-phase4-7am-et     0 7 * * *   (7:00 AM ET = 12:00 UTC)
```

### What 7 AM Scheduler SHOULD Do
```
Feb 11 at 7:00 AM ET:
  ↓
Process game_date = '2026-02-11' (TODAY)
  ↓
Refresh 192 players for Feb 11 games
  ↓
Predictions at 8 AM use FRESH Feb 11 data
  ↓
Result: ~113 quality-ready predictions
```

### What It ACTUALLY Does
```
Feb 11 at 7:00 AM ET:
  ↓
"TODAY" resolves to '2026-02-10' (YESTERDAY!)
  ↓
Refreshes 58 players for Feb 10 (games already happened)
  ↓
Feb 11 feature store remains stale (from night before)
  ↓
Predictions at 8 AM use STALE Feb 11 data
  ↓
Result: Only 18 predictions (84% loss)
```

## Evidence from Logs (This Morning)

```
2026-02-11T12:01:58 - Found 139 players with games on 2026-02-10 [BACKFILL MODE]
                                                        ^^^^^^^^^^^
                                                        SHOULD BE 2026-02-11!

2026-02-11T12:02:16 - Write complete: 137/137 rows (for 2026-02-10)
```

Scheduler ran at 12:00 UTC (7 AM ET) but processed **Feb 10** instead of **Feb 11**.

## Why Didn't We Notice Earlier?

### Coverage Metrics (Historical)

**Before bug (Jan 28-31):**
- Average: 267 players per day
- Range: 209-351 players
- Prediction rate: ~90% of roster

**After bug started (Feb 7-11):**
- Feb 7: 176 (still OK, benefited from Feb 6 refresh)
- Feb 8: 65 (63% drop from Feb 7)
- Feb 9: 84 (improved slightly)
- Feb 10: 20 (76% drop from Feb 9)
- Feb 11: 18 (10% drop from Feb 10, but 90% drop from baseline)

**Gradual degradation masked the bug initially.** The dramatic drop on Feb 10-11 made it obvious.

### Inactive Player Filtering (Session 195A)

Yesterday's investigation revealed 28 inactive/injured players (Tatum, Lillard, etc.) being correctly filtered by DNP logic from Session 2026-02-04. This is SEPARATE from the scheduler bug and is working correctly.

**Expected coverage with DNP filter:**
- 192 total roster
- ~28 inactive/injured (correct filter)
- ~50 missing shot zones (acceptable)
- **~113 quality-ready** (expected)

**Actual coverage:**
- 18 players (84% below expected) ← Scheduler bug impact

## Root Cause Summary

**The bug is in date resolution, not DNP filtering:**

1. ✅ **DNP filter works correctly** - Excludes 28 inactive players
2. ❌ **Scheduler date resolution broken** - Processes yesterday instead of today
3. ❌ **Creates 1-day lag** - Features refreshed a day late
4. ❌ **Compounds over time** - Each day gets staler data

## Questions for Investigation

1. **What changed on Feb 3** in scheduler configuration?
2. **Why does "TODAY" resolve to yesterday?** Timezone? Off-by-one bug?
3. **Are other schedulers affected?** (overnight-phase4-7am-et, etc.)
4. **Why 22:00 UTC night-before run?** That's 2 PM PT / 5 PM ET - not overnight
5. **Is there a 11:30 PM scheduler also running?** (ml-feature-store-daily)

## Recommended Actions

### Immediate (For Tomorrow Morning)
1. Manual trigger at 7 AM ET with explicit date:
   ```bash
   gcloud pubsub topics publish nba-phase4-trigger \
     --message='{"processors":["MLFeatureStoreProcessor"],"analysis_date":"2026-02-12",...}'
   ```

### Short-term (This Week)
1. Fix scheduler to use explicit date (Option 1 from main handoff)
2. OR fix service date resolution to use ET timezone (Option 2)
3. Add monitoring for stale feature stores (canary query)
4. Backfill missing refreshes for Feb 8-11 if needed

### Long-term (This Month)
1. Audit all schedulers for similar bugs
2. Add "last refresh age" metric to dashboards
3. Alert when feature store age > 12 hours
4. Document timezone handling standards

## Success Metrics

**Fix is working when:**
- ✅ Features for date X are refreshed on morning of date X (not X+1)
- ✅ Creation span for date X is 12-15 hours (night before + same-day refresh)
- ✅ Prediction coverage returns to ~113 quality-ready players
- ✅ Coverage stable for 3+ consecutive days

## Files to Examine

**Date resolution:**
- `data_processors/precompute/main_precompute_service.py` - Where "TODAY" is parsed
- `shared/utils/date_utils.py` - Date helper functions (if exists)

**Scheduler configuration:**
- Cloud Scheduler `ml-feature-store-7am-et` HTTP body
- Orchestrator publish messages

**Related code:**
- `orchestration/cloud_functions/phase3_to_phase4/main.py` - May also use "TODAY"

---

**Next session:** Start with scheduler configuration audit, then implement date resolution fix.
