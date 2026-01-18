# Option D: Phase 5 Production ML Deployment

**Project Start Date**: 2026-01-17
**Status**: Initial Assessment Complete
**Goal**: Train and deploy real production ML models to replace mocks

## Overview

This project implements Phase 5 of the NBA prediction system - moving from mock/placeholder ML models to real trained production models with automated training pipeline.

## Business Value

- Real ML predictions (not mock/placeholder)
- Automated model training pipeline
- Backtesting capability
- Production-grade prediction coordinator
- Foundation for continuous model improvement

## Project Scope

### Phase 5A: Model Training Infrastructure (4-5 hours)
- [ ] Feature engineering pipeline for training
- [ ] XGBoost model training script
- [ ] Training data validation
- [ ] Model evaluation and metrics
- [ ] Model versioning and storage (GCS)

### Phase 5B: Model Deployment (3-4 hours)
- [ ] Update prediction-worker to load trained models
- [ ] Model serving infrastructure
- [ ] A/B testing capability (optional)
- [ ] Rollback mechanism

### Phase 5C: Prediction Coordinator (4-5 hours)
- [ ] Orchestration of prediction flow
- [ ] Ensemble model coordination (if multiple models)
- [ ] Prediction aggregation and consensus
- [ ] Quality scoring and filtering

### Phase 5D: Automation & Monitoring (2-3 hours)
- [ ] Automated daily/weekly retraining schedule
- [ ] Model performance monitoring
- [ ] Training job failure alerts
- [ ] Model drift detection

**Expected Time**: 13-16 hours total

## Current System State (2026-01-17)

### ✅ What's Already Working

1. **CatBoost V8 Model - PRODUCTION READY**
   - MAE: 3.40 (vs mock's ~4.80)
   - Accuracy: 71.6% betting accuracy
   - Edge: Beats Vegas by 25% on 2024-25 out-of-sample
   - Status: Deployed in shadow mode
   - Model: `models/catboost_v8_33features_20260108_211817.cbm`

2. **Prediction Worker Architecture**
   - 6 prediction systems running (4 rule-based + 2 ML)
   - Per-player latency: ~200-300ms
   - Cloud Run deployment with auto-scaling (0-20 instances)
   - Batch processing: 450 players in 2-3 minutes

3. **ML Feature Store V2**
   - 33 features available (v2_33features)
   - Processing time: ~2 minutes for 450 players
   - Quality scoring: 0-100 with tiering
   - Table: `nba_predictions.ml_feature_store_v2`

4. **Infrastructure**
   - Cloud Run deployment scripts ready
   - BigQuery schemas defined
   - GCS storage configured
   - Pub/Sub integration exists

### ❌ What's Missing/Mock

1. **XGBoost V1 - Using Mock Model**
   - Current: Heuristic-based simulator (NOT real ML)
   - File: `predictions/shared/mock_xgboost_model.py`
   - Type: Hand-crafted logic simulating ML
   - Needs: Real XGBoost trained on historical data

2. **Historical Training Data**
   - **Option C backfill: Only ~15% complete**
     - ✅ Nov 2021: 100% done
     - ⏳ Dec 2021: 71% done
     - ❌ 2022-2024: Not started
     - ❌ 2025-present: Not started
   - **Remaining work**: ~15 hours of automated processing
   - **Risk**: Can't train production-quality models without this

3. **Prediction Coordinator**
   - Code written but not deployed
   - Needs: Docker container, Cloud Run deployment
   - Integration: Phase 4 → Phase 5 Pub/Sub missing

4. **Automated Training Pipeline**
   - No scheduled retraining
   - No model versioning system
   - No performance monitoring

## Critical Prerequisite Issue

**⚠️ BLOCKER: Option C Backfill Not Complete**

The start prompt states:
> "PREREQUISITE: Option C (Backfill Pipeline) must be substantially complete"
> "Need: Historical data from Nov 2021 → Present for model training"
> "Minimum: 80%+ date coverage with quality data"

**Current Status**: ~15% complete (only Nov 2021 fully done)

**Options**:
1. **Wait for Option C** - Lower risk, aligns with documented requirements
2. **Build infrastructure now, train later** - Set up training scripts/deployment, train when data ready
3. **Promote CatBoost V8 to production** - Quick win, already validated

## Decision: Hybrid Approach

We'll proceed with **Option 2 + 3**:

1. **Immediate (Phase 1)**: Promote CatBoost V8 from shadow to production
   - Already trained and validated
   - 3.40 MAE performance proven
   - Low risk deployment

2. **Parallel (Phase 2-4)**: Build training infrastructure
   - Create XGBoost training scripts (ready for when Option C completes)
   - Deploy prediction coordinator
   - Set up monitoring and automation
   - Test with limited Nov-Dec 2021 data

3. **Future (when Option C complete)**: Full production training
   - Retrain XGBoost with 3+ years of data
   - Deploy alongside CatBoost V8 for ensemble
   - Automated retraining pipeline active

## Key Files & Locations

### Existing Code
- **Prediction Worker**: `/predictions/worker/worker.py` (1,487 lines)
- **CatBoost V8 System**: `/predictions/worker/prediction_systems/catboost_v8.py`
- **Mock XGBoost**: `/predictions/shared/mock_xgboost_model.py`
- **Feature Store Processor**: `/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- **Models Directory**: `/models/` (local) or GCS

### Documentation
- **Implementation Guide**: `/docs/09-handoff/OPTION-D-PHASE5-DEPLOYMENT-HANDOFF.md`
- **Start Prompt**: `/docs/09-handoff/OPTION-D-START-PROMPT.txt`
- **Project Docs**: `/docs/08-projects/current/option-d-ml-deployment/` (this directory)

### New Files to Create
- `/ml_models/nba/train_xgboost_v1.py` - Training script
- `/docker/nba-prediction-coordinator.Dockerfile` - Coordinator container
- `/bin/predictions/deploy/deploy_prediction_coordinator.sh` - Deployment script
- `/bin/predictions/setup_phase5_pubsub.sh` - Pub/Sub integration
- `/bin/alerts/setup_phase5_alerts.sh` - Monitoring alerts

## Success Metrics

- [ ] CatBoost V8 promoted to primary system (confidence > 70%)
- [ ] XGBoost training infrastructure ready (scripts + deployment)
- [ ] Prediction coordinator deployed to Cloud Run
- [ ] Phase 4 → Phase 5 Pub/Sub integration working
- [ ] Model performance monitoring active
- [ ] No production incidents during deployment
- [ ] When Option C complete: Retrain and deploy with full historical data

## Risk Assessment

**Current Risk Level**: MEDIUM
- Promoting CatBoost V8: LOW (already validated)
- Building infrastructure: LOW (no production impact)
- Training without full data: MEDIUM (models won't be production-quality yet)

**Mitigation**:
- Gradual rollout of V8 (10% → 50% → 100%)
- Keep existing systems running in parallel
- Build infrastructure with test/validation mode
- Clear rollback procedures

## Related Projects

- **Option C**: Historical backfill (prerequisite for full training)
- **Session 85**: NBA grading system (measures prediction accuracy)
- **Email Alerting**: Alert delivery system for predictions

## Session Log

See [SESSION-LOG.md](./SESSION-LOG.md) for detailed progress tracking.

## Next Steps

See [NEXT-STEPS.md](./NEXT-STEPS.md) for immediate action items.
