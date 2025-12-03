# Pipeline Validation System

**Last Updated:** 2025-12-02
**Status:** Operational
**Location:** `bin/validate_pipeline.py`

---

## Overview

The validation system provides comprehensive data pipeline health checking across all 5 phases. It supports both single-date and date-range validation with multiple output formats.

---

## Quick Start

```bash
# Single date validation
python3 bin/validate_pipeline.py 2024-01-15

# Date range validation
python3 bin/validate_pipeline.py 2024-01-15 2024-01-28

# JSON output for programmatic use
python3 bin/validate_pipeline.py 2024-01-15 --format json

# Show missing players
python3 bin/validate_pipeline.py 2024-01-15 --show-missing

# Legacy terminal view
python3 bin/validate_pipeline.py 2024-01-15 --legacy-view
```

---

## What Gets Validated

### Per Phase

| Phase | What's Checked |
|-------|---------------|
| **Phase 1 (GCS)** | JSON files exist for each scraper |
| **Phase 2 (Raw)** | BQ records exist in raw tables |
| **Phase 3 (Analytics)** | Analytics tables populated, player counts |
| **Phase 4 (Precompute)** | Feature store populated, quality scores |
| **Phase 5 (Predictions)** | Predictions generated, confidence levels |

### Cross-Cutting Checks

| Check | Description |
|-------|-------------|
| **Schedule Context** | Game count, teams playing, season day |
| **Player Universe** | Rostered players, active vs DNP |
| **Run History** | Processor errors, alerts, durations |
| **Chain Validation** | Fallback source usage, quality tiers |
| **Cross-Phase Consistency** | Player sets match between phases |

---

## Data Integrity Checks (New in 2025-12-02)

### Duplicate Detection

```python
from shared.validation.validators import query_duplicate_count

count = query_duplicate_count(
    client, dataset='nba_analytics', table='player_game_summary',
    date_column='game_date', game_date=date(2024, 1, 15),
    unique_keys=['player_lookup', 'game_date']
)
# Returns: number of duplicate records
```

### NULL Field Tracking

```python
from shared.validation.validators import query_null_critical_fields

nulls = query_null_critical_fields(
    client, dataset='nba_analytics', table='player_game_summary',
    date_column='game_date', game_date=date(2024, 1, 15),
    critical_fields=['points', 'minutes', 'player_lookup']
)
# Returns: {'points': 0, 'minutes': 5, 'player_lookup': 0}
```

### Cross-Table Consistency

```python
from shared.validation.validators import check_cross_table_consistency

result = check_cross_table_consistency(
    client, game_date=date(2024, 1, 15),
    source_dataset='nba_analytics', source_table='player_game_summary',
    source_date_column='game_date',
    target_dataset='nba_predictions', target_table='ml_feature_store_v2',
    target_date_column='game_date'
)
# Returns: {'is_consistent': True, 'missing_count': 0, 'extra_count': 0}
```

### Comprehensive Integrity Check

```python
from shared.validation.validators import check_data_integrity

result = check_data_integrity(
    client, dataset='nba_analytics', table='player_game_summary',
    date_column='game_date', game_date=date(2024, 1, 15),
    unique_keys=['player_lookup', 'game_date'],
    critical_fields=['points', 'minutes']
)
# Returns: DataIntegrityResult with all checks
```

---

## Chain Validation

The system validates data through "chains" - logical groupings of related data sources:

| Chain | Sources | Fallback Order |
|-------|---------|----------------|
| `game_schedule` | nbac_schedule, espn_scoreboard | Primary -> Fallback |
| `player_boxscores` | gamebook, bdl, espn_boxscores | Primary -> Secondary -> Tertiary |
| `team_boxscores` | nbac_team_boxscore, reconstructed | Primary -> Virtual |
| `player_props` | odds_api, bettingpros | Primary -> Fallback |
| `game_lines` | odds_api, espn | Primary -> Fallback |
| `shot_zones` | bigdataball_pbp, nbac_pbp | Primary -> Fallback |
| `injury_reports` | nbac_injury, espn_injury | Primary -> Fallback |

### Virtual Sources

Some sources are "virtual" - derived from other data:

- `espn_team_boxscore`: Extracted from `espn_boxscores` (player rows with NULL player_lookup)
- `reconstructed_team_from_players`: Aggregated from player boxscores

See: [ESPN Virtual Source Pattern](../06-reference/data-sources/espn-virtual-source-pattern.md)

---

## Status Values

### Source Status

| Status | Meaning |
|--------|---------|
| `available` | Data exists in BQ |
| `missing` | No data for this date |
| `timeout` | BQ query timed out (distinct from missing) |
| `virtual` | Derived source, depends on parent chain |
| `virtual_unavailable` | Parent chain has no data |

### Chain Status

| Status | Meaning |
|--------|---------|
| `complete` | Primary or acceptable fallback has data |
| `partial` | Some sources have data, some missing |
| `missing` | No sources have data |

### Phase Status

| Status | Meaning |
|--------|---------|
| `complete` | All expected data present |
| `partial` | Some data missing |
| `missing` | No data |
| `bootstrap_skip` | Within 14-day bootstrap period |

---

## Mode Detection

The system auto-detects processing mode:

| Condition | Mode | Effect |
|-----------|------|--------|
| `game_date >= today` | `daily` | Uses roster for player universe |
| `game_date < today` | `backfill` | Uses gamebook for player universe |

Override with environment variable:
```bash
PROCESSING_MODE=backfill python3 bin/validate_pipeline.py 2024-01-15
```

---

## Output Formats

### Default (Summary)

```
PIPELINE VALIDATION: 2024-01-15 (2023-24, Day 87)
Status: COMPLETE

Phase 1 (GCS):     7/7 chains complete
Phase 2 (Raw):     7/7 chains complete
Phase 3:           67/67 players (100%)
Phase 4:           65/67 players (97%)
Phase 5:           65 predictions
```

### JSON Format

```bash
python3 bin/validate_pipeline.py 2024-01-15 --format json
```

Returns structured data for programmatic use.

### Legacy View

```bash
python3 bin/validate_pipeline.py 2024-01-15 --legacy-view
```

Detailed terminal output with tables and formatting.

---

## Troubleshooting

### "Timeout" Status

If a source shows `timeout`:
1. Check BQ query performance
2. Consider increasing `BQ_QUERY_TIMEOUT_SECONDS` (default: 30s)
3. Note: Timeout is distinct from "missing" - data may exist

### Cross-Phase Mismatch

If validation shows "X players in Phase 3 missing from Phase 4":
1. Check if Phase 4 ran with different data source (fallback)
2. Verify Phase 3 and Phase 4 ran on same day
3. May indicate processor re-run with stale cache

### Bootstrap Skip

For dates within 14 days of season start:
- Phase 4/5 validations show `bootstrap_skip`
- This is expected - insufficient historical data for ML features

---

## Files

| File | Purpose |
|------|---------|
| `bin/validate_pipeline.py` | Main entry point |
| `shared/validation/config.py` | Phase/table configurations |
| `shared/validation/chain_config.py` | Chain definitions |
| `shared/validation/validators/base.py` | Helper functions |
| `shared/validation/validators/chain_validator.py` | Chain validation logic |
| `shared/validation/context/schedule_context.py` | Game count, bootstrap detection |
| `shared/validation/context/player_universe.py` | Player set determination |

---

## Related Documentation

- [Validation Gaps Analysis](../08-projects/current/validation/VALIDATION-GAPS-ANALYSIS.md)
- [ESPN Virtual Source Pattern](../06-reference/data-sources/espn-virtual-source-pattern.md)
- [Fallback Strategies](../06-reference/data-sources/02-fallback-strategies.md)
