# Pipeline Resilience Improvements - Project Plan

## Executive Summary

This project addresses critical pipeline reliability issues discovered in Session 9:
- 6.6% Phase 3 success rate (target: 95%+)
- 26.8% Phase 4 success rate (target: 95%+)
- 5 services with deployment drift
- 2/7 games missing PBP data
- 4-24 hour issue detection delay

**Last Updated:** Session 10 (2026-01-28)

## Timeline

### Week 1: Critical Fixes (Complete)
| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| Fix `track_source_coverage_event` | ✅ Done | Claude | Commit c7c1e999 |
| Push to origin | ✅ Done | Claude | |
| Create auto-deploy workflow | ✅ Done | Claude | `.github/workflows/auto-deploy.yml` |
| Create deploy-all-stale script | ✅ Done | Claude | `bin/deploy-all-stale.sh` |
| Deploy stale services | ⏳ Pending | User | Requires GCP_SA_KEY secret |
| Create project documentation | ✅ Done | Claude | This directory |

### Week 2: Validation Improvements (Session 10)
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Create `validate-all.sh` unified command | ⏳ Pending | High | |
| Add phase boundary data quality checks | ✅ Done | High | Phase boundary validation |
| Add minutes coverage alerting | ✅ Done | Medium | Minutes coverage alerting |
| Add deployment health gate | ⏳ Pending | Medium | |
| Pre-extraction data check | ✅ Done | High | Validates data before extraction |
| Empty game detection | ✅ Done | High | Detects missing game data |
| Phase success monitor created | ✅ Done | High | Monitors phase success rates |

### Week 3: Auto-Recovery (Session 10)
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Add BDB scraper retry logic | ✅ Done | High | 95%+ PBP coverage |
| Add NBA.com PBP fallback | ✅ Done | Medium | 99%+ coverage |
| Implement exponential backoff | ⏳ Pending | Medium | Better rate limit handling |
| Add betting data timeout | ⏳ Pending | Low | Graceful degradation |

### Remaining Work (Post-Session 10)
| Task | Status | Priority | Notes |
|------|--------|----------|-------|
| Pub/Sub backlog purge | ⏳ Pending | High | Clear stale messages from queues |
| Retry queue SQL fix | ⏳ Pending | High | Fix SQL syntax issues in retry logic |
| Soft dependencies enablement | ⏳ Pending | Medium | Enable soft dependency handling |
| BigQuery migration for data_source column | ⏳ Pending | Medium | Add data_source tracking column |
| Circuit breaker batching | ⏳ Pending | Medium | Batch circuit breaker operations |

## Architecture Changes

### Current State
```
Scraper fails → Silent failure → Cascade through phases → Detected 12h later
```

### Target State
```
Scraper fails → Inline validation → Immediate alert → Auto-retry → Fallback if needed
```

### Key Components to Add

1. **Inline Validation** (at each phase boundary)
   - Check record counts
   - Validate NULL rates
   - Verify field completeness
   - Alert if thresholds breached

2. **Auto-Retry with Backoff**
   - 3 retry attempts
   - Exponential delays: 10s, 20s, 40s
   - Circuit breaker after max retries

3. **Fallback Sources**
   - NBA.com PBP when BDB unavailable
   - Basketball Reference for boxscores
   - NBA API as second backup

4. **Unified Monitoring**
   - Single `validate-all.sh` command
   - Real-time alerts (not just morning check)
   - Deployment health integration

## Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Issue detection time | 4-24h | <15min | Time from failure to alert |
| Auto-recovery rate | 0% | 80% | Issues fixed without manual intervention |
| PBP coverage | 71% | 98%+ | Games with PBP data / total games |
| Deployment drift | Common | Rare | Stale services detected by drift check |
| Phase 3 success | 6.6% | 95%+ | Successful runs / total runs |
| Phase 4 success | 26.8% | 95%+ | Successful runs / total runs |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Auto-deploy breaks prod | Medium | High | Add health check gate, rollback on 5xx |
| Retry storms | Low | Medium | Exponential backoff, circuit breaker |
| Fallback data quality | Low | Medium | Mark source, validate critical fields |
| Monitoring fatigue | Medium | Low | Deduplicate alerts, severity tiers |

## Dependencies

1. **GCP_SA_KEY secret** - Required for auto-deploy workflow
2. **Slack webhook** - For alerting (optional but recommended)
3. **Cloud Run permissions** - Service account needs deployer role

## Files Created/Modified

### Created This Session
- `shared/processors/patterns/quality_mixin.py` - Added `track_source_coverage_event`
- `.github/workflows/auto-deploy.yml` - Auto-deploy on push to main
- `bin/deploy-all-stale.sh` - Manual deploy script
- `docs/08-projects/current/pipeline-resilience-improvements/` - This project

### Created Session 10
- BDB scraper retry logic
- NBA.com PBP fallback implementation
- Phase boundary validation
- Minutes coverage alerting
- Pre-extraction data check
- Empty game detection
- Phase success monitor

### To Create Next Session
- `bin/validate-all.sh` - Unified validation (consolidate existing monitors)
- Pub/Sub backlog purge mechanism
- Retry queue SQL fix
- Soft dependencies enablement
- BigQuery schema migration for data_source column
- Circuit breaker batching implementation
