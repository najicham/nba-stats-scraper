# Session 208 Start Prompt

Copy-paste this into your next Claude Code session:

---

Hi! Continue monitoring the NBA predictions system.

## Context from Session 207 (Feb 11, 2026)

**What was accomplished:**
- ✅ Successfully deployed Feature 4 bug fix (Session 202)
- ✅ Verified 10x prediction improvement: 20 → 196 predictions
- ✅ Feature 4 defaults dropped from 49.6% → 8.6%
- ✅ Comprehensive daily validation: System healthy for Feb 11 games
- ✅ All critical services up to date (deployed at 1:34 PM PST)

**Pre-game status (5:17 PM ET, Feb 11):**
- 14 games scheduled for tonight
- 2,094 predictions across 11 models (426 actionable)
- catboost_v9: 192 predictions, 29 actionable
- Pre-game signal: 🟢 GREEN (balanced, 34.4% over)
- Feature quality: 75.8% ready (normal for pre-game)
- Vegas coverage: 42.8% (expected to improve by game time)

**System Status:** 🟢 HEALTHY - Ready for tonight's games

## Your Tasks

**1. Post-Game Validation (Morning)**
Check how last night's games performed:
```bash
/validate-daily
# Select: "Yesterday's results (post-game check)"
# Select: "Standard (Recommended)"
```

**2. Verify Feature 4 Fix持續Working**
```bash
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNTIF(4 IN UNNEST(default_feature_indices)) as feature_4_defaults,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(4 IN UNNEST(default_feature_indices)) / COUNT(*), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY 1 ORDER BY 1 DESC"
```
**Expected:** Feature 4 defaults ≤10% (Session 207 showed 8.6%)

**3. Check Prediction Accuracy**
Review how catboost_v9 performed on Feb 11 games:
```bash
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-11'
  AND system_id = 'catboost_v9'
GROUP BY system_id"
```

**4. Monitor Any Alerts**
Check for issues from overnight processing:
```bash
./bin/monitoring/morning_health_check.sh
```

## Expected Outcomes

✅ **Feature 4 defaults:** Should remain at ~8% (was 8.6% on Feb 11)
✅ **Predictions:** Should see 80-100+ predictions per day (vs 20 pre-fix)
✅ **Hit rate:** Target 60%+ on all predictions, 70%+ on high-edge

## Red Flags to Watch For

🚨 **Critical Issues:**
- Feature 4 defaults spike back above 40%
- Predictions drop below 50 per day
- Phase 4 deployment drift detected

🟡 **Warnings:**
- Feature quality ready < 70%
- Vegas line coverage < 40%
- Usage rate coverage < 80%

## Reference

**Handoff:** `docs/09-handoff/2026-02-11-SESSION-207-HANDOFF.md`
**Previous Fix:** Session 202 - Feature 4 bug fix deployment
**Commit:** `7fcc29ad` - games_in_last_7_days added to feature extraction

---

Start by running `/validate-daily` to check post-game results!
