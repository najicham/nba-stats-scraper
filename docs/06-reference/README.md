# 00 - Reference Documentation

**Created:** 2025-11-19 10:26 PM PST
**Last Updated:** 2025-11-25

> **📌 These are reference materials from research and planning.**
>
> **For actual implementation**, see:
> - [Architecture Overview](../01-architecture/quick-reference.md) ⭐ **Start Here**
> - [Quick Reference](phase2-phase3-quick-ref.md)

## What's in This Folder

This folder contains reference material that informed our implementation strategy. These documents represent **proposed patterns and approaches** from planning research, not our actual implementation.

### 📚 Reference Documents

1. **entity-level-processing-guide-v3.md**
   - Conceptual guide to entity-level processing
   - Three-phase approach (Monitor → Measure → Optimize)
   - Decision query framework
   - **Use for:** Understanding the overall strategy

2. **optimization-pattern-catalog.md**
   - 15 core optimization patterns
   - Implementation effort and ROI estimates
   - **Use for:** Finding patterns for specific pain points
   - **Note:** Many patterns already implemented or not applicable

3. **optimization-pattern-catalog-advanced.md**
   - 4 advanced patterns (Month 3+)
   - Incremental aggregation, cache warming, etc.
   - **Use for:** Advanced optimizations only if needed

4. **processor_base_complete.py** (when created)
   - Proposed processor base implementation
   - **Note:** Conflicts with our existing analytics_base.py
   - **Use for:** Extracting specific patterns only

---

## Implementation Status

### ✅ What We Already Have

These capabilities exist in our current codebase:

| Feature | Location | Notes |
|---------|----------|-------|
| Dependency Tracking v4.0 | analytics_base.py:283-567 | More sophisticated than proposed |
| BigQuery Batch Loading | analytics_base.py:746-814 | NDJSON load jobs |
| Processing Run Logging | analytics_base.py:908-927 | To analytics_processor_runs table |
| Date Range Processing | analytics_base.py | Supports backfills |
| Quality Issue Tracking | analytics_base.py:856-903 | Full quality management |
| MERGE_UPDATE Strategy | analytics_base.py:735 | DELETE+INSERT pattern |

### 💡 What We're Adding (Week 1-2)

Based on roadmap:

| Feature | Effort | Value | Status |
|---------|--------|-------|--------|
| Change Detection | 6-8 hours | High | Planned Week 1 |
| Context Tracking | 1 hour | High | Planned Week 1 |
| Waste Metrics | 2 hours | High | Planned Week 1 |
| Decision Query | 1 hour | High | Planned Week 2 |

### ⚠️ What Requires Phase 3

These patterns need entity-level infrastructure:

- Smart Skip Patterns (#1) - Needs source_table in Pub/Sub
- Batch Coalescing (#7) - Needs entity IDs in messages
- Processing Priority (#8) - Needs entity context
- Change Classification (#12) - Needs granular change detection

### ❌ What We're NOT Using

From the reference materials:

- ❌ Proposed processor_base.py - Conflicts with our analytics_base.py
- ❌ Time-based idempotency - Conflicts with MERGE_UPDATE
- ❌ Single game_date schema - We use date ranges
- ❌ New logging table - Extending existing table instead
- ❌ Most optimization patterns - Already have or premature

---

## How to Use These References

### ✅ DO Use For:

1. **Understanding Concepts**
   - Three-phase strategy (Monitor → Measure → Optimize)
   - Decision query framework
   - Waste metrics approach

2. **Pattern Research**
   - When you observe a specific pain point
   - Look up relevant pattern in catalog
   - Adapt to our architecture

3. **ROI Estimates**
   - Effort vs impact for patterns
   - Help prioritize what to implement

4. **Testing Patterns**
   - Test examples for validation
   - Monitoring query examples

### ❌ DON'T Use For:

1. **Direct Implementation**
   - These conflict with our existing code
   - Not adapted to our architecture
   - Use roadmap for actual plan

2. **Complete Pattern List**
   - Don't implement all patterns
   - Many are already implemented
   - Many are premature

3. **Schema Design**
   - Don't create new tables
   - Extend our existing schema instead

4. **Processor Base**
   - Don't replace analytics_base.py
   - Extract useful patterns only

---

## Quick Navigation

**Starting implementation?**
→ [Architecture Overview](../01-architecture/quick-reference.md)

**Need quick overview?**
→ [Quick Reference](phase2-phase3-quick-ref.md)

**Looking for a specific pattern?**
→ [Pattern Catalog](optimization-pattern-catalog.md) (check implementation status first)

**Understanding the strategy?**
→ [Entity-Level Processing Guide](entity-level-processing-guide-v3.md)

**Advanced optimizations?**
→ [Advanced Patterns](optimization-pattern-catalog-advanced.md) (Month 3+ only)

---

## Key Takeaways from Reference Materials

### What We're Keeping:

1. **Decision Query Concept** ⭐
   - Weekly monitoring with clear criteria
   - ROI-based decisions
   - This is the core value

2. **Three-Phase Approach** ⭐
   - Phase 1: Monitor (Week 1-2)
   - Phase 2: Measure (Week 3-7)
   - Phase 3: Optimize if justified (Week 8+)

3. **Waste Metrics** ⭐
   - entities_in_scope
   - entities_changed
   - waste_pct calculation

4. **Context Tracking Pattern**
   - trigger_chain, decisions_made
   - Better debugging

### What We're Adapting:

1. **Change Detection**
   - Proposed: processed_at comparison
   - Our approach: Snapshot comparison (works with DELETE+INSERT)

2. **Schema**
   - Proposed: Single game_date, new table
   - Our approach: Date ranges, extend existing table

3. **Idempotency**
   - Proposed: Time-based windows
   - Our approach: Content-based (signature comparison)

### What We're Skipping:

1. **Most Patterns**
   - 80% are premature or already implemented
   - Add only for observed pain points

2. **Processor Base Replacement**
   - Our analytics_base.py is more sophisticated
   - Extract useful patterns, don't replace

3. **Entity-Level Now**
   - Only if Week 8 data justifies it
   - Don't build before we know it's needed

---

## Contributing to Reference Docs

As you implement:

1. **Update Implementation Status**
   - Mark patterns as implemented
   - Note location in codebase
   - Update this README

2. **Add New Patterns**
   - If you discover useful patterns
   - Document effort and value
   - Share with team

3. **Document Adaptations**
   - How we adapted reference material
   - Why we made different choices
   - Lessons learned

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-19 | Initial reference docs created | Team |

---

**Remember:** These are references, not instructions. Follow the [architecture docs](../01-architecture/quick-reference.md) for actual implementation.
