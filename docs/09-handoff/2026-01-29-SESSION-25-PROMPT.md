# Session 25 Prompt - Deploy Fix & Implement Prevention

Copy this prompt to start the next Claude Code session:

---

## Context

Session 24 identified and fixed a critical bug in CatBoost V8 that caused predictions to be inflated by +29 points. The model actually works great (74.25% hit rate on 2024-25 season) - it was a feature passing bug.

**The fix is committed but NOT YET DEPLOYED.**

## Your Tasks

### 1. Deploy the Fix (P0)

The worker.py fix needs to be deployed to production:

```bash
# Build and deploy prediction-worker
docker build -t us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest -f predictions/worker/Dockerfile .
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest
gcloud run deploy prediction-worker --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest --region=us-west2
```

### 2. Verify Fix is Working

After deployment, verify predictions are reasonable:

```sql
-- Should see avg_edge around 0.5-4, not 8-9
SELECT
  game_date,
  AVG(predicted_points - current_points_line) as avg_edge,
  COUNT(*) as predictions,
  SUM(CASE WHEN predicted_points >= 55 THEN 1 ELSE 0 END) as extreme
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date >= CURRENT_DATE() - 1
GROUP BY 1
```

### 3. Implement Prevention (P1)

Work on these tasks from the prevention plan:

- **Task #8**: Add fallback severity classification (NONE/MINOR/MAJOR/CRITICAL)
- **Task #9**: Add Prometheus metrics for feature completeness
- **Task #10**: Add feature parity tests

## Files to Read First

1. **Handoff document** (full context):
   ```
   docs/09-handoff/2026-01-29-SESSION-24-HANDOFF.md
   ```

2. **Project documentation**:
   ```
   docs/08-projects/current/catboost-v8-performance-analysis/README.md
   docs/08-projects/current/catboost-v8-performance-analysis/PREVENTION-PLAN.md
   ```

3. **The fix that was applied**:
   ```
   predictions/worker/worker.py  (lines 815-870, v3.7 feature enrichment)
   ```

## Key Facts

| Fact | Value |
|------|-------|
| Model hit rate (when working) | 74.25% |
| Bug cause | Features 25-32 not populated |
| Fix location | `worker.py` v3.7 enrichment |
| Fix committed | Yes (ea88e526) |
| Fix deployed | **NO - needs deployment** |

### 4. Standardize Confidence Scale to Percentage (0-100)

Decision made: Use percentage for human readability. Currently mixed (backfill=percent, forward=decimal).

Steps:
1. Update `normalize_confidence()` in `predictions/worker/data_loaders.py` - remove the `/100` for catboost_v8
2. Convert existing decimal values:
   ```sql
   UPDATE nba_predictions.player_prop_predictions
   SET confidence_score = confidence_score * 100
   WHERE system_id = 'catboost_v8'
     AND confidence_score <= 1
     AND confidence_score > 0
   ```
3. Update any monitoring that expects 0-1 scale

## What NOT to Do

- Don't retrain the model yet - it works fine
- Don't modify catboost_v8.py prediction logic - the fix is in worker.py

## Success Criteria

1. Fix deployed and verified working
2. Predictions show reasonable edges (0.5-4 points, not 8-9)
3. No extreme predictions (>55 points)
4. At least one prevention task started (#8, #9, or #10)

---

*Prompt created: 2026-01-29 Session 24*
