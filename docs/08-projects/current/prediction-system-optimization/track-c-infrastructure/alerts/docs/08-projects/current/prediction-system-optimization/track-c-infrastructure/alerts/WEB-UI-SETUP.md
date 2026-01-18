# Alert Setup - Web UI Guide
**Created:** 2026-01-18
**Time Required:** 10-15 minutes
**Status:** Ready to execute

---

## ✅ Prerequisites Complete

The following log-based metrics are **already created** and tracking data:
- ✅ `coordinator_errors` - Tracks errors in prediction coordinator
- ✅ `daily_predictions` - Tracks prediction generation

---

## 🚀 Quick Setup (2 Alerts in 15 minutes)

### Step 1: Create Notification Channel (5 minutes)

**Option A: Email Notifications (Recommended)**

1. Go to: https://console.cloud.google.com/monitoring/alerting/notifications?project=nba-props-platform

2. Click **"Create Channel"**

3. Select **"Email"**

4. Enter your email address

5. Click **"Save"**

6. **Verify email** (check inbox for verification link)

**Option B: Slack (if you have Slack workspace)**
- Follow same steps but choose "Slack"
- Connect your workspace
- Select channel for alerts

---

### Step 2: Create Alert Policy #1 - Coordinator Errors (5 minutes)

1. Go to: https://console.cloud.google.com/monitoring/alerting/policies/create?project=nba-props-platform

2. Click **"Select a metric"**

3. In the search box, type: `coordinator_errors`

4. Select: **"Logging > User-defined Metrics > coordinator_errors"**

5. Click **"Apply"**

6. Configure threshold:
   - **Condition type:** Threshold
   - **Threshold position:** Above threshold
   - **Threshold value:** `0`
   - **For:** `5 minutes`

7. Click **"Next"**

8. Configure notifications:
   - Select your email notification channel
   - Click **"Next"**

9. Name your alert:
   - **Alert name:** "🔴 Prediction Coordinator - Errors Detected"
   - **Documentation:** (paste below)
   ```
   The prediction coordinator has experienced errors.

   **Immediate Actions:**
   1. Check Cloud Run logs: https://console.cloud.google.com/run/detail/us-west2/prediction-coordinator/logs?project=nba-props-platform
   2. Review error messages
   3. Check if feature store is accessible
   4. Verify Cloud Scheduler is running

   **Runbook:** docs/08-projects/current/prediction-system-optimization/track-c-infrastructure/RUNBOOK.md
   ```

10. Click **"Create Policy"**

✅ **Alert #1 Created!**

---

### Step 3: Create Alert Policy #2 - Low Prediction Volume (5 minutes)

1. Go to: https://console.cloud.google.com/monitoring/alerting/policies/create?project=nba-props-platform

2. Click **"Select a metric"**

3. In the search box, type: `daily_predictions`

4. Select: **"Logging > User-defined Metrics > daily_predictions"**

5. Click **"Apply"**

6. Configure threshold:
   - **Condition type:** Metric absence
   - **Duration:** `25 hours`
   - (This triggers if coordinator doesn't run for >25 hours)

7. Click **"Next"**

8. Configure notifications:
   - Select your email notification channel
   - Click **"Next"**

9. Name your alert:
   - **Alert name:** "⚠️ Prediction Coordinator - No Recent Runs"
   - **Documentation:** (paste below)
   ```
   The prediction coordinator has not run successfully in the past 25 hours.

   **Immediate Actions:**
   1. Check Cloud Scheduler: https://console.cloud.google.com/cloudscheduler?project=nba-props-platform
   2. Verify scheduler job is enabled
   3. Check last execution status
   4. Review Cloud Run service health

   **Expected:** Coordinator runs daily at 23:00 UTC (3:00 PM PST)

   **Runbook:** docs/08-projects/current/prediction-system-optimization/track-c-infrastructure/RUNBOOK.md
   ```

10. Click **"Create Policy"**

✅ **Alert #2 Created!**

---

## 🎯 Verification

After creating both alerts, verify they're active:

```bash
# List all alert policies
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --format="table(displayName,enabled,conditions[0].displayName)"
```

**Expected output:**
```
DISPLAY_NAME                                           ENABLED
🔴 Prediction Coordinator - Errors Detected            True
⚠️ Prediction Coordinator - No Recent Runs             True
```

---

## 📊 What You've Set Up

### Alert #1: Coordinator Errors
- **Triggers:** When ANY errors occur in prediction-coordinator
- **Threshold:** > 0 errors in 5 minutes
- **Severity:** CRITICAL 🔴
- **Action:** Check logs immediately

### Alert #2: No Recent Runs
- **Triggers:** When coordinator hasn't run in 25 hours
- **Threshold:** No log entries for "daily_predictions" metric
- **Severity:** HIGH ⚠️
- **Action:** Check Cloud Scheduler

---

## 🧪 Testing Your Alerts (Optional)

**Test Alert #1 (Errors):**
```bash
# Trigger a test error (if you want to verify alerting works)
# NOTE: This will actually trigger your alert!
gcloud logging write coordinator_errors \
  "Test error message" \
  --severity=ERROR \
  --resource=cloud_run_revision \
  --project=nba-props-platform

# You should receive an email within 5 minutes
```

**Test Alert #2 (No Runs):**
- This will naturally trigger if coordinator stops running
- Can't easily test without disabling the scheduler (not recommended)

---

## 📈 Monitoring Your Alerts

**View Alert Status:**
https://console.cloud.google.com/monitoring/alerting/policies?project=nba-props-platform

**View Alert Incidents:**
https://console.cloud.google.com/monitoring/alerting/incidents?project=nba-props-platform

**View Metrics Dashboard:**
https://console.cloud.google.com/monitoring/metrics-explorer?project=nba-props-platform

---

## ✅ Success Criteria

You'll know alerts are working when:
- ✅ Both policies show "Enabled" = True
- ✅ Email notification channel is verified
- ✅ You receive test alert email (if tested)
- ✅ No incidents currently firing (if system is healthy)

---

## 🔮 What's Next

After alerts are set up, consider:
1. **Add more alerts** (grading processor, model serving, etc.)
2. **Create dashboard** for visualizing metrics
3. **Write runbook** for common failure scenarios
4. **Set up PagerDuty** (if you need on-call rotation)

See: `docs/08-projects/current/prediction-system-optimization/FUTURE-OPTIONS.md` for Track C details

---

## 🆘 Troubleshooting

**Email not verified:**
- Check spam folder
- Resend verification email from notification channel settings

**Alert not triggering:**
- Check metric is collecting data: Metrics Explorer
- Verify threshold settings
- Check notification channel is selected

**Too many alerts:**
- Adjust threshold (e.g., > 5 errors instead of > 0)
- Increase duration (e.g., 10 minutes instead of 5)

---

**Time to complete:** ~15 minutes
**Value:** Proactive monitoring starts TODAY! 🎯
