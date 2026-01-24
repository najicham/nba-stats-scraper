# Validation Framework Master Guide

**Created:** 2026-01-24
**Status:** Active
**Path:** `validation/`

## Overview

The validation framework provides declarative YAML-based validation for all data pipelines in the NBA Props Platform. It covers raw scraped data, processed analytics, predictions, and grading metrics.

---

## Directory Structure

```
validation/
├── configs/                    # YAML validation configurations
│   ├── analytics/             # Phase 3 analytics processors
│   ├── grading/               # Phase 5.5 prediction grading
│   ├── mlb/                   # MLB-specific validations
│   ├── player_reports/        # Player report exports
│   ├── predictions/           # Phase 5 prediction coverage
│   ├── raw/                   # Phase 2 raw data scrapers
│   └── reference/             # Reference data tables
├── validators/                 # Python validator implementations
│   ├── analytics/             # Analytics validators
│   ├── grading/               # Grading validators
│   ├── precompute/            # Feature store validators
│   └── raw/                   # Raw data validators
└── runner.py                  # Validation execution runner
```

---

## Configuration Index

### Raw Data Validations (Phase 2)

| Config File | Description | Table |
|-------------|-------------|-------|
| `raw/bdl_active_players.yaml` | Ball Don't Lie active players | `nba_raw.bdl_active_players` |
| `raw/bdl_boxscores.yaml` | Ball Don't Lie box scores | `nba_raw.bdl_box_scores` |
| `raw/bdl_injuries.yaml` | Ball Don't Lie injuries | `nba_raw.bdl_injuries` |
| `raw/bdl_standings.yaml` | Ball Don't Lie standings | `nba_raw.bdl_standings` |
| `raw/bettingpros_props.yaml` | BettingPros player props | `nba_raw.bp_player_props` |
| `raw/bigdataball_pbp.yaml` | BigDataBall play-by-play | `nba_raw.bdb_play_by_play` |
| `raw/br_rosters.yaml` | Basketball-Reference rosters | `nba_raw.br_rosters` |
| `raw/espn_boxscore.yaml` | ESPN box scores | `nba_raw.espn_box_scores` |
| `raw/espn_scoreboard.yaml` | ESPN scoreboard | `nba_raw.espn_scoreboard` |
| `raw/espn_team_roster.yaml` | ESPN team rosters | `nba_raw.espn_rosters` |
| `raw/nbac_gamebook.yaml` | NBA.com gamebook | `nba_raw.nbac_gamebook` |
| `raw/nbac_injury_report.yaml` | NBA.com injury report | `nba_raw.nbac_injury_report` |
| `raw/nbac_play_by_play.yaml` | NBA.com play-by-play | `nba_raw.nbac_play_by_play` |
| `raw/nbac_player_boxscore.yaml` | NBA.com player box scores | `nba_raw.nbac_player_boxscore` |
| `raw/nbac_player_list.yaml` | NBA.com player list | `nba_raw.nbac_player_list` |
| `raw/nbac_player_movement.yaml` | NBA.com player movement | `nba_raw.nbac_player_movement` |
| `raw/nbac_referee.yaml` | NBA.com referee data | `nba_raw.nbac_referees` |
| `raw/nbac_schedule.yaml` | NBA.com schedule | `nba_raw.nbac_schedule` |
| `raw/nbac_scoreboard_v2.yaml` | NBA.com scoreboard v2 | `nba_raw.nbac_scoreboard_v2` |
| `raw/news_pipeline.yaml` | News RSS pipeline | `nba_raw.news_articles` |
| `raw/odds_api_props.yaml` | Odds API player props | `nba_raw.oddsa_player_props` |
| `raw/odds_game_lines.yaml` | Odds API game lines | `nba_raw.oddsa_game_lines` |

### Analytics Validations (Phase 3)

| Config File | Description | Table |
|-------------|-------------|-------|
| `analytics/player_game_summary.yaml` | Player game summaries | `nba_analytics.player_game_summary` |
| `analytics/team_offense_game_summary.yaml` | Team offense summaries | `nba_analytics.team_offense_game_summary` |
| `analytics/team_defense_game_summary.yaml` | Team defense summaries | `nba_analytics.team_defense_game_summary` |
| `analytics/game_referees.yaml` | Game referee assignments | `nba_analytics.game_referees` |
| `analytics/upcoming_team_game_context.yaml` | Upcoming game context | `nba_analytics.upcoming_team_game_context` |

### Prediction Validations (Phase 5)

| Config File | Description | Table |
|-------------|-------------|-------|
| `predictions/nba_prediction_coverage.yaml` | NBA prediction coverage | `nba_predictions.player_prop_predictions` |

### Grading Validations (Phase 5.5)

| Config File | Description | Table |
|-------------|-------------|-------|
| `grading/prediction_accuracy.yaml` | NBA prediction accuracy | `nba_predictions.prediction_accuracy` |
| `grading/system_daily_performance.yaml` | System daily performance | `nba_predictions.system_daily_performance` |
| `grading/performance_summary.yaml` | Multi-dimensional summaries | `nba_predictions.performance_summary` |
| `grading/mlb_prediction_grading.yaml` | MLB strikeout grading | `mlb_predictions.prediction_accuracy` |
| `grading/mlb_shadow_mode.yaml` | MLB shadow mode comparison | `mlb_predictions.shadow_mode_results` |

### Reference Data Validations

| Config File | Description | Table |
|-------------|-------------|-------|
| `reference/player_registry.yaml` | Player registry | `nba_reference.nba_players_registry` |

### Player Reports Validations

| Config File | Description | Output |
|-------------|-------------|--------|
| `player_reports/player_reports.yaml` | Player report exports | GCS JSON files |

### MLB Validations

| Config File | Description | Table |
|-------------|-------------|-------|
| `mlb/mlb_schedule.yaml` | MLB schedule | `mlb_raw.mlb_schedule` |
| `mlb/mlb_pitcher_props.yaml` | MLB pitcher props | `mlb_raw.pitcher_props` |
| `mlb/mlb_prediction_coverage.yaml` | MLB prediction coverage | `mlb_predictions.pitcher_strikeouts` |

---

## Configuration Schema

Each YAML config follows this structure:

```yaml
name: "config_name"
description: "What this validates"
type: "raw|analytics|predictions|grading"

processor:
  name: "processor_name"
  description: "Processor description"
  table: "dataset.table_name"
  partition_required: true
  partition_field: "game_date"
  business_key:
    - field1
    - field2

bigquery_validations:
  enabled: true

  no_duplicates:
    enabled: true
    severity: "critical"
    threshold: 0

  freshness:
    enabled: true
    severity: "error"
    max_days_stale: 3

data_quality:
  required_fields:
    - field1
    - field2
  optional_fields:
    - field3

notifications:
  enabled: true
  channels: ["slack"]
  on_failure: true
  on_success: false
```

---

## Validation Types

### 1. Data Freshness
Checks that data is not stale beyond threshold.
```yaml
freshness:
  enabled: true
  severity: "error"
  max_days_stale: 3
```

### 2. Duplicate Detection
Checks for duplicate business keys.
```yaml
no_duplicates:
  enabled: true
  severity: "critical"
  message: "Duplicate entries found"
  threshold: 0  # Zero tolerance
```

### 3. Value Bounds
Validates values are within expected ranges.
```yaml
error_bounds:
  enabled: true
  severity: "warning"
  min: 0
  max: 100
```

### 4. Coverage Checks
Validates expected data coverage.
```yaml
system_coverage:
  enabled: true
  severity: "warning"
  expected_systems: 5
```

### 5. Row Count Validation
Validates minimum row counts.
```yaml
minimum_volume:
  enabled: true
  severity: "warning"
  min_predictions: 100
```

---

## Severity Levels

| Level | Description | Action |
|-------|-------------|--------|
| `critical` | Data integrity issue | Immediate alert, halt pipeline |
| `error` | Significant problem | Alert, continue pipeline |
| `warning` | Potential issue | Log, continue pipeline |
| `info` | Informational | Log only |

---

## Running Validations

### Command Line
```bash
# Run all validations for a date
python validation/runner.py --date 2025-01-15

# Run specific config
python validation/runner.py --config analytics/player_game_summary --date 2025-01-15

# Dry run (no alerts)
python validation/runner.py --date 2025-01-15 --dry-run
```

### Programmatic
```python
from validation.runner import ValidationRunner

runner = ValidationRunner()
results = runner.run('analytics/player_game_summary', date='2025-01-15')
print(results)
```

---

## Adding New Validations

1. **Create YAML config** in appropriate `validation/configs/` subdirectory
2. **Define validations** using the schema above
3. **Test locally** with `--dry-run` flag
4. **Deploy** config with next release

### Template
```yaml
# validation/configs/{category}/{name}.yaml
name: "my_new_validation"
description: "Validates XYZ data"
type: "analytics"

processor:
  name: "my_processor"
  table: "nba_analytics.my_table"
  partition_field: "game_date"

bigquery_validations:
  enabled: true
  freshness:
    enabled: true
    max_days_stale: 2

notifications:
  enabled: true
  channels: ["slack"]
```

---

## Monitoring

Validation results are logged to:
- BigQuery: `nba_monitoring.validation_results`
- Slack: `#nba-data-quality`
- Cloud Logging: `validation-runner`

---

## Related Documentation

- [Pipeline Architecture](../../docs/architecture/pipeline-architecture.md)
- [Data Quality Guidelines](../../docs/data-quality/guidelines.md)
- [Alert Configuration](../../docs/alerting/configuration.md)
