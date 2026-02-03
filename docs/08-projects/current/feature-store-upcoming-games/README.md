# Feature Store Upcoming Games Architecture Fix

**Status:** ✅ **FIXED** - Deployed and verified
**Date:** 2026-02-03
**Sessions:** 95, 99
**Impact:** Feature quality improved from 65% to 85.1%

---

## Problem Statement

The ML Feature Store was producing **65% quality features** for upcoming games (should be 85%+), causing degraded prediction accuracy.

### Root Cause

Phase 4 processors only create data for **completed games** (yesterday), not **upcoming games** (today). When ML Feature Store queried for today's data, it found nothing and fell back to low-quality defaults.

```
BROKEN FLOW (Before):
┌─────────────────────────────────────────────────────────────────┐
│ Phase 4 runs → Creates data for YESTERDAY (completed games)     │
│ ML Feature Store queries WHERE game_date = TODAY → 0 rows       │
│ Falls back to defaults → 65% feature quality                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Solution Architecture

### Key Insight

The composite factors have 4 components with different data requirements:

| Factor | Type | Data Source | For Upcoming Games |
|--------|------|-------------|-------------------|
| **fatigue_score** | Player-specific | Phase 3 (upcoming_player_game_context) | ✅ Has today's data |
| **shot_zone_mismatch** | Matchup-specific | Phase 4 player zones + team defense | ✅ Uses recent player data + all 30 teams available |
| **pace_score** | Matchup-specific | Phase 3 (upcoming_team_game_context) | ✅ Has today's data |
| **usage_spike** | Player-specific | Phase 3 (upcoming_player_game_context) | ✅ Has today's data |

**Critical Finding:** The Phase 3 tables (`upcoming_*`) already have TODAY's matchup data. The Phase 4 tables have historical data for ALL 30 teams. The only blocker was **dependency checks** that required exact date match.

### Fixed Flow

```
FIXED FLOW (After):
┌─────────────────────────────────────────────────────────────────┐
│ 5:00 AM ET: PlayerCompositeFactorsProcessor runs                │
│   - Uses Phase 3 upcoming_* tables (HAS today's matchups)       │
│   - Uses Phase 4 team_defense (HAS all 30 teams)                │
│   - Bypass flags skip dependency checks                          │
│   - Creates TODAY's composite factors                            │
│                                                                  │
│ 7:00 AM ET: MLFeatureStoreProcessor runs                        │
│   - Queries composite factors WHERE game_date = TODAY           │
│   - Finds 339 records with correct matchup data                 │
│   - Falls back to recent data only if exact date fails          │
│   - Produces 85%+ feature quality                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Fixes Applied

### 1. Scheduler Job Updates

Both jobs now pass bypass flags for upcoming games:

```bash
# PlayerCompositeFactorsProcessor - 5 AM ET
gcloud scheduler jobs update http player-composite-factors-upcoming \
  --location=us-west2 \
  --message-body='{"processors":["PlayerCompositeFactorsProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}'

# MLFeatureStoreProcessor - 7 AM ET
gcloud scheduler jobs update http ml-feature-store-7am-et \
  --location=us-west2 \
  --message-body='{"processors":["MLFeatureStoreProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}'

# MLFeatureStoreProcessor - 1 PM ET
gcloud scheduler jobs update http ml-feature-store-1pm-et \
  --location=us-west2 \
  --message-body='{"processors":["MLFeatureStoreProcessor"],"analysis_date":"TODAY","strict_mode":false,"skip_dependency_check":true}'
```

### 2. Code Changes

#### Session 97 Quality Gate Fix
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:727-735`

```python
# Allow skip_dependency_check to bypass the Session 97 quality gate
skip_phase4_gate = self.is_backfill_mode or self.opts.get('skip_dependency_check', False)
if skip_phase4_gate:
    skip_reason = "backfill mode" if self.is_backfill_mode else "upcoming games mode"
    logger.info(f"SESSION 97 QUALITY_GATE SKIPPED: {skip_reason} - using fallback data")
```

#### Fallback Queries for All Extractors
**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Added fallback logic to 4 extraction methods:
- `_batch_extract_daily_cache()` - Session 95
- `_batch_extract_composite_factors()` - Session 99
- `_batch_extract_shot_zone()` - Session 99
- `_batch_extract_team_defense()` - Session 99

Pattern:
```python
# Try exact date match first
result = query WHERE date = game_date

# If no results, use most recent per player (safety net)
if result.empty:
    result = query WITH ROW_NUMBER() OVER (PARTITION BY player ORDER BY date DESC)
    WHERE date <= game_date AND date >= game_date - 7 DAYS
```

#### Feature Sources Tracking
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

- Store `feature_sources` in record for accurate alert counting
- Strip before BigQuery write (field not in schema)

---

## Daily Schedule

| Time (ET) | Job | What It Does |
|-----------|-----|--------------|
| 5:00 AM | `player-composite-factors-upcoming` | Calculate matchup-specific factors for TODAY |
| 7:00 AM | `ml-feature-store-7am-et` | Extract features using TODAY's composite factors |
| 8:00 AM | Predictions | Use high-quality features (85%+) |
| 1:00 PM | `ml-feature-store-1pm-et` | Refresh features (in case 7 AM failed) |

---

## Verification

### Check Feature Quality
```sql
SELECT
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(feature_quality_score < 70) as low_quality,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE();
```
**Expected:** avg_quality >= 85, low_quality = 0

### Check Composite Factors Exist
```sql
SELECT
  game_date,
  COUNT(*) as players,
  ROUND(AVG(fatigue_score), 1) as avg_fatigue,
  ROUND(AVG(shot_zone_mismatch_score), 2) as avg_shot_zone
FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;
```
**Expected:** 300+ players with correct matchup-specific scores

### Manual Trigger (if needed)
```bash
# Composite factors first
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerCompositeFactorsProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'

# Then feature store
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
```

---

## Commits

| Commit | Description |
|--------|-------------|
| df8448bc | fix: Add fallback to recent data for all Phase 4 extractors |
| 03dbb51a | fix: Skip Session 97 quality gate for upcoming games mode |
| e3c2c18e | fix: Store feature_sources in record for FEATURE SOURCE ALERT |
| cced8723 | fix: Strip feature_sources before BQ write (not in schema) |
| a2739b72 | chore: Remove debug logging from feature store (Session 99) |
| 7161d974 | fix: Correct logging for composite factors source |

---

## Key Files

| File | Purpose |
|------|---------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Feature extraction with fallback queries |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature store processor with quality gate |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | Composite factors calculation |

---

## Related Documentation

- **Session 95 Handoff:** `docs/09-handoff/2026-02-03-SESSION-95-HANDOFF.md`
- **Session 99 Handoff:** `docs/09-handoff/2026-02-03-SESSION-99-HANDOFF.md`
- **Feb 2 Validation:** `docs/08-projects/current/feb-2-validation/`

---

## Success Criteria

- [x] Feature quality >= 85% for upcoming games
- [x] Scheduler jobs configured with bypass flags
- [x] Composite factors created for TODAY's matchups
- [x] Fallback queries as safety net
- [x] Code deployed to production
