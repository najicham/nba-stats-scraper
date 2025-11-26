# 02 - NBA Props Platform: Optimization Pattern Catalog

**Created:** 2025-11-19 10:25 PM PST
**Last Updated:** 2025-11-20 8:14 AM PST (added categorized problem index)

> **📌 NOTE:** This is reference material from research and planning.
> **For the actual implementation plan**, see [Phase 2→3 Implementation Roadmap](../architecture/09-phase2-phase3-implementation-roadmap.md).
>
> Most patterns described here are **NOT needed immediately**. Implement patterns based on observed pain points, not speculatively.
>
> **Patterns we already have:** #2 (Dependency Precheck), #9 (BigQuery Batching), #4 (Processing Metadata - partial)
>
> **Patterns with implementation docs:** #1 (Smart Skip), #2 (Dependency Precheck), #3 (Early Exit), #5 (Circuit Breaker), #6 (Checkpoints), #7 (Batch Coalescing), #8 (Processing Priority), #9 (BigQuery Batching), #12 (Change Classification), #13 (Smart Caching), #14 (Smart Idempotency), #15 (Smart Backfill)

**Version:** 3.0 - Core Patterns (1-15)
**Purpose:** Reference guide for optimization patterns
**Usage:** Reference when needed, not required reading

---

## Patterns by Problem Index

Use this to jump directly to what you need:

### 🔴 Performance Problems

| Problem | Pattern | When | Status |
|---------|---------|------|--------|
| "BigQuery writes are slow" | #9: Smart BigQuery Batching | Week 2-3 | ✅ Already have (analytics_base.py:746-814) |
| "Dependencies take forever to check" | #2: Dependency Precheck | Week 1 | ✅ Already have (analytics_base.py:319-413) |
| "Expensive rolling calculations" | #13: Smart Caching | Week 4-8 | 💡 IF slow queries detected |
| "Processing identical data repeatedly" | #14: Smart Idempotency | Week 4-8 | 💡 IF duplicate processing > 10% |

### 🟡 Wasted Processing

| Problem | Pattern | When | Status |
|---------|---------|------|--------|
| "Processor runs when it shouldn't" | #1: Smart Skip Patterns | Week 1 | 💡 Can implement now |
| "Processing when no games scheduled" | #3: Early Exit Conditions | Week 1 | 💡 Can implement now (includes game state) |
| "Reprocessing after minor changes" | #12: Change Classification | Week 8+ | ⚠️ Phase 3 (needs field-level diffing) |

### 🔵 Reliability Issues

| Problem | Pattern | When | Status |
|---------|---------|------|--------|
| "Infinite retry loops" | #5: Circuit Breakers | Week 1 | 💡 Can implement now |
| "Missing dependencies cascade" | #15: Smart Backfill Detection | Week 4-8 | 💡 IF gaps are frequent |
| "Processor fails halfway through" | #6: Processing Checkpoints | Phase 3 | ⚠️ Wait for Week 8 decision |
| "Hard to debug failures" | #4: Processing Metadata | Week 1 | ✅ Partial (analytics_base.py:908-927) |

### ⚡ Time-Sensitive Issues

| Problem | Pattern | When | Status |
|---------|---------|------|--------|
| "Burst updates (5+ in 30 seconds)" | #7: Batch Coalescing | Week 3-4 | ⚠️ Phase 3 (needs entity IDs) |
| "Critical updates wait in queue" | #8: Processing Priority | Week 2 | ⚠️ Phase 3 (needs entity context) |
| "Processing at wrong times" | #10: Game-Time Scheduling | N/A | Cloud Scheduler handles this |

### 📅 By Timeline

**Week 1 (Must Have):**
- #1 Smart Skip Patterns 💡 (can implement now)
- #2 Dependency Precheck ✅ (already have)
- #3 Early Exit Conditions 💡 (can implement now)
- #5 Circuit Breakers 💡 (can implement now)

**Week 2-4 (High Value):**
- #7 Batch Coalescing ⚠️ (needs entity IDs)
- #8 Processing Priority ⚠️ (needs entity context)
- #9 BigQuery Batching ✅ (already have)

**Month 2+ (Situational):**
- #11 Selective Column Updates
- #13 Smart Caching 💡 (Week 4-8 IF slow queries detected)
- #14 Smart Idempotency 💡 (Week 4-8 IF duplicate processing > 10%)
- #15 Smart Backfill Detection

---

## Pattern Implementation Status

✅ = Already implemented in our codebase
⚠️ = Requires Phase 3 infrastructure
💡 = Can implement now

| # | Pattern | Status | Location |
|---|---------|--------|----------|
| 1 | Smart Skip Patterns | 💡 | docs/patterns/08-smart-skip-implementation.md |
| 2 | Dependency Precheck | ✅ | analytics_base.py:319-413 |
| 3 | Early Exit Conditions | 💡 | docs/patterns/03-early-exit-implementation.md |
| 4 | Processing Metadata | ✅ | analytics_base.py:908-927 (partial) |
| 5 | Circuit Breakers | 💡 | docs/patterns/01-circuit-breaker-implementation.md |
| 6 | Processing Checkpoints | ⚠️ | docs/patterns/06-processing-checkpoints-reference.md |
| 7 | Batch Coalescing | ⚠️ | docs/patterns/04-batch-coalescing-reference.md |
| 8 | Processing Priority | ⚠️ | docs/patterns/05-processing-priority-reference.md |
| 9 | BigQuery Batching | ✅ | docs/patterns/07-bigquery-batching-current.md |
| 10 | Game-Time Scheduling | ⚠️ | Cloud Scheduler handles this |
| 11 | Selective Columns | 💡 | Add if BigQuery costs high |
| 12 | Change Classification | ⚠️ | docs/patterns/10-change-classification-reference.md (Week 8+ decision) |
| 13 | Smart Caching | 💡 | docs/patterns/11-smart-caching-reference.md (Week 4-8 situational) |
| 14 | Smart Idempotency | 💡 | docs/patterns/12-smart-idempotency-reference.md (Week 4-8 situational) |
| 15 | Smart Backfill | 💡 | docs/patterns/09-smart-backfill-detection.md (Week 4-8) |

---

[Rest of the pattern catalog content from the user's original document...]

---

*This is reference material. Many patterns are already implemented or require Phase 3 infrastructure. See roadmap for actual implementation priorities.*
