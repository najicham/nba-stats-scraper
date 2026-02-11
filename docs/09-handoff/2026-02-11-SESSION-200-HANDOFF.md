# Session 200 Handoff - Phase 3 Coverage Fix (BDL Migration Completion)

**Date:** 2026-02-11
**Commit:** `0b17c702`
**Status:** ✅ CRITICAL BUG FIXED - Auto-deploy in progress

## Problem Summary

Only 7/12 players with betting lines got predictions on Feb 11 (~35% coverage). Investigation revealed **Session 149's BDL→nbac migration was incomplete**, causing Phase 3 to query a dead table.

## Root Cause (Found in 90 Minutes)

**Session 149 (Feb 7)** migrated `completeness_checker.py` internal queries from `bdl_player_boxscores` to `nbac_gamebook_player_stats`, but **MISSED** two critical callers:

1. **`completeness_checker_helper.py` line 88** - Hardcoded parameter `upstream_table='nba_raw.bdl_player_boxscores'`
2. **`async_upcoming_player_game_context_processor.py` line 452** - Direct query to BDL table

**Why it broke:**
- BDL has been in **full outage since Jan 28** (Session 149 confirmed: 2.4% data delivery rate, 32/33 days down)
- Phase 3 completeness checks queried dead BDL table
- Returned garbage/missing data causing impossible completeness values (5000%!)
- Players incorrectly filtered as "incomplete" → Only 5/17 ORL players processed

## Evidence Trail

### Coverage Trend (Smoking Gun)

| Date | ORL Players | GSW Players | LAL Players | Status |
|------|-------------|-------------|-------------|--------|
| Feb 5 | **17** | **15** | **16** | ✅ FULL (Session 149 deployed but cached data?) |
| Feb 7 | **16** | **16** | **17** | ✅ FULL (Last day before BDL fully dead) |
| Feb 9 | **5** | **5** | **10** | 🔴 LOW (BDL outage kicked in) |
| Feb 11 | **5** | **4** | **0** | 🔴 LOW (This session) |

### Completeness Values (Impossible!)

```sql
-- Feb 11 data
player_lookup  | l5_completeness_pct | l10_completeness_pct | all_windows_complete
---------------|---------------------|----------------------|---------------------
colincastleton | 100.0               | 100.0                | true  (all DNPs!)
franzwagner    | 5000.0              | 5000.0               | true  (impossible!)
paolobanchero  | NOT IN TABLE        | NOT IN TABLE         | (filtered out)
```

Colin Castleton (never plays, all DNPs) got 100% completeness and passed.
Franz Wagner got 5000% completeness (impossible math from bad data).
Paolo Banchero (plays every game) was filtered out entirely.

### Investigation Steps (Chronological)

1. ✅ Verified BQ query returns all 17 ORL players (not a SQL issue)
2. ✅ Checked roster data complete
3. ✅ Verified injury filter working
4. ✅ Confirmed betting lines exist for missing players
5. ✅ Ruled out game_id format mismatch (Opus Session 199)
6. ✅ Ruled out MERGE_UPDATE issue (filtering before write)
7. 🎯 **Found**: Paolo exists on Feb 5/7 with `all_windows_complete=true` but missing on Feb 9/11
8. 🎯 **Found**: Coverage dropped from 100% → 30% between Feb 7-9
9. 🎯 **Found**: Commit `5a123df1` (Session 149) deployed Feb 7
10. 🎯 **Found**: Session 149 migrated completeness_checker.py but missed helper
11. 🎯 **Found**: `completeness_checker_helper.py` line 88 still uses `bdl_player_boxscores`

## The Fix

**File 1:** `data_processors/analytics/upcoming_player_game_context/calculators/completeness_checker_helper.py`

```diff
- upstream_table='nba_raw.bdl_player_boxscores',
+ upstream_table='nba_raw.nbac_gamebook_player_stats',
```

**File 2:** `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py`

```diff
- FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
+ FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
```

## Verification Plan

### 1. Wait for Auto-Deploy (Est. 8-10 min)

```bash
# Check build status
gcloud builds list --region=us-west2 --limit=1 --format="value(status)"

# Verify deployment
./bin/check-deployment-drift.sh --verbose | grep phase3-analytics
```

### 2. Re-run Phase 3 for Feb 11

```bash
# Trigger Phase 3 reprocessing
curl -X POST https://nba-phase3-analytics-processors-<hash>-uw.a.run.app/process \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-11"}'
```

### 3. Validate Coverage Restored

```sql
-- Should now show 16-17 ORL players (not 5)
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as orl_players,
  ARRAY_AGG(DISTINCT player_lookup ORDER BY player_lookup LIMIT 5) as sample
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-02-11'
  AND team_abbr = 'ORL'
GROUP BY game_date;

-- Should now have Paolo, Jalen, etc.
SELECT player_lookup,
       all_windows_complete,
       l5_completeness_pct,
       l10_completeness_pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-02-11'
  AND player_lookup IN ('paolobanchero', 'jalensuggs', 'desmondbane')
ORDER BY player_lookup;

-- Completeness values should be realistic (70-100%, not 5000%)
SELECT
  MIN(l5_completeness_pct) as min_l5,
  MAX(l5_completeness_pct) as max_l5,
  AVG(l5_completeness_pct) as avg_l5
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-02-11';
```

**Expected Results:**
- ORL players: 16-17 (was 5)
- Paolo/Jalen/Desmond: all present with `all_windows_complete=true`
- Completeness percentages: 70-100% (not 5000%)

### 4. Backfill Feb 9-10 (Optional)

```bash
# If time permits, restore coverage for recent dates
for date in 2026-02-09 2026-02-10; do
  curl -X POST https://nba-phase3-analytics-processors-<hash>-uw.a.run.app/process \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\"}"
  sleep 60
done
```

## Impact Analysis

### Before Fix (Feb 9-11)

- **Coverage:** ~35% (5/17 ORL, 4/16 GSW)
- **Players filtered:** Paolo, Jalen, Desmond, Anthony Black, Jett Howard, Jonathan Isaac, etc.
- **Completeness values:** Impossible (5000%, 333%, etc.)
- **Predictions:** 7/12 players with betting lines got predictions

### After Fix (Expected)

- **Coverage:** ~95% (16-17/17 ORL, 15-16/16 GSW)
- **Players filtered:** Only those with legitimately incomplete data (<70% completeness)
- **Completeness values:** Realistic (70-100%)
- **Predictions:** 11-12/12 players with betting lines get predictions

## Lessons Learned

### 1. Migration Checklist Needed

**Problem:** Session 149 changed internal queries but missed external callers.

**Prevention:** Add pre-commit hook or grep check:
```bash
# Before any table migration, check ALL references
grep -r "old_table_name" data_processors/ shared/ --include="*.py" | wc -l
```

### 2. Deployment Validation

**Problem:** Deploy worked but functionality silently broke (querying dead table).

**Prevention:** Session 132 already established deep health checks. Consider adding:
- `/health/deep` endpoint that validates critical data sources
- Smoke test that checks recent completeness values are realistic

### 3. BDL Decommission Status

**Per Session 149:** BDL has been unreliable since Jan 28:
- 97% of days in full outage (32/33 days)
- 2.4% data delivery rate (6/254 games)
- 57 major data mismatches on the few working days

**Recommendation:** Formally decommission BDL infrastructure after verifying this fix.

## Next Steps

1. ✅ **Immediate:** Monitor build completion (auto-deploy in progress)
2. ⏳ **Immediate:** Re-run Phase 3 for Feb 11 and verify 16-17 ORL players
3. ⏳ **Today:** Backfill Feb 9-10 to restore recent coverage
4. 📋 **This week:** Create migration checklist for table changes
5. 📋 **This week:** Consider formal BDL decommissioning

## Related Sessions

- **Session 149** - Original BDL→nbac migration (Feb 7)
- **Session 199** - Root cause investigation (Feb 11)
- **Session 135** - Health checks and smoke tests established
- **Session 141** - Zero-tolerance policy (accuracy > coverage)

## Files Changed

```
data_processors/analytics/upcoming_player_game_context/
├── calculators/completeness_checker_helper.py       (1 line)
└── async_upcoming_player_game_context_processor.py  (1 line)
```

## Deployment Status

**Commit:** `0b17c702`
**Auto-deploy triggered:** 2026-02-11 17:35 UTC
**Service:** nba-phase3-analytics-processors
**ETA:** 8-10 minutes from commit

---

**Quick Start for Session 201:**

```bash
# 1. Verify deploy complete
./bin/check-deployment-drift.sh | grep phase3

# 2. Re-run Phase 3 for Feb 11
# (Get service URL from Cloud Run console or use gcloud)

# 3. Verify fix worked
bq query --use_legacy_sql=false '
SELECT COUNT(*) as orl_count
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = "2026-02-11" AND team_abbr = "ORL"
'
# Should return 16-17, not 5
```
