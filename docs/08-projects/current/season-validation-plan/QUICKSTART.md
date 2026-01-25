# Quick Start: Season Validation

## TL;DR

Run these commands to validate the entire 2024-25 season and identify what needs backfilling:

```bash
# 1. Setup
cd /home/naji/code/nba-stats-scraper
source venv/bin/activate
mkdir -p validation_results

# 2. Quick discovery scan
python bin/validation/daily_data_completeness.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --output-format json \
  > validation_results/season_scan.json

# 3. View summary
jq '.summary' validation_results/season_scan.json

# 4. Find gaps
jq '[.dates[] | select(.overall_status == "FAIL")] | length' validation_results/season_scan.json
```

## What This Plan Covers

| Document | Read When |
|----------|-----------|
| [README.md](./README.md) | Overview and objectives |
| [01-VALIDATION-APPROACH.md](./01-VALIDATION-APPROACH.md) | Understanding the methodology |
| [02-PHASE-VALIDATION-MATRIX.md](./02-PHASE-VALIDATION-MATRIX.md) | What to check for each phase |
| [03-CASCADE-IMPACT-TRACKING.md](./03-CASCADE-IMPACT-TRACKING.md) | Understanding downstream effects |
| [04-RESULTS-STORAGE-SCHEMA.md](./04-RESULTS-STORAGE-SCHEMA.md) | Setting up BigQuery tables |
| [05-EXECUTION-PLAN.md](./05-EXECUTION-PLAN.md) | Step-by-step commands |
| [06-PRIORITIZATION-FRAMEWORK.md](./06-PRIORITIZATION-FRAMEWORK.md) | What to fix first |

## Key Concepts

### 1. Six Pipeline Phases

```
Phase 1: Scrapers → GCS files
Phase 2: Raw Processors → nba_raw.* tables
Phase 3: Analytics → nba_analytics.* tables
Phase 4: Precompute → nba_precompute.* tables
Phase 5: Predictions → nba_predictions.* tables
Phase 6: Grading → nba_predictions.prediction_accuracy
```

### 2. Cascade Impact

A gap in Phase 2 affects up to 30 downstream dates due to rolling windows:
- L5: 5-game lookback
- L10: 10-game lookback
- L14d: 14-day lookback
- L20: 20-game lookback

**Rule:** Always fix upstream gaps first!

### 3. Priority Tiers

| Tier | Criteria | SLA |
|------|----------|-----|
| P0 | Recent (<14d) Phase 2 gaps | 24 hours |
| P1 | 14-30 day gaps, high cascade | 7 days |
| P2 | 30-60 day gaps | 2 weeks |
| P3 | Old gaps, bootstrap period | 30 days |

## Common Scenarios

### "I need to validate everything"

Follow the full [Execution Plan](./05-EXECUTION-PLAN.md):
1. Run discovery scan
2. Run detailed validators
3. Calculate cascade impact
4. Generate backfill queue
5. Execute backfills by phase
6. Verify resolution

### "I need to check a specific date"

```bash
python bin/validation/comprehensive_health_check.py --date 2025-01-15
```

### "I need to find all Phase 3 gaps"

```sql
-- In BigQuery
SELECT DISTINCT game_date
FROM `nba_raw.nbac_schedule` s
LEFT JOIN `nba_analytics.player_game_summary` p USING (game_date)
WHERE s.season_year = 2024
  AND s.game_status = 'Final'
  AND p.game_date IS NULL
ORDER BY game_date;
```

### "I need to backfill a single date"

```bash
DATE="2025-01-15"

# Phase 2
python backfill_jobs/raw/bdl_player_boxscores/bdl_player_boxscores_raw_backfill.py --date $DATE

# Phase 3
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date $DATE --end-date $DATE

# Phase 4 (in order)
./bin/backfill/run_phase4_backfill.sh --start-date $DATE --end-date $DATE
```

### "I need to know what dates are affected by a gap"

```sql
-- For gap on Jan 15
SELECT game_date as affected_date
FROM `nba_raw.nbac_schedule`
WHERE game_date > '2025-01-15'
  AND game_date <= DATE_ADD('2025-01-15', INTERVAL 20 DAY)
  AND season_year = 2024
ORDER BY game_date;
```

## Validation Status Meanings

| Status | Meaning | Action |
|--------|---------|--------|
| PASS | Data complete and quality OK | None |
| WARN | Data exists but quality below threshold | Review, maybe backfill |
| FAIL | Data missing or critically incomplete | Backfill required |
| SKIP | No games scheduled (All-Star break) | None |
| BOOTSTRAP | Early season, low quality expected | Accept or defer |

## BigQuery Tables to Query

```sql
-- Check Phase 2 completeness
SELECT game_date, COUNT(*) as records
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date;

-- Check Phase 3 quality
SELECT game_date,
  COUNT(*) as records,
  COUNTIF(is_production_ready) as prod_ready,
  AVG(completeness_pct) as avg_completeness
FROM `nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date;

-- Check Phase 4 quality tiers
SELECT game_date,
  COUNT(*) as records,
  COUNTIF(data_quality_tier = 'gold') as gold,
  COUNTIF(data_quality_tier = 'silver') as silver,
  COUNTIF(data_quality_tier = 'bronze') as bronze
FROM `nba_precompute.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date;
```

## Next Steps

1. **Read the full plan** - Start with [README.md](./README.md)
2. **Set up result storage** - See [04-RESULTS-STORAGE-SCHEMA.md](./04-RESULTS-STORAGE-SCHEMA.md)
3. **Run discovery scan** - Follow [05-EXECUTION-PLAN.md](./05-EXECUTION-PLAN.md)
4. **Prioritize backfills** - Use [06-PRIORITIZATION-FRAMEWORK.md](./06-PRIORITIZATION-FRAMEWORK.md)
5. **Execute and verify** - Track progress in BigQuery

## Questions?

Check existing documentation:
- `/docs/02-operations/` - Operational procedures
- `/docs/08-projects/current/validation-framework/` - Validation framework details
- `/bin/validation/` - Available validation scripts
- `/validation/` - Validator implementations
