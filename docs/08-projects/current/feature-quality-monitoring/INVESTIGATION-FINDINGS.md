# Feature Quality Investigation Findings

**Date:** 2026-01-30
**Session:** 47
**Status:** Complete Investigation - Ready for Review

---

## Executive Summary

A comprehensive investigation of ML feature store quality issues revealed:

| Feature | Status | Root Cause | Action Needed |
|---------|--------|------------|---------------|
| `vegas_points_line` (67% zeros) | **NOT A BUG** | BettingPros only provides lines for ~8 star players per team | Document expected coverage |
| `fatigue_score` (27% zeros) | **TIMING BUG** | Jan 30 ML feature store generated before source data existed | Re-backfill Jan 30 |
| `usage_spike_score` (100% zeros) | **INTENTIONALLY DEFERRED** | Upstream data not implemented (TODO in code) | No action - by design |
| `pace_score` (mean ~0) | **NOT A BUG** | Adjustment value, mean ~0 is expected | None |
| `shot_zone_mismatch_score` (mean ~0) | **NOT A BUG** | Adjustment value, mean ~0 is expected | None |

---

## Investigation 1: Vegas Lines (67% Zeros)

### Finding: Expected Behavior, Not a Bug

The 67% zero rate for `vegas_points_line` and `vegas_opening_line` reflects **fundamental sportsbook data limitations**.

### Why Only ~35% of Players Have Vegas Lines

| Factor | Explanation |
|--------|-------------|
| **Star players only** | Sportsbooks only publish lines for high-volume betting players |
| **~8 players per team** | BettingPros API returns lines for only 7-9 players per team |
| **15-18 players per team** | NBA teams typically play 15-18 players per game |
| **Result** | ~40-50% coverage is the natural ceiling |

### Data Verification

```sql
-- BettingPros coverage analysis
SELECT game_date,
       COUNT(DISTINCT player_lookup) as players_with_lines,
       COUNT(DISTINCT player_team) as teams
FROM nba_raw.bettingpros_player_points_props
WHERE game_date >= '2026-01-25' AND market_type = 'points'
GROUP BY 1 ORDER BY 1
```

| Date | Players with Lines | Teams | Avg per Team |
|------|-------------------|-------|--------------|
| 2026-01-25 | 98 | 12 | 8.2 |
| 2026-01-26 | 122 | 14 | 8.7 |
| 2026-01-27 | 113 | 14 | 8.1 |
| 2026-01-28 | 154 | 18 | 8.6 |

### Some Star Player Gaps Detected

| Player | Coverage | Notes |
|--------|----------|-------|
| Jayson Tatum | 0% | No data in 2026 |
| Anthony Davis | 0% | Last data 2026-01-03 (injury?) |
| Nikola Jokic | 11% | Only 1 of 9 dates |
| Giannis Antetokounmpo | 50% | Inconsistent coverage |

### Recommendation

1. **Document expected ~40-50% coverage** in ML feature documentation
2. **Create star player gap alerts** when top-50 scorers lack Vegas data
3. **Consider OddsAPI as supplementary source** for better coverage
4. **`has_vegas_line` feature (index 28)** correctly indicates data availability

---

## Investigation 2: Fatigue Score (27% Zeros)

### Finding: Timing Bug on Jan 30 Only

The **27% figure is misleading**. The actual breakdown:

| Scope | Zero Rate | Records |
|-------|-----------|---------|
| Overall (all dates) | **0.2%** | 305 of 128,143 |
| Jan 30 specifically | **95%** | 303 of 319 |
| All other dates | **0%** | 0 zeros |

### Root Cause: ML Feature Store Generated Before Source Data

| Table | Jan 30 Created At | Status |
|-------|-------------------|--------|
| `ml_feature_store_v2` | 2026-01-30 **17:13** | Generated mid-day |
| `player_composite_factors` | 2026-01-31 **02:03** | Generated after midnight |

The feature store was populated **9+ hours before** the composite factors existed.

### Why 0.0 Instead of Default 50.0

1. `_batch_extract_composite_factors()` queries for Jan 30 → **0 rows returned**
2. `_composite_factors_lookup` dictionary is **empty**
3. `extract_phase4_data()` returns empty dict for each player
4. Feature extraction falls back to 0.0 instead of expected 50.0 default

### Source Data is Correct

```sql
SELECT game_date, AVG(fatigue_score), COUNTIF(fatigue_score = 0)
FROM nba_precompute.player_composite_factors
WHERE game_date = '2026-01-30'
```

Result: **avg=91.2, zeros=0, count=319** (source is correct)

### Fix Required

```bash
# Delete bad Jan 30 records from ML feature store
bq query --use_legacy_sql=false "
DELETE FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-30'"

# Re-run ML feature store backfill for Jan 30
PYTHONPATH=/home/naji/code/nba-stats-scraper python \
  backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --dates="2026-01-30"
```

### Prevention

Add validation to flag `fatigue_score = 0.0` as suspicious (0.0 is technically valid but unlikely in practice - well-rested players have ~100, fatigued have ~60-80).

---

## Investigation 3: Usage Spike Score (100% Zeros)

### Finding: Intentionally Deferred - Not Implemented

The feature is **structurally complete** but **functionally disabled**.

### Why It Returns 0

The calculation requires 3 inputs:

| Input | Status | Location |
|-------|--------|----------|
| `projected_usage_rate` | **NOT IMPLEMENTED** | `context_builder.py:295`: `None  # TODO: future` |
| `avg_usage_rate_last_7_games` | **NOT IMPLEMENTED** | `player_stats.py:48,112`: `None  # TODO: future (needs play-by-play)` |
| `star_teammates_out` | Works | ~23% of records have values > 0 |

### Calculation Logic

```python
# In usage_spike_factor.py
projected = player_row.get('projected_usage_rate') or 25.0  # defaults to 25
avg_last_7 = player_row.get('avg_usage_rate_last_7_games') or 25.0  # defaults to 25
differential = projected - avg_last_7  # 25 - 25 = 0
score = differential / 10.0  # 0 / 10 = 0
```

Since both inputs are always NULL → defaults to 25.0 → differential = 0 → score = 0.

### Database Verification

```sql
-- player_composite_factors
SELECT COUNT(*), COUNTIF(usage_spike_score = 0) as zeros
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
-- Result: 1,584 rows, 100% zeros

-- upcoming_player_game_context
SELECT COUNT(*), COUNTIF(projected_usage_rate IS NOT NULL) as has_data
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2026-01-25'
-- Result: 1,784 rows, 0% have usage data
```

### Recommendation

**No action needed** - this is by design. Implementation requires:
- Play-by-play data ingestion
- Usage rate calculation from possession data
- Significant pipeline addition

---

## Investigation 4: Pace Score & Shot Zone Mismatch (Mean ~0)

### Finding: Working as Designed

These features are **adjustment values**, not 0-100 raw scores.

| Feature | Storage Type | Expected Range | Mean ~0 Expected? |
|---------|-------------|----------------|-------------------|
| `fatigue_score` | **Raw score** | 0-100 | NO (typical ~90) |
| `pace_score` | **Adjustment** | -3 to +3 | YES |
| `shot_zone_mismatch_score` | **Adjustment** | -10 to +10 | YES |
| `usage_spike_score` | **Adjustment** | -3 to +3 | YES |

### Why Fatigue is Different

```python
# fatigue_factor.py - TWO layers
def calculate():
    raw_score = self._calculate_fatigue_score()  # 0-100
    return self._score_to_adjustment(raw_score)   # -5 to 0 (for total_composite_adjustment)

def build_context():
    return {'final_score': raw_score}  # 0-100 stored in JSON

# worker.py - stores the RAW SCORE, not adjustment
'fatigue_score': factor_contexts['fatigue_context_json']['final_score']  # 0-100
```

### Other Factors Store Adjustment Directly

```python
# worker.py
'pace_score': round(factor_scores['pace_score'], 1)  # -3 to +3
'shot_zone_mismatch_score': round(factor_scores['shot_zone_mismatch_score'], 1)  # -10 to +10
```

### Recommendation

**No action needed** - initial SQL query had wrong expected ranges. Updated to use correct ranges.

---

## Investigation 5: Props Data Pipeline Health

### Finding: Well-Architected, No Critical Issues

The props/odds data pipeline has:

| Aspect | Status |
|--------|--------|
| **Dual sources** | ✅ OddsAPI + BettingPros (redundancy) |
| **Smart idempotency** | ✅ Data hashing prevents duplicates |
| **Team normalization** | ✅ PHO→PHX handled by NBATeamMapper |
| **Validation layers** | ✅ GCS, BigQuery, schedule cross-check |
| **Retry logic** | ✅ BettingPros: 3 retries, exponential backoff |
| **Notification system** | ✅ Error/warning alerting built-in |

### Key Tables

| Table | Purpose |
|-------|---------|
| `nba_raw.odds_api_player_points_props` | OddsAPI prop lines |
| `nba_raw.bettingpros_player_points_props` | BettingPros prop lines |

### Critical Note: Market Type Filtering

BettingPros table contains ALL prop types (points, assists, rebounds, etc.). **Must filter `market_type = 'points'`** for points prop queries.

---

## Summary of Actions

### Immediate

1. **Re-backfill Jan 30 ML feature store** (fatigue_score zeros)
   ```bash
   PYTHONPATH=/home/naji/code/nba-stats-scraper python \
     backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
     --dates="2026-01-30"
   ```

### Short-term

2. **Add validation for suspicious fatigue_score=0.0** (unlikely in practice)
3. **Document expected Vegas line coverage (~40-50%)** in ML feature docs
4. **Create star player gap alerts** for missing Vegas data

### No Action Needed

- `pace_score` and `shot_zone_mismatch_score` are working correctly
- `usage_spike_score` is intentionally deferred (needs play-by-play data)
- Vegas line coverage is inherent to sportsbook data availability

---

## Files Referenced

### Composite Factors
- `data_processors/precompute/player_composite_factors/factors/fatigue_factor.py`
- `data_processors/precompute/player_composite_factors/factors/pace_factor.py`
- `data_processors/precompute/player_composite_factors/factors/shot_zone_mismatch.py`
- `data_processors/precompute/player_composite_factors/factors/usage_spike_factor.py`
- `data_processors/precompute/player_composite_factors/worker.py`

### ML Feature Store
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

### Props Pipeline
- `scrapers/bettingpros/bp_player_props.py`
- `scrapers/oddsapi/oddsa_player_props.py`
- `data_processors/raw/bettingpros/bettingpros_player_props_processor.py`
- `data_processors/raw/oddsapi/odds_api_props_processor.py`

### Upstream Context (TODO markers)
- `data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py:295`
- `data_processors/analytics/upcoming_player_game_context/player_stats.py:48,112`

---

## Key Learnings

1. **Different factor types have different storage patterns** - fatigue uses 0-100 raw score, others use adjustment values
2. **Expected coverage matters** - 40-50% Vegas coverage is normal, not a bug
3. **Timing dependencies are critical** - ML feature store must run AFTER all upstream processors
4. **TODO markers indicate intentional gaps** - usage_spike_score is not broken, just not implemented
5. **Feature quality monitoring caught real issues** - the SQL query successfully identified timing bugs

---

*Document created: 2026-01-30*
*Investigation by: Claude Opus 4.5 (Session 47)*
