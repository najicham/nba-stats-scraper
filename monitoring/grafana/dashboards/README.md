# Grafana Dashboards for Entity-Level Processing

**Created:** 2025-11-19 11:40 PM PST
**Last Updated:** 2025-11-19 11:40 PM PST
**Location:** `monitoring/grafana/dashboards/`

---

## Available Dashboards

### 1. Phase 1 Basic Dashboard
**File:** `01-phase1-basic.json`

**Status:** ✅ **Works Now** (with existing schema)

**Panels:**
- Success Rate (24h)
- Average Duration (24h)
- Duration Over Time (7d)
- Recent Executions (24h)

**Requirements:**
- Existing `nba_processing.analytics_processor_runs` table
- No schema changes needed

**Use when:**
- Before Week 1 implementation
- Basic monitoring only
- Testing dashboard setup

---

### 2. Week 1+ Full Dashboard ⭐
**File:** `02-week1-full.json`

**Status:** ⚠️ **Requires Week 1 Schema Migration**

**Panels:**
- Avg Waste % (24h) - Gauge
- Wasted Hours (7d) - Gauge
- Success Rate (24h) - Gauge
- Avg Duration (24h) - Gauge
- Waste % Over Time (7d) - Time series
- Skip Reasons (Today) - Pie chart
- Duration Distribution (7d) - Bar chart
- **THE DECISION QUERY (7d)** - Table ⭐ Most Important
- Recent Executions (24h) - Table

**Requirements:**
- ✅ Week 1 schema migration deployed
- ✅ New fields added: `entities_processed`, `entities_changed`, `waste_pct`, `skip_reason`
- ✅ Change detection implemented in analytics_base.py

**Use when:**
- After Week 1 implementation complete
- Ready for Week 8 decision
- Full monitoring needed

---

## Installation Instructions

### Step 1: Configure BigQuery Data Source

1. **In Grafana:** Go to **Configuration → Data Sources**

2. **Add BigQuery:**
   - Name: `BigQuery-NBA-Props`
   - Type: Google BigQuery
   - Project: `nba-props-platform`
   - Default Dataset: `nba_processing`

3. **Authentication:**
   - Upload service account JSON key
   - Required permissions:
     - `bigquery.jobs.create`
     - `bigquery.tables.get`
     - `bigquery.tables.getData`

### Step 2: Import Dashboard

**Option A: Via UI**
```
Grafana → Dashboards → Import → Upload JSON file
Select: 01-phase1-basic.json (or 02-week1-full.json)
Choose: BigQuery-NBA-Props data source
Click: Import
```

**Option B: Via API**
```bash
# Phase 1 Basic
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @01-phase1-basic.json \
  https://your-grafana-instance.com/api/dashboards/db

# Week 1 Full (after migration)
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @02-week1-full.json \
  https://your-grafana-instance.com/api/dashboards/db
```

**Option C: Via Terraform**
```hcl
resource "grafana_dashboard" "nba_entity_processing" {
  config_json = file("${path.module}/02-week1-full.json")
}
```

### Step 3: Configure Variables

Both dashboards include these variables (auto-configured):

- **$project_id** - GCP project (default: `nba-props-platform`)
- **$processor** - Multi-select processor filter (auto-populated from data)

No manual configuration needed!

---

## Dashboard Comparison

| Feature | Phase 1 Basic | Week 1 Full |
|---------|---------------|-------------|
| **Success Rate** | ✅ | ✅ |
| **Duration Metrics** | ✅ | ✅ |
| **Waste Metrics** | ❌ | ✅ |
| **Skip Reasons** | ❌ | ✅ |
| **THE DECISION QUERY** | ❌ | ✅ |
| **Entity Tracking** | ❌ | ✅ |
| **Panels** | 4 | 9 |
| **Works Now** | ✅ | ⚠️ Needs Week 1 |

---

## Upgrade Path

### Current State (Before Week 1)
1. Install **Phase 1 Basic Dashboard**
2. Monitor success rate and duration
3. Get familiar with Grafana setup

### After Week 1 Migration
1. Deploy Week 1 schema changes
2. Install **Week 1 Full Dashboard**
3. Start collecting waste metrics
4. Use THE DECISION QUERY for Week 8 decision

### After Week 8 Decision
- Continue using Week 1 Full Dashboard
- If Phase 3 implemented: Dashboard works unchanged (shows entity-level metrics)

---

## Customization

### Change Project ID

Edit JSON before import:
```json
{
  "templating": {
    "list": [
      {
        "name": "project_id",
        "current": {
          "text": "your-project-id",  // ← Change this
          "value": "your-project-id"
        }
      }
    ]
  }
}
```

### Change Refresh Rate

Default: 1 minute

Change in JSON:
```json
{
  "refresh": "5m"  // Change to 30s, 1m, 5m, etc.
}
```

Or in Grafana UI: Dashboard settings → Auto refresh

### Add Custom Panels

See panel examples in dashboard JSON. Copy structure and change:
- `targets[0].rawSql` - Your BigQuery query
- `title` - Panel title
- `type` - gauge, timeseries, table, piechart, barchart
- `gridPos` - Position on grid

---

## Troubleshooting

### Dashboard Shows "No Data"

**Check table exists:**
```bash
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) FROM nba_processing.analytics_processor_runs'
```

**If 0 results:** No data in table yet
- Run a processor to generate data
- Check that processors are logging to this table

**If error:** Check table name and project ID match

---

### "Column not found" Error

**Symptom:** Panels show error like `Column 'waste_pct' not found`

**Cause:** Using Week 1 Full Dashboard before schema migration

**Solution:**
1. Use Phase 1 Basic Dashboard instead, or
2. Deploy Week 1 schema changes first (see `docs/architecture/10-week1-schema-and-code-changes.md`)

---

### Queries Timeout

**Cause:** Large dataset, no clustering

**Solution:** Add table clustering
```sql
ALTER TABLE nba_processing.analytics_processor_runs
CLUSTER BY processor_name, DATE(run_date);
```

**Or:** Reduce time range from 7d to 1d temporarily

---

### Wrong Data Source UID

**Symptom:** "Data source not found"

**Solution:**
1. Go to Configuration → Data Sources
2. Find your BigQuery data source
3. Copy the UID from URL
4. Edit dashboard JSON: Replace `"uid": "bigquery-nba-props"` with your UID

---

## Monitoring Queries Reference

All queries are documented in:
- [Visual Diagrams](../../docs/diagrams/01-entity-level-processing.md) - Diagram #3 (Metrics Dashboard)
- [Week 8 Decision Guide](../../docs/reference/04-week8-decision-guide.md) - THE DECISION QUERY

---

## Dashboard Screenshots

### Phase 1 Basic Dashboard
```
┌─────────────────────────────────────────────────────────┐
│  Success Rate: 98.5%    │  Avg Duration: 25.3s          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Duration Over Time (7d) - Line Chart                   │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  Recent Executions (24h) - Table                        │
│  Time | Processor | Date | Status | Duration           │
└─────────────────────────────────────────────────────────┘
```

### Week 1 Full Dashboard
```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│ Waste: 42.3% │ Wasted: 3.2h │Success: 98.5%│Duration: 25s │
├──────────────────────────────┬───────────────┬─────────────┤
│                              │               │             │
│  Waste Over Time (7d)        │ Skip Reasons  │ Duration    │
│  Line Chart                  │ Pie Chart     │ Bar Chart   │
│                              │               │             │
├──────────────────────────────────────────────────────────┤
│ THE DECISION QUERY ⭐                                     │
│ Processor | Waste% | Hours | ROI | Recommendation       │
├──────────────────────────────────────────────────────────┤
│ Recent Executions - Full Details                        │
└──────────────────────────────────────────────────────────┘
```

---

## Alert Configuration (Optional)

### Recommended Alerts

**Alert on High Waste:**
```
Panel: Avg Waste % (24h)
Condition: When value is above 30 for 1 hour
Notification: #nba-props-monitoring
```

**Alert on Low Success Rate:**
```
Panel: Success Rate (24h)
Condition: When value is below 95 for 15 minutes
Notification: #nba-props-critical
```

**Alert on Circuit Breaker:**
```
Annotation: Circuit Breaker Opens
Notification: Immediate Slack/PagerDuty
```

### Setup in Grafana

1. Edit panel → Alert tab
2. Create alert rule
3. Configure:
   - Condition
   - Evaluation interval
   - Notification channel
4. Save

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-19 | Initial dashboards created |
| | | Phase 1 Basic (4 panels) |
| | | Week 1 Full (9 panels) |

---

## References

- [Phase 2→3 Roadmap](../../docs/architecture/09-phase2-phase3-implementation-roadmap.md) - Overall plan
- [Week 1 Implementation](../../docs/architecture/10-week1-schema-and-code-changes.md) - Schema changes
- [Week 8 Decision Guide](../../docs/reference/04-week8-decision-guide.md) - How to use THE DECISION QUERY
- [Visual Diagrams](../../docs/diagrams/01-entity-level-processing.md) - Dashboard layout and queries

---

## Support

**Issues with dashboards?**
- Check this README's Troubleshooting section
- Verify schema matches (Phase 1 vs Week 1)
- Test queries directly in BigQuery first

**Need custom panels?**
- See Customization section above
- Copy existing panel structure
- Modify query and settings

**Dashboard improvements?**
- Submit PR with updated JSON
- Document changes in version history
- Update screenshots if layout changes
