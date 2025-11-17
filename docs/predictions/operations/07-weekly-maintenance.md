# Phase 5: Weekly Maintenance

**File:** `docs/predictions/operations/07-weekly-maintenance.md`
**Created:** 2025-11-16
**Purpose:** Weekly operational maintenance checklist for Phase 5 prediction services - performance review, data quality checks, cost analysis
**Status:** ✅ Production Ready

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Monday Morning Review (15 Minutes)](#monday-review)
3. [Week-Over-Week Comparison](#week-comparison)
4. [System Health Check](#system-health)
5. [Operations Log Template](#operations-log)
6. [Related Documentation](#related-docs)

---

## 🎯 Overview {#overview}

### Purpose

Weekly maintenance ensures your prediction systems remain healthy, performant, and cost-effective. This checklist helps you:
- **Track trends** - Identify improving or declining performance
- **Catch issues early** - Spot problems before they become critical
- **Optimize costs** - Ensure infrastructure spending is reasonable
- **Document findings** - Maintain operational history

### When to Run

**Day:** Monday mornings
**Time:** 15 minutes
**Frequency:** Every week during NBA season

### Quick Summary

```bash
# Generate weekly report
python monitoring/weekly_analysis.py

# Review trends and document findings
# Check cloud costs
# Update operations log
```

---

## 🌅 Monday Morning Review (15 Minutes) {#monday-review}

### Step 1: Generate Weekly Report

Run this query to get week-over-week comparison:

```sql
WITH this_week AS (
  SELECT
    system_id,
    COUNT(*) as predictions,
    AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as accuracy,
    AVG(ABS(predicted_points - actual_points)) as mae
  FROM `nba-props-platform.nba_predictions.prediction_results`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
),
last_week AS (
  SELECT
    system_id,
    COUNT(*) as predictions,
    AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as accuracy,
    AVG(ABS(predicted_points - actual_points)) as mae
  FROM `nba-props-platform.nba_predictions.prediction_results`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id
)
SELECT
  t.system_id,
  t.predictions as this_week_preds,
  t.accuracy as this_week_acc,
  l.accuracy as last_week_acc,
  t.accuracy - l.accuracy as accuracy_change,
  t.mae as this_week_mae,
  l.mae as last_week_mae,
  t.mae - l.mae as mae_change
FROM this_week t
LEFT JOIN last_week l ON t.system_id = l.system_id
ORDER BY t.accuracy DESC;
```

**Expected Output:**
```
+----------------------+----------------+--------------+--------------+-----------------+
| system_id            | this_week_acc  | last_week_acc| accuracy_chg | this_week_mae   |
+----------------------+----------------+--------------+--------------+-----------------+
| meta_ensemble_v1     | 59.2%          | 58.5%        | +0.7%        | 4.12            |
| xgboost_v1           | 57.8%          | 56.9%        | +0.9%        | 4.25            |
| similarity_balanced  | 55.1%          | 56.3%        | -1.2%        | 4.38            |
+----------------------+----------------+--------------+-----------------+--------------+
```

---

### Step 2: Review Trends {#week-comparison}

#### ✅ Stable Performance (±2% accuracy week-over-week)

**Indicators:**
- Accuracy change between -2% and +2%
- MAE change between -0.3 and +0.3
- Similar prediction volume

**Action:** None! Document as "Stable" in operations log.

**Example:**
```
Ensemble: 59.2% this week, 58.5% last week (+0.7%)
→ Stable performance, within normal variance
```

---

#### ⚠️ Declining Trend (>3% drop in accuracy over 2 weeks)

**Indicators:**
- Accuracy dropped >3% from 2 weeks ago
- OR MAE increased >0.5 from 2 weeks ago
- Trend persists for 2+ weeks

**Action:**
1. **Immediate investigation**
   - Check for data quality issues
   - Review feature distributions
   - Look for NBA schedule changes (All-Star break, etc.)

2. **Consider retraining**
   - If drift detected → Schedule retraining
   - See [Continuous Retraining](../../ml-training/02-continuous-retraining.md)

**Example:**
```
Ensemble: Week 1: 59%, Week 2: 56%, Week 3: 54%
→ Declining trend detected
→ Check for concept drift, consider retraining
```

---

#### 🌟 Improving Trend (consistent accuracy increase)

**Indicators:**
- Accuracy increasing 2+ weeks in a row
- MAE decreasing
- Confidence calibration improving

**Action:**
1. **Understand why**
   - Recent model retraining?
   - Data quality improvements?
   - Systems learning patterns?

2. **Document improvements**
   - Note what changed
   - Consider if repeatable

**Example:**
```
Ensemble: Week 1: 55%, Week 2: 57%, Week 3: 59%
→ Improving trend - likely from recent XGBoost retraining
→ Document for future reference
```

---

### Step 3: Check System Health {#system-health}

#### Cloud Run Costs from Last Week

Check cloud billing:

```bash
# List billing accounts
gcloud billing accounts list

# Then use Cloud Console → Billing → Reports
# Filter to Cloud Run services
# Date range: Last 7 days
```

**Target Costs:**
- **Total Phase 5:** $8-12/day
- **Breakdown:**
  - Coordinator: $0.50-1.00/day
  - Worker: $5-8/day
  - Line Monitor: $0.50/day
  - Post-Game: $1-2/day
  - ML Training (weekly): $2-5/week

**If costs exceed targets:**

1. **Check for anomalies**
   ```bash
   # Check unusual instance scaling
   gcloud run services describe predictions-worker \
     --region=us-central1 \
     --format='value(status.latestReadyRevisionName)'
   ```

2. **Review logs for errors**
   ```bash
   # Errors can cause retries and increased costs
   gcloud logging read \
     "resource.type=cloud_run_revision AND severity>=ERROR" \
     --limit=50
   ```

3. **Optimize if needed**
   - Reduce max instances if over-scaled
   - Check for memory leaks (high memory usage)
   - Review timeout settings (shorter = cheaper)

---

### Step 4: Document Findings {#operations-log}

Create entry in operations log:

```markdown
## Weekly Review - YYYY-MM-DD

**Overall Status:** Excellent / Good / Needs Attention

### Key Metrics
- Total Predictions: XXX
- Ensemble O/U Accuracy: XX.X%
- Ensemble MAE: X.XX
- Week-over-week change: +/-X.X%

### System Performance
- **meta_ensemble_v1:** XX.X% accuracy (±X.X% vs last week)
- **xgboost_v1:** XX.X% accuracy (±X.X% vs last week)
- **similarity_balanced_v1:** XX.X% accuracy (±X.X% vs last week)
- **zone_matchup_v1:** XX.X% accuracy (±X.X% vs last week)
- **moving_average:** XX.X% accuracy (±X.X% vs last week)

### Notable Events
- [Any system failures, unusual games, high-impact errors, etc.]
- [External factors: trade deadline, All-Star break, etc.]

### Cost Summary
- Cloud Run costs: $XX.XX this week
- Status: ✅ Within budget | ⚠️ Slightly over | 🔴 Significantly over
- Notes: [Any cost anomalies or optimizations made]

### Action Items
- [ ] [If any follow-up needed]
- [ ] [Schedule retraining if drift detected]
- [ ] [Investigate specific issues]

### Next Week Focus
- [Any specific monitoring areas]
- [Expected changes: model deployment, config updates, etc.]

**Reviewed by:** [Name]
**Date:** YYYY-MM-DD
```

---

## 📊 Weekly Performance Patterns to Watch

### Pattern 1: Weekend vs Weekday Performance

**Check if accuracy differs:**
```sql
SELECT
  CASE
    WHEN EXTRACT(DAYOFWEEK FROM game_date) IN (1, 7) THEN 'Weekend'
    ELSE 'Weekday'
  END as day_type,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as accuracy,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id = 'meta_ensemble_v1'
GROUP BY day_type
```

**If significant difference:**
- Weekend games may have different patterns (more national TV games, better teams playing)
- Consider separate models or adjustments

---

### Pattern 2: Early Season vs Late Season

**NBA season phases:**
- **October-December:** Early season, teams finding rhythm
- **January-February:** Mid-season, stable patterns
- **March-April:** Late season, playoff positioning, load management
- **April-June:** Playoffs (different dynamics)

**Action:**
- Note seasonal patterns in weekly log
- Adjust expectations for different phases
- May need retraining at season transitions

---

### Pattern 3: Back-to-Back Heavy Weeks

**Check frequency:**
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  SUM(CASE WHEN back_to_back = TRUE THEN 1 ELSE 0 END) as b2b_games,
  COUNT(*) as total_games,
  AVG(CASE WHEN back_to_back = TRUE AND prediction_correct THEN 1.0
           WHEN back_to_back = TRUE THEN 0.0 END) as b2b_accuracy
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY week
ORDER BY week DESC
```

**If accuracy lower on B2B-heavy weeks:**
- Expected - fatigue is hard to predict
- Ensure fatigue adjustments are working
- Consider being more conservative on B2B predictions

---

## 🔔 Weekly Alert Triggers

### Trigger 1: Accuracy Declined 2 Weeks in a Row

**Condition:**
```
Week N accuracy < Week N-1 accuracy < Week N-2 accuracy
```

**Action:**
- Deep investigation required
- Check for concept drift
- Schedule retraining review

---

### Trigger 2: Costs Exceeded Budget by 50%

**Condition:**
```
Weekly Cloud Run costs > $84 (target: $56-84/week)
```

**Action:**
- Review scaling settings
- Check for error-retry loops
- Optimize resource allocation

---

### Trigger 3: System Consistently Underperforming

**Condition:**
```
System X accuracy < 52% for 3 consecutive weeks
```

**Action:**
- Disable system temporarily
- Investigate root cause
- Fix or replace system

---

## 🔗 Related Documentation {#related-docs}

### Daily Operations
- **[Daily Operations Checklist](./05-daily-operations-checklist.md)** - Daily morning routine
- **[Performance Monitoring](./06-performance-monitoring.md)** - CLI monitoring tools

### Monthly Operations
- **[Monthly Maintenance](./08-monthly-maintenance.md)** - Model retraining and monthly reviews

### Troubleshooting
- **[Emergency Procedures](./09-emergency-procedures.md)** - Critical incident response
- **[Troubleshooting Guide](../operations/03-troubleshooting.md)** - Common issues and solutions

### ML & Training
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Drift detection and retraining procedures
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - XGBoost training guide

---

## 📝 Quick Reference

### Weekly Commands

```bash
# Generate weekly report
python monitoring/weekly_analysis.py

# Check Cloud Run costs
gcloud billing accounts list
# Then: Cloud Console → Billing → Reports

# Week-over-week performance query
bq query --use_legacy_sql=false \
  "SELECT system_id, AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy \
   FROM \`nba-props-platform.nba_predictions.prediction_results\` \
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) \
   GROUP BY system_id ORDER BY accuracy DESC"
```

### Weekly Checklist

- [ ] Run weekly analysis script
- [ ] Review week-over-week trends
- [ ] Check cloud costs
- [ ] Document findings in operations log
- [ ] Schedule retraining if drift detected
- [ ] Update team on any significant changes

### When to Escalate

- **Accuracy drop >5% over 2 weeks** → Immediate investigation
- **Costs >150% of budget** → Review infrastructure
- **System failures** → See [Emergency Procedures](./09-emergency-procedures.md)

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Platform Operations Team
