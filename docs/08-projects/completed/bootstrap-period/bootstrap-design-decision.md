# Bootstrap Period Design - Complete Decision Document

**Date:** 2025-11-27
**Status:** Design Phase - Awaiting Decision
**Project:** NBA Props Platform - Rolling Average Bootstrap Handling

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Current System Behavior](#current-system-behavior)
4. [Design Considerations](#design-considerations)
5. [Proposed Solutions](#proposed-solutions)
6. [Recommended Approach](#recommended-approach)
7. [Implementation Plan](#implementation-plan)
8. [Edge Cases & Gray Areas](#edge-cases--gray-areas)
9. [Decision Required](#decision-required)

---

## Executive Summary

### The Core Problem

When calculating rolling averages (e.g., "last 10 games average"), there are periods where insufficient data exists:
- **Early season**: October 22-25, 2024 → only 1-3 games available, need 10
- **Historical backfill**: 2021-10-19 (data epoch) → only 1 game available
- **Rookies**: First NBA season → no prior data
- **Trades/Injuries**: Player returns → limited recent data

### The Critical Question

**Should rolling averages use prior season data or only current season data?**

**Example:** October 25, 2024 (3 games into new season)
- **Option A (Cross-Season):** Use 3 current + 7 prior season games = 10 games total
- **Option B (Current Season Only):** Use only 3 current season games = insufficient data

### Current System: INCONSISTENT

Different processors handle this differently:
- **ML Feature Store (Phase 3 fallback):** ✅ Uses cross-season data
- **Player Daily Cache:** ❌ Uses current season only
- **Shot Zone Analysis:** ❌ Uses current season only
- **Team Defense:** ❌ Uses current season only

**Result:** When Daily Cache has insufficient data, ML Feature Store falls back to Phase 3, which uses different data = inconsistent features!

### User's Key Concerns

1. **Current season is a better indicator** than prior season (role changes, age, new team, etc.)
2. **Some stats benefit from cross-season** (shooting %, tendencies) more than others (volume stats)
3. **Need to track metadata** about how each average was calculated (for confidence scoring)
4. **Injured games should be excluded** but tracked
5. **Gray areas exist:** What if need 30 games but only 29 in current season? Include 1 prior game or use 29?

---

## Problem Statement

### What is a Rolling Average?

```python
points_avg_last_10 = mean(last 10 games)

# October 25, 2024 (3 games into new season)
# Question: What are "last 10 games"?

Option A: Last 10 chronologically (7 from April 2024 playoffs + 3 from Oct 2024)
Option B: Last 10 from current season only (only 3 available → insufficient)
Option C: Return NULL (wait until 10 current season games available)
```

### Why This Matters

**Impact on Predictions:**
- **Phase 4 processors** calculate rolling averages for ML features
- **Phase 5 predictions** depend on these features
- **NULL features** = no predictions = poor user experience
- **Wrong features** = bad predictions = user loses money

### Bootstrap Periods (When Problem Occurs)

| Period | Duration | Frequency | Affected Players |
|--------|----------|-----------|------------------|
| **Season Start** | Oct 22 - Nov 12 (~3 weeks) | Every year | All players |
| **Historical Epoch** | 2021-10-19 - 2021-11-08 | One time (backfill) | All players |
| **Rookie First Games** | First 10 games | Every season | ~60 rookies |
| **Trade** | First 10 games with new team | Varies | ~50-100 players/year |
| **Injury Return** | First 10 games back | Varies | ~200-300 instances/year |

---

## Current System Behavior

### Investigation Findings

**File: `ml_feature_store/feature_extractor.py:328-355`**
```python
def _query_last_n_games(self, player_lookup: str, game_date: date, n: int):
    """Query last N games for a player."""
    query = f"""
    SELECT game_date, points, minutes_played, ...
    FROM `{self.project_id}.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{game_date}'
    ORDER BY game_date DESC
    LIMIT {n}
    """
```
**No season filter! Uses cross-season data.**

**File: `player_daily_cache_processor.py:335-368`**
```python
def _extract_player_game_data(self, analysis_date: date, season_year: int):
    query = f"""
    SELECT ...
    FROM `{self.project_id}.nba_analytics.player_game_summary`
    WHERE game_date <= '{analysis_date.isoformat()}'
      AND season_year = {season_year}  # ← FILTERS TO CURRENT SEASON
      AND is_active = TRUE
    """
```
**Has season filter! Uses current season only.**

**File: `player_shot_zone_analysis_processor.py:269`**
```python
query = f"""
SELECT ...
WHERE game_date >= '{season_start_date}'  # ← CURRENT SEASON ONLY
  AND game_date < '{analysis_date}'
"""
```
**Has season filter! Uses current season only.**

### The Inconsistency

**October 25, 2024 (3 games into season):**

| Processor | Data Used | Result |
|-----------|-----------|--------|
| ML Feature Store (Phase 3 fallback) | 7 playoff games (Apr 2024) + 3 current (Oct 2024) | `points_avg_last_10 = 26.8` |
| Player Daily Cache | 3 current season games only | `points_avg_last_10 = NULL` (insufficient) |
| Shot Zone Analysis | 3 current season games only | `paint_rate_last_10 = NULL` (insufficient) |

**Problem:** Different processors produce different results for same metric!

---

## Design Considerations

### Basketball Context: Why Current Season Might Be Better

**Changes Between Seasons:**

1. **Role Changes**
   - Traded to new team (different system, usage)
   - Starter → Bench or vice versa
   - Coach change (new offensive philosophy)
   - Lost/gained star teammate (usage rate shift)

2. **Player Changes**
   - Age/decline (especially 30+ players)
   - Injury recovery (came back different)
   - Weight/fitness changes
   - Contract motivation (contract year vs post-max)

3. **Context Changes**
   - Playoff intensity ≠ regular season intensity
   - Rules changes (rare but happens)
   - Team personnel changes

**Example: Russell Westbrook**
```
April 2023 (Lakers): 18.5 ppg, starter
October 2023 (Clippers): 11.1 ppg, bench role

Cross-season L10: 17 ppg (WRONG - inflated by prior role)
Current season L10: 11 ppg (CORRECT - reflects new role)
```

### Basketball Context: Why Cross-Season Might Be Better

**Stable Attributes:**

1. **Skill-Based Stats**
   - Shooting percentages (FG%, 3P%, FT%)
   - Shot tendencies (paint vs perimeter)
   - Passing ability (assist rate)

2. **Physical Attributes**
   - Athletic ability (doesn't change overnight)
   - Size/reach (defensive metrics)
   - Speed/quickness

3. **Recent Form**
   - Hot/cold shooting streaks
   - Confidence level
   - Health/fitness

**Example: Steph Curry**
```
April 2024: 42% from 3PT
October 2024 (3 games): 38% from 3PT

Cross-season L10: 41% from 3PT (BETTER - more stable sample)
Current season L3: 38% from 3PT (NOISY - small sample)
```

### User Requirements (From Discussion)

1. ✅ **Okay with early season predictions** (don't want to wait 3 weeks)
2. ✅ **Need metadata tracking** (know which averages are less accurate)
3. ⚠️ **Prefer current season** but see value in cross-season for some stats
4. ✅ **Exclude injured games** but track exclusions
5. ✅ **Different strategies for different stats** (shooting % vs volume stats)
6. ❓ **Gray areas need clarification** (30 games needed, 29 available - use 1 prior or not?)

---

## Proposed Solutions

### Solution 1: Pure Current Season Only

**Philosophy:** Each season is independent. Never use prior season data.

**Implementation:**
```python
WHERE season_year = {current_season}

# October 25, 2024 (3 games in):
points_avg_last_10 = NULL  # Insufficient data
points_avg_season = 24.3   # Only 3 games

# November 15, 2024 (12 games in):
points_avg_last_10 = 25.1  # Now have enough data
```

**Pros:**
- ✅ No mixing of incompatible data (different roles/teams)
- ✅ Matches user's preference for current season
- ✅ Clean season boundaries
- ✅ Honest about data limitations

**Cons:**
- ❌ **No predictions for 3 weeks every October**
- ❌ Ignores valuable recent data (player didn't fundamentally change)
- ❌ Poor user experience (competitors might have predictions)
- ❌ Affects EVERY season start (recurring problem)

**Bootstrap Impact:** Affects every October + historical epoch

---

### Solution 2: Pure Cross-Season Rolling Window

**Philosophy:** "Last 10 games" means last 10 games, period. No season boundaries.

**Implementation:**
```python
WHERE game_date < '{analysis_date}'
ORDER BY game_date DESC
LIMIT {n}
# NO season filter!

# October 25, 2024 (3 games in):
points_avg_last_10 = 26.8  # 7 from April + 3 from October
points_avg_season = 24.3   # Only current season (different calculation)
```

**Pros:**
- ✅ **No NULL predictions** in early season
- ✅ Smooth transition between seasons
- ✅ Uses all available recent data
- ✅ Matches player's actual recent form
- ✅ Bootstrap only affects 2021-10-19 epoch (one-time)

**Cons:**
- ❌ Mixes playoff/regular season (different intensity)
- ❌ Player's role might have changed over summer
- ❌ Trades not reflected in cross-season averages
- ❌ Doesn't match user's preference for current season

**Bootstrap Impact:** Only 2021-10-19 epoch (one-time historical)

---

### Solution 3: Hybrid - Dual Fields (Both Available)

**Philosophy:** Provide BOTH cross-season and current-season. Let Phase 5 choose.

**Implementation:**
```python
# Two versions of every rolling average
{
  'points_avg_last_10': 26.8,              # Cross-season (7 prior + 3 current)
  'points_avg_last_10_current_only': 24.3, # Current season only (3 games)

  'points_avg_last_10_games_count': 10,
  'points_avg_last_10_current_only_games_count': 3,

  'points_avg_last_10_confidence': 1.0,
  'points_avg_last_10_current_only_confidence': 0.3
}
```

**Pros:**
- ✅ Maximum flexibility (Phase 5 can experiment)
- ✅ Can compare recent form vs current season form
- ✅ No NULL predictions (use cross-season as fallback)
- ✅ Clear confidence scoring for both

**Cons:**
- ❌ **Doubles field count** (25 features → 50+ features)
- ❌ Schema bloat (50-100 new fields)
- ❌ More complex queries
- ❌ Phase 5 needs to decide which to use

**Bootstrap Impact:** Hybrid (cross-season works always, current-season needs bootstrap)

---

### Solution 4: Metadata-Rich Single Approach ⭐ (RECOMMENDED)

**Philosophy:** Use ONE strategy but track rich metadata about HOW each average was calculated.

**Implementation:**
```python
# Single value with metadata
{
  'points_avg_last_10': 26.8,

  # Aggregate metadata (15 fields for entire record)
  'overall_data_confidence': 0.82,
  'min_games_available': 3,
  'max_games_available': 10,
  'uses_prior_season_data': true,
  'prior_season_game_count': 7,
  'bootstrap_mode': 'cross_season_fallback',
  'bootstrap_reason': 'Early season: 3 current + 7 prior season games',
  'is_rookie': false,
  'days_since_season_start': 3,
  'total_games_excluded_injury': 0,
  'has_recent_injury_return': false,
  'days_since_last_game': 2,

  # Selective per-feature metadata (only for key features)
  'points_avg_last_10_games_count': 10,
  'points_avg_last_10_confidence': 0.90,
  'points_avg_last_10_crosses_season': true,
  'points_avg_last_10_calculation_note': '7 Apr playoff + 3 Oct current'
}
```

**Field Count:**
- 25 features (existing)
- 15 aggregate metadata fields
- 16 selective per-feature metadata (4 key features × 4 metadata each)
- **Total: ~56 fields** (vs 100+ for full hybrid)

**Pros:**
- ✅ Tracks everything needed for experimentation
- ✅ Modest schema growth (30-35 new fields)
- ✅ Confidence scoring built-in
- ✅ Can change strategy later without schema changes
- ✅ Phase 5 can filter by confidence threshold
- ✅ Clear traceability for debugging

**Cons:**
- ⚠️ Still need to decide base strategy (cross-season or current-only)
- ⚠️ More complex calculation logic
- ⚠️ Need to define confidence calculation rules

**Bootstrap Impact:** Depends on base strategy chosen

---

## Recommended Approach

### Phase 1: Metadata-Rich Cross-Season Strategy

**Base Strategy:** Use cross-season data (Solution 2) but track everything (Solution 4)

**Why This Combination:**

1. **Predictions available day 1** of every season (good UX)
2. **Metadata lets you filter** low-quality predictions at Phase 5/UI
3. **Can experiment** with different confidence thresholds
4. **Only affects 2021-10-19 epoch** for bootstrap (one-time)
5. **Can change strategy later** without schema migration

**Implementation:**

```python
def calculate_rolling_average(
    player_lookup: str,
    analysis_date: date,
    metric: str,
    window_size: int,
    season_year: int
) -> dict:
    """
    Calculate rolling average with cross-season fallback and rich metadata.
    """

    # Step 1: Get current season games (exclude injury)
    current_season_games = query_games(
        player=player_lookup,
        season_year=season_year,
        max_date=analysis_date,
        min_minutes=10,  # Exclude injury/DNP
        order='DESC'
    )

    current_count = len(current_season_games)
    prior_count = 0
    all_games = current_season_games.copy()

    # Step 2: If insufficient, get prior season games
    if current_count < window_size:
        needed = window_size - current_count

        prior_season_games = query_games(
            player=player_lookup,
            season_year=season_year - 1,
            max_date=None,  # All prior season games
            order='DESC',
            limit=needed,
            min_minutes=10
        )

        prior_count = len(prior_season_games)
        all_games.extend(prior_season_games)

    actual_count = len(all_games)
    crosses_season = prior_count > 0

    # Step 3: Calculate average
    if actual_count == 0:
        return None  # No data

    average = sum(g[metric] for g in all_games) / actual_count

    # Step 4: Calculate confidence
    base_confidence = actual_count / window_size

    # Penalty for cross-season
    if crosses_season:
        base_confidence *= 0.9  # 10% penalty

    # Penalty for large time gaps (injury)
    if all_games:
        days_span = (all_games[0]['game_date'] - all_games[-1]['game_date']).days
        if days_span > 60:
            base_confidence *= 0.8  # 20% penalty

    confidence = min(1.0, base_confidence)

    # Step 5: Build metadata
    return {
        f'{metric}_avg_last_{window_size}': round(average, 1),
        f'{metric}_avg_last_{window_size}_games_count': actual_count,
        f'{metric}_avg_last_{window_size}_confidence': round(confidence, 2),
        f'{metric}_avg_last_{window_size}_crosses_season': crosses_season,
        'metadata': {
            'current_season_games': current_count,
            'prior_season_games': prior_count,
            'calculation_note': f"{current_count} current + {prior_count} prior season games" if crosses_season else f"{current_count} current season games"
        }
    }
```

### Aggregate Metadata Schema (15 fields)

```sql
-- Overall data quality
overall_data_confidence FLOAT64,           -- Weighted avg confidence across all features
min_games_available INTEGER,               -- Fewest games for any rolling avg
max_games_available INTEGER,               -- Most games for any rolling avg
uses_prior_season_data BOOLEAN,            -- TRUE if ANY feature used prior season
prior_season_game_count INTEGER,           -- Total prior season games used

-- Bootstrap context
bootstrap_mode STRING,                     -- 'full_data' | 'partial_current_season' | 'cross_season_fallback' | 'rookie_limited'
bootstrap_reason STRING,                   -- Human-readable explanation
is_rookie BOOLEAN,                         -- First NBA season
days_since_season_start INTEGER,           -- Days since Oct 22

-- Injury/availability
total_games_excluded_injury INTEGER,       -- Games excluded across all calcs
has_recent_injury_return BOOLEAN,          -- Returned from injury <14 days
days_since_last_game INTEGER,              -- Gap detection

-- Confidence breakdown (optional)
rolling_avg_confidence FLOAT64,            -- Confidence for L5, L10
season_avg_confidence FLOAT64,             -- Confidence for season stats
composite_factor_confidence FLOAT64        -- Confidence for Phase 4 factors
```

### Selective Per-Feature Metadata (16 fields for 4 key features)

```sql
-- Only add metadata for most important rolling averages
points_avg_last_5 FLOAT64,
points_avg_last_5_games_count INTEGER,
points_avg_last_5_confidence FLOAT64,
points_avg_last_5_crosses_season BOOLEAN,
points_avg_last_5_calculation_note STRING,

points_avg_last_10 FLOAT64,
points_avg_last_10_games_count INTEGER,
points_avg_last_10_confidence FLOAT64,
points_avg_last_10_crosses_season BOOLEAN,
points_avg_last_10_calculation_note STRING,

points_avg_season FLOAT64,
points_avg_season_games_count INTEGER,
points_avg_season_confidence FLOAT64,
points_avg_season_crosses_season BOOLEAN,
points_avg_season_calculation_note STRING,

points_std_last_10 FLOAT64,
points_std_last_10_games_count INTEGER,
points_std_last_10_confidence FLOAT64,
points_std_last_10_crosses_season BOOLEAN,
points_std_last_10_calculation_note STRING
```

**Total New Fields: 31** (15 aggregate + 16 selective) - Very manageable!

---

## Implementation Plan

### Phase 1: Add Metadata to Existing Processors (2-3 weeks)

**Tasks:**

1. **Update ml_feature_store_processor.py** (8-12 hours)
   - Add 15 aggregate metadata fields to output schema
   - Add 16 selective metadata fields for key features
   - Implement confidence calculation logic
   - Update `_generate_player_features()` to populate metadata

2. **Update player_daily_cache_processor.py** (8-12 hours)
   - Remove `season_year` filter from rolling calculations
   - Add cross-season fallback logic
   - Add same metadata fields
   - Keep season filter for season-specific stats

3. **Update player_shot_zone_analysis_processor.py** (4-6 hours)
   - Remove `season_start_date` filter from rolling calculations
   - Add metadata fields
   - Implement confidence scoring

4. **Update team_defense_zone_analysis_processor.py** (4-6 hours)
   - Same as shot zone analysis

5. **Create shared metadata utility** (4-6 hours)
   - `shared/utils/rolling_average_calculator.py`
   - Reusable function for all processors
   - Centralized confidence calculation rules

6. **Update BigQuery schemas** (2-4 hours)
   - Add 31 new fields to each table
   - Migration scripts for existing data

7. **Testing** (8-12 hours)
   - Test with 2021-10-19 epoch data
   - Test with current season data
   - Test edge cases (rookies, trades, injuries)
   - Validate confidence calculations

**Total Effort: 40-60 hours (1-1.5 weeks)**

### Phase 2: Stat-Specific Strategies (1-2 months later)

**Concept:** Different stats use different strategies

```python
STAT_STRATEGIES = {
    'points': {
        'allow_cross_season': True,
        'cross_season_penalty': 0.2,  # 20% confidence penalty
        'prefer_regular_season': True
    },
    'fg_pct': {
        'allow_cross_season': True,
        'cross_season_penalty': 0.05,  # Small penalty (stable stat)
        'prefer_regular_season': False
    },
    'minutes': {
        'allow_cross_season': True,
        'cross_season_penalty': 0.3,  # Large penalty (role-dependent)
        'warn_if_role_changed': True
    },
    'usage_rate': {
        'allow_cross_season': False,  # NEVER cross-season
        'current_season_minimum': 15
    }
}
```

**Effort:** 15-20 hours

### Phase 3: Advanced Bootstrap (3-6 months later)

- Similar player baselines for early season
- Situational models (primetime games, etc.)
- Rookie college stat integration

**Effort:** 40-60 hours

---

## Edge Cases & Gray Areas

### Case 1: Need 30 Games, Have 29 in Current Season

**Question:** Use 1 prior season game or just 29 games?

**Recommendation:** Use the 1 prior season game
```python
{
  'points_avg_last_30': 23.5,
  'points_avg_last_30_games_count': 30,
  'points_avg_last_30_current_season_games': 29,
  'points_avg_last_30_prior_season_games': 1,
  'points_avg_last_30_crosses_season': true,
  'points_avg_last_30_confidence': 0.97,  # 30/30 * 0.9 penalty
  'points_avg_last_30_calculation_note': '29 current + 1 prior season game'
}
```

**Rationale:** One prior game is better than losing data point. Metadata tracks it.

### Case 2: Rookie (No Prior Season Data)

**Question:** How to handle first NBA season?

**Implementation:**
```python
{
  'points_avg_last_10': 15.2,
  'points_avg_last_10_games_count': 4,  # Only 4 games played
  'points_avg_last_10_confidence': 0.4,
  'points_avg_last_10_crosses_season': false,
  'points_avg_last_10_calculation_note': 'Rookie: only 4 games available',

  'is_rookie': true,
  'bootstrap_mode': 'rookie_limited_data'
}
```

**Phase 5 Options:**
- Use with low confidence
- Use similar rookie baseline
- Use college stats (future enhancement)
- Skip prediction

### Case 3: Playoff Games - Include or Exclude?

**Question:** Should cross-season averages include playoff games?

**Recommendation:** Include but track in metadata

```python
# Track playoff vs regular season games
{
  'points_avg_last_10': 28.5,
  'points_avg_last_10_playoff_games': 3,
  'points_avg_last_10_regular_season_games': 7,
  'points_avg_last_10_confidence': 0.85,  # Slight penalty for mixing
  'points_avg_last_10_calculation_note': '7 regular season + 3 playoff games'
}
```

**Rationale:**
- For stars (LeBron): Playoff games might be MORE predictive
- For role players: Playoff games might be LESS predictive
- Let Phase 5 decide based on player type

### Case 4: Injured Games - Exclude but Track

**Question:** Should injured games be excluded from averages?

**Recommendation:** Exclude games with <10 minutes, track exclusions

```python
def query_games(player, season, min_minutes=10):
    """Get games, excluding injury but tracking."""

    # Get ALL games
    all_games = query(f"""
        SELECT game_date, points, minutes_played, player_status
        FROM player_game_summary
        WHERE player_lookup = '{player}'
          AND season_year = {season}
        ORDER BY game_date DESC
    """)

    # Separate healthy vs injured
    healthy = [g for g in all_games if g['minutes_played'] >= min_minutes]
    injured = [g for g in all_games if g['minutes_played'] < min_minutes]

    return {
        'games': healthy,
        'excluded_injury_count': len(injured)
    }

# Output:
{
  'points_avg_last_10': 24.5,
  'points_avg_last_10_excluded_injured': 2,
  'points_avg_last_10_calculation_note': 'Last 10 healthy games (excluded 2 injury-impacted)'
}
```

### Case 5: Large Time Gap (Injury/Suspension)

**Question:** What if L10 spans 3 months due to injury?

**Implementation:**
```python
# Detect large gaps
if all_games:
    days_span = (all_games[0]['game_date'] - all_games[-1]['game_date']).days
    if days_span > 60:
        confidence *= 0.8  # 20% penalty

{
  'points_avg_last_10': 22.0,
  'points_avg_last_10_confidence': 0.64,  # 0.8 (gap) * 1.0 (count)
  'points_avg_last_10_date_range': '2024-09-15 to 2024-12-15',
  'points_avg_last_10_calculation_note': '10 games over 3-month period (injury absence)',

  'days_since_last_game': 25,
  'has_recent_injury_return': true
}
```

### Case 6: Player Traded Mid-Season

**Question:** Should L10 include games with prior team?

**Current Approach:** Yes, but track in metadata (future enhancement)

```python
# Future enhancement: Track team changes
{
  'points_avg_last_10': 20.5,
  'points_avg_last_10_teams': ['LAL', 'GSW'],  # FUTURE
  'points_avg_last_10_with_current_team': 6,    # FUTURE
  'points_avg_last_10_calculation_note': '6 current team + 4 prior team games'
}
```

---

## Decision Required

### Questions for Product/Engineering Team

**Question 1: Base Strategy**

Which base strategy should we use for rolling averages?

- [ ] **Option A:** Current season only (no cross-season)
  - Result: No predictions for 3 weeks every October
  - Bootstrap affects: Every season start

- [ ] **Option B:** Cross-season with metadata (RECOMMENDED)
  - Result: Predictions available day 1 with confidence scores
  - Bootstrap affects: Only 2021-10-19 epoch

**Question 2: Metadata Scope**

How much metadata should we track?

- [ ] **Minimal:** Aggregate only (15 fields)
- [ ] **Recommended:** Aggregate + selective per-feature (31 fields)
- [ ] **Maximum:** Per-feature for all 25 features (225 fields) - NOT RECOMMENDED
- [ ] **Separate Table:** Keep metadata in separate table

**Question 3: Injured Games**

How should we handle games where player was injured/limited?

- [ ] **Exclude:** Don't include in averages (min 10 minutes played)
- [ ] **Include:** Include all games
- [ ] **Flag:** Include but reduce confidence

**Question 4: Playoff Games**

Should cross-season averages include playoff games?

- [ ] **Include:** Playoffs are games like any other
- [ ] **Exclude:** Only regular season games
- [ ] **Separate:** Track playoff vs regular season separately

**Question 5: Confidence Thresholds**

What confidence threshold should Phase 5 use for predictions?

- [ ] **No filter:** Show all predictions regardless of confidence
- [ ] **Low bar:** Only show predictions with >0.5 confidence
- [ ] **Medium bar:** Only show predictions with >0.7 confidence
- [ ] **High bar:** Only show predictions with >0.9 confidence

**Question 6: Implementation Timeline**

When should this be implemented?

- [ ] **Urgent:** Before December 2024 (current season)
- [ ] **Normal:** Q1 2025 (before next season)
- [ ] **Future:** After other priorities

---

## Appendix: Code Examples

### Example 1: Calculate Rolling Average with Metadata

```python
def calculate_rolling_average_with_metadata(
    player_lookup: str,
    analysis_date: date,
    metric: str,
    window_size: int,
    season_year: int,
    bq_client
) -> dict:
    """
    Calculate rolling average with rich metadata.

    Returns dict with value + metadata fields.
    """

    # Query current season games
    current_games_query = f"""
    SELECT game_date, {metric}, minutes_played
    FROM nba_analytics.player_game_summary
    WHERE player_lookup = '{player_lookup}'
      AND season_year = {season_year}
      AND game_date < '{analysis_date}'
      AND minutes_played >= 10  # Exclude injury
    ORDER BY game_date DESC
    """

    current_games = bq_client.query(current_games_query).to_dataframe()
    current_count = len(current_games)

    # If insufficient, query prior season
    prior_count = 0
    all_games = current_games.copy()

    if current_count < window_size:
        needed = window_size - current_count

        prior_games_query = f"""
        SELECT game_date, {metric}, minutes_played
        FROM nba_analytics.player_game_summary
        WHERE player_lookup = '{player_lookup}'
          AND season_year = {season_year - 1}
          AND minutes_played >= 10
        ORDER BY game_date DESC
        LIMIT {needed}
        """

        prior_games = bq_client.query(prior_games_query).to_dataframe()
        prior_count = len(prior_games)
        all_games = pd.concat([current_games, prior_games])

    # Calculate average
    actual_count = len(all_games)
    if actual_count == 0:
        return {
            f'{metric}_avg_last_{window_size}': None,
            f'{metric}_avg_last_{window_size}_games_count': 0,
            f'{metric}_avg_last_{window_size}_confidence': 0.0
        }

    average_value = all_games[metric].mean()

    # Calculate confidence
    base_confidence = actual_count / window_size
    crosses_season = prior_count > 0

    if crosses_season:
        base_confidence *= 0.9  # 10% penalty

    # Check for large time gaps
    if actual_count > 1:
        date_range = (all_games['game_date'].max() - all_games['game_date'].min()).days
        if date_range > 60:
            base_confidence *= 0.8  # 20% penalty for gaps

    confidence = min(1.0, base_confidence)

    # Build calculation note
    if crosses_season:
        note = f"{current_count} current + {prior_count} prior season games"
    elif actual_count < window_size:
        note = f"Partial: {actual_count}/{window_size} games (rookie or early season)"
    else:
        note = f"Last {window_size} games from current season"

    return {
        f'{metric}_avg_last_{window_size}': round(average_value, 1),
        f'{metric}_avg_last_{window_size}_games_count': actual_count,
        f'{metric}_avg_last_{window_size}_target_games': window_size,
        f'{metric}_avg_last_{window_size}_confidence': round(confidence, 2),
        f'{metric}_avg_last_{window_size}_crosses_season': crosses_season,
        f'{metric}_avg_last_{window_size}_calculation_note': note
    }
```

### Example 2: Aggregate Metadata Builder

```python
def build_aggregate_metadata(
    player_lookup: str,
    analysis_date: date,
    season_year: int,
    all_features: dict
) -> dict:
    """
    Build aggregate metadata for entire feature record.

    Args:
        all_features: Dict containing all calculated features and their metadata

    Returns:
        Dict with 15 aggregate metadata fields
    """

    # Collect all confidence scores
    confidences = [
        all_features.get('points_avg_last_5_confidence', 1.0),
        all_features.get('points_avg_last_10_confidence', 1.0),
        all_features.get('points_avg_season_confidence', 1.0),
        # ... other features
    ]

    # Collect all game counts
    game_counts = [
        all_features.get('points_avg_last_5_games_count', 0),
        all_features.get('points_avg_last_10_games_count', 0),
        # ... other features
    ]

    # Check if any feature crosses seasons
    uses_prior_season = any([
        all_features.get('points_avg_last_5_crosses_season', False),
        all_features.get('points_avg_last_10_crosses_season', False),
        # ... other features
    ])

    # Count total prior season games used
    prior_season_total = sum([
        all_features.get('points_avg_last_5_prior_season_games', 0),
        all_features.get('points_avg_last_10_prior_season_games', 0),
        # ... other features
    ])

    # Determine bootstrap mode
    season_start = date(season_year, 10, 1)
    days_since_start = (analysis_date - season_start).days

    min_games = min([g for g in game_counts if g > 0], default=0)

    if min_games == 0:
        bootstrap_mode = 'no_data'
        bootstrap_reason = 'No games available'
    elif uses_prior_season:
        bootstrap_mode = 'cross_season_fallback'
        bootstrap_reason = f"Early season: {days_since_start} days into season, using prior season data"
    elif min_games < 10:
        bootstrap_mode = 'partial_current_season'
        bootstrap_reason = f"Early season: only {min_games} games available"
    else:
        bootstrap_mode = 'full_data'
        bootstrap_reason = 'Sufficient current season data'

    return {
        'overall_data_confidence': round(sum(confidences) / len(confidences), 2),
        'min_games_available': min(game_counts),
        'max_games_available': max(game_counts),
        'uses_prior_season_data': uses_prior_season,
        'prior_season_game_count': prior_season_total,

        'bootstrap_mode': bootstrap_mode,
        'bootstrap_reason': bootstrap_reason,
        'is_rookie': season_year == 2024 and min_games < 82,  # Simple check
        'days_since_season_start': days_since_start,

        'total_games_excluded_injury': all_features.get('total_excluded', 0),
        'has_recent_injury_return': all_features.get('injury_return_flag', False),
        'days_since_last_game': all_features.get('days_since_last', 0),

        'rolling_avg_confidence': round(sum(confidences[:3]) / 3, 2),  # L5, L10, season
        'season_avg_confidence': confidences[2] if len(confidences) > 2 else 0.0,
        'composite_factor_confidence': 1.0  # From Phase 4
    }
```

---

## Summary

### What We Know

1. ✅ Current system is INCONSISTENT (different processors use different strategies)
2. ✅ User prefers current season data but sees value in cross-season for some stats
3. ✅ Need rich metadata to track how averages were calculated
4. ✅ Bootstrap affects early season, rookies, trades, injuries
5. ✅ Different stats should potentially use different strategies

### What We're Recommending

**Strategy:** Metadata-rich cross-season approach
- Use cross-season data by default (predictions available day 1)
- Track rich metadata (31 new fields)
- Confidence scoring (0.0 to 1.0)
- Phase 5 can filter by confidence
- Can change strategy later without schema migration

**Schema Impact:** 31 new fields (manageable)
**Implementation Effort:** 40-60 hours (1-1.5 weeks)
**Bootstrap Impact:** Only affects 2021-10-19 epoch (one-time)

### What We Need From You

1. **Confirm base strategy:** Cross-season or current-season-only?
2. **Approve metadata scope:** 31 fields okay?
3. **Clarify injured games:** Exclude from calculations?
4. **Clarify playoff games:** Include in cross-season averages?
5. **Set timeline:** When should this be implemented?

---

**End of Document**

*For questions or clarifications, refer to:*
- `docs/08-projects/current/bootstrap-period/investigation-findings.md`
- `docs/08-projects/current/bootstrap-period/README.md`
