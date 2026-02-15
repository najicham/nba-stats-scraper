# Session 250 Handoff — Backfill Monitoring + Decimal Bug Fix

**Date:** 2026-02-14
**Status:** Phase 4 backfill still running (b286722). One bug fixed. FEB25 backtests BLOCKED on backfill completion.
**Sessions:** 247-250 (continued across four context limits)

---

## What Was Done This Session

### 1. Bug Fix: decimal.Decimal TypeError in feature_extractor.py
**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py` line 886
**Bug:** `unsupported operand type(s) for +=: 'float' and 'decimal.Decimal'`
**Root cause:** BigQuery returns `minutes_played` as `decimal.Decimal`, but accumulators `minutes_in_7d`/`minutes_in_14d` were initialized as `float`. Python doesn't support `float += Decimal`.
**Fix:** Wrapped with `float()`: `mins = float(g.get('minutes_played', 0) or 0)`
**Impact:** ~28 players per game date were failing (mostly bench players with 1-3 historical games). NOT YET COMMITTED.

### 2. Backfill Monitoring
- Confirmed both background processes were running initially
- `b7a59e1` DIED during processor #5 (ml_feature_store) at game date 15/110
- `b286722` still ALIVE, progressing through processor #4

---

## Current State

### Background Process b286722 (ALIVE)
- **Processor:** #4 player_daily_cache
- **Progress:** 36/110 (2024-11-27) as of session end
- **After #4:** Will automatically start #5 (ml_feature_store) — 110 more dates
- **Note:** Early dates (Oct-Nov 2024) show `INSUFFICIENT_DATA` for player_daily_cache — this is expected for season start (no historical games yet)

### Background Process b7a59e1 (DEAD)
- Died on processor #5 (ml_feature_store) at game date 15/110
- No need to restart — b286722 will cover all the same work when it reaches #5
- If you want to speed up, start a parallel #5-only backfill (see commands below)

### Uncommitted Change
- `data_processors/precompute/ml_feature_store/feature_extractor.py` — decimal.Decimal fix (line 886)

---

## What Needs To Happen Next

### Priority 1: Wait for b286722 to Finish + Commit Bug Fix

**Check b286722 progress:**
```bash
grep "✓ #\|Running #" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b286722.output | tail -5
grep "Processing game date" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b286722.output | tail -3
# Check if still alive:
stat --format="%Y %s" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b286722.output
# Wait 5 sec, run again — if file size grows, it's alive
```

**Commit the bug fix:**
```bash
git add data_processors/precompute/ml_feature_store/feature_extractor.py
git commit -m "fix: cast BigQuery Decimal to float in feature_extractor minutes accumulation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

**If b286722 died, resume from wherever it stopped:**
```bash
# Check which processor it was on
grep "✓ #\|Running #" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b286722.output | tail -3
# Resume (change --start-from based on which processor needs to continue)
./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 4
# Or if #4 finished, start from #5:
./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 5
```

**Optional: speed up by launching parallel #5:**
```bash
./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 5
```

### Priority 2: After Backfill Complete — Verify 2024-25 Data Quality

```sql
SELECT COUNT(*) as total,
       COUNTIF(COALESCE(required_default_count,0)=0) as clean,
       ROUND(100.0*COUNTIF(COALESCE(required_default_count,0)=0)/COUNT(*),1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-11-06' AND '2025-01-31';
```

Expected: clean% > 50% (was 3.5% pre-backfill due to missing composite factors for feature index 37).

### Priority 3: Run FEB25 Backtests (Both in Parallel)

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MULTISEASON_FEB25_HUBER" \
  --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2024-11-01 --train-end 2025-01-31 \
  --eval-start 2025-02-01 --eval-end 2025-02-28 \
  --walkforward --include-no-line --force --skip-register

PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MULTISEASON_FEB25_MAE" \
  --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
  --train-start 2024-11-01 --train-end 2025-01-31 \
  --eval-start 2025-02-01 --eval-end 2025-02-28 \
  --walkforward --include-no-line --force --skip-register
```

### Priority 4: Update Results + Promotion Decision

Update `docs/08-projects/current/model-improvement-analysis/27-MULTI-SEASON-BACKTEST-RESULTS.md` with FEB25 results.

**Completed backtests so far (4/6):**

| Season | Loss | Edge 3+ HR | Edge 3+ N | Line Source |
|--------|------|-----------|-----------|-------------|
| 2022-23 | Huber | 85.19% | 878 | BettingPros |
| 2022-23 | MAE | 87.50% | 808 | BettingPros |
| 2023-24 | Huber | 89.77% | 831 | DraftKings |
| 2023-24 | MAE | 90.99% | 832 | DraftKings |
| 2024-25 | Huber | PENDING | - | Blocked on backfill |
| 2024-25 | MAE | PENDING | - | Blocked on backfill |

### Priority 5 (If Backtests Fail on Data Quality)

If FEB25 backtests get 0 training rows, the quality filter in `shared/ml/training_data_loader.py` line 47 (`get_quality_where_clause()`) may need to be made feature-version-aware. It checks `required_default_count = 0` across features 0-38 excluding vegas. If feature 37 (star_teammates_out) still defaults after backfill, this filter will reject all 2024-25 data. See Session 242 handoff for details.

### Priority 6: Re-backfill Decimal-Affected Players

After b286722 finishes processor #5 (which uses the OLD code without the fix), ~28 players per date will have missing feature store entries. Options:
1. **Re-run processor #5 only** with the fixed code after committing:
   ```bash
   ./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 5
   ```
2. **Skip for now** — affected players are mostly bench (Bronny James, Jeff Green, etc.) unlikely to appear in prop bets. Can re-backfill later if needed.

---

## Key Context from Previous Sessions (247-249)

- V12 recipe validated across 3 seasons (85-91% HR historical, 62-71% current)
- MAE outperforms Huber on hit rate in all tested seasons
- Training data flow: `load_clean_training_data()` → quality filter (features 0-38) → `augment_v11_features()` → `augment_v12_features()` → `prepare_features()`
- MERGE operations are idempotent — safe to run multiple backfills in parallel

---

## Deployment Drift (Not Blocking)

4 services with drift (from session 247, not addressed):
- `reconcile`, `nba-grading-service`, `validate-freshness`, `validation-runner`
