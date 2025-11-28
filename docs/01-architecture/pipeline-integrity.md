# Pipeline Integrity Architecture

**Status:** 🚧 Production-Ready, Awaiting Field Testing
**Created:** 2025-11-28
**Category:** Data Quality & Pipeline Safety
**Phase:** All phases (cross-cutting concern)

---

## Overview

Pipeline integrity provides mechanisms to ensure data completeness and prevent cascading failures across the multi-phase NBA stats pipeline. It addresses the fundamental challenge of **cross-date dependencies** in analytics pipelines.

### The Problem

In pipelines with lookback windows and auto-cascades:
```
Phase 2 (Raw):     Oct 1, 2, [FAIL], 4, 5...
                        ↓  ↓    X     ↓  ↓
Phase 3 (Analytics): Oct 1, 2,      4, 5... ← Incomplete data!
                        ↓  ↓         ↓  ↓
Phase 4 (Precompute): Bad predictions due to incomplete history
```

**Without controls:**
- Backfills cascade uncontrollably via Pub/Sub
- Daily jobs process with missing upstream data
- Gaps in historical windows go undetected
- Incomplete data propagates through all phases

---

## Solution Components

### 1. **Cascade Control**
Disable Pub/Sub auto-triggering during backfills.

```bash
# Batch load Phase 2 without triggering Phase 3
python processor.py --date 2023-10-15 --skip-downstream-trigger
```

**Use case:** Historical backfills where you want to verify Phase N complete before starting Phase N+1.

---

### 2. **Gap Detection**
Check for missing dates in continuous ranges.

```python
gaps = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=date(2023, 10, 31)
)
# Returns: has_gaps, missing_dates, coverage_pct
```

**Use case:** Verify backfill completeness before proceeding to next phase.

---

### 3. **Upstream Failure Detection**
Check if upstream processors succeeded before processing.

```python
status = checker.check_upstream_processor_status(
    processor_name='PlayerBoxscoreProcessor',
    data_date=date(2023, 10, 15)
)
# Returns: processor_succeeded, status, error_message
```

**Use case:** Daily operations - prevent Tuesday from processing if Monday's upstream failed.

---

### 4. **Defensive Checks (Strict Mode)**
Automatic guards in Phase 3+ processors that **block processing** when:
- Upstream processor failed for recent date
- Gaps detected in lookback window

```python
# Enabled by default in analytics_base.py
strict_mode = opts.get('strict_mode', True)

if strict_mode and not is_backfill_mode:
    # Check upstream status
    # Check for gaps
    # Raise DependencyError if problems found
```

**Use case:** Daily scheduled operations - fail-safe to prevent bad data propagation.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     BACKFILL MODE                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Phase 2 Batch Load (--skip-downstream-trigger)            │
│  ├─ Oct 1, 2, 3, 4, 5... (all dates)                       │
│  └─ No Pub/Sub cascade                                     │
│                                                             │
│  Gap Detection Check                                       │
│  └─ Verify 100% complete                                   │
│                                                             │
│  Phase 3 Date-by-Date (cascade enabled)                    │
│  ├─ Oct 1 → triggers Phase 4                               │
│  ├─ Oct 2 → triggers Phase 4                               │
│  └─ ...                                                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   DAILY OPERATIONS                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Phase 2: Monday's data                                    │
│  ↓ (Pub/Sub trigger)                                       │
│  Phase 3: Defensive Checks                                 │
│  ├─ ✓ Check if Sunday's Phase 2 succeeded                  │
│  ├─ ✓ Check for gaps in 15-day lookback                    │
│  └─ ✓ Block if problems detected                           │
│  ↓ (Pub/Sub trigger)                                       │
│  Phase 4: (inherits Phase 3 validation)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Status

### ✅ Implemented (Production-Ready)
- [x] Cascade control (`--skip-downstream-trigger` flag)
- [x] Gap detection (`check_date_range_completeness()`)
- [x] Upstream failure detection (`check_upstream_processor_status()`)
- [x] Defensive checks in `analytics_base.py` (strict mode)
- [x] `DependencyError` exception for clean failures
- [x] Comprehensive backfill strategy documented

### 🧪 Testing Status
- [x] Code implemented and reviewed
- [ ] Field tested with historical backfill
- [ ] Field tested with daily operations failures
- [ ] Validated alert delivery and recovery procedures

### 📊 Field Testing Plan
1. Test cascade control with small date range backfill
2. Test defensive checks by simulating upstream failure
3. Test gap detection with intentional incomplete data
4. Validate alert content and recovery runbook
5. Update architecture doc with lessons learned

---

## Key Design Decisions

### When Defensive Checks Run

**✅ Enabled (strict_mode=True, default):**
- Daily scheduled operations
- Manual CLI runs
- Production environments

**⏭️ Disabled:**
- Backfill mode (`backfill_mode=True`)
- Explicit opt-out (`strict_mode=False`)
- During initial Phase 2 batch load

### Why Phase 4 Doesn't Have Defensive Checks

Phase 4 relies on Phase 3's validation:
- Phase 3 already checked upstream status
- Phase 3 already validated gap-free data
- Phase 4 inherits this protection via cascade
- No duplicate checking needed

### Why Phase 5 Is Separate

Phase 5 (Predictions) is **forward-looking only**:
- Uses Cloud Scheduler trigger (6:15 AM ET daily)
- Queries upcoming games from Phase 3
- Not part of historical backfill workflow
- No cascade from Phase 4

---

## Usage Patterns

### Pattern 1: Historical Backfill
```bash
# 1. Batch load Phase 2 (all dates, no cascade)
for date in $(seq_dates); do
  python phase2_processor.py --date $date --skip-downstream-trigger
done

# 2. Verify completeness
python verify_phase2.py --fail-on-gaps

# 3. Process Phase 3+4 date-by-date (cascade enabled)
for date in $(seq_dates); do
  python phase3_processor.py --start-date $date --end-date $date
  # Phase 4 auto-triggers
done
```

### Pattern 2: Daily Operation with Defensive Checks
```python
# Phase 3 processor automatically:
# 1. Checks if yesterday's Phase 2 succeeded
# 2. Checks for gaps in lookback window
# 3. Raises DependencyError if problems
# 4. Sends detailed alert to ops team

# Ops team recovery:
# - Re-run failed Phase 2 date
# - Verify success
# - Manually trigger blocked Phase 3
```

### Pattern 3: Manual Gap Check
```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker(bq_client, project_id)
result = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=start,
    end_date=end
)

if result['has_gaps']:
    print(f"Missing {result['gap_count']} dates")
    print(f"Coverage: {result['coverage_pct']}%")
```

---

## Related Documentation

### Detailed Implementation Docs
📁 **Primary Location:** `docs/08-projects/current/pipeline-integrity/`

| Document | Purpose |
|----------|---------|
| [README.md](../08-projects/current/pipeline-integrity/README.md) | Project overview & status |
| [DESIGN.md](../08-projects/current/pipeline-integrity/DESIGN.md) | Technical design details |
| [BACKFILL-STRATEGY.md](../08-projects/current/pipeline-integrity/BACKFILL-STRATEGY.md) | Complete backfill guide |
| [PHASE1-IMPLEMENTATION-SUMMARY.md](../08-projects/current/pipeline-integrity/PHASE1-IMPLEMENTATION-SUMMARY.md) | Cascade control implementation |

### Related Architecture
- [Cross-Date Dependencies](./cross-date-dependencies.md) - Why this matters
- [Pipeline Design](./pipeline-design.md) - Overall pipeline architecture

---

## Code Locations

| Component | File | Line |
|-----------|------|------|
| Cascade control (Phase 2→3) | `data_processors/raw/processor_base.py` | 537 |
| Cascade control (Phase 3→4) | `data_processors/analytics/analytics_base.py` | 1394 |
| Defensive checks | `data_processors/analytics/analytics_base.py` | 255-358 |
| Gap detection | `shared/utils/completeness_checker.py` | 570 |
| Upstream status check | `shared/utils/completeness_checker.py` | 663 |
| DependencyError | `shared/utils/completeness_checker.py` | 22 |

---

## Future Enhancements

**After Field Testing:**
- [ ] Add precompute_base.py defensive checks (Phase 4)
- [ ] Automated backfill scripts (Phase 3 from original plan)
- [ ] Integration tests for defensive checks
- [ ] Metrics/dashboards for gap detection alerts
- [ ] Auto-recovery workflows (beyond manual runbooks)

**Migration Plan:**
Once field-tested and validated:
1. Update this doc with lessons learned
2. Add metrics from production usage
3. Consider moving detailed docs from `08-projects/current` to `08-projects/completed`
4. Expand to other processor types (Phase 4, custom processors)

---

## Open Questions

**Pending Field Testing:**
1. What's the false-positive rate for defensive checks?
2. Are alert details sufficient for ops team recovery?
3. Should we add auto-retry logic vs. manual recovery?
4. Do we need different thresholds for different processors?
5. Should strict_mode be configurable per-processor vs. global?

**Update this section after production experience.**

---

## Success Metrics

**Data Integrity:**
- Zero backfills with cascading failures
- Zero daily jobs processing with upstream gaps
- 100% gap detection before downstream processing

**Operations:**
- Mean time to recovery < 1 hour for blocked jobs
- Alert clarity (ops team can recover without escalation)
- No manual Pub/Sub manipulation needed for backfills

**Performance:**
- Defensive checks add < 5 seconds to processing time
- Historical backfill (4 seasons) completes in < 2 days

---

**Status:** Production-ready, awaiting field testing
**Next Review:** After first historical backfill + 2 weeks of daily operations
**Owner:** Engineering Team
**Created:** 2025-11-28
