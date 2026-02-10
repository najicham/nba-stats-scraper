Read docs/09-handoff/2026-02-10-SESSION-186-HANDOFF.md for full context. Session 186 ran 22 experiments and discovered that **quantile regression (alpha 0.43) creates staleness-independent edge** — the first approach in 85+ experiments to break the retrain paradox. Both QUANT_43 and QUANT_45 deployed as shadow models.

**P0 (Immediate):**

1. **Check if Feb 10 games have been graded:**
   ```bash
   bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as n FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-10' GROUP BY 1"
   ```
   If not graded:
   ```bash
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
   ```

2. **Check quantile shadows are generating predictions:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT system_id, game_date, COUNT(*) as n
   FROM nba_predictions.player_prop_predictions
   WHERE system_id IN ('catboost_v9_q43_train1102_0131', 'catboost_v9_q45_train1102_0131')
     AND game_date >= CURRENT_DATE() - 2
   GROUP BY 1, 2 ORDER BY 2 DESC, 1"
   ```

3. **Run model comparison** across all shadows:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 7
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q45_train1102_0131 --days 7
   ```

**Active shadow roster (4 models + champion):**

| system_id | Type | Purpose | Watch For |
|-----------|------|---------|-----------|
| `catboost_v9` (champion) | RMSE, Jan 8 | Baseline | Below breakeven (47.9% edge 3+), decaying |
| `catboost_v9_train1102_0108` | RMSE, Jan 8, clean | Best current edge HR | 58.3% edge 3+ (n=12) |
| `catboost_v9_train1102_0131_tuned` | RMSE, Jan 31, tuned | Same data as quantile models | 53.4% HR All but only 6 edge picks |
| `catboost_v9_q43_train1102_0131` | **Quantile 0.43**, Jan 31 | Session 186 discovery | Expect 55-60% HR, UNDER-heavy |
| `catboost_v9_q45_train1102_0131` | **Quantile 0.45**, Jan 31 | Less aggressive quantile | Expect similar, fewer edge picks |

**Retired:** `_0131` defaults (redundant with `_tuned`), `_0208`/`_0208_tuned` (contaminated).

**P1 (Validation — ~Feb 15-17):**

Re-run QUANT_43 and QUANT_45 with 2+ weeks of eval data:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q43_EXT" \
  --quantile-alpha 0.43 \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force

PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q45_EXT" \
  --quantile-alpha 0.45 \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force
```
Also try alpha 0.42 and 0.44 to narrow the sweet spot.

**P2 (Promotion — ~Feb 17-20):**

If either quantile shadow validates at 55%+ HR in production (accounting for 5-10pp backtest gap):
- Promote as new champion
- Update governance gates for quantile models (UNDER-heavy by design, may need to relax OVER gate)
- Establish bi-weekly retraining cadence (staleness doesn't matter for quantile)

**P3 (Research):**
- QUANT_43 + recency weighting (--recency-weight 30)
- UNDER-only deployment mode for quantile models
- Quantile regression for breakout classifier

**Key context from Session 186:**
- QUANT_43 gets **65.8% HR 3+ when fresh** vs BASELINE's 33.3% on same data
- QUANT_43 drops only **3.3pp** across eval windows vs BASELINE's **49.2pp** drop
- Edge comes from systematic prediction bias (loss function), not model drift (staleness)
- Best segments: Starters UNDER 85.7%, High Lines 76.5%, Edge [3-5) 71.4%
- Combos (NO_VEG + quantile, CHAOS + quantile) perform WORSE — don't stack
- Grow policy changes (Depthwise, Lossguide) = dead ends for edge generation
- Champion at 47.9% edge 3+ HR (Feb 2 week), 33 days stale, below breakeven

**85 total experiments across Sessions 179-186.**

Use agents in parallel where possible.
