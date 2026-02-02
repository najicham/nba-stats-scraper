# Session 84 Start Prompt - Post-Game Validation & Model Attribution

**Date**: Feb 2, 2026 (Evening) or Feb 3, 2026 (Morning)
**Previous**: Session 83 (Built 3-channel notifications, validated subset system)
**Priority**: Validate NEW V9 model performance + Add model attribution to picks

---

## 🎯 Your Mission

### CRITICAL Priority 1: Validate NEW V9 Model Performance

**Context**: Session 82 deployed NEW V9 model (catboost_v9_feb_02_retrain.cbm) but we don't know if it's actually working yet. Feb 2 was the FIRST day it generated predictions.

**Check if games finished**:
```bash
bq query --use_legacy_sql=false "
SELECT game_status, COUNT(*)
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-02')
GROUP BY 1"
```

**If game_status = 3 (Final), run validation**:
```bash
./bin/validate-feb2-model-performance.sh
```

**What to look for**:
- catboost_v9 hit rate ~74.6%? → ✅ NEW model working
- catboost_v9 hit rate ~50%? → ⚠️ OLD model or issue
- catboost_v9 MAE ~4.12? → ✅ NEW model
- catboost_v9 MAE ~5.0+? → ⚠️ OLD model

**Expected Results**:
- NEW model: MAE 4.12, High-edge HR 74.6%
- OLD model (catboost_v9_2026_02): MAE 5.08, HR 50.84%
- RED signal day: May see lower HR due to 79.5% UNDER bias

### Priority 2: Add Model Attribution to Predictions

**Problem**: We can't tell which exact model file generated which predictions. The 75.9% historical hit rate from Session 83 could be from OLD or NEW model - we don't know!

**Task**: Enhance prediction tracking to include:
1. **Exact model file used** (e.g., "catboost_v9_feb_02_retrain.cbm")
2. **Model training dates** (e.g., "2025-11-02 to 2026-01-31")
3. **Model MAE/performance** (e.g., "Expected MAE: 4.12")
4. **Deployment timestamp** (when this model was deployed)
5. **Which subset definition** was used (version/config)

**Where to add**:
- `player_prop_predictions` table: Add model_file_name, model_training_start, model_training_end fields
- `prediction_execution_log` table: Already has model_path but verify it's populated
- Subset pick notifications: Include model info in messages

**Example of what picks should show**:
```
🏀 Today's Top Picks - Feb 3, 2026
Model: CatBoost V9 Feb-02 Retrain (MAE 4.12, trained 11/2/25-1/31/26)
File: catboost_v9_feb_02_retrain.cbm
Deployed: Feb 2, 2026 1:31 PM PST (Session 82)

Signal: 🟢 GREEN (35% OVER)

Top 5 Picks...
```

**Why this matters**:
- We can't currently prove which model produced the 75.9% HR
- Future model comparisons need clear attribution
- Debugging requires knowing exact model version
- Historical analysis requires model provenance

### Priority 3: Configure Notifications (If User Ready)

**Status Check**:
```bash
# Check which channels are configured
echo "Slack: $SLACK_WEBHOOK_URL_SIGNALS"
echo "Email: $BREVO_SMTP_USERNAME"
echo "SMS: $TWILIO_ACCOUNT_SID"
```

**If user has signed up**:
- Help configure Twilio SMS (see SETUP_GUIDE.md)
- Help configure Brevo Email (see SETUP_GUIDE.md)
- Set up Cloud Scheduler automation

---

## 📋 Context from Session 83

### What Was Built

1. **Subset Picks System Validated**:
   - 9 active subsets running
   - Historical data: 23 days
   - Performance: v9_top5 = 75.9% HR, v9_top1 = 81.8% HR
   - **BUT**: Don't know which model version produced these results!

2. **3-Channel Notifications**:
   - Slack: Code ready, needs webhook config
   - Email: Code ready, needs Brevo signup
   - SMS: Code ready, needs Twilio signup

3. **V9 Model Documentation**:
   - Fixed metadata in catboost_v9.py
   - Created architecture docs
   - Clarified NEW vs OLD model confusion

### Current State

**Feb 2 Predictions**:
- 68 players predicted across 8 systems
- Signal: 🔴 RED (2.5% OVER - extreme UNDER bias)
- Top pick: Trey Murphy III UNDER 22.5 (Edge: 11.4)
- **Model used**: catboost_v9 (but unclear if NEW or OLD file!)

**Model Deployment**:
- NEW V9 deployed: Session 82 (Feb 2, 1:31 PM PST)
- Model file: catboost_v9_feb_02_retrain.cbm
- Expected: MAE 4.12, HR 74.6%
- Actual: **UNKNOWN** - needs validation

**Notifications**:
- Code complete for all 3 channels
- Not yet configured (pending user signups)
- Automation script ready

---

## 🔧 Key Files & Commands

### Validation
```bash
# Validate Feb 2 model performance
./bin/validate-feb2-model-performance.sh

# Check subset system
./bin/test-subset-system.sh

# Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

### Notifications
```bash
# Test dry run
PYTHONPATH=. python bin/notifications/send_daily_picks.py --test

# Test individual channels
PYTHONPATH=. python bin/notifications/send_daily_picks.py --slack-only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --email-only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --sms-only

# Setup automation
./bin/notifications/setup_daily_picks_scheduler.sh
```

### Investigation
```bash
# Check which model is deployed
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep CATBOOST

# Check prediction execution log
bq query --use_legacy_sql=false "
SELECT model_path, COUNT(*)
FROM nba_predictions.prediction_execution_log
WHERE DATE(execution_start_timestamp) = DATE('2026-02-02')
  AND model_path IS NOT NULL
GROUP BY model_path"

# Check worker startup logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND textPayload=~"Loading.*V9"' --limit=10
```

---

## ⚠️ Critical Questions to Answer

1. **Did the NEW model work?**
   - Check hit rate and MAE from validation script
   - Compare catboost_v9 vs catboost_v9_2026_02

2. **What model produced the 75.9% historical HR?**
   - Query prediction_execution_log for model_path
   - Check when NEW model started being used
   - Distinguish OLD vs NEW performance

3. **How do we prevent this confusion in the future?**
   - Add model file tracking to predictions table
   - Include model info in notifications
   - Create model version audit trail

4. **Is RED signal hypothesis validated?**
   - Did Feb 2 (RED day, 79.5% UNDER) have lower HR?
   - Compare to GREEN day performance
   - Statistical significance?

---

## 📊 Expected Outcomes

### If NEW Model Working (Expected)
- catboost_v9 hit rate: 70-75%
- catboost_v9 MAE: 4.0-4.5
- Confirms Session 82 deployment successful
- Can proceed with notifications setup

### If OLD Model Still Running (Problem)
- catboost_v9 hit rate: 50-55%
- catboost_v9 MAE: 5.0+
- Need to redeploy with correct model
- Investigate why Session 82 fix didn't work

### RED Signal Day Analysis
- Regardless of model, test signal hypothesis
- Feb 2 had 79.5% UNDER bias (extreme RED)
- Historical RED: 62.5% vs GREEN: 79.6%
- Does Feb 2 confirm this pattern?

---

## 📁 Key Files

### Documentation
- `docs/09-handoff/2026-02-02-SESSION-83-COMPLETE-HANDOFF.md` - Full session 83 handoff
- `docs/08-projects/current/ml-model-v9-architecture/README.md` - V9 architecture
- `bin/notifications/SETUP_GUIDE.md` - Notification setup guide

### Code
- `shared/notifications/subset_picks_notifier.py` - 3-channel notifier
- `shared/utils/sms_notifier.py` - SMS integration
- `bin/notifications/send_daily_picks.py` - CLI tool
- `predictions/worker/prediction_systems/catboost_v9.py` - V9 model loader

### Validation
- `bin/validate-feb2-model-performance.sh` - Feb 2 validation
- `bin/test-subset-system.sh` - Subset system test
- `schemas/bigquery/predictions/views/v_dynamic_subset_performance.sql` - Performance tracking

---

## 🎯 Session Goals

By end of session, you should have:
1. ✅ Validated NEW V9 model performance (or identified issue)
2. ✅ Enhanced predictions with model attribution
3. ✅ Updated notifications to show model details
4. ✅ Distinguished OLD vs NEW model historical performance
5. ✅ (Optional) Configured notification channels if user ready

---

## 🚀 Quick Start Commands

```bash
# 1. Check game status
bq query --use_legacy_sql=false "SELECT game_status, COUNT(*) FROM nba_reference.nba_schedule WHERE game_date = DATE('2026-02-02') GROUP BY 1"

# 2. If games finished, validate
./bin/validate-feb2-model-performance.sh

# 3. Investigate model attribution
bq query --use_legacy_sql=false "SELECT model_path, system_id, COUNT(*) FROM nba_predictions.prediction_execution_log WHERE DATE(execution_start_timestamp) = DATE('2026-02-02') GROUP BY 1,2"

# 4. Check subset performance by model
bq query --use_legacy_sql=false "SELECT system_id, COUNT(*) as picks, ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-02' GROUP BY 1 ORDER BY 2 DESC"
```

---

## 💡 Tips

- **Be skeptical of historical performance** - Always check which model version it came from
- **Model attribution is critical** - Can't improve what you can't track
- **RED signal day is valuable** - Use it to validate signal hypothesis
- **Don't assume deployment worked** - Verify with actual performance data
- **Documentation matters** - Future sessions need to know which model was used

---

## 📞 Questions to Ask User

1. Have games finished? (Check game_status)
2. Did you sign up for Twilio/Brevo? (If yes, help configure)
3. What's the priority: validation or notifications?
4. Do you want model attribution in notifications?

---

**TL;DR**: Validate if NEW V9 model worked tonight, then add model tracking to prevent future confusion about which model produced which results.

**Start here**: `./bin/validate-feb2-model-performance.sh`
