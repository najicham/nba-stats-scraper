# TIER 1 Improvements - Progress Tracker
**Date Started:** January 21, 2026
**Status:** IN PROGRESS
**Goal:** 34 hours of reliability + cost optimization work

---

## OVERVIEW

Tier 1 builds on Tier 0's critical security fixes with reliability improvements and cost optimizations.

**Expected Outcomes:**
- **Cost Savings:** $36-45/month
- **Reliability:** Prevent worker hangs, add timeouts
- **Testing:** Critical path coverage
- **Security:** SSL + headers hardening

---

## TIER 0 RECAP (COMPLETE ✅)

**Completed:** January 21, 2026
**Time:** 8.5 hours

| Item | Status | Impact |
|------|--------|--------|
| Query Caching Enabled | ✅ | $15-20/month |
| Secrets Verified | ✅ | All in Secret Manager |
| SQL Injection Fixed | ✅ | 2 files, 6 methods |
| Bare Except Blocks Fixed | ✅ | 7 files |

**Commits:**
- `033ed5a6` - SQL injection fixes
- `a4a8b6c2` - Bare except fixes

---

## TIER 1 ITEMS

### 1.1 Add Missing Timeouts (4 hours) - IN PROGRESS ⚙️

**Status:** Analyzing codebase
**Priority:** HIGH - Prevents worker hangs
**Impact:** Reliability

**Files to Update:**
- [ ] `predictions/worker/batch_staging_writer.py` - ALREADY HAS TIMEOUTS ✅
- [ ] `predictions/worker/shared/utils/bigquery_retry.py`
- [ ] `predictions/worker/shared/utils/completeness_checker.py`
- [ ] `predictions/worker/shared/utils/odds_preference.py`
- [ ] `predictions/worker/shared/utils/odds_player_props_preference.py`
- [ ] `data_processors/` - Various processors

**Timeout Standards:**
- Read queries: 60 seconds
- Write queries (INSERT/UPDATE): 120 seconds
- MERGE operations: 300 seconds
- Long-running analytics: 600 seconds

---

### 1.2 Add Partition Filters (4 hours) - PENDING

**Expected Savings:** $22-27/month
**Priority:** HIGH

**Tasks:**
- [ ] Fix health check queries
- [ ] Fix daily health summary queries
- [ ] Add `require_partition_filter=true` to 20+ tables
- [ ] Test for query failures

---

### 1.3 Create Materialized Views (8 hours) - PENDING

**Expected Savings:** $14-18/month
**Priority:** MEDIUM

**Views to Create:**
- [ ] `odds_api_game_lines_preferred_mv`
- [ ] `current_season_players_mv`
- [ ] `data_quality_summary_mv`

**Tasks:**
- [ ] Create DDL for each view
- [ ] Update processors to use MVs
- [ ] Test and validate results
- [ ] Set up refresh schedules

---

### 1.4 Add Tests for Critical Files (12 hours) - PENDING

**Priority:** HIGH - Prevent regressions
**Coverage Target:** 70%+

**Files to Test:**
- [ ] `batch_staging_writer.py` - Race condition tests (4h)
- [ ] `distributed_lock.py` - Concurrency tests (3h)
- [ ] `data_freshness_validator.py` - Validation logic (3h)
- [ ] `prediction_accuracy_processor.py` - Accuracy calculations (2h)

---

### 1.5 Fix SSL Verification (2 hours) - PENDING

**Priority:** HIGH - Security

**Tasks:**
- [ ] Fix `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py`
- [ ] Remove `session.verify = False`
- [ ] Remove `urllib3.disable_warnings()`
- [ ] Use proper certificates or proxy certs
- [ ] Test with valid certificates

---

### 1.6 Add Security Headers (4 hours) - PENDING

**Priority:** MEDIUM - Security hardening

**Headers to Add:**
- [ ] CORS headers to all Flask apps
- [ ] CSP (Content Security Policy)
- [ ] X-Frame-Options
- [ ] X-Content-Type-Options
- [ ] Strict-Transport-Security

**Files to Update:**
- [ ] `scrapers/main_scraper_service.py`
- [ ] `data_processors/raw/main_processor_service.py`
- [ ] `data_processors/analytics/main_analytics_service.py`
- [ ] `data_processors/precompute/main_precompute_service.py`
- [ ] `predictions/coordinator/coordinator.py`
- [ ] `predictions/worker/worker.py`

---

## PROGRESS SUMMARY

**Total Tier 1 Time:** 34 hours
**Completed:** 0 hours
**In Progress:** Item 1.1 (4 hours)
**Remaining:** 30 hours

**Cost Savings Target:** $36-45/month
**Achieved:** $0/month (pending completion)

---

## NEXT STEPS

1. **NOW:** Complete 1.1 (Add Missing Timeouts)
2. **NEXT:** 1.2 (Partition Filters) for immediate cost savings
3. **THEN:** 1.3 (Materialized Views) for additional savings
4. **PARALLEL:** Start 1.4 (Tests) while deploying optimizations

---

## COMMITS LOG

Will be updated as work progresses:

```
# Tier 1 commits will be listed here
```

---

**Last Updated:** 2026-01-21 18:15 PT
**Next Update:** After completing Item 1.1
