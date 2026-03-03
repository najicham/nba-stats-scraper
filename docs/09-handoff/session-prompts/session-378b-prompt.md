# Session 378b Continuation Plan

## Context from Session 378

**Deployed:** XGBoost DMatrix fix (now producing predictions), OVER edge 5+ floor, cross_model_subsets XGBoost family, LightGBM/XGBoost affinity mappings.

**Key findings:**
- XGBoost model produces 134 predictions but ALL UNDER (avg predicted 4.9 pts) — extreme UNDER bias, needs investigation
- Edge 3-5 OVER = 25% HR — now blocked by OVER edge 5+ floor
- catboost_v12 champion = 25% HR (1-3) in best bets Feb 19-28 — worst performer
- v12_noveg_q43 still appearing in best bets despite supposed DISABLE — needs investigation
- v9_low_vegas = 100% (3-0) — best recent performer
- CatBoost+XGBoost disagreement = 41% HR (N=83) — potential negative filter when data accumulates
- Line check scheduler blocked by IAM permission

---

## Priority 1: Investigate XGBoost UNDER Bias (30 min)

The XGBoost model predicts avg 4.9 points — clearly not calibrated for absolute points. Two possibilities:
1. The model was trained on a different label scale (e.g., actual-line deviation instead of absolute points)
2. XGBoost's tree structure is different from CatBoost and needs different hyperparameters

**Steps:**
- Check `quick_retrain.py --framework xgboost` training code — is the label y_train the same as CatBoost?
- Check training logs: what was the eval MAE? If MAE was 4.99 on eval, the model IS predicting points correctly.
- Actually, the registry says `evaluation_mae: 4.99` — that's reasonable. The issue may be that XGBoost is predicting correctly but with a systematic offset.
- Run: Compare XGBoost predictions vs CatBoost predictions for the same players today. If XGBoost is consistently 10-15 points below CatBoost, there's a calibration issue.
- If the model is genuinely miscalibrated, consider adding a bias correction or retraining with different parameters.

## Priority 2: Investigate v12_noveg_q43 Still Active (15 min)

Per CLAUDE.md, `catboost_v12_noveg_q43_train0104_0215` should be DISABLED (14.8% HR live). But it appeared in 5 best bets picks (50% HR) Feb 19-28.

**Steps:**
- Check registry: `bq query "SELECT model_id, enabled, status FROM nba_predictions.model_registry WHERE model_id LIKE '%q43%'"`
- If enabled=TRUE, disable it: `UPDATE model_registry SET enabled=FALSE WHERE model_id='catboost_v12_noveg_q43_train0104_0215'`
- Check if it was re-enabled by accident or if there's a different q43 model

## Priority 3: Fix Line Check Scheduler IAM (10 min)

**Run:**
```bash
gcloud iam service-accounts add-iam-policy-binding \
  756957797294-compute@developer.gserviceaccount.com \
  --member='user:nchammas@gmail.com' \
  --role='roles/iam.serviceAccountUser' \
  --project=nba-props-platform
```
Then: `bash bin/orchestrators/setup_line_check_scheduler.sh`

Also create 3:30 PM ET re-export scheduler:
```bash
gcloud scheduler jobs create http phase6-afternoon-reexport \
  --location=us-west2 \
  --schedule="30 15 * * *" \
  --time-zone="America/New_York" \
  --uri="PHASE6_TRIGGER_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"export_types": ["signal-best-bets"], "target_date": "today"}' \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --description="Session 378: Afternoon re-export after line movements"
```

## Priority 4: Model Champion Evaluation (30 min)

catboost_v12 champion = 25% HR in best bets is alarming. v9_low_vegas is the best recent performer.

**Steps:**
- Run full fleet evaluation for Feb 15-28 at best bets level (not raw)
- Check which models are contributing winning picks vs losing picks
- Consider whether v9_low_vegas should be promoted to champion or given higher weight
- Evaluate new Session 377-378 models that are now accumulating data

## Priority 5: New Experiment Angles (45 min)

Based on session 378 findings:

### E1: SC=3 OVER edge 7+ gate expansion
The SC=3 OVER edge 7+ gate already exists. But SC=3 overall is weakest at 55.1%. Consider:
- SC=3 UNDER also needs edge 5+? (Currently SC=3 UNDER is 62.5% — actually profitable)
- SC=4+ floor for OVER only? (SC=4+ OVER would be very restrictive)

### E2: Framework disagreement filter (when XGBoost has data)
CatBoost+XGBoost disagreement = 41% HR. Once XGBoost accumulates 2+ weeks of graded data:
- Implement negative filter: block picks where CatBoost and XGBoost disagree on direction
- Start with OVER only (most disagreements were OVER)

### E3: Retrain with March data
Training data currently ends Feb 8 (most models). Consider:
- Retrain v12_noveg + vw015 with window ending Feb 28
- Use 49-day window (Jan 10 - Feb 28)
- This captures the February regime shift in training data

### E4: Model-level hit rate in aggregator
The aggregator currently uses model HR-weighted selection. But catboost_v12 at 25% HR is STILL winning selection 4 times. Investigate:
- Is the HR weight decaying fast enough?
- Is the 14-day lookback too long? Try 7-day
- Should we temporarily block catboost_v12 from best bets?

## Priority 6: Tonight's Game Monitoring (ongoing)

11 games tonight. After games complete:
- Grade today's picks
- Check XGBoost vs CatBoost prediction accuracy
- Verify OVER edge 5+ floor is filtering correctly in tonight's export
- Check if the afternoon line check would have caught any line movements (manual check since scheduler isn't set up yet)
