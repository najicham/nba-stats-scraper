# Edge Filter Investigation - Session 106

**Date:** 2026-02-03
**Status:** ROOT CAUSE IDENTIFIED
**Severity:** P1 CRITICAL (data quality issue, but NOT a code bug)

---

## Summary

The edge filter appears to not be working because **all today's predictions were created BEFORE the Session 102 code was deployed**. This is a deployment timing issue, not a code bug.

---

## Timeline Analysis

| Event | Time (UTC) | Time (PST) | Notes |
|-------|------------|------------|-------|
| Predictions created | 19:03-19:53 | 11:03-11:53 AM | Used OLD worker code |
| Session 102 commit | 20:24:54 | 12:24 PM | Added edge filter |
| Worker deployed | 22:26:00+ | 2:26 PM+ | NEW code now active |

**Key Finding:** 243 predictions were created 1-2 hours BEFORE the edge filter code was even committed.

---

## Data Evidence

### Predictions by Timing
```
+---------------+-------------+---------------------+
|    timing     | predictions | actionable_low_edge |
+---------------+-------------+---------------------+
| Before Deploy |         243 |                  65 |
+---------------+-------------+---------------------+
```

All 243 predictions for Feb 3 were created before the deployment. 65 of them have edge < 3 but are marked `is_actionable = TRUE` (which is wrong).

### Edge Distribution for Active Predictions

| Edge Tier | is_actionable=TRUE | is_actionable=FALSE |
|-----------|-------------------|---------------------|
| HIGH (5+) | 9 | 1 |
| MEDIUM (3-5) | 10 | 3 |
| LOW (<3) | 65 | 42 |
| NO_LINE | 97 | 16 |

The 65 low-edge actionable predictions are the problem - they should have been filtered.

---

## Root Cause

**NOT a code bug.** The edge filter code exists and works correctly:

```python
# predictions/worker/worker.py lines 1740-1746
if is_actionable and current_points_line is not None:
    edge = abs(predicted_points - current_points_line)

    # Low edge filter: edge < 3 has ~50% hit rate (no better than chance)
    if edge < 3.0:
        is_actionable = False
        filter_reason = 'low_edge'
```

**The issue:** Predictions were generated at ~11 AM PST by a scheduled job, but the Session 102 code wasn't committed until 12:24 PM PST and deployed at ~2:26 PM PST.

---

## Session 102 Edge Filter Design

Session 102 changed the architecture from **write-time filtering** to **query-time filtering**:

### Old Approach (Pre-Session 102)
- MERGE query filtered out edge < 3 predictions
- Problem: Regeneration batches lost predictions when corrected features produced edge < 3

### New Approach (Session 102)
- All predictions stored in database
- `is_actionable` field marks whether to use for betting
- `filter_reason` explains why (e.g., 'low_edge', 'confidence_tier_88_90', 'star_under_bias_suspect')

### Filter Criteria
1. **Low Edge (<3):** ~50% hit rate, no better than chance
2. **Confidence Tier 88-90%:** 61.8% hit rate vs 74-76% for other tiers
3. **Star UNDER Bias:** Model under-predicts stars by ~9 pts, high-edge UNDERs on stars lose

---

## Verification

The edge filter code IS in the deployed version:

```bash
# Check if Session 102 commit is ancestor of deployed commit
$ git merge-base --is-ancestor c04be05a 14395e15
# Returns true - code IS deployed

# Check deployed commit has low_edge filter
$ git show 14395e15:predictions/worker/worker.py | grep -c "low_edge"
# Returns 1 - code exists
```

---

## Impact

### For Feb 3 Predictions
- 65 predictions incorrectly marked `is_actionable = TRUE` with edge < 3
- These should NOT be used for betting
- Hit rate on edge < 3 is ~50% (break-even after vig = losing money)

### Mitigation Options

1. **Ignore low-edge actionable predictions manually:**
   ```sql
   SELECT * FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-02-03'
     AND system_id = 'catboost_v9'
     AND is_actionable = TRUE
     AND (line_source = 'NO_PROP_LINE' OR ABS(predicted_points - current_points_line) >= 3)
   ```

2. **Regenerate predictions** (would use new worker with edge filter):
   ```bash
   COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
   curl -X POST "${COORDINATOR_URL}/regenerate-with-supersede" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-02-03", "reason": "apply_edge_filter"}'
   ```

3. **Update is_actionable directly** (one-time fix):
   ```sql
   UPDATE nba_predictions.player_prop_predictions
   SET is_actionable = FALSE, filter_reason = 'low_edge_backfill'
   WHERE game_date = '2026-02-03'
     AND system_id = 'catboost_v9'
     AND line_source != 'NO_PROP_LINE'
     AND ABS(predicted_points - current_points_line) < 3
     AND is_actionable = TRUE
   ```

---

## Correct Query for Betting (Feb 3)

Until predictions are fixed, use this query to filter properly:

```sql
SELECT
  player_lookup,
  predicted_points,
  current_points_line,
  ABS(predicted_points - current_points_line) as edge,
  recommendation
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-03'
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
  AND (
    -- Either use is_actionable (works for future predictions)
    -- OR manually filter edge >= 3 (needed for Feb 3)
    line_source = 'NO_PROP_LINE'
    OR ABS(predicted_points - current_points_line) >= 3
  )
ORDER BY edge DESC
```

---

## Lessons Learned

1. **Deployment timing matters:** Code committed != code deployed. Scheduled jobs may run old code.

2. **Deploy immediately after critical fixes:** Session 102 edge filter was committed at 12:24 PM but predictions ran at 11 AM.

3. **Validate assumptions:** The validation skill checked for edge < 3 predictions and found them - the correct response was to check WHEN they were created vs WHEN code was deployed.

---

## Recommendations

### Immediate (Feb 3)
- [ ] Either regenerate predictions OR update is_actionable for existing ones
- [ ] Use edge >= 3 filter manually for tonight's betting

### Short-term
- [ ] Update `/validate-daily` skill Phase 0.45 to check `filter_reason` distribution rather than expecting zero low-edge predictions
- [ ] Add deployment timestamp check to validation

### Long-term
- [ ] Consider triggering prediction regeneration automatically after worker deployments
- [ ] Add alerting when predictions are created with code older than N hours

---

## Files Referenced

| File | Lines | Purpose |
|------|-------|---------|
| `predictions/worker/worker.py` | 1740-1757 | Edge filter and bias filter logic |
| `predictions/shared/batch_staging_writer.py` | 462-495 | MERGE query (no edge filter - by design) |

---

## Related Sessions

- **Session 102:** Implemented edge filter via `is_actionable` field
- **Session 81:** Original edge filter in MERGE query (now removed)
- **Session 105:** Validation checks that surfaced this issue

---

**End of Investigation**
