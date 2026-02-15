# Session 131 - Verify Breakout Classifier Shadow Mode

## Quick Context

Session 130B deployed the breakout classifier shadow mode (developed in Session 128).
This session should verify shadow data is being collected.

## P0: Verify Shadow Data Collection

After predictions have run (~2:30 AM ET), verify shadow data:

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(JSON_VALUE(features_snapshot, '$.breakout_shadow.risk_score') IS NOT NULL) as with_shadow
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-05'
GROUP BY game_date
ORDER BY game_date;
```

**Expected:** Non-zero `with_shadow` count for dates after Feb 5

## If Shadow Data Missing

Check prediction-worker logs for errors:
```bash
gcloud run services logs read prediction-worker --region=us-west2 --limit=50 2>/dev/null | grep -i breakout
```

Check if classifier is being called:
- Location: `predictions/worker/prediction_systems/breakout_classifier_v1.py`
- Model: `models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm`

## If Shadow Data Present

Begin validation analysis:
1. Correlate `risk_score` with actual bet outcomes
2. Identify optimal threshold for filtering
3. Calculate potential ROI improvement

## Recent Changes

| Commit | Description |
|--------|-------------|
| `0ceb411f` | docs: Add Session 130B handoff |
| `a630f3b7` | fix: Add authentication to smoke tests |
| `8951a83c` | docs: Add Session 128 final handoff (breakout classifier) |

## Deployment Status

All services up to date as of Session 130B.

## Key Files

- **Classifier:** `predictions/worker/prediction_systems/breakout_classifier_v1.py`
- **Model:** `models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm`
- **Handoff:** `docs/09-handoff/2026-02-05-SESSION-130B-BREAKOUT-DEPLOY-HANDOFF.md`
