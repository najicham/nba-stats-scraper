Read docs/09-handoff/2026-02-10-SESSION-186-HANDOFF.md for full context. Session 186 ran 22 experiments and discovered that **quantile regression (alpha 0.43) creates staleness-independent edge** — the first approach in 85+ experiments to break the retrain paradox.

**P0 (Immediate):**

1. **Check if Feb 10 games have been graded:**
   ```bash
   bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as n FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-10' GROUP BY 1"
   ```
   If not graded:
   ```bash
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
   ```

2. **Run model comparison** to track champion decay and challenger performance:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
   ```

3. **Deploy QUANT_43 as shadow model.** This is the first model that works when fresh. Steps:
   - Train: `PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q43_SHADOW" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-10 --walkforward --force`
   - Upload model to GCS
   - Add config to `catboost_monthly.py` with system_id `catboost_v9_q43_train1102_0131`
   - Deploy worker
   - Monitor: `python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 7`

**P1 (Validation — ~Feb 15-17):**

Re-run QUANT_43 with 2+ weeks of eval data to validate the 65.8% HR finding at larger sample:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q43_EXT" \
  --quantile-alpha 0.43 \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force
```
Also try alpha 0.42 and 0.44 to narrow the sweet spot.

**P2 (Promotion — ~Feb 17-20):**

If QUANT_43 shadow validates at 55%+ HR in production (accounting for 5-10pp backtest gap):
- Promote as new champion
- Update governance gates for quantile models (UNDER-heavy by design, relax OVER gate)
- Establish bi-weekly retraining cadence (staleness doesn't matter for quantile)

**P3 (Research):**
- QUANT_43 + recency weighting (--recency-weight 30)
- UNDER-only deployment mode for quantile models
- Quantile regression for breakout classifier

**Key discovery from Session 186:**
- QUANT_43 gets **65.8% HR 3+ when fresh** vs BASELINE's 33.3% on same data
- QUANT_43 drops only **3.3pp** across eval windows vs BASELINE's **49.2pp** drop
- Edge comes from systematic prediction bias (loss function), not model drift (staleness)
- Best segments: Starters UNDER 85.7%, High Lines 76.5%, Edge [3-5) 71.4%
- Combos (NO_VEG + quantile, CHAOS + quantile) perform WORSE — don't stack
- Grow policy changes (Depthwise, Lossguide) = dead ends for edge generation

**85 total experiments across Sessions 179-186.**

Use agents in parallel where possible.
