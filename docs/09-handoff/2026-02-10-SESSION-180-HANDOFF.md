# Session 180 Handoff

**Date:** 2026-02-10
**Previous:** Session 179

---

## What Was Done

### 1. P0: Graded Feb 9 Predictions
- Found `nbac_gamebook_player_stats` had 0 records for Feb 9 — gamebook scraper hadn't fired yet (runs at 4 AM ET, session started at 1:30 AM ET)
- **Workaround:** `nbac_player_boxscores` had 211 records (scraped at 06:08 UTC). Manually triggered Phase 3 via `/process-date-range`:
  - First call: TeamOffense + TeamDefense succeeded (20 records each), PlayerGameSummary failed (dependency race)
  - Second call: PlayerGameSummary succeeded (209 records)
- Triggered grading via Pub/Sub — all 4 models graded for Feb 9

### 2. P1: Verified Feb 10 Live Predictions
- No predictions generated — 0 prop lines available for Feb 10 (normal, lines come later in the day)
- Phase 4 feature store has 79 records ready for Feb 10
- Prediction coordinator triggered but completed with 0 predictions (REAL_LINES_ONLY mode)
- **Action needed:** Re-trigger predictions once prop lines arrive

### 3. P2: Updated 4-Way Model Comparison (Feb 4-9, n=301 matched actionable)

| Model | HR | MAE | Vegas Bias | Stddev | OVER% |
|-------|-----|------|-----------|--------|-------|
| **Champion** (`catboost_v9`) | **49.5%** | 5.35 | -0.03 | 2.79 | 46.5% |
| Jan 8 (`_train1102_0108`) | 50.5% | 4.99 | -0.16 | 1.32 | 45.5% |
| Jan 31 defaults (`_train1102_0131`) | 54.2% | 4.90 | 0.00 | 1.07 | 49.2% |
| **Jan 31 tuned** (`_train1102_0131_tuned`) | **55.1%** | **4.89** | +0.03 | 1.12 | 50.8% |

**Daily breakdown (actionable):**

| Date | n (champ/chall) | Champion | Jan 8 | Jan 31 | Jan 31 Tuned |
|------|---------|----------|-------|--------|--------------|
| Feb 4 | 63/96 | 58.7% | 61.5% | 60.4% | **62.5%** |
| Feb 5 | 60/101 | 55.0% | 54.5% | **58.4%** | 55.4% |
| Feb 6 | 41/69 | 41.5% | 43.5% | **52.2%** | 44.9% |
| Feb 7 | 91/131 | 45.1% | 48.9% | 51.1% | **51.9%** |
| Feb 8 | 36/52 | 41.7% | 50.0% | 50.0% | **51.9%** |
| Feb 9 | 33/52 | 48.5% | **51.9%** | 42.3% | 48.1% |

**Disagreement analysis:**

| Comparison | Agreement | n | Champion HR | Challenger HR | Gap |
|-----------|-----------|---|-------------|---------------|-----|
| vs Defaults | AGREE | 217 | 52.5% | 52.5% | 0 |
| vs Defaults | DISAGREE | 84 | 41.7% | **58.3%** | **+16.6pp** |
| vs Tuned | AGREE | 230 | 53.0% | 53.0% | 0 |
| vs Tuned | DISAGREE | 71 | 38.0% | **62.0%** | **+24.0pp** |

### 4. Investigated Gamebook Scraper "Gap"
- **No gap found.** Gamebook scraper runs via `post_game_window_3` (4 AM ET / 09:00 UTC) and `morning_recovery` (6 AM ET / 11:00 UTC)
- Session started at ~1:30 AM ET — gamebook workflows hadn't fired yet
- The 04:00 UTC failure in logs was a separate direct scheduler call for today's date (no games) — expected behavior
- Gamebook scraper will auto-fire for Feb 9 games at 4 AM ET

### 5. Key Findings

- **Jan 31 tuned now leads** — overtook defaults (55.1% vs 54.2%)
- **Tuned has strongest disagreement signal** — when it disagrees with champion, it wins 62% vs 38% (+24pp)
- **Champion continues to decay** — producing fewer actionable picks (33-63/day vs challengers' 52-131) and losing on every metric
- **Feb 9 was a leveling day** — Jan 31 defaults had worst day (42.3%), Jan 8 best (51.9%), tuned in middle (48.1%)
- **Important note on hit rate calculation:** Champion predictions include many PASS (non-actionable) results. Session 179 reported 49.8% overall; matched actionable-only is 49.5%. The 29.7% "overall" number includes PASS predictions (prediction_correct=NULL) treated as losses — always filter to prediction_correct IS NOT NULL for accurate HR.

---

## Current Shadow Deployment

| # | system_id | Training | Status | Graded (actionable) |
|---|-----------|----------|--------|---------------------|
| 1 | `catboost_v9` | Nov 2 - Jan 8 | **CHAMPION** (decaying) | ~324 |
| 2 | `catboost_v9_train1102_0108` | Nov 2 - Jan 8 | Shadow | ~501 |
| 3 | `catboost_v9_train1102_0131` | Nov 2 - Jan 31 | Shadow | ~501 |
| 4 | `catboost_v9_train1102_0131_tuned` | Nov 2 - Jan 31 | Shadow | ~501 |

---

## Files Modified

- `docs/09-handoff/2026-02-10-SESSION-180-HANDOFF.md` — This file
- `docs/09-handoff/NEXT-SESSION-PROMPT.md` — Updated next session prompt

*No code changes this session — all work was operational (grading, analysis, investigation).*

---

## What Still Needs Doing

### P0 (Immediate — next session)
1. **Re-trigger Feb 10 predictions** once prop lines available:
   ```sql
   -- Check if props exist yet
   SELECT COUNT(*) FROM nba_raw.odds_api_player_points_props WHERE game_date = '2026-02-10'
   ```
   If >0, trigger:
   ```bash
   TOKEN=$(gcloud auth print-identity-token) && curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
     -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
     -d '{"game_date":"2026-02-10","prediction_run_mode":"REAL_LINES_ONLY"}'
   ```

2. **Backfill challengers for Feb 10:**
   ```bash
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 --start 2026-02-10 --end 2026-02-10
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131 --start 2026-02-10 --end 2026-02-10
   PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131_tuned --start 2026-02-10 --end 2026-02-10
   ```

3. **Grade Feb 10** once games complete:
   ```bash
   gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-10","trigger_source":"manual"}' --project=nba-props-platform
   ```

### P1 (After grading)
4. **Run updated comparison** with Feb 10 included:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
   ```

### P2 (Promotion Decision — ~Feb 17-20)
5. **Track Jan 31 tuned vs defaults** — tuned now slightly leads (55.1% vs 54.2%) with stronger disagreement signal (+24pp vs +16.6pp). Need 1-2 more weeks of data.
6. **Decision criteria for promotion:**
   - Sustained HR > 53% over 2+ weeks
   - Champion stays below 50%
   - Sufficient edge 3+ sample (currently only 6 across all Jan 31 predictions — very low)
7. **If tuned wins:** Update `CATBOOST_V9_MODEL_PATH` env var, recalibrate subsets (lower edge thresholds to 1.5+/2+ from 3+/5+), recalibrate signal system for tighter prediction distribution (stddev ~1.0 vs 2.2)

### P3 (Future)
8. **Signal recalibration** — 9 of 15 recent days RED. Signal tuned for champion's wider distribution
9. **Subset redefinition** — create model-agnostic subsets or challenger-specific ones
10. **Monthly retrain** — train through end of February, eval first week of March
