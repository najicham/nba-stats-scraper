# Root Cause Analysis: Why Rolling Window Gaps Go Undetected

**Document:** 02-ROOT-CAUSE-ANALYSIS.md
**Created:** January 22, 2026

---

## Summary

The system was designed for **daily forward processing** where each day's data is independent. It was NOT designed for **historical dependency tracking** where today's calculations depend on the last N days being complete.

---

## Architectural Gaps

### Gap 1: Completeness Checks Only Validate TODAY

**Location:** `shared/utils/completeness_checker.py`

```python
def check_daily_completeness_fast(self, entity_ids, target_date, ...):
    query = f"""
    SELECT DISTINCT {entity_field}
    FROM {upstream_table}
    WHERE DATE({date_field}) = @target_date  # <-- Only TODAY
    """
```

**The assumption:** If today's data exists, we're good to process.

**The reality:** Today's processing USES data from the last 60 days, not just today.

---

### Gap 2: Rolling Window Queries Don't Validate Counts

**Location:** `data_processors/precompute/ml_feature_store/feature_extractor.py:408-451`

```python
def _batch_extract_last_10_games(self, game_date):
    query = f"""
    SELECT
        player_lookup,
        game_date,
        points, minutes_played, ...
    FROM `nba_analytics.player_game_summary`
    WHERE game_date < '{game_date}'
      AND game_date >= '{lookback_date}'  -- 60-day window
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY game_date DESC
    ) <= 10
    """
    # Returns whatever exists - could be 8, 9, or 10 games
    # NO tracking of how many games were actually found
    # NO comparison against expected games from schedule
```

**The assumption:** If we get rows back, we have data.

**The reality:** We might get 10 rows, but they might be the WRONG 10 rows.

---

### Gap 3: No Staleness Detection

A 10-game window should span approximately 14-21 days in regular season (teams play 3-4 games/week).

**Current behavior:** No check on window span.

```
Normal window:
  Game 1: Jan 22    (today)
  Game 10: Jan 1    (21 days ago)
  Span: 21 days ✓

Gap-affected window:
  Game 1: Jan 22    (today)
  Game 2: Jan 20    (2 days ago)
  Game 3: Dec 26    (27 days ago) ← GAP JUMP
  Game 10: Dec 11   (42 days ago)
  Span: 42 days ✗ STALE
```

**Missing check:** If `window_span > 21 days`, data is likely stale.

---

### Gap 4: Phase Dependencies Are Day-Scoped

**Location:** `shared/validation/phase_boundary_validator.py`

The phase boundary validator checks if Phase N completed before Phase N+1 runs, but only for the SAME DATE.

```python
def validate_phase_boundary(from_phase, to_phase, game_date):
    # Check: Is from_phase complete for THIS game_date?
    return from_phase_complete(game_date)  # ← Only checks today
```

**Missing check:** Did Phase N complete for ALL dates in the lookback window?

---

### Gap 5: Silent Fallbacks in Feature Calculation

**Location:** `data_processors/precompute/ml_feature_store/feature_calculator.py:131-147`

```python
def calculate_recent_trend(self, phase3_data):
    last_10_games = phase3_data.get('last_10_games', [])

    if len(last_10_games) < 5:
        return 0.0  # Silent default - no logging, no flag

    # Calculate trend from whatever games we have
```

**The problem:** Returns a neutral value without any indication that data was insufficient.

---

### Gap 6: Backfill Mode Disables All Checks

**Location:** `ml_feature_store_processor.py:800-806`

```python
# Skip completeness in backfill/same-day/future
skip_completeness = (
    self.is_backfill_mode or
    self.opts.get('skip_dependency_check', False) or
    not self.opts.get('strict_mode', True) or
    is_same_day_or_future
)
```

**The assumption:** Backfill data is pre-validated.

**The reality:** Backfill can introduce gaps that cascade forward.

---

### Gap 7: No Data Lineage Tracking

We don't track which specific dates contributed to a calculation.

**Current state:**
```python
feature_record = {
    'player_lookup': 'lebron_james',
    'game_date': '2026-01-22',
    'points_avg_last_10': 25.5,
    # No record of WHICH 10 games were used
}
```

**Required state:**
```python
feature_record = {
    'player_lookup': 'lebron_james',
    'game_date': '2026-01-22',
    'points_avg_last_10': 25.5,
    'historical_completeness': {
        'contributing_game_dates': ['2026-01-20', '2026-01-18', ...],
        'games_found': 10,
        'is_complete': True
    }
}
```

Without lineage, we can't answer: "What needs to be re-run if we backfill Jan 1?"

---

## The Dependency Chain Visualization

```
                      RAW DATA (Scraped)
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   nbac_schedule      nbac_gamebook     nbac_team_boxscore
         │                  │                  │
         │                  │                  │ ← MISSING (Dec 27-Jan 21)
         │                  │                  │
         └─────────┬────────┘                  │
                   ▼                           │
         player_game_summary                   │
                   │                           │
         ┌────────┴────────┐                   │
         ▼                 ▼                   ▼
   upcoming_player_   team_defense_      team_offense_
   game_context       game_summary       game_summary
         │                 │                   │
         │                 │ ← EMPTY (Dec 27-Jan 21)
         │                 │
         └────────┬────────┴───────────────────┘
                  ▼
         player_daily_cache
         (ROLLING WINDOWS!)          ← BIASED (uses wrong games)
                  │
                  ▼
         player_composite_factors    ← BIASED (depends on daily_cache)
                  │
                  ▼
         ml_feature_store_v2         ← BIASED (uses biased sources)
                  │
                  ▼
         PREDICTIONS                 ← UNRELIABLE (based on biased features)
```

---

## Why Each Protection Failed

### Protection 1: Scraper Monitoring

**Expected:** Alert when scraper fails
**Actual:** Scraper ran but returned empty data (API issue, not scraper bug)
**Gap:** No alert on "successful but empty" scrapes

### Protection 2: Phase Completeness

**Expected:** Block Phase N+1 if Phase N incomplete
**Actual:** Phase N was "complete" for today (just empty)
**Gap:** Empty != incomplete in current logic

### Protection 3: Catch-Up System

**Expected:** Retry missed dates automatically
**Actual:** Only looks back 3 days by default
**Gap:** 26-day gap exceeds lookback window

### Protection 4: Daily Health Check

**Expected:** Alert on missing data
**Actual:** Checks yesterday's data exists, not historical window
**Gap:** Point-in-time check, not window check

### Protection 5: Feature Quality Score

**Expected:** Low score for degraded features
**Actual:** Score reflects data SOURCE (Phase 4 vs Phase 3), not completeness
**Gap:** Quality != Completeness

---

## The Core Design Flaw

The system was built with an **independence assumption**:

```
Day N's processing is independent of Day N-1's results
```

This is FALSE for rolling window calculations:

```
Day N's features DEPEND on Days N-1, N-2, ..., N-60
```

The fix requires adding **dependency awareness**:

1. Before processing Day N, verify Days N-1 through N-60 have data
2. Track which historical dates contributed to each calculation
3. When any historical date is backfilled, re-run affected calculations

---

## Summary of Root Causes

| # | Root Cause | Component | Why It Matters |
|---|------------|-----------|----------------|
| 1 | Completeness = today only | `completeness_checker.py` | Doesn't check historical window |
| 2 | No game count validation | `feature_extractor.py` | Accepts any number of games |
| 3 | No staleness detection | `feature_extractor.py` | Doesn't check window span |
| 4 | Day-scoped phase validation | `phase_boundary_validator.py` | Cross-day dependencies ignored |
| 5 | Silent fallbacks | `feature_calculator.py` | Returns defaults without flags |
| 6 | Backfill disables checks | `ml_feature_store_processor.py` | Assumes backfill is pre-validated |
| 7 | No data lineage | Schema | Can't trace calculation inputs |

---

## Related Documents

- `01-PROBLEM-STATEMENT.md` - What the problem is
- `03-CORNER-CASES.md` - Edge cases to consider
- `04-SOLUTION-ARCHITECTURE.md` - How to fix it

---

**Document Status:** Complete
