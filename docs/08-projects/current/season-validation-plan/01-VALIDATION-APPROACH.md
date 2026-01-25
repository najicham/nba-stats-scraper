# Validation Approach

## Overview

This document describes the systematic approach to validating all 2024-25 season data across the entire pipeline.

## Validation Philosophy

### Multi-Dimensional Validation

Data quality issues hide from single-dimension checks. We validate from multiple angles simultaneously:

1. **Existence**: Does data exist for this date?
2. **Completeness**: Is the data complete (expected record counts)?
3. **Quality**: Does the data meet quality thresholds?
4. **Consistency**: Does upstream data match downstream data?
5. **Timeliness**: Was the data processed within expected windows?

### Layered Approach

```
Layer 1: Schedule-Based Validation
├── For each game date in the season
├── Check: Were there games scheduled?
└── Expected: Yes (except All-Star break, offseason)

Layer 2: Phase-by-Phase Validation
├── For each phase (1-6)
├── Check: Does data exist for each scheduled game date?
└── Expected: Records > 0 for dates with games

Layer 3: Completeness Validation
├── For each table in each phase
├── Check: Record count >= expected threshold
└── Expected: Based on games scheduled (10-15 players per game)

Layer 4: Quality Validation
├── For each table with quality columns
├── Check: completeness_pct >= 70%, is_production_ready = TRUE
└── Expected: >70% production-ready records

Layer 5: Cascade Validation
├── For each date with issues
├── Check: Which downstream dates are affected?
└── Expected: Identify all dates within lookback windows
```

## Validation Scope

### Date Range

```
Start Date: 2024-10-22 (Season opener)
End Date:   2026-01-25 (Today - adjust as needed)
Total Days: ~460 days (through current date)
Game Days:  ~280 days (excluding offseason, All-Star)
```

### Phase Coverage

| Phase | Tables | Key Checks |
|-------|--------|------------|
| Phase 1 | GCS files | File existence per scraper/date |
| Phase 2 | 21+ tables | Record existence per game date |
| Phase 3 | 5 tables | Analytics completeness |
| Phase 4 | 5 tables | Feature quality, cascade health |
| Phase 5 | 6 tables | Prediction coverage |
| Phase 6 | 4 tables | Grading completeness |

## Validation Metrics

### Per-Date Metrics

For each date, we capture:

```yaml
date: "2024-12-15"
has_games: true
games_scheduled: 12
validation_status: "WARN"  # PASS | WARN | FAIL | SKIP

phases:
  phase2:
    status: "PASS"
    tables:
      nbac_player_boxscore:
        records: 156
        expected_min: 120  # 10 players * 12 games
        status: "PASS"
      bdl_player_boxscores:
        records: 152
        expected_min: 120
        status: "PASS"

  phase3:
    status: "WARN"
    tables:
      player_game_summary:
        records: 156
        expected_min: 120
        status: "PASS"
        quality_metrics:
          production_ready_pct: 68.5  # Below 70% threshold
          avg_completeness: 72.3
        status: "WARN"

  phase4:
    status: "FAIL"
    tables:
      ml_feature_store_v2:
        records: 0
        expected_min: 120
        status: "FAIL"

cascade_impact:
  affected_downstream_dates:
    - "2024-12-16"
    - "2024-12-17"
    # ... up to 30 days
  impact_severity: "HIGH"
```

### Aggregated Metrics

```yaml
season_summary:
  total_game_dates: 280
  validated_dates: 280

  by_status:
    PASS: 245
    WARN: 25
    FAIL: 10

  by_phase:
    phase2:
      pass_rate: 98.2%
      gaps: 5
    phase3:
      pass_rate: 95.0%
      gaps: 14
    phase4:
      pass_rate: 91.1%
      gaps: 25
    phase5:
      pass_rate: 88.5%
      gaps: 32

  cascade_contamination:
    total_affected_dates: 87
    high_severity: 15
    medium_severity: 32
    low_severity: 40
```

## Validation Sources

### Schedule as Ground Truth

The NBA schedule table serves as the "source of truth" for expected game dates:

```sql
-- Get all game dates with expected counts
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_scheduled,
  SUM(CASE WHEN game_status = 'Final' THEN 1 ELSE 0 END) as games_completed
FROM `nba_raw.nbac_schedule`
WHERE season_year = 2024
  AND game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date
```

### Expected Record Counts

| Table | Expected Records Per Game | Formula |
|-------|---------------------------|---------|
| Phase 2 raw player tables | 10-15 | ~12 active players per team * 2 teams |
| Phase 3 player_game_summary | 10-15 | Same as Phase 2 |
| Phase 4 ml_feature_store | 10-15 | Same as Phase 3 |
| Phase 5 predictions | 8-12 | Players with prop lines |
| Phase 6 grading | 8-12 | Predictions that can be graded |

## Validation Tools

### Existing Tools to Leverage

| Tool | Purpose | Location |
|------|---------|----------|
| `daily_data_completeness.py` | Quick phase coverage scan | `/bin/validation/` |
| `comprehensive_health_check.py` | 9-angle quality check | `/bin/validation/` |
| `preflight_check.py` | Pre-backfill data check | `/bin/backfill/` |
| `verify_phase3_for_phase4.py` | Phase 3 readiness | `/bin/backfill/` |
| `test_validation_system.sh` | Run all validators | `/validation/` |
| Individual validators | Per-table validation | `/validation/validators/` |

### New Validation Outputs Needed

1. **Season-wide validation runner** - Iterate all dates, all phases
2. **Cascade impact calculator** - Determine affected downstream dates
3. **Validation results table** - Store results in BigQuery
4. **Backfill priority queue** - Ranked list of dates to fix

## Validation Execution Strategy

### Phase 1: Quick Scan (Discovery)

Run lightweight checks to identify obvious gaps:

```bash
# Quick completeness scan across season
python bin/validation/daily_data_completeness.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --output-format json > validation_quick_scan.json
```

### Phase 2: Deep Validation (Analysis)

For dates flagged in Phase 1, run comprehensive checks:

```bash
# Run all validators for specific date range
./validation/test_validation_system.sh \
  --start-date 2024-10-22 \
  --end-date 2024-10-31 \
  --output-dir ./validation_results/
```

### Phase 3: Cascade Analysis (Impact)

Calculate cascade impact for all identified gaps:

```sql
-- For each gap date, calculate affected downstream dates
WITH gaps AS (
  SELECT game_date
  FROM validation_results
  WHERE status = 'FAIL' AND phase = 'phase3'
)
SELECT
  g.game_date as gap_date,
  d.game_date as affected_date,
  DATE_DIFF(d.game_date, g.game_date, DAY) as days_downstream
FROM gaps g
CROSS JOIN (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
) d
WHERE d.game_date > g.game_date
  AND d.game_date <= DATE_ADD(g.game_date, INTERVAL 30 DAY)
ORDER BY g.game_date, d.game_date
```

### Phase 4: Prioritization (Planning)

Rank gaps by impact for backfill prioritization:

```
Priority Score = (Recency Weight * 0.4) + (Cascade Impact * 0.3) + (Phase Severity * 0.3)

Where:
- Recency Weight: 1.0 for <30 days, 0.7 for 30-60 days, 0.4 for >60 days
- Cascade Impact: HIGH=1.0, MEDIUM=0.6, LOW=0.3
- Phase Severity: Phase2=1.0, Phase3=0.8, Phase4=0.6, Phase5=0.4
```

## Special Handling

### Early Season Bootstrap Period

First 14 days of season (Oct 22 - Nov 5, 2024) have expected lower quality:
- Rolling windows not yet populated
- `is_production_ready` may be FALSE (acceptable)
- Do not flag as failures

### All-Star Break

Feb 14-17, 2025: No regular games scheduled
- Skip validation for these dates
- Mark as "NO_GAMES"

### Playoffs

Different validation thresholds may apply:
- Fewer games per day (2-4 vs 10-15)
- Higher stakes = stricter validation

## Next Steps

1. Review [02-PHASE-VALIDATION-MATRIX.md](./02-PHASE-VALIDATION-MATRIX.md) for per-phase details
2. Review [03-CASCADE-IMPACT-TRACKING.md](./03-CASCADE-IMPACT-TRACKING.md) for cascade logic
3. Review [04-RESULTS-STORAGE-SCHEMA.md](./04-RESULTS-STORAGE-SCHEMA.md) for storage design
