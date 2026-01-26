# Source Block Alert Cloud Function

Monitors `source_blocked_resources` table and sends Slack alerts when source blocks are detected.

## Features

- 🆕 **New Blocks**: Alerts on resources blocked in last 6 hours
- ⏰ **Persistent Blocks**: Alerts on blocks lasting >24 hours
- 📊 **Patterns**: Detects multiple blocks from same source/date
- 🔔 **Slack Integration**: Rich formatted alerts with block details

## Deployment

### Prerequisites

1. **Slack Webhook URL**: Create webhook in Slack workspace
   - Go to: https://api.slack.com/apps → Create New App → Incoming Webhooks
   - Copy webhook URL

2. **GCP Project**: Ensure `gcloud` configured for `nba-props-platform`

### Deploy

```bash
# Set Slack webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Deploy function
cd cloud_functions/source_block_alert
chmod +x deploy.sh
./deploy.sh
```

This will:
- Deploy Cloud Function to `us-west2`
- Create Cloud Scheduler job (runs every 6 hours: 0, 6, 12, 18:00 ET)
- Configure environment variables

### Schedule

Runs every 6 hours at: **00:00, 06:00, 12:00, 18:00 ET**

### Manual Trigger

```bash
# Get function URL
FUNCTION_URL="https://us-west2-nba-props-platform.cloudfunctions.net/source-block-alert"

# Trigger manually
curl -X POST $FUNCTION_URL
```

## Alert Types

### 1. New Blocks (6 hours)

```
🆕 New Source Blocks (2):

Resource: 0022500651
Type: play_by_play
Source: cdn_nba_com
HTTP: 403
Game Date: 2026-01-25
Notes: DEN @ MEM - Blocked by NBA.com CDN
```

### 2. Persistent Blocks (>24h)

```
⏰ Persistent Blocks >24h (1):

Resource: 0022500651
Hours Blocked: 48h
Source: cdn_nba_com
Verifications: 8
```

### 3. Blocking Patterns

```
📊 Blocking Patterns (1):

Source: cdn_nba_com
Date: 2026-01-25
Type: play_by_play
Count: 2 blocked
Resources: 0022500651, 0022500652
```

## Configuration

### Environment Variables

- `SLACK_WEBHOOK_URL` (required): Slack incoming webhook URL

### Modify Schedule

Edit schedule in `deploy.sh`:

```bash
--schedule="0 */6 * * *"  # Every 6 hours
--schedule="0 */3 * * *"  # Every 3 hours
--schedule="0 0 * * *"    # Daily at midnight
```

## Monitoring

### View Logs

```bash
gcloud functions logs read source-block-alert \
    --region=us-west2 \
    --limit=50
```

### Check Scheduler

```bash
gcloud scheduler jobs describe source-block-alert-scheduler \
    --location=us-west2
```

### Test Locally

```python
# Set environment variable
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Run locally
python main.py
```

## Integration with Dashboard

Source blocks are also visible in the admin dashboard:

```
https://admin-dashboard-url/source-blocks
```

Dashboard shows:
- Active blocks list
- Blocking patterns
- Coverage analysis
- Resolve actions

## Troubleshooting

### No alerts sent

Check:
1. `SLACK_WEBHOOK_URL` is set correctly
2. Function deployed successfully
3. BigQuery table `source_blocked_resources` exists
4. Blocks exist in table (query manually)

### Test alert

Add a test block to trigger alert:

```sql
INSERT INTO `nba-props-platform.nba_orchestration.source_blocked_resources`
(resource_id, resource_type, source_system, http_status_code, game_date, first_detected_at, is_resolved)
VALUES
('TEST_GAME_001', 'play_by_play', 'test_source', 403, CURRENT_DATE(), CURRENT_TIMESTAMP(), FALSE);
```

Then trigger function manually.

### Check function errors

```bash
gcloud functions logs read source-block-alert \
    --region=us-west2 \
    --limit=10 \
    --severity=ERROR
```

## Cost

- **Invocations**: 4/day × 30 days = 120/month
- **Duration**: ~5s/invocation
- **Memory**: 256MB
- **Estimated cost**: <$0.01/month (free tier)

## Maintenance

### Update function

1. Modify `main.py`
2. Run `./deploy.sh` (re-deploys)

### Delete function

```bash
gcloud functions delete source-block-alert --region=us-west2
gcloud scheduler jobs delete source-block-alert-scheduler --location=us-west2
```
