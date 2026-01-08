# MLB Pipeline Deployment Progress - 2026-01-07

## Session Summary

This session made significant progress on the MLB pipeline deployment. The key deliverables - prediction worker and scrapers - are now deployed and working.

## Deployed Services

| Service | URL | Status |
|---------|-----|--------|
| MLB Prediction Worker | https://mlb-prediction-worker-756957797294.us-west2.run.app | ✅ Healthy |
| MLB Phase 1 Scrapers | https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app | ✅ Healthy (28 scrapers) |

## What Was Completed

### 1. MLB Prediction Worker (100%)
- Created `predictions/mlb/pitcher_strikeouts_predictor.py`
- Created `predictions/mlb/worker.py` (Flask service)
- Created `docker/mlb-prediction-worker.Dockerfile`
- Created `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`
- **Deployed and tested successfully**
- Prediction test: 7.51 Ks predicted for garrett_crochet (line 7.5) → PASS recommendation

### 2. MLB Scrapers (100%)
- 28 scrapers already implemented (previous sessions)
- Scraper registry is sport-aware (`SPORT=mlb`)
- Created `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
- **Deployed and tested successfully**
- Test: `mlb_schedule` scraper returned 15 games for 2025-06-15

### 3. BDL API Investigation
- Found that BDL MLB API requires `Bearer` prefix (unlike NBA)
- API was experiencing 500 errors (transient, now resolved)
- All GOAT-tier endpoints working

## What's Remaining

### 4. Phase 2 Raw Processors (80% done)
- MLB processors exist: `data_processors/raw/mlb/*.py`
- Deploy script created: `bin/raw/deploy/mlb/deploy_mlb_processors.sh`
- **BLOCKER**: main_processor_service.py is not sport-aware
- **NEEDED**: Add MLB processor imports and routing logic

### 5. Phase 3-4 Analytics/Precompute (Not started)
- Analytics processors exist: `data_processors/analytics/mlb/`
- Need deploy scripts for Phase 3-4

### 6. Orchestrators (Not started)
- Need to create MLB phase-to-phase orchestrators
- Similar to NBA: phase1→phase2→phase3→phase4→phase5

### 7. Schedulers (Not started)
- Need daily scheduler jobs for MLB pipeline
- MLB season is off-season until March 2026

## Files Created This Session

```
predictions/mlb/__init__.py
predictions/mlb/pitcher_strikeouts_predictor.py
predictions/mlb/worker.py
docker/mlb-prediction-worker.Dockerfile
bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh (updated)
bin/raw/deploy/mlb/deploy_mlb_processors.sh
```

## Next Steps (Priority Order)

1. **Make processor service sport-aware**:
   - Add MLB processor imports to `main_processor_service.py`
   - Route based on GCS path prefix (`mlb-stats-api/`, `mlb-bdl/`, etc.)

2. **Deploy MLB Phase 2 processors**:
   ```bash
   ./bin/raw/deploy/mlb/deploy_mlb_processors.sh
   ```

3. **Create Phase 3-4 deploy scripts**:
   - Copy from NBA patterns
   - Set `SPORT=mlb`

4. **Create orchestrators**:
   - phase1→phase2: GCS notification → processor
   - phase2→phase3: processor complete → analytics
   - etc.

5. **Create schedulers** (can wait until next season):
   - Daily MLB game scraping
   - Daily prediction generation

## Testing Commands

```bash
# Test prediction worker
curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_lookup": "garrett_crochet", "game_date": "2025-09-15", "strikeouts_line": 7.5}'

# Test scrapers
curl -X POST https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper": "mlb_schedule", "date": "2025-06-15"}'
```

## Model Performance

- **MAE**: 1.71 (11% better than 1.92 baseline)
- **Training samples**: 8,130
- **Features**: 19
- **Model path**: `gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json`
