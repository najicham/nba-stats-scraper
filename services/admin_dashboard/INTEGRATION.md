# Source Blocks Dashboard Integration

## Quick Start

Add source blocks monitoring to your admin dashboard in 3 steps:

### 1. Register Blueprint

In `services/admin_dashboard/app.py`, add:

```python
from blueprints.source_blocks import source_blocks_bp

# Register blueprint
app.register_blueprint(source_blocks_bp)
```

### 2. Add Navigation Link

In your main dashboard template (e.g., `templates/dashboard.html` or navbar), add:

```html
<a href="/source-blocks">🚫 Source Blocks</a>
```

### 3. Restart Dashboard

```bash
cd services/admin_dashboard
./run_local.sh  # For local testing

# OR for production
./deploy.sh
```

## Endpoints Added

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/source-blocks` | GET | Dashboard page |
| `/api/source-blocks` | GET | List active blocks |
| `/api/source-blocks/patterns` | GET | Blocking patterns |
| `/api/source-blocks/coverage` | GET | Coverage with blocks |
| `/api/source-blocks/resolve` | POST | Resolve a block |

## API Examples

### Get Active Blocks

```bash
curl "http://localhost:8080/api/source-blocks?days=7" \
    -H "X-API-Key: YOUR_API_KEY"
```

Response:
```json
{
  "success": true,
  "blocks": [
    {
      "resource_id": "0022500651",
      "resource_type": "play_by_play",
      "source_system": "cdn_nba_com",
      "http_status_code": 403,
      "game_date": "2026-01-25",
      "hours_blocked": 48,
      "is_resolved": false
    }
  ],
  "total": 1
}
```

### Get Blocking Patterns

```bash
curl "http://localhost:8080/api/source-blocks/patterns?days=30" \
    -H "X-API-Key: YOUR_API_KEY"
```

### Resolve Block

```bash
curl -X POST "http://localhost:8080/api/source-blocks/resolve" \
    -H "X-API-Key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "resource_id": "0022500651",
      "resolution_notes": "Data now available from alternative source",
      "available_from_alt_source": true,
      "alt_source_system": "bdb"
    }'
```

## Dashboard Features

### Main View

- **Summary Cards**: Active blocks, resolved count, coverage %, alt sources
- **Active Blocks Table**: Filterable by days, source, type
- **Actions**: Resolve button for each active block

### Patterns Analysis

- Shows sources/resources with multiple blocks
- Resolution rate tracking
- Identifies systemic issues

### Coverage Analysis

- Daily breakdown: total games vs blocked vs collected
- Coverage % accounting for source blocks
- Shows "100% of available" vs "75% of total"

## Customization

### Change Alert Thresholds

Edit `blueprints/source_blocks.py`:

```python
# Show blocks older than X hours
WHERE first_detected_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)

# Pattern threshold (2+ blocks = pattern)
HAVING COUNT(*) >= 3  -- Change to 3 for stricter patterns
```

### Add More Filters

Add source systems to `templates/source_blocks.html`:

```html
<select x-model="filters.source">
    <option value="">All Sources</option>
    <option value="cdn_nba_com">NBA.com CDN</option>
    <option value="bdb">BigDataBall</option>
    <option value="nba_stats_api">NBA Stats API</option>  <!-- NEW -->
</select>
```

### Styling

Dashboard uses your existing styles (dark theme). Colors:
- `#ef4444` - Active/error (red)
- `#10b981` - Resolved/success (green)
- `#f59e0b` - Warning (yellow)
- `#3b82f6` - Info (blue)

## Security

- ✅ Requires API key (`@require_api_key` decorator)
- ✅ Rate limited (100 req/min default)
- ✅ Audit logged (all resolve actions tracked)
- ✅ Parameterized queries (SQL injection protection)

## Testing

### Local Development

```bash
cd services/admin_dashboard
export ADMIN_DASHBOARD_API_KEY="test-key-123"
./run_local.sh
```

Open: http://localhost:8080/source-blocks

### Test Data

Insert test blocks:

```sql
INSERT INTO `nba-props-platform.nba_orchestration.source_blocked_resources`
(resource_id, resource_type, source_system, http_status_code, game_date,
 first_detected_at, last_verified_at, is_resolved, notes)
VALUES
('TEST_001', 'play_by_play', 'cdn_nba_com', 403, CURRENT_DATE(),
 CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), FALSE, 'Test block'),
('TEST_002', 'play_by_play', 'cdn_nba_com', 404, CURRENT_DATE(),
 TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 HOUR), CURRENT_TIMESTAMP(),
 FALSE, 'Persistent test block');
```

## Troubleshooting

### Blueprint not registered

Error: `werkzeug.routing.BuildError: Could not build url for endpoint 'source_blocks.get_source_blocks'`

Fix: Add blueprint registration to `app.py`:
```python
from blueprints.source_blocks import source_blocks_bp
app.register_blueprint(source_blocks_bp)
```

### BigQuery errors

Error: `Table not found: source_blocked_resources`

Fix: Create table using:
```bash
bq query < sql/create_source_blocked_resources.sql
```

### API key required

Error: `401 Unauthorized`

Fix: Include API key in request:
```bash
curl -H "X-API-Key: YOUR_KEY" http://localhost:8080/api/source-blocks
```

## Next Steps

1. **Deploy Cloud Function** for Slack alerts: `cloud_functions/source_block_alert/`
2. **Add to main nav** for easy access
3. **Set up monitoring** queries to run daily
4. **Train team** on resolving blocks

## Support

See full documentation:
- Technical design: `docs/08-projects/current/2026-01-25-incident-remediation/SOURCE-BLOCK-TRACKING-DESIGN.md`
- User guide: `docs/guides/source-block-tracking.md`
- Session summary: `docs/08-projects/current/SESSION-SUMMARY-2026-01-26.md`
