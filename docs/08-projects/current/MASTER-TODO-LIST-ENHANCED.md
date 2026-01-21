# Master TODO List - Enhanced System Hardening & Optimization
**Created:** January 21, 2026 (Enhanced)
**Source:** 10 Agent Deep-Dive Investigations + Tier 0-3 Audit
**Total Items:** ~250 hours of work identified
**Completed:** 9.5 hours (4%)
**Remaining:** ~240 hours (96%)
**Strategy:** Fix CRITICAL issues first, then optimize for cost & performance

---

## EXECUTIVE SUMMARY

**Total Opportunity Identified:**
- **Cost Savings:** $21,143/year ($80-120/month current + $18,500/year new)
- **Time Savings:** 100+ hours/year in debugging + 17-29 min/day faster processing
- **Reliability:** Prevents 14+ CRITICAL failure modes
- **Test Coverage:** 10% → 70%+ target

**Quick Wins (< 10 hours, high impact):**
1. Batch name lookups → 2.5 min/day saved (2h)
2. Add BigQuery indexes → 50-150 sec/run saved (1h)
3. GCS lifecycle policies → $4,200/year saved (3h)
4. Remove dual Pub/Sub → $1,200/year saved (4h)
5. Schema CHECK constraints → Prevent bad data (2h)

**Total Quick Wins:** 12 hours, $5,400/year + 3+ min/day

---

## PRIORITY LEVELS

🔴 **P0 - CRITICAL** - Must fix immediately (prevent system failures)
🟠 **P1 - HIGH** - Do next (high value, prevents issues)
🟡 **P2 - MEDIUM** - Important but not urgent
⚪ **P3 - LOW** - Nice to have

---

## P0 - CRITICAL FIXES (18 hours total)

### These prevent CRITICAL system failures and must be done FIRST

| # | Issue | File(s) | Effort | Impact | Agent |
|---|-------|---------|--------|--------|-------|
| 1 | Silent failures return None/False | `bigquery_utils.py:92`, `verify_phase2_for_phase3.py:78` | 4h | Data loss prevention | Error Handling |
| 2 | Distributed lock race conditions UNTESTED | `distributed_lock.py`, `batch_staging_writer.py` | 4h | Duplicate rows prevention | Race Conditions, Testing |
| 3 | ArrayUnion 1000-element limit UNTESTED | `batch_state_manager.py:20` | 3h | Batch stuck prevention | Race Conditions, Testing |
| 4 | No processor execution logging | Create `processor_execution_log` table | 2h | Debug production | Monitoring |
| 5 | No schema constraints | `player_prop_predictions` table | 2h | Bad data prevention | Data Quality |
| 6 | Batch name lookups (QUICK WIN) | `player_name_resolver.py:146` | 2h | 2.5 min/day saved | Performance |
| 7 | Add BigQuery indexes (QUICK WIN) | `player_aliases`, `nba_players_registry`, `player_daily_cache` | 1h | 50-150 sec/run | Performance |

**Total P0:** 18 hours
**Impact:** Prevents 9 CRITICAL failure modes, saves 2-3 min/day

---

## P1 - HIGH PRIORITY (101 hours total)

### High value optimizations - cost savings + performance + reliability

#### A. Cost Optimization (35 hours → $13,360/year)

| # | Optimization | File(s) | Effort | Annual Savings | Agent |
|---|--------------|---------|--------|----------------|-------|
| 8 | GCS lifecycle policies (QUICK WIN) | `infra/gcs_lifecycle.tf` | 3h | $4,200 | Cost |
| 9 | Remove dual Pub/Sub publishing (QUICK WIN) | `pubsub_topics.py` | 4h | $1,200 | Cost |
| 10 | Compress GCS files | `storage_client.py` | 4h | $2,400 | Cost |
| 11 | Cloud Run memory optimization | `infra/cloud_run.tf` | 4h | $840 | Cost |
| 12 | Cloud Run CPU optimization | `infra/cloud_run.tf` | 5h | $1,980 | Cost |
| 13 | Archive old BigQuery tables | Various schemas | 8h | $2,400 | Cost |
| 14 | Implement request batching | `bigquery_client.py` | 6h | $200 | Cost |
| 15 | Pub/Sub message compression | `pubsub_client.py` | 4h | $600 | Cost |
| 16 | Pub/Sub batch publishing | `pubsub_publishers.py` | 6h | $800 | Cost |

**Subtotal:** 44h, $14,620/year

#### B. Performance Optimization (24 hours → 15-20 min/day)

| # | Optimization | File(s) | Effort | Time Saved | Agent |
|---|--------------|---------|--------|------------|-------|
| 17 | Complete TIER 1.1 timeouts | scrapers/, bin/ | 3h | Prevents hangs | Error Handling |
| 18 | TIER 1.2 partition filters | schemas/bigquery/ | 4h | $22-27/month | Previous |
| 19 | TIER 1.3 materialized views | schemas/bigquery/ | 8h | $14-18/month | Previous |
| 20 | .to_dataframe() optimization (partial) | `feature_extractor.py`, etc. | 4h | 5-10 sec/run | Performance |
| 21 | Clear memory caches | `feature_extractor.py` | 1h | 60-120 sec (GC) | Performance |
| 22 | Connection pooling | `bigquery_client.py` | 4h | 5-15 min/day | Performance |

**Subtotal:** 24h, 15-20 min/day + $36-45/month

#### C. Testing & Validation (24 hours)

| # | Test Type | Focus | Effort | Impact | Agent |
|---|-----------|-------|--------|--------|-------|
| 23 | Contract tests | External APIs (Odds, BDL, ESPN) | 12h | API reliability | API Contracts |
| 24 | Schema validation tests | BigQuery tables | 4h | Schema enforcement | API Contracts, Data Quality |
| 25 | Pub/Sub message tests | Message contracts | 4h | Pipeline reliability | API Contracts |
| 26 | Data loader timeout tests | `data_loaders.py` | 4h | Prevent duplicates | Testing |

**Subtotal:** 24h, prevents silent failures

#### D. Monitoring & Observability (9 hours)

| # | Improvement | Implementation | Effort | Impact | Agent |
|---|-------------|----------------|--------|--------|-------|
| 27 | End-to-end tracing | Correlation IDs throughout | 8h | 2-4h debugging → minutes | Monitoring |
| 28 | Prediction coverage SLO | Tracking dashboard + alerts | 1h | Visibility | Monitoring |

**Subtotal:** 9h, massive debugging time reduction

**Total P1:** 101 hours
**Impact:** $13,396/year + 15-20 min/day + comprehensive testing + debugging efficiency

---

## P2 - MEDIUM PRIORITY (75 hours total)

### Important infrastructure & security improvements

#### A. Schema & Data Management (20 hours)

| # | Task | File(s) | Effort | Impact | Agent |
|---|------|---------|--------|--------|-------|
| 29 | BigQuery explicit schemas | `bigquery_client.py`, schema files | 8h | Schema evolution | API Contracts |
| 30 | Odds API response validation | `oddsa_player_props.py` | 4h | Data quality | API Contracts |
| 31 | ESPN HTML validation | `espn_game_boxscore.py` | 6h | Robustness | API Contracts |
| 32 | Firestore document validation | `firestore_state.py` | 2h | State consistency | API Contracts |

#### B. Configuration & Security (14 hours)

| # | Task | File(s) | Effort | Impact | Agent |
|---|------|---------|--------|--------|-------|
| 33 | Secret rotation strategy | `secrets.py` | 4h | Security | Configuration |
| 34 | Firestore env prefixing | `firestore_collections.py` | 2h | Prevent prod corruption | Configuration |
| 35 | Configuration versioning | All config files | 4h | Track changes | Configuration |
| 36 | Feature flag validation | `feature_flags.py` | 3h | Prevent inconsistency | Configuration |
| 37 | Project ID env var support | `sport_config.py` | 1h | Multi-tenant ready | Configuration |

#### C. Code Quality & Refactoring (25 hours)

| # | Task | File(s) | Effort | Impact | Agent |
|---|------|---------|--------|--------|-------|
| 38 | Remove global state | `coordinator.py:212-217` | 4h | Race condition fix | Race Conditions |
| 39 | Implement message deduplication | `pubsub_client.py` | 8h | Prevent duplicates | Race Conditions |
| 40 | Expand distributed lock scope | `distributed_lock.py` | 3h | Better isolation | Race Conditions |
| 41 | Fix NULL line handling | `batch_staging_writer.py:337,347` | 2h | Data quality | Data Quality |
| 42 | Timezone consistency | Multiple files | 4h | Correctness | Data Quality |
| 43 | Add stack traces to error handlers | Multiple files | 2h | Debugging | Error Handling |
| 44 | Sanitize error messages | Multiple files | 2h | Security | Error Handling |

#### D. Additional Testing (16 hours)

| # | Test Suite | Focus | Effort | Impact | Agent |
|---|------------|-------|--------|--------|-------|
| 45 | TIER 1.4 critical tests | batch_staging_writer, data_freshness_validator | 12h | Coverage on critical paths | Previous |
| 46 | Firestore-BigQuery consistency tests | State validation | 4h | Prevent partial data | Testing |

**Total P2:** 75 hours
**Impact:** Production hardening, security, comprehensive testing

---

## P3 - LOW PRIORITY (46 hours total)

### Nice-to-have improvements

| # | Task | File(s) | Effort | Impact | Agent |
|---|------|---------|--------|--------|-------|
| 47 | TIER 1.5 SSL verification | MLB backfill scripts | 2h | Security | Previous |
| 48 | TIER 1.6 security headers | Flask apps | 4h | Security hardening | Previous |
| 49 | .iterrows() replacement | 26 files | 8h | 10.4 sec/run | Performance |
| 50 | Full .to_dataframe() optimization | Remaining 800+ calls | 12h | Additional 10-20 sec | Performance |
| 51 | Streaming buffer optimization | `player_name_resolver.py:439` | 8h | 1.5-3 min/day | Performance |
| 52 | Rate limit handling | All scrapers | 6h | API reliability | API Contracts |
| 53 | Circuit breaker implementation | Pattern files | 6h | Cascading failure prevention | API Contracts |

**Total P3:** 46 hours
**Impact:** Additional optimizations, advanced features

---

## ARCHITECTURE & INFRASTRUCTURE FINDINGS

### From Agent 7 (Architecture) - Information, Not Tasks

**6-Phase Pipeline Documented:**
- Phase 1: Scrapers (30+ scrapers) → GCS → Pub/Sub
- Phase 2: Raw Processing (6 processors) → BigQuery nba_raw → Pub/Sub
- Phase 3: Analytics (5 processors) → BigQuery nba_analytics → Pub/Sub
- Phase 4: Precompute (5 processors) → BigQuery nba_precompute → Pub/Sub
- Phase 5: Predictions (Coordinator + Workers) → 7 ML systems → BigQuery
- Phase 6: Publishing → API + Dashboards

**Critical Dependencies:**
- `bdl_player_boxscores` → Phase 2 → Phase 3 → Phase 4 → Phase 5 (entire chain)
- `ml_feature_store_v2` is CRITICAL for Phase 5

**Processing Timeline (Ideal):**
- 06:00 - Scrapers start
- 07:10 - All predictions complete
- **Total:** ~70 minutes end-to-end

**Single Points of Failure:**
- NBA.com API (2/10 risk, has BDL fallback)
- ml_feature_store_v2 table (3/10 risk, has tiered timeout)
- BigQuery (1/10 risk, has GCS backup)

### From Agent 8 (Configuration) - Information

**5-Layer Configuration Stack:**
1. Environment Variables (Cloud Run native)
2. Secret Manager (GCP, secure)
3. Python Dataclass (complex logic)
4. YAML (data sources, parameters)
5. Terraform (infrastructure)

**Timeout Centralization:**
- 1,070+ hardcoded timeout values → single `timeout_config.py`
- HTTP: 30s, BigQuery: 60s, Firestore: 10s, Workflows: 600s

**Feature Flags:**
- All default to False for safety
- Enable gradually: query caching, subcollection completions, idempotency keys, etc.

---

## COST BREAKDOWN BY CATEGORY

| Category | Current Cost/Month | Optimized Cost/Month | Annual Savings | Effort |
|----------|-------------------|----------------------|----------------|--------|
| **BigQuery** | $80-100 | $50-70 | $360-960 (+ partition filters/MVs) | 24h |
| **Cloud Run** | $250 | $150 | $1,200 (+ memory/CPU optimization) | 15h |
| **Pub/Sub** | $250 | $100 | $1,800 | 24h |
| **GCS Storage** | $500 | $150 | $4,200 | 17h |
| **APIs** | $50 | $30 | $240 | 14h |
| **TOTAL TIER 0-3** | $1,130-1,150 | $480-500 | $7,800-7,920 | N/A |
| **NEW FINDINGS** | +$500 | +$100 | +$4,800 | 94h |
| **GRAND TOTAL** | ~$1,630-1,650 | ~$580-600 | **$12,600-12,720** | - |

---

## TIME SAVINGS BY CATEGORY

| Category | Current Time | Optimized Time | Daily Savings | Annual Savings |
|----------|--------------|----------------|---------------|----------------|
| **Sequential name lookups** | 2.5 min | 0 min | 2.5 min | 15 hours |
| **Debugging production issues** | 2-4 hours | 5-10 min | Variable | 100+ hours |
| **BigQuery query performance** | Baseline | -50-150 sec/run | 1-2 min | 6-12 hours |
| **.to_dataframe() materialization** | 15-30 sec/run | 5-10 sec/run | 10-20 sec | 1-2 hours |
| **GC overhead (cache cleanup)** | 60-120 sec | 0 sec | 1-2 min | 6-12 hours |
| **TOTAL** | - | - | **17-29 min/day** | **100-150 hours/year** |

---

## TESTING COVERAGE GOALS

| Component | Current Coverage | Target Coverage | Gap | Priority |
|-----------|------------------|-----------------|-----|----------|
| **Distributed Lock** | 0% | 80% | CRITICAL | P0 |
| **Batch State Manager** | 10% | 80% | CRITICAL | P0 |
| **Data Loaders** | 20% | 70% | HIGH | P1 |
| **Prediction Systems** | 15% | 70% | HIGH | P1 |
| **API Contracts** | 3% (1/36) | 80% | HIGH | P1 |
| **Processors** | 10-15% | 70% | MEDIUM | P2 |
| **OVERALL** | **10-15%** | **70%+** | **60%** | - |

---

## WEEKLY EXECUTION PLAN

### Week 1: P0 Critical Fixes + Quick Wins (30 hours)

**Priority:** Prevent system failures + grab low-hanging fruit

```
P0 Critical Fixes (18h):
[ ] Fix silent failures (4h)
[ ] Add distributed lock tests (4h)
[ ] Add ArrayUnion boundary tests (3h)
[ ] Create processor_execution_log (2h)
[ ] Add schema constraints (2h)
[ ] Batch name lookups (2h)
[ ] Add BigQuery indexes (1h)

P1 Quick Wins (12h):
[ ] GCS lifecycle policies (3h) → $4,200/year
[ ] Remove dual Pub/Sub (4h) → $1,200/year
[ ] TIER 1.2 partition filters (4h) → $22-27/month
[ ] Memory optimization (1h partial) → $200/year
```

**Total:** 30 hours
**Savings:** ~$5,627/year first week + prevent 9 CRITICAL failures

### Week 2: Cost + Performance (40 hours)

```
Cost Optimization (20h):
[ ] Compress GCS files (4h) → $2,400/year
[ ] Cloud Run memory optimization (4h) → $840/year
[ ] Cloud Run CPU optimization (5h) → $1,980/year
[ ] Pub/Sub message compression (4h) → $600/year
[ ] Delete test artifacts (2h) → $480/year
[ ] Archive old tables (8h) → $2,400/year

Performance Optimization (20h):
[ ] Complete TIER 1.1 timeouts (3h)
[ ] TIER 1.3 materialized views (8h) → $14-18/month
[ ] .to_dataframe() partial optimization (4h) → 5-10 sec/run
[ ] Clear memory caches (1h) → 60-120 sec saved
[ ] Connection pooling (4h) → 5-15 min/day
```

**Total:** 40 hours
**Savings:** $8,700/year + 10-20 min/day

### Week 3: Testing + Monitoring (40 hours)

```
Contract & Validation Tests (24h):
[ ] External API contract tests (12h)
[ ] Schema validation tests (4h)
[ ] Pub/Sub message tests (4h)
[ ] Data loader timeout tests (4h)

Monitoring (16h):
[ ] End-to-end tracing (8h) → 2-4h debugging → minutes
[ ] TIER 1.4 critical tests (12h)
[ ] Prediction coverage SLO (1h)
```

**Total:** 40 hours
**Impact:** 70% test coverage, massive debugging efficiency

### Week 4: Infrastructure + Security (40 hours)

```
Schema & Data (20h):
[ ] BigQuery explicit schemas (8h)
[ ] Odds API response validation (4h)
[ ] ESPN HTML validation (6h)
[ ] Firestore document validation (2h)

Configuration & Security (14h):
[ ] Secret rotation strategy (4h)
[ ] Firestore env prefixing (2h)
[ ] Configuration versioning (4h)
[ ] Feature flag validation (3h)
[ ] Project ID env var (1h)

Code Quality (6h):
[ ] Remove global state (4h)
[ ] Pub/Sub request batching (6h) → $800/year
[ ] Additional optimizations (partial)
```

**Total:** 40 hours
**Impact:** Production-grade hardening, additional $800/year

---

## SUMMARY & PROGRESS TRACKING

**Total Work Identified:** ~250 hours
**Completed:** 9.5 hours (4%)
**Remaining:** ~240 hours (96%)

**4-Week Execution Plan:** 150 hours
**After 4 Weeks:**
- ✅ All P0 critical fixes complete
- ✅ ~$15,127/year in cost savings realized (~71% of total)
- ✅ 17-29 min/day faster processing
- ✅ Test coverage: 10% → 70%+
- ✅ 14+ CRITICAL failure modes prevented
- ✅ Debugging time: hours → minutes

**Remaining After 4 Weeks:** ~100 hours of P2-P3 work
- Additional performance optimizations
- Advanced features (circuit breaker, rate limiting)
- Full .to_dataframe() optimization
- Additional security hardening

---

## KEY METRICS TO TRACK

### Cost Metrics
```sql
SELECT
  DATE_TRUNC(billing_month, MONTH) as month,
  service,
  SUM(cost_usd) as total_cost
FROM billing.gcp_costs
WHERE DATE(billing_month) >= '2026-01-01'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

### Performance Metrics
- Daily pipeline latency (target: < 90 minutes)
- Query performance (track top 10 slowest queries)
- GC overhead (track memory cleanup duration)
- Debugging time per production issue (target: < 30 min)

### Reliability Metrics
- Test coverage % (target: 70%+)
- Production errors per week (target: < 5)
- Data quality violations (target: 0 schema constraint violations)
- End-to-end trace success rate (target: 100%)

---

## FILES REQUIRING IMMEDIATE ATTENTION (P0)

**Must Fix This Week:**
1. `/home/naji/code/nba-stats-scraper/shared/utils/bigquery_utils.py:92-95`
2. `/home/naji/code/nba-stats-scraper/bin/backfill/verify_phase2_for_phase3.py:78-80`
3. `/home/naji/code/nba-stats-scraper/predictions/coordinator/distributed_lock.py` (add tests)
4. `/home/naji/code/nba-stats-scraper/predictions/coordinator/batch_staging_writer.py` (add tests)
5. `/home/naji/code/nba-stats-scraper/predictions/coordinator/batch_state_manager.py:20` (add tests)
6. `/home/naji/code/nba-stats-scraper/schemas/bigquery/predictions/player_prop_predictions.sql` (ADD CONSTRAINT)
7. `/home/naji/code/nba-stats-scraper/shared/utils/player_name_resolver.py:146` (batch queries)
8. Create `nba_monitoring.processor_execution_log` table (DDL)
9. Add indexes to `player_aliases`, `nba_players_registry`, `player_daily_cache`

---

**Last Updated:** 2026-01-21 22:30 PT
**Next Review:** After Week 1 execution (2026-01-28)
**Status:** Ready for execution 🚀

**May the code be with you.** ⚙️
