# Track A: XGBoost V1 Performance Monitoring

**Status:** 📋 Planned
**Priority:** HIGH
**Estimated Time:** 6-8 hours
**Target Completion:** 2026-01-20

---

## 🎯 Objective

Set up comprehensive production monitoring for XGBoost V1 V2 (deployed 2026-01-18) to:
1. Track real production performance vs validation (3.726 MAE)
2. Compare head-to-head vs CatBoost V8 (champion at 3.40 MAE)
3. Identify opportunities for optimization
4. Detect performance degradation early

---

## 📊 Model Details

**Model:** xgboost_v1_33features_20260118_103153
**Deployed:** 2026-01-18 18:33 UTC
**Validation MAE:** 3.726 points
**Expected Production:** 3.73 ± 0.5 points
**Features:** 33 (v2_33features)
**Training Data:** 101,692 samples (2021-2025)

---

## 📋 Task Breakdown

### 1. Daily Monitoring Queries (2 hours)

**Goal:** Automated queries to track daily performance

**Queries to Create:**
- [ ] Daily MAE, RMSE, win rate
- [ ] Prediction volume and coverage
- [ ] OVER vs UNDER performance
- [ ] Confidence tier breakdown
- [ ] Error distribution analysis
- [ ] Vegas line dependency check

**Output:** `daily-monitoring-queries.sql`

---

### 2. Weekly Report Templates (1 hour)

**Goal:** Structured reports for weekly performance review

**Reports:**
- [ ] Week-over-week MAE trends
- [ ] Cumulative performance metrics
- [ ] Player tier analysis (bench, role, starter, star)
- [ ] Home/away split performance
- [ ] Back-to-back game performance

**Output:** `weekly-reports.md` template

---

### 3. Head-to-Head Comparison (2 hours)

**Goal:** Compare XGBoost V1 vs CatBoost V8 on same predictions

**Analyses:**
- [ ] Same-game comparison (both models predict same player)
- [ ] Win rate when both models agree
- [ ] Win rate when models disagree
- [ ] MAE comparison by confidence level
- [ ] Feature importance correlation

**Output:** `head-to-head-analysis.sql`

---

### 4. Confidence Calibration (1 hour)

**Goal:** Validate that confidence scores accurately reflect accuracy

**Checks:**
- [ ] Win rate by confidence band (90%+, 70-90%, 55-70%, <55%)
- [ ] Calibration curve (predicted confidence vs actual accuracy)
- [ ] Confidence distribution over time
- [ ] High-confidence picks analysis (>90%)

**Output:** `confidence-analysis.sql`

---

### 5. Alert Rules Definition (1 hour)

**Goal:** Define when to alert on performance issues

**Alert Triggers:**
- [ ] Production MAE > 4.2 for 3+ consecutive days (>15% worse than validation)
- [ ] Win rate < 50% for 7+ days
- [ ] Prediction volume drops >50% vs baseline
- [ ] Placeholder predictions appear (should be 0)
- [ ] High-confidence picks (<70% win rate on >90% confidence)

**Output:** `alerting-rules.yaml`

---

### 6. Automated Reporting (1 hour)

**Goal:** Schedule queries to run automatically

**Setup:**
- [ ] BigQuery scheduled queries for daily metrics
- [ ] Export results to monitoring table
- [ ] Create views for dashboard consumption
- [ ] Set up email notifications (optional)

**Output:** `scheduled-queries-setup.sh`

---

## 🚀 Getting Started

### Prerequisites
```bash
# Ensure BigQuery access
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'xgboost_v1'"

# Should return count > 0 once predictions start being graded
```

### Step 1: Create Daily Monitoring Queries
```bash
cd /home/naji/code/nba-stats-scraper/docs/08-projects/current/prediction-system-optimization/track-a-monitoring/

# Start with template
cat > daily-monitoring-queries.sql << 'EOF'
-- XGBoost V1 Daily Performance Monitoring
-- Run this query daily to track production performance

-- Overall Daily Performance
SELECT
  game_date,
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2026-01-18'  -- XGBoost V1 V2 deployment date
  AND system_id = 'xgboost_v1'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC;
EOF
```

### Step 2: Test Queries
```bash
# Run the daily monitoring query
bq query --use_legacy_sql=false < daily-monitoring-queries.sql

# Expected: Results showing XGBoost V1 performance by date
```

### Step 3: Compare to Baseline
```bash
# Check validation performance
echo "Validation MAE: 3.726"
echo "Expected Production MAE: 3.73 ± 0.5"
echo "Actual Production MAE: [from query results]"
```

---

## 📈 Success Metrics

**Monitoring Setup Complete When:**
- ✅ Daily queries run successfully
- ✅ Weekly reports generate automatically
- ✅ Head-to-head comparison shows competitive performance
- ✅ Confidence calibration validated
- ✅ Alert rules defined and documented
- ✅ First week of data analyzed and documented

**Performance Targets:**
- Production MAE ≤ 4.2 (within 15% of validation 3.73)
- Win rate ≥ 52% (break-even for betting)
- Confidence calibration: ±5% of expected accuracy
- Within 10% of CatBoost V8 performance (3.40 MAE)

---

## 📊 Key Performance Indicators (KPIs)

### Primary KPIs
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Production MAE | 3.73 ± 0.5 | >4.2 for 3 days |
| Win Rate | ≥55% | <50% for 7 days |
| Predictions/Day | ~6,000 | <3,000 |
| Confidence Accuracy | ±5% | >10% deviation |

### Secondary KPIs
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| OVER Win Rate | ≥53% | <48% for 7 days |
| UNDER Win Rate | ≥53% | <48% for 7 days |
| High Confidence (>90%) Win Rate | ≥70% | <60% for 3 days |
| vs CatBoost Win Rate (head-to-head) | ≥45% | <40% for 7 days |

---

## 🔍 Analysis Framework

### Daily Checks (5 minutes)
1. Run daily monitoring query
2. Check MAE vs baseline (3.73)
3. Verify prediction volume normal
4. Scan for anomalies

### Weekly Deep Dive (30 minutes)
1. Generate weekly report
2. Analyze trends (improving/degrading)
3. Compare to CatBoost V8
4. Review confidence calibration
5. Document findings

### Monthly Review (2 hours)
1. Comprehensive performance analysis
2. Feature importance stability check
3. Retrain decision evaluation
4. Optimization opportunities identification

---

## 📝 Deliverables Checklist

- [ ] `daily-monitoring-queries.sql` - Core monitoring queries
- [ ] `weekly-reports.md` - Report template with example
- [ ] `head-to-head-analysis.sql` - XGBoost vs CatBoost comparison
- [ ] `confidence-analysis.sql` - Calibration and confidence queries
- [ ] `alerting-rules.yaml` - Alert specifications
- [ ] `scheduled-queries-setup.sh` - Automation setup script
- [ ] `first-week-analysis.md` - Initial findings and insights

---

## 🔗 Related Documentation

- [XGBoost V1 Performance Guide](../../ml-model-v8-deployment/XGBOOST-V1-PERFORMANCE-GUIDE.md)
- [Master Plan](../MASTER-PLAN.md)
- [Progress Log](../PROGRESS-LOG.md)
- [Session 88-89 Handoff](../../../../09-handoff/SESSION-88-89-HANDOFF.md)

---

## 💡 Tips & Best Practices

### Query Optimization
- Use `DATE` filters to limit data scanned
- Create materialized views for frequently accessed metrics
- Schedule heavy queries during off-peak hours

### Comparing Models
- Always compare on same player-game pairs
- Filter for games where both models made predictions
- Consider confidence scores when comparing

### Interpreting Results
- First 3-7 days may show variance (small sample)
- Look for trends, not daily fluctuations
- Compare to validation performance, not just absolute numbers

### Documentation
- Document all findings in PROGRESS-LOG.md
- Share insights with team weekly
- Update alert thresholds based on observed performance

---

**Track Owner:** Engineering Team
**Created:** 2026-01-18
**Status:** Ready to Start
**Next Step:** Create daily-monitoring-queries.sql
