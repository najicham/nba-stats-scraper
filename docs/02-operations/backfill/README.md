# Backfill Documentation Hub

**File:** `docs/02-operations/backfill/README.md`
**Created:** 2025-12-08 11:45 AM PST
**Last Updated:** 2025-12-08 12:45 PM PST
**Purpose:** Navigation hub for all backfill-related documentation
**Status:** Current

---

## Quick Start

**Planning a backfill?** Start with [backfill-guide.md](./backfill-guide.md)

**Understanding backfill mode?** See [backfill-mode-reference.md](./backfill-mode-reference.md)

**Investigating data issues?** See [data-gap-prevention-and-recovery.md](./data-gap-prevention-and-recovery.md)

**Running Phase 4?** Use [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md)

---

## Documentation Index

### Core Guides

| Document | Purpose | When to Use |
|----------|---------|-------------|
| [backfill-guide.md](./backfill-guide.md) | Comprehensive backfill procedures | Planning any backfill operation |
| [backfill-mode-reference.md](./backfill-mode-reference.md) | All backfill mode behaviors (13 optimizations) | Understanding what changes in backfill mode |
| [data-gap-prevention-and-recovery.md](./data-gap-prevention-and-recovery.md) | Gap detection, prevention, recovery | Investigating missing/bad data |
| [cascade-contamination-prevention.md](./cascade-contamination-prevention.md) | Cascade detection, 3-layer defense | Preventing upstream gaps from propagating |
| [PHASE4-PERFORMANCE-ANALYSIS.md](./PHASE4-PERFORMANCE-ANALYSIS.md) | Performance benchmarks, optimization details | Tuning backfill performance |

### Runbooks

| Document | Purpose |
|----------|---------|
| [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md) | Step-by-step Phase 4 backfill execution |
| [runbooks/phase4-data-integrity-guide.md](./runbooks/phase4-data-integrity-guide.md) | Phase 4 dependency chain, issue categories |
| [runbooks/name-resolution.md](./runbooks/name-resolution.md) | Player name resolution backfill |
| [runbooks/nbac-team-boxscore.md](./runbooks/nbac-team-boxscore.md) | NBAC team boxscore backfill |

---

## Validation Workflow

### Pre-Backfill Validation

```bash
# 1. Check upstream data exists
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# 2. Verify Phase 3 ready for Phase 4
.venv/bin/python bin/backfill/verify_phase3_for_phase4.py \
    --start-date 2021-11-01 --end-date 2021-12-31
```

### During Backfill

```bash
# Monitor progress (check logs or query)
bq query --use_legacy_sql=false '
SELECT processor_name, COUNT(*) as records
FROM nba_reference.processor_run_history
WHERE run_date >= "2021-11-01"
GROUP BY 1'
```

### Post-Backfill Validation

```bash
# 3. Check coverage and failures
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --details --reconcile

# 4. Check data quality (cascade contamination)
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --strict

# 5. Final verification
.venv/bin/python bin/backfill/verify_backfill_range.py \
    --start-date 2021-11-01 --end-date 2021-12-31
```

### Validation Tools Reference

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `bin/backfill/preflight_check.py` | Check GCS/BQ data availability | `--phase`, `--verbose` |
| `bin/backfill/verify_phase3_for_phase4.py` | Verify Phase 3 completeness | `--verbose` |
| `bin/backfill/verify_backfill_range.py` | Full phase 3-4 verification | `--verbose` |
| `scripts/validate_backfill_coverage.py` | Player-level coverage check | `--details`, `--reconcile`, `--processor` |
| `scripts/validate_cascade_contamination.py` | Critical field validation | `--strict`, `--stage`, `--show-dates` |

---

## Gap Types & Failure Categories

### Data Gap Types

| Gap Type | Description | Detection | Severity |
|----------|-------------|-----------|----------|
| **Missing Date** | Entire date missing from table | Date diff query | HIGH |
| **Partial Data** | Fewer records than expected | COUNT comparison | MEDIUM |
| **NULL Field** | Critical fields are NULL | NULL count query | HIGH |
| **Zero-Value** | Fields have 0 instead of calculated value | Zero detection | MEDIUM |
| **Cascade** | Upstream gap propagates downstream | Cascade query | CRITICAL |

### Failure Categories (Phase 4)

| Category | Meaning | Action | Expected? |
|----------|---------|--------|-----------|
| `INSUFFICIENT_DATA` | Player has <10 games | Wait for more games | Yes (early season) |
| `INCOMPLETE_DATA` | Upstream windows incomplete | Reprocess Phase 3 | Sometimes |
| `MISSING_DEPENDENCY` | No upstream data | Check upstream processor | Sometimes |
| `NO_SHOT_ZONE` | Shot zone data missing | Wait for PSZA | Yes (PDC) |
| `CIRCUIT_BREAKER_ACTIVE` | Too many retries | Manual investigation | No |
| `PROCESSING_ERROR` | Unhandled exception | Debug code | No (bug!) |

### Expected Failure Rates by Season Week

| Season Week | Days | Expected Failure % |
|-------------|------|-------------------|
| Week 1-2 | 1-14 | 90-100% |
| Week 3 | 15-21 | 60-75% |
| Week 4 | 22-28 | 40-50% |
| Week 5+ | 29+ | 25-30% |
| Mid-season | 60+ | 15-20% |

**Key insight:** High failure rates in early season are **expected**, not bugs. Only `PROCESSING_ERROR` indicates an actual code bug.

---

## Key Concepts

### Backfill Mode vs Daily Mode

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Dependency checks | Full validation (60s+) | Quick existence check (1-2s) |
| Completeness checks | Full per-entity (600s) | Skipped |
| Notifications | Alerts sent | Suppressed |
| Thresholds | Strict (100 players) | Relaxed (20 players) |
| Downstream trigger | Auto-triggers next phase | Suppressed |
| Performance | Prioritizes accuracy | Prioritizes throughput |

**Full details:** [backfill-mode-reference.md](./backfill-mode-reference.md)

### Phase Sequencing (Critical!)

**ALWAYS run phase-by-phase, NOT date-by-date:**

```
Phase 2 (all dates) → Phase 3 (all dates) → Phase 4 (all dates) → Phase 5 (all dates)
```

**Phase 4 internal order:**
```
TDZA + PSZA (parallel) → PCF → PDC → MLFS
```

### Processor Abbreviations

| Abbrev | Full Name | Table |
|--------|-----------|-------|
| TDZA | Team Defense Zone Analysis | `nba_precompute.team_defense_zone_analysis` |
| PSZA | Player Shot Zone Analysis | `nba_precompute.player_shot_zone_analysis` |
| PCF | Player Composite Factors | `nba_precompute.player_composite_factors` |
| PDC | Player Daily Cache | `nba_precompute.player_daily_cache` |
| MLFS | ML Feature Store | `nba_predictions.ml_feature_store_v2` |

### Data Integrity

- **Cascade contamination**: Upstream NULL/zero values propagate downstream
- **Prevention**: Lightweight existence checks even in backfill mode
- **Detection**: Critical field validation queries
- **Recovery**: Always fix upstream first, then reprocess downstream in order

---

## Common Commands

```bash
# === Pre-flight ===
# Check all phases
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# Verify Phase 3 ready for Phase 4
.venv/bin/python bin/backfill/verify_phase3_for_phase4.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# === Run Backfill ===
# Phase 4 full backfill
./bin/backfill/run_phase4_backfill.sh \
    --start-date 2021-11-01 --end-date 2021-12-31

# Single processor
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# === Validation ===
# Coverage check
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --details

# Quality check (cascade contamination)
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --strict

# Final verification
.venv/bin/python bin/backfill/verify_backfill_range.py \
    --start-date 2021-11-01 --end-date 2021-12-31
```

---

## Performance Expectations (Phase 4)

| Processor | Optimized Time/Date | Notes |
|-----------|---------------------|-------|
| TDZA | ~30s | Fastest (30 teams only) |
| PSZA | ~75s | Shot zone analysis |
| PCF | ~50s | Composite factors |
| PDC | ~65s | Player daily cache |
| MLFS | ~65s | ML feature store |

**Full Phase 4 backfill (30 dates):** ~90-120 minutes

### Performance Optimizations Active

| Optimization | Speedup | Activated By |
|--------------|---------|--------------|
| Dependency check skip | 100x | `backfill_mode=True` |
| Completeness check skip | 10-20x | `backfill_mode=True` |
| Circuit breaker skip | N/A | `backfill_mode=True` |
| Notification suppression | N/A | `backfill_mode=True` |
| Threshold relaxation | N/A | `backfill_mode=True` |

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| High failure rate (>50%) | Early season | Expected - check season week |
| PROCESSING_ERROR failures | Code bug | Debug, fix code, re-run |
| opponent_strength_score = 0 | Cascade contamination | Fix TDZA, reprocess PCF |
| Slow performance | Backfill mode not active | Verify `backfill_mode=True` |
| Missing dates | Batch boundary gap | Run missing dates explicitly |

---

## Related Documentation

- **Project tracking:** `docs/08-projects/current/backfill/` (27+ files)
- **Session handoffs:** `docs/09-handoff/` (lessons learned from sessions 62-76)
- **Scripts:** `bin/backfill/` (execution scripts)
- **Validation:** `scripts/validate_*.py` (validation tools)
