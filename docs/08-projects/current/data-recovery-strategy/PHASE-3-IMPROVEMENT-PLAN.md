# Phase 3 Improvement Plan

**Created:** Session 39 (2026-01-30)
**Status:** Analysis Complete, Implementation Pending

---

## Executive Summary

Phase 3 (Analytics Processors) has orchestration gaps compared to Phase 2 and Phase 4. This document analyzes patterns across all phases and provides a concrete improvement plan.

---

## Current Architecture Comparison

### Phase 2 (Raw Processors) - BEST PATTERNS

| Pattern | Implementation | Impact |
|---------|---------------|--------|
| **Missing data signals** | Explicit `skip_processing` flag | Prevents 30% of false failures |
| **Soft dependencies** | 80% threshold + graceful degrade | Reduces 2-3 daily alerts |
| **Smart idempotency** | Hash-based deduplication | Prevents 40-50% of cascade triggers |
| **Batch detection** | Routes to specialized handlers | Improves throughput |
| **Output validation** | Layer 5 zero-row detection | Catches silent failures |
| **Streaming buffer retry** | 3 retries, 7 min backoff | Handles transient errors |

### Phase 3 (Analytics) - CURRENT GAPS

| Gap | Current Behavior | Impact |
|-----|------------------|--------|
| **No missing data handling** | Fails immediately | Retry loops on empty upstream |
| **Hard 100% dependency** | All-or-nothing | Can't process partial data |
| **No source alternatives** | Single source per processor | Fails when source missing |
| **No early-season detection** | Treats Jan 1 like Jan 30 | False failures in bootstrap |
| **No output validation** | Silent zero-row saves | Undetected data gaps |

### Phase 4 (Precompute) - RECOVERY PATTERNS

| Pattern | Implementation | Impact |
|---------|---------------|--------|
| **Tiered dependency checks** | Full → Defensive → Quick | Catches issues at right level |
| **Soft dependencies** | 80% threshold option | Graceful degradation |
| **Early season detection** | First 14 days = bootstrap | Prevents false failures |
| **Defensive upstream checks** | Verify Phase 3 succeeded | Catches failures before wasting compute |
| **Gap detection** | Check rolling window completeness | Prevents partial processing |

### Phase 5 (Predictions) - QUALITY PATTERNS

| Pattern | Implementation | Impact |
|---------|---------------|--------|
| **Quality tiers** | GOLD/SILVER/BRONZE | Visibility into data state |
| **Pre-flight filter** | Skip <70% quality players | 15-25% faster processing |
| **Fail-open for non-critical** | Continue without injury data | Never blocks on optional data |
| **Multiple systems** | 7 independent predictors | Partial failure ≠ no prediction |
| **Automatic re-run** | BDB arrival triggers refresh | Self-healing |

---

## Known Gaps (Session 39)

### Gap 1: Jan 22-23 Cannot Be Backfilled

**Problem:** `nbac_gamebook_player_stats` table has 0 records for these dates.

```
| Date       | nbac_gamebook_stats | bdl_boxscores | Phase 3 Status |
|------------|---------------------|---------------|----------------|
| 2026-01-22 | 0 records           | 282 records   | ❌ Blocked     |
| 2026-01-23 | 0 records           | 281 records   | ❌ Blocked     |
```

**Root Cause:** NBAC scraper didn't run or failed for these dates.

**Impact:** Cannot recalculate shot zones for ~550 player-games.

**Resolution Options:**
1. Re-run NBAC scraper for Jan 22-23 (if data still available)
2. Modify Phase 3 to use BDL boxscores as alternative source
3. Accept as historical gap (predictions already made)

### Gap 2: nba-phase3-trigger Topic Has No Subscribers

**Problem:** The backfill script was publishing to `nba-phase3-trigger` but nothing listens.

**Current Trigger Paths:**
```
✅ nba-phase2-raw-complete → Eventarc → phase2-to-phase3-orchestrator → HTTP
✅ nba-phase2-raw-complete → nba-phase3-analytics-sub → Direct push to Phase 3
❌ nba-phase3-trigger → (no subscribers)
```

**Impact:** Any code using `nba-phase3-trigger` won't trigger Phase 3.

**Resolution:**
- Fixed backfill script to use HTTP `/process-date-range` endpoint
- Consider deleting vestigial topic to avoid confusion

### Gap 3: NBAC Play-by-Play Table Empty

**Problem:** `nba_raw.nbac_play_by_play` has 0 records.

**Impact:** Shot zone fallback path has nothing to fall back to.

**Root Cause:** NBAC PBP scraper not running or not populating this table.

**Resolution:** Investigate NBAC PBP scraper, or remove fallback path if unused.

### Gap 4: Phase 3 Retry Loops

**Problem:** Phase 3 fails on Jan 29 with "No data extracted" every ~15 seconds.

**Impact:** Wastes compute, creates noise in logs, Pub/Sub retries indefinitely.

**Root Cause:** Completeness check fails but returns 500 (triggers retry) instead of 200 (ACK).

**Resolution:** Return 200 with skip reason when upstream data is incomplete.

---

## Phase 3 Improvement Plan

### Priority 1: Add Missing Data Handling (Week 1)

**Problem:** Phase 3 fails when upstream has no data.

**Solution:** Check upstream record count before processing.

```python
# BEFORE:
def run(self):
    self.extract_data()  # Fails if no data
    self.validate_extracted_data()

# AFTER:
def run(self):
    if not self._has_upstream_data():
        logger.info("No upstream data - skipping (expected)")
        return {'status': 'skipped', 'reason': 'no_upstream_data'}

    self.extract_data()
    self.validate_extracted_data()
```

**Files to modify:**
- `data_processors/analytics/analytics_base.py`
- `data_processors/analytics/main_analytics_service.py`

### Priority 2: Implement Soft Dependencies (Week 2)

**Problem:** Phase 3 requires 100% of dependencies or fails.

**Solution:** Add 80% threshold option.

```python
# Add to analytics_base.py
SOFT_DEPENDENCY_THRESHOLD = 0.80  # Proceed if >80% fresh

def check_dependencies(self):
    coverage = self._calculate_dependency_coverage()

    if coverage >= SOFT_DEPENDENCY_THRESHOLD:
        logger.warning(f"Proceeding with {coverage*100:.1f}% coverage")
        return True
    elif coverage > 0:
        logger.error(f"Coverage {coverage*100:.1f}% below threshold")
        return False
```

### Priority 3: Add Alternative Source Support (Week 2)

**Problem:** If `nbac_gamebook_player_stats` is empty, can't use `bdl_player_boxscores`.

**Solution:** Configure multiple source options per processor.

```python
# In PlayerGameSummaryProcessor
SOURCES = {
    'primary': 'nbac_gamebook_player_stats',
    'fallback': 'bdl_player_boxscores',
}

def extract_data(self):
    if self._source_has_data(self.SOURCES['primary']):
        return self._extract_from_nbac()
    elif self._source_has_data(self.SOURCES['fallback']):
        logger.warning("Using BDL fallback (NBAC unavailable)")
        return self._extract_from_bdl()
    else:
        return None  # No data available
```

### Priority 4: Add Early Season Detection (Week 3)

**Problem:** First 14 days of season fail due to missing historical data.

**Solution:** Detect bootstrap period and return success.

```python
# In analytics_base.py
def is_early_season(self, analysis_date: date) -> bool:
    season_start = get_season_start_date(analysis_date)
    days_since_start = (analysis_date - season_start).days
    return days_since_start < 14

def check_dependencies(self):
    if self.is_early_season(self.analysis_date):
        if missing_dependencies:
            logger.info("Early season - missing dependencies expected")
            return True  # Proceed anyway
```

### Priority 5: Add Output Validation (Week 3)

**Problem:** Zero-row saves go undetected.

**Solution:** Validate output before marking success.

```python
# After save_data()
def validate_output(self):
    if self.stats['rows_inserted'] == 0:
        expected = self._estimate_expected_rows()
        if expected > 0:
            reason = self._diagnose_zero_rows()
            if reason not in ['no_games_scheduled', 'early_season']:
                self.notify_unexpected_zero_rows(reason)
```

### Priority 6: Fix HTTP Response Codes (Week 1)

**Problem:** Phase 3 returns 500 when it should return 200.

**Current behavior:**
```
No upstream data → Fail validation → Return 500 → Pub/Sub retry → Loop
```

**Correct behavior:**
```
No upstream data → Detect early → Return 200 with skip reason → No retry
```

```python
# In main_analytics_service.py
if result.get('status') == 'skipped':
    return jsonify({
        'status': 'skipped',
        'reason': result.get('reason'),
        'game_date': game_date
    }), 200  # ACK the message, don't retry
```

---

## Implementation Timeline

| Week | Priority | Task | Files | Status |
|------|----------|------|-------|--------|
| 1 | P1 | Missing data handling | analytics_base.py, main_analytics_service.py | ✅ Session 40 |
| 1 | P6 | Fix HTTP response codes | main_analytics_service.py | ✅ Session 40 |
| 2 | P2 | Soft dependencies (80% threshold) | dependency_mixin.py, analytics_base.py | ✅ Session 41 |
| 2 | P3 | Alternative sources (BDL fallback) | player_game_summary_processor.py | ⏸️ On hold - BDL unreliable |
| 3 | P4 | Early season detection | analytics_base.py | Not started |
| 3 | P5 | Output validation | analytics_base.py | Not started |

### Session 41 Updates (2026-01-30)

**P2 Soft Dependencies - COMPLETED:**
- Added coverage calculation to `dependency_mixin.py`
- When `use_soft_dependencies=True` and coverage >= 80%, processing continues in "degraded" mode
- Tracks degraded state in stats for monitoring

**P3 Alternative Sources - ON HOLD:**
- BDL data quality investigation showed ~50% accuracy for many players
- Decision: Keep BDL disabled until quality improves
- Added automated BDL quality monitoring via `data-quality-alerts` Cloud Function
- Check `nba_orchestration.bdl_quality_trend` view for readiness indicator
- Re-enable when `bdl_readiness = 'READY_TO_ENABLE'` for 7 consecutive days

---

## Pattern Adoption Summary

### Adopt from Phase 2

| Pattern | Phase 2 Location | Phase 3 Action |
|---------|-----------------|----------------|
| `skip_processing` flag | `main_processor_service.py` | Add to main_analytics_service.py |
| Batch detection | `batch_detector.py` | Not needed (analytics don't batch) |
| Smart idempotency | `SmartIdempotencyMixin` | Consider for future |
| Streaming buffer retry | `processor_base.py` | Copy retry logic |

### Adopt from Phase 4

| Pattern | Phase 4 Location | Phase 3 Action |
|---------|-----------------|----------------|
| Tiered dependencies | `precompute_base.py` | Implement in analytics_base.py |
| Early season detection | `defensive_check_mixin.py` | Copy logic |
| Upstream processor check | `defensive_check_mixin.py` | Add to dependency check |
| Gap detection | `completeness_checker.py` | Add rolling window validation |

### Adopt from Phase 5

| Pattern | Phase 5 Location | Phase 3 Action |
|---------|-----------------|----------------|
| Quality tiers | `quality_tracker.py` | Already added in Session 39 |
| Graceful degradation | `worker.py` | Apply to shot zone extraction |
| Automatic re-run | `bdb_arrival_trigger` | Already added in Session 39 |

---

## Success Metrics

After implementing these improvements:

| Metric | Current | Target |
|--------|---------|--------|
| False failures per week | 15-20 | <5 |
| Retry loop incidents | 2-3/day | 0 |
| Alert noise reduction | N/A | 50% fewer alerts |
| Backfill success rate | ~60% | >95% |
| Early season failures | 10-15/day | 0 |

---

## Next Steps

1. **Immediate (Session 40):**
   - Fix HTTP response codes to stop retry loops
   - Add missing data handling

2. **Short-term (Week 2):**
   - Implement soft dependencies
   - Add alternative source support

3. **Medium-term (Week 3-4):**
   - Add early season detection
   - Add output validation
   - Comprehensive testing

4. **Long-term:**
   - Consider smart idempotency (reduce cascade triggers)
   - Add pipeline event logging for unified visibility
