# System Resilience Improvements

**Created:** 2026-01-23
**Status:** Planning
**Priority:** P1

---

## Overview

This document outlines improvements to make the NBA prediction pipeline more resilient to data gaps, bootstrap issues, and quality problems. Based on findings from the historical data validation audit.

---

## Problem Categories

### 1. Bootstrap Gap (Season Start)

**Problem:** First ~14 days of each season have no predictions
**Impact:** 7% of season dates affected, every season
**Root Cause:** Rolling averages require 10+ games of historical data

### 2. Feature Calculation Drift

**Problem:** Phase 4 cached features don't match Phase 3 raw calculations
**Impact:** 16-72% drift in rolling averages for some players
**Root Cause:** Cross-season contamination, stale cache

### 3. Missing Odds Data (Historical)

**Problem:** 2021-23 seasons have minimal/no Odds API data
**Impact:** Predictions use estimated lines instead of real betting markets
**Root Cause:** Odds API integration wasn't available

### 4. Prediction Coverage Gaps

**Problem:** Some dates have games but no predictions
**Impact:** Incomplete ML training data, unreliable accuracy metrics
**Root Cause:** Multiple - bootstrap, system failures, name resolution

---

## Proposed Improvements

### Tier 1: Automated Detection (Quick Wins)

#### 1.1 Daily Prediction Coverage Alert

**Goal:** Alert when prediction coverage drops below threshold

```python
# Pseudo-code for daily validation job
def validate_daily_coverage(game_date):
    analytics_count = count_players_in_analytics(game_date)
    prediction_count = count_players_with_predictions(game_date)
    coverage_pct = prediction_count / analytics_count * 100

    if coverage_pct < 90:
        send_alert(f"Low prediction coverage: {coverage_pct}%")
```

**Implementation:**
- Add to `orchestration/cloud_functions/daily_validation/`
- Trigger after Phase 5 completes
- Alert via Slack and email

#### 1.2 Bootstrap Detection

**Goal:** Detect and track bootstrap period at season start

```sql
-- Check if we're in bootstrap period
SELECT
  game_date,
  COUNT(*) as players,
  COUNTIF(games_expected < 10) as bootstrap_players,
  ROUND(100.0 * COUNTIF(games_expected < 10) / COUNT(*), 1) as bootstrap_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
GROUP BY 1;
```

**Implementation:**
- Add bootstrap_mode flag to prediction coordinator
- Log but don't alert during bootstrap
- Auto-clear after 14 days

#### 1.3 Feature Drift Monitoring

**Goal:** Alert when Phase 4 features drift from Phase 3 calculations

```python
def check_feature_drift(game_date, sample_size=10):
    for player in random_sample_players(game_date, sample_size):
        phase3_avg = calculate_rolling_avg_from_raw(player, game_date)
        phase4_avg = get_cached_rolling_avg(player, game_date)
        drift = abs(phase3_avg - phase4_avg) / phase3_avg

        if drift > 0.15:  # 15% threshold
            log_warning(f"Feature drift for {player}: {drift*100:.1f}%")
```

**Implementation:**
- Integrate into Phase 4 processor post-run
- Add to daily validation job
- Alert threshold: 15% drift

---

### Tier 2: Self-Healing (Medium Priority)

#### 2.1 Automatic Backfill Trigger

**Goal:** Auto-trigger backfill when gaps detected

```python
# After orchestration completes
def check_and_heal_gaps(game_date):
    gaps = find_prediction_gaps(game_date)

    if gaps:
        # Check if odds data available
        if has_odds_data(game_date):
            trigger_backfill_predictions(game_date)
        else:
            # Try historical Odds API
            scrape_historical_odds(game_date)
            trigger_backfill_predictions(game_date)
```

**Implementation:**
- New Cloud Function: `prediction_gap_healer`
- Trigger: Pub/Sub after orchestration
- Rate limit: Max 3 backfills per day

#### 2.2 Season Boundary Filtering

**Goal:** Prevent cross-season data contamination

```python
def get_rolling_games(player_lookup, game_date, lookback=10):
    current_season = get_season(game_date)

    games = query_player_games(
        player_lookup=player_lookup,
        end_date=game_date,
        limit=lookback,
        season=current_season  # NEW: Filter by season
    )

    return games
```

**Implementation:**
- Update `ml_feature_store_v2` generation
- Add season_year column to features table
- Regenerate Phase 4 cache with filtering

#### 2.3 Precompute Cache Invalidation

**Goal:** Auto-invalidate cache when source data changes

```python
# When Phase 3 data updates
def on_phase3_complete(game_date):
    # Invalidate affected Phase 4 cache
    invalidate_cache_for_date(game_date)

    # Also invalidate future 10 days (affected by rolling window)
    for i in range(1, 11):
        future_date = game_date + timedelta(days=i)
        invalidate_cache_for_date(future_date)
```

**Implementation:**
- Event-driven cache invalidation
- Use Firestore for cache metadata
- Integrate with Phase 3 processor completion

---

### Tier 3: Structural Improvements (Long-term)

#### 3.1 Bootstrap-Aware Predictions

**Goal:** Make predictions even with limited historical data

```python
def get_player_features(player_lookup, game_date):
    games_available = count_player_games(player_lookup, game_date)

    if games_available < 10:
        # Use league averages as priors
        return blend_with_priors(
            player_features=get_features(player_lookup, games_available),
            league_priors=get_league_priors(game_date),
            weight=games_available / 10
        )
    else:
        return get_features(player_lookup, 10)
```

**Implementation:**
- Add prior blending to feature engineering
- Create league average cache
- Gradual transition from priors to player data

#### 3.2 Cascade Validation System

**Goal:** Validate data flow across all phases

```
Phase 1 → Validate → Phase 2 → Validate → Phase 3 → Validate → Phase 4 → Validate → Phase 5
```

**Implementation:**
- Add validation checkpoints between phases
- Block downstream if upstream validation fails
- Create validation dashboard

#### 3.3 Historical Odds Backfill System

**Goal:** Automated backfill of missing historical odds

```python
class HistoricalOddsBackfiller:
    def identify_gaps(self, start_date, end_date):
        """Find dates with predictions but no odds data"""
        return query_dates_without_odds(start_date, end_date)

    def backfill_date(self, game_date):
        """Scrape and process historical odds for a date"""
        events = scrape_historical_events(game_date)
        for event in events:
            scrape_historical_props(event.id, game_date)
        process_odds_to_bigquery(game_date)
```

**Implementation:**
- New backfill job: `historical_odds_backfiller`
- Respect API rate limits (500/month)
- Priority: 2024-25 > 2023-24 > earlier

---

## Implementation Roadmap

### Week 1 (Immediate)
- [ ] Add daily prediction coverage alert
- [ ] Document bootstrap gap as known limitation
- [ ] Create monitoring dashboard for coverage

### Week 2-3 (Short-term)
- [ ] Implement bootstrap detection
- [ ] Add feature drift monitoring
- [ ] Backfill 2024-25 missing predictions

### Week 4-6 (Medium-term)
- [ ] Implement season boundary filtering
- [ ] Add automatic backfill trigger
- [ ] Create precompute cache invalidation

### Week 7-12 (Long-term)
- [ ] Bootstrap-aware predictions
- [ ] Cascade validation system
- [ ] Historical odds backfill automation

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Prediction coverage | 93% | 98% |
| Feature drift alerts | Manual | Automated |
| Backfill response time | Days | < 4 hours |
| Bootstrap gap duration | 14 days | 7 days |

---

---

## Additional Resilience Ideas

### Idea 1: Line Source Health Dashboard

**Goal:** Real-time visibility into line source quality

**Components:**
- Grafana dashboard showing line source distribution
- Alerts for degraded OddsAPI (<50% coverage)
- Alerts for high ESTIMATED usage (>30%)
- Historical trends by date/season

### Idea 2: Automatic Line Quality Scoring

**Goal:** Score predictions by line data quality

```python
def compute_line_quality_score(prediction):
    """Score 0-100 based on line source quality."""
    scores = {
        'ODDS_API_DRAFTKINGS': 100,
        'ODDS_API_FANDUEL': 95,
        'BETTINGPROS_DRAFTKINGS': 90,
        'BETTINGPROS_FANDUEL': 85,
        'ODDS_API_BETMGM': 80,
        'BETTINGPROS_BETMGM': 75,
        'BETTINGPROS_CONSENSUS': 60,
        'ESTIMATED': 40,
        'NO_LINE': 0
    }
    return scores.get(prediction.line_source, 50)
```

### Idea 3: Multi-Source Line Consensus

**Goal:** Use multiple sources to validate line accuracy

**Approach:**
1. Fetch lines from OddsAPI and BettingPros
2. Compare DraftKings lines from both sources
3. Flag significant discrepancies (>1.5 points)
4. Use average when sources agree

### Idea 4: Stale Line Detection

**Goal:** Detect when lines haven't been updated

```python
def is_line_stale(line_data):
    """Check if line is potentially stale."""
    if line_data['line_source_api'] == 'ODDS_API':
        # OddsAPI has minutes_before_tipoff
        if line_data.get('line_minutes_before_game', 0) > 1440:  # >24 hours
            return True
    elif line_data['line_source_api'] == 'BETTINGPROS':
        # BettingPros doesn't track freshness - assume stale if created_at is old
        pass
    return False
```

### Idea 5: Prediction Confidence Adjustment

**Goal:** Adjust confidence based on line source quality

**Logic:**
- DraftKings from OddsAPI: No adjustment
- DraftKings from BettingPros: -5% confidence penalty
- Secondary sportsbook: -10% confidence penalty
- Estimated line: -20% confidence penalty

### Idea 6: Historical Backfill Automation

**Goal:** Automatically detect and backfill gaps

**Trigger:** Daily job at 6 AM ET
**Logic:**
1. Query for dates with >10% ESTIMATED lines
2. Check if BettingPros has data for those dates
3. If yes, trigger coordinator re-run
4. Re-grade after predictions complete

### Idea 7: Line Source A/B Testing

**Goal:** Validate that BettingPros lines are accurate

**Approach:**
1. For subset of predictions, fetch both OddsAPI and BettingPros
2. Compare grading accuracy between sources
3. If BettingPros matches OddsAPI accuracy, trust it fully
4. Build confidence score for each source

---

## Related Files

- `/predictions/coordinator/player_loader.py` - Line source fallback (UPDATED)
- `/orchestration/cloud_functions/daily_validation/` - Validation jobs
- `/data_processors/predictions/ml_feature_store/` - Feature generation
- `/predictions/coordinator/` - Prediction orchestration
- `/tools/monitoring/check_prediction_coverage.py` - Coverage tool
- `/bin/spot_check_features.py` - Feature validation
