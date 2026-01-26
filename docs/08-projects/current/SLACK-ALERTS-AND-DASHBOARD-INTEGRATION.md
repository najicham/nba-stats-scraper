# Slack Alerts & Dashboard Integration for Source-Block Tracking

**Date:** 2026-01-26
**Status:** ✅ Complete - Ready to Deploy
**Integration:** Flask Admin Dashboard + Cloud Functions

---

## Overview

Added two production-ready components to source-block tracking system:

1. **Slack Alerts** via Cloud Function (every 6 hours)
2. **Admin Dashboard Integration** via Flask blueprint

These integrate seamlessly with your existing infrastructure:
- ✅ Reuses existing Slack webhook pattern (same as other cloud functions)
- ✅ Follows Flask blueprint architecture (matches status, grading, analytics blueprints)
- ✅ Uses BigQuery for data (same as other dashboards)
- ✅ Prometheus metrics compatible
- ✅ API key authentication + rate limiting

---

## Why Your Stack > Looker

### Your Current Infrastructure

**Admin Dashboard:**
- Flask 2.3.3 with 9 specialized blueprints
- HTMX for dynamic updates, Alpine.js for interactivity
- BigQuery integration with smart caching
- Prometheus metrics built-in
- API key auth + rate limiting
- Already deployed to Cloud Run

**Monitoring:**
- 12+ Cloud Functions for specialized alerts
- Slack webhooks for notifications
- BigQuery `monitoring` dataset
- Grafana dashboards
- Daily scorecards

**Why This Works Better Than Looker:**

| Feature | Your Stack | Looker |
|---------|-----------|--------|
| **Cost** | Included (existing infra) | Expensive licensing |
| **Flexibility** | Full control (Python/SQL) | Limited customization |
| **Integration** | Native (same codebase) | External tool |
| **Real-time** | HTMX partial updates | Page refresh |
| **Actions** | Built-in (resolve button) | View-only |
| **Maintenance** | One stack | Extra tool to maintain |
| **Auth** | Existing API key system | Separate auth |

**Recommendation:** ✅ Use your Flask dashboard + Cloud Functions (what I implemented)

---

## Component 1: Slack Alerts

### What It Does

Cloud Function that monitors source blocks and sends Slack alerts for:

1. **New Blocks** (last 6 hours)
   - Resource ID, type, source, HTTP status
   - Game date, notes
   - Limited to 5 most recent

2. **Persistent Blocks** (>24 hours)
   - Hours blocked
   - Verification count
   - Top 3 oldest

3. **Blocking Patterns**
   - Multiple blocks from same source/date
   - Identifies systemic issues
   - Shows blocked resource counts

### Files Created

```
cloud_functions/source_block_alert/
├── main.py              # Cloud Function code (380 lines)
├── requirements.txt     # Dependencies (BigQuery, requests)
├── deploy.sh           # Deployment script with scheduler
└── README.md           # Documentation
```

### Deployment

```bash
cd cloud_functions/source_block_alert

# Set Slack webhook (get from: https://api.slack.com/apps)
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Deploy (creates function + scheduler)
chmod +x deploy.sh
./deploy.sh
```

**Result:**
- Function deployed to `us-west2`
- Runs every 6 hours: **00:00, 06:00, 12:00, 18:00 ET**
- Sends rich Slack notifications
- ~120 invocations/month, <$0.01/month cost

### Alert Example

```
⚠️ Source Block Alert

🆕 New Source Blocks (2):

Resource: 0022500651
Type: play_by_play
Source: cdn_nba_com
HTTP: 403
Game Date: 2026-01-25
Notes: DEN @ MEM - Blocked by NBA.com CDN

---

📊 Blocking Patterns (1):

Source: cdn_nba_com
Date: 2026-01-25
Count: 2 blocked
Resources: 0022500651, 0022500652

Next Steps:
• Check admin dashboard for details
• Verify if data available from alternative sources
• Mark as resolved if blocks clear
```

### Manual Testing

```bash
# Trigger manually
curl -X POST https://us-west2-nba-props-platform.cloudfunctions.net/source-block-alert

# View logs
gcloud functions logs read source-block-alert --region=us-west2 --limit=10
```

---

## Component 2: Dashboard Integration

### What It Does

New Flask blueprint adds source-block monitoring page with:

**Summary Cards:**
- Active blocks count
- Resolved count (7 days)
- Coverage % (accounting for blocks)
- Alt sources available count

**Active Blocks Table:**
- Filterable by days (7/14/30), source, type
- Shows: resource ID, type, source, HTTP status, game date, hours blocked
- Status badges (active/resolved/alt available)
- **Resolve button** for each block

**Patterns Analysis:**
- Sources with multiple blocks
- Resolution rates
- Identifies systemic issues

**Coverage Analysis:**
- Daily breakdown: total vs blocked vs collected
- Shows "100% of available" vs "75% of total"
- 7-day trend

### Files Created

```
services/admin_dashboard/
├── blueprints/
│   └── source_blocks.py           # Flask blueprint (350 lines)
├── templates/
│   └── source_blocks.html         # Dashboard UI (600 lines)
└── INTEGRATION.md                 # Integration guide
```

### Integration Steps

**1. Register Blueprint** (`services/admin_dashboard/app.py`):

```python
from blueprints.source_blocks import source_blocks_bp

# Add with other blueprints
app.register_blueprint(source_blocks_bp)
```

**2. Add Navigation Link** (your main template):

```html
<a href="/source-blocks">🚫 Source Blocks</a>
```

**3. Deploy:**

```bash
cd services/admin_dashboard
./deploy.sh  # Or ./run_local.sh for testing
```

### API Endpoints Added

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/source-blocks` | GET | Dashboard page (UI) |
| `/api/source-blocks` | GET | List blocks (JSON) |
| `/api/source-blocks/patterns` | GET | Patterns analysis |
| `/api/source-blocks/coverage` | GET | Coverage data |
| `/api/source-blocks/resolve` | POST | Mark block resolved |

### API Examples

```bash
# Get active blocks
curl "http://localhost:8080/api/source-blocks?days=7" \
    -H "X-API-Key: YOUR_KEY"

# Get patterns
curl "http://localhost:8080/api/source-blocks/patterns?days=30" \
    -H "X-API-Key: YOUR_KEY"

# Resolve a block
curl -X POST "http://localhost:8080/api/source-blocks/resolve" \
    -H "X-API-Key: YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "resource_id": "0022500651",
        "resolution_notes": "Data now available",
        "available_from_alt_source": true,
        "alt_source_system": "bdb"
    }'
```

### Security Features

- ✅ API key required (`@require_api_key`)
- ✅ Rate limiting (100 req/min)
- ✅ Audit logging (all actions logged)
- ✅ Parameterized queries (SQL injection safe)
- ✅ CORS headers
- ✅ Input validation

---

## Architecture Fit

### Integration Points

```
┌─────────────────────────────────────────────────────────┐
│                    Admin Dashboard                      │
│  (Flask + 9 Blueprints + New Source Blocks Blueprint)  │
│                                                         │
│  Blueprints:                                           │
│  • status.py      - Pipeline status                    │
│  • grading.py     - Grading metrics                    │
│  • analytics.py   - Coverage/ROI                       │
│  • trends.py      - Trend analysis                     │
│  • latency.py     - Latency metrics                    │
│  • costs.py       - Scraper costs                      │
│  • reliability.py - Reconciliation                     │
│  • audit.py       - Audit logs                         │
│  ➕ source_blocks.py - Source block tracking (NEW)     │
└─────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│                      BigQuery                           │
│                                                         │
│  Datasets:                                             │
│  • nba_raw - Raw scraped data                          │
│  • nba_analytics - Processed analytics                 │
│  • nba_orchestration - Execution tracking              │
│    └── source_blocked_resources (NEW TABLE)            │
│  • nba_predictions - ML predictions                    │
│  • monitoring - Health metrics                         │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│              Cloud Functions (Alerts)                   │
│                                                         │
│  Existing:                                             │
│  • daily_health_summary - Daily Slack summaries        │
│  • phase4_failure_alert - Phase 4 failures             │
│  • game_coverage_alert - Coverage issues               │
│  • scraper_availability_monitor - Scraper health       │
│  • [...10 more alerting functions...]                  │
│                                                         │
│  ➕ source_block_alert - Source block alerts (NEW)     │
│     Schedule: Every 6 hours                            │
│     Output: Slack notifications                        │
└─────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│                        Slack                            │
│  - Rich formatted alerts                               │
│  - #alerts channel (or your configured channel)        │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Scraper** hits 403/404/410 → Auto-records to `source_blocked_resources`
2. **Cloud Function** runs every 6 hours → Queries table → Sends Slack alerts
3. **Dashboard** loads data → Shows active blocks → User can resolve
4. **Resolution** updates BigQuery → Audit logged → Slack notified (optional)

---

## Testing

### Local Testing

**Dashboard:**
```bash
cd services/admin_dashboard
export ADMIN_DASHBOARD_API_KEY="test-key"
./run_local.sh

# Open: http://localhost:8080/source-blocks
```

**Cloud Function:**
```bash
cd cloud_functions/source_block_alert
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
python main.py
```

### Test Data

Insert test blocks to see alerts:

```sql
INSERT INTO `nba-props-platform.nba_orchestration.source_blocked_resources`
(resource_id, resource_type, source_system, http_status_code, game_date,
 first_detected_at, last_verified_at, is_resolved, notes)
VALUES
-- New block (triggers "new blocks" alert)
('TEST_001', 'play_by_play', 'cdn_nba_com', 403, CURRENT_DATE(),
 CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), FALSE, 'Test block'),

-- Persistent block (triggers "persistent" alert)
('TEST_002', 'play_by_play', 'cdn_nba_com', 404, CURRENT_DATE(),
 TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 HOUR), CURRENT_TIMESTAMP(),
 FALSE, 'Old test block'),

-- Pattern (2+ blocks from same source/date)
('TEST_003', 'play_by_play', 'cdn_nba_com', 403, CURRENT_DATE(),
 CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), FALSE, 'Pattern test');
```

Then trigger function or wait for next scheduled run.

---

## Production Checklist

- [ ] **Get Slack Webhook URL** from https://api.slack.com/apps
- [ ] **Deploy Cloud Function** (`./deploy.sh`)
- [ ] **Verify scheduler created** (`gcloud scheduler jobs list`)
- [ ] **Test alert manually** (curl function URL)
- [ ] **Register dashboard blueprint** in `app.py`
- [ ] **Add nav link** to main dashboard
- [ ] **Deploy dashboard** (`./deploy.sh`)
- [ ] **Test dashboard locally** first
- [ ] **Verify API key works**
- [ ] **Check Prometheus metrics** (`/metrics`)
- [ ] **Train team** on resolving blocks

---

## Monitoring

### Verify Alerts Working

```bash
# Check function logs
gcloud functions logs read source-block-alert --region=us-west2 --limit=20

# Check scheduler
gcloud scheduler jobs describe source-block-alert-scheduler --location=us-west2

# Trigger manually
curl -X POST https://us-west2-nba-props-platform.cloudfunctions.net/source-block-alert
```

### Dashboard Health

- Check `/health` endpoint
- View Prometheus metrics: `/metrics`
- Check BigQuery query logs
- Monitor API response times

---

## Cost

**Cloud Function:**
- Invocations: 120/month (4/day × 30)
- Duration: ~5s each
- Memory: 256MB
- **Cost: <$0.01/month** (within free tier)

**Dashboard:**
- Already deployed
- Minimal extra load (1-2 queries/page)
- **Cost: $0** (no change)

**BigQuery:**
- source_blocked_resources table: <1MB
- Queries: ~10/day
- **Cost: <$0.01/month** (within free tier)

**Total: <$0.05/month** 💰

---

## Customization

### Change Alert Frequency

Edit `deploy.sh`:

```bash
--schedule="0 */6 * * *"  # Every 6 hours (current)
--schedule="0 */3 * * *"  # Every 3 hours
--schedule="0 0 * * *"    # Daily at midnight
```

### Change Alert Thresholds

Edit `main.py`:

```python
# New blocks window
WHERE first_detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 12 HOUR)

# Persistent blocks threshold
WHERE first_detected_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)

# Pattern threshold
HAVING COUNT(*) >= 3  # Change from 2 to 3
```

### Add More Filters

Edit `templates/source_blocks.html`:

```javascript
filters: {
    days: 7,
    source: '',
    type: '',
    http_status: ''  // NEW filter
}
```

---

## Troubleshooting

### No Slack alerts

1. Check `SLACK_WEBHOOK_URL` set correctly
2. Verify function deployed: `gcloud functions list`
3. Check scheduler running: `gcloud scheduler jobs list`
4. View logs: `gcloud functions logs read source-block-alert`
5. Test manually: `curl -X POST [function-url]`

### Dashboard not loading

1. Verify blueprint registered in `app.py`
2. Check BigQuery table exists: `bq show nba_orchestration.source_blocked_resources`
3. Verify API key in request
4. Check logs: View Cloud Run logs
5. Test locally first

### 401 Unauthorized

Include API key:
```bash
curl -H "X-API-Key: YOUR_KEY" http://localhost:8080/api/source-blocks
```

---

## Documentation

- **Cloud Function**: `cloud_functions/source_block_alert/README.md`
- **Dashboard Integration**: `services/admin_dashboard/INTEGRATION.md`
- **Technical Design**: `docs/08-projects/current/2026-01-25-incident-remediation/SOURCE-BLOCK-TRACKING-DESIGN.md`
- **User Guide**: `docs/guides/source-block-tracking.md`
- **Session Summary**: `docs/08-projects/current/SESSION-SUMMARY-2026-01-26.md`

---

## Summary

✅ **Slack Alerts**: Production-ready Cloud Function with scheduler
✅ **Dashboard**: Flask blueprint matching your architecture
✅ **Integration**: Seamless fit with existing infrastructure
✅ **Cost**: <$0.05/month (basically free)
✅ **Security**: API key auth, rate limiting, audit logging
✅ **Testing**: Local test scripts, test data provided
✅ **Documentation**: Complete guides for deployment and usage

**Better than Looker because:**
- No licensing costs
- Native integration with your Flask app
- Full customization control
- Real-time actions (resolve button)
- Same auth/security model
- One less tool to maintain

**Ready to deploy!** 🚀
