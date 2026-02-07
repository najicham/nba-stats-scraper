# Session 146 Prompt

Read the Session 145 handoff at `docs/09-handoff/2026-02-07-SESSION-145-HANDOFF.md`.

## Context

Session 145 made vegas features (25-27) optional in zero-tolerance gating. The code is implemented across 4 files but needs to be committed and deployed. Session 144's cache miss fix deployments were in progress when the session ended.

## Immediate Tasks

### 1. Check Session 144 Deployments Completed
```bash
./bin/check-deployment-drift.sh --verbose
```

If Phase 4, Phase 2, Phase 3 are stale, redeploy them.

### 2. Commit and Deploy Session 145 Vegas Optional Changes

```bash
# Check what needs committing
git status

# Commit
git add shared/ml/feature_contract.py \
  data_processors/precompute/ml_feature_store/quality_scorer.py \
  predictions/coordinator/quality_gate.py \
  predictions/worker/worker.py \
  schemas/bigquery/predictions/04_ml_feature_store_v2.sql \
  docs/

git commit -m "feat: Make vegas features optional in zero-tolerance gating (Session 145)"

# Deploy affected services (Phase 4 + coordinator + worker)
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
./bin/deploy-service.sh prediction-worker
```

### 3. Verify Impact After Deployment
```sql
SELECT game_date,
  COUNT(*) as total_records,
  COUNTIF(is_quality_ready) as quality_ready,
  COUNTIF(required_default_count = 0) as req_defaults_zero,
  ROUND(COUNTIF(is_quality_ready) / COUNT(*) * 100, 1) as pct_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1;
```

Before: ~37-45% quality_ready. Expected: ~90-95% quality_ready.

### 4. Run 2021 Season Backfill (3,231 remaining records)
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

### 5. Add Scraper Health Monitoring (Vegas Lines)

Alert when star players are missing vegas lines (indicates scraper issue):
- Players with PPG > 20 and tier 1-2 should ALWAYS have lines
- If missing, check `odds_api_*` scrapers
- Add to canary monitoring or `/validate-daily`

### 6. Fix PlayerDailyCacheProcessor Root Cause

The cache miss fallback works but is a band-aid. Fix the root:
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Change player source to include all active season players (not just today's games)
- Reference: shot zone processor shows the correct approach

## Key Architecture

### Vegas Optional System
- `default_feature_count` → ALL defaults (including vegas) → for visibility
- `required_default_count` → REQUIRED defaults only → for gating
- `vegas_default_count` → vegas-specific → for scraper health
- `FEATURES_OPTIONAL = {25, 26, 27}` in `shared/ml/feature_contract.py`

### Cache Miss Fallback
- `feature_extractor.py:_compute_cache_fields_from_games()` computes stats from `last_10_games` when `player_daily_cache` misses
- Fixes features 0-4, 22-23, 31-32 (player history and team context)

### Gap Tracking
- Table: `nba_predictions.feature_store_gaps`
- Processor logs skipped players automatically
- Backfill resolves gaps on success
