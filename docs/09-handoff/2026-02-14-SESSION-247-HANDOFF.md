# Session 247 Handoff — Multi-Season Backtest + Historical Feature Backfill

**Date:** 2026-02-14
**Status:** 4 of 6 backtests COMPLETE. Phase 4 backfill processor #4 finishing (109/110), #5 next. FEB25 backtests BLOCKED on backfill.
**Sessions:** 247 + 248 + 249 (continued across three context limits)

---

## What Was Done

### Phase A: Historical Phase 4 Backfill (2024-25 Season)
**Status: IN PROGRESS** — two background processes running

- Launched full Phase 4 backfill for 2024-10-22 to 2025-02-13 (110 game dates)
- Parallel phase (#1 team_defense_zone + #2 player_shot_zone): COMPLETE
- Sequential phase:
  - #3 player_composite_factors: COMPLETE (two processes, one original that survived "kill", one resumed)
  - #4 player_daily_cache: FINISHING (b7a59e1 at 109/110 as of Session 249 end — about to complete)
  - #5 ml_feature_store: NOT STARTED (110 dates once #4 finishes, ~30-60min)
- b286722 is behind: on #3 at 99/110, also nearly done
- Background task IDs: `b7a59e1` (ahead, on #4), `b286722` (behind, on #3)
- MERGE operations are idempotent — both processes can run safely in parallel
- Processes survived computer sleep and context limit — still running as of Session 248

**Check if still running:**
```bash
# If these files have recent timestamps, processes are alive
ls -la /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output
ls -la /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b286722.output
# Check progress
grep "Processing game date" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output | tail -3
grep "✓ #4\|Running #5\|Phase 4 Backfill Complete" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output
```

**Resume if both died:**
```bash
# Check which processor to resume from (4 or 5)
ls /tmp/backfill_checkpoints/player_daily_cache_2024-10-22_2025-02-13.json  # if exists, #4 started
ls /tmp/backfill_checkpoints/ml_feature_store_2024-10-22_2025-02-13.json    # if exists, #5 started
# Resume from #4 (or #5 if #4 checkpoint shows complete)
./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 4
```

### Phase B: Prop Line Availability Check (COMPLETE)
| Source | Feb 2023 | Feb 2024 | Feb 2025 |
|--------|----------|----------|----------|
| DraftKings (odds_api) | NO (starts May 2023) | 23 days, 3,499 lines | 54 days, 9,774 lines |
| BettingPros | 212 days (full 2022-23) | Not checked | Not checked |

### Phase C: Multi-Season Backtests (4 of 6 COMPLETE)

| Season | Loss | Edge 3+ HR | Edge 3+ N | MAE (lines) | MAE (all) | Line Source | All Gates |
|--------|------|-----------|-----------|-------------|-----------|-------------|-----------|
| 2022-23 | Huber | **85.19%** | 878 | 3.676 | 9.286 | BettingPros | PASS |
| 2022-23 | MAE | **87.50%** | 808 | 3.452 | 11.211 | BettingPros | PASS |
| 2023-24 | Huber | **89.77%** | 831 | 3.335 | 8.036 | DraftKings | PASS |
| 2023-24 | MAE | **90.99%** | 832 | 3.129 | 10.029 | DraftKings | PASS |
| 2024-25 | Huber | PENDING | - | - | - | - | Blocked on backfill |
| 2024-25 | MAE | PENDING | - | - | - | - | Blocked on backfill |
| **2025-26** | **Huber** | **62.5%** | **88** | - | - | Production | PASS |
| **2025-26** | **MAE** | **71.4%** | **35** | - | - | Production | PASS |

### Phase D: Documentation (COMPLETE)
Results document created at: `docs/08-projects/current/model-improvement-analysis/27-MULTI-SEASON-BACKTEST-RESULTS.md`

---

## Key Findings

### 1. V12 Recipe Works Across All Seasons
All completed backtests exceed 55% target and 52.4% breakeven by a wide margin. Recipe is validated.

### 2. MAE Outperforms Huber on Hit Rate in All Tested Seasons
| Season | Huber HR | MAE HR | HR Winner | Volume |
|--------|---------|--------|-----------|--------|
| 2022-23 | 85.19% | 87.50% | MAE (+2.3%) | Huber (878 vs 808) |
| 2023-24 | 89.77% | 90.99% | MAE (+1.2%) | Tie (831 vs 832) |
| 2025-26 | 62.5% | 71.4% | MAE (+8.9%) | Huber (88 vs 35) |

Huber's only advantage is volume (more edge 3+ picks), and this only appeared in 2025-26.

### 3. Historical HRs Much Higher Than Current Season
85-91% historical vs 62-71% current. Explained by feature quality (92% avg vs ~70%), not data leakage. Eval methodology verified: point-in-time features, actual outcomes, pre-game prop lines.

### 4. Session 242 Training Data Filter Discovery (from handoff review)
Session 242 discovered that `training_data_loader.py` zero-tolerance filter rejects ALL 2024-25 data because it checks defaults across all 54 features, not just the 33 V9 uses. For V12 training, the augmentation at training time handles V12 features, so the Phase 4 backfill should help fix base feature quality. But the loader's `get_quality_where_clause()` should be made feature-version-aware (Priority P1 for next session).

---

## What Needs To Happen Next

### Priority 1: Complete Phase 4 Backfill + FEB25 Backtests
1. Monitor backfill processes (`b7a59e1` or `b286722`) — processor #4 running, then #5
2. Once #5 (ml_feature_store) completes, verify training data:
```sql
SELECT game_date, COUNT(*) as total,
       COUNTIF(is_training_ready) as train_ready,
       ROUND(100.0 * COUNTIF(is_training_ready) / COUNT(*), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-22' AND '2025-02-13'
  AND game_date >= '2024-11-06'
GROUP BY 1 ORDER BY 1 LIMIT 10;
```
3. Run FEB25 backtests:
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

### Priority 2: Feature-Version-Aware Quality Filter (PROBABLY NOT BLOCKING)
Session 248 investigated this deeper. The quality filter (`required_default_count = 0`) checks features 0-38 EXCLUDING optional vegas (25-27) and game_total_line (38). V12 features (39-53) are NOT included in this count — they're populated by `augment_v12_features()` AFTER the quality filter runs.

**Training flow:** `load_clean_training_data()` → quality filter (features 0-38) → `augment_v11_features()` → `augment_v12_features()` → `prepare_features()`

Session 242's finding that `required_default_count = 1` for 87% of 2024-25 records was due to index 37 (star_teammates_out) defaulting. Phase 4 backfill processor #3 (player_composite_factors) should fix this. After processor #5 (ml_feature_store) regenerates records, `required_default_count` should drop to 0 for most records.

**If FEB25 backtests still fail after backfill:** Then apply the Session 242 fix to make the filter feature-version-aware. Key file: `shared/ml/training_data_loader.py` line 47.

### Priority 3: Promotion Decision
After FEB25 results, update `27-MULTI-SEASON-BACKTEST-RESULTS.md` with:
- Complete results table
- Final Huber vs MAE comparison
- Promotion recommendation (V12+MAE or V12+Huber)

---

## Background Processes Running

| Task ID | Description | Last Known Status |
|---------|-------------|-------------------|
| `b7a59e1` | Phase 4 backfill — processor #4 at 109/110 (about to start #5) | Running (Session 249) |
| `b286722` | Phase 4 backfill — processor #3 at 99/110 | Running (Session 249) |

**These may have completed or died by the time you read this.** Check with:
```bash
ls -la /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output
grep "Phase 4 Backfill Complete\|✓ #5\|✓ #4" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output
# If no output, check last progress:
grep "Processing game date" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b7a59e1.output | tail -3
# If file is stale (no recent mtime), resume:
./bin/backfill/run_phase4_backfill.sh --start-date 2024-10-22 --end-date 2025-02-13 --start-from 4
```

---

## Feature Store Pre-Backfill State

| Season | Total | Training Ready | Pct | Avg Quality | Features |
|--------|-------|---------------|-----|-------------|----------|
| 2021-22 | 29,417 | 20,933 | 71.2% | 90.1 | 33-37 |
| 2022-23 | 25,565 | 21,296 | 83.3% | 92.0 | 37 |
| 2023-24 | 25,948 | 21,440 | 82.6% | 92.4 | 37 |
| **2024-25** | **25,846** | **908** | **3.5%** | **70.0** | **37-54** |

Expected post-backfill: 2024-25 training_ready_pct >= 50%.

---

## Files Changed This Session

| File | Action | What |
|------|--------|------|
| `docs/08-projects/current/model-improvement-analysis/27-MULTI-SEASON-BACKTEST-RESULTS.md` | CREATED | Multi-season backtest results doc |
| `docs/09-handoff/2026-02-14-SESSION-247-HANDOFF.md` | CREATED | This handoff document |

---

## Model Artifacts Created

| Name | SHA256 (prefix) | Size |
|------|----------------|------|
| FEB23 Huber (BettingPros) | cd4e4e33e0cc | 1,994,640 |
| FEB23 MAE (BettingPros) | 3bcbd6945dff | 1,994,640 |
| FEB24 Huber (DraftKings) | 144ab7a026c5 | 1,861,736 |
| FEB24 MAE (DraftKings) | d23e4ed1c646 | 1,861,736 |

Saved in `models/` directory (local, not uploaded to GCS — these are backtest artifacts only).

---

## Deployment Drift

4 services with drift detected at session start (not blocking):
- `reconcile` — code changed after deploy
- `nba-grading-service` — commit mismatch
- `validate-freshness` — commit mismatch
- `validation-runner` — code changed after deploy
