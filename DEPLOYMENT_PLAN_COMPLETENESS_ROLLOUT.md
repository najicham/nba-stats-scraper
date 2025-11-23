# Completeness Checking - Deployment Plan

**Date:** 2025-11-22
**Status:** Ready for Deployment
**Test Results:** ✅ All 30 tests passing (22 unit + 8 integration)
**Impact:** Zero downtime, backwards compatible
**Estimated Time:** 2 weeks for safe gradual rollout

---

## Executive Summary

Deploy completeness checking across all phases (3, 4, 5) to ensure processors only run when they have sufficient upstream data (≥90% complete). This prevents low-quality outputs and infinite reprocessing loops.

**Coverage:**
- 7 processors (Phase 3 + 4)
- 8 BigQuery schemas (156 new columns)
- 3 Phase 5 files (predictions)
- 5 helper scripts for operations
- Comprehensive documentation

**Risk Level:** LOW (backwards compatible, well-tested, gradual rollout)

---

## Pre-Deployment Checklist

### Code Verification ✅

- [x] All 30 tests passing
- [x] Code reviewed and changes understood
- [x] Git changes ready to commit
- [ ] One final code review (spot-check one processor)
- [ ] Documentation reviewed

### Environment Verification

- [ ] BigQuery access confirmed
- [ ] Deployment pipeline ready
- [ ] Monitoring tools available
- [ ] Helper scripts executable
- [ ] Team notified of upcoming changes

---

## Day 1: Code Review, Commit & Schema Deployment

### Morning (2-3 hours)

#### 1. Final Code Review (30 minutes)

**Spot-check one processor diff:**
```bash
git diff data_processors/precompute/player_daily_cache/player_daily_cache_processor.py | less
```

**Verify these patterns:**
- ✓ CompletenessChecker import at top
- ✓ self.completeness_checker initialized in __init__()
- ✓ check_completeness_batch() called before processing loop
- ✓ Skip logic for incomplete entities (if not is_production_ready and not bootstrap)
- ✓ 14+ completeness fields in output dict
- ✓ Circuit breaker recording for skipped entities

**Quick spot-check schema:**
```bash
git diff schemas/bigquery/precompute/player_daily_cache.sql | grep "ADD COLUMN IF NOT EXISTS"
```

**Verify:**
- ✓ ADD COLUMN IF NOT EXISTS (backwards compatible)
- ✓ 23 columns for multi-window (14 standard + 9 window-specific)
- ✓ Proper descriptions in OPTIONS

**If everything looks good → proceed to commit**

---

#### 2. Commit Code (30 minutes)

**Option A: Single Commit (Faster)**
```bash
cd /home/naji/code/nba-stats-scraper

git add shared/utils/completeness_checker.py
git add tests/unit/utils/
git add tests/integration/test_completeness_integration.py
git add data_processors/
git add schemas/bigquery/
git add predictions/
git add scripts/completeness/
git add docs/completeness/
git add docs/monitoring/
git add DOCUMENTATION_REORGANIZATION_COMPLETE.md

git commit -m "Add completeness checking across all phases (Phase 3/4/5)

- Add CompletenessChecker service (389 lines, 30 tests)
- Integrate completeness checking into 7 processors (Phase 3 + 4)
- Add 156 completeness columns to 8 BigQuery schemas
- Integrate Phase 5 predictions (coordinator + worker)
- Add 5 helper scripts for circuit breaker management
- Create comprehensive documentation (docs/completeness/)
- Add Grafana dashboard and monitoring queries

Coverage: 100% (all phases)
Impact: Zero downtime (ADD COLUMN IF NOT EXISTS)
Testing: 30 tests passing (22 unit + 8 integration)

Deployment order:
1. Deploy schemas (backwards compatible)
2. Deploy processors (one at a time recommended)
3. Monitor with helper scripts

See docs/completeness/README.md for complete documentation"

git push origin main
```

**Option B: Multiple Commits (Better for review)**

See detailed commit strategy in earlier conversation notes.

**Recommendation:** Use Option A since tests are passing and you reviewed the changes.

---

#### 3. Deploy BigQuery Schemas (30 minutes)

**Deploy in this order (backwards compatible):**

```bash
# Phase 4 Precompute (5 tables)
cd /home/naji/code/nba-stats-scraper

echo "Deploying team_defense_zone_analysis schema..."
bq query --use_legacy_sql=false < schemas/bigquery/precompute/team_defense_zone_analysis.sql

echo "Deploying player_shot_zone_analysis schema..."
bq query --use_legacy_sql=false < schemas/bigquery/precompute/player_shot_zone_analysis.sql

echo "Deploying player_daily_cache schema..."
bq query --use_legacy_sql=false < schemas/bigquery/precompute/player_daily_cache.sql

echo "Deploying player_composite_factors schema..."
bq query --use_legacy_sql=false < schemas/bigquery/precompute/player_composite_factors.sql

echo "Deploying ml_feature_store_v2 schema..."
bq query --use_legacy_sql=false < schemas/bigquery/predictions/04_ml_feature_store_v2.sql

# Phase 3 Analytics (2 tables)
echo "Deploying upcoming_player_game_context schema..."
bq query --use_legacy_sql=false < schemas/bigquery/analytics/upcoming_player_game_context_tables.sql

echo "Deploying upcoming_team_game_context schema..."
bq query --use_legacy_sql=false < schemas/bigquery/analytics/upcoming_team_game_context_tables.sql

# Phase 5 Predictions (1 table - only if exists)
# Check if table exists first
bq show nba_predictions.player_prop_predictions 2>/dev/null
if [ $? -eq 0 ]; then
  echo "Deploying player_prop_predictions schema..."
  bq query --use_legacy_sql=false < schemas/bigquery/predictions/01_player_prop_predictions.sql
else
  echo "Skipping player_prop_predictions (table doesn't exist yet)"
fi
```

**Verify Schemas Deployed:**
```bash
# Check one table
bq show --schema --format=prettyjson nba-props-platform:nba_precompute.player_daily_cache | grep -A 2 "expected_games_count"

# Should see:
# {
#   "name": "expected_games_count",
#   "type": "INTEGER",
#   "description": "Games expected from schedule"
# }

# Verify column counts
echo "team_defense_zone_analysis:"
bq show --schema nba_precompute.team_defense_zone_analysis | wc -l
# Expected: 48 fields

echo "player_daily_cache:"
bq show --schema nba_precompute.player_daily_cache | wc -l
# Expected: 66 fields
```

**Expected Output:**
- ✅ "Table ... successfully updated" for each ALTER TABLE
- ✅ No errors
- ✅ Correct field counts

**If errors occur:**
- Check error message
- Verify table exists: `bq show nba_precompute.player_daily_cache`
- Verify syntax in SQL file
- Try one ALTER COLUMN at a time if needed

---

### Afternoon (1-2 hours)

#### 4. Deploy Canary Processor (team_defense_zone_analysis)

**Why this one first:**
- Simplest pattern (single-window)
- Processes teams (only 30 entities vs 450 players)
- Fast to run (~2 minutes)
- Easy to verify

**Deployment Steps:**

```bash
# Your deployment method here - examples:

# Option A: Cloud Run
gcloud run deploy team-defense-zone-analysis \
  --source=data_processors/precompute/team_defense_zone_analysis \
  --region=us-central1

# Option B: Your deployment script
./deploy_processor.sh team_defense_zone_analysis

# Option C: Manual trigger for testing
python -m data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor \
  --analysis-date 2024-11-21
```

**Monitor Deployment:**

Watch logs for these key messages:
```
✓ "Initialized CompletenessChecker"
✓ "Completeness check complete. Bootstrap mode: False, Season boundary: False"
✓ "Processing LAL (completeness: 100.0%)"
✓ "Skipping PHX (completeness: 85.0%) - incomplete data"
✓ "Writing 25 teams to BigQuery"
```

**Red flags to watch for:**
```
❌ ImportError: No module named 'completeness_checker'
❌ AttributeError: 'CompletenessChecker' object has no attribute...
❌ BigQuery error: Column 'expected_games_count' not found
❌ All entities skipped
❌ Circuit breaker tripped for all entities
```

---

#### 5. Verify Canary Output (15 minutes)

```bash
# Check output has completeness fields
bq query --use_legacy_sql=false "
SELECT
  team_abbr,
  analysis_date,
  expected_games_count,
  actual_games_count,
  completeness_percentage,
  is_production_ready,
  processing_decision_reason
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date = '2024-11-21'
ORDER BY completeness_percentage DESC
LIMIT 10
"
```

**Expected Results:**
- ✓ Rows returned (not empty)
- ✓ `completeness_percentage` populated (not NULL)
- ✓ `is_production_ready` = TRUE for most teams (>90%)
- ✓ `processing_decision_reason` = 'processed_successfully' for production-ready
- ✓ `expected_games_count` and `actual_games_count` populated

**Sample expected output:**
```
team_abbr | expected | actual | completeness | is_production_ready | reason
----------|----------|--------|--------------|---------------------|---------------------------
LAL       | 15       | 15     | 100.0        | true                | processed_successfully
GSW       | 15       | 15     | 100.0        | true                | processed_successfully
BOS       | 15       | 14     | 93.3         | true                | processed_successfully
PHX       | 15       | 13     | 86.7         | false               | incomplete_upstream_data
```

**If output is wrong:**
- Check if schema deployed: `bq show --schema nba_precompute.team_defense_zone_analysis | grep expected_games`
- Check processor logs for errors
- Verify completeness_checker.py was deployed
- Test locally if needed

---

#### 6. Test Helper Scripts (10 minutes)

```bash
cd /home/naji/code/nba-stats-scraper

# Test circuit breaker status script
./scripts/completeness/check-circuit-breaker-status --active-only

# Expected: Either "No active circuit breakers" or a list of entities

# Test completeness check script
./scripts/completeness/check-completeness --entity LAL --date 2024-11-21

# Expected: Completeness details for LAL team
```

**If scripts don't work:**
```bash
# Make sure they're executable
chmod +x scripts/completeness/*

# Check shebang line
head -1 scripts/completeness/check-circuit-breaker-status
# Should be: #!/usr/bin/env python3 or #!/bin/bash
```

---

### End of Day 1

**Deliverables:**
- ✅ Code committed and pushed
- ✅ All schemas deployed (8 tables)
- ✅ Canary processor deployed (team_defense_zone_analysis)
- ✅ Output verified with completeness fields
- ✅ Helper scripts tested

**Monitor overnight:**
- Check if processor runs on schedule
- Review logs for any errors
- Check circuit breaker status in morning

---

## Day 2-3: Monitor Canary & Deploy Single-Window Processors

### Morning - Day 2 (1 hour)

#### 1. Canary Health Check (20 minutes)

```bash
# Check circuit breaker status
./scripts/completeness/check-circuit-breaker-status --active-only

# Expected: 0-2 active circuit breakers (normal variation)
# Alert if: >5 active circuit breakers

# Check completeness for sample teams
./scripts/completeness/check-completeness --entity LAL --date 2024-11-21
./scripts/completeness/check-completeness --entity GSW --date 2024-11-21

# Review processor logs from overnight run
# (Your log viewing method)
```

**Health Criteria:**
- ✅ Processor ran successfully
- ✅ <5 active circuit breakers
- ✅ >90% of teams are production-ready
- ✅ No errors in logs
- ✅ Output matches yesterday's pattern

**If unhealthy:**
- Investigate circuit breakers
- Check logs for errors
- Don't proceed to next deployment
- Fix issues first

---

#### 2. Deploy Second Processor: player_shot_zone_analysis (30 minutes)

**If canary is healthy, deploy next single-window processor:**

```bash
# Deploy player_shot_zone_analysis
# (Your deployment command)

# Trigger test run
# (Your trigger method)
```

**Monitor:**
- Similar pattern to canary
- More entities (450 players vs 30 teams)
- Longer runtime (~10 minutes vs 2 minutes)

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  analysis_date,
  completeness_percentage,
  is_production_ready,
  COUNT(*) OVER() as total_records
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date = '2024-11-21'
ORDER BY completeness_percentage DESC
LIMIT 10
"
```

**Expected:**
- ~400-450 player records
- >90% with is_production_ready = TRUE
- Completeness fields populated

---

### Afternoon - Day 2 (1 hour)

#### 3. Monitor Both Single-Window Processors

**Check health of both:**
```bash
# Circuit breakers across both processors
./scripts/completeness/check-circuit-breaker-status --active-only

# Sample completeness checks
./scripts/completeness/check-completeness --entity lebron_james --date 2024-11-21
```

**Run monitoring queries:**
```sql
-- Overall health across both processors
SELECT
  'team_defense_zone_analysis' as processor,
  COUNT(*) as total,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'player_shot_zone_analysis' as processor,
  COUNT(*) as total,
  ROUND(AVG(completeness_percentage), 2) as avg_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE() - 1
ORDER BY processor;
```

**Target Metrics:**
- avg_completeness: >92%
- production_ready_pct: >90%

---

### Day 3 - Monitor

**No new deployments. Just monitor:**
- Check logs
- Review circuit breakers
- Ensure stable operation
- Investigate any anomalies

**If stable for 48 hours → proceed to Day 4**

---

## Day 4-5: Deploy Multi-Window Processors

### Day 4 Morning (2 hours)

#### Deploy player_daily_cache

**Most complex processor (multi-window: L5, L10, L7d, L14d)**

```bash
# Deploy player_daily_cache
# (Your deployment command)
```

**Monitor carefully:**
- This processor has 4 windows to check
- ALL windows must be ≥90% for is_production_ready = TRUE
- Expect lower production_ready_pct initially

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  completeness_percentage,
  l5_completeness_pct,
  l10_completeness_pct,
  l7d_completeness_pct,
  l14d_completeness_pct,
  all_windows_complete,
  is_production_ready
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE analysis_date = '2024-11-21'
ORDER BY is_production_ready DESC, completeness_percentage DESC
LIMIT 20
"
```

**Expected:**
- ~400-450 player records
- Per-window completeness populated
- all_windows_complete matches is_production_ready
- Some players may have incomplete windows (normal)

---

### Day 4 Afternoon (1 hour)

#### Deploy upcoming_player_game_context

**Multi-window: 5 windows (L5, L10, L7d, L14d, L30d)**

```bash
# Deploy upcoming_player_game_context
# (Your deployment command)
```

**This is a Phase 3 Analytics processor (runs earlier in pipeline)**

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  game_date,
  completeness_percentage,
  is_production_ready,
  all_windows_complete
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = CURRENT_DATE()
LIMIT 10
"
```

---

### Day 5 Morning (1 hour)

#### Deploy upcoming_team_game_context

**Multi-window: 2 windows (L7d, L14d)**

```bash
# Deploy upcoming_team_game_context
# (Your deployment command)
```

**Simpler than player contexts (only 2 windows, 30 teams)**

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  team_abbr,
  game_date,
  completeness_percentage,
  l7d_completeness_pct,
  l14d_completeness_pct,
  is_production_ready
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date = CURRENT_DATE()
LIMIT 10
"
```

---

### Day 5 Afternoon - Monitor All Multi-Window

**Check health across all 3 multi-window processors:**

```bash
./scripts/completeness/check-circuit-breaker-status --active-only
```

**Run comprehensive health query:**
```sql
-- Multi-window processor health
SELECT
  processor,
  total_records,
  avg_completeness,
  production_ready_pct,
  avg_windows_complete_pct
FROM (
  SELECT
    'player_daily_cache' as processor,
    COUNT(*) as total_records,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
    ROUND(100.0 * SUM(CASE WHEN all_windows_complete THEN 1 ELSE 0 END) / COUNT(*), 2) as avg_windows_complete_pct
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'upcoming_player_game_context' as processor,
    COUNT(*) as total_records,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
    ROUND(100.0 * SUM(CASE WHEN all_windows_complete THEN 1 ELSE 0 END) / COUNT(*), 2) as avg_windows_complete_pct
  FROM `nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE()

  UNION ALL

  SELECT
    'upcoming_team_game_context' as processor,
    COUNT(*) as total_records,
    ROUND(AVG(completeness_percentage), 2) as avg_completeness,
    ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
    ROUND(100.0 * SUM(CASE WHEN all_windows_complete THEN 1 ELSE 0 END) / COUNT(*), 2) as avg_windows_complete_pct
  FROM `nba_analytics.upcoming_team_game_context`
  WHERE game_date = CURRENT_DATE()
)
ORDER BY processor;
```

---

## Day 6-7: Deploy Cascade Processors

### Day 6 Morning (1 hour)

#### Deploy player_composite_factors

**Cascade dependency: 1 upstream (player_daily_cache)**

```bash
# Deploy player_composite_factors
# (Your deployment command)
```

**This checks:**
1. Own completeness (L10 games)
2. Upstream completeness (player_daily_cache.is_production_ready)

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  analysis_date,
  completeness_percentage,
  is_production_ready,
  upstream_player_daily_cache_ready,
  processing_decision_reason
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = '2024-11-21'
ORDER BY is_production_ready DESC
LIMIT 20
"
```

**Expected:**
- is_production_ready TRUE only if BOTH own AND upstream complete
- upstream_player_daily_cache_ready field populated
- Some players may be skipped due to upstream

---

### Day 6 Afternoon (1 hour)

#### Deploy ml_feature_store

**Cascade dependencies: 4 upstreams**
- player_daily_cache
- player_composite_factors
- player_shot_zone_analysis
- upcoming_player_game_context

**Most complex processor - most dependencies**

```bash
# Deploy ml_feature_store
# (Your deployment command)
```

**Verify output:**
```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  analysis_date,
  completeness_percentage,
  is_production_ready,
  upstream_player_daily_cache_ready,
  upstream_player_composite_factors_ready,
  upstream_player_shot_zone_ready,
  upstream_upcoming_player_context_ready,
  processing_decision_reason
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE analysis_date = '2024-11-21'
ORDER BY is_production_ready DESC
LIMIT 20
"
```

**Expected:**
- is_production_ready TRUE only if ALL upstreams ready
- All upstream_*_ready fields populated
- Lower production_ready_pct than other processors (due to cascade)

---

### Day 7 - Monitor All Cascade

**Check cascade health:**

```sql
-- Cascade processor dependencies
SELECT
  'player_composite_factors' as processor,
  COUNT(*) as total,
  ROUND(AVG(completeness_percentage), 2) as avg_own_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
  ROUND(100.0 * SUM(CASE WHEN upstream_player_daily_cache_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as upstream_ready_pct
FROM `nba_precompute.player_composite_factors`
WHERE analysis_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'ml_feature_store' as processor,
  COUNT(*) as total,
  ROUND(AVG(completeness_percentage), 2) as avg_own_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct,
  ROUND(100.0 * MIN(
    CASE WHEN upstream_player_daily_cache_ready THEN 100 ELSE 0 END,
    CASE WHEN upstream_player_composite_factors_ready THEN 100 ELSE 0 END,
    CASE WHEN upstream_player_shot_zone_ready THEN 100 ELSE 0 END,
    CASE WHEN upcoming_player_context_ready THEN 100 ELSE 0 END
  ), 2) as min_upstream_ready_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE analysis_date = CURRENT_DATE() - 1;
```

---

## Day 8-9: Deploy Phase 5 Predictions (If Running)

### Day 8 (1-2 hours)

**Only if predictions are actively running in production**

#### Deploy predictions coordinator + worker

```bash
# Deploy coordinator
# (Your deployment command for coordinator)

# Deploy worker
# (Your deployment command for worker)
```

**Verify coordinator filtering:**

Check coordinator logs for:
```
✓ "Summary: 450 players (420 production ready, avg completeness: 94.5%)"
✓ "Dispatching 420 production-ready players to workers"
```

**Verify worker validation:**

Check worker logs for:
```
✓ "Loaded features for lebron_james (completeness: 95.0%, production_ready: True)"
✓ "Processing lebron_james in normal mode"
✗ "Features not production-ready for player_x (completeness: 85.0%) - skipping"
```

**Verify prediction output:**

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  predicted_points,
  confidence_score,
  completeness_percentage,
  is_production_ready,
  processing_decision_reason
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'ensemble_v1'
ORDER BY confidence_score DESC
LIMIT 20
"
```

**Expected:**
- All predictions have is_production_ready = TRUE (filtered by coordinator)
- completeness_percentage populated
- processing_decision_reason = 'processed_successfully'

---

### Day 9 - Monitor Phase 5

**Check prediction quality:**

```sql
SELECT
  COUNT(*) as total_predictions,
  ROUND(AVG(completeness_percentage), 2) as avg_feature_completeness,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE;
```

**Expected:**
- 100% production_ready (coordinator filtered)
- avg_feature_completeness >95%

---

## Day 10+: Production Hardening

### Import Grafana Dashboard (1 hour)

1. Open Grafana
2. Navigate to Dashboards → Import
3. Upload `docs/monitoring/completeness-grafana-dashboard.json`
4. Select BigQuery data source
5. Click Import

**Verify dashboard:**
- All 9 panels load
- Data populates correctly
- No errors

**Set up alerts:**
- Panel 2: Alert when >10 active circuit breakers
- Panel 1: Alert when production_ready_pct <90%

---

### Train Team (2 hours)

**Walkthrough with operations team:**

1. **Daily health check** (5 minutes)
   ```bash
   ./scripts/completeness/check-circuit-breaker-status --active-only
   ```

2. **Investigate incomplete entity** (10 minutes)
   ```bash
   ./scripts/completeness/check-completeness --entity lebron_james --date 2024-11-21
   ```

3. **Override circuit breaker** (15 minutes)
   ```bash
   ./scripts/completeness/override-circuit-breaker \
     --processor player_daily_cache \
     --entity lebron_james \
     --date 2024-11-21 \
     --reason "Data now available after scraper fix"
   ```

4. **Review Grafana dashboard** (30 minutes)

5. **Review operational runbook** (60 minutes)
   - `docs/completeness/02-operational-runbook.md`

---

### Establish SLAs

**Recommended SLAs:**

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Production Ready % | >95% | <90% |
| Active Circuit Breakers | <5 | >10 |
| Avg Completeness % | >92% | <85% |
| Circuit Breaker Response Time | <4 hours | <24 hours |

**Set up automated alerts in Grafana**

---

## Success Criteria

### Deployment Success

- [x] All schemas deployed (8 tables)
- [ ] All processors deployed (7 processors)
- [ ] Phase 5 deployed (if applicable)
- [ ] All deployments successful (no rollbacks)
- [ ] No production incidents

### Quality Metrics (After 1 Week)

- [ ] Production ready % >90% across all processors
- [ ] <10 active circuit breakers
- [ ] Avg completeness >92%
- [ ] No data quality incidents
- [ ] Circuit breaker false positive rate <5%

### Operational Readiness

- [ ] Helper scripts working and tested
- [ ] Grafana dashboard imported and monitored
- [ ] Team trained on runbook
- [ ] SLAs established and documented
- [ ] Monitoring alerts configured

---

## Rollback Plan

### If Schema Deployment Fails

**Schemas are additive (ADD COLUMN IF NOT EXISTS), so rollback not needed**

But if you need to remove columns:
```sql
ALTER TABLE `nba-props-platform.nba_precompute.player_daily_cache`
DROP COLUMN IF EXISTS expected_games_count,
DROP COLUMN IF EXISTS actual_games_count,
-- ... drop all completeness columns
```

**Not recommended unless absolutely necessary**

---

### If Processor Deployment Fails

**Processors are backwards compatible (handle missing columns gracefully)**

**Option 1: Rollback processor code**
```bash
# Redeploy previous version
git checkout HEAD~1
# Deploy old version
# (Your deployment command)
```

**Option 2: Disable completeness checking**
- Schemas remain (no harm)
- Old processor code works without completeness
- Fix issue, redeploy when ready

---

### If Circuit Breakers Trip Too Much

**Scenario:** >50% of entities have active circuit breakers

**Investigate:**
```bash
./scripts/completeness/check-circuit-breaker-status --active-only
```

**Possible causes:**
1. Scraper outage (upstream data missing) → Wait for scraper fix
2. Threshold too strict (90% too high) → Review threshold
3. Bootstrap mode not activating → Check season_start_date
4. Bug in completeness logic → Check logs

**Quick fix (if false positives):**
```bash
# Bulk override circuit breakers
./scripts/completeness/bulk-override-circuit-breaker \
  --date-from 2024-11-20 \
  --date-to 2024-11-22 \
  --reason "False positives - threshold tuning needed"
```

---

## Common Issues & Solutions

### Issue 1: ImportError - CompletenessChecker not found

**Symptom:**
```
ImportError: No module named 'shared.utils.completeness_checker'
```

**Cause:** `completeness_checker.py` not deployed

**Fix:**
```bash
# Verify file exists
ls -la shared/utils/completeness_checker.py

# Redeploy processor with all dependencies
# (Your deployment command)
```

---

### Issue 2: Column not found

**Symptom:**
```
BigQuery error: Column 'expected_games_count' not found
```

**Cause:** Schema not deployed

**Fix:**
```bash
# Deploy schema
bq query --use_legacy_sql=false < schemas/bigquery/precompute/player_daily_cache.sql

# Verify column exists
bq show --schema nba_precompute.player_daily_cache | grep expected_games_count
```

---

### Issue 3: All entities skipped

**Symptom:** Processor logs show all entities skipped

**Cause 1:** Bootstrap mode not activating (early season)

**Fix:**
```python
# Check season_start_date in processor
self.season_start_date = date(2024, 10, 1)  # Verify correct date
```

**Cause 2:** Upstream data genuinely incomplete

**Fix:**
```bash
# Investigate upstream data
./scripts/completeness/check-completeness --entity lebron_james --date 2024-11-21

# Check if scraper is running
# Verify game data exists
```

---

### Issue 4: Circuit breaker tripping immediately

**Symptom:** Entities hit circuit breaker after 1 attempt instead of 3

**Cause:** Bug in circuit breaker logic

**Fix:**
```bash
# Check orchestration table
bq query --use_legacy_sql=false "
SELECT * FROM nba_orchestration.reprocess_attempts
WHERE entity_id = 'lebron_james'
ORDER BY created_at DESC
LIMIT 5
"

# Verify attempt_count incrementing correctly
# Should be 1, 2, 3 before circuit_breaker_tripped = TRUE
```

---

## Monitoring Queries

### Daily Health Check Query

```sql
WITH processor_health AS (
  SELECT 'team_defense_zone_analysis' as processor,
         COUNT(*) as total,
         ROUND(AVG(completeness_percentage), 2) as avg_completeness,
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2) as production_ready_pct
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'player_shot_zone_analysis',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'player_daily_cache',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_precompute.player_daily_cache`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'player_composite_factors',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_precompute.player_composite_factors`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'ml_feature_store',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE analysis_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'upcoming_player_game_context',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE()

  UNION ALL

  SELECT 'upcoming_team_game_context',
         COUNT(*), ROUND(AVG(completeness_percentage), 2),
         ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 2)
  FROM `nba_analytics.upcoming_team_game_context`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  processor,
  total,
  avg_completeness,
  production_ready_pct,
  CASE
    WHEN production_ready_pct >= 95 THEN '✅ EXCELLENT'
    WHEN production_ready_pct >= 90 THEN '✓ GOOD'
    WHEN production_ready_pct >= 80 THEN '⚠ WARNING'
    ELSE '🚨 CRITICAL'
  END as status
FROM processor_health
ORDER BY production_ready_pct ASC;
```

---

### Active Circuit Breakers Query

```sql
SELECT
  processor_name,
  entity_id,
  analysis_date,
  completeness_pct,
  attempt_count,
  skip_reason,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining,
  created_at
FROM `nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
  AND manual_override_applied = FALSE
ORDER BY days_remaining DESC, processor_name, entity_id;
```

---

## Documentation Reference

**Quick Links:**

| Document | Purpose | Link |
|----------|---------|------|
| Quick Start | 5-min ops guide | docs/completeness/01-quick-start.md |
| Operational Runbook | Complete procedures | docs/completeness/02-operational-runbook.md |
| Helper Scripts | Script documentation | docs/completeness/03-helper-scripts.md |
| Implementation Guide | Technical details | docs/completeness/04-implementation-guide.md |
| Monitoring Guide | Dashboards & alerts | docs/completeness/05-monitoring.md |
| Overview | System architecture | docs/completeness/00-overview.md |

---

## Timeline Summary

| Day | Focus | Time | Deliverables |
|-----|-------|------|--------------|
| 1 | Code review, commit, schemas, canary | 4-5h | Code committed, schemas deployed, 1 processor deployed |
| 2-3 | Monitor canary, deploy single-window | 2h | 2 processors deployed, 48h monitoring |
| 4-5 | Deploy multi-window processors | 3h | 3 processors deployed |
| 6-7 | Deploy cascade processors | 2h | 2 processors deployed |
| 8-9 | Deploy Phase 5 (optional) | 2h | Predictions integrated |
| 10+ | Production hardening | 3h | Dashboard, training, SLAs |

**Total:** ~2 weeks for safe gradual rollout

---

## Final Checklist

### Pre-Deployment
- [x] Tests passing (30/30)
- [ ] Code reviewed
- [ ] Team notified
- [ ] Deployment pipeline ready

### Deployment
- [ ] Code committed and pushed
- [ ] Schemas deployed (8 tables)
- [ ] Processors deployed (7 processors)
- [ ] Phase 5 deployed (if applicable)
- [ ] No rollbacks required

### Validation
- [ ] Output verified (completeness fields populated)
- [ ] Helper scripts working
- [ ] Circuit breakers functioning correctly
- [ ] No unexpected errors

### Production Hardening
- [ ] Grafana dashboard imported
- [ ] Alerts configured
- [ ] Team trained
- [ ] SLAs established
- [ ] Runbook reviewed

---

## Contact & Escalation

**For Issues:**
1. Check operational runbook first: `docs/completeness/02-operational-runbook.md`
2. Use helper scripts to diagnose: `./scripts/completeness/check-*`
3. Review monitoring dashboard
4. Escalate if needed

**Emergency Contacts:**
- Engineering team lead
- On-call engineer
- Database team (for schema issues)

---

**Status:** ✅ READY TO DEPLOY
**Confidence Level:** HIGH
**Risk Level:** LOW
**Next Action:** Day 1 - Code review and commit

🚀 Good luck with the deployment!
