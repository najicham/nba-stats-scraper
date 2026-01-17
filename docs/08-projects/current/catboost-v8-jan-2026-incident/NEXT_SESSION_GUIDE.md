# Next Session Quick Start Guide
**For**: Session 77+ (After comprehensive investigation in Session 76)
**Priority**: P0 CRITICAL
**Estimated Time**: 2-4 hours for investigation, 1-2 hours for fixes

---

## 🚀 Start Here

**Don't read everything - start with this 5-minute brief:**

1. **What happened**: CatBoost V8 broke on Jan 8, 2026
   - Win rate: 54% → 47%
   - All picks stuck at 50% confidence
   - System unusable for production

2. **Root causes identified** (Session 76):
   - **PRIMARY**: CatBoost V8 deployment bugs (partially fixed Jan 9)
   - **SECONDARY**: player_daily_cache pipeline failures (Jan 8 & 12)
   - **MYSTERY**: Why confidence stuck at 50% after fixes?

3. **Your mission**: Fix the two unresolved issues
   - Investigate player_daily_cache failures
   - Investigate 50% confidence issue
   - Fix, backfill, and monitor

4. **Where to start**: Follow `ACTION_PLAN.md` step by step

---

## 📁 Essential Reading (20 minutes)

Read these in order:

1. **This file** (5 min) - You're reading it!
2. **[README.md](./README.md)** (10 min) - Overview and context
3. **[ROOT_CAUSE_ANALYSIS.md](./ROOT_CAUSE_ANALYSIS.md)** (5 min) - Focused analysis

**Optional deep dive**:
- [COMPREHENSIVE_INVESTIGATION_REPORT.md](./COMPREHENSIVE_INVESTIGATION_REPORT.md) (30-60 min) - Full details

---

## 🎯 Your Two Missions

### Mission 1: Fix player_daily_cache Pipeline ⚠️ P0

**Status**: BROKEN - Failed on Jan 8 & 12, will likely fail again

**What we know**:
- Table shows 0 records for Jan 8 and Jan 12
- All other Phase4 tables worked fine
- Pattern: Jan 8 = Wednesday, Jan 12 = Sunday (possible scheduler issue?)
- Missing 36% of features when this fails

**What we DON'T know**:
- Why did it fail?
- Is it a scheduler, timeout, code bug, or data issue?

**How to investigate**:
```bash
# Step 1: Check Cloud Scheduler logs
gcloud logging read \
  "resource.type=cloud_scheduler_job AND
   resource.labels.job_id=player-daily-cache-processor AND
   timestamp>=\"2026-01-07T00:00:00Z\" AND
   timestamp<=\"2026-01-13T00:00:00Z\"" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform

# Step 2: Check function execution logs
gcloud logging read \
  "resource.type=cloud_function AND
   resource.labels.function_name=player-daily-cache AND
   timestamp>=\"2026-01-07T00:00:00Z\" AND
   timestamp<=\"2026-01-13T00:00:00Z\"" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform

# Step 3: Try manual run
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --date 2026-01-08 \
  --dry-run
```

**Full details**: See `ACTION_PLAN.md` → Task 1

---

### Mission 2: Fix 50% Confidence Stuck Issue ⚠️ P0

**Status**: CRITICAL - System can't make recommendations

**What we know**:
- After deployment bugs fixed (Jan 9), accuracy returned to baseline
- But ALL picks show exactly 50% confidence
- 50% is the hardcoded fallback value in `_fallback_prediction()`

**What we DON'T know**:
- Why is fallback mode triggered?
- Is model not loading? Features invalid? Silent exception?

**How to investigate**:
```bash
# Step 1: Check prediction logs
gcloud logging read \
  "resource.type=cloud_run_revision AND
   resource.labels.service_name=prediction-worker AND
   timestamp>=\"2026-01-12T00:00:00Z\" AND
   timestamp<=\"2026-01-16T00:00:00Z\"" \
  --limit=200 \
  --format=json \
  --project=nba-props-platform | grep -i "fallback"

# Step 2: Test model loading locally
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8PredictionSystem
import numpy as np

system = CatBoostV8PredictionSystem()
print(f"Model loaded: {system.model is not None}")

# Test confidence calculation
features = {'feature_quality_score': 85, 'points_std_last_10': 5.2}
confidence = system._calculate_confidence(features, np.array([20.0] * 33))
print(f"Confidence: {confidence}")  # Should be ~89, NOT 50
EOF
```

**Full details**: See `ACTION_PLAN.md` → Task 2

---

## 📊 Quick Health Check

**Before you start investigating, verify the issue still exists**:

```sql
-- Check if player_daily_cache is updating now
SELECT
    cache_date,
    COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= CURRENT_DATE() - 3
GROUP BY cache_date
ORDER BY cache_date DESC;

-- Check current confidence distribution
SELECT
    ROUND(confidence_score * 100) as confidence_pct,
    COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v8'
  AND game_date >= CURRENT_DATE() - 1
GROUP BY confidence_pct
ORDER BY confidence_pct DESC;

-- If still showing 0 players or 100% at 50% confidence, proceed with investigation
```

---

## 🛠️ Tools & Resources

### Key Files to Know

**Code**:
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Pipeline that's failing
- `predictions/worker/prediction_systems/catboost_v8.py` - Confidence calculation (line 373-407)
- `data_processors/precompute/ml_feature_store/quality_scorer.py` - Feature quality scoring

**Config**:
- Cloud Scheduler: `player-daily-cache-processor` job
- Cloud Functions/Run: Check deployment configs

**Data**:
- `nba_precompute.player_daily_cache` - Table that's failing to update
- `ml_nba.ml_feature_store_v2` - Feature quality scores
- `nba_predictions.prediction_accuracy` - Prediction results

### Useful Commands

```bash
# List all Cloud Scheduler jobs
gcloud scheduler jobs list --project=nba-props-platform

# Tail prediction logs live
gcloud logging tail "resource.type=cloud_run_revision" --project=nba-props-platform

# Run manual backfill
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor --date YYYY-MM-DD

# Check BigQuery table
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_precompute.player_daily_cache WHERE cache_date = 'YYYY-MM-DD'"
```

### SQL Queries

All investigation queries are in: `queries/` directory (to be created)

---

## ⏱️ Time Budget

**Investigation Phase** (2-4 hours):
- Mission 1: player_daily_cache investigation (1-2 hours)
- Mission 2: 50% confidence investigation (1-2 hours)

**Fix Phase** (1-2 hours):
- Apply fixes based on findings (30 min each)
- Backfill missing data (30 min)

**Verification** (30 min):
- Run health checks
- Monitor for stability

**Don't spend more than 2 hours on any single task without documenting progress and asking for help.**

---

## 🚦 Decision Tree

```
START
  ↓
Run Quick Health Check (5 min)
  ↓
Issues still exist?
  ├─ YES → Proceed with investigation
  │         ↓
  │       Investigate player_daily_cache (Mission 1)
  │         ↓
  │       Found root cause?
  │         ├─ YES → Apply fix, backfill, verify
  │         └─ NO → Document findings, escalate
  │         ↓
  │       Investigate 50% confidence (Mission 2)
  │         ↓
  │       Found root cause?
  │         ├─ YES → Apply fix, verify
  │         └─ NO → Document findings, escalate
  │         ↓
  │       Both fixed?
  │         ├─ YES → Add monitoring, verify 3 days
  │         └─ NO → Continue investigation
  │
  └─ NO → System recovered on its own!
            ↓
          Document what changed
          Add monitoring anyway
          Close incident
```

---

## ✅ Success Criteria

**You'll know you succeeded when**:

1. **player_daily_cache updates daily**
   - Query shows 50-200 players per day
   - No gaps in cache_date

2. **Confidence shows distribution**
   - NOT 100% at 50%
   - Shows various values (75-95%)
   - Some high-confidence picks (85%+)

3. **Performance restored**
   - Win rate ≥53%
   - Avg error ≤5.0 points
   - Feature quality ≥90

4. **Stability confirmed**
   - 3+ consecutive days of healthy metrics
   - No sudden drops
   - Monitoring in place

---

## 🔔 When to Ask for Help

**Immediate escalation needed if**:
- Cloud logs show access denied/permissions errors
- Manual runs fail with infrastructure errors
- Fixes make things worse
- New critical issues discovered

**Ask for help after 2 hours if**:
- Can't find relevant logs
- Can't reproduce issue
- Root cause unclear after investigation
- Unsure how to fix identified issue

---

## 📝 Documentation Requirements

**As you investigate, create**:

1. `investigation-findings/player-daily-cache-failure.md`
   - Logs found
   - Root cause identified
   - Fix applied
   - Verification results

2. `investigation-findings/50-percent-confidence-issue.md`
   - Same structure

3. `RESOLUTION_SUMMARY.md`
   - Overall resolution
   - Timeline
   - Lessons learned

**Update**:
- `README.md` status (when resolved)
- `ACTION_PLAN.md` checkboxes (as you go)

---

## 🎓 Key Learnings from Session 76

**What Session 76 discovered**:

1. **Jan 7 commit was NOT the cause**
   - Original hypothesis was wrong
   - Commit was well-written infrastructure improvements
   - Do NOT revert

2. **Two separate failures occurred**
   - Deployment bugs (partially fixed)
   - Pipeline failures (unfixed)

3. **CatBoost V8 isolated**
   - All other systems IMPROVED during incident
   - Confirms V8-specific issues

4. **Confidence formula is correct**
   - Not a calculation bug
   - Stuck in fallback mode for unknown reason

**Don't repeat these mistakes**:
- Don't assume correlation = causation
- Don't trust initial hypothesis without evidence
- Don't revert commits without understanding impact

---

## 🔗 Quick Links

- [ACTION_PLAN.md](./ACTION_PLAN.md) - Step-by-step guide
- [ROOT_CAUSE_ANALYSIS.md](./ROOT_CAUSE_ANALYSIS.md) - Root causes
- [README.md](./README.md) - Full overview
- Session 75 handoff: `docs/09-handoff/2026-01-17-SESSION-75-CATBOOST-INVESTIGATION-HANDOFF.md` (outdated, ignore)

---

## 💡 Pro Tips

1. **Start with logs** - They usually have the answer
2. **Test locally first** - Faster iteration than production
3. **Document as you go** - You'll forget details quickly
4. **Verify assumptions** - Check what you think is true
5. **Ask for help early** - Don't waste hours stuck

---

## 🏁 Ready to Start?

1. ✅ Read this guide (done!)
2. ✅ Read README.md (10 min)
3. ✅ Read ROOT_CAUSE_ANALYSIS.md (5 min)
4. ✅ Run Quick Health Check (5 min)
5. ✅ Open ACTION_PLAN.md
6. ✅ Start Mission 1

**Good luck! You've got this.** 🚀

---

**Last Updated**: 2026-01-16 (Session 76)
**Next Update**: After investigations complete
**Status**: Ready for Session 77
