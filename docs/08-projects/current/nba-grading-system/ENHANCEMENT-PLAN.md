# NBA Grading System - Enhancement Plan

**Created**: 2026-01-17
**Status**: Planning
**Priority**: High (Slack alerts), Medium (Dashboard), Low (Advanced features)

---

## Current State

✅ **Implemented**:
- BigQuery table: `nba_predictions.prediction_grades`
- Grading query (ready for scheduled query)
- 3 reporting views (accuracy, calibration, player performance)
- Historical backfill (Jan 14-16, 2026)

⚠️ **Not Yet Done**:
- Scheduled query activation (requires manual setup)
- Slack alerting for failures/accuracy drops
- Admin dashboard grading features
- Advanced analytics (ROI, recalibration, etc.)

---

## Admin Dashboard Current State

**Tech Stack**: Flask + BigQuery + Firestore + Cloud Logging
**Deployment**: Cloud Run (gunicorn, 4 threads)
**Authentication**: API key validation
**Features**: 8 tabs including "Coverage Metrics" tab

**Existing Grading Features**:
- Tab 7 "Coverage Metrics" has TWO sections:
  1. **Player Game Summary Coverage**: Boxscore ingestion status
  2. **Grading Status**: Predictions vs graded (shows MAE)

**NBA Grading Query** (already exists in `bigquery_service.py`):
```python
get_grading_status(days: int = 7)
# Returns: game_date, prediction_count, graded_count, mae
# Table: nba_predictions.prediction_accuracy (OLD schema?)
```

**⚠️ Schema Mismatch Detected**:
- Dashboard queries `nba_predictions.prediction_accuracy` table
- We just created `nba_predictions.prediction_grades` table
- Need to align or update dashboard queries

---

## Enhancement 1: Slack Alerting (HIGH PRIORITY)

### Objectives

1. Alert on grading failures (scheduled query didn't run)
2. Alert on accuracy drops (model performance degrading)
3. Alert on data quality issues (high % of ungradeable predictions)
4. Daily summary report (optional)

### Architecture

**Option A: Separate Cloud Function** (Recommended)
```
Cloud Scheduler → Cloud Function → BigQuery → Slack Webhook
```

**Option B: Extend Scheduled Query**
```
Scheduled Query → grades table → Monitoring Query → Slack
```

**Option C: Admin Dashboard Integration**
```
Admin Dashboard cron → BigQuery → Slack
```

**Recommendation**: Option A (independent, reliable, easy to test)

### Implementation Plan

**Phase 1: Basic Alerting (2 hours)**

1. **Create Slack alerting service** (`services/nba_grading_alerts/`)
   - Cloud Function or Cloud Run service
   - Triggered by Cloud Scheduler (daily after grading)
   - Queries `prediction_grades` table for issues

2. **Alert Types**:
   - 🚨 **CRITICAL**: Grading query failed (0 grades yesterday)
   - ⚠️ **WARNING**: Accuracy dropped below 55% (7-day average)
   - ⚠️ **WARNING**: >20% ungradeable predictions (data quality issue)
   - ℹ️ **INFO**: Daily summary (optional)

3. **Alert Format**:
```
🏀 NBA Grading Alert - Jan 17, 2026

⚠️ WARNING: Accuracy Drop Detected

System: ensemble_v1
7-day accuracy: 52.3% (threshold: 55%)
Yesterday: 48.1%
Graded predictions: 156

Margin of error: 7.2 pts (↑ from 6.1 avg)

Action: Review model performance
Dashboard: https://admin.nba-props.com/dashboard

```

4. **Configuration**:
   - Slack webhook URL (from user)
   - Alert thresholds (accuracy min, ungradeable max, etc.)
   - Alert schedule (daily at 12:30 PM PT, after grading)

**Files to Create**:
```
services/nba_grading_alerts/
├── main.py                     # Cloud Function entry point
├── alert_generator.py          # Build Slack messages
├── grading_monitor.py          # Query BigQuery for issues
├── requirements.txt
├── Dockerfile (if Cloud Run)
└── deploy.sh

bin/alerts/
└── deploy_nba_grading_alerts.sh
```

**Phase 2: Advanced Alerting (1 hour)** - Optional

- Alert on confidence calibration errors >15 points
- Alert if specific players have <40% accuracy (outliers)
- Alert if grading takes >5 minutes (performance issue)
- Weekly summary report (trends, insights)

---

## Enhancement 2: Admin Dashboard Features (MEDIUM PRIORITY)

### Current Dashboard Analysis

**Coverage Metrics Tab** (existing):
- Shows: game_date, prediction_count, graded_count, mae
- Status: COMPLETE/PARTIAL/NOT_GRADED
- Color coded: green/yellow/red

**What's Missing**:
- No accuracy percentage displayed
- No system breakdown (ensemble_v1 vs others)
- No confidence calibration view
- No player-level insights
- No trend charts

### Proposed Dashboard Enhancements

**Phase 1: Extend Coverage Metrics Tab (2 hours)**

1. **Fix Schema Mismatch**:
   - Update `bigquery_service.py::get_grading_status()` to query `prediction_grades` table
   - Add `accuracy_pct`, `system_id` to returned fields
   - Update template to display new fields

2. **Add System Breakdown Section**:
   - New sub-table: "Grading by System (Last 7 Days)"
   - Columns: system_id, predictions, graded, accuracy_pct, avg_margin
   - Sort by accuracy descending

3. **Add Issue Detection**:
   - Show count of predictions with `has_issues=TRUE`
   - Display common issue types (dnp_count, missing_actuals, etc.)
   - Red badge if issues >10%

**Template Update** (`coverage_metrics.html`):
```html
<!-- After existing grading table -->
<div class="mt-6">
  <h3 class="text-lg font-medium mb-2">Grading by System</h3>
  <table class="min-w-full">
    <thead>
      <tr>
        <th>System</th>
        <th>Predictions</th>
        <th>Graded</th>
        <th>Accuracy</th>
        <th>Margin</th>
      </tr>
    </thead>
    <tbody>
      {% for row in grading_by_system %}
      <tr>
        <td>{{ row.system_id }}</td>
        <td>{{ row.total_predictions }}</td>
        <td>{{ row.graded_count }}</td>
        <td class="{% if row.accuracy_pct >= 60 %}text-green-600{% endif %}">
          {{ row.accuracy_pct }}%
        </td>
        <td>{{ row.avg_margin }} pts</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
```

**Phase 2: New "Grading Analysis" Tab (3 hours)**

Create dedicated tab (Tab 9) with 3 sections:

**Section 1: Accuracy Trends** (line chart or sparkline)
- 7-day accuracy by system
- Hover to see daily breakdown
- Uses Chart.js or similar

**Section 2: Confidence Calibration**
- Table: confidence_bucket | predictions | actual_accuracy | calibration_error
- Color code calibration error (green <5, yellow 5-15, red >15)
- Shows if models are over/underconfident

**Section 3: Top/Bottom Players**
- Two mini-tables side-by-side:
  - Most predictable (accuracy >75%)
  - Least predictable (accuracy <45%)
- Min 10 predictions filter

**API Endpoints to Add**:
```python
@app.route('/api/<sport>/grading-by-system')
def api_grading_by_system(sport):
    # Query prediction_accuracy_summary view
    # Return system breakdown

@app.route('/api/<sport>/confidence-calibration')
def api_confidence_calibration(sport):
    # Query confidence_calibration view
    # Return calibration data

@app.route('/api/<sport>/player-grading-extremes')
def api_player_grading_extremes(sport):
    # Query player_prediction_performance view
    # Return top 10 best + worst
```

**Phase 3: Grading Insights Cards (1 hour)** - Optional

Add to status cards at top:
- "Best System Today": moving_average (68.1%)
- "Calibration Status": ✅ Well-calibrated or ⚠️ Overconfident
- "Grading Health": ✅ All systems graded or ⚠️ Issues detected

---

## Enhancement 3: ROI Calculator (LOW PRIORITY)

### Objectives

Simulate betting strategy to calculate theoretical returns.

### Implementation Plan (3-4 hours)

**Phase 1: ROI Calculation Query**

Create view: `nba_predictions.roi_simulation`

```sql
CREATE OR REPLACE VIEW `nba_predictions.roi_simulation` AS
SELECT
  system_id,
  game_date,

  -- Betting simulation (assuming -110 odds, $100 bets)
  COUNTIF(prediction_correct) as wins,
  COUNTIF(NOT prediction_correct) as losses,
  COUNTIF(prediction_correct IS NULL) as pushes,

  -- ROI calculation
  COUNTIF(prediction_correct) * 90.91 as win_profit,  -- Win $90.91 per $100 bet at -110
  COUNTIF(NOT prediction_correct) * -100 as loss_cost,
  COUNTIF(prediction_correct) * 90.91 - COUNTIF(NOT prediction_correct) * 100 as net_profit,

  -- ROI percentage
  ROUND(
    100.0 * (COUNTIF(prediction_correct) * 90.91 - COUNTIF(NOT prediction_correct) * 100) /
    (COUNTIF(prediction_correct) + COUNTIF(NOT prediction_correct)) * 100,
    2
  ) as roi_pct,

  -- Confidence-filtered ROI (only bet when confidence >70%)
  COUNTIF(prediction_correct AND confidence_score > 0.7) as high_conf_wins,
  COUNTIF(NOT prediction_correct AND confidence_score > 0.7) as high_conf_losses

FROM `nba_predictions.prediction_grades`
WHERE has_issues = FALSE
  AND prediction_correct IS NOT NULL
GROUP BY system_id, game_date
ORDER BY game_date DESC;
```

**Phase 2: Dashboard Integration**

Add ROI tab or section:
- Table: system_id | 7-day ROI | 30-day ROI | total_profit
- Show breakeven point (accuracy needed for ROI=0)
- Compare flat betting vs confidence-weighted

**Phase 3: Advanced Strategies** (Future)

- Kelly criterion optimal bet sizing
- Bankroll simulation (starting $1000, track over time)
- Variance analysis (win streaks, drawdowns)

---

## Enhancement 4: Model Recalibration (LOW PRIORITY)

### Objectives

Use grading data to improve confidence score calibration.

### Implementation Plan (4-5 hours)

**Phase 1: Calibration Analysis**

Create script: `scripts/nba/analyze_calibration.py`

```python
# 1. Query confidence_calibration view
# 2. Identify buckets with high calibration error
# 3. Compute temperature scaling factor
# 4. Generate recalibration curve
```

**Phase 2: Recalibration Function**

Options:
1. **Temperature scaling**: `confidence_new = sigmoid(logit(confidence_old) / T)`
2. **Isotonic regression**: Fit monotonic curve
3. **Platt scaling**: Logistic regression on confidence scores

**Phase 3: Integration**

- Add recalibration to prediction generation code
- Track calibrated vs raw confidence
- Compare grading results before/after

---

## Enhancement 5: Historical Backfill (LOW PRIORITY)

### Objectives

Grade all predictions since Jan 1, 2026 (or earlier).

### Implementation Plan (30 minutes)

**Script**: `scripts/nba/backfill_grading.sh`

```bash
#!/bin/bash
# Grade all dates from Jan 1 to yesterday

START_DATE="2026-01-01"
END_DATE=$(date -d "yesterday" +%Y-%m-%d)

current_date="$START_DATE"
while [[ "$current_date" < "$END_DATE" ]]; do
    echo "Grading $current_date..."
    bq query --use_legacy_sql=false \
        --parameter=game_date:DATE:$current_date \
        < schemas/bigquery/nba_predictions/grade_predictions_query.sql

    current_date=$(date -d "$current_date + 1 day" +%Y-%m-%d)
done

echo "Backfill complete!"
```

Run once, then rely on scheduled query going forward.

---

## Enhancement 6: Grading Dashboard (Looker Studio)

### Objectives

Visual dashboard for executives/stakeholders.

### Implementation Plan (2-3 hours)

**Charts**:
1. **Accuracy Trend Line**: Daily accuracy over time
2. **System Comparison Bar Chart**: Current accuracy by system
3. **Calibration Scatter Plot**: Confidence vs actual accuracy
4. **ROI Timeline**: Cumulative profit over time
5. **Top Players Table**: Most/least predictable

**Data Source**: BigQuery views (already created)

**Sharing**: Embed in admin dashboard or standalone

---

## Implementation Priority & Timeline

### Phase 1: Critical (Week 1) - 4 hours

1. **Activate scheduled query** (5 min)
   - Follow setup guide
   - Verify first run

2. **Slack alerting** (2 hours)
   - Create alerting service
   - Deploy to Cloud Run/Function
   - Configure Slack webhook
   - Test with historical data

3. **Fix dashboard schema mismatch** (1 hour)
   - Update `get_grading_status()` to use `prediction_grades` table
   - Add accuracy_pct field
   - Test coverage metrics tab

4. **Add system breakdown to dashboard** (1 hour)
   - Create `get_grading_by_system()` method
   - Update coverage_metrics.html template
   - Add API endpoint

### Phase 2: Important (Week 2) - 6 hours

5. **New grading analysis tab** (3 hours)
   - Create tab 9 in dashboard
   - Add 3 API endpoints (by-system, calibration, player extremes)
   - Build templates with tables

6. **ROI calculator view** (2 hours)
   - Create ROI simulation view in BigQuery
   - Add to dashboard (new section or tab)

7. **Historical backfill** (30 min)
   - Run backfill script for all dates since Jan 1
   - Verify data quality

8. **Advanced Slack alerts** (30 min)
   - Add calibration error alerts
   - Add weekly summary report

### Phase 3: Nice-to-Have (Month 2+) - 8 hours

9. **Grading insights cards** (1 hour)
10. **Model recalibration** (4-5 hours)
11. **Looker Studio dashboard** (2-3 hours)

---

## Technical Requirements

### Slack Alerting

**Requirements from User**:
- [ ] Create Slack channel (e.g., `#nba-grading-alerts`)
- [ ] Create incoming webhook URL
- [ ] Provide webhook URL to store in Secret Manager

**Environment Variables**:
```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
ALERT_THRESHOLDS_ACCURACY_MIN=55  # Alert if accuracy drops below 55%
ALERT_THRESHOLDS_UNGRADEABLE_MAX=20  # Alert if >20% ungradeable
```

### Dashboard Updates

**BigQuery Service Changes**:
```python
# Update method signature
def get_grading_status(self, days: int = 7, include_system_breakdown: bool = False):
    # Query prediction_grades table (not prediction_accuracy)
    # Include accuracy_pct, system_id
    # Optionally return per-system breakdown

def get_grading_by_system(self, days: int = 7):
    # Query prediction_accuracy_summary view
    # Return list of dicts with system stats

def get_confidence_calibration(self, days: int = 7, system_id: str = None):
    # Query confidence_calibration view
    # Filter by system if provided

def get_player_grading_performance(self, limit: int = 10, order: str = 'best'):
    # Query player_prediction_performance view
    # Return top N or bottom N players
```

---

## Success Metrics

### Alerting

- ✅ Alerts fire within 5 minutes of issue detection
- ✅ <1% false positive rate
- ✅ All critical failures caught (0 missed alerts)

### Dashboard

- ✅ Grading data visible within 30 seconds of page load
- ✅ Accuracy trends clearly show model performance
- ✅ Stakeholders can self-serve grading reports

### Business Impact

- ✅ Detect model drift within 24 hours
- ✅ Identify improvement opportunities (recalibration, feature engineering)
- ✅ Validate model changes with data

---

## Files to Create/Modify

### New Files (Alerting)

```
services/nba_grading_alerts/
├── main.py
├── alert_generator.py
├── grading_monitor.py
├── requirements.txt
├── Dockerfile
└── deploy.sh

bin/alerts/
└── deploy_nba_grading_alerts.sh

docs/08-projects/current/nba-grading-system/
└── ALERTING-SETUP.md
```

### New Files (ROI)

```
schemas/bigquery/nba_predictions/views/
└── roi_simulation.sql

scripts/nba/
├── analyze_roi.py
└── backfill_grading.sh
```

### Modified Files (Dashboard)

```
services/admin_dashboard/
├── main.py                        # Add new API routes
├── services/bigquery_service.py   # Add new methods, update existing
└── templates/
    ├── dashboard.html             # Add tab 9 if needed
    └── components/
        ├── coverage_metrics.html  # Update with system breakdown
        └── grading_analysis.html  # New tab (if tab 9)
```

---

## Next Steps

1. **User Action Required**:
   - Create Slack channel for alerts
   - Generate incoming webhook URL
   - Share webhook URL

2. **Implementation Order**:
   - Start with Slack alerting (highest value)
   - Then dashboard schema fix
   - Then dashboard enhancements
   - Finally optional features (ROI, recalibration)

3. **Testing**:
   - Test alerts with mock data first
   - Verify dashboard updates don't break existing tabs
   - Load test with multiple users

---

**Ready to begin Phase 1 when:**
- [ ] Scheduled query is activated
- [ ] Slack webhook URL is available
- [ ] User confirms enhancement priorities

**Estimated Total Time**: 18-20 hours across all phases
**Phase 1 (Critical)**: 4 hours
**Phase 2 (Important)**: 6 hours
**Phase 3 (Nice-to-have)**: 8-10 hours
