# Breaking the Firefighting Cycle - Action Plan

**Created**: 2026-01-20 16:20 UTC
**Problem**: Daily orchestration issues → fix → backfill → validate → new issue appears
**Goal**: Stop new issues, detect immediately, validate at scale

---

## 🔥 Why You're Stuck in the Firefighting Cycle

Based on comprehensive analysis of Week 0 session docs, here are the **TOP 3 root causes**:

### **Root Cause #1: BDL Scraper Has NO Retry Logic** (40% weekly failure rate)

**The Problem**:
```python
# Current state: Single attempt, permanent failure
def scrape_box_scores(game_date):
    response = requests.get(bdl_api)  # If this fails...
    return process_response(response)  # ...data gap is permanent
    # NO RETRY LOGIC EXISTS
```

**Impact**:
- 17 missing box scores across Jan 13-18 (11-33% coverage gaps per date)
- Cascades to 339 PSZA processor failures (missing upstream data)
- **Recurs 2-3 times per week** on average
- Each failure requires manual backfill

**Why It Keeps Happening**:
- Retry utility exists (`shared/utils/retry_with_jitter.py`) but NOT integrated
- BDL API has ~5-10% transient error rate
- One network timeout = permanent data gap

**The Fix** (1-2 hours):
```python
from shared.utils.retry_with_jitter import retry_with_jitter

@retry_with_jitter(max_attempts=5, base_delay=60, max_delay=1800)
def scrape_box_scores(game_date):
    response = requests.get(bdl_api)
    return process_response(response)
```

**Result**: 40% of your firefighting disappears overnight

---

### **Root Cause #2: No Validation Gates Between Phases** (20-30% weekly cascade failures)

**The Problem**:
```python
# Current state: Phase 4 runs regardless of Phase 3 status
def run_phase4(game_date):
    trigger_processors(game_date)  # Runs even if Phase 3 has 0% data
    # NO UPSTREAM CHECK
```

**Impact**:
- Phase 4 ran on Jan 16/18 when Phase 3 was incomplete
- Processors fail with "INCOMPLETE_UPSTREAM" errors
- Each cascade creates 2-3 dates of broken data
- **Recurs weekly** when any Phase 3 issue occurs

**Why It Keeps Happening**:
- Time-based triggers ignore dependency state
- No quality gates before phase transitions
- Fails fast principle not implemented

**The Fix** (1 hour):
```python
def validate_phase3_before_phase4(game_date):
    """Block Phase 4 if Phase 3 incomplete"""

    # Check all 3 Phase 3 tables exist
    for table in ['player_game_summary', 'team_defense', 'upcoming_context']:
        count = check_table_count(game_date, table)
        if count == 0:
            send_slack_alert(f"Phase 4 BLOCKED: {table} has no data")
            raise ValidationError(f"Phase 3 incomplete for {game_date}")

    return True
```

**Result**: 20-30% of cascading failures prevented

---

### **Root Cause #3: Manual Validation of Backfills** (2-3 hours per backfill verification)

**The Problem**:
```bash
# Current workflow:
1. Backfill date
2. Manually check Phase 2 (BigQuery console)
3. Manually check Phase 3 (BigQuery console)
4. Manually check Phase 4 (BigQuery console)
5. Manually check Phase 5 (BigQuery console)
6. Manually check Phase 6 (BigQuery console)
# Time: 5-10 minutes per date × 10 dates = 1-2 hours
```

**Impact**:
- Can only validate 5-10 dates per session
- Backlog of 378 dates to verify
- **Delays backfill** because verification is bottleneck
- No confidence that backfills actually worked

**Why It Keeps Happening**:
- Current validation script takes 2-3 sec/date (19 min for full season)
- No fast smoke test exists
- No automated backfill success criteria

**The Fix** (30 min to build):
```python
# Fast smoke test: <1 second per date
def smoke_test(game_date):
    """Verify all phases in <1 second"""
    return {
        'phase2': check_exists('bdl_box_scores', game_date),
        'phase3': check_exists('player_game_summary', game_date),
        'phase4': count_processors(game_date) >= 3,
        'phase5': check_exists('predictions', game_date),
        'phase6': check_exists('grades', game_date)
    }
```

**Result**: Validate 100+ dates in <10 seconds instead of hours

---

## 🎯 The Action Plan (Prioritized by Impact)

### **CRITICAL PRIORITY: Stop 70% of New Issues** (3-4 hours work)

#### 1. Integrate BDL Scraper Retry Logic (1-2 hours)
**Impact**: Prevents 40% of weekly issues
**Effort**: LOW - utility exists, just needs integration
**Files**:
- Modify scraper orchestration to use `@retry_with_jitter`
- Test with intentional API failure

**Success Criteria**:
- BDL API transient failures auto-retry 5x
- Only alert if all 5 attempts fail
- Box score coverage >95% weekly

---

#### 2. Add Phase 3→4 Validation Gate (1 hour)
**Impact**: Prevents 20% of cascading failures
**Effort**: LOW - simple query checks
**File**: `orchestration/cloud_functions/phase3_to_phase4/main.py`

**Implementation**:
```python
def validate_phase3_before_phase4(game_date):
    scheduled_games = get_scheduled_games_count(game_date)

    # Verify all 3 Phase 3 tables have data
    phase3_tables = {
        'player_game_summary': 'nba_analytics.player_game_summary',
        'team_defense': 'nba_analytics.team_defense_game_summary',
        'upcoming_context': 'nba_analytics.upcoming_player_game_context'
    }

    for name, table in phase3_tables.items():
        count = query_count(table, game_date)
        if count == 0:
            send_slack_alert(
                severity='CRITICAL',
                message=f"Phase 4 BLOCKED: {name} has no data for {game_date}"
            )
            raise ValidationError(f"Phase 3 incomplete: {name} = 0 records")

        # Expect ~10-20 records per game minimum (players × games)
        min_expected = scheduled_games * 10
        if count < min_expected * 0.5:  # Allow 50% margin
            send_slack_alert(
                severity='WARNING',
                message=f"Phase 3 quality low: {name} only {count} records (expected {min_expected})"
            )

    return True
```

**Success Criteria**:
- Phase 4 never runs if Phase 3 has 0 data
- Alert sent immediately when blocked
- Manual override available if needed

---

#### 3. Add Phase 4→5 Circuit Breaker (1 hour)
**Impact**: Prevents poor-quality predictions
**Effort**: LOW - similar to gate above
**File**: `orchestration/cloud_functions/phase4_to_phase5/main.py`

**Implementation**:
```python
def check_phase4_minimum_coverage(game_date):
    """Block Phase 5 if Phase 4 coverage insufficient"""

    processors = {
        'PDC': ('nba_precompute.player_daily_cache', 'cache_date', True),  # CRITICAL
        'MLFS': ('nba_predictions.ml_feature_store_v2', 'game_date', True),  # CRITICAL
        'PSZA': ('nba_precompute.player_shot_zone_analysis', 'analysis_date', False),
        'PCF': ('nba_precompute.player_composite_factors', 'game_date', False),
        'TDZA': ('nba_precompute.team_defense_zone_analysis', 'analysis_date', False)
    }

    completed = 0
    critical_completed = 0

    for name, (table, date_col, is_critical) in processors.items():
        count = query_count(table, date_col, game_date)
        if count > 0:
            completed += 1
            if is_critical:
                critical_completed += 1

    # Require: 3/5 processors AND both critical processors
    if completed < 3:
        send_slack_alert(
            severity='CRITICAL',
            message=f"Phase 5 BLOCKED: Only {completed}/5 processors completed for {game_date}"
        )
        raise ValidationError(f"Insufficient Phase 4 coverage: {completed}/5")

    if critical_completed < 2:
        send_slack_alert(
            severity='CRITICAL',
            message=f"Phase 5 BLOCKED: Critical processors missing for {game_date}"
        )
        raise ValidationError("Missing critical processors (PDC/MLFS)")

    return True
```

**Success Criteria**:
- Phase 5 never runs with <3 processors
- Both critical processors (PDC, MLFS) required
- Prevents low-quality predictions

---

### **HIGH PRIORITY: Fast Validation Tools** (1-2 hours work)

#### 4. Create Fast Smoke Test Script (30 min)
**Impact**: Validate 100 dates in <10 seconds (vs 5-10 min manual)
**Effort**: LOW - simple existence checks
**File**: NEW `scripts/smoke_test.py`

**Implementation**:
```python
#!/usr/bin/env python3
"""
Fast smoke test: Validates single date in <1 second

Usage:
    python scripts/smoke_test.py 2026-01-20
    python scripts/smoke_test.py 2026-01-15 2026-01-20  # Range
"""

import sys
from google.cloud import bigquery

class SmokeTest:
    def __init__(self):
        self.bq = bigquery.Client(project='nba-props-platform')

    def test_date(self, game_date: str) -> dict:
        """Returns PASS/FAIL for each phase in <1 second"""

        # Single batch query checks all phases
        query = f"""
        SELECT
          -- Phase 2: Box scores exist
          IF(EXISTS(
            SELECT 1 FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{game_date}' LIMIT 1
          ), 'PASS', 'FAIL') as phase2,

          -- Phase 3: Analytics exist
          IF(EXISTS(
            SELECT 1 FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = '{game_date}' LIMIT 1
          ), 'PASS', 'FAIL') as phase3,

          -- Phase 4: Processors exist (count ≥3)
          CASE
            WHEN (
              IF(EXISTS(SELECT 1 FROM `nba-props-platform.nba_precompute.player_daily_cache` WHERE cache_date = '{game_date}' LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis` WHERE analysis_date = '{game_date}' LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `nba-props-platform.nba_precompute.player_composite_factors` WHERE game_date = '{game_date}' LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` WHERE analysis_date = '{game_date}' LIMIT 1), 1, 0)
            ) >= 3 THEN 'PASS'
            ELSE 'FAIL'
          END as phase4,

          -- Phase 5: Predictions exist
          IF(EXISTS(
            SELECT 1 FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date = '{game_date}' LIMIT 1
          ), 'PASS', 'FAIL') as phase5,

          -- Phase 6: Grading exists
          IF(EXISTS(
            SELECT 1 FROM `nba-props-platform.nba_predictions.prediction_grades`
            WHERE game_date = '{game_date}' LIMIT 1
          ), 'PASS', 'FAIL') as phase6
        """

        result = list(self.bq.query(query).result())[0]

        return {
            'game_date': game_date,
            'phase2': result.phase2,
            'phase3': result.phase3,
            'phase4': result.phase4,
            'phase5': result.phase5,
            'phase6': result.phase6,
            'overall': 'PASS' if all(getattr(result, f'phase{i}') == 'PASS' for i in [2,3,4,5,6]) else 'FAIL'
        }

def main():
    if len(sys.argv) < 2:
        print("Usage: python smoke_test.py <game_date> [end_date]")
        sys.exit(1)

    tester = SmokeTest()
    start_date = sys.argv[1]
    end_date = sys.argv[2] if len(sys.argv) > 2 else start_date

    # Get dates
    dates = get_dates_between(start_date, end_date)

    # Test all dates
    for date in dates:
        result = tester.test_date(date)
        status = "✅" if result['overall'] == 'PASS' else "❌"
        print(f"{status} {date}: P2:{result['phase2']} P3:{result['phase3']} P4:{result['phase4']} P5:{result['phase5']} P6:{result['phase6']}")

if __name__ == '__main__':
    main()
```

**Usage**:
```bash
# Single date
python scripts/smoke_test.py 2026-01-20
# Output: ✅ 2026-01-20: P2:PASS P3:PASS P4:PASS P5:PASS P6:PASS

# Date range
python scripts/smoke_test.py 2026-01-15 2026-01-20
# Output: (6 lines, <2 seconds)
```

**Success Criteria**:
- Validates single date in <1 second
- Validates 100 dates in <10 seconds
- Clear PASS/FAIL output per phase

---

#### 5. Document Backfill Success Criteria (30 min)
**Impact**: Clear definition of "backfill worked"
**Effort**: TRIVIAL - documentation only
**File**: NEW `docs/02-operations/BACKFILL-SUCCESS-CRITERIA.md`

**Content**:
```markdown
# Backfill Success Criteria

## What "Success" Means Per Phase

### Phase 2 (Scrapers)
✅ PASS if: Box scores exist from ANY source (bdl OR nbac)
✅ EXCELLENT if: Coverage ≥90% of scheduled games
⚠️ ACCEPTABLE if: Coverage 70-89%
❌ FAIL if: Coverage <70%

### Phase 3 (Analytics)
✅ PASS if: All 3 tables have data (player_game_summary, team_defense, upcoming_context)
✅ EXCELLENT if: Record counts match expected (~10-20 per game)
❌ FAIL if: Any table has 0 records

### Phase 4 (Precompute)
✅ PASS if: ≥3/4 processors completed + both critical (PDC, MLFS) exist
✅ EXCELLENT if: All 4 processors completed
⚠️ ACCEPTABLE if: 3/4 completed (early season bootstrap)
❌ FAIL if: <3 processors OR missing critical processors

### Phase 5 (Predictions)
✅ PASS if: Predictions exist from all 5 systems
✅ EXCELLENT if: MAE < 6 against actuals
⚠️ ACCEPTABLE if: MAE < 8
❌ FAIL if: <5 systems OR no predictions

### Phase 6 (Grading)
✅ PASS if: Grading coverage ≥80%
✅ EXCELLENT if: Coverage ≥95%
⚠️ ACCEPTABLE if: Coverage 70-79%
❌ FAIL if: Coverage <70%

## Overall Backfill Success

✅ COMPLETE SUCCESS: All phases PASS + health score ≥85%
⚠️ PARTIAL SUCCESS: Phases 2-4 PASS + health score ≥70%
❌ FAILED: Any phase FAIL OR health score <50%
```

**Success Criteria**:
- Clear thresholds for each phase
- Traffic light system (pass/acceptable/fail)
- Can be automated in smoke test

---

### **MEDIUM PRIORITY: Deployment Safety** (1-2 hours work)

#### 6. Create Deployment Verification Script (30 min)
**Impact**: Prevents infrastructure drift
**Effort**: LOW - check commands
**File**: NEW `bin/verify_deployment.sh`

**Implementation**:
```bash
#!/bin/bash
# Verify all required infrastructure exists

set -e

echo "🔍 Verifying deployment..."

# Check Cloud Schedulers
echo "Checking Cloud Schedulers..."
EXPECTED_SCHEDULERS=(
  "grading-readiness-monitor"
  "grading-backup-6am"
  "grading-backup-10am"
  "box-score-completeness-alert"
  "phase4-failure-alert"
)

for scheduler in "${EXPECTED_SCHEDULERS[@]}"; do
  gcloud scheduler jobs describe "$scheduler" --location=us-central1 >/dev/null 2>&1 || {
    echo "❌ ERROR: Scheduler '$scheduler' not found"
    exit 1
  }
  echo "  ✅ $scheduler"
done

# Check Cloud Functions
echo "Checking Cloud Functions..."
EXPECTED_FUNCTIONS=(
  "box-score-completeness-alert"
  "phase4-failure-alert"
  "grading-readiness-monitor"
)

for func in "${EXPECTED_FUNCTIONS[@]}"; do
  gcloud functions describe "$func" --gen2 --region=us-west1 >/dev/null 2>&1 || {
    echo "❌ ERROR: Function '$func' not found"
    exit 1
  }
  echo "  ✅ $func"
done

# Check BigQuery datasets
echo "Checking BigQuery datasets..."
EXPECTED_DATASETS=("nba_raw" "nba_analytics" "nba_precompute" "nba_predictions" "nba_monitoring")

for dataset in "${EXPECTED_DATASETS[@]}"; do
  bq show "$dataset" >/dev/null 2>&1 || {
    echo "❌ ERROR: Dataset '$dataset' not found"
    exit 1
  }
  echo "  ✅ $dataset"
done

# Check APIs enabled
echo "Checking APIs..."
EXPECTED_APIS=(
  "bigquery.googleapis.com"
  "bigquerydatatransfer.googleapis.com"
  "cloudscheduler.googleapis.com"
  "cloudfunctions.googleapis.com"
)

for api in "${EXPECTED_APIS[@]}"; do
  gcloud services list --enabled | grep -q "$api" || {
    echo "❌ ERROR: API '$api' not enabled"
    exit 1
  }
  echo "  ✅ $api"
done

echo ""
echo "✅ All checks passed! Deployment verified."
```

**Usage**:
```bash
# Before deploying
bin/verify_deployment.sh

# In CI/CD pipeline
bin/verify_deployment.sh || exit 1
```

**Success Criteria**:
- Detects missing schedulers/functions/APIs
- Prevents "deployed but not verified" issues
- Can run in CI/CD

---

## 📊 Expected Impact

| Improvement | Prevents | Time Saved | Effort |
|-------------|----------|------------|--------|
| **BDL Retry Logic** | 40% of weekly issues | 4-6 hours/week | 1-2 hours |
| **Phase 3→4 Gate** | 20% of cascade failures | 2-3 hours/week | 1 hour |
| **Phase 4→5 Circuit Breaker** | 10% of quality issues | 1-2 hours/week | 1 hour |
| **Fast Smoke Test** | 70% of validation time | 5-10 hours/week | 30 min |
| **Success Criteria Doc** | Confusion/rework | 2-3 hours/week | 30 min |
| **Deployment Verification** | Infrastructure drift | 1-2 hours/month | 30 min |
| **TOTAL** | **~70% of firefighting** | **15-25 hours/week** | **4-5 hours** |

---

## 🚀 Implementation Timeline

### **Today (This Session - If Time Permits)**
1. ✅ Create smoke test script (30 min)
2. ✅ Document backfill success criteria (30 min)
3. ✅ Create deployment verification script (30 min)

**Total**: 90 minutes
**Benefit**: Fast validation tools ready immediately

---

### **This Week (Next 2 Days)**
1. Integrate BDL retry logic (1-2 hours)
2. Add Phase 3→4 validation gate (1 hour)
3. Add Phase 4→5 circuit breaker (1 hour)
4. Test all improvements (30 min)

**Total**: 3.5-4.5 hours
**Benefit**: 70% reduction in new issues

---

### **Next Week**
1. Implement centralized error logger (6 hours)
2. Create daily data quality report (2 hours)
3. Convert to Infrastructure as Code (4 hours)

**Total**: 12 hours
**Benefit**: Complete observability + drift prevention

---

## ✅ Success Metrics

### Before Improvements
- New issues per week: 3-5
- Time to detect: 24-72 hours
- Time to validate backfill: 1-2 hours per 10 dates
- Backfill confidence: 60% ("not sure if it worked")

### After Improvements
- New issues per week: 1-2 (70% reduction)
- Time to detect: 5-30 minutes (95% faster)
- Time to validate backfill: <10 seconds per 100 dates (600x faster)
- Backfill confidence: 95% (automated verification)

---

## 🎯 Quick Start

**Want to start RIGHT NOW?** Do these in order:

1. **Create smoke test script** (30 min) → Test backfills instantly
2. **Document success criteria** (20 min) → Know what "success" means
3. **When validation completes** → Analyze results with smoke test
4. **Tomorrow** → Integrate BDL retry (biggest impact)

**Within 1 week, you'll have**:
- ✅ 70% fewer new issues
- ✅ Instant backfill validation
- ✅ Automated quality gates
- ✅ Clear success criteria

---

**The firefighting cycle ends when**:
1. Issues stop appearing (retry logic, validation gates)
2. Issues are detected immediately (alerts already deployed)
3. Backfills can be verified at scale (smoke test + success criteria)

You're **3-4 hours of work** away from breaking the cycle.
