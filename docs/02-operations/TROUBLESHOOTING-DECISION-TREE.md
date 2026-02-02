# Troubleshooting Decision Tree

**Purpose**: Quick diagnostic guide for common issues
**Last Updated**: 2026-02-02

---

## How to Use This Guide

1. Start with your symptom below
2. Follow the decision tree
3. Execute suggested commands
4. If unresolved, escalate with collected evidence

---

## Symptom 1: Predictions Not Generating

### Decision Tree

```
Predictions count = 0 for today
    │
    ├─▶ Are games scheduled today?
    │   Command: bq query "SELECT COUNT(*) FROM nba_reference.nba_schedule WHERE game_date=CURRENT_DATE()"
    │   │
    │   ├─▶ NO (0 games) ──▶ ✅ Expected, no action needed
    │   │
    │   └─▶ YES (>0 games) ──▶ Continue
    │
    ├─▶ Is feature store populated?
    │   Command: bq query "SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date=CURRENT_DATE()"
    │   │
    │   ├─▶ NO (0 records) ──▶ **ROOT CAUSE**: Phase 3/4 not running
    │   │   Fix: Check phase3/phase4 services
    │   │   Logs: gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"'
    │   │
    │   └─▶ YES (>0 records) ──▶ Continue
    │
    ├─▶ Is prediction-worker healthy?
    │   Command: curl $(gcloud run services describe prediction-worker --region=us-west2 --format="value(status.url)")/health
    │   │
    │   ├─▶ NO (non-200) ──▶ **ROOT CAUSE**: Service unhealthy
    │   │   Fix: Check logs, restart service
    │   │   Logs: gcloud logging read 'resource.labels.service_name="prediction-worker" AND severity>=ERROR'
    │   │
    │   └─▶ YES (200 OK) ──▶ Continue
    │
    └─▶ Is prediction-coordinator running?
        Command: gcloud scheduler jobs describe overnight-predictions --location=us-west2
        │
        ├─▶ Scheduler disabled ──▶ **ROOT CAUSE**: Scheduler paused
        │   Fix: gcloud scheduler jobs resume overnight-predictions --location=us-west2
        │
        └─▶ Scheduler enabled ──▶ Check execution logs
            Command: gcloud scheduler jobs run overnight-predictions --location=us-west2
```

### Common Causes & Fixes

| Cause | Detection | Fix | Session Reference |
|-------|-----------|-----|-------------------|
| No games scheduled | `nba_schedule` empty | ✅ Expected | N/A |
| Feature store empty | Phase 3/4 failed | Check processor logs, rerun | Session 59 |
| Worker crashed | Health check fails | Restart service, check logs | Session 64 |
| Scheduler disabled | Job state=DISABLED | Resume scheduler | N/A |
| Build commit stale | `build_commit_sha` old | Redeploy worker | Session 64 |

---

## Symptom 2: Vegas Line Coverage Low (<90%)

### Decision Tree

```
Vegas coverage < 90%
    │
    ├─▶ Is BettingPros scraper running?
    │   Command: bq query "SELECT MAX(processed_at) FROM nba_raw.bettingpros_player_points_props"
    │   │
    │   ├─▶ Last update > 4 hours ago ──▶ **ROOT CAUSE**: Scraper not running
    │   │   Fix: Check nba-scrapers service
    │   │   Logs: gcloud logging read 'resource.labels.service_name="nba-scrapers" AND textPayload=~"bettingpros"'
    │   │   Deploy: ./bin/deploy-service.sh nba-scrapers
    │   │
    │   └─▶ Recent updates (<1 hour) ──▶ Continue
    │
    ├─▶ Is VegasLineSummaryProcessor running?
    │   Command: bq query "SELECT MAX(processed_at) FROM nba_predictions.vegas_line_summary WHERE game_date>=CURRENT_DATE()"
    │   │
    │   ├─▶ No recent data ──▶ **ROOT CAUSE**: Processor not running
    │   │   Fix: Check phase4-processors service
    │   │   Logs: gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors"'
    │   │   Deploy: ./bin/deploy-service.sh nba-phase4-precompute-processors
    │   │
    │   └─▶ Recent data ──▶ Continue
    │
    └─▶ Is feature store builder using Vegas data correctly?
        Command: bq query "SELECT AVG(features[OFFSET(25)]) FROM ml_feature_store_v2 WHERE game_date=CURRENT_DATE()"
        │
        ├─▶ Result = 0 or NULL ──▶ **ROOT CAUSE**: Feature not populating
        │   Fix: Check Phase 4 feature builder logic
        │   File: data_processors/precompute/ml_feature_store/feature_builder.py
        │
        └─▶ Result > 0 ──▶ Data quality issue, investigate BettingPros source
```

### Quick Checks

```bash
# 1. End-to-end pipeline check
./bin/monitoring/check_vegas_line_coverage.sh --days 1

# 2. Check each stage
bq query "SELECT COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date=CURRENT_DATE()"
bq query "SELECT COUNT(*) FROM nba_predictions.vegas_line_summary WHERE game_date=CURRENT_DATE()"
bq query "SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date=CURRENT_DATE() AND features[OFFSET(25)]>0"
```

### Session 76 Recap

**What Happened**: Coverage dropped from 92% to 44%
**Root Cause**: `VegasLineSummaryProcessor` had a bug in line aggregation
**Detection**: Weekly manual check (should have been automated)
**Fix**: Fixed processor logic, deployed new code
**Prevention**: `unified-health-check.sh` now runs every 6 hours

---

## Symptom 3: Prediction Hit Rate Degraded

### Decision Tree

```
Hit rate < 55% for premium picks
    │
    ├─▶ Is grading completeness ≥80%?
    │   Command: ./bin/monitoring/check_grading_completeness.sh
    │   │
    │   ├─▶ NO (<80%) ──▶ **ROOT CAUSE**: Incomplete grading
    │   │   Impact: Hit rate calculation invalid (Session 68 scenario)
    │   │   Fix: Check nba-grading-service, ensure games are Final
    │   │   Query: bq query "SELECT COUNT(*) FROM nba_reference.nba_schedule WHERE game_date=CURRENT_DATE()-1 AND game_status=3"
    │   │
    │   └─▶ YES (≥80%) ──▶ Continue
    │
    ├─▶ Is deployed code current?
    │   Command: gcloud run services describe prediction-worker --region=us-west2 --format="value(metadata.labels.commit-sha)"
    │   Compare to: git log -1 --format="%h"
    │   │
    │   ├─▶ Commits behind ──▶ **ROOT CAUSE**: Stale code (Session 64 scenario)
    │   │   Fix: ./bin/deploy-service.sh prediction-worker
    │   │
    │   └─▶ Up to date ──▶ Continue
    │
    ├─▶ Is feature quality degraded?
    │   Command: Run prediction quality tests
    │   Test: pytest tests/integration/predictions/test_prediction_quality_regression.py -v
    │   │
    │   ├─▶ Tests fail ──▶ **ROOT CAUSE**: Feature quality issue
    │   │   Check: Feature store completeness, data quality
    │   │   Query: bq query "SELECT AVG(completeness_percentage) FROM ml_feature_store_v2 WHERE game_date>=CURRENT_DATE()-7"
    │   │
    │   └─▶ Tests pass ──▶ Continue
    │
    └─▶ Is this data leakage? (Session 66 scenario)
        Check: Hit rate > 80% overall?
        │
        ├─▶ YES (>80%) ──▶ **ROOT CAUSE**: Possible data leakage
        │   Action: Review feature generation logic
        │   Ensure: No game results in features
        │   Test: Run test_no_data_leakage_in_recent_predictions
        │
        └─▶ NO (55-80%) ──▶ Normal variance, monitor trend
```

### Quick Performance Check

```bash
# Premium picks hit rate (should be 55-58%)
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as bets,
  ROUND(100.0*COUNTIF(prediction_correct)/COUNT(*),1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id='catboost_v9'
  AND game_date>=CURRENT_DATE()-7
  AND confidence_score>=0.92
  AND ABS(predicted_points-line_value)>=3
"
```

---

## Symptom 4: Deployment Drift Detected

### Decision Tree

```
Service showing as STALE
    │
    ├─▶ Is local repo synced with remote?
    │   Command: git fetch && git status
    │   │
    │   ├─▶ Behind remote ──▶ git pull origin main
    │   │   Then: Check drift again
    │   │
    │   └─▶ Up to date ──▶ Continue
    │
    ├─▶ Was there a recent bug fix committed?
    │   Command: git log --oneline -10
    │   │
    │   ├─▶ YES ──▶ **ACTION REQUIRED**: Deploy immediately
    │   │   Fix: ./bin/deploy-service.sh <service-name>
    │   │   Reason: Bug fix not in production
    │   │
    │   └─▶ NO ──▶ Continue
    │
    └─▶ How many commits behind?
        Command: ./bin/check-deployment-drift.sh --verbose
        │
        ├─▶ >50 commits ──▶ **CRITICAL**: Major drift
        │   Action: Review changes, test thoroughly, deploy
        │   Risk: High probability of breaking changes
        │
        └─▶ <50 commits ──▶ **WARNING**: Minor drift
            Action: Deploy during maintenance window
```

### Prevention

- GitHub Action runs daily, creates issues automatically
- Pre-deployment checklist catches drift before deploy
- Unified health check monitors drift every 6 hours

---

## Symptom 5: Schema Mismatch Error

### Decision Tree

```
BigQuery write fails: "Invalid field"
    │
    ├─▶ Did pre-commit hook run?
    │   Command: pre-commit run validate-schema-fields
    │   │
    │   ├─▶ Hook passed ──▶ Schema should be aligned
    │   │   Check: Was schema migration applied?
    │   │   Action: Review ALTER TABLE statements
    │   │
    │   └─▶ Hook failed or not run ──▶ **ROOT CAUSE**: Schema mismatch
    │       Fix: Add missing fields to schema
    │       File: schemas/bigquery/predictions/01_player_prop_predictions.sql
    │
    └─▶ Apply schema migration
        Command: bash /tmp/apply_schema_migration.sh
        Or: Manually execute ALTER TABLE statements
```

### Quick Schema Check

```bash
# Validate schema alignment
python .pre-commit-hooks/validate_schema_fields.py

# Check BigQuery schema
bq show --schema nba-props-platform:nba_predictions.player_prop_predictions | jq '.[].name' | sort
```

---

## Symptom 6: Heartbeat Document Proliferation

### Decision Tree

```
Firestore has >100 heartbeat documents
    │
    ├─▶ Check document ID pattern
    │   Command: Query Firestore processor_heartbeats collection
    │   │
    │   ├─▶ Pattern: {processor}_{date}_{run_id} ──▶ **ROOT CAUSE**: Old heartbeat code
    │   │   Fix: Deploy services with Session 61 heartbeat fix
    │   │   Cleanup: python bin/cleanup-heartbeat-docs.py
    │   │
    │   └─▶ Pattern: {processor} ──▶ ✅ Correct, investigate other cause
    │
    └─▶ Expected: ~30 documents (one per processor)
```

### Session 61 Fix

**Old Code** (WRONG):
```python
def doc_id(self) -> str:
    return f"{self.processor_name}_{self.data_date}_{self.run_id}"
    # Creates new doc every run → 3,500 docs/day!
```

**New Code** (CORRECT):
```python
@property
def doc_id(self) -> str:
    return self.processor_name
    # One doc per processor → 30 docs total
```

---

## Escalation Matrix

| Symptom | Severity | Response Time | Owner |
|---------|----------|---------------|-------|
| No predictions | P0 - Critical | <1 hour | On-call engineer |
| Vegas coverage <50% | P0 - Critical | <2 hours | Data team |
| Hit rate <50% | P1 - High | <4 hours | ML team |
| Deployment drift >100 commits | P1 - High | <8 hours | DevOps |
| Schema mismatch | P1 - High | <4 hours | Engineering |
| Grading incomplete | P2 - Medium | <24 hours | Data team |
| Heartbeat proliferation | P3 - Low | <1 week | DevOps |

---

## Quick Reference Commands

### Health Checks
```bash
./bin/monitoring/unified-health-check.sh --verbose
./bin/monitoring/check_vegas_line_coverage.sh --days 1
./bin/monitoring/check_grading_completeness.sh
```

### Deployment
```bash
./bin/pre-deployment-checklist.sh <service>
./bin/deploy-service.sh <service>
./bin/monitoring/post-deployment-monitor.sh <service> --auto-rollback
```

### Debugging
```bash
# Service logs
gcloud logging read 'resource.labels.service_name="<service>" AND severity>=ERROR' --limit=20

# Recent predictions
bq query "SELECT COUNT(*),MIN(created_at),MAX(created_at) FROM nba_predictions.player_prop_predictions WHERE game_date=CURRENT_DATE()"

# Feature store check
bq query "SELECT COUNT(*),AVG(completeness_percentage) FROM ml_feature_store_v2 WHERE game_date=CURRENT_DATE()"
```

---

## Related Documentation

- [Deployment Runbooks](./runbooks/nba/)
- [Prevention & Monitoring Architecture](../01-architecture/prevention-monitoring-architecture.md)
- [Data Flow Documentation](../01-architecture/data-flow-comprehensive.md)
- [Session Handoffs](../09-handoff/)
