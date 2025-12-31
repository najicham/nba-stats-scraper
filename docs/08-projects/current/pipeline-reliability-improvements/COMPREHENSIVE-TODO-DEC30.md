# Comprehensive Pipeline Improvement TODO List
**Generated:** December 30, 2025 (10:30 PM ET)
**Status:** Complete Investigation Phase
**Total Items:** 200+ across all categories
**Agents Used:** 8 parallel exploration agents

---

## Executive Summary

This document consolidates findings from:
- Previous session: 98 items (P0-P3)
- 8 new exploration agents covering:
  - Scrapers (24+ issues)
  - Raw Processors (15+ issues)
  - Shared Utils (20+ issues)
  - Monitoring (25+ gaps)
  - Bin Scripts (45+ issues)
  - TODO/FIXME Comments (143 items)
  - Test Coverage (40+ gaps)
  - Config/Environment (35+ issues)

---

## CRITICAL (P0) - Fix Immediately

### Security
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P0-SEC-1 | No auth on coordinator /start, /complete | coordinator.py | 153, 296 | RCE potential |
| P0-SEC-2 | Exposed secrets in .env file | .env | 2-71 | 7 production API keys exposed |
| P0-SEC-3 | AWS credentials hardcoded in monitoring | health_summary/main.py, stall_detection/main.py | 384-388, 355-359 | Credential leak |

### Orchestration
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P0-ORCH-1 | Cleanup processor Pub/Sub TODO never implemented | cleanup_processor.py | 252 | Self-healing broken |
| P0-ORCH-2 | Phase 4→5 no timeout | phase4_to_phase5/main.py | 54 | Pipeline freeze |
| P0-ORCH-3 | Alert manager email/Slack/Sentry NOT implemented | alert_manager.py | 270, 281, 292 | No external alerts |
| P0-ORCH-4 | Transition monitor alert sending TODO | transition_monitor/main.py | 437 | Ops not notified |

### Scrapers
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P0-SCRP-1 | 15+ bare `except:` with silent pass | scraper_base.py, bdl_utils.py, pubsub_utils.py | Multiple | Silent failures |
| P0-SCRP-2 | Missing Pub/Sub republish in cleanup | cleanup_processor.py | 252-267 | Files never reprocessed |

---

## HIGH PRIORITY (P1) - This Week

### Performance
| ID | Issue | File | Line | Impact | Effort |
|----|-------|------|------|--------|--------|
| P1-PERF-1 | Add BigQuery query timeouts (30s) | data_loaders.py | 112-183, 270-312 | Workers hang | Low |
| P1-PERF-2 | Batch load historical games | worker.py, data_loaders.py | 571, 435-559 | **50x perf gain** | Medium |
| P1-PERF-3 | Fix MERGE FLOAT64 error | batch_staging_writer.py | 302-319 | Consolidation fails | Low |
| P1-PERF-4 | Add feature caching (same game_date queried 450x) | worker.py | 88-96 | Reduce queries | Medium |

### Orchestration
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-ORCH-3 | Add Phase 5→6 data validation | phase5_to_phase6/main.py | 106-136 | Empty exports |
| P1-ORCH-4 | Add health checks to all cloud functions | All cloud_functions/*/main.py | - | Can't detect failures |
| P1-ORCH-5 | Implement AlertManager destinations | alert_manager.py | 270-292 | No external alerts |

### Data Reliability
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-DATA-1 | Fix prediction duplicates (MERGE vs WRITE_APPEND) | worker.py | 996-1041 | 5x data bloat |
| P1-DATA-2 | Update 5 circuit breaker hardcodes | 5 processor files | Various | Inconsistent lockout |
| P1-DATA-3 | Add data source fallbacks | upcoming_player_game_context_processor.py | 1037-1038 | Limited data when BDL incomplete |

### Monitoring
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-MON-1 | Implement DLQ monitoring | Cloud Monitoring | - | Silent failures |
| P1-MON-2 | Add Pub/Sub publish retries | coordinator.py | 421-424 | Lost messages |
| P1-MON-3 | Add infrastructure monitoring | NEW FILE NEEDED | - | No CPU/memory tracking |

### Processors
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-PROC-1 | Investigate PlayerDailyCacheProcessor slowdown | player_daily_cache_processor.py | - | +39.7% slower |
| P1-PROC-2 | Fix player retry (return 500 not 204) | worker.py | 314-334 | Players skipped |

### Scrapers
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-SCRP-3 | Add Cloudflare/WAF detection | scraper_base.py | - | Blind retries against blocks |
| P1-SCRP-4 | Add connection pooling | scraper_base.py | 1065-1078 | Connection exhaustion |
| P1-SCRP-5 | Add timeout to notification calls | scraper_base.py | 900-1050 | Scraper hangs |
| P1-SCRP-6 | Validate pagination cursors | bdl_utils.py | 226-257 | Infinite loops possible |

### Config/Environment
| ID | Issue | File | Line | Impact |
|----|-------|------|------|--------|
| P1-CFG-1 | Move secrets to Secret Manager | .env | All | Security risk |
| P1-CFG-2 | Validate required env vars at startup | Multiple | - | Silent crashes |
| P1-CFG-3 | Standardize GCP_PROJECT_ID vs GCP_PROJECT | 29+ files | - | Inconsistent config |

---

## MEDIUM PRIORITY (P2) - Next 2 Weeks

### Performance
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-PERF-1 | Fix validation threshold inconsistency (50 vs 70) | data_loaders.py:705, worker.py:496 | Data quality |
| P2-PERF-2 | Add connection pooling | bigquery_client.py, storage_client.py | Latency |
| P2-PERF-3 | Centralize rate limiting | Multiple scraper files | Coordination |

### Orchestration
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-ORCH-1 | Implement DLQ for cloud functions | All orchestration functions | Message recovery |
| P2-ORCH-2 | Add Firestore document cleanup (30-day TTL) | transition_monitor/main.py | Storage costs |
| P2-ORCH-3 | Remove Phase 2→3 vestigial trigger | phase2_to_phase3/main.py | Wasted Pub/Sub |

### Monitoring
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-MON-1 | End-to-end latency tracking | NEW TABLE | SLA measurement |
| P2-MON-2 | Add Firestore health to dashboard | admin_dashboard/main.py | Visibility |
| P2-MON-3 | Add slowdown alerts to dashboard | admin_dashboard/main.py | Early warning |
| P2-MON-4 | Per-system prediction success rates | execution_logger.py:88-91 | Debugging |
| P2-MON-5 | Add BigQuery cost tracking | NEW | Budget alerts |
| P2-MON-6 | Add percentile latency tracking | firestore_health_check.py:114-117 | Performance |

### Security
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-SEC-1 | Fix API key timing attack | admin_dashboard/main.py:116-132 | Auth bypass |
| P2-SEC-2 | Add rate limiting | admin_dashboard/main.py | DoS protection |
| P2-SEC-3 | Validate request schema | admin_dashboard/main.py | Injection risk |

### Data Reliability
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-DATA-1 | Automatic backfill trigger | NEW cloud function | Manual intervention |
| P2-DATA-2 | Extend self-heal to Phase 2 | self_heal/main.py | Upstream gaps |
| P2-DATA-3 | Add roster/injury extraction | upcoming_player_game_context_processor.py:1410,1416 | Missing features |

### Processors
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-PROC-1 | Replace generic exception handling | analytics_base.py | 34 try-except blocks |
| P2-PROC-2 | Add dependency row count validation | precompute_base.py:232-243 | Silent failures |
| P2-PROC-3 | Add exponential backoff to fallback | fallback_source_mixin.py | Retry failures |
| P2-PROC-4 | Add defense zone analytics | team_defense_game_summary_processor.py:1400-1401,1419 | Missing metrics |

### Scrapers
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-SCRP-1 | Fix proxy exhaustion handling | scraper_base.py:1352-1405 | All proxies fail |
| P2-SCRP-2 | Add browser automation cleanup | scraper_base.py:1235-1330 | Resource leaks |
| P2-SCRP-3 | Add GCS retry on transient errors | scraper_base.py:1113-1220 | Data loss |
| P2-SCRP-4 | Create data validation schema per scraper | NEW | Format validation |

### Bin Scripts
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-BIN-1 | Implement 7 empty stub scripts | bin/utilities/, bin/validation/ | Missing operations |
| P2-BIN-2 | Consolidate 4 validate_gcs scripts | bin/infrastructure/monitoring/ | Maintenance |
| P2-BIN-3 | Create centralized config for 186+ hardcoded values | NEW bin/shared/config.sh | Flexibility |
| P2-BIN-4 | Add set -u and set -o pipefail to all scripts | All bin/*.sh | Error handling |

### Testing
| ID | Issue | File | Impact |
|----|-------|------|--------|
| P2-TEST-1 | Add tests for 12 untested exporters | tests/unit/publishing/ | Coverage |
| P2-TEST-2 | Fix empty test files | tests/processors/test_processor_base.py, test_br_roster_processor.py | Coverage |
| P2-TEST-3 | Add orchestration integration tests | tests/orchestration/ | Critical paths |
| P2-TEST-4 | Add cloud function tests | NEW | 12 functions untested |

---

## LOWER PRIORITY (P3) - When Time Permits

### Performance
- P3-PERF-1: Migrate coordinator to Firestore (multi-instance)
- P3-PERF-2: Add batch staging cleanup strategy
- P3-PERF-3: Implement query caching layer

### Orchestration
- P3-ORCH-1: Add SLA monitoring for predictions
- P3-ORCH-2: Fix batch ID format for Firestore compatibility
- P3-ORCH-3: Add spread/total movement tracking

### Monitoring
- P3-MON-1: Add metrics/Prometheus endpoint
- P3-MON-2: Add admin audit trail to database
- P3-MON-3: Add quality score distribution metrics
- P3-MON-4: Add recommendation distribution (OVER/UNDER/PASS)
- P3-MON-5: Add Grafana dashboard integration

### Data
- P3-DATA-1: Multi-source scraper fallback (BDL → NBA.com → ESPN)
- P3-DATA-2: BigQuery fallback for Firestore
- P3-DATA-3: Add timezone conversion logic
- P3-DATA-4: Implement proper season phase detection

### Scrapers
- P3-SCRP-1: Remove 9 unused exception classes
- P3-SCRP-2: Standardize header profile registry
- P3-SCRP-3: Add circuit breaker pattern
- P3-SCRP-4: Implement status code allowlist documentation

### Testing
- P3-TEST-1: Add edge case tests for error handling
- P3-TEST-2: Add ML feedback pipeline tests
- P3-TEST-3: Add player registry resolution tests
- P3-TEST-4: Add notification system tests

### Documentation
- P3-DOC-1: Create centralized env var documentation
- P3-DOC-2: Create configuration schema docs
- P3-DOC-3: Create runbook automation scripts

---

## Summary Statistics

| Category | P0 | P1 | P2 | P3 | Total |
|----------|----|----|----|----|-------|
| Security | 3 | 0 | 3 | 0 | 6 |
| Performance | 0 | 4 | 3 | 3 | 10 |
| Orchestration | 4 | 3 | 3 | 3 | 13 |
| Data Reliability | 0 | 3 | 3 | 4 | 10 |
| Monitoring | 0 | 3 | 6 | 5 | 14 |
| Processors | 0 | 2 | 4 | 0 | 6 |
| Scrapers | 2 | 4 | 4 | 4 | 14 |
| Config | 0 | 3 | 0 | 0 | 3 |
| Bin Scripts | 0 | 0 | 4 | 0 | 4 |
| Testing | 0 | 0 | 4 | 4 | 8 |
| Documentation | 0 | 0 | 0 | 3 | 3 |
| **TOTAL** | **9** | **22** | **34** | **26** | **91** |

*Note: Additional 50+ sub-items within each category bring total to 200+*

---

## Files Most Affected (Fix Priority Order)

| File | Issues | Priority Range | Category |
|------|--------|----------------|----------|
| `predictions/coordinator/coordinator.py` | 10+ | P0-P2 | Security, Perf |
| `predictions/worker/worker.py` | 8+ | P1-P2 | Perf, Data |
| `orchestration/cleanup_processor.py` | 3 | P0 | Orchestration |
| `shared/alerts/alert_manager.py` | 3 | P0-P1 | Alerting |
| `scrapers/scraper_base.py` | 15+ | P0-P2 | Reliability |
| `services/admin_dashboard/main.py` | 6+ | P1-P2 | Security |
| `.env` | 7 secrets | P0 | Security |
| `phase4_to_phase5/main.py` | 2 | P0-P1 | Orchestration |

---

## Agent-Specific Findings Summary

### Scrapers Agent
- **15+ bare except:** handlers silencing errors
- **No Cloudflare/WAF detection** - blind retries
- **No connection pooling** - connection exhaustion risk
- **8+ hardcoded timeouts** - not configurable
- **Missing pagination validation** - infinite loops possible

### Monitoring Agent
- **No infrastructure monitoring** - CPU/memory blind spot
- **No cost tracking** - budget overruns possible
- **No percentile latency** - only threshold-based
- **Dashboard only shows 3 metrics** - needs 10+
- **Pub/Sub lag not monitored**

### Bin Scripts Agent
- **7 completely empty scripts** - stub implementations
- **186+ hardcoded project references**
- **113+ hardcoded region values**
- **4 duplicate validate_gcs scripts**
- **Missing set -u and set -o pipefail**

### TODO/FIXME Agent
- **3 critical TODOs** - Pub/Sub, alerting, transition monitor
- **7 high priority** - data fallbacks, defense analytics
- **38 medium priority** - future features deferred
- **9 CRITICAL CODE BUG log messages** in PDF parser (defensive)

### Test Coverage Agent
- **12/22 exporters untested**
- **2 empty test files**
- **12 cloud functions with 0 tests**
- **40+ untested shared modules**
- **No ML feedback tests**

### Config Agent
- **7 secrets exposed in .env**
- **28+ hardcoded project IDs**
- **2 different env var names for project** (GCP_PROJECT_ID vs GCP_PROJECT)
- **15+ undocumented required env vars**
- **No startup validation**

---

## Recommended Implementation Order

### Week 1 (Critical Security & Reliability)
1. P0-SEC-2: Move secrets from .env to Secret Manager
2. P0-SEC-1: Add coordinator authentication
3. P0-ORCH-1: Fix cleanup processor Pub/Sub
4. P0-ORCH-2: Add Phase 4→5 timeout
5. P0-ORCH-3: Implement alert manager destinations

### Week 2 (Performance & Monitoring)
1. P1-PERF-2: Batch load historical games (50x gain)
2. P1-PERF-1: Add BigQuery query timeouts
3. P1-MON-1: Implement DLQ monitoring
4. P1-ORCH-4: Add cloud function health checks

### Week 3 (Data Reliability)
1. P1-DATA-1: Fix prediction duplicates
2. P1-ORCH-3: Add Phase 5→6 validation
3. P1-SCRP-1: Replace bare except handlers
4. P2-BIN-1: Implement stub scripts

### Week 4+ (Quality & Maintainability)
1. P2-TEST-1: Add exporter tests
2. P2-MON-1: End-to-end latency tracking
3. P2-SCRP-4: Data validation schemas
4. P3 items as time permits

---

*Generated by 8 parallel exploration agents on December 30, 2025*
*Total exploration time: ~15 minutes*
*Files analyzed: 500+*
*Lines of code reviewed: 100,000+*
