# Multi-Phase & Historical Dependency Enhancements

**Date**: 2025-11-21 14:00:00 PST
**Enhancement Type**: Cross-Phase Dependencies + Historical Backfill Awareness
**Files Modified**: 2 (Phase 4 & Phase 5 docs)

---

## Summary

Enhanced dependency checking documentation to properly reflect that **Phase 4 and Phase 5 can check Phase 2 directly** (not just their immediate predecessor), and that **historical data dependency checking** is critical for backfill scenarios.

---

## Key Enhancements

### 1. Multi-Phase Dependency Documentation

#### Phase 4 (Precompute) Now Documents:
✅ Can check Phase 3 (primary) AND Phase 2 (quality verification)
✅ Why this happens: quality verification, confidence scoring, root cause analysis
✅ Code example: ML Feature Store checking Phase 2 injury report completeness
✅ SQL query pattern for Phase 2 verification

#### Phase 5 (Predictions) Now Documents:
✅ Can check Phase 4 (primary), Phase 3 (ensemble weights), AND Phase 2 (root cause)
✅ Dependency hierarchy: Phase 4 → Phase 3 → Phase 2 (diagnostic chain)
✅ Code example: Root cause analysis tracing failures back to Phase 2
✅ SQL query pattern for Phase 2 data completeness verification

### 2. Historical Data Dependency Documentation

#### Phase 4 Historical Checks:
✅ Requires 10-20 games of historical data (vs Phase 3's current game only)
✅ Historical dependency pattern with 60-day lookback
✅ Early season handling (5 games minimum, 10 games preferred)
✅ **Historical backfill detection** - detects when Phase 3 processed old data
✅ 30-day lookback query pattern for reprocessing needs

#### Phase 5 Historical Checks:
✅ Tracks historical prediction accuracy (last 30 days)
✅ Dynamic system weighting based on historical performance
✅ Completed games detection for accuracy updates
✅ Historical accuracy influence on ensemble weights

---

## Code Examples Added

### Phase 4: Multi-Phase Checking

**5 New Code Examples**:

1. **ML Feature Store with Phase 2 Verification** (40 lines)
   ```python
   def check_dependencies_with_phase2_verification(...)
   ```

2. **Historical Dependency Check** (50 lines)
   ```python
   def check_historical_dependencies(...)
   ```

3. **Historical Backfill Detection** (40 lines)
   ```python
   def detect_historical_backfill(...)
   ```

4. **Phase 2 Quality Verification Query** (15 lines SQL)
   ```sql
   SELECT game_date, COUNT(...) as injury_count ...
   ```

5. **Historical Backfill Query Pattern** (25 lines SQL)
   ```sql
   SELECT p3.player_lookup, p3.game_date ...
   WHERE p3.processed_at > p4.processed_at  -- Backfill scenario
   ```

### Phase 5: Multi-Phase Checking

**3 New Code Examples**:

1. **Root Cause Analysis Checking Phase 2** (55 lines)
   ```python
   def diagnose_prediction_failure(...)
   ```

2. **Historical Accuracy Tracking** (35 lines)
   ```python
   def calculate_system_weight(...)  # Uses 30-day history
   ```

3. **Completed Games Detection** (25 lines)
   ```python
   def check_for_new_completed_games(...)
   ```

**Total New Code**: ~285 lines of Python + SQL examples

---

## Documentation Size Changes

| File | Before | After | Added |
|------|--------|-------|-------|
| 03-precompute-processors.md | 350 lines | 671 lines | **+321 lines** |
| 04-predictions-coordinator.md | 195 lines | 377 lines | **+182 lines** |
| **Total** | 545 lines | 1,048 lines | **+503 lines** |

---

## New Sections Added

### Phase 4 Document

1. **Multi-Phase Dependency Checking** (section)
   - Why Phase 4 checks Phase 2 directly
   - Quality verification use case
   - Confidence scoring adjustments
   - Code example with Phase 2 verification
   - SQL query pattern

2. **Historical Data Dependency Checking** (section)
   - Historical depth requirements (10-20 games)
   - Historical dependency pattern code
   - Backfill detection mechanism
   - 30-day lookback query pattern
   - Early season handling

### Phase 5 Document

1. **Multi-Phase Dependency Checking** (section)
   - Dependency hierarchy: Phase 4 → 3 → 2
   - Root cause analysis tracing
   - Why check multiple phases
   - Code example for diagnostics
   - SQL verification pattern

2. **Historical Prediction Tracking** (section)
   - Historical accuracy tracking (30 days)
   - Dynamic system weighting
   - Completed games detection
   - Accuracy-based weight calculation

---

## Key Insights Documented

### Multi-Phase Dependencies

**Phase 3**: Only checks Phase 2 (one level up)
**Phase 4**: Checks Phase 3 (primary) + Phase 2 (quality verification)
**Phase 5**: Checks Phase 4 (primary) + Phase 3 (ensemble weights) + Phase 2 (root cause)

**Why This Matters**:
- Later phases need to verify data quality at the source
- Root cause analysis requires tracing back to raw data
- Confidence scoring depends on upstream completeness

### Historical Dependencies

**Phase 2**: Current game only (no history needed)
**Phase 3**: Current game + optional historical context
**Phase 4**: **10-20 games required** (historical depth critical)
**Phase 5**: **30 days of prediction history** (for accuracy tracking)

**Why This Matters**:
- ML features need stable rolling averages
- Prediction systems improve via historical accuracy
- Backfills must be detected and reprocessed

---

## Example Scenarios Documented

### Scenario 1: Phase 4 ML Feature Store Quality Check

```
User Issue: "Why is my prediction confidence only 85%?"

Root Cause Analysis:
1. Check Phase 4 ML features → quality_score = 85
2. Check Phase 3 analytics → All present
3. Check Phase 2 injury report → Only 25 players (expected 40-60)
4. Diagnosis: Phase 2 injury data incomplete (-10% quality penalty)
5. Action: Wait for next injury report scrape or manually backfill
```

### Scenario 2: Historical Backfill Detection

```
Operations Scenario: "Phase 2 backfilled 5 days of missing data"

Phase 4 Response:
1. Query Phase 3 for games with recent processed_at timestamps
2. Find 15 games from 5 days ago were just processed
3. Detect that Phase 4 player_daily_cache is stale for those games
4. Trigger reprocessing for those 15 games
5. ML Feature Store updates with new historical data
```

### Scenario 3: Phase 5 Root Cause Tracing

```
Prediction Failure: "No prediction for player X"

Diagnostic Chain:
1. Phase 5: Check Phase 4 ML features → MISSING
2. Phase 4: Check Phase 3 analytics → MISSING
3. Phase 3: Check Phase 2 boxscores → MISSING
4. Phase 2: Check Phase 1 scraper logs → FAILED
5. Root Cause: Scraper failed, need to retry
6. Action: Re-run scraper, data will flow through phases
```

---

## Query Patterns Added

### 1. Phase 2 Verification (Phase 4)
```sql
-- Check injury report completeness
SELECT game_date, COUNT(DISTINCT player_lookup),
       CASE WHEN COUNT(...) >= 40 THEN 1.0 ELSE 0.7 END as quality_score
FROM `nba_raw.nbac_injury_report` ...
```

### 2. Historical Backfill Detection (Phase 4)
```sql
-- Find Phase 3 data newer than Phase 4 (needs reprocessing)
SELECT p3.game_date, p3.processed_at, p4.processed_at
WHERE p3.processed_at > p4.processed_at  -- Backfill!
```

### 3. Root Cause Verification (Phase 5)
```sql
-- Check Phase 2 completeness for failed prediction
SELECT
  (SELECT COUNT(*) FROM nba_raw.nbac_injury_report ...) as injury_count,
  (SELECT COUNT(*) FROM nba_raw.nbac_player_boxscores ...) as boxscore_count
```

### 4. Historical Accuracy (Phase 5)
```sql
-- Calculate system weight based on 30-day accuracy
SELECT COUNT(*) as predictions_made,
       COUNTIF(ABS(prediction - actual) <= 3.0) / COUNT(*) as accuracy
FROM prediction_accuracy_log
WHERE prediction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
```

---

## Best Practices Documented

### Multi-Phase Checking Best Practices

1. **Primary Dependencies First**: Always check immediate predecessor phase first
2. **Verification, Not Dependency**: Checking Phase 2 is usually for quality verification, not a hard dependency
3. **Root Cause Chain**: When failures occur, trace back through all phases systematically
4. **Quality Score Adjustments**: Use upstream data completeness to adjust confidence scores

### Historical Checking Best Practices

1. **Lookback Windows**:
   - Phase 4: 60 days (capture 10-20 games)
   - Phase 5: 30 days (prediction accuracy tracking)

2. **Minimum Viable History**:
   - Phase 4: 5 games (early season minimum)
   - Phase 4: 10 games (preferred for stable metrics)

3. **Backfill Detection**:
   - Check `processed_at` timestamps, not just data existence
   - Compare Phase 3 `processed_at` vs Phase 4 `processed_at`
   - Reprocess when Phase 3 is newer (indicates backfill)

4. **Early Season Handling**:
   - Flag records with `early_season_flag = True`
   - Reduce confidence scores appropriately
   - Still process (don't skip) if >= 5 games

---

## Impact Assessment

### Documentation Completeness

**Before**:
- ❌ No mention of Phase 4/5 checking Phase 2
- ❌ Historical checking mentioned but not detailed
- ❌ No backfill detection patterns

**After**:
- ✅ Clear multi-phase dependency hierarchy
- ✅ 8 code examples for cross-phase checking
- ✅ 4 SQL query patterns
- ✅ 3 real-world scenarios documented
- ✅ Best practices for historical and multi-phase checks

### Developer Guidance

**Before**: Developers might assume:
- Phase 4 only checks Phase 3
- Phase 5 only checks Phase 4
- Historical data not important

**After**: Developers understand:
- Later phases can check earlier phases for quality/diagnostics
- Historical data critical for Phase 4+ (not optional)
- Backfill detection is necessary
- Root cause analysis requires multi-phase tracing

---

## Testing Recommendations

### Multi-Phase Dependency Testing

```python
def test_ml_feature_store_phase2_verification():
    """Test that ML Feature Store checks Phase 2 for quality."""
    # Scenario: Phase 3 complete but Phase 2 injury data incomplete
    # Expected: quality_score reduced by 10%
    pass

def test_root_cause_traces_to_phase2():
    """Test that Phase 5 can trace failures back to Phase 2."""
    # Scenario: Prediction fails due to missing Phase 2 boxscores
    # Expected: diagnosis returns 'phase_2' failure level
    pass
```

### Historical Dependency Testing

```python
def test_historical_backfill_detection():
    """Test that Phase 4 detects Phase 3 backfills."""
    # Scenario: Phase 3 processes 5-day-old game
    # Expected: Phase 4 detects and reprocesses
    pass

def test_early_season_handling():
    """Test that Phase 4 handles <10 games gracefully."""
    # Scenario: Player has only 7 games
    # Expected: Process with early_season_flag=True, reduced confidence
    pass
```

---

## Related Documentation

### Already Exists (Overview)
- `00-overview.md` Section: "Cross-Phase Dependencies"
- `00-overview.md` Section: "Historical Backfill Dependency Checking"
- `00-overview.md` Example: "Phase 5 Checking Phase 2 for Root Cause"

### Now Enhanced (Phase-Specific)
- ✅ `03-precompute-processors.md` Section: "Multi-Phase Dependency Checking"
- ✅ `03-precompute-processors.md` Section: "Historical Data Dependency Checking"
- ✅ `04-predictions-coordinator.md` Section: "Multi-Phase Dependency Checking"
- ✅ `04-predictions-coordinator.md` Section: "Historical Prediction Tracking"

---

## Version History

**v2.1 - 2025-11-21 14:00** (Multi-Phase & Historical Enhancement)
- Added 503 lines of documentation
- 8 new code examples (285 lines)
- 4 new SQL query patterns
- 3 real-world scenario walkthroughs
- Best practices for multi-phase and historical checking

**v2.0 - 2025-11-21 13:30** (Major Restructuring)
- Added Phase 4 documentation
- Renamed all files
- Fixed all broken links

**v1.0 - 2025-11-21 12:00** (Initial Creation)
- Base structure created

---

**Enhancement Version**: 2.1
**Created**: 2025-11-21 14:00:00 PST
**Files Modified**: 2
**Lines Added**: 503
**Code Examples Added**: 8
**SQL Patterns Added**: 4
