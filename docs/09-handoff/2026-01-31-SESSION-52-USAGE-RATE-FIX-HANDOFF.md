# Session 52 Handoff: Usage Rate Fix & Backfill

**Date:** 2026-01-31
**Session:** 52
**Focus:** Fix usage_spike_score always being 0, backfill all affected data
**Status:** ML Feature Store backfill in progress

---

## Problem Identified

`usage_spike_score` was always 0 for all players in the ML Feature Store because:

1. `usage_spike_score` depends on `avg_usage_rate_last_7_games`
2. `avg_usage_rate_last_7_games` requires `usage_rate` from historical boxscore data
3. The historical boxscores query only pulled from `bdl_player_boxscores` which does NOT have `usage_rate`
4. The fix: LEFT JOIN with `player_game_summary` which has the calculated `usage_rate`

---

## Fixes Applied

### 1. Code Fix: Usage Rate Extraction
**File:** `data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py`

Added LEFT JOIN with `player_game_summary` to get `usage_rate` in the historical boxscores query:

```sql
FROM `nba_raw.bdl_player_boxscores` bdl
LEFT JOIN `nba_analytics.player_game_summary` pgs
  ON bdl.player_lookup = pgs.player_lookup AND bdl.game_date = pgs.game_date
```

### 2. Code Fix: Schema Mismatch
**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Fixed `scraped_at` → `created_at` column name in vegas_lines query (lines 686, 690).

### 3. Prevention Mechanisms Added
**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- Added feature quality validation that warns when critical features are <10% populated

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Added feature source validation that warns when Phase 4 features are >90% defaults

---

## Commits

| Commit | Description |
|--------|-------------|
| `78e5551b` | feat: Add usage_rate extraction and feature quality validation |

---

## Deployments

| Service | Status | Notes |
|---------|--------|-------|
| nba-phase3-analytics-processors | ✅ Deployed | Includes usage_rate fix |
| nba-phase4-precompute-processors | ✅ Deployed | Includes feature validation |

---

## Backfills Completed

### Phase 3: upcoming_player_game_context
- **Status:** ✅ Complete
- **Date Range:** 2025-11-13 to 2026-01-30
- **Dates Processed:** 77/77 (2 no-game days skipped: Thanksgiving, Christmas Eve)
- **Players Processed:** 32,157
- **Result:** `avg_usage_rate_last_7_games` now populated for ~55% of players

### Phase 4: player_composite_factors
- **Status:** ✅ Complete
- **Date Range:** 2025-11-13 to 2026-01-30
- **Dates Processed:** 77/77
- **Result:** `usage_spike_score` now calculated (avg ~0.9-1.0, not 0)

---

## Backfill In Progress

### ML Feature Store (ml_feature_store_v2)
- **Status:** 🔄 Running
- **Date Range:** 2025-11-13 to 2026-01-30
- **Log File:** `/tmp/ml_feature_store_backfill_v2.log`
- **Process:** PID 2501843
- **ETA:** ~1.5-2 hours from 10:45 PM PST (completion ~12:30 AM)

To check progress:
```bash
grep "Processing game date" /tmp/ml_feature_store_backfill_v2.log | tail -3
```

---

## Verification Queries

### Check usage_rate is populated in Phase 3:
```sql
SELECT
  game_date,
  COUNT(*) as records,
  COUNTIF(avg_usage_rate_last_7_games IS NOT NULL) as has_usage,
  ROUND(100.0 * COUNTIF(avg_usage_rate_last_7_games IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2025-11-13'
GROUP BY 1 ORDER BY 1 LIMIT 10
```

### Check usage_spike_score in Phase 4:
```sql
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(AVG(usage_spike_score), 2) as avg_usage_spike,
  COUNTIF(usage_spike_score != 0) as non_zero
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2025-11-13'
GROUP BY 1 ORDER BY 1 LIMIT 10
```

### Check ML Feature Store:
```sql
SELECT
  game_date,
  COUNT(*) as players,
  MAX(features[OFFSET(8)]) as max_usage_spike,
  ROUND(AVG(features[OFFSET(8)]), 2) as avg_usage_spike
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-13'
GROUP BY 1 ORDER BY 1 LIMIT 10
```

---

## Next Session Checklist

1. **Verify ML Feature Store backfill completed:**
   ```bash
   grep "BACKFILL COMPLETE" /tmp/ml_feature_store_backfill_v2.log
   ```

2. **Run verification queries above** to confirm data is correct

3. **Commit the schema fix** (scraped_at → created_at) if not already done

4. **Deploy ML Feature Store processor** if needed for production

---

## Root Cause Analysis

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| usage_spike_score = 0 | usage_rate not extracted from historical data | Added LEFT JOIN with player_game_summary |
| ML Feature Store batch failures | Schema mismatch (scraped_at vs created_at) | Fixed column name |

---

## Prevention Mechanisms

1. **Feature Quality Validation (Phase 3):** Logs warnings when critical features like `avg_usage_rate_last_7_games` are <10% populated

2. **Feature Source Validation (ML Feature Store):** Logs warnings when Phase 4 composite features are >90% defaults

These will alert us early if similar issues occur in the future.

---

*Session 52 Handoff - Usage Rate Fix*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
