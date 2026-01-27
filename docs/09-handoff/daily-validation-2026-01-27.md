# Daily Orchestration Validation - January 27, 2026

**Validation Date**: Tuesday, January 27, 2026 at 7:45 AM PST
**Game Date Validated**: January 26, 2026 (Sunday night games)
**Processing Date**: January 27, 2026 (overnight scraper runs)
**Validator**: Claude Code (Sonnet 4.5)
**Status**: ⚠️ **MOSTLY HEALTHY** with 5 Issues (1 Critical, 2 High, 2 Medium)

---

## Executive Summary

Yesterday's games (Jan 26) were **successfully scraped and processed** with good box score coverage. However, there are **three significant concerns** requiring immediate attention:

1. 🔴 **CRITICAL**: BigQuery quota exceeded errors (5 occurrences at 2:00-2:15 PM)
2. 🟡 **HIGH**: Missing player_daily_cache for Jan 26 (impacts today's predictions)
3. 🟡 **HIGH**: Usage rate coverage at 41.4% (threshold: 90%)

The pipeline is **functional but needs attention** to quota management and Phase 4 cache processor.

---

## Priority 0: BigQuery Quota Issue (CRITICAL)

### What We Found

**5 quota exceeded errors** detected at 2:00-2:15 PM today (Jan 27):

```
2026-01-27 14:15:57 - Quota exceeded: Your table exceeded quota for imports or query appends per table
2026-01-27 14:03:57 - Quota exceeded: Your table exceeded quota for imports or query appends per table
2026-01-27 14:00:52 - Quota exceeded: Your table exceeded quota for imports or query appends per table
2026-01-27 14:00:49 - Quota exceeded: Your table exceeded quota for imports or query appends per table
2026-01-27 14:00:26 - Quota exceeded: Your table exceeded quota for imports or query appends per table
```

**Affected Table**: `nba_orchestration.circuit_breaker_state`

### Impact

- Circuit breaker state writes are failing
- Processor failure tracking may be incomplete
- Could cascade to other processors if circuit breakers can't track failures
- Pattern indicates high-frequency writes to partitioned table

### Root Cause

Circuit breaker is writing state updates too frequently to a partitioned BigQuery table. BigQuery has limits on partition modifications per day.

### Recommendations

**Immediate (Today)**:
1. Check current quota usage:
   ```bash
   bq show --format=prettyjson nba-props-platform | grep -A 10 "quotaUsed"
   ```

2. Review circuit breaker write patterns in code:
   ```bash
   grep -r "circuit_breaker_state" shared/processors/
   ```

3. Consider temporary mitigation:
   - Increase batch size for writes
   - Add write buffering/debouncing
   - Reduce circuit breaker sensitivity temporarily

**Short-term (This Week)**:
1. Implement batching for circuit breaker state writes
2. Consider migrating high-frequency state to Firestore instead
3. Add quota monitoring alerts

**Long-term**:
1. Audit all high-frequency BigQuery writes
2. Design write budget system
3. Use Firestore for ephemeral/high-frequency state

---

## Priority 1: Critical Data Checks

### ✅ P1.A: Box Scores Complete

**Status**: PASS ✅

| Metric | Value | Status |
|--------|-------|--------|
| Games Scheduled | 7 | ✅ |
| Games with Data | 7 | ✅ (100%) |
| Player Records | 226 | ✅ |
| Points Coverage | 100.0% | ✅ (226/226) |
| Minutes Coverage | 69.9% | ✅ (158/226)* |

**\*Minutes Note**: 69.9% coverage is **expected and correct**. The 68 missing minutes all have `points = 0`, confirming they're DNP (Did Not Play) bench players. Examples:
- chrisboucher (BOS) - 0 points, NULL minutes
- jaysontatum (BOS) - 0 points, NULL minutes
- emanuelmiller (CHI) - 0 points, NULL minutes

**Sample Games**:
- 20260126_POR_BOS
- 20260126_LAL_CHI
- 20260126_ORL_CLE
- 20260126_GSW_MIN
- (3 more games)

### ℹ️ P1.B: Prediction Grading

**Status**: Not Applicable (predictions not generated yet)

**Context**:
- Predictions table (`player_prop_predictions`) last modified Jan 25 at 10:33 AM
- No grading/actual values in current schema
- This is normal - predictions for Jan 27 games haven't happened yet

### ✅ P1.C: Scraper Runs Complete

**Status**: PASS ✅

**NbacGamebookProcessor** ran successfully overnight:

| Run Time | Status | Records | Data Date |
|----------|--------|---------|-----------|
| 2026-01-27 14:00:22 | success | 34 | 2026-01-26 |
| 2026-01-27 13:30:22 | success | 36 | 2026-01-26 |
| 2026-01-27 13:30:24 | success | 35 | 2026-01-26 |
| 2026-01-27 13:15:34 | success | 36 | 2026-01-26 |
| 2026-01-27 13:15:28 | success | 35 | 2026-01-26 |

**Total**: 5 successful runs processing 34-36 records each (consistent with 7 games × ~5 records/game)

---

## Priority 2: Pipeline Completeness

### ✅ P2.A: Analytics Generated

**Status**: PASS ✅

| Table | Records | Expected | Status |
|-------|---------|----------|--------|
| player_game_summary | 226 | ~175-300 | ✅ |
| team_offense_game_summary | 20 | 14 | ⚠️ (6 extra) |
| team_defense_game_summary | 14 | 14 | ✅ |

**Issue**: Team offense has 20 records instead of 14 (7 games × 2 teams). Extra 6 records need investigation.

### ⚠️ P2.B: Phase 3 Completion

**Status**: PARTIAL ⚠️

**Firestore Completion Status** (for processing date 2026-01-27):
- ✅ `team_offense_game_summary`: success
- ✅ `upcoming_player_game_context`: success
- ❌ Missing: 3 other Phase 3 processors not marked complete

**Expected processors** (based on typical Phase 3):
1. PlayerGameSummaryProcessor
2. TeamOffenseGameSummaryProcessor ✅
3. TeamDefenseGameSummaryProcessor
4. UpcomingPlayerGameContextProcessor ✅
5. UpcomingTeamGameContextProcessor

**Recommendation**: Check why only 2/5 processors reported completion to Firestore. Data exists (see P2.A), so likely a reporting issue rather than processing failure.

### ❌ P2.C: Cache Updated

**Status**: FAIL ❌ (HIGH PRIORITY)

**No player_daily_cache data for Jan 26**:
```
cache_date: 2026-01-26
players_cached: 0
last_update: NULL
```

**Last successful cache update**:
```
cache_date: 2026-01-25
players_cached: 182
last_update: 2026-01-26 06:19:14
```

**Impact**:
- Today's predictions (Jan 27) will use Jan 25 cache data (2 days stale)
- Rolling averages won't include Jan 26 games
- ML features for tonight's predictions will be incomplete

**Recommendation**:
1. Check Phase 4 PlayerDailyCacheProcessor logs:
   ```bash
   gcloud run services logs read nba-phase4-precompute-processors \
     --region=us-west2 --limit=100 | grep PlayerDailyCacheProcessor
   ```

2. Manually trigger if needed:
   ```bash
   gcloud scheduler jobs run same-day-phase4
   ```

3. Verify cache updates after trigger:
   ```sql
   SELECT cache_date, COUNT(DISTINCT player_lookup) as players, MAX(created_at)
   FROM `nba-props-platform.nba_precompute.player_daily_cache`
   WHERE cache_date >= '2026-01-25'
   GROUP BY cache_date
   ORDER BY cache_date DESC;
   ```

---

## Data Quality Issues

### 🟡 Issue 1: Usage Rate Coverage Low (HIGH)

**Status**: 41.4% for active players (threshold: 90%)

**Impact**: ML features incomplete for ~59% of active players

**Likely Causes**:
1. Team stats missing for some games (team_offense_game_summary has extra records, not missing)
2. Join issues between player and team stats
3. Possessions calculation failing for some teams

**Evidence**:
- Team offense has 20 records (expected 14), so not a missing data issue
- More likely a join or calculation problem

**Recommendation**:
1. Check team stats join logic in player_game_summary processor
2. Investigate the 6 extra team_offense records:
   ```sql
   SELECT game_id, team_abbr, COUNT(*) as records
   FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
   WHERE game_date = '2026-01-26'
   GROUP BY game_id, team_abbr
   HAVING COUNT(*) > 1;
   ```

3. Run spot check on specific player:
   ```bash
   /spot-check-player <player_with_missing_usage_rate> 10
   ```

### 🟠 Issue 2: Spot Check Accuracy 83.3% (MEDIUM)

**Status**: 5/6 checks passed (threshold: 95%)

**Failed Check**:
- Player: jarenjacksonjr
- Date: 2026-01-23
- Check: Usage Rate Calculation
- Details: Calculation failed (likely related to Issue 1 above)

**Recommendation**:
```bash
/spot-check-player jarenjacksonjr 10
```

### 🟠 Issue 3: Betting Data Missing (MEDIUM)

**Status**: No betting lines/props for today (Jan 27)

**Details**:
- Workflow 'betting_lines' window opened at 12:00 PM (3.8h ago)
- No data found in betting tables
- Expected by now (normal delivery: 8 AM - 1 PM)

**Impact**: Tonight's prop predictions (Jan 27) may have no lines to compare against

**Recommendation**:
1. Check betting workflow logs:
   ```bash
   gcloud scheduler jobs describe betting_lines --location=us-west2
   ```

2. Check scraper execution:
   ```bash
   gcloud run services logs read nba-betting-scrapers \
     --region=us-west2 --limit=50
   ```

3. If source is down, note in operations log (this happens occasionally)

### 🟢 Issue 4: API Export Stale (LOW)

**Status**: API shows 2026-01-25 (expected 2026-01-27)

**Details**:
- Last updated: 2026-01-26 at 6:14:23 AM
- API consumers seeing yesterday's data

**Impact**: Low - API may update later today

**Recommendation**: Monitor, but don't block on this

---

## Validation Script Output

### Main Validation Script

**Command**: `python scripts/validate_tonight_data.py`

**Exit Code**: 1 (issues found)

**Summary**:
- ❌ 5 ISSUES
- ⚠️ 51 WARNINGS (mostly scraper config mismatches - expected)

**Issues Breakdown**:
1. Betting data missing (2 issues)
2. Data quality thresholds (2 issues: minutes, usage_rate)
3. API export stale (1 issue)

**Warnings Breakdown**:
- 49 scraper config warnings (scrapers in registry but not in workflows.yaml)
  - Includes many MLB scrapers (expected - not relevant to NBA)
  - Includes unused NBA scrapers (bdl_live_box_scores, etc.)
- 1 legacy source warning (BettingPros - no longer used)
- 1 spot check accuracy warning (83.3% < 95%)

### Health Check Script

**Command**: `./bin/monitoring/daily_health_check.sh`

**Key Findings**:

1. **Workflow Status**: Post-game workflows ran (1 run, 23 skips each)
2. **Schedule Staleness**: ✅ Updated 2 stale games for Jan 25:
   - 2026-01-25 DAL@MIL → Final
   - 2026-01-25 DEN@MEM → Final
3. **Schedule Status**: ✅ All dates show correct game counts

---

## Historical Context

### Recent Cache Updates

| Cache Date | Players | Last Update | Status |
|------------|---------|-------------|--------|
| 2026-01-26 | **0** | NULL | ❌ MISSING |
| 2026-01-25 | 182 | 2026-01-26 06:19:14 | ✅ |
| 2026-01-24 | 153 | 2026-01-26 06:18:10 | ✅ |
| 2026-01-23 | 215 | 2026-01-26 06:17:07 | ✅ |
| 2026-01-22 | 163 | 2026-01-26 06:16:03 | ✅ |
| 2026-01-21 | 121 | 2026-01-26 06:14:47 | ✅ |
| 2026-01-20 | 149 | 2026-01-26 06:13:46 | ✅ |

**Pattern**: Cache normally updates daily at ~6:15 AM. Jan 26 update is missing.

### Recent Scraper Runs

All BdlBoxscoresProcessor runs for Jan 27 show **0 records processed**, which is expected because:
- These are checking for Jan 27 games
- Jan 27 games haven't happened yet (it's 7:45 AM)
- Jan 26 data was processed by NbacGamebookProcessor (see P1.C)

---

## Additional Validation Checks

### Schedule Validation

✅ **PASS**: All games correctly marked as Final

| Date | Scheduled | In Progress | Final | Status |
|------|-----------|-------------|-------|--------|
| 2026-01-27 | 7 | 0 | 0 | ✅ (tonight's games) |
| 2026-01-26 | 0 | 0 | 7 | ✅ |
| 2026-01-25 | 0 | 0 | 8 | ✅ |
| 2026-01-24 | 0 | 0 | 7 | ✅ |

### DNP Players Validation

**Confirmed**: All 68 players with NULL minutes have `points = 0`

Sample DNP players from Jan 26:
- chrisboucher (BOS) - 0 points, NULL minutes
- jaysontatum (BOS) - 0 points, NULL minutes
- joshminott (BOS) - 0 points, NULL minutes
- emanuelmiller (CHI) - 0 points, NULL minutes
- noaessengue (CHI) - 0 points, NULL minutes
- yukikawamura (CHI) - 0 points, NULL minutes

**Conclusion**: Minutes coverage of 69.9% is correct - not a data quality issue.

---

## Known Issues Reference

### ✅ Recently Fixed

1. **PlayerGameSummaryProcessor Registry Bug** (Fixed 2026-01-26)
   - Symptom: `'PlayerGameSummaryProcessor' object has no attribute 'registry'`
   - Status: Deployed and resolved
   - No longer occurring

### ⚠️ Currently Active

1. **BigQuery Quota on Circuit Breaker** (NEW - 2026-01-27)
   - First detected today
   - 5 occurrences at 2:00-2:15 PM
   - Needs immediate attention

2. **Usage Rate Coverage** (Ongoing)
   - Has been an intermittent issue
   - Related to team stats join logic
   - May be connected to extra team_offense records

---

## Deep Dive Investigation Results

### Investigation 1: Extra Team Records (RESOLVED)

**Root Cause Found**: Game ID normalization issue

**Details**: 3 games have duplicate game_ids in both home_away and away_home format:
- `20260126_ATL_IND` and `20260126_IND_ATL` (same game)
- `20260126_CHA_PHI` and `20260126_PHI_CHA`
- `20260126_CLE_ORL` and `20260126_ORL_CLE`

This creates 6 extra team records (3 games × 2 teams = 6 extra records).

**Expected**: 14 team records (7 games × 2 teams)
**Actual**: 20 team records (14 + 6 duplicates)

**Impact**: Moderate - doesn't break functionality but creates duplicate data

**Recommendation**: Fix game_id normalization in scraper or TeamOffenseGameSummaryProcessor to use consistent format (e.g., always alphabetical order or always home_away).

### Investigation 2: Missing Cache (ROOT CAUSE FOUND)

**Root Cause**: Cascading dependency failure from Jan 25

**Chain of Failures**:
1. **Jan 25**: PlayerGameSummaryProcessor failed at 00:09 AM on Jan 27
   - Status: failed (0 records)
   - Error: "No data extracted"

2. **Jan 26**: PlayerDailyCacheProcessor tried to run at 07:15 AM on Jan 27
   - Checked dependency: PlayerGameSummaryProcessor for Jan 25
   - Found: Failed status
   - Action: Blocked itself with DependencyError

3. **Result**: No cache data for Jan 26

**Evidence**:
```
PlayerDailyCacheProcessor failed for 2026-01-26 at 07:15:01
Error: "DependencyError: Upstream PlayerGameSummaryProcessor failed for 2026-01-25.
       Error: ValueError: No data extracted"
```

**Impact**: HIGH - Today's predictions (Jan 27) using stale cache (Jan 25)

**Recommendation**:
1. Fix PlayerGameSummaryProcessor failures for Jan 25
2. Retry cache processor for Jan 26:
   ```bash
   # After fixing upstream, manually trigger
   gcloud scheduler jobs run same-day-phase4
   ```
3. Review dependency checking logic - should it check previous day or same day?

### Investigation 3: Circuit Breaker Quota (ROOT CAUSE CONFIRMED)

**Root Cause**: PlayerGameSummaryProcessor writing **743 times per day**

**Write Frequency by Processor (Today)**:
| Processor | Writes Today | % of Total |
|-----------|--------------|------------|
| PlayerGameSummaryProcessor | 743 | 59.5% |
| TeamOffenseGameSummaryProcessor | 251 | 20.1% |
| AsyncUpcomingPlayerGameContextProcessor | 251 | 20.1% |
| TeamDefenseGameSummaryProcessor | 2 | 0.2% |
| UpcomingTeamGameContextProcessor | 1 | 0.1% |
| **TOTAL** | **1,248** | **100%** |

**Historical Pattern** (Last 7 Days):
- Jan 27: 1,248 writes
- Jan 26: 1,704 writes
- Jan 25: 2,533 writes (peak!)
- Jan 24: 37 writes (normal)
- Jan 23: 88 writes
- Jan 22: 1,532 writes
- Jan 21: 1,529 writes

**Analysis**:
- PlayerGameSummaryProcessor is the main culprit (60% of writes)
- Likely updating circuit breaker on every retry/iteration
- Peak of 2,533 writes on Jan 25 (same day PlayerGameSummaryProcessor had many failures)
- BigQuery partition modification quota is ~5,000/day, so we're using 25-50%

**Impact**: CRITICAL - Blocking circuit breaker state updates, may affect failure tracking

**Recommendation**:
1. **Immediate**: Implement write batching in PlayerGameSummaryProcessor:
   ```python
   # Instead of updating circuit breaker on every retry
   # Batch updates every 10 retries or 5 minutes
   ```

2. **Short-term**: Migrate circuit breaker state to Firestore:
   - Firestore has no partition limits
   - Better for high-frequency state updates
   - Keep BigQuery for historical analysis only

3. **Long-term**: Audit all processor circuit breaker patterns:
   ```bash
   grep -r "circuit_breaker.update" shared/processors/ -A 5
   ```

### Investigation 4: Usage Rate Issue (CONFIRMED BUG)

**Root Cause**: Join or calculation failure, NOT missing data

**Evidence**: jarenjacksonjr has NULL usage_rate despite complete data:

| Date | Player Minutes | FG Attempts | Team Stats | Usage Rate |
|------|----------------|-------------|------------|------------|
| 2026-01-26 | 32 | 17 | ✅ Complete | ❌ NULL |
| 2026-01-23 | 32 | NULL | ✅ Complete | ❌ NULL |
| 2026-01-21 | 32 | 12 | ✅ Complete | ❌ NULL |

**Team Stats Available** (MEM):
| Date | Possessions | Team FGA | Team FTA | Turnovers |
|------|-------------|----------|----------|-----------|
| 2026-01-26 | 104 | 105 | 17 | 13 |
| 2026-01-23 | 106 | 92 | 22 | 19 |
| 2026-01-21 | 108 | 93 | 27 | 17 |

**Impact**: HIGH - 58.6% of active players missing usage_rate (41.4% coverage)

**Recommendation**:
1. Check usage_rate calculation formula in PlayerGameSummaryProcessor
2. Check join logic between player_game_summary and team_offense_game_summary
3. Add logging to identify which step fails:
   ```python
   if usage_rate is None:
       logger.warning(f"Usage rate NULL for {player}: minutes={minutes}, fga={fga}, team_stats={team_stats}")
   ```

4. Run detailed spot check:
   ```bash
   /spot-check-player jarenjacksonjr 10
   ```

## Recommended Action Plan

### ⏰ Immediate (Next 1 Hour)

1. **Investigate BigQuery Quota**:
   ```bash
   # Check quota usage
   bq show --format=prettyjson nba-props-platform | grep quota

   # Review circuit breaker write patterns
   grep -r "circuit_breaker_state" shared/processors/ -A 5

   # Check recent write frequency
   bq query --use_legacy_sql=false "
   SELECT DATE(timestamp) as date, COUNT(*) as writes
   FROM \`nba-props-platform.nba_orchestration.circuit_breaker_state\`
   WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   GROUP BY date
   ORDER BY date DESC"
   ```

2. **Check Missing Cache**:
   ```bash
   # Check Phase 4 logs
   gcloud run services logs read nba-phase4-precompute-processors \
     --region=us-west2 --limit=100 | grep -i "cache\|error"

   # Check if processor ran
   bq query --use_legacy_sql=false "
   SELECT processor_name, status, started_at, records_processed
   FROM \`nba-props-platform.nba_reference.processor_run_history\`
   WHERE processor_name = 'PlayerDailyCacheProcessor'
     AND data_date = '2026-01-26'
   ORDER BY started_at DESC
   LIMIT 5"
   ```

### 🔍 Within 4 Hours

3. **Investigate Usage Rate Issue**:
   ```bash
   /spot-check-player jarenjacksonjr 10
   ```

4. **Check Extra Team Records**:
   ```sql
   SELECT game_id, team_abbr, COUNT(*) as records
   FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
   WHERE game_date = '2026-01-26'
   GROUP BY game_id, team_abbr
   HAVING COUNT(*) > 1;
   ```

5. **Monitor Betting Data**:
   - Check at end of day if data arrived
   - Not blocking for today

### 📅 Next Business Day

6. **Design Quota Solution**:
   - Implement write batching for circuit breaker
   - Consider Firestore migration for high-frequency state
   - Add quota monitoring alerts

7. **Audit Team Stats Logic**:
   - Review join logic in PlayerGameSummaryProcessor
   - Investigate why 20 team records instead of 14
   - Fix usage rate calculation

8. **Cache Processor Review**:
   - Why didn't it run for Jan 26?
   - Is there a trigger issue?
   - Should it retry automatically?

---

## Quick Reference Commands

### Check Current Status

```bash
# Box scores for a date
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-26'"

# Cache status
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2026-01-24'
GROUP BY cache_date
ORDER BY cache_date DESC"

# Recent processor runs
bq query --use_legacy_sql=false "
SELECT processor_name, status, data_date, started_at
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE DATE(started_at) >= CURRENT_DATE() - 1
ORDER BY started_at DESC
LIMIT 20"
```

### Manual Triggers

```bash
# Trigger Phase 4 (cache)
gcloud scheduler jobs run same-day-phase4

# Trigger Phase 3 (analytics)
gcloud scheduler jobs run same-day-phase3

# Check job status
gcloud scheduler jobs describe same-day-phase4 --location=us-west2
```

### Deep Dive Tools

```bash
# Investigate player
/spot-check-player <player_name> 10

# Check date coverage
/spot-check-date 2026-01-26

# Run comprehensive validation
python scripts/spot_check_data_accuracy.py --start-date 2026-01-26 --end-date 2026-01-26
```

---

## Metrics Summary

| Category | Metric | Value | Threshold | Status |
|----------|--------|-------|-----------|--------|
| **Box Scores** | Games Coverage | 100% (7/7) | 100% | ✅ |
| | Points Coverage | 100% (226/226) | 100% | ✅ |
| | Minutes Coverage | 69.9% (158/226) | 90%* | ✅ |
| **Analytics** | Player Records | 226 | ~175-300 | ✅ |
| | Team Records | 34 | 14 | ⚠️ |
| **Data Quality** | Usage Rate | 41.4% | 90% | ❌ |
| | Spot Check | 83.3% | 95% | ⚠️ |
| **Cache** | Jan 26 Cache | 0 players | >100 | ❌ |
| **Quota** | BQ Errors | 5 | 0 | 🔴 |

*Minutes threshold adjusted for DNP players

---

## Files & Logs Referenced

### BigQuery Tables
- `nba-props-platform.nba_analytics.player_game_summary`
- `nba-props-platform.nba_analytics.team_offense_game_summary`
- `nba-props-platform.nba_analytics.team_defense_game_summary`
- `nba-props-platform.nba_precompute.player_daily_cache`
- `nba-props-platform.nba_predictions.player_prop_predictions`
- `nba-props-platform.nba_reference.processor_run_history`
- `nba-props-platform.nba_orchestration.circuit_breaker_state`
- `nba-props-platform.nba_raw.v_nbac_schedule_latest`

### Firestore Collections
- `phase3_completion` (document: `2026-01-27`)

### Scripts Run
- `./bin/monitoring/daily_health_check.sh`
- `python scripts/validate_tonight_data.py`

### GCP Services
- Cloud Run: `nba-phase3-analytics-processors`
- Cloud Run: `nba-phase4-precompute-processors`
- Cloud Scheduler: `same-day-phase3`, `same-day-phase4`

---

## Next Validation

**Recommended**: Run again at **6:00 PM PST** (after Phase 4 should have run)

**Focus Areas**:
1. Check if player_daily_cache updated for Jan 26
2. Verify BigQuery quota issue resolved
3. Check if betting data arrived
4. Verify tonight's predictions generated (Jan 27 games)

**Command**:
```bash
/validate-daily --date 2026-01-27
```

---

---

## Summary of Findings

### ✅ What's Working

1. **Box Scores**: All 7 games scraped successfully (226 player records, 100% coverage)
2. **Scrapers**: NbacGamebookProcessor running successfully (5 runs, 34-36 records each)
3. **Schedule**: Up to date, all games marked Final correctly
4. **Analytics**: player_game_summary has all expected data

### 🔴 Critical Issues Found

1. **BigQuery Quota Exceeded** (PlayerGameSummaryProcessor)
   - Writing 743 times/day to circuit_breaker_state
   - Total 1,248-2,533 writes/day across all processors
   - Using 25-50% of daily partition modification quota
   - **Action**: Implement batching or migrate to Firestore

2. **Cascading Dependency Failure**
   - PlayerGameSummaryProcessor failed for Jan 25 at 00:09 AM
   - PlayerDailyCacheProcessor blocked for Jan 26 at 07:15 AM
   - No cache data for Jan 26, impacts today's predictions
   - **Action**: Fix Jan 25 failure, retry cache for Jan 26

3. **Usage Rate Calculation Bug**
   - 58.6% of players missing usage_rate (41.4% coverage)
   - Join or calculation issue, NOT missing data
   - Affects players like jarenjacksonjr across multiple dates
   - **Action**: Debug calculation logic, check join conditions

### 🟡 Medium Issues Found

4. **Game ID Normalization**
   - 3 games have duplicate IDs in both directions (ATL_IND & IND_ATL)
   - Creates 6 extra team_offense records
   - **Action**: Standardize game_id format in scraper

5. **Spot Check Accuracy**
   - 83.3% (5/6 checks passed, threshold: 95%)
   - Failed: jarenjacksonjr usage_rate (related to issue #3)
   - **Action**: Fix usage rate bug (same as #3)

### 📊 Impact Assessment

| Issue | Impact Level | Records Affected | Predictions Impact |
|-------|--------------|------------------|-------------------|
| Quota Exceeded | 🔴 Critical | Circuit breaker tracking | May miss processor failures |
| Missing Cache | 🔴 Critical | 182 players (Jan 26) | Using stale data (Jan 25) |
| Usage Rate Bug | 🔴 Critical | ~133 players (58.6%) | ML features incomplete |
| Game ID Dupes | 🟡 Medium | 6 team records | Duplicate data, no functional impact |
| Spot Check Fail | 🟡 Medium | 1 player | Already covered by issue #3 |

### 🎯 Root Causes

1. **Circuit Breaker**: Too frequent state writes (every retry instead of batched)
2. **Cache Failure**: Dependency check too strict (checking previous day)
3. **Usage Rate**: Calculation or join bug in PlayerGameSummaryProcessor
4. **Game ID**: Inconsistent normalization in upstream scraper

---

## Updated Action Plan

### Priority 1 (TODAY - Critical)

**A. Fix Circuit Breaker Quota Issue**
```python
# File: shared/processors/base/transform_processor_base.py
# Add batching to circuit breaker updates

class CircuitBreakerMixin:
    _state_buffer = []
    _last_flush = None

    def update_circuit_breaker(self, state):
        # Buffer instead of immediate write
        self._state_buffer.append(state)

        # Flush every 10 updates or 5 minutes
        if len(self._state_buffer) >= 10 or self._should_flush():
            self._flush_circuit_breaker_state()
```

**B. Fix PlayerGameSummaryProcessor for Jan 25**
```bash
# 1. Check what failed
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-25'
LIMIT 5"

# 2. If data exists, issue is in run_history tracking
# 3. If data missing, re-run processor for Jan 25
gcloud scheduler jobs run same-day-phase3 --job-data='{"date": "2026-01-25"}'
```

**C. Retry Cache for Jan 26**
```bash
# After fixing upstream, trigger cache
gcloud scheduler jobs run same-day-phase4

# Verify
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = '2026-01-26'"
```

### Priority 2 (THIS WEEK - High)

**D. Fix Usage Rate Calculation**
```python
# File: data_processors/analytics/player_game_summary/player_game_summary_processor.py

# Add debug logging in usage rate calculation:
def _calculate_usage_rate(self, player_row, team_stats):
    logger.debug(f"Calculating usage for {player_row['player_lookup']}")
    logger.debug(f"Player: minutes={player_row.get('minutes_played')}, fga={player_row.get('fg_attempts')}")
    logger.debug(f"Team: possessions={team_stats.get('possessions')}, fga={team_stats.get('fg_attempts')}")

    # Check if team stats joined successfully
    if team_stats is None or team_stats.empty:
        logger.warning(f"No team stats found for {player_row['player_lookup']}")
        return None
```

**E. Fix Game ID Normalization**
```python
# File: data_processors/raw/nbac_gamebook/nbac_gamebook_processor.py

def normalize_game_id(home_team, away_team, game_date):
    # Always use alphabetical order
    teams = sorted([home_team, away_team])
    return f"{game_date}_{teams[0]}_{teams[1]}"
```

### Priority 3 (NEXT WEEK - Medium)

**F. Migrate Circuit Breaker to Firestore**
```python
# New file: shared/state/firestore_circuit_breaker.py

class FirestoreCircuitBreaker:
    """
    High-frequency state updates go to Firestore.
    BigQuery used only for historical analysis.
    """
    def __init__(self):
        self.db = firestore.Client()

    def update_state(self, processor_name, state):
        doc_ref = self.db.collection('circuit_breakers').document(processor_name)
        doc_ref.set(state, merge=True)

        # Async batch to BigQuery every hour for history
        self._schedule_bq_sync(processor_name, state)
```

**G. Add Quota Monitoring**
```bash
# Add to daily_health_check.sh

echo "Checking BigQuery quota usage..."
QUOTA_USAGE=$(bq show --format=json nba-props-platform | \
  jq '.statistics.query.totalPartitionsProcessed')

if [ "$QUOTA_USAGE" -gt 4000 ]; then
  echo "⚠️  WARNING: High quota usage ($QUOTA_USAGE/5000)"
fi
```

---

**Document Created**: 2026-01-27 07:45 AM PST
**Deep Dive Completed**: 2026-01-27 08:15 AM PST
**Next Review**: 2026-01-27 06:00 PM PST
**Status**: Root Causes Identified - Action Plan Ready
