# Validation Improvements - Session 81 Handoff

**Date:** February 2-3, 2026
**Session:** 81
**Status:** 2 of 11 validation checks implemented, 9 remaining

---

## Quick Context

Session 81 analyzed recent incidents (Sessions 73-85) and identified **11 critical validation gaps** that allowed bugs to reach production. We've implemented 2 quick wins, and this handoff describes how to implement the remaining 9.

---

## What Was Completed (Session 81)

### ✅ Implemented (2 checks)

1. **Deployment Drift Check** - Phase 0.1 in `/validate-daily`
   - Catches when bug fixes are committed but not deployed
   - Prevented issues in Sessions 82, 81, 64

2. **Prediction Deactivation Validation** - Phase 0.46 in `/validate-daily`
   - Catches when `is_active` logic breaks
   - Would have caught Session 78 bug (85% predictions incorrectly deactivated)

---

## What Needs Implementation (9 checks)

### Priority 0 - Data Loss & Service Outages (3 remaining)

#### P0-1: Silent BigQuery Write Failures

**Problem:** Services complete successfully but write 0 records to BigQuery (Session 80: grading service)

**Impact:** Data loss, false success signals, broken pipelines

**Implementation:** Post-deployment verification suite

**Where to add:** New script `bin/monitoring/verify-bigquery-writes.sh`

**Code:**
```bash
#!/bin/bash
# Verify recent BigQuery writes after deployment

SERVICE=$1
LOOKBACK_MINUTES=${2:-60}

case "$SERVICE" in
  "nba-grading-service")
    TABLES=("nba_predictions.prediction_accuracy")
    ;;
  "nba-phase3-analytics-processors")
    TABLES=("nba_analytics.player_game_summary" "nba_analytics.team_game_summary")
    ;;
  "prediction-worker")
    TABLES=("nba_predictions.player_prop_predictions")
    ;;
  *)
    echo "Unknown service: $SERVICE"
    exit 1
    ;;
esac

ERRORS=0
for table in "${TABLES[@]}"; do
  echo "Checking $table..."

  count=$(bq query --use_legacy_sql=false --format=csv "
    SELECT COUNT(*) FROM \`$table\`
    WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $LOOKBACK_MINUTES MINUTE)
  " | tail -1)

  if [[ "$count" == "0" ]]; then
    echo "❌ CRITICAL: $table has 0 recent writes (last $LOOKBACK_MINUTES minutes)"
    ERRORS=$((ERRORS + 1))
  else
    echo "✅ OK: $table has $count recent writes"
  fi
done

if [[ $ERRORS -gt 0 ]]; then
  echo ""
  echo "🚨 CRITICAL: $ERRORS table(s) with no recent writes detected!"
  echo "Service may be silently failing. Check logs:"
  echo "  gcloud logging read 'resource.labels.service_name=\"$SERVICE\" AND severity>=ERROR' --limit=50"
  exit 1
fi

echo ""
echo "✅ All tables have recent writes - service is writing data correctly"
```

**Integration:** Add to `./bin/deploy-service.sh` as post-deployment check

**Effort:** 1 hour

---

#### P0-2: Missing Docker Dependencies

**Problem:** Service works locally but crashes in Docker due to missing requirements.txt entries (Session 80: missing google-cloud-pubsub)

**Impact:** Service down for 38+ hours

**Implementation:** Pre-deployment Docker import test

**Where to add:** Enhance `./bin/deploy-service.sh`

**Code:**
```bash
# Add to deploy-service.sh BEFORE deployment

echo "🔍 Testing Docker dependencies..."

# Build test image
docker build -t "$SERVICE:dep-test" -f "$DOCKERFILE_PATH" . --quiet

# Test all imports
docker run --rm "$SERVICE:dep-test" python3 << 'PYEOF'
import sys
import pkgutil
import importlib

# Find all Python files in service directory
# Extract import statements
# Try importing each one

critical_imports = []
service_dir = sys.argv[1] if len(sys.argv) > 1 else "."

# Basic test: try importing the main module
try:
    # For coordinator
    import coordinator
    print("✅ Main module imports successfully")
except ImportError as e:
    print(f"❌ CRITICAL: Main module import failed: {e}")
    sys.exit(1)

# Test common dependencies
common_deps = [
    "google.cloud.bigquery",
    "google.cloud.pubsub_v1",
    "google.cloud.firestore",
    "flask",
    "pandas"
]

failed = []
for dep in common_deps:
    try:
        importlib.import_module(dep)
        print(f"✅ {dep}")
    except ImportError as e:
        failed.append((dep, str(e)))

if failed:
    print("\n❌ Missing dependencies:")
    for dep, error in failed:
        print(f"  - {dep}: {error}")
    sys.exit(1)
PYEOF

if [[ $? -ne 0 ]]; then
  echo "🚨 BLOCKING DEPLOYMENT: Missing dependencies in Docker"
  echo "Fix requirements.txt and try again"
  exit 1
fi

echo "✅ Docker dependency test passed"
```

**Effort:** 2 hours

---

#### P0-3: Schema Mismatches (Code Writes Non-Existent Fields)

**Problem:** Code writes fields that don't exist in BigQuery schema (Sessions 79, 85)

**Impact:** Write failures, data loss, perpetual retry loops

**Implementation:** Enhance existing pre-commit hook

**Where to add:** `.pre-commit-hooks/validate_schema_fields.py`

**Enhancement needed:**
1. Scan for `insert_rows_json()` calls (currently only checks `load_table_from_json`)
2. Detect REPEATED fields receiving NULL (use `[]` instead)
3. Check for field type mismatches (string vs int)

**Specific improvements:**
```python
# Add to validate_schema_fields.py

def check_repeated_field_nulls(file_path, table_id, code):
    """Check if REPEATED fields might receive NULL values."""

    schema = load_bigquery_schema(table_id)
    repeated_fields = [f for f, meta in schema.items() if meta.get('mode') == 'REPEATED']

    issues = []
    for field in repeated_fields:
        # Check if field is set to None anywhere
        if re.search(rf"['\"]?{field}['\"]?\s*:\s*None", code):
            issues.append({
                'file': file_path,
                'field': field,
                'table': table_id,
                'error': f'REPEATED field {field} set to None (use [] for empty array)'
            })

    return issues

def check_insert_rows_json(file_path):
    """Scan for insert_rows_json calls and validate schema."""

    # Pattern to find insert_rows_json calls
    pattern = r'client\.insert_rows_json\(\s*["\']([^"\']+)["\']\s*,\s*(\[.*?\])'

    # Extract and validate...
```

**Effort:** 3 hours

---

### Priority 1 - Service Failures & False Alarms (4 remaining)

#### P1-1: Missing Partition Filters (400 Errors)

**Problem:** Querying partitioned tables without required filters (Sessions 73-74)

**Impact:** Service failures, 400 errors every 15 minutes

**Implementation:** Pre-commit hook to detect queries missing partition filters

**Code:**
```python
# .pre-commit-hooks/validate_partition_filters.py

PARTITIONED_TABLES = {
    'nba_raw.bdl_player_boxscores': {'field': 'game_date', 'required': True},
    'nba_raw.espn_scoreboard': {'field': 'game_date', 'required': True},
    'nba_raw.espn_team_rosters': {'field': 'roster_date', 'required': True},
    # ... add all 12 tables from Session 73-74
}

def validate_queries_in_file(file_path):
    """Check all BigQuery queries have required partition filters."""

    with open(file_path) as f:
        content = f.read()

    # Extract SQL queries (triple-quoted strings, f-strings, etc.)
    queries = extract_sql_queries(content)

    issues = []
    for query in queries:
        tables = parse_tables_from_query(query)

        for table in tables:
            if table in PARTITIONED_TABLES:
                config = PARTITIONED_TABLES[table]
                if config['required']:
                    partition_field = config['field']

                    # Check if partition field appears in WHERE clause
                    if not has_partition_filter(query, partition_field):
                        issues.append({
                            'file': file_path,
                            'table': table,
                            'error': f'Missing required partition filter on {partition_field}'
                        })

    return issues
```

**Effort:** 2 hours

---

#### P1-2: Environment Variable Drift

**Problem:** Manual deployments use `--set-env-vars` instead of `--update-env-vars`, wiping variables (Session 81)

**Impact:** Service crashes, missing configuration

**Implementation:** Post-deployment verification

**Code:**
```bash
# bin/monitoring/verify-env-vars-preserved.sh

SERVICE=$1

# Define required env vars per service
case "$SERVICE" in
  "prediction-worker")
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "DATASET_PREFIX"
      "CATBOOST_VERSION"
      "MIN_CONFIDENCE_THRESHOLD"
    )
    ;;
  "prediction-coordinator")
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "MIN_EDGE_THRESHOLD"
      "ENABLE_MULTI_INSTANCE"
    )
    ;;
  # ... other services
esac

# Get deployed env vars
DEPLOYED_VARS=$(gcloud run services describe "$SERVICE" --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env[].name)")

# Check all required vars present
MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
  if ! echo "$DEPLOYED_VARS" | grep -q "^$var$"; then
    MISSING+=("$var")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "🚨 CRITICAL: Missing env vars after deployment:"
  printf '  - %s\n' "${MISSING[@]}"
  echo ""
  echo "This indicates --set-env-vars was used instead of --update-env-vars"
  echo "Re-deploy with correct env vars"
  exit 1
fi
```

**Effort:** 1 hour

---

#### P1-3: Wrong Grading Denominator (Fixed in Session 80, but document)

**Problem:** Grading metric included ungradable predictions in denominator

**Status:** ✅ FIXED in Session 80 (multi-metric monitoring)

**No action needed** - Just document as resolved

---

#### P1-4: False Alarm Threshold Calibration

**Problem:** Validation thresholds based on assumptions, not data (Session 80: Vegas 90% when 44% is normal)

**Status:** ✅ FIXED in Session 80 for Vegas coverage

**Future work:** Add threshold calibration script for NEW metrics

**Code:**
```bash
# bin/monitoring/calibrate-threshold.sh

METRIC_NAME=$1
DAYS_LOOKBACK=${2:-30}

echo "Calibrating threshold for $METRIC_NAME using last $DAYS_LOOKBACK days..."

# Query historical values
bq query --use_legacy_sql=false --format=csv "
WITH historical AS (
  SELECT metric_value
  FROM monitoring.metric_history
  WHERE metric_name = '$METRIC_NAME'
    AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $DAYS_LOOKBACK DAY)
)
SELECT
  APPROX_QUANTILES(metric_value, 100)[OFFSET(1)] as p1,
  APPROX_QUANTILES(metric_value, 100)[OFFSET(5)] as p5,
  APPROX_QUANTILES(metric_value, 100)[OFFSET(10)] as p10,
  APPROX_QUANTILES(metric_value, 100)[OFFSET(50)] as median,
  MIN(metric_value) as min_observed,
  MAX(metric_value) as max_observed
FROM historical
" | tail -1 | while IFS=, read p1 p5 p10 median min max; do
  echo "Recommended thresholds for $METRIC_NAME:"
  echo "  CRITICAL: < $p1 (p1 - almost never below this)"
  echo "  WARNING:  < $p5 (p5 - rare but happens)"
  echo "  OK:       >= $p10 (p10 - normal range)"
  echo ""
  echo "Historical range: $min - $max (median: $median)"
done
```

**Effort:** 1 hour

---

### Priority 2 - Nice to Have (2 remaining)

#### P2-1: Model Attribution Tracking

**Status:** ✅ IMPLEMENTED in Session 83-84

**No action needed** - Already has `model_file_name`, `build_commit_sha` tracking

---

#### P2-2: Prediction Timing Lag Monitoring

**Problem:** Vegas lines available at 2 AM but predictions run at 7 AM (5-hour lag)

**Status:** Investigation complete (Sessions 73-74), early predictions now run at 2:30 AM

**Future work:** Monitor for regression

**Code:**
```sql
-- Add to daily validation
-- Check prediction timing vs line availability

WITH line_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_line_available
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = CURRENT_DATE()
    AND points_line IS NOT NULL
  GROUP BY game_date
),
pred_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_prediction
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
    AND system_id = 'catboost_v9'
  GROUP BY game_date
)
SELECT
  p.game_date,
  l.first_line_available,
  p.first_prediction,
  TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, HOUR) as lag_hours,
  CASE
    WHEN TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, HOUR) > 4
      THEN '⚠️ Timing regression detected'
    ELSE '✅ OK'
  END as status
FROM pred_timing p
JOIN line_timing l USING (game_date)
```

**Effort:** 30 minutes

---

## Implementation Priority

### Phase 1: Critical Prevention (Week 1)
1. **P0-1: Silent BigQuery writes** - 1 hour
2. **P0-2: Missing Docker dependencies** - 2 hours
3. **P1-2: Env var drift** - 1 hour

**Total:** 4 hours, prevents data loss and service outages

### Phase 2: Data Quality (Week 2)
4. **P0-3: Schema mismatches** - 3 hours
5. **P1-1: Partition filters** - 2 hours

**Total:** 5 hours, prevents write failures

### Phase 3: Nice to Have (Week 3)
6. **P1-4: Threshold calibration** - 1 hour
7. **P2-2: Timing lag monitor** - 30 minutes

**Total:** 1.5 hours, reduces false alarms

---

## Testing Strategy

### For Each New Validation Check:

1. **Create test scenario** that reproduces the original bug
2. **Run validation** - should detect the issue
3. **Fix the issue** - validation should pass
4. **Document** - Add to troubleshooting guide

### Integration Testing:

```bash
# Run full validation suite
/validate-daily

# Should now catch:
# - Deployment drift (Phase 0.1) ✅
# - Deactivation bugs (Phase 0.46) ✅
# - Edge filter issues (Phase 0.45) ✅
# + 9 more once implemented
```

---

## Metrics for Success

| Metric | Current | Target |
|--------|---------|--------|
| Validation checks in /validate-daily | 9 phases | 18 phases |
| P0 issues caught pre-production | 0 | 5 |
| Mean time to detect production issues | Hours | Minutes |
| False alarm rate | 30% (Session 80) | <5% |
| Services with post-deploy verification | 0 | 8 |

---

## Reference Material

**Analysis Source:** Explore agent analysis in Session 81
**Agent ID:** a9ee256 (can resume for more details)

**Session References:**
- Session 80: Grading service down, false alarms
- Session 78: Prediction deactivation bug
- Sessions 73-74: Partition filter issues
- Session 64: Backfill with stale code

**Related Documents:**
- `docs/02-operations/troubleshooting-matrix.md`
- `docs/09-handoff/` - All session handoffs
- `.pre-commit-hooks/` - Existing validation hooks

---

## Quick Start for Next Session

```bash
# 1. Read this document
cat docs/08-projects/current/validation-improvements/HANDOFF-SESSION-81.md

# 2. Start with Phase 1 (Critical Prevention)
# Implement P0-1: Silent BigQuery writes

# 3. Test it
./bin/monitoring/verify-bigquery-writes.sh nba-grading-service

# 4. Integrate into deploy script
# Add to ./bin/deploy-service.sh

# 5. Deploy and verify
./bin/deploy-service.sh nba-grading-service
```

---

## Questions for Next Session

1. Should we create a unified post-deployment test suite?
2. Should validation failures block deployments (CI/CD)?
3. Do we need a validation dashboard (vs just /validate-daily)?
4. Should we auto-create GitHub issues for validation failures?

---

**Status:** 2/11 complete, 9 remaining
**Estimated effort remaining:** 10.5 hours over 3 weeks
**Impact:** Prevent 5 critical bug classes from reaching production

**Next session:** Start with Phase 1 (Critical Prevention) - highest ROI

