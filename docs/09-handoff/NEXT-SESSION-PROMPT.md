Read docs/09-handoff/2026-02-10-SESSION-182-HANDOFF.md and work through priorities:

- P0: **Grade Feb 10** once games complete. Trigger grading, then run comparison:
  ```bash
  gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
  PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
  ```

- P1: **Commit and push Session 181+182 changes.** Session 181 added segmented hit rates to `quick_retrain.py` (uncommitted). Session 182 added docs. Stage and push:
  ```bash
  git add ml/experiments/quick_retrain.py docs/09-handoff/ docs/08-projects/current/session-179-validation-and-retrain/
  ```

- P2: **Re-run C1_CHAOS and C4_MATCHUP_ONLY with extended eval** (Feb 1-15+) once 2 weeks of data available. Look at segmented hit rates for segments with HR >= 58% and N >= 20+. Commands in Session 182 handoff P2.

- P3: **Investigate systematic OVER weakness.** All 40 experiments had OVER HR below breakeven. Is this model-specific or systemic? Query OVER vs UNDER in `prediction_accuracy`.

- P4: **Monitor promotion decision** (~Feb 17-20). Jan 31 tuned leads at 55.1% HR with +24pp disagreement signal. Champion decaying at 49.5%.

Session 182 context:
- Re-triggered Feb 10 predictions: 222 prop lines available, 18 preds per model, 4 actionable (champion only). Challengers produce 0 actionable (avg |edge| < 1 — retrain paradox in production).
- Re-ran A1 Vegas Weight Sweep (6 experiments) with Session 181's segmented HR code. Key finding: UNDER + High Lines (>20.5) is profitable at 70-80% HR across models. NO_VEG has richest niche segments. No experiment passes all governance gates overall.
- Updated project docs: `docs/08-projects/current/session-179-validation-and-retrain/03-A1-VEGAS-WEIGHT-SWEEP-RESULTS.md` (new), `01-RETRAIN-PARADOX-AND-STRATEGY.md` (updated with empirical results + revised priority)
- Session 180 (Feb 9) ran 34 experiments, none passed gates. Session 181 added segmented HR breakdowns. Session 182 (this) re-ran A1 with segmented HR + ops.
- 4-way matched comparison (Feb 4-9, n=301): Champion 49.5%, Jan 8 50.5%, Jan 31 defaults 54.2%, **Jan 31 tuned 55.1%**

Use agents in parallel where possible.
