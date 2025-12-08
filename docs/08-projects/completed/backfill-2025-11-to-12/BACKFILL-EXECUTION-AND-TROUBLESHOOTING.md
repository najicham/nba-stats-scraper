# Backfill Execution Order & Troubleshooting Guide

**Created:** 2025-11-29 19:30 PST
**Last Updated:** 2025-11-29 21:12 PST
**Purpose:** Critical review of backfill strategy with execution order, failure scenarios, and troubleshooting procedures
**Author:** Deep-dive review session
**Status:** CRITICAL - Read before executing backfill

---

## 🚨 Executive Summary: Critical Review Findings

### Your Instinct is Correct: Phase 1 & 2 First

**YES, you should backfill Phase 1 & 2 completely before starting Phase 3 & 4.**

**Why:**
1. Phase 3 has NO cross-date dependencies - each date is independent
2. Phase 4 has CRITICAL cross-date dependencies - needs 30 days of Phase 3 history
3. If Phase 2 has gaps, Phase 3 will fail with `DependencyError`
4. If Phase 3 has gaps, Phase 4 will either fail or produce degraded data

### Key Risks Identified

| Risk | Severity | Mitigation |
|------|----------|------------|
| Phase 4 fails silently with incomplete data | HIGH | Validate Phase 3 100% complete before Phase 4 |
| Defensive checks disabled in backfill mode | MEDIUM | Still runs dependency checks, just relaxed thresholds |
| Serial dates processing one error cascades | HIGH | Use parallel processing within phase, validate after each season |
| Alert suppression hides real problems | MEDIUM | Monitor processor_run_history table actively |
| Phase 4 processors must run sequentially | HIGH | Document ordering, never parallelize Phase 4 processors |

---

## 📋 Definitive Execution Order

### Phase-by-Phase, Season-by-Season

```
PHASE 1: Scrapers (parallel per date)
    ↓ Validate all GCS files exist
PHASE 2: Raw Processors (parallel per date)
    ↓ Validate all 21 tables have data for ALL dates
PHASE 3: Analytics Processors (parallel per date, parallel across 5 processors)
    ↓ Validate all 5 tables have data for ALL dates
PHASE 4: Precompute Processors (parallel per date, SEQUENTIAL across 5 processors)
    ↓ Validate all 5 tables have data for ALL dates
PHASE 5: Predictions (after Phase 4 complete)
```

### Within Phase 3: All 5 Processors are Independent ✅

```
Can run in parallel:
├── player_game_summary
├── team_defense_game_summary
├── team_offense_game_summary
├── upcoming_player_game_context
└── upcoming_team_game_context
```

### Within Phase 4: MUST Run Sequentially ⚠️

```
MUST run in this order:
1. team_defense_zone_analysis (reads Phase 3 only)
2. player_shot_zone_analysis (reads Phase 3 only)
3. player_composite_factors (reads #1, #2, and Phase 3)
4. player_daily_cache (reads #1, #2, #3, and Phase 3)
5. ml_feature_store (reads #1, #2, #3, #4)
```

**If you parallelize Phase 4 processors, they WILL fail!**

---

## 🔍 What the Safeguards Actually Do in Backfill Mode

### Safeguards Still Active in Backfill Mode

| Safeguard | Normal Mode | Backfill Mode | Impact |
|-----------|-------------|---------------|--------|
| Dependency checks | Strict (configured min) | Relaxed (min=1) | Still validates data exists |
| Data extraction | Full | Full | No change |
| BigQuery writes | Full | Full | No change |
| Run history logging | Yes | Yes | Can track progress |
| Deduplication | Yes | Yes | Skip already-processed |

### Safeguards Disabled in Backfill Mode

| Safeguard | Normal Mode | Backfill Mode | Risk |
|-----------|-------------|---------------|------|
| Defensive checks (gap detection) | Blocks if gaps | **SKIPPED** | Won't catch gaps proactively |
| Upstream processor status check | Blocks if failed | **SKIPPED** | Won't know if Phase 3 failed |
| Alert notifications | Sends immediately | **SUPPRESSED** | Won't get error emails |
| Stale data FAIL threshold | 72h = fail | **WARN only** | Processes stale data silently |

### Critical Implication

**In backfill mode, the system TRUSTS that you've validated everything before running.** The safety nets are intentionally lowered to allow processing incomplete historical data.

---

## 🎯 Recommended Execution Strategy

### Strategy: Season-by-Season with Validation Gates

Instead of backfilling all 4 years at once, process one season at a time:

```
Season 1: 2021-22 (Oct 2021 - Apr 2022)
├── Phase 2 all dates → Validate
├── Phase 3 all dates → Validate
├── Phase 4 all dates → Validate
└── CHECKPOINT: Confirm 100% complete

Season 2: 2022-23 (Oct 2022 - Apr 2023)
├── Phase 2 all dates → Validate
├── Phase 3 all dates → Validate (now has Season 1 for context)
├── Phase 4 all dates → Validate
└── CHECKPOINT: Confirm 100% complete

Season 3: 2023-24 (Oct 2023 - Apr 2024)
... same pattern ...

Season 4: 2024-25 (Oct 2024 - Present)
... same pattern ...
```

**Benefits:**
1. Smaller blast radius if something goes wrong
2. Natural checkpoints every ~180 dates
3. Early seasons become historical context for later seasons
4. Easier to diagnose issues within a bounded set

---

## 🔧 Troubleshooting: What Could Go Wrong

### Failure Scenario 1: Phase 2 Has Gaps (GCS Files Missing)

**Symptoms:**
```
FileNotFoundError: gs://nba-scraped-data/.../2022-03-15/... not found
```

**Diagnosis:**
```sql
-- Find Phase 2 gaps
WITH expected AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
),
actual AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
)
SELECT e.game_date as missing_date
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY e.game_date;
```

**Recovery:**
1. Identify missing GCS files
2. Check if scrapers ran for those dates
3. Re-run Phase 1 scrapers for missing dates
4. Then re-run Phase 2 for those dates

**Prevention:**
- Before Phase 3, run validation query above
- Fix ALL gaps before proceeding

---

### Failure Scenario 2: Phase 3 Processor Fails Mid-Season

**Symptoms:**
```
Processing date 50/180...
Error: BigQuery timeout
Processing stopped
```

**Diagnosis:**
```sql
-- Find where Phase 3 stopped
SELECT
  data_date,
  processor_name,
  status,
  error_message
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date BETWEEN '2022-10-01' AND '2023-04-15'
  AND status = 'failed'
ORDER BY data_date;
```

**Recovery:**
```bash
# Backfill is resumable! Just re-run the script
# It will skip already-processed dates
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=2022-10-01 \
  --end-date=2023-04-15 \
  --skip-downstream-trigger=true
```

**Prevention:**
- Run in tmux/screen session
- Monitor progress actively
- Use `nohup` for long-running jobs

---

### Failure Scenario 3: Phase 4 Runs Without Complete Phase 3

**Symptoms:**
```
player_shot_zone_analysis: Processing 2023-01-15
quality_score: 0 (expected 100)
games_used: 0 (expected 10)
```

**This is the SILENT FAILURE you're worried about!**

**Diagnosis:**
```sql
-- Check if Phase 3 is complete for lookback window
WITH target_date AS (SELECT DATE '2023-01-15' as d),
lookback AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB((SELECT d FROM target_date), INTERVAL 30 DAY),
    DATE_SUB((SELECT d FROM target_date), INTERVAL 1 DAY)
  )) as date
),
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
)
SELECT
  l.date,
  CASE WHEN p.game_date IS NOT NULL THEN '✅' ELSE '❌ MISSING' END as status
FROM lookback l
LEFT JOIN phase3_dates p ON l.date = p.game_date
WHERE p.game_date IS NULL;
```

**Recovery:**
1. STOP Phase 4 immediately
2. Identify missing Phase 3 dates
3. Backfill Phase 3 for those dates
4. Validate Phase 3 complete
5. Re-run Phase 4 (may need to delete bad data first)

**Prevention:**
- ALWAYS validate Phase 3 complete before Phase 4
- Use the validation query before EVERY Phase 4 run

---

### Failure Scenario 4: Phase 4 Processors Run Out of Order

**Symptoms:**
```
player_composite_factors: Error
KeyError: 'player_shot_zone_analysis' - table not found
```

**Root Cause:**
Phase 4 processors have internal dependencies:
- `player_composite_factors` needs `player_shot_zone_analysis` and `team_defense_zone_analysis`
- If those haven't run yet, composite_factors fails

**Recovery:**
```bash
# Run in correct order
./bin/run_backfill.sh precompute/team_defense_zone_analysis --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_composite_factors --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_daily_cache --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/ml_feature_store --start-date=$DATE --end-date=$DATE
```

**Prevention:**
- NEVER parallelize Phase 4 processors for the same date
- Create a single script that runs them in order

---

### Failure Scenario 5: Alert Suppression Hides Real Errors

**Symptoms:**
```
Backfill completed "successfully"
But 50 dates have status='failed' in processor_run_history
No emails received
```

**Diagnosis:**
```sql
-- Check for hidden failures
SELECT
  data_date,
  processor_name,
  status,
  SUBSTR(CAST(errors AS STRING), 1, 200) as error_preview
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date BETWEEN '2022-10-01' AND '2023-04-15'
  AND status = 'failed'
ORDER BY data_date;
```

**Recovery:**
- Re-run failed dates individually
- Check the specific error messages

**Prevention:**
- Query processor_run_history periodically during backfill
- Set up a monitoring script to check every 30 minutes

---

### Failure Scenario 6: Early Season Data Causes Low Quality Scores

**Symptoms:**
```
2022-10-25: quality_score = 20 (player only has 2 games)
2022-10-27: quality_score = 30 (player has 3 games)
```

**This is EXPECTED behavior, not a failure!**

**Why:**
- First 2-3 weeks of each season have insufficient history
- Players only have 0-10 games of data
- Phase 4 can't compute meaningful rolling averages

**What to do:**
- Accept degraded quality for first 30 days of each season
- `early_season_flag = true` marks these records
- Don't try to "fix" this - it's architecturally correct

---

### Failure Scenario 7: Cross-Season Boundary Issues

**Symptoms:**
```
2023-10-22 (season start): quality_score = 0
But 2022-23 season data exists!
```

**Root Cause:**
Processors only look within the current season for historical data.
Oct 22, 2023 has zero 2023-24 season games (it's day 1).

**This is INTENTIONAL:**
- Season boundaries reset rolling averages
- New season = fresh start for stats

**What to do:**
- Accept that first 2-3 weeks of each season have low quality
- This is statistically correct behavior

---

## 📊 Validation Queries: Run These at Each Checkpoint

### Query 1: Phase 2 Completeness (Run Before Phase 3)

```sql
-- How many dates have Phase 2 data?
SELECT
  'Phase 2' as phase,
  COUNT(DISTINCT game_date) as dates_with_data,
  (SELECT COUNT(DISTINCT game_date)
   FROM `nba-props-platform.nba_raw.nbac_schedule`
   WHERE game_status = 3
     AND game_date BETWEEN '2021-10-01' AND '2024-11-29') as expected_dates,
  ROUND(COUNT(DISTINCT game_date) * 100.0 /
    (SELECT COUNT(DISTINCT game_date)
     FROM `nba-props-platform.nba_raw.nbac_schedule`
     WHERE game_status = 3
       AND game_date BETWEEN '2021-10-01' AND '2024-11-29'), 1) as pct_complete
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29';
```

**Expected:** 100% complete before starting Phase 3

---

### Query 2: Phase 3 Completeness (Run Before Phase 4)

```sql
-- All 5 Phase 3 processors complete?
WITH expected AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3 AND game_date BETWEEN '2021-10-01' AND '2024-11-29'
)
SELECT
  processor,
  actual_dates,
  (SELECT cnt FROM expected) as expected_dates,
  ROUND(actual_dates * 100.0 / (SELECT cnt FROM expected), 1) as pct_complete
FROM (
  SELECT 'player_game_summary' as processor,
         COUNT(DISTINCT game_date) as actual_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'team_defense_game_summary', COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'team_offense_game_summary', COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'upcoming_player_game_context', COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'upcoming_team_game_context', COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
);
```

**Expected:** ALL 5 processors at 100% before starting Phase 4

---

### Query 3: Find Failures in processor_run_history

```sql
-- Any failed runs?
SELECT
  phase,
  processor_name,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT CAST(data_date AS STRING) LIMIT 5) as sample_failed_dates
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND data_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY phase, processor_name
ORDER BY failure_count DESC;
```

**Expected:** Zero failures (or understand and accept each one)

---

### Query 4: Phase 4 Quality Score Distribution

```sql
-- After Phase 4, check quality distribution
SELECT
  CASE
    WHEN quality_score >= 90 THEN '90-100 (Good)'
    WHEN quality_score >= 70 THEN '70-89 (Acceptable)'
    WHEN quality_score >= 50 THEN '50-69 (Degraded)'
    ELSE '0-49 (Poor)'
  END as quality_bucket,
  COUNT(*) as record_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
GROUP BY 1
ORDER BY 1;
```

**Expected:**
- 80%+ in "Good" bucket after first 30 days of each season
- "Poor" only in first 2-3 weeks of each season

---

## 📝 Monitoring During Backfill

### Active Monitoring Script

Run this in a separate terminal during backfill:

```bash
#!/bin/bash
# monitor_backfill.sh

while true; do
  clear
  echo "=== BACKFILL MONITOR - $(date) ==="
  echo ""

  # Count completed dates per phase
  bq query --use_legacy_sql=false --format=pretty "
  SELECT
    'Phase 2' as phase, COUNT(DISTINCT game_date) as completed
  FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'Phase 3 (player)', COUNT(DISTINCT game_date)
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  UNION ALL
  SELECT 'Phase 4 (shot_zone)', COUNT(DISTINCT game_date)
  FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  "

  echo ""
  echo "=== RECENT FAILURES ==="
  bq query --use_legacy_sql=false --format=pretty "
  SELECT data_date, processor_name, status
  FROM \`nba-props-platform.nba_reference.processor_run_history\`
  WHERE status = 'failed'
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
  ORDER BY started_at DESC
  LIMIT 10
  "

  echo ""
  echo "Refreshing in 5 minutes..."
  sleep 300
done
```

---

## ✅ Pre-Backfill Checklist

Before starting the backfill:

- [ ] Verify Phase 2 100% complete (run Query 1)
- [ ] All processors deployed to Cloud Run
- [ ] All BigQuery tables exist with correct schemas
- [ ] Test with 1 date first (full Phase 2-4 for 2023-11-01)
- [ ] Set up monitoring terminal
- [ ] Running in tmux/screen session
- [ ] Have this document open for reference
- [ ] Know how to stop backfill if needed

---

## 🚀 Quick Reference Commands

### Check what's missing
```bash
# Phase 2 gaps
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`"

# Phase 3 gaps
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.player_game_summary\`"
```

### Run single date (test)
```bash
DATE="2023-11-01"
./bin/run_backfill.sh analytics/player_game_summary --start-date=$DATE --end-date=$DATE --skip-downstream-trigger=true
```

### Run Phase 4 in correct order
```bash
DATE="2023-11-01"
./bin/run_backfill.sh precompute/team_defense_zone_analysis --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_composite_factors --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/player_daily_cache --start-date=$DATE --end-date=$DATE
./bin/run_backfill.sh precompute/ml_feature_store --start-date=$DATE --end-date=$DATE
```

### Find failures
```bash
bq query --use_legacy_sql=false "SELECT data_date, processor_name FROM \`nba-props-platform.nba_reference.processor_run_history\` WHERE status='failed' ORDER BY data_date LIMIT 20"
```

---

## 📌 Key Takeaways

1. **Your instinct is right**: Backfill Phase 1 & 2 completely before Phase 3 & 4
2. **Phase 3 processors can run in parallel**
3. **Phase 4 processors MUST run in sequence** (they depend on each other)
4. **Validate after EVERY phase** using the queries above
5. **Season-by-season is safer** than all-at-once
6. **Monitor processor_run_history** - alerts are suppressed in backfill mode
7. **Early season low quality is expected** - not a bug

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29 21:12 PST
