# Data Cascade Problem - Comprehensive Analysis & Solution Design

**Date:** January 22, 2026
**Priority:** HIGH - Architectural Issue
**Status:** Analysis Complete, Solution Design Needed

---

## 1. The Problem Statement

**When historical data is missing, subsequent dates continue processing but produce BIASED RESULTS.**

### Real Example from Today's Audit

1. **Jan 1, 17, 18** were missing analytics data (4 games total)
2. **Jan 2-21** continued processing normally
3. Completeness checks PASSED for Jan 2-21 (they only check TODAY's data)
4. But rolling averages (last_10_games, last_5_games) were calculated with MISSING GAMES
5. Feature values were biased (e.g., `points_avg_last_10` used 8 games instead of 10)
6. Predictions were generated with these biased features

**Impact:** A player who played on Jan 1 and Jan 17 would have:
- `points_avg_last_10` calculated with 8 games instead of 10 (20% fewer samples)
- If their missing games had low scores, the average is BIASED HIGH
- Predictions over-estimate their performance

---

## 2. Current Architecture (The Gap)

### What Completeness Checks Currently Do

```
check_daily_completeness_fast():
  - Checks: "Does this player have data on TODAY's date?"
  - Returns: has_data = true/false
  - Does NOT check: "Is the historical lookback window complete?"
```

### What Rolling Averages Currently Do

```python
# In feature_extractor.py
query = """
SELECT *
FROM player_game_summary
WHERE game_date < '{target_date}'
  AND game_date >= DATE_SUB('{target_date}', INTERVAL 60 DAY)
QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
"""
# Problem: If 2 games are missing, returns 8 games silently
# No flag, no warning, no tracking
```

### What SHOULD Happen (But Doesn't)

```
Before generating features for Jan 20:
1. Check if ALL dates in lookback window (Dec 21 - Jan 19) have complete data
2. If any date is missing/incomplete, flag the feature as "potentially_biased"
3. Store metadata: "This feature was computed with 8/10 expected games"
4. Optionally: Block processing until historical data is backfilled
```

---

## 3. Why This Matters

### Business Impact

| Scenario | Impact |
|----------|--------|
| Player's low-scoring game missing | Average inflated → Over bet → Loss |
| Player's high-scoring game missing | Average deflated → Under bet → Loss |
| Multiple games missing | Confidence intervals meaningless |
| Trend calculation with gaps | `recent_trend` feature unreliable |

### Model Quality Impact

The CatBoost v8 model uses 33 features. Key affected features:

| Feature | Weight | Impact of Missing Data |
|---------|--------|------------------------|
| `points_avg_last_10` | HIGH | Biased by 10-25% |
| `points_avg_last_5` | HIGH | More volatile, bigger bias |
| `recent_trend` | MEDIUM | Can flip sign (positive → negative) |
| `ppm_avg_last_10` | HIGH | Efficiency metric corrupted |
| `consistency_score` | MEDIUM | Std dev calculation wrong |

---

## 4. Root Cause Analysis

### Why Completeness Checks Don't Catch This

1. **Design Intent:** Fast daily checks for orchestration (1-2 seconds)
2. **Trade-off:** Historical window checking is expensive (10+ seconds per player)
3. **Gap:** No intermediate tracking of "historical completeness"

### Why It's Hard to Fix

1. **No Lineage Tracking:** We don't record which historical dates contributed to each feature
2. **No Dependency Graph:** We don't know which downstream records depend on a given upstream date
3. **Performance:** Checking historical windows for every player is expensive
4. **Complexity:** Rolling windows overlap (Jan 20's last_10 and Jan 21's last_10 share 9 games)

---

## 5. Proposed Solutions

### Solution A: Defensive - Historical Window Validation (SHORT-TERM)

**Add a pre-flight check before feature generation:**

```python
def validate_historical_window(player_lookup, target_date, lookback_days=60, min_games=10):
    """Check if player has sufficient historical data."""
    query = f"""
    SELECT COUNT(DISTINCT game_date) as game_count
    FROM player_game_summary
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{target_date}'
      AND game_date >= DATE_SUB('{target_date}', INTERVAL {lookback_days} DAY)
    """
    # If game_count < min_games * 0.8, flag as "incomplete_history"
```

**Pros:** Simple, catches most issues
**Cons:** Per-player queries are slow, doesn't track which dates are missing

### Solution B: Metadata Tracking - Feature Quality Scores (MEDIUM-TERM)

**Store metadata with each feature record:**

```python
{
    "player_lookup": "lebron_james",
    "game_date": "2026-01-20",
    "points_avg_last_10": 25.5,

    # NEW: Quality metadata
    "historical_completeness": {
        "last_10_games_found": 8,
        "last_10_games_expected": 10,
        "completeness_pct": 80.0,
        "missing_dates": ["2026-01-01", "2026-01-17"],
        "is_reliable": False  # < 90% completeness
    }
}
```

**Pros:** Full visibility, can filter unreliable predictions
**Cons:** Schema changes, storage increase

### Solution C: Cascade Tracking - Dependency Graph (LONG-TERM)

**Build a dependency graph:**

```
Analytics (Jan 1) ──┬──► Features (Jan 2) ──► Predictions (Jan 2)
                    ├──► Features (Jan 3) ──► Predictions (Jan 3)
                    ├──► ...
                    └──► Features (Jan 11) ──► Predictions (Jan 11)
```

**On backfill of Jan 1:**
1. Query: "Which feature records used Jan 1 in their lookback window?"
2. Answer: Features for Jan 2-11 (10 days forward)
3. Re-run: Feature generation for those dates
4. Re-run: Predictions for those dates (if needed)

**Implementation:**

```sql
-- New table: feature_lineage
CREATE TABLE nba_precompute.feature_lineage (
    feature_record_id STRING,
    target_game_date DATE,
    player_lookup STRING,
    contributing_game_dates ARRAY<DATE>,  -- Dates used in rolling window
    created_at TIMESTAMP
);

-- Query for cascade detection
SELECT DISTINCT target_game_date, player_lookup
FROM feature_lineage
WHERE '2026-01-01' IN UNNEST(contributing_game_dates)
```

**Pros:** Complete solution, automated cascades
**Cons:** Complex, significant development effort, storage costs

---

## 6. Recommended Implementation Path

### Phase 1: Immediate (This Week)

1. **Add warning logging** when rolling window returns <10 games
2. **Track in metadata** the actual game count used
3. **Create monitoring query** to identify affected predictions

```sql
-- Query to find potentially biased features
SELECT game_date, player_lookup,
       points_avg_last_10,
       historical_games_used  -- New field
FROM ml_feature_store_v2
WHERE historical_games_used < 10
  AND game_date >= '2026-01-01'
```

### Phase 2: Short-Term (Next 2 Weeks)

1. **Implement Solution B** (Metadata tracking)
2. **Add `is_reliable` flag** to feature store
3. **Filter predictions** on unreliable features (or flag them)

### Phase 3: Medium-Term (Next Month)

1. **Build backfill impact analyzer**
2. **Create cascade re-run script**
3. **Implement Solution C** (Dependency graph)

---

## 7. Specific Backfill Procedure

**When you backfill historical data, follow this process:**

### Step 1: Identify Affected Date Range

```python
backfilled_date = date(2026, 1, 1)
lookback_window = 60  # days used in feature extraction
affected_start = backfilled_date + timedelta(days=1)
affected_end = backfilled_date + timedelta(days=lookback_window)
# Jan 1 backfill affects Jan 2 - Mar 2 features
```

### Step 2: Re-run Feature Store for Affected Dates

```bash
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2026-01-02 --end-date 2026-03-02 --skip-preflight
```

### Step 3: Re-run Predictions (If Actionable)

For historical dates, predictions are for grading only. For future dates, re-run prediction coordinator.

### Step 4: Verify

```sql
-- Confirm feature store updated
SELECT game_date, COUNT(*) as records, MAX(processed_at) as last_updated
FROM ml_feature_store_v2
WHERE game_date BETWEEN '2026-01-02' AND '2026-03-02'
GROUP BY game_date
ORDER BY game_date
```

---

## 8. Today's Session Status

### Completed

| Task | Status | Notes |
|------|--------|-------|
| Analytics backfill (Jan 1, 17, 18) | DONE | 499 records added |
| Feature store backfill (Jan 19-21) | DONE | 610 records updated |
| Grading backfill | N/A | No real prop lines (ESTIMATED_AVG only) |

### Remaining Gaps

| Gap | Impact | Action |
|-----|--------|--------|
| WAS @ DEN (Jan 17) | Missing from analytics | Raw data incomplete (17 players in NBAC) |
| POR @ SAC (Jan 18) | Missing from analytics | Raw data incomplete (23 players in NBAC) |
| Phase 5 predictions (Jan 21) | 0 predictions | Need to run prediction coordinator |

### Feature Cascade Impact

**Dates potentially affected by Jan 1, 17, 18 backfill:**

| Backfilled Date | Affects Features Through |
|-----------------|-------------------------|
| Jan 1 | Jan 2 - Mar 2 (60-day window) |
| Jan 17 | Jan 18 - Mar 18 |
| Jan 18 | Jan 19 - Mar 19 |

**We only re-ran Jan 19-21** - earlier dates (Jan 2-18) still have potentially biased features.

---

## 9. Key Questions for Architecture Decision

1. **How critical is prediction accuracy for historical dates?**
   - If grading-only: Lower priority
   - If used for model training: Higher priority

2. **What's the acceptable completeness threshold?**
   - Current: No threshold (any data = OK)
   - Recommended: 80% minimum for reliable features

3. **Should we block processing when historical data is incomplete?**
   - Current: No blocking, silent degradation
   - Options: Warn, flag, or block

4. **What's the performance budget for historical window checking?**
   - Current: 0 seconds (no checking)
   - Solution A: ~10 seconds per date
   - Solution B: ~1 second per date (metadata lookup)

---

## 10. Files Referenced

| File | Purpose |
|------|---------|
| `/shared/utils/completeness_checker.py` | Current completeness logic |
| `/data_processors/precompute/ml_feature_store/feature_extractor.py` | Rolling window queries |
| `/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature generation |
| `/backfill_jobs/precompute/ml_feature_store/` | Backfill scripts |

---

## 11. Next Steps for Incoming Session

1. **Run Phase 5 predictions for Jan 21** (7 games currently with 0 predictions)
2. **Decide on cascade re-run scope** (Jan 2-18 or just recent dates)
3. **Implement Phase 1** (warning logging + metadata tracking)
4. **Create automated backfill impact analyzer**

---

**Document Author:** Claude Code (Session Jan 22, 2026)
**Related Docs:**
- `2026-01-22-HISTORICAL-DATA-AUDIT-REPORT.md`
- `jan-21-critical-fixes/` directory
