# Slack Setup Guide for NBA Grading Alerts

## Step 1: Create Slack Channel

**In your Slack workspace:**

1. Click the **"+"** button next to "Channels" in the left sidebar
2. Select **"Create a channel"**
3. Configure channel:
   - **Name**: `nba-grading-alerts`
   - **Description**: `Automated alerts for NBA prediction grading system - accuracy monitoring, data quality, and grading failures`
   - **Privacy**:
     - Choose **Private** if you want to limit who sees alerts
     - Choose **Public** if anyone in workspace should see
   - **Send invites to**: Add relevant team members (engineers, data scientists, stakeholders)
4. Click **"Create"**

**✅ Channel created!** You should now see `#nba-grading-alerts` in your channels list.

---

## Step 2: Create Incoming Webhook (5 minutes)

### Option A: Using Existing Slack App (If you have one)

**If you already have a Slack app for your workspace:**

1. Go to https://api.slack.com/apps
2. Click on your existing app (or click **"Create New App"** if you don't have one)
3. In the left sidebar, click **"Incoming Webhooks"**
4. Toggle **"Activate Incoming Webhooks"** to **On**
5. Scroll down and click **"Add New Webhook to Workspace"**
6. Select channel: **#nba-grading-alerts**
7. Click **"Allow"**
8. **Copy the Webhook URL** - it looks like:
   ```
   https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
   ```

### Option B: Create New Slack App (Recommended if starting fresh)

1. Go to https://api.slack.com/apps
2. Click **"Create New App"**
3. Select **"From scratch"**
4. Configure:
   - **App Name**: `NBA Props Grading Monitor`
   - **Pick a workspace**: Select your workspace
   - Click **"Create App"**
5. You'll be taken to the app's settings page
6. In the left sidebar under "Features", click **"Incoming Webhooks"**
7. Toggle **"Activate Incoming Webhooks"** to **On**
8. Scroll down and click **"Add New Webhook to Workspace"**
9. Select channel: **#nba-grading-alerts**
10. Click **"Allow"**
11. **Copy the Webhook URL** - it looks like:
    ```
    https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
    ```

**⚠️ Keep this URL secure!** It allows posting to your Slack channel.

---

## Step 3: Test the Webhook

Before deploying, test that it works:

```bash
# Replace with your actual webhook URL
WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Send test message
curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"✅ NBA Grading Alerts test - webhook is working!"}' \
    "$WEBHOOK_URL"
```

**Expected result**: You should see the test message appear in `#nba-grading-alerts`

---

## Step 4: Store Webhook in Google Secret Manager

```bash
# Set your webhook URL
WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Store it securely in Secret Manager
echo "$WEBHOOK_URL" | gcloud secrets create nba-grading-slack-webhook \
    --data-file=- \
    --replication-policy="automatic" \
    --project=nba-props-platform

# Verify it was stored
gcloud secrets describe nba-grading-slack-webhook --project=nba-props-platform
```

**✅ Webhook stored securely!**

---

## Step 5: Grant Cloud Function Access to Secret

```bash
# Get the default compute service account (used by Cloud Functions)
PROJECT_ID="nba-props-platform"
SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"

# Grant access to read the secret
gcloud secrets add-iam-policy-binding nba-grading-slack-webhook \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=$PROJECT_ID

echo "✅ Service account can now read the webhook URL"
```

---

## Webhook URL Format

Your webhook URL should look exactly like this:
```
https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
                                 ^          ^          ^
                                 |          |          |
                          Workspace ID   Channel ID   Secret Token
```

**Example** (fake):
```
https://hooks.slack.com/services/YOUR_WORKSPACE/YOUR_CHANNEL/YOUR_TOKEN
```

---

## Alert Message Examples

Once deployed, you'll receive alerts like these:

### 🚨 Critical: Grading Failure
```
🚨 NBA Grading Alert: No grades generated for 2026-01-17

Date: 2026-01-17
Grades: 0

Action Required: Check scheduled query execution history
```

### ⚠️ Warning: Accuracy Drop
```
⚠️ NBA Grading Alert: Accuracy drop detected

Systems below 55% threshold:
• ensemble_v1: 52.3% (min: 48.1%)
• zone_matchup_v1: 53.8% (min: 50.2%)

Period: Last 7 days
Count: 2 system(s)
```

### ⚠️ Warning: Data Quality Issue
```
⚠️ NBA Grading Alert: High ungradeable rate

Date: 2026-01-17
Issue Rate: 23.5%

Details: 47 of 200 predictions have issues
```

### ℹ️ Info: Daily Summary (Optional)
```
🏀 NBA Grading Daily Summary - Jan 17, 2026

✅ Grading Status: Complete
• Total predictions: 245
• Graded: 245 (100%)
• Issues: 12 (4.9%)

📊 System Performance:
• moving_average: 67.2% accuracy
• ensemble_v1: 64.1% accuracy
• similarity_balanced_v1: 61.8% accuracy
• zone_matchup_v1: 58.3% accuracy

Best performing: moving_average
Avg margin of error: 5.8 points
```

---

## Customizing Alerts

### Alert Thresholds

Edit these in the Cloud Function environment variables:

```bash
ALERT_THRESHOLD_ACCURACY_MIN=55      # Alert if accuracy drops below 55%
ALERT_THRESHOLD_UNGRADEABLE_MAX=20   # Alert if >20% ungradeable
ALERT_THRESHOLD_DAYS=7                # Check accuracy over last 7 days
```

### Alert Schedule

Default: **12:30 PM PT daily** (30 minutes after grading query runs at noon)

To change:
```bash
# Update Cloud Scheduler cron expression
# Current: "30 20 * * *" = 12:30 PM PT (20:30 UTC)
# Example: "0 21 * * *" = 1:00 PM PT (21:00 UTC)

gcloud scheduler jobs update http nba-grading-alerts-daily \
    --schedule="0 21 * * *" \
    --location=us-west2 \
    --project=nba-props-platform
```

### Alert Recipients

To notify specific people:
1. Invite them to `#nba-grading-alerts` channel
2. Or create user group: `@nba-grading-team`
3. Mention in alerts: Add `<!subteam^S01234ABCDE>` to message

---

## Troubleshooting

### Webhook URL not working
- **Check format**: Must start with `https://hooks.slack.com/services/`
- **Re-generate**: Delete old webhook, create new one
- **Test with curl**: See Step 3 above

### Not seeing alerts in Slack
- **Check Cloud Function logs**:
  ```bash
  gcloud functions logs read nba-grading-alerts --region=us-west2 --limit=50
  ```
- **Verify webhook stored**:
  ```bash
  gcloud secrets versions access latest --secret=nba-grading-slack-webhook
  ```
- **Check scheduler ran**:
  ```bash
  gcloud scheduler jobs describe nba-grading-alerts-daily --location=us-west2
  ```

### Too many alerts / Alert fatigue
- **Increase thresholds**: Raise accuracy_min from 55% to 50%
- **Reduce frequency**: Change from daily to weekly
- **Disable specific alert types**: Comment out in main.py

---

## Next Steps

Once webhook is set up:

1. ✅ Webhook URL obtained
2. ✅ Stored in Secret Manager
3. ✅ Permissions granted
4. 🔄 **Next**: Deploy alerting service (see QUICK-START-ENHANCEMENTS.md)

---

**Ready?** Provide your webhook URL and we'll deploy the alerting service!
