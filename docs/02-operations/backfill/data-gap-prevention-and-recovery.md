# Data Gap Prevention and Recovery Guide

> **Date:** 2025-12-08
> **Status:** Living document
> **Audience:** Data Engineers, Operations

---

## Executive Summary

This guide addresses how to prevent data gaps from cascading through the NBA stats pipeline and how to recover when gaps occur. It's based on a real incident where missing shot zone data in Phase 3 (`team_defense_game_summary`) cascaded through Phase 4 (`team_defense_zone_analysis` → `player_composite_factors`) resulting in 10,000+ records with `opponent_strength_score = 0`.

---

## Table of Contents

1. [Pipeline Architecture Overview](#1-pipeline-architecture-overview)
2. [Types of Data Gaps](#2-types-of-data-gaps)
3. [Prevention Strategies](#3-prevention-strategies)
4. [Detection Methods](#4-detection-methods)
5. [Recovery Procedures](#5-recovery-procedures)
6. [Diagnostic Queries](#6-diagnostic-queries)
7. [Future Improvements](#7-future-improvements)

---

## 1. Pipeline Architecture Overview

### Data Flow

```
Phase 1: Raw Data (nba_raw)
    ↓
Phase 2: Reference Data (nba_reference)
    ↓
Phase 3: Analytics (nba_analytics)
    ├── player_game_summary
    ├── upcoming_player_game_context
    ├── team_defense_game_summary    ← Shot zone data extracted here
    └── team_offense_game_summary
    ↓
Phase 4: Precompute (nba_precompute)
    ├── player_daily_cache (PDC)
    ├── player_shot_zone_analysis (PSZA)
    ├── team_defense_zone_analysis (TDZA)  ← Uses team_defense_game_summary
    └── player_composite_factors (PCF)     ← Uses TDZA for opponent_strength
    ↓
Phase 5: Predictions (nba_predictions)
    ├── ml_feature_store_v2              ← Extracts from PCF
    └── player_prop_predictions
```

### Key Dependencies

| Processor | Depends On | Critical Fields |
|-----------|-----------|-----------------|
| TDZA | team_defense_game_summary | opp_paint_attempts, opp_mid_range_attempts |
| PCF | TDZA, PSZA, upcoming_player_game_context | paint_defense_vs_league_avg |
| MLFS | PCF, PDC, PSZA, TDZA | opponent_strength_score |

---

## 2. Types of Data Gaps

### 2.1 Missing Date Gaps
**Definition:** An entire date is missing from a table.

**Example:** Dec 7, 2021 missing from `upcoming_player_game_context`

**Detection:**
```sql
SELECT DISTINCT game_date FROM expected_dates
EXCEPT DISTINCT
SELECT DISTINCT game_date FROM actual_table
```

### 2.2 Partial Data Gaps
**Definition:** A date exists but has fewer records than expected.

**Example:** Only 50 of 200 expected players processed

**Detection:** Compare `COUNT(*)` against schedule-based expectations

### 2.3 NULL Field Gaps
**Definition:** Records exist but critical fields are NULL.

**Example:** `opp_paint_attempts = NULL` for all records

**Detection:**
```sql
SELECT COUNT(*) as total,
       SUM(CASE WHEN critical_field IS NULL THEN 1 ELSE 0 END) as null_count
FROM table
```

### 2.4 Zero-Value Gaps
**Definition:** Fields have default values (0) instead of actual calculated values.

**Example:** `opponent_strength_score = 0` when it should be calculated

**Detection:**
```sql
SELECT game_date, COUNT(*)
FROM table
WHERE calculated_field = 0  -- Should never be exactly 0
GROUP BY game_date
```

### 2.5 Cascade Gaps
**Definition:** Gaps that propagate from upstream to downstream tables.

**Example:** Missing shot zone → NULL paint defense → opponent_strength = 0

**Impact:** Most dangerous type; affects multiple downstream tables

---

## 3. Prevention Strategies

### 3.1 Pre-Run Dependency Validation

**What exists:** `check_dependencies()` method validates upstream tables before processing.

**Best practices:**
1. Always define dependencies with `get_dependencies()` method
2. Set `critical=True` for must-have dependencies
3. Use appropriate check types: `date_match`, `lookback`, `existence`

```python
def get_dependencies(self):
    return {
        'team_defense_game_summary': {
            'description': 'Team defensive metrics including shot zone data',
            'date_field': 'game_date',
            'check_type': 'date_match',
            'expected_min_rows': 30,  # At least 30 teams
            'critical': True,
        }
    }
```

### 3.2 Critical Field Validation

**Gap in current system:** No field-level validation for NULL/zero values.

**Recommended addition:**
```python
CRITICAL_FIELDS = {
    'team_defense_zone_analysis': ['paint_defense_vs_league_avg', 'mid_range_defense_vs_league_avg'],
    'player_composite_factors': ['opponent_strength_score', 'shot_zone_mismatch_score'],
}

def validate_critical_fields(df, table_name):
    """Validate critical fields are not NULL or zero."""
    for field in CRITICAL_FIELDS.get(table_name, []):
        null_pct = df[field].isna().sum() / len(df) * 100
        zero_pct = (df[field] == 0).sum() / len(df) * 100

        if null_pct > 50:
            raise DataQualityError(f"{field} is NULL for {null_pct:.1f}% of records")
        if zero_pct > 90:  # Allow some zeros but not all
            logger.warning(f"{field} is 0 for {zero_pct:.1f}% of records - verify upstream")
```

### 3.3 Source Hash Tracking

**What exists:** `source_*_hash` columns in some processors.

**What's needed:** Consistent implementation across all processors.

**Purpose:**
- Track which version of upstream data produced downstream records
- Detect when upstream changes require downstream reprocessing

**Implementation pattern:**
```python
def build_source_tracking_fields(self) -> dict:
    """Build source tracking fields for output records."""
    return {
        'source_tdza_hash': self._compute_hash(self.tdza_data),
        'source_tdza_last_updated': self.tdza_data['processed_at'].max(),
        'source_tdza_completeness_pct': self._calc_completeness(self.tdza_data),
    }
```

### 3.4 Backfill Mode Safeguards

**Current issue:** Backfill mode (`--skip-preflight`) bypasses too many checks.

**Recommended safeguards:**
1. **Never skip critical field validation** even in backfill mode
2. **Log warnings** for skipped checks (for audit trail)
3. **Require explicit flag** for each type of skipped check

```python
# Instead of single --skip-preflight, use specific flags:
--skip-upstream-freshness    # Skip age checks (safe for backfill)
--skip-completeness-check    # Skip % threshold (risky)
--force-despite-nulls        # Explicitly acknowledge null upstream data
```

---

## 4. Detection Methods

### 4.1 Automated Detection (Currently Available)

**validate_backfill_coverage.py** - Validates backfill completeness:
```bash
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --details
```

Output categories:
- `OK` - Records present
- `Skipped` - Expected incomplete (early season)
- `DepsMiss` - Upstream dependencies missing
- `Untracked` - No records AND no failure tracking (investigate!)
- `Investigate` - Has processing errors

### 4.2 Cascade Impact Detection Query

Find all downstream tables affected by an upstream gap:
```sql
-- Step 1: Find dates with NULL critical fields in TDZA
WITH bad_tdza_dates AS (
  SELECT DISTINCT analysis_date
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE paint_defense_vs_league_avg IS NULL
),
-- Step 2: Find PCF records processed with that bad data
bad_pcf AS (
  SELECT game_date, player_lookup, processed_at
  FROM `nba_precompute.player_composite_factors`
  WHERE game_date IN (SELECT analysis_date FROM bad_tdza_dates)
    AND opponent_strength_score = 0
)
SELECT
  game_date,
  COUNT(*) as affected_records,
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed
FROM bad_pcf
GROUP BY game_date
ORDER BY game_date;
```

### 4.3 Source Freshness Check

Verify if downstream data is stale relative to upstream:
```sql
WITH upstream_updates AS (
  SELECT MAX(processed_at) as last_upstream
  FROM `nba_analytics.team_defense_game_summary`
  WHERE game_date = '2021-12-01'
),
downstream_records AS (
  SELECT processed_at as downstream_time
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = '2021-12-01'
)
SELECT
  d.downstream_time,
  u.last_upstream,
  CASE
    WHEN d.downstream_time < u.last_upstream THEN 'STALE - needs reprocessing'
    ELSE 'FRESH'
  END as status
FROM downstream_records d
CROSS JOIN upstream_updates u;
```

---

## 5. Recovery Procedures

### 5.1 Recovery Flowchart

```
Gap Detected
    │
    ▼
┌─────────────────────────────┐
│ 1. DIAGNOSE: Identify root  │
│    cause table/field        │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ 2. SCOPE: Run cascade       │
│    impact detection query   │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ 3. FIX ROOT: Backfill the   │
│    upstream table first     │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ 4. PROPAGATE: Backfill      │
│    downstream in order      │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ 5. VERIFY: Run validation   │
│    queries to confirm fix   │
└─────────────────────────────┘
```

### 5.2 Backfill Order (Critical!)

Always backfill in dependency order:

```bash
# Phase 3 (if needed)
.venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# Phase 4 - Order matters!
# 1. TDZA and PSZA can run in parallel
.venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

# 2. PDC (depends on PSZA)
.venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --skip-preflight

# 3. PCF (depends on TDZA, PSZA)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31 --skip-preflight

# Phase 5 (if needed)
.venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-11-05 --end-date 2021-12-31 --skip-preflight
```

### 5.3 Verification After Recovery

```sql
-- Verify shot zone data populated
SELECT
  game_date,
  COUNT(*) as records,
  SUM(CASE WHEN opp_paint_attempts IS NOT NULL THEN 1 ELSE 0 END) as with_paint,
  AVG(opp_paint_attempts) as avg_paint
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date
ORDER BY game_date;

-- Verify TDZA paint defense populated
SELECT
  analysis_date,
  AVG(paint_defense_vs_league_avg) as avg_paint_defense,
  SUM(CASE WHEN paint_defense_vs_league_avg IS NULL THEN 1 ELSE 0 END) as null_count
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY analysis_date
ORDER BY analysis_date;

-- Verify opponent_strength_score now > 0
SELECT
  game_date,
  AVG(opponent_strength_score) as avg_opp_score,
  SUM(CASE WHEN opponent_strength_score = 0 THEN 1 ELSE 0 END) as zero_count,
  COUNT(*) as total
FROM `nba_precompute.player_composite_factors`
WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY game_date
ORDER BY game_date;
```

---

## 6. Diagnostic Queries

### 6.1 Full Pipeline Health Check

```sql
-- Cross-table completeness check for a date range
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY('2021-11-01', '2021-12-31')) as date
),
tdgs AS (
  SELECT game_date, COUNT(*) as cnt,
         SUM(CASE WHEN opp_paint_attempts IS NULL THEN 1 ELSE 0 END) as null_paint
  FROM `nba_analytics.team_defense_game_summary`
  GROUP BY game_date
),
tdza AS (
  SELECT analysis_date, COUNT(*) as cnt,
         SUM(CASE WHEN paint_defense_vs_league_avg IS NULL THEN 1 ELSE 0 END) as null_paint
  FROM `nba_precompute.team_defense_zone_analysis`
  GROUP BY analysis_date
),
pcf AS (
  SELECT game_date, COUNT(*) as cnt,
         SUM(CASE WHEN opponent_strength_score = 0 THEN 1 ELSE 0 END) as zero_opp
  FROM `nba_precompute.player_composite_factors`
  GROUP BY game_date
)
SELECT
  d.date,
  COALESCE(tdgs.cnt, 0) as tdgs_records,
  COALESCE(tdgs.null_paint, 0) as tdgs_null_paint,
  COALESCE(tdza.cnt, 0) as tdza_records,
  COALESCE(tdza.null_paint, 0) as tdza_null_paint,
  COALESCE(pcf.cnt, 0) as pcf_records,
  COALESCE(pcf.zero_opp, 0) as pcf_zero_opp,
  CASE
    WHEN tdgs.cnt IS NULL THEN 'MISSING_TDGS'
    WHEN tdgs.null_paint = tdgs.cnt THEN 'NULL_PAINT_DATA'
    WHEN tdza.null_paint = tdza.cnt THEN 'NULL_TDZA_PAINT'
    WHEN pcf.zero_opp = pcf.cnt THEN 'ZERO_OPP_STRENGTH'
    ELSE 'OK'
  END as status
FROM date_range d
LEFT JOIN tdgs ON d.date = tdgs.game_date
LEFT JOIN tdza ON d.date = tdza.analysis_date
LEFT JOIN pcf ON d.date = pcf.game_date
WHERE d.date IN (SELECT DISTINCT game_date FROM `nba_analytics.player_game_summary`)
ORDER BY d.date;
```

### 6.2 Find Processing Timestamps

```sql
-- When was each table last processed for a specific date?
SELECT
  'team_defense_game_summary' as table_name,
  MAX(processed_at) as last_processed
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date = '2021-12-01'

UNION ALL

SELECT
  'team_defense_zone_analysis',
  MAX(processed_at)
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = '2021-12-01'

UNION ALL

SELECT
  'player_composite_factors',
  MAX(processed_at)
FROM `nba_precompute.player_composite_factors`
WHERE game_date = '2021-12-01';
```

---

## 7. Future Improvements

### 7.1 High Priority (Implement Soon)

1. **Critical Field Validation Mixin**
   - Add field-level NULL/zero validation to base processors
   - Configurable per-processor critical fields
   - Fail loudly when critical fields are invalid

2. **Cascade Impact Analyzer**
   - Script that takes a table+date and shows all downstream impact
   - Outputs list of tables/dates that need reprocessing

3. **Automated Recovery Suggestions**
   - When a gap is detected, suggest the backfill commands needed
   - Include proper ordering and flags

### 7.2 Medium Priority

4. **Data Lineage Dashboard**
   - Visual DAG showing pipeline dependencies
   - Click on a gap to see cascade impact

5. **Source Hash Consistency**
   - Implement source hash tracking in all Phase 4 processors
   - Automated stale data detection

6. **Smart Backfill Mode**
   - Instead of `--skip-preflight`, use `--backfill-mode`
   - Skip freshness checks but keep critical validation

### 7.3 Lower Priority

7. **Anomaly Detection**
   - Detect sudden changes in metric distributions
   - Alert when values deviate significantly from historical norms

8. **Self-Healing Workflows**
   - Automated retry for recoverable failures
   - Cascading reprocessing when upstream fixes detected

---

## Appendix A: Real Incident - Shot Zone Cascade Failure

### Timeline
1. **Root cause:** `_extract_shot_zone_stats()` method was missing from `TeamDefenseGameSummaryProcessor`
2. **Result:** `opp_paint_attempts` was NULL for all records
3. **Cascade:** TDZA calculated `paint_defense_vs_league_avg` as NULL
4. **Final impact:** PCF calculated `opponent_strength_score = 0` for 10,068 records

### Detection Method
```sql
-- This query revealed the problem
SELECT
  AVG(opponent_strength_score) as avg,
  SUM(CASE WHEN opponent_strength_score = 0 THEN 1 ELSE 0 END) as zero_count
FROM `nba_precompute.player_composite_factors`
-- Result: avg=0, zero_count=10068
```

### Resolution
1. Fixed `_extract_shot_zone_stats()` in Session 75
2. Committed fix (43f41a7)
3. Need to run full backfill sequence (Phase 3 → Phase 4 → Phase 5)

---

## Appendix B: Quick Reference Commands

```bash
# Validate backfill coverage
.venv/bin/python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-12-31 --details

# Check shot zone data
bq query --use_legacy_sql=false 'SELECT game_date, AVG(opp_paint_attempts) FROM nba_analytics.team_defense_game_summary GROUP BY 1 ORDER BY 1'

# Check TDZA paint defense
bq query --use_legacy_sql=false 'SELECT analysis_date, AVG(paint_defense_vs_league_avg) FROM nba_precompute.team_defense_zone_analysis GROUP BY 1 ORDER BY 1'

# Check PCF opponent_strength
bq query --use_legacy_sql=false 'SELECT game_date, AVG(opponent_strength_score), COUNT(*) FROM nba_precompute.player_composite_factors GROUP BY 1 ORDER BY 1'
```

---

*Last updated: 2025-12-08*
