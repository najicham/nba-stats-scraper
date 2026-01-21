# Architectural Decisions - Health Endpoints Implementation

**Project:** Health Endpoints Implementation (Phase 1, Task 1.1)
**Date:** January 18, 2026
**Status:** Active

This document captures key architectural decisions made during the health endpoints implementation project.

---

## Decision 001: NBA Worker Migration Strategy

**Date:** January 18, 2026
**Status:** ✅ DECIDED
**Decision Maker:** Analysis by Claude Sonnet 4.5, final approval by user

### Context

The NBA Prediction Worker (`predictions/worker/`) has a comprehensive, custom health check implementation (`health_checks.py`, 422 lines) that predates our new shared health module. We need to decide whether to migrate it to the shared module or keep it separate.

### Current NBA Worker Health Checks

**File:** `predictions/worker/health_checks.py`

**Custom HealthChecker class with 4 specialized checks:**

1. **`check_gcs_access()`** - ML Model-Specific GCS Validation
   - Parses `CATBOOST_V8_MODEL_PATH` (format: `gs://bucket/path/file.cbm`)
   - Validates model file exists and reads metadata (size, last updated)
   - Checks `nba-scraped-data` bucket accessibility
   - Returns detailed model information in health response

2. **`check_bigquery_access()`** - Production Table-Specific Checks
   - Queries actual production table: `nba_predictions.player_prop_predictions`
   - Counts predictions for today (validates table structure)
   - Returns row count in health response

3. **`check_model_loading()`** - CatBoost Model Validation
   - Validates `.cbm` file extension
   - Checks both GCS and local model paths
   - Supports local model fallback (searches `models/` directory)
   - Returns model source and availability details

4. **`check_configuration()`** - Worker-Specific Environment Variables
   - Required: `GCP_PROJECT_ID`
   - Optional: `CATBOOST_V8_MODEL_PATH`, `PREDICTIONS_TABLE`, `PUBSUB_READY_TOPIC`
   - Provides warnings for missing optional vars

**Integration:** Endpoint `/health/deep` imports and uses this custom HealthChecker (line 1641-1668)

### Shared Health Module

**File:** `shared/endpoints/health.py`

**Generic HealthChecker class with configurable checks:**
- `check_bigquery_connectivity()` - Generic BigQuery validation (SELECT 1)
- `check_firestore_connectivity()` - Generic Firestore validation
- `check_gcs_connectivity()` - Generic GCS bucket listing (configurable buckets)
- `check_environment_variables()` - Generic env var validation
- **`custom_checks` parameter** - Dict of custom check functions (extensible!)

**Key difference:** Generic vs. Specialized
- Shared module: Validates basic connectivity
- NBA Worker: Validates specific model paths, production tables, file formats

### Options Considered

#### Option A: Keep NBA Worker Separate (No Migration)

**Pros:**
- ✅ Zero risk - existing implementation is working perfectly
- ✅ No code changes needed - tested and battle-hardened
- ✅ Model-specific logic stays in worker context
- ✅ Can implement immediately (no migration work)

**Cons:**
- ❌ Two health check patterns in codebase
- ❌ Maintenance burden (two implementations to update)
- ❌ NBA Worker doesn't benefit from shared module improvements

#### Option B: Full Migration to Shared Module

**Pros:**
- ✅ Single health check pattern across all services
- ✅ NBA Worker benefits from shared module improvements
- ✅ Centralized health check logic

**Cons:**
- ❌ HIGH RISK - NBA Worker is production-critical
- ❌ Significant work required (2-4 hours migration + testing)
- ❌ Custom logic needs to be ported carefully
- ❌ Potential for introducing bugs in working system

#### Option C: Hybrid Approach (Shared + Custom Checks)

**Pros:**
- ✅ Best of both worlds - uses shared module for common checks
- ✅ Custom checks implemented via `custom_checks` parameter
- ✅ Validates shared module's extensibility
- ✅ Eventually brings NBA Worker into shared pattern

**Cons:**
- ❌ Still requires migration work
- ❌ Still carries migration risk
- ❌ More complex implementation

#### Option D: Keep Separate + Enhance Shared Module (SELECTED)

**Pros:**
- ✅ ZERO risk to NBA Worker (keep as-is)
- ✅ Shared module proves itself with simpler services first
- ✅ Custom checks feature can be validated incrementally
- ✅ NBA Worker serves as reference implementation
- ✅ Migration can happen later when shared module is mature
- ✅ No immediate work required for NBA Worker

**Cons:**
- ❌ Two patterns exist temporarily (acceptable tradeoff)
- ❌ Migration work deferred (but not abandoned)

### Decision

**SELECTED: Option D - Keep NBA Worker Separate (for now)**

**Rationale:**

1. **Production Safety First**
   - NBA Worker is the most critical prediction service
   - It has comprehensive, working health checks
   - "If it ain't broke, don't fix it"

2. **Shared Module Should Prove Itself**
   - Test shared module with simpler services first (coordinator, dashboard, etc.)
   - Once proven stable and reliable, consider NBA Worker migration
   - Real-world usage will reveal any issues or missing features

3. **Custom Checks Need Validation**
   - Shared module has `custom_checks` parameter but it's untested
   - Other services don't need custom checks yet
   - NBA Worker migration would be a good test case LATER

4. **Pragmatic Timeline**
   - Immediate focus: Test and deploy shared module to 5 services
   - Phase 2 or 3: Revisit NBA Worker migration
   - No rush - working code is good code

5. **Reference Implementation**
   - NBA Worker's health_checks.py serves as gold standard
   - It shows what comprehensive health checks should look like
   - Other services can learn from its pattern

### Implementation Plan

**Phase 1 (Current - Week 1-2):**
- ✅ Keep NBA Worker health checks as-is
- ✅ Deploy shared module to 5 other services
- ✅ Document both patterns in codebase
- ✅ Monitor shared module in production

**Phase 2 (Week 3-6):**
- Validate custom_checks feature with simpler use case
- Gather feedback on shared module from production usage
- Identify any missing features or issues

**Phase 3+ (Month 2+):**
- Re-evaluate NBA Worker migration
- If shared module is stable and feature-complete, migrate NBA Worker
- Use migration as comprehensive test of custom_checks feature
- Compare health check response quality before/after

### Code Documentation

Both patterns will be documented:

**In shared/endpoints/health.py:**
```python
# NOTE: NBA Prediction Worker uses a custom health check implementation
# (predictions/worker/health_checks.py) with specialized ML model validation.
# This is intentional - the shared module focuses on generic dependency checks,
# while the worker requires model-specific validation logic.
# See: docs/08-projects/current/health-endpoints-implementation/DECISIONS.md
```

**In predictions/worker/health_checks.py:**
```python
# NOTE: This module is NBA Worker-specific and not using the shared health module
# (shared/endpoints/health.py). This is intentional - the worker requires specialized
# ML model validation that goes beyond generic dependency checks.
# See: docs/08-projects/current/health-endpoints-implementation/DECISIONS.md
```

### Success Metrics

**For Keeping Separate:**
- NBA Worker health checks continue to work without issues
- Zero incidents related to health check changes
- NBA Worker serves as reference for best practices

**For Eventual Migration:**
- Shared module runs in production for 30+ days without issues
- Custom checks feature validated with at least one other service
- Team consensus that migration would add value
- Clear migration plan with rollback strategy

### Related Decisions

- [Decision 002](#decision-002-custom-checks-feature) - Custom Checks Feature in Shared Module
- [Decision 003](#decision-003-health-check-caching) - Health Check Response Caching

---

## Decision 002: Custom Checks Feature in Shared Module

**Date:** January 18, 2026
**Status:** ✅ IMPLEMENTED (Ready for Use)

### Context

The shared health module needs to support service-specific health checks beyond generic dependency validation.

### Decision

**APPROVED:** Implement custom_checks parameter in HealthChecker class

**Implementation:**

```python
health_checker = HealthChecker(
    project_id='nba-props-platform',
    service_name='my-service',
    custom_checks={
        'model_availability': check_model_file,
        'pubsub_topic': check_pubsub_topic_exists,
        'api_rate_limit': check_api_rate_limit_remaining
    }
)
```

**Custom check function signature:**
```python
def check_model_file() -> Dict[str, Any]:
    """
    Custom health check example.

    Returns:
        {
            "check": "model_availability",
            "status": "pass|fail|skip",
            "details": {...},
            "duration_ms": 123
        }
    """
    # Implementation...
```

**Benefits:**
- Services can add specialized health checks
- Maintains consistent response format
- Integrates with parallel execution
- Works with timeouts and error handling

**Current Status:** Implemented but not yet used in production

**Next Steps:** Validate with a simple custom check before considering NBA Worker migration

---

## Decision 003: Health Check Response Caching

**Date:** January 18, 2026
**Status:** 🤔 DEFERRED

### Context

Health endpoints may be called frequently by load balancers, monitoring systems, and dashboards. Should we cache responses to reduce load on dependencies?

### Options

**Option A: No Caching**
- Always run fresh checks
- Most accurate status
- Higher load on dependencies

**Option B: Cache /health Only**
- Cache basic liveness check (10-30 seconds)
- Deep checks always fresh
- Reduces load for simple health checks

**Option C: Cache Everything**
- Cache all health check results
- Risk of stale data
- Significantly reduces dependency load

### Decision

**DEFERRED** - Implement caching only if needed

**Rationale:**
- Health checks are lightweight (SELECT 1, bucket list)
- No evidence of performance issues
- Premature optimization
- Can add later if monitoring shows excessive load

**When to revisit:**
- BigQuery costs from health checks >$10/month
- Health check latency p95 >1 second
- Dependency rate limiting issues
- >100 health checks/minute sustained

---

## Decision 004: Authentication for Health Endpoints

**Date:** January 18, 2026
**Status:** ✅ DECIDED

### Decision

**NO AUTHENTICATION** for /health and /ready endpoints

**Rationale:**
- Industry standard practice (Kubernetes, Cloud Run, etc.)
- Health endpoints don't expose secrets
- Load balancers and orchestrators need unauthenticated access
- Monitoring systems expect public health endpoints

**Exception:** Admin Dashboard has rate limiting but not authentication

**Security Mitigations:**
- Rate limiting can be added if abuse detected
- Responses are sanitized (no sensitive data exposed)
- Error messages don't reveal internal architecture details

---

## Decision 005: Cloud Run Health Check Configuration

**Date:** January 18, 2026
**Status:** 📋 TODO (After Staging Validation)

### Context

Cloud Run supports configurable health checks for liveness and startup probes.

### Decision (Proposed)

**Use /health for liveness, /ready for startup:**

```yaml
# service.yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3

startupProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 0
  periodSeconds: 5
  timeoutSeconds: 10
  failureThreshold: 12  # Allow 60 seconds for startup
```

**Rationale:**
- `/health` is fast (<100ms) - good for liveness
- `/ready` is thorough (<5s) - good for startup validation
- Prevents traffic to unhealthy instances
- Enables automatic health-based scaling

**Status:** Not yet implemented - waiting for staging validation

---

## Appendix: NBA Worker Health Check Details

### Example NBA Worker /health/deep Response

```json
{
  "status": "healthy",
  "checks": [
    {
      "check": "gcs_access",
      "status": "pass",
      "details": {
        "catboost_model": {
          "status": "pass",
          "path": "gs://nba-scraped-data/ml-models/catboost_v8_33features_20250115_120000.cbm",
          "size_bytes": 15728640,
          "updated": "2025-01-15T12:00:00Z"
        },
        "data_bucket": {
          "status": "pass",
          "bucket": "nba-scraped-data",
          "accessible": true
        }
      },
      "duration_ms": 234
    },
    {
      "check": "bigquery_access",
      "status": "pass",
      "details": {
        "table": "nba_predictions.player_prop_predictions",
        "query_successful": true,
        "row_count": 3400
      },
      "duration_ms": 187
    },
    {
      "check": "model_loading",
      "status": "pass",
      "details": {
        "catboost_v8": {
          "status": "pass",
          "path": "gs://nba-scraped-data/ml-models/catboost_v8_33features_20250115_120000.cbm",
          "format_valid": true,
          "note": "Model loading deferred to first prediction (lazy load)"
        }
      },
      "duration_ms": 12
    },
    {
      "check": "configuration",
      "status": "pass",
      "details": {
        "GCP_PROJECT_ID": {"status": "pass", "set": true},
        "CATBOOST_V8_MODEL_PATH": {"status": "pass", "set": true, "value": "gs://..."},
        "PREDICTIONS_TABLE": {"status": "pass", "set": true, "value": "nba_predictions.player_prop_predictions"},
        "PUBSUB_READY_TOPIC": {"status": "pass", "set": true, "value": "prediction-ready"}
      },
      "duration_ms": 3
    }
  ],
  "total_duration_ms": 436,
  "checks_run": 4,
  "checks_passed": 4,
  "checks_failed": 0
}
```

This level of detail is valuable for debugging and exactly what comprehensive health checks should provide.

---

**Document Status:** Active
**Last Updated:** January 18, 2026
**Next Review:** After Phase 1 deployment complete
