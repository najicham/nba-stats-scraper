# Pipeline Integrity Project

**Status:** 🚧 Phases 1-2 Complete, Ready for Production
**Created:** 2025-11-27
**Last Updated:** 2025-11-28
**Priority:** HIGH - Critical for Data Integrity

---

## 🎯 Problem Statement

**Core Issue:** Processors can run with incomplete historical data when upstream processors fail or have gaps in date ranges.

**Affects:**
- ✅ **Backfill operations** (primary focus)
  - Multi-day backfills where date X fails but date X+1 continues
  - Cascading bad data through phases
- ✅ **Daily scheduled operations** (secondary benefit)
  - Monday scraper fails, Tuesday processor uses incomplete data
  - Gap in historical data goes undetected

**Impact:** Data integrity issues, incorrect predictions, difficult debugging

---

## 🔍 Specific Scenarios

### Scenario 1: Backfill Cascade Failure
```
Phase 1: Oct 1-2, ❌ 3 (FAILS), 4-5 (continue)
           ↓                    ↓
Phase 2: Oct 1-2,              4-5
           ↓                    ↓
Phase 3: Oct 1-2,              4 (uses incomplete data!) ❌
```

**Problem:** Date 4 processes without date 3 historical data

### Scenario 2: Daily Operation Gap
```
Monday (Oct 15):   Scraper fails ❌
Tuesday (Oct 16):  Scheduled job runs
                   Phase 4 needs last 10 games
                   Oct 15 is missing!
                   Phase 4 runs with incomplete data ❌
```

**Problem:** Daily job doesn't detect gap in historical data

### Scenario 3: Uncontrolled Cascade
```
Phase 1 backfill → Auto-triggers Phase 2 → Auto-triggers Phase 3
                   (via Pub/Sub)    (via Pub/Sub)

Can't verify Phase 1 complete before Phase 2 starts! ❌
```

**Problem:** No way to disable auto-cascade during backfills

---

## ✅ Proposed Solutions

### 1. **Gap Detection** (Universal) ✅ IMPLEMENTED
Detect missing dates in continuous historical ranges.

**Use Cases:**
- Backfill: Check Phase 2 complete before Phase 3 starts
- Daily: Detect if yesterday's data is missing

**Status:** ✅ **COMPLETE** - Implemented 2025-11-28
**Implementation:**
- Added `check_date_range_completeness()` method to CompletenessChecker
- Returns gap analysis with missing dates and coverage percentage

**Usage:**
```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker(bq_client, 'nba-props-platform')
result = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=date(2023, 10, 31)
)

if result['has_gaps']:
    print(f"Missing {result['gap_count']} dates: {result['missing_dates']}")
```

### 2. **Upstream Failure Detection** (Universal) ✅ IMPLEMENTED
Check if upstream processor failed before processing.

**Use Cases:**
- Backfill: Date 6 checks if date 5 failed
- Daily: Oct 16 checks if Oct 15 failed

**Status:** ✅ **COMPLETE** - Implemented 2025-11-28
**Implementation:**
- Added `check_upstream_processor_status()` method to CompletenessChecker
- Queries processor_run_history table for failure detection
- Returns status, error messages, and run_id

**Usage:**
```python
result = checker.check_upstream_processor_status(
    processor_name='PlayerBoxscoreProcessor',
    data_date=date(2023, 10, 15)
)

if not result['safe_to_process']:
    raise Exception(f"Upstream failed: {result['error_message']}")
```

### 3. **Cascade Control** (Backfill-Specific) ✅ IMPLEMENTED
Disable Pub/Sub triggers during backfills.

**Use Cases:**
- Backfill: `--skip-downstream-trigger` flag
- Daily: Not needed (want auto-cascade)

**Status:** ✅ **COMPLETE** - Implemented 2025-11-28
**Implementation:**
- Updated `ProcessorBase._publish_completion_event()` (Phase 2 → 3)
- Updated `AnalyticsProcessorBase.post_process()` (Phase 3 → 4)
- Added `--skip-downstream-trigger` CLI flag to 8 processors (3 Phase 2, 5 Phase 3)

**Usage:**
```bash
# Disable Phase 2 → Phase 3 cascade
python nbac_player_boxscore_processor.py --file path.json --skip-downstream-trigger

# Disable Phase 3 → Phase 4 cascade
python player_game_summary_processor.py --start-date 2023-10-01 --end-date 2023-10-31 --skip-downstream-trigger
```

### 4. **Error Policies** (Backfill-Specific)
Configurable error handling in backfill scripts.

**Use Cases:**
- Backfill: Stop/continue/skip-deps policies
- Daily: Always stop on error

**Status:** 🎯 Design complete, needs implementation

---

## 📚 Documents

| Document | Purpose | Status |
|----------|---------|--------|
| **[DESIGN.md](./DESIGN.md)** | Complete design document with all solutions | ✅ Complete |
| **[BACKFILL-STRATEGY.md](./BACKFILL-STRATEGY.md)** | Historical backfill & daily operations strategy | ✅ Complete |
| **[PHASE1-IMPLEMENTATION-SUMMARY.md](./PHASE1-IMPLEMENTATION-SUMMARY.md)** | Phase 1 (Cascade Control) implementation | ✅ Complete |
| **IMPLEMENTATION-PLAN.md** | Implementation checklist and priorities | ✅ Complete (phases 1-2) |
| **TESTING-GUIDE.md** | How to test each feature | ⏳ TODO |
| **OPERATIONS-GUIDE.md** | User guide for ops team | ⏳ TODO |

---

## 🗓️ Implementation Phases

### Phase 1: Cascade Control ✅ COMPLETE

**Completed Features:**
- [x] Cascade control (`--skip-downstream-trigger`) - **DONE 2025-11-28**
  - Base classes updated (ProcessorBase, AnalyticsProcessorBase)
  - 8 processors updated with CLI flag support
  - Ready for use in backfills

**Actual Effort:** ~5 hours (faster than estimated)

### Phase 2: Completeness Enhancements ✅ COMPLETE

**Completed Features:**
- [x] Gap detection (`check_date_range_completeness()`) - **DONE 2025-11-28**
- [x] Upstream failure detection (`check_upstream_processor_status()`) - **DONE 2025-11-28**
- [x] Strict mode (`fail_on_incomplete` parameter) - **DONE 2025-11-28**
- [x] DependencyError exception class - **DONE 2025-11-28**

**Implementation:**
- All methods added to `shared/utils/completeness_checker.py`
- Ready for use in processors
- Backward compatible (all parameters optional)

**Actual Effort:** ~3 hours (much faster than estimated)

### Phase 3: Backfill Tooling (Priority 3)

**Future Focus:**
- [ ] Backfill scripts with cascade control
- [ ] Verification helpers
- [ ] Error policies in scripts

**Estimated Effort:** ~8-10 hours

---

## 💡 Features Ready to Use

### 🎯 **NEW:** [Backfill Strategy Guide](./BACKFILL-STRATEGY.md)

Complete guide for:
- ✅ Historical backfill (4 seasons)
- ✅ Daily operations & failure recovery
- ✅ Defensive checks configuration
- ✅ Phase-by-phase details

**[→ Read the Backfill Strategy](./BACKFILL-STRATEGY.md)**

---

### 1. Cascade Control ✅ AVAILABLE NOW
```bash
# Use --skip-downstream-trigger flag during backfills
python nbac_player_boxscore_processor.py --file path.json --skip-downstream-trigger
python player_game_summary_processor.py --start-date 2023-10-01 --end-date 2023-10-31 --skip-downstream-trigger
```

**Benefits:**
- No more manual Pub/Sub manipulation
- Clean, explicit control
- Works per-processor run

### 2. Stop-on-Error Pattern (Manual)
```bash
set -e  # Exit on any error
for date in dates; do
    python processor.py --game-date $date --skip-downstream-trigger || exit 1
done
```

### 3. Manual Gap Detection (Until Phase 2 complete)
```sql
WITH expected AS (
    SELECT date FROM UNNEST(GENERATE_DATE_ARRAY(@start, @end))
),
actual AS (
    SELECT DISTINCT game_date FROM your_table
)
SELECT e.date as missing_date
FROM expected e
LEFT JOIN actual a ON e.date = a.date
WHERE a.date IS NULL;
```

---

## 🎯 Success Metrics

**Data Integrity:**
- ✅ Zero backfills with cascading failures
- ✅ Zero daily jobs processing with gaps
- ✅ All gaps detected before downstream processing

**Operations:**
- ✅ Backfill scripts have configurable error handling
- ✅ Operators can control Pub/Sub cascades
- ✅ Clear visibility into data completeness

**Confidence:**
- ✅ Can run large backfills confidently
- ✅ Can trust daily operations
- ✅ Easy to debug when issues occur

---

## 📊 Current State vs Future State

### Current State ❌

**Backfills:**
- Scripts continue after failures
- No gap detection between phases
- Can't disable Pub/Sub cascade
- Incomplete data propagates downstream

**Daily Operations:**
- Jobs run even if yesterday failed
- Completeness checks warn but don't stop
- Gaps in historical data go unnoticed
- Debugging requires manual SQL queries

### Future State ✅

**Backfills:**
- Configurable error policies
- Automatic gap detection between phases
- `--skip-downstream-trigger` flag
- Verify-then-proceed workflow

**Daily Operations:**
- Gap detection prevents bad processing
- Upstream failure detection
- Clear alerts for data issues
- Production-ready integrity checks

---

## 🔗 Related Projects

**Cross-References:**
- `../bootstrap-period/` - Uses some backfill features (cascade control)
- `../../02-operations/backfill-guide.md` - Will be updated with new features
- `../../../01-architecture/cross-date-dependencies.md` - Context for why this matters

---

## 📞 Quick Reference

| Need | See |
|------|-----|
| **Full design** | [DESIGN.md](./DESIGN.md) |
| **Start implementing** | IMPLEMENTATION-PLAN.md (TODO) |
| **Test features** | TESTING-GUIDE.md (TODO) |
| **Use in production** | OPERATIONS-GUIDE.md (TODO) |
| **Quick workarounds** | This README, "Quick Wins" section above |

---

## 🚀 Next Steps

1. **Review** - Review DESIGN.md and provide feedback
2. **Prioritize** - Confirm Priority 1 features
3. **Plan** - Create IMPLEMENTATION-PLAN.md
4. **Implement** - Build features (estimated 20 hours)
5. **Test** - Validate with historical backfills
6. **Document** - Update operations guides
7. **Deploy** - Roll out to production

---

**Status:** ✅ Phases 1-2 Complete - Production Ready!
**Priority:** HIGH
**Progress:** Phase 1 (Cascade Control) ✅ / Phase 2 (Completeness) ✅ / Phase 3 (Backfill Scripts) ⏳ Optional
**Actual Effort:** 8 hours total (Phase 1: 5h, Phase 2: 3h)
**Remaining Effort:** ~8-10 hours (Phase 3 - optional backfill scripts)
**ROI:** Prevents data corruption, saves debugging time, enables confident operations

**Owner:** Engineering team
**Created:** 2025-11-27
**Last Updated:** 2025-11-28
