# Session 38 Handoff - Shot Zone Data Quality Investigation

**Date:** 2026-01-30
**Duration:** ~2 hours
**Status:** Investigation Complete, Validation Fixes Deployed, Upstream Fixes Pending

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-01-30-SESSION-38-SHOT-ZONE-INVESTIGATION-HANDOFF.md

# 2. Study the system using agents (IMPORTANT - use these commands)
# Agent 1: Understand the shot zone data flow
Task(subagent_type="Explore", prompt="Trace the complete data flow for shot zone features from raw play-by-play data to ML feature store. Find: 1) Where paint_attempts comes from 2) Why it's NULL on many days 3) The fallback logic when BigDataBall is unavailable")

# Agent 2: Understand the validation framework
Task(subagent_type="Explore", prompt="Study the validation framework in validation/ directory. Find: 1) How validators are structured 2) How to integrate new checks into /validate-daily 3) Where feature drift detection should be scheduled")

# Agent 3: Understand the prediction pipeline
Task(subagent_type="Explore", prompt="Study how CatBoost V8 uses features. Find: 1) Which features it expects 2) How it handles NULL/zero values 3) Where confidence is calculated")

# 3. Run the new validators to see current state
python validation/validators/precompute/player_shot_zone_validator.py --days 14
python validation/validators/precompute/ml_feature_store_validator.py --days 14

# 4. Check the investigation plan
cat docs/08-projects/current/shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md
```

---

## Executive Summary

### The Problem
The CatBoost V8 model hit rate collapsed from **77% (Dec 21) to 34% (Jan 25)** - a 43 percentage point drop.

### Root Cause
**Shot zone feature corruption** caused by upstream data quality issues:
- `paint_attempts` was NULL in `player_game_summary` for many days
- When paint=NULL but three_pt populated, rate calculations became corrupted
- Paint rate dropped from 41% → 21% (should be 30-50%)
- Three-pt rate spiked from 34% → 70% (should be 20-50%)

### What We Fixed
- Added domain-specific validation to catch out-of-range shot zone values
- Added zero-value detection to catch complete data failures
- Added distribution drift detection to catch gradual shifts
- Created validator configs and investigation documentation

### What Still Needs Fixing
1. **Upstream data extraction** - Fix why `paint_attempts` is NULL
2. **Validation integration** - Add new checks to `/validate-daily`
3. **Automated alerting** - Create GitHub workflow for drift detection
4. **Fallback logic** - Improve shot zone extraction when BigDataBall unavailable

---

## Investigation Findings

### 1. The Data Corruption Timeline

```
Dec 15-21:  paint_rate = 40-50%, three_rate = 30-40%  ← NORMAL
Dec 22-30:  paint_attempts = NULL in player_game_summary  ← CORRUPTION STARTS
Jan 1-23:   paint_rate dropping, three_rate rising  ← MODEL DEGRADING
Jan 23:     ALL ZEROS in feature store (complete data failure)
Jan 24+:    paint_rate = 20%, three_rate = 70%  ← FULLY CORRUPTED
```

### 2. Evidence from BigQuery

**player_game_summary shot zone fields (the source):**
```sql
-- Many days have NULL paint_attempts but populated three_pt_attempts
SELECT game_date,
       COUNTIF(paint_attempts IS NULL) as null_paint,
       COUNTIF(three_pt_attempts IS NULL) as null_three
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01' AND minutes_played > 0
GROUP BY 1 ORDER BY 1;

-- Result: Jan 9, 12-23 have nearly ALL paint_attempts = NULL
```

**Feature store shot zone values (the symptom):**
```sql
-- Paint rate crashed, three-pt rate spiked
SELECT DATE_TRUNC(game_date, WEEK) as week,
       ROUND(AVG(features[SAFE_OFFSET(18)]), 3) as avg_paint,
       ROUND(AVG(features[SAFE_OFFSET(20)]), 3) as avg_three
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-12-01'
GROUP BY 1 ORDER BY 1 DESC;

-- Result:
-- Dec 7:  paint=0.497, three=0.138  ← NORMAL
-- Jan 25: paint=0.181, three=0.480  ← CORRUPTED (inverted!)
```

### 3. Why This Happened

The data flow has multiple failure points:

```
BigDataBall Play-by-Play (PRIMARY)
    ↓ (FAILED: BDB disabled Jan 28, gaps before)
NBAC Play-by-Play (FALLBACK)
    ↓ (FAILED: Missing data for Jan 1, 3, 9, 12-19, 24)
player_game_summary (Phase 3)
    ↓ (RESULT: paint_attempts = NULL, three_pt_attempts = populated)
player_shot_zone_analysis (Phase 4)
    ↓ (RESULT: Corrupted rates - three_rate = three / (0 + 0 + three) = 100%)
player_daily_cache (Phase 4)
    ↓ (RESULT: Passes through corrupted values)
ml_feature_store_v2 (Phase 4)
    ↓ (RESULT: Out-of-distribution features)
CatBoost V8 predictions
    ↓ (RESULT: Model failures - 34% hit rate)
```

### 4. Impact on Model Performance

| Week | Hit Rate | Paint Rate | Three Rate | Status |
|------|----------|------------|------------|--------|
| Dec 21 | **77%** | 0.34 | 0.40 | Normal |
| Dec 28 | 67% | 0.33 | 0.41 | Degrading |
| Jan 4 | 60% | 0.30 | 0.49 | Degrading |
| Jan 11 | 49% | 0.27 | 0.55 | Failing |
| Jan 18 | 39% | 0.18 | 0.42 | Failed |
| Jan 25 | **34%** | 0.18 | 0.48 | Failed |

---

## Fixes Implemented (Session 38)

### 1. Domain-Specific Range Validation

**File:** `validation/validators/precompute/player_shot_zone_validator.py`

Added `_validate_domain_specific_ranges()` method that checks:
- Paint rate: 15-65% (catches the 20% anomaly)
- Mid-range rate: 3-40%
- Three-pt rate: 10-60% (catches the 70% anomaly)

**Severity escalation:**
- \>50 violations = CRITICAL
- 10-50 violations = WARNING
- <10 = INFO (normal edge cases)

### 2. Zero-Value Detection

**File:** `validation/validators/precompute/ml_feature_store_validator.py`

Added `_validate_no_shot_zone_zeros()` method that:
- Detects days where features[18], [19], [20] are all 0
- Catches Jan 23 and Jan 29 complete data failures
- CRITICAL severity if >50% of records affected

### 3. Distribution Drift Detection

**File:** `validation/validators/precompute/ml_feature_store_validator.py`

Added `_validate_shot_zone_distribution()` method that:
- Checks daily averages against expected ranges
- Paint avg: 0.25-0.50 expected
- Three avg: 0.25-0.50 expected
- CRITICAL if >5 days have drift

### 4. Validator Configs

**Files:**
- `validation/configs/precompute/player_shot_zone_analysis.yaml`
- `validation/configs/precompute/ml_feature_store.yaml`

### 5. Documentation

**File:** `docs/08-projects/current/shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md`

Contains complete investigation findings and fix plan.

---

## What Still Needs To Be Done

### Priority 1: Fix Upstream Data Extraction (CRITICAL)

**Problem:** `paint_attempts` is NULL because play-by-play data is missing.

**Files to fix:**
1. `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`
   - Lines 47-86: Fallback logic when BigDataBall unavailable
   - Need to improve NBAC fallback to extract paint/mid-range attempts

2. `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
   - Line 914: `extract_shot_zones` call
   - Need to add validation that all three zone attempts are populated

**Fix approach:**
```python
# In shot_zone_analyzer.py
def get_shot_zone_data(self, game_id: str, player_lookup: str) -> Dict:
    result = self._extract_from_bigdataball(game_id, player_lookup)

    # If partial data, try fallback
    if result and not self._is_complete(result):
        nbac_result = self._extract_from_nbac(game_id, player_lookup)
        result = self._merge_results(result, nbac_result)

    # Validate before returning
    if result and not self._validate_bounds(result):
        logger.warning(f"Shot zone bounds violated: {result}")
        return None  # Don't return corrupted data

    return result
```

### Priority 2: Integrate Validation into Daily Flow

**Problem:** New validation checks exist but aren't run automatically.

**Files to modify:**
1. `.claude/skills/validate-daily/SKILL.md`
   - Add shot zone validation to daily checklist
   - Add feature distribution check

2. `scripts/validate_tonight_data.py`
   - Import and call new validators
   - Add feature drift check

**Fix approach:**
```python
# In validate_tonight_data.py
def check_feature_distributions(self) -> bool:
    """Check ML feature distributions haven't drifted."""
    from validation.validators.precompute.ml_feature_store_validator import MLFeatureStoreValidator

    validator = MLFeatureStoreValidator(
        config_path='validation/configs/precompute/ml_feature_store.yaml'
    )
    results = validator.validate(self.target_date, self.target_date)

    # Check for critical failures
    critical_failures = [r for r in results if r.severity == 'critical' and not r.passed]
    if critical_failures:
        for f in critical_failures:
            self.add_issue('feature_quality', f.message, severity='ERROR')
        return False
    return True
```

### Priority 3: Create Automated Alerting

**Problem:** Feature drift went undetected for a month.

**File to create:** `.github/workflows/feature-drift-monitor.yml`

```yaml
name: Feature Drift Monitor
on:
  schedule:
    - cron: '0 14 * * *'  # 2 PM UTC daily
  workflow_dispatch:

jobs:
  check-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run feature drift detector
        env:
          GOOGLE_APPLICATION_CREDENTIALS: ${{ secrets.GCP_SA_KEY }}
        run: |
          python -m shared.validation.feature_drift_detector \
            --days 7 \
            --threshold 0.15 \
            --slack-webhook ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Priority 4: Add Rate Calculation Validation

**Problem:** Rate calculations don't validate that all zone attempts are populated.

**File to fix:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

```python
# Lines 99-143: Add validation
def _calculate_zone_metrics_static(games_df: pd.DataFrame) -> dict:
    paint_att = games_df['paint_attempts'].sum()
    mid_att = games_df['mid_range_attempts'].sum()
    three_att = games_df['three_pt_attempts'].sum()

    # ADD: Validate all zones have data
    if pd.isna(paint_att) or pd.isna(mid_att) or pd.isna(three_att):
        logger.warning("Incomplete shot zone data - one or more zones NULL")
        return {'paint_rate': None, 'mid_rate': None, 'three_rate': None}

    total_att = paint_att + mid_att + three_att
    if total_att == 0:
        return {'paint_rate': None, 'mid_rate': None, 'three_rate': None}

    paint_rate = (paint_att / total_att * 100)
    mid_rate = (mid_att / total_att * 100)
    three_rate = (three_att / total_att * 100)

    # ADD: Validate rates sum to ~100%
    total_rate = paint_rate + mid_rate + three_rate
    if abs(total_rate - 100) > 2:
        logger.error(f"Shot zone rates don't sum to 100%: {total_rate}")
        return {'paint_rate': None, 'mid_rate': None, 'three_rate': None}

    return {'paint_rate': paint_rate, 'mid_rate': mid_rate, 'three_rate': three_rate}
```

---

## Key Files Reference

### Investigation & Documentation
| File | Purpose |
|------|---------|
| `docs/08-projects/current/shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md` | Complete investigation findings |
| `docs/09-handoff/2026-01-30-SESSION-37-COMPLETE-HANDOFF.md` | Previous session context |

### Validation (Modified in Session 38)
| File | Changes |
|------|---------|
| `validation/validators/precompute/player_shot_zone_validator.py` | Added domain bounds check |
| `validation/validators/precompute/ml_feature_store_validator.py` | Added zero detection, drift check |
| `validation/configs/precompute/player_shot_zone_analysis.yaml` | NEW - validator config |
| `validation/configs/precompute/ml_feature_store.yaml` | NEW - validator config |

### Data Pipeline (Need Fixes)
| File | Issue |
|------|-------|
| `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py` | Fallback logic needs improvement |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | No validation of shot zone data |
| `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` | Rate calculation doesn't validate completeness |

### Prediction Pipeline (Reference)
| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Model that uses features |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature store generation |

---

## Queries for Monitoring

### Check Current Shot Zone Health
```sql
-- Daily shot zone feature averages
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(AVG(features[SAFE_OFFSET(18)]), 3) as avg_paint,
  ROUND(AVG(features[SAFE_OFFSET(20)]), 3) as avg_three,
  COUNTIF(features[SAFE_OFFSET(18)] = 0 AND features[SAFE_OFFSET(20)] = 0) as zeros
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1 ORDER BY 1 DESC;
```

### Check Upstream Data Quality
```sql
-- player_game_summary shot zone completeness
SELECT
  game_date,
  COUNT(*) as records,
  COUNTIF(paint_attempts IS NULL) as null_paint,
  COUNTIF(three_pt_attempts IS NULL) as null_three
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND minutes_played > 0
GROUP BY 1 ORDER BY 1 DESC;
```

### Check Model Performance
```sql
-- Weekly hit rate with shot zone correlation
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
GROUP BY 1 ORDER BY 1 DESC;
```

---

## Commands to Run Validators

```bash
# Run shot zone validator (should show CRITICAL for domain violations)
python validation/validators/precompute/player_shot_zone_validator.py \
  --start-date 2026-01-15 --end-date 2026-01-30

# Run ML feature store validator (should show CRITICAL for zeros and drift)
python validation/validators/precompute/ml_feature_store_validator.py \
  --start-date 2026-01-15 --end-date 2026-01-30
```

---

## Commits from Session 38

```
58e04b49 feat: Add domain-specific shot zone validation and zero-detection
```

---

## Recommended Approach for Next Session

### Step 1: Study the System (Use Agents)

Spawn these three agents in parallel to understand the system:

```python
# Agent 1: Data flow
Task(subagent_type="Explore", prompt="""
Trace the shot zone data flow from raw to predictions:
1. Find scrapers/bigdataball/ and scrapers/nbac/ - how is play-by-play scraped?
2. Find data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py
3. Find data_processors/precompute/player_shot_zone_analysis/
4. Report: Where does paint_attempts come from? Why would it be NULL?
""")

# Agent 2: Validation framework
Task(subagent_type="Explore", prompt="""
Study the validation framework:
1. Read validation/base_validator.py - how do validators work?
2. Read .claude/skills/validate-daily/SKILL.md - what does daily validation do?
3. Read scripts/validate_tonight_data.py - main validation entry point
4. Report: How to add new checks to daily validation flow?
""")

# Agent 3: BigDataBall status
Task(subagent_type="Explore", prompt="""
Investigate BigDataBall data source:
1. Find why BDB was disabled (look for commit d503c5c0)
2. Check nba_raw.bigdataball_play_by_play for recent data
3. Check bin/monitoring/bdb_pbp_monitor.py
4. Report: Is BDB data available? What's the fallback?
""")
```

### Step 2: Fix Priority 1 - Upstream Data

Focus on `shot_zone_analyzer.py` to improve fallback logic.

### Step 3: Fix Priority 2 - Daily Validation Integration

Modify `/validate-daily` skill to include new checks.

### Step 4: Test and Deploy

Run validators, verify fixes work, deploy changes.

---

## Key Learnings from Session 38

1. **Silent data corruption is worse than failures** - The system kept running with corrupted data for a month
2. **Domain knowledge matters** - Generic validation (0-100%) passed; basketball-specific validation (30-50%) would have caught it
3. **Validation exists but isn't integrated** - Feature drift detector was available but not scheduled
4. **Upstream fixes need downstream validation** - Even if we fix data extraction, we need validation to catch future issues
5. **Multiple data sources need careful fallback** - BDB→NBAC fallback wasn't producing complete data

---

## Contact Points

- Previous session: `docs/09-handoff/2026-01-30-SESSION-37-COMPLETE-HANDOFF.md`
- Investigation plan: `docs/08-projects/current/shot-zone-data-quality/INVESTIGATION-AND-FIX-PLAN.md`
- Operations runbook: `docs/02-operations/daily-operations-runbook.md`

---

*Session 38 complete. Shot zone data corruption identified as root cause of V8 model collapse. Validation fixes deployed. Upstream data fixes and automation still needed.*
