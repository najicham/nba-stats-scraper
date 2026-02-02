# Session 72: Deploy Coordinator + Verify Signals

## Context

Session 71 completed the pre-game signals system (all 6 phases). One deployment is pending.

## Read First

```bash
cat docs/09-handoff/2026-02-02-SESSION-71-SIGNALS-COMPLETE.md
cat docs/08-projects/current/pre-game-signals-strategy/IMPLEMENTATION-COMPLETE.md
```

## Immediate Task: Deploy Coordinator

The coordinator has Slack signal alerts but hasn't been deployed yet:

```bash
./bin/deploy-service.sh prediction-coordinator
```

After deployment, verify the env var is set:
```bash
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)" | grep SLACK_WEBHOOK_URL_SIGNALS
```

## Verify Signal System

Once deployed, the next time predictions run, signals should:
1. Auto-calculate after batch consolidation
2. Send alert to `#nba-betting-signals` channel

Check signals table:
```sql
SELECT game_date, system_id, pct_over, daily_signal, calculated_at
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= CURRENT_DATE() - 1
ORDER BY calculated_at DESC;
```

## Feb 1 Signal Validation (If Games Finished)

Feb 1 had a RED signal (10.6% pct_over). After games complete, validate:

```sql
SELECT COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.game_date = DATE('2026-02-01')
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5;
```

Expected: ~50-65% hit rate (confirms RED signal working)

## Monthly Model Check

Verify catboost_v9_2026_02 is generating predictions:
```sql
SELECT system_id, COUNT(*) 
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-02' AND system_id LIKE 'catboost%'
GROUP BY 1;
```

## Available Skills

- `/subset-picks` - Get picks from dynamic subsets
- `/subset-performance` - Compare subset performance
- `/validate-daily` - Includes signal check

## Threshold Tuning Reminder

Already set for Feb 15. No action needed until then. Guide: `THRESHOLD-TUNING.md`

## No Agents Needed

These are straightforward verification tasks - direct queries and deployment.
