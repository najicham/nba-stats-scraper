# Session 409 Prompt

Read the handoff: `docs/09-handoff/2026-03-05-SESSION-408-HANDOFF.md`

## Priority Tasks

### P0: Verify Worker Fix (Session 407) — Predictions Flowing?
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT system_id) as models
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1 DESC
```
If 0 predictions: check worker logs for NoneType crash (should be fixed in `8f52e279`).

### P1: Investigate Combo Signals (88.2% HR, stopped Feb 11)
`combo_3way` and `combo_he_ms` are the highest-HR signals but haven't fired since Feb 11.
- Check how many OVER edge 3+ predictions have `minutes_surge >= 3`
- Check if confidence threshold or tier exclusion is blocking
- Consider loosening minutes_surge threshold if data shows it's too restrictive

### P1: Pick Volume Recovery
Currently 2 picks/day (target 4-8). Monitor if post-ASB edge recovery is improving pick flow.

### P2: Check Shadow Signal Accumulation
```sql
SELECT signal_tag, COUNT(*) as fires,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks, UNNEST(signal_tags) signal_tag
WHERE signal_tag LIKE '%projection_consensus%' OR signal_tag LIKE '%predicted_pace%'
  AND game_date >= '2026-03-04'
GROUP BY 1
```

### P3: Experiment Grid Status
- **pace_v1**: DEAD END (Session 408). Don't re-test.
- **tracking_v1**: Low priority, likely WASH (same static problem)
- **Tier 2 experiments** (projections_v1, sharp_money_v1, dvp_v1): Need ~30 days data (~Apr 5)
- Infrastructure is ready: backfill script + `--experiment-features` flag working

## Context
- Auto-deploy SUCCESS from Session 408 pushes
- Deployment drift: only legacy nba-phase1-scrapers (expected)
- TeamRankings scraper now captures efficiency data (30/30 teams)
