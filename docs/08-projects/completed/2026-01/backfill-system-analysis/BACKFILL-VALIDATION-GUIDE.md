# Backfill Validation Guide
**Purpose**: Step-by-step guide for validating backfill results
**Audience**: Future you, or anyone running backfills
**Last Updated**: 2026-01-03

---

## 📋 QUICK VALIDATION CHECKLIST

Use this checklist to validate any backfill:

- [ ] **Completeness**: Backfill finished without crashes
- [ ] **NULL Rate**: 35-45% for minutes_played (target range)
- [ ] **Record Count**: Within expected range for date period
- [ ] **Date Coverage**: All dates in range are present
- [ ] **Shot Zones**: >90% of records have shot zone data
- [ ] **Data Quality**: Spot checks show realistic values
- [ ] **No Duplicates**: Each (player, game, date) appears once

---

## 🎯 VALIDATION PROCEDURE

### Step 1: Verify Backfill Completion (2 min)

**Check tmux session or logs**:

```bash
# Check if backfill tmux session is still running
tmux ls | grep backfill

# If not running, check the log file for completion
tail -50 logs/backfill_parallel_*.log | grep -E "COMPLETE|SUMMARY|FAILED"

# Look for success indicators:
# ✓ "PARALLEL BACKFILL COMPLETE"
# ✓ "Success rate: XX.X%"
# ✓ Total records processed

# Red flags:
# ✗ "Exception"
# ✗ "Failed: N" (where N > 10% of total days)
# ✗ Process crashed without summary
```

**Success Criteria**:
- ✅ Log shows "PARALLEL BACKFILL COMPLETE"
- ✅ Success rate > 90%
- ✅ Process exited cleanly (not killed)

---

### Step 2: Primary Metric - NULL Rate Check (5 min)

**Most important validation**: Check if minutes_played NULL rate is in expected range.

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  COUNT(*) as total_records,
  COUNTIF(minutes_played IS NULL) as null_count,
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 2) as null_pct,
  ROUND(COUNTIF(minutes_played IS NOT NULL) / COUNT(*) * 100, 2) as has_data_pct,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
'
```

**Expected Results**:
```
+--------------+------------+----------+--------------+---------------+-------------+
| total_records| null_count | null_pct | has_data_pct | earliest_date | latest_date |
+--------------+------------+----------+--------------+---------------+-------------+
| 120000-150000|  45000-60000| 35-45  |    55-65     | 2021-10-19    | 2024-04-30  |
+--------------+------------+----------+--------------+---------------+-------------+
```

**Decision Tree**:

- **null_pct 35-45%**: ✅ **SUCCESS** - Proceed to next validation
- **null_pct 45-60%**: ⚠️ **ACCEPTABLE** - Continue, but investigate
- **null_pct >60%**: 🚨 **FAILURE** - Parser bug, do not proceed to ML

**Why 35-45% NULL is expected**:
- ~35-40% of player-game records are DNP (did not play)
- ~5% are inactive/scratched
- This is NORMAL and expected

**Why >60% NULL is a problem**:
- Indicates parser failure (like the bug we fixed on Jan 2)
- ML model will underperform without minutes data
- Must investigate and re-run

---

### Step 3: Data Volume Check (5 min)

**Verify record counts are reasonable**:

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(*) as player_records,
  ROUND(COUNTIF(minutes_played IS NOT NULL) / COUNT(*) * 100, 1) as pct_with_minutes,
  ROUND(AVG(CASE WHEN minutes_played IS NOT NULL THEN minutes_played END), 1) as avg_minutes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
GROUP BY year
ORDER BY year
'
```

**Expected Results**:
```
+------+--------------+-------------+---------------+------------------+-------------+
| year | unique_dates | unique_games| player_records| pct_with_minutes | avg_minutes |
+------+--------------+-------------+---------------+------------------+-------------+
| 2021 |     80-90    |   400-450   |   35,000-45,000|      55-65      |   20-25     |
| 2022 |    240-250   |  1,200-1,250|  115,000-125,000|     55-65      |   20-25     |
| 2023 |    240-250   |  1,200-1,250|  115,000-125,000|     55-65      |   20-25     |
| 2024 |    120-130   |   600-650   |   60,000-70,000|      55-65      |   20-25     |
+------+--------------+-------------+---------------+------------------+-------------+
```

**Red Flags**:
- ✗ Any year with < 30K records (should be 35K+)
- ✗ pct_with_minutes < 45% (should be 55-65%)
- ✗ avg_minutes < 15 or > 30 (should be 20-25)
- ✗ Missing a full year (all counts = 0)

---

### Step 4: Shot Zone Coverage Check (5 min)

**Verify shot zones were populated** (critical for ML features):

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  COUNTIF(paint_attempts IS NOT NULL) as has_paint,
  COUNTIF(mid_range_attempts IS NOT NULL) as has_mid_range,
  COUNTIF(assisted_fg_makes IS NOT NULL) as has_assisted,
  COUNT(*) as total_with_minutes,
  ROUND(COUNTIF(paint_attempts IS NOT NULL) / COUNT(*) * 100, 1) as paint_coverage_pct,
  ROUND(COUNTIF(mid_range_attempts IS NOT NULL) / COUNT(*) * 100, 1) as mid_range_coverage_pct,
  ROUND(COUNTIF(assisted_fg_makes IS NOT NULL) / COUNT(*) * 100, 1) as assisted_coverage_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
  AND minutes_played IS NOT NULL  -- Only check players who actually played
'
```

**Expected Results**:
```
+-----------+-----------------+-------------+-------------------+--------------------+------------------------+-----------------------+
| has_paint | has_mid_range   | has_assisted| total_with_minutes| paint_coverage_pct | mid_range_coverage_pct | assisted_coverage_pct |
+-----------+-----------------+-------------+-------------------+--------------------+------------------------+-----------------------+
| 65K-90K   |   65K-90K       |  65K-90K    |     70K-95K       |       90-98        |         90-98          |         90-98         |
+-----------+-----------------+-------------+-------------------+--------------------+------------------------+-----------------------+
```

**Decision**:
- ✅ **Coverage >90%**: EXCELLENT - Full shot zone data
- ⚠️ **Coverage 70-90%**: ACCEPTABLE - Some missing, but usable
- 🚨 **Coverage <70%**: FAILURE - Shot zones missing, check BigDataBall availability

**Why this matters**:
- ML model v3 uses 4 shot zone features (paint_rate, mid_range_rate, three_pt_rate, assisted_rate)
- Missing shot zones = model fills with league averages = degraded performance
- Need >90% coverage for optimal ML performance

---

### Step 5: Spot Check - Known Game Validation (10 min)

**Validate a well-known game to ensure data looks realistic**:

Example: 2022 NBA Finals Game 1 (Warriors vs Celtics, June 2, 2022)

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  player_full_name,
  team_abbr,
  minutes_played,
  points,
  assists,
  rebounds_total,
  three_pt_makes,
  paint_attempts,
  mid_range_attempts,
  primary_source_used
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = "2022-06-02"
  AND minutes_played IS NOT NULL
ORDER BY minutes_played DESC
LIMIT 20
'
```

**Manual Validation**:
1. **Check top players**: Should see starters (Curry, Tatum, Brown, Wiggins, Horford, etc.)
2. **Minutes range**: Starters should have 35-45 minutes, bench 10-25 minutes
3. **Stats look realistic**: Points 10-30, assists 0-10, rebounds 5-15
4. **Shot zones present**: Most players should have paint/mid/three attempts
5. **Source tracking**: Should show "nbac_gamebook" or "bdl_boxscores"

**Example Expected Output**:
```
Stephen Curry  | GSW | 42 | 34 | 5  | 5  | 6 | 8  | 12 | nbac_gamebook
Jayson Tatum   | BOS | 45 | 28 | 4  | 7  | 3 | 10 | 8  | nbac_gamebook
Klay Thompson  | GSW | 35 | 15 | 2  | 5  | 5 | 3  | 9  | nbac_gamebook
... (realistic NBA stats)
```

**Red Flags**:
- ✗ Major players missing from top 20
- ✗ Minutes > 48 (impossible)
- ✗ Stats look wrong (e.g., bench player with 45 minutes)
- ✗ Shot zones all NULL
- ✗ primary_source_used all NULL

---

### Step 6: Date Coverage Check (5 min)

**Verify all dates in range are present** (no gaps):

```bash
bq query --use_legacy_sql=false '
WITH expected_dates AS (
  SELECT DATE_ADD("2021-10-01", INTERVAL n DAY) as date
  FROM UNNEST(GENERATE_ARRAY(0, DATE_DIFF("2024-05-01", "2021-10-01", DAY))) as n
),
actual_dates AS (
  SELECT DISTINCT game_date as date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
)
SELECT
  e.date as missing_date
FROM expected_dates e
LEFT JOIN actual_dates a ON e.date = a.date
WHERE a.date IS NULL
  AND EXTRACT(DAYOFWEEK FROM e.date) NOT IN (1, 7)  -- Exclude most Sundays/Saturdays
ORDER BY e.date
LIMIT 50
'
```

**Expected Results**:
- Missing dates should be **off-season only** (July, August, September)
- During regular season (Oct-Apr), only a few dates should be missing (All-Star break, etc.)

**Red Flags**:
- ✗ >10 consecutive dates missing during regular season
- ✗ Entire month missing
- ✗ Random missing dates throughout season

---

### Step 7: Duplicate Check (5 min)

**Ensure no duplicate records**:

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT
  player_lookup,
  game_id,
  game_date,
  COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
GROUP BY player_lookup, game_id, game_date
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20
'
```

**Expected Results**:
```
(No rows returned)
```

**If duplicates found**:
```sql
-- Delete duplicates (keep most recent row_id)
DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE row_id IN (
  SELECT row_id
  FROM (
    SELECT row_id,
           ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id, game_date ORDER BY updated_at DESC) as rn
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
  )
  WHERE rn > 1
)
```

---

### Step 8: Final Summary Report (5 min)

**Generate a final validation summary**:

```bash
bq query --use_legacy_sql=false --format=pretty '
WITH metrics AS (
  SELECT
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNTIF(minutes_played IS NULL) as null_minutes,
    COUNTIF(paint_attempts IS NOT NULL) as has_shot_zones,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
)
SELECT
  total_records,
  unique_dates,
  unique_games,
  unique_players,
  ROUND(null_minutes / total_records * 100, 2) as null_minutes_pct,
  ROUND(has_shot_zones / total_records * 100, 2) as shot_zone_coverage_pct,
  earliest_date,
  latest_date,
  CASE
    WHEN ROUND(null_minutes / total_records * 100, 2) BETWEEN 35 AND 45
      AND ROUND(has_shot_zones / total_records * 100, 2) >= 85
      AND total_records >= 110000
    THEN "✅ SUCCESS - Ready for ML training"
    WHEN ROUND(null_minutes / total_records * 100, 2) BETWEEN 45 AND 60
      AND total_records >= 90000
    THEN "⚠️ PARTIAL SUCCESS - Usable but investigate NULL rate"
    ELSE "🚨 FAILURE - Do not proceed to ML, debug required"
  END as validation_status
FROM metrics
'
```

---

## 🎯 DECISION CRITERIA

### ✅ SUCCESS (Proceed to ML Training)

**All criteria must be met**:
- [x] Backfill completed without major failures (>90% success rate)
- [x] NULL rate: 35-45%
- [x] Total records: 110,000 - 160,000
- [x] Shot zone coverage: >85%
- [x] Spot checks look realistic
- [x] No major date gaps
- [x] No duplicates

**Next Step**: Proceed to ML v3 training

---

### ⚠️ PARTIAL SUCCESS (Investigate but can proceed)

**Some criteria not met but data is usable**:
- [x] Backfill completed (>85% success rate)
- [ ] NULL rate: 45-60% (higher than ideal)
- [x] Total records: 90,000+
- [ ] Shot zone coverage: 70-85% (some missing)
- [x] Other checks pass

**Action**:
1. Document the issues
2. Investigate root cause (but don't block ML)
3. Proceed to ML training with caution
4. Consider re-backfill later if ML performance is poor

**Next Step**: Proceed to ML v3 training (with asterisk)

---

### 🚨 FAILURE (Do not proceed)

**Critical failures**:
- [ ] Backfill crashed or <80% success rate
- [ ] NULL rate >60% (parser bug)
- [ ] Total records <80,000 (massive data loss)
- [ ] Shot zones missing (<70% coverage)
- [ ] Spot checks show wrong data

**Action**:
1. **DO NOT** proceed to ML training
2. Debug the issue:
   - Check logs for errors
   - Verify parser is working (test single day)
   - Check BigQuery data availability
   - Review failed dates in checkpoint
3. Fix the issue
4. Re-run backfill

**Next Step**: Troubleshooting (see below)

---

## 🔧 TROUBLESHOOTING

### Issue: NULL rate >60%

**Possible Causes**:
1. Parser bug (check `_parse_minutes_to_decimal()` function)
2. Source data missing minutes field
3. Wrong source being used

**Debug**:
```bash
# Test parser on single known-good date
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-12 \
  --end-date 2022-01-12 \
  --no-resume

# Check NULL rate for that date
bq query --use_legacy_sql=false '
SELECT COUNT(*), COUNTIF(minutes_played IS NULL)
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = "2022-01-12"
'

# If NULL count is high, parser is broken
# Check player_game_summary_processor.py lines 891-956
```

---

### Issue: Low record count (<90K)

**Possible Causes**:
1. Many dates failed to process
2. Source data missing for date range
3. Checkpoint resume skipped too many dates

**Debug**:
```bash
# Check failed dates in checkpoint
cat /tmp/backfill_checkpoints/player_game_summary_*.json | jq '.failed_dates'

# Check source data availability
bq query --use_legacy_sql=false '
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as raw_records
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
'
```

---

### Issue: Shot zones missing (<70% coverage)

**Possible Causes**:
1. BigDataBall play-by-play data missing for date range
2. Shot zone extraction query failed
3. Backfill was run with `skip_shot_zones` flag (if we implement it)

**Debug**:
```bash
# Check BigDataBall data availability
bq query --use_legacy_sql=false '
SELECT
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as events
FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
  AND event_type = "shot"
'

# If BigDataBall data is present, check processor logs for errors
grep -i "shot zone\|bigdataball" logs/backfill_*.log | tail -50
```

---

## 📊 VALIDATION REPORT TEMPLATE

Copy this template and fill it out after validation:

```markdown
# Backfill Validation Report
**Date**: 2026-01-XX
**Backfill Range**: 2021-10-01 to 2024-05-01
**Validator**: [Your Name]

## Summary
- **Status**: ✅ SUCCESS / ⚠️ PARTIAL / 🚨 FAILURE
- **Total Records**: XXX,XXX
- **NULL Rate**: XX.X%
- **Shot Zone Coverage**: XX.X%
- **Ready for ML**: YES / NO

## Detailed Results

### Step 1: Completeness
- [x] Backfill completed
- [x] Success rate: XX.X%
- [ ] Failures: X dates

### Step 2: NULL Rate
- [x] NULL pct: XX.X% (target: 35-45%)
- [x] Within acceptable range

### Step 3: Data Volume
- [x] Total records: XXX,XXX
- [x] 2021: XX,XXX records
- [x] 2022: XXX,XXX records
- [x] 2023: XXX,XXX records
- [x] 2024: XX,XXX records

### Step 4: Shot Zones
- [x] Coverage: XX.X%
- [x] Paint attempts: XX,XXX
- [x] Mid-range attempts: XX,XXX
- [x] Assisted FG: XX,XXX

### Step 5: Spot Check
- [x] 2022 Finals Game 1 looks realistic
- [x] Curry: 42 min, 34 pts ✓
- [x] Tatum: 45 min, 28 pts ✓

### Step 6: Date Coverage
- [x] No unexpected gaps
- [x] Only off-season dates missing

### Step 7: Duplicates
- [x] No duplicates found

### Step 8: Final Summary
- **Validation Status**: ✅ SUCCESS
- **Ready for ML**: YES
- **Notes**: All checks passed. Proceed to ML v3 training.

## Action Items
- [x] Validation complete
- [ ] Proceed to ML training
- [ ] Document results in handoff doc
```

---

## 🚀 NEXT STEPS AFTER VALIDATION

### If Validation Succeeds (✅):

1. **Document results** in handoff doc
2. **Proceed to ML v3 training**:
   - Read: `docs/09-handoff/2026-01-03-CHAT-4-ML-TRAINING.md`
   - Train model with full historical data
   - Target: MAE <4.00
3. **Archive backfill logs** for reference

### If Validation Partial (⚠️):

1. **Document issues** in project docs
2. **Investigate** but don't block ML training
3. **Proceed to ML** with notes about data quality
4. **Plan re-backfill** if ML performance is poor

### If Validation Fails (🚨):

1. **DO NOT proceed to ML**
2. **Troubleshoot** using guide above
3. **Fix issues** (parser, data availability, etc.)
4. **Re-run backfill** with fixes
5. **Re-validate** using this guide

---

## 📁 FILES & REFERENCES

**Backfill Scripts**:
- `/home/naji/code/nba-stats-scraper/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

**Processor (with parser)**:
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- Lines 891-956: `_parse_minutes_to_decimal()` function

**Validation Queries** (save for reuse):
- Copy queries from this document into a `.sql` file for easy re-running

**Documentation**:
- Backfill analysis: `docs/08-projects/current/backfill-system-analysis/`
- Handoff docs: `docs/09-handoff/`

---

## 💡 TIPS FOR FUTURE BACKFILLS

1. **Always validate before ML training**: Don't assume backfill worked
2. **Test on small range first**: Run 7-day test before full backfill
3. **Check logs during execution**: Don't wait until end to find issues
4. **Save checkpoint backups**: Allows resume if something goes wrong
5. **Document everything**: Future you will thank present you

---

**Last Updated**: 2026-01-03
**Next Review**: After next backfill run
**Owner**: NBA Analytics Team
