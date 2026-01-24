# Code Quality & Test Coverage Initiative - January 2026

**Started:** 2026-01-24
**Status:** In Progress
**Owner:** Data Engineering Team

---

## Executive Summary

Comprehensive code quality improvement initiative identified through automated codebase analysis. This project addresses security vulnerabilities, test coverage gaps, code duplication, and technical debt.

### Key Metrics

| Metric | Before | Target | Current |
|--------|--------|--------|---------|
| SQL Injection Vulnerabilities | 5+ files | 0 | **0** |
| Duplicate Utility Files | 17 x 9 copies | 17 x 1 | 17 x 9 (sync script created) |
| Test Coverage (Scrapers) | ~1 test / 147 files | 50%+ | ~2% (base tests added) |
| Test Coverage (Monitoring) | 0 tests | 80%+ | 0% |
| Files > 1000 LOC | 12 files | 6 files | 12 |
| Functions > 250 lines | 10+ functions | 0 | 10+ |

### Progress: 6/15 tasks completed (40%)

---

## Priority Matrix

### P0 - Critical (Security/Reliability)
| # | Task | Status | Impact |
|---|------|--------|--------|
| 1 | Fix SQL injection vulnerabilities | **DONE** | CRITICAL |
| 8 | Add missing timeouts to network requests | **DONE** | HIGH |
| 11 | Improve error handling for external API calls | **DONE** | HIGH |

### P1 - High (Code Quality)
| # | Task | Status | Impact |
|---|------|--------|--------|
| 2 | Consolidate 17 duplicate utility files | **DONE** (sync script) | HIGH |
| 6 | Extract hardcoded Cloud Run URLs to config | **DONE** | MEDIUM |
| 15 | Deploy pipeline-dashboard and auto-backfill-orchestrator | **DONE** (script) | HIGH |

### P2 - Medium (Test Coverage)
| # | Task | Status | Impact |
|---|------|--------|--------|
| 3 | Add tests for scrapers module (147 files) | In Progress | HIGH |
| 4 | Add tests for monitoring module | Pending | HIGH |
| 5 | Add tests for services module | Pending | MEDIUM |
| 10 | Add tests for tools module | Pending | MEDIUM |
| 13 | Add tests for ML training scripts | Pending | MEDIUM |

### P3 - Low (Refactoring/Tech Debt)
| # | Task | Status | Impact |
|---|------|--------|--------|
| 7 | Refactor 12 files over 1000 lines | Pending | MEDIUM |
| 9 | Address 47+ TODO comments | Pending | LOW |
| 12 | Convert 37 raw processors to BigQuery pool | Pending | MEDIUM |
| 14 | Refactor functions over 250 lines | Pending | MEDIUM |

---

## Quick Reference

### Progress Tracking
- [PROGRESS.md](./PROGRESS.md) - Detailed task status and notes
- [CHANGELOG.md](./CHANGELOG.md) - Log of all changes made

### Related Documents
- Previous Session: `docs/09-handoff/2026-01-24-RESILIENCE-SESSION-2-HANDOFF.md`
- Master Tracker: `docs/08-projects/current/MASTER-PROJECT-TRACKER.md`

---

## Discovery Findings

### Security Issues Found
1. **SQL Injection (5+ files)** - Using f-strings in BigQuery queries
2. **Missing Request Timeouts** - Network calls without timeout parameter
3. **Inadequate Error Handling** - Bare `except:` or missing try-catch

### Code Duplication (Critical)
- 17 utility files duplicated 9-10 times each across cloud functions
- Estimated 150+ redundant files to consolidate
- Major maintenance burden and inconsistency risk

### Test Coverage Gaps
| Module | Files | Tests | Coverage |
|--------|-------|-------|----------|
| Scrapers | 147 | ~1 | <1% |
| Monitoring | Many | 0 | 0% |
| Services | 7 | 0 | 0% |
| Tools | 12 | 0 | 0% |
| ML Scripts | 33 | 4 | ~12% |

### Large File Analysis
| File | Lines | Issue |
|------|-------|-------|
| upcoming_player_game_context_processor.py | 4039 | 19 TODOs, needs split |
| analytics_base.py | 2951 | Base class too large |
| precompute_base.py | 2628 | Base class too large |
| scraper_base.py | 2394 | Core framework file |

---

## Success Criteria

### Phase 1 Complete When: DONE
- [x] All SQL injection vulnerabilities fixed
- [x] All network requests have timeouts
- [x] Error handling improved on external API calls
- [x] New cloud functions deployment script created

### Phase 2 Complete When:
- [x] Utility files sync script created
- [x] Hardcoded URLs extracted to config
- [ ] Scrapers module has 50%+ test coverage (in progress)

### Project Complete When:
- [ ] All 15 tasks marked complete (6/15 done)
- [x] No critical security issues remaining
- [ ] Test coverage > 50% for all major modules
- [ ] No files > 2000 LOC (with exceptions documented)

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `shared/config/service_urls.py` | Centralized Cloud Run service URLs |
| `bin/deploy/deploy_new_cloud_functions.sh` | Deployment script for new cloud functions |
| `bin/maintenance/sync_shared_utils.py` | Sync script for duplicate utility files |
| `tests/scrapers/unit/test_scraper_base.py` | Unit tests for ScraperBase |
| `tests/scrapers/conftest.py` | Shared fixtures for scraper tests |

---

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
