# Session 152 Prompt

Read the Session 151 handoff: `docs/09-handoff/2026-02-07-SESSION-151-HANDOFF.md`

## Context

Session 151 completed three tasks:
- **Breakout V3 trained:** AUC 0.5924 (+0.02 vs V2 0.5708) on 7-day eval (N=520). Not promoted — no high-confidence predictions yet.
- **Feature completeness fix:** Added team_pace_last_10, team_off_rating_last_10, mid_range_rate_last_10 to fallback computation. Unblocks ~48 players/day.
- **BDL decommission:** Removed BDL from 10 config files (orchestration, workflows, registry, deploy scripts, secrets). Kept injuries + source code.

## Suggested Priorities

### 1. Monitor Feature Completeness Impact (HIGH)
Check if today's predictions show fewer defaults:
```sql
SELECT game_date, COUNTIF(default_feature_count = 0) as clean, COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-08'
GROUP BY 1
```

### 2. Breakout V3 Larger Evaluation (MEDIUM)
7-day eval showed +0.02 AUC improvement but `star_teammate_out` had 4.5x distribution shift (eval mean 0.971 vs train 0.213). Try:
```bash
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-end 2026-01-15 --eval-start 2026-01-16 --eval-end 2026-02-07
```

### 3. Remaining BDL Cleanup (LOW)
10 more files still reference BDL as fallback source (validation configs, processor patterns). See Session 151 handoff for full list.

## Verification
```bash
/validate-daily
./bin/check-deployment-drift.sh --verbose
```
