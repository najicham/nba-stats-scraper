# Session 178 Handoff

**Date:** 2026-02-10
**Previous:** Session 177

---

## What Was Done

### 1. P0: Challenger vs Champion Analysis (COMPLETE)

Ran full comparison of `catboost_v9_train1102_0108` (2,430/2,958 predictions graded) against champion.

**Overall (Jan 10 - Feb 8, edge 3+, actionable):**

| Metric | Champion | Challenger | Delta |
|--------|----------|------------|-------|
| HR Edge 3+ | 63.2% (n=396) | **83.8%** (n=131) | **+20.6pp** |
| HR Edge 3+ (excl. Jan 12) | 56.9% (n=325) | **79.3%** (n=58) | **+22.4pp** |
| MAE | 5.2 | **4.8** | -0.4 |
| Vegas Bias | +0.94 | **+4.73** | Heavy OVER |
| OVER/UNDER split | 52%/48% | 75%/25% | OVER-heavy |

**Weekly breakdown (edge 3+, actionable):**

| Week | Champion HR (n) | Challenger HR (n) |
|------|----------------|-------------------|
| Jan 12 | 71.2% (139) | 83.5% (79) |
| Jan 19 | 66.4% (113) | 90.9% (22) |
| Jan 26 | 54.0% (87) | 88.9% (18) |
| Feb 2 | 47.4% (57) | 58.3% (12) |

**Key caveats:**
- Backfilled predictions, not live — uses same production lines (apples-to-apples) but feature store may have post-hoc improvements
- Small sample — only 58 edge 3+ picks excluding Jan 12
- Heavy OVER bias (+4.73 pvl) — 75% of picks are OVER. Risky if market shifts to UNDERs
- Low pick volume — 131 actionable vs champion's 396 in the same period
- Jan 12 accounts for 73/131 (56%) of challenger's edge 3+ picks — one exceptional OVER day

### 2. P4: Jan 12 Anomaly (RESOLVED)

Both models show extreme OVER bias on Jan 12 (avg pvl +7.4-7.6), but overs actually hit massively. Champion 88.7% (n=71), challenger 86.3% (n=73). Feature quality was good (86.2 avg, 97.8% matchup). **Legitimate — not a feature store issue.**

### 3. Fixed compare-model-performance.py (Bug Fix)

Script referenced non-existent `edge` column in `prediction_accuracy` table. Fixed:
- `edge` → `predicted_margin` (7 occurrences in the SQL query)
- `Decimal` vs `float` type mismatch in gap calculation
- `format_val()` now handles BigQuery Decimal types cleanly

### 4. Backfill Infrastructure Verified (READY)

Verified all components for backfilling `catboost_v9_train1102_0208` and `catboost_v9_train1102_0208_tuned`:

| Component | Status |
|-----------|--------|
| GCS model files | All 3 challengers exist |
| MONTHLY_MODELS config | Both enabled with correct GCS paths |
| Backfill script | Works with explicit `--start/--end` flags |
| Feb 9 feature store | 226 rows, 157 pass quality gate |
| Feb 9 production lines | 67 champion predictions with lines |

**Only blocker:** Script default date math (`end=yesterday=Feb 8` < `start=train_end+1=Feb 9`). Use explicit dates:

```bash
PYTHONPATH=. python bin/backfill-challenger-predictions.py \
    --model catboost_v9_train1102_0208 \
    --start 2026-02-09 --end 2026-02-09

PYTHONPATH=. python bin/backfill-challenger-predictions.py \
    --model catboost_v9_train1102_0208_tuned \
    --start 2026-02-09 --end 2026-02-09
```

### 5. P1/P2: Pending (Not Actionable Yet)

- **Feb 9 games:** All 10 still `game_status=1` (Scheduled). Cannot grade.
- **Feb 10 predictions:** Not generated yet (pipeline runs ~6 AM ET).

---

## Files Modified

- `bin/compare-model-performance.py` — Fixed `edge` → `predicted_margin`, Decimal type handling, format_val display

---

## What Still Needs Doing

### P0 (Immediate)
1. **Run Feb 9 backfills** for `_0208` and `_0208_tuned` models (commands above)
2. **Grade Feb 9 games** once `game_status=3` — trigger: `gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform`

### P1 (Next Morning)
3. **Verify Feb 10 live predictions** — first overnight run with all 3 challengers deployed. Check: `SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1`
4. **Check OddsAPI diagnostics** in prediction-worker Cloud Run logs

### P2 (Ongoing)
5. **Monitor challenger live performance** — live data eliminates backfill caveats. Run: `PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 7`
6. **Watch the OVER bias** — challenger's +4.73 vegas bias and 75% OVER split is the biggest risk factor. If live predictions show similar bias, consider whether this is a feature or a bug.

### P3 (Low Priority)
7. **Model decay tracking** — champion hit rate dropped from 71.2% → 47.3% over 4 weeks. Challenger promotion may be urgent.
8. **Signal system recalibration** — 9 of 15 recent days are RED, losing discriminative power.
