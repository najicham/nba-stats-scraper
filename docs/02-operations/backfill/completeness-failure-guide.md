# Completeness Failure Guide

**Last Updated:** 2025-12-08 | **Status:** Current

---

## Overview

This guide explains what happens when a completeness check fails, where to find visibility into failures, how to diagnose root causes, and how to recover.

---

## Table of Contents

1. [What Happens When Completeness Fails](#what-happens-when-completeness-fails)
2. [Visibility: Where to Find Failures](#visibility-where-to-find-failures)
3. [Root Cause Diagnosis Decision Tree](#root-cause-diagnosis-decision-tree)
4. [Recovery Procedures](#recovery-procedures)
5. [Quick Reference Queries](#quick-reference-queries)

---

## What Happens When Completeness Fails

### Completeness Check Flow

When a processor runs, it checks upstream data completeness before processing each entity:

```
Processor starts for date D
    │
    ▼
┌─────────────────────────────┐
│ Check: Is backfill_mode?    │
└─────────────────────────────┘
    │                    │
    │ YES                │ NO
    ▼                    ▼
┌──────────────┐   ┌───────────────────────────┐
│ SKIP checks  │   │ Run completeness check    │
│ Assume 100%  │   │ Expected vs Actual games  │
│ ⚠️ BLINDSPOT │   └───────────────────────────┘
└──────────────┘              │
                              ▼
                   ┌─────────────────────────┐
                   │ Completeness >= 90%?    │
                   └─────────────────────────┘
                        │           │
                        │ YES       │ NO
                        ▼           ▼
                   ┌─────────┐  ┌─────────────────────────┐
                   │ PROCESS │  │ Check bootstrap mode?   │
                   │ Record  │  │ (First 30 days season)  │
                   └─────────┘  └─────────────────────────┘
                                     │           │
                                     │ YES       │ NO
                                     ▼           ▼
                                ┌─────────┐  ┌──────────┐
                                │ PROCESS │  │ SKIP     │
                                │ with    │  │ Entity   │
                                │ READY=F │  │ Log fail │
                                └─────────┘  └──────────┘
```

### Outcomes by Scenario

| Mode | Completeness | Result | Visibility |
|------|--------------|--------|------------|
| **Production, >= 90%** | Complete | Record saved with `is_production_ready=TRUE` | Normal |
| **Production, < 90%** | Incomplete | **SKIPPED** - Entity not processed | `precompute_failures` table |
| **Bootstrap, < 90%** | Incomplete | Record saved with `is_production_ready=FALSE` | Output table, queryable |
| **Backfill mode** | Not checked | Record saved assuming 100% | **NO VISIBILITY** (blindspot) |

### Key Fields Set on Output Records

When a record IS processed (even with incomplete data), these fields capture quality:

```python
{
    # Completeness metrics
    'completeness_percentage': 88.2,      # Actual percentage
    'expected_games_count': 17,           # From schedule
    'actual_games_count': 15,             # From upstream table
    'missing_games_count': 2,             # Gap count

    # Production readiness
    'is_production_ready': False,         # THE KEY FIELD

    # Context
    'backfill_bootstrap_mode': True,      # If in bootstrap mode
    'processing_decision_reason': 'bootstrap_mode_allowed',

    # Upstream dependency tracking
    'upstream_player_shot_ready': False,
    'upstream_team_defense_ready': True,
    'all_upstreams_ready': False,
    'data_quality_issues': ['upstream_player_shot_zone_incomplete']
}
```

---

## Visibility: Where to Find Failures

### 1. Skipped Entities (Production Mode Failures)

Entities that failed completeness and were **skipped** go to `precompute_failures`:

```sql
-- Find skipped entities for a date range
SELECT
    processor_name,
    analysis_date,
    entity_id,
    failure_category,
    failure_reason,
    can_retry,
    created_at
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-12-31'
  AND failure_category IN ('INCOMPLETE_DATA', 'MISSING_UPSTREAM', 'INSUFFICIENT_DATA')
ORDER BY analysis_date, processor_name;
```

### 2. Records Processed with Low Quality

Records that were processed but marked not production-ready:

```sql
-- Player Daily Cache: Records with completeness issues
SELECT
    cache_date,
    player_lookup,
    l5_completeness_pct,
    l10_completeness_pct,
    is_production_ready,
    backfill_bootstrap_mode,
    processing_decision_reason
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2021-11-01' AND '2021-12-31'
  AND is_production_ready = FALSE
ORDER BY cache_date;

-- Player Composite Factors: Records with completeness issues
SELECT
    analysis_date,
    player_lookup,
    completeness_percentage,
    is_production_ready,
    data_quality_issues
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-12-31'
  AND is_production_ready = FALSE
ORDER BY analysis_date;
```

### 3. Circuit Breaker Status

Entities blocked by circuit breaker (too many failed retries):

```sql
SELECT
    processor_name,
    entity_id,
    analysis_date,
    attempt_number,
    completeness_pct,
    skip_reason,
    circuit_breaker_until,
    TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY analysis_date DESC;
```

### 4. Gap Detection Script

Run the gap detection script for comprehensive analysis:

```bash
# Detect all gaps with cascade impact
python scripts/detect_gaps.py \
    --start-date 2021-11-01 \
    --end-date 2021-12-31 \
    --check-contamination

# JSON output for automation
python scripts/detect_gaps.py \
    --start-date 2021-11-01 \
    --end-date 2021-12-31 \
    --json > gaps.json
```

---

## Root Cause Diagnosis Decision Tree

### When Many Entities Fail on Same Date

```
90%+ of entities fail on date D
    │
    ▼
┌─────────────────────────────────────────┐
│ Check Phase 3 Analytics for date D      │
│                                         │
│ bq query "SELECT COUNT(*) FROM          │
│   nba_analytics.player_game_summary     │
│   WHERE game_date = 'D'"                │
└─────────────────────────────────────────┘
    │
    │ Count = 0 or very low?
    │
    ├─── YES ──► Phase 3 didn't run or failed
    │            → Check processor_run_history for Phase 3
    │            → Rerun Phase 3 backfill for date D
    │
    └─── NO ───► Phase 3 has data, check Phase 2
                 │
                 ▼
    ┌─────────────────────────────────────────┐
    │ Check Phase 2 Raw data for date D       │
    │                                         │
    │ bq query "SELECT COUNT(*) FROM          │
    │   nba_raw.bigdataball_play_by_play      │
    │   WHERE game_date = 'D'"                │
    └─────────────────────────────────────────┘
         │
         │ Count = 0?
         │
         ├─── YES ──► Raw data never ingested
         │            → Check GCS files exist
         │            → Rerun Phase 1 scraper + Phase 2
         │
         └─── NO ───► Raw data exists but Phase 3 failed
                      → Check for schema issues
                      → Check for name resolution failures
```

### When Specific Entities Fail

```
Specific player/team fails repeatedly
    │
    ▼
┌─────────────────────────────────────────┐
│ Check if player exists in name registry │
│                                         │
│ bq query "SELECT * FROM                 │
│   nba_reference.player_name_registry    │
│   WHERE player_lookup = 'X'"            │
└─────────────────────────────────────────┘
    │
    │ Not found?
    │
    ├─── YES ──► Name resolution issue
    │            → Check registry_errors table
    │            → Run name resolution backfill
    │
    └─── NO ───► Player exists, check data
                 │
                 ▼
    ┌─────────────────────────────────────────┐
    │ Check player's games in Phase 3         │
    │                                         │
    │ bq query "SELECT game_date FROM         │
    │   nba_analytics.player_game_summary     │
    │   WHERE player_lookup = 'X'             │
    │   AND game_date >= 'SEASON_START'"      │
    └─────────────────────────────────────────┘
         │
         │ Fewer games than expected?
         │
         ├─── YES ──► Missing game data for player
         │            → Check if player was injured/DNP
         │            → Check boxscore raw data
         │
         └─── NO ───► Player has all games
                      → Issue is in precompute logic
                      → Check specific processor logs
```

### Failure Category Quick Reference

| Category | Meaning | Root Cause | Action |
|----------|---------|------------|--------|
| `INSUFFICIENT_DATA` | Player has <10 games | Early season, new player | Wait for more games (expected) |
| `INCOMPLETE_DATA` | Completeness <90% | Phase 3 missing games | Check Phase 3 backfill |
| `MISSING_UPSTREAM` | No upstream data | Phase 3 didn't run | Run Phase 3 backfill |
| `NO_SHOT_ZONE` | Shot zone missing | PSZA didn't process player | Run PSZA backfill |
| `CIRCUIT_BREAKER_ACTIVE` | Too many retries | Persistent issue | Manual investigation needed |
| `PROCESSING_ERROR` | Unhandled exception | Bug in code | Debug and fix code |

---

## Recovery Procedures

### Step 1: Identify Scope

```bash
# Run gap detection
python scripts/detect_gaps.py \
    --start-date 2021-11-01 \
    --end-date 2021-12-31

# Run validation coverage
python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 \
    --end-date 2021-12-31 \
    --details
```

### Step 2: Fix Upstream First

**If Phase 3 is missing:**
```bash
# Rerun Phase 3 for affected dates
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15
```

**If Phase 2 is missing:**
```bash
# Check GCS files exist, then rerun Phase 2
PYTHONPATH=. .venv/bin/python backfill_jobs/phase2/run_phase2_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15
```

### Step 3: Reprocess Downstream

After fixing upstream, reprocess affected Phase 4 processors:

```bash
# Order matters: TDZA+PSZA → PCF → PDC → MLFS

# 1. Team Defense Zone Analysis
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15

# 2. Player Shot Zone Analysis
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15

# 3. Player Composite Factors
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15

# 4. Player Daily Cache
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-15
```

### Step 4: Validate Recovery

```bash
# Verify no more gaps
python scripts/detect_gaps.py \
    --start-date 2021-12-01 --end-date 2021-12-15

# Verify data quality
python scripts/validate_cascade_contamination.py \
    --start-date 2021-12-01 --end-date 2021-12-15 --strict

# Check completeness
python scripts/validate_backfill_coverage.py \
    --start-date 2021-12-01 --end-date 2021-12-15 --reconcile
```

### Step 5: Override Circuit Breakers (If Needed)

If entities are blocked by circuit breaker after upstream fix:

```bash
# Check what's blocked
bq query --use_legacy_sql=false "
SELECT processor_name, entity_id, analysis_date, circuit_breaker_until
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
LIMIT 20"

# Override specific entity (careful!)
# Use the override script or manual update
```

---

## Quick Reference Queries

### Daily Health Check

```sql
-- Records processed yesterday with quality issues
SELECT
    'player_daily_cache' as processor,
    COUNT(*) as total,
    COUNTIF(is_production_ready = FALSE) as not_ready,
    ROUND(100.0 * COUNTIF(is_production_ready = FALSE) / COUNT(*), 1) as pct_not_ready
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)

UNION ALL

SELECT
    'player_composite_factors',
    COUNT(*),
    COUNTIF(is_production_ready = FALSE),
    ROUND(100.0 * COUNTIF(is_production_ready = FALSE) / COUNT(*), 1)
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE analysis_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
```

### Find Dates with High Failure Rates

```sql
SELECT
    analysis_date,
    processor_name,
    COUNT(*) as failures,
    ARRAY_AGG(DISTINCT failure_category) as categories
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY analysis_date, processor_name
HAVING COUNT(*) > 10
ORDER BY analysis_date DESC, failures DESC;
```

### Compare Expected vs Actual Records

```sql
-- Expected players from schedule
WITH expected AS (
    SELECT
        game_date,
        COUNT(DISTINCT player_lookup) as expected_players
    FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE game_date BETWEEN '2021-11-01' AND '2021-12-31'
    GROUP BY game_date
),
-- Actual records in PDC
actual AS (
    SELECT
        cache_date as game_date,
        COUNT(DISTINCT player_lookup) as actual_players
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE cache_date BETWEEN '2021-11-01' AND '2021-12-31'
    GROUP BY cache_date
)
SELECT
    e.game_date,
    e.expected_players,
    COALESCE(a.actual_players, 0) as actual_players,
    e.expected_players - COALESCE(a.actual_players, 0) as gap
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE e.expected_players - COALESCE(a.actual_players, 0) > 0
ORDER BY e.game_date;
```

---

## Related Documentation

- [Backfill Guide](./backfill-guide.md) - Comprehensive backfill procedures
- [Data Integrity Guide](./data-integrity-guide.md) - Cascade contamination prevention
- [Gap Detection](./gap-detection.md) - Gap detection tool usage
- [Completeness Runbook](./runbooks/completeness/operational-runbook.md) - Circuit breaker management
