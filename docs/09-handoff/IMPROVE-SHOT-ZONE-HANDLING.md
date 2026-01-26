# Improve Shot Zone Data Handling

**Type:** Enhancement
**Priority:** Medium
**Estimated Effort:** 3-4 hours
**Model:** Sonnet recommended

---

## Context

Shot zone data comes from play-by-play scrapers (BigDataBall primary, NBAC fallback). When this data is missing, the ML feature store currently fills in **league averages** (30% paint, 20% mid-range, 35% three-point).

**Problems with current approach:**
1. Model can't distinguish "average shooter" from "data missing"
2. Hides data quality issues from ML predictions
3. No automated fallback from BigDataBall to NBAC PBP
4. Limited visibility into shot zone completeness

---

## Tasks

### Task 1: Add Missingness Indicator to Feature Store

**Goal:** Let the model know when shot zone data is missing instead of hiding it with averages.

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Current code (lines ~1178-1181):**
```python
features.append(self._get_feature_with_fallback(18, 'paint_rate_last_10', phase4_data, phase3_data, 30.0, feature_sources) / 100.0)
features.append(self._get_feature_with_fallback(19, 'mid_range_rate_last_10', phase4_data, phase3_data, 20.0, feature_sources) / 100.0)
features.append(self._get_feature_with_fallback(20, 'three_pt_rate_last_10', phase4_data, phase3_data, 35.0, feature_sources) / 100.0)
```

**Change to:**
```python
# Shot zone features - use NULL instead of defaults, add indicator flag
paint_rate = self._get_feature_nullable(18, 'paint_rate_last_10', phase4_data, phase3_data, feature_sources)
mid_range_rate = self._get_feature_nullable(19, 'mid_range_rate_last_10', phase4_data, phase3_data, feature_sources)
three_pt_rate = self._get_feature_nullable(20, 'three_pt_rate_last_10', phase4_data, phase3_data, feature_sources)

# Convert to decimal if not None
features.append(paint_rate / 100.0 if paint_rate is not None else None)
features.append(mid_range_rate / 100.0 if mid_range_rate is not None else None)
features.append(three_pt_rate / 100.0 if three_pt_rate is not None else None)

# Add missingness indicator (Feature #XX - find next available index)
has_shot_zone_data = 1.0 if all([paint_rate, mid_range_rate, three_pt_rate]) else 0.0
features.append(has_shot_zone_data)
feature_sources[XX] = 'calculated'
```

**Add new helper method:**
```python
def _get_feature_nullable(self, index: int, field_name: str,
                          phase4_data: Dict, phase3_data: Dict,
                          feature_sources: Dict) -> Optional[float]:
    """Get feature value, returning None if not available (no default)."""
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        return float(phase4_data[field_name])

    if field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        return float(phase3_data[field_name])

    feature_sources[index] = 'missing'
    return None
```

**Update BigQuery schema** if needed to allow NULL for these columns.

---

### Task 2: Implement Actual Fallback in Shot Zone Analyzer

**Goal:** When BigDataBall PBP fails, actually try NBAC PBP as fallback (currently it just gives up).

**File:** `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`

**Current behavior:** If BigDataBall query fails, sets `shot_zones_available = False` and returns empty.

**Change to:**
```python
def extract_shot_zones(self, game_id: str, player_id: str) -> Dict:
    """Extract shot zones with BigDataBall -> NBAC fallback."""

    # Try BigDataBall first (primary source)
    try:
        result = self._extract_from_bigdataball(game_id, player_id)
        if result:
            self.shot_zones_source = 'bigdataball_pbp'
            self.shot_zones_available = True
            return result
    except Exception as e:
        logger.warning(f"BigDataBall shot zone extraction failed: {e}")

    # Fallback to NBAC PBP
    try:
        result = self._extract_from_nbac(game_id, player_id)
        if result:
            self.shot_zones_source = 'nbac_play_by_play'
            self.shot_zones_available = True
            logger.info(f"Using NBAC fallback for shot zones: {game_id}/{player_id}")
            return result
    except Exception as e:
        logger.warning(f"NBAC shot zone extraction also failed: {e}")

    # Both failed
    self.shot_zones_source = None
    self.shot_zones_available = False
    return {}

def _extract_from_bigdataball(self, game_id: str, player_id: str) -> Optional[Dict]:
    """Extract from BigDataBall PBP (primary, has coordinates)."""
    # Move existing BigDataBall extraction logic here
    pass

def _extract_from_nbac(self, game_id: str, player_id: str) -> Optional[Dict]:
    """Extract from NBAC PBP (fallback, simpler structure)."""
    # Implement NBAC extraction - may have different field names
    # Note: NBAC PBP may not have exact coordinates, use event types
    pass
```

---

### Task 3: Add Shot Zone Completeness to Daily Validation

**Goal:** Make shot zone coverage visible in daily validation output.

**File:** `scripts/validate_tonight_data.py`

**Add new check:**
```python
def check_shot_zone_completeness(self, game_date: str) -> ValidationResult:
    """Check shot zone data completeness for the date."""
    query = f"""
    SELECT
        COUNT(*) as total_players,
        COUNTIF(source_shot_zones_completeness_pct IS NOT NULL) as has_completeness,
        AVG(IFNULL(source_shot_zones_completeness_pct, 0)) as avg_completeness,
        COUNTIF(source_shot_zones_completeness_pct >= 80) as good_completeness,
        COUNTIF(source_shot_zones_completeness_pct < 50) as poor_completeness
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    """
    result = self.bq_client.query(query).result()
    row = list(result)[0]

    issues = []
    if row.avg_completeness < 80:
        issues.append(f"Shot zone completeness low: {row.avg_completeness:.1f}%")
    if row.poor_completeness > 0:
        issues.append(f"{row.poor_completeness} players with <50% shot zone data")

    return ValidationResult(
        check_name='shot_zone_completeness',
        passed=row.avg_completeness >= 80,
        message=f"Shot zone completeness: {row.avg_completeness:.1f}% ({row.good_completeness}/{row.total_players} players ≥80%)",
        issues=issues
    )
```

**Add to validation output:**
```
Shot Zone Coverage:
  ✓ Average completeness: 94.2%
  ✓ Players with good data (≥80%): 98/99
  △ Players with poor data (<50%): 1
```

---

### Task 4: Add Shot Zone Metrics to Admin Dashboard

**Goal:** Surface shot zone completeness in the admin dashboard.

**File:** `services/admin_dashboard/services/bigquery_service.py`

**Add method:**
```python
def get_shot_zone_coverage(self, game_date: str) -> Dict:
    """Get shot zone data coverage metrics."""
    query = f"""
    SELECT
        game_date,
        COUNT(*) as total_players,
        AVG(source_shot_zones_completeness_pct) as avg_completeness,
        COUNTIF(source_shot_zones_completeness_pct >= 80) as good_count,
        COUNTIF(source_shot_zones_completeness_pct < 50) as poor_count,
        COUNTIF(source_shot_zones_completeness_pct IS NULL) as missing_count
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    GROUP BY game_date
    """
    # Execute and return
```

**File:** `services/admin_dashboard/main.py`

**Add endpoint:**
```python
@app.route('/api/shot-zone-coverage')
def api_shot_zone_coverage():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    coverage = bq_service.get_shot_zone_coverage(date_str)
    return jsonify(coverage)
```

**File:** `services/admin_dashboard/templates/components/coverage_metrics.html`

**Add section for shot zone coverage** with:
- Completeness percentage gauge
- Good/Poor/Missing breakdown
- 7-day trend chart

---

### Task 5: Update Prediction Models to Handle NULLs

**Goal:** Ensure prediction models work correctly with NULL shot zone features.

**Files:**
- `predictions/worker/prediction_systems/catboost_v8.py`
- `predictions/worker/prediction_systems/xgboost_v1.py`
- `predictions/worker/prediction_systems/ensemble_v1.py`

**Verify:**
1. Models can handle NULL values in feature vectors
2. Feature extraction doesn't crash on NULL
3. Add explicit handling if needed:

```python
# CatBoost handles NaN natively, but ensure we're passing it correctly
features_array = np.array(features, dtype=np.float64)  # NaN-safe
```

**Test:**
- Run prediction with a player who has NULL shot zone data
- Verify prediction completes without error
- Compare accuracy with/without shot zone data

---

## Documentation Updates

After completing the above tasks, update these documents:

### 1. ML Feature Documentation
**File:** `docs/05-ml/features/feature-catalog.md` (create if doesn't exist)

Document:
- Feature #18-20: Shot zone rates (now nullable)
- Feature #XX: `has_shot_zone_data` indicator
- Fallback behavior: BigDataBall → NBAC → NULL

### 2. Daily Validation Checklist
**File:** `docs/02-operations/daily-validation-checklist.md`

Add to Step 3 (Data Freshness):
```markdown
### Shot Zone Coverage
- Check shot zone completeness: target ≥80%
- Alert if <70% or >10 players missing
```

### 3. Data Chain Documentation
**File:** `docs/07-monitoring/validation-system.md`

Update shot_zones chain definition:
```markdown
### Shot Zones Chain
- Primary: bigdataball_play_by_play (Gold, 94% coverage)
- Fallback: nbac_play_by_play (Silver, 100% coverage)
- On all fail: NULL with has_shot_zone_data=0
- Quality impact: -15 points
- ML handling: Uses missingness indicator feature
```

### 4. Incident Runbook
**File:** `docs/02-operations/runbooks/shot-zone-failures.md` (create)

Document:
- How to diagnose shot zone scraper failures
- How to backfill missing shot zone data
- Impact on predictions when data missing
- Monitoring queries for completeness

---

## Testing

1. **Unit tests for nullable feature extraction**
2. **Integration test for BigDataBall → NBAC fallback**
3. **Validation test for completeness check**
4. **Model test with NULL features**

---

## Success Criteria

- [ ] ML feature store uses NULL instead of averages for missing shot zones
- [ ] `has_shot_zone_data` indicator added to feature vector
- [ ] Shot zone analyzer falls back from BigDataBall to NBAC
- [ ] Daily validation shows shot zone completeness
- [ ] Admin dashboard displays shot zone coverage
- [ ] All prediction models handle NULL features correctly
- [ ] Documentation updated in 4 locations
- [ ] Tests passing

---

## Rollback Plan

If issues arise:
1. Revert to average-based defaults (feature store change only)
2. Keep visibility improvements (validation, dashboard)
3. Keep fallback implementation (always beneficial)

The visibility improvements are low-risk and can be deployed independently.
