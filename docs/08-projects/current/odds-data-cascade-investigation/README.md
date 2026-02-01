# Odds Data Cascade Investigation

**Created:** 2026-01-31 (Session 59)
**Status:** In Progress
**Priority:** P0 - Affects ML model training data quality

---

## Executive Summary

Investigation into why the ML feature store has missing Vegas line data for Nov 2025, despite raw odds data being available. Discovered a cascade architecture inconsistency where:

- **Phase 3 (Analytics):** Uses odds_api as primary, bettingpros as fallback
- **Phase 4 (Feature Store):** Uses bettingpros ONLY (no fallback)

This caused 68% of Oct-Dec 2025 training data to have `vegas_line = 0`, corrupting monthly retrain experiments.

---

## Data Source Coverage Analysis

### Historical Coverage (When V8 Was Trained)

| Period | odds_api Records | bettingpros Records | Primary Source |
|--------|------------------|---------------------|----------------|
| 2021-11 to 2024-06 | 60,810 | 1,382,694 | **bettingpros** |

V8 was designed when bettingpros had 20x more data than odds_api.

### Current Coverage (2024-2026)

| Month | odds_api | bettingpros | Notes |
|-------|----------|-------------|-------|
| 2024-01 to 2025-06 | 8-11K | 80-160K | bettingpros dominant |
| **2025-10** | 5,064 | **0** | bettingpros scraper DOWN |
| **2025-11** | 16,236 | **0** | bettingpros scraper DOWN |
| 2025-12 | 16,985 | 114,995 | bettingpros recovered |
| 2026-01 | 40,175 | 2,435,163 | Both active |

**Key Finding:** BettingPros scraper was completely down Oct-Nov 2025, but odds_api was running fine.

---

## Component Cascade Analysis

### Phase 3: upcoming_player_game_context

**File:** `data_processors/analytics/upcoming_player_game_context/betting_data.py`

```
Source Priority:
1. odds_api_player_points_props (via extract_prop_lines_from_odds_api)
2. bettingpros_player_points_props (via extract_prop_lines_from_bettingpros)

Strategy: UNION of both sources in SQL CTEs
Output: has_prop_line = TRUE if either source has data
```

**Status:** ✅ Correct cascade architecture

### Phase 3: upcoming_team_game_context

**File:** `data_processors/analytics/upcoming_team_game_context/calculators/betting_context.py`

```
Source: odds_api_game_lines only
Bookmaker Priority: DraftKings → FanDuel
```

**Status:** ✅ Correct (game lines only from odds_api)

### Phase 4: ml_feature_store_v2

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

```python
def _batch_extract_vegas_lines(self, game_date, player_lookups):
    query = f"""
    FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`  # <-- BUG!
    WHERE game_date = '{game_date}'
      AND market_type = 'points'
      AND bet_side = 'over'
    ...
    """
```

**Status:** ❌ NO CASCADE - Uses bettingpros only, ignores odds_api

### Phase 5: Prediction Coordinator

**File:** `predictions/coordinator/player_loader.py`

```
Source: Reads from upcoming_player_game_context (Phase 3)
Does NOT directly query raw odds tables
```

**Status:** ✅ Inherits Phase 3 cascade correctly

### Phase 5: Prediction Worker

**File:** `predictions/worker/data_loaders.py`

```
Source: Reads features from ml_feature_store_v2 (Phase 4)
Does NOT directly query raw odds tables
```

**Status:** ⚠️ Affected by Phase 4 bug

---

## The Bug: Feature Store Vegas Line Extraction

### Current (Broken) Architecture

```
Raw Layer:
┌─────────────────────────┐     ┌─────────────────────────┐
│ odds_api_player_props   │     │ bettingpros_player_props│
│ ✅ Has Nov 2025 data    │     │ ❌ No Nov 2025 data     │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            │                               │
            ▼                               ▼
Phase 3:  ┌─────────────────────────────────────────────────┐
          │ upcoming_player_game_context                    │
          │ Uses UNION of both sources ✅                    │
          │ has_prop_line = TRUE for 62 players on Nov 20   │
          └─────────────────────────────────────────────────┘
                            │
                            │ (IGNORED!)
                            ▼
Phase 4:  ┌─────────────────────────────────────────────────┐
          │ ml_feature_store_v2                             │
          │ Queries ONLY bettingpros ❌                      │
          │ vegas_line = 0 for all players on Nov 20        │
          └─────────────────────────────────────────────────┘
```

### Verification Query (Nov 20, 2025)

| Source | Records | With Vegas Data |
|--------|---------|-----------------|
| odds_api_player_points_props | 327 | 63 players |
| bettingpros_player_points_props | 0 | 0 players |
| upcoming_player_game_context | 176 | 62 with lines |
| ml_feature_store_v2 | 140 | **0 with lines** |

---

## Recommended Fix Options

### Option A: Feature Store Reads from Phase 3 (Recommended)

Change `feature_extractor._batch_extract_vegas_lines()` to read from `upcoming_player_game_context` instead of raw bettingpros table.

**Pros:**
- Follows existing Phase 3 → Phase 4 architecture pattern
- Inherits Phase 3 cascade logic automatically
- Single source of truth for betting data

**Cons:**
- Feature store becomes dependent on Phase 3 completing first
- Need to ensure Phase 3 runs before Phase 4

### Option B: Feature Store Implements Own Cascade

Change `feature_extractor._batch_extract_vegas_lines()` to query odds_api first, then bettingpros as fallback.

**Pros:**
- Feature store is self-contained
- No dependency on Phase 3 for betting data

**Cons:**
- Duplicates cascade logic from Phase 3
- Two places to maintain priority rules
- Potential for drift

### Option C: Shared Betting Data Utility

Create `shared/utils/betting_cascade.py` that both Phase 3 and Phase 4 use.

**Pros:**
- DRY principle - single cascade implementation
- Consistent behavior across all phases

**Cons:**
- More refactoring required
- New shared module to maintain

---

## V8 Training Context

### V8 Training Architecture (Robust)

V8 was trained using a **different approach** than quick_retrain:

```python
# V8 Training (train_final_ensemble_v8.py)
query = """
  SELECT mf.features  -- 25-feature records (NO Vegas baked in)
  FROM ml_feature_store_v2 mf
  LEFT JOIN bettingpros_player_points_props v  -- Vegas joined dynamically
    ON mf.player_lookup = v.player_lookup
  ...
"""
# Then imputes: df['vegas_points_line'].fillna(df['player_season_avg'])
```

**Key differences:**
1. Uses **25-feature records** (no Vegas baked in)
2. Joins Vegas **dynamically at training time**
3. Uses **LEFT JOIN** - trains on records even without Vegas
4. **Imputes missing Vegas** with player season average

### quick_retrain Architecture (Fragile)

```python
# quick_retrain.py (current)
query = """
  SELECT mf.features  -- 33-feature records (Vegas already baked in)
  FROM ml_feature_store_v2 mf
  WHERE mf.feature_count >= 33
  ...
"""
# NO imputation - if vegas_line = 0, it stays 0
```

**Problems:**
1. Uses **33-feature records** (Vegas pre-baked)
2. If Vegas was missing at feature extraction time, it's **permanently 0**
3. No dynamic fallback or imputation
4. Completely dependent on feature store data quality

### Historical Coverage

V8 was trained on Nov 2021 - Jun 2024 data when:
- bettingpros had 1.38M records (dominant source)
- odds_api had only 60K records
- Feature store correctly used bettingpros for Vegas extraction

The architecture became broken when:
1. odds_api became more reliable (2024+)
2. bettingpros had outages (Oct-Nov 2025)
3. Feature store still only queries bettingpros (no fallback)
4. quick_retrain uses pre-baked 33f records (no recovery possible)

---

## Affected Data Ranges

| Period | Feature Store Vegas Coverage | Root Cause |
|--------|------------------------------|------------|
| 2021-11 to 2024-06 | ~99% | bettingpros active |
| 2024-11 to 2025-09 | ~99% | bettingpros active |
| **2025-10 to 2025-11** | **~0%** | bettingpros down, no fallback |
| 2025-12-01 to 2025-12-19 | ~30% | bettingpros partially back |
| 2025-12-20+ | ~75% | Both sources active |

---

## Impact Assessment

### Monthly Retraining (Session 59)

Model trained on Oct-Dec 2025 data:
- 68.6% of records had `vegas_line = 0`
- Model learned wrong patterns about Vegas importance
- Result: Lower hit rate (49%) vs V8 baseline (55%)

### Production Predictions

Predictions made Nov 2025:
- Feature store had vegas_line = 0
- Model predictions were generated without Vegas context
- **Unknown impact on prediction accuracy during this period**

---

## Decision Matrix

### For Feature Store (Phase 4)

| Option | Effort | Risk | Consistency | Recommendation |
|--------|--------|------|-------------|----------------|
| **A. Read from Phase 3** | Low | Low | High | **Recommended** |
| B. Implement own cascade | Medium | Medium | Low | Not recommended |
| C. Shared utility | High | Low | High | Overkill for now |

**Rationale for Option A:**
- Phase 3 already has the correct cascade logic
- Feature store should follow the Phase 3 → Phase 4 pattern
- `upcoming_player_game_context.current_points_line` is already computed correctly
- Minimal code change required

### For quick_retrain.py

**Two options:**

1. **Use V8's approach** - Join Vegas dynamically with imputation
   - More robust, matches production V8 training
   - Requires SQL change and imputation code

2. **Keep using 33f records** - But ensure feature store is fixed first
   - Simpler, but dependent on feature store quality
   - Only works after Option A is implemented

## Next Steps

1. [ ] Decide on fix option (A, B, or C) → **Recommending Option A**
2. [ ] Implement fix to feature_extractor.py
3. [ ] Backfill feature store for Oct-Nov 2025 with correct Vegas data
4. [ ] Re-run monthly retrain experiment with fixed data
5. [ ] Add monitoring for Vegas data coverage in feature store
6. [ ] Consider updating quick_retrain.py to use V8's dynamic join approach

---

## Related Files

| File | Role |
|------|------|
| `data_processors/analytics/upcoming_player_game_context/betting_data.py` | Phase 3 cascade |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Phase 4 (broken) |
| `predictions/coordinator/player_loader.py` | Phase 5 consumer |
| `shared/utils/odds_preference.py` | Game lines utility |
| `shared/utils/odds_player_props_preference.py` | Player props utility |

---

## Session Log

### Session 59 (2026-01-31)

1. Discovered monthly retrain had worse hit rate despite better MAE
2. Investigated Vegas data coverage in feature store
3. Found bettingpros scraper was down Oct-Nov 2025
4. Traced bug to feature_extractor.py using bettingpros only
5. Documented cascade architecture across all components
6. Created this project document

---

*Last Updated: 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
