# Backfill and Regeneration Plan

**Created:** 2026-01-25
**Priority:** P0
**Status:** Ready to Execute

---

## Summary

After the 45-hour Firestore outage (Jan 23 04:20 - Jan 25 01:35), several data gaps need backfilling.

---

## Phase 1: Grading Backfill (READY)

**Issue Fixed:** Grading filter bug (removed has_prop_line filter)
**Result:** Jan 23 now has 1,294 graded predictions (was 21)

### Run Grading Backfill for All Recent Dates

```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-15 --end-date 2026-01-24
```

**Expected Duration:** ~5 minutes
**Expected Output:** Grading for all dates with predictions

---

## Phase 2: Feature Regeneration (AFTER GAMES COMPLETE)

**Issue:** Feature quality degraded during outage (avg 69 vs normal 75+)

### Wait for Jan 24 Games to Complete

Jan 24 has games still in progress. After all games are Final:

```bash
# Check games are final
bq query "SELECT game_status, COUNT(*) FROM nba_raw.v_nbac_schedule_latest WHERE game_date = '2026-01-24' GROUP BY 1"

# Expected: All games status=3 (Final)
```

### Regenerate Phase 3 Analytics

```bash
# Regenerate analytics for Jan 23-24
./bin/backfill/run_year_phase3.sh --start-date 2026-01-23 --end-date 2026-01-24
```

### Regenerate Phase 4 Features

```bash
# Regenerate features for Jan 23-24
./bin/backfill/run_phase4.sh --start-date 2026-01-23 --end-date 2026-01-24
```

---

## Phase 3: Prediction Regeneration (OPTIONAL)

**Consideration:** Predictions were already made with degraded features. Re-running predictions would:
- Use better features (higher quality)
- Potentially change recommendations
- Lose historical record of what was actually predicted

**Recommendation:** Do NOT regenerate predictions. Keep historical record for analysis.
Instead, let the system naturally recover and monitor future dates.

---

## Phase 4: Validation

After backfills complete, run validation:

```bash
# Comprehensive health check
python bin/validation/comprehensive_health_check.py --date 2026-01-23

# Multi-angle validation
python bin/validation/multi_angle_validator.py --start-date 2026-01-20 --end-date 2026-01-24

# Prediction coverage
python bin/validation/check_prediction_coverage.py --weeks 4
```

---

## Execution Order

1. [x] **DONE:** Fix grading processor (removed has_prop_line filter)
2. [x] **DONE:** Run grading backfill for Jan 23 (1,294 now graded)
3. [ ] Run grading backfill for Jan 15-24 (full date range)
4. [ ] Wait for Jan 24 games to complete (~11 PM PST)
5. [ ] Verify schedule shows all games Final
6. [ ] Run Phase 3 analytics backfill for Jan 23-24
7. [ ] Run Phase 4 feature backfill for Jan 23-24
8. [ ] Run validation suite
9. [ ] Monitor Jan 25 for normal operation

---

## Monitoring After Backfill

```bash
# Morning check (run tomorrow AM)
python bin/validation/comprehensive_health_check.py --date 2026-01-24

# Should show:
# - Feature quality > 70
# - Grading > 90%
# - No critical issues
```

---

## Prevention Measures Implemented

1. **Workflow Decision Gap Alert:** New check catches controller outages
2. **Feature Quality Monitoring:** New check catches quality degradation
3. **Prop Line Consistency Check:** New check catches data bugs
4. **Grading Fix:** Now uses line_source instead of has_prop_line

---

## Notes

- Do NOT regenerate predictions - keep historical record
- Feature regeneration will improve FUTURE predictions
- Grading backfill recovers historical accuracy data
