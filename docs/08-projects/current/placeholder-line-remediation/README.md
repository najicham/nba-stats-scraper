# Placeholder Line Remediation Project

**Start Date**: 2026-01-16
**Session**: 76-77
**Priority**: CRITICAL
**Status**: Phase 1 Complete, Executing Phases 2-5

---

## Problem Statement

24,033 NBA predictions were evaluated against placeholder betting lines (line_value = 20.0) instead of real DraftKings/sportsbook lines, causing win rates to be artificially inflated by +11 to +44 percentage points.

### Affected Data
- **XGBoost V1**: 6,548 predictions (Nov 19, 2025 - Jan 10, 2026) - 100% placeholders
- **Nov-Dec System-wide**: 15,915 predictions (Nov 19 - Dec 19, 2025) - 100% placeholders
- **Jan 9-10, 2026**: 1,570 predictions - 63-100% placeholders

---

## Root Causes

1. **20.0 Default Bug**: Code defaulted to `season_avg = 20.0` for players with no historical games
2. **Enrichment Gap**: Enrichment only updated NULL lines, not ESTIMATED_AVG lines when real props available
3. **No Validation Gate**: Worker wrote ANY line_value to BigQuery without quality checks
4. **Grading Accepts Invalids**: Grading processor included placeholder predictions in metrics

---

## Solution: 5-Phase Remediation Plan

### Phase 1: Code Fixes ✅ COMPLETE
**Deployed**: 2026-01-17 02:29 UTC
**Status**: SUCCESSFUL

**Changes**:
- `predictions/worker/worker.py`: Added validation gate to block placeholders
- `predictions/worker/data_loaders.py`: Removed 20.0 defaults
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`: Added query filters

**Validation**:
- ✅ Unit tests: 6/6 passed
- ✅ Deployments: Worker + Grading processor active
- ✅ No new placeholders since deployment
- ✅ Services operational

**Commit**: 265cf0a

---

### Phase 2: Delete Invalid Data
**Status**: READY TO EXECUTE
**Estimated Time**: 10 minutes
**Script**: `scripts/nba/phase2_delete_invalid_predictions.sql`

**What it does**:
1. Creates backup table: `deleted_placeholder_predictions_20260116`
2. Deletes XGBoost V1 predictions (6,548 rows)
3. Deletes Jan 9-10 predictions (1,570 rows)
4. Deletes Nov-Dec predictions without matching props (~1,000 rows)
5. Keeps Nov-Dec predictions that CAN be backfilled (~15,000 rows)

**Safety**:
- Full backup created before deletion
- Precise WHERE clauses
- Verification queries after each deletion
- Rollback: Single INSERT from backup table

**Validation Criteria**:
- Backup table has ~8,000-10,000 rows
- XGBoost V1: 0 remaining
- Jan 9-10: 0 remaining
- Nov-Dec: ~15,000 remaining for backfill

---

### Phase 3: Backfill Nov-Dec Lines
**Status**: PENDING (after Phase 2)
**Estimated Time**: 1-2 minutes
**Script**: `scripts/nba/phase3_backfill_nov_dec_lines.py`

**What it does**:
1. Fetches historical DraftKings props from `nba_raw.odds_api_player_points_props`
2. Matches predictions to props via `player_lookup`
3. Updates `current_points_line` with real line values
4. Recalculates `recommendation` and `line_margin`
5. Tracks changes in `previous_line_source`

**Safety**:
- Dry-run mode available
- Idempotent (safe to re-run)
- Resumable by date
- Rollback: UPDATE to restore original values

**Validation Criteria**:
- Success rate >95% (~14,250+ of 15,000 updated)
- 0 remaining placeholders in Nov-Dec
- Line values varied (5-40 range, not all 20.0)
- Sportsbook distribution (mostly DraftKings)

**Historical Props Verified**: ✅
- Nov 19: 627 props
- Nov 20: 327 props
- Nov 21: 758 props

---

### Phase 4a: Regenerate Jan 9-10 (VALIDATION TEST)
**Status**: PENDING (after Phase 3)
**Estimated Time**: 30 minutes
**Script**: `scripts/nba/phase4_regenerate_predictions.sh` (first section)

**Purpose**: Tests that Phase 1 validation gate works with real production workload

**What it does**:
1. Publishes Pub/Sub messages for Jan 9-10
2. Coordinator triggers worker with Phase 1 fixes active
3. Validation gate blocks any placeholders
4. Script pauses for user verification before continuing

**CRITICAL CHECKPOINT**:
This is the validation test. If Jan 9-10 regenerates with 0 placeholders, Phase 1 is proven to work.

**Validation Criteria**:
- Jan 9-10: 0 predictions with line_value = 20.0
- All 7 systems generated predictions
- Line sources are ACTUAL_PROP
- User confirms before Phase 4b

**If Failures Occur**:
- Stop immediately
- Delete Jan 9-10 regenerated predictions
- Investigate Phase 1 validation gate
- DO NOT proceed to Phase 4b

---

### Phase 4b: Regenerate XGBoost V1
**Status**: PENDING (after Phase 4a success)
**Estimated Time**: 4 hours
**Script**: `scripts/nba/phase4_regenerate_predictions.sh` (second section)

**What it does**:
1. Queries backup table for exact XGBoost V1 dates (53 dates)
2. Publishes Pub/Sub message for each date
3. 3-minute delays between messages (rate limiting)
4. Regenerates xgboost_v1 system only

**Safety**:
- User confirmation required before starting
- Can delete regenerated data if issues found
- Batch delays prevent overwhelming workers

**Validation Criteria**:
- 0 placeholders across all 53 dates
- Line source distribution shows ACTUAL_PROP majority
- System coverage verified (xgboost_v1 has predictions)
- Win rates normalized to 50-65% range

---

### Phase 5: Setup Monitoring
**Status**: PENDING (after Phase 4b)
**Estimated Time**: 10 minutes
**Script**: `scripts/nba/phase5_setup_monitoring.sql`

**What it creates**:
1. `line_quality_daily` - Daily line quality metrics per system
2. `placeholder_alerts` - Recent placeholder detections (should be empty)
3. `performance_valid_lines_only` - Win rates calculated only on valid lines
4. `data_quality_summary` - Overall quality snapshot

**Additional Setup**:
- Configure BigQuery scheduled queries
- Setup Slack alerts for daily monitoring
- Test alert functionality

**Success Criteria**:
- 4 views created successfully
- `placeholder_alerts` returns 0 rows
- `data_quality_summary` shows >95% valid lines

---

## Execution Timeline

```
Phase 1: COMPLETED (2026-01-17 02:29 UTC)
    ↓
Phase 2: Execute deletion (~10 min)
    ↓ Validate
Phase 3: Execute backfill (~2 min)
    ↓ Validate
Phase 4a: Regenerate Jan 9-10 (~30 min)
    ↓ CRITICAL CHECKPOINT - Verify 0 placeholders
Phase 4b: Regenerate XGBoost V1 (~4 hours)
    ↓ Validate
Phase 5: Setup monitoring (~10 min)
    ↓
Final Validation & 30-day monitoring
```

**Total Time**: ~5 hours 30 minutes

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Phase 1 doesn't work → recreate placeholders | HIGH | Phase 4a tests this before full regeneration |
| Delete wrong data | MEDIUM | Backup table created; precise WHERE clauses |
| Backfill incorrect lines | LOW | Dry-run first; player_lookup matching verified |
| Worker overwhelmed | LOW | 3-min delays; scales to 10 instances |
| Props data missing | LOW | Verified props exist for Nov 19-Dec 19 |

---

## Success Criteria

**Data Quality**:
- ✅ 0 predictions with `current_points_line = 20.0`
- ✅ 95%+ predictions have `line_source = 'ACTUAL_PROP'`
- ✅ All 7 systems have valid data Nov 19 - Jan 15

**Performance**:
- ✅ Win rates normalized to 50-65% range
- ✅ Grading uses only real sportsbook lines
- ✅ Performance metrics accurate

**Monitoring**:
- ✅ Daily alerts functional
- ✅ BigQuery views show line quality
- ✅ 30 consecutive days with 0 placeholder incidents

---

## Rollback Procedures

See individual phase sections above for specific rollback procedures.

**General Principle**: Each phase has safety mechanisms and can be reversed.

---

## Key Files

**Documentation**:
- This README
- `EXECUTION_LOG.md` - Real-time execution tracking
- `VALIDATION_RESULTS.md` - Validation query results
- `/docs/09-handoff/SESSION_76_FINAL_HANDOFF.md` - Original plan

**Scripts**:
- `scripts/nba/phase2_delete_invalid_predictions.sql`
- `scripts/nba/phase3_backfill_nov_dec_lines.py`
- `scripts/nba/phase4_regenerate_predictions.sh`
- `scripts/nba/phase5_setup_monitoring.sql`

**Code Changes**:
- `predictions/worker/worker.py`
- `predictions/worker/data_loaders.py`
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

---

## Contact & References

**Sessions**: 76 (investigation), 77 (execution)
**Related Issues**: Placeholder line data quality
**Dependencies**: Phase 1 MUST be deployed before Phases 2-5
