# BDB Reprocessing Strategy: Decision Matrix

**Project**: BigDataBall Reprocessing Strategy
**Date**: 2026-01-31
**Purpose**: Evaluate different approaches to handling late-arriving BDB data

---

## Strategy Options

We evaluated 4 different strategies for handling late-arriving BigDataBall data:

| Strategy | Description | Complexity | Cost | Accuracy Impact |
|----------|-------------|------------|------|-----------------|
| **A. Do Nothing** | Accept NBAC fallback, no reprocessing | Low | $0 | Baseline |
| **B. Phase 3-4 Only** | Reprocess features, skip predictions | Medium | $5-10/mo | +0% |
| **C. Full Reprocessing** | Reprocess + regenerate predictions | High | $15-25/mo | +2.3% |
| **D. Selective Reprocessing** | Only reprocess if quality tier changes | High | $10-15/mo | +1.5% |

---

## Detailed Comparison

### Strategy A: Do Nothing (Baseline)

**Implementation**:
- Current state - no changes
- Accept NBAC fallback when BDB unavailable
- Predictions use degraded features

**Pros**:
- ✅ Zero implementation cost
- ✅ No operational complexity
- ✅ No additional compute costs
- ✅ System already works this way

**Cons**:
- ❌ -2.3% accuracy vs full BDB
- ❌ SILVER/BRONZE quality tier vs GOLD
- ❌ Inconsistent prediction quality
- ❌ User trust issues ("why did quality drop?")
- ❌ Competitive disadvantage

**Cost**: $0/month

**Recommendation**: ❌ **NOT RECOMMENDED** - Accuracy degradation unacceptable

---

### Strategy B: Phase 3-4 Only (Feature Update Without Prediction Regeneration)

**Implementation**:
- Trigger Phase 3-4 when BDB arrives (CURRENT STATE)
- Update features in `ml_feature_store_v2`
- Do NOT regenerate predictions
- Future predictions use new features

**Pros**:
- ✅ Minimal implementation (already done in Session 53)
- ✅ Features stay current for future predictions
- ✅ Low operational cost
- ✅ No prediction churn

**Cons**:
- ❌ Old predictions stuck with NBAC fallback features
- ❌ No accuracy improvement for affected games
- ❌ Inconsistent historical data quality
- ❌ Grading analysis polluted (mix of SILVER and GOLD predictions)

**Cost**: $5-10/month (Phase 3-4 reprocessing only)

**Recommendation**: ⚠️ **PARTIAL SOLUTION** - Helps future predictions but doesn't fix historical

---

### Strategy C: Full Reprocessing (RECOMMENDED)

**Implementation**:
- Trigger Phase 3-4-5 when BDB arrives
- Mark old predictions as "superseded"
- Generate new predictions with BDB features
- Re-grade if game complete

**Pros**:
- ✅ +2.3% accuracy improvement for affected games
- ✅ Consistent GOLD quality tier
- ✅ Clean historical data for analysis
- ✅ User trust maintained (best predictions always shown)
- ✅ Competitive advantage

**Cons**:
- ❌ Higher implementation complexity (2-3 days)
- ❌ Moderate compute cost ($15-25/month)
- ❌ Prediction "churn" (predictions change post-publication)
- ❌ Requires schema migrations

**Cost**: $15-25/month

**Recommendation**: ✅ **RECOMMENDED** - Best long-term solution for quality

---

### Strategy D: Selective Reprocessing (Quality Tier Threshold)

**Implementation**:
- Only regenerate if quality tier improves significantly
- Example: BRONZE → GOLD (yes), SILVER → GOLD (maybe), GOLD → GOLD (no)
- Threshold: Only if feature completeness improves >20%

**Pros**:
- ✅ Reduced compute cost vs Strategy C ($10-15/month)
- ✅ Less prediction churn
- ✅ Focuses on biggest quality gaps
- ✅ Still maintains high standards

**Cons**:
- ❌ Complex threshold logic (when to regenerate?)
- ❌ Inconsistent approach (some SILVER predictions kept)
- ❌ Harder to explain to users
- ❌ Still requires full implementation

**Cost**: $10-15/month

**Recommendation**: ⚠️ **ALTERNATIVE** - Good middle ground but adds complexity

---

## Decision Criteria Scoring

| Criterion | Weight | Strategy A | Strategy B | Strategy C | Strategy D |
|-----------|--------|------------|------------|------------|------------|
| **Accuracy Improvement** | 35% | 0 | 0 | 10 | 7 |
| **Implementation Cost** | 15% | 10 | 8 | 3 | 2 |
| **Operational Cost** | 10% | 10 | 8 | 5 | 6 |
| **User Experience** | 25% | 3 | 5 | 10 | 7 |
| **System Consistency** | 15% | 2 | 4 | 10 | 6 |
| **WEIGHTED TOTAL** | 100% | **3.65** | **4.85** | **8.20** | **6.20** |

**Winner**: **Strategy C (Full Reprocessing)** with 8.20/10 score

---

## Key Trade-offs

### Cost vs Quality

```
Strategy A (Do Nothing):    $0/mo  →  Baseline accuracy
Strategy B (Phase 3-4):     $5/mo  →  +0% accuracy (future only)
Strategy C (Full):          $20/mo →  +2.3% accuracy (all games)
Strategy D (Selective):     $12/mo →  +1.5% accuracy (selective)
```

**ROI**: Strategy C costs $20/month for +2.3% accuracy = **$8.70 per accuracy point**

### Complexity vs Consistency

- **Strategy A/B**: Simple but inconsistent quality
- **Strategy C**: Complex but fully consistent
- **Strategy D**: Very complex (threshold logic) + partially consistent

**Winner**: Strategy C - Complexity pays off in consistency

### Churn vs Correctness

**Prediction Churn** (how often predictions change):
- Strategy A/B: 0% churn (predictions never change)
- Strategy C: ~5-10% churn (when BDB arrives late for ~5-10% of games)
- Strategy D: ~2-5% churn (only worst quality gaps)

**User Impact**:
- Most users check predictions <2 hours before game
- BDB reprocessing happens within 45 hours (before most users check)
- Churn is transparent (users see "best" prediction always)

**Winner**: Strategy C - Churn is acceptable for correctness

---

## Risk Analysis

### Strategy C Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Cost Overrun** | Medium | Low | Batch reprocess, cache queries |
| **Prediction Churn Confusion** | Low | Medium | Add "Last updated" timestamp |
| **Feature Version Conflicts** | Low | High | Use version hash, test thoroughly |
| **Grading Complexity** | Low | Medium | Track superseded vs original |
| **Deployment Issues** | Medium | High | Phased rollout, dry-run testing |

### Strategy D Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Threshold Too Aggressive** | High | Medium | Start conservative (BRONZE only) |
| **Threshold Too Lenient** | Medium | Medium | Monitor quality metrics |
| **User Confusion** | Medium | High | Inconsistent "why regenerate?" logic |
| **Implementation Bugs** | High | High | Complex conditionals = more bugs |

**Risk Winner**: Strategy C - Fewer complex conditionals, lower bug risk

---

## Stakeholder Impact

### Users (Prediction Consumers)

**Strategy C Impact**:
- ✅ Always see best predictions (GOLD quality when possible)
- ✅ No action required (transparent upgrades)
- ⚠️ Predictions may change before game (rare, acceptable)

### Data Analysts

**Strategy C Impact**:
- ✅ Clean historical data (all GOLD quality)
- ✅ Can filter superseded predictions for analysis
- ✅ Audit trail for regeneration events

### Operations Team

**Strategy C Impact**:
- ⚠️ More complex reprocessing pipeline
- ✅ Automated (no manual intervention)
- ✅ Good monitoring/alerting

---

## Phased Implementation Plan

We recommend implementing Strategy C in phases:

### Phase 1: Foundation (Week 1) - IMMEDIATE

**Goal**: Get basic reprocessing working

**Deliverables**:
- Extend BDB retry processor to trigger Phase 4-5
- Add superseding endpoint to prediction coordinator
- Schema migrations (superseded columns)
- Basic testing

**Risk**: Low - Builds on Session 53 work

### Phase 2: Production Rollout (Week 2) - HIGH PRIORITY

**Goal**: Deploy to production with safeguards

**Deliverables**:
- Deploy with DRY_RUN=true first
- Test on Jan 17-24 historical data
- Monitor first automatic trigger
- Enable for real

**Risk**: Medium - First production reprocessing

### Phase 3: Quality & Analytics (Week 3) - MEDIUM PRIORITY

**Goal**: Add source tracking to grading

**Deliverables**:
- Backfill source columns in prediction_accuracy
- Analyze BDB vs NBAC accuracy delta
- Calibrate confidence penalties if needed
- Create BDB quality dashboard

**Risk**: Low - Analytics improvements

### Phase 4: Optimization (Week 4) - LOW PRIORITY

**Goal**: Reduce costs, improve monitoring

**Deliverables**:
- Batch reprocessing optimization
- Advanced monitoring dashboards
- Runbooks for manual intervention
- Consider Strategy D thresholds (optional)

**Risk**: Low - Refinements only

---

## Final Recommendation

### Recommended Strategy: **C (Full Reprocessing)**

**Rationale**:
1. **Highest accuracy impact**: +2.3% hit rate improvement
2. **Best user experience**: Always show best predictions
3. **Clean data**: Consistent GOLD quality for analysis
4. **Acceptable cost**: $15-25/month is reasonable ROI
5. **Manageable complexity**: 2-3 days implementation vs permanent quality issues

**Alternative Strategy**: **D (Selective)** if cost is a major concern

**Reject**: **A (Do Nothing)** - Unacceptable quality degradation
**Reject**: **B (Phase 3-4 Only)** - Doesn't fix historical predictions

---

## Decision Questions

### Question 1: Should we regenerate predictions after game starts?

**Options**:
- A. Yes - Always keep predictions current
- B. No - Lock predictions at game start
- C. Hybrid - Only before game start

**Recommendation**: **B (No)** - Lock at game start

**Rationale**:
- Grading uses prediction at game start time
- Regenerating mid-game confuses grading
- Users expect predictions to be "locked in"

### Question 2: How long to keep superseded predictions?

**Options**:
- A. 30 days (audit window)
- B. Forever (unlimited audit trail)
- C. 7 days (minimal)

**Recommendation**: **B (Forever)** - Storage is cheap

**Rationale**:
- Helps debug historical issues
- Enables "before/after" analysis
- BigQuery storage cost is minimal (~$0.02/GB/month)

### Question 3: Should we alert users when predictions change?

**Options**:
- A. Yes - Send notification "Prediction updated"
- B. No - Silent upgrade
- C. Hybrid - Only if user actively viewing

**Recommendation**: **B (No)** - Silent upgrade

**Rationale**:
- Most users check <2 hours before game (after BDB arrives)
- Notification creates anxiety ("why did it change?")
- "Last updated" timestamp provides transparency

---

## Success Criteria

After implementing Strategy C, we expect:

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Accuracy Improvement** | +2.0% hit rate | Compare BDB vs NBAC predictions |
| **Quality Tier** | ≥80% GOLD tier | % of predictions with full BDB data |
| **Reprocessing Latency** | <6 hours | BDB arrival → new predictions |
| **Superseding Accuracy** | 100% | All old predictions marked |
| **Cost** | <$30/month | BigQuery + compute costs |
| **User Complaints** | <5/month | "Quality inconsistent" tickets |

---

## Conclusion

**Strategy C (Full Reprocessing)** is the clear winner based on:
- Highest accuracy impact (+2.3%)
- Best user experience (consistent quality)
- Acceptable cost ($15-25/month)
- Manageable implementation (2-3 days)

While Strategy D (Selective) saves ~$5-10/month, the added complexity and inconsistency outweigh the savings. Strategy C provides a clean, predictable system with measurable ROI.

**Next Steps**:
1. ✅ Approve Strategy C
2. Start Week 1 implementation (extend retry processor)
3. Test on Jan 17-24 historical data
4. Deploy to production with monitoring

---

**Document Status**: ✅ Ready for Approval
**Recommended Decision**: Implement Strategy C (Full Reprocessing)
**Owner**: TBD
**Review Date**: 2026-01-31
