# Architectural Analysis: Data Dependencies and Completeness Gaps
## Why Missing Historical Data Doesn't Block Downstream Processing

**Created:** January 22, 2026
**Context:** Team boxscore data gap incident analysis
**Purpose:** Document the architectural gaps that allow bad predictions to be made with incomplete historical data

---

## Executive Summary

The current pipeline architecture has a fundamental flaw: **completeness checks validate TODAY's data exists, but don't validate that the HISTORICAL data needed for calculations exists.**

This allows:
- Predictions to run with stale/incomplete rolling averages
- Downstream dates to process while upstream dates have gaps
- Quality degradation to go undetected for weeks

---

## 1. Current Completeness Check Architecture

### 1.1 What We Check Today

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT VALIDATION                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Processing Date: Jan 22, 2026                              │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Completeness Check #1: Schedule                      │   │
│  │ Query: SELECT COUNT(*) FROM schedule                 │   │
│  │        WHERE game_date = '2026-01-22'               │   │
│  │ Result: 7 games → PASS ✓                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Completeness Check #2: Gamebook                      │   │
│  │ Query: SELECT COUNT(*) FROM gamebook                 │   │
│  │        WHERE game_date = '2026-01-22'               │   │
│  │ Result: 247 records → PASS ✓                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Completeness Check #3: Props                         │   │
│  │ Query: SELECT COUNT(*) FROM props                    │   │
│  │        WHERE game_date = '2026-01-22'               │   │
│  │ Result: 28,000+ lines → PASS ✓                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ALL CHECKS PASS → PROCEED WITH PROCESSING                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 What We DON'T Check

```
┌─────────────────────────────────────────────────────────────┐
│                    MISSING VALIDATION                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✗ Is yesterday's team_boxscore complete?                   │
│  ✗ Are all 10 games in the rolling window present?          │
│  ✗ Is the 7-day historical window complete?                 │
│  ✗ Do we have team stats for opponent's recent games?       │
│  ✗ Is the data we're about to USE actually there?           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 The Fundamental Gap

**Current Logic:**
```python
def should_process(game_date):
    # Check: Does today's data exist?
    if schedule_exists(game_date) and gamebook_exists(game_date):
        return True  # PROCEED
    return False
```

**What's Missing:**
```python
def should_process(game_date):
    # Check: Does today's data exist?
    if not schedule_exists(game_date):
        return False

    # CHECK: Does the data we NEED for calculations exist?
    if not rolling_window_complete(game_date, window=10):
        return False  # ← THIS IS MISSING

    if not historical_team_data_complete(game_date, lookback=7):
        return False  # ← THIS IS MISSING

    return True
```

---

## 2. The Rolling Window Problem

### 2.1 How Rolling Averages Work

```python
# player_daily_cache_processor.py (simplified)
def calculate_rolling_stats(player_id, analysis_date):
    query = """
        SELECT points, minutes, usage_rate
        FROM player_game_summary
        WHERE player_lookup = @player_id
          AND game_date <= @analysis_date
        ORDER BY game_date DESC
        LIMIT 10
    """
    games = run_query(query)
    return {
        'points_avg_last_10': mean(games.points),
        'minutes_avg_last_10': mean(games.minutes),
    }
```

### 2.2 The Problem: LIMIT 10 Doesn't Validate Completeness

```
Expected behavior:
  "Get the last 10 games this player played"

Actual behavior:
  "Get the 10 most recent rows in the table"

When data is missing:
  The query still returns 10 rows, but they're the WRONG 10 games!
```

**Example with Data Gap:**

```
Player: LeBron James
Analysis Date: Jan 22, 2026
Gap Period: Dec 27 - Jan 21 (team boxscore missing)

Expected 10-game window:
  Jan 22, Jan 20, Jan 18, Jan 15, Jan 13, Jan 10, Jan 8, Jan 5, Jan 3, Jan 1

Actual query result (with gap):
  Jan 22, Jan 20, Dec 26, Dec 24, Dec 22, Dec 20, Dec 18, Dec 15, Dec 13, Dec 11

Problem:
  - 8 of 10 games are from BEFORE the gap (3+ weeks old)
  - Rolling average reflects December performance, not January
  - No error thrown - query "succeeded" with 10 rows
```

### 2.3 The Staleness Problem

```
┌────────────────────────────────────────────────────────────────┐
│                ROLLING WINDOW STALENESS                         │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Normal (no gap):                                              │
│  ├── Game 1: Jan 22 (today)                                    │
│  ├── Game 2: Jan 20 (2 days ago)                               │
│  ├── Game 3: Jan 18 (4 days ago)                               │
│  ├── ...                                                       │
│  └── Game 10: Jan 1 (21 days ago)                              │
│  Window span: 21 days ✓ HEALTHY                                │
│                                                                │
│  With 4-week gap:                                              │
│  ├── Game 1: Jan 22 (today)                                    │
│  ├── Game 2: Jan 20 (2 days ago)                               │
│  ├── Game 3: Dec 26 (27 days ago!) ← GAP JUMP                  │
│  ├── Game 4: Dec 24 (29 days ago)                              │
│  ├── ...                                                       │
│  └── Game 10: Dec 11 (42 days ago)                             │
│  Window span: 42 days ✗ DEGRADED                               │
│                                                                │
│  Result: 80% of "recent" games are 4+ weeks old                │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Why Downstream Dates Keep Running

### 3.1 The Independence Illusion

Each day's processing is treated as INDEPENDENT:

```
Day N processing doesn't ask:
  "Did Day N-1 complete successfully?"
  "Is Day N-1's data available for my calculations?"

It only asks:
  "Is Day N's input data available?"
```

### 3.2 The Cascade Blindness

```
┌─────────────────────────────────────────────────────────────────┐
│                     PROCESSING TIMELINE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Dec 26: team_boxscore scraped ✓                                │
│  Dec 27: team_boxscore FAILS (scraper error) ✗                  │
│  Dec 28: team_boxscore FAILS ✗                                  │
│  ...                                                            │
│  Jan 20: team_boxscore FAILS ✗                                  │
│  Jan 21: team_boxscore FAILS ✗                                  │
│                                                                 │
│  BUT MEANWHILE...                                               │
│                                                                 │
│  Dec 28: Predictions run! Uses Dec 26 + older data              │
│  Dec 29: Predictions run! Uses Dec 26 + older data              │
│  ...                                                            │
│  Jan 21: Predictions run! Uses Dec 26 + older data              │
│                                                                 │
│  Each day's completeness check PASSES because:                  │
│  - Today's schedule exists ✓                                    │
│  - Today's gamebook exists ✓                                    │
│  - Today's props exist ✓                                        │
│                                                                 │
│  Nobody checks:                                                 │
│  - "Does yesterday's team_boxscore exist?"                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 The Quality Score Doesn't Reflect Reality

```python
# Current quality score calculation
def calculate_feature_quality(features):
    # Checks: Are features non-null?
    # Checks: Are features within expected ranges?
    # Does NOT check: Are features FRESH?
    # Does NOT check: Is the rolling window COMPLETE?

    if all(f is not None for f in features):
        return 100  # "Perfect" quality
```

**The lie:** A "100% quality" feature set can be built entirely from stale data.

---

## 4. Data Lineage and Cascade Effects

### 4.1 Dependency Graph

```
                    SOURCE DATA (Phase 1-2)
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   nbac_schedule    nbac_gamebook    nbac_team_boxscore ← MISSING
         │                 │                 │
         └────────┬────────┘                 │
                  ▼                          │
         player_game_summary                 │
                  │                          │
         ┌───────┴────────┐                  │
         ▼                ▼                  ▼
   upcoming_player_   team_defense_    team_offense_
   game_context       game_summary     game_summary
         │                 │                 │
         └────────┬────────┴────────┬────────┘
                  ▼                 ▼
         upcoming_team_game_context
                           │
                           ▼
                  player_daily_cache
                  (ROLLING WINDOWS!)
                           │
                           ▼
               player_composite_factors
                           │
                           ▼
                   ml_feature_store
                           │
                           ▼
                     PREDICTIONS
```

### 4.2 Cascade Scope After Backfill

When we backfill `nbac_team_boxscore` for Dec 27 - Jan 21:

```
DIRECT REPROCESSING NEEDED (Gap Period):
├── team_defense_game_summary   (Dec 27 - Jan 21)
├── team_offense_game_summary   (Dec 27 - Jan 21)
├── upcoming_team_game_context  (Dec 27 - Jan 21)
├── player_daily_cache          (Dec 27 - Jan 21)
├── player_composite_factors    (Dec 27 - Jan 21)
├── ml_feature_store            (Dec 27 - Jan 21)
└── predictions                 (Dec 27 - Jan 21)

INDIRECT REPROCESSING NEEDED (Post-Gap):
├── player_daily_cache          (Jan 22 - Feb 15)
│   └── Why? Rolling windows include gap-period games
├── player_composite_factors    (Jan 22 - Feb 15)
├── ml_feature_store            (Jan 22 - Feb 15)
└── predictions                 (Jan 22 - Feb 15)
    └── Why? Features were calculated with stale windows
```

### 4.3 The "Healing" Timeline

```
Rolling window recovery after backfill:

Jan 22: Backfill complete
        Rolling window: 1 new game, 9 from gap period
        Quality: 10% current

Jan 25: 4 days later
        Rolling window: 4 new games, 6 from gap period
        Quality: 40% current

Feb 1:  10 days later
        Rolling window: 7 new games, 3 from gap period
        Quality: 70% current

Feb 8:  17 days later
        Rolling window: 10 new games, 0 from gap period
        Quality: 100% current ← FULLY HEALED
```

---

## 5. Why Current Checks Don't Catch This

### 5.1 Check #1: Schedule-Based Completeness

```python
# shared/utils/completeness_checker.py
def check_schedule_completeness(game_date):
    expected = count_scheduled_games(game_date)
    actual = count_records_in_table(game_date)
    return actual >= expected * 0.8
```

**Gap:** Only checks current day. Historical completeness ignored.

### 5.2 Check #2: Phase Boundary Validation

```python
# shared/validation/phase_boundary_validator.py
def validate_phase_boundary(from_phase, to_phase, game_date):
    # Check: Is from_phase complete for TODAY?
    return from_phase_complete(game_date)  # ← Only today!
```

**Gap:** Doesn't check if yesterday's phase completed.

### 5.3 Check #3: Catch-Up System

```yaml
# shared/config/scraper_retry_config.yaml
nbac_team_boxscore:
  lookback_days: 3  # Only checks 3 days back!
```

**Gap:** 3-day window misses longer gaps entirely.

### 5.4 Check #4: Dependency Validation in Processors

```python
# Typical processor pattern
def get_dependencies(self):
    return {
        'nba_raw.nbac_team_boxscore': {
            'expected_count_min': 10,
            'max_age_hours': 24,  # ← Only checks freshness for TODAY
        }
    }
```

**Gap:** `max_age_hours` checks if today's data is fresh, not if historical data exists.

---

## 6. The Prediction Quality Impact

### 6.1 How Bad Predictions Get Made

```
┌─────────────────────────────────────────────────────────────────┐
│                  BAD PREDICTION FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Jan 22 processing starts                                    │
│                                                                 │
│  2. Completeness check: "Is Jan 22 data ready?"                 │
│     → YES ✓ (today's data exists)                               │
│                                                                 │
│  3. Calculate rolling averages:                                 │
│     Query: SELECT * FROM games ORDER BY date DESC LIMIT 10      │
│     Result: Jan 22, Jan 20, Dec 26, Dec 24...                   │
│     → Returns 10 rows ✓ (no error)                              │
│                                                                 │
│  4. Build ML features:                                          │
│     points_avg_last_10 = 24.2 (stale, should be 27.5)           │
│     → No validation that window is healthy                      │
│                                                                 │
│  5. Generate prediction:                                        │
│     Model sees: avg=24.2, expects low scoring                   │
│     Predicts: 23.5 points                                       │
│     Actual: 29 points                                           │
│     → Prediction off by 5.5 points!                             │
│                                                                 │
│  6. Quality score: 95% (lies - data was stale)                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 The Confidence Score Lie

```python
# Current confidence calculation
confidence = 75.0  # Base

if feature_quality >= 90:
    confidence += 10  # Boost for "high quality"

# But feature_quality doesn't account for:
# - Rolling window staleness
# - Historical data gaps
# - Degraded team context

# Result: High confidence on bad predictions
```

---

## 7. Summary of Architectural Gaps

| Gap | Current Behavior | Required Behavior |
|-----|------------------|-------------------|
| **Completeness scope** | Validates today only | Validate today + historical window |
| **Rolling window validation** | None | Validate all games in window exist |
| **Cross-day dependencies** | None | Check yesterday completed before today |
| **Data staleness tracking** | None | Track age of data used in calculations |
| **Cascade awareness** | None | Know what downstream tables are affected |
| **Quality score accuracy** | Reflects nulls only | Reflect data freshness and completeness |

---

## Next Steps

See companion document: **SOLUTION-PROPOSAL-DATA-DEPENDENCY-VALIDATION.md**

This document proposes:
1. Historical dependency validation system
2. Rolling window integrity checks
3. Cascade reprocessing algorithm
4. Data lineage tracking
5. Quality score improvements

---

**Document Status:** Analysis Complete
**Next Action:** Review solution proposal
