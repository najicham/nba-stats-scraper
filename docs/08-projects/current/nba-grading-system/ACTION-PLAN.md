# NBA Grading Enhancements - Action Plan

**Your Next Steps** - Follow this guide step-by-step

---

## ✅ What's Ready

All code is written and ready to deploy:
- ✅ Slack alerting service (Cloud Function)
- ✅ Deployment scripts
- ✅ Documentation

**Files created**:
```
services/nba_grading_alerts/
├── main.py                  # Alert logic
├── requirements.txt         # Dependencies
├── .gcloudignore           # Deployment config
└── README.md               # Service docs

bin/alerts/
└── deploy_nba_grading_alerts.sh  # One-command deployment

docs/08-projects/current/nba-grading-system/
├── SLACK-SETUP-GUIDE.md    # Detailed Slack setup
├── QUICK-START-ENHANCEMENTS.md  # Full implementation guide
├── ENHANCEMENT-PLAN.md     # Long-term roadmap
└── ACTION-PLAN.md          # This file
```

---

## 🎯 Step-by-Step: Get Alerts Working (30 minutes)

### Step 1: Create Slack Channel (2 minutes)

1. Open your Slack workspace
2. Click **"+"** next to "Channels"
3. Select **"Create a channel"**
4. Configure:
   - **Name**: `nba-grading-alerts`
   - **Description**: `Automated NBA prediction grading alerts`
   - **Privacy**: Your choice (Public or Private)
5. Click **"Create"**
6. Invite team members who should see alerts

**✅ Done?** You should see `#nba-grading-alerts` in your channels.

---

### Step 2: Create Slack Webhook (5 minutes)

#### Option A: Create New Slack App (Recommended)

1. Go to https://api.slack.com/apps
2. Click **"Create New App"**
3. Select **"From scratch"**
4. Enter:
   - **App Name**: `NBA Props Grading Monitor`
   - **Workspace**: Select your workspace
5. Click **"Create App"**
6. In left sidebar, click **"Incoming Webhooks"**
7. Toggle **"Activate Incoming Webhooks"** to **ON**
8. Scroll down, click **"Add New Webhook to Workspace"**
9. Select channel: **#nba-grading-alerts**
10. Click **"Allow"**
11. **COPY THE WEBHOOK URL** - looks like:
    ```
    https://hooks.slack.com/services/T12345678/B12345678/XXXXXXXXXXXXXXXX
    ```

#### Option B: Use Existing App

1. Go to https://api.slack.com/apps
2. Select your existing app
3. Click **"Incoming Webhooks"** in sidebar
4. Enable if not already on
5. Click **"Add New Webhook to Workspace"**
6. Select **#nba-grading-alerts**
7. **COPY THE WEBHOOK URL**

**✅ Done?** You have a webhook URL that starts with `https://hooks.slack.com/services/`

---

### Step 3: Test Webhook (2 minutes)

Verify the webhook works before deploying:

```bash
# Replace with your actual webhook URL
WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Send test message
curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"✅ Test successful! NBA Grading Alerts webhook is working."}' \
    "$WEBHOOK_URL"
```

**✅ Expected**: You see the test message in `#nba-grading-alerts` channel.

**❌ If it fails**:
- Check webhook URL is correct (no typos)
- Ensure webhook is enabled in Slack app settings
- Try regenerating the webhook

---

### Step 4: Store Webhook in Secret Manager (3 minutes)

```bash
# Set your webhook URL (replace with yours)
WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Store securely in Google Secret Manager
echo "$WEBHOOK_URL" | gcloud secrets create nba-grading-slack-webhook \
    --data-file=- \
    --replication-policy="automatic" \
    --project=nba-props-platform

# Verify it was stored
gcloud secrets describe nba-grading-slack-webhook --project=nba-props-platform
```

**✅ Expected output**: Secret details showing it was created.

**If secret already exists**:
```bash
# Update existing secret with new version
echo "$WEBHOOK_URL" | gcloud secrets versions add nba-grading-slack-webhook \
    --data-file=- \
    --project=nba-props-platform
```

---

### Step 5: Deploy Alerting Service (5 minutes)

```bash
# From repo root
./bin/alerts/deploy_nba_grading_alerts.sh
```

**What this does**:
1. Checks webhook secret exists
2. Grants Cloud Function access to secret
3. Deploys Cloud Function to us-west2
4. Creates Cloud Scheduler job (daily at 12:30 PM PT)
5. Tests the function

**✅ Expected output**:
```
========================================
 Deployment Complete!
========================================

📋 Summary:
  Function: nba-grading-alerts
  URL: https://nba-grading-alerts-...
  Schedule: Daily at 12:30 PM PT
  Thresholds:
    - Accuracy minimum: 55%
    - Ungradeable maximum: 20%
    - Check period: 7 days

✅ Check Slack channel #nba-grading-alerts for test message!
```

**❌ If deployment fails**:
- Check you're authenticated: `gcloud auth list`
- Check project is correct: `gcloud config get-value project`
- Check you have permissions to deploy Cloud Functions

---

### Step 6: Test Alerts (3 minutes)

Manually trigger the function to verify it works:

```bash
# Trigger the scheduler job manually
gcloud scheduler jobs run nba-grading-alerts-daily \
    --location=us-west2 \
    --project=nba-props-platform
```

**✅ Expected**: Within 30 seconds, you should see alerts in `#nba-grading-alerts`

**Check function logs**:
```bash
gcloud functions logs read nba-grading-alerts \
    --region=us-west2 \
    --limit=20 \
    --project=nba-props-platform
```

---

### Step 7: Verify Scheduler (2 minutes)

Confirm the job is scheduled correctly:

```bash
gcloud scheduler jobs describe nba-grading-alerts-daily \
    --location=us-west2 \
    --project=nba-props-platform
```

**Look for**:
- `schedule: 30 20 * * *` (12:30 PM PT daily)
- `state: ENABLED`
- `timeZone: America/Los_Angeles`

---

## 🎉 Phase 1 Complete!

You now have:
- ✅ Slack channel for alerts
- ✅ Webhook configured and tested
- ✅ Cloud Function deployed
- ✅ Daily scheduler running at 12:30 PM PT

**What happens next**:
- Tomorrow at 12:30 PM PT, the function will check yesterday's grading
- If issues found, you'll get Slack alerts
- If everything is healthy, no alerts (unless you enable daily summary)

---

## 📊 Phase 2: Dashboard Updates (Optional, 2 hours)

Want to add grading features to your admin dashboard?

See: `QUICK-START-ENHANCEMENTS.md` - Phase 2 section

**What it adds**:
- Fix schema mismatch (use new `prediction_grades` table)
- Add accuracy percentage to Coverage Metrics tab
- Add system breakdown table showing each system's accuracy
- Real-time accuracy monitoring

---

## ⚙️ Configuration Options

### Enable Daily Summary

Get a daily report even when everything is healthy:

```bash
gcloud functions deploy nba-grading-alerts \
    --update-env-vars SEND_DAILY_SUMMARY=true \
    --region=us-west2 \
    --gen2 \
    --project=nba-props-platform
```

### Adjust Alert Thresholds

Change when alerts fire:

```bash
# Lower accuracy threshold to 50% (more lenient)
gcloud functions deploy nba-grading-alerts \
    --update-env-vars ALERT_THRESHOLD_ACCURACY_MIN=50 \
    --region=us-west2 \
    --gen2 \
    --project=nba-props-platform

# Raise ungradeable threshold to 30% (more lenient)
gcloud functions deploy nba-grading-alerts \
    --update-env-vars ALERT_THRESHOLD_UNGRADEABLE_MAX=30 \
    --region=us-west2 \
    --gen2 \
    --project=nba-props-platform
```

### Change Alert Schedule

Run at different time:

```bash
# Change to 1:00 PM PT (21:00 UTC)
gcloud scheduler jobs update http nba-grading-alerts-daily \
    --schedule="0 21 * * *" \
    --location=us-west2 \
    --project=nba-props-platform
```

---

## 🐛 Troubleshooting

### "Webhook not found" during deployment

**Problem**: Secret doesn't exist in Secret Manager

**Fix**:
```bash
echo "YOUR_WEBHOOK_URL" | gcloud secrets create nba-grading-slack-webhook \
    --data-file=- --replication-policy=automatic --project=nba-props-platform
```

### No alerts appearing in Slack

**Diagnose**:
```bash
# Check function logs
gcloud functions logs read nba-grading-alerts --region=us-west2 --limit=50

# Check if webhook URL is correct
gcloud secrets versions access latest --secret=nba-grading-slack-webhook
```

**Common causes**:
- Webhook URL is wrong → Re-create secret with correct URL
- Function errored → Check logs for Python errors
- No issues detected → Expected behavior (only alerts on problems)

### Function deployment fails

**Check permissions**:
```bash
# Ensure you have Cloud Functions Admin role
gcloud projects get-iam-policy nba-props-platform \
    --flatten="bindings[].members" \
    --filter="bindings.members:$(gcloud config get-value account)"
```

**Re-authenticate**:
```bash
gcloud auth login
gcloud auth application-default login
```

### Scheduler not triggering

**Check state**:
```bash
gcloud scheduler jobs describe nba-grading-alerts-daily --location=us-west2
```

**If PAUSED**:
```bash
gcloud scheduler jobs resume nba-grading-alerts-daily --location=us-west2
```

---

## 📚 Documentation

- **Slack Setup**: `SLACK-SETUP-GUIDE.md` (detailed webhook guide)
- **Full Enhancement Plan**: `ENHANCEMENT-PLAN.md` (all 6 phases)
- **Quick Start**: `QUICK-START-ENHANCEMENTS.md` (code-ready guide)
- **Service Docs**: `services/nba_grading_alerts/README.md`

---

## ✅ Checklist

Before moving to Phase 2, verify:

- [ ] Slack channel `#nba-grading-alerts` created
- [ ] Incoming webhook URL obtained
- [ ] Webhook tested with curl (message appeared)
- [ ] Secret stored in Secret Manager
- [ ] Cloud Function deployed successfully
- [ ] Scheduler job created and enabled
- [ ] Manual trigger test passed (alert received)
- [ ] Function logs show no errors

**All checked?** You're done with Phase 1! 🎉

---

## 🚀 What's Next?

1. **Monitor for 1 week**: Let the system run and verify alerts work
2. **Tune thresholds**: Adjust if getting too many/few alerts
3. **Phase 2** (optional): Add dashboard features
4. **Phase 3** (optional): ROI calculator, advanced analytics

**Questions?** Check the troubleshooting section or review the logs.

---

**Need help?** All code is ready to go. Just follow the steps above!
