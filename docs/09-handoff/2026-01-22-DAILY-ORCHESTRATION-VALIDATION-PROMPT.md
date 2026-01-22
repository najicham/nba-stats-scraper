# Daily Orchestration Validation - January 22, 2026
**Chat Purpose:** Validate tonight's (Jan 21) pipeline orchestration run
**When to Run:** Tomorrow morning (Jan 22, 12:00 PM ET)
**Expected Duration:** 15-30 minutes

---

## Your Mission

Validate that last night's (Jan 21, 2026) NBA daily pipeline orchestration ran successfully. Tonight has 7 games scheduled. We expect 850-900 predictions covering 6-7 games based on Jan 20 baseline performance.

---

## Context: Recent System State

**Recent Performance (Jan 20 baseline):**
- ✅ 885 predictions generated (target: 500-2000)
- ✅ 6/7 games covered (85.7% coverage)
- ✅ All 5 phases completed successfully
- ✅ Pipeline duration: 31 minutes (excellent)
- ✅ No critical errors
- ⚠️ 1 missing gamebook from Jan 19 (88.9% completeness)

**Recent Fixes Deployed (Jan 21-22):**
1. ✅ Prediction coordinator Dockerfile fixed (ModuleNotFoundError)
2. ✅ Analytics BDL threshold relaxed (36h → 72h, critical → non-critical)
3. ✅ Raw processor pdfplumber added (injury discovery)
4. ✅ Phase 4 Pub/Sub ack deadline fixed (10s → 600s)
5. ✅ Scheduler permissions granted (6 services)
6. ✅ Phase 2-3 execution logging deployed

**Services Deployed:**
- prediction-coordinator-00078 (Jan 22, 03:34 UTC)
- nba-phase3-analytics-processors-00097 (Jan 22, 03:32 UTC)
- nba-phase2-raw-processors-00105 (Jan 22, 03:50 UTC)

---

## Step-by-Step Validation Instructions

### Step 1: Quick Health Check (2-3 minutes)

**Run this command:**
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 bin/validate_pipeline.py 2026-01-21 --legacy-view
```

**Expected Output:**
- Game date: 2026-01-21
- Games covered: 6-7 (min: 5)
- Total predictions: 850-900 (min: 500)
- Unique players: 25-30 (min: 15)
- Systems active: 7/7 (min: 5)
- Average confidence: 0.50-0.80 (min: 0.40)

**If this passes, you're 90% done. Continue to Step 2 for detailed verification.**

---

### Step 2: Verify Prediction Generation (5 minutes)

**Check total predictions:**
```sql
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems_active,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(DISTINCT game_id) as games_covered,
  ROUND(AVG(confidence), 3) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21'
  AND DATE(created_at) = '2026-01-21'
  AND is_active = TRUE
GROUP BY game_date;
```

**Expected Results:**
- total_predictions: 850-900 (⚠️ flag if <500 or >2000)
- systems_active: 7 (⚠️ flag if <5)
- unique_players: 25-30 (⚠️ flag if <15)
- games_covered: 6-7 (⚠️ flag if <5)
- avg_confidence: 0.50-0.80 (⚠️ flag if <0.40)

**Check per-game coverage:**
```sql
SELECT
  game_id,
  COUNT(DISTINCT system_id) as systems,
  COUNT(DISTINCT player_id) as players,
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence), 3) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21'
  AND DATE(created_at) = '2026-01-21'
  AND is_active = TRUE
GROUP BY game_id
ORDER BY game_id;
```

**Expected Results:**
- 6-7 rows (one per game)
- Each game: 100-300 predictions
- Each game: 5-7 systems active
- Each game: 10-20 unique players

**⚠️ If any game has 0 predictions:** This is the issue from Jan 20 (TOR @ GSW). Investigate why (likely late game time or insufficient data quality).

---

### Step 3: Check for R-009 Regression (2 minutes)

**This is CRITICAL - R-009 bug causes zero-active-player games.**

**Run validator:**
```bash
cd /home/naji/code/nba-stats-scraper
python validation/validators/nba/r009_validation.py --date 2026-01-21
```

**OR run SQL directly:**
```sql
-- Check for games with zero active players (R-009 regression)
SELECT
  game_date,
  game_id,
  COUNTIF(is_active = TRUE) as active_players,
  COUNT(*) as total_rows
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-21'
GROUP BY game_date, game_id
HAVING active_players = 0;
```

**Expected Result:** 0 rows (no R-009 regression)

**🔴 If any rows returned:** CRITICAL - R-009 regression detected. This is a P0 issue that blocks predictions.

---

### Step 4: Verify Phase 4 Quality Boost (3 minutes)

**Quick Win #1 was deployed on Jan 20: Phase 3 fallback weight boost from 75% → 87%**

**Check quality score distribution:**
```sql
SELECT
  CASE
    WHEN feature_quality_score >= 0.87 THEN '87%+ (Phase 3 boost)'
    WHEN feature_quality_score >= 0.75 THEN '75-87% (Previous)'
    WHEN feature_quality_score >= 0.50 THEN '50-75% (Acceptable)'
    ELSE '<50% (Low)'
  END as quality_tier,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_precompute.ml_feature_store_v2
WHERE game_date = '2026-01-21'
  AND DATE(created_at) = '2026-01-21'
GROUP BY quality_tier
ORDER BY quality_tier DESC;
```

**Expected Result:**
- Increase in 87%+ tier vs baseline (compare to Jan 20 if available)
- Quick Win #1 should show measurable impact

---

### Step 5: Verify Upstream Data Completeness (5 minutes)

**Check Phase 3 analytics (upcoming_player_game_context):**
```sql
SELECT
  game_date,
  COUNT(*) as context_records,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(DISTINCT game_id) as games
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-21'
GROUP BY game_date;
```

**Expected:** 130-150 records (all players in 7 games)

**Check BettingPros props availability:**
```sql
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players_with_props,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_prop_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = '2026-01-21'
GROUP BY game_date;
```

**Expected:** 50-70 players, 10+ bookmakers, 500+ lines

**Check yesterday's gamebook completeness (Jan 20 - for Phase 4 data):**
```sql
-- Yesterday's gamebooks
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_with_gamebooks,
  COUNT(*) as player_records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2026-01-20'
GROUP BY game_date;

-- Compare with scheduled games
SELECT COUNT(*) as scheduled_games
FROM nba_raw.nbac_schedule
WHERE game_date = '2026-01-20' AND game_status = 3;
```

**Expected:** Counts should match (100% gamebook completeness)
**⚠️ If mismatch:** Missing gamebooks reduce Phase 4 quality scores

---

### Step 6: Check Service Health (2 minutes)

**Check all services are healthy:**
```bash
for svc in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator prediction-worker; do
  echo -n "$svc: "
  curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "ERROR"
done
```

**Expected:** All return "healthy"

**Check for recent errors in logs:**
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --freshness=12h --format="table(timestamp,resource.labels.service_name,textPayload)" \
  --project=nba-props-platform
```

**Expected:** No critical errors in last 12 hours

---

### Step 7: Verify New Infrastructure (3 minutes)

**Check Phase 2-3 execution logging (NEW - deployed Jan 22):**
```sql
SELECT
  execution_timestamp,
  phase_name,
  game_date,
  duration_seconds,
  games_processed,
  status
FROM nba_orchestration.phase_execution_log
WHERE game_date = '2026-01-21'
ORDER BY execution_timestamp DESC
LIMIT 10;
```

**Expected:** Records showing Phase 2→3 transition with duration in seconds

**Check workflow orchestration:**
```sql
-- Check workflow decisions
SELECT decision_time, workflow_name, action, reason
FROM nba_orchestration.workflow_decisions
WHERE DATE(decision_time) = '2026-01-21'
ORDER BY decision_time DESC
LIMIT 10;

-- Check workflow executions
SELECT execution_time, workflow_name, status, scrapers_succeeded, scrapers_failed
FROM nba_orchestration.workflow_executions
WHERE DATE(execution_time) = '2026-01-21'
ORDER BY execution_time DESC
LIMIT 10;
```

**Expected:** Workflow decisions = "RUN" and executions = "SUCCESS"

---

## Success Criteria

**Pipeline is HEALTHY if:**
- ✅ 500+ predictions generated (excellent: 850-900)
- ✅ 5+ games covered (excellent: 6-7)
- ✅ 5+ systems active (excellent: 7)
- ✅ 0 R-009 regressions
- ✅ All services returning HTTP 200
- ✅ No critical errors in logs

**Pipeline is DEGRADED if:**
- ⚠️ 200-500 predictions (acceptable but investigate)
- ⚠️ 3-4 games covered (below target)
- ⚠️ 3-4 systems active (some systems down)
- ⚠️ Missing gamebooks from yesterday

**Pipeline is FAILED if:**
- 🔴 <200 predictions (critical failure)
- 🔴 <3 games covered (major failure)
- 🔴 Any R-009 regressions detected
- 🔴 Services returning HTTP 503

---

## Known Issues to Watch

1. **Coordinator Firestore Import (Known blocker from Jan 21)**
   - Status: Known issue, not critical for morning pipeline
   - Impact: Evening batch coordination may be blocked
   - Workaround: Morning pipeline works independently

2. **Worker Model Path (Missing env var)**
   - Impact: Falls back to 50% confidence if CATBOOST_V8_MODEL_PATH missing
   - Check: If avg_confidence is exactly 0.50, this may be the issue

3. **Phase 1 Procfile (Scrapers deployment)**
   - Status: Known blocker for scraper deployments
   - Impact: Doesn't affect tonight's run (already deployed)

---

## Troubleshooting Guide

**If predictions < 500:**
1. Check if all 7 systems are active (query from Step 2)
2. Check if upstream data arrived (Step 5 queries)
3. Check for R-009 regression (Step 3)
4. Check service logs for errors

**If any game has 0 predictions:**
1. Check if BettingPros props exist for that game
2. Check if upcoming_player_game_context has players for that game
3. Check if quality scores are too low (<70%)
4. May be late game time or insufficient data

**If R-009 regression detected:**
1. This is CRITICAL - notify immediately
2. Check player_game_summary for affected games
3. May need analytics reprocessing
4. Could block all predictions for affected games

**If gamebooks missing from yesterday:**
1. Note the count and game IDs
2. This reduces Phase 4 quality scores
3. May need manual gamebook backfill
4. Not blocking but reduces prediction quality

---

## Reference Documentation

**Primary Reference:**
- `/docs/02-operations/daily-validation-checklist.md` (comprehensive guide)

**Recent Baseline:**
- `/docs/02-operations/validation-reports/2026-01-20-daily-validation.md` (885 predictions, 31 min)

**Validation Framework:**
- `/docs/07-monitoring/validation-system.md`
- `/validation/validators/nba/r009_validation.py`

---

## Expected Timeline

**10:30 AM ET:** Props arrive, pipeline starts (Phase 3 Analytics)
**11:00 AM ET:** Phase 4 Precompute starts
**11:30 AM ET:** Phase 5 Predictions generation
**12:00 PM ET:** Pipeline complete (expected duration: 30-35 min)

**Run validation at 12:00 PM ET or later.**

---

## Deliverable

Create a brief validation report with:
1. ✅/⚠️/🔴 Status for each step
2. Key metrics (predictions, games, systems, confidence)
3. Any issues found
4. Comparison to Jan 20 baseline
5. Recommendations (if any issues)

**Example format:**
```
DAILY VALIDATION REPORT - January 22, 2026
===========================================

OVERALL STATUS: ✅ HEALTHY

Key Metrics:
- Total Predictions: 892 (baseline: 885) ✅
- Games Covered: 7/7 (100%) ✅
- Systems Active: 7/7 ✅
- Avg Confidence: 0.65 ✅
- R-009 Regressions: 0 ✅

Pipeline Health:
- Phase 3 Analytics: ✅ Complete
- Phase 4 Precompute: ✅ Complete
- Phase 5 Predictions: ✅ Complete
- Duration: 32 minutes ✅

Issues:
- None

Comparison to Baseline:
- Predictions: +7 (+0.8%)
- Coverage: Same (100%)
- Duration: +1 min (+3%)

Recommendation: Pipeline performing excellently. No action needed.
```

---

**Good luck! The pipeline has been running well, and all recent fixes are deployed. You should see excellent results.** 🚀
