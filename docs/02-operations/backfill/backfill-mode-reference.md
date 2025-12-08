# Backfill Mode Reference

**File:** `docs/02-operations/backfill/backfill-mode-reference.md`
**Created:** 2025-12-08 12:30 PM PST
**Last Updated:** 2025-12-08 12:30 PM PST
**Purpose:** Comprehensive reference for backfill mode flag behaviors
**Status:** Current

---

## Overview

Backfill mode is a processing configuration that optimizes for throughput when processing historical data. It trades some validation overhead for significant performance gains while maintaining data integrity through lightweight safety checks.

**Key principle:** Backfill mode is aggressive but not reckless - it skips expensive validation but keeps lightweight safety checks.

---

## Activating Backfill Mode

### Python API
```python
processor.run({
    'backfill_mode': True,              # Primary flag (preferred)
    'skip_downstream_trigger': True,    # Prevents auto-triggering Phase 4/5
    'start_date': '2021-11-01',
    'end_date': '2021-11-30'
})
```

### Legacy Aliases (Still Supported)
```python
# These also activate backfill mode:
'is_backfill': True           # Legacy alias, logs deprecation warning
'skip_downstream_trigger': True  # Implies backfill mode
```

### Detection in Code
```python
@property
def is_backfill_mode(self) -> bool:
    return (
        self.opts.get('backfill_mode', False) or
        self.opts.get('is_backfill', False) or
        self.opts.get('skip_downstream_trigger', False)
    )
```

**Location:** `data_processors/precompute/precompute_base.py:736-753`

---

## Behavior Changes in Backfill Mode

### 1. Dependency Check Optimization (100x Speedup)

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Full BQ dependency check | Yes (120-300s) | No |
| Quick existence check | No | Yes (~1-2s) |
| Freshness validation | Yes | No |
| Age checks | Yes | No |

**Why:** Pre-flight checks already verify data exists before backfill starts. Full dependency checks are redundant.

**Implementation:**
```python
# Phase 4 (precompute_base.py:208-231)
if self.is_backfill_mode:
    missing = self._quick_upstream_existence_check(analysis_date)
    if missing:
        raise ValueError(f"Missing critical upstream: {missing}")
    logger.info("BACKFILL MODE: Quick check passed")
else:
    # Full 60+ second validation
    full_result = self.completeness_checker.check_completeness_batch(...)
```

**Files:**
- `data_processors/precompute/precompute_base.py:208-231`
- `data_processors/analytics/analytics_base.py:196-223`

---

### 2. Completeness Check Skip (10-20x Speedup)

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Per-player completeness | Yes (600s+) | No |
| Window validation | Yes | No |
| Expected count check | Strict | Relaxed (min=1) |

**Why:** Historical backfills process hundreds of dates. Per-player completeness checks across 600+ players take 10+ minutes per date.

**Applied to:** PSZA, PCF, PDC, MLFS processors

**Files:**
- `player_composite_factors_processor.py:1016-1017`
- `player_shot_zone_analysis_processor.py:874-875`
- `ml_feature_store_processor.py:762-763`

---

### 3. Defensive Checks Bypass

| Check | Daily Mode | Backfill Mode |
|-------|-----------|---------------|
| Yesterday's upstream success | Verified | Skipped |
| Gap detection in lookback | Yes | No |
| Date range completeness | Enforced | Skipped |

**Why:** Backfill mode processes historical data with known gaps. Defensive checks designed for continuous daily data don't apply.

**Files:**
- `precompute_base.py:835-836`
- `analytics_base.py:411-412`

---

### 4. Notification Suppression

| Notification Type | Daily Mode | Backfill Mode |
|-------------------|-----------|---------------|
| Missing dependency alerts | Sent | Suppressed |
| Stale data warnings | Sent | Suppressed |
| Processor failure alerts | Sent | Suppressed |

**Why:** Backfill jobs process thousands of dates. Without suppression, alerts flood email/Slack with expected historical failures.

**Implementation:**
```python
def _send_notification(self, alert_func, *args, **kwargs):
    if self.is_backfill_mode:
        logger.info(f"BACKFILL_MODE: Suppressing alert...")
        return
    return alert_func(*args, **kwargs)
```

**File:** `analytics_base.py:135-147`

---

### 5. Threshold Relaxation

| Threshold | Daily Mode | Backfill Mode |
|-----------|-----------|---------------|
| Min players required | 100 | 20 |
| Min teams required | 10 | 5 |
| Expected count min | Per config | 1 |

**Why:** Early season (bootstrap period) has fewer players with enough game history. Backfill mode accommodates this.

**Files:**
- `player_composite_factors_processor.py:554-555`
- `ml_feature_store_processor.py:230`

---

### 6. Query Timeout Optimization

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Dependency query timeout | 300s (5 min) | 60s |

**Why:** Fail fast on BigQuery connectivity issues. Backfill retry loops recover faster with quick timeouts.

**File:** `precompute_base.py:621`

---

### 7. Circuit Breaker Skip

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Circuit breaker check | Yes | No |
| Rate limit tracking | Yes | No |
| Retry counting | Yes | No |

**Why:** Circuit breakers prevent runaway retries in production. For historical data, there's no operational concern about retry storms.

**File:** `team_defense_zone_analysis_processor.py:592-596`

---

### 8. Reprocess Recording Skip

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Log reprocess attempts | Yes | No |
| Update tracking table | Yes | No |

**Why:** Reprocess tracking only relevant for current/recent dates, not historical backfill.

**File:** `player_daily_cache_processor.py:1490-1491`

---

### 9. Downstream Trigger Suppression

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Pub/Sub completion message | Published | Skipped |
| Auto-trigger Phase 4 | Yes | No |
| Auto-trigger Phase 5 | Yes | No |

**Why:** Backfill jobs control their own orchestration. Without suppression, completing one date would auto-trigger downstream phases multiple times.

**Implementation:**
```python
if skip_downstream_trigger:
    logger.info("Skipping downstream trigger (backfill mode)")
    return
# Otherwise publish to nba-phase3-analytics-complete or nba-phase4-precompute-complete
```

**Files:**
- `precompute_base.py:1398-1486`
- `analytics_base.py:1674-1834`

---

### 10. Historical Date Check Bypass

| Check | Daily Mode | Backfill Mode |
|-------|-----------|---------------|
| Reject dates >90 days old | Yes | No |
| Offseason check | Still applies | Still applies |
| No games check | Still applies | Still applies |

**Why:** Backfill jobs intentionally process old dates. Historical check exists to catch daily mode mistakes.

**File:** `shared/processors/patterns/early_exit_mixin.py:68-90`

---

### 11. Stale Data Handling

| Scenario | Daily Mode | Backfill Mode |
|----------|-----------|---------------|
| Stale upstream detected | Fail | Continue with warning |

**Why:** Backfill mode intentionally processes stale historical data.

**File:** `upcoming_team_game_context_processor.py:412-427`

---

## Safety Checks Still Active in Backfill Mode

Even in aggressive backfill mode, these safety checks remain:

1. **Quick upstream existence check** - Verifies critical tables have data (~1s)
2. **Failure recording** - All failures still logged to `precompute_failures`
3. **Data hash computation** - Idempotency tracking still active
4. **Bootstrap period detection** - Early season handling still applies
5. **Basic validation** - Output schema validation still runs

---

## Performance Impact Summary

| Optimization | Before | After | Speedup |
|--------------|--------|-------|---------|
| Dependency check | 103s | ~0s | **100x** |
| Completeness check | 600s | ~0s | **10-20x** |
| Circuit breaker | 2-3s/entity | 0s | **N/A** |
| Total per date | 45 min | ~5 min | **9x** |
| 4-year backfill | ~76 hours | ~33 hours | **2.3x** |

---

## When to Use Backfill Mode

**Use backfill mode when:**
- Processing historical data (>1 day old)
- Running batch backfills across date ranges
- Re-processing after upstream fixes
- Initial data population

**Do NOT use backfill mode when:**
- Processing today's data
- Running production daily orchestration
- Data quality is critical and time is not a concern

---

## Common Patterns

### Standard Backfill Job Pattern
```python
opts = {
    'start_date': date_to_process,
    'end_date': date_to_process,
    'backfill_mode': True,
    'skip_downstream_trigger': True
}
processor.run(opts)
```

### Backfill with Validation
```bash
# 1. Pre-flight check
python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-11-01 --end-date 2021-11-30

# 2. Run backfill
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-11-30

# 3. Validate results
python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-11-30 --details
python scripts/validate_cascade_contamination.py --start-date 2021-11-01 --end-date 2021-11-30 --strict
```

---

## Troubleshooting

### Backfill Mode Not Activating
```python
# Check if backfill mode is active
if processor.is_backfill_mode:
    print("Backfill mode is ACTIVE")
else:
    print("Backfill mode is NOT active - check opts")
```

### Silent Data Gaps Despite Backfill Mode
If cascade contamination occurs despite backfill mode:
1. Check quick existence check passed
2. Verify upstream data quality (not just existence)
3. Run `validate_cascade_contamination.py` after backfill

### Performance Not Improved
Verify these optimizations are active:
1. Check logs for "BACKFILL MODE: Skipping..."
2. Verify `skip_downstream_trigger: True` is set
3. Check completeness check is actually skipped

---

## Related Documentation

- [backfill-guide.md](./backfill-guide.md) - Overall backfill procedures
- [data-gap-prevention-and-recovery.md](./data-gap-prevention-and-recovery.md) - Gap handling
- [PHASE4-PERFORMANCE-ANALYSIS.md](./PHASE4-PERFORMANCE-ANALYSIS.md) - Performance benchmarks
- [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md) - Phase 4 runbook
