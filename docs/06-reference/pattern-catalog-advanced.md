# 03 - NBA Props Platform: Advanced Optimization Patterns

**Created:** 2025-11-19 10:41 PM PST
**Last Updated:** 2025-11-19 10:41 PM PST

> **📌 NOTE:** This is reference material from research and planning.
> **For the actual implementation plan**, see [Phase 2→3 Implementation Roadmap](../architecture/phase2-phase3-implementation-roadmap.md).
>
> **IMPORTANT:** These are Month 3+ patterns. Only implement if you have specific pain points they address.

**Version:** 1.0
**Purpose:** Advanced optimization patterns (Month 3+)
**Prerequisites:** Core patterns implemented, system stable

---

## Overview

These are advanced patterns for Month 3+ optimization. Only implement if:

- ✅ Core patterns (1-15) already deployed
- ✅ System is stable and monitored
- ✅ You have a specific pain point these address
- ✅ ROI analysis justifies the effort

Each pattern requires 3-4 hours implementation. These provide marginal improvements (5-10%) on top of the 80-95% efficiency already achieved.

---

## Pattern Index

1. **Incremental Aggregation** - 98% faster rolling calculations ⭐ **High value if applicable**
2. **Data Freshness Scoring** - Multi-factor staleness detection
3. **Change Velocity Tracking** - Predictive capacity management
4. **Smart Cache Warming** - Pre-aggregate for API performance

---

## Pattern #1: Incremental Aggregation ⭐

**Problem:**
Calculating 10-game rolling average requires scanning 10 games every time (2s per player × 450 players = 15 minutes total).

**Solution:**
Cache rolling totals, update incrementally: `new_avg = (old_total + new_game - old_game) / 10`. Single calculation: 0.1s (98% faster).

**Value:**
- Effort: 3-4 hours
- Impact: Very High (80% reduction in lookback costs)
- ROI: Week 2 if rolling averages used heavily

**When:** Month 2+ if you have rolling calculations

**Key Concept:**
```python
# Traditional approach: Scan N games
SELECT AVG(points) FROM games WHERE player_id = 'X' AND game_date <= 'Y' LIMIT 10

# Incremental approach: Update cache
new_total = cached_total + new_game_points - old_game_points
new_avg = new_total / 10
```

**Use Cases:**
- Perfect for: Rolling averages (last 10 games), moving totals, sliding window metrics
- Not needed for: Season-long aggregates, one-time calculations

---

## Pattern #2: Data Freshness Scoring

**Problem:**
Hard to know if data is "stale enough" to warrant reprocessing. Binary fresh/stale decision wastes processing.

**Solution:**
Multi-factor freshness score (0-100): recency (50%) + completeness (40%) + activity (10%). Skip if score >70.

**Value:**
- Effort: 2 hours
- Impact: Medium
- When: Month 3+, for advanced data quality management

**Key Concept:**
- Score = Recency (50%) + Completeness (40%) + Activity (10%)
- Recency: Hours since last update
- Completeness: % of expected entities present
- Activity: Recent change velocity

**Note:** Our existing Dependency Tracking v4.0 staleness detection is usually sufficient.

---

## Pattern #3: Change Velocity Tracking

**Problem:**
Hard to predict when system will be busy. Reactive capacity management causes slowdowns.

**Solution:**
Track change rate over time. Alert when acceleration detected (15/hr → 40/hr). Enable predictive capacity management.

**Value:**
- Effort: 2-3 hours
- Impact: Medium
- When: Month 3+, for capacity planning

**Key Concept:**
- Track changes per hour
- Calculate acceleration
- Alert on significant acceleration
- Helps predict burst periods

**Note:** NBA system has relatively predictable patterns (game schedules). Most useful for unpredictable load systems.

---

## Pattern #4: Smart Cache Warming

**Problem:**
Frontend queries hit full analytics tables repeatedly (2s per query × 100 queries/day).

**Solution:**
Pre-aggregate common access patterns after processing. Frontend queries cache table (0.1s, 95% faster).

**Value:**
- Effort: 3-4 hours
- Impact: Medium
- When: Month 3+, if you have API/frontend

**Key Concept:**
- After processing, create denormalized cache tables
- Frontend queries cached tables instead of full tables

**Note:** Only needed if you have API performance issues.

---

## Implementation Priority

### Only Implement If:

**Pattern #1 (Incremental Aggregation):**
- ✅ You have rolling averages (last N games)
- ✅ Calculating them is slow (>1s per player)
- ✅ Calculated frequently (every game)

**Pattern #2 (Freshness Scoring):**
- ✅ Managing staleness manually is painful
- ✅ Need multi-factor quality scoring

**Pattern #3 (Velocity Tracking):**
- ✅ Experiencing burst capacity issues
- ✅ Need predictive capacity management

**Pattern #4 (Cache Warming):**
- ✅ Have slow API queries (>1s)
- ✅ Queries hit same patterns repeatedly

---

## Pattern Summary

| Pattern | Effort | Impact | When | Best For |
|---------|--------|--------|------|----------|
| Incremental Aggregation | 3-4 hrs | Very High | Month 2+ | Rolling calculations ⭐ |
| Data Freshness Scoring | 2 hrs | Medium | Month 3+ | Data quality mgmt |
| Change Velocity Tracking | 2-3 hrs | Medium | Month 3+ | Capacity planning |
| Smart Cache Warming | 3-4 hrs | Medium | Month 3+ | API performance |

---

## Key Message

**Most teams will never need these patterns.**

The core patterns (1-15) + Phases 1-3 already give you 85-95% efficiency. These advanced patterns provide marginal improvements for specific use cases.

**Only implement if:**
1. You have the specific pain point
2. ROI analysis justifies the effort
3. Core patterns are fully implemented
4. System is stable

**Don't implement just because they're here.**

---

## Next Steps

1. **Focus on core first:** See [Core Pattern Catalog](02-optimization-pattern-catalog.md)
2. **Implement foundation:** See [Roadmap](../architecture/phase2-phase3-implementation-roadmap.md)
3. **Measure pain points:** Week 3-7 monitoring
4. **Reference this doc:** Only if specific pain point observed

---

*This is reference material for advanced patterns. Most systems won't need these. Focus on core patterns and foundation first.*
