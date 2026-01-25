# Session 19+ Priorities and Roadmap
**Created:** 2026-01-25
**Status:** Ready for execution
**Context:** Comprehensive analysis of all current projects and priorities

---

## Executive Summary

Based on comprehensive review of Sessions 16-18 and project tracker analysis:

**Pipeline Health:** ✅ EXCELLENT
- Grading coverage: 98.1% (100% last 3 days)
- Feature availability: 99% (99.8% high quality)
- System performance: Current (updated Jan 24)
- GCS exports: Fresh (< 1 hour old)
- Zero data quality issues found

**Monitoring Status:** ✅ DEPLOYED
- Daily summary Cloud Function deployed with grading coverage
- BigQuery grading coverage view created (nba_orchestration.grading_coverage_daily)
- Comprehensive health check script available
- Weekly ML automation script ready (deployment optional)

**Technical Debt:** ⚠️ SIGNIFICANT
- 30K duplicate lines in Cloud Functions (P0)
- 12 large files >2000 LOC requiring refactoring (P1)
- 79 skipped tests need investigation (P2)
- Session 18 test coverage: 6/27 tasks complete (22%)

---

## P0 - Critical & Immediate (Do First)

### 1. Complete Session 18 Test Coverage (IN PROGRESS)
**Status:** 6/27 tasks (22%), 98 tests created, all passing
**Time:** ~40 hours remaining
**Impact:** Safety net before code refactoring, prevents regressions

**Next Tasks:**
- [ ] Task #3: Test stale prediction SQL (7 test cases)
- [ ] Task #6: Test race condition prevention (5 test cases)
- [ ] Task #9-10: Cache integration & orchestrator tests

**Why P0:** Must complete before ANY code refactoring to prevent breaking changes

**Action:** Continue Session 18 work, complete Phase 2-3 tests next

---

## P1 - High Value (Do Soon)

### 2. Cloud Function Consolidation
**Status:** Planning complete, not started
**Time:** 8 hours
**Impact:** Eliminates 30K duplicate lines, reduces maintenance burden

**Scope:**
- 6 Cloud Functions with duplicate `/shared/utils/` directories
- Files: completeness_checker.py (10K lines), player_registry/reader.py (6K lines), terminal.py (7K lines), player_name_resolver.py (6K lines)

**Approach:** Create `orchestration-shared` pip package, update imports

**Why P1:** High-impact technical debt with clear solution and modest time investment

**Action:** Start after Session 18 Phase 2 complete

---

### 3. Large File Refactoring
**Status:** 2/12 files done, 10 remaining
**Time:** 24 hours
**Impact:** Improved testability, maintainability, code clarity

**Priority Files:**
- [ ] `scraper_base.py` (2,900 lines) - Extract 3 mixins
- [ ] `admin_dashboard/main.py` (2,718 lines) - Flask blueprints
- [ ] `upcoming_player_game_context_processor.py` (2,634 lines) - Extract context classes
- [ ] `player_composite_factors_processor.py` (2,611 lines) - Extract calculators

**Already Done:**
- [x] `analytics_base.py` (down to 2,870 from 3,062)
- [x] `precompute_base.py` (down to 2,519 from 2,665)

**Why P1:** Enables better testing, reduces cognitive load, improves onboarding

**Action:** Start after Cloud Function consolidation

---

## P2 - Medium Value (Plan Ahead)

### 4. Skipped Test Investigation
**Status:** Not started
**Time:** 24 hours
**Impact:** Complete test coverage, identify hidden issues

**Scope:** 79 skipped tests across codebase

**Why P2:** Important for comprehensive coverage but Session 18 focuses on critical paths first

**Action:** Add to Session 18 backlog or separate session

---

### 5. BDL Boxscore Gap Resolution (OPTIONAL)
**Status:** Investigated - LOW IMPACT
**Time:** 2-4 hours
**Impact:** Minimal - Analytics has 100% coverage via fallback sources

**Findings:**
- 11 games missing BDL data (Jan 8: 4 games, Jan 24: 7 games)
- One postponed game (expected)
- Analytics working with ESPN/NBAC fallbacks
- No functional impact

**Why P2:** Already working, gaps may auto-resolve as BDL API updates

**Action:** Monitor only, revisit if gaps persist >7 days

---

## P3 - Nice to Have (Low Priority)

### 6. Looker Studio Monitoring Dashboard
**Status:** Not started
**Time:** 4-6 hours
**Impact:** Visual monitoring for stakeholders

**Prerequisites:** BigQuery grading coverage view (✅ DEPLOYED)

**Why P3:** Monitoring already functional via daily Slack summaries, dashboard is cosmetic

**Action:** Create when bandwidth allows

---

### 7. Weekly ML Adjustments Deployment
**Status:** Script ready, deployment optional
**Time:** 2 hours (Cloud Run job setup)
**Impact:** Low - Manual updates working fine, last updated Jan 24

**Current State:**
- Bash script: `bin/cron/weekly_ml_adjustments.sh`
- Documented usage and deployment options
- ML adjustments current

**Why P3:** Manual process working, weekly cadence not urgent

**Action:** Deploy to Cloud Scheduler when convenient

---

## Recommended Execution Order

### Next 2 Weeks

**Week 1: Session 18 Continuation**
- Days 1-2: Complete Phase 2 tests (stale prediction, race conditions)
- Days 3-4: Complete Phase 3 tests (cache integration, orchestrator)
- Day 5: Review and plan Phase 4 (remaining 15 tasks)

**Week 2: Architecture Cleanup Begins**
- Days 1-2: Cloud Function consolidation (P0, 8h)
- Days 3-5: Start large file refactoring (admin_dashboard/main.py)

### Weeks 3-4

**Continue Architecture Refactoring:**
- Complete large file refactoring (remaining ~16h)
- Base class hierarchy cleanup (16h)
- distributed_lock relocation (2h)

**Testing:**
- E2E validation of refactored components (8h)
- Skipped test investigation if time allows

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Refactoring breaks production | Medium | High | Complete Session 18 tests first (safety net) |
| Cloud Function consolidation deployment issues | Low | Medium | Test thoroughly in staging, rollback plan |
| Time estimates too optimistic | Medium | Medium | Prioritize P0/P1, defer P2/P3 if needed |
| New bugs discovered during testing | Medium | Medium | Expected and desired - better to find now |

---

## Success Metrics

**By End of Week 2:**
- [ ] Session 18 Phase 2-3 complete (15+ additional tests)
- [ ] Cloud Function duplication eliminated (30K → 0 lines)
- [ ] Test coverage >150 total tests

**By End of Week 4:**
- [ ] 4+ large files refactored (<2000 LOC each)
- [ ] Base class hierarchy simplified (<20% overlap)
- [ ] All critical code paths covered by tests

---

## Projects NOT in Scope (Deferred)

These were identified but are lower priority:

1. **Resilience pattern gaps** - Already addressed in Session 13-15
2. **Config drift detection** - Script created in Session 15
3. **Proxy infrastructure improvements** - Working adequately
4. **Performance optimization** - No performance issues identified
5. **ML model improvements** - Pipeline focus first, model improvements later

---

## Quick Reference: Current Status

**✅ Production-Ready:**
- Grading pipeline: 98.1% coverage
- Monitoring: Daily Slack summaries with grading coverage
- Health checks: Comprehensive script available
- Analytics: 100% coverage via multi-source strategy

**🔧 In Progress:**
- Session 18 test coverage: 22% complete
- Architecture refactoring: Planning phase

**📋 Ready to Start:**
- Cloud Function consolidation: Scoped, estimated, ready
- Large file refactoring: 2/12 done, clear targets identified

**💡 Nice to Have:**
- Looker dashboard: Low priority, cosmetic
- ML automation deployment: Working manually, not urgent

---

## Contact & Questions

**For Session 18 work:**
- See: `docs/08-projects/current/MASTER-PROJECT-TRACKER.md` Session 18 section
- Next steps clearly defined

**For architecture refactoring:**
- See: `docs/08-projects/current/architecture-refactoring-2026-01/README.md`
- Complete plan with 4-week schedule

**For monitoring deployment:**
- Daily summary: ✅ Deployed (includes grading coverage)
- Health check: `python bin/validation/comprehensive_health.py --days 3`
- BigQuery view: `SELECT * FROM nba_orchestration.grading_coverage_daily ORDER BY game_date DESC LIMIT 10`

---

**Next Session Recommendation:** Continue Session 18 Phase 2 tests (stale prediction SQL, race condition prevention)

**Status:** Ready for execution
**Last Updated:** 2026-01-25
