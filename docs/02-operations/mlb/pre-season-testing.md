# MLB Pre-Season Testing Guide

Before Opening Day, run these tests to ensure the MLB prediction pipeline is ready.

---

## Quick Start

```bash
# 1. Run deployment verification tests
./bin/testing/mlb/run_mlb_tests.sh

# 2. Run a full pipeline replay
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# 3. Run the game day simulator
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28
```

---

## Test Components

### 1. Deployment Verification (`run_mlb_tests.sh`)

Checks all infrastructure components:

| Phase | Check | Pass Criteria |
|-------|-------|---------------|
| 1 | Cloud Run Health | HTTP 200 from prediction worker |
| 2 | BigQuery Datasets | mlb_raw, mlb_analytics, mlb_predictions exist |
| 3 | Model Availability | V1.4 and V1.6 models in GCS |
| 4 | Pipeline Replay | Dry run completes without error |
| 5 | Recent Data | Has historical data for testing |

```bash
# Quick mode (just health checks)
./bin/testing/mlb/run_mlb_tests.sh --quick

# Verbose mode (detailed output)
./bin/testing/mlb/run_mlb_tests.sh --verbose
```

### 2. Pipeline Replay (`replay_mlb_pipeline.py`)

End-to-end test that replays a historical game day:

| Phase | Description | Output |
|-------|-------------|--------|
| 1 | Verify Raw Data | Games, stats, props exist |
| 2 | Verify Analytics | pitcher_game_summary populated |
| 3 | Run Predictions | V1.4 and V1.6 predictions |
| 4 | Verify Grading | All data for grading exists |
| 5 | Generate Report | Summary statistics |

```bash
# Find dates with good test data
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --find-dates

# Run full replay
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28

# Output JSON report
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --output-json report.json

# Skip specific phases
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --skip-phase=1,2
```

### 3. Game Day Simulator (`simulate_game_day.py`)

Detailed simulation with individual pitcher results:

```bash
# Run simulation
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28

# Compare different threshold settings
PYTHONPATH=. python scripts/mlb/simulate_game_day.py --date 2025-09-28 --compare-thresholds
```

---

## Pre-Season Checklist

### 2 Weeks Before Opening Day

- [ ] Run `./bin/testing/mlb/run_mlb_tests.sh` - all checks pass
- [ ] Run pipeline replay on 5+ historical dates
- [ ] Verify V1.4 and V1.6 models are accessible
- [ ] Check Cloud Run services are deployed and healthy

### 1 Week Before Opening Day

- [ ] Deploy latest code to Cloud Run
  ```bash
  ./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
  ```
- [ ] Create Cloud Scheduler jobs (paused)
  ```bash
  ./bin/schedulers/setup_mlb_schedulers.sh --paused
  ```
- [ ] Verify scheduler jobs created in GCP Console
- [ ] Test prediction worker endpoint manually
  ```bash
  curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/predict-batch \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2025-09-28"}'
  ```

### Day Before Opening Day

- [ ] Enable Cloud Scheduler jobs
- [ ] Run one final pipeline replay
- [ ] Verify all dashboards/monitoring are working
- [ ] Set up alerts for pipeline failures

### Opening Day

- [ ] Monitor first batch of predictions
- [ ] Verify grading runs after games complete
- [ ] Check shadow mode comparison (V1.4 vs V1.6)

---

## Expected Results

### Pipeline Replay Success Criteria

| Metric | Minimum | Target |
|--------|---------|--------|
| Total Pitchers | 10 | 25+ |
| With Lines | 5 | 15+ |
| With Results | 5 | 15+ |
| V1.4 Accuracy | 40% | 50%+ |
| V1.6 Accuracy | 40% | 50%+ |

### Deployment Tests Success Criteria

| Test | Required | Expected |
|------|----------|----------|
| Prediction Worker Health | PASS | HTTP 200 |
| Grading Service Health | WARN OK | HTTP 200 or not deployed |
| BigQuery Datasets | PASS | All 3 exist |
| Models Available | PASS | Both V1.4 and V1.6 |
| Recent Data | WARN OK | May not exist off-season |

---

## Troubleshooting

### Common Issues

**1. Pipeline replay fails at Phase 3**
- Check if models are accessible in GCS
- Verify `pitcher_game_summary` has data for the date
- Check Cloud Run worker logs

**2. No pitchers found for date**
- Use `--find-dates` to discover dates with data
- Ensure `pitcher_game_summary` is populated
- Check date format (YYYY-MM-DD)

**3. All predictions are PASS**
- Check if betting lines exist for the date
- Verify odds API data is loaded
- Player lookup normalization may need aliases

**4. Models not loading**
- Check GCS bucket permissions
- Verify model paths are correct
- Check for network/firewall issues

### Useful Queries

```sql
-- Check data availability for a date
SELECT
  COUNT(DISTINCT pgs.player_lookup) as pitchers,
  COUNT(DISTINCT CASE WHEN odds.point IS NOT NULL THEN pgs.player_lookup END) as with_lines,
  COUNT(DISTINCT CASE WHEN stats.strikeouts IS NOT NULL THEN pgs.player_lookup END) as with_results
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
LEFT JOIN `nba-props-platform.mlb_raw.oddsa_pitcher_props` odds
  ON REPLACE(pgs.player_lookup, '_', '') = odds.player_lookup
  AND pgs.game_date = odds.game_date
  AND odds.market_key = 'pitcher_strikeouts'
LEFT JOIN `nba-props-platform.mlb_raw.mlb_pitcher_stats` stats
  ON pgs.player_lookup = stats.player_lookup
  AND pgs.game_date = stats.game_date
  AND stats.is_starter = TRUE
WHERE pgs.game_date = '2025-09-28'
```

```sql
-- Find good test dates
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as pitchers
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-04-01'
GROUP BY game_date
HAVING COUNT(DISTINCT player_lookup) >= 10
ORDER BY game_date DESC
LIMIT 20
```

---

## Contact

For issues with the MLB pipeline, check:
1. Cloud Run logs in GCP Console
2. BigQuery job history
3. Scheduler execution logs

---

**Last Updated**: 2026-01-15
