# Backfill Documentation Hub

**Last Updated:** 2025-12-08 | **Status:** Current

---

## Contents

1. [Current Backfill Strategy](#current-backfill-strategy) - Test small, validate, iterate
2. [Quick Start](#quick-start) - Links to guides
3. [Documentation Index](#documentation-index) - All backfill docs
4. [Validation Workflow](#validation-workflow) - Pre/during/post validation
5. [Gap Types & Failure Categories](#gap-types--failure-categories) - Understanding failures
6. [Backfill Mode vs Daily Orchestration](#backfill-mode-vs-daily-orchestration) - Key differences
7. [Key Concepts](#key-concepts) - Phase sequencing, abbreviations
8. [Common Commands](#common-commands) - Copy-paste reference
9. [Performance Expectations](#performance-expectations-phase-4) - Timing benchmarks
10. [Troubleshooting](#troubleshooting) - Fixing gaps, common issues

---

## Current Backfill Strategy

Our approach is **test small, validate, iterate**:

1. **Test on 1-3 dates first** - Run a processor on a single date or small range
2. **Validate efficiency** - Check it runs in expected time, no excessive queries
3. **Check for errors** - Use preflight scripts, validation scripts, error tables
4. **Verify no data loss** - Ensure all expected records are created
5. **Iterate and optimize** - Fix issues, optimize queries, improve observability
6. **Scale up carefully** - Only run larger batches after small tests pass

### Error Detection Tools

```bash
# Pre-flight check before any backfill
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2021-11-15 --end-date 2021-11-15 --verbose

# Check name registry errors
bq query --use_legacy_sql=false '
SELECT * FROM nba_reference.registry_errors
WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
ORDER BY created_at DESC LIMIT 20'

# Check processor failures
bq query --use_legacy_sql=false '
SELECT processor_name, data_date, status, error_message
FROM nba_reference.processor_run_history
WHERE status = "failed" AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
ORDER BY started_at DESC'

# Post-run validation
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-15 --end-date 2021-11-15 --details
```

---

## Quick Start

**First time running a backfill?** Start with [quick-start.md](./quick-start.md)

**Planning a larger backfill?** See [backfill-guide.md](./backfill-guide.md)

**Understanding backfill mode?** See [backfill-mode-reference.md](./backfill-mode-reference.md)

**Investigating data issues?** See [data-integrity-guide.md](./data-integrity-guide.md)

**Running Phase 4?** Use [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md)

---

## Documentation Index

### Core Guides

| Document | Purpose | When to Use |
|----------|---------|-------------|
| [quick-start.md](./quick-start.md) | Run your first backfill in 10 minutes | New to backfills |
| [backfill-guide.md](./backfill-guide.md) | Comprehensive backfill procedures | Planning any backfill operation |
| [backfill-mode-reference.md](./backfill-mode-reference.md) | All backfill mode behaviors (13 optimizations) | Understanding what changes in backfill mode |
| [backfill-validation-checklist.md](./backfill-validation-checklist.md) | **Comprehensive validation checklist** | After running any backfill - 7-part validation |
| [completeness-failure-guide.md](./completeness-failure-guide.md) | Completeness failures, visibility, diagnosis, recovery | When entities fail completeness checks |
| [data-integrity-guide.md](./data-integrity-guide.md) | Gap detection, prevention, cascade contamination, recovery | Investigating missing/bad data |
| [phase4-performance-analysis.md](./phase4-performance-analysis.md) | Performance benchmarks, optimization details | Tuning backfill performance |

### Runbooks

| Document | Purpose |
|----------|---------|
| [runbooks/phase4-precompute-backfill.md](./runbooks/phase4-precompute-backfill.md) | Step-by-step Phase 4 backfill execution |
| [runbooks/phase4-dependencies.md](./runbooks/phase4-dependencies.md) | Phase 4 dependency chain, issue categories |
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

### Enhanced Failure Tracking (New)

We now track additional failure metadata to distinguish correctable vs permanent failures:

| Field | Description |
|-------|-------------|
| `failure_type` | 'PLAYER_DNP', 'DATA_GAP', 'PROCESSING_ERROR', 'UNKNOWN' |
| `is_correctable` | TRUE = can be fixed by re-ingesting data |
| `expected_game_count` | Games expected from schedule |
| `actual_game_count` | Games actually found |
| `missing_game_dates` | JSON array of missing dates |
| `resolution_status` | 'UNRESOLVED', 'RESOLVED', 'PERMANENT' |

**Failure Tables by Phase:**
- Phase 3 (Analytics): `nba_processing.analytics_failures`
- Phase 4 (Precompute): `nba_processing.precompute_failures`
- Phase 5 (Predictions): `nba_processing.prediction_failures`

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

## Backfill Mode vs Daily Orchestration

Understanding the difference is critical - daily mode has safeguards that backfill mode skips for performance.

### What Daily Orchestration Does (Extra Checks)

Daily orchestration runs automatically via Cloud Scheduler and includes these safeguards:

| Check | What It Does | Time Cost | Why It Matters |
|-------|--------------|-----------|----------------|
| **Full dependency validation** | Queries BQ to verify all upstream tables have fresh data for the date | 60-120s | Prevents processing with stale/missing upstream |
| **Completeness per entity** | For each player, checks L5/L10/L7d/L14d windows are complete | 600s+ | Ensures rolling averages are accurate |
| **Freshness validation** | Checks upstream data was processed within expected window | 10-30s | Catches stuck pipelines |
| **Downstream auto-trigger** | Publishes Pub/Sub message to trigger next phase | N/A | Maintains pipeline flow |
| **Alert on failure** | Sends Slack/email alerts for failures | N/A | Ensures visibility |
| **Circuit breaker** | Tracks retry counts, stops runaway retries | 2-3s/entity | Prevents resource waste |

### What Backfill Mode Skips

Backfill mode (`backfill_mode=True`) is aggressive for throughput:

```
Daily:    Full validation → Process → Full validation → Alert → Trigger downstream
Backfill: Quick check → Process → Done (no alerts, no triggers)
```

**Key implication:** In backfill mode, YOU are responsible for validation. The system trusts you.

### When to Use Which

| Scenario | Mode | Why |
|----------|------|-----|
| Today's data | Daily | Need full validation, alerts |
| Yesterday's data (catch-up) | Daily | Still recent, alerts useful |
| Historical (>7 days old) | Backfill | Performance matters, you'll validate manually |
| Re-processing after fix | Backfill | Data already validated once |
| Testing/development | Backfill | Don't want alerts |

**Full technical details:** [backfill-mode-reference.md](./backfill-mode-reference.md)

---

## Key Concepts

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

## Troubleshooting

### Quick Reference

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| High failure rate (>50%) | Early season | Expected - check season week |
| PROCESSING_ERROR failures | Code bug | Debug, fix code, re-run |
| opponent_strength_score = 0 | Cascade contamination | Fix TDZA, reprocess PCF |
| Slow performance | Backfill mode not active | Verify `backfill_mode=True` |
| Missing dates | Batch boundary gap | Run missing dates explicitly |

### Dealing with Gaps

#### Step 1: Identify the Gap

```bash
# Find missing dates in Phase 4
bq query --use_legacy_sql=false '
WITH expected AS (
  SELECT date FROM UNNEST(GENERATE_DATE_ARRAY("2021-11-01", "2021-12-31")) AS date
),
actual AS (
  SELECT DISTINCT game_date FROM nba_precompute.player_composite_factors
  WHERE game_date BETWEEN "2021-11-01" AND "2021-12-31"
)
SELECT e.date as missing_date
FROM expected e
LEFT JOIN actual a ON e.date = a.game_date
WHERE a.game_date IS NULL
ORDER BY 1'

# Or use validation script
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-11-01 --end-date 2021-12-31 --show-gaps
```

#### Step 2: Determine Gap Type

| Gap Type | How to Identify | Root Cause |
|----------|-----------------|------------|
| **Missing entirely** | Date not in table at all | Backfill never ran |
| **Partial records** | Date exists but fewer records than expected | Some players failed |
| **Cascade contamination** | Records exist but critical fields are NULL/0 | Upstream gap propagated |

```bash
# Check if it's cascade contamination
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-12-04 --end-date 2021-12-04
```

#### Step 3: Fix the Gap

**For missing dates (never ran):**
```bash
# Just run the backfill for missing dates
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04
```

**For cascade contamination (upstream issue):**
```bash
# 1. Find the upstream source of the problem
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total,
       COUNTIF(opp_paint_attempts > 0) as valid
FROM nba_analytics.team_defense_game_summary
WHERE game_date = "2021-12-04"
GROUP BY 1'

# 2. Fix upstream FIRST (example: TDZA)
.venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04

# 3. Then reprocess downstream in order
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04
```

**For partial records (some players failed):**
```bash
# Check which players failed
bq query --use_legacy_sql=false '
SELECT player_id, failure_reason, COUNT(*) as failures
FROM nba_precompute.precompute_failures
WHERE data_date = "2021-12-04"
  AND processor_name = "player_composite_factors"
GROUP BY 1, 2
ORDER BY 3 DESC'

# Re-run the backfill (will retry failed players)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04
```

#### Step 4: Validate the Fix

```bash
# Confirm gap is fixed
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --details

# Confirm no cascade contamination
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --strict
```

### Common Gap Scenarios

| Scenario | Cause | Fix |
|----------|-------|-----|
| Gap at batch boundary | Backfill stopped mid-range | Re-run for missing dates |
| All zeros in opponent_strength | TDZA missing for that date | Fix TDZA → reprocess PCF |
| Low player count (~50 vs ~300) | Early season bootstrap | Expected, not a bug |
| Random scattered gaps | Transient failures | Re-run those specific dates |

---

## Related Documentation

- **Scripts:** `bin/backfill/` - Preflight, verification, backfill execution
- **Validation:** `scripts/validate_*.py` - Coverage and quality checks
- **Error tables:** `nba_reference.processor_run_history`, `nba_reference.registry_errors`
- **Archived project docs:** `docs/08-projects/completed/backfill-2025-11-to-12/` - Historical reference
- **Session handoffs:** `docs/09-handoff/` - Session-by-session notes
