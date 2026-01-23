# Session 62 MLB Handoff: E2E Testing System + Backfill Monitoring

**Date**: 2026-01-15
**Focus**: MLB E2E testing system, shadow mode automation, backfill monitoring
**Status**: E2E system complete, backfill at ~80%

---

## Quick Start for New Chat

```bash
# Read this handoff
cat docs/09-handoff/2026-01-15-SESSION-62-MLB-HANDOFF.md

# Check backfill progress
tail -10 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# Test the E2E system
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28
```

---

## Background Task: BettingPros Backfill

**Task ID**: `b77281f`
**Status**: Running (~80% complete)
**Monitor**: `tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output`

### Current Progress
- **6401/8140** props processed (79%)
- **Currently Processing**: April 23, 2025 data
- **ETA**: ~15-20 minutes remaining

### When Backfill Completes

Run these commands in order:

```bash
# 1. Load pitcher props to BigQuery (~2 min)
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type pitcher

# 2. Verify data loaded
bq query --use_legacy_sql=false "
SELECT MIN(game_date) as min_date, MAX(game_date) as max_date, COUNT(*) as total
FROM mlb_raw.bp_pitcher_props
WHERE market_name = 'pitcher-strikeouts'"

# 3. (Optional) Load batter props
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter

# 4. Redeploy worker to get shadow mode endpoint
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh

# 5. Create scheduler jobs (paused until season)
./bin/schedulers/setup_mlb_schedulers.sh --paused
```

---

## What Was Accomplished This Session

### 1. MLB E2E Testing System (Complete)

Created comprehensive testing infrastructure:

| Component | Path | Purpose |
|-----------|------|---------|
| Pipeline Replay | `bin/testing/mlb/replay_mlb_pipeline.py` | 5-phase E2E validation |
| Deployment Tests | `bin/testing/mlb/run_mlb_tests.sh` | Infrastructure verification |
| Dataset Setup | `bin/testing/mlb/setup_test_datasets.sh` | Isolated test datasets |
| Game Day Simulator | `scripts/mlb/simulate_game_day.py` | Per-pitcher simulation |
| Pre-Season Guide | `docs/06-operations/mlb/pre-season-testing.md` | Operations documentation |
| Project Docs | `docs/08-projects/current/mlb-e2e-testing/` | Full system documentation |

**Test Results (Sept 28, 2025):**
- All 5 phases passed
- 30 pitchers, 24 with props
- V1.4: 11 picks, 45.5% accuracy
- V1.6: 2 picks (higher edge threshold)

### 2. Shadow Mode Automation (Complete)

Added endpoints and scheduler jobs for automated A/B testing:

| Endpoint | Service | Purpose |
|----------|---------|---------|
| `/execute-shadow-mode` | Prediction Worker | Run V1.4 vs V1.6 comparison |
| `/grade-shadow` | Grading Service | Grade shadow predictions |

**Scheduler Jobs Added:**
- `mlb-shadow-mode-daily` - 1:30 PM ET
- `mlb-shadow-grading-daily` - 10:30 AM ET

### 3. Centralized Config System (Complete)

All prediction thresholds now configurable via environment variables:

```bash
# Example: Adjust V1.4 edge threshold
MLB_MIN_EDGE=0.3 python ...

# Example: Adjust V1.6 edge threshold
MLB_MIN_EDGE_V2=1.5 python ...
```

Config file: `predictions/mlb/config.py`

### 4. Load Script Fix (Complete)

Fixed schema mismatch in BettingPros load script:
- `player_id` → `bp_player_id`
- `processed_at` → `created_at`

---

## Git Commits This Session

```
011325f feat(predictions): Add stall detection for coordinator batches
81aa54a docs(mlb): Add E2E testing system project documentation
c9ce40d feat(mlb): Add E2E test system for pre-season validation
16e79fe feat(mlb): Add game day simulator for testing and backtesting
d556096 fix(mlb): Align load script fields with BigQuery schema
1d558ed feat(mlb): Add shadow mode automation and centralized config system
```

---

## Files Modified/Created

### New Files
- `bin/testing/mlb/replay_mlb_pipeline.py`
- `bin/testing/mlb/run_mlb_tests.sh`
- `bin/testing/mlb/setup_test_datasets.sh`
- `scripts/mlb/simulate_game_day.py`
- `predictions/mlb/config.py`
- `docs/06-operations/mlb/pre-season-testing.md`
- `docs/08-projects/current/mlb-e2e-testing/README.md`
- `docs/08-projects/current/mlb-e2e-testing/CHANGELOG.md`

### Modified Files
- `predictions/mlb/worker.py` - Added `/execute-shadow-mode` endpoint
- `predictions/mlb/shadow_mode_runner.py` - Added `run_shadow_mode()` function
- `predictions/mlb/pitcher_strikeouts_predictor.py` - Use centralized config
- `predictions/mlb/pitcher_strikeouts_predictor_v2.py` - Use centralized config
- `data_processors/grading/mlb/main_mlb_grading_service.py` - Added `/grade-shadow`
- `bin/schedulers/setup_mlb_schedulers.sh` - Added shadow mode jobs (11 total)
- `bin/predictions/consolidate/manual_consolidation.py` - Added CLI args
- `scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py` - Schema fix

---

## Remaining Work

### After Backfill Completes (HIGH PRIORITY)
1. Load data to BigQuery (see commands above)
2. Redeploy prediction worker
3. Test shadow mode endpoint manually

### Pre-Season Checklist
1. Run `./bin/testing/mlb/run_mlb_tests.sh` - verify all infrastructure
2. Run pipeline replay on 5+ historical dates
3. Enable Cloud Scheduler jobs before Opening Day

### Lower Priority
- Add unit tests for predictor classes
- Improve exception handling (replace bare `except Exception`)
- Add feature validation layer

---

## Key URLs

| Service | URL |
|---------|-----|
| Prediction Worker | `https://mlb-prediction-worker-756957797294.us-west2.run.app` |
| Grading Service | `https://mlb-grading-service-756957797294.us-west2.run.app` |

---

## Useful Commands

```bash
# Monitor backfill
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# Run E2E test
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Run deployment tests
./bin/testing/mlb/run_mlb_tests.sh

# Simulate game day
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28

# Find good test dates
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --find-dates
```

---

**Session Duration**: ~2 hours
**Primary Outcome**: Complete MLB E2E testing system ready for pre-season validation
