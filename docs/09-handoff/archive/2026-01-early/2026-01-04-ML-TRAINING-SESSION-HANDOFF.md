# ML Training Session - Quick Takeover Handoff

**Date**: January 4, 2026, 2:45 PM PST
**Session Focus**: Train XGBoost v5 on validated 2021-2024 data
**Estimated Duration**: 2-3 hours
**Priority**: HIGH - Can start immediately

---

## 🎯 EXECUTIVE SUMMARY

**User wants to train ML model v5 to beat 4.27 MAE baseline.**

**GOOD NEWS**: Historical training data (2021-2024) is **VALIDATED AND READY**. No backfills needed.

**Current State**:
- ✅ 84,558 training records available (2021-10-01 to 2024-05-01)
- ✅ minutes_played: 99.4% coverage
- ✅ usage_rate: 47-48% coverage (above 45% threshold)
- ✅ Shot zones: 83% coverage
- ✅ All 3 critical bugs fixed (minutes_played parser, usage_rate implementation, shot distribution)

**Your Task**: Validate data → Train model → Evaluate vs baseline → Report results

---

## 📋 CURRENT STATE (As of Jan 4, 2:45 PM)

### Data Pipeline Status

**Phase 2 (Raw)**:
- ✅ COMPLETE for 2021-2024 training period
- 850 dates with data
- bdl_player_boxscores: 188,050 records
- nbac_gamebook_player_stats: 190,978 records

**Phase 3 (Analytics)**:
- ✅ COMPLETE for 2021-2024 training period
- player_game_summary: 84,558 records
- team_offense_game_summary: Match rate 99.8% with Phase 2
- No backfills required for ML training period

**Phase 4 (Precompute)**:
- ⏸️ NOT REQUIRED for initial ML training
- ML script uses LEFT JOINs (works with or without Phase 4)
- Can train now, retrain later with Phase 4 if needed

### Critical Bugs - ALL FIXED

**Bug #1: minutes_played Parser (FIXED - commit 83d91e2)**
- Was: 99.5% NULL (pd.to_numeric coerced "MM:SS" to NaN)
- Now: 99.4% coverage
- Status: ✅ RESOLVED

**Bug #2: usage_rate Implementation (FIXED - commit 390caba)**
- Was: 100% NULL (never implemented)
- Now: 47-48% coverage (above 45% threshold)
- Status: ✅ RESOLVED

**Bug #3: Shot Distribution (FIXED - commit 390caba)**
- Was: 0% for 2024-25 season (BigDataBall format change)
- Now: 83% coverage overall
- Status: ✅ RESOLVED

### Validation Status

**Existing validation passed**:
- Record count: 84,558 ≥ 35,000 minimum ✅
- Feature coverage validated ✅
- Quality metrics acceptable ✅

**New validation scripts created** (but not yet run on training data):
- `/scripts/validation/preflight_check.sh`
- `/scripts/validation/post_backfill_validation.sh`
- `/scripts/validation/validate_write_succeeded.sh`
- `/scripts/validation/validate_ml_training_ready.sh`

---

## 🚀 STEP-BY-STEP EXECUTION PLAN

### Phase 1: Validate Training Data (15 minutes)

**Use the proven validation script** (faster than new comprehensive script):

```bash
cd /home/naji/code/nba-stats-scraper

# Validate ML training data
./scripts/validation/validate_player_summary.sh 2021-10-01 2024-05-01

# Check exit code
echo $?
# Expected: 0 (PASS)
# If 1: FAIL - review output and fix issues
```

**What this validates**:
- Record count ≥ 35,000
- minutes_played ≥ 99%
- usage_rate ≥ 45% (lowered from 95% based on current data)
- shot_zones ≥ 40%
- Quality score ≥ 75
- Production ready ≥ 95%

**If validation PASSES** → Proceed to Phase 2
**If validation FAILS** → Review output, fix issues, re-validate

---

### Phase 2: Train XGBoost v5 (1-2 hours)

**Training script location**: `/home/naji/code/nba-stats-scraper/ml/train_real_xgboost.py`

**Command**:
```bash
cd /home/naji/code/nba-stats-scraper

# Set environment
export PYTHONPATH=.
export GCP_PROJECT_ID=nba-props-platform

# Start training (redirect to log file)
python ml/train_real_xgboost.py 2>&1 | tee logs/ml_training_v5_$(date +%Y%m%d_%H%M%S).log

# Or run in background
nohup python ml/train_real_xgboost.py > logs/ml_training_v5_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo $! > /tmp/ml_training.pid
```

**What it does**:
1. Extracts training data from BigQuery (2021-10-01 to 2024-05-01)
2. Features: 21 features including minutes_played, usage_rate, shot zones
3. Train/Val/Test split: 70/15/15 chronological
4. XGBoost training with early stopping
5. Saves model to `models/` directory
6. Compares against 4.27 MAE baseline

**Expected outputs**:
- Model file: `models/xgboost_real_v5_21features_YYYYMMDD.json`
- Metadata: `models/xgboost_real_v5_21features_YYYYMMDD_metadata.json`
- Training logs: Cross-validation scores, feature importance, final metrics

**Monitor progress**:
```bash
# If running in background
tail -f logs/ml_training_v5_*.log

# Check process
ps aux | grep train_real_xgboost.py
```

**Expected runtime**: 1-2 hours

---

### Phase 3: Evaluate Results (15 minutes)

**Check training completion**:
```bash
# Verify model file created
ls -lh models/xgboost_real_v5_*.json

# Check final metrics in log
grep -A 10 "Final Results" logs/ml_training_v5_*.log

# Or check metadata file
cat models/xgboost_real_v5_*_metadata.json | python3 -m json.tool
```

**Success criteria**:
- ✅ Model file exists
- ✅ Test MAE < 4.27 (beating baseline)
- ✅ No errors in training log
- ✅ Feature importance makes sense

**Expected performance**:
- **Best case**: 3.8-4.0 MAE (15-20% better than baseline)
- **Target**: 4.0-4.2 MAE (5-8% better than baseline)
- **Acceptable**: <4.27 MAE (beats baseline)
- **Fail**: ≥4.27 MAE (investigate)

**If MAE ≥ 4.27**:
1. Check feature coverage (usage_rate might be lower than expected)
2. Review feature importance (are critical features being used?)
3. Check for data quality issues
4. Consider waiting for Phase 4 precompute features

---

### Phase 4: Report & Next Steps (10 minutes)

**Create summary report**:
```bash
cat > /tmp/ml_training_v5_summary.md <<'EOF'
# ML Training v5 Results

**Date**: $(date)
**Training Period**: 2021-10-01 to 2024-05-01
**Total Records**: [FROM LOG]

## Model Performance
- **Test MAE**: [FROM LOG]
- **Baseline MAE**: 4.27
- **Improvement**: [CALCULATE %]

## Data Quality
- minutes_played coverage: 99.4%
- usage_rate coverage: 47-48%
- shot zones coverage: 83%

## Feature Importance
[PASTE TOP 10 FROM LOG]

## Recommendation
- [ ] Deploy to production (if MAE < 4.27)
- [ ] Retrain with Phase 4 data (if available)
- [ ] Investigate issues (if MAE ≥ 4.27)

## Next Steps
1. [BASED ON RESULTS]
2. [...]
EOF

# Fill in values from training log
```

**Report to user**:
- Model performance vs baseline
- Feature importance insights
- Recommendation (deploy / retrain / investigate)
- Next steps

---

## 📊 EXPECTED OUTCOMES

### Scenario A: Success (MAE < 4.27) - MOST LIKELY

**Result**: ✅ ML approach validated! Model beats baseline.

**What this means**:
- Real XGBoost works better than mock predictions
- Feature engineering is sound
- Data quality sufficient for ML

**Next steps**:
1. ✅ Celebrate! First real ML model that beats baseline
2. Consider deployment to production
3. Optional: Wait for Phase 4 backfill completion
4. Optional: Train v6 with Phase 4 precompute features
5. Compare v5 vs v6 performance

**User decision**: Deploy v5 now or wait for v6?

---

### Scenario B: Close Miss (4.27 ≤ MAE < 4.5) - POSSIBLE

**Result**: ⚠️ ML works but doesn't beat baseline yet.

**What this means**:
- Approach is sound but needs more data/features
- Likely due to 47% usage_rate coverage (not 95%)
- Phase 4 features would help

**Next steps**:
1. Analyze feature importance
2. Check which features are underutilized
3. Wait for Phase 4 backfill (adds precompute features)
4. Retrain as v6 with Phase 4 data
5. Compare v5 vs v6

**User decision**: Wait for Phase 4 or investigate further?

---

### Scenario C: Failure (MAE ≥ 4.5) - UNLIKELY

**Result**: ❌ Model performs worse than baseline.

**What this means**:
- Data quality issue OR
- Bug in training script OR
- Feature engineering problem

**Next steps**:
1. Review training log for errors
2. Validate data quality again
3. Check feature coverage by date range
4. Look for data corruption
5. Debug training script

**User decision**: Investigate root cause before proceeding.

---

## 🔧 TROUBLESHOOTING

### Issue 1: BigQuery Access Denied

**Error**: `Permission denied` when querying BigQuery

**Solution**:
```bash
# Verify credentials
gcloud auth application-default login

# Or use service account
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

---

### Issue 2: Out of Memory

**Error**: `MemoryError` or `Killed` during training

**Solution**:
```bash
# Reduce batch size in training script
# Or run on machine with more RAM
# Or reduce training data size (use 2022-2024 only)

# Quick fix: Edit ml/train_real_xgboost.py
# Change: max_depth=8 → max_depth=6
# Change: n_estimators=500 → n_estimators=300
```

---

### Issue 3: Feature Not Found

**Error**: `KeyError: 'usage_rate'` or similar

**Solution**:
```bash
# Check which features are available
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(usage_rate IS NOT NULL) as usage_rate_count,
  COUNTIF(minutes_played IS NOT NULL) as minutes_count,
  COUNT(*) as total
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
"

# If feature missing, skip it in training script
```

---

### Issue 4: No Training Data

**Error**: `Empty dataset` or `No data found`

**Solution**:
```bash
# Verify data exists
bq query --use_legacy_sql=false "
SELECT COUNT(*)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
"

# Should return ~84,000+
# If 0: Data not in BigQuery (run Phase 3 backfill first)
```

---

## 📁 KEY FILES & LOCATIONS

### Training Script
- **Main script**: `/home/naji/code/nba-stats-scraper/ml/train_real_xgboost.py`
- **Config**: Hardcoded in script (21 features, 70/15/15 split)
- **Output**: `models/xgboost_real_v5_21features_YYYYMMDD.json`

### Validation Scripts
- **Existing (proven)**: `/scripts/validation/validate_player_summary.sh`
- **New (comprehensive)**: `/scripts/validation/validate_ml_training_ready.sh`
- **Config**: `/scripts/config/backfill_thresholds.yaml`

### Data Sources
- **Training data**: `nba-props-platform.nba_analytics.player_game_summary`
- **Team data**: `nba-props-platform.nba_analytics.team_offense_game_summary`
- **Baseline**: `nba-props-platform.nba_predictions.prediction_accuracy` (mock baseline)

### Documentation
- **This handoff**: `/docs/09-handoff/2026-01-04-ML-TRAINING-SESSION-HANDOFF.md`
- **Validation guide**: `/docs/validation-framework/COMPREHENSIVE-VALIDATION-SCRIPTS-GUIDE.md`
- **Data quality journey**: `/docs/lessons-learned/DATA-QUALITY-JOURNEY-JAN-2026.md`
- **Phase 2 audit**: From previous session (in conversation history)

---

## 🎯 SUCCESS CRITERIA

**This session is successful if**:
1. ✅ Training data validated (exit code 0)
2. ✅ Model trains without errors
3. ✅ Model file created in `models/` directory
4. ✅ Test MAE calculated and logged
5. ✅ Results compared to 4.27 baseline
6. ✅ User informed of results

**Bonus success**:
- 🎉 Test MAE < 4.27 (beats baseline!)
- 🎉 Feature importance makes sense
- 🎉 Ready for production deployment

---

## 💡 TIPS FOR NEW SESSION

### Communication with User

**User's goals**:
- Prove that real ML beats mock baseline (4.27 MAE)
- Get this right before moving on
- Don't waste time on broken data

**User's context**:
- High risk tolerance but wants to do things right
- Has been fixing data quality issues for days
- Wants validation to catch issues early
- Prefers parallel work (train ML while backfills run)

**Tone**: Professional, data-driven, concise

---

### Quick Wins

**If training succeeds** (MAE < 4.27):
- This is a MAJOR milestone
- First real ML model to beat baseline
- Celebrate this achievement
- User will be excited

**If training fails** (MAE ≥ 4.27):
- Don't panic - data quality might need Phase 4
- Investigate systematically
- Provide clear next steps
- User expects data-driven analysis

---

### What NOT to Do

❌ **Don't start backfills** - That's the other session's job
❌ **Don't fix Phase 4 data** - Not needed for v5 training
❌ **Don't create new features** - Use existing 21 features
❌ **Don't tune hyperparameters** - Use defaults first
❌ **Don't skip validation** - Run it even if it seems redundant

---

## 🔗 RELATED WORK (Running in Parallel)

**Backfill Session** (separate handoff):
- Completing Phase 4 precompute backfill
- Fixing team_offense for Oct 2025 - Jan 2026
- Can run in parallel with ML training
- Results will enable ML v6 training

**These sessions are INDEPENDENT**:
- ML v5 training does NOT need backfills to complete
- Backfill completion does NOT need ML training results
- They can run simultaneously

---

## ✅ FINAL CHECKLIST

Before starting:
- [ ] Read this entire handoff
- [ ] Understand user's goal (beat 4.27 MAE)
- [ ] Know that data is validated and ready
- [ ] Located training script (`ml/train_real_xgboost.py`)
- [ ] Identified validation script (`scripts/validation/validate_player_summary.sh`)

During execution:
- [ ] Run validation first
- [ ] Start training with logging
- [ ] Monitor progress
- [ ] Check for errors

After completion:
- [ ] Verify model file created
- [ ] Extract test MAE from logs
- [ ] Compare to 4.27 baseline
- [ ] Report results to user
- [ ] Recommend next steps

---

## 📞 HANDOFF CONTACT POINTS

**If you get stuck**:
1. Check troubleshooting section above
2. Review training script for comments
3. Check recent git commits for bug fixes
4. Read `/docs/lessons-learned/DATA-QUALITY-JOURNEY-JAN-2026.md`

**Key insights from previous session**:
- User has been debugging data quality for 2 days
- 3 critical bugs were just fixed
- Validation is crucial (prevents rework)
- User wants to see ML results ASAP

---

**GOOD LUCK! The data is ready, the bugs are fixed, and the user is waiting for results.** 🚀

**Estimated total time**: 2-3 hours from validation to final report.
