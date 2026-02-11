# Q43 Performance Monitor

Daily monitoring script that compares the QUANT_43 shadow model (`catboost_v9_q43_train1102_0131`) against the production champion (`catboost_v9`) to determine when Q43 is ready for promotion.

## Background

Session 186 discovered that quantile regression (alpha=0.43) creates edge through systematic prediction bias built into the loss function. Unlike standard models that only perform well when stale, Q43's edge is staleness-independent. This monitor tracks whether that theoretical advantage translates to sustained production performance.

## Quick Start

```bash
# Standard daily check (last 7 days)
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py

# Custom date range
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --days 14

# Include Q45 model in comparison
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --include-q45

# Send Slack alert to #nba-alerts
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --slack

# JSON output for automation
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --json
```

## Reading the Output

### Daily Table

Shows day-by-day comparison of each model's performance:

- **HR**: Overall hit rate (all graded picks)
- **N**: Number of graded picks
- **3+ HR**: Hit rate for edge 3+ picks only (the metric that matters for betting)
- **3+ N**: Number of edge 3+ picks
- **Winner**: Which model had higher edge 3+ HR that day

### Summary Section

Aggregate metrics over the full period:

- **Weekly hit rate**: Overall HR with sample size
- **Edge 3+ HR**: The most important metric -- must be above 52.4% (breakeven) to be profitable
- **MAE**: Mean absolute error (lower is better for prediction accuracy, but NOT the same as betting performance)
- **Vegas bias**: Average (predicted - line). Q43 should be negative (predicts UNDER), around -1.5 to -2.0

### High-Edge Breakdown

- **Edge 3+**: Picks where model disagrees with Vegas by 3+ points. These are the actionable bets.
- **Edge 5+**: High-confidence subset. Higher HR expected but fewer picks.
- **UNDER/OVER split**: Q43 should be UNDER-heavy (by design). Champion should be more balanced.

### Statistical Confidence

- **LOW** (< 20 picks): Too early to draw conclusions
- **MODERATE** (20-49 picks): Directional signal but not definitive
- **HIGH** (50+ picks): Reliable comparison

### Recommendation

| Recommendation | Meaning | Action |
|---------------|---------|--------|
| **PROMOTE** | Q43 outperforming champion by 5+pp with sufficient data | Run promotion procedure (below) |
| **MONITOR** | Q43 performing acceptably, need more data or smaller advantage | Continue daily monitoring |
| **INVESTIGATE** | Q43 edge 3+ HR below 45% | Check model deployment, prediction volume, data issues |
| **INSUFFICIENT_DATA** | Fewer than 20 edge 3+ picks graded | Wait for more game days |
| **NO_DATA** | No Q43 graded data at all | Verify model is deployed and producing predictions |

## Alert Thresholds

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Q43 Edge 3+ HR | >= 60% | < 52.4% (breakeven) | < 45% |
| Q43 vs Champion advantage | >= 5pp | < 0pp | < -10pp |
| Daily actionable picks | >= 3/day | < 3/day | 0/day |
| Sample size (edge 3+) | >= 50 | < 20 | < 5 |
| Vegas bias | -1.0 to -2.0 | < -2.5 or > 0 | < -3.0 |

## Promoting Q43

When the monitor recommends PROMOTE, follow this procedure:

### Pre-Promotion Checklist

1. **Minimum 7 days of shadow data** with 50+ edge 3+ graded picks
2. **Edge 3+ HR >= 60%** sustained over the monitoring period
3. **Q43 beats champion by >= 5pp** on edge 3+ HR
4. **No systematic issues**: Vegas bias between -1.0 and -2.5
5. **Consistent daily performance**: Not driven by a single outlier day

### Promotion Steps

```bash
# 1. Verify current performance
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --days 14

# 2. Run full comparison with segments
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 14 --segments

# 3. Update production model path
gcloud run services update prediction-worker \
    --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_q0.43_train20251102-20260131_20260210_094854.cbm"

# 4. Update model registry
./bin/model-registry.sh promote catboost_v9_q43_train1102_0131

# 5. Verify deployment
./bin/check-deployment-drift.sh --verbose

# 6. Monitor first 24 hours closely
PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --days 1
```

### Rollback (if needed)

```bash
# Revert to original champion model
gcloud run services update prediction-worker \
    --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm"
```

## Cloud Scheduler Setup

The monitor runs daily at 8 AM ET via Cloud Scheduler:

```bash
# Deploy the scheduled job
./bin/monitoring/setup_q43_monitor_scheduler.sh

# Manual trigger
gcloud run jobs execute nba-q43-performance-monitor \
    --region us-west2 \
    --project nba-props-platform

# View recent runs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=nba-q43-performance-monitor" \
    --limit 10 \
    --project nba-props-platform
```

## Troubleshooting

### No Q43 data appearing

1. **Verify model is enabled** in `predictions/worker/prediction_systems/catboost_monthly.py`:
   ```python
   "catboost_v9_q43_train1102_0131": {
       "enabled": True,
       ...
   }
   ```

2. **Verify model is deployed**: Check prediction-worker has the latest code:
   ```bash
   gcloud run services describe prediction-worker --region=us-west2 \
       --format="value(metadata.labels.commit-sha)"
   ```

3. **Check quality gate**: Session 192 fixed a bug where quality gate hardcoded champion system_id, blocking shadow models. Verify the fix is deployed.

4. **Check prediction logs**:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND textPayload:q43" \
       --limit 20 --project nba-props-platform
   ```

### Q43 producing very few predictions

1. **Check daily prediction count**:
   ```sql
   SELECT game_date, COUNT(*) as predictions
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9_q43_train1102_0131'
     AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY 1 ORDER BY 1 DESC;
   ```

2. **Compare to champion volume**:
   ```sql
   SELECT system_id, game_date, COUNT(*) as predictions
   FROM nba_predictions.player_prop_predictions
   WHERE system_id IN ('catboost_v9', 'catboost_v9_q43_train1102_0131')
     AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY 1, 2 ORDER BY 2 DESC, 1;
   ```

3. Q43 naturally produces fewer actionable picks than the champion because its quantile bias means fewer picks cross the edge threshold. This is expected. Focus on hit rate, not volume.

### Grading not happening

1. **Check grading service is running**:
   ```bash
   gcloud run services describe phase5b-grading --region=us-west2 --format="value(status.conditions[0].status)"
   ```

2. **Check prediction_accuracy for recent Q43 entries**:
   ```sql
   SELECT MAX(graded_at), COUNT(*)
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9_q43_train1102_0131'
     AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY);
   ```

### Slack alerts not sending

1. Verify `SLACK_WEBHOOK_URL_WARNING` environment variable is set
2. Test locally: `PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --slack`
3. Check logs for "No Slack webhook URL configured" message

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Normal: PROMOTE, MONITOR, or INFO status |
| 1 | Warning: Performance below target but not critical |
| 2 | Critical: Performance below investigation threshold |

## Related Scripts

- `bin/compare-model-performance.py` -- Detailed model comparison with segment breakdowns
- `bin/monitoring/model_drift_detection.py` -- General model drift detection
- `bin/monitoring/weekly_model_drift_check.sh` -- Weekly drift check
- `bin/model-registry.sh` -- Model registry management
