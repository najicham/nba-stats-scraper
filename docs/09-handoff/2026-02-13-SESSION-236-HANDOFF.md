# Session 236 Handoff - Phase 4 Data Quality Validation

**Date:** 2026-02-13
**Session Type:** Data Quality Validation & Root Cause Analysis
**Status:** ✅ Complete - Critical Issue Identified, Monitoring Setup
**Next Session Focus:** Fix UPCG days_rest Calculation

---

## Mission Accomplished

### Primary Objective: Validate Phase 4 ML Feature Quality ✅

**Executed all 5 recommended actions from Session 235:**
1. ✅ **Investigated Feb 12 quality failure** → ROOT CAUSE FOUND
2. ✅ **Fixed zero-tolerance bypass** → NOT A BUG (working as designed)
3. ✅ **Tracked Q43 progression** → 39/50 picks (78% toward promotion)
4. ✅ **Set up Feb 19 monitoring** → Validation script created
5. ✅ **Champion model decision** → RECOMMENDATION: Deploy V12 Model 1

---

## 🔴 CRITICAL FINDING: Phase 3 UPCG days_rest Field Broken

### Root Cause Summary

The `upcoming_player_game_context` table is **NOT computing `days_rest`** for Feb 11-12:

| Date | Total Players | Has days_rest | % Coverage |
|------|--------------|---------------|------------|
| Feb 10 | 80 | 79 | **98.8%** ✅ |
| Feb 11 | 494 | **0** | **0%** 🔴 |
| Feb 12 | 107 | **0** | **0%** 🔴 |

**Impact:**
- ALL players missing Feature 39 (days_rest) in ml_feature_store_v2
- Feb 12: 100% of Phase 4 players had defaults (avg 7.0), 0% quality_ready
- Only 32 predictions made (vs 192 on Feb 11)
- Quality gate correctly blocked 71 players (103 - 32)

**Technical Details:**
- Phase: **Phase 3 (Analytics)** - NOT Phase 4
- Processor: `upcoming_player_game_context_processor.py`
- Field: `days_rest` column calculation broken since Feb 11
- Other fields (e.g., `minutes_in_last_7_days`) are working correctly
- Feature Store reads `days_rest` from UPCG via `feature_extractor.get_days_rest_float()`

**Default Feature Pattern (Feb 12):**
- **Common to ALL 103 players:** [39, 47, 50]
  - 39: days_rest (BROKEN - should be from UPCG)
  - 47: teammate_usage_available (dead feature, always 0.0)
  - 50: multi_book_line_std (dead feature, always 0.5)
- **Tier 2 (35 players):** + [25, 26, 27, 53] (Vegas features)
- **Worst tier (10 players):** + 16 more features (player history, shot zones, team context)

### Next Steps for Fix

**P0 CRITICAL (Before Feb 19):**
1. Investigate `upcoming_player_game_context_processor.py` days_rest calculation
2. Check if the issue started Feb 11 (0%) or earlier
3. Identify root cause (code change, dependency failure, upstream data gap)
4. Fix the processor and backfill Feb 11-12
5. Verify Feb 19 morning that days_rest populates correctly

**Diagnostic Queries:**
```sql
-- Check UPCG processor completion
SELECT * FROM `nba-props-platform.nba_orchestration.phase_completions`
WHERE phase = 'phase3' AND game_date >= '2026-02-10'
  AND processor_name = 'upcoming_player_game_context'

-- Check if issue is older
SELECT game_date,
  COUNT(*) as total,
  COUNTIF(days_rest IS NOT NULL) as has_days_rest
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= '2026-02-01'
GROUP BY game_date
ORDER BY game_date DESC
```

---

## ✅ Zero-Tolerance Enforcement: Working as Designed

### Investigation Results

7 predictions on Feb 10-11 had `default_feature_count > 0` despite HARD_FLOOR_MAX_DEFAULTS = 0.

**Finding:** NOT A BUG - Vegas features are intentionally OPTIONAL (Session 145).

**Details:**
- All 7 predictions had ONLY Vegas defaults: [25, 26, 27]
  - Feature 25: vegas_points_line
  - Feature 26: vegas_opening_line
  - Feature 27: vegas_line_move
- Quality scorer uses `required_default_count` (excludes optional Vegas features)
- Coordinator quality gate uses `required_default_count` (line 359-360)
- These players marked `is_quality_ready = true`, `quality_alert_level = green`

**Why Vegas is Optional:**
- ~60% of players lack Vegas lines (bench players, no prop markets)
- Vegas absence is normal and doesn't indicate data quality issues
- Zero-tolerance applies to REQUIRED features only

**Verification:**
```sql
-- All 7 bypassed predictions had Vegas-only defaults
SELECT player_lookup, default_feature_indices
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date IN ('2026-02-10', '2026-02-11')
  AND default_feature_count = 3
  AND default_feature_indices = ['25', '26', '27']
LIMIT 7
```

**Conclusion:** System working correctly. No action needed.

---

## Q43 Model Progression: 39/50 Picks (78% Toward Promotion)

### 30-Day Performance Summary

| Model | Total Graded | Edge 3+ | Edge 5+ | HR Edge 3+ | HR Edge 5+ | MAE |
|-------|--------------|---------|---------|------------|------------|-----|
| **Champion (catboost_v9)** | 2,996 | 454 | 126 | **50.2%** 🔴 | 52.4% | 5.09 |
| **Q43 (challenger)** | 364 | **39** | 2 | **51.3%** ⚠️ | 50.0% | **4.60** ✅ |

**Key Findings:**
- **Champion decaying:** 50.2% HR (below 52.4% breakeven)
- **Q43 above breakeven:** 51.3% HR but SMALL SAMPLE (39 picks vs 454)
- **Q43 progression:** 39/50 edge 3+ picks needed for promotion (78%)
- **Q43 better MAE:** 4.60 vs 5.09 (0.49 improvement)

### Daily Edge 3+ Pick Generation (Last 5 Days)

| Date | Total Predictions | Edge 3+ Picks |
|------|-------------------|---------------|
| Feb 12 | 32 | 8 |
| Feb 11 | 192 | 18 |
| Feb 10 | 23 | 3 |
| Feb 09 | 65 | 4 |
| Feb 08 | 52 | 6 |
| **Total** | **364** | **39** |

**Trend Analysis:**
- Q43 produces ~8 edge 3+ picks per game day (small slates: 3-4, large slates: 8-18)
- At current rate: ~3-4 more game days to reach 50+ picks
- Feb 19 (10 games) could add 12-15 edge 3+ picks
- **Estimated promotion eligibility:** Feb 20-22 (within 1 week)

### Promotion Recommendation

**DO NOT promote Q43 yet. Wait for 50+ edge 3+ sample.**

**Rationale:**
- 39 picks is too small (95% CI: ~35-67% true HR)
- 1 week away from statistically valid sample
- Champion is weak (50.2%) but not critical (still near breakeven)
- Better option available (V12 Model 1)

**Decision Tree:**
1. **If Q43 reaches 50+ picks by Feb 22 with 55%+ HR:** Promote Q43
2. **If Q43 < 55% HR at 50+ picks:** Deploy V12 Model 1 instead
3. **If Q43 stalls (< 50 picks by Feb 25):** Deploy V12 Model 1 immediately

---

## 🎯 RECOMMENDATION: Deploy V12 Model 1 (Production Ready)

### V12 Model 1 Performance

**Per Session 228-230 (Phase 1B Results):**

| Metric | Value | Status |
|--------|-------|--------|
| **Avg HR Edge 3+ (4 windows)** | **67.05%** | ✅ EXCELLENT |
| **Best Window (Jan 2026)** | **78.70%** | ✅ OUTSTANDING |
| **Problem Period (Feb 2026)** | **60.00%** | ✅ FIRST TO CROSS BREAKEVEN |
| **MAE** | **4.94** | ✅ (vs 5.09 champion) |
| **All Phase 1 Gates** | PASS | ✅ |

**Feature Set:**
- Vegas-free (no features 25-28)
- 50 active features (54 total - 4 vegas excluded)
- V12 features reduce `points_avg_season` dominance (20% vs 29%)

**Governance:**
- ✅ All 6 Phase 1 decision gates PASS
- ✅ MAE <= 6.0 (actual: 4.94)
- ✅ Avg HR > 55% (actual: 67%)
- ✅ All windows > breakeven (56.6-78.7%)

### Deployment Plan

**Phase 1: Shadow Deployment (1 week)**
1. Deploy V12 Model 1 as shadow model (new system_id: `catboost_v12_model1_vegas_free`)
2. Run alongside champion and Q43 (3 models total)
3. Monitor edge 3+ HR daily for 7 days
4. Target: Maintain 60%+ HR edge 3+ in production

**Phase 2: Promotion Decision (Feb 20-22)**
1. If V12 Model 1 shadow performance validates (60%+ HR):
   - Promote V12 Model 1 to champion
   - Retire current champion
   - Keep Q43 in shadow for comparison
2. If V12 Model 1 underperforms (<55% HR):
   - Keep current champion
   - Wait for Q43 to reach 50+ picks
   - Investigate V12 discrepancy

**Phase 3: Model 2 (Edge Classifier)**
- Per Session 230: Edge Classifier (Model 2) FAILED (AUC < 0.50)
- **DO NOT implement Model 2** - pre-game features cannot discriminate winning edges
- Use Model 1 + edge threshold instead

### Comparison: Q43 vs V12 Model 1

| Dimension | Q43 Challenger | V12 Model 1 | Winner |
|-----------|----------------|-------------|--------|
| **30-day HR** | 51.3% (n=39) | 67% avg (4 windows) | V12 |
| **Sample Size** | 39 picks 🔴 | 533 picks ✅ | V12 |
| **Statistical Confidence** | Low (95% CI: 35-67%) | High | V12 |
| **MAE** | 4.60 ✅ | 4.94 ✅ | Q43 (slight) |
| **Production Ready** | NO (need 50+) | YES (all gates pass) | V12 |
| **Vegas-free** | NO (uses Vegas) | YES | V12 |
| **Training Data** | 2025-11-02 to 2026-01-31 | Same | TIE |

**Verdict:** V12 Model 1 is superior choice for immediate deployment.

**Action Plan:**
1. Deploy V12 Model 1 to shadow mode (Feb 14-15)
2. Monitor performance through Feb 19 (10-game slate)
3. Promote to champion by Feb 20 if performance validates
4. Keep Q43 in shadow for ongoing comparison

---

## Feb 19 Monitoring Setup ✅

### Validation Script Created

**File:** `bin/monitoring/validate_phase4_quality_feb19.sh`

**Functionality:**
- Checks Phase 4 quality metrics for Feb 19 (10-game slate)
- Alert thresholds:
  - `quality_ready_pct < 70%` → 🔴 ALERT
  - `avg_defaults > 5.0` → 🔴 ALERT
  - `days_rest_missing > 0` → ⚠️ WARNING (Session 236 issue)
- Outputs CSV report with quality breakdown

**Usage:**
```bash
# Feb 19 morning (pre-game check)
./bin/monitoring/validate_phase4_quality_feb19.sh

# Custom date
./bin/monitoring/validate_phase4_quality_feb19.sh 2026-02-20
```

**Monitoring Schedule:**
- **Feb 18 evening:** Run `/validate-daily` for pre-game check
- **Feb 19 morning:** Run validation script + verify predictions generated
- **Feb 19 post-game:** Monitor Q43 edge 3+ pick accumulation
- **Daily:** Track Phase 4 quality metrics for days_rest field

---

## System Status

### Deployment Drift: ✅ ACCEPTABLE

All critical services current (Session 235 verification).

### Data Quality: 🔴 CRITICAL (UPCG days_rest Broken)

| Component | Status | Notes |
|-----------|--------|-------|
| **Phase 3 UPCG** | 🔴 BROKEN | days_rest NULL for all players (Feb 11-12) |
| **Phase 4 ML Features** | ⚠️ DEGRADED | Avg 7.0 defaults on Feb 12 (should be 3.0) |
| **Phase 5 Predictions** | ✅ WORKING | Quality gate correctly blocking bad data |
| **Phase 6 Grading** | ✅ WORKING | Session 232 fix validated |

### Model Performance: 🔴 CHAMPION DECAYING

| Model | 30-Day Edge 3+ HR | Status |
|-------|-------------------|--------|
| **Champion** | 50.2% (454 picks) | 🔴 BELOW BREAKEVEN |
| **Q43** | 51.3% (39 picks) | ⚠️ SMALL SAMPLE |
| **V12 Model 1** | 67% avg (533 picks) | ✅ READY TO DEPLOY |

---

## Game Schedule

- **Feb 13-18:** Off-days (no games)
- **Feb 19:** 10 games (next validation checkpoint)
- **Feb 20:** 9 games

**Critical Deadlines:**
- **Feb 18 evening:** Fix UPCG days_rest processor
- **Feb 19 morning:** Verify days_rest populating correctly
- **Feb 19 post-game:** Validate 10-game slate quality

---

## Immediate Actions for Next Session

### Priority 0: CRITICAL (Before Feb 19)

**1. Fix UPCG days_rest Calculation**
- Investigate `data_processors/analytics/upcoming_player_game_context/` processor
- Check if calculation logic changed or dependency failed
- Verify upstream data (player_game_summary) has necessary fields
- Test fix on Feb 18 (off-day, safe to backfill)
- Backfill Feb 11-12 if fix successful

**Diagnostic Steps:**
```bash
# 1. Check UPCG processor code changes
git log --since="2026-02-10" --until="2026-02-11" -- data_processors/analytics/upcoming_player_game_context/

# 2. Check processor completion status
bq query "SELECT * FROM \`nba-orchestration.phase_completions\`
  WHERE phase = 'phase3' AND game_date >= '2026-02-10'
  AND processor_name = 'upcoming_player_game_context'"

# 3. Check if issue is older
bq query "SELECT game_date, COUNT(*) as total,
  COUNTIF(days_rest IS NOT NULL) as has_days_rest
FROM \`nba-analytics.upcoming_player_game_context\`
WHERE game_date >= '2026-02-01'
GROUP BY game_date ORDER BY game_date DESC"

# 4. Test fix locally
PYTHONPATH=. python data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py \
  --analysis-date 2026-02-18 --dry-run
```

**2. Verify Feb 19 Quality**
```bash
# Feb 19 morning
./bin/monitoring/validate_phase4_quality_feb19.sh 2026-02-19
/validate-daily
```

### Priority 1: HIGH (This Week)

**3. Deploy V12 Model 1 Shadow**
```bash
# Deploy model artifact to GCS
gsutil cp ml/models/catboost_v12_model1_vegas_free_*.cbm \
  gs://nba-props-platform-models/catboost_v12/

# Register in model registry
./bin/model-registry.sh register catboost_v12_model1_vegas_free \
  --path gs://... --sha256 <hash>

# Add to prediction config (shadow mode)
# Edit predictions/coordinator/config.yml
# Add system_id: catboost_v12_model1_vegas_free, enabled: true

# Deploy prediction-worker
./bin/deploy-service.sh prediction-worker

# Verify shadow predictions
bq query "SELECT system_id, COUNT(*) FROM \`nba_predictions.player_prop_predictions\`
  WHERE game_date = '2026-02-19' GROUP BY system_id"
```

**4. Monitor Q43 Progression**
```bash
# Daily check
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --days 7

# Track toward 50+ threshold
bq query "SELECT COUNT(*) as edge_3plus_picks
FROM \`nba_predictions.prediction_accuracy\`
WHERE system_id = 'catboost_v9_q43_train1102_0131'
  AND ABS(predicted_points - line_value) >= 3"
```

### Priority 2: MEDIUM (Next Week)

**5. V12 Model 1 Promotion Decision (Feb 20-22)**
- If shadow HR >= 60%: Promote to champion
- If shadow HR < 55%: Investigate discrepancy
- Update CLAUDE.md MODEL section with new champion

**6. Retire Decaying Champion**
- Set `enabled: false` for `catboost_v9` in config
- Keep in database for historical analysis
- Document retirement in model registry

---

## Files Modified This Session

1. **bin/monitoring/validate_phase4_quality_feb19.sh** (NEW)
   - Phase 4 quality validation script for Feb 19
   - Alert thresholds: quality_ready < 70%, avg_defaults > 5.0
   - Checks for Session 236 days_rest issue

---

## Key Learnings

1. **Phase 3→4 dependencies matter:** Feature Store (Phase 4) quality depends entirely on upstream Phase 3 data. A broken field in UPCG cascades to 100% Phase 4 quality failure.

2. **Zero-tolerance has nuance:** `HARD_FLOOR_MAX_DEFAULTS = 0` applies to REQUIRED features only. Optional Vegas features (25-27) can default without blocking predictions.

3. **Small sample sizes are risky:** Q43 at 51.3% HR with 39 picks has 95% CI of 35-67%, making promotion decision premature. Always wait for statistically valid sample (50+ picks).

4. **Quality metrics correlate inversely with performance:** Feb 12 (terrible quality) had 60-75% HR, while Feb 11 (good quality) had 38-42% HR. This paradox suggests quality metrics may be measuring wrong things.

5. **V12 Model 1 is breakthrough:** First model to cross breakeven (60%) in problem period (Feb 2026), average 67% HR across 4 windows. Reduces `points_avg_season` dominance by 30%.

6. **Dead features are intentional:** Features 47 (teammate_usage_available) and 50 (multi_book_line_std) always default by design. Their presence doesn't indicate quality issues.

7. **Edge Classifier (Model 2) doesn't work:** Pre-game features cannot discriminate winning edges from losing ones (AUC < 0.50). Stick with Model 1 + edge threshold.

---

## Questions for Next Session

1. Why did UPCG days_rest calculation break on Feb 11?
2. Is the quality-performance paradox real or sample size artifact?
3. Should we deploy V12 Model 1 immediately or wait for Q43?
4. How often should we retrain models to prevent decay?

---

## Related Documentation

- Session 235 Handoff: Grading fix validation, Phase 4 gap discovery
- Session 230 Handoff: V12 Model 1 validation (Phase 1B)
- Session 228 Handoff: V12 feature development
- Session 145: Vegas features made optional (required_default_count)
- Session 141: Zero tolerance for defaults implemented
- CLAUDE.md MODEL section: Champion model specs and governance

---

**Handoff Complete. Next session: Fix UPCG days_rest processor before Feb 19 games.**
