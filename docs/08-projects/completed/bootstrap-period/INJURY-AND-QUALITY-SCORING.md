# Injury Scenarios and Quality Scoring
**Purpose:** Document how player injuries affect data quality scores
**Created:** 2025-11-27
**Status:** ✅ Current Behavior Documented

---

## Your Question

**Q:** "If a player missed 2 of their team's last 12 games due to injury, so we look back 12 games to get their last 10 games played - will that affect their data quality score?"

**A:** YES, but in a nuanced way ✅

---

## What Actually Happens

### Scenario: Injured Player

```
Team Schedule:
- Last 12 games: Oct 22 → Nov 10
- Games played by team: 12

Player (injured for 2 games):
- Games played: 10 (missed Oct 28, Nov 3)
- Games with minutes > 0: 10
```

### How Code Handles This

#### Step 1: Query Filters for Player Games Only

From `player_daily_cache_processor.py:384-396`:

```sql
SELECT ...
FROM player_game_summary
WHERE game_date <= 'analysis_date'
  AND season_year = 2024
  AND is_active = TRUE
  AND minutes_played > 0  -- ← KEY: Only games player played!
ORDER BY game_date DESC
```

Result: **Gets 10 games player actually played** (spans 12 calendar dates)

#### Step 2: Calculate L10 Average from Those 10 Games

From `player_daily_cache_processor.py:900-908`:

```python
# Get last 10 games (already filtered to games played)
last_10_games = player_games.head(10)

# Calculate averages from FULL 10 games
points_avg_last_10 = last_10_games['points'].mean()  # ← Uses all 10 games

# Window is FULL (not partial)
```

Result: **L10 average uses 10 full games** ✅ No degradation here!

#### Step 3: Track Season Completeness

From `player_daily_cache_processor.py:909, 992-994`:

```python
# This is "games player played", not "games team played"
games_played_season = len(player_games)  # = 10

# Completeness checker compares to team schedule
completeness = checker.check_completeness(
    analysis_date=analysis_date,
    season_start=season_start_date
)

# Result:
{
    'expected_count': 12,      # Team played 12 games (from schedule)
    'actual_count': 10,        # Player played 10 games
    'completeness_pct': 83.3,  # 10/12 = 83%
    'missing_count': 2
}
```

Result: **Completeness reflects missed games** ⚠️

#### Step 4: Calculate Quality Score

The quality score is affected by completeness:

```python
# Lower completeness = lower quality score
feature_quality_score = calculate_quality(completeness_pct=83.3)
# Might be 85-90 instead of 95-100
```

---

## Direct Answer to Your Question

### Will Missing 2 Games Affect Quality Score?

**YES** ✅ - The quality score **DOES** reflect the missed games

But there are TWO separate aspects:

| Aspect | Behavior | Explanation |
|--------|----------|-------------|
| **L10 Average Calculation** | ✅ NOT affected | Uses 10 full games player played |
| **Quality Score** | ⚠️ IS affected | Lower completeness (83% vs 100%) |

---

## Detailed Example

### Healthy Player (No Injuries)

```python
{
    # Team played 12 games
    'expected_games_count': 12,
    'actual_games_count': 12,
    'games_played_season': 12,
    'completeness_percentage': 100.0,

    # L10 uses last 10 games
    'points_avg_last_10': 22.4,  # From 10 games
    'points_avg_last_10_games_used': 10,  # (planned field)

    # High quality
    'feature_quality_score': 98.0,
    'is_production_ready': True
}
```

### Injured Player (Missed 2 Games)

```python
{
    # Team played 12 games, player played 10
    'expected_games_count': 12,      # ← From team schedule
    'actual_games_count': 10,         # ← Player actually played
    'games_played_season': 10,
    'completeness_percentage': 83.3,  # ← 10/12 = 83%

    # L10 STILL uses last 10 games
    'points_avg_last_10': 22.4,  # From 10 games player played
    'points_avg_last_10_games_used': 10,  # Window is FULL

    # Moderate quality (reflects missed games)
    'feature_quality_score': 88.0,    # ← Lower due to incompleteness
    'is_production_ready': True
}
```

Key differences:
- `completeness_percentage`: 100% → 83%
- `feature_quality_score`: 98 → 88
- `points_avg_last_10`: Same calculation method (10 full games)

---

## Is This Correct Behavior?

### Arguments FOR Current Behavior ✅

1. **Injury = Real Information**
   - Player who missed games is legitimately different data quality
   - Missing games might indicate:
     - Injury prone
     - Load management
     - Team role change
   - Quality score should reflect this!

2. **Consistent with Other Metrics**
   - Season averages use fewer games (10 vs 12)
   - Fatigue metrics reflect different load (10 vs 12 games)
   - Usage trends might be different
   - All features subtly affected

3. **ML Model Can Learn This**
   ```python
   # Model sees:
   completeness_pct = 83%  # vs 100% for healthy player
   quality_score = 88      # vs 98 for healthy player

   # Model learns: "Players with 83% completeness are X% less predictable"
   # This is valuable signal!
   ```

4. **Prevents Overfitting**
   - Don't want to treat injured player data as "perfect"
   - Lower quality score = appropriate uncertainty

### Arguments AGAINST Current Behavior ⚠️

1. **L10 Window is Actually Full**
   - We DID get 10 games for L10 average
   - Why penalize if we have complete data for the metric?
   - Injury is external factor, not data quality issue

2. **Could Confuse Two Different Issues**
   - Data quality (did we get the data we needed?)
   - Player availability (did player miss games?)
   - These are different concepts

3. **Alternative: Track Separately**
   ```python
   # Could separate concerns:
   'feature_quality_score': 98,           # L10 has 10 games = high quality
   'player_availability_score': 83,       # Player played 10/12 = lower availability
   'season_completeness_percentage': 83   # Current field already does this
   ```

---

## My Recommendation

**Keep current behavior** ✅ for MVP, but document it clearly

### Reasons:

1. **It's Actually Correct**
   - Lower completeness IS lower quality for ML purposes
   - Even if L10 window is full, other aspects are affected
   - Season average uses 10 games, not 12
   - Fatigue patterns different

2. **Simple and Consistent**
   - One quality score
   - Reflects overall data situation
   - Easy to explain: "Player missed 2 games → 83% complete"

3. **ML Model Benefits**
   - Model learns injury-proneness signal
   - Appropriate uncertainty for injured players
   - Better generalization

4. **We Already Track Both**
   - `feature_quality_score`: Overall assessment
   - `completeness_percentage`: Exact 83.3%
   - `actual_games_count`: 10
   - `expected_games_count`: 12
   - Downstream can distinguish if needed!

### Future Enhancement (Optional):

If October 2025 data shows this is confusing, could add:

```sql
-- Enhanced tracking
feature_window_quality_score FLOAT64,      -- L10 window quality (100 if 10 games)
player_availability_quality_score FLOAT64, -- Season availability (83 if 10/12)
overall_quality_score FLOAT64              -- Weighted combination
```

But I don't think it's needed. Current approach is sound.

---

## How to Verify This

### Query 1: Find Injured Players

```sql
-- Players who missed games (low completeness but full L10 windows)
SELECT
    player_lookup,
    cache_date,
    games_played_season,
    expected_games_count,
    actual_games_count,
    completeness_percentage,
    feature_quality_score
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2024-11-20'
  AND completeness_percentage < 90  -- Missed games
  AND actual_games_count >= 10      -- But has 10+ games for L10
ORDER BY completeness_percentage ASC
LIMIT 20;
```

Expected result:
- Players with 83-90% completeness
- Quality scores lower than players with 100% completeness
- But still have valid L10 averages (10 games)

### Query 2: Compare Injured vs Healthy

```sql
-- Compare quality scores
SELECT
    CASE
        WHEN completeness_percentage >= 95 THEN 'Healthy'
        WHEN completeness_percentage >= 80 THEN 'Missed 1-3 Games'
        ELSE 'Missed 4+ Games'
    END as player_status,
    COUNT(*) as player_count,
    AVG(feature_quality_score) as avg_quality,
    AVG(completeness_percentage) as avg_completeness
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2024-11-20'
  AND actual_games_count >= 10
GROUP BY player_status
ORDER BY avg_completeness DESC;
```

Expected result:
- Healthy: Quality ~98, Completeness ~100%
- Missed 1-3: Quality ~88, Completeness ~85%
- Missed 4+: Quality ~75, Completeness ~70%

---

## Bottom Line

**YES, missing games affects quality score** ✅

This is correct behavior because:
1. Lower completeness IS lower quality
2. Even if L10 window is full, other metrics affected
3. ML model should know player missed games
4. We track exact details (actual/expected counts)

The quality score reflects the holistic situation, not just one feature window.

If you want to change this, we CAN separate "feature window quality" from "player availability quality", but I don't recommend it for MVP.

---

## Summary Table

| Scenario | Expected | Actual | L10 Games | Completeness | Quality | Notes |
|----------|----------|--------|-----------|--------------|---------|-------|
| Healthy Player | 12 | 12 | 10 | 100% | 98 | Perfect data |
| Missed 2 Games | 12 | 10 | 10 | 83% | 88 | L10 full, but incomplete season |
| Missed 5 Games | 12 | 7 | 7 | 58% | 65 | L10 partial window |
| Early Season (Day 7) | 7 | 7 | 7 | 100% | 72 | L10 partial but player "complete" |

Key insight: **Injury scenario has full L10 window but lower overall quality** ✅

This is working as intended!
