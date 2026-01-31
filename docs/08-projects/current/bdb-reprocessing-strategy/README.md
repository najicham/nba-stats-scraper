# BDB Reprocessing Strategy Project

**Project Start**: 2026-01-31 (Session 53)
**Status**: Design Complete - Ready for Implementation
**Priority**: P1 - Critical for Prediction Quality

---

## Quick Links

- **[EXECUTIVE-SUMMARY.md](./EXECUTIVE-SUMMARY.md)** - Start here for project overview
- **[DECISION-MATRIX.md](./DECISION-MATRIX.md)** - Strategy comparison and recommendation
- **[TECHNICAL-IMPLEMENTATION-GUIDE.md](./TECHNICAL-IMPLEMENTATION-GUIDE.md)** - Detailed implementation specs

---

## Problem Statement

BigDataBall (BDB) play-by-play data is critical for shot zone features (ranked #3 in feature importance at 11%). When BDB data arrives late (45+ hours after games), the system currently:

✅ **WORKS**: Reprocesses Phase 3-4 (player stats → ML features)
❌ **BROKEN**: Does NOT regenerate Phase 5 predictions

**Impact**: 48 games from Jan 17-24, 2026 have production predictions using NBAC fallback or no shot zones, even though BDB data later arrived.

---

## Solution Overview

**Recommended Strategy**: Full Reprocessing Pipeline (Strategy C)

When BDB data arrives late:
1. ✅ Phase 3: Reprocess player stats (existing)
2. ✅ Phase 4: Recompute ML features (existing)
3. ✨ Phase 5: **Regenerate predictions** (NEW)
4. ✨ Mark old predictions as "superseded" (NEW)

**Benefits**:
- +2.3% accuracy improvement (38.6% vs 36.3% hit rate)
- -0.96 MAE reduction (5.25 vs 6.21)
- Consistent GOLD quality tier
- Clean historical data for analysis

**Cost**: $15-25/month (acceptable ROI)

---

## Key Findings from Research

### BDB vs NBAC Feature Comparison

BDB provides **6 major feature categories** that NBAC doesn't:

| Feature | BDB | NBAC | Impact |
|---------|-----|------|--------|
| Shot coordinates | ✅ | ❌ | Heat maps, zone validation |
| Assisted/unassisted FG | ✅ | ❌ | Shot creation analysis |
| And-1 counts | ✅ | ❌ | FT volume, momentum |
| Blocks by zone | ✅ | ❌ | Defensive range |
| Full lineups (10 players) | ✅ | ❌ | On/off analysis |
| Rich timing data | ✅ | ❌ | Fatigue modeling |

### Accuracy Analysis

| Scenario | Hit Rate | MAE | Quality Tier |
|----------|----------|-----|--------------|
| **Without shot zones** | 36.3% | 6.21 | BRONZE |
| **NBAC fallback** | 37.0% | 6.07 | SILVER |
| **With BDB** | 38.6% | 5.25 | GOLD |

**Improvement**: +2.3% hit rate, -0.96 MAE when using BDB vs no shot zones

### Current Reprocessing Flow

```
BDB Data Arrives Late (45+ hours)
    ↓
[Phase 1] BDB catch-up workflows (10 AM, 2 PM, 6 PM ET)
    ↓
[Phase 2] Raw data updated (MERGE strategy)
    ↓
[Phase 3] player_game_summary reprocesses ✅
    ↓
[Phase 4] ML feature store updates ✅
    ↓
[Phase 5] ❌ Predictions NOT regenerated
```

**Gap**: Phase 5 predictions use stale features from NBAC fallback

---

## Implementation Roadmap

### Week 1: Foundation (IMMEDIATE)
- [ ] Extend BDB retry processor to trigger Phase 4-5
- [ ] Add `/regenerate-with-supersede` endpoint to coordinator
- [ ] Schema migrations (superseded columns)
- [ ] Basic testing

### Week 2: Production Rollout (HIGH PRIORITY)
- [ ] Deploy with dry-run testing
- [ ] Test on Jan 17-24 historical data
- [ ] Monitor first automatic trigger
- [ ] Enable for production

### Week 3: Quality & Analytics (MEDIUM PRIORITY)
- [ ] Backfill source tracking in grading table
- [ ] Analyze BDB vs NBAC accuracy delta
- [ ] Create BDB quality dashboard
- [ ] Calibrate confidence penalties

### Week 4: Optimization (LOW PRIORITY)
- [ ] Batch reprocessing optimization
- [ ] Advanced monitoring dashboards
- [ ] Runbooks for manual intervention
- [ ] Cost optimization

---

## File Guide

### EXECUTIVE-SUMMARY.md
**Purpose**: High-level project overview
**Audience**: Product managers, stakeholders
**Contents**:
- Problem statement and impact
- BDB vs NBAC comparison table
- Current vs proposed reprocessing flow
- Cost-benefit analysis
- Implementation roadmap
- Success metrics

### DECISION-MATRIX.md
**Purpose**: Strategy evaluation and recommendation
**Audience**: Technical leads, decision makers
**Contents**:
- 4 strategy options (Do Nothing, Phase 3-4 Only, Full Reprocessing, Selective)
- Scoring matrix with weighted criteria
- Risk analysis per strategy
- Phased implementation plan
- Final recommendation with rationale

### TECHNICAL-IMPLEMENTATION-GUIDE.md
**Purpose**: Detailed implementation specifications
**Audience**: Engineers implementing the solution
**Contents**:
- Code changes with line-by-line diffs
- Schema migrations (SQL)
- Pub/Sub topic configuration
- Testing plan (unit + integration tests)
- Deployment checklist
- Monitoring queries
- Rollback procedures

---

## Related Documentation

### Session 53 Handoffs
- [SESSION-53-BDB-RETRY-SYSTEM-HANDOFF.md](../../../09-handoff/2026-01-31-SESSION-53-BDB-RETRY-SYSTEM-HANDOFF.md) - BDB retry processor implementation
- [DOWNSTREAM-DATA-QUALITY-TRACKING.md](../../../09-handoff/2026-01-31-DOWNSTREAM-DATA-QUALITY-TRACKING.md) - Downstream source tracking analysis

### Shot Zone Investigations
- [SHOT-ZONE-DATA-INVESTIGATION.md](../../../09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md) - Shot zone data quality analysis
- [shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md](../shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md) - Shot zone fix plan

### Model Analysis
- [catboost-v8-jan-2026-incident/](../catboost-v8-jan-2026-incident/) - V8 model incident analysis
- [season-validation-2024-25/MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md](../season-validation-2024-25/MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md) - Model drift investigation

---

## Key Metrics to Monitor

### Pre-Implementation Baseline (Jan 17-24, 2026)
- BDB Coverage: 0-57% (48 of 61 games missing)
- Prediction Quality Tier: SILVER/BRONZE
- Accuracy: 36.3% hit rate, 6.21 MAE (without shot zones)

### Post-Implementation Targets
- BDB Coverage: ≥80% within 12 hours
- Prediction Quality Tier: ≥80% GOLD
- Accuracy: +2.3% hit rate improvement vs NBAC
- Reprocessing Latency: <6 hours (BDB arrival → new predictions)
- Cost: <$30/month

---

## FAQ

### Q: Why not just accept NBAC fallback?
**A**: Shot zones are #3 feature (11% importance). NBAC fallback provides +2.3% worse accuracy and lacks 6 feature categories (coordinates, assisted FG, and-1s, blocks, lineups, timing).

### Q: Is the cost worth it?
**A**: Yes. $15-25/month for +2.3% accuracy = $8.70 per accuracy point. User satisfaction and competitive advantage justify the investment.

### Q: Will predictions change after users see them?
**A**: Rarely. BDB usually arrives within 24 hours. Most users check <2 hours before game (after BDB arrives). Churn is ~5-10% of games and transparent to users.

### Q: What about games that already started?
**A**: We'll lock predictions at game start time. Reprocessing only applies to pre-game predictions.

### Q: Can we be more selective (Strategy D)?
**A**: Yes, but it adds complexity (threshold logic, inconsistent quality). Strategy C (full reprocessing) is cleaner and only ~$5-10/month more expensive.

---

## Next Steps

1. **Review Documentation**: Read EXECUTIVE-SUMMARY.md → DECISION-MATRIX.md → TECHNICAL-IMPLEMENTATION-GUIDE.md
2. **Approve Strategy C**: Confirm full reprocessing approach
3. **Start Week 1 Implementation**: Extend BDB retry processor
4. **Test on Jan 17-24**: Validate with real historical data
5. **Deploy to Production**: Monitor first automatic trigger

---

## Contact & Ownership

**Project Lead**: TBD
**Technical Owner**: TBD
**Started**: 2026-01-31 (Session 53)
**Target Completion**: Week 4 (optimization complete)
**Status**: ✅ Design Complete - Ready for Implementation

---

## Document Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-31 | 1.0 | Initial project documentation created |

---

**Last Updated**: 2026-01-31
**Next Review**: After Week 1 implementation complete
