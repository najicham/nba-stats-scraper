# Historical Feature Store Cleanup Plan

**Created:** 2026-02-01 (Session 67)
**Status:** PLANNED
**Goal:** Clean historical feature data to enable cross-season training and trend analysis

---

## Motivation

Currently, only current season data (Nov 2025+) is trustworthy for training. Historical data has known issues:

| Issue | Impact | Seasons Affected |
|-------|--------|------------------|
| team_win_pct = 0.5 constant | Model couldn't learn team strength | 2021-2024 |
| Data leakage in rolling averages | Inflated historical performance | All before Jan 26, 2026 |
| Vegas imputation mismatch | Different handling train vs inference | All |

**Benefits of clean historical data:**
1. Train on 3+ seasons of data (100K+ samples)
2. Learn late-season trends (playoff push, tanking, load management)
3. Identify year-over-year patterns
4. Better handle edge cases (injuries, trades, back-to-backs)

---

## Phase 1: Feature Audit Script

Create a comprehensive script to scan and validate all features across all seasons.

### Script Requirements

```python
# bin/audit_feature_store.py

"""
ML Feature Store Audit Script

Scans all seasons/dates and checks every feature for:
1. Missing values (unexpected NULLs)
2. Constant values (stuck at default)
3. Out-of-range values
4. Distribution anomalies
5. Correlation with actuals (leakage detection)
"""
```

### Checks Per Feature

| Feature | Valid Range | Constant Check | Leakage Check |
|---------|-------------|----------------|---------------|
| points_avg_last_5 | 0-50 | STD > 3 | Corr with actual < 0.85 |
| points_avg_last_10 | 0-50 | STD > 3 | Corr with actual < 0.85 |
| points_std_last_10 | 0-15 | STD > 1 | - |
| team_win_pct | 0.0-1.0 | Not 100% = 0.5 | - |
| vegas_points_line | 0-50 | Coverage > 30% | - |
| fatigue_score | 0-100 | STD > 10 | - |
| pace_score | -50 to 50 | Not 100% = 0 | - |
| opponent_def_rating | 90-130 | STD > 3 | - |

### Output Format

```
=================================================================
 ML FEATURE STORE AUDIT REPORT
 Generated: 2026-02-01 01:30:00 UTC
=================================================================

SEASON: 2024-25
-----------------------------------------------------------------
Period: 2024-10-22 to 2025-06-15
Records: 125,432

Feature Health Summary:
✅ points_avg_last_5    OK (STD=6.2, range=0-48)
✅ points_avg_last_10   OK (STD=5.8, range=0-45)
❌ team_win_pct         FAILED: 98.2% constant at 0.5
⚠️ vegas_points_line   WARNING: 25% coverage (low)
✅ fatigue_score        OK (STD=15.3, range=20-100)

Leakage Detection:
✅ points_avg_last_5 vs actual: corr=0.72 (no leakage)
✅ points_avg_last_10 vs actual: corr=0.68 (no leakage)

Recommendations:
1. RECOMPUTE team_win_pct for 2024-25 season
2. BACKFILL Vegas data from BettingPros archive
```

---

## Phase 2: Historical Data Fixes

### 2.1 Fix team_win_pct (Critical)

The team_win_pct was 0.5 because the feature calculator wasn't receiving team data.

**Fix approach:**
```sql
-- Recompute team_win_pct from game results
WITH team_records AS (
  SELECT
    team,
    game_date,
    SUM(CASE WHEN win_flag THEN 1 ELSE 0 END) OVER (
      PARTITION BY team, season
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as wins_before,
    COUNT(*) OVER (
      PARTITION BY team, season
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as games_before
  FROM team_game_results
)
SELECT
  player_lookup,
  game_date,
  CASE
    WHEN games_before >= 5 THEN wins_before / games_before
    ELSE 0.5
  END as corrected_team_win_pct
FROM player_game_summary pgs
JOIN team_records tr ON pgs.team_abbr = tr.team AND pgs.game_date = tr.game_date
```

### 2.2 Fix Rolling Averages (If Needed)

The feature store was re-backfilled for 2025-26 season. For 2024-25 and earlier:

**Check if fix needed:**
```sql
-- Check correlation between avg_last_5 and actual for historical seasons
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  CORR(points_avg_last_5, actual_points) as correlation
FROM historical_feature_audit
GROUP BY 1
ORDER BY 1
```

If correlation > 0.85, data has leakage and needs recomputation.

### 2.3 Backfill Vegas Data

Historical Vegas coverage is low (~25%). Options:
1. **BettingPros archive** - May have historical DraftKings lines
2. **Accept as-is** - Model handles missing Vegas with NaN
3. **Impute from season average** - Risk of introducing bias

---

## Phase 3: Season-by-Season Backfill

### Target Seasons

| Season | Priority | Notes |
|--------|----------|-------|
| 2024-25 | HIGH | Last full season, best for trend analysis |
| 2023-24 | MEDIUM | Useful for multi-year patterns |
| 2022-23 | LOW | Older data, more drift |
| 2021-22 | LOW | V8 original training data |

### Backfill Command

```bash
# Backfill 2024-25 season with corrected features
PYTHONPATH=. python bin/backfill_feature_store.py \
    --season 2024-25 \
    --start-date 2024-10-22 \
    --end-date 2025-06-15 \
    --fix-team-win-pct \
    --fix-rolling-averages \
    --dry-run  # Remove for actual run
```

---

## Phase 4: Trend Analysis Experiments

Once historical data is clean, run experiments to find cross-season patterns:

### Experiment Ideas

1. **Late Season Performance**
   - Training: Nov-Feb data
   - Eval: Mar-Apr data
   - Hypothesis: Late season has different patterns (load management, tanking)

2. **Playoff Push**
   - Training: Regular season
   - Eval: Final 2 weeks before playoffs
   - Hypothesis: Contending teams play starters more

3. **Back-to-Back Trends**
   - Compare B2B performance across seasons
   - Hypothesis: B2B impact is consistent year-over-year

4. **Vegas Line Evolution**
   - How do Vegas lines shift during season?
   - Are early-season lines less accurate?

### Experiment Framework

```python
# ml/experiments/cross_season_analysis.py

def analyze_late_season_trends():
    """
    Compare model performance in different season phases.
    """
    phases = {
        'early': ('2024-10-22', '2024-12-31'),
        'mid': ('2025-01-01', '2025-02-28'),
        'late': ('2025-03-01', '2025-04-15'),
        'playoff_push': ('2025-04-01', '2025-04-15'),
    }

    for phase, (start, end) in phases.items():
        # Train on all other phases, eval on this phase
        results = train_and_evaluate(
            train_exclude=(start, end),
            eval_range=(start, end)
        )
        print(f"{phase}: {results['hit_rate']:.1f}%")
```

---

## Implementation Timeline

| Week | Task |
|------|------|
| Week 1 | Build feature audit script |
| Week 1 | Run audit on all seasons |
| Week 2 | Fix team_win_pct for 2024-25 |
| Week 2 | Verify rolling averages are clean |
| Week 3 | Backfill 2024-25 feature store |
| Week 3 | Run trend analysis experiments |
| Week 4 | Document findings, update training strategy |

---

## Success Criteria

1. **Audit script** catches all known issues when run on current data
2. **2024-25 data** passes all audit checks after fixes
3. **Cross-season training** improves performance vs current-season-only
4. **Trend analysis** identifies actionable patterns for late season

---

## Scripts to Create

1. `bin/audit_feature_store.py` - Comprehensive feature audit
2. `bin/backfill_feature_store.py` - Historical data backfill
3. `ml/experiments/cross_season_analysis.py` - Trend experiments

---

*Created: Session 67, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
