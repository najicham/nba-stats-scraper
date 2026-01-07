# Player Game Summary Backfill Project
**Project ID**: BACKFILL-PGS-001
**Created**: 2026-01-03
**Status**: 🔴 READY TO EXECUTE
**Priority**: P0 - CRITICAL (Blocks ML work)
**Estimated Duration**: 6-12 hours
**Owner**: Data Pipeline Team

---

## 🎯 OBJECTIVE

Backfill `nba_analytics.player_game_summary.minutes_played` field for historical period (2021-10-01 to 2024-05-01) to fix 99.5% NULL rate that is blocking ML model development.

---

## 📊 PROBLEM STATEMENT

### Current State
```sql
-- Current NULL rate for historical data
SELECT
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Current result:
-- total_games: 83,534
-- null_count: 83,111
-- null_pct: 99.5%
```

### Target State
```sql
-- Target NULL rate: ~40% (matching recent data pattern)
-- Recent data (Nov 2025+) shows processor working correctly:
--   - ~60% players have valid minutes (played)
--   - ~40% players have NULL (legitimate DNP/inactive)
```

### Impact of Problem
- ML training data has 95% missing features
- Models train on imputed defaults instead of real patterns
- XGBoost v3 underperforms mock baseline by 6.9%
- Business impact: $100-150k potential value blocked

---

## 🔍 ROOT CAUSE

**Investigation Date**: 2026-01-03

**Finding**: Historical data was never processed/backfilled

**Evidence**:
1. Raw data health: BDL 0% NULL, NBA.com 0.42% NULL ✅
2. Processor code: Correct, no bugs found ✅
3. Recent data: Nov 2025+ shows ~40% NULL (working correctly) ✅
4. Historical data: 2021-2024 shows 95-100% NULL (never processed) ❌

**Conclusion**: Processor works perfectly. Historical data simply never ran through it.

**Full Root Cause Doc**: `docs/09-handoff/2026-01-03-MINUTES-PLAYED-ROOT-CAUSE.md`

---

## ✅ SOLUTION: BACKFILL WITH CURRENT PROCESSOR

### Strategy
Re-run the existing `player_game_summary` processor for 2021-2024 period using current working code. No code changes needed.

**EXECUTION STRATEGY: Sequential Processing** (RECOMMENDED)
- Single-process execution with day-by-day batching
- Estimated time: 6-12 hours (acceptable for overnight run)
- Risk level: LOW (no concurrent write conflicts)
- See: `PARALLELIZATION-ANALYSIS.md` for detailed analysis

### Why This Works
- Current processor proven working (Nov 2025+ data)
- Raw data exists with excellent quality (BDL 0% NULL)
- Processor correctly handles both played minutes and DNP cases
- Recent data validates expected outcome (~40% NULL)
- Sequential execution avoids DELETE+INSERT race conditions

### Expected Outcome
- NULL rate drops from 99.5% to ~40%
- 38,500+ training samples with valid minutes_avg_last_10 (vs 3,214 currently)
- ML models can learn from real patterns instead of defaults

### Alternative: Parallel Execution
For time-critical deployments, 3-season parallelization can reduce time to 2-4 hours. However, this introduces medium-risk race conditions due to the DELETE+INSERT pattern used by MERGE_UPDATE. Only use if deadline requires <6 hour completion.

**Full Analysis**: See `PARALLELIZATION-ANALYSIS.md`
**Copy-Paste Commands**: See `EXECUTION-COMMANDS.md`

---

## 📋 EXECUTION PLAN

### Step 1: Pre-flight Validation (1 hour)

**1.1 Verify Raw Data Quality**
```sql
-- Check BDL has minutes data for backfill period
SELECT
  DATE_TRUNC(game_date, YEAR) as year,
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY year
ORDER BY year;

-- Expected: null_pct < 1% for all years
-- If > 5%: STOP and investigate raw data collection
```

**1.2 Check NBA.com as Backup**
```sql
-- Verify NBA.com also has minutes data
SELECT
  DATE_TRUNC(game_date, YEAR) as year,
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY year
ORDER BY year;

-- Expected: null_pct < 1%
```

**1.3 Verify Processor Script Exists**
```bash
# Check backfill script exists
ls -la /home/naji/code/nba-stats-scraper/bin/analytics/reprocess_player_game_summary.sh

# OR check Python script exists
ls -la /home/naji/code/nba-stats-scraper/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py

# Expected: Script exists and is executable
```

**1.4 Estimate BigQuery Cost**
```
Rows to process: ~1.4M (930 days × ~1,500 players/day)
Data scanned: ~50GB
Query cost: ~$0.25 ($5/TB)
Compute cost: ~$12-60 (6-12 hours Cloud Run at $2-5/hour)
Total estimated cost: $12-60
```

**Decision Point**: If all checks pass, proceed to Step 2

### Step 2: Sample Backfill Test (1 hour)

**2.1 Test Processor on Single Week**
```bash
# Activate virtual environment
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Run backfill for 1 week from Jan 2022 (sample test)
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-10 \
  --end-date 2022-01-17

# OR if shell script exists:
./bin/analytics/reprocess_player_game_summary.sh \
  --start-date 2022-01-10 \
  --end-date 2022-01-17 \
  --batch-size 7
```

**2.2 Validate Sample Results**
```sql
-- Check NULL rate for sample week
SELECT
  game_date,
  COUNT(*) as total_players,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2022-01-10' AND '2022-01-17'
GROUP BY game_date
ORDER BY game_date;

-- Expected: null_pct ~35-45% for most dates (matching recent data)
-- Success: null_pct < 50% for all dates
-- Failure: null_pct > 80% → investigate processor
```

**2.3 Spot Check Sample Data**
```sql
-- Verify actual players have correct minutes
SELECT
  game_date,
  player_full_name,
  team_abbr,
  points,
  minutes_played,
  primary_source_used
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2022-01-15'  -- Sample date
ORDER BY minutes_played DESC NULLS LAST
LIMIT 20;

-- Expected:
--   - Top players have valid minutes (e.g., 35-40 min)
--   - DNP players have NULL
--   - Values match known games (cross-reference basketball-reference.com)
```

**Decision Point**: If sample succeeds (null_pct < 50%), proceed to Step 3

### Step 3: Full Backfill Execution (6-12 hours)

**3.1 Season-by-Season Backfill**

**Option A: Single Command (Recommended if script supports)**
```bash
# Run full backfill for all 3 seasons
./bin/analytics/reprocess_player_game_summary.sh \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --batch-size 7 \
  --skip-downstream-trigger

# Estimated duration: 6-12 hours
```

**Option B: Season-by-Season with Validation**
```bash
# 2021-22 Season
echo "=== Backfilling 2021-22 Season ==="
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2022-04-15

# Validate 2021-22
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2022-04-15';
"

# 2022-23 Season
echo "=== Backfilling 2022-23 Season ==="
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-10-01 \
  --end-date 2023-04-15

# Validate 2022-23
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2022-10-01' AND game_date < '2023-04-15';
"

# 2023-24 Season
echo "=== Backfilling 2023-24 Season ==="
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2023-10-01 \
  --end-date 2024-05-01

# Validate 2023-24
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2023-10-01' AND game_date < '2024-05-01';
"
```

**3.2 Progress Monitoring**
```bash
# Monitor backfill progress (run in separate terminal)
watch -n 60 'bq query --use_legacy_sql=false "
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '\''2021-10-01'\'' AND game_date < '\''2024-05-01'\''
GROUP BY month
ORDER BY month DESC
LIMIT 12;
"'

# Watch for null_pct dropping from 95%+ to ~40% as backfill progresses
```

### Step 4: Post-Backfill Validation (2 hours)

**4.1 Overall NULL Rate Check**
```sql
-- Primary validation query
SELECT
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct,

  -- Break down by season
  SUM(CASE WHEN game_date >= '2021-10-01' AND game_date < '2022-04-15' THEN 1 ELSE 0 END) as season_2021_total,
  SUM(CASE WHEN game_date >= '2021-10-01' AND game_date < '2022-04-15' AND minutes_played IS NULL THEN 1 ELSE 0 END) as season_2021_null,

  SUM(CASE WHEN game_date >= '2022-10-01' AND game_date < '2023-04-15' THEN 1 ELSE 0 END) as season_2022_total,
  SUM(CASE WHEN game_date >= '2022-10-01' AND game_date < '2023-04-15' AND minutes_played IS NULL THEN 1 ELSE 0 END) as season_2022_null,

  SUM(CASE WHEN game_date >= '2023-10-01' AND game_date < '2024-05-01' THEN 1 ELSE 0 END) as season_2023_total,
  SUM(CASE WHEN game_date >= '2023-10-01' AND game_date < '2024-05-01' AND minutes_played IS NULL THEN 1 ELSE 0 END) as season_2023_null
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Success criteria: null_pct < 45%
-- Bonus: null_pct < 40%
```

**4.2 Row Count Verification**
```sql
-- Ensure no duplicates or data loss
SELECT
  'Before backfill' as state,
  83534 as expected_rows  -- From pre-flight check
UNION ALL
SELECT
  'After backfill' as state,
  COUNT(*) as actual_rows
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Expected: actual_rows = expected_rows (±2% acceptable)
-- Failure: >2% difference → investigate duplicates or data loss
```

**4.3 Sample Game Validation**
```sql
-- Validate known games have correct data
-- Example: Lakers vs Warriors, Jan 18, 2022
SELECT
  player_full_name,
  team_abbr,
  points,
  minutes_played,
  primary_source_used
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2022-01-18'
  AND (team_abbr = 'LAL' OR team_abbr = 'GSW')
ORDER BY minutes_played DESC NULLS LAST;

-- Cross-reference with basketball-reference.com:
-- https://www.basketball-reference.com/boxscores/202201180LAL.html
-- Expected: Top players (LeBron, Curry) have ~35-40 min
--          Bench players have valid minutes
--          DNP players have NULL
```

**4.4 Downstream Feature Check**
```sql
-- Check if cascading features improve
-- From nba_precompute.player_composite_factors
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_avg_last_10 IS NULL THEN 1 ELSE 0 END) as minutes_avg_null,
  SUM(CASE WHEN fatigue_score IS NULL THEN 1 ELSE 0 END) as fatigue_null,
  ROUND(SUM(CASE WHEN minutes_avg_last_10 IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as minutes_avg_null_pct,
  ROUND(SUM(CASE WHEN fatigue_score IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as fatigue_null_pct
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Before backfill: minutes_avg_null_pct = 95.8%
-- After backfill: minutes_avg_null_pct should drop significantly
-- Note: Phase 4 might need reprocessing to fully benefit
```

---

## ✅ SUCCESS CRITERIA

### Primary Success (Required)
- [ ] NULL rate drops from 99.5% to <45%
- [ ] Row count unchanged (±2%)
- [ ] Sample validation shows correct values
- [ ] No BigQuery errors during execution

### Bonus Success (Ideal)
- [ ] NULL rate <40% (matching recent data pattern)
- [ ] Training samples with valid minutes_avg > 38,000
- [ ] Downstream features (fatigue_score) also improve

### Failure Conditions (Stop and Investigate)
- [ ] NULL rate remains >80% after backfill
- [ ] Row count changes >5%
- [ ] Sample validation shows incorrect values
- [ ] Backfill errors/failures

---

## 🔄 ROLLBACK PLAN

### If Backfill Fails Catastrophically

**Scenario 1: Data Corrupted**
```sql
-- Check if data was corrupted
SELECT
  game_date,
  COUNT(*) as players,
  COUNT(DISTINCT player_lookup) as unique_players,
  MAX(minutes_played) as max_minutes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY game_date
HAVING max_minutes > 60 OR players > 500
ORDER BY game_date;

-- If corruption found: Restore from backup (if exists)
-- OR re-run backfill with corrected parameters
```

**Scenario 2: Duplicates Created**
```sql
-- Check for duplicates
SELECT
  game_date,
  player_lookup,
  team_abbr,
  COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY game_date, player_lookup, team_abbr
HAVING COUNT(*) > 1;

-- If duplicates found: DELETE using specific criteria
DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
  AND <condition to identify duplicates>;
```

**Scenario 3: Backfill Script Fails**
```bash
# Check error logs
tail -f /tmp/player_game_summary_backfill.log

# Common issues:
# 1. BigQuery quota exceeded → Wait and retry
# 2. Permissions error → Fix permissions and retry
# 3. Code bug → Debug and fix processor

# Resume from checkpoint if supported:
./bin/analytics/reprocess_player_game_summary.sh \
  --start-date <last_successful_date> \
  --end-date 2024-05-01 \
  --resume
```

---

## ⚠️ DEPENDENCIES AND IMPACTS

### Upstream Dependencies
- ✅ Raw data collection (Phase 1-2) - COMPLETE
- ✅ BDL and NBA.com boxscores exist - VERIFIED
- ✅ Processor code working - VERIFIED

### Downstream Impacts

**Immediate Impact**:
- `nba_analytics.player_game_summary.minutes_played` populated

**Cascading Improvements**:
- `player_composite_factors.minutes_avg_last_10` - Should improve
- `player_composite_factors.fatigue_score` - Depends on minutes
- `player_daily_cache.usage_rate_last_10` - Still 100% NULL (separate issue)

**Phase 4 Precompute**:
- May need reprocessing to benefit from new minutes_played data
- Estimated additional effort: 6-12 hours
- Can defer until after ML v1 deployed

**ML Training**:
- Can resume immediately after backfill validation
- Expected MAE improvement: 4.63 → 3.80-4.10
- Timeline: Week 2 after backfill complete

---

## 📊 MONITORING AND VALIDATION

### During Backfill
```bash
# Monitor BigQuery job progress
bq ls -j -n 100 | grep player_game_summary

# Check for errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="nba-phase3-analytics-processors"
  AND severity>=ERROR
  AND timestamp>="2026-01-03T00:00:00Z"' \
  --limit=50

# Monitor NULL rate improvement
# (Use progress monitoring query from Step 3.2)
```

### After Backfill
```bash
# Run full validation suite
./bin/backfill/validate_player_game_summary.sh 2021-10-01 2024-05-01

# Check data quality metrics
bq query --use_legacy_sql=false < /path/to/validation_queries.sql

# Document results in completion report
```

---

## 💾 DOCUMENTATION REQUIREMENTS

### During Execution
- [ ] Log start time and parameters
- [ ] Capture any errors or warnings
- [ ] Document any deviations from plan
- [ ] Save validation query results

### After Completion
- [ ] Create backfill completion report
- [ ] Document before/after metrics
- [ ] List any issues encountered
- [ ] Provide recommendations for future

**Report Template**: `docs/08-projects/current/backfill-system-analysis/BACKFILL-COMPLETION-REPORT.md`

---

## 📅 TIMELINE

| Step | Duration | Cumulative |
|------|----------|------------|
| Step 1: Pre-flight validation | 1 hour | 1 hour |
| Step 2: Sample backfill test | 1 hour | 2 hours |
| Step 3: Full backfill execution | 6-12 hours | 8-14 hours |
| Step 4: Post-backfill validation | 2 hours | 10-16 hours |

**Total Estimated Time**: 10-16 hours (can run overnight)

**Recommended Schedule**:
- Day 1 Morning: Steps 1-2 (pre-flight + sample)
- Day 1 Afternoon: Start Step 3 (full backfill)
- Day 1 Evening: Monitor progress
- Day 2 Morning: Complete Step 3, run Step 4 (validation)

---

## 🎯 NEXT STEPS AFTER COMPLETION

### Immediate (Same Day)
1. Update ML project status: UNBLOCKED
2. Document backfill results
3. Communicate success to stakeholders

### Short-term (Week 2)
4. Retrain XGBoost v3 with clean data
5. Validate MAE improvement
6. Implement quick wins (if training successful)

### Medium-term (Week 3-4)
7. Consider Phase 4 precompute backfill
8. Continue ML model development
9. Deploy to production

---

## 📚 RELATED DOCUMENTATION

- `docs/09-handoff/2026-01-03-MINUTES-PLAYED-ROOT-CAUSE.md` - Root cause analysis
- `docs/09-handoff/2026-01-03-ULTRATHINK-ANALYSIS-COMPLETE.md` - Comprehensive analysis
- `docs/08-projects/current/ml-model-development/00-PROJECT-MASTER.md` - ML project master plan
- `docs/08-projects/current/backfill-system-analysis/README.md` - General backfill overview

---

## ❓ FAQ

**Q: Will this affect production?**
A: No. Backfill runs separately from real-time pipeline. Production unaffected.

**Q: Can we resume if interrupted?**
A: Yes, if using season-by-season approach. Single command may need manual resume.

**Q: What if backfill doesn't improve NULL rate?**
A: Investigate raw data quality and processor execution. See rollback plan above.

**Q: Do we need to backfill Phase 4 too?**
A: Eventually yes, but can defer. ML can start with Phase 3 backfill alone.

**Q: How much will this cost?**
A: Estimated $12-60 total (BigQuery + Cloud Run). Negligible.

**Q: How confident are we this will work?**
A: 85% confidence. Recent data proves processor works. Main risk is execution.

---

**PROJECT STATUS**: 🔴 READY TO EXECUTE

**NEXT ACTION**: Run Step 1 pre-flight validation queries

**ESTIMATED COMPLETION**: 10-16 hours from start
