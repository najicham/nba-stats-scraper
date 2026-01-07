# MLB Pitcher Strikeouts Prop Betting - Project Plan

**Created**: 2026-01-06
**Status**: Planning
**Estimated Effort**: 14-20 weeks total

## Executive Summary

This project adds MLB pitcher strikeout over/under prop betting predictions to the existing NBA props platform. Rather than creating a separate codebase, we will refactor the current system to support multiple sports through a sport abstraction layer.

### Key Decision: Single Repo with Sport Parameter

After comprehensive analysis, the recommended approach is:
1. **Refactor** existing code to be sport-agnostic (~50-65 hours)
2. **Add** MLB-specific implementations alongside NBA
3. **Share** base classes, infrastructure, and deployment patterns

---

## Part 1: Refactoring Scope Analysis

### Current Hardcoding Summary

| Category | Occurrences | Files Affected | Refactoring Effort |
|----------|-------------|----------------|-------------------|
| Project ID (`nba-props-platform`) | 12,483 | 193 Python files | 15-20 hours |
| GCS Bucket (`nba-scraped-data`) | 976 | 82 Python files | 6-8 hours |
| Dataset Names (`nba_*`) | 1,340 | 242 Python files | 20-30 hours |
| Pub/Sub Topics (`nba-*`) | 47 | 28 files | 1-2 hours |
| Team Mappers | 20 imports | 20 files | 4-6 hours |
| **TOTAL** | **~15,000** | **~550 files** | **50-65 hours** |

### Dataset Name Breakdown

| Dataset | Occurrences | Primary Usage |
|---------|-------------|---------------|
| `nba_raw` | 508 | Raw processors |
| `nba_analytics` | 357 | Phase 3 analytics |
| `nba_precompute` | 186 | Phase 4 features |
| `nba_predictions` | 114 | Phase 5 predictions |
| `nba_reference` | 117 | Reference data |
| `nba_orchestration` | 69 | Orchestration tracking |

---

## Part 2: MLB Data Sources

### Primary Data Sources

#### 1. Baseball Savant / Statcast (Pitcher Stats)
- **URL**: https://baseballsavant.mlb.com/
- **Python Package**: `pybaseball` with `statcast_pitcher()` function
- **Data Available**:
  - Pitch-by-pitch data (2008-present)
  - Strikeout events with full context
  - Pitch velocity, spin rate, movement
  - K/9, K%, swinging strike rate
- **Limitation**: 25,000 row query limit per request

#### 2. The Odds API (Betting Lines)
- **URL**: https://the-odds-api.com/
- **Sport Key**: `baseball_mlb`
- **Market**: `pitcher_strikeouts` (directly supported!)
- **Bookmakers**: DraftKings, FanDuel, BetMGM, bet365, PointsBet
- **Status**: Already integrated for NBA - just add MLB sport key

#### 3. FanGraphs (Advanced Metrics)
- **URL**: https://www.fangraphs.com/
- **Python Package**: `pybaseball` includes FanGraphs scraper
- **Metrics**: K/9, K%, xFIP, WAR, pitch values

#### 4. Baseball Reference (Historical Data)
- **URL**: https://www.baseball-reference.com/
- **Python Package**: `pybaseball` with `daily_pitcher_bref()`
- **Data**: Comprehensive historical statistics

### Betting Data Sources

| Source | API Status | Strikeout Props | Notes |
|--------|------------|-----------------|-------|
| The Odds API | Official API | Yes (`pitcher_strikeouts`) | Already in codebase |
| BettingPros | Web scraping | Yes | Already in codebase |
| DraftKings | No public API | Yes | Multiple thresholds |
| FanDuel | No public API | Yes | Full coverage |
| Sports Game Odds | Official API | Yes | Customizable |
| OddsMatrix | Official API | Yes | 350+ markets |

---

## Part 3: Feature Engineering for Strikeout Prediction

### Proposed 25-Feature Vector (Matching NBA Pattern)

```
# Performance Indicators (0-4)
0. strikeouts_avg_last_5          # Recent K rate
1. strikeouts_avg_last_10         # Short-term consistency
2. strikeouts_avg_season          # Season baseline
3. strikeouts_std_last_10         # Volatility
4. innings_pitched_avg_last_10    # Workload indicator

# Pitcher Factors (5-8)
5. fatigue_score                  # Pitch count / rest days
6. swinging_strike_rate           # Pitch effectiveness
7. first_pitch_strike_rate        # Command indicator
8. pitch_velocity_trend           # Velocity changes

# Matchup Context (9-12)
9. opponent_team_k_rate           # Team strikeout tendency
10. opponent_contact_rate         # Team contact ability
11. lineup_handedness_advantage   # L/R matchup edge
12. umpire_k_tendency             # Umpire strike zone size

# Environmental Factors (13-17)
13. ballpark_k_factor             # Park effect on Ks
14. is_home                       # Home/away
15. days_rest                     # Pitcher rest
16. is_day_game                   # Day vs night
17. temperature_factor            # Weather impact

# Pitch Arsenal (18-21)
18. fastball_usage_pct            # Pitch mix
19. breaking_ball_usage_pct       # Secondary pitches
20. offspeed_usage_pct            # Changeup/splitter usage
21. spin_rate_percentile          # Pitch quality

# Game Context (22-24)
22. expected_innings              # How deep pitcher goes
23. team_bullpen_usage            # Bullpen availability
24. game_importance               # Playoff race factor
```

### Key Prediction Factors (Research-Based)

1. **Historical K/9 Rate**: Primary predictor
2. **Opposing Team K%**: How much opponents strike out
3. **Ballpark Factor**: Park-specific strikeout adjustment
4. **Umpire Tendencies**: Some umps generate 17.5+ K/game (vs 14.8 avg)
5. **Recent Form**: Last 5-10 game trends
6. **Pitch Velocity Trend**: Declining velocity = fewer Ks
7. **Rest Days**: Optimal rest vs fatigue
8. **Day/Night Splits**: Performance varies by game time

---

## Part 4: Implementation Phases

### Phase 0: Sport Abstraction Layer (Week 1-2)
**Effort**: 50-65 hours

#### 0.1 Create Sport Configuration Module
```python
# shared/config/sport_config.py
import os

SPORT = os.environ.get('SPORT', 'nba')

# Derived configuration
GCS_BUCKET = f"{SPORT}-scraped-data"
RAW_DATASET = f"{SPORT}_raw"
ANALYTICS_DATASET = f"{SPORT}_analytics"
PRECOMPUTE_DATASET = f"{SPORT}_precompute"
PREDICTIONS_DATASET = f"{SPORT}_predictions"
REFERENCE_DATASET = f"{SPORT}_reference"
ORCHESTRATION_DATASET = f"{SPORT}_orchestration"

def topic(phase: str) -> str:
    return f"{SPORT}-{phase}"
```

#### 0.2 Refactoring Tasks

| Task | Files | Estimated Hours |
|------|-------|-----------------|
| Create `sport_config.py` | 1 new file | 2 |
| Update Pub/Sub topics config | 1 file | 1 |
| Create sport-agnostic team mapper interface | 2 files | 3 |
| Refactor project ID references | 193 files | 15-20 |
| Refactor GCS bucket references | 82 files | 6-8 |
| Refactor dataset name references | 242 files | 20-30 |
| Update deployment scripts | ~20 files | 4-6 |
| Testing and validation | - | 8-10 |

#### 0.3 Refactoring Priority Order

1. **Pub/Sub Topics** (1-2 hours) - All centralized in one file
2. **Sport Config Module** (2-3 hours) - New abstraction layer
3. **Team Mapper Interface** (3-4 hours) - Create abstract interface
4. **Dataset Names** (20-30 hours) - Most widespread changes
5. **GCS Bucket Names** (6-8 hours) - Scattered defaults
6. **Project ID** (15-20 hours) - Default parameters throughout
7. **Deployment Scripts** (4-6 hours) - Shell scripts and configs

### Phase 1: GCP Infrastructure Setup (Week 2)
**Effort**: 8-12 hours

#### 1.1 Create MLB GCP Resources
```bash
# GCS Bucket
gsutil mb -l us-west2 gs://mlb-scraped-data

# BigQuery Datasets
bq mk --dataset mlb_raw
bq mk --dataset mlb_analytics
bq mk --dataset mlb_precompute
bq mk --dataset mlb_predictions
bq mk --dataset mlb_reference
bq mk --dataset mlb_orchestration

# Pub/Sub Topics
gcloud pubsub topics create mlb-phase1-scrapers-complete
gcloud pubsub topics create mlb-phase2-raw-complete
gcloud pubsub topics create mlb-phase3-trigger
gcloud pubsub topics create mlb-phase3-analytics-complete
gcloud pubsub topics create mlb-phase4-trigger
gcloud pubsub topics create mlb-phase4-precompute-complete
gcloud pubsub topics create mlb-phase5-predictions-complete
gcloud pubsub topics create mlb-phase6-export-trigger
```

#### 1.2 MLB Team Configuration
```python
# shared/config/mlb_teams.py
MLB_TEAMS = [
    {"teamId": "108", "abbr": "LAA", "name": "Los Angeles Angels", "league": "AL"},
    {"teamId": "109", "abbr": "ARI", "name": "Arizona Diamondbacks", "league": "NL"},
    # ... 30 teams total
]
```

### Phase 2: MLB Scrapers (Week 3-5)
**Effort**: 3-4 weeks

#### 2.1 Required Scrapers

| Scraper | Data Source | Priority | Effort |
|---------|-------------|----------|--------|
| `statcast_pitcher_stats` | Baseball Savant | P0 | 3-4 days |
| `mlb_schedule` | MLB Stats API | P0 | 2-3 days |
| `mlb_pitcher_game_logs` | Baseball Reference | P0 | 2-3 days |
| `odds_api_pitcher_props` | The Odds API | P0 | 1-2 days |
| `fangraphs_pitcher_stats` | FanGraphs | P1 | 2-3 days |
| `mlb_ballpark_factors` | Baseball Savant | P1 | 1-2 days |
| `mlb_umpire_stats` | Umpire Scorecards | P2 | 2-3 days |
| `bettingpros_pitcher_props` | BettingPros | P2 | 1-2 days |

#### 2.2 Statcast Pitcher Scraper (Primary)
```python
# scrapers/baseball_savant/statcast_pitcher.py
from pybaseball import statcast_pitcher
from scrapers.scraper_base import ScraperBase

class StatcastPitcherScraper(ScraperBase):
    """Fetches pitcher statistics from Baseball Savant Statcast."""

    required_opts = ['pitcher_id', 'start_date', 'end_date']

    def download_data(self):
        data = statcast_pitcher(
            start_dt=self.opts['start_date'],
            end_dt=self.opts['end_date'],
            player_id=self.opts['pitcher_id']
        )
        return data.to_dict('records')
```

#### 2.3 Odds API MLB Scraper (Modify Existing)
```python
# scrapers/oddsapi/oddsa_mlb_pitcher_props.py
# Leverage existing oddsa_player_props.py pattern
# Just change sport_key to 'baseball_mlb' and market to 'pitcher_strikeouts'
```

### Phase 3: Raw Processors (Week 5-6)
**Effort**: 2-3 weeks

#### 3.1 Required Processors

| Processor | Input | Output Table | Effort |
|-----------|-------|--------------|--------|
| `statcast_pitcher_processor` | Statcast JSON | `mlb_raw.statcast_pitcher_stats` | 3-4 days |
| `mlb_schedule_processor` | MLB API JSON | `mlb_raw.mlb_schedule` | 2-3 days |
| `pitcher_game_log_processor` | BR scrape | `mlb_raw.pitcher_game_logs` | 2-3 days |
| `mlb_odds_props_processor` | Odds API JSON | `mlb_raw.pitcher_props_odds` | 2-3 days |
| `ballpark_factors_processor` | Savant scrape | `mlb_raw.ballpark_factors` | 1-2 days |

### Phase 4: Analytics Processors (Week 7-8)
**Effort**: 2-3 weeks

#### 4.1 Core Analytics Tables

| Table | Description | NBA Equivalent |
|-------|-------------|----------------|
| `pitcher_game_summary` | Per-game pitcher performance | `player_game_summary` |
| `team_batting_summary` | Team hitting stats vs pitchers | `team_offense_game_summary` |
| `upcoming_pitcher_context` | Context for today's starters | `upcoming_player_game_context` |

### Phase 5: Precompute / Feature Store (Week 8-9)
**Effort**: 2-3 weeks

#### 5.1 Feature Store Table
```sql
CREATE TABLE mlb_precompute.pitcher_strikeout_features (
    game_date DATE,
    pitcher_id STRING,
    pitcher_name STRING,
    team_abbr STRING,
    opponent_abbr STRING,

    -- Performance features (0-4)
    strikeouts_avg_last_5 FLOAT64,
    strikeouts_avg_last_10 FLOAT64,
    strikeouts_avg_season FLOAT64,
    strikeouts_std_last_10 FLOAT64,
    innings_pitched_avg_last_10 FLOAT64,

    -- Pitcher factors (5-8)
    fatigue_score FLOAT64,
    swinging_strike_rate FLOAT64,
    first_pitch_strike_rate FLOAT64,
    pitch_velocity_trend FLOAT64,

    -- ... remaining 16 features

    feature_quality_score FLOAT64,
    updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_id;
```

### Phase 6: ML Model Training (Week 9-10)
**Effort**: 1-2 weeks

#### 6.1 Training Data Requirements
- Minimum 2 full seasons of historical data (2024-2025)
- ~2,500 games per season × ~2 starters = ~10,000 data points
- Feature completeness threshold: 90%

#### 6.2 Model Architecture
```python
# ml/train_pitcher_strikeouts_xgboost.py
# Follow existing train_real_xgboost.py pattern

features = [
    'strikeouts_avg_last_5',
    'strikeouts_avg_last_10',
    'strikeouts_avg_season',
    # ... 25 features total
]

xgb_params = {
    'objective': 'reg:squarederror',
    'max_depth': 6,
    'learning_rate': 0.1,
    'n_estimators': 100,
}
```

### Phase 7: Prediction Pipeline (Week 10-11)
**Effort**: 1-2 weeks

#### 7.1 Prediction Systems (Reuse NBA Pattern)
1. **Moving Average Baseline** - Weighted average of recent Ks
2. **Similarity Matching** - Find similar historical games
3. **XGBoost V1** - Trained ML model
4. **Ensemble V1** - Confidence-weighted combination

#### 7.2 Key Changes from NBA
- Different feature indices
- Different line thresholds (typical K lines: 4.5, 5.5, 6.5, 7.5)
- Different confidence calibration

### Phase 8: Testing & Deployment (Week 11-12)
**Effort**: 2-3 weeks

#### 8.1 Testing Checklist
- [ ] Unit tests for all scrapers
- [ ] Integration tests for processor pipeline
- [ ] Backtest predictions against historical results
- [ ] A/B test ensemble vs individual models
- [ ] Load testing for concurrent predictions

#### 8.2 Deployment
- Separate Cloud Run services for MLB
- Shared Cloud Scheduler patterns
- MLB-specific monitoring dashboards

---

## Part 5: Implementation Todo List

### Week 1-2: Sport Abstraction Layer
- [ ] Create `shared/config/sport_config.py`
- [ ] Refactor `shared/config/pubsub_topics.py` to use sport prefix
- [ ] Create abstract `TeamMapper` interface
- [ ] Create `shared/config/mlb_teams.py`
- [ ] Create `shared/utils/mlb_team_mapper.py`
- [ ] Refactor dataset name references (242 files)
- [ ] Refactor GCS bucket references (82 files)
- [ ] Refactor project ID references (193 files)
- [ ] Update deployment scripts
- [ ] Validate NBA still works after refactoring

### Week 2: GCP Infrastructure
- [ ] Create `mlb-scraped-data` GCS bucket
- [ ] Create MLB BigQuery datasets
- [ ] Create MLB Pub/Sub topics and subscriptions
- [ ] Set up Cloud Scheduler jobs for MLB
- [ ] Configure IAM permissions

### Week 3-5: MLB Scrapers
- [ ] Implement `statcast_pitcher` scraper (pybaseball)
- [ ] Implement `mlb_schedule` scraper (MLB Stats API)
- [ ] Implement `pitcher_game_logs` scraper (Baseball Reference)
- [ ] Modify Odds API scraper for MLB
- [ ] Implement `fangraphs_pitcher` scraper
- [ ] Implement `ballpark_factors` scraper
- [ ] Add scrapers to registry
- [ ] Test all scrapers with real data

### Week 5-6: Raw Processors
- [ ] Create BigQuery schemas for MLB raw tables
- [ ] Implement `statcast_pitcher_processor`
- [ ] Implement `mlb_schedule_processor`
- [ ] Implement `pitcher_game_log_processor`
- [ ] Implement `mlb_odds_props_processor`
- [ ] Implement `ballpark_factors_processor`
- [ ] Add processors to registry
- [ ] Backfill 2 seasons of historical data

### Week 7-8: Analytics Processors
- [ ] Create BigQuery schemas for MLB analytics tables
- [ ] Implement `pitcher_game_summary_processor`
- [ ] Implement `team_batting_summary_processor`
- [ ] Implement `upcoming_pitcher_context_processor`
- [ ] Validate analytics calculations

### Week 8-9: Feature Store
- [ ] Create `pitcher_strikeout_features` schema
- [ ] Implement feature calculation processor
- [ ] Implement feature quality scoring
- [ ] Backfill feature store with historical data
- [ ] Validate feature completeness

### Week 9-10: ML Training
- [ ] Collect training data (2+ seasons)
- [ ] Create training script
- [ ] Train initial XGBoost model
- [ ] Evaluate model accuracy (MAE, RMSE)
- [ ] Tune hyperparameters
- [ ] Save model to GCS

### Week 10-11: Prediction Pipeline
- [ ] Implement MLB moving average predictor
- [ ] Implement MLB similarity predictor
- [ ] Implement MLB XGBoost predictor
- [ ] Implement MLB ensemble predictor
- [ ] Create prediction coordinator for MLB
- [ ] Test end-to-end prediction flow

### Week 11-12: Testing & Deployment
- [ ] Write unit tests for all components
- [ ] Run integration tests
- [ ] Backtest against historical results
- [ ] Deploy to staging environment
- [ ] Monitor for 1 week
- [ ] Deploy to production
- [ ] Set up monitoring and alerting

---

## Part 6: Risk Assessment

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Refactoring breaks NBA | Medium | High | Comprehensive test suite, phased rollout |
| Baseball Savant rate limiting | Medium | Medium | Implement caching, respect limits |
| Insufficient historical data | Low | High | Supplement with FanGraphs/BR data |
| Model accuracy issues | Medium | Medium | Start with simple moving average, iterate |

### Timeline Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Refactoring takes longer | High | Medium | Start with critical path only |
| MLB season starts before ready | Medium | Low | Deploy with basic model first |
| Data quality issues | Medium | Medium | Build validation checks early |

---

## Part 7: Success Criteria

### Phase 0 (Refactoring)
- [ ] NBA pipeline still works with `SPORT=nba`
- [ ] All tests pass
- [ ] No hardcoded "nba-" strings in shared code

### Phase 1-6 (MLB Implementation)
- [ ] All MLB scrapers collecting data successfully
- [ ] Raw → Analytics → Precompute pipeline working
- [ ] Feature store populated with 2+ seasons

### Phase 7-8 (Predictions)
- [ ] Predictions generated for all MLB games with starting pitchers
- [ ] Model MAE < 1.5 strikeouts
- [ ] Betting edge identified in backtesting

### Production
- [ ] 99.5% uptime for prediction pipeline
- [ ] Predictions available 2+ hours before game time
- [ ] Monitoring and alerting in place

---

## Appendix A: Python Package Dependencies

```
# New packages for MLB
pybaseball>=2.0.0          # Baseball Savant, FanGraphs, BR integration
baseball_scraper>=0.4.0    # Additional baseball data scraping
```

## Appendix B: Key File Locations

### Files to Create (MLB-specific)
```
shared/config/mlb_teams.py
shared/utils/mlb_team_mapper.py
scrapers/baseball_savant/statcast_pitcher.py
scrapers/mlb_stats_api/mlb_schedule.py
data_processors/raw/mlb/statcast_pitcher_processor.py
data_processors/analytics/mlb/pitcher_game_summary_processor.py
data_processors/precompute/mlb/pitcher_strikeout_features_processor.py
ml/train_pitcher_strikeouts_xgboost.py
predictions/worker/prediction_systems/mlb/pitcher_strikeouts_predictor.py
schemas/bigquery/mlb_raw/*.sql
schemas/bigquery/mlb_analytics/*.sql
schemas/bigquery/mlb_precompute/*.sql
```

### Files to Modify (Sport Abstraction)
```
shared/config/sport_config.py (NEW)
shared/config/pubsub_topics.py
data_processors/raw/processor_base.py
data_processors/analytics/analytics_base.py
data_processors/precompute/precompute_base.py
scrapers/scraper_base.py
predictions/coordinator/coordinator.py
predictions/worker/worker.py
bin/shared/deploy_common.sh
```

## Appendix C: References

- [Baseball Savant API](https://baseballsavant.mlb.com/)
- [pybaseball Documentation](https://github.com/jldbc/pybaseball)
- [The Odds API MLB Docs](https://the-odds-api.com/sports/mlb-odds.html)
- [FanGraphs Glossary](https://library.fangraphs.com/getting-started/)
- [MLB Stats API](https://statsapi.mlb.com/)
