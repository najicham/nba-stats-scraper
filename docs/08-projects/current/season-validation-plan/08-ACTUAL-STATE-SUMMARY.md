# Actual Season State Summary

**Generated:** 2026-01-25
**Season:** 2025-26
**Date Range:** Oct 27, 2025 - Jan 24, 2026 (88 game dates, 638 games)

## Executive Summary

| Phase | Coverage | Status |
|-------|----------|--------|
| Phase 2 (BDL Boxscores) | 96.2% (614/638 games) | GOOD - 14 dates with minor gaps |
| Phase 3 (Analytics) | 100.0% (638/638 games) | COMPLETE |
| Phase 5 (Predictions) | 95.3% (608/638 games) | GOOD |
| Phase 6 (Grading) | **45.9%** (293/638 games) | **CRITICAL** - Major backfill needed |

## Critical Finding: Grading is Only 45.9% Complete

The biggest issue is grading:
- **14 dates with 0% grading** (mostly Nov 4-18 + Dec 15, 30, Jan 8)
- **31 dates with < 50% grading**
- Only ~34 dates with acceptable grading (>50%)

This means **over half of our predictions have never been graded** against actual results.

---

## Detailed Gap Analysis

### Phase 2 (BDL Boxscores) - 14 Gap Dates

| Date | Expected | Actual | Missing |
|------|----------|--------|---------|
| 2026-01-24 | 7 | 6 | 1 (GSW@MIN postponed) |
| 2026-01-17 | 9 | 8 | 1 |
| 2026-01-16 | 6 | 5 | 1 |
| 2026-01-15 | 9 | 6 | 3 |
| 2026-01-14 | 7 | 5 | 2 |
| 2026-01-13 | 7 | 5 | 2 |
| 2026-01-12 | 6 | 4 | 2 |
| 2026-01-08 | 4 | 3 | 1 |
| 2026-01-07 | 12 | 10 | 2 |
| 2026-01-06 | 6 | 5 | 1 |
| 2026-01-05 | 8 | 6 | 2 |
| 2026-01-03 | 8 | 6 | 2 |
| 2026-01-02 | 10 | 8 | 2 |
| 2026-01-01 | 5 | 3 | 2 |

**Total missing: 24 games across 14 dates**

### Phase 6 (Grading) - Dates with 0% Grading

| Date | Predictions | Graded | Issue |
|------|-------------|--------|-------|
| 2025-11-04 | 207 | 0 | First prediction day - grading never ran |
| 2025-11-05 | 381 | 0 | |
| 2025-11-06 | 34 | 0 | |
| 2025-11-07 | 379 | 0 | |
| 2025-11-08 | 277 | 0 | |
| 2025-11-09 | 243 | 0 | |
| 2025-11-11 | 208 | 0 | |
| 2025-11-12 | 414 | 0 | |
| 2025-11-13 | 69 | 0 | |
| 2025-11-14 | 190 | 0 | |
| 2025-11-15 | 110 | 0 | |
| 2025-11-16 | 211 | 0 | |
| 2025-11-17 | 264 | 0 | |
| 2025-11-18 | 202 | 0 | |
| 2025-12-15 | 157 | 0 | |
| 2025-12-30 | 285 | 0 | |
| 2026-01-08 | 195 | 0 | |

**Total ungraded: ~3,826 predictions across 17 dates**

### Phase 6 (Grading) - Dates with Low Grading (<50%)

Many dates from Dec 20 onwards have 1-35% grading coverage. Example:
- Dec 20: 1,096 predictions, only 15 graded (1%)
- Dec 23: 1,496 predictions, only 16 graded (1%)
- Jan 23: 3,891 predictions, only 1,294 graded (33%)

---

## Known Issues Affecting Data

### Postponed Games
- **GSW@MIN** (game_id=0022500644): Rescheduled from Jan 24 to Jan 25
- **CHI@MIA** (game_id=0022500692): Rescheduled from Jan 30 to Jan 31

### Recent Outages (from handoff docs)
- **Jan 23-25**: 45-hour Firestore outage stopped all workflows
- **Jan 24**: nbac_player_boxscore scraper failure (85.7% complete)
- **Ongoing**: Feature quality degraded (all bronze tier)

### Prediction Duplicates
- 6,473 duplicate prediction rows identified
- Cleanup pending

---

## Priority Backfill Queue

### P0 - Critical (Do First)

**Grading Backfill: Nov 4 - Dec 15 (0% grading period)**
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-11-04 --end-date 2025-12-15
```

**Grading Backfill: Recent period**
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-12-16 --end-date 2026-01-24
```

### P1 - High (Do Second)

**BDL Boxscores: 14 dates with gaps**
```bash
# Run for each gap date
python bin/backfill/bdl_boxscores.py --date 2026-01-15
python bin/backfill/bdl_boxscores.py --date 2026-01-14
# ... etc for all 14 dates
```

### P2 - Medium (Do Third)

**Prediction Duplicate Cleanup**
```sql
-- Identify and remove duplicate predictions
-- (Query from handoff docs)
```

---

## Validation Commands

### Quick Health Check
```bash
python bin/validation/daily_data_completeness.py --days 14
```

### Full Season Scan
```bash
python bin/validation/season_reconciliation.py --full-season --output /tmp/season_validation.json
```

### Check Specific Date
```bash
python bin/validation/comprehensive_health_check.py --date 2025-11-15
```

---

## Success Criteria After Backfill

| Metric | Current | Target |
|--------|---------|--------|
| Phase 2 coverage | 96.2% | >98% |
| Phase 6 grading coverage | 45.9% | >80% |
| Dates with 0% grading | 17 | 0 |
| Prediction duplicates | 6,473 | 0 |

---

## Notes for Sonnet Handoff

1. **Grading is the top priority** - Over half of predictions ungraded
2. **BDL gaps are minor** - Only 24 missing games across 14 dates
3. **Analytics is complete** - No action needed for Phase 3
4. **Start with Nov 4-18 grading** - These are the oldest ungraded dates
5. **Verify GSW@MIN postponement** - May cause count mismatches
