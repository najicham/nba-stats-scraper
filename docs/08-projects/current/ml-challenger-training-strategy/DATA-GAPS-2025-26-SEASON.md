# Data Gaps Analysis: 2025-26 Season

**Date:** 2026-01-31 (Session 60)
**Purpose:** Identify data gaps that need to be filled before training V9 challenger

---

## Executive Summary

**Critical Gap:** BettingPros data only starts Dec 20, 2025 - we're missing Oct 22 - Dec 19 (58 game days).

**Good News:** Odds API has DraftKings data for the entire season, so we can still train on DraftKings lines.

---

## Data Availability Matrix

### Vegas Lines (for Training Labels)

| Source | Bookmaker | Date Range | Days | Records | Status |
|--------|-----------|------------|------|---------|--------|
| Odds API | DraftKings | Oct 22 - Jan 31 | ~100 | 39,901 | ✅ COMPLETE |
| BettingPros | DraftKings | Dec 20 - Jan 31 | 37 | 77,323 | ⚠️ PARTIAL |
| BettingPros | Consensus | Dec 20 - Jan 31 | 38 | 93,884 | ⚠️ PARTIAL |

**Recommendation:** Use Odds API DraftKings for Oct-Dec training, supplement with BettingPros from Dec 20+.

---

### Game Lines (Spreads/Totals for Context Features)

| Month | Scheduled Games | Games with Lines | Coverage | Status |
|-------|-----------------|------------------|----------|--------|
| Oct 2025 | 80 | 80 | 100% | ✅ COMPLETE |
| Nov 2025 | 219 | 219 | 100% | ✅ COMPLETE |
| Dec 2025 | 198 | 198 | 100% | ✅ COMPLETE |
| Jan 2026 | 232 | 163 | 70% | ⚠️ Month in progress |

**Status:** All historical game lines complete (Oct-Dec 100%).

---

### Feature Store (ML Features)

| Month | Feature Records | Avg Quality | Status |
|-------|-----------------|-------------|--------|
| Oct 2025 | 0 | N/A | ⏭️ Bootstrap period (by design) |
| Nov 2025 | 6,563 | 78.7 | ✅ OK (starts Nov 4) |
| Dec 2025 | 6,873 | 83.1 | ✅ OK |
| Jan 2026 | 8,567 | 82.5 | ✅ OK |

**Note:** Oct 2025 is intentionally empty. The 2025-26 season started Oct 21, and the first 14 days (Oct 21 - Nov 3) are the "bootstrap period" where players lack sufficient historical data for reliable feature generation. Feature store correctly starts Nov 4.

---

### Phase 3 Context (Pre-game Context)

| Month | Records | With Points Line | With Game Spread | Status |
|-------|---------|------------------|------------------|--------|
| Oct 2025 | 3,116 | 525 (17%) | 0 (0%) | 🔴 CRITICAL |
| Nov 2025 | 8,794 | 2,281 (26%) | 0 (0%) | 🔴 CRITICAL |
| Dec 2025 | 9,232 | 4,067 (44%) | 9,112 (99%) | ✅ OK |
| Jan 2026 | 9,595 | 4,288 (45%) | 6,956 (73%) | ⚠️ PARTIAL |

**Critical Gap:** Oct-Nov context has NO game spreads - features were missing.

---

### Player Outcomes (Actual Points)

| Month | Player Games | With Points | Coverage |
|-------|--------------|-------------|----------|
| Oct 2025 | 1,566 | 1,566 | 100% ✅ |
| Nov 2025 | 8,099 | 5,185 | 64% ⚠️ |
| Dec 2025 | 7,142 | 4,495 | 63% ⚠️ |
| Jan 2026 | 7,859 | 4,806 | 61% ⚠️ |

**Note:** ~60-65% coverage is normal - only players with significant minutes get included.

---

## Data Gaps to Fix

### Priority 1: Complete Historical Game Lines Scrape ✅ DONE
- **What:** Oct 22 - Nov 13 game lines
- **Status:** ✅ COMPLETE (Session 60)
- **Coverage:** Oct 100% (80/80), Nov 100% (219/219), Dec 100% (198/198)

### ~~Priority 2: Backfill Oct 2025 Feature Store~~ ❌ NOT NEEDED
- **Status:** RESOLVED - Oct 2025 is within bootstrap period (first 14 days of season)
- **Why:** Season started Oct 21. Bootstrap ends Nov 3. Feature store correctly starts Nov 4.
- **Training Impact:** None - bootstrap period data excluded from ML training by design

### Priority 3: Reprocess Oct-Nov Phase 3 Context with Game Lines 🔄 IN PROGRESS
- **What:** Re-run Phase 3 for Oct-Nov with the new game lines
- **Status:** Backfill running (Session 61)
- **Command:** `python backfill_jobs/analytics/upcoming_player_game_context/*.py --start-date 2025-10-01 --end-date 2025-11-30 --parallel`
- **Progress:** Oct at ~25%, Nov at 0% (processing...)

### Priority 4: Verify Jan 2026 Game Lines
- **What:** Check recent days for missing lines
- **How:** Run `/validate-scraped-data` for Jan 2026

---

## Training Data Options

### Option A: Use Odds API DraftKings Only
**Pros:**
- Full season coverage (Oct - Jan)
- ~40K records available
- Single source consistency

**Cons:**
- Lower volume than BettingPros
- May miss some players

**Training Query:**
```sql
SELECT p.*, o.line as vegas_line
FROM player_outcomes p
JOIN odds_api_player_points_props o
  ON p.player_lookup = o.player_lookup
  AND p.game_id = o.game_id
WHERE LOWER(o.bookmaker) = 'draftkings'
```

### Option B: Odds API Oct-Nov + BettingPros Dec+
**Pros:**
- Maximum data coverage
- Uses best source for each period

**Cons:**
- Mixed sources may have calibration differences
- Need to verify line consistency

### Option C: BettingPros Only (Dec 20 - Jan 31)
**Pros:**
- Higher volume (77K+ records)
- Consistent source
- More recent data

**Cons:**
- Only 42 days of data
- May not be enough for robust training

---

## Recommended Action Plan

```
1. ⏳ Wait for historical scraper to complete (~10 min)
2. 📥 Process scraped data to BigQuery
3. 🔄 Backfill Oct 2025 feature store
4. 🔄 Reprocess Oct-Nov Phase 3 context
5. ✅ Verify data coverage with /validate-scraped-data
6. 🧪 Train V9 challenger on Odds API DraftKings
7. 📊 Compare V8 (Consensus) vs V9 (DraftKings) hit rates
```

---

## Verification Queries

### Check Odds API DraftKings Coverage
```sql
SELECT game_date, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2025-10-22'
  AND LOWER(bookmaker) = 'draftkings'
GROUP BY 1
ORDER BY 1
```

### Check Feature Store Coverage After Backfill
```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-10-01'
GROUP BY 1
ORDER BY 1
```

### Check Context Coverage After Reprocess
```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  COUNTIF(current_points_line IS NOT NULL) as with_line,
  COUNTIF(game_spread IS NOT NULL) as with_spread
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2025-10-01'
GROUP BY 1
ORDER BY 1
```

---

*Created: 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
