# Phase 3: NBA Grading Advanced Features - Start Here

**Status**: Ready to Start
**Prerequisites**: ✅ Session 85 + Phases 1-2 Complete
**Estimated Time**: 4-6 hours
**Priority**: Medium (nice-to-have enhancements)

---

## Context: What's Already Done

### Session 85 (Complete) ✅
**Core Grading System**:
- BigQuery table: `nba_predictions.prediction_grades` (4,720 predictions graded)
- Grading query: Handles all edge cases (DNP, pushes, missing data)
- 3 reporting views: accuracy_summary, confidence_calibration, player_performance
- Complete documentation in `docs/08-projects/current/nba-grading-system/`

**Current Performance**:
- Best system: `moving_average` at 64.8% accuracy
- All systems >50% (beating random chance)
- 100% gold-tier data quality

### Phase 1 (Complete) ✅
**Slack Alerting**:
- Cloud Function: `nba-grading-alerts` deployed
- Schedule: Daily at 12:30 PM PT
- Channel: `#nba-grading-alerts`
- Alerts: Grading failures, accuracy drops, data quality issues

### Phase 2 (Complete) ✅
**Dashboard Updates**:
- Admin dashboard: https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/dashboard
- New features: Accuracy column, system breakdown table
- Real-time data loading with JavaScript
- API endpoint: `/api/grading-by-system`

### What Should Be Running Now ✅
- **Scheduled grading query**: Daily at 12:00 PM PT (if activated)
- **Alert monitoring**: Daily at 12:30 PM PT
- **Dashboard**: Always available with live data

---

## Phase 3: What to Build

### Objective
Add advanced analytics and insights to help optimize betting strategy and model performance.

### Features to Implement

**1. ROI Calculator** (2-3 hours)
- **What**: Simulate betting strategy to calculate theoretical returns
- **Why**: Measure profitability, validate betting strategy
- **Deliverables**:
  - BigQuery view: `roi_simulation`
  - Dashboard section showing ROI metrics
  - Betting strategy simulator (flat betting vs confidence-weighted)

**2. Confidence Calibration Insights** (1 hour)
- **What**: Deep dive into model confidence vs actual accuracy
- **Why**: Identify overconfident/underconfident systems
- **Deliverables**:
  - Dashboard visualization of calibration
  - Alerts for poor calibration (>15 point error)
  - Recommendations for recalibration

**3. Player Insights** (1 hour)
- **What**: Identify most/least predictable players
- **Why**: Focus predictions on high-confidence players
- **Deliverables**:
  - Top 10 most predictable players table
  - Bottom 10 least predictable players table
  - Player volatility metrics

**4. Advanced Slack Alerts** (30 min)
- **What**: Weekly summary reports, calibration warnings
- **Why**: Proactive monitoring beyond daily checks
- **Deliverables**:
  - Weekly accuracy trend summary (sent Mondays)
  - Calibration error alerts (if >15 points)
  - System ranking changes (if top system changes)

**5. Historical Backfill** (30 min)
- **What**: Grade all predictions since Jan 1, 2026
- **Why**: More data = better statistical significance
- **Deliverables**:
  - Script to backfill all dates
  - Validation of backfilled data
  - Updated accuracy baselines

---

## Current State

### What's Working ✅
```
BigQuery Tables:
  ✅ nba_predictions.prediction_grades (3 days graded)
  ✅ nba_predictions.player_prop_predictions
  ✅ nba_analytics.player_game_summary

BigQuery Views:
  ✅ prediction_accuracy_summary
  ✅ confidence_calibration
  ✅ player_prediction_performance

Services:
  ✅ nba-grading-alerts (Cloud Function)
  ✅ nba-admin-dashboard (Cloud Run)

Scheduled Jobs:
  ✅ nba-grading-alerts-daily (12:30 PM PT)
  ⏳ nba-prediction-grading-daily (12:00 PM PT - needs activation)
```

### Current Metrics (Jan 14-16, 2026)

| System | Predictions | Accuracy | Margin | Confidence |
|--------|-------------|----------|--------|------------|
| moving_average | 1,139 | 64.8% | 5.6 pts | 52% |
| ensemble_v1 | 1,139 | 61.8% | 6.1 pts | 73% |
| similarity_balanced_v1 | 988 | 60.6% | 6.1 pts | 88% |
| zone_matchup_v1 | 1,139 | 57.4% | 6.6 pts | 52% |

**Observations**:
- `similarity_balanced_v1` may be overconfident (88% confidence, 60.6% accuracy)
- Calibration error: ~27 points (should investigate)
- `zone_matchup_v1` lowest accuracy (needs improvement)

---

## Files & Documentation

### Key Documentation
```
docs/08-projects/current/nba-grading-system/
├── START-HERE.md                      # Overview
├── ENHANCEMENT-PLAN.md                # Full 6-phase roadmap
├── IMPLEMENTATION-SUMMARY.md          # Technical details
└── README.md                          # Quick reference

docs/09-handoff/
├── SESSION-85-NBA-GRADING-COMPLETE.md     # Session 85 summary
├── SESSION-85-ENHANCEMENTS-COMPLETE.md    # Phases 1-2 summary
└── PHASE-3-START-HERE.md                  # This file
```

### Code Locations
```
services/
├── nba_grading_alerts/
│   ├── main.py                        # Alert logic
│   └── requirements.txt
└── admin_dashboard/
    ├── main.py                        # Dashboard app
    ├── services/bigquery_service.py   # BQ queries
    └── templates/components/
        └── coverage_metrics.html      # Grading UI

schemas/bigquery/nba_predictions/
├── prediction_grades.sql              # Table schema
├── grade_predictions_query.sql        # Grading logic
└── views/
    ├── prediction_accuracy_summary.sql
    ├── confidence_calibration.sql
    └── player_prediction_performance.sql
```

---

## Phase 3 Implementation Guide

### Step 1: ROI Calculator (2-3 hours)

**Create ROI view**:
```sql
-- File: schemas/bigquery/nba_predictions/views/roi_simulation.sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.roi_simulation` AS
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
    ((COUNTIF(prediction_correct) + COUNTIF(NOT prediction_correct)) * 100),
    2
  ) as roi_pct,

  -- High-confidence ROI (only bet when confidence >70%)
  COUNTIF(prediction_correct AND confidence_score > 0.7) as high_conf_wins,
  COUNTIF(NOT prediction_correct AND confidence_score > 0.7) as high_conf_losses

FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE has_issues = FALSE
  AND prediction_correct IS NOT NULL
GROUP BY system_id, game_date
ORDER BY game_date DESC;
```

**Add to dashboard**:
- BigQuery service method: `get_roi_simulation(days=7)`
- API endpoint: `/api/roi-simulation`
- Dashboard section with ROI table

**Expected output**:
```
System          | 7-Day ROI | Total Profit | Win Rate
moving_average  | +12.3%    | +$147        | 64.8%
ensemble_v1     | +8.5%     | +$102        | 61.8%
```

### Step 2: Calibration Insights (1 hour)

**Dashboard visualization**:
- Show calibration error by system
- Highlight systems with error >15 points
- Recommendation: "Recalibrate similarity_balanced_v1"

**Alert enhancement**:
```python
# Add to services/nba_grading_alerts/main.py
def check_calibration_health(client, days=7):
    query = f"""
    SELECT
      system_id,
      confidence_bucket,
      calibration_error
    FROM `nba-props-platform.nba_predictions.confidence_calibration`
    WHERE ABS(calibration_error) > 15  -- Alert threshold
    """
    # Return systems with poor calibration
```

### Step 3: Player Insights (1 hour)

**Add to dashboard**:
- Query `player_prediction_performance` view
- Show top 10 most predictable (accuracy >75%)
- Show bottom 10 least predictable (accuracy <45%)

**Use case**: Focus predictions on predictable players, investigate unpredictable ones

### Step 4: Advanced Alerts (30 min)

**Weekly summary**:
```python
# New Cloud Function: nba-grading-weekly-summary
# Schedule: Mondays at 9:00 AM PT
# Sends: 7-day accuracy trends, system rankings, insights
```

**Calibration alerts**:
- Add to daily alert check
- Alert if calibration error >15 points
- Suggest recalibration actions

### Step 5: Historical Backfill (30 min)

**Script**:
```bash
# File: scripts/nba/backfill_grading.sh
#!/bin/bash
START_DATE="2026-01-01"
END_DATE="2026-01-13"  # Day before we started

for date in $(seq -f "%Y-%m-%d" ...); do
  bq query --use_legacy_sql=false \
    --parameter=game_date:DATE:$date \
    < schemas/bigquery/nba_predictions/grade_predictions_query.sql
done
```

---

## Quick Start Commands

### Test Current System
```bash
# Check grading data exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total_grades, MIN(game_date) as first, MAX(game_date) as last
FROM \`nba-props-platform.nba_predictions.prediction_grades\`
"

# Check alert service
gcloud functions logs read nba-grading-alerts --region=us-west2 --limit=10

# Check dashboard
curl https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/health
```

### Access Services
```bash
# Dashboard
open "https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/dashboard?key=d71edd85bf250d5737687cdee289719d"

# BigQuery views
bq query --use_legacy_sql=false "
SELECT * FROM \`nba-props-platform.nba_predictions.prediction_accuracy_summary\`
ORDER BY game_date DESC LIMIT 5
"
```

---

## Success Criteria for Phase 3

### Must Have
- [ ] ROI simulation view created and tested
- [ ] Dashboard shows ROI metrics
- [ ] Calibration insights visible in dashboard
- [ ] Player insights (top/bottom performers) shown
- [ ] Historical backfill completed (Jan 1-13)

### Nice to Have
- [ ] Weekly summary alerts configured
- [ ] Calibration error alerts added
- [ ] ROI by confidence threshold (70%, 80%, 90%)
- [ ] Betting strategy comparison (flat vs weighted)

### Validation
- [ ] ROI calculations match manual verification
- [ ] Calibration errors calculated correctly
- [ ] Player rankings make sense (eye test)
- [ ] Historical data quality validated

---

## Known Challenges

### Challenge 1: ROI Calculation Complexity
- **Issue**: Different sportsbooks have different odds
- **Solution**: Start with standard -110 odds, make configurable later
- **Workaround**: Document assumption clearly

### Challenge 2: Historical Betting Lines
- **Issue**: May not have historical lines for all dates
- **Solution**: Only calculate ROI where lines exist
- **Workaround**: Flag missing lines in ROI view

### Challenge 3: Calibration Interpretation
- **Issue**: What's "good" calibration?
- **Solution**: Industry standard is <5 point error for high-stakes
- **Threshold**: Alert if >15 points (conservative)

---

## Estimated Timeline

| Task | Time | Priority |
|------|------|----------|
| ROI view creation | 1 hour | High |
| Dashboard ROI integration | 1 hour | High |
| Calibration visualization | 1 hour | Medium |
| Player insights | 1 hour | Medium |
| Historical backfill | 30 min | High |
| Weekly alerts | 30 min | Low |
| Testing & validation | 1 hour | High |

**Total**: 6 hours (can be done in 2 sessions)

---

## Resources

### BigQuery Tables
- `nba_predictions.prediction_grades` - Source data
- `nba_predictions.prediction_accuracy_summary` - Daily rollups
- `nba_predictions.confidence_calibration` - Calibration data
- `nba_predictions.player_prediction_performance` - Player stats

### Existing Code Patterns
- **View creation**: See `schemas/bigquery/nba_predictions/views/`
- **Dashboard integration**: See `services/admin_dashboard/`
- **Alert logic**: See `services/nba_grading_alerts/main.py`

### Reference Docs
- Grading runbook: `docs/06-grading/NBA-GRADING-SYSTEM.md`
- Enhancement plan: `docs/08-projects/current/nba-grading-system/ENHANCEMENT-PLAN.md`
- Implementation summary: `docs/08-projects/current/nba-grading-system/IMPLEMENTATION-SUMMARY.md`

---

## Questions to Answer in Phase 3

1. **What's the theoretical ROI of each system?**
   - Flat betting strategy: What would we make/lose?
   - Confidence-weighted: Better returns?

2. **Which systems need recalibration?**
   - Is `similarity_balanced_v1` overconfident?
   - How to fix calibration issues?

3. **Which players are most/least predictable?**
   - Should we avoid predictions for certain players?
   - Are star players more predictable?

4. **What's the optimal betting strategy?**
   - Bet on all predictions?
   - Only high-confidence (>70%)?
   - Only best system (moving_average)?

5. **How much historical data do we have?**
   - Can we backfill to Jan 1?
   - Does accuracy change over time?

---

## Next Steps to Start Phase 3

1. **Review current data**:
   ```sql
   SELECT * FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
   ORDER BY game_date DESC;
   ```

2. **Read enhancement plan**:
   - `docs/08-projects/current/nba-grading-system/ENHANCEMENT-PLAN.md`
   - Phases 3-6 detailed there

3. **Choose what to build first**:
   - ROI calculator (highest value)
   - Calibration insights (quick win)
   - Historical backfill (foundation)

4. **Start coding**!

---

## Copy/Paste to Start New Session

```
Hi! I want to continue NBA grading work - Phase 3.

Context:
- Session 85 + Phases 1-2 are complete (grading system + alerts + dashboard)
- Ready to build Phase 3: ROI calculator and advanced features
- See handoff: docs/09-handoff/PHASE-3-START-HERE.md

Current state:
- 4,720 predictions graded (Jan 14-16)
- Alerts monitoring daily at 12:30 PM PT
- Dashboard live with system breakdown

What I want to build:
1. ROI simulation view in BigQuery
2. Dashboard integration showing theoretical returns
3. Calibration insights
4. Player performance insights
5. Historical backfill (grade Jan 1-13)

Can you help implement these Phase 3 features?
```

---

**Phase 3 is ready to start!** All groundwork is in place. Just start a new chat with the copy/paste prompt above.

**Estimated completion**: 6 hours (can split into 2 sessions)
**Priority**: Medium (nice to have, not critical)
**Dependencies**: All met ✅

---

**Last Updated**: 2026-01-17
**Created By**: Session 85 + Enhancements
**Status**: Ready to Start
