# NBA Props Platform - Source Coverage System
## Documentation Index

**Created:** 2025-11-26
**Version:** 2.0 (Consolidated Design)
**Status:** Production-Ready

---

## Quick Navigation

| Document | Purpose | When to Use |
|----------|---------|-------------|
| [**Part 1: Core Design**](01-core-design.md) | System overview, architecture, decisions | Understanding the "why" and "what" |
| [**Part 2: Schema Reference**](02-schema-reference.md) | Complete DDL, table schemas, indexes | Creating tables, understanding data model |
| [**Part 3: Implementation**](03-implementation-guide.md) | Python code, mixins, processors | Writing code, integrating with processors |
| [**Part 4: Testing & Operations**](04-testing-operations.md) | Tests, runbooks, troubleshooting | Testing, running, maintaining system |
| [Part 5: Review & Enhancements](05-review-enhancements.md) | Additional code from design review | Optional enhancements, reference |

---

## What This System Does

The **Source Coverage System** tracks data availability from external sources (NBA.com, ESPN, Odds API, etc.) and handles gaps gracefully through:

- **Automatic fallbacks** to backup sources
- **Data reconstruction** when possible
- **Quality scoring** that flows through pipeline
- **Silent failure detection** via daily audit
- **Smart alerting** (critical immediate, others digest)

> **⚠️ CRITICAL: Reprocessing Cascade**
>
> Quality propagates downstream (Phase 3 → 4 → 5). If you backfill upstream data,
> downstream quality becomes **stale**. Use `quality_calculated_at` to detect
> staleness. **Document your reprocessing procedure.**

### Key Benefits

- **Complete visibility** - Know what data you have from which sources
- **Graceful degradation** - Predictions continue with quality flags
- **Automated handling** - Fallback and reconstruction automatic
- **Production-ready** - Tested, documented, operational
- **Cost-effective** - ~$5-7/month additional cost

---

## Quick Start Guide

### Phase 1: Setup (Day 1-2)

**1. Create tables:**
```bash
# Run these SQL scripts in order:
cd schemas/bigquery/

# Create the source coverage log table and view
bq query --use_legacy_sql=false < nba_reference/source_coverage_log.sql

# Add quality columns to analytics tables
bq query --use_legacy_sql=false < analytics/source_coverage_quality_columns.sql
```

**2. Deploy constants:**
```bash
# Copy event type constants
cp shared_services/constants/source_coverage.py $YOUR_REPO/shared_services/constants/
```

**3. Deploy mixins:**
```bash
# Copy quality and fallback mixins
cp shared_services/processors/quality_mixin.py $YOUR_REPO/shared_services/processors/
cp shared_services/processors/fallback_source_mixin.py $YOUR_REPO/shared_services/processors/
```

### Phase 2: First Integration (Day 3-5)

**1. Update one processor:**
```python
# Example: player_game_summary.py
from shared_services.processors.quality_mixin import QualityMixin
from shared_services.processors.fallback_source_mixin import FallbackSourceMixin

class PlayerGameSummaryProcessor(
    FallbackSourceMixin,
    QualityMixin,
    BaseProcessor
):
    # Add configuration
    PRIMARY_SOURCES = ['nbac_gamebook_player_stats']
    FALLBACK_SOURCES = ['bdl_player_boxscores']
    REQUIRED_FIELDS = ['points', 'minutes_played']

    # Rest of your existing code...
```

**2. Test it:**
```bash
# Run tests
pytest tests/unit/test_quality_mixin.py
pytest tests/integration/test_source_coverage_flow.py

# Process one game
python run_processor.py --processor player_game_summary --game_id 0022400001
```

**3. Verify:**
```sql
-- Check quality columns populated
SELECT quality_tier, quality_score, quality_issues
FROM nba_analytics.player_game_summary
WHERE game_id = '0022400001';

-- Check event logged
SELECT * FROM nba_reference.source_coverage_log
WHERE game_id = '0022400001';
```

### Phase 3: Rollout (Week 2-3)

**1. Add to more processors:**
- Follow pattern from first integration
- Test each one independently
- Deploy gradually

**2. Deploy audit job:**
```bash
# Deploy coverage audit processor
cp phase_2_analytics/processors/source_coverage_audit.py $YOUR_REPO/phase_2_analytics/processors/

# Schedule daily run (9 AM PT)
gcloud scheduler jobs create http coverage-audit \
  --schedule="0 9 * * *" \
  --uri="https://your-service.run.app/audit" \
  --time-zone="America/Los_Angeles"
```

**3. Setup alerts:**
```bash
# Configure Slack webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK"

# Test alert
python -c "from shared_services.notifications import send_slack_alert; \
           send_slack_alert('#nba-data-quality', 'Test alert', 'info')"
```

---

## Architecture At-A-Glance

```
External Sources -> Scrapers -> Raw Tables (Phase 2)
                                    |
                                    +-- Event logged to source_coverage_log
                                    +-- Quality assessed by mixins
                                    v
                            Analytics Tables (Phase 3)
                                    | (quality columns added)
                                    v
                            Features (Phase 4)
                                    | (quality propagated)
                                    v
                            Predictions (Phase 5)
                                    | (confidence capped by quality)

Daily Audit Job -> Checks schedule vs actual -> Creates synthetic events for gaps
```

---

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **Event vs State** | Event log | Simpler, no state sync issues |
| **Quality Columns** | On every table | Performance over storage |
| **Fallback Location** | Phase 3 processors | Keep Phase 2 as source truth |
| **Audit Frequency** | Daily batch | Cost-effective, sufficient |
| **Alert Strategy** | Critical immediate, others digest | Reduce noise |

---

## Cost Summary

| Component | Monthly Cost | One-Time Cost |
|-----------|--------------|---------------|
| Storage (log table + columns) | $0.01 | - |
| Query costs (processing) | $2-3 | - |
| Alert queries | $1 | - |
| Audit job | $0.01 | - |
| Historical backfill | - | $5 |
| **Total (steady state)** | **$3-4 actual** | **$5** |

**Cost Estimates by Phase:**

| Phase | Monthly Cost | Notes |
|-------|--------------|-------|
| Steady state (after stabilization) | $5-7 | Normal operation |
| Active development/iteration | $15-25 | Frequent reprocessing, debugging queries |
| Playoff season | $10-15 | Higher game volume |

**Use $15-25/month for budgeting during initial rollout** - you'll iterate on quality thresholds and rebackfill multiple times.

---

## Common Workflows

### Workflow 1: Investigating a Quality Issue

```
1. Check game summary view:
   SELECT * FROM game_source_coverage_summary WHERE game_id = 'XXX';

2. Review events:
   SELECT * FROM source_coverage_log WHERE game_id = 'XXX' ORDER BY event_timestamp;

3. Check actual data:
   SELECT quality_tier, quality_score, quality_issues
   FROM player_game_summary WHERE game_id = 'XXX';

4. Decide action:
   - Can backfill? -> Manual data entry -> Reprocess
   - Accept gap? -> Mark resolved with 'accepted_gap'
   - Source issue? -> Check source status, wait for recovery
```

### Workflow 2: Responding to Critical Alert

```
1. Alert received: "Game X completely missing"

2. Check source status:
   - Is NBA.com up? curl https://stats.nba.com/...
   - Is it a known issue? Check status page

3. Try manual alternatives:
   - ESPN website
   - Basketball Reference
   - NBA.com game page

4. Document resolution:
   UPDATE source_coverage_log
   SET is_resolved = TRUE, resolution_method = '...'
   WHERE event_id = '...';
```

### Workflow 3: Adding New Table to Pipeline

```
1. Add quality columns:
   ALTER TABLE new_table
   ADD COLUMN quality_tier STRING, ...

2. Update processor to use mixins:
   class NewProcessor(FallbackSourceMixin, QualityMixin, ...):

3. Add to audit check list:
   AUDIT_CHECK_TABLES.append(('new_table', 'game_id'))

4. Test and deploy
```

---

## Key Metrics to Monitor

### Daily (Automated)

- **Average quality score** - Target: > 85
- **Bronze rate** - Target: < 10%
- **Unresolved critical count** - Target: 0
- **Audit-detected gaps** - Target: 0

### Weekly (Manual Review)

- **Source success rates** - Target: > 90% for all
- **Alert volume trends** - Watch for increases
- **Top quality issues** - Identify patterns

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Check | Solution |
|---------|--------------|-------|----------|
| High bronze rate | Thin samples or source issues | quality_issues array | Expected early season, or investigate sources |
| Many fallback events | Primary source unreliable | Source success rate query | Add retries or promote backup |
| Audit detecting gaps | Processor failures | Cloud Run logs | Fix processor error handling |
| Predictions blocked | Critical source gaps | Event log for game | Manual data entry or wait |

---

## Success Criteria

### After Week 1
- Source coverage log receiving events
- At least 1 processor using mixins
- Quality columns populating correctly

### After Week 2
- Fallback logic working automatically
- Quality propagating through Phase 3 -> 4
- 3+ processors integrated

### After Week 3
- Alerts configured and working
- Daily digest emails sent
- Audit job deployed

### After Week 4
- Historical backfill complete
- All processors integrated
- Team trained on runbooks
- System fully operational

---

## Support & Maintenance

### Documentation Updates

When you add new features:
1. Update Part 1 (design decisions)
2. Add to Part 2 (schemas if changed)
3. Provide Part 3 (code examples)
4. Update Part 4 (tests and procedures)

### Getting Help

- **Schema questions** -> Part 2
- **Implementation questions** -> Part 3
- **Operational questions** -> Part 4
- **"Why" questions** -> Part 1

---

## Adaptation Notes for This Codebase

### Existing Infrastructure to Use

| Component | Location | Use Instead Of |
|-----------|----------|----------------|
| Notification system | `shared/utils/notification_system.py` | Custom alert functions |
| `notify_error()` | Already exists | New alert system |
| `notify_warning()` | Already exists | New alert system |
| `notify_info()` | Already exists | New alert system |
| `quality_issues` | `analytics_base.py:86` | Already on base class |
| `source_metadata` | `analytics_base.py:83` | Already on base class |
| BigQuery batch loading | `bigquery-best-practices.md` | Streaming inserts |

### Key Adaptations Required

1. **Remove BigQuery `CREATE INDEX` statements** - BigQuery uses partitioning/clustering, not indexes
2. **Use existing notification system** - Don't create new alert functions
3. **Extend existing base classes** - `AnalyticsProcessorBase` already has quality tracking
4. **Streaming buffer migration first** - Fix `insert_rows_json` -> `load_table_from_json` before implementing

---

## Future Enhancements (Deferred)

The following enhancements were identified during review but deferred for v1. Add as needed based on operational experience.

### Priority 1: Add If Pain Points Emerge

| Enhancement | Trigger to Implement |
|-------------|---------------------|
| **Alert backoff for extended outages** | If you get alert fatigue during 2+ day outages (4hr window = alerts every 4hr) |
| **Reconstruction confidence levels** | If perfect reconstruction (10/10 players) unfairly penalized as silver |
| **Historical quality upgrade path** | If you need to "promote" silver → gold after verification |
| **Automatic reprocessing orchestration** | If manual reprocess triggers become burdensome |

### Priority 2: Add for Production Maturity

| Enhancement | When to Add |
|-------------|-------------|
| **API/frontend quality display guidance** | When building prediction publishing layer (Phase 6) |
| **Performance benchmarks** | After 2-4 weeks of production data |
| **Configurable confidence ceilings** | If different prediction algorithms need different thresholds |
| **Quality version tracking** | If you need to track quality recalculations over time |

### Priority 3: Nice-to-Have

| Enhancement | Notes |
|-------------|-------|
| Centralized source priority YAML config | Currently hardcoded, YAML adds flexibility |
| Batch_id on all events consistently | For better alert grouping |
| Auto-resolve for recovered sources | Part 5 has pattern, promote if useful |

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-26 | 2.0 | Complete redesign: event-based, mixin integration, audit job |
| 2025-11-26 | 2.1 | Added adaptation notes for existing infrastructure |
| 2025-11-26 | 2.2 | Review feedback: event buffering, alert dedup, timezone fix, Phase 4/5 examples |
| 2025-11-26 | 2.3 | Added reprocessing workflow, context manager auto-flush, future enhancements |
| 2025-11-26 | 2.4 | Fixed alert buffer deduplication bug (check buffer before DB) |

---

*Index complete. Navigate to any part using links above.*
