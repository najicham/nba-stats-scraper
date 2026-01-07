# 🔍 Validation Queries - Ready for Jan 4, 2026
**Created**: January 3, 2026 (evening)
**Purpose**: Validate Phase 1/2 backfill completion before Phase 4 & ML training
**Status**: READY TO EXECUTE (when backfills complete)

---

## 📊 CURRENT STATE (Jan 3, 11:26 PM PST)

### Running Backfills
- **Phase 1**: team_offense_game_summary (PID 3022978)
  - Progress: 465/1537 days (30%)
  - ETA: ~7:30-8:00 PM PST Jan 3 (or early Jan 4)
  - Purpose: Enable usage_rate calculation

- **Phase 2**: player_game_summary (will auto-start after Phase 1)
  - Dates: 2024-05-01 to 2026-01-02
  - Purpose: Fix minutes_played, add usage_rate, fix shot_zones
  - ETA: Unknown (likely 2-4 hours after Phase 1)

### Critical Issues Being Fixed
| Issue | Current State | Target State | Fix |
|-------|---------------|--------------|-----|
| usage_rate | 0% ALL YEARS | 95-99% | Phase 1+2 backfill |
| minutes_played (2025-26) | 27% | 99%+ | Phase 2 backfill |
| shot_zones (2025-26) | 0% | 40-50% | Phase 2 backfill |
| Phase 4 coverage | 26.5% | 88%+ | Phase 4 backfill (after Phase 2) |

---

## ✅ STEP 1: CHECK BACKFILL COMPLETION

### 1.1: Check if Backfills Still Running

```bash
# Check for running processes
ps aux | grep backfill | grep -v grep

# Expected: No processes (both complete)
# If still running, wait and check logs
```

### 1.2: Check Orchestrator Final Status

```bash
# Check orchestrator log
tail -100 logs/orchestrator_20260103_134700.log

# Look for:
# - "PHASE 1 VALIDATION: PASSED"
# - "PHASE 2 STARTED"
# - "PHASE 2 VALIDATION: PASSED"
# - Final completion message
```

### 1.3: Check Phase 1 Final Summary

```bash
# Check Phase 1 log final lines
tail -200 logs/team_offense_backfill_phase1.log | grep -i "summary\|complete\|success rate\|total records"

# Expected:
# - Success rate ≥95%
# - Total records ~6,000-7,000 (2 per game × ~1,500 days)
# - "BACKFILL COMPLETE" message
```

### 1.4: Check Phase 2 Final Summary

```bash
# Find Phase 2 log file (orchestrator will show path)
# Should be something like: logs/player_game_summary_backfill_phase2.log

tail -200 logs/player_game_summary_backfill_phase2.log | grep -i "summary\|complete\|success rate\|total records"

# Expected:
# - Success rate ≥95%
# - Total records ~35,000-40,000 (player-games from May 2024 to Jan 2026)
# - "BACKFILL COMPLETE" message
```

**Decision Point:**
- ✅ Both complete, success rate ≥95% → Proceed to Phase 1 validation
- ⏸️ Still running → Wait, check back in 1 hour
- ❌ Failed → Check error logs, debug, may need to re-run

---

## ✅ STEP 2: VALIDATE PHASE 1 (Team Offense)

### 2.1: Overall Coverage Check

```sql
-- Check Phase 1 team_offense_game_summary data
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(DISTINCT game_id) as unique_games,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(*) * 100.0 / (1537 * 2) as expected_coverage_pct
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date >= '2021-10-19' AND game_date <= '2026-01-02';

-- Expected:
-- total_records: 6,000-7,000 (2 teams per game)
-- unique_dates: 1,500-1,537 (may have All-Star gaps)
-- unique_games: 3,000-3,500
-- earliest_date: 2021-10-19
-- latest_date: 2026-01-02
-- expected_coverage_pct: ≥95%
```

**Acceptance Criteria:**
- [ ] Total records: ≥6,000
- [ ] Coverage: ≥95%
- [ ] Date range matches: 2021-10-19 to 2026-01-02

### 2.2: Critical Fields Completeness

```sql
-- Check that all required fields for usage_rate calculation are populated
SELECT
  COUNTIF(possessions IS NOT NULL) * 100.0 / COUNT(*) as possessions_pct,
  COUNTIF(team_fga IS NOT NULL) * 100.0 / COUNT(*) as team_fga_pct,
  COUNTIF(team_fta IS NOT NULL) * 100.0 / COUNT(*) as team_fta_pct,
  COUNTIF(team_to IS NOT NULL) * 100.0 / COUNT(*) as team_to_pct,
  COUNTIF(pace IS NOT NULL) * 100.0 / COUNT(*) as pace_pct,
  COUNTIF(offensive_rating IS NOT NULL) * 100.0 / COUNT(*) as off_rating_pct,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date >= '2021-10-19';

-- Expected: All ≥99%
```

**Acceptance Criteria:**
- [ ] All critical fields ≥99% populated
- [ ] possessions, FGA, FTA, TO all present (needed for usage_rate)

### 2.3: Quality Distribution

```sql
-- Check quality tiers
SELECT
  quality_tier,
  COUNT(*) as count,
  COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as pct
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date >= '2021-10-19'
GROUP BY quality_tier
ORDER BY count DESC;

-- Expected: Gold ≥80%, Silver ≥10%, Bronze+Poor+Unusable <10%
```

**Acceptance Criteria:**
- [ ] Gold + Silver ≥90%
- [ ] Production ready ≥80%

### 2.4: Spot Check (Recent Game)

```sql
-- Pick a recent Lakers game and verify stats look correct
SELECT
  game_date,
  team_abbr,
  opponent_team_abbr,
  points_scored,
  team_fga,
  team_fta,
  team_to,
  possessions,
  pace,
  offensive_rating,
  quality_tier
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE team_abbr = 'LAL'
  AND game_date >= '2025-12-01'
ORDER BY game_date DESC
LIMIT 5;

-- Manual check: Do points/stats look realistic?
-- Expected: Points 100-130, possessions 95-105, pace 95-105, offensive_rating 100-120
```

**Acceptance Criteria:**
- [ ] Stats look realistic (not all zeros, not extreme outliers)
- [ ] Recent games present (through Jan 2)

### ✅ Phase 1 Decision: PASS / FAIL

**If PASS (all criteria met):**
→ Proceed to Phase 2 validation

**If FAIL:**
→ Investigate issues, may need targeted re-run
→ Do NOT proceed to Phase 2 validation until fixed

---

## ✅ STEP 3: VALIDATE PHASE 2 (Player Game Summary) - CRITICAL

### 3.1: Overall Coverage Check

```sql
-- Check Phase 2 player_game_summary for the backfilled date range
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-05-01' AND game_date <= '2026-01-02';

-- Expected:
-- total_records: 35,000-40,000 (player-games)
-- unique_dates: 240-280 (game days from May 2024 to Jan 2026)
-- unique_players: 400-600 (active players)
-- earliest_date: 2024-05-01 (or first game day after)
-- latest_date: 2026-01-02
```

**Acceptance Criteria:**
- [ ] Total records: ≥35,000
- [ ] Unique dates: ≥240
- [ ] Date range matches: 2024-05-01 to 2026-01-02

### 3.2: 🔴 CRITICAL: usage_rate Coverage (NEW FEATURE)

```sql
-- Check usage_rate coverage - THIS IS THE KEY BUG FIX
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
  COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*) as usage_rate_pct,
  AVG(usage_rate) as avg_usage_rate,
  MIN(usage_rate) as min_usage_rate,
  MAX(usage_rate) as max_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND points IS NOT NULL  -- Active players only
GROUP BY year
ORDER BY year;

-- Expected:
-- 2021-2023: 95-99% coverage (if Phase 1 backfilled full history)
-- 2024-2026: 95-99% coverage (Phase 2 backfill)
-- avg_usage_rate: 20-25% (realistic)
-- min: 5-10%, max: 40-50%
```

**Acceptance Criteria:**
- [ ] **2024-2026 usage_rate: ≥95%** (CRITICAL - was 0%)
- [ ] Average usage_rate: 18-28% (realistic range)
- [ ] No extreme outliers (min >0%, max <60%)

### 3.3: 🔴 CRITICAL: minutes_played Coverage (BUG FIX)

```sql
-- Check minutes_played coverage - CRITICAL BUG FIX
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_records,
  COUNTIF(minutes_played IS NOT NULL) as has_minutes,
  COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*) as minutes_pct,
  AVG(minutes_played) as avg_minutes,
  COUNTIF(minutes_played IS NULL AND points > 0) as null_with_points
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND points IS NOT NULL
GROUP BY year
ORDER BY year;

-- Expected:
-- 2024-2026: 99%+ coverage (was 27% for 2025-26)
-- avg_minutes: 20-30 minutes
-- null_with_points: 0-10 (should be rare)
```

**Acceptance Criteria:**
- [ ] **2024-2026 minutes_played: ≥99%** (CRITICAL - was 27%)
- [ ] Average minutes: 18-32 minutes (realistic)
- [ ] null_with_points: <50 (rare edge cases only)

### 3.4: Shot Distribution Coverage (BUG FIX)

```sql
-- Check shot zone coverage - BIG DATA BALL FORMAT FIX
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_records,
  COUNTIF(paint_attempts IS NOT NULL) * 100.0 / COUNT(*) as paint_pct,
  COUNTIF(mid_range_attempts IS NOT NULL) * 100.0 / COUNT(*) as mid_range_pct,
  COUNTIF(three_pt_attempts IS NOT NULL) * 100.0 / COUNT(*) as three_pt_pct,
  COUNTIF(assisted_fg_makes IS NOT NULL) * 100.0 / COUNT(*) as assisted_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND points IS NOT NULL
GROUP BY year
ORDER BY year;

-- Expected:
-- 2021-2023: 86-88% (historical - no change)
-- 2024: 40-60% (BigDataBall format fixed)
-- 2025-2026: 40-60% (was 0%)
```

**Acceptance Criteria:**
- [ ] **2024-2026 shot zones: ≥40%** (CRITICAL - was 0%)
- [ ] three_pt_attempts: ≥99% (always available)
- [ ] Historical (2021-2023): ≥80% maintained

### 3.5: Quality Distribution

```sql
-- Check data quality tiers for recent data
SELECT
  quality_tier,
  COUNT(*) as count,
  COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-05-01'
GROUP BY quality_tier
ORDER BY count DESC;

-- Expected: Gold ≥60%, Gold+Silver ≥80%, Production Ready ≥95%
```

**Acceptance Criteria:**
- [ ] Gold + Silver ≥80%
- [ ] Production ready ≥95%

### 3.6: Duplicate Check

```sql
-- Check for duplicates (should be ZERO)
SELECT
  game_id,
  player_lookup,
  COUNT(*) as dup_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2024-05-01'
GROUP BY game_id, player_lookup
HAVING COUNT(*) > 1
ORDER BY dup_count DESC
LIMIT 20;

-- Expected: 0 rows
```

**Acceptance Criteria:**
- [ ] Zero duplicates (CRITICAL)

### 3.7: Spot Check - LeBron James Recent Games

```sql
-- Pick LeBron James and verify stats look correct
SELECT
  game_date,
  opponent_team_abbr,
  points,
  minutes_played,
  usage_rate,
  paint_attempts,
  mid_range_attempts,
  three_pt_attempts,
  quality_tier
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE player_lookup = 'lebronjames'
  AND game_date >= '2025-12-01'
ORDER BY game_date DESC
LIMIT 10;

-- Manual verification:
-- - Points: 15-35 range (realistic for LeBron)
-- - Minutes: 30-38 (realistic starter minutes)
-- - usage_rate: 25-35% (high usage player)
-- - Shot attempts populated (paint/mid/three)
-- - Quality: Gold or Silver
```

**Acceptance Criteria:**
- [ ] All stats look realistic (no zeros, no extreme outliers)
- [ ] usage_rate present (NEW - was NULL)
- [ ] minutes_played present (was sometimes NULL)
- [ ] Shot zones present (was NULL for 2025)

### 3.8: Cross-Check Phase 1 → Phase 2 (usage_rate dependency)

```sql
-- Verify usage_rate calculation uses team_offense data correctly
SELECT
  p.game_date,
  p.player_lookup,
  p.points,
  p.minutes_played,
  p.usage_rate,
  p.fg_attempts,
  p.fta,
  p.turnovers,
  t.team_fga,
  t.team_fta,
  t.team_to,
  t.possessions
FROM `nba-props-platform.nba_analytics.player_game_summary` p
JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr
WHERE p.game_date >= '2025-12-01'
  AND p.points > 20  -- High scorers
  AND p.usage_rate IS NOT NULL
ORDER BY p.usage_rate DESC
LIMIT 10;

-- Manual check:
-- - usage_rate should correlate with FGA + FTA + TO
-- - High scorers should have usage_rate 25-40%
-- - Team totals should be populated (team_fga, team_fta, team_to)
-- - Possessions should be realistic (95-110)
```

**Acceptance Criteria:**
- [ ] High scorers have high usage_rate (makes sense)
- [ ] Team data populated (join successful)
- [ ] usage_rate formula appears correct (spot check calculations)

### ✅ Phase 2 Decision: PASS / FAIL

**If PASS (all criteria met):**
→ Phase 2 backfill successful, all bug fixes applied
→ Proceed to Phase 4 backfill planning

**If FAIL on usage_rate (<90%):**
→ CRITICAL - Check Phase 1 completion, re-run Phase 2 if needed
→ Do NOT proceed to Phase 4 until fixed

**If FAIL on minutes_played (<95%):**
→ CRITICAL - Check for data format issues, investigate
→ Do NOT proceed to ML training until fixed

**If FAIL on shot_zones (<30% for 2024-26):**
→ WARNING - Check BigDataBall format fix, may be acceptable if >30%
→ Can proceed but ML model may underperform slightly

---

## ✅ STEP 4: VALIDATE FULL TRAINING DATA (2021-2024)

### 4.1: Training Data Readiness

```sql
-- Check the full training data range with all features
SELECT
  COUNT(*) as total_training_samples,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(DISTINCT player_lookup) as unique_players,

  -- CRITICAL FEATURES
  COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*) as minutes_pct,
  COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*) as usage_rate_pct,

  -- Other key features
  COUNTIF(points IS NOT NULL) * 100.0 / COUNT(*) as points_pct,
  COUNTIF(fg_attempts IS NOT NULL) * 100.0 / COUNT(*) as fga_pct,
  COUNTIF(three_pt_attempts IS NOT NULL) * 100.0 / COUNT(*) as three_pct,
  COUNTIF(paint_attempts IS NOT NULL) * 100.0 / COUNT(*) as paint_pct,

  -- Averages for sanity check
  AVG(points) as avg_points,
  AVG(minutes_played) as avg_minutes,
  AVG(usage_rate) as avg_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date <= '2024-05-01'
  AND points IS NOT NULL;

-- Expected:
-- total_training_samples: 50,000-60,000
-- minutes_pct: ≥99%
-- usage_rate_pct: ≥90% (CRITICAL - was 0%)
-- points_pct: 100%
-- avg_points: 10-15
-- avg_minutes: 20-28
-- avg_usage_rate: 18-25%
```

**Acceptance Criteria:**
- [ ] Training samples: ≥50,000
- [ ] **usage_rate: ≥90%** (CRITICAL - enables ML training)
- [ ] minutes_played: ≥99%
- [ ] Other features: ≥95%

### 4.2: Feature Completeness by Season

```sql
-- Break down feature coverage by season for training data
SELECT
  CASE
    WHEN game_date >= '2021-10-01' AND game_date < '2022-07-01' THEN '2021-22'
    WHEN game_date >= '2022-10-01' AND game_date < '2023-07-01' THEN '2022-23'
    WHEN game_date >= '2023-10-01' AND game_date < '2024-07-01' THEN '2023-24'
  END as season,
  COUNT(*) as records,
  COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*) as minutes_pct,
  COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*) as usage_rate_pct,
  COUNTIF(paint_attempts IS NOT NULL) * 100.0 / COUNT(*) as paint_pct,
  AVG(usage_rate) as avg_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date <= '2024-05-01'
  AND points IS NOT NULL
GROUP BY season
ORDER BY season;

-- Expected: usage_rate 90%+ for all seasons (was 0%)
```

**Acceptance Criteria:**
- [ ] All seasons have usage_rate ≥90%
- [ ] No season has <50,000 total records across all seasons
- [ ] Average usage_rate realistic (18-28%)

### 4.3: Missing Data Analysis

```sql
-- Identify where data is still missing (for ML training context)
SELECT
  'minutes_played' as feature,
  COUNTIF(minutes_played IS NULL) as null_count,
  COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date <= '2024-05-01'
  AND points IS NOT NULL

UNION ALL

SELECT
  'usage_rate' as feature,
  COUNTIF(usage_rate IS NULL) as null_count,
  COUNTIF(usage_rate IS NULL) * 100.0 / COUNT(*) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date <= '2024-05-01'
  AND points IS NOT NULL

UNION ALL

SELECT
  'paint_attempts' as feature,
  COUNTIF(paint_attempts IS NULL) as null_count,
  COUNTIF(paint_attempts IS NULL) * 100.0 / COUNT(*) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date <= '2024-05-01'
  AND points IS NOT NULL

ORDER BY null_pct DESC;

-- Understand what's still missing - acceptable if:
-- - minutes_played: <1% NULL
-- - usage_rate: <10% NULL
-- - paint_attempts: <30% NULL (season dependent)
```

**Acceptance Criteria:**
- [ ] minutes_played: <1% NULL
- [ ] usage_rate: <10% NULL (CRITICAL)
- [ ] paint_attempts: <30% NULL acceptable

### ✅ Training Data Decision: GO / NO-GO for ML Training

**GO Criteria (ALL must be met):**
- [ ] Training samples ≥50,000
- [ ] usage_rate ≥90% (was 0%)
- [ ] minutes_played ≥99%
- [ ] No critical data quality issues
- [ ] All spot checks look realistic

**NO-GO Criteria (ANY triggers):**
- [ ] usage_rate <80% (insufficient for training)
- [ ] minutes_played <95% (insufficient for training)
- [ ] Training samples <40,000 (insufficient volume)
- [ ] Major data quality issues (duplicates, corrupted values)

---

## ✅ STEP 5: PLAN PHASE 4 BACKFILL

### 5.1: Check Current Phase 4 State

```sql
-- Check what Phase 4 data already exists
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as unique_dates,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNTIF(fatigue_score IS NOT NULL) * 100.0 / COUNT(*) as fatigue_pct,
  COUNTIF(shot_zone_mismatch_score IS NOT NULL) * 100.0 / COUNT(*) as shot_zone_pct,
  COUNTIF(pace_score IS NOT NULL) * 100.0 / COUNT(*) as pace_pct,
  COUNTIF(usage_spike_score IS NOT NULL) * 100.0 / COUNT(*) as usage_spike_pct
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-10-01';

-- Current state (as of Jan 3):
-- total_records: 13,360
-- unique_dates: 74
-- Coverage: 26.5% (74/279 dates)
-- All factors: 100% when present
```

### 5.2: Calculate Phase 4 Gap

```sql
-- Identify missing dates that need Phase 4 backfill
WITH expected_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-15'  -- Skip first 14 days (bootstrap)
    AND game_date <= '2026-01-02'
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2024-10-15'
),
missing_dates AS (
  SELECT e.game_date
  FROM expected_dates e
  WHERE NOT EXISTS (
    SELECT 1 FROM actual_dates a WHERE a.game_date = e.game_date
  )
)
SELECT
  (SELECT COUNT(*) FROM expected_dates) as expected_dates,
  (SELECT COUNT(*) FROM actual_dates) as actual_dates,
  (SELECT COUNT(*) FROM missing_dates) as missing_dates,
  (SELECT COUNT(*) FROM actual_dates) * 100.0 / (SELECT COUNT(*) FROM expected_dates) as current_coverage_pct,
  ((SELECT COUNT(*) FROM actual_dates) + (SELECT COUNT(*) FROM missing_dates)) * 100.0 / (SELECT COUNT(*) FROM expected_dates) as target_coverage_pct;

-- This tells you:
-- - How many dates still need processing
-- - Current vs target coverage
-- - Gap to close with Phase 4 backfill
```

### 5.3: Estimate Phase 4 Workload

```sql
-- Get list of missing dates with game counts
WITH missing_dates AS (
  SELECT DISTINCT e.game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary` e
  WHERE e.game_date >= '2024-10-15'
    AND e.game_date <= '2026-01-02'
    AND NOT EXISTS (
      SELECT 1
      FROM `nba-props-platform.nba_precompute.player_composite_factors` a
      WHERE a.game_date = e.game_date
    )
)
SELECT
  m.game_date,
  COUNT(DISTINCT p.game_id) as games_on_date,
  COUNT(DISTINCT p.player_lookup) as players_on_date
FROM missing_dates m
LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` p
  ON m.game_date = p.game_date
  AND p.points IS NOT NULL
GROUP BY m.game_date
ORDER BY m.game_date;

-- Export this to CSV for Phase 4 backfill script
-- Estimate time: ~206 dates × 60-90 seconds = 3-4 hours
```

### ✅ Phase 4 Readiness Decision

**Ready to Run Phase 4 Backfill if:**
- [ ] Phase 2 validation PASSED
- [ ] usage_rate ≥90% in training data
- [ ] Missing dates identified (~200-210 dates)
- [ ] Time allocated (3-4 hours)

**NOT Ready if:**
- [ ] Phase 2 validation FAILED
- [ ] Critical features still missing
- [ ] Data quality issues unresolved

---

## ✅ STEP 6: FINAL GO/NO-GO FOR ML TRAINING

### 6.1: Pre-ML Training Checklist

Run this query before starting ML training:

```sql
-- Final comprehensive check before ML training
WITH training_data AS (
  SELECT
    p3.game_id,
    p3.player_lookup,
    p3.game_date,
    p3.points,
    p3.minutes_played,
    p3.usage_rate,
    p3.fg_attempts,
    p3.three_pt_attempts,
    p3.paint_attempts,
    p4.fatigue_score,
    p4.shot_zone_mismatch_score,
    p4.pace_score,
    p4.usage_spike_score
  FROM `nba-props-platform.nba_analytics.player_game_summary` p3
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` p4
    ON p3.game_id = p4.game_id AND p3.player_lookup = p4.player_lookup
  WHERE p3.game_date >= '2021-10-01' AND p3.game_date <= '2024-05-01'
    AND p3.points IS NOT NULL
)
SELECT
  COUNT(*) as total_samples,

  -- Phase 3 features
  COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*) as minutes_pct,
  COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*) as usage_rate_pct,
  COUNTIF(fg_attempts IS NOT NULL) * 100.0 / COUNT(*) as fga_pct,
  COUNTIF(three_pt_attempts IS NOT NULL) * 100.0 / COUNT(*) as three_pct,
  COUNTIF(paint_attempts IS NOT NULL) * 100.0 / COUNT(*) as paint_pct,

  -- Phase 4 features (should have some coverage)
  COUNTIF(fatigue_score IS NOT NULL) * 100.0 / COUNT(*) as phase4_fatigue_pct,
  COUNTIF(shot_zone_mismatch_score IS NOT NULL) * 100.0 / COUNT(*) as phase4_shot_zone_pct,

  -- Sanity checks
  AVG(points) as avg_points,
  AVG(minutes_played) as avg_minutes,
  AVG(usage_rate) as avg_usage_rate,

  -- Data quality
  COUNTIF(minutes_played IS NULL AND points > 0) as corrupt_records
FROM training_data;

-- GO criteria:
-- total_samples: ≥50,000
-- minutes_pct: ≥99%
-- usage_rate_pct: ≥90% (CRITICAL)
-- fga_pct, three_pct: ≥99%
-- paint_pct: ≥70%
-- phase4_fatigue_pct: ≥70% (after Phase 4 backfill)
-- corrupt_records: <100
```

### 6.2: ML Training GO/NO-GO Decision Matrix

| Metric | GO Threshold | Current | Status | Blocking? |
|--------|--------------|---------|--------|-----------|
| Training samples | ≥50,000 | ? | ? | YES |
| minutes_played | ≥99% | ? | ? | YES |
| **usage_rate** | **≥90%** | ? | ? | **YES** |
| fg_attempts | ≥99% | ? | ? | YES |
| three_pt_attempts | ≥99% | ? | ? | YES |
| paint_attempts | ≥70% | ? | ? | NO |
| Phase 4 features | ≥70% | ? | ? | NO |
| Corrupt records | <100 | ? | ? | YES |

**GO Decision:**
- ALL blocking metrics meet threshold → **START ML TRAINING**
- Phase 4 features can use defaults if <70% (not blocking)

**NO-GO Decision:**
- ANY blocking metric fails → **DO NOT START ML TRAINING**
- Fix issues first, re-validate

---

## 📋 QUICK REFERENCE: COPY-PASTE SEQUENCE

### Morning Routine (Jan 4)

```bash
# 1. Check if backfills complete
ps aux | grep backfill | grep -v grep

# 2. Check orchestrator status
tail -100 logs/orchestrator_20260103_134700.log

# 3. If complete, run validation queries in this order:
#    - Step 2: Phase 1 validation (6 queries)
#    - Step 3: Phase 2 validation (8 queries)
#    - Step 4: Training data validation (3 queries)
#    - Step 6: Final GO/NO-GO check (1 query)

# 4. Make GO/NO-GO decision for ML training

# 5. If GO, proceed to ML training:
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
PYTHONPATH=. python ml/train_real_xgboost.py
```

---

## 🎯 SUCCESS CRITERIA SUMMARY

### Phase 1 (Team Offense) - PASS Criteria
- ✅ Records: ≥6,000
- ✅ Coverage: ≥95%
- ✅ All key fields populated: ≥99%
- ✅ Quality: Gold+Silver ≥90%

### Phase 2 (Player Summary) - PASS Criteria
- ✅ Records: ≥35,000
- ✅ **usage_rate: ≥95%** (CRITICAL - was 0%)
- ✅ **minutes_played: ≥99%** (was 27% for 2025-26)
- ✅ **shot_zones: ≥40%** (was 0% for 2025-26)
- ✅ Zero duplicates

### Training Data - GO Criteria
- ✅ Samples: ≥50,000
- ✅ **usage_rate: ≥90%** (CRITICAL)
- ✅ minutes_played: ≥99%
- ✅ Other features: ≥95%

### Phase 4 - Target
- ✅ Coverage: ≥88% (from 26.5%)
- ✅ Missing dates: ~200-210 to backfill
- ✅ Time: 3-4 hours

---

## 🚨 RED FLAGS TO WATCH FOR

### Critical Issues (STOP if found)
- ❌ usage_rate still 0% or <80%
- ❌ minutes_played <95% for 2024-2026
- ❌ Duplicates found in Phase 2 data
- ❌ Training samples <40,000
- ❌ Corrupted data (points >100, minutes >48, usage_rate >100%)

### Warning Issues (Investigate but can proceed)
- ⚠️ Shot zones <30% for 2024-2026
- ⚠️ Phase 4 coverage <80%
- ⚠️ Quality: Gold+Silver <80%
- ⚠️ Some missing dates in Phase 1/2

---

## 📊 EXPECTED OUTCOMES

### Best Case
- ✅ Phase 1 & 2 both PASS all criteria
- ✅ usage_rate 95%+ (was 0%)
- ✅ minutes_played 99%+ (was 27%)
- ✅ Training data ready (50K+ samples)
- ✅ Phase 4 backfill ready to run
- ✅ ML training can start tomorrow

### Expected Case
- ✅ Phase 1 & 2 PASS most criteria
- ✅ usage_rate 90-95% (good enough)
- ✅ minutes_played 97-99% (good enough)
- ⚠️ Shot zones 30-40% (acceptable)
- ✅ ML training can start after Phase 4

### Concerning Case
- ⚠️ usage_rate 80-90% (borderline)
- ⚠️ Some data quality issues
- ⚠️ May need targeted fixes
- ⏸️ ML training delayed until fixes applied

### Failure Case
- ❌ usage_rate still <50%
- ❌ minutes_played still broken
- ❌ Critical bugs not fixed
- ❌ Need to re-run backfills

---

**READY TO EXECUTE**: Jan 4, 2026 (morning)
**ESTIMATED TIME**: 1-2 hours for all validation queries
**NEXT STEP AFTER VALIDATION**: Phase 4 backfill OR ML training (depending on Phase 4 coverage)
**ULTIMATE GOAL**: Train XGBoost v5 with MAE <4.27 (beat baseline)
