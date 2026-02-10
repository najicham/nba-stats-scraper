Read docs/09-handoff/2026-02-10-SESSION-183-HANDOFF.md for full context. Session 183 ran 18 cross-window experiments and proved the "staleness mechanism" — models create betting edge through natural divergence from Vegas as they age.

**P0 (Immediate):**

1. **Commit and push all uncommitted files.** There are 7 uncommitted files — 4 docs (Session 183 analysis + OVER weakness corrections) and 3 code fixes from earlier sessions (severity enum fix, processor name typos, coordinator get_json). Check `git status` and review diffs before committing. The code changes are small bug fixes, not Session 183 work.

2. **Check if Feb 10 games have been graded** (they should auto-grade, but verify):
   ```bash
   bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as n FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-10' GROUP BY 1"
   ```
   If not graded:
   ```bash
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
   ```

3. **Run model comparison** to track promotion decision:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
   ```

**P1 (Promotion Decision — target ~Feb 17-20):**

The Jan 31 tuned model (`catboost_v9_train1102_0131_tuned`) leads at 53.4% HR All vs champion's decaying 48.8%. Champion was trained Jan 8 and follows a 4-week lifecycle — by Feb 17 it should be at ~43-44% HR. At that point, promoting the tuned model (even with few high-edge picks) is better than a decaying champion.

**P2 (Extended Eval — ~Feb 15+):**

Re-run the best experiments with 2+ weeks of eval data once available:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C1_CHAOS_EXT2" \
  --rsm 0.3 --random-strength 10 --subsample 0.5 --bootstrap Bernoulli \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force

PYTHONPATH=. python ml/experiments/quick_retrain.py --name "NO_VEG_EXT2" \
  --no-vegas \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force
```
Focus on: Is UNDER HR still ~60%+ with larger sample? Do niche segments (Starters UNDER, Edge 7+, High Lines >20.5) hold?

**P3 (Strategic — Model Rotation or UNDER-Only):**

Session 183 identified two strategic paths:
- **Staleness rotation:** Train every 2-3 weeks, shadow 1 week, promote for 2-3 weeks, retire. Needs automation.
- **UNDER-restricted NO_VEG:** Deploy a model that only makes UNDER picks (~40/week at ~60% HR). Needs custom actionability filter.

Both are viable. Rotation is simpler but requires discipline. UNDER-only is more novel but needs infrastructure work.

**Key context from Sessions 179-183:**
- 63+ experiments across 5 sessions, none beat controlled staleness for overall performance
- All architectures follow the same staleness decay curve — architecture affects volume (number of edge picks), not accuracy
- NO_VEG generates 10x more edge picks than BASELINE/MATCHUP but at slightly lower HR
- UNDER direction is stable (58-64% HR) across all windows; OVER swings wildly week-to-week
- Residual mode and two-stage pipeline are dead ends — don't revisit
- OVER weakness was a Feb 1-8 eval window artifact, not structural (champion OVER=53.6%, UNDER=53.1% over 6 weeks)
- Backtest-to-production gap: expect 5-10pp discount from experiment results

Use agents in parallel where possible.
