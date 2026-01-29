# DNP Tracking Improvements - January 29, 2026

## Project Summary

Improved injured/DNP player detection in the prediction pipeline by leveraging historical gamebook data to supplement pre-game injury reports.

## Problem Statement

Two parallel injury tracking systems existed but didn't communicate:

1. **Gamebook-based (Post-Game)**: Captured DNP/inactive status after games
   - Source: `nbac_gamebook_player_stats` → `player_game_summary.is_dnp`
   - Used by: Analytics, grading
   - NOT used by: Predictions

2. **Injury Report-based (Pre-Game)**: NBA.com injury report PDF
   - Source: `nbac_injury_report`
   - Used by: `InjuryFilter` in predictions
   - NOT connected to: Analytics pipeline

**Key Finding**: On Jan 28, 2026:
- 112 players were DNP
- 73 (65%) were in injury report as "out" → correctly filtered
- **39 (35%) NOT in injury report** → slipped through predictions
  - 23 coach decisions (D'Angelo Russell, Gary Payton II, etc.)
  - 5 injured but not reported (Stephen Curry - sciatic nerve, Jimmy Butler - ACL!)
  - 11 G League two-way / unspecified

## Solution Implemented

### 1. InjuryFilter v2.1 (`predictions/shared/injury_filter.py`)

Added historical DNP pattern detection:

```python
from predictions.shared.injury_filter import get_injury_filter, DNPHistory

filter = get_injury_filter()

# Check DNP history (v2.1)
dnp_history = filter.check_dnp_history(player_lookup, game_date)
if dnp_history.has_dnp_risk:
    # Player has 2+ DNPs in last 5 games
    print(f"DNP Risk: {dnp_history.dnp_count}/{dnp_history.games_checked} games")
    print(f"Category: {dnp_history.risk_category}")

# Or get combined risk
status, dnp_history = filter.get_combined_risk(player_lookup, game_date)
```

**New Methods:**
- `check_dnp_history(player_lookup, game_date)` - Single player
- `check_dnp_history_batch(players, game_date)` - Batch check
- `get_combined_risk(player_lookup, game_date)` - Both injury + DNP
- `get_combined_risk_batch(players, game_date)` - Batch combined

**Configuration:**
- `DNP_HISTORY_WINDOW = 5` - Games to check
- `DNP_RISK_THRESHOLD = 2` - DNPs to trigger risk flag

### 2. Worker Integration v4.1 (`predictions/worker/worker.py`)

Added DNP history checking to prediction generation:
- Calls `check_dnp_history()` after injury status check
- Injects `dnp_history` into features and metadata
- Logs warnings for players with DNP risk patterns

### 3. ML Feature Store v3.1

Added Feature 33: `dnp_rate` to enable model learning:

- **feature_calculator.py**: Added `calculate_dnp_rate()` method
- **feature_extractor.py**: Updated query to include `is_dnp` field
- **ml_feature_store_processor.py**:
  - Upgraded to `v2_34features`
  - Added dnp_rate calculation at Feature 33

## Files Changed

| File | Change |
|------|--------|
| `predictions/shared/injury_filter.py` | Added DNPHistory dataclass and v2.1 methods |
| `predictions/worker/worker.py` | Integrated DNP history checking |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Added calculate_dnp_rate() |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Added is_dnp to query |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Added Feature 33 |

## Commits

| Commit | Description |
|--------|-------------|
| `c1d90122` | feat: Add InjuryFilter v2.1 with historical DNP pattern detection |
| `76af278f` | feat: Integrate DNP history into worker and add dnp_rate ML feature |
| `835dc9b6` | docs: Update Session 17 handoff |

## Deployments

| Service | Old Revision | New Revision |
|---------|-------------|--------------|
| prediction-worker | 00020-mwv | 00022-f7b |
| prediction-coordinator | 00101-dtr | 00102-m28 |
| nba-phase4-precompute-processors | 00073-tg4 | 00075-vhh |

## Data Caveat

The `is_dnp` field in `player_game_summary` only started being populated on 2026-01-28. Historical DNP patterns will become more effective as data accumulates over the coming weeks.

## Future Enhancements

1. **Backfill is_dnp data**: Could enable immediate pattern detection
2. **Adjust risk thresholds**: Based on observed DNP patterns
3. **Coach decision prediction**: ML model to predict coach decisions based on game context
4. **Integration with betting lines**: Factor DNP risk into confidence scoring

## Testing

```bash
# Check DNP data availability
bq query --use_legacy_sql=false "
SELECT is_dnp, dnp_reason_category, COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-28'
GROUP BY 1, 2"

# Check injury filter v2.1 in logs
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload:"DNP risk"' --limit=20
```

## Related Documentation

- Handoff: `docs/09-handoff/2026-01-29-SESSION-17-HANDOFF.md`
- Schema: `schemas/bigquery/analytics/player_game_summary_tables.sql`
