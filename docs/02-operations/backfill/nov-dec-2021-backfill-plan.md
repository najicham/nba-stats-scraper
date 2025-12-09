# November-December 2021 Cascade Backfill Plan

## Executive Summary

**Goal:** Complete Phase 4 backfill for Nov-Dec 2021 with comprehensive failure handling and validation.

**Current State (from gap detection):**
| Phase | Nov 2021 Status | Dec 2021 Status |
|-------|-----------------|-----------------|
| Phase 2 (Raw) | 100% coverage (29 dates) | 100% coverage |
| Phase 3 (Analytics) | 100% coverage (29 dates) | 100% coverage |
| Phase 4 (Precompute) | Gaps in early days (Nov 1-4) | Some gaps |
| Phase 5 (ML) | Almost all missing | Gaps |

---

## Understanding Early Season Expectations

### 2021-22 Season Timeline
- **Season Start:** October 19, 2021
- **November 1:** Day 13 of season
- **November 4:** Day 16 of season
- **Bootstrap Period:** Days 0-14 (high failure rate expected)

### Expected Failure Rates by Week

| Week | Dates | Expected Success Rate | Reason |
|------|-------|----------------------|--------|
| Week 1-2 | Oct 19 - Nov 1 | 10-25% | Bootstrap - insufficient games |
| Week 3 | Nov 2 - Nov 8 | 40-60% | Some players have 5+ games |
| Week 4+ | Nov 9+ | 75-90% | Most players have sufficient data |
| Month 2+ | Dec 1+ | 90-95% | Steady state |

### Failure Categories to Expect

| Category | Meaning | Retryable | Action |
|----------|---------|-----------|--------|
| `EXPECTED_INCOMPLETE` | Player < 5 games | No | Auto-resolves as games accumulate |
| `INSUFFICIENT_DATA` | Legacy: not enough history | No | Expected early season |
| `NO_SHOT_ZONE` | Player has no shots in PBP | No | Normal for bench players |
| `INCOMPLETE_UPSTREAM` | Upstream gap | Yes | Fix upstream first |
| `PROCESSING_ERROR` | Actual bug | Yes | Investigate |

---

## Cascade Backfill Strategy

### Phase Dependency Order

```
                    Phase 3                          Phase 4                    Phase 5
               (Already Complete)                 (Backfill Now)              (After P4)
                      │                                │                          │
     ┌────────────────┼────────────────┐              │                          │
     │                │                │              │                          │
     ▼                ▼                ▼              ▼                          ▼
   PGS             TDGS             TOGS           TDZA ──┐                      │
     │                │                │              │    │                      │
     │                │                │              │    ├──► PCF ──► PDC ──► MLFS
     │                │                │              │    │           │
     └────────────────┼────────────────┘         PSZA ──┘           │
                      │                                              │
                      └──────────────────────────────────────────────┘
```

### Backfill Order (Critical!)

1. **TDZA + PSZA** (parallel) - No dependencies on each other
2. **PCF** - Depends on TDZA
3. **PDC** - Depends on PSZA, PCF
4. **MLFS** - Depends on all above

---

## Execution Plan

### Step 1: Pre-Flight Validation

```bash
# Verify Phase 3 is complete for Nov-Dec 2021
python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31 --phase 3

# Expected output: "OK: Full coverage" for all Phase 3 tables
```

### Step 2: Run Phase 4 Backfill (TDZA + PSZA in Parallel)

```bash
# Terminal 1: TDZA backfill
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 2>&1 | tee /tmp/tdza_nov_dec_2021.log &

# Terminal 2: PSZA backfill
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 2>&1 | tee /tmp/psza_nov_dec_2021.log &
```

### Step 3: Validate TDZA + PSZA

```bash
# Check for gaps
python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31 --phase 4

# Check for contamination (NULL values in critical fields)
python scripts/validate_cascade_contamination.py --start-date 2021-11-01 --end-date 2021-12-31

# Check failure tracking
python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-12-31 --reconcile
```

### Step 4: Run PCF (After TDZA Complete)

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 2>&1 | tee /tmp/pcf_nov_dec_2021.log
```

### Step 5: Run PDC (After PSZA + PCF Complete)

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 2>&1 | tee /tmp/pdc_nov_dec_2021.log
```

### Step 6: Final Validation

```bash
# Full gap detection
python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31

# Contamination check with strict mode
python scripts/validate_cascade_contamination.py --start-date 2021-11-01 --end-date 2021-12-31 --strict

# Coverage reconciliation
python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-12-31 --reconcile
```

---

## Failure Handling & Recovery

### Recovery Decision Tree

```
Gap Detected in Phase 4
        │
        ▼
Is it early season (Nov 1-4)?
        │
   YES  │  NO
        │   │
        ▼   ▼
Expected  Check upstream
failure   Phase 3 data
(accept)       │
               ▼
          Has upstream?
               │
          YES  │  NO
               │   │
               ▼   ▼
          Re-run   Backfill
          Phase 4  Phase 3
                   first
```

### When to Retry vs Accept Failure

**Accept (Don't Retry):**
- `EXPECTED_INCOMPLETE` during weeks 1-2
- `INSUFFICIENT_DATA` during weeks 1-3
- `NO_SHOT_ZONE` for players with 0 FGA
- Success rate < 30% on Nov 1-4

**Retry:**
- `INCOMPLETE_UPSTREAM` after fixing upstream
- `PROCESSING_ERROR` (investigate first)
- Success rate < 70% on Nov 15+
- Any contamination detected

### Retry Commands

```bash
# Retry specific failed dates
python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
    --dates 2021-11-05,2021-11-06

# Force re-run (ignore checkpoint)
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-11-30 --no-resume
```

---

## Validation Checklist

### After Each Processor

- [ ] Check log for error count: `grep -c "ERROR\|FAILED" /tmp/[processor]_nov_dec_2021.log`
- [ ] Run gap detection: `python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31 --phase 4`
- [ ] Check failure tracking: `bq query 'SELECT failure_category, COUNT(*) FROM nba_processing.precompute_failures WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31" GROUP BY 1'`

### Final Validation

- [ ] All Phase 4 tables have data for Nov 5+ dates
- [ ] Contamination check passes (or shows expected early-season NULLs)
- [ ] Failure tracking accounts for all missing records
- [ ] No `UNTRACKED` status in coverage validation

---

## Expected Outcomes

### Success Metrics

| Metric | Nov 1-4 | Nov 5-30 | Dec 1-31 |
|--------|---------|----------|----------|
| TDZA record count | ~100 | ~870 | ~960 |
| PSZA record count | ~1000 | ~6000 | ~6500 |
| PCF record count | ~800 | ~5500 | ~6000 |
| PDC record count | ~800 | ~5500 | ~6000 |
| Expected failures | 70-90% | 20-40% | 5-15% |

### Acceptable Failure Rates

| Period | Max Acceptable Failure Rate | Action if Exceeded |
|--------|----------------------------|-------------------|
| Nov 1-4 | 90% | Expected, document |
| Nov 5-14 | 50% | Investigate upstream |
| Nov 15-30 | 25% | Investigate root cause |
| Dec 1-31 | 15% | Investigate + fix |

---

## Troubleshooting

### "Too many failures on Nov 5+"

1. Check Phase 3 data exists: `python scripts/detect_gaps.py --phase 3`
2. Check for contamination: `python scripts/validate_cascade_contamination.py`
3. Look at failure categories in precompute_failures table
4. If `INCOMPLETE_UPSTREAM`, fix Phase 3 first

### "Checkpoint says complete but gaps exist"

1. Clear checkpoint: `rm /tmp/backfill_checkpoints/[job]_*.json`
2. Re-run with `--no-resume`

### "Contamination detected"

1. Identify contaminated dates from validation output
2. Re-run upstream processor for those dates
3. Re-run downstream processors in order
4. Re-validate

---

## Quick Reference Commands

```bash
# Full pipeline for Nov-Dec 2021
./bin/backfill/run_phase4_backfill.sh 2021-11-01 2021-12-31

# Check progress
tail -f /tmp/*_nov_dec_2021.log

# Quick gap check
python scripts/detect_gaps.py --start-date 2021-11-01 --end-date 2021-12-31 --phase 4

# Reconcile failures
python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-12-31 --reconcile
```

---

**Created:** 2025-12-08
**Author:** Claude Code Session 82
