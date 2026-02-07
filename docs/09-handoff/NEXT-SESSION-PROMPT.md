# Session 146 Prompt

Read these handoff docs for context:
- `docs/09-handoff/2026-02-07-SESSION-145-HANDOFF.md` - Vegas optional implementation details
- `docs/09-handoff/2026-02-07-SESSION-144-HANDOFF.md` - Cache miss fallback and root cause analysis
- `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md` - Full project overview

## Why We're Working on This

Our ML feature store (`ml_feature_store_v2`) had only 37-45% of records fully complete (zero defaults) despite 100% player coverage. The zero-tolerance policy (Session 141) blocks predictions for ANY player with default features. This meant only ~75 predictions/day instead of ~180+.

Sessions 144-145 fixed this:
1. **Session 144:** Cache miss fallback in `feature_extractor.py` - computed stats from `last_10_games` when `player_daily_cache` missed (~13% of records). Deployed.
2. **Session 145:** Made vegas features (25-27) optional in zero-tolerance gating. Vegas lines are unavailable for ~60% of players (bench players) - this is normal, not a bug.

## Current State (end of Session 145)

### Deployed Services
| Service | Status | Commit |
|---------|--------|--------|
| Phase 4 (precompute) | **Deployed** with vegas optional | `aa1248e0` |
| Phase 2 (raw) | **Deployed** with timing breakdown | `246abe9b` |
| Phase 3 (analytics) | **Deployed** with timing breakdown | `246abe9b` |
| Prediction Worker | **Deployed** with vegas optional | `aa1248e0` |
| Prediction Coordinator | **NEEDS DEPLOY** - TLS timeout during push | - |

### Background Tasks (may still be running)
- **2025-26 backfill** (task b09541c): Processing ~92 dates from 2025-11-04. Was at date 9/92 when session ended. Uses checkpoints so progress is saved.
- **Coordinator deploy** (task b745dcf): Hot-deploy retry was in progress.

## Immediate Tasks

### 1. Deploy Prediction Coordinator
The coordinator deploy failed twice with TLS handshake timeouts. Retry:
```bash
./bin/hot-deploy.sh prediction-coordinator
# or
./bin/deploy-service.sh prediction-coordinator
```

### 2. Verify All Deployments
```bash
./bin/check-deployment-drift.sh --verbose
```

All services should show commit `aa1248e0` or later.

### 3. Verify Vegas Optional Impact
After the next pipeline run with deployed code, check:
```sql
SELECT game_date,
  COUNT(*) as total_records,
  COUNTIF(is_quality_ready) as quality_ready,
  COUNTIF(required_default_count = 0) as req_defaults_zero,
  COUNTIF(default_feature_count = 0) as all_defaults_zero,
  ROUND(COUNTIF(is_quality_ready) / COUNT(*) * 100, 1) as pct_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1;
```

Before: ~37-45% quality_ready. Expected after: ~90-95% quality_ready.

### 4. Check/Finish 2025-26 Backfill
```bash
# Check remaining
bq query --use_legacy_sql=false "
SELECT COUNTIF(feature_1_source IS NULL) as missing, COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-04' AND game_date <= '2026-02-06'
"

# If still missing, restart:
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-04 --end-date 2026-02-06 --skip-preflight
```

### 5. Run 2021 Season Backfill (3,231 records)
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

### 6. Add Scraper Health Monitoring (Vegas Lines)
User wants to know when star players (PPG > 20) are missing vegas lines, since that indicates a scraper issue vs normal bench player absence. Add to canary monitoring or `/validate-daily`.

### 7. Fix PlayerDailyCacheProcessor Root Cause
The cache miss fallback is a band-aid. Fix the processor to cache ALL active season players:
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Currently queries `upcoming_player_game_context WHERE game_date = TODAY` (175 players)
- Should also query all active season players like shot zone processor does (457 players)

## Key Architecture

### Vegas Optional System (Session 145)
- `FEATURES_OPTIONAL = {25, 26, 27}` in `shared/ml/feature_contract.py`
- `default_feature_count` → ALL defaults (including vegas) → for visibility
- `required_default_count` → REQUIRED defaults only → for gating
- `is_quality_ready` uses `required_default_count == 0` (not `default_feature_count`)
- Coordinator and worker both use `required_default_count` for zero-tolerance check
- BQ column `required_default_count INT64` added to `ml_feature_store_v2`

### Cache Miss Fallback (Session 144)
- `feature_extractor.py:_compute_cache_fields_from_games()` computes from `last_10_games`
- Fixes features 0-4, 22-23, 31-32 when `player_daily_cache` misses

### Gap Tracking (Session 144)
- Table: `nba_predictions.feature_store_gaps`
- Processor logs skipped players with reason mapping
- Backfill resolves gaps on success

### Pipeline Flow for Late-Arriving Vegas Lines
Verified working: odds scraper runs continuously → feature store queries latest snapshot → Phase 4→5 orchestrator triggers prediction regeneration → old predictions superseded
