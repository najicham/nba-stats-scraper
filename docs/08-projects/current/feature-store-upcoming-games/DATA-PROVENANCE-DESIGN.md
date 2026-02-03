# Data Provenance & Fallback Quality Design

**Status:** 🟡 **DESIGN PHASE**
**Date:** 2026-02-03
**Priority:** P0 - Critical for prediction quality

---

## Problem Statement

Current fallback logic can **silently degrade prediction quality** by using incorrect data:

### The Core Issue

| Factor | Type | Current Fallback | Problem |
|--------|------|------------------|---------|
| **fatigue_score** | Player-specific | Yesterday's value | ⚠️ Acceptable - changes slowly |
| **shot_zone_mismatch** | **Matchup-specific** | Yesterday's opponent data | ❌ **WRONG** - different opponent |
| **pace_score** | **Matchup-specific** | Yesterday's opponent data | ❌ **WRONG** - different opponent |
| **usage_spike** | Player-specific | Yesterday's value | ⚠️ Acceptable - based on teammate status |

### Example of Why This Matters

```
LeBron James on Feb 3 vs BOSTON (elite defense)
- Correct shot_zone_mismatch: -3.0 (paint defender is elite)

Fallback uses Feb 2 vs CHARLOTTE (weak defense):
- Wrong shot_zone_mismatch: +4.5 (paint defender is weak)

Result: Prediction thinks matchup is FAVORABLE when it's UNFAVORABLE
→ Bad pick recommendation
```

---

## Design Principles

### 1. Don't Use Wrong Data
**For matchup-specific factors:** Use neutral defaults (0.0) instead of wrong opponent data.
- Better to have no signal than wrong signal
- Clearly mark as "matchup_data_unavailable"

### 2. Track Everything
**Store provenance at feature level:**
- Which source provided each feature
- Was it the correct date/matchup?
- What was the fallback reason?

### 3. Make It Visible
**Show data quality in all outputs:**
- Subset picks should show quality tier
- API exports should include provenance
- Alerts when using degraded data

### 4. Enable Replacement
**When better data becomes available:**
- Flag predictions as "upgradeable"
- Re-run when composite factors created
- Track which predictions were updated

---

## Schema Changes

### 1. Add feature_sources to ml_feature_store_v2

```sql
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_sources JSON
  OPTIONS (description='Per-feature source tracking: {"0": "phase4", "5": "default", ...}'),
ADD COLUMN IF NOT EXISTS fallback_reasons ARRAY<STRING>
  OPTIONS (description='Why fallbacks were used: ["composite_factors_missing", "wrong_matchup_date"]'),
ADD COLUMN IF NOT EXISTS matchup_data_status STRING
  OPTIONS (description='COMPLETE, PARTIAL_FALLBACK, MATCHUP_UNAVAILABLE'),
ADD COLUMN IF NOT EXISTS data_date_used DATE
  OPTIONS (description='Actual date of source data used (may differ from game_date)');
```

### 2. Add provenance to player_prop_predictions

```sql
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_data_status STRING
  OPTIONS (description='COMPLETE, PARTIAL_FALLBACK, MATCHUP_UNAVAILABLE'),
ADD COLUMN IF NOT EXISTS can_be_upgraded BOOL
  OPTIONS (description='TRUE if better data may become available'),
ADD COLUMN IF NOT EXISTS upgrade_reason STRING
  OPTIONS (description='Why this prediction could be upgraded'),
ADD COLUMN IF NOT EXISTS original_prediction_id STRING
  OPTIONS (description='If upgraded, link to original prediction');
```

---

## Code Changes

### 1. Fix Fallback Logic for Matchup-Specific Factors

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

```python
def _batch_extract_composite_factors(self, game_date: date) -> None:
    """
    Extract composite factors with smart fallback handling.

    For MATCHUP-SPECIFIC factors (shot_zone_mismatch, pace_score):
    - Only use data if it matches today's game_date AND opponent
    - If no match, use NEUTRAL DEFAULT (0.0), not wrong opponent data

    For PLAYER-SPECIFIC factors (fatigue, usage_spike):
    - Can use recent data as fallback (stable over short periods)
    """
    # First try exact date match
    result = self._safe_query(exact_date_query)

    if result.empty:
        self._fallback_reasons.append("composite_factors_missing_for_date")

        # For player-specific factors, use recent data
        # For matchup-specific factors, use neutral defaults
        logger.warning(f"No composite factors for {game_date}")
        self._matchup_data_status = "MATCHUP_UNAVAILABLE"

        # Mark matchup-specific features for default values
        for player in self._player_list:
            self._composite_factors_lookup[player] = {
                'fatigue_score': self._get_recent_fatigue(player),  # OK to fallback
                'shot_zone_mismatch_score': 0.0,  # Use neutral, NOT wrong opponent
                'pace_score': 0.0,  # Use neutral, NOT wrong opponent
                'usage_spike_score': self._get_recent_usage_spike(player),  # OK to fallback
                '_fallback_used': True,
                '_matchup_factors_defaulted': True
            }
```

### 2. Track Feature Sources in Feature Extraction

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
def _calculate_features(self, player_lookup: str, ...) -> Dict:
    """Calculate features with source tracking."""
    feature_sources = {}
    fallback_reasons = []

    # Feature 5: fatigue_score
    fatigue, source, reason = self._get_feature_with_provenance(
        phase4_data, 'fatigue_score', default=50.0
    )
    feature_sources['5'] = source
    if reason:
        fallback_reasons.append(reason)

    # Feature 6: shot_zone_mismatch (MATCHUP-SPECIFIC)
    if phase4_data.get('_matchup_factors_defaulted'):
        shot_zone = 0.0
        feature_sources['6'] = 'default_wrong_matchup'
        fallback_reasons.append('shot_zone_mismatch_no_matchup_data')
    else:
        shot_zone = phase4_data.get('shot_zone_mismatch_score', 0.0)
        feature_sources['6'] = 'phase4'

    # ... similar for other features

    return {
        'features': features,
        'feature_sources': feature_sources,
        'fallback_reasons': fallback_reasons,
        'matchup_data_status': self._determine_matchup_status(feature_sources)
    }
```

### 3. Store Provenance in BigQuery

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
def _prepare_record(self, ...) -> Dict:
    """Prepare record with full provenance."""
    record = {
        # ... existing fields ...

        # NEW: Provenance tracking
        'feature_sources': json.dumps(feature_sources),
        'fallback_reasons': fallback_reasons,
        'matchup_data_status': matchup_status,
        'data_date_used': self._get_actual_data_date(),
    }
    return record
```

### 4. Pass Provenance to Predictions

**File:** `predictions/worker/worker.py`

```python
def _create_prediction_record(self, feature_data: Dict, ...) -> Dict:
    """Create prediction with provenance from feature store."""
    return {
        # ... existing fields ...

        # NEW: Inherited provenance
        'feature_data_status': feature_data.get('matchup_data_status'),
        'can_be_upgraded': feature_data.get('matchup_data_status') == 'MATCHUP_UNAVAILABLE',
        'upgrade_reason': 'Matchup-specific factors used defaults' if can_upgrade else None,
    }
```

---

## Visibility Changes

### 1. Update /subset-picks to Show Data Quality

**File:** `.claude/skills/subset-picks/SKILL.md`

Add to query output:
```sql
SELECT
    p.player_lookup,
    p.predicted_points,
    p.line_value,
    p.edge,
    p.recommendation,
    -- NEW: Data quality visibility
    f.feature_quality_score,
    f.matchup_data_status,
    CASE
        WHEN f.matchup_data_status = 'COMPLETE' THEN '✅'
        WHEN f.matchup_data_status = 'PARTIAL_FALLBACK' THEN '⚠️'
        ELSE '❌'
    END as data_status_emoji,
    p.can_be_upgraded
FROM predictions p
JOIN ml_feature_store_v2 f ON p.player_lookup = f.player_lookup
```

### 2. Add Quality Tier to Pick Output

```
HIGH-EDGE PICKS (edge >= 5):
┌─────────────────┬──────┬──────┬────────┬─────────────┬────────────┐
│ Player          │ Pred │ Line │ Edge   │ Recommend   │ Data       │
├─────────────────┼──────┼──────┼────────┼─────────────┼────────────┤
│ LeBron James    │ 28.1 │ 22.5 │ +5.6   │ OVER        │ ✅ Complete │
│ Jayson Tatum    │ 30.2 │ 25.0 │ +5.2   │ OVER        │ ⚠️ Partial  │
│ Anthony Davis   │ 25.8 │ 20.5 │ +5.3   │ OVER        │ ❌ Degraded │
└─────────────────┴──────┴──────┴────────┴─────────────┴────────────┘

⚠️ 1 pick has partial data - review before betting
❌ 1 pick used default matchup factors - consider skipping
```

---

## Upgrade Flow

### When Better Data Becomes Available

```
SCENARIO: Composite factors calculated at 5 AM but feature store ran at 4 AM

1. Feature store ran with MATCHUP_UNAVAILABLE status
2. Composite factors processor runs at 5 AM
3. Feature store 7 AM refresh detects:
   - composite_factors now available
   - Previous features had matchup_data_status = MATCHUP_UNAVAILABLE

4. Re-extract features with correct matchup data
5. Update ml_feature_store_v2 with:
   - feature_sources = correct sources
   - matchup_data_status = COMPLETE

6. Optionally re-run predictions for affected players
   - Only if lines haven't moved significantly
   - Store link to original prediction
```

### Tracking Upgrades

```sql
-- Find predictions that were upgraded
SELECT
    p1.player_lookup,
    p1.predicted_points as original_prediction,
    p2.predicted_points as upgraded_prediction,
    p1.feature_data_status as original_status,
    p2.feature_data_status as upgraded_status,
    ABS(p1.predicted_points - p2.predicted_points) as prediction_change
FROM player_prop_predictions p1
JOIN player_prop_predictions p2
    ON p1.player_lookup = p2.player_lookup
    AND p1.game_date = p2.game_date
    AND p2.original_prediction_id = p1.prediction_id
WHERE p1.game_date = CURRENT_DATE();
```

---

## Implementation Plan

### Phase 1: Schema Changes (1 hour)
- [ ] Add feature_sources column to ml_feature_store_v2
- [ ] Add fallback_reasons column
- [ ] Add matchup_data_status column
- [ ] Add provenance columns to predictions table

### Phase 2: Fix Fallback Logic (2 hours)
- [ ] Update _batch_extract_composite_factors to not use wrong matchups
- [ ] Add neutral defaults for matchup-specific factors
- [ ] Track fallback reasons

### Phase 3: Store Provenance (2 hours)
- [ ] Update feature calculation to track sources
- [ ] Store feature_sources JSON in BigQuery
- [ ] Pass provenance to predictions

### Phase 4: Visibility (2 hours)
- [ ] Update subset-picks skill to show data quality
- [ ] Add quality tier to output
- [ ] Add warning messages

### Phase 5: Upgrade Flow (4 hours)
- [ ] Detect when better data becomes available
- [ ] Re-run feature extraction
- [ ] Optionally re-run predictions

---

## Success Criteria

1. **No silent quality degradation** - Matchup-specific factors use defaults, not wrong data
2. **Full provenance tracking** - Can trace any prediction back to its data sources
3. **Visible data quality** - Subset picks show status (✅/⚠️/❌)
4. **Upgradeable predictions** - When better data arrives, predictions can be updated

---

## Verification Queries

### Check Provenance Distribution
```sql
SELECT
    matchup_data_status,
    COUNT(*) as records,
    ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY matchup_data_status;
```

### Check Feature Source Distribution
```sql
SELECT
    JSON_EXTRACT_SCALAR(feature_sources, '$.6') as shot_zone_source,
    COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY shot_zone_source;
```

### Find Predictions That Could Be Upgraded
```sql
SELECT
    player_lookup,
    predicted_points,
    feature_data_status,
    can_be_upgraded,
    upgrade_reason
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND can_be_upgraded = TRUE;
```
