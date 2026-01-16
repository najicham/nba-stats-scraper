# MLB End-to-End Testing System

**Status**: Complete
**Created**: 2026-01-15
**Purpose**: Validate MLB prediction pipeline before and during season

---

## Overview

The MLB E2E testing system provides comprehensive validation of the prediction pipeline through:

1. **Pipeline Replay** - Replay historical dates through all pipeline phases
2. **Deployment Tests** - Verify Cloud Run, BigQuery, and model availability
3. **Game Day Simulator** - Detailed simulation with per-pitcher results
4. **Pre-Season Checklist** - Step-by-step validation guide

---

## Quick Start

```bash
# Run all deployment tests
./bin/testing/mlb/run_mlb_tests.sh

# Full pipeline replay
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Game day simulation
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28

# Find good test dates
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --find-dates
```

---

## Components

### 1. Pipeline Replay (`bin/testing/mlb/replay_mlb_pipeline.py`)

End-to-end pipeline validation that runs through 5 phases:

| Phase | Name | Description | Pass Criteria |
|-------|------|-------------|---------------|
| 1 | Verify Raw Data | Check stats, props exist | ≥5 pitchers with stats |
| 2 | Verify Analytics | Check pitcher_game_summary | ≥10 pitchers in summary |
| 3 | Run Predictions | Execute V1.4 and V1.6 | Predictions generated |
| 4 | Verify Grading | Check grading data complete | Gradeable records exist |
| 5 | Generate Report | Summary statistics | Report created |

**Usage:**
```bash
# Basic replay
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Dry run (preview only)
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --dry-run

# Skip phases
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --skip-phase=1,2

# Start from specific phase
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --start-phase=3

# Output JSON report
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --output-json report.json
```

**Sample Output:**
```
============================================================
  MLB PIPELINE REPLAY - E2E TEST
============================================================
Date:        2025-09-28
Dry Run:     False
============================================================

Phase 1: Verify Raw Data
--------------------------------------------------
  Games scheduled: 15
  Pitchers with stats: 30
  Pitchers with props: 24
Phase 1 complete: 3.4s, 30 records

Phase 2: Verify Analytics
--------------------------------------------------
  Pitchers in summary: 30
  With rolling stats: 28
Phase 2 complete: 0.9s, 30 records

Phase 3: Run Predictions
--------------------------------------------------
  V1.4: 11 picks, 5 correct (45.5%)
  V1.6: 2 picks, 0 correct (0.0%)
Phase 3 complete: 43.0s, 21 records

...

Status: PASSED
```

### 2. Deployment Tests (`bin/testing/mlb/run_mlb_tests.sh`)

Quick verification of all infrastructure components:

| Phase | Component | Check |
|-------|-----------|-------|
| 1 | Cloud Run | Health endpoints respond HTTP 200 |
| 2 | BigQuery | mlb_raw, mlb_analytics, mlb_predictions exist |
| 3 | Models | V1.4 and V1.6 accessible in GCS |
| 4 | Pipeline | Dry run replay completes |
| 5 | Data | Recent data exists |

**Usage:**
```bash
# Full test suite
./bin/testing/mlb/run_mlb_tests.sh

# Quick mode (health checks only)
./bin/testing/mlb/run_mlb_tests.sh --quick

# Verbose output
./bin/testing/mlb/run_mlb_tests.sh --verbose
```

**Exit Codes:**
- `0` = All tests passed
- `1` = Some tests failed
- `2` = Critical failure

### 3. Game Day Simulator (`scripts/mlb/simulate_game_day.py`)

Detailed simulation showing individual pitcher predictions and results:

**Usage:**
```bash
# Basic simulation
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28

# Compare different thresholds
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28 --compare-thresholds

# Find dates with data
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --find-dates
```

**Sample Output:**
```
======================================================================
SIMULATION RESULTS: 2025-09-28
======================================================================

Data Coverage:
  Total pitchers:     30
  With betting lines: 22
  With results:       30
  Errors:             0

Model      Picks    Correct    Wrong    Accuracy   MAE      PASS
----------------------------------------------------------------------
V1.4       11       5          6          45.5%    1.74     19
V1.6       2        0          2           0.0%    1.66     28

Head-to-Head (which prediction was closer to actual):
  V1.4 closer: 9 (40.9%)
  V1.6 closer: 13 (59.1%)
  Ties:        0 (0.0%)

Pitcher              Team   Line   Actual   V1.4     V1.6     Winner
----------------------------------------------------------------------
cole_ragans          UNK    6.5    8        4.5 U-   6.7      v1_6
kyle_bradish         UNK    5.5    8        6.1 O+   5.7      v1_4
...
```

### 4. Test Dataset Setup (`bin/testing/mlb/setup_test_datasets.sh`)

Creates isolated BigQuery datasets for testing:

```bash
# Create test datasets with default prefix
./bin/testing/mlb/setup_test_datasets.sh

# Custom prefix
./bin/testing/mlb/setup_test_datasets.sh dev_

# Dry run
./bin/testing/mlb/setup_test_datasets.sh test_ --dry-run
```

Creates:
- `test_mlb_raw`
- `test_mlb_analytics`
- `test_mlb_predictions`

Tables auto-expire after 7 days.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    E2E Test System                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Deployment   │    │  Pipeline    │    │  Game Day    │  │
│  │   Tests      │    │   Replay     │    │  Simulator   │  │
│  │              │    │              │    │              │  │
│  │ - Health     │    │ - Phase 1-5  │    │ - V1.4/V1.6  │  │
│  │ - Datasets   │    │ - Raw→Grade  │    │ - Per-pitcher│  │
│  │ - Models     │    │ - JSON out   │    │ - Thresholds │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                   │                   │          │
│         └───────────────────┼───────────────────┘          │
│                             │                              │
│                    ┌────────▼────────┐                     │
│                    │    BigQuery     │                     │
│                    │  - mlb_raw      │                     │
│                    │  - mlb_analytics│                     │
│                    │  - mlb_predict  │                     │
│                    └─────────────────┘                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## File Locations

| Component | Path |
|-----------|------|
| Pipeline Replay | `bin/testing/mlb/replay_mlb_pipeline.py` |
| Deployment Tests | `bin/testing/mlb/run_mlb_tests.sh` |
| Dataset Setup | `bin/testing/mlb/setup_test_datasets.sh` |
| Game Day Simulator | `scripts/mlb/simulate_game_day.py` |
| Pre-Season Guide | `docs/06-operations/mlb/pre-season-testing.md` |
| This Documentation | `docs/08-projects/current/mlb-e2e-testing/` |

---

## Related Documentation

- [Pre-Season Testing Guide](../../../06-operations/mlb/pre-season-testing.md)
- [MLB Pipeline Deployment](../mlb-pipeline-deployment/)
- [MLB Pitcher Strikeouts Model](../mlb-pitcher-strikeouts/)

---

## Maintenance

### Adding New Test Phases

To add a new phase to the pipeline replay:

1. Add phase function in `replay_mlb_pipeline.py`:
   ```python
   def phase6_new_check(self) -> tuple:
       """Phase 6: Description."""
       # Implementation
       return records, details
   ```

2. Add to phases list in `run()` method:
   ```python
   phases = [
       ...
       (6, "New Check", self.phase6_new_check),
   ]
   ```

3. Add threshold in `PHASE_THRESHOLDS`:
   ```python
   'phase6': {'warn': 30, 'critical': 60},
   ```

### Updating Deployment Tests

Edit `run_mlb_tests.sh` to add new checks:
- Add new Phase section following existing pattern
- Update `PASSED/FAILED/WARNINGS` counters
- Use `log_pass`, `log_fail`, `log_warn` helpers

---

**Last Updated**: 2026-01-15
