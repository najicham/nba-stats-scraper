# MLB Pipeline Deployment - Handoff Document

**Date:** January 7, 2026, 7:30 PM PST
**Session Duration:** ~4 hours
**Project:** MLB Pitcher Strikeouts Full Pipeline Deployment

---

## Executive Summary

This session accomplished two major milestones:
1. **Trained and deployed MLB pitcher strikeouts ML model** (MAE 1.71, beats 1.92 baseline by 11%)
2. **Set up infrastructure for full 6-phase MLB pipeline** (Pub/Sub, BigQuery, registry)

The next session needs to complete the Cloud Run deployments and create orchestration/schedulers.

---

## What Was Accomplished

### 1. ML Model Training (Complete)

**Problem Fixed:** The data collection script wasn't storing pitcher stats to BigQuery (missing `walks_allowed` column).

**Solution:**
```sql
ALTER TABLE mlb_raw.mlb_pitcher_stats ADD COLUMN walks_allowed INTEGER
```

**Data Collected:**
- 2024 season: 20,976 pitcher stats
- 2025 season: 21,149 pitcher stats
- Total: 42,125 records

**Analytics Processed:**
- 9,793 pitcher game summaries in `mlb_analytics.pitcher_game_summary`

**Model Results:**
| Metric | Value |
|--------|-------|
| Test MAE | 1.71 |
| Baseline MAE | 1.92 |
| Improvement | 11% |
| Training samples | 8,130 |

**Model Location:**
```
gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107_metadata.json
```

### 2. Code Fixes Applied

**File: `data_processors/analytics/mlb/pitcher_game_summary_processor.py`**
- Fixed RANGE INTERVAL syntax for BigQuery (use UNIX_DATE)
- Added date/datetime JSON serialization
- Changed NUMERIC columns to FLOAT64 (precision issues)

**File: `scripts/mlb/train_pitcher_strikeouts.py`**
- Added game_date filters for partition elimination

**File: `scrapers/registry.py`**
- Made registry sport-aware via SPORT env var
- Added MLB_SCRAPER_REGISTRY with 28 scrapers
- SCRAPER_REGISTRY dynamically selects based on SPORT=nba|mlb

### 3. Infrastructure Created

**Pub/Sub Topics (12 created):**
```
mlb-phase1-scrapers-complete
mlb-phase2-raw-complete
mlb-phase3-analytics-complete
mlb-phase4-precompute-complete
mlb-phase5-predictions-complete
mlb-phase6-export-complete
mlb-phase3-trigger
mlb-phase4-trigger
mlb-phase5-trigger
mlb-phase6-trigger
mlb-phase1-scrapers-complete-dlq
mlb-phase2-raw-complete-dlq
```

**BigQuery Tables Created:**
```sql
mlb_predictions.pitcher_strikeouts    -- Prediction output
mlb_orchestration.phase_completions   -- Track processor completions
mlb_orchestration.pipeline_runs       -- Track pipeline runs
```

**BigQuery Schema Fixes:**
- Changed all NUMERIC columns in `mlb_analytics.pitcher_game_summary` to FLOAT64

### 4. Deploy Scripts Created

**`bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`**
- Deploys MLB scrapers to Cloud Run
- Configures SPORT=mlb environment
- Sets up API keys and alerting

**`scrapers/mlb/registry.py`**
- MLB-specific scraper registry
- 28 scrapers organized by source

---

## What Still Needs To Be Done

### Priority 1: Cloud Run Deployments

| Service | Status | Deploy Script |
|---------|--------|---------------|
| mlb-phase1-scrapers | NOT DEPLOYED | `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` |
| mlb-phase2-raw-processors | NOT DEPLOYED | Need to create |
| mlb-phase3-analytics-processors | NOT DEPLOYED | Need to create |
| mlb-phase4-precompute-processors | NOT DEPLOYED | Need to create |
| mlb-prediction-worker | NOT DEPLOYED | Need to create code + deploy |

### Priority 2: Prediction Worker Code

Need to create:
```
predictions/mlb/__init__.py
predictions/mlb/pitcher_strikeouts_predictor.py
predictions/mlb/worker.py
```

This should:
1. Load model from GCS
2. Query today's starting pitchers from BigQuery
3. Generate predictions using feature data
4. Write to `mlb_predictions.pitcher_strikeouts`

### Priority 3: Orchestrators

Need to create Cloud Functions:
```
orchestrators/mlb/phase2_to_phase3.py
orchestrators/mlb/phase3_to_phase4.py
orchestrators/mlb/phase4_to_phase5.py
orchestrators/mlb/phase5_to_phase6.py
```

### Priority 4: Scheduler Jobs

Need to create (~15 jobs):
```
mlb-schedule-daily          6:00 AM ET
mlb-lineups-morning        10:00 AM ET
mlb-lineups-pregame        12:00 PM ET
mlb-props-morning          10:30 AM ET
mlb-props-pregame          12:30 PM ET
mlb-live-evening           */5 13-23 ET
mlb-overnight-boxscores     2:00 AM ET
mlb-overnight-analytics     6:00 AM ET
mlb-predictions-daily      12:00 PM ET
```

### Priority 5: Documentation

- Update docs structure for MLB
- Create MLB-specific runbooks
- Document scheduler configurations

---

## Known Issues

### 1. Ball Don't Lie API Returning Unauthorized

**Symptom:** BDL MLB API returns 401 Unauthorized
```bash
curl -H "Authorization: $BDL_API_KEY" "https://api.balldontlie.io/mlb/v1/games?dates[]=2025-06-15"
# Returns: Unauthorized
```

**Possible causes:**
- API key format issue (with/without Bearer prefix)
- BDL temporary outage
- GOAT subscription may need MLB access enabled separately

**Workaround:** MLB Stats API works without auth and provides schedule/lineups/box scores.

**Action needed:** Test BDL API again or contact BDL support about MLB access.

### 2. BigQuery NUMERIC Precision

Fixed for `pitcher_game_summary` by converting to FLOAT64. May need to apply same fix to other tables if similar issues occur.

---

## File Locations

### Key Implementation Files
```
scripts/mlb/collect_season.py              # Raw data collection (fixed)
scripts/mlb/train_pitcher_strikeouts.py    # ML training (fixed)
data_processors/analytics/mlb/pitcher_game_summary_processor.py  # (fixed)
scrapers/registry.py                        # Sport-aware registry (updated)
scrapers/mlb/registry.py                    # MLB scraper registry (new)
```

### Deploy Scripts
```
bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh  # MLB scrapers deploy (new)
```

### Documentation
```
docs/08-projects/current/mlb-pipeline-deployment/IMPLEMENTATION-PLAN.md
```

---

## Quick Commands for New Session

### Check Current State
```bash
# Verify Pub/Sub topics exist
gcloud pubsub topics list | grep mlb

# Check BigQuery tables
bq ls mlb_predictions
bq ls mlb_orchestration

# Verify model in GCS
gsutil ls gs://nba-scraped-data/ml-models/mlb/

# Check data counts
bq query --nouse_legacy_sql "SELECT COUNT(*) FROM mlb_raw.mlb_pitcher_stats"
bq query --nouse_legacy_sql "SELECT COUNT(*) FROM mlb_analytics.pitcher_game_summary WHERE game_date >= '2024-01-01'"
```

### Test Registry
```bash
# Test MLB registry loads correctly
SPORT=mlb PYTHONPATH=. python -c "
from scrapers.registry import SCRAPER_REGISTRY, list_scrapers
print(f'MLB Scrapers: {len(SCRAPER_REGISTRY)}')
print('Sample:', list_scrapers()[:5])
"
```

### Deploy MLB Scrapers (when ready)
```bash
chmod +x bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
```

---

## Architecture Reference

### MLB Pipeline (6 Phases)
```
Phase 1: Scrapers (28)
├── balldontlie (13): games, box_scores, pitcher_stats, batter_stats, etc.
├── mlbstatsapi (3): schedule, lineups, game_feed
├── oddsapi (8): events, game_lines, pitcher_props, batter_props
├── external (3): weather, ballpark_factors, umpire_stats
└── statcast (1): statcast_pitcher

Phase 2: Raw Processors (8)
├── mlb_schedule_processor
├── mlb_lineups_processor
├── mlb_pitcher_stats_processor
├── mlb_batter_stats_processor
├── mlb_pitcher_props_processor
├── mlb_batter_props_processor
├── mlb_game_lines_processor
└── mlb_events_processor

Phase 3: Analytics (2)
├── pitcher_game_summary_processor  ✅ Working
└── batter_game_summary_processor

Phase 4: Precompute (2)
├── pitcher_features_processor
└── lineup_k_analysis_processor

Phase 5: Predictions
└── pitcher_strikeouts_predictor (model ready, worker needed)

Phase 6: Export
└── TBD
```

### Comparison to NBA
| Component | NBA | MLB |
|-----------|-----|-----|
| Scrapers | 33 | 28 |
| Raw Processors | 21 | 8 |
| Analytics | 5 | 2 |
| Precompute | 5 | 2 |
| Cloud Run Services | 16 | 0 (not yet) |
| Schedulers | 29 | 0 (not yet) |

---

## Git History

```bash
# Today's commits
git log --oneline -5

# Expected output:
# d00ebbc feat(mlb): Add MLB pipeline infrastructure and sport-aware registry
# 35e21b6 feat(mlb): Fix analytics pipeline and train pitcher strikeouts model
# 207a513 chore: Remove orphaned root files and old backup files
```

---

## Recommended Next Steps (In Order)

1. **Test BDL API** - Verify if it's working or switch to MLB Stats API only
2. **Deploy Phase 1 scrapers** - `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
3. **Create prediction worker** - This is the key deliverable
4. **Deploy prediction worker** - Get predictions running
5. **Add orchestrators** - For automation
6. **Add schedulers** - For daily runs
7. **Create Phase 2-4 deploy scripts** - For full pipeline
8. **Test end-to-end** - Verify everything works

---

## Success Criteria

- [ ] MLB scrapers deployed and responding to `/health`
- [ ] Prediction worker generating daily predictions
- [ ] Predictions appearing in `mlb_predictions.pitcher_strikeouts`
- [ ] All 6 phases connected via Pub/Sub
- [ ] Schedulers running daily during MLB season
- [ ] Documentation complete

---

## Contact/Context

This is part of a larger sports prediction platform:
- **NBA predictions:** Production (working)
- **MLB predictions:** Development (this project)
- **Target:** Pitcher strikeout over/under predictions
- **Model:** XGBoost, MAE 1.71 (beats 1.92 baseline)
