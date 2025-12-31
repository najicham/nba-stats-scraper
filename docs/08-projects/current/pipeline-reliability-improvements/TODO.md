# Pipeline Reliability Improvements - Task List

**Last Updated:** December 30, 2025 (Evening Session)
**Status:** Active Development

---

## Deployment Status (Dec 30)

| Component | Status | Notes |
|-----------|--------|-------|
| Phase 6 (pre-export validation) | Deployed | Revision phase6-export-00005-giy |
| Self-heal (12:45 PM timing) | Deployed | Revision self-heal-predictions-00002-bom |
| Admin dashboard (action endpoints) | Deployed | Revision nba-admin-dashboard-00003-x6l |
| Prediction worker (lazy import) | Deployed | Earlier today |

---

## High Priority Tasks

### P1: Performance Issues

- [ ] **Investigate PlayerDailyCacheProcessor slowdown**
  - Current: 48.21s (3-day avg) vs 34.52s (7-day avg) = +39.7%
  - Root cause analysis needed:
    - Check if data volume increased with season progression
    - Profile the 4 extract queries for bottlenecks
    - Review completeness checking overhead
    - Consider caching completeness checker results
  - File: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

- [ ] **Fix MERGE FLOAT64 partitioning error**
  - Error: `Invalid MERGE query: 400 Partitioning by expressions of type FLOAT64 is not allowed`
  - Location: `predictions/worker/batch_staging_writer.py:302-315`
  - Issue: ROW_NUMBER uses CAST(current_points_line AS STRING) but ON clause doesn't
  - Fix: Add CAST to both sides of the comparison in ON clause

### P2: Monitoring & Observability

- [ ] **P1-4: End-to-end pipeline latency tracking**
  - Create `nba_monitoring.pipeline_execution_log` table
  - Track: game_id, game_end_time, phase1-5_complete, grading_complete
  - Add game_end_time capture from live boxscore scraper
  - Define target SLA (e.g., 6 hours game_end → grading)
  - Create latency monitoring view

- [ ] **P1-5: DLQ monitoring and alerting**
  - Existing DLQs: `analytics-ready-dead-letter`, `line-changed-dead-letter`
  - Create Cloud Monitoring alert on DLQ message count > 0
  - Add DLQ status to admin dashboard
  - Create comprehensive DLQ checker for all subscriptions
  - Consider auto-replay mechanism after fixes

- [ ] **Add Firestore health to admin dashboard**
  - Integrate `monitoring/firestore_health_check.py` results
  - Show connectivity status, latency, stuck processors

- [ ] **Add processor slowdown alerts to dashboard**
  - Integrate `monitoring/processor_slowdown_detector.py` results
  - Show processors > 2x baseline with warning

### P3: Self-Healing Improvements

- [ ] **Extend self-heal to check Phase 2 data**
  - Add boxscore completeness check to self-heal
  - Add game context check for today
  - Trigger backfill if gaps detected
  - File: `orchestration/cloud_functions/self_heal/main.py`

- [ ] **Automatic backfill trigger**
  - Create `boxscore-backfill-trigger` Cloud Function
  - Listen to `boxscore-gaps-detected` topic
  - Trigger BDL player boxscores scraper for missing dates

- [ ] **Circuit breaker improvements**
  - Add per-processor thresholds based on criticality
  - Implement gradual recovery (N requests in half-open)
  - Distinguish transient vs permanent failures
  - Add state restoration on service restart
  - File: `shared/processors/patterns/circuit_breaker_mixin.py`

### P4: Documentation & Organization

- [ ] **Organize loose files in docs/08-projects/current/**
  - Move handoff files to `session-handoffs/` or archive
  - Move postmortem files to `postmortems/`
  - Consolidate pipeline/orchestration docs into this project
  - Clean up redundant documents

---

## Medium Priority Tasks

### M1: Alert Infrastructure

- [ ] **Email/Slack alerting for critical issues**
  - Firestore connectivity failures
  - Processor slowdowns > 3x baseline
  - DLQ message accumulation
  - Pipeline SLA breaches

- [ ] **PagerDuty integration for on-call**
  - Critical alerts should reach on-call engineer
  - Integrate with existing notification system

### M2: Dashboard Improvements

- [ ] **Real-time WebSocket updates**
  - Replace polling with WebSocket for live status
  - Show prediction generation progress

- [ ] **Historical performance dashboard**
  - Track duration trends over time
  - Weekly/monthly processor performance reports
  - Automatic regression detection

- [ ] **Unified monitoring dashboard**
  - Single pane of glass for all monitoring
  - Combine scraper, processor, prediction status

### M3: Data Quality

- [ ] **Fix prediction duplicates**
  - Use MERGE instead of WRITE_APPEND in worker
  - File: `predictions/worker/worker.py:996-1041`
  - Or: Add deduplication in tonight exporter

- [ ] **Pre-grading validation**
  - Check if player_game_summary exists before grading
  - Alert if analytics data missing

---

## Lower Priority Tasks

### L1: Resilience

- [ ] **BigQuery fallback for Firestore**
  - Currently Firestore is single point of failure for orchestration
  - Consider BigQuery-based fallback for phase completion tracking

- [ ] **Multi-source fallback for scrapers**
  - When BDL API fails, fall back to NBA.com
  - Priority: BDL → NBA.com → ESPN

- [ ] **Prediction worker autoscaling**
  - Dynamic scaling based on queue depth
  - Add metrics for Pub/Sub subscription backlog

### L2: Testing

- [ ] **Integration tests for orchestration flow**
  - Test phase transitions
  - Test failure recovery

- [ ] **Load tests for prediction worker**
  - Simulate high-volume prediction requests
  - Verify autoscaling behavior

- [ ] **Chaos testing**
  - What happens if Firestore is down?
  - What happens if BigQuery is slow?

### L3: Optimization

- [ ] **Batch consolidation optimization**
  - Currently merges all staging tables at once
  - Consider incremental consolidation during batch
  - Parallel consolidation for different game dates

- [ ] **Query performance monitoring**
  - Track BigQuery slot usage
  - Identify slow queries

---

## Completed Tasks (Dec 30)

- [x] Deploy Phase 6 with pre-export validation
- [x] Deploy self-heal with 12:45 PM timing
- [x] Deploy admin dashboard with action endpoints
- [x] Deploy prediction worker with lazy import fix
- [x] Create Firestore health check script
- [x] Create processor slowdown detector
- [x] Investigate PredictionCoordinator 8.2x slowdown (was boot failure)

---

## Files Reference

### New Files This Session
- `monitoring/firestore_health_check.py`
- `monitoring/processor_slowdown_detector.py`
- `docs/08-projects/current/pipeline-reliability-improvements/` (this project)

### Key Files for Improvements
| Area | Files |
|------|-------|
| PlayerDailyCacheProcessor | `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` |
| MERGE Error | `predictions/worker/batch_staging_writer.py` |
| Self-heal | `orchestration/cloud_functions/self_heal/main.py` |
| Circuit Breaker | `shared/processors/patterns/circuit_breaker_mixin.py` |
| DLQ Infrastructure | `infra/pubsub.tf` |
| Admin Dashboard | `services/admin_dashboard/main.py` |

---

## Quick Reference Commands

```bash
# Check current health
PYTHONPATH=. .venv/bin/python monitoring/processor_slowdown_detector.py
PYTHONPATH=. .venv/bin/python monitoring/firestore_health_check.py

# Check DLQ status
./bin/orchestration/check_dead_letter_queue.sh

# Profile PlayerDailyCacheProcessor
bq query --use_legacy_sql=false "
SELECT DATE(started_at) as run_date, AVG(duration_seconds) as avg_dur, MAX(records_processed) as records
FROM nba_reference.processor_run_history
WHERE processor_name = 'PlayerDailyCacheProcessor' AND status = 'success'
GROUP BY DATE(started_at) ORDER BY run_date DESC LIMIT 14"
```

---

*Updated: December 30, 2025*
