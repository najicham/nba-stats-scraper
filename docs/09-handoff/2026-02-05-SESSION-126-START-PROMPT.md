# Session 126 Start Prompt

## Context from Session 125B

Session 125B built comprehensive **breakout detection infrastructure** to improve role player UNDER bet performance. The work is committed but **NOT DEPLOYED**.

### Key Problem Solved
Role player (8-16 PPG) UNDER bets were losing money:
- Edge 3-5: 42% hit rate
- Hot streak players: 14% hit rate
- Low quality data: 39% hit rate

### What Was Built

**1. Three New Filters (in prediction worker):**
```python
# Filter 1: Role player UNDER with low edge
if 8 <= season_avg <= 16 and edge < 5 and recommendation == 'UNDER':
    filter_reason = 'role_player_under_low_edge'

# Filter 2: Hot streak UNDER (L5 > season + 3)
if l5_avg - season_avg > 3 and recommendation == 'UNDER':
    filter_reason = 'hot_streak_under_risk'

# Filter 3: Low data quality
if quality_score < 80:
    filter_reason = 'low_data_quality'
```

**2. Breakout Classifier Training Script:**
- Location: `ml/experiments/train_breakout_classifier.py`
- Target: `is_breakout = 1 if actual_points >= season_avg * 1.5`
- 10 features including `explosion_ratio`, `days_since_breakout`
- NOT YET TRAINED - infrastructure only

**3. Breakout Risk Score Calculator:**
- Location: `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py`
- Score 0-100 combining: hot streak (30%), volatility (20%), opponent defense (20%), opportunity (15%), historical rate (15%)
- 30 unit tests (all passing)
- NOT YET INTEGRATED into feature store

**4. Quality Propagation to Grading:**
- `feature_quality_score` now flows to `prediction_accuracy` table
- New `data_quality_tier` field: HIGH/MEDIUM/LOW

**5. Monitoring Queries:**
- Location: `validation/queries/monitoring/breakout_filter_monitoring.sql`
- 6 queries for tracking filter performance

### Commits (NOT DEPLOYED)
```
f59e4c37 - feat: Add quality filters and propagate quality to grading
95bcc254 - feat: Strengthen role player UNDER filter and add breakout monitoring
6e8f7079 - feat: Add hot streak UNDER filter and breakout classifier infrastructure
3e8f35ef - feat: Add breakout_risk_score calculator with tests and design docs
```

---

## Priority Actions for This Session

### P1: Deploy Changes
```bash
./bin/deploy-service.sh prediction-worker

# Verify
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should show: 1e3a99d1
```

### P2: Train Breakout Classifier (Optional)
```bash
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_V1" \
    --train-start 2025-11-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-04
```
Target: AUC >= 0.65

### P3: Integrate breakout_risk_score
Add to feature store pipeline as Feature 37.

### P4: Monitor Filter Performance
After games complete, run:
```sql
SELECT filter_reason, COUNT(*) as filtered,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as would_have_hit
FROM nba_predictions.prediction_accuracy
WHERE is_actionable = false AND filter_reason IS NOT NULL
  AND game_date >= CURRENT_DATE() - 3
GROUP BY 1
```

---

## Key Documentation

- **Handoff:** `docs/09-handoff/2026-02-05-SESSION-125B-BREAKOUT-DETECTION-HANDOFF.md`
- **Implementation:** `docs/08-projects/current/breakout-detection-design/SESSION-125-IMPLEMENTATION.md`
- **Risk Score Design:** `docs/08-projects/current/breakout-risk-score/BREAKOUT-RISK-SCORE-DESIGN.md`
- **Monitoring Queries:** `validation/queries/monitoring/breakout_filter_monitoring.sql`

---

## Quick Verification Commands

```bash
# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Verify new files exist
ls -la ml/experiments/train_breakout_classifier.py
ls -la data_processors/precompute/ml_feature_store/breakout_risk_calculator.py

# Run breakout risk score tests
PYTHONPATH=. python -m pytest tests/processors/precompute/ml_feature_store/test_breakout_risk_calculator.py -v

# Check recent commits
git log --oneline -6
```

---

## Expected Outcomes

After deploying and training:
- Role player UNDER hit rate: 42% → 55-62%
- Overall UNDER ROI improvement: +5-12%
- Breakout classifier AUC: >= 0.65
