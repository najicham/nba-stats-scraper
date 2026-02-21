---
name: backfill-subsets
description: Dry-run and execute subset backfills with before/after comparison
---

# Backfill Subsets Skill

Simulate and execute best bets subset backfills for historical date ranges. Compares what the current consolidated code (v314) would pick against existing subset data, with full grading against actual results.

## Trigger
- `/backfill-subsets`
- "backfill subsets", "re-materialize picks", "dry run best bets"
- "test how backfill would perform"

## Quick Start

### Dry-run a single date
```bash
PYTHONPATH=. python bin/backfill_dry_run.py --date 2026-02-19
```

### Dry-run a range with comparison to existing picks
```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-02-01 --end 2026-02-19 --compare
```

### Full season simulation
```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-01 --end 2026-02-19 --compare
```

## Step-by-Step Workflow

### Phase 1: Dry Run (always do this first)

Run the simulation for the target date range:

```bash
PYTHONPATH=. python bin/backfill_dry_run.py \
    --start {START_DATE} --end {END_DATE} --compare
```

This will:
1. For each date, query all CatBoost predictions (multi_model=True)
2. Evaluate signals, compute blacklist, games_vs_opponent
3. Run BestBetsAggregator with consolidated filters (edge 5+, UNDER 7+ block, etc.)
4. Grade picks against prediction_accuracy
5. Compare against existing best_bets subset picks
6. Print daily picks with W/L and summary stats

**Interpret results:**
- Hit rate should be 60%+ at edge 5+ (season average is ~71%)
- Check filter_summary for any unexpected rejections
- `--compare` shows which players would be added/removed vs old picks

### Phase 2: Review Results

Before executing, check:
- [ ] Overall HR is >= 60%
- [ ] No dates with 0 picks that previously had picks (regression)
- [ ] Filter rejections make sense (edge_floor should be the largest)
- [ ] No surprising player removals in `--compare` output

### Phase 3: Execute Backfill (after user approval)

```bash
# Step 1: Delete old rows for the date range
python3 -c "
from google.cloud import bigquery
c = bigquery.Client(project='nba-props-platform')

for table in ['current_subset_picks', 'signal_best_bets_picks', 'pick_signal_tags']:
    q = f'''DELETE FROM \`nba-props-platform.nba_predictions.{table}\`
    WHERE game_date BETWEEN '{START_DATE}' AND '{END_DATE}'
    '''
    result = c.query(q).result()
    print(f'Deleted from {table}')
"

# Step 2: Re-materialize
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
    --start-date {START_DATE} --end-date {END_DATE} \
    --only subset-picks,signal-best-bets,live-grading
```

**Important:** The delete + re-materialize should run in sequence. Estimated time: ~30 sec per date.

### Phase 4: Verify

```bash
# Check row counts
python3 -c "
from google.cloud import bigquery
c = bigquery.Client(project='nba-props-platform')
for table in ['current_subset_picks', 'signal_best_bets_picks', 'pick_signal_tags']:
    rows = list(c.query(f'''
    SELECT COUNT(*) as n, COUNT(DISTINCT game_date) as dates
    FROM nba_predictions.{table}
    WHERE game_date BETWEEN \"{START_DATE}\" AND \"{END_DATE}\"
    ''').result())
    print(f'{table}: {rows[0].n} rows, {rows[0].dates} dates')
"

# Check algorithm_version on new rows
python3 -c "
from google.cloud import bigquery
c = bigquery.Client(project='nba-props-platform')
rows = list(c.query('''
SELECT algorithm_version, COUNT(*) as n
FROM nba_predictions.signal_best_bets_picks
WHERE game_date BETWEEN \"{START_DATE}\" AND \"{END_DATE}\"
GROUP BY 1
''').result())
for r in rows:
    print(f'  {r.algorithm_version}: {r.n} rows')
"
```

## Parameters

| Flag | Description | Default |
|------|-------------|---------|
| `--date` | Single date (YYYY-MM-DD) | — |
| `--start` | Range start date | — |
| `--end` | Range end date | — |
| `--compare` | Compare against existing best_bets subset | Off |
| `--verbose` / `-v` | Show debug logging | Off |

## Output Format

Per date:
```
  2026-02-19  |  85 preds → 4 passed → 4 picks  |  3-1 (75%)
  Filters: edge_floor=52, signal_count=18, quality_floor=7
    ✓ tyresemaxey               UNDER edge=  8.7 actual=28 model=v12
    ✓ jarrettallen              OVER  edge=  9.0 actual=31 model=v8
```

Summary:
```
SUMMARY — 50 days, v314_consolidated
  Total picks:  185
  Graded:       180 (128W - 52L)
  Hit Rate:     71.1%
  Est. P&L:     $+7,080 ($110 risk / $100 win)
```

## Key Files

| File | Purpose |
|------|---------|
| `bin/backfill_dry_run.py` | Dry-run simulation script |
| `backfill_jobs/publishing/daily_export.py` | Production backfill runner |
| `ml/signals/aggregator.py` | BestBetsAggregator (v314_consolidated) |
| `data_processors/publishing/signal_best_bets_exporter.py` | System 2 exporter |
| `data_processors/publishing/signal_annotator.py` | System 3 annotator bridge |

## Safety Notes

- **Always dry-run first** — never execute Phase 3 without reviewing Phase 1 results
- The delete is irreversible for the date range, but data is fully reconstructable
- Old picks did NOT have `algorithm_version` set (always NULL). New picks will have `v314_consolidated`
- Backfill is date-relative for all filters (blacklist, familiar matchup, signals)
- Model health uses `CURRENT_DATE()` (not target_date) but doesn't affect selection

---
*Created: Session 314C*
*Algorithm: v314_consolidated*
