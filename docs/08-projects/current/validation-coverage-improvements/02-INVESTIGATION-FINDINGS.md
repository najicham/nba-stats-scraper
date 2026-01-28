# Golden Dataset - Investigation Findings

**Investigated**: 2026-01-28
**Status**: Ready for Implementation

---

## Key Finding: Clear Path Forward

The calculation logic is simple (pandas `.mean()`), making verification straightforward. No existing golden dataset tests exist - this is a gap we can fill.

---

## 1. Tables with Rolling Averages

**nba_precompute.player_daily_cache** (primary):
- `points_avg_last_5` (NUMERIC(5,1))
- `points_avg_last_10` (NUMERIC(5,1))
- `points_avg_season` (NUMERIC(5,1))
- Also: `minutes_avg_last_10`, `usage_rate_last_10`, `ts_pct_last_10`

**Note**: L15 and L20 averages are NOT in the current schema. Only L5, L10, and season.

---

## 2. Raw Source Tables

| Table | Coverage | Notes |
|-------|----------|-------|
| `nba_raw.nbac_gamebook_player_stats` | 95% | Has plus_minus |
| `nba_raw.bdl_player_boxscores` | 100% | Fallback source |
| `nba_raw.nbac_player_boxscores` | Alternative | NBA.com direct |

---

## 3. How Averages Are Calculated

**File**: `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py`

```python
# Games sorted descending by date
last_5_games = player_games.head(5)
last_10_games = player_games.head(10)

# Simple mean, rounded to 4 decimals
points_avg_last_5 = round(float(last_5_games['points'].mean()), 4)
points_avg_last_10 = round(float(last_10_games['points'].mean()), 4)
```

**Key**: Simple pandas mean - no complex windowing or weighting.

---

## 4. Existing Tests

**Property tests exist** but no golden dataset verification:
- `tests/property/test_aggregation_properties.py` - Sum invariants
- `tests/property/test_calculation_invariants.py` - Statistical bounds
- `tests/processors/precompute/player_daily_cache/test_unit.py`

**Gap**: No tests verifying L5/L10 against manually computed values.

---

## 5. Recommended Golden Dataset Players

| Player | Reason |
|--------|--------|
| LeBron James | High-volume, consistent |
| Stephen Curry | High-volume, 3PT specialist |
| Luka Doncic | High usage, triple-double threat |
| Giannis Antetokounmpo | Paint-heavy scorer |
| Joel Embiid | High-volume big man |
| Jayson Tatum | Versatile scorer |

**Selection Criteria:**
- Play most games (reliable data)
- High minutes (starters/stars)
- Mix of scoring styles
- Consistent prop market availability

---

## 6. Tolerance Recommendation

**0.1 points tolerance**

**Justification:**
- Rounding is to 4 decimal places
- Display precision is 1 decimal place
- 0.1 over 5 games = 0.02 ppg difference (negligible)
- Catches real errors, avoids false positives

---

## 7. Implementation Plan

1. Create `nba_reference.golden_dataset` table with 10-20 player-dates
2. Create `scripts/verify_golden_dataset.py`:
   - Query raw boxscores for player's last N games
   - Calculate expected L5/L10 averages
   - Compare to `player_daily_cache` values
   - Alert if difference > 0.1
3. Add to `/validate-daily` workflow
4. Run daily as part of validation suite
