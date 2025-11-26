# Phase 4 Historical Dependencies - Complete Analysis

**Date:** 2025-11-22
**Purpose:** Document historical data requirements, partial data handling, and backfill strategy for all Phase 4 processors
**Status:** Complete analysis for deployment planning

---

## Table of Contents

1. [Overview](#overview)
2. [Processor-by-Processor Analysis](#processor-by-processor-analysis)
3. [Historical Range Dependency Detection](#historical-range-dependency-detection)
4. [Backfill Strategy (4 Seasons Ago)](#backfill-strategy-4-seasons-ago)
5. [Partial Data Handling Matrix](#partial-data-handling-matrix)
6. [Alert & Retry Strategy](#alert--retry-strategy)
7. [Implementation Recommendations](#implementation-recommendations)

---

## Overview

### What is Historical Range Dependency?

**Definition**: A processor has historical range dependency when the output for date D depends on multiple previous dates of input data (e.g., "last 10 games", "last 30 days").

**Why It Matters**:
- Point-in-time hash tracking doesn't detect changes across the historical window
- Backfilling 4 seasons ago means processors must gracefully handle sparse historical data
- We need strategies for: early season, mid-season backfill, and normal operation

### Phase 4 Processor Chain

```
Phase 3 (Analytics)
    ↓
[team_defense_zone_analysis] ←─── Last 15 games
[player_shot_zone_analysis]  ←─── Last 10 games, Last 20 games
    ↓
[player_daily_cache]         ←─── Last 180 days (references L5, L7, L10, L14)
[player_composite_factors]   ←─── Cascades from upstream
    ↓
[ml_feature_store]           ←─── Cascades from upstream
```

**Key Insight**: Early processors (zone analysis) define historical requirements. Later processors cascade the `early_season_flag` forward.

---

## Processor-by-Processor Analysis

### 1. team_defense_zone_analysis

**Location**: `data_processors/precompute/team_defense_zone_analysis/`

#### Historical Requirements

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `min_games_required` | 15 | Minimum games for meaningful zone defense analysis |
| `league_avg_lookback_days` | 30 | Days to look back for league average comparison |
| `early_season_threshold_days` | 14 | Days to consider "early season" |

**What It Calculates**:
- FG% allowed by zone (paint, mid-range, 3PT) over **last 15 games**
- Volume metrics (attempts/points per game)
- Comparison to league averages
- Defensive strengths/weaknesses identification

**Upstream Dependencies**:
- `nba_analytics.team_defense_game_summary` (Phase 3)

#### Partial Data Handling

```python
# Line 558-568: Check sufficient games
if games_count < self.min_games_required:
    failed.append({
        'entity_id': team_abbr,
        'reason': f"Only {games_count} games, need {self.min_games_required}",
        'category': 'INSUFFICIENT_DATA',
        'can_retry': True
    })
    continue  # Skip this team
```

**Behavior**:

| Games Available | Behavior | early_season_flag | Output |
|----------------|----------|-------------------|--------|
| 0 games | Write placeholder | TRUE | NULL metrics, "Season start" reason |
| 1-14 games | Skip team | N/A | No record, logged as failed entity |
| 15+ games | Process normally | FALSE | Full zone defense metrics |

**Early Season Detection** (Line 305-323):
```python
is_early = is_early_season(
    analysis_date,
    self.opts['season_year'],
    self.early_season_threshold_days  # 14 days
)

if is_early:
    # Write placeholder rows for all 30 teams
    self._write_placeholder_rows(dep_check)
    return
```

#### Backfill Scenario: 4 Seasons Ago

**Timeline**:
- Season start: October 20, 2020
- Backfill date: October 20 (Day 0) → November 3 (Day 14)

| Date | Games Played | Behavior | Retry? |
|------|--------------|----------|--------|
| Oct 20-24 (Days 0-4) | 2 games per team | **Write placeholders** (early season) | No - will auto-correct Day 15+ |
| Oct 25-Nov 2 (Days 5-13) | 6-8 games per team | **Write placeholders** (early season) | No - will auto-correct Day 15+ |
| Nov 3+ (Day 14+) | 14 games per team | **Skip teams** (insufficient data) | Yes - retry when 15+ games |
| Nov 7+ (Day 18+) | 15+ games per team | **Process normally** | No - complete data |

**Key Insight**: Early season detection prevents failures on Days 0-13. Days 14-17 will have failed entities that need retry.

---

### 2. player_shot_zone_analysis

**Location**: `data_processors/precompute/player_shot_zone_analysis/`

#### Historical Requirements

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `min_games_required` | 10 | Minimum games for quality shot zone analysis |
| `sample_window` | 10 | Primary analysis window (L10) |
| `trend_window` | 20 | Broader trend window (L20) |
| `early_season_days` | 14 | Early season threshold |

**What It Calculates**:
- Shot distribution by zone (paint, mid-range, 3PT) over **last 10 games**
- Shot efficiency percentages (FG%)
- Assisted vs unassisted rates
- Trend analysis over **last 20 games**

**Upstream Dependencies**:
- `nba_analytics.player_game_summary` (Phase 3)

#### Partial Data Handling

```python
# Line 446-453: Check sufficient games
if len(games_10) < self.min_games_required:
    failed.append({
        'entity_id': player_lookup,
        'reason': f"Only {len(games_10)} games, need {self.min_games_required}",
        'category': 'INSUFFICIENT_DATA',
        'can_retry': True
    })
    continue  # Skip this player
```

**Behavior**:

| Games Available | Behavior | early_season_flag | L10 Metrics | L20 Metrics |
|----------------|----------|-------------------|-------------|-------------|
| 0-9 games (Days 0-13) | Write placeholder | TRUE | NULL | NULL |
| 10-19 games | Process with L10 only | FALSE | ✅ Calculated | NULL |
| 20+ games | Process with L10+L20 | FALSE | ✅ Calculated | ✅ Calculated |

**Data Quality Scoring** (Line 638-643):
```python
def _determine_sample_quality(self, games_count: int) -> str:
    if games_count >= self.min_games_required:  # 10+
        return 'high'
    elif games_count >= 7:
        return 'medium'
    else:
        return 'low'
```

#### Backfill Scenario: 4 Seasons Ago

**Timeline**:
- Season start: October 20, 2020
- Typical player schedule: 3 games per week

| Date | Avg Games Played | Behavior | Retry? |
|------|-----------------|----------|--------|
| Oct 20-Nov 2 (Days 0-13) | 2-4 games | **Write placeholders** (early season) | No |
| Nov 3-10 (Days 14-21) | 5-9 games | **Skip players** (insufficient data) | Yes |
| Nov 11+ (Day 22+) | 10+ games | **Process with L10** | No |
| Dec 10+ (Day 51+) | 20+ games | **Process with L10+L20** | No |

**Key Consideration**: Different players play different number of games (injuries, rest). Retry logic must be player-specific.

---

### 3. player_daily_cache

**Location**: `data_processors/precompute/player_daily_cache/`

#### Historical Requirements

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `min_games_required` | 10 | Preferred minimum for quality cache |
| `absolute_min_games` | 5 | Absolute minimum to write ANY record |
| `lookback_days` | 180 | Full season lookback |
| `early_season_days` | 14 | Early season threshold |

**What It Calculates**:
- Player performance stats: L5, L10, season averages
- Team context: L10 pace, offensive rating
- Fatigue metrics: games/minutes in L7, L14, back-to-backs
- Shot zone preferences (from player_shot_zone_analysis - Phase 4!)

**Upstream Dependencies**:
- `nba_analytics.player_game_summary` (Phase 3) - **180 day lookback**
- `nba_analytics.team_offense_game_summary` (Phase 3) - **30 day lookback**
- `nba_analytics.upcoming_player_game_context` (Phase 3)
- `nba_precompute.player_shot_zone_analysis` (Phase 4!) - **dependency cascade**

#### Partial Data Handling

```python
# Line 530-536: Absolute minimum check
if games_count < self.absolute_min_games:  # 5
    failed.append({
        'entity_id': player_lookup,
        'reason': f"Only {games_count} games played, need {self.absolute_min_games} minimum",
        'category': 'INSUFFICIENT_DATA',
        'can_retry': True
    })
    continue

# Line 540: Flag if below preferred
is_early_season = games_count < self.min_games_required  # 10
```

**Behavior**:

| Games Available | Behavior | early_season_flag | Cache Quality | Retry? |
|----------------|----------|-------------------|---------------|--------|
| 0-4 games | Skip player | N/A | N/A | Yes - need 5+ |
| 5-9 games | Write partial cache | TRUE | Low-Medium | No - will improve naturally |
| 10+ games | Write full cache | FALSE | High | No |

**Critical Insight**: This is the **most lenient** processor - writes records with only 5 games to enable downstream processing.

#### Backfill Scenario: 4 Seasons Ago

**Timeline**:
- Season start: October 20, 2020

| Date | Avg Games | Behavior | L5 Avg | L10 Avg | Season Avg | Fatigue L7 |
|------|-----------|----------|--------|---------|------------|------------|
| Oct 20-28 (Days 0-8) | 2-3 | **Skip** (< 5 games) | NULL | NULL | NULL | NULL |
| Oct 29-Nov 10 (Days 9-21) | 5-9 | **Write partial** | ✅ If 5+ games | ❌ NULL | ✅ From available | ✅ From L7 |
| Nov 11+ (Day 22+) | 10+ | **Write full** | ✅ | ✅ | ✅ | ✅ |

**Special Handling for Backfill**:
- L5 average: Needs 5 games → available Day 9+
- L10 average: Needs 10 games → available Day 22+
- L7/L14 fatigue: Calculated from games in last 7/14 days (not game count)
- Season average: Always available (even with 1 game)

**Important**: During backfill, fatigue metrics (games in L7/L14) will be LOW because we're processing historical dates one at a time. This is EXPECTED and CORRECT.

---

### 4. player_composite_factors

**Location**: `data_processors/precompute/player_composite_factors/`

#### Historical Requirements

**NO EXPLICIT GAME COUNT REQUIREMENTS** - Cascades from upstream processors.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Early season detection | Cascaded | Checks if >50% players have `early_season_flag` in upstream |

**What It Calculates**:
- Fatigue adjustment (from player_daily_cache)
- Shot zone mismatch score (from player_shot_zone_analysis + team_defense_zone_analysis)
- Pace adjustment
- Usage spike detection
- Other composite factors

**Upstream Dependencies**:
- `nba_analytics.upcoming_player_game_context` (Phase 3)
- `nba_analytics.upcoming_team_game_context` (Phase 3)
- `nba_precompute.player_shot_zone_analysis` (Phase 4)
- `nba_precompute.team_defense_zone_analysis` (Phase 4)

#### Partial Data Handling

```python
# Line 347-375: Early season detection (CASCADE)
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Check if we're in early season (insufficient data).

    Early season = >50% of players have early_season_flag set in
    their shot zone analysis.
    """
    # Query player_shot_zone_analysis
    early_season_query = f"""
    SELECT
        COUNT(*) as total_players,
        SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players
    FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
    WHERE analysis_date = '{analysis_date}'
    """

    if total > 0 and (early / total) > 0.5:
        self.early_season_flag = True
        self.insufficient_data_reason = f"Early season: {early}/{total} players lack historical data"
        return True
```

**Behavior**:

| Upstream Status | Behavior | early_season_flag | Composite Factors |
|----------------|----------|-------------------|-------------------|
| >50% upstream early season | Write placeholders | TRUE | All NULL |
| <50% upstream early season | Process normally | FALSE | Calculated |
| Missing upstream data | Handle missing fields | FALSE | Partial scores with warnings |

**Key Insight**: This processor is **smart about cascading** - it doesn't fail if upstream is incomplete, it just flags which factors couldn't be calculated.

#### Backfill Scenario: 4 Seasons Ago

**Timeline**:
- Inherits early season status from player_shot_zone_analysis (Day 14 threshold)

| Date | Upstream Status | Behavior | Composite Factors |
|------|----------------|----------|-------------------|
| Days 0-13 | 100% early season | **Write placeholders** | All NULL |
| Days 14-21 | 80% early season | **Write placeholders** (>50%) | All NULL |
| Days 22+ | 20% early season | **Process normally** (<50%) | Calculated |

**Missing Data Handling**:
- If shot zone data missing: `shot_zone_mismatch_score = NULL`, logs warning
- If fatigue data missing: `fatigue_score = NULL`, logs warning
- Tracks all missing fields in `missing_data_fields` column
- Sets `data_completeness_pct` to show quality

---

### 5. ml_feature_store

**Location**: `data_processors/precompute/ml_feature_store/`

#### Historical Requirements

**NO EXPLICIT GAME COUNT REQUIREMENTS** - Cascades from player_daily_cache.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Early season detection | Cascaded | Checks if >50% players have `early_season_flag` in player_daily_cache |

**What It Calculates**:
- Assembles feature vector from all Phase 4 sources
- Feature engineering and transformation
- Feature quality scoring

**Upstream Dependencies**:
- `nba_precompute.player_daily_cache` (Phase 4) - **Primary cascade source**
- `nba_precompute.player_composite_factors` (Phase 4)
- `nba_precompute.player_shot_zone_analysis` (Phase 4)
- `nba_precompute.team_defense_zone_analysis` (Phase 4)

#### Partial Data Handling

```python
# Line 326-358: Early season detection (CASCADE from player_daily_cache)
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Early season = >50% of players have early_season_flag set in
    their Phase 4 player_daily_cache data.
    """
    query = f"""
    SELECT
        COUNT(*) as total_players,
        SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players
    FROM `{self.project_id}.nba_precompute.player_daily_cache`
    WHERE cache_date = '{analysis_date}'
    """

    if total > 0 and (early / total) > 0.5:
        self.early_season_flag = True
        return True
```

**Behavior**:

| Upstream Status | Behavior | early_season_flag | Features |
|----------------|----------|-------------------|----------|
| >50% cache early season | Write placeholders | TRUE | NULL feature array |
| <50% cache early season | Process normally | FALSE | Full feature vector |

#### Backfill Scenario: 4 Seasons Ago

**Timeline**:
- Inherits from player_daily_cache (5 game threshold for cache, 10 game threshold for full quality)

| Date | Upstream Status | Behavior | Features |
|------|----------------|----------|----------|
| Days 0-8 | 100% early season (no cache) | **Write placeholders** | NULL |
| Days 9-21 | 100% early season (partial cache) | **Write placeholders** | NULL |
| Days 22+ | <50% early season (full cache) | **Process normally** | Full vectors |

**Key Insight**: ml_feature_store is the **END of the cascade** - it only processes when the entire upstream chain is ready.

---

## Historical Range Dependency Detection

### Do We Need Additional Hash Checking?

**Current Implementation**: We extract `data_hash` from most recent upstream record.

**Question**: Does this detect changes in L10/L15/L30 historical data?

**Answer**: **Partially**, but not completely.

### What Current Implementation Detects

✅ **Detects**:
- Change to most recent game in the window
- New data arriving (new game added)
- Corrections to most recent game

❌ **Doesn't Detect**:
- Backfill of game from 10 days ago
- Correction to historical game (not most recent)
- Reprocessing of Phase 3 data for games 5-15 in the window

### Example Scenario

**Timeline**:
- Nov 15: Process player_shot_zone_analysis (uses games Nov 1-14, last 10 games)
- Source hash extracted: hash from Nov 14 game
- Nov 16: **Backfill corrects Nov 5 game** in player_game_summary
- Nov 16: Process player_shot_zone_analysis again
- Source hash extracted: hash from Nov 15 game (different from Nov 14)
- **Result**: Reprocessing triggered ✅

**BUT**:
- Nov 17: No new games, but Nov 7 game corrected
- Nov 17: Process player_shot_zone_analysis
- Source hash extracted: hash from Nov 16 game
- **Comparison**: Nov 16 hash vs Nov 16 hash → **NO CHANGE**
- **Result**: Skipped ❌ (missed the Nov 7 correction!)

### Proposed Solution: Historical Range Hash Checking

**Concept**: Instead of extracting ONE hash, extract MAX(processed_at) across the entire historical window.

```python
def _extract_source_hash_with_historical_check(
    self,
    analysis_date: date,
    lookback_days: int = 30
) -> tuple[str, datetime]:
    """
    Extract hash AND max processed_at from historical window.

    Returns:
        (hash, max_processed_at): Hash from most recent + timestamp from any record in window
    """
    # Get date range
    window_start = analysis_date - timedelta(days=lookback_days)

    query = f"""
    SELECT
        data_hash,
        MAX(processed_at) OVER() as max_processed_at_in_window
    FROM `{self.project_id}.nba_analytics.player_game_summary`
    WHERE game_date BETWEEN '{window_start}' AND '{analysis_date}'
      AND player_lookup = '{player_lookup}'
      AND data_hash IS NOT NULL
    ORDER BY game_date DESC
    LIMIT 1  -- Get most recent hash
    """

    result = self.bq_client.query(query).to_dataframe()

    if result.empty:
        return None, None

    # Most recent hash (for current logic)
    hash_value = result['data_hash'].iloc[0]

    # Max processed_at across entire window (for historical change detection)
    max_processed_at = result['max_processed_at_in_window'].iloc[0]

    return hash_value, max_processed_at
```

**Skip Logic**:
```python
def should_reprocess(self, analysis_date: date) -> bool:
    """Determine if reprocessing needed."""

    # Get existing record
    existing = self.get_existing_record(analysis_date)
    if not existing:
        return True  # No record exists

    # Get source hash + historical window timestamp
    source_hash, source_max_processed_at = self._extract_source_hash_with_historical_check(
        analysis_date,
        lookback_days=10  # L10 window
    )

    # Check 1: Hash changed (current logic)
    if existing['source_player_game_hash'] != source_hash:
        logger.info("Source hash changed - reprocessing")
        return True

    # Check 2: Historical window updated (NEW logic)
    if source_max_processed_at > existing['processed_at']:
        logger.info(f"Historical data updated ({source_max_processed_at} > {existing['processed_at']}) - reprocessing")
        return True

    # Both unchanged
    logger.info("Source hash AND historical window unchanged - skipping")
    return False
```

**Storage in BigQuery**:
```sql
-- Current schema
source_player_game_hash STRING,  -- Hash from most recent game
source_player_game_last_updated TIMESTAMP,  -- When most recent game processed

-- ADD these fields
source_player_game_window_last_updated TIMESTAMP,  -- When ANY game in L10 window last processed
source_player_game_window_size INT64  -- How many games were in window
```

---

## Backfill Strategy (4 Seasons Ago)

### Scenario

**Goal**: Backfill historical data starting from 4 seasons ago (October 2020)

**Challenge**: On Day 0, there is NO historical data. By Day 60, we have 60 days of historical data.

**User Requirement**:
- Fill in as much as possible early on
- Eventually use full historical data once available
- No manual intervention required

### Phase-by-Phase Backfill Timeline

#### Phase 2 (Raw) & Phase 3 (Analytics)

**No special handling needed** - these are point-in-time processors that don't depend on historical ranges.

**Backfill approach**: Process sequentially from Day 0 → Day N.

---

#### Phase 4 Backfill Timeline

**Start Date**: October 20, 2020 (Season Start)

### Week 1: Days 0-6 (Oct 20-26)

| Processor | Games Available | Behavior | Output |
|-----------|----------------|----------|--------|
| team_defense_zone_analysis | 2-3 per team | Write placeholders (early season) | 30 placeholder rows |
| player_shot_zone_analysis | 1-2 per player | Write placeholders (early season) | ~450 placeholder rows |
| player_daily_cache | 1-2 per player | **Skip** (< 5 games) | **0 rows** |
| player_composite_factors | N/A (depends on cache) | **Skip** (no cache) | **0 rows** |
| ml_feature_store | N/A (depends on cache) | **Skip** (no cache) | **0 rows** |

**Key Point**: Last 3 processors write NOTHING during Week 1.

---

### Week 2: Days 7-13 (Oct 27-Nov 2)

| Processor | Games Available | Behavior | Output |
|-----------|----------------|----------|--------|
| team_defense_zone_analysis | 4-6 per team | Write placeholders (early season) | 30 placeholder rows |
| player_shot_zone_analysis | 3-5 per player | Write placeholders (early season) | ~450 placeholder rows |
| player_daily_cache | 3-5 per player | **Skip** (< 5 games) | **0 rows** |
| player_composite_factors | N/A | **Skip** | **0 rows** |
| ml_feature_store | N/A | **Skip** | **0 rows** |

---

### Week 3: Days 14-20 (Nov 3-9)

| Processor | Games Available | Behavior | Output |
|-----------|----------------|----------|--------|
| team_defense_zone_analysis | 7-9 per team | **Skip teams** (need 15) | **0 rows** ⚠️ |
| player_shot_zone_analysis | 6-8 per player | **Skip players** (need 10) | **0 rows** ⚠️ |
| player_daily_cache | 6-8 per player | **Write partial cache** | ~450 rows with early_season_flag |
| player_composite_factors | Cache available | Write placeholders (>50% early) | ~450 placeholder rows |
| ml_feature_store | Cache available | Write placeholders (>50% early) | ~450 placeholder rows |

**CRITICAL ISSUE**: Zone analysis processors **stop writing** because early_season_threshold passed but insufficient games!

**Failed Entities**: Team/player records logged as failed with `can_retry: True`.

---

### Week 4-5: Days 21-35 (Nov 10-24)

| Processor | Games Available | Behavior | Output |
|-----------|----------------|----------|--------|
| team_defense_zone_analysis | 12-14 per team | **Skip teams** (need 15) | **0 rows** ⚠️ |
| player_shot_zone_analysis | 9-12 per player | **Mixed** (some reach 10) | Partial coverage |
| player_daily_cache | 9-12 per player | **Write partial/full** | ~450 rows (some full quality) |
| player_composite_factors | Cache + some zone data | **Process with missing fields** | ~450 rows with warnings |
| ml_feature_store | Mixed upstream | **Process with partial features** | ~450 rows with quality flags |

**Note**: Coverage gradually improves as players/teams cross thresholds at different rates.

---

### Week 6+: Days 36+ (Nov 25+)

| Processor | Games Available | Behavior | Output |
|-----------|----------------|----------|--------|
| team_defense_zone_analysis | 15+ per team | **Process normally** | 30 rows (full quality) |
| player_shot_zone_analysis | 10+ per player | **Process normally** | ~450 rows (L10 available) |
| player_daily_cache | 10+ per player | **Process normally** | ~450 rows (full quality) |
| player_composite_factors | Full upstream | **Process normally** | ~450 rows |
| ml_feature_store | Full upstream | **Process normally** | ~450 rows |

**Steady State**: All processors producing high-quality output.

---

## Partial Data Handling Matrix

### Summary Table

| Processor | Absolute Min | Preferred Min | Early Season Threshold | Placeholder Behavior | Skip Behavior |
|-----------|--------------|---------------|----------------------|---------------------|---------------|
| team_defense_zone_analysis | N/A | 15 games | 14 days | Days 0-13: Write placeholders | Days 14+: Skip if < 15 games |
| player_shot_zone_analysis | N/A | 10 games | 14 days | Days 0-13: Write placeholders | Days 14+: Skip if < 10 games |
| player_daily_cache | 5 games | 10 games | 14 days | Days 0-13: Write placeholders | Days 14+: Skip if < 5, flag if 5-9 |
| player_composite_factors | N/A (cascade) | N/A | 50% threshold | If >50% upstream early | Process with missing field warnings |
| ml_feature_store | N/A (cascade) | N/A | 50% threshold | If >50% upstream early | N/A (always processes if cache exists) |

### Recommendations for Backfill

**Option 1: Strict Thresholds (Current Implementation)**
- Pros: High data quality, clear early season signal
- Cons: Days 14-35 have **NO records** for zone analysis processors
- **Impact**: Missing 3 weeks of data during backfill

**Option 2: Relaxed Thresholds for Backfill** ⭐ RECOMMENDED
- Modify early_season_threshold from 14 → 30 days for backfill runs
- Pros: Continuous data coverage, graceful quality degradation
- Cons: Lower quality data during Days 14-30
- **Impact**: Full coverage with quality flags

**Option 3: Progressive Fill Strategy**
- First pass: Process all dates with strict thresholds (Days 0-13, 36+)
- Second pass: Retry failed entities (Days 14-35)
- Pros: Two-tier quality approach
- Cons: Requires manual retry logic

---

## Alert & Retry Strategy

### Alert Levels

#### 1. INFO (Log Only)

**Trigger**: Expected partial data during early season or backfill

**Examples**:
- "Early season detected: 5 days since season start"
- "Player X: Only 7 games available, need 10 minimum" (when < 14 days)
- "Writing placeholder rows for 30 teams"

**Action**: None - expected behavior

---

#### 2. WARNING (Log + Email)

**Trigger**: Unexpected partial data mid-season

**Examples**:
- "Day 20 of season: Only 250/450 players have 10+ games"
- "Team LAL: Only 8 games after 15 days (missed games?)"
- "50% of composite factors have missing shot zone data"

**Action**:
- Email to: `nchammas@gmail.com`
- Subject: "[NBA] Warning: Unexpected Partial Data - [Processor]"
- Check for upstream processing failures

---

#### 3. ERROR (Log + Email + Slack)

**Trigger**: Critical processing failure

**Examples**:
- "Failed to process ANY teams/players"
- "Dependency check failed: player_game_summary missing"
- "BigQuery write failed after 3 retries"

**Action**:
- Email to: `nchammas@gmail.com` (critical recipients)
- Slack alert (if configured)
- Manual investigation required

---

### Retry Strategy

#### Automatic Retry (Built-in)

**When**: Failed entities with `can_retry: True`

**How**:
```python
# In processor code (already implemented)
failed.append({
    'entity_id': player_lookup,
    'reason': f"Only {games_count} games, need {min_games_required}",
    'category': 'INSUFFICIENT_DATA',
    'can_retry': True  # Processor marks as retryable
})
```

**Behavior**:
- Failed entities logged but not written
- Next run (next day) will attempt again
- If more games available, will succeed
- If still insufficient, will fail again

**No manual intervention needed** - processor retries automatically on next scheduled run.

---

#### Manual Retry (User-Initiated)

**When**: Need to reprocess specific date range (e.g., after backfill completes)

**Command Pattern**:
```bash
# Retry single date
python -m data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor \
    --analysis_date 2020-11-05

# Retry date range (if script supports it)
./bin/precompute/retry_failed_dates.sh \
    --processor player_shot_zone_analysis \
    --start_date 2020-11-03 \
    --end_date 2020-11-09
```

**Use Cases**:
1. After backfill reaches sufficient data (Day 36+)
2. After correcting upstream data issues
3. Testing processor changes

---

#### Intelligent Retry Logic

**Concept**: Track which dates have failed entities and retry only those.

```python
# Query failed entity dates
query = """
SELECT DISTINCT game_date, COUNT(*) as failed_count
FROM `nba_precompute.player_shot_zone_analysis`
WHERE early_season_flag = TRUE
  OR insufficient_data_reason IS NOT NULL
  AND game_date BETWEEN '2020-11-03' AND '2020-11-09'
GROUP BY game_date
ORDER BY game_date
"""

# Retry only dates with failed entities
for date_row in results:
    if date_row['failed_count'] > 100:  # Threshold for retry
        retry_processor(analysis_date=date_row['game_date'])
```

---

## Implementation Recommendations

### 1. Update Documentation ✅

**Files to update**:
- ✅ Created: `docs/implementation/05-phase4-historical-dependencies-complete.md` (this file)
- 📝 Update: `docs/implementation/04-dependency-checking-strategy.md` with findings
- 📝 Add: `docs/operations/backfill-guide-phase4.md` with step-by-step instructions

---

### 2. Add Historical Range Checking (Optional)

**Priority**: Medium (can add after deployment)

**Approach**: Add MAX(processed_at) window checking per processor

**Processors to update**:
1. team_defense_zone_analysis (L15 window)
2. player_shot_zone_analysis (L10/L20 window)
3. player_daily_cache (L5/L7/L10/L14 windows)

**Schema additions**:
```sql
-- Add to each processor's schema
source_{prefix}_window_last_updated TIMESTAMP,
source_{prefix}_window_size INT64
```

**Code pattern**:
```python
# Extract max processed_at across window
max_processed_at = self._get_max_processed_at_in_window(
    entity_lookup,
    analysis_date,
    lookback_games=15
)

# Store in record
record['source_team_defense_window_last_updated'] = max_processed_at
record['source_team_defense_window_size'] = games_in_window
```

**Estimated effort**: 4-6 hours across all processors

---

### 3. Backfill Mode Configuration

**Add environment variable**: `BACKFILL_MODE=true`

**Behavior changes when enabled**:
```python
if os.environ.get('BACKFILL_MODE') == 'true':
    # Relax early season threshold
    self.early_season_threshold_days = 30  # Instead of 14

    # Lower minimum game requirements
    self.min_games_required = max(self.min_games_required - 3, 5)

    # Change placeholder behavior
    self.early_season_behavior = 'WRITE_PARTIAL'  # Instead of 'WRITE_PLACEHOLDER'
```

**Usage**:
```bash
# Normal mode
gcloud run services update nba-phase4-precompute-processors

# Backfill mode
gcloud run services update nba-phase4-precompute-processors \
    --set-env-vars BACKFILL_MODE=true
```

**Estimated effort**: 2-3 hours

---

### 4. Improve Alert Messaging

**Current**: Generic "Early season detected"

**Improved**: Specific, actionable messages

```python
# Before
logger.warning("Early season detected")

# After
if days_since_season_start < 14:
    logger.info(
        f"Early season (Day {days_since_season_start}): Writing placeholders. "
        f"Normal processing begins Day 14."
    )
elif days_since_season_start < 30:
    logger.warning(
        f"Transitional period (Day {days_since_season_start}): "
        f"{teams_with_data}/{total_teams} teams have {min_games_required}+ games. "
        f"Skipping teams with insufficient data."
    )
```

**Estimated effort**: 1-2 hours

---

### 5. Monitoring Dashboard Queries

**Add to monitoring dashboard**:

```sql
-- Query 1: Failed entity counts by date
SELECT
    analysis_date,
    COUNT(*) as total_records,
    SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_count,
    SUM(CASE WHEN insufficient_data_reason IS NOT NULL THEN 1 ELSE 0 END) as insufficient_data_count
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date >= CURRENT_DATE() - 30
GROUP BY analysis_date
ORDER BY analysis_date DESC
```

```sql
-- Query 2: Data quality progression
SELECT
    analysis_date,
    AVG(CASE WHEN data_quality_tier = 'high' THEN 1.0 ELSE 0.0 END) as pct_high_quality,
    AVG(cache_quality_score) as avg_quality_score
FROM `nba_precompute.player_daily_cache`
WHERE analysis_date >= CURRENT_DATE() - 30
GROUP BY analysis_date
ORDER BY analysis_date DESC
```

---

## Deployment Decision

### Current Status

✅ **Ready to deploy without historical range checking**
- Smart idempotency (skip writes) works perfectly
- Dependency checking comprehensive
- Partial data handling well-designed
- Early season logic solid

⚠️ **Historical range checking incomplete**
- May miss backfills of games 5-15 in window
- May over-reprocess when not needed
- Can add later based on real behavior

### Recommended Approach

**Phase 1: Deploy Now** (Today)
- Deploy Phase 3 & Phase 4 with current implementation
- Monitor first week for issues
- Measure skip rates and reprocessing patterns

**Phase 2: Historical Range Checking** (Week 2)
- Add MAX(processed_at) window checking if needed
- Based on real production behavior
- 4-6 hours of work

**Phase 3: Backfill** (Week 3+)
- Run backfill with BACKFILL_MODE=true
- Monitor failed entity retry patterns
- Document lessons learned

---

## Summary

| Processor | Historical Range | Min Games | Early Season | Backfill Strategy |
|-----------|-----------------|-----------|--------------|-------------------|
| team_defense_zone_analysis | L15 games | 15 | 14 days | Placeholders → Skip → Process |
| player_shot_zone_analysis | L10/L20 games | 10 | 14 days | Placeholders → Skip → Process |
| player_daily_cache | L5/L7/L10/L14 | 5 (abs), 10 (pref) | 14 days | Skip → Partial → Full |
| player_composite_factors | Cascade | N/A | 50% threshold | Placeholders → Partial → Full |
| ml_feature_store | Cascade | N/A | 50% threshold | Placeholders → Full |

**Key Insight**: The cascade design is elegant - early processors define thresholds, later processors inherit quality flags. This enables graceful degradation during backfill without complex retry logic.

**Ready for deployment** with plan to add historical range checking if production monitoring shows it's needed.

---

**Next Steps**:
1. Review this document with user
2. Decide: deploy now or add historical range checking first
3. Create backfill operations guide
4. Update dependency tracking documentation
