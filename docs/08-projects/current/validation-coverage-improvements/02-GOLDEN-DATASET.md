# Golden Dataset - Calculation Verification

**Priority**: P2
**Effort**: 6-8 hours
**Status**: Investigation

---

## Problem Statement

We currently trust that processors calculate values correctly. There's no verification that:
- Rolling averages (L5, L10, L15, L20) are computed correctly
- Usage rate calculations are accurate
- Feature store values match expectations

If a calculation bug is introduced, we'd only catch it through manual inspection.

---

## Proposed Solution

Create a "golden dataset" - a small set of manually-verified player-dates that we recalculate from source and compare against cached values.

### Golden Dataset Criteria

Select 10-20 player-dates that cover:
- High-volume players (LeBron, Curry, etc.)
- Edge cases (first game of season, after injury return)
- Different game types (home/away, back-to-back)
- Recent dates (within last 30 days)

### Verification Process

```python
# Pseudo-code for golden dataset verification
for player_date in golden_dataset:
    # 1. Fetch raw box scores for player's last 20 games
    raw_games = query_raw_boxscores(player, last_20_games)
    
    # 2. Calculate expected rolling averages
    expected_l5 = calculate_l5_average(raw_games)
    expected_l10 = calculate_l10_average(raw_games)
    
    # 3. Fetch cached values from analytics table
    actual = query_player_game_summary(player, date)
    
    # 4. Compare with tolerance
    if abs(expected_l5 - actual.pts_l5) > 0.1:
        alert("L5 points mismatch", player, date, expected_l5, actual.pts_l5)
```

---

## Implementation Plan

### Step 1: Create Golden Dataset Table
```sql
CREATE TABLE nba_reference.golden_dataset (
  player_id INT64,
  player_name STRING,
  game_date DATE,
  -- Expected values (manually calculated/verified)
  expected_pts_l5 FLOAT64,
  expected_pts_l10 FLOAT64,
  expected_usage_rate FLOAT64,
  -- Metadata
  verified_by STRING,
  verified_at TIMESTAMP,
  notes STRING
);
```

### Step 2: Create Verification Script
```python
# scripts/verify_golden_dataset.py
# Runs daily, compares cached vs expected values
```

### Step 3: Integrate with /validate-daily
Add golden dataset check to daily validation.

---

## Investigation Questions

1. Which players/dates should be in the golden dataset?
2. What's the acceptable tolerance for each metric? (0.1? 1%?)
3. Should we recalculate expected values daily or store static?
4. How do we handle new players added to roster mid-season?
5. What's the process for updating golden dataset when schema changes?

---

## Success Criteria

- [ ] Golden dataset with 20+ verified player-dates
- [ ] Daily verification runs without false positives
- [ ] Calculation bugs caught before reaching production
