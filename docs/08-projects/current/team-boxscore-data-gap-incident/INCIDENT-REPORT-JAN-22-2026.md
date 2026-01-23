# Team Boxscore Data Gap Incident Report
## January 22, 2026

**Incident Discovery Date:** January 22, 2026
**Data Gap Period:** December 27, 2025 - January 21, 2026 (26 days)
**Games Affected:** 100 games
**Status:** Analysis Complete, Backfill Pending

---

## Executive Summary

A critical data gap was discovered in the `nbac_team_boxscore` table spanning **4 weeks** (Dec 27, 2025 - Jan 21, 2026). The last successful team boxscore scrape was December 26, 2025. This gap caused **cascading failures** across the entire analytics pipeline, resulting in:

- **0 predictions generated** for January 21, 2026
- **Corrupted rolling averages** for all players (10-game windows affected)
- **Degraded ML model accuracy** (~3.6% quality loss, confidence drops 10-20%)
- **Phase 3-5 processor failures** due to missing upstream dependencies

This document analyzes the root cause, cascade effects, detection gaps, and proposes prevention strategies.

---

## Table of Contents

1. [What Needs to Be Backfilled](#1-what-needs-to-be-backfilled)
2. [The Cascade Effect Analysis](#2-the-cascade-effect-analysis)
3. [Impact on Completeness Checks](#3-impact-on-completeness-checks)
4. [Impact on Downstream Calculations](#4-impact-on-downstream-calculations)
5. [Why This Wasn't Detected Earlier](#5-why-this-wasnt-detected-earlier)
6. [Detection Mechanisms Needed](#6-detection-mechanisms-needed)
7. [Prevention Strategies](#7-prevention-strategies)
8. [Backfill Execution Plan](#8-backfill-execution-plan)
9. [Recovery Timeline](#9-recovery-timeline)
10. [Lessons Learned](#10-lessons-learned)

---

## 1. What Needs to Be Backfilled

### 1.1 Primary Data Gap

| Table | Dataset | Gap Period | Records Missing | Status |
|-------|---------|------------|-----------------|--------|
| `nbac_team_boxscore` | `nba_raw` | Dec 27 - Jan 21 | ~200 team records | **CRITICAL** |

### 1.2 Games Requiring Backfill

**Total Games:** 100 games across 26 days

```
Date Range Breakdown:
- December 2025: 28 games (Dec 27-31)
- January 2026: 72 games (Jan 1-21)
```

**Game IDs have been populated in:**
```
/backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv
```

### 1.3 Downstream Tables Affected (Cascade)

After `nbac_team_boxscore` is backfilled, these tables need reprocessing:

| Phase | Table | Dataset | Dependency | Reprocess Order |
|-------|-------|---------|------------|-----------------|
| 2 | `nbac_team_boxscore` | `nba_raw` | Scraper | 1 (backfill) |
| 3 | `team_defense_game_summary` | `nba_analytics` | `nbac_team_boxscore` | 2 |
| 3 | `team_offense_game_summary` | `nba_analytics` | `nbac_team_boxscore` | 2 |
| 3 | `upcoming_team_game_context` | `nba_analytics` | team summaries | 3 |
| 4 | `player_daily_cache` | `nba_precompute` | team context | 4 |
| 4 | `player_composite_factors` | `nba_precompute` | team context + cache | 5 |
| 4 | `ml_feature_store_v2` | `nba_predictions` | all Phase 4 | 6 |
| 5 | `player_prop_predictions` | `nba_predictions` | ML features | 7 |

---

## 2. The Cascade Effect Analysis

### 2.1 Dependency Chain Visualization

```
                    ┌─────────────────────────────┐
                    │   nbac_team_boxscore        │
                    │   (PRIMARY DATA SOURCE)     │
                    │   MISSING: Dec 27 - Jan 21  │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────┴───────────────┐
                    ▼                             ▼
        ┌───────────────────────┐   ┌───────────────────────┐
        │ team_defense_game_    │   │ team_offense_game_    │
        │ summary               │   │ summary               │
        │ IMPACT: 0 rows        │   │ IMPACT: Uses fallback │
        │ for gap period        │   │ (reconstructed)       │
        └───────────┬───────────┘   └───────────┬───────────┘
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │ upcoming_team_game_context  │
                    │ IMPACT: 0 rows for Jan 21   │
                    │ (Missing team pace, lines)  │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────┴───────────────┐
                    ▼                             ▼
        ┌───────────────────────┐   ┌───────────────────────┐
        │ player_daily_cache    │   │ player_composite_     │
        │                       │   │ factors               │
        │ IMPACT: Rolling       │   │ IMPACT: DependencyErr │
        │ averages stale/wrong  │   │ (missing team context)│
        └───────────┬───────────┘   └───────────┬───────────┘
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │ ml_feature_store_v2         │
                    │ IMPACT: DependencyError     │
                    │ 143/246 players only        │
                    │ ~50% feature quality lost   │
                    └─────────────┬───────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │ player_prop_predictions     │
                    │ IMPACT: 0 predictions       │
                    │ (Phase 5 blocked)           │
                    └─────────────────────────────┘
```

### 2.2 Cascade Effect by Phase

| Phase | Processor | Failure Mode | Downstream Impact |
|-------|-----------|--------------|-------------------|
| **Phase 2** | Raw team boxscore processor | No data to process | Phase 3 blocked |
| **Phase 3** | TeamDefenseGameSummaryProcessor | Returns 0 rows | Composite factors fail |
| **Phase 3** | TeamOffenseGameSummaryProcessor | Falls back to reconstruction | Quality degraded |
| **Phase 3** | UpcomingTeamGameContextProcessor | Returns 0 rows | **CRITICAL BLOCKER** |
| **Phase 4** | PlayerCompositeFacorsProcessor | `DependencyError` | ML features incomplete |
| **Phase 4** | MLFeatureStoreProcessor | `DependencyError` | Predictions blocked |
| **Phase 5** | PredictionCoordinator | No features available | **0 PREDICTIONS** |

### 2.3 The Domino Effect in Detail

**Day 1 (Dec 27): Silent Failure Begins**
1. Team boxscore scraper attempts to fetch data
2. Scraper fails (148 consecutive failures logged)
3. Error: "Expected 2 teams for game X, got 0"
4. Root cause: Scraper querying games before completion
5. No alert triggered (errors below threshold? or ignored)

**Days 2-26: Data Gap Accumulates**
1. Each day, scraper continues failing
2. `team_defense_game_summary` has no new data
3. Rolling averages become increasingly stale
4. Completeness checks DON'T catch this (see Section 3)

**Day 26 (Jan 21): Cascade Failure Manifests**
1. Pipeline runs for Jan 21 games
2. `upcoming_team_game_context` returns 0 rows
3. `PlayerCompositeFactorsProcessor` fails with DependencyError
4. `MLFeatureStoreProcessor` fails (missing composite factors)
5. Phase 5 receives no features
6. **Result: 0 predictions generated**

---

## 3. Impact on Completeness Checks

### 3.1 Why Completeness Checks Didn't Catch This

The system has THREE completeness check mechanisms, and **ALL THREE** have blind spots that allowed this gap to persist undetected:

#### Mechanism 1: Schedule-Based Completeness Check

**Location:** `shared/utils/completeness_checker.py`

**How it works:**
```python
# Checks: Do we have data for today's scheduled games?
expected = scheduled_games_count(analysis_date)
actual = records_in_table(analysis_date)
completeness = actual / expected
```

**Blind Spot:** Only checks the CURRENT day being processed, NOT historical data completeness.

```
Example:
- Jan 21 scheduled games: 7
- Jan 21 team boxscore records: 0 (gap!)
- BUT: Check only runs for today's processing date
- Historical dates (Dec 27 - Jan 20) are NEVER re-validated
```

#### Mechanism 2: Phase Boundary Validation

**Location:** `shared/validation/phase_boundary_validator.py`

**How it works:**
```python
# Checks: Is Phase N complete before Phase N+1 starts?
game_count_ratio = actual_games / expected_games
if game_count_ratio >= 0.8:  # 80% threshold
    return PASS
```

**Blind Spot:** Uses `game_date = CURRENT_DATE` filter - doesn't look backward.

```python
# The validation query:
SELECT COUNT(DISTINCT game_id)
FROM table
WHERE game_date = CURRENT_DATE  # <-- Only today!
```

#### Mechanism 3: Catch-Up System

**Location:** `bin/scraper_catchup_controller.py`

**Config:** `shared/config/scraper_retry_config.yaml`

**How it works:**
```yaml
nbac_team_boxscore:
  lookback_days: 3  # Only checks last 3 days!
```

**Blind Spot:** 3-day lookback window is too short to detect multi-week gaps.

```
On Jan 21:
- Catch-up checks: Jan 18, 19, 20
- Gap start: Dec 27
- Days missed: 22 days completely invisible!
```

### 3.2 Completeness Check Gap Analysis

| Check Type | Lookback Window | Gap Detection | Result |
|------------|-----------------|---------------|--------|
| Schedule-based | Current day only | **NO** | Missed 26 days |
| Phase boundary | Current day only | **NO** | Missed 26 days |
| Catch-up system | 3 days | **NO** | Missed 22+ days |
| Cross-phase validation | Current day | **NO** | Missed gap entirely |

### 3.3 How Rolling Window Checks Are Affected

**Problem:** Processors using rolling windows (10 games, 5 games) DON'T validate that all games in the window exist.

```python
# Current pattern (player_daily_cache_processor.py):
def get_player_rolling_stats(player_id, lookback=10):
    query = """
        SELECT * FROM player_game_summary
        WHERE player_id = @player
        ORDER BY game_date DESC
        LIMIT 10  -- Gets 10 most recent, regardless of gaps!
    """
```

**The Problem Illustrated:**

```
Expected 10-game window for Player X on Jan 21:
  Game 10: Jan 20 ✓ (exists)
  Game 9:  Jan 18 ✓ (exists)
  Game 8:  Jan 15 ✗ (MISSING - gap)
  Game 7:  Jan 12 ✗ (MISSING - gap)
  Game 6:  Jan 10 ✗ (MISSING - gap)
  Game 5:  Jan 7  ✗ (MISSING - gap)
  Game 4:  Jan 5  ✗ (MISSING - gap)
  Game 3:  Jan 2  ✗ (MISSING - gap)
  Game 2:  Dec 30 ✗ (MISSING - gap)
  Game 1:  Dec 26 ✓ (exists - pre-gap)

Actual query returns:
  Jan 20, Jan 18, Dec 26, Dec 24, Dec 22, Dec 20, Dec 18, Dec 16, Dec 14, Dec 12

Result: 8 of 10 "recent" games are from 3+ weeks ago!
Rolling average is STALE and MISLEADING.
```

---

## 4. Impact on Downstream Calculations

### 4.1 Rolling Average Corruption

**Affected Features:**

| Feature | Window | Impact During Gap | Staleness |
|---------|--------|-------------------|-----------|
| `points_avg_last_10` | 10 games | 8/10 games from pre-gap | **27 days stale** |
| `points_avg_last_5` | 5 games | 3-4/5 games from pre-gap | **21+ days stale** |
| `minutes_avg_last_10` | 10 games | Includes holiday pattern | Misleading |
| `usage_rate_last_10` | 10 games | Pre-holiday usage | Wrong baseline |
| `ts_pct_last_10` | 10 games | Old shooting patterns | Inaccurate |

**Mathematical Impact:**

```
Example: LeBron James scoring trend
- Actual recent games (Jan): 28, 31, 27, 29, 30 PPG
- Pre-gap games (Dec): 24, 22, 25, 23, 26 PPG (holiday rest)

Expected 10-game average: 26.5 PPG
Actual calculated (with gap): 24.2 PPG (-2.3 points bias!)

Prediction impact: Model underestimates by ~2 points
```

### 4.2 Team Pace Calculation Errors

**How Team Pace Is Calculated:**

```python
# team_offense_game_summary_processor.py
pace = (fga + 0.44 * fta - oreb + tov) / minutes * 48
team_pace_last_10 = AVG(pace) OVER last 10 team games
```

**Gap Impact:**

| Team | Actual Pace (Jan) | Calculated Pace (with gap) | Error |
|------|-------------------|---------------------------|-------|
| GSW | 103.2 | 100.0 (default) | -3.2 |
| ATL | 101.5 | 100.0 (default) | -1.5 |
| MIL | 98.7 | 100.0 (default) | +1.3 |

**Prediction Impact:**
- Fast teams underestimated (fewer predicted points)
- Slow teams overestimated (more predicted points)

### 4.3 Opponent Defense Rating Errors

**Missing Data:**
```
opponent_def_rating = Points Allowed / 100 Possessions

Without team boxscore:
- Can't calculate opponent's defensive performance
- Falls back to league average (112.0)
- Loses matchup-specific context
```

**Impact Example:**
```
Player vs Elite Defense (actual DRtg: 105):
- Model thinks: average defense (112.0)
- Overestimates points by 3-4

Player vs Poor Defense (actual DRtg: 118):
- Model thinks: average defense (112.0)
- Underestimates points by 3-4
```

### 4.4 Composite Factor Degradation

**Factors Affected:**

| Factor | Calculation | Gap Impact |
|--------|-------------|------------|
| `fatigue_score` | Games in last 7 days + minutes | Wrong games in window |
| `pace_score` | Player pace vs team pace | Team pace missing |
| `shot_zone_mismatch` | Player zones vs opponent defense | Defense zones missing |
| `usage_spike` | Current usage vs 10-game avg | Stale 10-game avg |

### 4.5 ML Feature Quality Degradation

**V8 CatBoost Model - 33 Features:**

| Feature Category | Count | Quality Impact |
|-----------------|-------|----------------|
| Player rolling stats (0-4) | 5 | 100 → 60 (stale windows) |
| Composite factors (5-8) | 4 | 100 → 40 (DependencyError) |
| Context features (9-14) | 6 | 100 → 40 (missing team data) |
| Team features (22-24) | 3 | 100 → 40 (defaults used) |
| Other features (15-21, 25-32) | 15 | 100 (unaffected) |

**Overall Quality Score:**
```
Normal: (33 × 100) / 33 = 100
With Gap: ((15 × 100) + (5 × 60) + (4 × 40) + (6 × 40) + (3 × 40)) / 33
        = (1500 + 300 + 160 + 240 + 120) / 33
        = 2320 / 33
        = 70.3

Quality Degradation: 29.7%
```

---

## 5. Why This Wasn't Detected Earlier

### 5.1 Alert System Gaps

| Alert Type | Expected | Actual | Why It Failed |
|------------|----------|--------|---------------|
| Scraper failure alert | Alert on consecutive failures | None sent | Threshold not reached? |
| Data freshness alert | Alert on stale data | None sent | Only checks current day |
| Completeness alert | Alert on low completeness | None sent | Only checks current day |
| Pipeline failure alert | Alert on 0 predictions | Sent Jan 21 | **26 days late** |

### 5.2 Monitoring Blind Spots

1. **No Historical Completeness Dashboard**
   - We monitor today's data
   - We don't track "data completeness over time"
   - Multi-day gaps are invisible

2. **No Rolling Window Validation**
   - Processors assume data exists
   - No check for "are all 10 games in my window present?"
   - Silently uses whatever data is available

3. **No Cross-Day Dependency Tracking**
   - We validate Phase 2→3→4→5 within a day
   - We don't validate "does today's Phase 4 have good Phase 2 data from yesterday?"

4. **Scraper Error Aggregation Missing**
   - Individual scraper errors logged
   - No aggregation showing "148 consecutive failures"
   - No trend detection

### 5.3 The Silent Failure Pattern

```
Day 1: Scraper fails, logs error, continues
Day 2: Scraper fails, logs error, continues
...
Day 25: Scraper fails, logs error, continues
Day 26: Pipeline has no data, FINALLY alerts

The 25 days of warning were there - nobody was watching.
```

---

## 6. Detection Mechanisms Needed

### 6.1 Historical Completeness Monitor (NEW)

**Purpose:** Detect multi-day data gaps before they cascade

```python
# Proposed: bin/monitoring/historical_completeness_monitor.py

def check_historical_completeness(table, lookback_days=30):
    """
    Check data completeness for each day in lookback window.
    Alert if any day has <80% expected records.
    """
    query = """
    WITH expected AS (
        SELECT game_date, COUNT(*) as expected_count
        FROM nba_raw.nbac_schedule
        WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY)
          AND CURRENT_DATE()
          AND game_status = 3
        GROUP BY game_date
    ),
    actual AS (
        SELECT game_date, COUNT(*) as actual_count
        FROM @table
        WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY)
          AND CURRENT_DATE()
        GROUP BY game_date
    )
    SELECT
        e.game_date,
        e.expected_count,
        COALESCE(a.actual_count, 0) as actual_count,
        ROUND(COALESCE(a.actual_count, 0) / e.expected_count * 100, 1) as pct
    FROM expected e
    LEFT JOIN actual a ON e.game_date = a.game_date
    WHERE COALESCE(a.actual_count, 0) / e.expected_count < 0.8
    ORDER BY e.game_date
    """

    gaps = run_query(query, table=table, lookback=lookback_days)
    if gaps:
        alert(f"HISTORICAL DATA GAP DETECTED in {table}: {len(gaps)} days below 80%")
        return gaps
    return []
```

**Scheduling:** Run daily at 6 AM ET (before pipeline starts)

### 6.2 Rolling Window Integrity Check (NEW)

**Purpose:** Validate that rolling averages have complete data

```python
# Proposed: shared/validation/rolling_window_validator.py

def validate_rolling_window(player_id, window_size=10, analysis_date):
    """
    Ensure the 10-game window for a player has no gaps.
    """
    query = """
    WITH player_games AS (
        SELECT game_date, game_id,
               ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
        FROM nba_analytics.player_game_summary
        WHERE player_lookup = @player_id
          AND game_date <= @analysis_date
        LIMIT @window_size
    )
    SELECT
        MIN(game_date) as oldest_game,
        MAX(game_date) as newest_game,
        DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as date_span,
        COUNT(*) as games_in_window
    FROM player_games
    """

    result = run_query(query)

    # If 10 games span more than 21 days, window is degraded
    if result.date_span > 21:
        log_warning(f"Rolling window degraded: {result.games_in_window} games span {result.date_span} days")
        return False
    return True
```

### 6.3 Scraper Consecutive Failure Alert (NEW)

**Purpose:** Alert immediately when a scraper fails multiple times in a row

```python
# Proposed: shared/alerting/scraper_failure_tracker.py

CONSECUTIVE_FAILURE_THRESHOLD = 10  # Alert after 10 consecutive failures

def track_scraper_result(scraper_name, success, error_message=None):
    """
    Track scraper results and alert on consecutive failures.
    """
    state = get_scraper_state(scraper_name)

    if success:
        state.consecutive_failures = 0
    else:
        state.consecutive_failures += 1
        state.last_error = error_message

        if state.consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
            alert_critical(
                f"SCRAPER CONSECUTIVE FAILURE ALERT\n"
                f"Scraper: {scraper_name}\n"
                f"Consecutive failures: {state.consecutive_failures}\n"
                f"Last error: {error_message}\n"
                f"First failure: {state.first_failure_time}\n"
                f"ACTION REQUIRED: Manual investigation needed"
            )

    save_scraper_state(scraper_name, state)
```

### 6.4 Cross-Day Dependency Validator (NEW)

**Purpose:** Ensure today's pipeline has good historical data

```python
# Proposed: shared/validation/cross_day_validator.py

def validate_upstream_history(analysis_date, lookback_days=7):
    """
    Before running Phase 4, ensure Phase 2 data exists for recent days.
    """
    critical_tables = [
        ('nba_raw.nbac_team_boxscore', 'game_date'),
        ('nba_raw.nbac_gamebook_player_stats', 'game_date'),
        ('nba_analytics.player_game_summary', 'game_date'),
    ]

    issues = []
    for table, date_col in critical_tables:
        query = f"""
        SELECT game_date, COUNT(*) as records
        FROM {table}
        WHERE {date_col} BETWEEN DATE_SUB(@date, INTERVAL @lookback DAY) AND @date
        GROUP BY game_date
        HAVING COUNT(*) < 100
        """
        gaps = run_query(query, date=analysis_date, lookback=lookback_days)
        if gaps:
            issues.append((table, gaps))

    if issues:
        alert(f"UPSTREAM HISTORY INCOMPLETE: {issues}")
        return False
    return True
```

---

## 7. Prevention Strategies

### 7.1 Immediate Fixes (This Week)

| Fix | Priority | Effort | Impact |
|-----|----------|--------|--------|
| Deploy historical completeness monitor | P0 | 2 hours | Detect gaps within 24h |
| Increase catch-up lookback to 14 days | P0 | 30 min | Catch 2-week gaps |
| Add consecutive failure alerting | P0 | 2 hours | Alert within hours |
| Add data freshness dashboard | P1 | 4 hours | Visibility |

### 7.2 Short-Term Improvements (This Month)

| Improvement | Description | Benefit |
|-------------|-------------|---------|
| Rolling window validation | Validate data completeness before using | Prevent stale calculations |
| Cross-day dependency checks | Ensure historical data exists | Prevent cascade failures |
| Scraper health dashboard | Show success/failure trends | Early warning |
| Automated backfill triggering | Auto-detect and backfill gaps | Self-healing |

### 7.3 Long-Term Architecture Changes (This Quarter)

| Change | Description | Benefit |
|--------|-------------|---------|
| Data lineage tracking | Track data flow through pipeline | Understand dependencies |
| Circuit breakers with history | Stop processing if historical data missing | Prevent bad predictions |
| Multi-source redundancy | Add ESPN/CBS as backup sources | Reduce single-point failures |
| Bounded staleness model | Define max age for each feature | Explicit quality guarantees |

### 7.4 Configuration Changes

**Catch-Up System:**
```yaml
# shared/config/scraper_retry_config.yaml
# BEFORE:
nbac_team_boxscore:
  lookback_days: 3

# AFTER:
nbac_team_boxscore:
  lookback_days: 14  # Increased to catch 2-week gaps
  consecutive_failure_alert_threshold: 10
  alert_on_gap: true
```

**Phase Validation:**
```yaml
# BEFORE: Only validates current day
# AFTER: Add historical validation

phase_validation:
  validate_historical: true
  historical_lookback_days: 7
  min_historical_completeness: 0.8
```

---

## 8. Backfill Execution Plan

### 8.1 Prerequisites

- [x] Game IDs CSV populated (100 games)
- [ ] Phase 1 scrapers service healthy
- [ ] Sufficient API rate limit capacity
- [ ] Monitoring in place for backfill progress

### 8.2 Backfill Commands

**Step 1: Run Team Boxscore Scraper Backfill**
```bash
cd /home/naji/code/nba-stats-scraper

# Multi-threaded (faster, ~15-20 min)
PYTHONPATH=. python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --workers=10

# Monitor progress
tail -f backfill_jobs/scrapers/nbac_team_boxscore/failed_games_*.json
```

**Step 2: Process Raw Data (Phase 2)**
```bash
# Trigger Phase 2 processor for each date
for date in $(seq -f "2025-12-%02g" 27 31) $(seq -f "2026-01-%02g" 1 21); do
  curl -X POST "https://nba-phase2-raw-processors-756957797294.us-west2.run.app/process" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\", \"processor\": \"nbac_team_boxscore\"}"
  sleep 2
done
```

**Step 3: Reprocess Phase 3 Analytics**
```bash
# Run Phase 3 for each date
./bin/backfill/run_year_phase3.sh --start-date=2025-12-27 --end-date=2026-01-21
```

**Step 4: Reprocess Phase 4 Precompute**
```bash
# Run Phase 4 for each date
./bin/backfill/run_year_phase4.sh --start-date=2025-12-27 --end-date=2026-01-21
```

**Step 5: Regenerate Predictions for Jan 21**
```bash
# Trigger prediction generation
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/trigger" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-21", "force_regenerate": true}'
```

### 8.3 Verification Queries

**Verify Team Boxscore Backfill:**
```sql
SELECT game_date, COUNT(*) as team_records
FROM nba_raw.nbac_team_boxscore
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Expected: 100 rows total (2 teams × 100 games ÷ 2 = 100)
-- Actually 200 records (2 teams per game)
```

**Verify Phase 3 Analytics:**
```sql
SELECT game_date, COUNT(*) as records
FROM nba_analytics.team_defense_game_summary
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Expected: Records for all 26 days
```

**Verify Predictions Generated:**
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-21'
  AND is_active = TRUE
GROUP BY game_date;

-- Expected: 850-900 predictions, 7 systems
```

---

## 9. Recovery Timeline

### 9.1 Immediate Recovery (After Backfill)

| Milestone | Expected Time | Verification |
|-----------|---------------|--------------|
| Team boxscore backfill complete | +20 min | Query shows 200 records |
| Phase 2 processing complete | +30 min | Raw table populated |
| Phase 3 analytics complete | +45 min | team_defense_game_summary has data |
| Phase 4 precompute complete | +60 min | ml_feature_store populated |
| Jan 21 predictions generated | +75 min | 850+ predictions in table |

### 9.2 Rolling Average Recovery

Even after backfill, rolling averages need time to "heal":

| Timeframe | Rolling Window State | Quality |
|-----------|---------------------|---------|
| Day 0 (backfill complete) | 10-game window now includes gap period | 70% |
| Day 7 | ~3 new games in window | 80% |
| Day 14 | ~6 new games in window | 90% |
| Day 21 | ~9 new games in window | 95% |
| Day 28 | Full 10-game refresh | 100% |

**Key Insight:** Backfilling historical data doesn't immediately fix rolling averages - they improve gradually as new games are played.

### 9.3 Full System Recovery

| Component | Recovery After Backfill | Full Recovery |
|-----------|------------------------|---------------|
| Team boxscore data | Immediate | Immediate |
| Team defense/offense summaries | Immediate | Immediate |
| Player rolling averages | Partial (gap filled) | 28 days |
| ML feature quality | 70% → 90% | 28 days |
| Prediction confidence | Restored but degraded | 28 days |
| Betting accuracy | 69-70% → 71% | 28 days |

---

## 10. Lessons Learned

### 10.1 What Went Wrong

1. **Single point of failure:** `nbac_team_boxscore` is THE source for team stats
2. **No historical validation:** Completeness checks only look at today
3. **Short catch-up window:** 3-day lookback misses longer gaps
4. **Silent failures:** 148 scraper failures, no alert
5. **No dependency tracking:** Didn't know team boxscore → everything

### 10.2 What We're Changing

1. **Add redundancy:** Consider backup data sources
2. **Extend monitoring:** Historical completeness checks
3. **Increase lookback:** 3 days → 14 days for catch-up
4. **Add alerting:** Consecutive failure detection
5. **Document dependencies:** Data lineage tracking

### 10.3 Key Takeaways

> **Takeaway 1:** A data pipeline is only as reliable as its weakest scraper. One failing scraper can cascade to zero predictions 26 days later.

> **Takeaway 2:** Completeness checks that only validate "today" are insufficient. Historical data gaps can corrupt calculations silently.

> **Takeaway 3:** Rolling window calculations need explicit validation. "Get last 10 games" doesn't mean "get last 10 COMPLETE games."

> **Takeaway 4:** Alert on trends, not just thresholds. 148 consecutive failures should have triggered an alert on day 2, not day 26.

---

## Appendix A: Affected Tables Reference

| Table | Dataset | Primary Source | Gap Impact |
|-------|---------|----------------|------------|
| nbac_team_boxscore | nba_raw | NBA.com API | **ROOT CAUSE** |
| team_defense_game_summary | nba_analytics | nbac_team_boxscore | 0 rows |
| team_offense_game_summary | nba_analytics | nbac_team_boxscore | Fallback used |
| upcoming_team_game_context | nba_analytics | team summaries | 0 rows |
| player_daily_cache | nba_precompute | player_game_summary | Stale windows |
| player_composite_factors | nba_precompute | multiple | DependencyError |
| ml_feature_store_v2 | nba_predictions | Phase 4 tables | DependencyError |
| player_prop_predictions | nba_predictions | ml_feature_store | 0 rows |

## Appendix B: Related Documentation

- `/docs/08-projects/current/jan-21-critical-fixes/` - Related critical fixes
- `/docs/02-operations/daily-validation-checklist.md` - Validation procedures
- `/shared/utils/completeness_checker.py` - Completeness check implementation
- `/shared/validation/phase_boundary_validator.py` - Phase validation
- `/bin/scraper_catchup_controller.py` - Catch-up system

---

**Document Created:** January 22, 2026
**Author:** Pipeline Investigation
**Status:** Analysis Complete, Backfill Pending
**Next Review:** After backfill completion
