# Session 128 - Daily Validation Issues Investigation

**Date:** 2026-02-05
**Game Date Validated:** 2026-02-04

## Executive Summary

Comprehensive daily validation revealed multiple critical issues affecting data quality and prediction accuracy. Root cause analysis identified bugs in change detection, odds processing, and cache generation.

## Issues Discovered

### 1. Missing Games in Analytics (P1 CRITICAL)

**Symptom:** 5/7 games processed, CLE_LAC and MEM_SAC missing from `player_game_summary`

**Root Cause:** Source mismatch in incremental change detection
- Change detection queries `bdl_player_boxscores`
- Extraction queries `nbac_gamebook_player_stats`
- When BDL data arrives late, players in gamebook but not in BDL are excluded

**Impact:**
- 2 games missing from analytics
- 170 predictions ungradable (46% of total)
- Incomplete daily grading

**Fix:**
1. Immediate: Reprocess Feb 4 with `force_full_batch=true`
2. Long-term: Align change detection source with extraction source

**Files Involved:**
- `shared/change_detection/change_detector.py` - Uses BDL as reference
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Extracts from gamebook

---

### 2. Edge Filter Bug in OddsAPI Processor (P1 CRITICAL)

**Symptom:** 78 predictions have OVER/UNDER recommendation but LOW edge (<3)

**Root Cause:** `oddsapi_batch_processor.py` updates predictions with new Vegas lines but doesn't set `is_actionable=FALSE` for low-edge predictions

**Location:** `data_processors/raw/oddsapi/oddsapi_batch_processor.py` lines 500-504

**Current Code:**
```sql
recommendation = CASE
    WHEN pred.predicted_points - lines.points_line > 2.0 THEN 'OVER'
    WHEN lines.points_line - pred.predicted_points > 2.0 THEN 'UNDER'
    ELSE 'HOLD'
END,
```

**Missing:** `is_actionable = FALSE` when edge < 3

**Impact:** Users may bet on unprofitable low-edge predictions

**Fix:** Add `is_actionable` and `filter_reason` to the UPDATE query

---

### 3. DNP Pollution in Player Daily Cache (P2 HIGH)

**Symptom:** 12 DNP-only players in cache for Feb 4

**Root Cause:** Session 123 fix filters DNP games but doesn't filter stale players (no active game in 30-90 days)

**Affected Players:**
- Taurean Prince (92 days since active)
- Bradley Beal (88 days)
- Zach Edey (59 days)
- Jakob Poeltl (45 days)
- Cameron Johnson (43 days)
- And 6 more...

**Impact:** Stale "last 10" averages (1-3 months old) produce unreliable predictions

**Fix:** Add recency filter - skip players with no active game in last 30 days

**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

---

### 4. Model Bias (P2 - HANDLED BY ANOTHER SESSION)

**Symptom:**
- Stars (25+ pts): -9.7 pts bias
- 6:1 UNDER skew in high-edge picks
- 42.5% hit rate (below 55% threshold)

**Root Cause:** Model follows Vegas too closely, no tier features

**Status:** Being addressed by another chat session (tier calibration)

---

### 5. Vegas Line Coverage at 42.5% (NOT A BUG)

**Finding:** This is expected behavior
- Feature store includes ALL 339 players
- Sportsbooks only offer props for ~150 players
- Effective coverage for 15+ minute players: 80.5%

**Action:** Update monitoring thresholds (alarm at 35%, not 80%)

---

## Data Quality Metrics - Feb 4, 2026

| Metric | Value | Status |
|--------|-------|--------|
| Games scheduled | 7 | - |
| Games in analytics | 5 | ⚠️ 71% |
| Raw data coverage | 7/7 | ✅ 100% |
| Minutes coverage | 58.5% | 🔴 Critical |
| Usage rate coverage | 94.7-100% | ✅ Good |
| Predictions graded | 200/370 | ⚠️ 54% |
| Hit rate | 42.5% | 🔴 Below target |
| DNP pollution | 12 players | ⚠️ 5.5% |
| BDB coverage | 100% | ✅ Good |

## Fix Priority

| Priority | Issue | Owner |
|----------|-------|-------|
| P1 | Reprocess missing games | This session |
| P1 | Fix oddsapi edge filter | This session |
| P2 | Add DNP recency filter | This session |
| P2 | Model tier calibration | Other session |
| P3 | Align change detection sources | Future |

## Related Documentation

- Session 102: Original edge filter implementation
- Session 123: DNP pollution fix (incomplete)
- `docs/08-projects/current/feature-mismatch-investigation/` - Model bias analysis
