# Future Improvement Opportunities

**Created:** 2026-01-24 (Session 15)
**Purpose:** Comprehensive list of improvements for future Claude Code sessions
**Status:** Reference Document

---

## Quick Reference: Session Starter Ideas

| If you have... | Work on... | Priority |
|----------------|------------|----------|
| 30 minutes | Fix 2-3 skipped tests | P2 |
| 1-2 hours | Migrate remaining processors to BQ pool | P1 |
| 2-4 hours | Add Sentry to processors/predictions | P1 |
| 4-8 hours | Cloud function consolidation | P0 |
| Full day | Start base class refactoring | P1 |

---

## Category 1: Security & Credentials

### 1.1 Secret Management Improvements
**Priority:** P1 | **Effort:** 4h

- [ ] Audit all environment variables for hardcoded secrets
- [ ] Move remaining secrets to GCP Secret Manager
- [ ] Add pre-commit hook to detect secrets in code
- [ ] Document secret rotation procedures

**Files to check:**
```
grep -r "api.key\|password\|secret\|token" --include="*.py" --include="*.sh" | grep -v test
```

### 1.2 Git History Cleanup (Optional)
**Priority:** P3 | **Effort:** 2h

The exposed API key `0B5gc7vv9oNZYjST9lhe4rY2jEG2kYdz` is still in git history.

```bash
# If needed, use git-filter-repo to remove from history
# WARNING: This rewrites history - coordinate with team
git filter-repo --path regenerate_xgboost_v1.sh --invert-paths
```

---

## Category 2: Code Quality & Architecture

### 2.1 Cloud Function Consolidation (P0)
**Priority:** P0 | **Effort:** 8h | **Impact:** Eliminate 30K duplicate lines

**Problem:** 6 cloud functions each have identical `/shared/utils/` directories.

**Solution:** Create `orchestration/shared/` package.

**Affected functions:**
- `phase2_to_phase3/shared/` (41,199 lines)
- `phase3_to_phase4/shared/` (39,688 lines)
- `phase4_to_phase5/shared/` (38,469 lines)
- `phase5_to_phase6/shared/` (39,650 lines)
- `daily_health_summary/shared/` (39,650 lines)
- `self_heal/shared/` (39,155 lines)

**Implementation:**
1. Create `orchestration/shared/utils/` with canonical files
2. Update imports in each cloud function
3. Test each phase transition
4. Delete old duplicate directories

### 2.2 Finish BigQuery Pool Migration (P1)
**Priority:** P1 | **Effort:** 2h | **Impact:** 90% init overhead reduction

**Session 15 migrated 7 processors. ~25 remain:**

```
data_processors/raw/balldontlie/bdl_active_players_processor.py
data_processors/raw/balldontlie/bdl_standings_processor.py
data_processors/raw/balldontlie/bdl_live_boxscores_processor.py
data_processors/raw/bettingpros/bettingpros_player_props_processor.py
data_processors/raw/bigdataball/bigdataball_pbp_processor.py
data_processors/raw/basketball_ref/br_roster_processor.py
data_processors/raw/espn/espn_boxscore_processor.py
data_processors/raw/espn/espn_team_roster_processor.py
data_processors/raw/nbacom/nbac_player_boxscore_processor.py
data_processors/raw/nbacom/nbac_player_movement_processor.py
data_processors/raw/nbacom/nbac_injury_report_processor.py
data_processors/raw/nbacom/nbac_gamebook_processor.py
data_processors/raw/oddsapi/odds_game_lines_processor.py
data_processors/raw/oddsapi/odds_api_props_processor.py
data_processors/raw/mlb/*.py (10 files)
data_processors/analytics/upcoming_team_game_context_processor.py
data_processors/reference/base/registry_processor_base.py
```

**Pattern:**
```python
# Change:
from google.cloud import bigquery
self.bq_client = bigquery.Client(project=self.project_id)

# To:
from shared.clients.bigquery_pool import get_bigquery_client
self.bq_client = get_bigquery_client(self.project_id)
```

### 2.3 Large File Refactoring (P1)
**Priority:** P1 | **Effort:** 24h | **Impact:** Maintainability

**Files >2000 lines:**

| File | Lines | Strategy |
|------|-------|----------|
| `analytics_base.py` | 3,062 | Extract mixins, unify with precompute_base |
| `scraper_base.py` | 2,900 | Extract 3 mixins |
| `admin_dashboard/main.py` | 2,718 | Split into Flask blueprints |
| `precompute_base.py` | 2,665 | Unify with analytics_base |
| `upcoming_player_game_context_processor.py` | 2,634 | Extract context classes |
| `player_composite_factors_processor.py` | 2,611 | Extract calculators |

### 2.4 Base Class Hierarchy Cleanup (P2)
**Priority:** P2 | **Effort:** 16h

**Current:** 4 base classes with 60% overlap
- `ProcessorBase` (1,519 lines)
- `AnalyticsProcessorBase` (3,062 lines)
- `PrecomputeProcessorBase` (2,665 lines)
- `RegistryProcessorBase` (~1,200 lines)

**Target:**
```
BaseProcessor (shared/processors/base.py) - 500 lines
├── RawProcessorBase
├── TransformProcessorBase (analytics + precompute)
└── ReferenceProcessorBase
```

### 2.5 Code Duplication Fixes (P2)
**Priority:** P2 | **Effort:** 4h

**`_categorize_failure()` duplicated in 3 places (300 lines):**
- `data_processors/analytics/analytics_base.py`
- `data_processors/precompute/precompute_base.py`
- Already extracted to `shared/processors/base/failure_categorization.py`
- Need to update imports in the base classes

**Mixin duplication across cloud functions (2,800 lines):**
- CircuitBreakerMixin duplicated in 6+ places
- Move to shared package

---

## Category 3: Performance Improvements

### 3.1 Batch Inserts Instead of Row-by-Row (P1)
**Priority:** P1 | **Effort:** 4h | **Impact:** 10-20x faster writes

**Problem:** Some processors insert rows individually.

**Solution:** Batch inserts using `load_table_from_json()` or streaming inserts with batching.

**Files to audit:**
```bash
grep -r "insert_rows\|streaming_insert" data_processors/ --include="*.py"
```

### 3.2 MERGE Query Batching (P1)
**Priority:** P1 | **Effort:** 2h | **Impact:** Prevent quota exhaustion

**Problem:** Large MERGE operations can hit BigQuery quotas.

**Solution:** Batch records before MERGE, add quota handling.

### 3.3 Query Result Caching Expansion (P2)
**Priority:** P2 | **Effort:** 2h

**Already implemented:** `shared/utils/query_cache.py`

**Expand to:**
- More processor queries
- Feature store lookups
- Reference data queries

### 3.4 CircuitBreakerMixin Thread Safety (P2)
**Priority:** P2 | **Effort:** 4h

**Problem:** Potential race conditions in circuit breaker state.

**Location:** `shared/utils/circuit_breaker.py` (if exists) or inline in base classes

**Fix:** Add proper locking around state transitions.

---

## Category 4: Error Handling & Observability

### 4.1 Add Sentry to Processors/Predictions (P1)
**Priority:** P1 | **Effort:** 2h | **Impact:** Error visibility

**Problem:** Missing Sentry integration in:
- `data_processors/` modules
- `predictions/` modules

**Pattern:**
```python
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN'),
    integrations=[LoggingIntegration(level=logging.INFO)],
    traces_sample_rate=0.1,
)
```

### 4.2 Improve Error Categorization (P2)
**Priority:** P2 | **Effort:** 2h

**Problem:** Some errors aren't properly categorized for alerting.

**Files:**
- `shared/processors/base/failure_categorization.py`
- Base class error handlers

### 4.3 Add Structured Logging (P3)
**Priority:** P3 | **Effort:** 4h

**Current:** Plain text logging
**Target:** JSON structured logs for Cloud Logging queries

---

## Category 5: Testing

### 5.1 Fix Skipped Tests - Quick Wins (P1)
**Priority:** P1 | **Effort:** 4h | **Impact:** 40 tests fixed

**Tier 1 (Easiest):**
- Fix 6 Write Batch API tests in `tests/processors/precompute/ml_feature_store/test_unit.py:682-766`
- Fix BoxScore fixture test in `tests/contract/test_boxscore_end_to_end.py:14`
- Create `MockBigQueryResult` helper

**Tier 2 (Medium):**
- Fix 7 `upcoming_player_game_context` tests (mock DataFrame schema)
- Update BigQuery mock for `.result()` iterator pattern

### 5.2 E2E Test Expansion (P2)
**Priority:** P2 | **Effort:** 8h

**Current:** Only 2 E2E test files
**Target:** 8+ E2E test files

**Missing scenarios:**
- Scraper → Processor → Prediction flow
- Phase 2 → 3 → 4 → 5 transitions
- Error recovery flows
- Circuit breaker behavior

### 5.3 Service Layer Tests (P2)
**Priority:** P2 | **Effort:** 6h

**Admin Dashboard:** 2,718 lines with minimal tests
**Grading Alerts:** 0 tests

### 5.4 Integration Test Database (P3)
**Priority:** P3 | **Effort:** 8h

Set up isolated BigQuery test dataset for integration tests.

---

## Category 6: Infrastructure & DevOps

### 6.1 Dockerfile Optimization (P2)
**Priority:** P2 | **Effort:** 2h

- Multi-stage builds for smaller images
- Layer caching optimization
- Shared base images

### 6.2 CI/CD Improvements (P2)
**Priority:** P2 | **Effort:** 4h

- [ ] Run tests on every PR
- [ ] Coverage threshold enforcement
- [ ] Automated deployment on merge to main
- [ ] Pre-commit hooks for linting

### 6.3 Monitoring Dashboard Improvements (P3)
**Priority:** P3 | **Effort:** 4h

- Grafana/Cloud Monitoring dashboards
- Cost tracking per service
- Latency percentiles

---

## Category 7: Documentation

### 7.1 API Documentation (P3)
**Priority:** P3 | **Effort:** 4h

Generate OpenAPI/Swagger docs for:
- Admin Dashboard endpoints
- Prediction Coordinator endpoints
- Health endpoints

### 7.2 Architecture Diagrams (P3)
**Priority:** P3 | **Effort:** 2h

Create/update:
- Data flow diagrams
- Service dependency diagrams
- Phase transition diagrams

### 7.3 Runbook Updates (P3)
**Priority:** P3 | **Effort:** 2h

Document common operations:
- Secret rotation
- Manual backfill procedures
- Incident response

---

## Category 8: Feature Improvements

### 8.1 Proxy Infrastructure (P1)
**Priority:** P1 | **Effort:** 8h

**Problem:** BettingPros blocking both ProxyFuel and Decodo.

**Options:**
- Bright Data integration (residential)
- Direct API access negotiation
- Alternative data sources

### 8.2 Model Improvements (P2)
**Priority:** P2 | **Effort:** Variable

- Feature engineering for edge cases
- Early season handling
- Back-to-back game adjustments

### 8.3 Real-time Updates (P3)
**Priority:** P3 | **Effort:** 16h

- WebSocket support for live updates
- Real-time injury impact adjustments

---

## Prioritized Backlog Summary

### This Week (P0-P1, High Impact)
1. Cloud function consolidation (8h) - Eliminates 30K duplicate lines
2. Finish BigQuery pool migration (2h) - 90% init reduction
3. Add Sentry to processors (2h) - Error visibility
4. Fix 40 skipped tests (4h) - Test confidence

### This Month (P1-P2)
5. Batch inserts optimization (4h)
6. Large file refactoring (24h)
7. E2E test expansion (8h)
8. Base class hierarchy cleanup (16h)

### Backlog (P2-P3)
9. CircuitBreaker thread safety (4h)
10. Service layer tests (6h)
11. CI/CD improvements (4h)
12. Documentation updates (8h)

---

## Session Checklist

Before starting a session, check:

```bash
# 1. Current test status
python -m pytest tests/unit/shared/ tests/unit/utils/ -q --tb=line

# 2. Git status
git status
git log --oneline -5

# 3. Any failing processors (check Cloud Logging)
gcloud logging read "severity>=ERROR" --limit=10 --format="table(timestamp,textPayload)"
```

---

**Document Created:** 2026-01-24
**Last Updated:** 2026-01-24
**Author:** Claude Code (Session 15)
