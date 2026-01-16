# MLB E2E Testing System - Changelog

## [1.0.0] - 2026-01-15

### Added
- **Pipeline Replay** (`bin/testing/mlb/replay_mlb_pipeline.py`)
  - 5-phase validation: raw data, analytics, predictions, grading, report
  - Support for `--dry-run`, `--skip-phase`, `--start-phase`, `--output-json`
  - `--find-dates` to discover dates with good test data
  - Runs V1.4 and V1.6 predictions and calculates accuracy

- **Deployment Tests** (`bin/testing/mlb/run_mlb_tests.sh`)
  - Phase 1: Cloud Run health checks (prediction worker, grading service)
  - Phase 2: BigQuery dataset verification
  - Phase 3: Model availability in GCS
  - Phase 4: Pipeline replay dry run
  - Phase 5: Recent data check
  - `--quick` mode for health checks only
  - `--verbose` mode for detailed output

- **Test Dataset Setup** (`bin/testing/mlb/setup_test_datasets.sh`)
  - Creates isolated `test_mlb_*` datasets
  - 7-day auto-expiration
  - Support for custom prefixes

- **Game Day Simulator** (`scripts/mlb/simulate_game_day.py`)
  - Per-pitcher prediction details
  - V1.4 vs V1.6 head-to-head comparison
  - `--compare-thresholds` for A/B testing config values
  - Joins with odds API for betting lines

- **Documentation**
  - Pre-season testing guide (`docs/06-operations/mlb/pre-season-testing.md`)
  - Project documentation (`docs/08-projects/current/mlb-e2e-testing/`)

### Validated
- Successfully ran pipeline replay on 2025-09-28:
  - 30 pitchers, 24 with props
  - V1.4: 11 picks, 45.5% accuracy
  - V1.6: 2 picks, 0% accuracy (higher edge threshold)
  - All 5 phases passed

---

## Usage Summary

```bash
# Quick health check
./bin/testing/mlb/run_mlb_tests.sh --quick

# Full E2E test
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Detailed simulation
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28
```

---

## Git Commits

| Commit | Description |
|--------|-------------|
| `c9ce40d` | feat(mlb): Add E2E test system for pre-season validation |
| `16e79fe` | feat(mlb): Add game day simulator for testing and backtesting |
