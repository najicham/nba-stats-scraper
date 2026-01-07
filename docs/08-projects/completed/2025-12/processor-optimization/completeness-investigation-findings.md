# Completeness Checker Investigation Findings

**Date:** 2025-12-08
**Status:** Complete
**Related Session:** 86

---

## Investigation Summary

Investigated what happens when completeness checks fail, visibility into failures, and recovery procedures.

---

## Key Findings

### 1. Completeness Check Flow

When a processor runs, it checks upstream data completeness:

| Mode | Completeness | Result | Visibility |
|------|--------------|--------|------------|
| Production, >= 90% | Complete | Record saved with `is_production_ready=TRUE` | Normal |
| Production, < 90% | Incomplete | **SKIPPED** - Entity not processed | `precompute_failures` table |
| Bootstrap (first 30 days) | Incomplete | Record saved with `is_production_ready=FALSE` | Output table |
| Backfill mode | Not checked | Record saved assuming 100% | **NO VISIBILITY** |

### 2. Visibility Sources

**Where to find failures:**

1. **`nba_processing.precompute_failures`** - Skipped entities with reason
2. **Output tables** - Records with `is_production_ready=FALSE`
3. **`nba_orchestration.reprocess_attempts`** - Circuit breaker status
4. **`scripts/detect_gaps.py`** - Gap detection with cascade analysis

### 3. Backfill Mode Blindspot

When `backfill_mode=True`, completeness checks are **skipped entirely**:
- Assumes 100% completeness
- No visibility into actual data quality
- Relies on upstream preflight checks only

**Decision:** Kept this behavior because:
1. Backfill mode runs preflight checks at date level
2. Skipping saves ~4.3s per date (4 BQ queries)
3. For historical data, we trust upstream is complete
4. Adding per-entity checks would be marginal improvement (~5 min on multi-hour backfill)

### 4. Failure Categories

| Category | Meaning | Expected? | Action |
|----------|---------|-----------|--------|
| `INSUFFICIENT_DATA` | <10 games | YES (early season) | Wait for more games |
| `INCOMPLETE_DATA` | <90% completeness | Sometimes | Check Phase 3 |
| `MISSING_UPSTREAM` | No upstream data | Sometimes | Run Phase 3 backfill |
| `NO_SHOT_ZONE` | Shot zone missing | YES (PDC) | Run PSZA backfill |
| `CIRCUIT_BREAKER_ACTIVE` | Too many retries | NO | Manual investigation |
| `PROCESSING_ERROR` | Exception | NO (bug) | Debug code |

---

## Documentation Created

### Main Backfill Docs (Production Ready)

1. **`docs/02-operations/backfill/completeness-failure-guide.md`** (NEW)
   - What happens when completeness fails
   - Where to find visibility
   - Root cause diagnosis decision trees
   - Recovery procedures
   - Quick reference queries

2. **`docs/02-operations/backfill/README.md`** (UPDATED)
   - Added link to completeness-failure-guide.md in documentation index

3. **`docs/02-operations/runbooks/completeness/operational-runbook.md`** (UPDATED)
   - Added root cause quick reference section
   - Added failure category table
   - Added quick diagnosis for many entities failing

---

## Key Queries Added

### Find Records with Quality Issues

```sql
SELECT cache_date, player_lookup, l5_completeness_pct, is_production_ready
FROM nba_precompute.player_daily_cache
WHERE is_production_ready = FALSE
  AND cache_date >= '2021-11-01'
ORDER BY cache_date;
```

### Find Skipped Entities

```sql
SELECT analysis_date, entity_id, failure_category, failure_reason
FROM nba_processing.precompute_failures
WHERE processor_name = 'PlayerDailyCacheProcessor'
  AND analysis_date >= '2021-11-01'
ORDER BY analysis_date;
```

### Check Circuit Breakers

```sql
SELECT processor_name, entity_id, circuit_breaker_until
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP();
```

---

## Considered but Rejected

### Skip Completeness Checks in Backfill Mode

**Proposal:** Skip completeness checks entirely in backfill mode for all processors.

**Investigation:**
- PDC runs 4 parallel BQ queries taking ~4.3s per date
- Would save ~5 minutes on 61-date backfill
- But completeness checks catch missing upstream data
- Setting `expected_count = actual_count` masks real data gaps

**Decision:** Rejected. The ~5 min savings doesn't justify:
1. Losing visibility into actual completeness
2. Masking potential upstream data gaps
3. Making debugging harder when issues occur

---

## Related Files

- `shared/utils/completeness_checker.py` - Core completeness logic
- `data_processors/precompute/precompute_base.py` - Base processor with completeness integration
- `scripts/detect_gaps.py` - Gap detection tool
- `scripts/validate_backfill_coverage.py` - Coverage validation
