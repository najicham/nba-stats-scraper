# Phase 5: Daily Operations Checklist

**File:** `docs/predictions/operations/05-daily-operations-checklist.md`
**Created:** 2025-11-16
**Purpose:** Daily operational checklist for Phase 5 prediction services - morning routine, health checks, and daily monitoring
**Status:** ✅ Production Ready

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Morning Routine (2 Minutes)](#morning-routine)
3. [Daily Health Checks](#health-checks)
4. [Interpreting Results](#interpreting-results)
5. [Success Thresholds](#thresholds)
6. [Related Documentation](#related-docs)

---

## 🚀 Quick Start {#quick-start}

### Daily Morning Routine

**Time:** 9-10 AM daily (after previous night's games are finalized)
**Duration:** 2 minutes
**Frequency:** Every day during NBA season

**Quick Check:**
```bash
# Check yesterday's performance
python monitoring/performance_monitor.py --date yesterday

# If all green → Done! (30 seconds)
# If issues → See troubleshooting section
```

### Success Thresholds

| Status | O/U Accuracy | MAE | Interpretation |
|--------|-------------|-----|----------------|
| 🌟 **EXCELLENT** | ≥60% | <4.0 | Very profitable, system performing exceptionally |
| ✅ **GOOD** | 55-60% | 4.0-4.5 | Profitable, normal operations |
| ⚠️ **MARGINAL** | 52-55% | 4.5-5.0 | Barely profitable, monitor closely |
| 🔴 **PROBLEM** | <52% | >5.0 | Losing money, action required |

### System Status Quick Reference

- **All 5 systems running** → ✅ Normal operations
- **3-4 systems running** → ⚠️ Check logs
- **<3 systems running** → 🔴 ACTION REQUIRED

---

## 🌅 Morning Routine (2 Minutes) {#morning-routine}

### Step 1: Check Yesterday's Performance

Query BigQuery for daily summary:

```sql
SELECT
    system_id,
    COUNT(*) as total_predictions,
    AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as ou_accuracy,
    AVG(ABS(predicted_points - actual_points)) as mae,
    AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY system_id
ORDER BY ou_accuracy DESC;
```

**Expected Output:**
```
+----------------------+-----------+-------------+------+----------------+
| system_id            | total_preds| ou_accuracy | mae  | avg_confidence |
+----------------------+-----------+-------------+------+----------------+
| meta_ensemble_v1     | 42        | 0.595       | 4.12 | 76.3           |
| xgboost_v1           | 42        | 0.571       | 4.28 | 72.1           |
| similarity_balanced  | 42        | 0.548       | 4.45 | 68.5           |
| zone_matchup_v1      | 42        | 0.524       | 4.67 | 65.2           |
| moving_average       | 42        | 0.500       | 4.89 | 61.8           |
+----------------------+-----------+-------------+------+----------------+
```

**Using CLI Tool:**
```bash
# Recommended: Use monitoring tool
python monitoring/performance_monitor.py --date yesterday

# This provides formatted output with status indicators
```

---

### Step 2: Interpret Results {#interpreting-results}

#### ✅ ALL GREEN (95% of days)

**Indicators:**
- O/U Accuracy >55% for ensemble
- MAE <4.5 for ensemble
- All 5 systems generated predictions

**Action:** None! You're done. ✓

**Example:**
```
Ensemble: 59.5% accuracy, MAE 4.2
→ Excellent performance, no action needed
```

---

#### ⚠️ WARNINGS (4% of days)

**Indicators:**
- O/U Accuracy 52-55% for ensemble
- OR MAE 4.5-5.0
- OR 1-2 systems didn't run

**Action:**
1. Note in operations log
2. Monitor tomorrow
3. If continues for 3 days → Investigate

**Example:**
```
Ensemble: 53.2% accuracy, MAE 4.7
→ Below target but acceptable
→ Monitor for trend
```

---

#### 🔴 CRITICAL (1% of days)

**Indicators:**
- O/U Accuracy <52%
- OR MAE >5.0
- OR 3+ systems didn't run
- OR No predictions generated

**Action:** Jump to [Emergency Procedures](./09-emergency-procedures.md)

**Example:**
```
Ensemble: 47% accuracy, MAE 5.8
→ CRITICAL: Losing money
→ Immediate investigation required
```

---

### Step 3: Check Cloud Run Service Health {#health-checks}

Check if all 5 services are healthy:

```bash
# List all Phase 5 services
gcloud run services list \
  --platform=managed \
  --region=us-central1 \
  --project=nba-props-platform | grep predictions-
```

**Expected Output:**
```
✓ predictions-coordinator    us-central1
✓ predictions-worker         us-central1
✓ predictions-line-monitor   us-central1
✓ predictions-postgame       us-central1
✓ predictions-ml-training    us-central1
```

**What to check:**
- All 5 services show ✓ (ready)
- No services in error state
- Recent revisions deployed successfully

**If services show issues:**
```bash
# Check specific service details
gcloud run services describe predictions-worker \
  --region=us-central1 \
  --format=json
```

---

### Step 4: Check for Alerts

Check Cloud Logging for errors from last 24 hours:

```bash
# Check for ERROR-level logs
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   severity>=ERROR AND \
   timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
  --project=nba-props-platform \
  --limit=20 \
  --format=json
```

**If errors found:**

1. **Review error messages**
   - Check the error type and frequency
   - Note which service is affected

2. **Determine severity**
   - Transient (network issues, timeouts) → Monitor
   - Systematic (data quality, model errors) → Investigate

3. **Take action**
   - If transient → Note in log, monitor
   - If systematic → See [Troubleshooting](../operations/03-troubleshooting.md)

**Common transient errors (OK to ignore):**
- `DEADLINE_EXCEEDED` (occasional timeout)
- `Connection reset by peer` (network blip)
- `Temporary failure in name resolution` (DNS issue)

**Systematic errors (require investigation):**
- `Model file not found`
- `Feature store empty`
- `BigQuery write failed`
- `Invalid prediction values`

---

## 📊 Success Thresholds {#thresholds}

### Performance Metrics

#### Over/Under Accuracy (MOST IMPORTANT)

**What it measures:** % of times system correctly predicted OVER or UNDER

**Why it matters:** This is what wins bets - all other metrics support this

**Thresholds:**
- 🌟 **60%+** = Excellent (very profitable)
- ✅ **55-60%** = Good (profitable)
- ⚠️ **52-55%** = Marginal (barely profitable)
- 🔴 **<52%** = Losing money (need 52.4% to break even after vig)

---

#### Mean Absolute Error (MAE)

**What it measures:** Average difference between predicted and actual points

**Why it matters:** Shows if system understands player performance

**Thresholds:**
- 🌟 **<4.0** = Excellent
- ✅ **4.0-4.5** = Good
- ⚠️ **4.5-5.0** = Acceptable
- 🔴 **>5.0** = Needs improvement

**Example:**
```
Game 1: Predict 25, Actual 28 → Error 3
Game 2: Predict 22, Actual 19 → Error 3
Game 3: Predict 31, Actual 27 → Error 4
Average MAE = (3+3+4)/3 = 3.33 ✅ EXCELLENT
```

---

#### Confidence Calibration

**What it measures:** Do high-confidence predictions perform better than low-confidence?

**Why it matters:** Validates that confidence scores are meaningful

**Expected Pattern:**
- **Confidence 85-100:** 62-68% accuracy
- **Confidence 70-84:** 58-62% accuracy
- **Confidence 55-69:** 52-56% accuracy
- **Confidence <55:** Pass (don't bet)

**Check calibration:**
```sql
SELECT
    CASE
        WHEN confidence_score >= 85 THEN 'High (85+)'
        WHEN confidence_score >= 70 THEN 'Medium (70-84)'
        WHEN confidence_score >= 55 THEN 'Low (55-69)'
        ELSE 'Very Low (<55)'
    END as confidence_tier,
    COUNT(*) as predictions,
    AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as accuracy_pct
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE system_id = 'meta_ensemble_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY confidence_tier
ORDER BY MIN(confidence_score) DESC;
```

---

### System-Specific Performance

Compare all 5 systems side-by-side:

```sql
SELECT
    system_id,
    COUNT(*) as predictions,
    AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as ou_accuracy,
    AVG(ABS(predicted_points - actual_points)) as mae,
    AVG(confidence_score) as avg_confidence,
    COUNT(CASE WHEN recommendation = 'PASS' THEN 1 END) as pass_count
FROM `nba-props-platform.nba_predictions.prediction_results`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY system_id
ORDER BY ou_accuracy DESC;
```

**Expected Ranking (typical):**
1. meta_ensemble_v1 (59% accuracy, 4.1 MAE)
2. xgboost_v1 (57% accuracy, 4.3 MAE)
3. similarity_balanced (55% accuracy, 4.4 MAE)
4. zone_matchup_v1 (53% accuracy, 4.6 MAE)
5. moving_average (52% accuracy, 4.8 MAE)

---

## 🔗 Related Documentation {#related-docs}

### Daily Operations
- **[Performance Monitoring](./06-performance-monitoring.md)** - Detailed monitoring guide with CLI tools
- **[Troubleshooting](../operations/03-troubleshooting.md)** - Common issues and solutions
- **[Emergency Procedures](./09-emergency-procedures.md)** - Critical incident response

### Weekly & Monthly Operations
- **[Weekly Maintenance](./07-weekly-maintenance.md)** - Weekly review checklist
- **[Monthly Maintenance](./08-monthly-maintenance.md)** - Model retraining and monthly tasks

### Reference
- **[Operations Command Reference](../tutorials/04-operations-command-reference.md)** - Quick command lookup
- **[Worker Deep Dive](./04-worker-deepdive.md)** - Worker internals and debugging

### Getting Started
- **[Deployment Guide](./01-deployment-guide.md)** - Initial deployment procedures
- **[Getting Started Tutorial](../tutorials/01-getting-started.md)** - New operator onboarding

---

## 📝 Operations Log Template

Use this template when documenting daily checks:

```markdown
## Daily Check - YYYY-MM-DD

**Status:** ✅ Green | ⚠️ Warning | 🔴 Critical

### Performance Summary
- Total Predictions: XXX
- Ensemble O/U Accuracy: XX.X%
- Ensemble MAE: X.XX
- Systems Running: X/5

### Issues Detected
- [ ] None
- [ ] [Description of any issues]

### Actions Taken
- [ ] None required
- [ ] [Actions if any]

### Notes
- [Any relevant observations]

**Checked by:** [Name]
**Time:** [HH:MM AM/PM]
```

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Platform Operations Team
