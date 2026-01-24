# Session 86: Platform Maintenance & Optimization

**Status**: Ongoing (use as needed)
**Priority**: Variable
**Estimated Scope**: 1-3 hours per task
**Prerequisites**: None (general maintenance)

---

## Purpose

This handoff document is for **general platform maintenance, bug fixes, and optimizations** that don't fit into a specific feature session.

Use this session type when you need to:
- Fix bugs discovered in production
- Optimize performance
- Clean up technical debt
- Investigate anomalies
- Improve documentation
- Refactor code

---

## Current Platform State (as of 2026-01-17)

### ✅ What's Working Well
- **Prediction generation**: 100% ML-based predictions, no fallbacks
- **Model loading**: Fixed and stable (CATBOOST_V8_MODEL_PATH preserved)
- **Data ingestion**: BDL + NBA.com boxscores ingesting reliably
- **Orchestration**: 0% failure rate on workflows
- **Alerting**: Week 1 critical alerts deployed and healthy

### ⚠️ Known Issues to Address

From Session 82 validation:

1. **Phase 4 Dependency Failures**:
   - `PlayerGameSummaryProcessor on 2026-01-15` failed completeness check
   - **Impact**: Minimal (doesn't affect current day)
   - **Investigation needed**: Why did 2026-01-15 fail?

2. **ESPN Boxscore Lag**:
   - 0 ESPN boxscores for 2026-01-16 (expected to lag BDL)
   - **Investigation needed**: Is this normal? Should we alert on it?

3. **Prediction Grading Not Implemented**:
   - See Session 85 for implementation
   - This is a feature, not maintenance

4. **FeatureValidationError 500s**:
   - Enhanced validation catching invalid features for old games
   - **Status**: Working as designed
   - **Question**: Should we filter out old games from retry?

### 🔧 Technical Debt

1. **Staging Tables Cleanup**:
   - 200+ `_staging_batch_2025_11_19_*` tables in nba_predictions dataset
   - **Action**: Investigate if safe to delete, create cleanup job

2. **Documentation Gaps**:
   - NBA grading system not documented (until Session 85)
   - No troubleshooting guide for common issues
   - Missing architecture diagrams

3. **Alert Documentation**:
   - Week 2+ alerts not yet documented (until Sessions 83-84)

4. **Code Quality**:
   - No unit tests mentioned in codebase review
   - Deployment scripts could use error handling improvements

---

## Common Maintenance Tasks

### Task 1: Investigate Production Issue

**When to use**: Something is broken or behaving unexpectedly

**Template**:
1. **Identify the issue**:
   - What's the symptom?
   - When did it start?
   - What's the impact?

2. **Gather context**:
   - Recent deployments?
   - Log analysis?
   - Metrics/dashboards?

3. **Root cause analysis**:
   - What's the underlying cause?
   - Why did it happen?

4. **Fix + validation**:
   - Apply fix
   - Verify issue resolved
   - Add monitoring to prevent recurrence

5. **Document**:
   - Update runbooks
   - Add to known issues list

### Task 2: Performance Optimization

**When to use**: System is slow or resource-constrained

**Areas to investigate**:
- BigQuery query performance (use EXPLAIN)
- Cloud Run instance sizing
- Model loading time
- Prediction latency
- Data pipeline bottlenecks

**Tools**:
```bash
# Check Cloud Run metrics
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform

# Check BigQuery query performance
bq show --job [job_id]

# Analyze logs for slow operations
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"completed in"' \
  --project=nba-props-platform \
  --limit=100
```

### Task 3: Data Quality Investigation

**When to use**: Predictions or data look wrong

**Checklist**:
- [ ] Check data sources (BDL, ESPN, NBA.com) for freshness
- [ ] Validate boxscore data quality
- [ ] Check feature pipeline outputs
- [ ] Verify model is loading correctly
- [ ] Review recent predictions for anomalies

**Queries**:
```sql
-- Check data freshness
SELECT
  'bdl_boxscores' as source,
  MAX(game_date) as latest_date,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_old
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
UNION ALL
SELECT
  'player_game_summary' as source,
  MAX(game_date) as latest_date,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_old
FROM `nba-props-platform.nba_analytics.player_game_summary`;

-- Check prediction distribution
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as count,
  ROUND(AVG(predicted_points), 1) as avg_predicted_points
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND system_id = 'catboost_v8'
GROUP BY confidence
ORDER BY confidence DESC;
```

### Task 4: Cleanup & Housekeeping

**When to use**: System needs cleanup

**Areas**:
1. **BigQuery tables**:
   - Delete old staging tables
   - Expire old logs
   - Archive historical data

2. **Cloud Storage**:
   - Clean up old model files
   - Remove temporary files
   - Organize bucket structure

3. **Cloud Run**:
   - Delete old revisions (keep last 5-10)
   - Review unused services

**Commands**:
```bash
# List staging tables
bq ls --max_results=500 nba-props-platform:nba_predictions | grep staging

# Delete old staging tables (be careful!)
# First, verify they're safe to delete
bq show nba-props-platform:nba_predictions._staging_batch_[ID]

# Delete (after verification)
bq rm -t nba-props-platform:nba_predictions._staging_batch_[ID]

# List Cloud Run revisions
gcloud run revisions list --service=prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform

# Delete old revisions (keep active + last 5)
gcloud run revisions delete [REVISION_NAME] \
  --region=us-west2 \
  --project=nba-props-platform
```

### Task 5: Documentation Updates

**When to use**: Docs are outdated or missing

**Key docs to maintain**:
- `docs/04-deployment/ALERT-RUNBOOKS.md`
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md`
- `docs/04-deployment/NBA-ENVIRONMENT-VARIABLES.md`
- Session handoff documents

**Process**:
1. Identify outdated section
2. Update with current information
3. Add examples if helpful
4. Test commands/queries still work
5. Commit with clear message

### Task 6: Cost Optimization

**When to use**: GCP costs are high

**Areas to investigate**:
1. **BigQuery costs**:
   - Query patterns
   - Table scans vs. partitioned queries
   - Frequent full table scans

2. **Cloud Run costs**:
   - Instance sizing
   - Cold starts
   - Request patterns

3. **Cloud Logging costs**:
   - Log volume
   - Log retention
   - Unnecessary verbose logging

**Tools**:
```bash
# Check BigQuery costs (last 30 days)
bq ls -j --max_results=100 --project_id=nba-props-platform

# View billing dashboard
gcloud billing projects describe nba-props-platform

# Check log volume
gcloud logging read 'timestamp>="2026-01-10T00:00:00Z"' \
  --project=nba-props-platform \
  --format=json | wc -l
```

---

## Specific Tasks to Consider

### Priority 1: Investigate 2026-01-15 Dependency Failure

**Context**: From Session 82, Phase 4 dependency check failed for 2026-01-15

**Investigation steps**:
```sql
-- Check what data exists for 2026-01-15
SELECT
  COUNT(*) as boxscore_count,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2026-01-15';

SELECT
  COUNT(*) as summary_count,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-15';

-- Check processor completions
SELECT *
FROM `nba-props-platform.nba_orchestration.processor_completions`
WHERE game_date = '2026-01-15'
ORDER BY completed_at DESC;
```

**Expected outcome**:
- Identify why PlayerGameSummaryProcessor failed
- Fix if needed, or document as known limitation
- Ensure doesn't affect current processing

### Priority 2: Staging Table Cleanup

**Context**: 200+ staging tables from 2025-11-19

**Investigation**:
```bash
# Count staging tables
bq ls --max_results=1000 nba-props-platform:nba_predictions | grep staging | wc -l

# Check one staging table to understand purpose
bq show --format=prettyjson nba-props-platform:nba_predictions._staging_batch_2025_11_19_[ID]

# Check if any recent staging tables (should they be cleaned automatically?)
bq ls nba-props-platform:nba_predictions | grep staging | grep 2026
```

**Decision**:
- Are these safe to delete?
- Should we implement automatic cleanup?
- Add to deployment script or separate cleanup job?

### Priority 3: ESPN Boxscore Monitoring

**Context**: ESPN had 0 boxscores for 2026-01-16

**Investigation**:
```sql
-- Check ESPN boxscore coverage over last 7 days
SELECT
  game_date,
  COUNT(*) as espn_boxscores,
  COUNT(DISTINCT game_id) as espn_games
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Compare to BDL coverage
SELECT
  'bdl' as source,
  game_date,
  COUNT(*) as boxscores,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
UNION ALL
SELECT
  'espn' as source,
  game_date,
  COUNT(*) as boxscores,
  COUNT(DISTINCT game_id) as games
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC, source;
```

**Decision**:
- Is ESPN lag normal?
- Do we need ESPN if NBA.com is primary?
- Should we alert on ESPN failures?

---

## Maintenance Schedule Recommendations

### Daily (Automated)
- Validation checks (similar to Session 82)
- Log monitoring for errors
- Alert review

### Weekly (Manual)
- Review Week 2+ digest report (from Session 84)
- Check grading accuracy trends (after Session 85)
- Review open issues and prioritize

### Monthly (Manual)
- Cost analysis and optimization
- Performance review
- Documentation updates
- Technical debt prioritization

---

## Tools & Resources

### Monitoring & Debugging
```bash
# Quick health check
cat << 'EOF' > /tmp/health_check.sh
#!/bin/bash
echo "=== NBA Platform Health Check ==="
echo ""
echo "Prediction Worker Status:"
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.traffic[0].revisionName,status.conditions[0].status)"
echo ""
echo "Recent Predictions:"
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT COUNT(*) as count, MAX(created_at) as latest
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = "catboost_v8"
   AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)'
echo ""
echo "Critical Alerts:"
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter="displayName:\"[CRITICAL] NBA\"" \
  --format="table(displayName,enabled)"
EOF
chmod +x /tmp/health_check.sh
```

### Useful Queries
See `docs/04-deployment/ALERT-RUNBOOKS.md` for runbook queries

---

## Success Criteria for Maintenance Sessions

After completing maintenance work:
- [ ] Issue resolved or documented
- [ ] Root cause identified
- [ ] Fix validated in production
- [ ] Monitoring/alerting updated if needed
- [ ] Documentation updated
- [ ] Handoff notes added to COPY_TO_NEXT_CHAT.txt (if relevant)

---

## When to Create a New Feature Session Instead

Use maintenance session for:
- Bug fixes
- Small optimizations
- Cleanup
- Investigation

Create new dedicated session for:
- New features (>4 hours work)
- Major refactoring
- Architecture changes
- Multi-component changes

**Rule of thumb**: If it needs its own handoff doc, it's not maintenance!

---

## Related Sessions

- **Session 82**: Current baseline (model fixes + Week 1 alerts)
- **Session 83-84**: Alerting (may generate maintenance tasks)
- **Session 85**: Grading (may expose data quality issues)

---

**Ready to use**: Start a new chat with specific maintenance task:

```
Session 86: Maintenance - [Specific Task]

Task: [Describe the issue/task]
Context: [Recent changes, symptoms, impact]
Priority: [High/Medium/Low]

Refer to: docs/09-handoff/SESSION-86-MAINTENANCE.md
Current state: docs/09-handoff/SESSION-82-IMPLEMENTATION-COMPLETE.md
```

**Estimated time**: Variable (1-3 hours typical)
