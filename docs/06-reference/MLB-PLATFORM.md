# MLB Platform Documentation

**Last Updated:** 2026-01-24
**Status:** Production

---

## Overview

The MLB platform extends the NBA Props system to support baseball predictions, focusing on **pitcher strikeout totals** (over/under betting). It uses the same 6-phase pipeline architecture with MLB-specific scrapers, processors, and prediction models.

### Key Differences from NBA

| Aspect | NBA | MLB |
|--------|-----|-----|
| Primary Prediction | Player props (points, rebounds, assists) | Pitcher strikeouts |
| Prediction Systems | CatBoost V8 (primary) | V1 Baseline + V1.6 Rolling + Ensemble |
| Data Sources | NBA.com, BallDontLie, OddsAPI | Ball Don't Lie, MLB Stats API, OddsAPI, Statcast |
| Season | October - June | April - October |
| Bootstrap Period | 10 games | 14 days |

---

## Architecture

### Pipeline Phases

```
Phase 1: Orchestration  →  Daily scheduling (same as NBA)
Phase 2: Raw Data       →  31 MLB scrapers across 6 sources
Phase 3: Analytics      →  Pitcher/batter game summaries
Phase 4: Precompute     →  ML feature preparation
Phase 5: Predictions    →  V1, V1.6, V2 prediction systems
Phase 6: Publishing     →  GCS exports, grading
```

### BigQuery Datasets

| Dataset | Purpose |
|---------|---------|
| `mlb_raw` | Raw scraped data (pitcher stats, props, schedules) |
| `mlb_analytics` | Processed game summaries |
| `mlb_precompute` | ML-ready features |
| `mlb_predictions` | Prediction outputs |
| `mlb_reference` | Static reference data |
| `mlb_orchestration` | Pipeline state tracking |

### GCS Buckets

- `mlb-scraped-data` - Raw scraper outputs
- `mlb-props-platform-api` - API exports (predictions JSON)

---

## Data Sources (31 Scrapers)

### Ball Don't Lie (13 scrapers)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `mlb_pitcher_stats` | `mlb_raw.bdl_pitcher_stats` | Per-game pitcher stats (strikeouts, ERA, IP) - **TARGET variable** |
| `mlb_batter_stats` | `mlb_raw.bdl_batter_stats` | Per-game batter performance |
| `mlb_games` | `mlb_raw.bdl_games` | Game results and outcomes |
| `mlb_box_scores` | `mlb_raw.bdl_box_scores` | Complete game box scores |
| `mlb_live_box_scores` | `mlb_raw.bdl_live_box_scores` | Real-time updates |
| `mlb_active_players` | `mlb_raw.bdl_active_players` | Current rosters |
| `mlb_injuries` | `mlb_raw.bdl_injuries` | Injury reports, IL status |
| `mlb_player_splits` | `mlb_raw.bdl_player_splits` | Home/away splits |
| `mlb_player_versus` | `mlb_raw.bdl_player_versus` | Pitcher vs batter matchups |
| `mlb_season_stats` | `mlb_raw.bdl_season_stats` | YTD aggregate stats |
| `mlb_standings` | `mlb_raw.bdl_standings` | League standings |
| `mlb_team_season_stats` | `mlb_raw.bdl_team_season_stats` | Team aggregates |
| `mlb_teams` | `mlb_raw.bdl_teams` | Team metadata |

### MLB Stats API (3 scrapers)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `mlb_schedule` | `mlb_raw.mlbstatsapi_schedule` | Daily schedule with probable pitchers - **CRITICAL** |
| `mlb_lineups` | `mlb_raw.mlbstatsapi_lineups` | Starting lineups |
| `mlb_game_feed` | `mlb_raw.mlbstatsapi_game_feed` | Live play-by-play |

### Odds API (8 scrapers)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `mlb_events` | `mlb_raw.oddsa_events` | Event IDs for prop fetching |
| `mlb_pitcher_props` | `mlb_raw.oddsa_pitcher_props` | Strikeout lines - **PRIMARY TARGET** |
| `mlb_batter_props` | `mlb_raw.oddsa_batter_props` | Batter prop lines |
| `mlb_game_lines` | `mlb_raw.oddsa_game_lines` | Moneyline/spread odds |
| `*_his` variants | Historical tables | Backfill data |

### External Sources (3 scrapers)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `mlb_weather` | `mlb_raw.external_weather` | Game-day weather (affects ball flight) |
| `mlb_ballpark_factors` | `mlb_raw.external_ballpark_factors` | Stadium K-rate factors |
| `mlb_umpire_stats` | `mlb_raw.external_umpire_stats` | Umpire strike zone data |

### BettingPros (2 scrapers)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `bp_mlb_player_props` | `mlb_raw.bp_pitcher_props` | Consensus lines (market 285) |
| `bp_mlb_props_historical` | `mlb_raw.bp_props_historical` | Historical backfill |

### Statcast (1 scraper)

| Scraper | Output Table | Description |
|---------|--------------|-------------|
| `mlb_statcast_pitcher` | `mlb_raw.statcast_pitcher` | Pitch-by-pitch advanced metrics |

---

## Prediction Systems

### Model Architecture

MLB uses a **champion-challenger** framework:

| System | Model | Weight in Ensemble | Features |
|--------|-------|-------------------|----------|
| **V1 Baseline** | XGBoost | 30% | 19 features (rolling, season, context) |
| **V1.6 Rolling** | XGBoost | 50% | Enhanced rolling windows |
| **V2 Challenger** | CatBoost | Shadow mode | 29 features (matchups, ballpark, advanced) |

### Ensemble Logic

```python
# Ensemble V1 combines V1 + V1.6 with agreement bonuses
final_prediction = 0.30 * v1_baseline + 0.50 * v1_6_rolling

# Confidence adjustments
if abs(v1_baseline - v1_6_rolling) <= 1.0:  # Systems agree
    confidence += 10%
elif abs(v1_baseline - v1_6_rolling) > 2.0:  # Systems disagree
    confidence -= 15%
```

### V1 Features (19)

```
Rolling Performance:
- k_per_9_last_5, k_per_9_last_10
- k_rate_last_5, k_rate_last_10
- era_last_5, era_last_10

Season Stats:
- season_k_per_9, season_k_rate
- season_era, season_whip

Game Context:
- home_away (0/1)
- days_rest
- opponent_k_rate
- ballpark_k_factor

Line Context:
- prop_line (target)
- implied_total
```

### V2 Features (29) - Additional

```
Matchup Context:
- vs_team_k_rate_30d
- batter_k_rate_vs_pitcher_type

Ballpark Factors:
- stadium_k_factor
- altitude_factor

Advanced Metrics:
- stuff_plus
- command_plus
- pitch_mix_entropy
```

### Red Flags

Predictions are suppressed when red flags are present:

| Red Flag | Threshold | Impact |
|----------|-----------|--------|
| Low confidence | < 40% | Suppressed |
| Insufficient data | < 3 starts | Suppressed |
| Injury concern | IL status | Suppressed |
| Extreme weather | Wind > 20mph | Warning |

---

## Processors

### Phase 3: Analytics

| Processor | Output Table | Description |
|-----------|--------------|-------------|
| `MlbPitcherGameSummaryProcessor` | `mlb_analytics.pitcher_game_summary` | Aggregated pitcher stats |
| `MlbBatterGameSummaryProcessor` | `mlb_analytics.batter_game_summary` | Aggregated batter stats |

### Phase 6: Grading

| Processor | Output Table | Description |
|-----------|--------------|-------------|
| `MlbPredictionGradingProcessor` | Updates `mlb_predictions.pitcher_strikeouts` | Grades predictions vs actuals |
| `MlbShadowGradingProcessor` | `mlb_predictions.shadow_mode_results` | V1.4 vs V1.6 comparison |

### Phase 6: Exports

| Exporter | Output Path | Description |
|----------|-------------|-------------|
| `MlbPredictionsExporter` | `gs://mlb-props-platform-api/v1/mlb/predictions/{date}.json` | Daily predictions |
| `MlbBestBetsExporter` | `gs://mlb-props-platform-api/v1/mlb/best-bets/{date}.json` | Top recommendations |
| `MlbResultsExporter` | `gs://mlb-props-platform-api/v1/mlb/results/{date}.json` | Game results |
| `MlbSystemPerformanceExporter` | `gs://mlb-props-platform-api/v1/mlb/performance/{date}.json` | System metrics |

---

## Configuration

### Environment Variables

```bash
# Sport selection
SPORT=mlb  # Activates MLB configuration

# MLB-specific
MLB_BOOTSTRAP_DAYS=14  # Rolling window bootstrap period
MLB_MIN_STARTS=3       # Minimum starts for predictions
MLB_MIN_CONFIDENCE=40  # Minimum confidence threshold

# Season dates (configured in mlb_schedule_context.py)
MLB_SEASON_START=2026-03-27
MLB_SEASON_END=2026-09-29
MLB_ALL_STAR_START=2026-07-14
MLB_ALL_STAR_END=2026-07-17
```

### Orchestration Collections (Firestore)

| Collection | Purpose |
|------------|---------|
| `mlb_phase3_completion` | Phase 3 processor tracking |
| `mlb_phase4_completion` | Phase 4 processor tracking |
| `mlb_run_history` | Processor execution history |

---

## Team Mapping

The `mlb_team_mapper.py` provides comprehensive team ID translation:

```python
from predictions.coordinator.shared.utils.mlb_team_mapper import MLBTeamMapper

mapper = MLBTeamMapper()

# Convert between formats
mapper.normalize("NYY")  # → "NYY"
mapper.normalize("New York Yankees")  # → "NYY"
mapper.to_espn("NYY")  # → "nyy"
mapper.to_statcast("NYY")  # → 147

# Get team info
info = mapper.get_team_info("NYY")
# {
#     'name': 'New York Yankees',
#     'tricode': 'NYY',
#     'league': 'AL',
#     'division': 'East',
#     'stadium': 'Yankee Stadium'
# }
```

---

## API Endpoints

### Prediction Worker (`/predict-batch`)

```bash
curl -X POST "https://mlb-prediction-worker-xxx.run.app/predict-batch" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-04-15"}'
```

Response:
```json
{
  "status": "success",
  "game_date": "2026-04-15",
  "predictions": [
    {
      "pitcher_id": "660271",
      "pitcher_name": "Gerrit Cole",
      "team": "NYY",
      "opponent": "TOR",
      "prop_line": 7.5,
      "predicted_strikeouts": 8.2,
      "confidence": 72,
      "recommendation": "OVER",
      "edge": 0.7,
      "red_flags": []
    }
  ],
  "total_predictions": 12
}
```

### Shadow Mode (`/execute-shadow-mode`)

```bash
curl -X POST "https://mlb-prediction-worker-xxx.run.app/execute-shadow-mode" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2026-04-15"}'
```

---

## Monitoring

### Dashboard

The admin dashboard supports MLB via `?sport=mlb` parameter:

```
/dashboard?sport=mlb
/api/status?sport=mlb
/api/grading-by-system?sport=mlb&days=7
```

### Key Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Prediction accuracy | > 55% | ~57% |
| MAE (strikeouts) | < 2.0 | ~1.8 |
| Daily coverage | > 80% | ~85% |
| Grading coverage | > 70% | ~75% |

---

## Season Context

```python
# Season dates are configured per year
MLB_SEASONS = {
    2026: {
        'start': '2026-03-27',
        'end': '2026-09-29',
        'all_star_start': '2026-07-14',
        'all_star_end': '2026-07-17'
    }
}

# Bootstrap period: First 14 days of season
# - Limited rolling window data
# - Reduced confidence thresholds
# - Heavier weight on season projections
```

---

## File Locations

### Scrapers
```
scrapers/mlb/
├── balldontlie/      # 13 BDL scrapers
├── mlbstatsapi/      # 3 MLB Stats API scrapers
├── oddsapi/          # 8 Odds API scrapers
├── external/         # 3 external source scrapers
├── statcast/         # 1 Statcast scraper
└── registry.py       # Scraper registry
```

### Processors
```
data_processors/
├── raw/mlb/          # 9 raw processors
├── analytics/mlb/    # Analytics service
├── precompute/mlb/   # Precompute service
├── grading/mlb/      # 3 grading processors
└── publishing/mlb/   # 4 exporters
```

### Predictions
```
predictions/mlb/
├── base_predictor.py           # Base class
├── pitcher_loader.py           # Data loading
├── pitcher_strikeouts_predictor.py    # V1 model
├── pitcher_strikeouts_predictor_v2.py # V2 model
├── prediction_systems/         # V1, V1.6, Ensemble
├── worker.py                   # Cloud Run service
├── shadow_mode_runner.py       # Model comparison
└── config.py                   # Configuration
```

---

## Troubleshooting

### Common Issues

**No predictions generated:**
1. Check `mlb_raw.mlbstatsapi_schedule` for game data
2. Verify `mlb_raw.oddsa_pitcher_props` has prop lines
3. Check pitcher has minimum 3 starts

**Low confidence predictions:**
1. Check rolling window data availability
2. Verify no red flags (injuries, weather)
3. Review bootstrap period status

**Grading failures:**
1. Verify `mlb_raw.bdl_pitcher_stats` has actual results
2. Check game completion status
3. Review prediction-to-actual matching

### Logs

```bash
# View prediction worker logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=mlb-prediction-worker" --limit=50

# View grading logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=mlb-grading-service" --limit=50
```

---

## Related Documentation

- [Pipeline Architecture](../01-architecture/quick-reference.md)
- [Validation Framework Guide](../08-projects/current/comprehensive-improvements-jan-2026/VALIDATION-FRAMEWORK-GUIDE.md)
- [Troubleshooting Matrix](../02-operations/troubleshooting-matrix.md)
