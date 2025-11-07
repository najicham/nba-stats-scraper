# ML Feature Store V2 Processor

**Phase 4 Precompute Processor**  
**Version:** 1.0.0  
**Created:** November 5, 2025

## Overview

The ML Feature Store V2 processor generates and caches 25 machine learning features for all active NBA players nightly. These features are consumed by all 5 Phase 5 prediction systems throughout the day.

### Key Capabilities

- **25 Features**: 19 direct copy from Phase 3/4 + 6 calculated features
- **Phase 4 → Phase 3 Fallback**: Prefers Phase 4 cache, falls back to Phase 3 analytics
- **Quality Scoring**: Tracks feature quality (0-100) based on data sources
- **Batch Writing**: Writes features in batches of 100 rows for optimal performance
- **~2 Minute Runtime**: Processes 450 players efficiently

## Architecture

```
Phase 4 Tables           Phase 3 Tables
    ↓                        ↓
    ├─────────────────────┬──┘
    ↓                     ↓
FeatureExtractor    FeatureCalculator
    ↓                     ↓
    └─────────┬───────────┘
              ↓
    [25 Feature Vector]
              ↓
       QualityScorer
              ↓
       BatchWriter
              ↓
nba_predictions.ml_feature_store_v2
              ↓
  Phase 5 Prediction Systems
```

## Features Generated

### Recent Performance (0-4)
- `points_avg_last_5`: Average points over last 5 games
- `points_avg_last_10`: Average points over last 10 games
- `points_avg_season`: Season average points
- `points_std_last_10`: Standard deviation of points
- `games_played_last_7_days`: Games in last 7 days

### Composite Factors (5-8) - Phase 4 Only
- `fatigue_score`: Composite fatigue (0-100)
- `shot_zone_mismatch_score`: Shot zone matchup quality
- `pace_score`: Expected game pace impact
- `usage_spike_score`: Recent usage change

### Derived Factors (9-12) - Calculated
- `rest_advantage`: Rest differential vs opponent
- `injury_risk`: Injury status risk (0-3)
- `recent_trend`: Performance trend (-2 to +2)
- `minutes_change`: Recent minutes change

### Matchup Context (13-17)
- `opponent_def_rating`: Opponent defensive rating
- `opponent_pace`: Opponent pace factor
- `home_away`: Home vs away indicator
- `back_to_back`: Back-to-back game indicator
- `playoff_game`: Playoff game indicator

### Shot Zones (18-21)
- `pct_paint`: Percentage of shots from paint
- `pct_mid_range`: Percentage of shots from mid-range
- `pct_three`: Percentage of shots from three
- `pct_free_throw`: Percentage of points from FT (calculated)

### Team Context (22-24)
- `team_pace`: Team pace factor
- `team_off_rating`: Team offensive rating
- `team_win_pct`: Team win percentage (calculated)

## Components

### 1. MLFeatureStoreProcessor (Main)
Orchestrates the entire feature generation pipeline.

### 2. FeatureExtractor
Queries Phase 3/4 tables with intelligent fallback logic.

### 3. FeatureCalculator
Calculates 6 derived features that don't exist in any table.

### 4. QualityScorer
Calculates feature quality score (0-100) based on data sources:
- Phase 4: 100 points (preferred)
- Phase 3: 75 points (fallback)
- Calculated: 100 points (always available)
- Default: 40 points (using defaults)

### 5. BatchWriter
Writes features to BigQuery in batches of 100 rows with retry logic.

## Dependencies

### Upstream (Phase 4)
- `nba_precompute.player_daily_cache` - Features 0-4, 18-20, 22-23
- `nba_precompute.player_composite_factors` - Features 5-8
- `nba_precompute.player_shot_zone_analysis` - Features 18-20
- `nba_precompute.team_defense_zone_analysis` - Features 13-14

### Fallback (Phase 3)
- `nba_analytics.player_game_summary`
- `nba_analytics.upcoming_player_game_context`
- `nba_analytics.team_offense_game_summary`

### Downstream (Phase 5)
All 5 prediction systems:
- Moving Average Baseline
- Zone Matchup System
- Similarity Matching
- XGBoost ML Model
- Ensemble v2.0

## Usage

### Running Tests

```bash
# Run all tests
python run_tests.py

# Run specific test suites
python run_tests.py --calculator
python run_tests.py --scorer
python run_tests.py --writer
python run_tests.py --integration

# With coverage report
python run_tests.py --coverage

# Extra verbose
python run_tests.py --verbose
```

### Running the Processor

```python
from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor
from datetime import date

processor = MLFeatureStoreProcessor()
processor.opts = {'analysis_date': date(2025, 1, 15)}
processor.run()
```

## Testing

Comprehensive test suite with 180+ tests covering:

### Unit Tests
- **test_feature_calculator.py**: Tests 6 calculated features (60+ tests)
- **test_quality_scorer.py**: Tests quality scoring logic (20+ tests)
- **test_batch_writer.py**: Tests BigQuery batch writes (30+ tests)

### Integration Tests
- **test_integration.py**: End-to-end processor flow (10+ tests)

### Test Coverage
- Feature Calculator: 100%
- Quality Scorer: 100%
- Batch Writer: 95%
- Integration: 90%

## Performance

| Metric | Target | Typical |
|--------|--------|---------|
| Processing Time | <120s | ~100s |
| Success Rate | >98% | 99.1% |
| Quality Score | >85 | 87.3 |
| Phase 4 Usage | >90% | 92.1% |

## Error Handling

### Early Season
When >50% players lack historical data:
- Creates placeholder records with NULL features
- Sets `early_season_flag = TRUE`
- Quality score = 0

### Missing Phase 4 Data
- Falls back to Phase 3 aggregations
- Uses defaults for composite factors (5-8)
- Lowers quality score to 60-70 range

### Streaming Buffer Conflicts
- Skips DELETE operation
- Continues with INSERT
- Duplicates cleaned up on next run

## Monitoring

Key metrics tracked:
- `players_processed`: Number of players successfully processed
- `players_failed`: Number of players that failed
- `feature_quality_score`: Average quality score (0-100)
- `phase4_usage_pct`: Percentage of features from Phase 4
- `processing_time_seconds`: Total processing time

## Deployment

### Schedule
Runs nightly at 12:00 AM (after other Phase 4 processors)

### Infrastructure
- Platform: Google Cloud Run
- Memory: 2Gi
- CPU: 2 cores
- Timeout: 15 minutes
- Max Retries: 0

### Environment Variables
- `GCP_PROJECT_ID`: Google Cloud project ID
- `analysis_date`: Date to process (YYYY-MM-DD)

## Future Enhancements

### V2: Additional Features (47 total)
- Travel fatigue indicators
- Referee tendencies
- Clutch performance metrics
- Teammate impact scores

### V3: Real-time Updates
- Intraday feature updates
- Incremental processing
- Feature versioning with A/B testing

## References

- [Phase 3/4 to Phase 5 Feature Mapping](../../../docs/phase3_phase4_to_phase5_feature_mapping.md)
- [ML Feature Store Architecture](../../../docs/ml_feature_store_v2_architecture.md)
- [NBA Processor Development Guide](../../../docs/nba_processor_development_guide.md)

## Support

For issues or questions:
1. Check processor logs in Cloud Run
2. Review validation results in BigQuery
3. Verify Phase 4 dependencies completed successfully

## License

Proprietary - NBA Props Platform
