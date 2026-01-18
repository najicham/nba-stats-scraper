# Option D: Next Steps

**Last Updated**: 2026-01-17
**Current Status**: Initial assessment complete, ready to implement

## Immediate Actions (Session 1 Continuation)

### Option 1: Quick Win - Promote CatBoost V8 (Recommended)

**Estimated Time**: 2-3 hours
**Risk**: LOW
**Value**: HIGH (immediate real ML in production)

#### Steps
1. **Analyze current ensemble logic** (30 min)
   - [ ] Read ensemble weighting in `predictions/worker/prediction_systems/ensemble_v1.py`
   - [ ] Identify where recommendations are generated
   - [ ] Map CatBoost V8 current role (shadow mode)

2. **Design promotion strategy** (30 min)
   - [ ] Create gradual rollout plan (10% → 50% → 100%)
   - [ ] Define success metrics and monitoring
   - [ ] Write rollback procedure

3. **Update configuration** (1 hour)
   - [ ] Change ensemble to weight V8 as primary system
   - [ ] Update confidence threshold logic
   - [ ] Add feature flags for gradual rollout (if needed)

4. **Test and validate** (30-60 min)
   - [ ] Run predictions in test mode
   - [ ] Compare V8 vs ensemble recommendations
   - [ ] Verify confidence scores
   - [ ] Check BigQuery output format

5. **Deploy and monitor** (30 min)
   - [ ] Deploy to Cloud Run
   - [ ] Monitor first batch of predictions
   - [ ] Validate accuracy vs Session 85 grading
   - [ ] Document results

**Success Criteria**:
- V8 controlling recommendations (not shadow mode)
- Confidence scores > 70% for actionable predictions
- No prediction failures
- Monitoring shows improved accuracy

---

### Option 2: Build Training Infrastructure (Parallel Track)

**Estimated Time**: 4-5 hours
**Risk**: LOW (no production impact)
**Value**: MEDIUM (ready for when Option C completes)

#### Steps
1. **Create XGBoost training script** (2-3 hours)
   - [ ] Set up `/ml_models/nba/train_xgboost_v1.py`
   - [ ] Implement feature extraction from BigQuery
   - [ ] Build training pipeline with validation split
   - [ ] Add model serialization to GCS
   - [ ] Create metadata tracking

2. **Test with limited data** (1 hour)
   - [ ] Train on Nov-Dec 2021 data (~60 days)
   - [ ] Validate model performance (expect lower MAE on limited data)
   - [ ] Verify GCS upload works
   - [ ] Test model loading in worker

3. **Document training process** (30 min)
   - [ ] Write training README
   - [ ] Document required features
   - [ ] Create retraining procedure
   - [ ] Add troubleshooting guide

**Success Criteria**:
- Training script runs successfully
- Model saved to GCS with versioning
- Worker can load trained model
- Documentation complete

---

### Option 3: Deploy Prediction Coordinator

**Estimated Time**: 3-4 hours
**Risk**: MEDIUM (new infrastructure)
**Value**: HIGH (enables automation)

#### Steps
1. **Create Dockerfile** (1 hour)
   - [ ] Set up `/docker/nba-prediction-coordinator.Dockerfile`
   - [ ] Base: Python 3.11 slim
   - [ ] Dependencies: Flask, BigQuery, Pub/Sub, requests
   - [ ] Health check endpoint
   - [ ] Test local build

2. **Create coordinator service** (2 hours)
   - [ ] Flask endpoint for Pub/Sub messages
   - [ ] Player determination logic (who needs predictions)
   - [ ] Batch prediction triggering
   - [ ] Error handling and retries
   - [ ] Logging and monitoring

3. **Deployment script** (1 hour)
   - [ ] Create `/bin/predictions/deploy/deploy_prediction_coordinator.sh`
   - [ ] Build and push Docker image
   - [ ] Deploy to Cloud Run
   - [ ] Configure environment variables
   - [ ] Set up service account permissions
   - [ ] Health check validation

**Success Criteria**:
- Coordinator deployed to Cloud Run
- Health endpoint responds
- Can receive test Pub/Sub messages
- Triggers predictions on worker
- Logging works correctly

---

## Recommended Sequence

### Week 1: Quick Wins + Foundation
**Day 1-2**: Promote CatBoost V8 to production (Option 1)
**Day 3-4**: Build XGBoost training infrastructure (Option 2)
**Day 5**: Test and validate both changes

### Week 2: Automation
**Day 1-2**: Deploy prediction coordinator (Option 3)
**Day 3**: Set up Phase 4 → Phase 5 Pub/Sub integration
**Day 4-5**: Monitoring and alerting setup

### Week 3: Full Production (when Option C completes)
**Day 1-2**: Retrain XGBoost with full historical data
**Day 3**: Deploy trained models
**Day 4**: Enable automated retraining schedule
**Day 5**: Final validation and documentation

---

## Prerequisites to Check

Before starting, verify:
- [ ] Cloud Run access working
- [ ] BigQuery access to all required tables
- [ ] GCS bucket permissions for model storage
- [ ] Pub/Sub topic/subscription creation permissions
- [ ] Service account has correct IAM roles
- [ ] Local development environment ready

---

## Open Questions

1. **Option C Timeline**: When will Option C backfill complete?
   - Affects: XGBoost training timeline
   - Workaround: Build scripts now, train later

2. **Staging Environment**: Do we have a staging/test environment?
   - Affects: Risk of V8 promotion
   - Mitigation: Gradual rollout if no staging

3. **Monitoring Setup**: Is Cloud Monitoring already configured?
   - Affects: Alert setup timeline
   - Reference: Session 85 grading monitoring patterns

4. **Risk Tolerance**: What's acceptable for V8 gradual rollout?
   - 10% → 50% → 100% over 3 days?
   - Or immediate 100% switch?

---

## Risk Mitigation

### CatBoost V8 Promotion Risks
- **Risk**: V8 performs worse than expected in production
- **Mitigation**: Gradual rollout, keep old systems running
- **Rollback**: Feature flag to disable V8, revert to ensemble

### Training Infrastructure Risks
- **Risk**: Limited data produces poor models
- **Mitigation**: Clearly mark as "test mode" until Option C complete
- **Validation**: Compare to V8 baseline (3.40 MAE)

### Coordinator Deployment Risks
- **Risk**: New service failures disrupt predictions
- **Mitigation**: Deploy alongside existing worker, test thoroughly
- **Rollback**: Keep manual trigger path working

---

## Success Metrics

### Phase 1 (CatBoost V8)
- [ ] V8 is primary system (70%+ of recommendations)
- [ ] Prediction accuracy ≥ 71.6% (V8 baseline)
- [ ] No production failures
- [ ] Confidence scores appropriate (60-90% range)

### Phase 2 (Training Infrastructure)
- [ ] Script trains successfully on available data
- [ ] Model MAE ≤ 4.0 on test set
- [ ] GCS versioning works
- [ ] Documentation complete

### Phase 3 (Coordinator)
- [ ] Coordinator responds to Pub/Sub messages
- [ ] Triggers predictions for all scheduled players
- [ ] Coverage ≥ 95%
- [ ] Latency < 5 minutes for 450 players

---

## Related Documentation

- **Implementation Guide**: `/docs/09-handoff/OPTION-D-PHASE5-DEPLOYMENT-HANDOFF.md`
- **Start Prompt**: `/docs/09-handoff/OPTION-D-START-PROMPT.txt`
- **Option C Status**: `/docs/09-handoff/OPTION-C-BACKFILL-ADVANCEMENT-HANDOFF.md`
- **Session 85 Grading**: For prediction accuracy measurement
- **Project README**: `./README.md`
- **Session Log**: `./SESSION-LOG.md`

---

**Recommendation**: Start with **Option 1 (CatBoost V8 Promotion)** for immediate value, then proceed to **Option 2 (Training Infrastructure)** and **Option 3 (Coordinator)** in parallel.
