# Completeness Checking - Operational Runbook

**Version:** 1.0
**Last Updated:** 2025-11-22
**Maintainer:** Data Engineering Team

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Circuit Breaker Management](#circuit-breaker-management)
3. [Investigating Incomplete Data](#investigating-incomplete-data)
4. [Manual Override Procedures](#manual-override-procedures)
5. [Troubleshooting Guide](#troubleshooting-guide)
6. [Common Scenarios](#common-scenarios)
7. [Emergency Procedures](#emergency-procedures)
8. [Threshold Tuning](#threshold-tuning)

---

## Quick Reference

### Key Thresholds
- **Production Ready:** >= 90% completeness
- **Circuit Breaker Trips:** After 3 failed attempts
- **Cooldown Period:** 7 days
- **Bootstrap Mode:** First 30 days of season or backfill

### Critical Tables
- **Tracking:** `nba_orchestration.reprocess_attempts`
- **Phase 4 Precompute:** `nba_precompute.*`
- **Phase 3 Analytics:** `nba_analytics.*`
- **Predictions:** `nba_predictions.ml_feature_store_v2`

### Common Commands
```bash
# Check circuit breaker status
bq query --use_legacy_sql=false "
SELECT * FROM \`nba_orchestration.reprocess_attempts\`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY attempted_at DESC
LIMIT 20
"

# Check completeness for specific processor
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  analysis_date,
  completeness_percentage,
  is_production_ready,
  expected_games_count,
  actual_games_count,
  processing_decision_reason
FROM \`nba_precompute.player_daily_cache\`
WHERE analysis_date = CURRENT_DATE() - 1
  AND is_production_ready = FALSE
LIMIT 20
"
```

---

## Circuit Breaker Management

### Understanding Circuit Breaker States

**State 1: Normal (No Circuit Breaker)**
- `circuit_breaker_active = FALSE`
- `reprocess_attempt_count = 0`
- Entity processes normally

**State 2: Warning (1-2 Attempts)**
- `circuit_breaker_active = FALSE`
- `reprocess_attempt_count = 1 or 2`
- Entity still processes, but tracking failures
- **Action:** Monitor closely, investigate root cause

**State 3: Tripped (3+ Attempts)**
- `circuit_breaker_active = TRUE`
- `circuit_breaker_until = 7 days from last attempt`
- Entity BLOCKED from processing
- **Action:** Manual override required

### Checking Circuit Breaker Status

```sql
-- Find all active circuit breakers
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  circuit_breaker_until,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining
FROM `nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY circuit_breaker_until DESC;
```

### When Circuit Breaker SHOULD Trip
✅ **Valid Reasons:**
- Upstream data genuinely missing (scraper issues)
- Schedule changes (postponed/cancelled games)
- Late-season scenarios (teams resting players)
- Known data source outages

### When Circuit Breaker is FALSE POSITIVE
❌ **Invalid Triggers:**
- Season boundary issues (Oct 1 transition)
- Backfill first-run scenarios
- Timezone mismatches causing date alignment issues
- Bootstrap mode not detected correctly

---

## Investigating Incomplete Data

### Step 1: Identify the Problem

```sql
-- Get detailed completeness info for an entity
SELECT
  player_lookup,
  analysis_date,
  expected_games_count,
  actual_games_count,
  completeness_percentage,
  missing_games_count,
  is_production_ready,
  data_quality_issues,
  processing_decision_reason
FROM `nba_precompute.player_daily_cache`
WHERE player_lookup = 'lebron_james'
  AND analysis_date = '2024-12-15'
;
```

### Step 2: Check Upstream Data

```sql
-- Verify upstream data exists
SELECT
  player_lookup,
  game_date,
  COUNT(*) as record_count
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = 'lebron_james'
  AND game_date >= DATE_SUB('2024-12-15', INTERVAL 10 DAY)
  AND game_date < '2024-12-15'
GROUP BY player_lookup, game_date
ORDER BY game_date DESC;
```

### Step 3: Check Schedule

```sql
-- Verify expected games from schedule
SELECT
  game_date,
  home_team_abbr,
  away_team_abbr,
  game_status
FROM `nba_raw.nbac_schedule`
WHERE (home_team_abbr = 'LAL' OR away_team_abbr = 'LAL')
  AND game_date >= DATE_SUB('2024-12-15', INTERVAL 10 DAY)
  AND game_date < '2024-12-15'
ORDER BY game_date DESC;
```

### Step 4: Compare Expected vs Actual

```sql
-- Find missing games
WITH expected_games AS (
  SELECT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE (home_team_abbr = 'LAL' OR away_team_abbr = 'LAL')
    AND game_date >= DATE_SUB('2024-12-15', INTERVAL 10 DAY)
    AND game_date < '2024-12-15'
),
actual_games AS (
  SELECT DISTINCT game_date
  FROM `nba_analytics.player_game_summary`
  WHERE player_lookup = 'lebron_james'
    AND game_date >= DATE_SUB('2024-12-15', INTERVAL 10 DAY)
    AND game_date < '2024-12-15'
)
SELECT
  e.game_date,
  CASE WHEN a.game_date IS NULL THEN 'MISSING' ELSE 'PRESENT' END as status
FROM expected_games e
LEFT JOIN actual_games a ON e.game_date = a.game_date
ORDER BY e.game_date DESC;
```

---

## Manual Override Procedures

### Scenario 1: Override Circuit Breaker for Valid Entity

**When to Use:**
- Circuit breaker tripped due to false positive
- Upstream data now available (was temporarily missing)
- Bootstrap mode should have applied but didn't

**Procedure:**

```sql
-- Step 1: Verify entity is safe to override
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  circuit_breaker_until
FROM `nba_orchestration.reprocess_attempts`
WHERE processor_name = 'player_daily_cache'
  AND entity_id = 'lebron_james'
  AND analysis_date = '2024-12-15'
ORDER BY attempted_at DESC
LIMIT 1;

-- Step 2: Apply manual override
UPDATE `nba_orchestration.reprocess_attempts`
SET
  manual_override_applied = TRUE,
  notes = 'Override applied: Upstream data now available. Approved by [YOUR_NAME] on [DATE]'
WHERE processor_name = 'player_daily_cache'
  AND entity_id = 'lebron_james'
  AND analysis_date = '2024-12-15'
  AND circuit_breaker_tripped = TRUE;

-- Step 3: Verify override applied
SELECT
  processor_name,
  entity_id,
  analysis_date,
  manual_override_applied,
  notes
FROM `nba_orchestration.reprocess_attempts`
WHERE processor_name = 'player_daily_cache'
  AND entity_id = 'lebron_james'
  AND analysis_date = '2024-12-15'
ORDER BY attempted_at DESC
LIMIT 1;
```

**Important Notes:**
- Always document WHY you're overriding in the `notes` field
- Verify upstream data completeness before overriding
- Override does NOT automatically reprocess - you must trigger processor manually

### Scenario 2: Reset Circuit Breaker Entirely

**When to Use:**
- Circuit breaker logic had bugs (now fixed)
- Backfill scenario where all attempts should be reset
- Major data ingestion issue resolved

**Procedure:**

```sql
-- Nuclear option: Delete all circuit breaker attempts for entity
DELETE FROM `nba_orchestration.reprocess_attempts`
WHERE processor_name = 'player_daily_cache'
  AND entity_id = 'lebron_james'
  AND analysis_date = '2024-12-15';
```

**WARNING:** This is destructive. Only use when:
- You've thoroughly investigated
- You've documented the reason
- You've gotten approval from team lead

### Scenario 3: Bulk Override for Known Issue

**When to Use:**
- Scraper outage affected many entities
- Season boundary affected all players/teams
- Bootstrap mode detection failed systematically

**Procedure:**

```sql
-- Example: Override all circuit breakers from a specific date range
UPDATE `nba_orchestration.reprocess_attempts`
SET
  manual_override_applied = TRUE,
  notes = 'Bulk override: Scraper outage on 2024-12-10 resolved. All entities safe to reprocess. Approved by [YOUR_NAME] on [DATE]'
WHERE analysis_date BETWEEN '2024-12-10' AND '2024-12-15'
  AND circuit_breaker_tripped = TRUE
  AND skip_reason LIKE '%incomplete%';

-- Verify bulk override
SELECT
  processor_name,
  COUNT(*) as override_count
FROM `nba_orchestration.reprocess_attempts`
WHERE manual_override_applied = TRUE
  AND TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY) = TIMESTAMP_TRUNC(_PARTITIONTIME, DAY)
GROUP BY processor_name;
```

---

## Troubleshooting Guide

### Problem: Circuit Breaker Tripping Too Frequently

**Symptoms:**
- Many entities hitting 3 attempts quickly
- Circuit breaker table growing rapidly
- Production readiness percentage dropping

**Diagnosis:**
```sql
-- Check circuit breaker trip rate
SELECT
  processor_name,
  DATE(attempted_at) as attempt_date,
  COUNT(DISTINCT entity_id) as entities_attempted,
  SUM(CASE WHEN circuit_breaker_tripped THEN 1 ELSE 0 END) as circuit_breaker_count,
  ROUND(100.0 * SUM(CASE WHEN circuit_breaker_tripped THEN 1 ELSE 0 END) / COUNT(DISTINCT entity_id), 2) as trip_rate_pct
FROM `nba_orchestration.reprocess_attempts`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, DATE(attempted_at)
ORDER BY attempt_date DESC, trip_rate_pct DESC;
```

**Potential Causes:**
1. **Upstream scraper issues** - Check scraper health
2. **90% threshold too strict** - Consider lowering to 85% for specific processors
3. **Bootstrap mode not detecting correctly** - Check season_start_date logic
4. **Date alignment issues** - Verify timezone handling

**Solutions:**
- If scraper issue: Fix scraper, then bulk override circuit breakers
- If threshold issue: See [Threshold Tuning](#threshold-tuning)
- If bootstrap issue: Verify `season_start_date` is correct in processor initialization
- If date issue: Check timezone consistency between schedule and game data

---

### Problem: Completeness Percentage Always Low

**Symptoms:**
- Many entities at 70-80% completeness (below 90% threshold)
- Completeness not improving over time
- Expected vs actual counts consistently mismatched

**Diagnosis:**
```sql
-- Check completeness distribution
SELECT
  processor_name,
  CASE
    WHEN completeness_percentage >= 90 THEN '90-100%'
    WHEN completeness_percentage >= 80 THEN '80-90%'
    WHEN completeness_percentage >= 70 THEN '70-80%'
    WHEN completeness_percentage >= 60 THEN '60-70%'
    ELSE '<60%'
  END as completeness_bucket,
  COUNT(*) as entity_count
FROM (
  SELECT 'player_daily_cache' as processor_name, completeness_percentage
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'player_composite_factors' as processor_name, completeness_percentage
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1
  -- Add other processors...
)
GROUP BY processor_name, completeness_bucket
ORDER BY processor_name, completeness_bucket;
```

**Potential Causes:**
1. **Expected count calculation wrong** - CompletenessChecker counting games incorrectly
2. **Upstream table missing data** - Scraper not populating records
3. **Window type mismatch** - Using 'games' when should use 'days' (or vice versa)

**Solutions:**
1. Verify expected count calculation:
```sql
-- Compare CompletenessChecker logic vs actual schedule
WITH expected_from_schedule AS (
  SELECT
    'LAL' as team,
    COUNT(*) as expected_games
  FROM `nba_raw.nbac_schedule`
  WHERE (home_team_abbr = 'LAL' OR away_team_abbr = 'LAL')
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
    AND game_date < CURRENT_DATE()
)
SELECT * FROM expected_from_schedule;
```

2. Check upstream data:
```sql
-- Verify upstream table has data
SELECT
  COUNT(*) as record_count,
  COUNT(DISTINCT player_lookup) as unique_players,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

---

### Problem: Bootstrap Mode Not Activating

**Symptoms:**
- Early season processing being skipped
- `backfill_bootstrap_mode = FALSE` when should be TRUE
- Entities with low completeness being skipped in October

**Diagnosis:**
```sql
-- Check bootstrap mode detection
SELECT
  analysis_date,
  COUNT(*) as total_records,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_count,
  ROUND(100.0 * SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) / COUNT(*), 2) as bootstrap_pct
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN '2024-10-01' AND '2024-10-30'
GROUP BY analysis_date
ORDER BY analysis_date;
```

**Potential Causes:**
1. **season_start_date incorrect** - Hardcoded or wrong value
2. **Bootstrap logic not implemented** - Processor missing is_bootstrap check
3. **30-day window wrong** - Should be season_start + 30 days

**Solutions:**
1. Check processor initialization:
```python
# Verify season_start_date is set correctly
self.season_start_date = date(2024, 10, 1)  # Should match actual season start
```

2. Check bootstrap detection:
```python
# In calculate_precompute method
is_bootstrap = self.completeness_checker.is_bootstrap_mode(
    analysis_date, self.season_start_date
)
```

3. Manual override for early season:
```sql
-- Override early season circuit breakers
UPDATE `nba_orchestration.reprocess_attempts`
SET
  manual_override_applied = TRUE,
  notes = 'Early season bootstrap override - approved by [YOUR_NAME]'
WHERE analysis_date BETWEEN '2024-10-01' AND '2024-10-30'
  AND circuit_breaker_tripped = TRUE;
```

---

### Problem: Multi-Window Processor Always Failing

**Symptoms:**
- `all_windows_complete = FALSE` for all entities
- One specific window always incomplete (e.g., L30d)
- Other windows complete but overall production_ready = FALSE

**Diagnosis:**
```sql
-- Check which windows are failing
SELECT
  player_lookup,
  analysis_date,
  l5_completeness_pct,
  l5_is_complete,
  l10_completeness_pct,
  l10_is_complete,
  l7d_completeness_pct,
  l7d_is_complete,
  l14d_completeness_pct,
  l14d_is_complete,
  all_windows_complete
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE() - 1
  AND all_windows_complete = FALSE
LIMIT 20;
```

**Potential Causes:**
1. **One window has wrong parameters** - Check lookback_window value
2. **Window type mismatch** - 'games' vs 'days'
3. **Upstream table doesn't have enough history** - L30d requires 30+ days of data

**Solutions:**
1. Identify failing window:
```sql
-- Aggregate to see patterns
SELECT
  'L5' as window,
  AVG(l5_completeness_pct) as avg_pct,
  SUM(CASE WHEN l5_is_complete THEN 1 ELSE 0 END) as complete_count,
  COUNT(*) as total_count
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE() - 1
UNION ALL
SELECT
  'L10' as window,
  AVG(l10_completeness_pct) as avg_pct,
  SUM(CASE WHEN l10_is_complete THEN 1 ELSE 0 END) as complete_count,
  COUNT(*) as total_count
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE() - 1
-- ... repeat for all windows
ORDER BY avg_pct;
```

2. If one window consistently failing, consider:
   - Adjusting threshold for that specific window
   - Removing the window from production readiness check
   - Investigating upstream data quality

---

## Common Scenarios

### Scenario: New Season Starting

**Expected Behavior:**
- Bootstrap mode activates automatically for first 30 days
- Entities processed even with low completeness
- `backfill_bootstrap_mode = TRUE` in output

**Verification:**
```sql
-- Check bootstrap mode is working
SELECT
  analysis_date,
  COUNT(*) as total_records,
  AVG(completeness_percentage) as avg_completeness,
  SUM(CASE WHEN backfill_bootstrap_mode THEN 1 ELSE 0 END) as bootstrap_count
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date >= '2024-10-01'  -- Season start
  AND analysis_date < '2024-10-31'  -- First 30 days
GROUP BY analysis_date
ORDER BY analysis_date;
```

**Action Required:**
- None if bootstrap mode working correctly
- If not activating, check season_start_date in processor code

---

### Scenario: Scraper Outage (Missed Games)

**Expected Behavior:**
- Completeness percentage drops below 90%
- Entities skip processing (unless bootstrap mode)
- Circuit breaker tracking starts

**Immediate Actions:**

1. **Identify Impact:**
```sql
SELECT
  processor_name,
  COUNT(DISTINCT entity_id) as affected_entities,
  AVG(completeness_pct) as avg_completeness
FROM `nba_orchestration.reprocess_attempts`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY processor_name;
```

2. **Fix Scraper** - Ensure upstream data ingestion working

3. **Backfill Missing Data** - Run scraper backfill for missing dates

4. **Verify Data Restored:**
```sql
-- Check upstream data completeness
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

5. **Override Circuit Breakers (if needed):**
```sql
-- After data restored, override circuit breakers
UPDATE `nba_orchestration.reprocess_attempts`
SET
  manual_override_applied = TRUE,
  notes = 'Scraper outage resolved, data backfilled - approved by [YOUR_NAME]'
WHERE analysis_date >= '2024-12-10'
  AND skip_reason LIKE '%incomplete%'
  AND circuit_breaker_tripped = TRUE;
```

6. **Reprocess Affected Dates** - Manually trigger processors for affected dates

---

### Scenario: Postponed/Cancelled Game

**Expected Behavior:**
- Schedule shows game, but no game data exists
- Completeness percentage slightly lower (one missing game)
- May still be >= 90% depending on window size

**Action Required:**

1. **Verify Game Actually Postponed:**
```sql
SELECT
  game_date,
  home_team_abbr,
  away_team_abbr,
  game_status
FROM `nba_raw.nbac_schedule`
WHERE game_date = '2024-12-15'
  AND (home_team_abbr = 'LAL' OR away_team_abbr = 'LAL');
```

2. **If Legitimately Postponed:**
- Update schedule table to reflect game_status = 'POSTPONED'
- CompletenessChecker should exclude postponed games from expected count
- No override needed

3. **If Schedule Wrong:**
- Fix schedule data
- Reprocess affected entities

---

### Scenario: Player Load Management / Rest Day

**Expected Behavior:**
- Player has no game data for specific date
- Team has game, but player didn't play
- Completeness calculation should still count team's game

**Verification:**
```sql
-- Check if player played in team's game
SELECT
  p.game_date,
  p.player_lookup,
  p.minutes_played,
  s.home_team_abbr,
  s.away_team_abbr
FROM `nba_analytics.player_game_summary` p
LEFT JOIN `nba_raw.nbac_schedule` s
  ON p.game_date = s.game_date
  AND (s.home_team_abbr = p.team_abbr OR s.away_team_abbr = p.team_abbr)
WHERE p.player_lookup = 'lebron_james'
  AND p.game_date = '2024-12-15';
```

**Note:** If player didn't play (DNP), there may be no record. This is expected behavior. Completeness checking tracks team games, not player participation.

---

## Emergency Procedures

### Emergency: All Processors Failing (Mass Outage)

**Symptoms:**
- 90%+ of entities skipping processing
- Circuit breakers tripping across all processors
- Completeness percentages uniformly low

**Immediate Actions:**

1. **Check Upstream Data Health:**
```sql
-- Verify upstream tables have recent data
SELECT
  'player_game_summary' as table_name,
  MAX(game_date) as latest_date,
  COUNT(*) as record_count_last_24h
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
UNION ALL
SELECT
  'schedule' as table_name,
  MAX(game_date) as latest_date,
  COUNT(*) as record_count_last_24h
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
```

2. **Pause All Automated Processors** - Prevent more circuit breaker trips

3. **Escalate to On-Call Engineer** - This is not a completeness checking issue

4. **Document Incident:**
- Time outage detected
- Affected processors
- Upstream data status
- Actions taken

5. **After Resolution:**
- Bulk override circuit breakers (see [Bulk Override](#scenario-3-bulk-override-for-known-issue))
- Manually trigger backfill for affected dates
- Monitor completeness recovery

---

### Emergency: Circuit Breaker Table Growing Rapidly (Performance Issue)

**Symptoms:**
- `nba_orchestration.reprocess_attempts` table size exploding
- Queries against table slowing down
- Storage costs increasing

**Immediate Actions:**

1. **Check Table Size:**
```sql
SELECT
  ROUND(size_bytes / POW(10, 9), 2) as size_gb,
  row_count
FROM `nba-props-platform.nba_orchestration.__TABLES__`
WHERE table_id = 'reprocess_attempts';
```

2. **Identify Source of Growth:**
```sql
-- Check which processors contributing most
SELECT
  processor_name,
  COUNT(*) as attempt_count,
  COUNT(DISTINCT entity_id) as unique_entities,
  AVG(attempt_number) as avg_attempts
FROM `nba_orchestration.reprocess_attempts`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name
ORDER BY attempt_count DESC;
```

3. **Apply Retention Policy (if needed):**
```sql
-- Delete old attempts (>365 days per partition retention)
-- This should be automatic, but can manually trigger if needed
DELETE FROM `nba_orchestration.reprocess_attempts`
WHERE _PARTITIONTIME < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 365 DAY);
```

4. **Long-term Solution:**
- Verify partition expiration is set correctly (365 days)
- Consider reducing retention to 180 days if safe
- Add monitoring alerts for table growth

---

## Threshold Tuning

### When to Adjust the 90% Threshold

**Consider Lowering (to 85% or 80%) If:**
- Circuit breakers tripping frequently (>20% of entities)
- Completeness consistently 85-89% due to legitimate data gaps
- Early season scenarios common
- Load management causing systematic <90% patterns

**Consider Raising (to 95%) If:**
- Data quality extremely high
- Predictions require very complete data
- Circuit breakers rarely triggering (<5% of entities)

### How to Adjust Threshold

**Option 1: Global Change (Affects All Processors)**

Edit `shared/utils/completeness_checker.py`:
```python
# Line ~150 in check_completeness_batch method
is_production_ready = (completeness_pct >= 85.0 and actual_count >= min_required)
#                                        ^^^ Changed from 90.0
```

**Option 2: Processor-Specific Override**

In processor code (e.g., `player_daily_cache_processor.py`):
```python
# After batch completeness check
completeness = completeness_results.get(player_lookup)
if completeness:
    # Override production ready threshold for this processor
    if completeness['completeness_pct'] >= 85.0:  # Lower threshold
        completeness['is_production_ready'] = True
```

**Option 3: Window-Specific Override (Multi-Window Processors)**

```python
# For multi-window processors, adjust specific window thresholds
l30d_threshold = 80.0  # Lower threshold for L30d (harder to meet)
l5_threshold = 95.0    # Higher threshold for L5 (easier to meet)

all_windows_ready = (
    comp_l5['completeness_pct'] >= l5_threshold and
    comp_l10['is_production_ready'] and
    comp_l7d['is_production_ready'] and
    comp_l14d['is_production_ready'] and
    comp_l30d['completeness_pct'] >= l30d_threshold
)
```

### Testing Threshold Changes

**Before Deploying Threshold Change:**

1. **Analyze Impact:**
```sql
-- See how many additional entities would process with lower threshold
SELECT
  processor_name,
  threshold,
  entity_count
FROM (
  SELECT
    'player_daily_cache' as processor_name,
    '>=90%' as threshold,
    COUNT(*) as entity_count
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1
    AND completeness_percentage >= 90.0
  UNION ALL
  SELECT
    'player_daily_cache' as processor_name,
    '>=85%' as threshold,
    COUNT(*) as entity_count
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1
    AND completeness_percentage >= 85.0
  UNION ALL
  SELECT
    'player_daily_cache' as processor_name,
    '>=80%' as threshold,
    COUNT(*) as entity_count
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1
    AND completeness_percentage >= 80.0
);
```

2. **Run A/B Test (if possible):**
- Process subset of entities with new threshold
- Compare data quality metrics
- Validate downstream predictions not degraded

3. **Deploy Gradually:**
- Start with one processor
- Monitor for 1 week
- Expand to other processors if successful

---

## Contacts and Escalation

### Level 1: Self-Service
- Use this runbook
- Check monitoring dashboard
- Query `reprocess_attempts` table

### Level 2: Team Lead
- Circuit breaker bulk overrides
- Threshold tuning decisions
- Incident investigation

### Level 3: Engineering Team
- CompletenessChecker bugs
- Schema changes needed
- Performance issues

### Level 4: On-Call (Emergency Only)
- Mass processor outages
- Data loss scenarios
- Production system down

---

## Appendix: Useful Queries

### Query 1: Daily Health Check
```sql
SELECT
  processor_name,
  COUNT(*) as total_entities,
  AVG(completeness_percentage) as avg_completeness,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready_count,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM (
  SELECT 'team_defense_zone_analysis' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'player_shot_zone_analysis' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'player_daily_cache' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'player_composite_factors' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'ml_feature_store' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'upcoming_player_game_context' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_analytics.upcoming_player_game_context`
  WHERE analysis_date = CURRENT_DATE() - 1
  UNION ALL
  SELECT 'upcoming_team_game_context' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_analytics.upcoming_team_game_context`
  WHERE analysis_date = CURRENT_DATE() - 1
)
GROUP BY processor_name
ORDER BY production_ready_pct;
```

### Query 2: Find Entities Stuck in Circuit Breaker
```sql
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  circuit_breaker_until,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining,
  manual_override_applied,
  notes
FROM `nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
  AND manual_override_applied = FALSE
ORDER BY days_remaining DESC;
```

### Query 3: Completeness Trend (Last 30 Days)
```sql
SELECT
  analysis_date,
  processor_name,
  AVG(completeness_percentage) as avg_completeness,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as production_ready_count,
  COUNT(*) as total_count
FROM (
  SELECT analysis_date, 'player_daily_cache' as processor_name, completeness_percentage, is_production_ready
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  -- Add other processors...
)
GROUP BY analysis_date, processor_name
ORDER BY processor_name, analysis_date DESC;
```

---

**End of Runbook**

For questions or improvements to this runbook, contact the Data Engineering Team.
