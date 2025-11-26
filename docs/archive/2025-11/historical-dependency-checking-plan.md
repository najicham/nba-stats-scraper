# Historical Dependency Checking - Implementation Plan (v2.1)

`/docs/architecture/historical-dependency-checking-plan.md`

**Version:** 2.1
**Date:** November 22, 2025
**Status:** Production-Ready Architecture
**Author:** NBA Props Platform Team

**Changes from v2.0:**
- Added circuit breaker for reprocessing (prevents oscillation)
- Added season boundary detection (prevents false alerts)
- Clarified multi-window production-ready logic
- Added concrete alert thresholds with day-based expectations
- Added integration testing checklist for each implementation week
- Documented deferred enhancements with monitoring triggers

---

## Executive Summary

This document outlines our approach to handling historical data dependencies during Phase 4 processor backfill. The core challenge: processors require historical windows (last 10-15 games) that don't exist during early backfill dates.

**Our Solution:** Progressive data quality tracking with completeness percentages, simple boolean flags, comprehensive decision visibility, reprocessing safeguards, and monitoring. No complex tier systems, no fully-automated reprocessing across 4 years of data.

**Key Principles:**
- Write data with partial historical windows, track completeness explicitly
- Use completeness percentage (0-100%) instead of complex quality tiers
- Automatic reprocessing only for recent data (last 60 days) with circuit breaker protection
- Manual reprocessing for historical backfill with clear detection queries
- Full visibility of all processing decisions (successes and skips)
- Comprehensive monitoring with concrete alert thresholds
- Season boundary awareness to prevent false alerts

**Expected Outcomes:**
- Continuous data coverage from Day 0 of backfill (no gaps)
- Transparent data quality metadata on every record
- Clear identification of records needing reprocessing
- Full audit trail of processing decisions
- Protected against reprocessing oscillation
- Monitoring dashboard showing completeness trends
- Cost increase: ~$3-5/month

---

## Table of Contents

1. [Core Architecture](#core-architecture)
2. [What We're NOT Doing](#what-were-not-doing)
3. [Implementation Plan](#implementation-plan)
4. [Schema Design](#schema-design)
5. [Completeness Checking](#completeness-checking)
6. [Downstream Consumption Guidelines](#downstream-consumption-guidelines)
7. [Decision Visibility Schema](#decision-visibility-schema)
8. [Reprocessing Strategy](#reprocessing-strategy)
9. [Monitoring & Alerting](#monitoring--alerting)
10. [Edge Case Handling](#edge-case-handling)
11. [Rollback Procedure](#rollback-procedure)
12. [Cost Analysis](#cost-analysis)
13. [Future Enhancements](#future-enhancements)
14. [Success Criteria](#success-criteria)

---

## Core Architecture

### Design Philosophy

**Embrace Partial Data with Full Transparency**

Rather than skip processing when historical data is incomplete, we:
1. Process with available data
2. Track exactly what's missing
3. Mark records that need reprocessing
4. Record all processing decisions (successes and skips)
5. Let downstream consumers decide acceptability
6. Protect against reprocessing oscillation with circuit breakers

### Three Components with Safeguards

```
┌─────────────────────────────────────────────────────────────┐
│ 1. COMPLETENESS CHECKER                                      │
│    - Queries schedule vs upstream data                       │
│    - Calculates completeness percentage                      │
│    - Identifies missing game dates                           │
│    - Season boundary aware                                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. PROCESSOR LOGIC                                           │
│    - Processes with available data (no skipping)             │
│    - Writes completeness metadata to every record            │
│    - Sets reprocessing flags appropriately                   │
│    - Circuit breaker prevents oscillation                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. DECISION TRACKING & MONITORING                            │
│    - Records all processing decisions (success/skip)         │
│    - Daily monitoring with concrete alert thresholds         │
│    - Automatic detection of reprocessable records            │
│    - Manual trigger for historical reprocessing              │
└─────────────────────────────────────────────────────────────┘
```

### Completeness Tracking Approach

Instead of complex quality tiers (BOOTSTRAP → EARLY → DEVELOPING → MATURE), we use:

**Simple completeness percentage:**
```python
completeness_pct = (games_available / games_required) * 100

Examples:
- Day 5:  5 games available, need 15 → 33.3% complete
- Day 10: 10 games available, need 15 → 66.7% complete
- Day 20: 15 games available, need 15 → 100% complete
```

**Production-ready flag:**
```python
is_production_ready = (completeness_pct >= 90.0)

Downstream consumers can filter:
- ML training: WHERE is_production_ready = TRUE
- API responses: Include completeness_pct in metadata
- Analytics: Group by completeness ranges
```

**Why this is simpler:**
- One number (0-100%) instead of 5 named tiers
- Clear threshold (90%) for production use
- No cascade complexity (downstream doesn't need to track tier changes)
- Easy to query and filter

---

## What We're NOT Doing

### ❌ Complex Quality Tier System

**Considered:** 5-tier system (INSUFFICIENT → LOW → MEDIUM → HIGH → OPTIMAL) with context-aware adjustments

**Why not:**
- Adds complexity: Each downstream processor would need to store incoming tier, check for tier upgrades
- Cascade issues: If upstream changes from MEDIUM → HIGH, do all downstream records need reprocessing?
- Ambiguity: Is "MEDIUM" quality acceptable for predictions? For training data?
- Maintenance: Defining and documenting tier meanings across 5+ processors

**Instead:** Simple percentage (33.3%, 66.7%, 100%) with one boolean flag (`is_production_ready`)

### ❌ Fully Automatic Reprocessing Across 4 Years

**Considered:** System automatically detects and reprocesses any record when more data becomes available

**Why not:**
- Complexity: During backfill, millions of records could trigger reprocessing simultaneously
- Dependencies: Phase 4 → Phase 5 cascade means reprocessing Phase 4 record requires reprocessing Phase 5 predictions
- Cost: Reprocessing 4 years × 450 players × 82 games = massive BigQuery write costs
- Control: No way to throttle or schedule reprocessing strategically

**Instead:**
- **Automatic** for recent data (last 60 days) with circuit breaker protection - small, manageable scope
- **Manual** for historical backfill - you control when/what to reprocess

### ❌ Precomputed Completeness Table

**Considered:** Hourly job that maintains `nba_orchestration.data_completeness` table

**Why not:**
- Extra infrastructure to maintain
- Update lag (hourly vs real-time)
- Not necessary for current scale (batch queries are efficient enough)

**Instead:** On-demand batch completeness checking during processor runs (2 queries total, not 450)

### ❌ Strict 100% Completeness Requirement

**Considered:** Skip processing entirely if any required data is missing

**Why not:**
- Coverage gaps: First 25 days of backfill would have NO Phase 4 data
- Brittleness: One missing game (due to postponement, scraper failure) blocks entire chain
- Reality mismatch: 95% complete data is still very useful

**Instead:** Process with available data, mark completeness, let consumers filter if needed

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

**Goal:** Build completeness checking foundation

**Tasks:**
1. Create `CompletenessChecker` service class
2. Add schema columns to `team_defense_zone_analysis` (pilot processor)
3. Implement batch completeness queries (schedule vs upstream)
4. Add completeness tracking to processor logic
5. Implement circuit breaker for reprocessing
6. Write unit tests for completeness calculations

**Deliverables:**
- `/processors/shared/completeness_checker.py` (new file)
- `/processors/shared/reprocessing_circuit_breaker.py` (new file)
- Updated `team_defense_zone_analysis_processor.py`
- Schema migration script
- Unit test suite (20+ tests)

**Integration Testing Checklist (Week 1):**
```sql
-- Test 1: Verify CompletenessChecker accuracy
-- Run on known date with known game count
SELECT
    team_abbr,
    completeness_pct,
    games_available,
    games_required
FROM test_completeness_results
WHERE analysis_date = '2024-11-22';
-- Manually verify counts match reality

-- Test 2: Verify schema migration successful
SELECT COUNT(*) as tables_with_completeness_fields
FROM INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'team_defense_zone_analysis'
  AND column_name IN ('completeness_pct', 'is_production_ready');
-- Expected: 2 columns present

-- Test 3: Verify no NULL completeness after processing
SELECT COUNT(*) as null_completeness_count
FROM `nba_precompute.team_defense_zone_analysis`
WHERE completeness_pct IS NULL
  AND analysis_date >= '2024-11-22';
-- Expected: 0
```

**Validation:**
- Run processor for single date (Nov 22, 2024)
- Verify completeness metadata written correctly
- Query BigQuery to confirm schema changes
- Verify circuit breaker prevents excessive reprocessing

**Success Criteria:**
- All 30 teams have completeness_pct calculated
- Missing game dates identified correctly
- Circuit breaker limits reprocessing attempts
- Processor completes in <2 minutes (same as before)
- All integration tests pass

---

### Phase 2: Single Processor Integration (Week 2)

**Goal:** Validate approach with simplest processor

**Tasks:**
1. Test `team_defense_zone_analysis` with 1-month historical data (Oct 2024)
2. Validate early season handling (Day 0-14)
3. Validate mid-season handling (Day 15-30)
4. Add completeness filtering to existing Phase 5 dependencies
5. Document completeness usage for downstream
6. Implement season boundary detection in monitoring

**Test Scenarios:**
```
Oct 22 (Day 0):  1 game available → 6.7% complete → is_production_ready=FALSE
Oct 27 (Day 5):  5 games available → 33.3% complete → is_production_ready=FALSE
Nov 1 (Day 10):  10 games available → 66.7% complete → is_production_ready=FALSE
Nov 11 (Day 20): 15 games available → 100% complete → is_production_ready=TRUE
```

**Integration Testing Checklist (Week 2):**
```sql
-- Test 1: Verify completeness progression
SELECT
    analysis_date,
    AVG(completeness_pct) as avg_completeness
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN '2024-10-22' AND '2024-11-22'
GROUP BY analysis_date
ORDER BY analysis_date;
-- Expected: Steady increase from ~7% to ~100%

-- Test 2: Verify production-ready logic correct
SELECT completeness_pct, is_production_ready
FROM `nba_precompute.team_defense_zone_analysis`
WHERE (completeness_pct >= 90 AND is_production_ready = FALSE)
   OR (completeness_pct < 90 AND is_production_ready = TRUE);
-- Expected: 0 rows (no logic errors)

-- Test 3: Verify reprocessing flags set correctly
SELECT
    COUNT(CASE WHEN completeness_pct < 90 AND needs_reprocessing = FALSE THEN 1 END) as flag_errors
FROM `nba_precompute.team_defense_zone_analysis`;
-- Expected: 0 (all incomplete records flagged)

-- Test 4: Verify circuit breaker working
SELECT
    entity_id,
    analysis_date,
    reprocessed_count,
    last_reprocessed_at
FROM `nba_precompute.team_defense_zone_analysis`
WHERE reprocessed_count > 3;
-- Expected: 0 rows (circuit breaker prevents >3 attempts)
```

**Success Criteria:**
- Day 0-14: Records have completeness_pct < 90%, needs_reprocessing=TRUE
- Day 15+: Records have completeness_pct ≥ 90%, needs_reprocessing=FALSE
- No processing failures (all dates process successfully)
- Completeness metadata matches manual validation
- Circuit breaker prevents runaway reprocessing
- All integration tests pass

---

### Phase 3: Multi-Window Processor (Week 3)

**Goal:** Handle processor with multiple lookback windows

**Tasks:**
1. Integrate completeness checking into `player_daily_cache`
2. Implement per-window completeness tracking
3. Handle NULL values for incomplete windows
4. Clarify multi-window production-ready logic
5. Test with player data (450 players vs 30 teams)

**Multi-Window Handling:**

`player_daily_cache` requires multiple windows:
- L5 games (5 games)
- L10 games (10 games)
- L7 days (7 days of games)
- L14 days (14 days of games)

**Multi-Window Production-Ready Logic:**

**Decision:** ALL windows must be complete for `is_production_ready = TRUE`

```python
def calculate_multi_window_production_ready(windows: dict) -> bool:
    """
    ALL windows must be 90%+ complete for production-ready.

    This ensures downstream consumers get complete feature sets.
    Partial windows would create inconsistent ML training data.
    """
    return all([
        windows.get('l5_complete', False),
        windows.get('l10_complete', False),
        windows.get('l7d_complete', False),
        windows.get('l14d_complete', False)
    ])

# Example:
# L5: 100% complete ✓
# L10: 100% complete ✓
# L7d: 100% complete ✓
# L14d: 80% complete ✗
# Result: is_production_ready = FALSE (one window incomplete)
```

**Why ALL windows required:**
- Consistency: ML models trained on complete feature sets
- Simplicity: Clear boolean logic (no weighted averages)
- Safety: Conservative approach prevents partial data issues

**Strategy: Best-Effort with Explicit Tracking**

```python
def calculate_multiple_windows(self, player_games: List) -> dict:
    """Calculate available windows, set unavailable to NULL."""

    results = {}

    # L5 window
    if len(player_games) >= 5:
        results['l5_ppg'] = calculate_avg(player_games[:5], 'points')
        results['l5_complete'] = True
    else:
        results['l5_ppg'] = None
        results['l5_complete'] = False

    # L10 window
    if len(player_games) >= 10:
        results['l10_ppg'] = calculate_avg(player_games[:10], 'points')
        results['l10_complete'] = True
    else:
        results['l10_ppg'] = None
        results['l10_complete'] = False

    # L7d window
    games_in_7d = [g for g in player_games if days_ago(g['game_date']) <= 7]
    if len(games_in_7d) >= 3:  # Need minimum 3 games in 7 days
        results['l7d_fatigue'] = calculate_fatigue(games_in_7d)
        results['l7d_complete'] = True
    else:
        results['l7d_fatigue'] = None
        results['l7d_complete'] = False

    # L14d window
    games_in_14d = [g for g in player_games if days_ago(g['game_date']) <= 14]
    if len(games_in_14d) >= 5:  # Need minimum 5 games in 14 days
        results['l14d_fatigue'] = calculate_fatigue(games_in_14d)
        results['l14d_complete'] = True
    else:
        results['l14d_fatigue'] = None
        results['l14d_complete'] = False

    # Overall production readiness: ALL windows must be complete
    results['all_windows_complete'] = all([
        results['l5_complete'],
        results['l10_complete'],
        results['l7d_complete'],
        results['l14d_complete']
    ])

    results['is_production_ready'] = results['all_windows_complete']

    # Track incomplete windows for debugging
    incomplete = []
    if not results['l5_complete']: incomplete.append('l5')
    if not results['l10_complete']: incomplete.append('l10')
    if not results['l7d_complete']: incomplete.append('l7d')
    if not results['l14d_complete']: incomplete.append('l14d')
    results['incomplete_windows'] = incomplete

    return results
```

**Schema for Multi-Window:**
```sql
-- player_daily_cache additions
l5_ppg NUMERIC(5,2),
l5_complete BOOLEAN,
l10_ppg NUMERIC(5,2),
l10_complete BOOLEAN,
l7d_fatigue_score NUMERIC(5,2),
l7d_complete BOOLEAN,
l14d_fatigue_score NUMERIC(5,2),
l14d_complete BOOLEAN,

-- Overall tracking
all_windows_complete BOOLEAN,  -- TRUE only if ALL 4 windows complete
is_production_ready BOOLEAN,   -- Same as all_windows_complete
incomplete_windows ARRAY<STRING> COMMENT 'List of incomplete window names'
```

**Integration Testing Checklist (Week 3):**
```sql
-- Test 1: Verify window completeness logic
SELECT
    player_name,
    l5_complete,
    l10_complete,
    l7d_complete,
    l14d_complete,
    all_windows_complete,
    is_production_ready
FROM `nba_precompute.player_daily_cache`
WHERE (l5_complete AND l10_complete AND l7d_complete AND l14d_complete AND NOT all_windows_complete)
   OR (NOT (l5_complete AND l10_complete AND l7d_complete AND l14d_complete) AND all_windows_complete);
-- Expected: 0 rows (logic is consistent)

-- Test 2: Verify NULL handling for incomplete windows
SELECT
    COUNT(*) as errors
FROM `nba_precompute.player_daily_cache`
WHERE (NOT l10_complete AND l10_ppg IS NOT NULL)
   OR (l10_complete AND l10_ppg IS NULL);
-- Expected: 0 (NULLs match completeness flags)

-- Test 3: Verify incomplete_windows array
SELECT
    player_name,
    incomplete_windows,
    l5_complete,
    l10_complete,
    l7d_complete,
    l14d_complete
FROM `nba_precompute.player_daily_cache`
WHERE ARRAY_LENGTH(incomplete_windows) > 0
LIMIT 10;
-- Manually verify: array matches actual incomplete windows
```

**Success Criteria:**
- Early dates: Some windows NULL, others populated
- Later dates: All windows populated
- Multi-window logic: is_production_ready = TRUE only when ALL windows complete
- Incomplete windows tracked in array
- Downstream can query: `WHERE l10_ppg IS NOT NULL` for complete L10 data
- All integration tests pass

---

### Phase 4: Remaining Processors (Week 4)

**Goal:** Roll out to all Phase 4 processors

**Processors to update:**
1. ✅ `team_defense_zone_analysis` (done Week 2)
2. `player_shot_zone_analysis`
3. ✅ `player_daily_cache` (done Week 3)
4. `player_composite_factors`
5. `ml_feature_store`

**Special Consideration: Cascade Dependencies**

`player_composite_factors` depends on `team_defense_zone_analysis`:

**Approach: Graceful Degradation**

```python
def calculate_composite_factors(self, player_data: dict, analysis_date: date) -> dict:
    """Calculate factors with upstream awareness."""

    # Check if upstream team defense data exists
    opponent_defense = self._get_opponent_defense(
        player_data['opponent_team'],
        analysis_date
    )

    factors = {}

    if opponent_defense is None:
        # No upstream data at all
        factors['matchup_difficulty'] = None
        factors['upstream_complete'] = False
        factors['upstream_completeness_pct'] = 0.0

    elif opponent_defense['is_production_ready']:
        # High quality upstream
        factors['matchup_difficulty'] = calculate_matchup(player_data, opponent_defense)
        factors['upstream_complete'] = True
        factors['upstream_completeness_pct'] = opponent_defense['completeness_pct']

    else:
        # Low quality upstream - still calculate but flag it
        factors['matchup_difficulty'] = calculate_matchup(player_data, opponent_defense)
        factors['upstream_complete'] = False
        factors['upstream_completeness_pct'] = opponent_defense['completeness_pct']

    # Our own production readiness depends on BOTH our data AND upstream
    factors['is_production_ready'] = (
        player_data['is_production_ready'] and  # Our data is good
        factors.get('upstream_complete', False)   # Upstream is good
    )

    # Track what limited our quality
    if not factors['is_production_ready']:
        reasons = []
        if not player_data['is_production_ready']:
            reasons.append('own_data_incomplete')
        if not factors.get('upstream_complete', False):
            reasons.append('upstream_incomplete')
        factors['quality_limited_by'] = reasons

    return factors
```

**Integration Testing Checklist (Week 4):**
```sql
-- Test 1: Verify cascade dependency handling
SELECT
    COUNT(*) as cascade_errors
FROM `nba_precompute.player_composite_factors` pcf
LEFT JOIN `nba_precompute.team_defense_zone_analysis` tdza
  ON pcf.opponent_team = tdza.team_abbr
  AND pcf.analysis_date = tdza.analysis_date
WHERE pcf.upstream_complete = TRUE
  AND (tdza.is_production_ready = FALSE OR tdza.is_production_ready IS NULL);
-- Expected: 0 (upstream_complete only TRUE when upstream is production-ready)

-- Test 2: Verify quality_limited_by tracking
SELECT
    quality_limited_by,
    COUNT(*) as count
FROM `nba_precompute.player_composite_factors`
WHERE is_production_ready = FALSE
  AND quality_limited_by IS NOT NULL
GROUP BY quality_limited_by;
-- Verify: All incomplete records have reason tracked

-- Test 3: Cross-processor consistency
SELECT
    'team_defense' as processor,
    AVG(completeness_pct) as avg_completeness
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE - 1
UNION ALL
SELECT
    'player_daily' as processor,
    AVG(completeness_pct) as avg_completeness
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date = CURRENT_DATE - 1;
-- Verify: Both processors showing similar completeness trends
```

**Key Point:** Don't cascade-fail. Process with available data, track upstream completeness.

**Success Criteria:**
- All 5 Phase 4 processors updated
- Cascade dependencies handled gracefully
- Completeness metadata consistent across processors
- All integration tests pass

---

### Phase 5: Monitoring Implementation (Week 5)

**Goal:** Build comprehensive monitoring and alerting

See [Monitoring & Alerting](#monitoring--alerting) section for details.

**Deliverables:**
- Completeness dashboard queries
- Daily monitoring job with concrete alert thresholds
- Season boundary detection
- Slack/email alerts for anomalies
- Documentation for interpreting metrics

**Integration Testing Checklist (Week 5):**
```sql
-- Test 1: Verify all monitoring views exist
SELECT table_name
FROM INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'nba_monitoring'
  AND table_name IN (
    'phase4_completeness_daily',
    'reprocessing_queue',
    'processor_health',
    'missing_games_summary',
    'phase5_processing_success',
    'phase5_skip_reasons'
  );
-- Expected: 6 rows

-- Test 2: Verify monitoring views return data
SELECT COUNT(*) as has_data
FROM `nba_monitoring.phase4_completeness_daily`
WHERE analysis_date >= CURRENT_DATE - 7;
-- Expected: >0 (views are populated)

-- Test 3: Verify alert thresholds are reasonable
SELECT
    analysis_date,
    days_since_season_start,
    production_ready_pct,
    CASE
        WHEN days_since_season_start <= 10 AND production_ready_pct >= 30 THEN 'OK'
        WHEN days_since_season_start <= 20 AND production_ready_pct >= 80 THEN 'OK'
        WHEN days_since_season_start > 20 AND production_ready_pct >= 95 THEN 'OK'
        ELSE 'ALERT'
    END as threshold_status
FROM `nba_monitoring.phase4_completeness_daily`
WHERE analysis_date >= CURRENT_DATE - 30;
-- Review: Are alerts triggering appropriately?
```

---

### Phase 6: Backfill Execution (Week 6-7)

**Goal:** Execute 4-year backfill with monitoring

**Approach: Staged backfill with validation**

**Stage 1: 3-Month Test (Week 6)**
```bash
# Backfill Oct 2020 - Dec 2020 (3 months)
python backfill_phase4.py \
    --start-date 2020-10-20 \
    --end-date 2020-12-31 \
    --processors all \
    --parallel 4 \
    --enable-auto-reprocess false  # Disable during backfill
```

**Validation:**
- Check completeness distribution (should progress 0% → 100% over ~25 days)
- Verify no processing failures
- Monitor BigQuery costs
- Review sample records for data quality
- Verify circuit breaker not triggered (expected during backfill)

**Stage 2: Full Backfill (Week 7)**
```bash
# Backfill all 4 seasons
python backfill_phase4.py \
    --start-date 2020-10-20 \
    --end-date 2024-10-31 \
    --processors all \
    --parallel 8 \
    --enable-auto-reprocess false
```

**Monitor during backfill:**
- Processing rate (dates/hour)
- Error rate (should be <1%)
- Completeness progression
- Cost accumulation
- Circuit breaker events (should be none during clean backfill)

**Integration Testing Checklist (Week 6-7):**
```sql
-- Test 1: Verify full date coverage
SELECT
    MIN(analysis_date) as earliest_date,
    MAX(analysis_date) as latest_date,
    COUNT(DISTINCT analysis_date) as unique_dates,
    DATE_DIFF(MAX(analysis_date), MIN(analysis_date), DAY) + 1 as expected_dates
FROM `nba_precompute.team_defense_zone_analysis`;
-- Verify: unique_dates ≈ expected_dates (allowing for off-days)

-- Test 2: Verify completeness progression pattern
WITH daily_avg AS (
    SELECT
        analysis_date,
        AVG(completeness_pct) as avg_completeness,
        MIN(analysis_date) OVER () as season_start
    FROM `nba_precompute.team_defense_zone_analysis`
    WHERE analysis_date BETWEEN '2020-10-20' AND '2020-11-20'
    GROUP BY analysis_date
)
SELECT
    analysis_date,
    avg_completeness,
    DATE_DIFF(analysis_date, season_start, DAY) as days_into_season
FROM daily_avg
ORDER BY analysis_date;
-- Verify: Steady increase from low % to 90%+ over ~20 days

-- Test 3: Verify no excessive reprocessing during backfill
SELECT
    reprocessed_count,
    COUNT(*) as record_count
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN '2020-10-20' AND '2024-10-31'
GROUP BY reprocessed_count
ORDER BY reprocessed_count;
-- Expected: Most records have reprocessed_count = 0 (backfill with auto-reprocess disabled)
```

**Success Criteria:**
- All dates 2020-2024 processed
- No critical failures
- Completeness metadata present on all records
- Cost within expectations (<$50 for full backfill)
- Circuit breaker not triggered during backfill (expected behavior)
- All integration tests pass

---

[The document continues with all remaining sections from the Opus plan - Schema Design, Completeness Checking, Downstream Consumption Guidelines, Decision Visibility Schema, Reprocessing Strategy, Monitoring & Alerting, Edge Case Handling, Rollback Procedure, Cost Analysis, Future Enhancements, Success Criteria...]

[Due to length limits, I'm truncating here, but the full document would contain all ~1000 lines of the Opus plan you provided]
