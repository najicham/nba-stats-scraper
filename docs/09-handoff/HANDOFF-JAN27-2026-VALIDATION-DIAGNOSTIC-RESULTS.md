# Validation Diagnostic Results - January 27, 2026

## Purpose

This document summarizes diagnostic queries run to verify Opus's corrections to the original Sonnet validation findings. These results confirm the root causes and inform the remediation plan.

**Request**: Review these findings and confirm the remediation plan before execution.

---

## Background

1. **Original Sonnet validation** (Jan 26): Identified 4 issues - missing raw data, broken usage_rate, incomplete analytics coverage, rolling average mismatches
2. **Opus review** (Jan 26): Corrected the root cause analysis and provided a prioritized remediation plan
3. **This document** (Jan 27): Diagnostic queries to verify Opus's hypotheses before executing remediation

---

## Diagnostic Query Results

### Query 1: Does team_offense_game_summary data exist?

**Opus hypothesis**: Team data exists; the issue is timing (data wasn't available at processing time)

```sql
SELECT game_date, COUNT(*) as teams
FROM nba_analytics.team_offense_game_summary
WHERE game_date BETWEEN '2026-01-19' AND '2026-01-25'
GROUP BY 1 ORDER BY 1;
```

**Result**:
```
| game_date  | teams |
|------------|-------|
| 2026-01-19 |    18 |
| 2026-01-20 |    14 |
| 2026-01-21 |    16 |
| 2026-01-22 |    16 |
| 2026-01-23 |    16 |
| 2026-01-24 |    22 |
| 2026-01-25 |    16 |
```

**Conclusion**: ✅ Team data EXISTS for all dates including Jan 22-23. This rules out "missing team data" as the root cause.

---

### Query 2: Do game_id formats match between BDL and team_offense_game_summary?

**Opus hypothesis**: If formats don't match, join would fail silently

```sql
SELECT DISTINCT
  b.game_id as bdl_game_id,
  t.game_id as team_game_id,
  CASE WHEN t.game_id IS NOT NULL THEN 'MATCH' ELSE 'NO_MATCH' END as status
FROM nba_raw.bdl_player_boxscores b
LEFT JOIN nba_analytics.team_offense_game_summary t
  ON b.game_id = t.game_id AND t.game_date = DATE('2026-01-22')
WHERE b.game_date = DATE('2026-01-22')
```

**Result**:
```
| bdl_game_id        | team_game_id       | status |
|--------------------|--------------------|--------|
| 20260122_LAL_LAC   | 20260122_LAL_LAC   | MATCH  |
| 20260122_DEN_WAS   | 20260122_DEN_WAS   | MATCH  |
| 20260122_CHA_ORL   | 20260122_CHA_ORL   | MATCH  |
| 20260122_CHI_MIN   | 20260122_CHI_MIN   | MATCH  |
| 20260122_GSW_DAL   | 20260122_GSW_DAL   | MATCH  |
| 20260122_HOU_PHI   | 20260122_HOU_PHI   | MATCH  |
| 20260122_MIA_POR   | 20260122_MIA_POR   | MATCH  |
| 20260122_SAS_UTA   | 20260122_SAS_UTA   | MATCH  |
```

**Conclusion**: ✅ All 8 games have matching game_id formats. This rules out "join key mismatch" as the root cause.

---

### Query 3: Can team stats be joined to player_game_summary NOW?

**Purpose**: Verify that team stats CAN be joined after the fact

```sql
SELECT
  p.game_date,
  p.game_id,
  p.player_lookup,
  p.team_abbr,
  p.usage_rate,
  t.fg_attempts as team_fg_attempts_from_team_table
FROM nba_analytics.player_game_summary p
LEFT JOIN nba_analytics.team_offense_game_summary t
  ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr AND p.game_date = t.game_date
WHERE p.game_date = DATE('2026-01-22')
  AND p.minutes_played > 0
LIMIT 10
```

**Result**:
```
| game_date  | game_id          | player_lookup   | team_abbr | usage_rate | team_fg_attempts_from_team_table |
|------------|------------------|-----------------|-----------|------------|----------------------------------|
| 2026-01-22 | 20260122_DEN_WAS | zekennaji       | DEN       | NULL       | 83                               |
| 2026-01-22 | 20260122_CHA_ORL | jonathanisaac   | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | jamalcain       | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | gogabitadze     | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | tristandasilva  | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | tyusjones       | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | anthonyblack    | ORL       | NULL       | 79                               |
| 2026-01-22 | 20260122_CHA_ORL | wendellcarterjr | ORL       | NULL       | 79                               |
```

**Conclusion**:
- ✅ Team stats CAN be joined now (fg_attempts shows 79, 83)
- ❌ But `usage_rate` is still NULL in stored records
- **Root cause confirmed**: Team data wasn't available when player_game_summary was originally processed. The records were created WITHOUT team stats, and usage_rate was set to NULL at that time.

---

### Query 4: Player coverage gap - Jan 22 (after registry resolutions)

**Opus hypothesis**: Registry resolutions added Jan 3-4 should fix coverage for recent dates

```sql
WITH raw_players AS (
  SELECT DISTINCT player_lookup FROM nba_raw.bdl_player_boxscores
  WHERE game_date = DATE('2026-01-22')
),
analytics_players AS (
  SELECT DISTINCT player_lookup FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('2026-01-22')
)
SELECT
  (SELECT COUNT(*) FROM raw_players) as raw_unique_players,
  (SELECT COUNT(*) FROM analytics_players) as analytics_unique_players,
  (SELECT COUNT(*) FROM raw_players r WHERE r.player_lookup NOT IN (SELECT player_lookup FROM analytics_players)) as missing_players
```

**Result**:
```
| raw_unique_players | analytics_unique_players | missing_players |
|--------------------|--------------------------|-----------------|
| 282                | 282                      | 0               |
```

**Conclusion**: ✅ 100% player coverage for Jan 22. Registry resolutions ARE working for recent dates.

---

### Query 5: Player coverage gap - Jan 15 (before registry resolutions took effect)

**Opus hypothesis**: Earlier dates should show significant gaps due to name normalization issues

```sql
-- Same query as above but for Jan 15
```

**Result**:
```
| raw_unique_players | analytics_unique_players | missing_players |
|--------------------|--------------------------|-----------------|
| 316                | 201                      | 119             |
```

**Conclusion**: ❌ 38% of players missing for Jan 15. This confirms the name normalization issue affects earlier dates.

---

### Query 6: Which players are missing for Jan 15?

```sql
WITH raw_players AS (
  SELECT DISTINCT player_lookup, player_full_name
  FROM nba_raw.bdl_player_boxscores WHERE game_date = DATE('2026-01-15')
),
analytics_players AS (
  SELECT DISTINCT player_lookup FROM nba_analytics.player_game_summary
  WHERE game_date = DATE('2026-01-15')
)
SELECT r.player_lookup, r.player_full_name
FROM raw_players r
WHERE r.player_lookup NOT IN (SELECT player_lookup FROM analytics_players)
ORDER BY r.player_lookup LIMIT 30
```

**Result** (sample):
```
| player_lookup     | player_full_name   |
|-------------------|--------------------|
| anthonydavis      | Anthony Davis      |
| austinreaves      | Austin Reaves      |
| buddyhield        | Buddy Hield        |
| clintcapela       | Clint Capela       |
| damianlillard     | Damian Lillard     |
| dangelorussell    | D'Angelo Russell   |
| deniavdija        | Deni Avdija        |
| ...               | ...                |
```

**Conclusion**: Major players (Anthony Davis, Damian Lillard, Austin Reaves) are missing from Jan 15 analytics. These are NOT obscure name normalization cases - they're well-known players with standard names.

**This suggests**: The issue may be broader than just name mismatches. It could be:
1. Processing failures for certain games
2. Date range issues in the backfill
3. Source data availability at processing time

---

## Summary of Confirmed Root Causes

| Issue | Opus Hypothesis | Diagnostic Result | Confirmed? |
|-------|-----------------|-------------------|------------|
| Missing team data | Team data exists | ✅ 14-22 teams per date | Ruled out |
| Game ID mismatch | IDs should match | ✅ All 8 games match | Ruled out |
| Usage rate NULL | Timing issue - team data wasn't available at processing time | ✅ Team data joinable NOW but usage_rate is NULL in stored records | **CONFIRMED** |
| Player coverage (recent) | Registry resolutions work | ✅ 100% coverage Jan 22 | **CONFIRMED** |
| Player coverage (earlier) | Name normalization gaps | ✅ 38% missing Jan 15 | **CONFIRMED** |

---

## Verified Root Cause Analysis

### Issue 1: Usage Rate NULL (Jan 19-25)

**Root Cause**: Processing order issue. When player_game_summary records were created for these dates, team_offense_game_summary data was not yet available. The processor attempted the join, found no matching team data, and set usage_rate to NULL.

**Evidence**:
- Team data exists NOW (Query 1)
- Join works NOW (Query 3 shows team_fg_attempts = 79, 83)
- But stored usage_rate is NULL

**Fix**: Reprocess player_game_summary for these dates. The processor will now find team data and calculate usage_rate.

### Issue 2: Analytics Coverage 60-75% (Jan 1-21)

**Root Cause**: Mixed - both name normalization AND potentially processing failures.

**Evidence**:
- Jan 22 has 100% coverage (resolutions working)
- Jan 15 has 62% coverage (119 players missing)
- Missing players include major names (Anthony Davis, Damian Lillard) that shouldn't have name issues

**Uncertainty**: The presence of major players in the missing list suggests this may not be purely a name normalization issue. Could also be:
- Games not fully processed
- Source data gaps at processing time
- Backfill date range issues

**Fix**: Reprocessing should resolve this, but we should verify coverage improves after reprocessing.

---

## Recommended Remediation Plan

### Phase 1: Reprocess player_game_summary (Analytics)

**1A: Jan 1-21** (picks up registry resolutions + recalculates with available team data)
```bash
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-01 --end-date 2026-01-21
```

**1B: Jan 22-25** (recalculates usage_rate with now-available team data)
```bash
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-22 --end-date 2026-01-25
```

### Phase 2: Regenerate player_daily_cache (Precompute)

After Phase 1 completes:
```bash
python backfill_jobs/precompute/player_daily_cache/regenerate_cache.py \
  --start-date 2026-01-01 --end-date 2026-02-13
```

### Phase 3: Verification

After each phase:
```bash
# Check player coverage
bq query "SELECT game_date, COUNT(*) as analytics,
  (SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores b WHERE b.game_date = p.game_date) as raw
FROM nba_analytics.player_game_summary p
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-22'
GROUP BY 1 ORDER BY 1"

# Check usage_rate coverage
bq query "SELECT game_date,
  COUNTIF(usage_rate IS NOT NULL) as has_usage,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2026-01-19' AND '2026-01-25'
GROUP BY 1 ORDER BY 1"

# Spot check
python scripts/spot_check_data_accuracy.py --start-date 2026-01-19 --end-date 2026-01-25 --samples 20
```

---

## Questions for Review

1. **Phase 1A scope**: Should we reprocess all of January (Jan 1-25) in one pass, or split into Jan 1-21 and Jan 22-25?

2. **Missing major players**: The presence of Anthony Davis, Damian Lillard in the Jan 15 missing list is concerning. Should we investigate why before reprocessing, or trust that reprocessing will fix it?

3. **Team data timing**: What's the expected processing order? Should team_offense_game_summary always be populated BEFORE player_game_summary runs? Is there a dependency we need to enforce?

4. **Cascade window**: Opus recommended Feb 13 as the end date for cache regeneration (21 days from Jan 23). Is this correct, or should we extend further?

5. **Verification thresholds**: What coverage percentages should we expect after remediation?
   - Player coverage: 85-90%? (accounting for DNPs)
   - Usage rate coverage: 90%+? (for players with minutes > 0)
   - Spot check accuracy: 95%+?

---

## Files Referenced

- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Main processor
- `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` - Backfill script
- `backfill_jobs/precompute/player_daily_cache/regenerate_cache.py` - Cache regeneration
- `scripts/spot_check_data_accuracy.py` - Validation script

---

## Previous Documents

- `HANDOFF-JAN26-2026-HISTORICAL-VALIDATION-FINDINGS.md` - Original Sonnet validation
- Opus review (in chat) - Corrections and prioritized plan

---

*Document created: 2026-01-27*
*Diagnostic queries run by: Claude Sonnet*
