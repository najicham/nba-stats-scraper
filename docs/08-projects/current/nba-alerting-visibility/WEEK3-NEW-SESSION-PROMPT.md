# Week 3 Dashboards - New Session Prompt

**Copy everything below the line into a new Claude Code chat**

---

# NBA Alerting Week 3: Dashboards & Visibility

## Context

I'm continuing the NBA Alerting & Visibility project. **Weeks 1-2 are complete** with 6 fully autonomous alerts deployed. Now I want to implement **Week 3: Dashboards & Visibility**.

## What Was Already Completed (Weeks 1-2)

**Time Invested**: 8.5 hours (vs 26 estimated - 67% efficiency)
**Status**: ✅ 100% autonomous monitoring achieved

### Alerts Deployed (6 total - all autonomous):
1. `[CRITICAL] NBA Model Loading Failures` - Real-time log-based
2. `[CRITICAL] NBA High Fallback Prediction Rate` - Real-time log-based
3. `[WARNING] NBA Stale Predictions` - Real-time log-based (absence detection)
4. `[WARNING] NBA High DLQ Depth` - Real-time Pub/Sub metrics
5. `[WARNING] NBA Feature Pipeline Stale` - Cloud Scheduler (hourly)
6. `[WARNING] NBA Confidence Distribution Drift` - Cloud Scheduler (every 2 hours)

### Infrastructure Created:
- 5 log-based metrics
- 6 alert policies (all enabled)
- 2 Cloud Run Jobs (monitoring scripts)
- 2 Cloud Scheduler jobs (hourly + every 2 hours)
- 1 container image: `gcr.io/nba-props-platform/nba-monitoring`
- Unified health check script: `bin/alerts/check_system_health.sh`
- Comprehensive runbooks: `docs/04-deployment/ALERT-RUNBOOKS.md`

**Impact**: Detection time improved from 3 days → < 5 minutes (864x faster)

## Current System State (Verify First)

```bash
# Check all alerts are enabled
gcloud alpha monitoring policies list --project=nba-props-platform --format="table(displayName,enabled)" | grep NBA

# Check Cloud Scheduler is running
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep nba-

# Run health check
./bin/alerts/check_system_health.sh
```

**Expected**: All 6 NBA alerts enabled, 2 schedulers running, system healthy

## Week 3 Scope: Dashboards & Visibility

**Goal**: Add visual visibility and daily summaries (optional polish on top of autonomous alerts)

**Estimated Time**: 10 hours (likely ~3 actual based on 67% efficiency)

### Task 1: Cloud Monitoring Dashboard (1.5 hours)
Create custom dashboard in Google Cloud Monitoring with panels for:
- Model loading success rate (last 24h)
- Fallback prediction rate (last 24h)
- Confidence score distribution (today)
- Predictions generated (last 7 days)
- Service uptime (last 30 days)
- Environment variable stability (last 30 days)

**Files to reference**:
- `docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md` (lines 441-480) - Dashboard spec
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md` (Week 3 section) - Requirements

**Deliverable**: Dashboard URL, screenshot or YAML export

---

### Task 2: Daily Prediction Summary to Slack (1 hour)
Set up automated daily summary sent to Slack each morning:

**Components**:
1. BigQuery scheduled query (runs 9 AM daily)
2. Pub/Sub topic for results
3. Cloud Function to format and send to Slack
4. Message format with prediction stats

**Query Template** (from ALERTING-AND-VISIBILITY-STRATEGY.md line 398):
```sql
SELECT
  CURRENT_DATE() as report_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  COUNTIF(confidence_score = 0.50) as fallback_count,
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
GROUP BY system_id
```

**Slack Channel**: Create or use existing (recommend #predictions-summary)

**Deliverable**: Daily summaries posting automatically

---

### Task 3: Quick Status Script (30 min)
Create `bin/alerts/quick_status.sh` that shows:
- Last prediction time
- DLQ depth
- Feature freshness
- Alert status
- Scheduler status

**This is simpler than the full health check** - just key metrics in one glance.

**Deliverable**: Script that runs in < 5 seconds

---

## Key Files & Locations

### Documentation (Read These First):
- **Project README**: `docs/08-projects/current/nba-alerting-visibility/README.md`
- **Documentation Index**: `docs/08-projects/current/nba-alerting-visibility/DOCUMENTATION-INDEX.md`
- **Week 1-2 Handoff**: `docs/08-projects/current/nba-alerting-visibility/SESSION-83-FINAL-HANDOFF.md`
- **Alert Runbooks**: `docs/04-deployment/ALERT-RUNBOOKS.md`
- **Implementation Roadmap**: `docs/04-deployment/IMPLEMENTATION-ROADMAP.md`
- **Alerting Strategy**: `docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md`

### Scripts:
- **Health Check**: `bin/alerts/check_system_health.sh`
- **Feature Monitor**: `bin/alerts/monitor_feature_staleness.sh`
- **Confidence Monitor**: `bin/alerts/monitor_confidence_drift.sh`

### Cloud Resources:
- **Project**: nba-props-platform
- **Region**: us-west2
- **Slack Channel**: Projects have a webhook at `projects/nba-props-platform/notificationChannels/13444328261517403081`

## Success Criteria for Week 3

- [ ] Cloud Monitoring dashboard created with all 6 panels
- [ ] Dashboard accessible and shows real data
- [ ] Daily prediction summary scheduled and tested
- [ ] Summary posts to Slack successfully
- [ ] Quick status script created and working
- [ ] Documentation updated (IMPLEMENTATION-ROADMAP.md, new handoff)
- [ ] Session handoff document created

## Important Notes

### Cost Considerations:
- Current system: $4.38/month
- BigQuery scheduled query: +$0.05/month
- Cloud Function: +$0.03/month
- Total Week 3 additions: ~$0.08/month

### Week 1-2 Context:
The CatBoost V8 incident (Jan 14-17, 2026) caused 1,071 degraded predictions over 3 days because:
- Missing `CATBOOST_V8_MODEL_PATH` environment variable
- Model failed to load → all predictions used 50% confidence fallback
- No alerts triggered → detected only through manual investigation after 3 days

Weeks 1-2 fixed this with autonomous alerts. Week 3 adds visual polish.

### GCP Project Context:
- **Project**: nba-props-platform
- **Main Service**: prediction-worker (Cloud Run, us-west2)
- **Database**: BigQuery dataset `nba_predictions`
- **Main Table**: `player_prop_predictions`
- **Active Model**: CatBoost V8

## Recommended Approach

1. **Start by verifying system state** (run commands above)
2. **Read documentation index** to understand structure
3. **Create todo list** for Week 3 tasks
4. **Implement in order**: Dashboard → Daily Summary → Quick Status
5. **Test each component** before moving to next
6. **Update documentation** as you go
7. **Create session handoff** when complete

## Questions to Ask Me

- Do you want the dashboard in a specific format?
- Which Slack channel for daily summaries?
- Any specific metrics to highlight?
- Should quick status be super minimal or detailed?

## Expected Time

Based on Week 1-2 efficiency (67% time saved):
- **Estimated**: 10 hours
- **Likely Actual**: ~3 hours
- **Could be done in one session**

## File to Update When Complete

1. `docs/04-deployment/IMPLEMENTATION-ROADMAP.md` - Mark Week 3 complete
2. `docs/08-projects/current/nba-alerting-visibility/README.md` - Update status
3. Create `docs/08-projects/current/nba-alerting-visibility/SESSION-XX-WEEK3-COMPLETE.md`

---

**Ready to start Week 3!** Please begin by verifying the system state, then create a todo list and start with the Cloud Monitoring dashboard.
