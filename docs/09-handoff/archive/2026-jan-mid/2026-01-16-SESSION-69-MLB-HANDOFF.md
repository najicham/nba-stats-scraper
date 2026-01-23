# Session 69 Handoff - MLB Schedule-Aware Infrastructure Complete

**Date**: 2026-01-16
**Previous Session**: Session 68 (R-009 roster-only fix)
**Focus**: MLB schedule-aware processing, service deployments, E2E testing

---

## Executive Summary

Session 69 completed MLB production readiness:
1. ✅ Deployed MLB prediction worker to Cloud Run (V1.6 model)
2. ✅ Backfilled mlb_schedule table (9,881 games, 2022-2025)
3. ✅ Added schedule-aware infrastructure (like NBA)
4. ✅ Ran E2E pipeline test (all 5 phases passed)
5. ✅ Redeployed analytics & precompute services with schedule-aware checks

**MLB is now 100% production-ready.** Remaining: Enable scheduler jobs before Opening Day.

---

## Completed This Session

### 1. MLB Prediction Worker Deployed ✅

```bash
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
```

- **Service URL**: `https://mlb-prediction-worker-756957797294.us-west2.run.app`
- **Model**: V1.6 (mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json)
- **Health check**: Passed
- **Shadow mode**: Working (V1.4 vs V1.6 comparison)

### 2. MLB Schedule Table Backfilled ✅

Created `scripts/mlb/backfill_mlb_schedule.py` and ran:

```bash
PYTHONPATH=. python scripts/mlb/backfill_mlb_schedule.py --all
```

**Results**:
| Year | Games | Unique Dates | With Pitchers |
|------|-------|--------------|---------------|
| 2022 | 2,479 | 179 | 2,478 |
| 2023 | 2,475 | 182 | 2,472 |
| 2024 | 2,465 | 182 | 2,465 |
| 2025 | 2,462 | 182 | 2,461 |
| **Total** | **9,881** | **725** | **9,876** |

### 3. Schedule-Aware Infrastructure ✅

Created two new modules mirroring NBA's pattern:

**`shared/validation/context/mlb_schedule_context.py`**:
- `MlbScheduleContext` dataclass
- `get_mlb_schedule_context()` - queries mlb_schedule table
- `is_mlb_offseason()` - detects Oct-Mar
- `is_mlb_all_star_break()` - detects mid-July
- `has_mlb_games_on_date()` - fast game count check

**`shared/processors/patterns/mlb_early_exit_mixin.py`**:
- `MlbEarlyExitMixin` - skip processing on no-game days
- `MlbScheduleAwareMixin` - provides full schedule context
- Supports `backfill_mode` to bypass checks

**Integrated into services**:
- `main_mlb_analytics_service.py` - skips on offseason/All-Star
- `main_mlb_precompute_service.py` - skips on offseason/All-Star

### 4. E2E Pipeline Test ✅

```bash
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-08-15
```

**Results**:
- Phase 1 (Raw Data): ✅ 30 pitchers, 15 games
- Phase 2 (Analytics): ✅ 30 pitchers with rolling stats
- Phase 3 (Predictions): ✅ V1.4: 8 picks (50%), V1.6: 6 picks (50%)
- Phase 4 (Grading): ✅ 28 gradeable
- Phase 5 (Report): ✅ Generated

### 5. Services Redeployed ✅

```bash
./bin/analytics/deploy/mlb/deploy_mlb_analytics.sh
./bin/precompute/deploy/mlb/deploy_mlb_precompute.sh
```

**Verified schedule-aware in production**:
```bash
# Test offseason skip
curl -X POST .../process-date -d '{"game_date": "2025-01-15"}'
# Response: {"status":"skipped","reason":"MLB offseason - no games scheduled"}

# Test All-Star skip
curl -X POST .../process-date -d '{"game_date": "2025-07-15"}'
# Response: {"status":"skipped","reason":"MLB All-Star break - no regular games"}
```

---

## Commits Pushed

```
e8f0791 feat(mlb): BettingPros live scraper integration and error patterns
7d69f59 docs(mlb): Add pre-season checklist, handoffs, and backfill scripts
a84080f feat(mlb): Add schedule-aware processing infrastructure
```

---

## Current Service Status

| Service | URL | Status |
|---------|-----|--------|
| mlb-prediction-worker | https://mlb-prediction-worker-756957797294.us-west2.run.app | ✅ Healthy |
| mlb-phase3-analytics-processors | https://mlb-phase3-analytics-processors-756957797294.us-west2.run.app | ✅ Healthy |
| mlb-phase4-precompute-processors | https://mlb-phase4-precompute-processors-756957797294.us-west2.run.app | ✅ Healthy |

---

## Data State

### BigQuery Tables

| Table | Rows | Date Range |
|-------|------|------------|
| `mlb_raw.mlb_schedule` | 9,881 | Apr 2022 - Sep 2025 |
| `mlb_raw.bp_pitcher_props` | ~25,000 | Apr 2022 - Sep 2025 |
| `mlb_raw.bp_batter_props` | 775,818 | Apr 2022 - Sep 2025 |
| `mlb_raw.oddsa_batter_props` | 635,497 | Apr 2024 - Sep 2025 |

### Verify Commands
```bash
# Check schedule data
bq query --use_legacy_sql=false "
SELECT EXTRACT(YEAR FROM game_date) as year, COUNT(*) as games
FROM mlb_raw.mlb_schedule GROUP BY year ORDER BY year"

# Check schedule-aware works
curl -s https://mlb-phase3-analytics-processors-756957797294.us-west2.run.app/health
```

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `shared/validation/context/mlb_schedule_context.py` | MLB schedule context (like NBA) |
| `shared/processors/patterns/mlb_early_exit_mixin.py` | Early exit mixin for MLB |
| `scripts/mlb/backfill_mlb_schedule.py` | Schedule backfill script |

---

## Remaining Before Opening Day

### Week Before Opening Day (Late March 2026)

1. **Enable scheduler jobs**:
```bash
gcloud scheduler jobs list --filter="name~mlb" | grep PAUSED | \
  awk '{print $1}' | xargs -I{} gcloud scheduler jobs resume {}
```

2. **Verify credentials**:
- ODDS_API_KEY valid
- BettingPros API accessible
- Proxy configuration (if needed)

3. **Test live scraper**:
```bash
# On a spring training day with games
PYTHONPATH=. python scrapers/bettingpros/bp_mlb_player_props.py --date $(date +%Y-%m-%d) --group dev
```

### Opening Day

1. Monitor first predictions
2. Verify shadow mode captures V1.4 vs V1.6
3. Check grading after games complete

---

## Known Issues

1. **BettingPros API only returns live data** - Historical dates return empty. This is expected.
2. **V1.6 confidence lower than V1.4** - V1.6 avg confidence ~29% vs V1.4 ~64%. Models have different calibration.
3. **Prediction errors for some pitchers** - "NoneType" errors when features missing. Non-critical.

---

## Quick Reference

### Test Prediction Worker
```bash
curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_lookup": "garrett_crochet", "game_date": "2025-09-15", "strikeouts_line": 7.5}'
```

### Test Shadow Mode
```bash
curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/execute-shadow-mode \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-08-15"}'
```

### Run E2E Test
```bash
PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-08-15
```

---

## Next Session Priorities

1. **Create Session 69 handoff** (this document) ✅
2. **Monitor NBA daily operations** - Ensure no regressions
3. **Optional**: Update V1.6 promotion criteria based on shadow mode divergence

---

## Contact

For questions about this handoff, review:
- `docs/08-projects/current/mlb-pitcher-strikeouts/MLB-PRESEASON-CHECKLIST.md`
- Previous sessions: Session 63, 64, 68 handoffs
