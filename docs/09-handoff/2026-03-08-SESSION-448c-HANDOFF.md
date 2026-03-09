# Session 448c Handoff — MLB Feature Store Audit + Statcast Backfill

*Date: 2026-03-08*

## What Was Done

### 1. Complete MLB Feature Store Audit
Traced all 36 training features to their upstream data sources and measured coverage rates on 5,695 training rows:

| Feature Group | Features | Source Table | Coverage |
|---------------|----------|-------------|----------|
| Rolling K stats | f00-f04 | pitcher_game_summary | 100% |
| Season stats | f05-f09 | pitcher_game_summary | 100% |
| Game context | f10, f25 | pitcher_game_summary | 100% |
| Opponent K rate | f15 | pitcher_game_summary | 100% |
| Ballpark K factor | f16 | pitcher_game_summary (venue history) | 100% |
| SwStr%/CSW% | f19, f19b | fangraphs_pitcher_season_stats | 99.6% |
| Workload | f20-f23 | pitcher_game_summary | 100% |
| Line-relative | f30, f32 | bp_pitcher_props | 100% |
| Projections | f40-f44 | bp_pitcher_props | 100% |
| **Statcast rolling** | **f50-f53** | **pitcher_rolling_statcast** | **91.3% → ~98%+ (backfilling)** |
| Vs opponent | f65-f66 | pitcher_game_summary | 46.3% (improves in-season) |
| Deep workload | f68 | pitcher_game_summary | 100% |
| FanGraphs advanced | f70-f73 | fangraphs_pitcher_season_stats | 99.6% |

### 2. Ballpark Factors Loaded — COMPLETE
- `mlb_reference.ballpark_factors` was **empty** — loaded 60 rows (30 teams x 2025 + 2026)
- Script: `scripts/mlb/backfill_ballpark_factors.py`

### 3. Statcast Backfill — IN PROGRESS (background tasks)
Two backfill processes were started and are **still running in the background**:

```bash
# 2024 season (was at day 26/186 when session ended)
PYTHONPATH=. .venv/bin/python scripts/mlb/backfill_statcast.py --start 2024-03-28 --end 2024-09-29 --sleep 2

# 2025 Apr-Jun gap (was at day 25/96 when session ended)
PYTHONPATH=. .venv/bin/python scripts/mlb/backfill_statcast.py --start 2025-03-27 --end 2025-06-30 --sleep 2
```

**Before backfill:** Only Jul-Sep 2025 existed (9,629 rows).
**After completion:** Full 2024 + 2025 coverage (~35,000+ rows).
**Occasional Baseball Savant timeouts** (~16 min stall) but script recovers and continues. Those dates get logged as "no games" but can be re-run for missing dates.

**Check if backfills completed:**
```bash
bq query --use_legacy_sql=false '
SELECT FORMAT_DATE("%Y-%m", game_date) as month, COUNT(*) as rows, COUNT(DISTINCT game_date) as days
FROM mlb_raw.statcast_pitcher_daily WHERE game_date >= "2024-01-01"
GROUP BY 1 ORDER BY 1'
```

**Expected when complete:** 18 months of data (2024-03 through 2025-09), each month having 25-31 game days.

**If backfill died or missed dates**, re-run for missing ranges:
```bash
PYTHONPATH=. .venv/bin/python scripts/mlb/backfill_statcast.py --start YYYY-MM-DD --end YYYY-MM-DD --sleep 3
```

### 4. Identified Dead/Empty Tables (Not Blocking)

| Table | Status | Why It's OK |
|-------|--------|-------------|
| `oddsa_game_lines` | 0 rows | Game totals already in `pitcher_game_summary` |
| `mlbapi_pitcher_stats` | 0 rows | Stats come from game feed scraper |
| `bdl_player_versus` | 0 rows | BDL retired; vs_opponent derived from game history |
| `pitcher_ml_features` | 0 rows | Phase 4 feature store bypassed — training queries BQ directly |
| `bdl_pitcher_splits` | 972 rows (dead) | PGS computes splits from actual games |

### 5. Updated Season Plan Doc
`docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md` — added complete data audit, coverage table, backup assessment, new feature recommendations.

## What's Next (Priority Order)

### 1. Verify Statcast Backfill Completed
Run the check query above. If months are missing, re-run the backfill script for those date ranges.

### 2. Reprocess pitcher_rolling_statcast
The `pitcher_rolling_statcast` analytics table derives rolling metrics from `statcast_pitcher_daily`. It needs to be reprocessed to pick up the newly backfilled raw data for 2024 and early 2025. Check current coverage:
```bash
bq query --use_legacy_sql=false '
SELECT FORMAT_DATE("%Y-%m", game_date) as month, COUNT(*) as rows
FROM mlb_analytics.pitcher_rolling_statcast WHERE game_date >= "2024-01-01"
GROUP BY 1 ORDER BY 1'
```
If 2024 months are already covered (they showed 39,918 rows from 2024-03 to 2025-10), the analytics processor may already be using a different data source. Verify before re-running.

### 3. Run Season Replay
Compare BB HR with improved Statcast coverage vs the baseline (63.4% / V6 from Session 444):
```bash
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py
```

### 4. Optional: Build Catcher Framing Scraper
The only genuinely new feature worth testing. Elite catchers add ~0.5 K/game. Shadow signal `catcher_framing_over` exists but has no data source. Baseball Savant has framing data via pybaseball.

**Caveat:** Dead ends doc shows 14/14 derived features were NOISE for CatBoost. Catcher framing is the strongest candidate because it's genuinely new information not captured anywhere.

### 5. Follow Season Plan Timeline
- Mar 18-23: Train final model (`scripts/mlb/training/train_regressor_v2.py --training-end 2026-03-20 --window 120`)
- Mar 24: Resume all 24 schedulers (`./bin/mlb-season-resume.sh`)
- Mar 27: Opening Day

## Key Context

- **36 features, NOT 35** — Session 444 removed 5 dead features. `FEATURE_COLS` in `scripts/mlb/training/train_regressor_v2.py` is source of truth.
- **Training SQL bypasses the feature store** — joins `bp_pitcher_props` + `pitcher_game_summary` + `statcast_rolling` + `fangraphs` directly. `pitcher_ml_features` being empty is expected.
- **BDL is fully retired** — Phase 4 processor methods return `{}` for dead BDL tables. Doesn't affect training.
- **No Reddit scraping needed** — dead ends doc confirms derived features are noise.
- **No code was pushed** — backfill script and doc updates are local only.

## Files Modified/Created

| File | Change |
|------|--------|
| `scripts/mlb/backfill_ballpark_factors.py` | **NEW** — loads park factors to BQ |
| `docs/08-projects/current/mlb-2026-season-strategy/06-SEASON-PLAN-2026.md` | Updated with full data audit |
| `docs/09-handoff/2026-03-08-SESSION-448c-HANDOFF.md` | This file |
