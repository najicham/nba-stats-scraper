# 09 - Phase 2→3 Implementation Roadmap

**Version:** 1.0
**Created:** 2025-11-19 10:19 PM PST
**Last Updated:** 2025-11-19 10:41 PM PST
**Status:** Planning
**Owner:** NBA Props Platform Team

## Executive Summary

This document outlines our plan to add entity-level processing optimization to the NBA Props Platform, focusing on **data-driven decision making** rather than premature optimization.

**Key Principle:** Ship simple monitoring first, measure for 4-6 weeks, then decide if optimization is justified based on actual waste metrics.

---

## Current State (As of 2025-11-19 10:41 PM PST)

### ✅ What We Have

**Phase 1→2 (Complete)**
- Scrapers → Raw Processors via Pub/Sub: **100% working**
- pubsub_publishers.py: Publishes table-level events
- Raw processors: DELETE+INSERT pattern for date ranges

**Phase 3 Analytics (Complete)**
- analytics_base.py: Sophisticated base class with:
  - Dependency Tracking v4.0 (staleness detection, source metadata)
  - Date range processing (supports backfills)
  - Quality issue tracking
  - Processing run logging to `nba_processing.analytics_processor_runs`
- Multiple analytics processors: PlayerGameSummary, TeamDefense, etc.
- MERGE_UPDATE strategy: DELETE existing + INSERT new

**Monitoring**
- Basic logging exists in `analytics_processor_runs` table
- Fields: processor_name, date_range_start/end, records_processed, duration_seconds, success

### ❌ What We Don't Have

**Change Detection**
- No mechanism to detect what changed since last run
- No entity-level tracking (player_ids, team_ids in events)
- No content-based comparison

**Entity-Level Processing**
- Pub/Sub messages: table-level only (source_table, game_date, record_count)
- Processors: date-level processing (all entities for date)
- No filtering to changed entities

**Decision Metrics**
- No `entities_in_scope`, `entities_changed`, `waste_pct` tracking
- No decision query to determine if optimization is justified
- No baseline measurements

---

## The Problem We're Solving

**Scenario:**
```
10:00 AM - LeBron's injury status changes OUT → IN
10:01 AM - Phase 2 publishes: nbac_injury_report updated
10:02 AM - PlayerGameSummaryProcessor runs
          → Processes ALL 450 players for the date
          → Only LeBron actually changed
          → 449 players = wasted computation (99.8% waste)
```

**Question:** Is this waste significant enough to justify entity-level optimization?

**Answer:** We don't know yet! That's what we're measuring.

---

## Strategy: Three Phases

### **Phase 1: Monitor & Measure (Week 1-3)**

**Goal:** Get visibility into what's actually happening

**Tasks:**
1. Extend `analytics_processor_runs` schema with waste metrics
2. Add change detection to analytics_base.py (snapshot comparison)
3. Add context tracking for better debugging
4. Implement in 2-3 processors for testing
5. Validate metrics are accurate

**Deliverables:**
- Working change detection (content-based)
- Metrics flowing to BigQuery
- No code changes to Phase 2

**Time:** 12-15 hours over 2 weeks

**Success Criteria:**
- [ ] Change detection correctly identifies when data hasn't changed
- [ ] Waste metrics logged for every processor run
- [ ] Can run decision query and get meaningful results

---

### **Phase 2: Measure & Decide (Week 3-7)**

**Goal:** Accumulate data to make informed decision

**Tasks:**
1. Run decision query every Monday at 9 AM
2. Log results to tracking spreadsheet
3. Watch for patterns:
   - Which processors have high waste?
   - What times of day are busiest?
   - Are there burst patterns?
4. Identify pain points for patterns

**Deliverables:**
- 4-6 weeks of waste metrics
- Clear picture of where optimization would help
- Data-driven decision on Phase 3

**Time:** 30 min/week (total: ~3 hours)

**Success Criteria:**
- [ ] Have 4+ weeks of consistent metrics
- [ ] Can answer: "What % of our processing is wasted?"
- [ ] Can answer: "Which processors need optimization most?"
- [ ] Can calculate ROI of entity-level implementation

**Decision Criteria (Week 7):**
```
IF (avg_waste_pct > 30%
    AND wasted_hours > 2/week
    AND weeks_to_roi < 8)
THEN implement Phase 3
ELSE continue monitoring monthly
```

---

### **Phase 3: Entity-Level Optimization (Week 8+, Conditional)**

**Goal:** Implement entity-level processing for high-waste processors

**Only proceed if Phase 2 data shows clear justification!**

**Tasks:**
1. Enhance Phase 2 Pub/Sub messages with entity IDs
2. Modify pubsub_publishers.py to include changed entities
3. Update analytics_base.py to filter by entity IDs
4. Migrate one high-waste processor as pilot
5. Validate improvement
6. Gradual rollout to other processors

**Deliverables:**
- Entity-level Pub/Sub events
- Selective processing capability
- 10-15% additional efficiency gain

**Time:** 25-30 hours over 2-3 weeks

**Success Criteria:**
- [ ] Pilot processor shows <5% waste (down from >30%)
- [ ] Processing time reduced by 50%+ for incremental updates
- [ ] No regressions in data quality

---

## Week-by-Week Plan

### **Week 1: Foundation Setup**

**Monday-Tuesday: Schema & Change Detection**
- [ ] Extend analytics_processor_runs schema (30 min)
- [ ] Add context tracking to analytics_base.py (1 hour)
- [ ] Implement change detection methods (4 hours)
  - `_count_entities_in_scope()`
  - `_detect_changes_snapshot()`
  - `_get_current_data_signature()`
  - `_get_previous_run_signature()`

**Wednesday-Thursday: Integration**
- [ ] Modify `run()` to use change detection (2 hours)
- [ ] Update `log_processing_run()` with new fields (1 hour)
- [ ] Test with PlayerGameSummaryProcessor (2 hours)

**Friday: Validation**
- [ ] Run multiple times, verify skip behavior (1 hour)
- [ ] Check logs have correct metrics (1 hour)
- [ ] Fix any edge cases (2 hours)

**Total:** 14-15 hours

---

### **Week 2: Rollout & Testing**

**Monday-Wednesday: Implement in More Processors**
- [ ] Add `_count_entities_in_scope()` to 3-5 processors (3 hours)
- [ ] Deploy and monitor (2 hours)
- [ ] Fix any issues (2 hours)

**Thursday: Decision Query Setup**
- [ ] Create decision query script (1 hour)
- [ ] Test query with current data (30 min)
- [ ] Set up weekly calendar reminder (15 min)

**Friday: Documentation**
- [ ] Document change detection implementation (1 hour)
- [ ] Create decision query guide (1 hour)
- [ ] Update this roadmap with learnings (30 min)

**Total:** 11-12 hours

---

### **Week 3-7: Measure (Hands Off!)**

**Every Monday at 9 AM:**
- [ ] Run decision query (5 min)
- [ ] Log results to spreadsheet (5 min)
- [ ] Review trends (10 min)
- [ ] Note any anomalies (5 min)

**Observe:**
- Waste patterns by processor
- Waste patterns by time of day
- Burst update patterns
- Pain points

**Time:** 25 min/week × 5 weeks = 2 hours total

---

### **Week 8: Decision Point**

**Monday: Final Analysis**
- [ ] Run decision query for all 6 weeks (15 min)
- [ ] Calculate average waste across processors (15 min)
- [ ] Calculate total wasted compute hours (15 min)
- [ ] Calculate ROI of Phase 3 implementation (30 min)

**Tuesday: Team Discussion**
- [ ] Present findings to team (30 min)
- [ ] Discuss whether to proceed with Phase 3 (30 min)
- [ ] Document decision and rationale (30 min)

**If Decision is "Implement Phase 3":**
- [ ] Create Phase 3 implementation plan (2 hours)
- [ ] Prioritize which processors to migrate first (1 hour)
- [ ] Schedule implementation sprint (Week 9-11)

**If Decision is "Stay on Phase 1":**
- [ ] Set up monthly monitoring cadence (30 min)
- [ ] Identify other optimization opportunities (1 hour)
- [ ] Consider other patterns from catalog (1 hour)

**Time:** 4-6 hours

---

## What We're Extracting from Proposed Docs

From the 58 pages of proposed documentation, we're extracting only these concepts:

### ✅ **Using These Ideas**

1. **Decision Query Concept** (from Entity-Level Processing Guide)
   - Weekly monitoring with clear decision criteria
   - ROI-based optimization decisions
   - Waste percentage tracking

2. **Context Tracking Pattern** (from Processor Base)
   - `self.context = {'trigger_chain': [], 'decisions_made': []}`
   - Better debugging through decision logging
   - ~30 min implementation

3. **Change Detection Structure** (from Processor Base)
   - `_count_entities_in_scope()` + `_count_changed_entities()`
   - But using snapshot comparison, not processed_at
   - ~4 hours implementation

4. **Three-Layer Protection Concept** (from Processor Base)
   - Layer 1: Change detection (skip if no changes)
   - Layer 2: Dependency check (skip if missing dependencies)
   - Layer 3: Business logic processing
   - Conceptual model only

5. **Useful Patterns** (from Pattern Catalogs)
   - Circuit Breakers (#5) - Prevent infinite retries
   - Early Exit (#3) - Skip off-days
   - Backfill Detection (#15) - Auto-recover from gaps
   - Incremental Aggregation (Advanced #1) - If we have rolling averages

### ❌ **NOT Using These**

1. ❌ Complete processor base replacement - Our analytics_base.py is more sophisticated
2. ❌ Time-based idempotency - Conflicts with our MERGE_UPDATE strategy
3. ❌ New logging schema - Extending our existing schema instead
4. ❌ Single game_date - We support date ranges for backfills
5. ❌ 15+ optimization patterns - Most are premature or already implemented
6. ❌ Advanced patterns catalog - Month 3+ is too early to plan
7. ❌ Visual diagrams collection - Nice-to-have, not essential
8. ❌ Migration checklist - Nothing to migrate from

---

## Patterns We'll Implement (Based on Need)

### **Week 1-2: Foundation Only**

No patterns yet - just monitoring infrastructure.

### **Week 3-4: Add Based on Observation**

**If we see:** Infinite retry cascades
→ **Implement:** Circuit Breakers (#5)
→ **Effort:** 3 hours
→ **Value:** Prevents cascade failures

**If we see:** Processing on off-days
→ **Implement:** Early Exit Conditions (#3)
→ **Effort:** 30 min
→ **Value:** 30-40% savings on off-days

### **Week 5-8: Add Based on Pain Points**

**If we see:** Missing backfills causing repeated failures
→ **Implement:** Smart Backfill Detection (#15)
→ **Effort:** 3 hours
→ **Value:** Auto-recovery

**If we see:** Slow rolling average calculations
→ **Implement:** Incremental Aggregation (Advanced #1)
→ **Effort:** 4 hours
→ **Value:** 98% speedup for rolling calcs

**If we see:** Burst updates (5+ changes in 30 seconds)
→ **Implement:** Batch Coalescing (#7)
→ **Effort:** 3 hours
→ **Value:** 60-80% reduction during bursts

### **Patterns We Already Have (Don't Need)**

- ✅ Dependency Precheck (#2) - Already in analytics_base.py:319-413
- ✅ BigQuery Batching (#9) - Already in analytics_base.py:746-814
- ✅ Processing Metadata (#4) - Partially in analytics_base.py:908-927

---

## Technical Design Decisions

### **Change Detection: Snapshot Comparison Approach**

**Why not `processed_at` comparison?**
- Our Phase 2 does DELETE+INSERT all rows
- All rows have same `processed_at` timestamp
- Can't distinguish which entities actually changed

**Chosen Approach: Snapshot Comparison**
```python
def _detect_changes_snapshot(self, start_date, end_date):
    # 1. Get signature of current data from dependencies
    current_sig = self._get_current_data_signature(start_date, end_date)

    # 2. Get signature from last successful run
    previous_sig = self._get_previous_run_signature(start_date, end_date)

    # 3. Compare
    if current_sig == previous_sig:
        return None  # No changes, skip processing

    # 4. Something changed - process
    return {
        'entities_in_scope': self._count_entities_in_scope(...),
        'entities_changed': entities_in_scope,  # Conservative estimate
        'has_changes': True
    }
```

**Tradeoffs:**
- ✅ Pros: Works with DELETE+INSERT pattern
- ✅ Pros: Simple to implement
- ❌ Cons: Conservative (assumes all entities changed if any changed)
- ❌ Cons: Can't provide granular entity list for Phase 3

**Evolution Path:**
- Phase 1: Signature comparison (good enough for skip/no-skip decision)
- Phase 3: Add entity-level tracking in Phase 2 (enables granular filtering)

---

### **Schema Extension: Augment, Don't Replace**

**Decision:** Extend `nba_processing.analytics_processor_runs` instead of creating new table.

**Reasoning:**
- Existing schema has date ranges (supports backfills)
- Already has quality tracking, error handling
- Adding fields is backward compatible
- Avoids data duplication

**New Fields:**
```sql
ALTER TABLE nba_processing.analytics_processor_runs
ADD COLUMN IF NOT EXISTS entities_in_scope INT64,
ADD COLUMN IF NOT EXISTS entities_processed INT64,
ADD COLUMN IF NOT EXISTS entities_changed INT64,
ADD COLUMN IF NOT EXISTS processing_mode STRING DEFAULT 'date_range',
ADD COLUMN IF NOT EXISTS waste_pct FLOAT64,
ADD COLUMN IF NOT EXISTS skip_reason STRING,
ADD COLUMN IF NOT EXISTS change_signature STRING,
ADD COLUMN IF NOT EXISTS trigger_chain STRING,
ADD COLUMN IF NOT EXISTS decisions_made STRING,
ADD COLUMN IF NOT EXISTS optimizations_used STRING;
```

---

### **Decision Query: Adapted for Date Ranges**

**Proposed query assumed single `game_date`.**
**Our query uses `date_range_start` for date filtering:**

```sql
-- THE DECISION QUERY (Adapted for our schema)
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

    FROM nba_processing.analytics_processor_runs
    WHERE date_range_start >= CURRENT_DATE() - 7  -- Last week
      AND success = TRUE
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

---

## Success Metrics

### **Phase 1 Success (Week 2)**
- [ ] Change detection works correctly (skip when no changes)
- [ ] Waste metrics logged for all processor runs
- [ ] Zero regressions in data quality
- [ ] Can run decision query

### **Phase 2 Success (Week 7)**
- [ ] 4-6 weeks of reliable metrics collected
- [ ] Can answer: "What processors have >30% waste?"
- [ ] Can answer: "How many compute hours wasted per week?"
- [ ] Can calculate ROI of Phase 3 implementation

### **Phase 3 Success (Week 11, if implemented)**
- [ ] Waste reduced from >30% to <5% in pilot processor
- [ ] Processing time reduced by 50%+ for incremental updates
- [ ] Zero data quality regressions
- [ ] Gradual rollout to other high-waste processors

---

## Risks & Mitigations

### **Risk 1: Change Detection False Negatives**

**Risk:** Signature comparison misses actual changes

**Likelihood:** Low
**Impact:** High (stale data)

**Mitigation:**
- Use COUNT(*) + MAX(processed_at) from ALL dependencies
- Test thoroughly with known change scenarios
- Monitor for data freshness alerts
- Have manual reprocess capability

---

### **Risk 2: Metrics Show Phase 3 Not Justified**

**Risk:** After 6 weeks of measurement, waste is <20%

**Likelihood:** Medium
**Impact:** Low (we learned something valuable!)

**Mitigation:**
- This is actually a SUCCESS - we avoided premature optimization
- We still have monitoring infrastructure for future needs
- We can apply optimization patterns to specific pain points
- Continue monthly monitoring

---

### **Risk 3: Schema Evolution Complexity**

**Risk:** Adding fields breaks existing queries/dashboards

**Likelihood:** Low
**Impact:** Medium

**Mitigation:**
- New fields are nullable (backward compatible)
- Test schema change in dev environment first
- Update known queries proactively
- Document schema changes

---

## Documentation Plan

### **Week 2: After Foundation Works**

Create these docs:
1. `docs/architecture/change-detection-implementation.md` (2-3 pages)
   - How snapshot comparison works
   - Schema extension details
   - Integration with analytics_base.py

2. `docs/operations/weekly-decision-query.md` (2 pages)
   - The decision query
   - How to interpret results
   - Weekly review process

3. `docs/operations/monitoring-dashboard-setup.md` (2 pages)
   - Grafana panel configs
   - Key metrics to track
   - Alert thresholds

**Total:** ~7-8 pages of focused, accurate documentation

### **Week 8+: If Phase 3 Implemented**

Create these docs:
4. `docs/architecture/entity-level-processing.md` (3-4 pages)
   - Phase 2 Pub/Sub enhancement
   - Entity filtering in processors
   - Migration guide

5. `docs/patterns/` (1 page each for implemented patterns)
   - Circuit breaker
   - Early exit
   - Backfill detection
   - etc.

**Total:** Additional 6-8 pages

### **What We're NOT Creating**

- ❌ 20-page entity-level processing guide (too much, too early)
- ❌ 28-page pattern catalog (most patterns not needed)
- ❌ 10-page advanced patterns (month 3+ is premature)
- ❌ Visual diagrams collection (nice-to-have)
- ❌ Migration checklists (nothing to migrate from)
- ❌ Artifacts summary (meta-docs about docs)

**Philosophy:** Document what you BUILD, not what you MIGHT build.

---

## Open Questions

### **Q1: Should we implement idempotency?**

**Current thinking:** NO - conflicts with MERGE_UPDATE strategy.

**Reasoning:**
- Our DELETE+INSERT pattern allows reprocessing anytime
- Corrections can arrive 5 minutes after initial data
- Content-based skip (via change detection) is sufficient

**Decision:** Use change detection for skip logic, not time windows.

---

### **Q2: Should we track processing context now or later?**

**Current thinking:** NOW - high value, low effort.

**Reasoning:**
- Context tracking (trigger_chain, decisions_made) = 30 min implementation
- Makes debugging 10x faster
- Helps understand why processing happened/skipped
- No downside

**Decision:** Include in Week 1 implementation.

---

### **Q3: How granular should entity counts be?**

**Current thinking:** Start conservative, refine if needed.

**Phase 1 Approach:**
- If signature matches: entities_changed = 0 (skip processing)
- If signature differs: entities_changed = entities_in_scope (process all)

**Tradeoff:**
- ✅ Simple to implement
- ✅ Gives us waste metrics for decision
- ❌ Doesn't tell us WHICH entities changed
- ❌ Can't filter to changed entities yet

**Evolution:**
- Phase 1: Good enough for decision query
- Phase 3: Add granular entity tracking in Phase 2 if justified

**Decision:** Start conservative, enhance if Phase 3 warranted.

---

## Approval & Sign-Off

**This roadmap approved by:**
- [ ] Technical Lead: _________________ Date: _________
- [ ] Product Owner: _________________ Date: _________
- [ ] DevOps/SRE: ___________________ Date: _________

**Next Review:** Week 8 (Decision Point)

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-11-19 | 1.0 | Initial roadmap created | Team |

---

## References

- Existing Implementation: `data_processors/analytics/analytics_base.py`
- Pub/Sub Publishers: `shared/utils/pubsub_publishers.py`
- Processing Runs Schema: `nba_processing.analytics_processor_runs`
- Dependency Tracking v4.0: Implemented in analytics_base.py:283-567
