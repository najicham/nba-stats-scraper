# Shot Zone Data Quality Investigation and Fix Plan

**Date:** 2026-01-30
**Session:** 38
**Status:** Investigation Complete, Implementation Plan Ready

---

## Executive Summary

The CatBoost V8 model collapsed from 77% to 34% hit rate primarily due to **shot zone feature corruption**. The investigation revealed:

1. **Root Cause**: `paint_attempts` and `mid_range_attempts` are NULL for many days in `player_game_summary`, while `three_pt_attempts` is always populated
2. **Impact**: When paint=NULL but three=populated, rate calculations become corrupted (three_pt_rate artificially inflates to 60-70%)
3. **Timeline**: Data quality issues started Dec 22, 2025 and persisted through January 2026
4. **Missing Detection**: No monitoring exists for feature distribution shifts or domain-specific bounds

---

## Root Cause Analysis

### The Data Flow Problem

```
BigDataBall/NBAC Play-by-Play (intermittent)
           ↓
player_game_summary (paint_attempts=NULL on many days)
           ↓
player_shot_zone_analysis (corrupted rates: 20% paint, 70% three)
           ↓
player_daily_cache (passes through corrupted values)
           ↓
ml_feature_store_v2 (out-of-distribution features)
           ↓
CatBoost V8 (predictions based on invalid features)
```

### Evidence from BigQuery

**player_game_summary shot zone fields:**
| Date Range | paint_attempts | three_pt_attempts | Status |
|------------|----------------|-------------------|--------|
| Dec 15-21 | **Populated** | Populated | OK |
| Dec 22-30 | **NULL** | Populated | CORRUPTED |
| Jan 1-8 | **Intermittent** | Populated | PARTIALLY CORRUPTED |
| Jan 9-23 | **NULL** | Populated | CORRUPTED |
| Jan 24+ | **Intermittent** | Populated | PARTIALLY CORRUPTED |

**Impact on shot zone rates:**
| Period | avg_paint_rate | avg_three_rate | Expected |
|--------|----------------|----------------|----------|
| Dec 1-15 | 40-50% | 30-40% | Normal NBA |
| Dec 22+ | 20-25% | 60-70% | CORRUPTED |

### Why This Happened

1. **BigDataBall data source disabled** (Jan 28 commit d503c5c0) due to quality issues
2. **NBAC play-by-play has gaps** for many dates (Jan 1, 3, 9, 12-19, 24)
3. **Shot zone extraction fails silently** when play-by-play unavailable
4. **Rate calculation doesn't handle partial data** - divides by only populated fields
5. **No validation** of domain-specific bounds (paint should be 30-50%)

---

## Affected Files

### Data Processors (Source of Problem)

| File | Issue | Lines |
|------|-------|-------|
| `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py` | Fails silently when PBP unavailable | 47-86 |
| `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` | No bounds validation | 99-143 |
| `data_processors/precompute/player_daily_cache/worker.py` | Silently uses NULL values | 134-148 |

### Validation (Missing Checks)

| File | Missing Check |
|------|---------------|
| `validation/validators/precompute/player_shot_zone_validator.py` | Domain-specific bounds (paint 30-50%) |
| `shared/validation/feature_drift_detector.py` | Not scheduled, no Slack alerts |
| `scripts/validate_tonight_data.py` | No feature distribution checks |

### Monitoring (Gaps)

| Gap | Impact |
|-----|--------|
| No feature drift alerts | Month-long shift undetected |
| No zero-value detection | Jan 23, 29 all-zeros undetected |
| No domain bounds alerts | 20% paint rate not flagged |

---

## Fix Plan

### Phase 1: Immediate Fixes (Today)

#### 1.1 Add Domain Bounds Validation to Shot Zone Validator

**File:** `validation/validators/precompute/player_shot_zone_validator.py`

```python
def _validate_domain_specific_ranges(self, start_date: str, end_date: str) -> ValidationResult:
    """Validate shot zone percentages match basketball expectations."""
    query = f"""
    SELECT
        analysis_date,
        player_lookup,
        paint_rate_last_10,
        mid_range_rate_last_10,
        three_pt_rate_last_10,
        CASE
            WHEN paint_rate_last_10 < 20 OR paint_rate_last_10 > 60 THEN 'paint_out_of_bounds'
            WHEN mid_range_rate_last_10 < 5 OR mid_range_rate_last_10 > 35 THEN 'mid_out_of_bounds'
            WHEN three_pt_rate_last_10 < 15 OR three_pt_rate_last_10 > 55 THEN 'three_out_of_bounds'
        END as violation
    FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
    WHERE analysis_date >= '{start_date}' AND analysis_date <= '{end_date}'
      AND (
        paint_rate_last_10 < 20 OR paint_rate_last_10 > 60 OR
        mid_range_rate_last_10 < 5 OR mid_range_rate_last_10 > 35 OR
        three_pt_rate_last_10 < 15 OR three_pt_rate_last_10 > 55
      )
    """
    # Return ValidationResult with severity based on count
```

#### 1.2 Add Feature Distribution Check to Daily Validation

**File:** `scripts/validate_tonight_data.py`

Add after line ~400:
```python
def check_feature_distributions(self) -> bool:
    """Check ML feature distributions haven't drifted."""
    query = """
    SELECT
        AVG(features[SAFE_OFFSET(18)]) as avg_paint,
        AVG(features[SAFE_OFFSET(20)]) as avg_three
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = CURRENT_DATE()
    """
    result = self.client.query(query).result()
    row = list(result)[0]

    # Alert if paint < 0.25 or three > 0.55
    if row.avg_paint < 0.25:
        self.add_issue('feature_drift', f'Paint rate too low: {row.avg_paint:.1%}')
    if row.avg_three > 0.55:
        self.add_issue('feature_drift', f'Three-pt rate too high: {row.avg_three:.1%}')
```

#### 1.3 Add Zero-Value Detection

**File:** `validation/validators/precompute/ml_feature_store_validator.py`

```python
def _validate_no_all_zeros(self, start_date: str, end_date: str) -> ValidationResult:
    """Detect records where shot zone features are all zeros."""
    query = f"""
    SELECT game_date, COUNT(*) as zero_count
    FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
      AND features[SAFE_OFFSET(18)] = 0
      AND features[SAFE_OFFSET(19)] = 0
      AND features[SAFE_OFFSET(20)] = 0
    GROUP BY game_date
    HAVING zero_count > 10
    """
```

### Phase 2: Monitoring Integration (This Week)

#### 2.1 Create GitHub Workflow for Feature Drift Detection

**File:** `.github/workflows/feature-drift-monitor.yml`

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
      - name: Run feature drift detector
        run: |
          python -m shared.validation.feature_drift_detector \
            --days 7 \
            --threshold 0.15 \
            --slack-alert
```

#### 2.2 Add Slack Alerting to Feature Drift Detector

**File:** `shared/validation/feature_drift_detector.py`

Add Slack webhook integration for critical drift alerts.

#### 2.3 Integrate into /validate-daily Skill

**File:** `.claude/skills/validate-daily/SKILL.md`

Add feature distribution check to daily validation checklist.

### Phase 3: Data Quality Improvements (Next Week)

#### 3.1 Fix Shot Zone Extraction Fallback

**File:** `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`

```python
def get_shot_zone_data(self, game_id: str, player_lookup: str) -> Dict:
    """Extract shot zones with proper fallback and validation."""
    # Try BigDataBall first
    result = self._extract_from_bigdataball(game_id, player_lookup)

    # If partial data (e.g., only three_pt populated), try NBAC
    if result and not self._is_complete(result):
        nbac_result = self._extract_from_nbac(game_id, player_lookup)
        result = self._merge_results(result, nbac_result)

    # Validate domain bounds before returning
    if result and not self._validate_bounds(result):
        logger.warning(f"Shot zone bounds violated for {player_lookup}: {result}")
        return None  # Return None instead of corrupted data

    return result
```

#### 3.2 Add Rate Calculation Validation

**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

```python
def _calculate_zone_metrics_static(games_df: pd.DataFrame) -> dict:
    # Existing calculation...

    # ADD: Validate all three zone attempts are populated
    if paint_att is None or mid_att is None or three_att is None:
        logger.warning("Incomplete shot zone data - skipping rate calculation")
        return {'paint_rate': None, 'mid_rate': None, 'three_rate': None}

    # ADD: Validate rates sum to ~100%
    total_rate = paint_rate + mid_rate + three_rate
    if abs(total_rate - 100) > 2:
        logger.error(f"Shot zone rates don't sum to 100%: {total_rate}")
        return {'paint_rate': None, 'mid_rate': None, 'three_rate': None}
```

### Phase 4: Long-term Resilience (Next Sprint)

#### 4.1 Create Feature Quality Dashboard

- Track feature statistics over time
- Visualize distribution shifts
- Alert on anomalies

#### 4.2 Add Baseline Tracking

Store expected feature ranges and alert when current values deviate:

```sql
CREATE TABLE nba_orchestration.feature_baselines (
  feature_name STRING,
  expected_min FLOAT64,
  expected_max FLOAT64,
  expected_mean FLOAT64,
  expected_std FLOAT64,
  last_updated TIMESTAMP
)
```

#### 4.3 Implement Circuit Breaker for Feature Store

If feature quality drops below threshold, pause predictions rather than produce bad ones.

---

## Validation Checks to Add

### To `/validate-daily` Skill

| Check | Query | Threshold | Severity |
|-------|-------|-----------|----------|
| Paint rate bounds | AVG(features[18]) | 0.25-0.55 | WARNING |
| Three-pt rate bounds | AVG(features[20]) | 0.20-0.50 | WARNING |
| All-zeros count | COUNT(*) WHERE features[18:20]=0 | >10 | CRITICAL |
| Feature drift | Week-over-week mean change | >15% | WARNING |

### To Shot Zone Validator

| Check | Expected Range | Severity if Violated |
|-------|----------------|---------------------|
| paint_rate_last_10 | 20-60% | WARNING |
| mid_range_rate_last_10 | 5-35% | WARNING |
| three_pt_rate_last_10 | 15-55% | WARNING |
| Rate sum | 98-102% | ERROR |

### To Feature Store Validator

| Check | Threshold | Severity |
|-------|-----------|----------|
| NULL count per feature | >5% | WARNING |
| Zero count for shot zones | >10 records | CRITICAL |
| Feature array length | Must be 33 or 37 | ERROR |

---

## Implementation Priority

| Task | Priority | Effort | Impact |
|------|----------|--------|--------|
| Add domain bounds to shot zone validator | P0 | 2h | Catches future issues |
| Add zero-value detection | P0 | 1h | Catches complete failures |
| Add feature check to daily validation | P0 | 2h | Daily monitoring |
| Create feature drift GitHub workflow | P1 | 3h | Automated alerting |
| Fix shot zone extraction fallback | P1 | 4h | Prevents data corruption |
| Add rate calculation validation | P1 | 2h | Catches partial data |
| Create feature quality dashboard | P2 | 8h | Visualization |
| Implement circuit breaker | P2 | 4h | Prevents bad predictions |

---

## Success Criteria

1. **Detection**: Feature drift alerts fire within 24 hours of shift
2. **Prevention**: Domain bounds validation catches invalid rates before they reach model
3. **Visibility**: Daily validation reports feature distribution statistics
4. **Resilience**: Circuit breaker pauses predictions when feature quality degrades

---

## Related Documents

- `docs/09-handoff/2026-01-30-SESSION-37-COMPLETE-HANDOFF.md` - V8 investigation
- `docs/08-projects/current/v8-model-investigation/ROOT-CAUSE-ANALYSIS-JAN-7-9.md` - Model collapse analysis
- `validation/validators/precompute/player_shot_zone_validator.py` - Existing validator
- `shared/validation/feature_drift_detector.py` - Drift detection tool
