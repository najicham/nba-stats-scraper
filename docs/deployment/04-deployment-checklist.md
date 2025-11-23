# Deployment Checklist - Completeness Checking

**Created:** 2025-11-23 08:40:00 PST
**Last Updated:** 2025-11-23 09:58:00 PST
**Estimated Time:** 50 minutes total
**Status:** ✅ All schemas deployed | Ready to deploy processors

---

## Pre-Deployment Verification ✅

- [x] All tests passing (30/30 tests)
- [x] All 8 BigQuery schemas deployed
- [x] Circuit breaker table exists
- [x] Code committed (commit a46f572)
- [x] Helper scripts ready

---

## Phase 3: Analytics Processors (15 min)

### Deploy upcoming_player_game_context_processor

```bash
# Your deployment command here
# Example: gcloud run deploy phase3-upcoming-player-context --source=...

# Or trigger manually for testing:
python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor \
  --game-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = CURRENT_DATE()
"
```

**Expected:** ~400-450 rows, >90% prod_ready, >92% avg_completeness

---

### Deploy upcoming_team_game_context_processor

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor \
  --game-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date = CURRENT_DATE()
"
```

**Expected:** ~30 rows, >90% prod_ready, >92% avg_completeness

**✓ Phase 3 Complete** → Proceed to Phase 4

---

## Phase 4: Single-Window Processors (10 min)

### Deploy team_defense_zone_analysis_processor (RECOMMENDED FIRST)

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor \
  --analysis-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = CURRENT_DATE() - 1
"
```

**Expected:** ~30 rows, >90% prod_ready

---

### Deploy player_shot_zone_analysis_processor

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor \
  --analysis-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date = CURRENT_DATE() - 1
"
```

**Expected:** ~400-450 rows, >90% prod_ready

**✓ Single-Window Complete** → Proceed to Multi-Window

---

## Phase 4: Multi-Window Processor (5 min)

### Deploy player_daily_cache_processor

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --cache-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  COUNTIF(all_windows_complete = TRUE) as all_windows,
  ROUND(AVG(l5_completeness_pct), 2) as l5,
  ROUND(AVG(l10_completeness_pct), 2) as l10,
  ROUND(AVG(l7d_completeness_pct), 2) as l7d,
  ROUND(AVG(l14d_completeness_pct), 2) as l14d
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = CURRENT_DATE() - 1
"
```

**Expected:** ~400-450 rows, all windows >90%

**✓ Multi-Window Complete** → Proceed to Cascade

---

## Phase 4: Cascade Processors (10 min)

### Deploy player_composite_factors_processor

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --analysis-date 2024-11-22
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  COUNTIF(upstream_player_daily_cache_ready = TRUE) as upstream_ready
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = CURRENT_DATE() - 1
"
```

**Expected:** prod_ready = upstream_ready (cascade check working)

---

### Deploy ml_feature_store_processor

```bash
# Your deployment command here

# Or trigger manually:
python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
  --game-date 2024-11-23
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  COUNTIF(upstream_player_daily_cache_ready) as cache_ready,
  COUNTIF(upstream_player_composite_factors_ready) as composite_ready,
  COUNTIF(upstream_player_shot_zone_ready) as shot_ready,
  COUNTIF(upstream_upcoming_player_context_ready) as context_ready
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = CURRENT_DATE()
"
```

**Expected:** All upstreams ready = prod_ready (full cascade check working)

**✓ Phase 4 Complete** → Proceed to Phase 5

---

## Phase 5: Predictions (10 min)

### Deploy Coordinator

```bash
# Your deployment command here
# Example: gcloud run jobs deploy phase5-coordinator --source=...
```

---

### Deploy Worker

```bash
# Your deployment command here
# Example: gcloud run deploy phase5-worker --source=predictions/worker --region=us-central1
```

---

### Trigger Test Prediction

```bash
# Trigger coordinator to dispatch predictions
python predictions/coordinator/coordinator.py --game-date 2024-11-23
```

**Verify:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(is_production_ready = TRUE) as prod_ready_count,
  ROUND(AVG(completeness_percentage), 2) as avg_feature_completeness,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT system_id) as systems_used
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
"
```

**Expected:**
- 100% prod_ready_count (coordinator filtered)
- avg_feature_completeness >95%
- 5 systems_used (moving_average, zone_matchup_v1, similarity_balanced_v1, xgboost_v1, ensemble_v1)

**✓ Phase 5 Complete** → All deployments done!

---

## Post-Deployment: Helper Scripts (5 min)

### Test Circuit Breaker Status

```bash
./scripts/completeness/check-circuit-breaker-status --active-only
```

**Expected:** 0-5 active circuit breakers (normal)

---

### Test Completeness Check (Player)

```bash
./scripts/completeness/check-completeness --entity lebron_james --date 2024-11-22
```

**Expected:** Detailed completeness breakdown for player

---

### Test Completeness Check (Team)

```bash
./scripts/completeness/check-completeness --entity LAL --date 2024-11-22
```

**Expected:** Detailed completeness breakdown for team

**✓ Helper Scripts Working** → Deployment complete!

---

## Overall Health Check

Run comprehensive health query:

```bash
bq query --use_legacy_sql=false "
WITH processor_health AS (
  SELECT 'team_defense_zone_analysis' as processor,
         COUNT(*) as total,
         COUNTIF(is_production_ready = TRUE) as production_ready,
         ROUND(AVG(completeness_percentage), 2) as avg_completeness
  FROM \`nba_precompute.team_defense_zone_analysis\`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL
  SELECT 'player_shot_zone_analysis', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_precompute.player_shot_zone_analysis\`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL
  SELECT 'player_daily_cache', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_precompute.player_daily_cache\`
  WHERE cache_date = CURRENT_DATE() - 1

  UNION ALL
  SELECT 'player_composite_factors', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_precompute.player_composite_factors\`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL
  SELECT 'ml_feature_store', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_predictions.ml_feature_store_v2\`
  WHERE game_date = CURRENT_DATE()

  UNION ALL
  SELECT 'upcoming_player_game_context', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_analytics.upcoming_player_game_context\`
  WHERE game_date = CURRENT_DATE()

  UNION ALL
  SELECT 'upcoming_team_game_context', COUNT(*),
         COUNTIF(is_production_ready = TRUE),
         ROUND(AVG(completeness_percentage), 2)
  FROM \`nba_analytics.upcoming_team_game_context\`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  processor,
  total,
  production_ready,
  ROUND(100.0 * production_ready / NULLIF(total, 0), 2) as production_ready_pct,
  avg_completeness,
  CASE
    WHEN ROUND(100.0 * production_ready / NULLIF(total, 0), 2) >= 95 THEN 'EXCELLENT'
    WHEN ROUND(100.0 * production_ready / NULLIF(total, 0), 2) >= 90 THEN 'GOOD'
    WHEN ROUND(100.0 * production_ready / NULLIF(total, 0), 2) >= 80 THEN 'WARNING'
    ELSE 'CRITICAL'
  END as status
FROM processor_health
ORDER BY production_ready_pct ASC
"
```

**Target Metrics:**
- ✅ Production Ready % >90%
- ✅ Avg Completeness >92%
- ✅ All processors GOOD or EXCELLENT status

---

## Success Checklist

- [ ] Phase 3 processors deployed (2)
- [ ] Phase 4 single-window deployed (2)
- [ ] Phase 4 multi-window deployed (1)
- [ ] Phase 4 cascade deployed (2)
- [ ] Phase 5 coordinator deployed (1)
- [ ] Phase 5 worker deployed (1)
- [ ] Helper scripts tested (3)
- [ ] Overall health check passed
- [ ] Production ready % >90%
- [ ] Active circuit breakers <10
- [ ] No errors in logs

---

## Troubleshooting

### Issue: No data in completeness columns
**Fix:** Re-run processor - columns exist, just need to be populated

### Issue: All entities skipped
**Likely:** Bootstrap mode not activating (check season_start_date in processor)
**Fix:** Verify date is within 30 days of season start

### Issue: Circuit breaker trips immediately
**Likely:** Upstream data incomplete
**Fix:** Check upstream processor ran successfully, use helper script to investigate

### Issue: ImportError for CompletenessChecker
**Fix:** Verify `shared/utils/completeness_checker.py` is deployed with processor

---

## Documentation

- **Full deployment plan:** `DEPLOYMENT_PLAN_COMPLETENESS_ROLLOUT.md`
- **Deployment status:** `DEPLOYMENT_STATUS_COMPLETENESS.md`
- **Quick start guide:** `docs/completeness/01-quick-start.md`
- **Operations runbook:** `docs/completeness/02-operational-runbook.md`
- **Helper scripts:** `docs/completeness/03-helper-scripts.md`

---

**Estimated Total Time:** 50 minutes
**Status:** ✅ Ready to Deploy
**Risk:** LOW (schemas deployed, code tested, backwards compatible)

Let's go! 🚀
