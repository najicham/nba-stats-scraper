# Pipeline Resilience Improvements - Project Plan

## Executive Summary

This project addresses critical pipeline reliability issues discovered in Session 9:
- 6.6% Phase 3 success rate (target: 95%+)
- 26.8% Phase 4 success rate (target: 95%+)
- 5 services with deployment drift
- 2/7 games missing PBP data
- 4-24 hour issue detection delay

## Timeline

### Week 1: Critical Fixes (Current)
| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| Fix `track_source_coverage_event` | ✅ Done | Claude | Commit c7c1e999 |
| Push to origin | ✅ Done | Claude | |
| Create auto-deploy workflow | ✅ Done | Claude | `.github/workflows/auto-deploy.yml` |
| Create deploy-all-stale script | ✅ Done | Claude | `bin/deploy-all-stale.sh` |
| Deploy stale services | ⏳ Pending | User | Requires GCP_SA_KEY secret |
| Create project documentation | ✅ Done | Claude | This directory |

### Week 2: Validation Improvements
| Task | Priority | Effort | Impact |
|------|----------|--------|--------|
| Create `validate-all.sh` unified command | High | 2h | Easier daily checks |
| Add phase boundary data quality checks | High | 3h | Prevent cascades |
| Add minutes coverage alerting | Medium | 1h | Earlier detection |
| Add deployment health gate | Medium | 2h | Prevent bad deploys |

### Week 3: Auto-Recovery
| Task | Priority | Effort | Impact |
|------|----------|--------|--------|
| Add BDB scraper retry logic | High | 2h | 95%+ PBP coverage |
| Add NBA.com PBP fallback | Medium | 3h | 99%+ coverage |
| Implement exponential backoff | Medium | 2h | Better rate limit handling |
| Add betting data timeout | Low | 1h | Graceful degradation |

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

### To Create Next Session
- `bin/validate-all.sh` - Unified validation
- `data_processors/phase3/validators/` - Data quality checks
- Updates to BDB scraper for retry logic
