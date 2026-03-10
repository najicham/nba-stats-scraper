# Session 449 Handoff — Multi-Season Backfill + Pitcher Watchlist System

*Date: 2026-03-09*

## What Was Done

### 1. Season Replay (2025) — Improved Results
Ran fresh 2025 season replay with updated statcast/ballpark data:
- **BB HR: 65.5%** (300-158) — up from 62.4% last session
- **Ultra HR: 81.5%** (53-12) — up from 76.0%
- **Bankroll: +183u, ROI 35%**
- Results in `results/mlb_season_replay_449/`

### 2. MLB Pitcher Watchlist System — BUILT
Full shadow pick tracking + dynamic blacklist management:

**Files created/modified:**
| File | Change |
|------|--------|
| `ml/signals/mlb/best_bets_exporter.py` | Added shadow pick tracking for blacklisted pitchers |
| `data_processors/grading/mlb/main_mlb_grading_service.py` | Added `_backfill_shadow_picks()` grading backfill |
| `orchestration/cloud_functions/mlb_pitcher_watchlist/main.py` | **NEW** — Weekly watchlist evaluator CF |
| `orchestration/cloud_functions/mlb_pitcher_watchlist/requirements.txt` | **NEW** |
| `tests/mlb/test_shadow_picks.py` | **NEW** — 10 tests, all passing |
| `scripts/mlb/backfill_pitcher_stats.py` | **NEW** — Backfill pitcher stats from MLB API |

**BQ Tables created:**
- `mlb_predictions.blacklist_shadow_picks` — partitioned by game_date
- `mlb_predictions.pitcher_watchlist` — partitioned by evaluation_date

**How it works:**
1. Exporter records shadow picks when blacklist blocks a pitcher (full signal evaluation + rank position)
2. After grading, `_backfill_shadow_picks()` fills in actuals from prediction_accuracy
3. Weekly CF evaluates: ADD (BB HR < 45%, N >= 8), REMOVE (shadow HR >= 60%, N >= 8)
4. Slack digest to `#nba-alerts` with recommendations (manual approval required)

**Still TODO for watchlist:**
- Deploy CF: `./bin/deploy-function.sh mlb-pitcher-watchlist`
- Create Cloud Scheduler: weekly Monday 10 AM ET, April-October
- Set `SLACK_WEBHOOK_URL_ALERTS` env var on the CF

### 3. Multi-Season Backfill — IN PROGRESS

**Goal:** Backfill 2022-2023 data so we can run multi-season replay to validate strategy isn't overfit to 2025.

**Completed backfills:**
| Data | 2022 | 2023 | Status |
|------|------|------|--------|
| `mlb_raw.mlbapi_pitcher_stats` | 21,117 rows | 21,277 rows | **DONE** |
| `mlb_raw.mlb_pitcher_stats` (copy) | 21,117 rows | 21,277 rows | **DONE** (game_id = `YYYY-MM-DD_UNK_UNK`) |
| `mlb_raw.mlb_schedule` | 2,459 games | 2,475 games | **DONE** (9,881 total across 4 seasons) |
| `mlb_raw.fangraphs_pitcher_season_stats` | ~850 rows | ~850 rows | **DONE** (5,120 total across 4 seasons) |

**Still running (background processes):**

#### pitcher_game_summary processor (CRITICAL — must finish before replay)
```bash
# Check progress:
grep "Processed" /tmp/mlb-backfill-logs/pgs_2022.log | tail -1
grep "Processed" /tmp/mlb-backfill-logs/pgs_2023.log | tail -1

# Check BQ:
bq query --use_legacy_sql=false "
SELECT EXTRACT(YEAR FROM game_date) as season, COUNT(DISTINCT game_date) as dates, COUNT(*) as total
FROM mlb_analytics.pitcher_game_summary WHERE game_date >= '2022-01-01'
GROUP BY 1 ORDER BY 1"
```
- **2022**: ~79/179 dates done when session ended (~45%)
- **2023**: ~74/182 dates done when session ended (~41%)
- **ETA**: ~15-20 more minutes each
- **Expected when done**: ~5,000 rows per season, ~180 dates each

**If PGS processes died**, restart with:
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper SPORT=mlb nohup /home/naji/code/nba-stats-scraper/.venv/bin/python /home/naji/code/nba-stats-scraper/data_processors/analytics/mlb/pitcher_game_summary_processor.py --start-date 2022-04-07 --end-date 2022-10-05 > /tmp/mlb-backfill-logs/pgs_2022.log 2>&1 &

PYTHONPATH=/home/naji/code/nba-stats-scraper SPORT=mlb nohup /home/naji/code/nba-stats-scraper/.venv/bin/python /home/naji/code/nba-stats-scraper/data_processors/analytics/mlb/pitcher_game_summary_processor.py --start-date 2023-03-30 --end-date 2023-10-01 > /tmp/mlb-backfill-logs/pgs_2023.log 2>&1 &
```
**CRITICAL: Must set `SPORT=mlb`** or processor reads from `nba_raw` instead of `mlb_raw`.

#### Statcast backfills (NICE-TO-HAVE — not blocking replay)
```bash
# Check statcast progress:
tail -1 /tmp/mlb-backfill-logs/statcast_2022.log
tail -1 /tmp/mlb-backfill-logs/statcast_2023.log
tail -1 /tmp/mlb-backfill-logs/statcast_2024_gap.log
tail -1 /tmp/mlb-backfill-logs/statcast_2025_gap.log
```
- Baseball Savant is slow (~2s per day + timeouts). Will take hours.
- **Not blocking** — training SQL uses `COALESCE(statcast, season_avg)` fallback.
- After raw statcast completes, `pitcher_rolling_statcast` analytics also needs reprocessing.

### 4. Key Fixes/Discoveries
- **`mlb_pitcher_stats` vs `mlbapi_pitcher_stats`**: Two different tables with different schemas. PGS processor reads `mlb_pitcher_stats`. Backfill script writes to `mlbapi_pitcher_stats`. Solution: INSERT...SELECT with column mapping, set `game_id = 'YYYY-MM-DD_UNK_UNK'`.
- **`SPORT=mlb` env var**: Required for all MLB analytics processors. Without it, `sport_config.py` defaults to `nba` and reads from wrong dataset.

## What's Next (Priority Order)

### 1. Verify PGS Backfill Completed
Check that `pitcher_game_summary` has ~5,000 rows per season for 2022 and 2023:
```bash
bq query --use_legacy_sql=false "
SELECT EXTRACT(YEAR FROM game_date) as season, COUNT(DISTINCT game_date) as dates, COUNT(*) as total
FROM mlb_analytics.pitcher_game_summary WHERE game_date >= '2022-01-01'
GROUP BY 1 ORDER BY 1"
```

### 2. Run Multi-Season Replay
Validate strategy across 4 seasons — the big test for overfitting:
```bash
# 2022 season
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2022-05-01 --end-date 2022-09-28 \
    --output-dir results/mlb_season_replay_2022/

# 2023 season
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2023-05-01 --end-date 2023-09-28 \
    --output-dir results/mlb_season_replay_2023/

# 2024 season
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2024-05-01 --end-date 2024-09-28 \
    --output-dir results/mlb_season_replay_2024/
```
2025 already done: `results/mlb_season_replay_449/` (65.5% BB HR)

**Evaluation framework:**
- **Layer 1 (must work cross-season):** Model arch, edge floor, probability caps, core filters, core signals
- **Layer 2 (season-adaptive):** Pitcher blacklist (dynamic via watchlist), signal weights, whole-number line filter
- Compare BB HR, Ultra HR, ROI across all 4 seasons
- Flag any parameter that only works in 2025

**NOTE:** The replay script's `PITCHER_BLACKLIST` is 2025-specific. For honest cross-season testing, consider running with NO blacklist first to see base performance, then with blacklist to measure the lift.

**NOTE:** 2022 and 2023 have NO prop lines data for the first ~3 weeks (April) because `bp_pitcher_props` coverage starts ~April. Use `--start-date` at May 1 for cleaner comparison.

### 3. Season-Specific Indicators
User wants to identify signals that are season-specific vs universal:
- Run each signal's lift per season independently
- Some signals may be era-dependent (K rates change year to year)
- League-level K rate, pace of play rules, dead ball era shifts

### 4. Deploy Watchlist CF + Prepare for 2026 Season
- Deploy `mlb-pitcher-watchlist` CF
- Mar 18-23: Train final model
- Mar 24: Resume schedulers
- Mar 27: Opening Day

## Existing Tests
- `tests/mlb/test_shadow_picks.py` — 10 tests passing
- `tests/mlb/test_exporter_with_regressor.py` — 19 tests passing

## No Code Was Pushed
All changes are local only. The following need to be committed:
- Watchlist system (exporter changes, grading backfill, CF, tests)
- `backfill_pitcher_stats.py` script
- This handoff doc
