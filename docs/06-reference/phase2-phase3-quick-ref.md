# Phase 2→3 Quick Reference

**Created:** 2025-11-19 10:19 PM PST
**Last Updated:** 2025-11-19 10:41 PM PST
**Status:** Planning → Implementation
**Main Plan:** docs/architecture/09-phase2-phase3-implementation-roadmap.md

## The Strategy (One Sentence)

Ship monitoring with change detection (Week 1-2), measure waste for 4-6 weeks (Week 3-7), then decide if entity-level optimization is justified (Week 8).

## Current Week: Week 0 (Planning)

**This Week's Goal:** Finalize roadmap, get team buy-in

**Next Week's Goal:** Implement change detection foundation

---

## What We're Building (Week 1-2)

### **Change Detection**
- Detect when data hasn't changed since last run
- Skip processing if no changes (save compute)
- Track waste metrics (entities_in_scope vs entities_changed)

### **Decision Query**
- Weekly query to measure waste across processors
- Clear decision criteria for Phase 3
- ROI calculation

### **Context Tracking**
- Log decision chain (why processing happened/skipped)
- 10x faster debugging

---

## What We're NOT Building (Yet)

- ❌ Entity-level Pub/Sub messages (Phase 3 only, if justified)
- ❌ Entity filtering in processors (Phase 3 only)
- ❌ 15+ optimization patterns (add based on observed pain points)
- ❌ Advanced patterns (Month 3+)

---

## Week-by-Week Summary

| Week | Goal | Deliverable | Time |
|------|------|-------------|------|
| **1-2** | Build foundation | Change detection working | 15 hrs |
| **3-7** | Measure | 4-6 weeks of metrics | 30 min/week |
| **8** | Decide | Go/no-go on Phase 3 | 4-6 hrs |
| **9-11** | Optimize (maybe) | Entity-level processing | 25-30 hrs |

---

## Decision Criteria (Week 8)

```
IF (avg_waste_pct > 30%
    AND wasted_hours > 2/week
    AND total_runs > 10/week
    AND weeks_to_roi < 8)
THEN implement Phase 3
ELSE continue monitoring monthly
```

**Example:**
- PlayerGameSummary: 42% waste, 3.2 hrs/week → **🔴 IMPLEMENT PHASE 3**
- TeamDefense: 18% waste, 0.5 hrs/week → **🟢 PHASE 1 SUFFICIENT**

---

## Patterns to Implement (Based on Need)

### **Definitely Implementing (Week 1-2)**
- Change detection (foundation)
- Context tracking (debugging)

### **Probably Implementing (Week 3-4)**
- Circuit Breakers (#5) - If we see infinite retries
- Early Exit (#3) - If we see off-day processing

### **Maybe Implementing (Week 5-8)**
- Backfill Detection (#15) - If missing data causes failures
- Incremental Aggregation (Adv #1) - If we have slow rolling averages
- Batch Coalescing (#7) - If we see burst updates

### **Already Have (Don't Need)**
- ✅ Dependency Precheck - analytics_base.py:319-413
- ✅ BigQuery Batching - analytics_base.py:746-814
- ✅ Processing Metadata - analytics_base.py:908-927

---

## Key Files

### **Existing Code**
- `data_processors/analytics/analytics_base.py` - Our sophisticated base class
- `shared/utils/pubsub_publishers.py` - Phase 2 event publishing
- `nba_processing.analytics_processor_runs` - Logging table

### **Will Modify**
- `analytics_base.py` - Add change detection + context tracking
- `analytics_processor_runs` table - Extend with waste metrics

### **Will Create**
- `bin/monitoring/weekly_decision_query.sql` - The decision query
- `docs/architecture/change-detection-implementation.md` - How it works
- `docs/operations/weekly-decision-query.md` - How to use it

---

## Success Criteria

### **Week 2: Foundation Working**
- [ ] Change detection skips when no changes
- [ ] Waste metrics logged correctly
- [ ] Can run decision query
- [ ] Zero data quality regressions

### **Week 7: Decision Ready**
- [ ] 4-6 weeks of reliable metrics
- [ ] Can identify high-waste processors
- [ ] Can calculate ROI of Phase 3

### **Week 11: Optimized (if implemented)**
- [ ] Waste <5% in pilot processor
- [ ] 50%+ faster for incremental updates
- [ ] Zero regressions

---

## Open Questions

**Q: What if metrics show Phase 3 isn't justified?**
A: Perfect! We avoided premature optimization. Continue monthly monitoring.

**Q: Do we need idempotency?**
A: No - conflicts with MERGE_UPDATE. Use change detection instead.

**Q: Should we implement all 15+ patterns?**
A: No - only add patterns for observed pain points.

---

## Next Actions (Week 1 Start)

1. [ ] Review roadmap doc
2. [ ] Get team sign-off
3. [ ] Extend analytics_processor_runs schema (30 min)
4. [ ] Add context tracking to analytics_base.py (1 hour)
5. [ ] Implement change detection methods (4 hours)

**Start Here:** docs/architecture/phase2-phase3-implementation-roadmap.md
