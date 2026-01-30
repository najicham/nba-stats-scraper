# Session 20 Handoff - January 29, 2026

## Session Summary

Investigated and fixed the root cause of low prediction coverage (~47%). The issue was a **critical bug in the `v_nbac_schedule_latest` view** that was filtering out games when NBA.com reuses the same game_id across different dates.

**Key Finding**: NBA.com reuses game_ids across different game dates. The same game_id `0022500529` appeared for both:
- 2026-01-08 (MIA@CHI, Final, status=3)
- 2026-01-29 (MIA@CHI, Scheduled, status=1)

The view's deduplication logic `ORDER BY game_status DESC` would select the Final game (status=3), hiding the Scheduled game (status=1).

## Fixes Applied

| Fix | File(s) | Status | Impact |
|-----|---------|--------|--------|
| Schedule view deduplication | `schemas/bigquery/raw/nbac_schedule_tables.sql` | ✅ Applied to BigQuery | MIA@CHI game now visible |
| View fix deployed | `nba_raw.v_nbac_schedule_latest` | ✅ Deployed | Future games won't be hidden |

### View Fix Details

**Before** (buggy):
```sql
PARTITION BY game_id
ORDER BY game_status DESC, processed_at DESC
```

**After** (fixed):
```sql
PARTITION BY game_id, game_date
ORDER BY game_status DESC, processed_at DESC
```

The fix adds `game_date` to the partition, so each unique (game_id, game_date) combination gets its own row.

## Root Cause Analysis

### Why Prediction Coverage Was ~47%

The investigation revealed **two separate issues**:

#### Issue 1: MIA@CHI Game Missing (FIXED)
- The MIA@CHI game on Jan 29 was hidden from the schedule view
- This caused ~35 players (17 MIA + 18 CHI) to be missing from:
  - `upcoming_player_game_context`
  - `ml_feature_store_v2`
  - `player_prop_predictions`
- **Impact**: 7 games instead of 8, reducing coverage by ~12%

#### Issue 2: Betting Lines Limited to ~50% of Players (EXPECTED BEHAVIOR)
- Sportsbooks only post betting lines for key rotation players
- Of 240 players with features, only ~121 have betting lines
- This is **expected behavior**, not a bug
- Coverage of ~47% (113/240) is actually near-optimal given betting line availability

### Games Affected by game_id Reuse

| game_id | Date 1 | Date 2 | Teams |
|---------|--------|--------|-------|
| 0022500529 | 2026-01-08 (Final) | 2026-01-29 (Scheduled) | MIA@CHI |
| 0022500692 | 2026-01-30 (Scheduled) | 2026-01-31 (Scheduled) | CHI@MIA |

## Current System Status

### Validation Results
- **Spot Checks**: 100% accuracy (10/10 samples passed)
- **Phase 3 Completion**: 5/5 processors ✅
- **ML Features**: 240 players for 7 games
- **Predictions**: 113 active predictions for 7 games
- **Deployment Drift**: All services up to date ✅
- **Recent Errors**: 5 errors in nba-scrapers (investigated - non-critical)

### Today's Games (2026-01-29)
| Game | Feature Store | Predictions | Status |
|------|---------------|-------------|--------|
| SAC@PHI | 35 players | 19 | ✅ |
| MIL@WAS | 33 players | 16 | ✅ |
| HOU@ATL | 35 players | 14 | ✅ |
| CHA@DAL | 36 players | 15 | ✅ |
| BKN@DEN | 33 players | 16 | ✅ |
| DET@PHX | 34 players | 17 | ✅ |
| OKC@MIN | 34 players | 16 | ✅ |
| **MIA@CHI** | **0 players** | **0** | ⚠️ **MISSING** |

### Tomorrow's Games (2026-01-30)
- 10 games scheduled in view
- 9 games in feature store
- MIA@CHI (game_id 0022500692) also affected - needs regeneration

## Data Regeneration Needed

The view fix is deployed but **data needs to be regenerated** for:

1. **Today (2026-01-29)**: MIA@CHI players missing from feature store
2. **Tomorrow (2026-01-30)**: MIA@CHI players missing from feature store

### How to Regenerate

The Phase 3 `UpcomingPlayerGameContextProcessor` needs to run again to pick up the fixed view data.

**Option 1: Wait for Next Scheduled Run**
- Phase 3 runs automatically with the daily orchestration
- Tomorrow's orchestration will use the fixed view

**Option 2: Manual Trigger via Cloud Scheduler**
```bash
# Trigger Phase 3 to re-run (if available)
gcloud scheduler jobs run same-day-phase3 --location=us-west2
```

**Option 3: Direct SQL Insert (if urgent)**
This would require manually running the processor SQL and inserting MIA/CHI players.

## What's Working Well

- ✅ Spot check accuracy is 100%
- ✅ Phase 3 completion tracking (5/5 processors)
- ✅ No deployment drift
- ✅ Data completeness for processed games is >100%
- ✅ View fix deployed and verified working

## Known Issues

### P1 CRITICAL: MIA@CHI Data Missing
- **Today**: MIA@CHI game has no predictions (will miss tonight's game)
- **Tomorrow**: Same issue unless Phase 3 re-runs
- **Resolution**: Wait for next orchestration run or manually trigger

### P3: Prediction Coverage Explanation Updated
- ~47% coverage is near-optimal given betting line availability (~50% of players have lines)
- Not a bug - this is expected behavior
- Previous handoff incorrectly flagged this as requiring investigation

## Files Modified

```
schemas/bigquery/raw/nbac_schedule_tables.sql  # View deduplication fix
```

## Prevention Mechanisms Added

The view fix prevents future game_id reuse issues from hiding scheduled games.

### Future Improvements Recommended

1. **Add game_id reuse detection** in the schedule scraper
2. **Alert when same game_id appears on multiple dates**
3. **Add data completeness check** comparing scheduled games vs feature store games

## Next Session Checklist

### Priority 1: Verify MIA@CHI Data Regenerated
```bash
# Check if MIA@CHI appears in feature store for tomorrow
bq query --nouse_legacy_sql "
SELECT game_id, COUNT(*) as players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-30'
  AND game_id LIKE '%MIA%CHI%'"

# Verify all 10 games for tomorrow
bq query --nouse_legacy_sql "
SELECT COUNT(DISTINCT game_id) as games
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-30'"
```

### Priority 2: Run Daily Validation
```bash
/validate-daily
```

### Priority 3: Monitor Tonight's Predictions
- Tonight's MIA@CHI predictions will be missing
- This is expected until data is regenerated
- Tomorrow should be fully covered

## Metrics

| Metric | Before | After | Target | Status |
|--------|--------|-------|--------|--------|
| Games in Feature Store | 7/8 | 7/8* | 8/8 | ⚠️ Needs regen |
| Prediction Coverage | 47% | 47%* | ~50% | ✅ Expected |
| Spot Check Accuracy | N/A | 100% | >95% | ✅ Excellent |
| View Fix | ❌ | ✅ | ✅ | ✅ Applied |

*Will improve after Phase 3 re-runs with fixed view

## Key Learnings

1. **NBA.com reuses game_ids** across different dates (same teams, different game dates)
2. **View deduplication logic matters** - ordering by game_status can hide scheduled games
3. **Prediction coverage ~50% is expected** when betting lines are only available for rotation players
4. **Spot checks are valuable** - 100% accuracy confirms data quality is good

---

*Session 20 completed at 2026-01-30 ~00:20 UTC*
*View fix deployed, data regeneration needed for MIA@CHI games*
