# Session 59 Handoff - Odds Data Investigation (For Continuation)

**Date:** 2026-01-31
**Status:** Investigation complete, implementation needed
**Priority:** P1 - Affects ML training and betting accuracy

---

## Context for New Session

This session investigated why the ML feature store had missing Vegas line data. The investigation uncovered deeper questions about which data source to use for training and grading.

**Key project doc:** `docs/08-projects/current/odds-data-cascade-investigation/README.md`

### Key Decision Made

**Use BettingPros DraftKings as fallback for Odds API DraftKings.** This adds 15% more coverage (2,400 player/games per season) while keeping all lines DraftKings-consistent.

---

## Summary of Findings

### 1. V8 Model Was Trained on BettingPros Consensus

```python
# ml/train_final_ensemble_v8.py line 62-63
FROM `nba_raw.bettingpros_player_points_props`
WHERE bookmaker = 'BettingPros Consensus'
```

V8 was NOT trained on DraftKings lines. It was trained on BettingPros Consensus (an aggregate of multiple books).

### 2. Data Source Comparison (V8 Training Period: Nov 2021 - Jun 2024)

| Source | DraftKings Records | Date Range |
|--------|-------------------|------------|
| Odds API | 30,296 | May 2023 - Jun 2024 only |
| BettingPros | 104,196 | May 2022 - Jun 2024 |

**Why the 3x difference:**
1. Odds API DraftKings data only starts May 2023 (no earlier history)
2. BettingPros stores both `over` and `under` bet sides (2x records)
3. BettingPros has 4 snapshots/day vs Odds API's 2 snapshots/day
4. BettingPros covers 294 unique players vs Odds API's 252

### 3. BettingPros Has Individual Sportsbook Data

BettingPros is NOT just an aggregate. It has lines from specific books:

| Bookmaker | Records (Dec 2025+) |
|-----------|---------------------|
| BettingPros Consensus | 179,932 |
| DraftKings | 149,902 |
| FanDuel | 155,072 |
| BetMGM | 143,254 |
| Caesars | 154,400 |
| + 15 more books | |

### 4. Current Tracking Gaps

| What | Where Tracked | Gap |
|------|---------------|-----|
| Bookmaker in raw data | ✅ Both sources | None |
| Bookmaker in Phase 3 | ✅ `current_points_line_source` | None |
| Bookmaker in predictions | ❌ Only "ACTUAL_PROP" | **Missing** |
| Snapshot time | ✅ Raw tables only | Not propagated |

---

## Questions That Need Investigation

### Q1: Should we train on DraftKings-only lines?

**Current state:** V8 trained on BettingPros Consensus
**Consideration:** Users bet on DraftKings, so model should be calibrated to DK lines

**Options:**
- Use BettingPros DraftKings data (104K records, goes back to 2022)
- Use Odds API DraftKings data (30K records, only from May 2023)
- Continue with Consensus (largest dataset, but may not match DK exactly)

**To investigate:**
- How different are Consensus lines from DraftKings lines?
- Does hit rate vary by bookmaker?

### Q2: Do hit rates differ by bookmaker?

**Blocked by:** `prediction_accuracy` table doesn't track bookmaker

**To fix:**
1. Add `line_bookmaker` column to `prediction_accuracy` schema
2. Backfill with bookmaker data from Phase 3
3. Query hit rates grouped by bookmaker

### Q3: Why does BettingPros have more data?

**Answered:**
- Stores both over/under (2x)
- More frequent snapshots (4 vs 2 per day)
- More player coverage (294 vs 252)
- Longer history (2022 vs 2023 for DraftKings)

### Q4: What cascade priority should we use?

**DECIDED - Implement this cascade:**
```
1. Odds API DraftKings      ← Primary (most real-time)
2. BettingPros DraftKings   ← Fills 15% coverage gap
3. Odds API FanDuel         ← If no DK anywhere
4. BettingPros FanDuel      ← Fallback
5. BettingPros Consensus    ← Last resort only
```

**Currently:** No explicit DK > FD priority, and BettingPros DK not used as fallback.

### Q5: How much extra coverage does BettingPros DraftKings provide?

**ANSWERED (2024-25 Season, apples-to-apples comparison):**

| Metric | Odds API DK | BettingPros DK | Difference |
|--------|-------------|----------------|------------|
| Unique player/games | 15,855 | 18,254 | **+15%** |
| Unique players | 383 | 413 | +30 |

| Overlap | Player/Games |
|---------|-------------|
| In BOTH sources | 14,754 (93%) |
| Only in Odds API | 1,101 |
| Only in BettingPros | 3,500 |

**Conclusion:** BettingPros DraftKings captures ~2,400 more player/games (bench players) that Odds API misses. Using it as fallback gives DraftKings-consistent lines with maximum coverage.

---

## Fixes Applied This Session

### 1. Feature Store Cascade ✅

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Changed to read from `upcoming_player_game_context` (Phase 3) instead of querying `bettingpros_player_points_props` directly. This inherits the Phase 3 cascade.

### 2. Backfill Script ✅

**File:** `scripts/backfill_feature_store_vegas.py`

```bash
# Dry run
PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31 --dry-run

# Execute
PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31
```

Can fix ~3,500 records from Nov-Dec 2025 with missing Vegas data.

---

## Recommended Next Steps

### Priority 1: Implement New Cascade in betting_data.py

**File:** `data_processors/analytics/upcoming_player_game_context/betting_data.py`

**Goal:** Implement this cascade for player props:
```
1. Odds API DraftKings
2. BettingPros DraftKings  ← NEW
3. Odds API FanDuel
4. BettingPros FanDuel
5. BettingPros Consensus
```

**Implementation approach:**
1. Modify `extract_prop_lines_from_odds_api()` to prefer DraftKings over FanDuel
2. Modify `extract_prop_lines_from_bettingpros()` to prefer DraftKings over FanDuel over Consensus
3. Ensure Phase 3 tries Odds API DK first, then BettingPros DK, before moving to FD

**SQL pattern to add:**
```sql
ORDER BY
  CASE bookmaker
    WHEN 'draftkings' THEN 1
    WHEN 'DraftKings' THEN 1
    WHEN 'fanduel' THEN 2
    WHEN 'FanDuel' THEN 2
    ELSE 99  -- Consensus and others
  END,
  snapshot_timestamp DESC
```

### Priority 2: Add Bookmaker to Grading

1. **Schema change:** Add `line_bookmaker STRING` to `prediction_accuracy`
2. **Populate from:** `upcoming_player_game_context.current_points_line_source`
3. **Query example:**
   ```sql
   SELECT line_bookmaker,
          ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as hit_rate
   FROM prediction_accuracy
   WHERE prediction_correct IS NOT NULL
   GROUP BY 1
   ```

### Priority 3: Run Backfill Script

```bash
# Fix Oct-Nov 2025 feature store data
PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31 --dry-run
PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31
```

### Priority 4: Investigate Exactly What V8 Trained On

**Question:** Did V8 train only on BettingPros Consensus, or did it also include DraftKings/FanDuel lines?

**What we know:**
- `ml/train_final_ensemble_v8.py` line 63 filters: `WHERE bookmaker = 'BettingPros Consensus'`
- But we should verify this is what actually ran

**Investigation needed:**
1. Check if there's a training log or metadata file from V8 training
2. Look for `models/ensemble_v8_*_metadata.json` - may have training details
3. Query the actual data that would have been used:
   ```sql
   -- What was available for V8 training period?
   SELECT bookmaker, COUNT(*) as records
   FROM nba_raw.bettingpros_player_points_props
   WHERE game_date BETWEEN '2021-11-01' AND '2024-06-01'
     AND market_type = 'points' AND bet_side = 'over'
   GROUP BY 1
   ORDER BY 2 DESC
   ```
4. Check if the training script was ever modified to use different bookmakers
5. Determine if we can reproduce V8's exact training data

**Why this matters:**
- If V8 trained on Consensus but users bet on DraftKings, there may be calibration mismatch
- Understanding V8's training helps decide V9 approach
- May explain some hit rate variance

### Priority 5: Consider V9 Training on DraftKings Only

Once we understand V8's training data, consider training V9 on DraftKings-only lines to match what users actually bet on.

---

## Key Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/odds-data-cascade-investigation/README.md` | Full project documentation |
| `docs/05-development/model-comparison-v8-vs-monthly-retrain.md` | V8 vs retrain analysis |
| `ml/train_final_ensemble_v8.py` | V8 training script (uses BettingPros Consensus) |
| `data_processors/analytics/upcoming_player_game_context/betting_data.py` | Phase 3 betting cascade |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Feature store (now fixed) |
| `scripts/backfill_feature_store_vegas.py` | Backfill script for Oct-Nov 2025 |

---

## Schema Reference

### odds_api_player_points_props

```sql
player_lookup STRING
game_date DATE
game_id STRING
bookmaker STRING  -- 'draftkings' or 'fanduel'
points_line FLOAT64
over_price FLOAT64
under_price FLOAT64
snapshot_timestamp TIMESTAMP
minutes_before_tipoff INT64
```

### bettingpros_player_points_props

```sql
player_lookup STRING
game_date DATE
market_type STRING  -- 'points', 'assists', etc.
bet_side STRING  -- 'over' or 'under'
bookmaker STRING  -- 'DraftKings', 'FanDuel', 'BettingPros Consensus', etc.
points_line FLOAT64
opening_line FLOAT64
is_best_line BOOL
is_active BOOL
bookmaker_last_update TIMESTAMP
```

### upcoming_player_game_context (Phase 3)

```sql
current_points_line NUMERIC(4,1)
opening_points_line NUMERIC(4,1)
line_movement NUMERIC(4,1)
current_points_line_source STRING  -- 'odds_api', 'bettingpros', 'draftkings', etc.
has_prop_line BOOL
```

### prediction_accuracy (Grading)

```sql
line_value NUMERIC(5,1)
line_source STRING  -- Currently only 'ACTUAL_PROP' or 'NO_PROP_LINE'
-- MISSING: line_bookmaker (needs to be added)
```

---

## Investigation Queries

### Compare Consensus vs DraftKings Lines
```sql
-- How different are Consensus lines from DraftKings?
WITH lines AS (
  SELECT game_date, player_lookup,
    MAX(CASE WHEN bookmaker = 'BettingPros Consensus' THEN points_line END) as consensus,
    MAX(CASE WHEN bookmaker = 'DraftKings' THEN points_line END) as draftkings
  FROM nba_raw.bettingpros_player_points_props
  WHERE market_type = 'points' AND bet_side = 'over'
    AND game_date >= '2025-12-20'
  GROUP BY 1, 2
  HAVING consensus IS NOT NULL AND draftkings IS NOT NULL
)
SELECT
  COUNTIF(consensus = draftkings) as exact_match,
  COUNTIF(ABS(consensus - draftkings) <= 0.5) as within_half_point,
  COUNTIF(ABS(consensus - draftkings) > 1) as more_than_1pt_diff,
  COUNT(*) as total
FROM lines
```

### Check Odds API DraftKings Historical Coverage
```sql
-- When did Odds API start collecting DraftKings data?
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players
FROM nba_raw.odds_api_player_points_props
WHERE bookmaker = 'draftkings'
GROUP BY 1
ORDER BY 1
LIMIT 20
```

---

## Commits This Session

```
f9bdf678 docs: Add V8 vs monthly retrain deep dive analysis
f744a932 docs: Add odds data cascade investigation project doc
bde97bd7 feat: Fix feature store to use Phase 3 cascade for Vegas lines
6f7131b6 docs: Add Session 59 handoff - Odds cascade investigation
```

---

## Summary for Continuation

### What's Done
1. ✅ **Feature store fixed** - Now reads from Phase 3 (inherits cascade)
2. ✅ **Investigation complete** - BettingPros DK has 15% more coverage than Odds API DK
3. ✅ **Decision made** - Use BettingPros DraftKings as fallback for Odds API DraftKings
4. ✅ **Backfill script ready** - `scripts/backfill_feature_store_vegas.py`

### What Needs Implementation
1. **Implement new cascade in betting_data.py** - DK priority + BettingPros DK as fallback
2. **Add bookmaker to prediction_accuracy** - For per-book hit rate analysis
3. **Run backfill script** - Fix Oct-Nov 2025 data
4. **Consider V9 on DraftKings** - V8 used Consensus

### Key Insight
BettingPros DraftKings provides 2,400 extra player/games per season (15% more coverage) that Odds API misses. These are real DraftKings lines, so using them as fallback keeps predictions DraftKings-consistent while maximizing coverage.

---

*Session 59 Complete - Ready for Continuation*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
