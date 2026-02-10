# Session 179 Handoff

**Date:** 2026-02-10
**Previous:** Session 178

---

## What Was Done

### 1. P0: Pushed Session 178 Commits & Verified Deploy
- Pushed 3 commits to `origin/main` (Session 178 had committed but NOT pushed)
- Cloud Build triggered `deploy-prediction-worker` — **SUCCESS** (commit `c76ecb7`)
- Prediction-worker now has Jan 31 challenger models in shadow mode

### 2. P1: Backfilled All 3 Challengers for Feb 9
- All 10 Feb 9 games are Final (`game_status=3`)
- Backfilled 59 predictions each for all 3 challengers:
  - `catboost_v9_train1102_0108` — 59 predictions (33 OVER, 26 UNDER)
  - `catboost_v9_train1102_0131` — 59 predictions (31 OVER, 28 UNDER)
  - `catboost_v9_train1102_0131_tuned` — 59 predictions (32 OVER, 27 UNDER)
- **Grading BLOCKED** — Feb 9 raw player stats not yet scraped (0 records in `nbac_gamebook_player_stats`). Pipeline scrapes ~6 AM ET. Grading must be re-triggered after pipeline completes.

### 3. P3: 4-Way Model Comparison (Feb 4-8, n=449 matched)

| Model | HR | MAE | OVER% | Vegas Bias | Stddev |
|-------|-----|------|-------|------------|--------|
| **Champion** (`catboost_v9`) | **49.8%** | 5.38 | 28.2% | -0.07 | 2.23 |
| Jan 8 (`_train1102_0108`) | 52.1% | 5.11 | 47.9% | -0.12 | 1.19 |
| **Jan 31 defaults** (`_train1102_0131`) | **54.8%** | **5.06** | 53.2% | **+0.01** | 0.97 |
| Jan 31 tuned (`_train1102_0131_tuned`) | 53.9% | 5.08 | 53.7% | +0.05 | 1.01 |

**Daily breakdown:**

| Date | n | Champ | Jan 8 | Jan 31 | Jan 31 Tuned |
|------|---|-------|-------|--------|--------------|
| Feb 4 | 96 | 57.6% | 61.5% | 60.4% | 62.5% |
| Feb 5 | 101 | 57.9% | 54.5% | 58.4% | 55.4% |
| Feb 6 | 69 | 41.7% | 43.5% | 52.2% | 44.9% |
| Feb 7 | 131 | 45.1% | 48.9% | 51.1% | 51.9% |
| Feb 8 | 52 | 42.9% | 50.0% | 50.0% | 51.9% |

### 4. Disagreement Analysis (Champion vs Jan 31 Defaults)

| Agreement | n | Champion HR | Jan 31 HR |
|-----------|---|-------------|-----------|
| **AGREE** | 192 | 54.2% | 54.2% |
| **DISAGREE** | 257 | **39.0%** | **55.3%** |

When they disagree, Jan 31 wins by **+16.3pp**. This is the strongest signal for promotion.

### 5. Champion Decay Confirmed (Urgent)

| Week | HR All | HR Edge 3+ | MAE | N Edge 3+ |
|------|--------|------------|-----|-----------|
| Jan 12 | 54.4% | **71.2%** | 5.19 | 139 |
| Jan 19 | 58.1% | 67.0% | 4.62 | 113 |
| Jan 26 | 50.1% | 56.0% | 4.83 | 87 |
| Feb 2 | **49.1%** | **47.9%** | 5.47 | 73 |

Champion is now **below breakeven** at every edge tier. Edge 3+ HR crashed from 71.2% to 47.9% in 4 weeks.

### 6. Subset Analysis
- Only "Green Light" subset had sufficient picks: **58.4% HR** (n=197, 14 days), +11.4% ROI
- Other subsets filtered out due to champion's low edge generation
- **Signal effectiveness degrading**: GREEN signal days only 50.2% HR on edge 3+ picks (was ~80%)
- Subset definitions are all `catboost_v9`-only; need new definitions for challengers if promoted

### 7. Key Discovery: Jan 31 Models Have Tight Predictions
- Jan 31 models have stddev ~1.0 vs champion's 2.23
- This means they generate **very few edge 3+ picks** (only 6 in 449 predictions)
- Their value is in **overall accuracy** (54.8%), not high-edge picks
- If promoted, subset filters need to be lowered (edge 1.5+ or 2+ instead of 3+/5+)

---

## Current Shadow Deployment

| # | system_id | Training | Status | Graded |
|---|-----------|----------|--------|--------|
| 1 | `catboost_v9` | Nov 2 - Jan 8 | **CHAMPION** (decaying) | ~3500+ |
| 2 | `catboost_v9_train1102_0108` | Nov 2 - Jan 8 | Shadow | ~2490 |
| 3 | `catboost_v9_train1102_0131` | Nov 2 - Jan 31 | Shadow | 449 (+59 ungraded) |
| 4 | `catboost_v9_train1102_0131_tuned` | Nov 2 - Jan 31 | Shadow | 449 (+59 ungraded) |

---

## Files Modified

- `docs/09-handoff/2026-02-10-SESSION-179-HANDOFF.md` — This file
- `docs/09-handoff/NEXT-SESSION-PROMPT.md` — Updated next session prompt

*No code changes this session — all work was operational (deploy, backfill, analysis).*

---

## What Still Needs Doing

### P0 (Immediate — next session)
1. **Grade Feb 9 predictions** — pipeline should have scraped by now. Trigger grading:
   ```bash
   # Verify raw data exists
   bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date='2026-02-09'"
   # Trigger grading
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform
   ```
2. **Verify Feb 10 live predictions** — first overnight run with Jan 31 challengers deployed:
   ```sql
   SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1
   ```
   Expect 4 system_ids. If only `catboost_v9` appears, check prediction-worker logs for challenger errors.

### P1 (After grading)
3. **Run updated 4-way comparison** with Feb 9 data included:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131 --days 7
   ```
4. **Grade Feb 10** once games complete, backfill challengers, repeat comparison

### P2 (Promotion Decision — ~Feb 17)
5. **Accumulate live data** — Jan 31 models need ~2 more weeks of shadow data. Target: 50+ edge 3+ graded bets (currently only 6)
6. **Monitor OVER bias** — Jan 31 models show 53% OVER rate; verify this matches actual market movement
7. **Decision point**: If Jan 31 defaults sustains 53%+ HR over 2+ weeks AND champion stays below 50%, promote:
   - Update `CATBOOST_V9_MODEL_PATH` env var to Jan 31 defaults GCS path
   - Adjust subset definitions: lower edge thresholds from 3+/5+ to 1.5+/3+
   - Recalibrate signal system for new model characteristics

### P3 (Future)
8. **Signal recalibration** — 9 of 15 recent days RED. Signal thresholds were tuned for champion's prediction distribution (stddev 2.23). Jan 31 model's tighter distribution (stddev ~1.0) needs different thresholds.
9. **Subset redefinition** — Create challenger-specific subsets, or generalize existing ones to work across models
10. **Monthly retrain cadence** — train through end of February, eval first week of March
11. **Update CLAUDE.md** — model section needs Session 179 analysis results
