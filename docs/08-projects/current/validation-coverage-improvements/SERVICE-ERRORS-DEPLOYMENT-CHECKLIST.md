# Service Errors Table - Deployment Checklist

**Date**: 2026-01-28
**Status**: Ready for Deployment

---

## Pre-Deployment Checklist

### ✅ Code Complete
- [x] BigQuery schema created (`schemas/bigquery/nba_orchestration/service_errors.sql`)
- [x] ServiceErrorLogger utility implemented (`shared/utils/service_error_logger.py`)
- [x] TransformProcessorBase integration complete
- [x] Unit tests passing (13/13)
- [x] Import verification successful
- [x] Documentation complete

### ✅ Testing Complete
- [x] Unit tests pass: `pytest tests/unit/utils/test_service_error_logger.py -v`
- [x] Import tests pass: `python -c "from shared.utils.service_error_logger import ServiceErrorLogger"`
- [x] Example script runs: `python examples/service_error_logger_usage.py`
- [x] Integration verified: TransformProcessorBase imports successfully

---

## Deployment Steps

### Step 1: Deploy BigQuery Schema

```bash
# Navigate to project root
cd /home/naji/code/nba-stats-scraper

# Deploy the schema
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/service_errors.sql
```

**Verification**:
```bash
# Check table exists
bq show nba-props-platform:nba_orchestration.service_errors

# Check schema
bq show --schema --format=prettyjson nba-props-platform:nba_orchestration.service_errors
```

**Expected Output**:
- Table created successfully
- Partitioned by `DATE(error_timestamp)`
- Clustered by `service_name, error_category, severity`

---

### Step 2: Commit and Push Code Changes

```bash
# Review changes
git status
git diff shared/processors/base/transform_processor_base.py

# Stage files
git add schemas/bigquery/nba_orchestration/service_errors.sql
git add shared/utils/service_error_logger.py
git add shared/processors/base/transform_processor_base.py
git add tests/unit/utils/test_service_error_logger.py
git add examples/service_error_logger_usage.py
git add docs/08-projects/current/validation-coverage-improvements/

# Commit
git commit -m "feat: Add centralized error logging to BigQuery

Implements Service Errors Table for centralized error persistence across all services.

Changes:
- Add BigQuery schema for nba_orchestration.service_errors table
- Add ServiceErrorLogger utility with automatic error categorization
- Integrate error logging into TransformProcessorBase.report_error()
- Add 13 unit tests (all passing)
- Add usage examples and comprehensive documentation

Coverage:
- Phase 3 Analytics processors: Automatic (via TransformProcessorBase)
- Phase 4 Precompute processors: Automatic (via TransformProcessorBase)
- Cloud Functions: Manual integration available (decorator pattern)

Features:
- Automatic error categorization via failure_categorization.py
- Hash-based deduplication via error_id
- <10ms overhead per log call
- Graceful failure (doesn't crash main process)
- 90-day retention, <\$0.01/month cost

References:
- Investigation: docs/.../05-INVESTIGATION-FINDINGS.md
- Implementation: docs/.../06-SERVICE-ERRORS-IMPLEMENTATION.md
- User Guide: docs/.../SERVICE-ERROR-LOGGER-README.md

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

# Push
git push origin main
```

---

### Step 3: Deploy to Production

**For Phase 3 & 4 Processors** (Analytics & Precompute):
- No additional deployment needed
- Changes in TransformProcessorBase automatically apply
- Errors will start logging on next processor run

**For Cloud Functions** (Optional):
- Manually integrate using decorator pattern (see examples)
- Redeploy functions after adding ServiceErrorLogger

---

### Step 4: Verify Initial Data Flow

Wait for next processor run (or trigger manually), then check for data:

```sql
-- Check first errors logged
SELECT
  error_timestamp,
  service_name,
  error_category,
  severity,
  error_message
FROM `nba-props-platform.nba_orchestration.service_errors`
ORDER BY error_timestamp DESC
LIMIT 10;
```

**Expected**:
- Errors from Phase 3 & 4 processors appear
- error_category correctly set (no_data_available, processing_error, etc.)
- severity matches category (critical, warning, info)
- game_date, phase, processor_name populated

---

### Step 5: Monitor Initial Performance

```sql
-- Error volume by day
SELECT
  DATE(error_timestamp) as date,
  COUNT(*) as error_count,
  COUNT(DISTINCT service_name) as unique_services
FROM `nba-props-platform.nba_orchestration.service_errors`
GROUP BY date
ORDER BY date DESC;

-- Error breakdown by category
SELECT
  error_category,
  severity,
  COUNT(*) as count,
  COUNT(DISTINCT service_name) as services
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY error_category, severity
ORDER BY count DESC;

-- Top error sources
SELECT
  service_name,
  COUNT(*) as error_count,
  COUNT(DISTINCT error_type) as unique_error_types
FROM `nba-props-platform.nba_orchestration.service_errors`
WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY service_name
ORDER BY error_count DESC
LIMIT 10;
```

---

### Step 6: Verify Deduplication

Test that same error within same minute gets same error_id:

```sql
-- Check for duplicate error_ids
SELECT
  error_id,
  COUNT(*) as occurrences,
  ARRAY_AGG(error_timestamp ORDER BY error_timestamp LIMIT 3) as timestamps
FROM `nba-props-platform.nba_orchestration.service_errors`
GROUP BY error_id
HAVING COUNT(*) > 1
ORDER BY occurrences DESC
LIMIT 10;
```

**Expected**: Multiple occurrences of same error_id within same minute (deduplication working)

---

## Post-Deployment Monitoring

### Week 1: Initial Monitoring

**Daily checks**:
- [ ] Errors being logged (>0 rows/day)
- [ ] No BigQuery quota issues
- [ ] Error categorization looks correct
- [ ] Query performance <1s for common queries

**Queries to run**:
```sql
-- Daily summary
SELECT
  DATE(error_timestamp) as date,
  error_category,
  COUNT(*) as count
FROM `nba-props-platform.nba_orchestration.service_errors`
GROUP BY date, error_category
ORDER BY date DESC, count DESC;
```

### Week 2: Validation

**Check**:
- [ ] Error volume matches expectations (10-42/day normal)
- [ ] False alert rate reduced (should be ~90% reduction)
- [ ] Storage cost <$0.01/month
- [ ] No application performance impact

### Month 1: Optimize

**Actions**:
- [ ] Review error patterns
- [ ] Adjust categorization if needed
- [ ] Add missing services (Cloud Functions)
- [ ] Setup recommended alerts

---

## Rollback Plan

If issues occur:

### Rollback Step 1: Disable Logging

Option A - Environment variable:
```bash
# Set environment variable to disable logging
export SERVICE_ERROR_LOGGING_ENABLED=false
```

Option B - Code change:
```python
# In shared/utils/service_error_logger.py
# Change default enabled to False
def __init__(self, enabled: bool = False):  # Changed from True to False
```

### Rollback Step 2: Revert Code Changes

```bash
# Revert TransformProcessorBase changes
git revert <commit-hash>

# Push
git push origin main
```

### Rollback Step 3: Drop Table (if needed)

```bash
# Only if table causes issues
bq rm -f nba-props-platform:nba_orchestration.service_errors
```

---

## Success Criteria

### ✅ Deployment Successful If:
1. BigQuery table created successfully
2. Code deployed without errors
3. First errors logged within 24 hours
4. Error categorization accurate (spot check)
5. No application performance degradation
6. Query performance <1s for common queries
7. Storage cost <$0.01/month

### ⚠️ Issues to Watch For:
- BigQuery quota exceeded (unlikely with low volume)
- Slow query performance (should be fast with partitioning/clustering)
- Application errors from logging failures (should fail gracefully)
- Incorrect error categorization (fix in failure_categorization.py)

---

## Support Resources

### Documentation
- User Guide: `docs/.../SERVICE-ERROR-LOGGER-README.md`
- Implementation: `docs/.../06-SERVICE-ERRORS-IMPLEMENTATION.md`
- Investigation: `docs/.../05-INVESTIGATION-FINDINGS.md`

### Code
- ServiceErrorLogger: `shared/utils/service_error_logger.py`
- Integration: `shared/processors/base/transform_processor_base.py`
- Tests: `tests/unit/utils/test_service_error_logger.py`
- Examples: `examples/service_error_logger_usage.py`

### Queries
- All example queries in schema file: `schemas/bigquery/nba_orchestration/service_errors.sql`

---

## Contact

**Questions or Issues?**
- Review documentation in `docs/08-projects/current/validation-coverage-improvements/`
- Check unit tests for usage examples
- Run example script: `python examples/service_error_logger_usage.py`

---

## Deployment Sign-Off

**Pre-Deployment**:
- [ ] All code changes reviewed
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Deployment plan reviewed

**Post-Deployment**:
- [ ] BigQuery table created
- [ ] Code deployed to production
- [ ] Initial data verified
- [ ] Performance monitored
- [ ] No issues detected

**Approved By**: _________________
**Date**: _________________
**Notes**: _________________

---

**Status**: Ready for deployment 🚀
