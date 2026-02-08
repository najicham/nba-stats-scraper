# Session 158 Handoff — Training Data Quality Prevention + Phase 6 Export Redesign

**Date:** 2026-02-08
**Focus:** Contamination prevention, monitoring, backfill, and consolidated Phase 6 exports
**Status:** Code complete, backfill in progress, nothing committed/pushed yet

## TL;DR for Next Session

1. Check if current-season backfill finished (PID 3383866)
2. Verify contamination dropped: `./bin/monitoring/check_training_data_quality.sh`
3. Commit all changes, push to main (auto-deploys)
4. Start past-seasons backfill
5. Export Phase 6 season file
6. Wire `season-subsets` export into daily orchestration

---

## What Was Done

### Part A: Training Data Quality Prevention

Session 157 discovered **33.2% of V9 training data was contaminated** with default feature values. This session added four prevention layers:

#### 1. Fixed Backfill Script Pre-Flight Check
- **File:** `bin/backfill/run_phase4_backfill.sh`
- Changed BQ connectivity test from `timeout bq query` to Python-based `bigquery.Client().query('SELECT 1').result()`
- The `bq` CLI wasn't reliably available in nohup/background environments

#### 2. Post-Write Validation in ML Feature Store Processor
- **File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- New methods: `_validate_written_data()` and `_send_contamination_alert()`
- Runs after every BigQuery write in `save_precompute()`
- Queries just-written records for contamination metrics
- Always logs quality summary (observability)
- Sends Slack alert if `pct_with_defaults > 30%`
- Non-blocking — does not prevent completion publishing
- Stats tracked: `post_write_pct_with_defaults`, `post_write_pct_quality_ready`, `post_write_avg_matchup_quality`

#### 3. Phase 4→5 Quality Gate Enhancement
- **File:** `orchestration/cloud_functions/phase4_to_phase5/main.py`
- Extended `verify_phase4_data_ready()` to query quality metrics from `ml_feature_store_v2`
- Checks `pct_quality_ready` and `avg_required_defaults`
- Logs WARNING if quality-ready < 40%
- Informational only — Phase 5 quality gate remains enforcement point

#### 4. Training Data Contamination Monitor
- **New file:** `bin/monitoring/check_training_data_quality.sh` (executable)
- Checks V9 training window (default: Nov 2025 - present)
- Monthly breakdown: total, clean, contaminated, contamination %, quality-ready %
- Exit code 1 if contamination > 5%
- Integrated into `/validate-daily` as Phase 0.487
- Added to `/spot-check-features` as Check #28

#### Baseline (pre-backfill):
```
Overall: 40.79% contaminated (10,032 of 24,594 records)
Nov 2025: 72.8% contaminated
Dec 2025: 30.7%
Jan 2026: 26.1%
Feb 2026: 24.1%
```

### Part B: Phase 6 Export Redesign

#### 5. Consolidated Per-Day Export (picks/{date}.json)
- **File:** `data_processors/publishing/all_subsets_picks_exporter.py`
- Replaced `stats` (30-day rolling) with `record` (calendar-aligned W-L)
- Added `signal` at top level (was a separate file)
- Records include season-to-date, current month, current week (Mon-Sun)
- Single BigQuery query via conditional aggregation
- Old `signals/{date}.json` and `subsets/performance.json` still work independently

**New per-day JSON structure:**
```json
{
  "date": "2026-02-07",
  "generated_at": "...",
  "model": "926A",
  "signal": "favorable",
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "record": {
        "season": {"wins": 42, "losses": 18, "pct": 70.0},
        "month": {"wins": 8, "losses": 3, "pct": 72.7},
        "week": {"wins": 3, "losses": 1, "pct": 75.0}
      },
      "picks": [
        {"player": "LeBron James", "team": "LAL", "opponent": "BOS",
         "prediction": 26.1, "line": 24.5, "direction": "OVER"}
      ]
    }
  ]
}
```

#### 6. Season Subset Picks Exporter (NEW)
- **New file:** `data_processors/publishing/season_subset_picks_exporter.py`
- Full season of picks in one file for instant tab/date switching on frontend
- Estimated ~1MB for full season (96 dates × 8 subsets)
- Includes actual results and hit/miss for graded games
- Dates ordered newest-first within each subset
- W-L records (season/month/week) at subset level
- GCS path: `gs://nba-props-platform-api/v1/subsets/season.json`
- Cache: 1 hour
- Registered in daily_export.py as `season-subsets` export type

**Season JSON structure:**
```json
{
  "generated_at": "...",
  "model": "926A",
  "season": "2025-26",
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "record": {
        "season": {"wins": 42, "losses": 18, "pct": 70.0},
        "month": {"wins": 8, "losses": 3, "pct": 72.7},
        "week": {"wins": 3, "losses": 1, "pct": 75.0}
      },
      "dates": [
        {
          "date": "2026-02-07",
          "signal": "favorable",
          "picks": [
            {"player": "LeBron James", "team": "LAL", "opponent": "BOS",
             "prediction": 26.1, "line": 24.5, "direction": "OVER",
             "actual": 28, "result": "hit"}
          ]
        }
      ]
    }
  ]
}
```

**Key design decisions:**
- `actual` and `result` are `null` for unplayed/ungraded games
- `result` is one of: `"hit"`, `"miss"`, `"push"`, `null`
- Reads from `current_subset_picks` joined with `player_game_summary` for actuals
- Uses latest `version_id` per date (append-only materialization design)
- Records query uses `v_dynamic_subset_performance` view — **NOTE:** this view has a 30-day window hardcoded. For season records, the query uses conditional aggregation within the base CTE, so it works. But if the view is changed, check this.

---

## What Still Needs To Be Done

### Immediate (this or next session)

#### 1. Check Backfill Status
```bash
# Check if still running
ps -p 3383866 -o pid,etime --no-headers 2>/dev/null || echo "Finished"

# Check progress
grep "Processing game date" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/d47f9bad-ba83-4067-a1b2-601b94d64944/scratchpad/current_season_backfill2.log | sort -u | tail -5

# After completion, verify contamination dropped
./bin/monitoring/check_training_data_quality.sh
```

#### 2. Commit and Push (Auto-Deploys)
```bash
# Stage all changes
git add \
  bin/backfill/run_phase4_backfill.sh \
  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  orchestration/cloud_functions/phase4_to_phase5/main.py \
  bin/monitoring/check_training_data_quality.sh \
  .claude/skills/validate-daily/SKILL.md \
  .claude/skills/spot-check-features/SKILL.md \
  data_processors/publishing/all_subsets_picks_exporter.py \
  data_processors/publishing/season_subset_picks_exporter.py \
  backfill_jobs/publishing/daily_export.py \
  docs/08-projects/current/training-data-quality-prevention/00-PROJECT-OVERVIEW.md \
  docs/09-handoff/2026-02-08-SESSION-158-HANDOFF.md

git commit -m "feat: Training data quality prevention + consolidated Phase 6 exports (Session 158)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main
```

Auto-deploy triggers will deploy:
- `nba-phase4-precompute-processors` (post-write validation)
- `nba-scrapers` (if shared/ changed)
- Phase 4→5 orchestrator is a Cloud Function — needs manual deploy or separate trigger

#### 3. Start Past-Seasons Backfill
```bash
nohup ./bin/backfill/run_phase4_backfill.sh \
  --start-date 2021-10-19 --end-date 2025-06-22 --no-resume \
  > /tmp/past_seasons_backfill.log 2>&1 &
```
~853 game dates, estimated 7-9 hours.

#### 4. Export Season Subset Picks
```bash
# Export the new season file
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date 2026-02-08 --only season-subsets

# Verify it landed in GCS
gsutil ls gs://nba-props-platform-api/v1/subsets/season.json
gsutil cat gs://nba-props-platform-api/v1/subsets/season.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"groups\"])} groups, {sum(len(g[\"dates\"]) for g in d[\"groups\"])} date entries')"
```

#### 5. Wire `season-subsets` Into Daily Orchestration (NOT YET DONE)

The `season-subsets` export is registered in `daily_export.py` but is **not yet triggered automatically** by the daily pipeline. It needs to be added to the Phase 5→6 orchestration.

**Where to add it:**

The Phase 5→6 trigger happens in the prediction coordinator after predictions complete. Look at:
- `predictions/coordinator/` — after prediction batch completes, it triggers Phase 6 exports
- `orchestration/cloud_functions/` — check if there's a phase5_to_phase6 orchestrator

The season file should regenerate **once per day** (not on every prediction run, since it's the full season). Options:
1. **Add to the existing subset-picks export trigger** — when `subset-picks` runs, also run `season-subsets`
2. **Add to a daily scheduler** — Cloud Scheduler job that runs the export once at ~6 AM ET
3. **Trigger after grading** — since results are needed, trigger after Phase 5b grading completes

**Recommended approach:** Add `season-subsets` alongside the existing `subset-picks` export in the Phase 6 trigger path. The query is fast (~10s) and the file has a 1-hour cache, so running it multiple times per day is fine.

**What to look for in the codebase:**
```bash
# Find where subset-picks export is triggered in production
grep -r "subset-picks\|subset_picks\|AllSubsetsPicksExporter" predictions/ orchestration/
```

---

## Research Findings (Not Yet Implemented)

### Phase 2 Data Completeness for L5/L10 Averages

**Problem:** `StatsAggregator.aggregate()` blindly does `played_games.head(5)` — no verification that 5 games represent all games in the lookback period. If Phase 2 missed a box score, the "L5" silently computes from a wider window.

**Infrastructure exists but isn't wired up:**
- `shared/validation/historical_completeness.py` — has `assess_historical_completeness()`
- `shared/validation/window_completeness.py` — has decision logic (skip < 70%, flag < 100%)
- `ml_feature_store_v2` schema has `historical_completeness` STRUCT
- Feature extractor populates it at prediction time

**What's missing:**
- `StatsAggregator` doesn't return metadata (games_used, completeness_pct)
- `player_daily_cache` doesn't store completeness fields
- `WindowCompletenessValidator` isn't integrated into Phase 4 cache

**Files to modify if implementing:**
- `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py`
- `data_processors/precompute/player_daily_cache/builders/cache_builder.py`
- `schemas/bigquery/precompute/04_player_daily_cache.sql`

This is a medium-sized project — plan it before implementing.

---

## All Files Changed

| File | Change |
|------|--------|
| `bin/backfill/run_phase4_backfill.sh` | Fix pre-flight BQ check (Python instead of bq CLI) |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add `_validate_written_data()` + `_send_contamination_alert()` |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Add quality metrics check in `verify_phase4_data_ready()` |
| `bin/monitoring/check_training_data_quality.sh` | **NEW** — training data contamination monitor |
| `.claude/skills/validate-daily/SKILL.md` | Add Phase 0.487 training contamination check |
| `.claude/skills/spot-check-features/SKILL.md` | Add Check #28 training contamination check |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Replace `stats` with `record`, add `signal`, calendar-aligned W-L |
| `data_processors/publishing/season_subset_picks_exporter.py` | **NEW** — full-season picks with results in one file |
| `backfill_jobs/publishing/daily_export.py` | Register `season-subsets` export type |
| `docs/08-projects/current/training-data-quality-prevention/00-PROJECT-OVERVIEW.md` | **NEW** — project overview |
| `docs/09-handoff/2026-02-08-SESSION-158-HANDOFF.md` | **NEW** — this handoff |

## Key Context

- **Nothing has been committed or pushed yet** — all changes are local
- **Current-season backfill is running** in background (PID 3383866)
- The `v_dynamic_subset_performance` view has a **30-day hardcoded window** (`WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)`). The season records query works around this by using `current_subset_picks` + `player_game_summary` directly for picks, and conditional aggregation for the records query. But the records query does go through the view — if season records show zeros, this view's 30-day limit may need to be extended or the records query needs to go direct.
- The `AllSubsetsPicksExporter` changes are **breaking** for any frontend that expected the old `stats` field — it's now `record` with a different structure. If there's a frontend consuming this, coordinate the deploy.

---
*Session 158 — Co-Authored-By: Claude Opus 4.6*
