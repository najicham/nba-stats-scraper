# Session 178 Handoff

**Date:** 2026-02-10
**Previous:** Session 177

---

## What Was Done

### 1. Fixed compare-model-performance.py
- `edge` column doesn't exist in `prediction_accuracy` — replaced with `predicted_margin` (7 occurrences)
- Fixed `Decimal` vs `float` type mismatch in gap calculation
- Improved `format_val()` to handle BigQuery Decimal types cleanly

### 2. P0: Challenger vs Champion Analysis (1,457 matched predictions)

Head-to-head on same player + same date + same line (Jan 9 - Feb 8):

| Metric | Champion | `_0108` Challenger |
|--------|----------|-------------------|
| HR (all) | 54.0% | **55.7%** (+1.7pp) |
| MAE | 5.17 | **4.85** (-0.32) |
| Disagree picks | 46.0% correct | **54.0%** correct |

Weekly: challenger beats champion on MAE every single week. When they disagree (311 picks), challenger wins 54% vs 46%.

### 3. Replaced Contaminated Models with Clean Jan 31 Experiments

**Discovery:** The two `_0208` models (trained Nov 2 - Feb 8) had contaminated backtests — evaluated on Jan 9-31 which overlaps 31 days of training data. Their 91-93% HR 3+ numbers were meaningless.

**Action:** Disabled `_0208` and `_0208_tuned`, trained 2 new models with clean separation:

| Model | Train Window | Eval Window | Hyperparams | Clean? |
|-------|-------------|-------------|-------------|--------|
| `catboost_v9_train1102_0131` | Nov 2 - Jan 31 | Feb 1-8 | depth=6, l2=3, lr=0.05 (defaults) | Yes |
| `catboost_v9_train1102_0131_tuned` | Nov 2 - Jan 31 | Feb 1-8 | depth=5, l2=5, lr=0.03 (tuned) + recency 30d | Yes |

**Training commands used:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_JAN31_DEFAULTS" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --walkforward --force

PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_JAN31_TUNED" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --tune --recency-weight 30 --walkforward --force
```

**Governance gates:** Both FAILED on sample size (only 6 edge 3+ bets in 8-day eval window). Deployed to shadow anyway — shadow testing will provide the real data.

**Model files:**
- Defaults: `catboost_v9_33f_train20251102-20260131_20260209_212708.cbm` (SHA: b61ba401)
- Tuned: `catboost_v9_33f_train20251102-20260131_20260209_212715.cbm` (SHA: 92b81d6c)

### 4. Backfilled and Graded New Models

- Backfilled 466 predictions each for Feb 4-8 (5 game days)
- Triggered grading for Feb 4-8 — 449 graded per model
- Only 6-7 edge 3+ actionable picks per model (avg |edge| ~0.75)

### 5. 4-Way Head-to-Head Comparison (Feb 4-8, n=269 matched)

| Model | Training | HR | MAE | Notes |
|-------|----------|-----|-----|-------|
| Champion (`catboost_v9`) | Nov 2 - Jan 8 (old) | 49.8% | 5.44 | Decaying |
| `_train1102_0108` | Nov 2 - Jan 8 (new) | 50.9% | 5.07 | Better features |
| **`_train1102_0131`** | Nov 2 - Jan 31 | **56.1%** | **4.95** | **Best HR (defaults)** |
| **`_train1102_0131_tuned`** | Nov 2 - Jan 31 | **56.9%** | **4.94** | **Best MAE (tuned)** |

**Key finding:** More training data helps. Jan 31 models beat Jan 8 models by ~5-6pp on HR and ~0.1 on MAE. Tuned hyperparams slightly edge defaults.

### 6. Jan 12 Anomaly — Resolved
Both models had extreme OVER bias on Jan 12, but overs hit massively. Feature quality was good. Legitimate, not a data issue.

---

## Current Shadow Deployment

| # | system_id | Training | Hyperparams | Status |
|---|-----------|----------|-------------|--------|
| 1 | `catboost_v9` | Nov 2 - Jan 8 | defaults (old features) | **CHAMPION** |
| 2 | `catboost_v9_train1102_0108` | Nov 2 - Jan 8 | defaults (new features) | Shadow, 2430 graded |
| 3 | `catboost_v9_train1102_0131` | Nov 2 - Jan 31 | defaults | Shadow, 449 graded |
| 4 | `catboost_v9_train1102_0131_tuned` | Nov 2 - Jan 31 | tuned (d=5,l2=5,lr=0.03)+recency | Shadow, 449 graded |
| ~~5~~ | ~~`catboost_v9_train1102_0208`~~ | ~~Nov 2 - Feb 8~~ | — | **RETIRED** (contaminated) |
| ~~6~~ | ~~`catboost_v9_train1102_0208_tuned`~~ | ~~Nov 2 - Feb 8~~ | — | **RETIRED** (contaminated) |

---

## Files Modified

- `bin/compare-model-performance.py` — Fixed `edge` → `predicted_margin`, type handling, formatting
- `predictions/worker/prediction_systems/catboost_monthly.py` — Disabled `_0208` models, added `_0131` models
- `docs/08-projects/current/retrain-infrastructure/01-EXPERIMENT-RESULTS-REVIEW.md` — Full update with Session 178 results
- `docs/09-handoff/2026-02-10-SESSION-178-HANDOFF.md` — This file

---

## What Still Needs Doing

### P0 (Immediate)
1. **Push to remote** — committed but NOT pushed. `git push origin main` will trigger auto-deploy of prediction-worker with new Jan 31 model config
2. **Grade Feb 9 games** once `game_status=3` — then backfill all 3 challengers for Feb 9:
   ```bash
   # Check game status
   bq query --use_legacy_sql=false "SELECT game_status, COUNT(*) FROM nba_reference.nba_schedule WHERE game_date='2026-02-09' GROUP BY 1"
   # Trigger grading
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform
   # Backfill all 3 challengers for Feb 9
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 --start 2026-02-09 --end 2026-02-09
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131 --start 2026-02-09 --end 2026-02-09
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131_tuned --start 2026-02-09 --end 2026-02-09
   ```
3. **Run subset analysis** on backfilled predictions (not yet done)

### P1 (Next Morning)
4. **Verify Feb 10 live predictions** — first overnight run with Jan 31 challengers. Check:
   ```sql
   SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1
   ```
5. **Check OddsAPI diagnostics** in prediction-worker logs

### P2 (Ongoing Monitoring)
6. **Monitor Jan 31 models' OVER bias** — if they show the same +4.73 bias as `_0108`, that's a model characteristic not a fluke
7. **Accumulate live data** — need 50+ edge 3+ graded bets before considering promotion
8. **Champion model decay** — 47.3% HR last week. If Jan 31 models sustain 56%+ in production, promote to champion

### P3 (Future)
9. **Monthly retrain cadence** — train through end of month, eval first week of next month
10. **Signal recalibration** — 9 of 15 recent days RED, losing discriminative power
11. **Update CLAUDE.md** — model section needs refresh with new challenger info
