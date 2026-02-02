# Daily Subset Picks Notifications

**Session 83 (2026-02-02)**: Automated Slack + Email notifications for daily subset picks

## Quick Start

### 1. Test the Notification (Safe - doesn't send)

```bash
PYTHONPATH=. python bin/notifications/send_daily_picks.py --test
```

### 2. Send Manually (Requires credentials)

```bash
# Send both Slack + Email
PYTHONPATH=. python bin/notifications/send_daily_picks.py

# Slack only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --slack-only

# Email only
PYTHONPATH=. python bin/notifications/send_daily_picks.py --email-only

# Different subset
PYTHONPATH=. python bin/notifications/send_daily_picks.py --subset v9_high_edge_top1

# Specific date
PYTHONPATH=. python bin/notifications/send_daily_picks.py --date 2026-02-01
```

### 3. Setup Automated Daily Delivery

```bash
# Setup Cloud Scheduler (8:30 AM ET daily)
./bin/notifications/setup_daily_picks_scheduler.sh
```

## What It Sends

### Slack (#nba-betting-signals)

```
🏀 Today's Top Picks - 2026-02-02

🔴 RED SIGNAL (2.5% OVER)
⚠️ Reduce bet sizing or skip today

V9 Top 5:
1. Trey Murphy III - UNDER 22.5 pts
   Edge: 11.4 | Conf: 84%
2. Jaren Jackson Jr - UNDER 20.5 pts
   Edge: 6.7 | Conf: 89%
...

Historical Performance:
• 75.9% hit rate (22 days)
• 63/83 wins

View all subsets: /subset-picks
```

### Email (HTML formatted)

Professional HTML email with:
- Signal status and warning (RED/YELLOW/GREEN)
- Top 10 picks in formatted table
- Historical performance stats
- Mobile-friendly design

## Configuration

### Required Environment Variables

**Slack** (already configured):
- `SLACK_WEBHOOK_URL_SIGNALS` - #nba-betting-signals webhook

**Email** (Brevo SMTP):
- `BREVO_SMTP_USERNAME` - Brevo username
- `BREVO_SMTP_PASSWORD` - Brevo password
- `BREVO_FROM_EMAIL` - Sender email
- `EMAIL_ALERTS_TO` - Comma-separated recipient emails

**BigQuery**:
- `GCP_PROJECT_ID` - nba-props-platform (default)

## Schedule

**When**: 8:30 AM ET daily
**Why**: Predictions run at 7:00 AM, complete by 8:00 AM

## Available Subsets

| Subset ID | Description | Typical Count |
|-----------|-------------|---------------|
| `v9_high_edge_top1` | Best Pick | 1 |
| `v9_high_edge_top3` | Top 3 | 3 |
| `v9_high_edge_top5` | Top 5 (default) | 5 |
| `v9_high_edge_top10` | Top 10 | 10 |
| `v9_high_edge_balanced` | GREEN signal only | varies |

## Monitoring

```bash
# View scheduler logs
gcloud logging read 'resource.type="cloud_scheduler_job"
  resource.labels.job_id="daily-subset-picks-notification"' --limit=10

# Check notification success
gcloud logging read 'jsonPayload.message=~"notification sent"' --limit=5

# Manual trigger (for testing)
gcloud scheduler jobs run daily-subset-picks-notification --location=us-west2
```

## Troubleshooting

### Email not sending

Check credentials:
```bash
echo $BREVO_SMTP_USERNAME
echo $EMAIL_ALERTS_TO
```

Test email config:
```python
from shared.utils.email_alerting import EmailAlerter
alerter = EmailAlerter()
alerter.test_email_configuration()
```

### Slack not sending

Check webhook:
```bash
echo $SLACK_WEBHOOK_URL_SIGNALS
```

Test Slack:
```python
from shared.utils.slack_channels import send_to_slack
import os
send_to_slack(os.environ.get('SLACK_WEBHOOK_URL_SIGNALS'), 'Test message')
```

### No picks found

Check predictions exist:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

## Files

- `shared/notifications/subset_picks_notifier.py` - Core notification logic
- `bin/notifications/send_daily_picks.py` - CLI script
- `bin/notifications/setup_daily_picks_scheduler.sh` - Scheduler setup

## Future Enhancements

- [ ] SMS via Twilio integration
- [ ] Multiple subset support (send top 1, 3, 5 in one message)
- [ ] Performance dashboard link
- [ ] Personalized subsets per user
- [ ] Push notifications via mobile app
- [ ] Discord integration
- [ ] Telegram bot

## Examples

### Send to Different Slack Channel

```python
from shared.notifications.subset_picks_notifier import SubsetPicksNotifier

notifier = SubsetPicksNotifier()
# Override webhook
notifier.slack_webhook = 'https://hooks.slack.com/services/YOUR/WEBHOOK/HERE'
notifier.send_daily_notifications()
```

### Custom Email Recipients

```python
from shared.notifications.subset_picks_notifier import SubsetPicksNotifier

notifier = SubsetPicksNotifier()
# Override recipients
notifier.email_alerter.alert_recipients = ['user@example.com', 'user2@example.com']
notifier.send_daily_notifications()
```

### Multiple Subsets

```python
from shared.notifications.subset_picks_notifier import send_daily_picks

# Send top 1 (lock of the day)
send_daily_picks('v9_high_edge_top1')

# Send top 5 (default)
send_daily_picks('v9_high_edge_top5')

# Send only on GREEN days
send_daily_picks('v9_high_edge_balanced')
```
