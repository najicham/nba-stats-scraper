# Session 68 Handoff: Grading Backfill Gap Fixes

**Date**: February 1, 2026
**From**: Session 68 (Validation & Analysis)
**To**: Implementation Session
**Priority**: P1 - Prevent Validation Data Confusion

---

## Context: What Happened

### The Problem

Session 68 analyzed V9 model performance and concluded it was performing poorly (42% hit rate, low edge production). **This analysis was completely wrong.**

**Root Cause**: Used incomplete data
- Analyzed `prediction_accuracy` table: 94 V9 records (Jan 31 only)
- Missed `player_prop_predictions` table: 6,665 V9 records (Jan 9-31)
- **Actual V9 performance**: 79.4% high-edge hit rate ✅ EXCELLENT

### Why the Gap Existed

```
V9 Backfill Process (Jan 9-31):
1. ml/backfill_v8_predictions.py ran ✅
   └─> Wrote 6,665 predictions to player_prop_predictions

2. Grading backfill NOT run ❌
   └─> prediction_accuracy only has 94 records (Jan 31 live grading)

3. Validation used prediction_accuracy ❌
   └─> Saw 94 records, wrong analysis
```

**The gap**: Prediction backfill and grading backfill are separate manual steps. The grading step was forgotten.

---

## Your Mission

Implement **3 fixes** to prevent this from happening again:

1. **Fix 2: Validation Fallback** (P1, ~15 min) - Detection layer
2. **Fix 3: Documentation Update** (P1, ~10 min) - Prevent analyst mistakes
3. **Fix 1: Auto Grading Trigger** (P1, ~45 min) - Prevention layer

**Total Estimated Time**: ~70 minutes

---

## Fix 2: Add Grading Completeness Check to Validation (P1)

### Goal
Add a validation check that compares `prediction_accuracy` vs `player_prop_predictions` and alerts if grading is incomplete.

### Files to Modify

#### 1. `.claude/skills/validate-daily/SKILL.md`

**Location**: After "Phase 0.2: Heartbeat System Health" section (around line 180)

**Add this new section**:

```markdown
### Phase 0.4: Grading Completeness Check (NEW - Session 68)

**IMPORTANT**: Check if grading pipeline is up-to-date for all active models.

**Why this matters**: Backfilled predictions may not be graded yet. If `prediction_accuracy` is missing >20% of `player_prop_predictions`, model analysis will be wrong.

**What to check**:

\`\`\`bash
bq query --use_legacy_sql=false "
-- Check grading completeness for all active models
WITH prediction_counts AS (
  SELECT
    'player_prop_predictions' as source,
    system_id,
    COUNT(*) as record_count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id

  UNION ALL

  SELECT
    'prediction_accuracy' as source,
    system_id,
    COUNT(*) as record_count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as predictions,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as grading_coverage_pct,
  CASE
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 50
    THEN '🔴 CRITICAL - Run grading backfill'
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 80
    THEN '🟡 WARNING - Partial grading gap'
    ELSE '✅ OK'
  END as status
FROM prediction_counts
GROUP BY system_id
ORDER BY system_id"
\`\`\`

**Expected**: All models show ≥80% grading coverage

**Thresholds**:
- **<50% coverage** → 🔴 CRITICAL - Grading backfill needed
- **50-80% coverage** → 🟡 WARNING - Partial gap
- **≥80% coverage** → ✅ OK

**If CRITICAL or WARNING**:
1. Check if recent backfill was run: `SELECT MAX(game_date) FROM player_prop_predictions WHERE system_id = '<model>'`
2. Run grading backfill:
   \`\`\`bash
   PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\
     --start-date <first-date> --end-date <last-date>
   \`\`\`
3. **Use correct data source for analysis**: When analyzing models with <80% grading coverage, use `player_prop_predictions` joined with `player_game_summary` instead of `prediction_accuracy`

**Correct Query for Incomplete Grading**:
\`\`\`sql
-- When prediction_accuracy is incomplete, use this join approach
SELECT
  p.system_id,
  p.game_date,
  p.predicted_points,
  p.current_points_line as line_value,
  pgs.points as actual_points,
  CASE
    WHEN pgs.points > p.current_points_line AND p.recommendation = 'OVER' THEN TRUE
    WHEN pgs.points < p.current_points_line AND p.recommendation = 'UNDER' THEN TRUE
    WHEN pgs.points = p.current_points_line THEN NULL  -- Push
    ELSE FALSE
  END as prediction_correct
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup
  AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9'
  AND p.current_points_line IS NOT NULL
\`\`\`

**References**: Session 68 incident - V9 had 6,665 predictions but only 94 graded
```

### Testing Fix 2

After adding the section, verify it works:

```bash
# Run the query manually
bq query --use_legacy_sql=false "
WITH prediction_counts AS (
  SELECT 'player_prop_predictions' as source, system_id, COUNT(*) as record_count
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
  UNION ALL
  SELECT 'prediction_accuracy', system_id, COUNT(*)
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as predictions,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as coverage_pct
FROM prediction_counts
GROUP BY system_id"
```

**Expected output** (before V9 grading backfill):
```
system_id       | predictions | graded | coverage_pct
----------------|-------------|--------|-------------
catboost_v8     | 1234        | 1234   | 100.0
catboost_v9     | 6665        | 94     | 1.4  🔴 CRITICAL
ensemble_v1_1   | 456         | 456    | 100.0
```

If you see a low coverage_pct for V9, the check is working correctly.

---

## Fix 3: Update CLAUDE.md Documentation (P1)

### Goal
Document the grading table selection rule so future sessions know when to use which table.

### File to Modify

**File**: `CLAUDE.md`

**Location**: Add a new section after "Grading Tables" (around line 180, before "Hit Rate Measurement")

**Add this section**:

```markdown
### Grading Table Selection (IMPORTANT - Session 68 Learning)

**Two sources of graded prediction data:**

| Table | Use For | Grading Status |
|-------|---------|----------------|
| `prediction_accuracy` | Live production analysis, historical data (2021-2025) | Complete for production, may lag for backfills |
| `player_prop_predictions` + `player_game_summary` join | Backfilled predictions, any analysis with <80% grading coverage | Always complete |

**CRITICAL RULE**: Always verify data completeness before model analysis.

#### Pre-Analysis Verification (REQUIRED)

Before analyzing any model, run this check:

\`\`\`sql
-- Check grading completeness for model analysis
SELECT
  system_id,
  COUNT(*) as predictions,
  (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy pa
   WHERE pa.system_id = p.system_id
     AND pa.game_date >= '<your-start-date>') as graded,
  ROUND(100.0 * (SELECT COUNT(*) FROM nba_predictions.prediction_accuracy pa
                 WHERE pa.system_id = p.system_id
                   AND pa.game_date >= '<your-start-date>')
        / COUNT(*), 1) as coverage_pct
FROM nba_predictions.player_prop_predictions p
WHERE system_id = '<model-to-analyze>'
  AND game_date >= '<your-start-date>'
GROUP BY system_id
\`\`\`

**Decision Rule**:
- `coverage_pct >= 80%` → Use `prediction_accuracy` (faster, all fields populated)
- `coverage_pct < 80%` → Use join approach (see below)

#### Join Approach for Incomplete Grading

When `prediction_accuracy` is incomplete, use this pattern:

\`\`\`sql
-- Correct approach for backfilled/incomplete grading data
SELECT
  p.system_id,
  p.game_date,
  p.player_lookup,
  p.predicted_points,
  p.current_points_line as line_value,
  pgs.points as actual_points,
  p.confidence_score,
  ABS(p.predicted_points - pgs.points) as absolute_error,
  p.predicted_points - pgs.points as signed_error,
  ABS(p.predicted_points - p.current_points_line) as edge,
  CASE
    WHEN pgs.points > p.current_points_line AND p.recommendation = 'OVER' THEN TRUE
    WHEN pgs.points < p.current_points_line AND p.recommendation = 'UNDER' THEN TRUE
    WHEN pgs.points = p.current_points_line THEN NULL  -- Push
    ELSE FALSE
  END as prediction_correct
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup
  AND p.game_date = pgs.game_date
WHERE p.system_id = 'catboost_v9'
  AND p.current_points_line IS NOT NULL
  AND p.game_date >= '2026-01-09'
  AND pgs.is_dnp = FALSE  -- Exclude DNP players
\`\`\`

#### Why This Matters (Session 68 Incident)

**Real Example**: V9 model analysis (Feb 1, 2026)
- `prediction_accuracy`: 94 records → Analysis showed 42% hit rate ❌ WRONG
- `player_prop_predictions`: 6,665 records → Actual 79.4% high-edge hit rate ✅ CORRECT
- **Coverage**: 1.4% (94/6,665) → Should have triggered alert

The grading backfill job hadn't run for V9's historical predictions, causing incomplete data in `prediction_accuracy`. Always verify completeness before drawing conclusions.

**Fix**: Run grading backfill if coverage <80%:
\`\`\`bash
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\
  --start-date 2026-01-09 --end-date 2026-01-31
\`\`\`
```

### Testing Fix 3

After updating CLAUDE.md, verify the new section is clear:

1. Read through it as if you're a new analyst
2. Check that the SQL queries are syntactically correct
3. Ensure the decision rule (80% threshold) is clear

---

## Fix 1: Auto Grading Trigger in Backfill Script (P1)

### Goal
Make prediction backfill scripts automatically run grading backfill, so the gap can't happen.

### File to Modify

**File**: `ml/backfill_v8_predictions.py`

### Changes Required

#### 1. Add grading trigger function (around line 250, before `main()`)

```python
def run_grading_backfill(start_date: date, end_date: date, dry_run: bool = False) -> None:
    """
    Automatically trigger grading backfill after predictions are generated.

    This ensures prediction_accuracy table stays in sync with player_prop_predictions.

    Args:
        start_date: Start date for grading
        end_date: End date for grading
        dry_run: If True, only log what would be done
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would trigger grading backfill for {start_date} to {end_date}")
        return

    logger.info("=" * 80)
    logger.info(f"Step 2: Running grading backfill for {start_date} to {end_date}")
    logger.info("=" * 80)

    try:
        # Import grading backfill (avoid circular imports by importing here)
        import sys
        from pathlib import Path

        # Add backfill_jobs to path
        backfill_jobs_path = Path(__file__).parent.parent / 'backfill_jobs'
        sys.path.insert(0, str(backfill_jobs_path))

        from grading.prediction_accuracy.prediction_accuracy_grading_backfill import PredictionAccuracyBackfill

        # Run grading backfill
        grader = PredictionAccuracyBackfill()
        success = grader.backfill_date_range(start_date, end_date)

        if success:
            logger.info("✅ Grading backfill completed successfully")
        else:
            logger.warning("⚠️  Grading backfill completed with errors - check logs")

    except Exception as e:
        logger.error(f"❌ Failed to run grading backfill: {e}")
        logger.error("Manual grading backfill required:")
        logger.error(f"  PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\")
        logger.error(f"    --start-date {start_date} --end-date {end_date}")
        raise
```

#### 2. Update main() to call grading after predictions (around line 400, at the end of main())

**Find this section** (around the end of `main()` function):

```python
    if args.dry_run:
        logger.info("=== DRY RUN COMPLETE ===")
        logger.info("No data was written. Re-run without --dry-run to execute.")
    else:
        logger.info("=== BACKFILL COMPLETE ===")
        logger.info(f"Generated predictions for {len(dates)} dates")
```

**Replace with**:

```python
    if args.dry_run:
        logger.info("=== DRY RUN COMPLETE ===")
        logger.info("No data was written. Re-run without --dry-run to execute.")
        logger.info("Would run grading backfill for date range after predictions")
    else:
        logger.info("=" * 80)
        logger.info("=== STEP 1 COMPLETE: Predictions Generated ===")
        logger.info(f"Generated predictions for {len(dates)} dates")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info("=" * 80)

        # NEW: Auto-trigger grading backfill (Session 68 fix)
        logger.info("")
        logger.info("Starting automatic grading backfill...")
        try:
            run_grading_backfill(start_date, end_date, dry_run=args.dry_run)
            logger.info("")
            logger.info("=" * 80)
            logger.info("=== BACKFILL COMPLETE (PREDICTIONS + GRADING) ===")
            logger.info(f"✅ Predictions: {len(dates)} dates")
            logger.info(f"✅ Grading: {start_date} to {end_date}")
            logger.info("Both player_prop_predictions and prediction_accuracy are now in sync")
            logger.info("=" * 80)
        except Exception as e:
            logger.error("=" * 80)
            logger.error("=== PARTIAL COMPLETION ===")
            logger.error(f"✅ Predictions generated successfully")
            logger.error(f"❌ Grading backfill failed: {e}")
            logger.error("")
            logger.error("Manual grading backfill required:")
            logger.error(f"  PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\")
            logger.error(f"    --start-date {start_date} --end-date {end_date}")
            logger.error("=" * 80)
            raise
```

### Testing Fix 1

**IMPORTANT**: Test with a small date range before trusting it on large backfills.

#### Test 1: Dry Run

```bash
# Test dry run shows both steps
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --model-version v9 \
  --start-date 2026-02-01 \
  --end-date 2026-02-01 \
  --dry-run
```

**Expected output should include**:
```
=== DRY RUN COMPLETE ===
No data was written. Re-run without --dry-run to execute.
Would run grading backfill for date range after predictions
```

#### Test 2: Small Date Range Live Run

```bash
# Test with 1 day of real data
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --model-version v9 \
  --start-date 2026-02-01 \
  --end-date 2026-02-01
```

**Expected output should include**:
```
=== STEP 1 COMPLETE: Predictions Generated ===
Generated predictions for 1 dates

Starting automatic grading backfill...
Step 2: Running grading backfill for 2026-02-01 to 2026-02-01
[grading backfill logs...]
✅ Grading backfill completed successfully

=== BACKFILL COMPLETE (PREDICTIONS + GRADING) ===
✅ Predictions: 1 dates
✅ Grading: 2026-02-01 to 2026-02-01
Both player_prop_predictions and prediction_accuracy are now in sync
```

#### Test 3: Verify Data Completeness

After test run, verify both tables have the same records:

```sql
-- Check both tables for test date
SELECT
  'player_prop_predictions' as source,
  COUNT(*) as v9_records
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND game_date = '2026-02-01'

UNION ALL

SELECT
  'prediction_accuracy',
  COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = '2026-02-01'
```

**Expected**: Both sources show the same record count.

#### Test 4: Error Handling

Test that error handling works by temporarily breaking the grading import:

```bash
# Temporarily rename grading backfill file to simulate missing dependency
mv backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
   backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py.bak

# Run backfill - should fail gracefully with instructions
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --model-version v9 \
  --start-date 2026-02-01 \
  --end-date 2026-02-01

# Restore file
mv backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py.bak \
   backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py
```

**Expected**: Should show manual grading command and exit with error.

---

## Implementation Checklist

Use this checklist to track progress:

### Fix 2: Validation Fallback (P1)
- [ ] Update `.claude/skills/validate-daily/SKILL.md` with Phase 0.4 section
- [ ] Test query manually - verify it detects V9 grading gap
- [ ] Verify output format is clear (shows coverage_pct and status)
- [ ] Commit changes: `git add .claude/skills/validate-daily/SKILL.md && git commit -m "feat: Add grading completeness check to validation (Session 68 fix)"`

### Fix 3: Documentation (P1)
- [ ] Update `CLAUDE.md` with grading table selection section
- [ ] Verify SQL queries are syntactically correct
- [ ] Check that 80% threshold rule is clearly stated
- [ ] Test join query on sample data
- [ ] Commit changes: `git add CLAUDE.md && git commit -m "docs: Add grading table selection guidance (Session 68 fix)"`

### Fix 1: Auto Grading Trigger (P1)
- [ ] Add `run_grading_backfill()` function to `ml/backfill_v8_predictions.py`
- [ ] Update `main()` to call grading after predictions
- [ ] Test dry run - verify output shows both steps
- [ ] Test small date range (1 day) - verify both tables updated
- [ ] Verify data completeness with SQL query
- [ ] Test error handling - verify graceful failure with instructions
- [ ] Commit changes: `git add ml/backfill_v8_predictions.py && git commit -m "feat: Auto-trigger grading backfill after predictions (Session 68 fix)"`

### Final Verification
- [ ] Run `/validate-daily` - should now include grading completeness check
- [ ] Verify CLAUDE.md section is clear and complete
- [ ] Run small backfill end-to-end - verify auto-grading works
- [ ] Document any issues encountered

---

## Success Criteria

After implementing all three fixes:

1. **Detection**: Next `/validate-daily` will show grading coverage for all models ✅
2. **Documentation**: Analysts know to check coverage before analysis ✅
3. **Prevention**: Future backfills automatically grade predictions ✅

**Test**: Run a small V9 backfill (1 day) and verify:
- Both `player_prop_predictions` and `prediction_accuracy` get updated
- Validation shows 100% grading coverage
- No manual grading step required

---

## If You Encounter Issues

### Issue: Grading backfill import fails
**Solution**: Check path in `run_grading_backfill()` - may need to adjust import

### Issue: Grading backfill has different API
**Solution**: Check `PredictionAccuracyBackfill` class - method might not be `backfill_date_range()`

### Issue: Validation query too slow
**Solution**: Add WHERE clause to limit to recent dates (already included)

### Issue: SQL syntax error in CLAUDE.md
**Solution**: Test queries in bq CLI before committing

---

## Related Documents

- **Root cause analysis**: `docs/08-projects/current/catboost-v9-experiments/GRADING-BACKFILL-GAP-PREVENTION.md`
- **Session handoff**: `docs/09-handoff/2026-02-01-SESSION-68-VALIDATION-V9-ANALYSIS.md`
- **Corrected V9 analysis**: `docs/08-projects/current/catboost-v9-experiments/V9-EDGE-FINDING-PERFORMANCE-ISSUE.md`

---

## Questions to Ask User (If Needed)

1. Should the backfill script fail if grading fails, or continue with warning?
   - **Current implementation**: Fails (raises exception)
   - **Alternative**: Log warning, continue (less safe but more resilient)

2. Should we backfill V9 grading now (Jan 9-31) or wait until fixes are in place?
   - **Recommendation**: Do it now to fix current gap, then implement fixes

3. Do we want automated daily alerts (Fix 4) or is manual validation (Fix 2) sufficient?
   - **Recommendation**: Start with Fix 2, add Fix 4 later if needed

---

**Status**: 📋 Ready for Implementation
**Estimated Time**: 70 minutes (15 + 10 + 45)
**Priority**: P1 - Prevents critical validation mistakes

**Next Session Start Here**: Begin with Fix 2 (validation fallback) - quickest win, immediate protection.

---

*Handoff created: Session 68, 2026-02-01*
*For questions, refer to: `docs/08-projects/current/catboost-v9-experiments/GRADING-BACKFILL-GAP-PREVENTION.md`*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
