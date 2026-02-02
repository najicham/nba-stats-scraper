# Complete Setup Guide: Slack + Email + SMS

**Session 83 (2026-02-02)**: Get daily NBA picks delivered via Slack, Email, and SMS

---

## 🚀 Quick Setup (15 minutes total)

### Step 1: Slack (5 minutes) ✅ Already Configured

**Status**: Channel exists, webhook should be configured in Cloud Run

**Test it:**
```bash
# Check if webhook is set
echo $SLACK_WEBHOOK_URL_SIGNALS

# If empty, get it from Cloud Run
gcloud run services describe nba-scrapers --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep SLACK_WEBHOOK_URL_SIGNALS

# Send test notification
PYTHONPATH=. python bin/notifications/send_daily_picks.py --slack-only --test
```

**What you'll receive:**
```
🏀 Today's Top Picks - 2026-02-02

🔴 RED SIGNAL (2.5% OVER)
⚠️ Reduce bet sizing or skip today

V9 Top 5:
1. Trey Murphy III - UNDER 22.5 pts
   Edge: 11.4 | Conf: 84%
...
```

---

### Step 2: Email (10 minutes) 📧 Requires Brevo Account

**Sign up for Brevo (free tier):**
1. Go to https://www.brevo.com/
2. Sign up (free tier: 300 emails/day)
3. Go to Settings → SMTP & API
4. Create SMTP credentials

**Get your credentials:**
- SMTP Username: `your-email@example.com`
- SMTP Password: (generated)
- From Email: `your-email@example.com`

**Set environment variables:**

```bash
# In your local environment
export BREVO_SMTP_USERNAME="your-email@example.com"
export BREVO_SMTP_PASSWORD="xsmtpsib-XXXXXXXXXXXXXXXX"
export BREVO_FROM_EMAIL="your-email@example.com"
export EMAIL_ALERTS_TO="your-personal-email@gmail.com"

# For Cloud Scheduler (production)
gcloud scheduler jobs update http daily-subset-picks-notification \
  --location=us-west2 \
  --update-env-vars="BREVO_SMTP_USERNAME=your-email@example.com,BREVO_SMTP_PASSWORD=xsmtpsib-XXX,BREVO_FROM_EMAIL=your-email@example.com,EMAIL_ALERTS_TO=your-personal-email@gmail.com"
```

**Test it:**
```bash
PYTHONPATH=. python bin/notifications/send_daily_picks.py --email-only
```

**Pro tip**: Forward email to SMS gateway:
- AT&T: `5555551234@txt.att.net`
- Verizon: `5555551234@vtext.com`
- T-Mobile: `5555551234@tmomail.net`

---

### Step 3: SMS via Twilio (Tonight - 15 minutes) 📱

**Sign up for Twilio:**
1. Go to https://www.twilio.com/try-twilio
2. Sign up (free trial: $15 credit + 1 phone number)
3. Verify your phone number
4. Get a Twilio phone number

**Get your credentials:**
1. Go to Console → Account Info
2. Copy:
   - Account SID: `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
   - Auth Token: `your_auth_token`
   - Your Twilio Phone: `+1555123XXXX`

**Install Twilio SDK:**
```bash
pip install twilio

# Or add to requirements.txt
echo "twilio>=8.0.0" >> requirements.txt
```

**Set environment variables:**

```bash
# Test locally first
export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_AUTH_TOKEN="your_auth_token"
export TWILIO_FROM_PHONE="+15551234567"  # Your Twilio number
export SMS_TO_PHONE="+15559876543"       # Your personal phone

# Test SMS
python shared/utils/sms_notifier.py --test
```

**Expected SMS:**
```
🏀 NBA Props - Test SMS
From: +15551234567
To: +15559876543
If you received this, SMS is working!
```

**Send test picks:**
```bash
PYTHONPATH=. python bin/notifications/send_daily_picks.py --sms-only
```

**Expected picks SMS:**
```
NBA 🔴RED (2.5%)
1.T.Murphy U22.5 E:11.4 2.J.Jackson U20.5 E:6.7 3.K.Oubre U14.5 E:6.2
HR:75.9%
/subset-picks
```

**For Cloud Scheduler (production):**
```bash
# Add SMS env vars to scheduler job
gcloud scheduler jobs update http daily-subset-picks-notification \
  --location=us-west2 \
  --update-env-vars="TWILIO_ACCOUNT_SID=ACxxx,TWILIO_AUTH_TOKEN=xxx,TWILIO_FROM_PHONE=+15551234567,SMS_TO_PHONE=+15559876543"
```

---

## 📋 Testing All Three Channels

### Test individually:
```bash
# Slack only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --slack-only

# Email only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --email-only

# SMS only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --sms-only
```

### Test all together:
```bash
# Send to all configured channels
PYTHONPATH=. python bin/notifications/send_daily_picks.py
```

### Dry run (safe test):
```bash
# See what would be sent without actually sending
PYTHONPATH=. python bin/notifications/send_daily_picks.py --test
```

---

## ⏰ Automate Daily Delivery

Once all channels are working, set up automated delivery:

```bash
# Setup Cloud Scheduler (8:30 AM ET daily)
./bin/notifications/setup_daily_picks_scheduler.sh

# Manual trigger to test
gcloud scheduler jobs run daily-subset-picks-notification --location=us-west2

# View logs
gcloud logging read 'resource.type="cloud_scheduler_job"
  resource.labels.job_id="daily-subset-picks-notification"' --limit=10
```

---

## 🔍 Troubleshooting

### Slack not working

```bash
# Check webhook
echo $SLACK_WEBHOOK_URL_SIGNALS

# If empty, check Cloud Run
gcloud run services describe nba-scrapers --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep SLACK

# Test with curl
curl -X POST $SLACK_WEBHOOK_URL_SIGNALS \
  -H 'Content-Type: application/json' \
  -d '{"text": "Test from command line"}'
```

### Email not working

```bash
# Check credentials
echo $BREVO_SMTP_USERNAME
echo $BREVO_FROM_EMAIL
echo $EMAIL_ALERTS_TO

# Test email config
python -c "
from shared.utils.email_alerting import EmailAlerter
alerter = EmailAlerter()
alerter.test_email_configuration()
"
```

### SMS not working

```bash
# Check Twilio credentials
echo $TWILIO_ACCOUNT_SID
echo $TWILIO_FROM_PHONE
echo $SMS_TO_PHONE

# Test SMS
python shared/utils/sms_notifier.py --test

# Check Twilio console for errors
# https://console.twilio.com/us1/monitor/logs/sms
```

### No picks found

```bash
# Check if predictions exist for today
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'"
```

---

## 💰 Cost Breakdown

| Channel | Setup | Monthly Cost |
|---------|-------|--------------|
| **Slack** | Free | $0 |
| **Email** (Brevo free tier) | Free | $0 (up to 300/day) |
| **SMS** (Twilio) | $15 credit free | ~$3/year ($0.01/text) |

**Total yearly cost**: ~$3 (just SMS)

---

## 📱 What You'll Receive

### Daily (8:30 AM ET):

**Phone (Slack app)**: Push notification with top 5 picks
**Email inbox**: Professional HTML digest with top 10 picks
**Text message**: Concise top 3 picks (if SMS configured)

### Example Timeline:

```
7:00 AM ET → Predictions run
8:00 AM ET → Predictions complete
8:30 AM ET → Notifications sent
8:31 AM ET → Wake up to picks on your phone!
```

---

## 🎯 Customization Options

### Different subset:
```bash
# Best pick only (lock of the day)
PYTHONPATH=. python bin/notifications/send_daily_picks.py --subset v9_high_edge_top1

# Top 10 (more volume)
PYTHONPATH=. python bin/notifications/send_daily_picks.py --subset v9_high_edge_top10

# GREEN days only (historical 81% HR)
PYTHONPATH=. python bin/notifications/send_daily_picks.py --subset v9_high_edge_balanced
```

### Multiple phone numbers:
```bash
# Comma-separated in env var
export SMS_TO_PHONE="+15559876543,+15551234567"
```

### Different times:
```bash
# Update scheduler to 7:30 AM ET
gcloud scheduler jobs update http daily-subset-picks-notification \
  --location=us-west2 \
  --schedule="30 12 * * *"  # 7:30 AM ET = 12:30 PM UTC
```

---

## ✅ Quick Checklist

**Tonight (15 min):**
- [ ] Sign up for Twilio
- [ ] Get Twilio phone number
- [ ] Set TWILIO_* env vars
- [ ] Run: `python shared/utils/sms_notifier.py --test`
- [ ] Run: `PYTHONPATH=. python bin/notifications/send_daily_picks.py --sms-only`

**Tomorrow (5 min):**
- [ ] Sign up for Brevo
- [ ] Get SMTP credentials
- [ ] Set BREVO_* env vars
- [ ] Run: `PYTHONPATH=. python bin/notifications/send_daily_picks.py --email-only`

**Final (5 min):**
- [ ] Test all three: `PYTHONPATH=. python bin/notifications/send_daily_picks.py`
- [ ] Setup automation: `./bin/notifications/setup_daily_picks_scheduler.sh`
- [ ] Done! 🎉

---

## 📞 Support

If something's not working:
1. Check logs: `gcloud logging read ...`
2. Test individually (--slack-only, --email-only, --sms-only)
3. Verify env vars are set
4. Check service credentials (Brevo/Twilio dashboards)

## 🎊 You're All Set!

You'll now receive daily NBA picks via:
- 📱 Slack push notifications
- 📧 Email digest
- 💬 Text messages

Every morning at 8:30 AM ET, automatically!
