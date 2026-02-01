# Cross-Phase Troubleshooting Matrix

**File:** `docs/operations/cross-phase-troubleshooting-matrix.md`
**Created:** 2025-11-15
**Last Updated:** 2025-12-27
**Purpose:** Symptom-based troubleshooting that traces issues backward through the pipeline
**Audience:** On-call engineers debugging production issues

---

## How to Use This Guide

**This is NOT a replacement for phase-specific troubleshooting docs.** Instead, it's a **symptom-based index** that helps you:
1. Identify which phase is causing the problem
2. Find the relevant detailed troubleshooting doc
3. Trace issues backward through dependencies

**Phase-Specific Troubleshooting Docs:**
- **Phase 1 Orchestration:** `docs/orchestration/04-troubleshooting.md`
- **Phase 3 Analytics:** `docs/processors/04-phase3-troubleshooting.md`
- **Phase 4 Precompute:** `docs/processors/07-phase4-troubleshooting.md`
- **Phase 5 Predictions:** `docs/predictions/operations/03-troubleshooting.md`

**Processor Cards (Detailed Issues):**
- **All processors:** `docs/06-reference/processor-cards/README.md`
- **Phase 5 predictions:** `docs/06-reference/processor-cards/phase5-prediction-coordinator.md`
- **Workflow timing:** `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`
- **Real-time flow:** `docs/06-reference/processor-cards/workflow-realtime-prediction-flow.md`

---

## Quick Diagnosis Decision Tree

```
Start here: What's the symptom?
│
├─ Predictions missing/stale/wrong → Section 1: Prediction Issues
├─ Data missing in analytics tables → Section 2: Data Quality Issues
├─ Pipeline didn't run on schedule → Section 3: Timing Issues
├─ Processing taking too long → Section 4: Performance Issues
├─ Early season errors → Section 5: Early Season Issues
├─ Database/infrastructure errors → Section 6: Infrastructure Issues
└─ Dashboard/monitoring issues → Section 7: Observability Issues
```

---

## Section 1: Prediction Issues (Phase 5 Symptoms)

### 1.1 - No Predictions Generated Today

**Symptom:** `nba_predictions.player_points_predictions` has 0 rows for today.

**Potential Root Causes (trace backward):**

#### Step 1: Is Phase 5 coordinator running?
```bash
# Check if Phase 5 prediction coordinator ran today
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=phase5-prediction-coordinator \
  AND timestamp>=today" \
  --limit=1 \
  --format=json
```
- **If NO LOGS:** Coordinator didn't run → Manually trigger
- **If ERROR LOGS:** Coordinator crashed → Check error, fix, and re-trigger
- **If SUCCESS LOGS:** Continue to Step 2

#### Step 2: Is the ML Feature Store populated?
```sql
-- Check if Phase 5 has data to work with
SELECT COUNT(*) as feature_count
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```
- **If 0:** Phase 4 issue → Go to **[1.2 - Missing ML Features]**
- **If 100+:** Phase 5 logic issue → Check Phase 5 logs

#### Step 3: Are there games today?
```sql
-- Verify games scheduled
SELECT COUNT(*) as games_today
FROM `nba_raw.nbac_schedule`
WHERE game_date = CURRENT_DATE();
```
- **If 0:** Normal (off day, no predictions needed)
- **If 5+:** Data available, Phase 5 logic issue

**Fix Procedures:**
1. **Coordinator didn't run:** Manually trigger: `gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1`
2. **Phase 4 incomplete:** See Section 2.3 (must run Phase 4 first)
3. **Coordinator crashed:** Check logs for XGBoost model loading errors, feature validation errors, or worker spawn failures
4. **No prop lines:** Verify `odds_api_player_points_props` has data for today

**Common Errors:**
- "XGBoost model not found" → Deploy trained model to GCS (currently using mock model)
- "No features found for game_date" → Phase 4 didn't run, trigger ML Feature Store processor
- "Insufficient feature quality" → Phase 4 ran but quality too low (<70%), check Phase 4 dependencies

**References:**
- Phase 5 processor card: `docs/06-reference/processor-cards/phase5-prediction-coordinator.md`
- Phase 5 troubleshooting: `docs/predictions/operations/03-troubleshooting.md`
- ML Feature Store: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md`

---

### 1.2 - Missing ML Features (Phase 4 → Phase 5)

**Symptom:** `ml_feature_store_v2` has 0 rows or very few rows for today.

**Trace Backward Through Dependencies:**

#### Check 1: Did Phase 4 processors run?
```sql
-- Check all Phase 4 processors
SELECT
  'team_defense' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone', COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_composite', COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT 'player_daily_cache', COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();
```

**Expected Results:**
- Team Defense: 30 rows
- Player Shot Zone: 400-450 rows
- Player Composite: 100-450 rows (depends on games today)
- Player Daily Cache: 100-450 rows

**If any are 0 or too low:**
→ That Phase 4 processor failed → See Section 2.3

#### Check 2: Did Phase 3 context processors run?
```sql
-- Check Phase 3 context (ML Feature Store fallback)
SELECT COUNT(*) as player_context_count
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();

SELECT COUNT(*) as team_context_count
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE();
```

**Expected:** 100-450 player contexts, 20-30 team contexts (for games today)

**If 0:**
→ Phase 3 context issue → See Section 2.2

**Fix Procedures:**
1. **Phase 4 incomplete:** Manually trigger missing Phase 4 processors
2. **Phase 3 context missing:** Fix Phase 3 first, then re-run Phase 4
3. **Dependencies out of order:** Check orchestration timing

**References:**
- ML Feature Store dependencies: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md`
- Phase 4 troubleshooting: `docs/processors/07-phase4-troubleshooting.md`
- Dependency flow: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`

---

### 1.3 - Predictions Are Stale (Using Old Data)

**Symptom:** Predictions timestamp shows yesterday's data, odds have updated but predictions haven't.

**Root Cause Diagnosis:**

#### Check 1: Is the daily cache stale?
```sql
-- Check cache freshness
SELECT
  cache_date,
  COUNT(*) as player_count,
  MAX(processed_at) as cache_created,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_old
FROM `nba_precompute.player_daily_cache`
WHERE cache_date >= CURRENT_DATE() - 1
GROUP BY cache_date
ORDER BY cache_date DESC;
```

**Expected:**
- `cache_date = CURRENT_DATE()`
- `hours_old < 12` (created at midnight)

**If cache_date is yesterday:**
→ Phase 4 daily cache didn't run → See Section 2.3

#### Check 2: Did Phase 5 reload the cache today?
```bash
# Check Phase 5 startup logs for cache load
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-predictions \
  AND textPayload=~'Loading daily cache'" \
  --limit=10 \
  --format=json
```

**Look for:** Recent log entry showing cache loaded today

**If no recent cache load:**
→ Phase 5 needs restart to reload cache

**Fix Procedures:**
1. **Stale cache in BigQuery:** Re-run Phase 4 daily cache processor
2. **Phase 5 using old cache:** Restart Phase 5 service to force reload
3. **Emergency mid-day refresh:** Use cache refresh endpoint (if implemented)

**References:**
- Cache pattern: `docs/06-reference/processor-cards/phase4-player-daily-cache.md`
- Real-time flow: `docs/06-reference/processor-cards/workflow-realtime-prediction-flow.md`

---

### 1.4 - Low Confidence Predictions / All PASS Recommendations

**Symptom:** Many predictions have `ensemble_confidence < 65` or all recommendations are PASS.

**Trace Data Quality Backward:**

#### Check 1: What's the feature quality score?
```sql
-- Check feature quality distribution
SELECT
  CASE
    WHEN feature_quality_score >= 95 THEN 'Excellent (95-100)'
    WHEN feature_quality_score >= 85 THEN 'Good (85-94)'
    WHEN feature_quality_score >= 70 THEN 'Medium (70-84)'
    ELSE 'Low (<70)'
  END as quality_tier,
  COUNT(*) as player_count,
  AVG(feature_quality_score) as avg_score
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
GROUP BY quality_tier
ORDER BY avg_score DESC;
```

**If most players are "Low" or "Medium":**
→ Phase 4 data incomplete, falling back to Phase 3

#### Check 2: Which Phase 4 sources are incomplete?
```sql
-- Check source completeness in ML Feature Store
SELECT
  AVG(source_daily_cache_completeness_pct) as cache_pct,
  AVG(source_composite_completeness_pct) as composite_pct,
  AVG(source_shot_zones_completeness_pct) as shot_zones_pct,
  AVG(source_team_defense_completeness_pct) as defense_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Expected:** All > 85%

**If < 85%:**
→ That Phase 4 processor is incomplete → Check specific processor

#### Check 3: Is it early season?
```sql
-- Check early season flags
SELECT
  COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_players,
  COUNT(*) as total_players,
  ROUND(100.0 * COUNT(CASE WHEN early_season_flag THEN 1 END) / COUNT(*), 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Expected:** < 20% after week 3 of season

**If > 30%:**
→ Normal for early season → See Section 5

#### Check 4: What's the recommendation distribution?
```sql
-- Check how many actionable picks vs PASS
SELECT
  recommendation,
  COUNT(*) as count,
  AVG(ensemble_confidence) as avg_confidence,
  AVG(ABS(ensemble_prediction - prop_line)) as avg_edge
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE()
GROUP BY recommendation
ORDER BY count DESC;
```

**Expected:** 30-50% PASS, 25-35% OVER, 25-35% UNDER

**If > 70% PASS:**
→ Confidence or edge thresholds not met (intentional for quality filtering)

**Fix Procedures:**
1. **Phase 4 incomplete:** Identify and re-run failed Phase 4 processors
2. **Early season:** Expected (50-70% PASS in first 3 weeks), quality improves as season progresses
3. **Chronic low quality:** Review Phase 3 data quality
4. **All systems disagree:** Check `prediction_variance` (>6.0 = high disagreement, system marks PASS)
5. **XGBoost missing:** Only 3/4 systems running, lower ensemble confidence → more PASS

**Thresholds (in ensemble_v1.py):**
- Minimum confidence: 65 (recommendations below this are PASS)
- Minimum edge: 1.5 points (must beat line by 1.5+ to recommend)

**References:**
- Phase 5 processor card: `docs/06-reference/processor-cards/phase5-prediction-coordinator.md`
- Quality scoring: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md` (lines 112-132)
- Early season handling: Section 5
- Confidence thresholds: `docs/predictions/tutorials/01-getting-started.md` (Q3)

---

### 1.5 - XGBoost Model Errors / Only 3 Systems Predicting

**Symptom:** `systems_count = 3` instead of 4, XGBoost predictions missing.

**Root Cause:** XGBoost model not loaded or prediction failed.

#### Check 1: Is XGBoost model file present?
```bash
# Check if model exists in GCS
gsutil ls gs://nba-models-production/xgboost/current/model.json

# If not found: Currently using mock model (expected until real model trained)
```

#### Check 2: Check coordinator logs for model loading
```bash
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=phase5-prediction-coordinator \
  AND textPayload=~'XGBoost'" \
  --limit=20
```

**Look for:**
- "XGBoost model loaded successfully" → Model OK
- "Using mock XGBoost model" → Expected (real model not trained yet)
- "XGBoost model not found" → Model deployment issue

#### Check 3: Verify prediction failures
```sql
-- Check which systems are missing
SELECT
  COUNT(CASE WHEN xgboost_prediction IS NOT NULL THEN 1 END) as has_xgboost,
  COUNT(CASE WHEN moving_avg_prediction IS NOT NULL THEN 1 END) as has_moving_avg,
  COUNT(CASE WHEN zone_matchup_prediction IS NOT NULL THEN 1 END) as has_zone,
  COUNT(CASE WHEN similarity_prediction IS NOT NULL THEN 1 END) as has_similarity,
  COUNT(*) as total
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE();
```

**Expected:** All 4 counts should be close to total (>95%)

**Fix Procedures:**
1. **Mock model (expected):** Train real XGBoost model (~4 hours), deploy to GCS
2. **Model file missing:** Deploy model to `gs://nba-models-production/xgboost/current/`
3. **Model load error:** Check model compatibility (trained with same XGBoost version as worker)
4. **Prediction failures:** Check worker logs for feature compatibility errors

**Impact:**
- **3/4 systems:** Ensemble still works, confidence slightly lower (OK for production)
- **2/4 systems or fewer:** Ensemble confidence very low, most predictions become PASS

**References:**
- Phase 5 processor card: `docs/06-reference/processor-cards/phase5-prediction-coordinator.md`
- XGBoost training guide: `docs/predictions/operations/01-deployment-guide.md` (Model Training section)

---

## Section 2: Data Quality Issues

### 2.1 - Missing Raw Data (Phase 2)

**Symptom:** Phase 3 processors can't find raw data they need.

**Common Missing Tables:**
- `nba_raw.nbac_gamebook_player_stats`
- `nba_raw.bdl_player_boxscores`
- `nba_raw.nbac_team_boxscore`
- `nba_raw.odds_api_player_points_props`

#### Diagnosis: Check Phase 1 orchestration
```sql
-- Check recent scraper executions
SELECT
  workflow_name,
  status,
  scrapers_succeeded,
  scrapers_failed,
  execution_time
FROM `nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE()
ORDER BY execution_time DESC
LIMIT 20;
```

**Look for:**
- `status = 'failed'`
- `scrapers_failed > 0`

#### Check specific raw table
```sql
-- Example: Check if player boxscores exist for yesterday's games
SELECT COUNT(DISTINCT game_id) as games_with_data
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE() - 1;
```

**Compare against schedule:**
```sql
SELECT COUNT(*) as games_scheduled
FROM `nba_raw.nbac_schedule`
WHERE game_date = CURRENT_DATE() - 1;
```

**If games_with_data < games_scheduled:**
→ Phase 1 scraper failed or didn't run

**Fix Procedures:**
1. Check Phase 1 orchestration logs: `docs/orchestration/04-troubleshooting.md`
2. Manually trigger scraper for missing games
3. Verify Cloud Run service health
4. Check BigQuery write permissions

**References:**
- Phase 1 troubleshooting: `docs/orchestration/04-troubleshooting.md`
- Phase 1 workflows: `docs/orchestration/01-how-it-works.md`

---

### 2.2 - Missing Phase 3 Analytics

**Symptom:** Phase 4 processors can't find Phase 3 data they need.

**Common Missing Tables:**
- `nba_analytics.player_game_summary`
- `nba_analytics.team_offense_game_summary`
- `nba_analytics.team_defense_game_summary`
- `nba_analytics.upcoming_player_game_context`

#### Quick Check: Run Phase 3 health query
```sql
-- From Phase 3 troubleshooting doc
SELECT
  'player_game_summary' as processor,
  CASE WHEN COUNT(*) >= 200 THEN '✅ OK' ELSE '❌ FAILED' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'team_offense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'team_defense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'upcoming_player_game_context',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT 'upcoming_team_game_context',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE();
```

**Any ❌ FAILED?**
→ Check that specific processor card for detailed troubleshooting

#### Trace backward to Phase 2
If Phase 3 is missing data, check if Phase 2 has the raw data:
→ See Section 2.1

**Fix Procedures:**
1. **Phase 2 missing:** Fix Phase 1/2 first (Section 2.1)
2. **Phase 2 exists but Phase 3 empty:** Manually trigger Phase 3 processor
3. **Phase 3 failed with errors:** Check processor logs and fix validation issues

**References:**
- Phase 3 troubleshooting: `docs/processors/04-phase3-troubleshooting.md`
- Phase 3 processor cards: `docs/06-reference/processor-cards/README.md` (Phase 3 section)

**Specific Processor Cards:**
- Player Game Summary: `docs/06-reference/processor-cards/phase3-player-game-summary.md`
- Team Offense: `docs/06-reference/processor-cards/phase3-team-offense-game-summary.md`
- Team Defense: `docs/06-reference/processor-cards/phase3-team-defense-game-summary.md`
- Upcoming Player: `docs/06-reference/processor-cards/phase3-upcoming-player-game-context.md`
- Upcoming Team: `docs/06-reference/processor-cards/phase3-upcoming-team-game-context.md`

---

### 2.3 - Missing Phase 4 Precompute

**Symptom:** Phase 5 can't find Phase 4 precomputed data.

**Common Missing Tables:**
- `nba_precompute.team_defense_zone_analysis`
- `nba_precompute.player_shot_zone_analysis`
- `nba_precompute.player_composite_factors`
- `nba_precompute.player_daily_cache`
- `nba_predictions.ml_feature_store_v2`

#### Quick Check: Run Phase 4 health query
```sql
-- From Phase 4 troubleshooting doc
SELECT
  'team_defense' as processor,
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone',
  CASE WHEN COUNT(*) >= 400 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_composite',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT 'player_daily_cache',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(processed_at)
FROM `nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE()

UNION ALL

SELECT 'ml_feature_store',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*), MAX(created_at)
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```

**Critical: Check the dependency order**

Phase 4 processors have strict dependencies:

```
11:00 PM: P1 - Team Defense Zone ──┐
11:15 PM: P2 - Player Shot Zone ───┤
                                   ├─→ 11:30 PM: P3 - Player Composite ──┐
Phase 3 Context ───────────────────┘                                     │
                                                                         ├─→ 12:00 AM: P5 - ML Feature Store
Phase 3 Analytics ───────────────────────────────────────────────────────┤
Phase 4 P1-P3 ────────────────────────────────────────────────────────→ 12:00 AM: P4 - Player Daily Cache
```

**If P3 failed:**
→ Check if P1 and P2 completed first

**If P5 (ML Feature Store) failed:**
→ Check if P1, P2, P3 all completed first

#### Trace backward to Phase 3
Phase 4 depends on Phase 3 analytics:
→ See Section 2.2

**Fix Procedures:**
1. **Out of order:** Wait for dependencies, then manually trigger
2. **Dependency failed:** Fix upstream processor first
3. **Timing issue:** Check orchestration triggers

**References:**
- Phase 4 troubleshooting: `docs/processors/07-phase4-troubleshooting.md`
- Phase 4 timing: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`
- Phase 4 processor cards: `docs/06-reference/processor-cards/README.md` (Phase 4 section)

**Specific Processor Cards:**
- Team Defense Zone: `docs/06-reference/processor-cards/phase4-team-defense-zone-analysis.md`
- Player Shot Zone: `docs/06-reference/processor-cards/phase4-player-shot-zone-analysis.md`
- Player Composite: `docs/06-reference/processor-cards/phase4-player-composite-factors.md`
- Player Daily Cache: `docs/06-reference/processor-cards/phase4-player-daily-cache.md`
- ML Feature Store: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md`

---

### 2.4 - Shot Zone Data Corruption (FIXED Jan 2026)

**Symptom:** Shot zone rates look wrong - paint rate too low (<30%) or three-point rate too high (>50%).

**Historical Issue (RESOLVED):**
- **Problem:** Paint/mid-range from play-by-play (PBP), three-point from box score
- **Impact:** When PBP missing, paint/mid = 0 but three-pt = actual value → corrupted rates
- **Fix Applied:** All zone fields now from same PBP source (Session 53, Jan 31 2026)

#### Diagnosis: Check Shot Zone Completeness

```sql
-- Check if shot zones have complete PBP data
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(has_complete_shot_zones = TRUE) as complete_zones,
  ROUND(COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*), 1) as pct_complete,

  -- Zone rates for complete zones only
  ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
    THEN SAFE_DIVIDE(paint_attempts * 100.0, paint_attempts + mid_range_attempts + three_attempts_pbp)
    END), 1) as avg_paint_rate,
  ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
    THEN SAFE_DIVIDE(three_attempts_pbp * 100.0, paint_attempts + mid_range_attempts + three_attempts_pbp)
    END), 1) as avg_three_rate

FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**Expected Results:**
- `pct_complete`: 50-90% (depends on BigDataBall PBP availability)
- `avg_paint_rate`: 30-45%
- `avg_three_rate`: 20-50%

**If rates are outside expected ranges:**
1. Check `has_complete_shot_zones = TRUE` filter is applied
2. Verify BigDataBall PBP data exists for that date
3. Check for code regression (three_pt should use PBP, not box score)

#### Check BigDataBall PBP Coverage

```sql
-- Check if BigDataBall PBP data is available
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_with_bdb,
  COUNT(*) as pbp_events
FROM `nba_raw.bigdataball_play_by_play`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**Compare against schedule:**
```sql
SELECT game_date, COUNT(*) as scheduled_games
FROM `nba_reference.nba_schedule`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

**If games_with_bdb < scheduled_games:**
→ BigDataBall scraper failed or data not available yet

#### Validate Source Consistency

```sql
-- Verify three_pt_attempts matches three_attempts_pbp (should be 100%)
SELECT
  COUNTIF(three_pt_attempts = three_attempts_pbp) as matching,
  COUNTIF(three_pt_attempts != three_attempts_pbp) as mismatched,
  COUNT(*) as total
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
  AND has_complete_shot_zones = TRUE;
```

**Expected:** `matching = total`, `mismatched = 0`

**If mismatched > 0:**
→ Code regression! three_pt_attempts is using box score instead of PBP

**Fix Procedures:**
1. **Low completeness (<50%):** Normal if BigDataBall PBP unavailable - use `has_complete_shot_zones = TRUE` filter
2. **Wrong rates despite filter:** Check code - ensure `three_pt_attempts = shot_zone_data.get('three_attempts_pbp')`
3. **Historical data corrupted:** Reprocess those dates with fixed code
4. **Code regression:** Review `player_game_summary_processor.py` lines ~1686, 2275

**Impact:**
- **ML models:** Filter for `has_complete_shot_zones = TRUE` in training data
- **Analytics:** Zone rates unreliable when flag is FALSE or NULL
- **Predictions:** Shot zone features may be NULL when PBP unavailable

**Prevention:**
- Daily validation includes shot zone completeness check
- Pre-commit hook validates schema field consistency
- `has_complete_shot_zones` flag tracks data quality

**References:**
- Fix documentation: `docs/09-handoff/2026-01-31-SESSION-53-SHOT-ZONE-FIX-COMPLETE.md`
- Investigation: `docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md`
- Code: `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`

---

## Section 3: Timing Issues

### 3.1 - Pipeline Didn't Run on Schedule

**Symptom:** Expected processing didn't happen at scheduled time.

**Check Orchestration:**

#### Step 1: Verify Cloud Scheduler triggered
```bash
# Check recent Cloud Scheduler executions
gcloud scheduler jobs describe [JOB_NAME] \
  --location=us-west2 \
  --format=json | jq '.state, .lastAttemptTime'
```

#### Step 2: Check if workflow was scheduled
```sql
-- Check daily schedule generation
SELECT
  date,
  workflow_name,
  scheduled_time,
  workflow_context
FROM `nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
ORDER BY scheduled_time;
```

**If empty:**
→ Schedule generation failed (runs at 5 AM ET)

#### Step 3: Check workflow decisions
```sql
-- Check if workflows were evaluated
SELECT
  workflow_name,
  decision_time,
  action,
  reason
FROM `nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE()
ORDER BY decision_time;
```

**Look for:**
- `action = 'SKIP'` with reason explaining why
- Missing workflows (never evaluated)

#### Step 4: Check executions
```sql
-- Check if workflows actually ran
SELECT
  workflow_name,
  execution_time,
  status,
  scrapers_succeeded,
  scrapers_failed
FROM `nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE()
ORDER BY execution_time;
```

**Common Issues:**
1. **No games scheduled:** Normal, workflows skip on off-days
2. **Schedule locked:** Another instance running, check locks
3. **Workflow context missing:** Data dependencies not met
4. **Cloud Run timeout:** Long-running workflow exceeded 60min limit

**Fix Procedures:**
1. **Schedule not generated:** Manually trigger schedule generation endpoint
2. **Locks stuck:** Clear stale locks in `workflow_locks` table
3. **Dependencies missing:** Fix upstream issues first
4. **Timeout:** Reduce scraper parallelism or increase timeout

**References:**
- Phase 1 orchestration: `docs/orchestration/01-how-it-works.md`
- Phase 1 troubleshooting: `docs/orchestration/04-troubleshooting.md`
- Daily timeline: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`

---

### 3.2 - Phase 4 Ran Too Early (Missing Phase 3 Data)

**Symptom:** Phase 4 processors completed but have very low row counts.

**Root Cause:** Phase 4 started before Phase 3 finished.

#### Diagnosis: Check timing
```sql
-- Compare Phase 3 completion vs Phase 4 start
WITH phase3_times AS (
  SELECT
    'player_game_summary' as processor,
    MAX(processed_at) as completed
  FROM `nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT 'team_offense', MAX(processed_at)
  FROM `nba_analytics.team_offense_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
),
phase4_times AS (
  SELECT
    'team_defense_zone' as processor,
    MIN(processed_at) as started
  FROM `nba_precompute.team_defense_zone_analysis`
  WHERE analysis_date = CURRENT_DATE()

  UNION ALL

  SELECT 'player_shot_zone', MIN(processed_at)
  FROM `nba_precompute.player_shot_zone_analysis`
  WHERE analysis_date = CURRENT_DATE()
)
SELECT
  p3.processor as phase3_processor,
  p3.completed as phase3_completed,
  p4.processor as phase4_processor,
  p4.started as phase4_started,
  TIMESTAMP_DIFF(p4.started, p3.completed, MINUTE) as gap_minutes
FROM phase3_times p3
CROSS JOIN phase4_times p4;
```

**Expected:** gap_minutes > 0 (Phase 4 started AFTER Phase 3 finished)

**If gap_minutes < 0:**
→ Phase 4 started before Phase 3 finished!

**Fix Procedures:**
1. **Re-run Phase 4:** All processors need to re-run with complete Phase 3 data
2. **Fix orchestration:** Add dependency checks before Phase 4 triggers
3. **Adjust timing:** Cloud Scheduler Phase 4 trigger should wait for Phase 3 completion event

**Expected Timeline:**
- 10:30 PM: Phase 3 completes
- 11:00 PM: Phase 4 starts (30min buffer)

**References:**
- Daily timeline: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`
- Phase 4 dependencies: `docs/06-reference/processor-cards/README.md` (Phase 4 section)

---

### 3.3 - Cache Loaded Before Phase 4 Completed

**Symptom:** Phase 5 predictions using incomplete/stale data despite cache being "fresh".

**Root Cause:** Phase 5 started at 6 AM, but Phase 4 didn't finish until after 6 AM.

#### Diagnosis: Check Phase 4 completion time
```sql
-- When did Phase 4 actually complete?
SELECT
  MAX(processed_at) as phase4_completed,
  EXTRACT(HOUR FROM MAX(processed_at)) as completion_hour
FROM `nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();
```

**Expected:** completion_hour = 0 (midnight) or 23 (11 PM previous day)

**If completion_hour >= 1:**
→ Phase 4 ran late! Phase 5 already loaded stale cache.

#### Check Phase 5 cache load time
```bash
# Check Phase 5 startup logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-predictions \
  AND textPayload=~'Loading daily cache'" \
  --limit=1 \
  --format='value(timestamp, textPayload)'
```

**If cache loaded at 6:00 AM but Phase 4 finished at 1:00 AM:**
→ Cache is actually stale (previous day's data)

**Fix Procedures:**
1. **Immediate:** Restart Phase 5 service to reload fresh cache
2. **Root cause:** Investigate why Phase 4 ran late (see Section 3.2)
3. **Prevention:** Add health check before Phase 5 startup (verify Phase 4 complete)

**Expected Flow:**
- 11:00 PM - 12:30 AM: Phase 4 runs
- 12:30 AM - 6:00 AM: Data is stable
- 6:00 AM: Phase 5 loads cache (guaranteed complete)

**References:**
- Cache pattern: `docs/06-reference/processor-cards/phase4-player-daily-cache.md`
- Real-time flow: `docs/06-reference/processor-cards/workflow-realtime-prediction-flow.md`
- Daily timeline: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`

---

## Section 4: Performance Issues

### 4.1 - Phase 3 Processing Too Slow

**Symptom:** Phase 3 processors taking >30 minutes (expected: 10-15 min total).

#### Diagnosis: Which processor is slow?
```sql
-- Check processing duration per processor
WITH processing_times AS (
  SELECT
    'player_game_summary' as processor,
    MIN(processed_at) as start_time,
    MAX(processed_at) as end_time,
    TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) as duration_minutes
  FROM `nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1

  UNION ALL

  SELECT
    'team_offense',
    MIN(processed_at), MAX(processed_at),
    TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE)
  FROM `nba_analytics.team_offense_game_summary`
  WHERE game_date = CURRENT_DATE() - 1

  -- Add other processors...
)
SELECT * FROM processing_times
ORDER BY duration_minutes DESC;
```

**Expected Durations:**
- Player Game Summary: 2-5 min
- Team Offense: 1-2 min
- Team Defense: 2-3 min
- Upcoming Player: 3-5 min
- Upcoming Team: 1-2 min

**If any processor > 2x expected:**
→ Performance issue with that specific processor

#### Common Causes:
1. **Large game day:** 15 games vs typical 10 → More data to process (expected)
2. **BigQuery slot contention:** Other queries running simultaneously
3. **Multi-source fallback:** Primary source unavailable, using slower fallback
4. **Inefficient query:** Check query execution plan

**Fix Procedures:**
1. **Large game day:** Normal, accept longer processing
2. **Slot contention:** Schedule processors during off-peak hours
3. **Fallback usage:** Fix primary data source availability
4. **Query optimization:** Review query plan, add indexes if possible

**References:**
- Performance benchmarks: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md` (Performance Benchmarks section)
- Specific processor cards for optimization notes

---

### 4.2 - Phase 4 Processing Too Slow

**Symptom:** Phase 4 taking >45 minutes (expected: 20-30 min).

#### Check Each Phase 4 Processor:
```sql
-- Similar to 4.1, but for Phase 4 tables
SELECT
  'team_defense_zone' as processor,
  MIN(processed_at) as start_time,
  MAX(processed_at) as end_time,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) as duration_minutes
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_shot_zone',
  MIN(processed_at), MAX(processed_at),
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE)
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()

UNION ALL

SELECT 'player_composite',
  MIN(processed_at), MAX(processed_at),
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE)
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();
```

**Expected Durations:**
- Team Defense Zone: ~2 min
- Player Shot Zone: 5-8 min
- Player Composite: 10-15 min
- Player Daily Cache: 5-10 min
- ML Feature Store: ~2 min

**Common Issues:**
1. **Player Composite taking >20 min:** Too many Phase 3 fallbacks (slower than Phase 4 cache)
2. **Player Shot Zone >15 min:** Large rolling window (20 games × 450 players)

**Fix Procedures:**
1. **Ensure Phase 4 P1/P2 complete:** So P3 can use fast Phase 4 cache
2. **Optimize window sizes:** Consider reducing from 20-game to 15-game window
3. **Parallelize:** P1 and P2 can run simultaneously, P4 and P5 can run simultaneously

**References:**
- Phase 4 timing: `docs/06-reference/processor-cards/workflow-daily-processing-timeline.md`
- Player Composite: `docs/06-reference/processor-cards/phase4-player-composite-factors.md`
- Player Shot Zone: `docs/06-reference/processor-cards/phase4-player-shot-zone-analysis.md`

---

### 4.3 - Real-Time Predictions Too Slow

**Symptom:** Predictions taking >5 seconds per odds update (expected: <1 second for 450 players).

#### Diagnosis: Is Phase 5 using the cache?
```bash
# Check Phase 5 logs for cache hit rate
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-predictions \
  AND textPayload=~'cache'" \
  --limit=50
```

**Look for:**
- "Cache miss" warnings (should be rare)
- "BigQuery query" logs (should only be for odds, not player data)

#### Check prediction latency
```bash
# Check recent prediction latency metrics
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-predictions \
  AND textPayload=~'prediction_latency'" \
  --limit=20
```

**Expected:**
- Per-player: <250ms
- Batch (450 players): 10-15 seconds

**If >1 second per player:**
→ Not using cache, querying BigQuery repeatedly

**Fix Procedures:**
1. **Cache not loaded:** Restart Phase 5 service to load cache
2. **Cache miss:** Players not in cache (verify Phase 4 completed)
3. **Model latency:** XGBoost or similarity model taking too long
4. **No parallelization:** Predictions running sequentially instead of parallel

**References:**
- Real-time flow: `docs/06-reference/processor-cards/workflow-realtime-prediction-flow.md`
- Cache pattern: `docs/06-reference/processor-cards/phase4-player-daily-cache.md`
- Performance metrics: `docs/06-reference/processor-cards/workflow-realtime-prediction-flow.md` (Performance Metrics section)

---

## Section 5: Early Season Issues

### 5.1 - High Early Season Flag Rate

**Symptom:** Many players have `early_season_flag = TRUE`, low quality scores.

**This is EXPECTED during:**
- First 2-3 weeks of regular season
- First week after All-Star break
- First week of playoffs

#### Check Current Season Week:
```sql
-- How many games have been played?
SELECT
  MIN(game_date) as season_start,
  MAX(game_date) as latest_game,
  DATE_DIFF(CURRENT_DATE(), MIN(game_date), DAY) as days_into_season,
  COUNT(DISTINCT game_date) as game_days
FROM `nba_analytics.player_game_summary`
WHERE season_year = 2024;  -- Adjust for current season
```

**Expected Early Season Rates:**

| Days Into Season | Expected Early Season % | Quality Score Range |
|------------------|------------------------|---------------------|
| 0-14 days | 60-80% | 60-75 |
| 15-28 days | 30-50% | 70-85 |
| 29+ days | 10-20% | 85-95 |

#### Check Per-Player Game History:
```sql
-- How many games has each player played?
SELECT
  COUNT(CASE WHEN games_played < 5 THEN 1 END) as players_under_5_games,
  COUNT(CASE WHEN games_played >= 5 AND games_played < 10 THEN 1 END) as players_5_to_9_games,
  COUNT(CASE WHEN games_played >= 10 THEN 1 END) as players_10plus_games,
  COUNT(*) as total_players
FROM (
  SELECT
    player_lookup,
    COUNT(*) as games_played
  FROM `nba_analytics.player_game_summary`
  WHERE season_year = 2024  -- Current season
  GROUP BY player_lookup
);
```

**Expected Early Season:**
- Week 1: Most players <5 games
- Week 3: Most players 5-10 games
- Week 5+: Most players 10+ games

**This is NOT a problem** - quality will naturally improve as:
- Phase 3 accumulates more game history
- Phase 4 rolling windows fill up (10/15/20 games)
- ML models have more training data

**What TO FIX:**
- If it's week 8+ and still >30% early season → Data pipeline issue
- Check if historical backfill completed properly

**What NOT to Fix:**
- Normal early season low quality (expected, will resolve naturally)

**References:**
- Early season handling: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md` (lines 126-132)
- Quality tiers: `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md` (lines 126-132)

---

### 5.2 - Insufficient Historical Data

**Symptom:** Processor failing with "insufficient data" errors mid-season.

**This should NOT happen mid-season** - indicates backfill issue.

#### Check Historical Depth:
```sql
-- How far back does our data go?
SELECT
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game,
  DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as total_days,
  COUNT(DISTINCT game_date) as total_game_days
FROM `nba_analytics.player_game_summary`;
```

**Expected:**
- Current season: earliest_game within 1 week of season start
- Full historical: earliest_game = multiple seasons back

**If earliest_game is recent (e.g., 2 weeks ago) but we're 3 months into season:**
→ Historical backfill never completed

#### Check Per-Phase Historical Depth:
```sql
-- Phase 2 Raw
SELECT 'Phase 2' as phase, MIN(game_date), MAX(game_date)
FROM `nba_raw.bdl_player_boxscores`

UNION ALL

-- Phase 3 Analytics
SELECT 'Phase 3', MIN(game_date), MAX(game_date)
FROM `nba_analytics.player_game_summary`

UNION ALL

-- Phase 4 Precompute
SELECT 'Phase 4', MIN(analysis_date), MAX(analysis_date)
FROM `nba_precompute.player_shot_zone_analysis`;
```

**All phases should have similar date ranges.**

**If Phase 3 < Phase 2:**
→ Phase 3 backfill incomplete

**If Phase 4 < Phase 3:**
→ Phase 4 backfill incomplete

**Fix Procedures:**
1. Run historical backfill for affected phase
2. Verify backfill completed (check date ranges again)
3. Re-run dependent downstream processors

**References:**
- Backfill guide: TBD (to be created)
- Phase-specific operations guides in `docs/processors/`

---

## Section 6: Infrastructure Issues

### 6.1 - BigQuery Permission Errors

**Symptom:** Processor failing with "Access Denied" or permission errors.

**Common Causes:**
1. Service account missing BigQuery Data Editor role
2. Cross-dataset writes blocked (e.g., writing to `nba_predictions` from `nba_precompute`)
3. Table doesn't exist (looks like permission error)

#### Diagnosis:
```bash
# Check service account permissions
gcloud projects get-iam-policy [PROJECT_ID] \
  --flatten="bindings[].members" \
  --filter="bindings.members:[SERVICE_ACCOUNT_EMAIL]"
```

**Required Roles:**
- `roles/bigquery.dataEditor` (read/write tables)
- `roles/bigquery.jobUser` (run queries)

#### Check if table exists:
```bash
# Example: Check if ML feature store table exists
bq show nba_predictions.ml_feature_store_v2
```

**If "Not found":**
→ Create table using schema definition

**Fix Procedures:**
1. **Missing permissions:** Grant required roles to service account
2. **Table missing:** Create table from schema definitions in `schemas/bigquery/`
3. **Cross-dataset:** Verify service account has permissions on BOTH datasets

**References:**
- Schema definitions: `schemas/bigquery/` directory
- BigQuery schemas doc: `docs/orchestration/03-bigquery-schemas.md`

---

### 6.2 - Cloud Run Timeout Errors

**Symptom:** Processor failing after 60 minutes (default timeout).

**Common in:**
- Large backfills
- Phase 4 processors with large rolling windows
- First run of a processor (no data exists yet)

#### Check timeout setting:
```bash
# Check current timeout
gcloud run services describe [SERVICE_NAME] \
  --region=us-west2 \
  --format="value(spec.template.spec.timeoutSeconds)"
```

**Default:** 3600 seconds (60 minutes)

#### Check actual runtime:
```bash
# Check recent logs for duration
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=[SERVICE_NAME] \
  AND textPayload=~'Processing complete'" \
  --limit=5 \
  --format='value(timestamp, textPayload)'
```

**Fix Procedures:**
1. **Increase timeout:** Max 60 minutes for Cloud Run (hard limit)
2. **Reduce batch size:** Process fewer records per run
3. **Add checkpointing:** Resume from last checkpoint on retry
4. **Switch to Cloud Run Jobs:** No timeout limit (for backfills)

**For backfills specifically:**
- Use Cloud Run Jobs instead of Cloud Run Services
- Or run backfill locally with `bq query` commands

**References:**
- Cloud Run limits: https://cloud.google.com/run/docs/configuring/request-timeout

---

### 6.3 - Out of Memory Errors

**Symptom:** Cloud Run instance crashing with OOM (out of memory).

**Common in:**
- Loading large datasets into memory
- Phase 5 cache loading (450 players × 50 fields)
- Processing large rolling windows

#### Check memory allocation:
```bash
# Check current memory limit
gcloud run services describe [SERVICE_NAME] \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].resources.limits.memory)"
```

**Default:** Usually 512 MB or 1 GB

#### Estimate required memory:
- Phase 5 cache: ~10 MB (450 players × ~20 KB each)
- Phase 4 processing: Depends on window size
- Generally: 2 GB should be sufficient for all processors

**Fix Procedures:**
1. **Increase memory:** Up to 32 GB available on Cloud Run
2. **Optimize data loading:** Use streaming instead of loading all into memory
3. **Reduce batch size:** Process smaller chunks
4. **Use BigQuery storage API:** For very large data reads

**Update memory:**
```bash
gcloud run services update [SERVICE_NAME] \
  --region=us-west2 \
  --memory=2Gi
```

**References:**
- Cloud Run memory limits: https://cloud.google.com/run/docs/configuring/memory-limits

---

### 7.4 - Monitoring Metrics Not Recording

**Symptom:** Custom metrics (hit rate, latency, etc.) not appearing in Cloud Monitoring.

**Common Log Error:**
```
Failed to record metric: 403 Permission 'monitoring.timeSeries.create' denied on resource
'projects/nba-props-platform' (or it may not exist).
```

**Root Cause:** Service account missing `roles/monitoring.metricWriter` IAM role.

**Impact:**
- Cannot track prediction hit rates
- Missing latency metrics
- No custom dashboards
- Lost observability data

#### Diagnosis

**Step 1: Check for permission errors in logs**

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND textPayload=~"403.*monitoring"
  AND severity>=ERROR' \
  --limit=20 --freshness=7d
```

**Look for:**
- "Permission 'monitoring.timeSeries.create' denied"
- "Permission 'monitoring.metricDescriptors.create' denied"

**Step 2: Check if metrics exist**

```bash
# List custom metrics (should show prediction metrics)
gcloud monitoring metrics-descriptors list \
  --filter="custom.googleapis.com/prediction" \
  --format="table(type,description)"

# If empty or missing expected metrics = problem
```

**Step 3: Check service account permissions**

```bash
# Get service account for service
SERVICE_ACCOUNT=$(gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(spec.template.spec.serviceAccountName)")

# Check IAM roles
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:$SERVICE_ACCOUNT" \
  --format="table(bindings.role)"
```

**Expected roles:**
- `roles/monitoring.metricWriter` ← MUST HAVE
- `roles/bigquery.dataEditor`
- `roles/bigquery.jobUser`
- `roles/run.invoker`

**If `monitoring.metricWriter` missing:** → Root cause confirmed

#### Fix Procedure

**Grant monitoring.metricWriter role:**

```bash
# For prediction-worker
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"

# For other services (replace SERVICE_ACCOUNT_EMAIL)
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/monitoring.metricWriter"
```

**Output should confirm:**
```
Updated IAM policy for project [nba-props-platform].
bindings:
- members:
  - serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com
  role: roles/monitoring.metricWriter
```

#### Verification

**Step 1: Wait for next service execution**

Metrics only get created when service runs and tries to write them.

**Step 2: Check logs for success**

```bash
# Should see metric writes, no more 403 errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND textPayload=~"metric"' \
  --limit=20 --freshness=1h
```

**Step 3: Verify metrics appearing**

```bash
# Should now show custom metrics
gcloud monitoring metrics-descriptors list \
  --filter="custom.googleapis.com/prediction"

# Should show recent data points
gcloud monitoring time-series list \
  --filter='metric.type="custom.googleapis.com/prediction/hit_rate"' \
  --interval-start-time="2026-02-01T00:00:00Z" \
  --format=json | \
  jq -r '.[] | .points[] | [.interval.endTime, .value.doubleValue] | @tsv'
```

**Expected:** Metrics created, data points visible

#### Prevention

**When creating new Cloud Run services:**

1. **Always grant monitoring.metricWriter:**
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:NEW_SERVICE@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```

2. **Use service account template with required roles:**
```bash
# Create service account with all required roles
gcloud iam service-accounts create NEW_SERVICE \
  --display-name="NEW_SERVICE"

# Grant standard roles
for role in monitoring.metricWriter bigquery.dataEditor bigquery.jobUser; do
  gcloud projects add-iam-policy-binding nba-props-platform \
    --member="serviceAccount:NEW_SERVICE@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/$role"
done
```

3. **Add to deployment checklist:**
- [ ] Service account created
- [ ] monitoring.metricWriter granted
- [ ] bigquery.dataEditor granted
- [ ] bigquery.jobUser granted
- [ ] Verify metrics recording after first run

#### Common Mistakes

**1. Granting role to wrong account:**
```bash
# WRONG - granting to user, not service account
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="user:email@example.com" \
  --role="roles/monitoring.metricWriter"

# CORRECT - service account
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:SERVICE@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```

**2. Using default compute service account:**

Default compute SA has broad permissions but may not include monitoring.metricWriter.
Always use service-specific service accounts.

**3. Forgetting to redeploy:**

IAM changes take effect immediately, but code must retry metric writes.
If service already ran and failed, wait for next scheduled run or manually trigger.

#### Related Issues

**Permission denied for other operations:**
- `monitoring.metricDescriptors.create` - Same fix (monitoring.metricWriter)
- `logging.logEntries.create` - Need `logging.logWriter` role
- `cloudtrace.traces.patch` - Need `cloudtrace.agent` role

**Metrics writing but not appearing in dashboards:**
- Check metric filter in dashboard config
- Verify time range selected
- Check project ID matches

#### Monitoring Permissions Reference

| Operation | Required Role | Purpose |
|-----------|---------------|---------|
| Create custom metrics | `monitoring.metricWriter` | Define new metric types |
| Write metric data points | `monitoring.metricWriter` | Record metric values |
| Read metrics | `monitoring.viewer` | View in Cloud Console |
| Create dashboards | `monitoring.editor` | Build custom dashboards |
| Create alerts | `monitoring.alertPolicyEditor` | Set up alerting |

**References:**
- CLAUDE.md "Monitoring Permissions Error" section
- Session 61 handoff Part 3
- Infrastructure health checks: `docs/02-operations/infrastructure-health-checks.md`
- GCP IAM roles: https://cloud.google.com/iam/docs/understanding-roles

---

## Section 8: Quick Reference - All Health Checks

**Copy-paste these queries for complete system health check:**

**For comprehensive infrastructure audit, see:** `docs/02-operations/infrastructure-health-checks.md`

### Phase 1 - Orchestration
```sql
-- Check recent workflow executions
SELECT workflow_name, status, scrapers_succeeded, scrapers_failed, execution_time
FROM `nba_orchestration.workflow_executions`
WHERE DATE(execution_time, 'America/New_York') = CURRENT_DATE()
ORDER BY execution_time DESC;
```

### Phase 2 - Raw Data
```sql
-- Check raw data completeness (yesterday's games)
SELECT
  COUNT(DISTINCT game_id) as games_with_boxscores
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE() - 1;

SELECT COUNT(*) as games_scheduled
FROM `nba_raw.nbac_schedule`
WHERE game_date = CURRENT_DATE() - 1;
```

### Phase 3 - Analytics
```sql
-- Full Phase 3 health check (see Section 2.2 for complete query)
-- Expected: All ✅ OK
```

### Phase 4 - Precompute
```sql
-- Full Phase 4 health check (see Section 2.3 for complete query)
-- Expected: All ✅ OK
```

### Phase 5 - Predictions
```sql
-- Check if predictions exist for today
SELECT
  COUNT(*) as prediction_count,
  AVG(ensemble_confidence) as avg_confidence,
  COUNT(CASE WHEN recommendation != 'PASS' THEN 1 END) as actionable_picks,
  AVG(feature_quality_score) as avg_feature_quality,
  COUNT(CASE WHEN systems_count = 4 THEN 1 END) as all_systems_count,
  AVG(systems_count) as avg_systems
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE();

-- Expected:
-- prediction_count: 100-450 (depends on games today)
-- avg_confidence: 70-80
-- actionable_picks: 30-150 (30-50% should be actionable)
-- avg_feature_quality: 85-95 (after week 3)
-- all_systems_count: >90% should have all 4 systems
-- avg_systems: 3.8-4.0
```

---

## Section 7: Observability Issues (Dashboard & Monitoring)

### 7.1 - Dashboard Shows Low Health Score

**Symptom:** Unified dashboard shows services health score <50/100 when most services are running.

**Example:** Dashboard showed 39/100 health score in Session 61, but all services were actually healthy.

#### Root Cause: Firestore Document Proliferation

**Problem:** Heartbeat system creating multiple documents per processor instead of one.

**How it happens:**
- Old heartbeat implementation used `f"{processor_name}_{data_date}_{run_id}"` as document ID
- Each processor run created a NEW Firestore document instead of updating existing one
- Dashboard query (`ORDER BY last_heartbeat DESC LIMIT 100`) returned mix of current + stale docs
- Health score calculation saw multiple stale entries per processor → artificially low score

**Diagnosis:**

```bash
# Check Firestore document count (should be ~30, one per processor)
# If >100, indicates proliferation issue
gcloud firestore documents list processor_heartbeats --limit=200 2>/dev/null | wc -l

# Check for duplicate processor entries in dashboard
curl https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health
```

**Expected:**
- Firestore collection: ~30 documents (one per unique processor)
- Health score: 70-100/100 (based on actual service health)

**If document count >100:**
- Indicates old heartbeat format still in use
- Multiple documents exist per processor
- Dashboard showing stale/duplicate entries

#### Fix Procedures

**Step 1: Verify heartbeat fix is deployed**

Check which services have the heartbeat fix deployed:

```bash
# Check Phase 3 deployment
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | \
  grep BUILD_COMMIT

# Should be commit e1c10e88 or later (Feb 1, 2026+)
```

Repeat for:
- `nba-phase2-raw-processors`
- `nba-phase3-analytics-processors`
- `nba-phase4-precompute-processors`

**Step 2: Deploy heartbeat fix to any missing services**

```bash
# Deploy services that don't have the fix
./bin/deploy-service.sh nba-phase2-processors
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
```

**Step 3: Run Firestore cleanup script**

After all services deployed with fix:

```bash
# Preview what will be deleted
python bin/cleanup-heartbeat-docs.py --dry-run

# Shows breakdown like:
#   106,234 total documents
#   30 unique processors
#   106,204 documents to delete

# Execute cleanup (requires typing 'DELETE' to confirm)
python bin/cleanup-heartbeat-docs.py
```

**Step 4: Verify health score improved**

Wait 5-10 minutes for processors to emit new heartbeats, then:

```bash
# Check dashboard health score
curl https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health

# Expected: 70-100/100 (was 39/100 before fix)
```

#### Prevention

**Monitor Firestore collection size:**

```bash
# Should stay ~30 documents (one per processor)
# If growing, indicates a service deployed without heartbeat fix
gcloud firestore documents list processor_heartbeats --limit=50 | wc -l
```

**Alert if collection exceeds 50 documents** - indicates issue.

**References:**
- Heartbeat implementation: `shared/monitoring/processor_heartbeat.py`
- Cleanup script: `bin/cleanup-heartbeat-docs.py`
- Session 61 handoff: `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md`
- CLAUDE.md Heartbeat System section

---

### 7.2 - Dashboard Shows Stale Processor Status

**Symptom:** Dashboard shows processor as "running" but last heartbeat was hours/days ago.

**Potential Causes:**

#### Cause 1: Processor crashed without updating status

```bash
# Check if processor actually running
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="nba-phase3-analytics-processors"
  AND timestamp>=2026-02-01T00:00:00Z' \
  --limit=10 \
  --format=json
```

**If no recent logs:**
- Processor not running
- Heartbeat status is stale
- Manually update Firestore document or wait for next run

**If recent logs show errors:**
- Processor crashed mid-run
- Check error logs for root cause
- Re-trigger processor after fixing issue

#### Cause 2: Firestore write failures

```bash
# Check for Firestore permission errors
gcloud logging read 'resource.type="cloud_run_revision"
  AND textPayload=~"Firestore"
  AND severity>=ERROR' \
  --limit=20
```

**Common errors:**
- "Permission denied" - Service account needs Firestore write access
- "Deadline exceeded" - Network issues or Firestore unavailable

**Fix:** Check service account permissions for `datastore.entities.create/update`

#### Cause 3: Multiple documents per processor (proliferation)

See Section 7.1 above - run cleanup script.

---

### 7.3 - Firestore Collection Growing Unbounded

**Symptom:** Firestore `processor_heartbeats` collection has thousands of documents.

**Root Cause:** Old heartbeat format creating document per run instead of updating single document.

**Diagnosis:**

```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())

print(f"Total documents: {len(docs)}")

# Group by processor name
from collections import Counter
processor_counts = Counter()
for doc in docs:
    # Extract processor name (before first underscore + date pattern)
    parts = doc.id.split('_')
    processor_name = parts[0] if len(parts) > 0 else doc.id
    processor_counts[processor_name] += 1

print("\nDocuments per processor:")
for processor, count in processor_counts.most_common(10):
    print(f"  {processor}: {count} documents")
```

**Expected:** Each processor should have 1 document (maybe 2-3 during transition)

**If 100+ docs per processor:** Old heartbeat format still in use

**Fix:** Follow Section 7.1 steps (deploy heartbeat fix, run cleanup script)

**Cost Impact:**
- 106,000 documents = ~$0.30/day in Firestore costs
- 30 documents = ~$0.001/day
- **Savings: $110/year** from fixing proliferation

---

## Section 8: Escalation Path

### When to Escalate

**Escalate to engineering lead if:**
1. Multiple phases failing simultaneously
2. Infrastructure-level failures (BigQuery down, Cloud Run unavailable)
3. Data corruption detected (stats don't validate)
4. Recovery procedures not resolving issue within 2 hours
5. Production predictions unavailable for >4 hours

### Incident Response Checklist

1. ✅ Run all health check queries (Section 7)
2. ✅ Identify failed phase (use decision tree in Quick Diagnosis)
3. ✅ Check detailed processor card for specific issue
4. ✅ Attempt fix procedures from this doc
5. ✅ Document issue and resolution in incident log
6. ✅ If unresolved after 2 hours → Escalate

### Emergency Contacts

- **On-call Engineer:** [TBD]
- **Engineering Lead:** [TBD]
- **Slack Channel:** #nba-pipeline-alerts

---

## Appendix: Common Error Messages

| Error Message | Section | Likely Cause |
|--------------|---------|--------------|
| **Infrastructure** |||
| "Access Denied" | 6.1 | BigQuery permissions |
| "Table not found" | 6.1 | Schema not created |
| "Timeout exceeded" | 6.2 | Cloud Run timeout (60 min limit) |
| "Out of memory" | 6.3 | Need more memory allocation |
| **Observability/Monitoring** |||
| "Dashboard health score <50/100" | 7.1 | Firestore document proliferation |
| "Firestore permission denied" | 7.2 | Service account needs datastore.entities write access |
| "Processor status stale" | 7.2 | Processor crashed or Firestore writes failing |
| "Collection growing unbounded" | 7.3 | Old heartbeat format creating doc per run |
| "403 Permission monitoring.timeSeries.create denied" | 7.4 | Service account needs monitoring.metricWriter role |
| "Custom metrics not recording" | 7.4 | Missing monitoring permissions |
| **Phase 1-4 Data** |||
| "Insufficient data for player" | 5.1, 5.2 | Early season or missing historical data |
| "No games scheduled" | 3.1 | Normal off-day |
| "Player not in cache" | 1.3, 4.3 | Phase 4 didn't process this player |
| "Cache date mismatch" | 1.3, 3.3 | Phase 5 loaded stale cache |
| "Missing dependency" | 2.2, 2.3 | Upstream phase incomplete |
| **Phase 5 Predictions** |||
| "XGBoost model not found" | 1.5 | Real model not trained/deployed (using mock) |
| "No features found for game_date" | 1.1, 1.2 | Phase 4 ML Feature Store didn't run |
| "Insufficient feature quality" | 1.4 | Phase 4 incomplete, using Phase 3 fallback |
| "Feature quality score < 70" | 1.4 | Low data quality, early season, or Phase 4 issues |
| "Worker spawn failed" | 1.1 | Coordinator couldn't create worker instances |
| "All predictions are PASS" | 1.4 | Normal (confidence/edge filtering), or early season |
| "systems_count < 4" | 1.5 | One or more prediction systems failed (likely XGBoost) |

---

**Document Version**: 1.3
**Created**: 2025-11-15
**Last Updated**: 2026-02-01
**Maintained By**: Engineering Team
**Review Frequency**: Monthly or after major incidents

**Version History:**
- v1.3 (2026-02-01): Added Section 7.4: Monitoring metrics permissions troubleshooting
- v1.2 (2026-02-01): Added Section 7: Observability Issues (dashboard health, Firestore proliferation, monitoring)
- v1.1 (2025-11-15): Added Phase 5 prediction details (sections 1.1-1.5), XGBoost troubleshooting, updated error messages
- v1.0 (2025-11-15): Initial version with Phase 1-4 troubleshooting
