# Session 144 Prompt - Feature Store Backfill + Coverage Completeness

Copy-paste this into the next Claude Code session.

---

Read the Session 143 handoff at `docs/09-handoff/2026-02-07-SESSION-143-HANDOFF.md`.

## Context

Session 143 fixed ML feature store backfill performance (17.7 min → ~3s per date) and added timing visibility across all processors. Phase 4 is deployed. Now we need to run the backfill and ensure complete player coverage.

## Tasks (in priority order)

### 1. Run the Feature Store Backfill

3,594 records need `feature_N_source` columns populated:

```bash
# 2025-26 season first (363 records, ~33 dates)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-12-01 --end-date 2026-02-07 --skip-preflight

# 2021 season (3,231 records, ~56 dates)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

Verify after:
```sql
SELECT COUNT(*) as still_missing
FROM nba_predictions.ml_feature_store_v2
WHERE feature_1_source IS NULL;
```

### 2. Backfill Oct-Nov 2025 Coverage Gap

1,566 + 843 = 2,409 records missing for 2025-10-22 through 2025-11-03 (bootstrap period). The processor skips the first 14 days of each season. Investigate whether we can backfill these dates:

```bash
# Dry run first to check dependencies
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2025-11-03 --dry-run --skip-preflight
```

If bootstrap skip blocks it, consider temporarily lowering `BOOTSTRAP_DAYS` in `shared/validation/config.py` for the backfill run.

### 3. Create Feature Store Gap Tracking

Create a system to log when the feature store processor skips players, so gaps can be detected and backfilled automatically:

- Create table `nba_predictions.feature_store_gaps` with:
  - `player_lookup STRING`, `game_date DATE`, `skip_reason STRING`
  - `detected_at TIMESTAMP`, `resolved_at TIMESTAMP`
- Update `ml_feature_store_processor.py` to log skipped players to this table
- Create a query/script to find unresolved gaps and suggest backfill commands

### 4. Deploy Phase 2 and Phase 3 with Timing Breakdown

```bash
./bin/deploy-service.sh nba-phase2-processors
./bin/deploy-service.sh nba-phase3-analytics-processors
```

These services got the `timing_breakdown` persistence code but haven't been deployed yet.

### 5. Verify Timing Data is Flowing

After next pipeline run, check:
```sql
SELECT processor_name, data_date, duration_seconds,
  JSON_VALUE(timing_breakdown, '$.extract_time') as extract_s,
  JSON_VALUE(timing_breakdown, '$.save_time') as save_s
FROM nba_reference.processor_run_history
WHERE data_date >= CURRENT_DATE() - 1
  AND timing_breakdown IS NOT NULL
ORDER BY data_date DESC, duration_seconds DESC
LIMIT 20;
```

## Key Questions to Resolve

1. **Should we create feature store records for injured-but-not-dressed players?** Currently only players in `player_game_summary` (dressed for game) get feature records. Players only on the injury report (~9K missing records) don't.

2. **Should we lower bootstrap threshold?** 14 days means first 2 weeks of each season have no feature records. Could lower to 7 days or even 3 days for players with prior season data.

## Key Files

| File | What to Look At |
|------|----------------|
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | Backfill orchestration |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Where players get skipped |
| `shared/validation/config.py` | `BOOTSTRAP_DAYS` setting |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | The optimized extraction queries |
