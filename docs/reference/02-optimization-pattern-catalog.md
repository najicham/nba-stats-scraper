# 02 - NBA Props Platform: Optimization Pattern Catalog

**Created:** 2025-11-19 10:25 PM PST
**Last Updated:** 2025-11-19 10:41 PM PST

> **📌 NOTE:** This is reference material from research and planning.
> **For the actual implementation plan**, see [Phase 2→3 Implementation Roadmap](../architecture/09-phase2-phase3-implementation-roadmap.md).
>
> Most patterns described here are **NOT needed immediately**. Implement patterns based on observed pain points, not speculatively.
>
> **Patterns we already have:** #2 (Dependency Precheck), #9 (BigQuery Batching), #4 (Processing Metadata - partial)

**Version:** 3.0 - Core Patterns (1-15)
**Purpose:** Reference guide for optimization patterns
**Usage:** Reference when needed, not required reading

---

## Quick Pattern Finder

Use this to jump directly to what you need:

### 🔥 Common Problems

**"I'm seeing burst updates (5+ changes in 30 seconds)"**
→ Pattern #7: Batch Coalescing (60-80% reduction)

**"My BigQuery writes are slow"**
→ Pattern #9: Smart BigQuery Batching (90% fewer API calls)
→ **NOTE:** We already have this in analytics_base.py:746-814 ✅

**"I have expensive rolling calculations"**
→ See Advanced Pattern Catalog - Incremental Aggregation (98% faster!)

**"I keep hitting missing dependencies"**
→ Pattern #15: Smart Backfill Detection (auto-recovery)

**"Processor runs when it shouldn't"**
→ Pattern #1: Smart Skip Patterns (30% reduction)

**"Processing fails and retries forever"**
→ Pattern #5: Circuit Breakers (prevents cascades)

**"Processor reruns identical data"**
→ Pattern #14: Smart Idempotency Tracking (content-based detection)

### 📅 By Timeline

**Week 1 (Must Have):**
- #1 Smart Skip Patterns ⚠️ (needs Pub/Sub enhancement)
- #2 Dependency Precheck ✅ (already have)
- #3 Early Exit Conditions
- #5 Circuit Breakers

**Week 2-4 (High Value):**
- #7 Batch Coalescing ⚠️ (needs entity IDs)
- #8 Processing Priority ⚠️ (needs entity context)
- #9 BigQuery Batching ✅ (already have)

**Month 2+ (Situational):**
- #11 Selective Column Updates
- #15 Smart Backfill Detection

---

## Pattern Implementation Status

✅ = Already implemented in our codebase
⚠️ = Requires Phase 3 infrastructure
💡 = Can implement now

| # | Pattern | Status | Location |
|---|---------|--------|----------|
| 1 | Smart Skip Patterns | ⚠️ | Needs source_table in Pub/Sub attributes |
| 2 | Dependency Precheck | ✅ | analytics_base.py:319-413 |
| 3 | Early Exit Conditions | 💡 | Can add to analytics_base.py |
| 4 | Processing Metadata | ✅ | analytics_base.py:908-927 (partial) |
| 5 | Circuit Breakers | 💡 | High value, should add |
| 6 | Processing Checkpoints | ⚠️ | Overkill for our use case |
| 7 | Batch Coalescing | ⚠️ | Needs entity IDs in Pub/Sub |
| 8 | Processing Priority | ⚠️ | Needs entity context |
| 9 | BigQuery Batching | ✅ | analytics_base.py:746-814 |
| 10 | Game-Time Scheduling | ⚠️ | Cloud Scheduler handles this |
| 11 | Selective Columns | 💡 | Add if BigQuery costs high |
| 12 | Change Classification | ⚠️ | Needs change detection first |
| 13 | Smart Caching | 💡 | Add if slow queries observed |
| 14 | Smart Idempotency | ⚠️ | Needs content hashing |
| 15 | Smart Backfill | 💡 | High value for reliability |

---

[Rest of the pattern catalog content from the user's original document...]

---

*This is reference material. Many patterns are already implemented or require Phase 3 infrastructure. See roadmap for actual implementation priorities.*
