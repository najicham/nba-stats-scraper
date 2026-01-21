# Phase 4: NBA Grading System Enhancements

**Status:** Planning
**Created:** 2026-01-17
**Phase 3 Completion Date:** 2026-01-17
**Target Start:** Q1 2026

## Executive Summary

Phase 3 of the NBA Grading System delivered a comprehensive prediction grading and analysis platform with:
- 6 alert types for proactive monitoring
- 7 dashboard tabs for ROI, calibration, and player insights
- 11,554 predictions graded across 16 days
- All 6 prediction systems profitable (4.41% - 19.99% ROI)

Phase 4 will focus on **automation, optimization, and expansion** to transform the grading system from a monitoring tool into an intelligent, self-improving prediction platform.

---

## Phase 3 Achievements (Context)

### What Was Built
1. **Grading Infrastructure** - Automated daily grading via BigQuery scheduled queries
2. **ROI Analysis** - Betting simulation with -110 odds across all systems
3. **Player Insights** - Identification of predictable/unpredictable players
4. **Calibration Monitoring** - Confidence vs accuracy tracking
5. **Alert System** - 6 alert types including weekly summaries
6. **Admin Dashboard** - 7 tabs with comprehensive analytics

### Key Metrics (16 Days of Data)
- **Best System:** catboost_v8 (19.99% high-conf ROI, 17.26% flat)
- **Most Consistent:** ensemble_v1 (11.77% high-conf ROI)
- **Most Volatile:** LeBron James (6.25% accuracy across all systems)
- **Most Predictable:** 4 players with 100% accuracy (15+ predictions)

### Known Issues (Fixed in Session 91)
1. ~~catboost_v8 confidence format inconsistency~~ ✅ Already normalized
2. ~~similarity_balanced_v1 overconfident by 27 pts~~ ✅ Recalibrated
3. ~~zone_matchup_v1 low ROI (4.41%)~~ ✅ Critical bug fixed (inverted defense logic)

---

## Phase 4 Initiatives

### Priority 1: Automated Recalibration Pipeline

**Problem:** Systems become overconfident or underconfident as conditions change. Currently requires manual intervention.

**Solution:** Automated weekly recalibration based on actual accuracy.

**Implementation:**
```
1. Weekly Analysis Job
   - Query last 30 days of predictions
   - Calculate actual accuracy by confidence bucket
   - Detect drift >5% between confidence and accuracy

2. Auto-Calibration
   - Generate new confidence multipliers
   - Deploy updated prediction systems automatically
   - Alert Slack on recalibration events

3. Rollback Safety
   - Track calibration history
   - Auto-rollback if accuracy degrades >10%
   - Manual approval for major changes
```

**Technical Approach:**
- BigQuery scheduled query for analysis
- Cloud Function for calibration logic
- GitHub Actions for deployment
- Firestore for calibration history

**Estimated Effort:** 2-3 weeks
**Expected Impact:** Maintain optimal confidence levels automatically, improve betting decisions

---

### Priority 2: Player-Specific Model Optimization

**Problem:** LeBron James 6.25% accurate, Donovan Mitchell 7.02% accurate. Some players are systematically unpredictable.

**Solution:** Identify player archetypes and apply specialized prediction strategies.

**Implementation:**
```
1. Player Archetype Analysis
   - Cluster players by predictability patterns
   - Identify common features of unpredictable players
   - Detect load management, coaching changes, etc.

2. Archetype-Specific Systems
   - High-volume stars (LeBron, Giannis): Reduce confidence, widen thresholds
   - Consistent role players: Increase confidence
   - Injury-prone: Add injury risk multiplier
   - Rookies/young players: Use limited sample strategies

3. Dynamic System Selection
   - Route players to best-performing system for their archetype
   - Ensemble different systems per archetype
   - Track archetype drift over season
```

**Technical Approach:**
- Python clustering analysis (scikit-learn)
- New prediction routing logic in worker
- BigQuery archetype tracking table
- Dashboard tab for archetype insights

**Estimated Effort:** 3-4 weeks
**Expected Impact:** Improve accuracy on difficult players, reduce bad bets

---

### Priority 3: Real-Time Prediction Updates

**Problem:** Predictions become stale as news breaks (injuries, lineup changes, weather).

**Solution:** WebSocket-based live prediction updates with news integration.

**Implementation:**
```
1. News Monitoring
   - Monitor Twitter/ESPN for breaking news
   - Detect injury reports, lineup changes
   - Extract player names and impact assessment

2. Real-Time Recalculation
   - Trigger prediction update on news event
   - Adjust confidence based on news severity
   - Push updates via WebSocket to dashboard

3. User Notifications
   - Alert when high-confidence prediction changes
   - Show news event that triggered update
   - Track update history per prediction
```

**Technical Approach:**
- Pub/Sub for news events
- WebSocket server (Socket.io)
- News AI analysis (existing system)
- Dashboard WebSocket client

**Estimated Effort:** 4-5 weeks
**Expected Impact:** React to breaking news, avoid stale predictions

---

### Priority 4: MLB Grading System Expansion

**Problem:** MLB predictions have no grading infrastructure. Can't measure accuracy or ROI.

**Solution:** Extend NBA grading system to MLB.

**Implementation:**
```
1. Schema Replication
   - Create mlb_predictions.prediction_grades table
   - Replicate BigQuery views (ROI, calibration, player insights)
   - Update scheduled queries for MLB

2. MLB-Specific Adjustments
   - Pitcher vs batter matchups
   - Ballpark factors
   - Weather impact (outdoor vs dome)
   - Innings pitched limits

3. Unified Dashboard
   - Sport selector in admin dashboard
   - Shared alert infrastructure
   - Cross-sport comparison tab
```

**Technical Approach:**
- Reuse NBA grading code with sport parameter
- MLB-specific BigQuery views
- Dashboard sport toggle
- Unified alert service

**Estimated Effort:** 3-4 weeks
**Expected Impact:** Measure MLB prediction quality, identify profitable MLB systems

---

### Priority 5: Historical Backtesting Framework

**Problem:** Can't test new strategies on historical data. Must wait for real games.

**Solution:** Backtesting framework to simulate betting strategies on past data.

**Implementation:**
```
1. Backtest Engine
   - Replay historical predictions
   - Apply betting strategy (Kelly Criterion, flat betting, etc.)
   - Calculate ROI, Sharpe ratio, drawdown

2. Strategy Library
   - High-confidence only (>70%)
   - System-specific (catboost_v8 only)
   - Player-specific (avoid LeBron)
   - Combination strategies (ensemble of top 3)

3. Optimization
   - Grid search for optimal thresholds
   - Walk-forward validation
   - Monte Carlo simulation for risk assessment

4. Dashboard Integration
   - Backtest results comparison
   - Strategy performance charts
   - Risk/reward scatter plots
```

**Technical Approach:**
- Python backtesting library
- BigQuery for historical data
- Cloud Run job for large backtests
- Dashboard tab for results

**Estimated Effort:** 4-5 weeks
**Expected Impact:** Test strategies risk-free, optimize betting approach

---

### Priority 6: Advanced Anomaly Detection

**Problem:** Current alerts are threshold-based. Can't detect subtle patterns or anomalies.

**Solution:** ML-based anomaly detection for prediction quality.

**Implementation:**
```
1. Anomaly Detection Models
   - Time series forecasting (Prophet)
   - Isolation Forest for outliers
   - LSTM for sequence anomalies

2. Anomaly Types
   - Sudden accuracy drop across all systems
   - Single system divergence from ensemble
   - Unusual confidence distribution
   - Geographic patterns (home/away bias)

3. Root Cause Analysis
   - Correlate anomalies with external events
   - Identify common features of anomalous predictions
   - Suggest remediation actions

4. Alert Integration
   - New alert type: "Anomaly Detected"
   - Include anomaly score and likely cause
   - Link to investigation dashboard
```

**Technical Approach:**
- scikit-learn, Prophet for models
- Cloud Function for daily analysis
- BigQuery ML for in-database detection
- Alert service integration

**Estimated Effort:** 3-4 weeks
**Expected Impact:** Early detection of systematic issues, faster root cause analysis

---

## Phase 4 Roadmap

### Month 1: Foundation
- **Week 1-2:** Automated Recalibration Pipeline (Priority 1)
- **Week 3-4:** Player-Specific Model Optimization setup (Priority 2)

### Month 2: Intelligence
- **Week 5-6:** Complete Player Archetypes (Priority 2)
- **Week 7-8:** Real-Time Updates infrastructure (Priority 3)

### Month 3: Expansion
- **Week 9-10:** MLB Grading System (Priority 4)
- **Week 11-12:** Historical Backtesting Framework (Priority 5)

### Month 4: Polish
- **Week 13-14:** Advanced Anomaly Detection (Priority 6)
- **Week 15-16:** Documentation, testing, optimization

---

## Success Metrics

### Quantitative
- **ROI Improvement:** +5% absolute improvement across systems
- **Accuracy:** 65%+ accuracy on high-confidence predictions
- **Uptime:** 99.9% grading system availability
- **Latency:** Real-time updates within 60 seconds of news

### Qualitative
- Self-calibrating system (minimal manual intervention)
- Cross-sport capability (NBA + MLB)
- Proactive anomaly detection (vs reactive alerts)
- Profitable betting strategies validated via backtesting

---

## Technical Dependencies

### Infrastructure
- BigQuery scheduled queries (existing)
- Cloud Functions (existing)
- Cloud Run workers (existing)
- Pub/Sub for events (existing)
- WebSocket server (new)

### Data
- 30+ days of grading data for recalibration
- Historical predictions for backtesting (2+ years ideal)
- News API integration (existing)
- MLB prediction data (exists, needs grading)

### Skills/Knowledge
- Machine learning (scikit-learn, Prophet)
- Time series analysis
- Real-time systems (WebSockets)
- Backtesting frameworks
- Statistical analysis

---

## Risk Assessment

### High Risk
1. **Real-time updates complexity** - WebSockets at scale can be challenging
2. **MLB grading accuracy** - Baseball has different dynamics than basketball

### Medium Risk
1. **Automated recalibration errors** - Could make systems worse
2. **Player archetype drift** - Players change roles over season

### Low Risk
1. **Backtesting framework** - Well-understood problem
2. **Anomaly detection** - Additive, doesn't break existing system

### Mitigation Strategies
- Gradual rollout with kill switches
- A/B testing for automated changes
- Manual approval gates for critical updates
- Comprehensive monitoring and rollback procedures

---

## Resource Requirements

### Engineering Time
- **Phase 4 Total:** ~12-16 weeks (3-4 months)
- **Per Initiative:** 2-5 weeks depending on complexity
- **Maintenance:** ~20% ongoing after completion

### Infrastructure Costs (Incremental)
- WebSocket server: ~$50/month (Cloud Run)
- Additional BigQuery queries: ~$20/month
- Cloud Functions for automation: ~$10/month
- **Total:** ~$80/month incremental

### Data Storage
- Historical backtest results: ~10GB/year
- Anomaly detection models: ~1GB
- Real-time event log: ~5GB/month

---

## Open Questions

1. **Recalibration Frequency:** Weekly? Daily? Event-triggered?
2. **Real-time Updates:** Push to all users or subscription-based?
3. **MLB Priority:** Should MLB grading come before backtesting?
4. **Backtesting Scope:** How many years of historical data?
5. **Player Archetypes:** How many clusters? Manual or automated?

---

## Next Steps

1. **Validate Fixes (1-2 days):**
   - Monitor similarity_balanced_v1 confidence drop
   - Monitor zone_matchup_v1 ROI improvement
   - Collect 2-3 days of new grading data

2. **Stakeholder Review:**
   - Review Phase 4 priorities
   - Adjust roadmap based on business goals
   - Approve budget and timeline

3. **Kick off Priority 1:**
   - Design recalibration algorithm
   - Set up BigQuery analysis queries
   - Build Cloud Function for automation

4. **Document Current State:**
   - Capture Phase 3 final metrics
   - Document lessons learned
   - Archive Phase 3 project files

---

## References

- Phase 3 Complete: `docs/09-handoff/PHASE-3-COMPLETE.md`
- Session 90: `docs/09-handoff/SESSION-90-COMPLETE.md`
- Session 91: This session (deployment + data quality fixes)
- Admin Dashboard: https://nba-admin-dashboard-756957797294.us-west2.run.app
- Alert Service: https://nba-grading-alerts-f7p3g7f6ya-wl.a.run.app

---

**Status:** ✅ Planning document complete - ready for review and prioritization
