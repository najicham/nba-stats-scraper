# Phase 4 Backfill: Data Integrity & Prevention Guide

> **Created:** 2025-12-07 (Session 73)
> **Purpose:** Comprehensive guide for preventing data integrity issues during Phase 4 backfills
> **Status:** Active - Use this for all future backfill operations

---

## Table of Contents

1. [Phase 4 Dependency Chain](#phase-4-dependency-chain)
2. [Issue Categories](#issue-categories)
3. [Data Integrity Issues Found](#data-integrity-issues-found)
4. [Prevention Strategies](#prevention-strategies)
5. [Observability Improvements](#observability-improvements)
6. [Code Changes Required](#code-changes-required)
7. [Validation Queries](#validation-queries)
8. [Runbook: Fixing Data Issues](#runbook-fixing-data-issues)

---

## Phase 4 Dependency Chain

### Visual Dependency Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 4 PROCESSOR DEPENDENCIES                      │
└─────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐           ┌──────────────┐
    │     TDZA     │           │     PSZA     │
    │  Team Defense│           │ Player Shot  │
    │ Zone Analysis│           │ Zone Analysis│
    └──────┬───────┘           └──────┬───────┘
           │                          │
           │    No Phase 4 deps       │    No Phase 4 deps
           │    (run in PARALLEL)     │    (run in PARALLEL)
           │                          │
           └──────────┬───────────────┘
                      │
                      ▼
              ┌───────────────┐
              │      PCF      │
              │    Player     │
              │  Composite    │◄─── Depends on TDZA (opponent matchups)
              │   Factors     │◄─── Depends on PSZA (shot zone data)
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │      PDC      │
              │ Player Daily  │◄─── Depends on PSZA (shot zones)
              │    Cache      │◄─── Depends on PCF (composite factors)
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │      ML       │
              │  ML Feature   │◄─── Depends on ALL upstream processors
              │    Store      │
              └───────────────┘

    ════════════════════════════════════════════════════════════════════

    EXECUTION ORDER (Orchestrator):

    Step 1: TDZA + PSZA ───► Run in PARALLEL (no Phase 4 dependencies)
                │
                ▼
    Step 2: PCF ───────────► Run SEQUENTIALLY (needs Step 1)
                │
                ▼
    Step 3: PDC ───────────► Run SEQUENTIALLY (needs Step 1, 2)
                │
                ▼
    Step 4: ML ────────────► Run SEQUENTIALLY (needs ALL)
```

### Processor Details

| Processor | Table | Dependencies | Key Output |
|-----------|-------|--------------|------------|
| **TDZA** | `team_defense_zone_analysis` | None (Phase 4) | 30 teams per date |
| **PSZA** | `player_shot_zone_analysis` | None (Phase 4) | Cumulative player stats |
| **PCF** | `player_composite_factors` | TDZA, PSZA | Per-game player adjustments |
| **PDC** | `player_daily_cache` | PSZA, PCF | Player rolling averages |
| **ML** | `ml_feature_store_v2` | ALL | ML prediction features |

---

## Issue Categories

### Issue Category Matrix

```
┌────────────────────────────────────────────────────────────────────────┐
│                    BACKFILL DATA ISSUE CATEGORIES                       │
└────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┬──────────────────┬─────────────────┬─────────────┐
│ Category            │ Example          │ Root Cause      │ Severity    │
├─────────────────────┼──────────────────┼─────────────────┼─────────────┤
│ Cascading           │ Dec 4: TDZA=0    │ backfill_mode   │ 🔴 CRITICAL │
│ Incomplete Data     │ PCF has zeros    │ skips checks    │             │
├─────────────────────┼──────────────────┼─────────────────┼─────────────┤
│ Stale Scheduled     │ Dec 16-30: ML    │ Used schedule   │ 🟡 MEDIUM   │
│ Data                │ for postponed    │ not actuals     │             │
├─────────────────────┼──────────────────┼─────────────────┼─────────────┤
│ Bootstrap Gaps      │ Nov 5-19: PDC    │ Players need    │ 🟢 EXPECTED │
│                     │ 18-93% complete  │ 5+ games        │             │
├─────────────────────┼──────────────────┼─────────────────┼─────────────┤
│ True Gaps           │ Dec 23, 31:      │ Backfill never  │ 🔴 CRITICAL │
│                     │ ML=0 records     │ ran             │             │
└─────────────────────┴──────────────────┴─────────────────┴─────────────┘
```

### Detailed Category Explanations

#### 1. Cascading Incomplete Data (CRITICAL)

**What happens:** A downstream processor runs when upstream data is missing, producing incorrect results.

**Example found:** December 4, 2021
- TDZA: 0 records (MISSING)
- PSZA: 351 records (OK)
- PCF: 131 records with `opponent_strength_score = 0` for ALL players
- ML: 131 records built on bad PCF data

**Impact:** Predictions are based on incomplete composite factors.

#### 2. Stale Scheduled Data (MEDIUM)

**What happens:** ML features built from scheduled games that were postponed (COVID, etc.)

**Example found:** December 2021 COVID outbreak
- Dec 16, 17, 18, 20, 21, 25, 28, 30: Games were SCHEDULED but POSTPONED
- ML has feature records for games that never happened

**Impact:** Wasted storage, potential confusion in analysis.

#### 3. Bootstrap Gaps (EXPECTED)

**What happens:** Early season dates have low completeness because players need game history.

**Example:** November 5-19, 2021
- PDC completeness starts at 18% (Nov 5)
- Grows to 93% by Nov 19
- Failures show: "Only 0 games played, need 5 minimum"

**Impact:** Expected behavior - not an error.

#### 4. True Gaps (CRITICAL)

**What happens:** Backfill never ran for certain dates.

**Example:** December 23 and 31, 2021
- Games happened (12 and 10 games respectively)
- ML has 0 records - backfill simply stopped before these dates

**Impact:** Missing predictions for actual games.

---

## Data Integrity Issues Found

### December 2021 Analysis

```
┌────────────────────────────────────────────────────────────────────────┐
│              DECEMBER 2021 DATA STATE (COVID OUTBREAK)                  │
└────────────────────────────────────────────────────────────────────────┘

Date       │ Scheduled │ Played │ Status     │ ML Data    │ Issue
───────────┼───────────┼────────┼────────────┼────────────┼─────────────
Dec 15     │    11     │   11   │ OK         │ ✓ OK       │ None
Dec 16     │     4     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 17     │     8     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 18     │     7     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 19     │     6     │    9   │ PARTIAL    │ ✓ OK       │ None
Dec 20     │     6     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 21     │     5     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 23     │    11     │   12   │ PARTIAL    │ ❌ MISSING │ True gap
Dec 25     │     5     │    0   │ POSTPONED  │ (none)     │ OK (Christmas)
Dec 26     │     8     │    8   │ OK         │ ✓ PARTIAL  │ 78% complete
Dec 28     │     8     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 29     │     8     │    9   │ PARTIAL    │ ✓ PARTIAL  │ 56% complete
Dec 30     │     3     │    0   │ POSTPONED  │ ⚠ STALE    │ Data for no game
Dec 31     │    10     │   10   │ OK         │ ❌ MISSING │ True gap
```

### Specific Data Integrity Issue: Dec 4, 2021

```sql
-- This query reveals the cascading data issue

SELECT
  "TDZA" as processor, COUNT(*) as records FROM team_defense_zone_analysis WHERE analysis_date = "2021-12-04"
UNION ALL SELECT "PSZA", COUNT(*) FROM player_shot_zone_analysis WHERE analysis_date = "2021-12-04"
UNION ALL SELECT "PCF", COUNT(*) FROM player_composite_factors WHERE game_date = "2021-12-04"
UNION ALL SELECT "PDC", COUNT(*) FROM player_daily_cache WHERE cache_date = "2021-12-04"
UNION ALL SELECT "ML", COUNT(*) FROM ml_feature_store_v2 WHERE game_date = "2021-12-04"

-- Result:
-- TDZA: 0      ← MISSING (should be 30)
-- PSZA: 351   ← OK
-- PCF:  131   ← Has data but opponent_strength_score = 0 for all
-- PDC:  97    ← Has data
-- ML:   131   ← Built on bad PCF data
```

---

## Prevention Strategies

### Strategy 1: Lightweight Existence Check (RECOMMENDED)

**Problem:** `backfill_mode=True` skips ALL dependency checks
**Solution:** Add a quick existence check that runs even in backfill mode

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CHECK COMPARISON: NORMAL vs BACKFILL                 │
└────────────────────────────────────────────────────────────────────────┘

                          NORMAL MODE              BACKFILL MODE
                          ───────────              ─────────────
Full completeness query   ✓ Yes (60s)             ✗ Skip
Freshness age check       ✓ Yes (5s)              ✗ Skip
Reprocess tracking        ✓ Yes (2s)              ✗ Skip
Quick existence check     (not needed)            ✓ ADD THIS (1s)
Output validation         ✗ No                    ✓ ADD THIS (0.1s)

PROPOSED CHANGE:
┌─────────────────────────────────────────────────────────────────────┐
│ if self.is_backfill_mode:                                           │
│     # FAST check: Just verify upstream has ANY data for this date   │
│     upstream_exists = self._quick_upstream_existence_check(date)    │
│     if not upstream_exists:                                         │
│         logger.error(f"⛔ BACKFILL SAFETY: No upstream for {date}") │
│         return {'status': 'error', 'reason': 'upstream_missing'}    │
│     logger.info("✓ Quick existence check passed")                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Implementation:**

```python
def _quick_upstream_existence_check(self, analysis_date: date) -> bool:
    """
    Fast check that upstream data exists for this date.
    Takes ~1s instead of 60s for full completeness check.
    """
    for table_info in self.upstream_tables:
        table_name = table_info['table']
        date_column = table_info.get('date_column', 'analysis_date')

        query = f"""
        SELECT COUNT(*) > 0 as has_data
        FROM `{table_name}`
        WHERE {date_column} = '{analysis_date}'
        LIMIT 1
        """

        result = self.bq_client.query(query).to_dataframe()
        if not result['has_data'].iloc[0]:
            logger.warning(f"No data in {table_name} for {analysis_date}")
            return False

    return True
```

### Strategy 2: Output Validation

**Problem:** Processors don't validate their output quality
**Solution:** Validate after writing

```python
def _validate_output(self, analysis_date: date, records_written: int) -> bool:
    """Validate output completeness after writing."""
    expected = self._count_expected_entities(analysis_date)

    if records_written == 0 and expected > 0:
        logger.error(f"⛔ OUTPUT VALIDATION: 0/{expected} records written")
        return False

    completeness = records_written / expected if expected > 0 else 0

    if completeness < 0.5:
        logger.warning(
            f"⚠️ LOW COMPLETENESS: {records_written}/{expected} "
            f"({completeness:.1%}) for {analysis_date}"
        )

    # Log for monitoring
    self._record_output_metrics(analysis_date, expected, records_written)

    return True
```

### Strategy 3: Cross-Processor Consistency Check

Run after all processors complete for a date:

```python
def validate_date_consistency(date: date) -> List[str]:
    """Verify all processors are consistent for a date."""
    counts = {
        'TDZA': query_count('team_defense_zone_analysis', date, 'analysis_date'),
        'PSZA': query_count('player_shot_zone_analysis', date, 'analysis_date'),
        'PCF': query_count('player_composite_factors', date, 'game_date'),
        'PDC': query_count('player_daily_cache', date, 'cache_date'),
        'ML': query_count('ml_feature_store_v2', date, 'game_date'),
    }

    issues = []

    # TDZA should have ~30 teams if games happened
    if counts['PSZA'] > 0 and counts['TDZA'] == 0:
        issues.append(f"TDZA=0 but PSZA has {counts['PSZA']} records")

    # ML should not exceed PCF
    if counts['ML'] > counts['PCF'] * 1.1:
        issues.append(f"ML ({counts['ML']}) > PCF ({counts['PCF']})")

    # PCF should not exceed PSZA significantly
    if counts['PCF'] > counts['PSZA'] * 1.1:
        issues.append(f"PCF ({counts['PCF']}) > PSZA ({counts['PSZA']})")

    return issues
```

### Strategy 4: Schedule vs Actual Game Validation

**Problem:** ML built from scheduled games that were postponed
**Solution:** Use actual game data, not schedule

```python
def get_valid_game_dates(start_date: date, end_date: date) -> List[date]:
    """Return only dates where games ACTUALLY happened."""
    query = f"""
    SELECT DISTINCT game_date
    FROM `nba_analytics.player_game_summary`  -- Actual games, not schedule
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    ORDER BY game_date
    """
    result = bq_client.query(query).to_dataframe()
    return result['game_date'].tolist()
```

---

## Observability Improvements

### 1. Date-Level Outcome Tracking Table

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.backfill_date_outcomes (
  backfill_run_id STRING NOT NULL,
  analysis_date DATE NOT NULL,
  processor_name STRING NOT NULL,
  expected_count INT64,
  actual_count INT64,
  completeness_pct FLOAT64,
  upstream_available BOOL,
  status STRING,  -- 'complete', 'partial', 'failed', 'skipped'
  error_message STRING,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, status;
```

### 2. Alert Conditions

```
┌────────────────────────────────────────────────────────────────────────┐
│                         ALERT CONDITION MATRIX                          │
└────────────────────────────────────────────────────────────────────────┘

Condition                           │ Severity │ Action
────────────────────────────────────┼──────────┼──────────────────────────
TDZA = 0 for a game date            │ 🔴 CRIT  │ Block downstream, alert
PCF opponent_score = 0 for all      │ 🔴 CRIT  │ TDZA missing, investigate
Completeness < 50%                  │ 🟡 WARN  │ Log, continue, review
ML records > PCF records            │ 🔴 CRIT  │ Data integrity issue
UNTRACKED dates after backfill      │ 🟡 WARN  │ Investigate gaps
Zero records written                │ 🔴 CRIT  │ Fail the date, retry
```

### 3. Monitoring Queries

Add to post-backfill validation:

```sql
-- Find dates with potential upstream issues
SELECT
  p.game_date,
  COALESCE(t.tdza_count, 0) as tdza,
  p.pcf_count,
  p.zero_opponent_count,
  ROUND(100.0 * p.zero_opponent_count / p.pcf_count, 1) as pct_zero
FROM (
  SELECT
    game_date,
    COUNT(*) as pcf_count,
    COUNTIF(opponent_strength_score = 0) as zero_opponent_count
  FROM `nba_precompute.player_composite_factors`
  GROUP BY game_date
) p
LEFT JOIN (
  SELECT analysis_date as game_date, COUNT(*) as tdza_count
  FROM `nba_precompute.team_defense_zone_analysis`
  GROUP BY analysis_date
) t ON p.game_date = t.game_date
WHERE p.zero_opponent_count = p.pcf_count  -- All zeros = missing TDZA
ORDER BY p.game_date;
```

---

## Code Changes Required

### Priority Matrix

```
┌────────────────────────────────────────────────────────────────────────┐
│                      CODE CHANGES PRIORITY MATRIX                       │
└────────────────────────────────────────────────────────────────────────┘

Priority │ File                      │ Change                    │ Effort
─────────┼───────────────────────────┼───────────────────────────┼────────
🔴 HIGH  │ precompute_base.py        │ Add quick existence check │ 2 hours
🔴 HIGH  │ run_phase4_backfill.sh    │ Add post-run validation   │ 1 hour
🟡 MED   │ precompute_base.py        │ Add output validation     │ 2 hours
🟡 MED   │ validate_backfill.py      │ Add consistency check     │ 3 hours
🟡 MED   │ New table creation        │ backfill_date_outcomes    │ 1 hour
🟢 LOW   │ Each processor            │ Log upstream counts       │ 1 hour
```

### Implementation Order

1. **Quick existence check** - Prevents cascading issues
2. **Post-run validation** - Catches issues immediately
3. **Output validation** - Logs completeness metrics
4. **Date outcomes table** - Long-term tracking
5. **Consistency checks** - Cross-processor validation

---

## Validation Queries

### Query 1: Find Dates with Missing Upstream Data

```sql
-- PCF dates where TDZA or PSZA is missing
WITH pcf_dates AS (
  SELECT DISTINCT game_date FROM `nba_precompute.player_composite_factors`
),
tdza_dates AS (
  SELECT DISTINCT analysis_date as game_date
  FROM `nba_precompute.team_defense_zone_analysis`
),
psza_dates AS (
  SELECT DISTINCT analysis_date as game_date
  FROM `nba_precompute.player_shot_zone_analysis`
)
SELECT
  p.game_date,
  CASE WHEN t.game_date IS NULL THEN "MISSING" ELSE "OK" END as tdza_status,
  CASE WHEN s.game_date IS NULL THEN "MISSING" ELSE "OK" END as psza_status
FROM pcf_dates p
LEFT JOIN tdza_dates t ON p.game_date = t.game_date
LEFT JOIN psza_dates s ON p.game_date = s.game_date
WHERE t.game_date IS NULL OR s.game_date IS NULL
ORDER BY p.game_date;
```

### Query 2: Find Dates with Zero Opponent Scores

```sql
-- Indicates missing TDZA data
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(opponent_strength_score = 0) as zero_opponent,
  ROUND(100.0 * COUNTIF(opponent_strength_score = 0) / COUNT(*), 1) as pct_zero
FROM `nba_precompute.player_composite_factors`
GROUP BY game_date
HAVING COUNTIF(opponent_strength_score = 0) = COUNT(*)
ORDER BY game_date;
```

### Query 3: Compare Expected vs Actual

```sql
-- Check ML completeness against expected game data
WITH expected AS (
  SELECT
    game_date,
    COUNT(DISTINCT universal_player_id) as expected_players
  FROM `nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
  GROUP BY game_date
),
actual AS (
  SELECT
    game_date,
    COUNT(DISTINCT universal_player_id) as ml_players
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.expected_players,
  COALESCE(a.ml_players, 0) as ml_players,
  e.expected_players - COALESCE(a.ml_players, 0) as missing,
  ROUND(100.0 * COALESCE(a.ml_players, 0) / e.expected_players, 1) as pct_complete
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE COALESCE(a.ml_players, 0) < e.expected_players * 0.5
ORDER BY e.game_date;
```

### Query 4: Cross-Processor Consistency

```sql
-- Full date comparison across all processors
WITH all_dates AS (
  SELECT DISTINCT game_date FROM `nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
)
SELECT
  d.game_date,
  (SELECT COUNT(*) FROM `nba_precompute.team_defense_zone_analysis`
   WHERE analysis_date = d.game_date) as tdza,
  (SELECT COUNT(*) FROM `nba_precompute.player_shot_zone_analysis`
   WHERE analysis_date = d.game_date) as psza,
  (SELECT COUNT(*) FROM `nba_precompute.player_composite_factors`
   WHERE game_date = d.game_date) as pcf,
  (SELECT COUNT(*) FROM `nba_precompute.player_daily_cache`
   WHERE cache_date = d.game_date) as pdc,
  (SELECT COUNT(*) FROM `nba_predictions.ml_feature_store_v2`
   WHERE game_date = d.game_date) as ml
FROM all_dates d
ORDER BY d.game_date;
```

---

## Runbook: Fixing Data Issues

### Scenario 1: Fix Missing TDZA (Dec 4, 2021 example)

```bash
# Step 1: Run TDZA for the missing date
.venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --skip-preflight

# Step 2: Verify TDZA has data now
bq query --use_legacy_sql=false \
    "SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date = '2021-12-04'"
# Should return 30

# Step 3: Re-run PCF (will now have opponent data)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --skip-preflight

# Step 4: Re-run ML (will now have correct PCF data)
.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --skip-preflight

# Step 5: Verify fix
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  opponent_strength_score
FROM nba_precompute.player_composite_factors
WHERE game_date = '2021-12-04'
LIMIT 5"
# opponent_strength_score should now vary (not all zeros)
```

### Scenario 2: Fill True Gaps (ML missing dates)

```bash
# Step 1: Identify missing dates
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-12-01 --end-date 2021-12-31 --details

# Step 2: Run ML backfill for missing dates
.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-12-23 --end-date 2021-12-23 --skip-preflight

.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-12-31 --end-date 2021-12-31 --skip-preflight

# Step 3: Verify
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date IN ('2021-12-23', '2021-12-31')
GROUP BY game_date"
```

### Scenario 3: Clean Up Stale Data (Postponed Games)

```bash
# Optional: Remove ML records for postponed games
# Only do this if you need clean data

bq query --use_legacy_sql=false "
DELETE FROM nba_predictions.ml_feature_store_v2
WHERE game_date IN (
  '2021-12-16', '2021-12-17', '2021-12-18',
  '2021-12-20', '2021-12-21', '2021-12-25',
  '2021-12-28', '2021-12-30'
)"
```

---

## Summary: Key Takeaways

### The Core Insight

**The current "skip ALL checks in backfill mode" is too aggressive.**

Better approach: **"Skip EXPENSIVE checks, keep CHEAP safety checks"**

| Check Type | Cost | Should Skip in Backfill? |
|------------|------|--------------------------|
| Full completeness query | 60s | ✅ Yes |
| Freshness age calculation | 5s | ✅ Yes |
| Reprocess attempt tracking | 2s | ✅ Yes |
| **Quick existence check** | 1s | ❌ No - Keep |
| **Output validation** | 0.1s | ❌ No - Keep |

This gives 90% of the speed benefit with 99% of the safety.

### Before Running 4-Year Backfill

1. ✅ Fix Dec 4, 2021 (TDZA → PCF → ML)
2. ✅ Implement lightweight existence check
3. ✅ Add post-run validation to orchestrator
4. ✅ Run validation after each major batch

### Monitoring Checklist

- [ ] No dates with TDZA = 0 when PCF has data
- [ ] No dates with 100% zero opponent scores
- [ ] No UNTRACKED dates after backfill
- [ ] ML records ≤ PCF records for all dates
- [ ] Completeness > 50% for non-bootstrap dates

---

*Last updated: 2025-12-07 | Session 73*
