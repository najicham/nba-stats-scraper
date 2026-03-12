# Session 471 Handoff — Morning Report + What's Next

**Date:** 2026-03-12
**Previous:** Session 470 (Mar 7-8 autopsy, high_skew demotion, model refresh) + Session 471a (MLB pre-season, reminders)

## Current State Summary

### NBA Algorithm: `v470_demote_high_skew`

The system is running v470, deployed Mar 11. Key changes from recent sessions:
- **OVER edge floor 5.0** (Session 468) — blocks unprofitable low-edge OVER (net-negative 4/5 seasons)
- **hot_shooting_over_block filter** (Session 468) — blocks OVER when FG diff >= 10% OR 3PT diff >= 15%
- **high_skew_over_block → observation** (Session 470) — was blocking 75% winners
- **Health-aware signal weights** (Session 469) — COLD signals downweighted
- **Pick locking fix** (Session 468) — model_disabled no longer hides published picks

### Model Fleet

7 enabled models retrained Mar 10-11. Two issues to verify:
- Ghost model (`catboost_v16_noveg_train0112_0309`) — enabled but had 0 predictions. Cache refresh pushed via v470.
- Zombie model (`catboost_v9_low_vegas_train0106_0205`) — disabled but still predicting. Same fix.

### BB Performance Context

Recent downturn: 7d HR was ~37.5% entering v470. Mar 7-8 root causes identified and fixed:
1. Stale LGBM dominance (54% of picks, 18% HR) → **FIXED** by retrain
2. Low-line OVER rescue (0/7) → **FIXED** by v468 OVER floor 5.0
3. UNDER collapse (stars scored big) → one-off, no action needed

### MLB Pre-Season: 15 Days to Opening Day (Mar 27)

All pre-season prep completed in Session 471a:
- ✅ Blacklist updated 28→23 pitchers (removed Gore, Severino, Suárez, Skenes, Horton)
- ✅ Shadow grading scheduler URL fixed (was targeting non-existent service)
- ✅ Training pipeline dry-run passed (CatBoost, LightGBM, XGBoost all installed)
- ✅ BQ training tables verified healthy (4 tables, data through Sep 2025)
- ✅ All 24 MLB schedulers verified PAUSED
- ✅ Launch runbook created: `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`
- ✅ 11 automated Slack+Pushover reminders set up (first fires Mar 18)
- ✅ `slack-reminder` CF deployed and tested (Slack + Pushover both working)

**MLB timeline:**

| Date | Milestone | Reminder Set? |
|------|-----------|---------------|
| Mar 18 | Retrain window opens (120d CatBoost) | ✅ 9 AM ET |
| Mar 24 | Resume 24 schedulers (`./bin/mlb-season-resume.sh`) | ✅ 8 AM ET |
| Mar 27 | Opening Day verification | ✅ 2 PM ET |
| Apr 3 | Week 1 grading review | ✅ 10 AM ET |

Full runbook: `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`
Opening day guide: `docs/09-handoff/2026-03-11-MLB-OPENING-DAY-HANDOFF.md`

### Uncommitted Changes

2 files modified in `orchestration/cloud_functions/weekly_retrain/`:
- `main.py` — Added LightGBM and XGBoost support (was CatBoost-only)
- `requirements.txt` — Added lightgbm, xgboost deps

These are from a previous session and should be reviewed before committing.

### Code Status

All pushed to main, auto-deployed. Zero deployment drift as of Mar 11 evening.

## Priority Tasks for This Session

### P0 — Morning Health Check

1. **Grade yesterday's results** (Mar 11):
   ```bash
   /yesterdays-grading
   ```

2. **Verify model fixes** — ghost model predicting, zombie model stopped:
   ```sql
   SELECT system_id, COUNT(*) as predictions
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-03-12'
   GROUP BY 1 ORDER BY 2 DESC
   ```

3. **Check today's picks**:
   ```bash
   /todays-predictions
   ```

### P1 — Monitor v470 Performance (3-Day Window)

Decision gates (through Mar 13):
- v470 HR >= 50% over 3 days → keep
- v470 HR < 40% over 3 days → deeper investigation
- Track `high_skew_over_block_obs` impact — would it have helped or hurt?

### P2 — NBA Daily Operations

```bash
/daily-steering          # Full morning report
/daily-autopsy           # Deep dive on misses
/trend-check             # Model drift detection
```

### P3 — Review Uncommitted weekly-retrain Changes

The multi-family weekly retrain CF (LightGBM + XGBoost support) is modified but not committed. Review and decide:
- Does the code look correct?
- Should we commit + deploy before next Monday's auto-retrain?
- This would fix the LightGBM/XGBoost short training window issue (P3 from Session 470)

### P4 — Graduate book_disagree Signals (~Mar 18 target)

Check if `book_disagree_over` has reached N >= 30 at BB level with HR >= 60%:
```sql
SELECT signal_tag, COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb,
UNNEST(bb.signal_tags) AS signal_tag
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE signal_tag LIKE 'book_disagree%' AND pa.prediction_correct IS NOT NULL
GROUP BY 1
```

### P5 — Season-End Planning

NBA regular season ends ~Apr 13. Start thinking about:
- When to stop picks (last 2 weeks = tanking teams)
- Full season autopsy planning
- What to preserve for 2026-27

## Quick Start

```bash
/daily-steering                             # 1. Morning health report
/yesterdays-grading                          # 2. How did yesterday go?
/validate-daily                             # 3. Pipeline health
./bin/check-deployment-drift.sh --verbose   # 4. Deployment drift
```

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | All filter logic, OVER floor 5.0 |
| `ml/signals/pipeline_merger.py` | ALGORITHM_VERSION = v470 |
| `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md` | MLB launch playbook |
| `bin/schedulers/setup_mlb_reminders.sh` | MLB reminder scheduler setup |
| `orchestration/cloud_functions/slack_reminder/main.py` | Slack+Pushover reminder forwarder |

## What NOT to Do

- Don't lower OVER floor below 5.0 without 2+ season validation
- Don't re-activate `high_skew_over_block` without N >= 20 and CF HR < 45%
- Don't manually deploy MLB worker yet — wait for Mar 18 retrain
- Don't resume MLB schedulers before Mar 24
- Don't commit the weekly-retrain changes without reviewing them first
