# Backfill Documentation Hub

**File:** `docs/02-operations/backfill/README.md`
**Created:** 2025-12-08 11:45 AM PST
**Last Updated:** 2025-12-08 11:45 AM PST
**Purpose:** Navigation hub for all backfill-related documentation
**Status:** Current

---

## Quick Start

**Planning a backfill?** Start with [backfill-guide.md](./backfill-guide.md)

**Investigating data issues?** See [data-gap-prevention-and-recovery.md](./data-gap-prevention-and-recovery.md)

**Running Phase 4?** Use [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md)

---

## Documentation Index

### Core Guides

| Document | Purpose | When to Use |
|----------|---------|-------------|
| [backfill-guide.md](./backfill-guide.md) | Comprehensive backfill procedures | Planning any backfill operation |
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

## Key Concepts

### Backfill Mode vs Daily Mode

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| Dependency checks | Full validation (60s+) | Quick existence check (1-2s) |
| Completeness checks | Full per-entity | Skipped |
| Error handling | Detailed tracking | Aggregate logging |
| Performance | Prioritizes accuracy | Prioritizes throughput |

### Phase Sequencing (Critical!)

**ALWAYS run phase-by-phase, NOT date-by-date:**

```
Phase 3 (all dates) → Phase 4 (all dates) → Phase 5 (all dates)
```

**Phase 4 internal order:**
```
TDZA + PSZA (parallel) → PCF → PDC → MLFS
```

### Data Integrity

- **Cascade contamination**: Upstream NULL/zero values propagate downstream
- **Prevention**: Lightweight existence checks even in backfill mode
- **Detection**: Critical field validation queries
- **Recovery**: Always fix upstream first, then reprocess downstream in order

---

## Common Commands

```bash
# Validate backfill coverage
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --details

# Pre-flight check for Phase 4
.venv/bin/python bin/backfill/verify_phase3_for_phase4.py \
    --start-date 2021-11-01 --end-date 2021-12-31

# Run Phase 4 backfill
./bin/backfill/run_phase4_backfill.sh \
    --start-date 2021-11-01 --end-date 2021-12-31

# Check for cascade contamination
.venv/bin/python scripts/validate_cascade_contamination.py \
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

---

## Related Documentation

- **Project tracking:** `docs/08-projects/current/backfill/` (27+ files)
- **Session handoffs:** `docs/09-handoff/` (lessons learned)
- **Scripts:** `bin/backfill/` (execution scripts)
- **Validation:** `scripts/validate_*.py` (validation tools)
