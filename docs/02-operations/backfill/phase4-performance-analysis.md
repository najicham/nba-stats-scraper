# Phase 4 Backfill Performance Analysis

**Date:** 2025-12-07
**Scope:** November-December 2021 backfill analysis
**Status:** Comprehensive investigation complete

---

## Executive Summary

This document captures a deep investigation into Phase 4 backfill performance, including timing patterns, failure analysis, code bottlenecks, and optimization effectiveness. Key findings:

| Metric | Finding |
|--------|---------|
| **100x Optimization** | Confirmed working - dependency check: 103s → ~0s |
| **Bug Count** | 0 PROCESSING_ERROR in 9,118 failures |
| **Failure Pattern** | 88% INSUFFICIENT_DATA (expected), 12% cascades |
| **Slowest Processor** | MLFeatureStoreProcessor (avg 12.8 min pre-optimization) |
| **December Gap** | PCF/PDC/ML have 0 records (needs backfill) |

---

## 1. Processor Timing Analysis

### Average Duration (With Optimization)

| Processor | Avg Duration | Min | Max | Notes |
|-----------|-------------|-----|-----|-------|
| TeamDefenseZoneAnalysis | 28.7s | 24s | 35s | Fastest, 30 teams only |
| PlayerCompositeFactors | 46.6s | 28s | 75s | Fast, in-memory calcs |
| MLFeatureStore | 64.2s | 50s | 90s | **31x faster** post-opt |
| PlayerDailyCache | 65.0s | 43s | 120s | 4.4x faster post-opt |
| PlayerShotZoneAnalysis | 73.4s | 45s | 90s | 5.8x faster post-opt |

### Pre vs Post Optimization (Dec 7, 2025)

| Processor | Before (avg) | After (avg) | Speedup |
|-----------|--------------|-------------|---------|
| MLFeatureStoreProcessor | 1,989s (33 min) | 64s | **31x** |
| PlayerShotZoneAnalysisProcessor | 424s (7 min) | 73s | **5.8x** |
| PlayerDailyCacheProcessor | 286s (4.8 min) | 65s | **4.4x** |
| PlayerCompositeFactorsProcessor | 121s (2 min) | 47s | **2.6x** |
| TeamDefenseZoneAnalysisProcessor | 63s | 29s | **2.2x** |

### Dependency Check Speedup (100x Optimization)

**Location:** `data_processors/precompute/precompute_base.py` lines 206-217

```python
if self.is_backfill_mode:
    logger.info("⏭️  BACKFILL MODE: Skipping dependency check")
    self.dep_check = {
        'all_critical_present': True,
        'all_fresh': True,
        'skipped_in_backfill': True
    }
```

**Impact by Processor:**

| Processor | Dep Check Before | After | Speedup |
|-----------|-----------------|-------|---------|
| MLFeatureStoreProcessor | 7,797s (2.2 hrs) | 0.2s | **38,985x** |
| PlayerShotZoneAnalysis | 5,777s (1.6 hrs) | 0s | **∞** |
| PlayerDailyCacheProcessor | 885s (14.8 min) | 0s | **∞** |

---

## 2. Time Breakdown by Phase

Based on code analysis of all Phase 4 processors:

### Extract Phase (BigQuery Queries)
| Processor | Queries | Time | Strategy |
|-----------|---------|------|----------|
| PSZA | 1 | 10-20s | Window function for L20 games |
| TDZA | 1 | 5-10s | Team aggregation |
| PCF | 4 | 15-25s | Batch extract |
| PDC | 4 | 15-25s | Batch extract |
| ML | 8 | 20-40s | Batch extract (20x optimization) |

### Calculate Phase (Player Processing)
| Processor | Workers | Rate | Strategy |
|-----------|---------|------|----------|
| PSZA | 10 | 12-13 players/sec | ThreadPoolExecutor |
| TDZA | 4 | 5-6 teams/sec | ThreadPoolExecutor |
| PCF | 10 | 600+ players/sec | In-memory (fast) |
| PDC | 8 | 10 players/sec | ThreadPoolExecutor |
| ML | 10 | 13-14 players/sec | ThreadPoolExecutor |

### Save Phase (BigQuery Writes)
- All processors: DELETE + INSERT pattern
- Batch size: Full date payload
- Time: 5-15s per processor

---

## 3. Failure Pattern Analysis

### Overall Stats (Nov-Dec 2021)
- **Total Failures:** 9,118
- **PROCESSING_ERROR (bugs):** 0 (100% healthy)
- **INSUFFICIENT_DATA:** 8,057 (88%)
- **MISSING_DEPENDENCY:** 1,034 (11%)
- **MISSING_DEPENDENCIES:** 27 (0.3%)

### By Processor
| Processor | Failures | Category | Root Cause |
|-----------|----------|----------|------------|
| PSZA | 5,976 | INSUFFICIENT_DATA | <10 games played |
| PDC | 2,081 | INSUFFICIENT_DATA | <5 games played |
| PDC | 1,034 | MISSING_DEPENDENCY | PSZA cascade |
| ML | 19 | MISSING_DEPENDENCIES | Upstream cascade |
| PCF | 8 | MISSING_DEPENDENCIES | Upstream cascade |

### Weekly Failure Trend (PSZA)
| Week | Failures | Unique Players | Pattern |
|------|----------|----------------|---------|
| Oct 31 | 749 | 387 | Bootstrap |
| Nov 07 | 1,644 | 323 | Peak |
| Nov 14 | 1,884 | 186 | High |
| Nov 21 | 1,337 | 146 | Declining |
| Nov 28 | 362 | 126 | Baseline |

**Trend:** 60% reduction from week 3 to week 5 - healthy ramp-down.

### Expected Failure Rates by Season Week
| Season Week | Days | Expected Failure % | Actual (Nov 2021) |
|-------------|------|-------------------|-------------------|
| 1-2 | 1-14 | 90-100% | 83.8% ✓ |
| 3 | 15-21 | 60-75% | 51.3% ✓ |
| 4 | 22-28 | 40-50% | 31.6% ✓ |
| 5+ | 29+ | 25-30% | 26.1% ✓ |

---

## 4. Data Completeness Status

### November 2021
| Processor | Dates | Records | Status |
|-----------|-------|---------|--------|
| PSZA | 26 | 6,659 | ✅ Complete |
| TDZA | 26 | 780 | ✅ Complete |
| PCF | 25 | 6,534 | ✅ Complete |
| PDC | 25 | 3,485 | ✅ Complete |
| ML | 25 | 6,699 | ✅ Complete |

### December 2021
| Processor | Dates | Records | Status |
|-----------|-------|---------|--------|
| PSZA | 30 | 10,914 | ✅ Complete |
| TDZA | 29 | 870 | ⚠️ Missing Dec 4 |
| PCF | 0 | 0 | ❌ Empty |
| PDC | 0 | 0 | ❌ Empty |
| ML | 0 | 0 | ❌ Empty |

**Root Cause:** Backfill stopped after Nov 30, processors 1-2 continued but 3-5 never ran.

---

## 5. Code Architecture & Bottlenecks

### Parallelization Strategy
```
┌─────────────────────────────────────────────────────────┐
│  Phase 4 Execution (per date)                           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  PARALLEL:     TDZA ─────┐                              │
│                          ├──> Wait                      │
│                PSZA ─────┘                              │
│                                                         │
│  SEQUENTIAL:  PCF ──> PDC ──> ML                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Key Optimizations Implemented

1. **100x Dependency Skip** (commit `1e0284b`)
   - Skip freshness checks in backfill mode
   - Impact: 103s → 0s per date

2. **20x Batch Extraction** (ML Feature Store)
   - 8 queries total vs 8 × N players
   - Impact: 3,600 queries → 8 queries

3. **4x Parallel Completeness** (Player Daily Cache)
   - 4 sequential checks → 4 parallel
   - Impact: 120s → 30s

4. **Backfill Mode Completeness Skip**
   - Skip per-player completeness checks
   - Impact: 450 queries → 0

### Remaining Bottlenecks

| Bottleneck | Location | Current | Potential Fix |
|------------|----------|---------|---------------|
| Player processing | Calculate phase | 10-15 players/sec | Increase workers |
| BQ write | Save phase | 5-15s | Already optimized |
| Circuit breaker check | Per-player query | 450 queries | Batch query |

---

## 6. Backfill Execution Guide

### Full Phase 4 Backfill Command
```bash
# Run all 5 processors in correct order
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2021-12-01 \
  --end-date 2021-12-31

# Or start from processor 3 (PCF) if PSZA/TDZA done:
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2021-12-01 \
  --end-date 2021-12-31 \
  --start-from 3
```

### Expected Timing (December 2021)
| Phase | Duration | Notes |
|-------|----------|-------|
| PCF (30 dates) | ~25-35 min | ~50s per date |
| PDC (30 dates) | ~35-45 min | ~70s per date |
| ML (30 dates) | ~30-40 min | ~65s per date |
| **Total** | **~90-120 min** | With optimization |

### Validation Queries
```sql
-- Quick status check
SELECT
  "PCF" as proc, COUNT(DISTINCT DATE(analysis_date)) as dates, COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE DATE(analysis_date) BETWEEN "2021-12-01" AND "2021-12-31"
UNION ALL
SELECT "PDC", COUNT(DISTINCT DATE(cache_date)), COUNT(*)
FROM nba_precompute.player_daily_cache
WHERE DATE(cache_date) BETWEEN "2021-12-01" AND "2021-12-31"
UNION ALL
SELECT "ML", COUNT(DISTINCT DATE(game_date)), COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE DATE(game_date) BETWEEN "2021-12-01" AND "2021-12-31";

-- Check for bugs (should return 0)
SELECT COUNT(*) as bug_count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN "2021-12-01" AND "2021-12-31"
  AND failure_category = "PROCESSING_ERROR";
```

---

## 7. Key Insights

### What Works Well
1. **Parallelization** - 10 workers per processor, ThreadPoolExecutor
2. **Batch extraction** - Single queries for all players
3. **Dependency skip** - 100x speedup in backfill mode
4. **Error tracking** - All failures categorized and logged
5. **Checkpointing** - Resume capability at date level

### What to Monitor
1. **Failure rate** - Should be 15-25% for December (mid-season)
2. **PROCESSING_ERROR** - Must be 0 (any = bug)
3. **Processing time** - Should be <2 min/date with optimization
4. **Record counts** - ~350-400 per processor per date

### Expected December Results
| Metric | Expected |
|--------|----------|
| PSZA Success Rate | 75-85% |
| PDC Success Rate | 80-90% |
| Records per Date | 350-400 |
| Total Time | ~2 hours |
| PROCESSING_ERROR | 0 |

---

## Appendix: File References

### Core Code
- `data_processors/precompute/precompute_base.py` - Base class, 100x optimization
- `data_processors/precompute/*/` - Individual processors
- `backfill_jobs/precompute/*/` - Backfill scripts
- `bin/backfill/run_phase4_backfill.sh` - Orchestrator

### Documentation
- `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md` - Runbook
- `docs/09-handoff/2025-12-07-SESSION67-*.md` - Session notes

### Validation
- `bin/validate_pipeline.py` - Pipeline validation
- `nba_processing.precompute_failures` - Failure tracking
- `nba_reference.processor_run_history` - Run history
