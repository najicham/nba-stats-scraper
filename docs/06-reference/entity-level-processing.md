# 01 - NBA Props Platform: Entity-Level Processing - Implementation Guide

**Created:** 2025-11-19 10:24 PM PST
**Last Updated:** 2025-11-19 10:41 PM PST

> **📌 NOTE:** This is reference material from research and planning.
> **For the actual implementation plan**, see [Phase 2→3 Implementation Roadmap](../architecture/09-phase2-phase3-implementation-roadmap.md).
>
> This document represents proposed patterns and approaches. Our actual implementation adapts these concepts to fit our existing `analytics_base.py` architecture.

**Version:** 3.0 - Streamlined (Reference)
**Purpose:** Reference material for entity-level processing patterns

---

## Quick Start (Read This First)

### Your Challenge

When LeBron gets ruled OUT at 2 PM, you don't want to reprocess all 450 players. When a single spread changes, you don't want to regenerate predictions for all 14 games.

### The Solution (Three Phases)

**Phase 1 (Week 1-2): Smart Detection + Monitoring**
- Date-level processing (simple, works)
- Built-in change detection (prevents 80% waste)
- Comprehensive monitoring (measures everything)
- Expected: 80% efficiency gain, 10 hours effort

**Phase 2 (Week 3-7): Measure & Decide**
- Run THE DECISION QUERY weekly
- Metrics accumulate automatically
- Clear go/no-go for Phase 3
- Expected: Data-driven decision, 30 min/week

**Phase 3 (Week 8+, Conditional): Entity-Level Optimization**
- Process only changed entities
- 10-60x faster for incremental updates
- Expected: Additional 10-15% gain, 15 hours effort

### Key Philosophy

✅ Phase 1 is NOT wasteful - has change detection, idempotency, logging
✅ Monitoring works for ALL phases - same schema, same queries
✅ Clear decision criteria - waste >30% AND >2 hrs/week → optimize
✅ Backward compatible - can run Phase 1 and Phase 3 simultaneously

### Time Investment Summary

| Phase | Time | ROI | When |
|-------|------|-----|------|
| Phase 1 | 10 hours | 80% efficiency gain | Week 1-2 |
| Phase 2 | 30 min/week | Clear decision | Week 3-7 |
| Phase 3 | 15 hours | Additional 10-15% | Week 8+ (if justified) |

---

## Getting Started in 5 Minutes

### 1. Copy Base Processor (2 minutes)

```python
# File: shared/processors/processor_base.py
# See complete implementation: docs/reference/processor_base_complete.py

from datetime import datetime, timedelta
import uuid, logging

class AnalyticsProcessorBase:
    """
    Three-layer protection:
    1. Idempotency: Skip if processed recently
    2. Change Detection: Skip if no data changed
    3. Logging: Enable data-driven decisions
    """

    IDEMPOTENCY_WINDOW = timedelta(hours=1)

    def run(self, opts):
        game_date = opts['game_date']
        self.started_at = datetime.utcnow()

        try:
            # Layer 1: Skip if recent
            if self._skip_due_to_recent_run(game_date):
                self._log_execution('skipped', skip_reason='recent_run')
                return True

            # Layer 2: Skip if no changes
            change_info = self._detect_changes(game_date)
            if change_info is None:
                self._log_execution('skipped', skip_reason='no_changes')
                return True

            # Layer 3: Check dependencies
            if not self.check_dependencies(game_date)['all_critical_present']:
                self._log_execution('skipped', skip_reason='dependencies')
                return True

            # PROCESS (only if all checks pass)
            result = self._process_data(game_date, change_info)

            # Track metrics for Phase 2 decision
            self.entities_in_scope = change_info['entities_in_scope']
            self.entities_processed = result['records_processed']
            self.entities_changed = change_info['entities_changed']

            self._log_execution('completed')
            return True

        except Exception as e:
            self._log_execution('failed', error=e)
            raise
```

👉 See complete implementation: `docs/reference/processor_base_complete.py`

### 2. Create Monitoring Schema (2 minutes)

```sql
-- Run this once to set up monitoring
CREATE TABLE IF NOT EXISTS `nba_orchestration.pipeline_execution_log` (
    execution_id STRING NOT NULL,
    processor_name STRING NOT NULL,
    game_date DATE NOT NULL,
    processing_mode STRING NOT NULL,   -- 'date_level' or 'entity_level'

    -- CRITICAL METRICS (for decision-making)
    entities_in_scope INT64,           -- Total entities for date
    entities_processed INT64,          -- How many we processed
    entities_changed INT64,            -- How many ACTUALLY changed ← KEY!

    -- Calculated waste (automatic)
    waste_pct FLOAT64 AS (
        CASE WHEN entities_processed > 0
        THEN ((entities_processed - entities_changed) / entities_processed * 100)
        ELSE 0 END
    ) STORED,

    -- Performance
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds FLOAT64,
    status STRING NOT NULL,
    skip_reason STRING
)
PARTITION BY game_date
CLUSTER BY processor_name, processing_mode, started_at;
```

### 3. Deploy & Verify (1 minute)

```bash
# Deploy
gcloud builds submit --config cloudbuild-processors.yaml

# Trigger test
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message '{"game_date": "2025-11-18"}'

# Check logs
bq query --use_legacy_sql=false '
SELECT processor_name, status, entities_changed, waste_pct
FROM nba_orchestration.pipeline_execution_log
WHERE DATE(started_at) = CURRENT_DATE()
ORDER BY started_at DESC LIMIT 5'
```

✅ You're now in Phase 1 with smart detection and monitoring!

---

## THE DECISION QUERY (Most Important Section!)

This single query tells you everything you need to know about Phase 3.

**Run this every Monday at 9 AM starting Week 3:**

```sql
-- THE ONE QUERY THAT ANSWERS EVERYTHING
WITH processor_metrics AS (
    SELECT
        processor_name,
        processing_mode,

        -- Volume
        COUNT(*) as total_runs,

        -- Waste (KEY!)
        ROUND(AVG(waste_pct), 1) as avg_waste_pct,
        ROUND(SUM(duration_seconds * waste_pct / 100) / 3600, 2) as wasted_hours,

        -- Performance
        ROUND(AVG(duration_seconds), 1) as avg_duration_sec

    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date >= CURRENT_DATE() - 7
      AND status = 'completed'
      AND entities_changed > 0
    GROUP BY processor_name, processing_mode
)
SELECT
    processor_name,
    total_runs,
    avg_waste_pct,
    wasted_hours,

    -- ROI calculation
    ROUND(15.0 / NULLIF(wasted_hours, 0), 1) as weeks_to_roi,

    -- AUTOMATED DECISION
    CASE
        WHEN avg_waste_pct > 30
         AND wasted_hours > 2
         AND total_runs > 10
         AND (15.0 / NULLIF(wasted_hours, 0)) < 8
        THEN '🔴 IMPLEMENT PHASE 3 NOW'

        WHEN avg_waste_pct > 20 AND wasted_hours > 1
        THEN '🟡 MONITOR CLOSELY'

        ELSE '🟢 PHASE 1 SUFFICIENT'
    END as recommendation

FROM processor_metrics
ORDER BY wasted_hours DESC;
```

### Example Output (Week 4)

| processor_name | avg_waste | wasted_hrs | weeks_roi | recommendation |
|---------------|-----------|------------|-----------|----------------|
| PlayerGameSummaryProcessor | 42.3 | 3.2 | 4.7 | 🔴 IMPLEMENT PHASE 3 NOW |
| TeamDefenseGameSummaryProcessor | 28.1 | 1.8 | 8.3 | 🟡 MONITOR CLOSELY |
| UpcomingPlayerGameContextProcessor | 15.2 | 0.4 | 37.5 | 🟢 PHASE 1 SUFFICIENT |

### Decision Flowchart

```
Run Decision Query (Week 3+)
         ↓
Check ALL 4 conditions:
  ✓ avg_waste_pct > 30%?
  ✓ wasted_hours > 2/week?
  ✓ total_runs > 10/week?
  ✓ weeks_to_roi < 8?
         ↓
    ┌────┴────┐
    NO       YES
    ↓         ↓
Continue   Implement Phase 3
Phase 1    for that processor
    ↓         ↓
Check      Monitor 1 week
again in       ↓
4 weeks    Validate improvement
              ↓
          Repeat for next
```

### What to Watch For

**🔴 Implement Phase 3 Now:**
- Waste is high (>30%)
- Time adds up (>2 hrs/week)
- ROI is attractive (<8 weeks)
- All conditions must be TRUE

**🟡 Monitor Closely:**
- Trending toward Phase 3 territory
- Review weekly
- May need optimization soon

**🟢 Phase 1 Sufficient:**
- Low waste (<20%)
- Good efficiency
- Continue monitoring monthly

---

## Phase 1: Implementation Details

### Step 1: Create Monitoring Schema (30 minutes)

Already shown in "Getting Started" section above. Also create:

```sql
-- Last run tracking (for idempotency)
CREATE TABLE IF NOT EXISTS `nba_orchestration.processor_last_run` (
    processor_name STRING NOT NULL,
    game_date DATE NOT NULL,
    last_completed_at TIMESTAMP NOT NULL,
    last_execution_id STRING NOT NULL
)
PARTITION BY game_date
CLUSTER BY processor_name, game_date;
```

### Step 2: Implement Base Processor (3-4 hours)

The streamlined version shown above has the key concepts. For complete implementation with all helper methods:

👉 See: `docs/reference/processor_base_complete.py`

**Key methods you need to implement:**
- `_detect_changes()` - Counts what changed since last run
- `_count_total_entities()` - Total possible entities for date
- `_count_changed_entities()` - Entities with recent updates
- `_log_execution()` - Writes to monitoring table
- `transform_data()` - Your business logic (override in subclass)
- `load_to_bigquery()` - Your loading logic (override in subclass)

### Step 3: Add Essential Patterns (2-3 hours)

Choose 2-3 optimization patterns to enhance Phase 1:

**Recommended for Week 1:**

1. **Smart Skip Patterns (30 min)**
   - Filter irrelevant sources
   - 30% reduction in invocations
   - Example: PlayerGameSummary skips spread changes

2. **Dependency Precheck (30 min)**
   - Quick COUNT(*) before heavy processing
   - 250x faster failure (0.1s vs 20s)
   - Fail fast on missing data

3. **Early Exit Conditions (30 min)**
   - Skip if no games scheduled
   - 30-40% savings on off-days
   - Check eliminated teams in playoffs

👉 See full pattern catalog: `docs/reference/optimization-pattern-catalog.md`

### Step 4: Deploy & Verify (1-2 hours)

```bash
# Deploy processors
gcloud builds submit --config cloudbuild-processors.yaml

# Test with multiple scenarios
for date in 2025-11-15 2025-11-16 2025-11-17; do
    gcloud pubsub topics publish nba-phase2-raw-complete \
      --message "{\"game_date\": \"$date\"}"
done

# Verify metrics
bq query --use_legacy_sql=false '
SELECT
    processor_name,
    DATE(started_at) as date,
    COUNT(*) as runs,
    COUNTIF(status = "completed") as completed,
    COUNTIF(status = "skipped") as skipped,
    ROUND(AVG(waste_pct), 1) as avg_waste,
    ROUND(AVG(duration_seconds), 1) as avg_duration
FROM nba_orchestration.pipeline_execution_log
WHERE DATE(started_at) >= CURRENT_DATE() - 3
GROUP BY processor_name, date
ORDER BY date DESC, processor_name'
```

### Step 5: Set Up Monitoring (2-3 hours)

Create Grafana dashboard with these panels:

**Panel 1: Waste Over Time**
```sql
SELECT
    DATE(started_at) as date,
    processor_name,
    AVG(waste_pct) as waste
FROM nba_orchestration.pipeline_execution_log
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'completed'
GROUP BY date, processor_name
ORDER BY date
```

**Panel 2: Skip Reasons**
```sql
SELECT
    skip_reason,
    COUNT(*) as count
FROM nba_orchestration.pipeline_execution_log
WHERE DATE(started_at) = CURRENT_DATE()
  AND status = 'skipped'
GROUP BY skip_reason
```

**Panel 3: Processing Duration**
```sql
SELECT
    processor_name,
    duration_seconds
FROM nba_orchestration.pipeline_execution_log
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND status = 'completed'
```

---

## Phase 2: Measure & Decide (Week 3-7)

### Weekly Activity (30 minutes)

Every Monday at 9 AM:

1. Run THE DECISION QUERY (shown above)
2. Check recommendations
3. Log results to tracking spreadsheet:

| Week | Processor | Waste% | Hours | Recommendation | Action |
|------|-----------|--------|-------|----------------|--------|
| 3 | PlayerGameSummary | 38.2 | 2.8 | 🔴 PHASE 3 | Monitor 1 more week |
| 4 | PlayerGameSummary | 42.3 | 3.2 | 🔴 PHASE 3 | Start implementation |
| 4 | TeamDefenseGameSummary | 28.1 | 1.8 | 🟡 MONITOR | Continue watching |

If 🔴 appears for 2 consecutive weeks → Start Phase 3 for that processor

### Automated Weekly Report (Optional)

```python
# bin/monitoring/weekly_optimization_report.py

def send_weekly_report():
    """Run decision query and send Slack alert."""
    results = run_decision_query()

    optimize_now = results[results['recommendation'] == '🔴 IMPLEMENT PHASE 3 NOW']

    if not optimize_now.empty:
        send_slack_alert(
            channel='#nba-props-weekly',
            title='📊 Optimization Recommendation',
            message=f"""
            {len(optimize_now)} processors ready for Phase 3:

            {optimize_now[['processor_name', 'avg_waste_pct', 'wasted_hours']].to_markdown()}

            Potential savings: {optimize_now['wasted_hours'].sum():.2f} hours/week
            Estimated ROI: {15 / optimize_now['wasted_hours'].sum():.1f} weeks
            """
        )

# Schedule: Cloud Scheduler, Monday 9 AM
```

---

## Phase 3: Entity-Level Optimization (Week 8+, Conditional)

### When to Implement

ALL of these must be true:

✅ avg_waste_pct > 30%
✅ wasted_hours > 2/week
✅ total_runs > 10/week
✅ weeks_to_roi < 8

If even one is FALSE → Stay on Phase 1, check again in 4 weeks

### High-Level Approach

Phase 3 changes from date-level to entity-level processing:

**Phase 1 (Date-Level):**
```python
# Process ALL entities for date
query = f"""
SELECT * FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '{game_date}'
"""
data = bq_client.query(query).to_dataframe()
process_all(data)  # 450 players
```

**Phase 3 (Entity-Level):**
```python
# Process ONLY changed entities
if 'player_ids' in opts:
    player_list = "','".join(opts['player_ids'])
    query = f"""
    SELECT * FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date = '{game_date}'
      AND universal_player_id IN ('{player_list}')
    """
    data = bq_client.query(query).to_dataframe()
    process_changed(data)  # 3 players (99% faster)
```

### Implementation Changes Required

1. **Phase 2 Enhancement** - Add entity tracking to Pub/Sub messages
2. **Processor Enhancement** - Add entity filtering capability
3. **Gradual Rollout** - Enable one processor at a time

👉 See detailed implementation: `docs/architecture/phase3-implementation-details.md` (create when needed)

### Expected Improvements

| Scenario | Entities Changed | Phase 1 Time | Phase 3 Time | Speedup |
|----------|------------------|--------------|--------------|---------|
| Small update | 3 players | 30s | 0.5s | 60x |
| Medium update | 50 players | 30s | 5s | 6x |
| Large update | 450 players | 30s | 30s | 1x |

Additional waste reduction: 10-15% (bringing total to 85-95% efficiency)

---

## Validation & Testing

### Test 1: Idempotency

```python
def test_idempotency():
    """Verify duplicate runs are skipped."""
    processor = PlayerGameSummaryProcessor()

    # Run 1
    result1 = processor.run({'game_date': '2025-11-01'})
    assert result1 == True

    # Run 2 (within 1 hour)
    result2 = processor.run({'game_date': '2025-11-01'})

    # Check skip
    logs = get_execution_logs('2025-11-01')
    assert logs.iloc[1]['skip_reason'] == 'recent_run'
```

### Test 2: Change Detection

```python
def test_change_detection():
    """Verify changes are detected correctly."""
    processor = PlayerGameSummaryProcessor()

    # Initial run
    processor.run({'game_date': '2025-11-01'})

    # No changes
    result = processor.run({'game_date': '2025-11-01'})
    logs = get_execution_logs('2025-11-01')
    assert logs.iloc[1]['skip_reason'] == 'no_changes'

    # Update data
    update_player_stat('player_001', '2025-11-01')

    # Detect change
    result = processor.run({'game_date': '2025-11-01'})
    logs = get_execution_logs('2025-11-01')
    assert logs.iloc[2]['entities_changed'] == 1
```

### Test 3: Metrics Accuracy

```python
def test_metrics_calculation():
    """Verify waste metrics are accurate."""
    processor = PlayerGameSummaryProcessor()

    # Scenario: 3 changed out of 450
    result = processor.run({'game_date': '2025-11-01'})

    logs = get_execution_logs('2025-11-01')
    assert logs.iloc[0]['entities_in_scope'] == 450
    assert logs.iloc[0]['entities_processed'] == 450
    assert logs.iloc[0]['entities_changed'] == 3
    assert logs.iloc[0]['waste_pct'] == pytest.approx(99.3, 0.1)
```

---

## FAQ

**Q: What if Phase 1 metrics show we don't need Phase 3?**
A: Perfect! That's the point. You've gained 80% efficiency with minimal complexity. Continue monitoring monthly.

**Q: Can we implement Phase 3 for some processors but not others?**
A: Yes! Implement based on individual processor metrics. Some may need it, others may not.

**Q: What if we want to add more optimization patterns?**
A: See the Pattern Catalog for 15+ additional patterns. Add incrementally based on observed pain points.

**Q: How do we handle backfills with this system?**
A: Backfills always use date-level processing (not entity-level) to ensure completeness. The system automatically handles this via processing_mode flag.

**Q: What if waste percentage is high but hours are low?**
A: Don't implement Phase 3. The ROI isn't there. High waste% with low hours means the processor is already fast.

**Q: Can we go directly to Phase 3?**
A: Not recommended. You need Phase 1 metrics to know WHERE to optimize. Phase 1 also gives you 80% of the value.

---

## Summary

### Phase 1 (Week 1-2)
✅ Ship smart detection with monitoring
✅ 80% efficiency gain
✅ Full visibility into patterns
✅ Production ready
⏱️ 10 hours

### Phase 2 (Week 3-7)
✅ Run decision query weekly
✅ Track metrics automatically
✅ Clear go/no-go at Week 8
✅ No guesswork
⏱️ 30 min/week

### Phase 3 (Week 8+ if triggered)
✅ Entity-level processing
✅ Additional 10-15% efficiency
✅ Validated improvement
✅ Gradual rollout
⏱️ 15 hours

**Total time to decision:** 2 weeks
**Total time if optimizing:** 4 weeks
**Expected efficiency:** 85-95%

---

## Next Steps

✅ Copy base processor to your codebase
✅ Create monitoring schema
✅ Add 2-3 essential patterns from Pattern Catalog
✅ Deploy and verify
✅ Run decision query starting Week 3
✅ Decide Phase 3 at Week 8 based on data

**You're ready to ship!** 🚀

---

## Reference Documents

- **Complete Base Processor:** `docs/reference/processor_base_complete.py`
- **Pattern Catalog:** `docs/reference/optimization-pattern-catalog.md`
- **Advanced Patterns:** `docs/reference/optimization-pattern-catalog-advanced.md`
- **Actual Implementation Plan:** `docs/architecture/phase2-phase3-implementation-roadmap.md` ⭐

---

*This is reference material. For actual implementation adapted to our architecture, see the roadmap.*
