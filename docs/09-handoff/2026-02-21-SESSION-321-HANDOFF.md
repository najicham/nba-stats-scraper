# Session 321 Handoff: Line Contamination Remediation (Partial)

**Date:** 2026-02-21
**Status:** PARTIAL — Jan 12 fixed, broader remediation still needed

---

## The Problem

`bettingpros_player_points_props` stores ALL prop types (points, rebounds, assists, blocks, steals, threes) despite its name. Six production code paths queried it without `AND market_type = 'points'`, so the pipeline picked up non-points lines (rebounds at 4.5, assists at 5.5) as points lines, creating fake 10-20pt edges.

**Code fix already deployed** in prior session: 6 files patched (commit `a50fd28e`).

---

## What Was Completed This Session

### Jan 12 Remediation (DONE)

| Phase | Status | Result |
|-------|--------|--------|
| **A: Snapshot** | DONE | Captured: 132 sub-5 lines, 76.3% HR, 52 best bets, 92-32 season |
| **B: Fix lines** | DONE | NULL'd 990 lines → re-enriched 482 from OddsAPI. Avg line: 7.1→13.9 |
| **C: Re-grade** | DONE | 312 graded, HR: 76.3%→49.0%, MAE: 4.92 |
| **D: Signals/best-bets** | DONE | Best bets: 52→1 pick. Signal tags re-annotated |
| **E: model_performance_daily** | DONE | 74 rows backfilled (Jan 12→Feb 20) |
| **E: signal_health_daily** | DONE | 492 rows backfilled (Jan 12→Feb 21) |
| **H: Prevention code** | DONE | Line <5.0 floor in 5 code paths, committed+pushed (`a9bf195c`) |

### Season Record After Jan 12 Fix

- **Before:** 92-32 (74.2%) — inflated by 52 fake Jan 12 picks
- **After:** 50-34 (64.1%)

---

## What Was NOT Completed

### 1. Phase F: GCS Full Re-export for Jan 12

Partial export (`--only subset-picks,signal-best-bets,results`) completed. Full export got stuck. Need:

```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-01-12
```

### 2. Dec 20, 22, 25 Remediation

Investigation found **3 additional contaminated dates**:

| Date | Contaminated Lines | Avg BP Line | Avg OddsAPI Line | Inflated HR |
|------|--------------------|-------------|------------------|-------------|
| Dec 20 | 90 | 3.7 | 9.4 | 83.2% |
| Dec 22 | 67 | 3.7 | 9.4 | 91.3% |
| Dec 25 | 23 | 4.0 | 6.4 | 78.9% |

**Impact:** Does NOT affect best bets record (no best bets on those dates). Affects `prediction_accuracy` and rolling metric windows.

### 3. Rolling Metrics Need Broader Backfill

After fixing Dec 20/22/25, need to re-backfill from Dec 20 → present.

### 4. Model Retrain for Freshness

All models 16+ days stale vs 7-day cadence. Not contamination-related but needed.

---

## Investigation Findings

### Training Data: NOT CONTAMINATED

- Feature store Phase 4 extractor already had `market_type='points'` filter
- Training labels come from box scores
- Models are clean — no retraining needed for contamination

### Model Eval Windows

- **Production model** (`catboost_v9_33f_train20260106-20260205`): eval Feb 6+. **Clean.**
- Two old non-production models had Jan 12 in eval (Jan 9-15). Neither deployed.

### Best Bets Record: Clean (post Jan 12 fix)

3 other best bets with lines < 5.0 are all **legitimate** bench player lines:
- Jan 11: Mitchell Robinson 4.0 (OddsAPI confirms)
- Jan 16: Bryce McGowens 4.5 (OddsAPI confirms)
- Jan 25: Ochai Agbaji 3.5 (OddsAPI confirms)

### Edge/Subset Cold-Start (Early January): No Issue

System works from day one:
- Edge is `predicted - line` (current-day only)
- Player blacklist needs 8+ picks to fire (permissive at startup)
- Games vs opponent uses gamebooks, not predictions
- Signals use current game context

---

## Full Plan for Next Session

### Step 1: Fix Dec 20, 22, 25 (sequential, ~15 min)

For EACH date (2025-12-20, 2025-12-22, 2025-12-25):

```bash
# NULL out BETTINGPROS-sourced lines only
bq query --use_legacy_sql=false '
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET current_points_line = NULL, has_prop_line = FALSE, line_source = NULL,
    line_source_api = NULL, sportsbook = NULL, line_margin = NULL,
    recommendation = CASE WHEN recommendation IN ("OVER","UNDER") THEN "NO_LINE" ELSE recommendation END,
    updated_at = CURRENT_TIMESTAMP()
WHERE game_date = "YYYY-MM-DD" AND line_source_api = "BETTINGPROS"'

# Re-enrich from clean OddsAPI
PYTHONPATH=. python data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py --date YYYY-MM-DD

# Re-grade
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --dates YYYY-MM-DD --no-resume
```

### Step 2: Full export for Jan 12 (~5 min)

```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-01-12
```

### Step 3: Delete + backfill rolling metrics from Dec 20 (~10 min)

```bash
bq query --use_legacy_sql=false 'DELETE FROM `nba-props-platform.nba_predictions.model_performance_daily` WHERE game_date >= "2025-12-20"'
bq query --use_legacy_sql=false 'DELETE FROM `nba-props-platform.nba_predictions.signal_health_daily` WHERE game_date >= "2025-12-20"'
PYTHONPATH=. python ml/analysis/model_performance.py --backfill --start 2025-12-20 --end 2026-02-22
PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2025-12-20 --end 2026-02-22
```

### Step 4: Export today's dashboard (~2 min)

```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-22 --only best-bets-all,admin-dashboard
```

### Step 5: Validate

```sql
-- Zero sub-5 BETTINGPROS lines on Dec 20/22/25
SELECT game_date, COUNTIF(line_value < 5.0) as below_5
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date IN ('2025-12-20','2025-12-22','2025-12-25')
GROUP BY 1;

-- Season record
-- (JOIN signal_best_bets_picks with prediction_accuracy on game_date+player_lookup+system_id)
```

### Step 6: Model retrain for freshness (~30 min)

```bash
./bin/retrain.sh --promote --eval-days 14
./bin/model-registry.sh sync
```

---

## Broader Remediation: Full Season Replay + Best Bets Backfill

### Context

The signal best bets system (v314 consolidated algorithm) was deployed mid-January 2026. The current season record only starts from Jan 9. We want to:

1. **Replay early January** as if the current algorithm was running then — backfill best bets picks from the start of the season using the current edge-first architecture (edge 5+, negative filters, all models)
2. **Retrain all model families** for freshness (all 16+ days stale vs 7-day cadence)
3. **Backfill shadow model best bets** — see what picks the shadow models (V12, V9 Q43/Q45, V12 Q43/Q45) would have made

### How Edge Filtering Works at Cold Start (Early January)

The edge-based system has **no cold start problem**:
- **Edge calculation**: `predicted_points - line_value` — purely current-day, no history needed
- **Edge floor (>= 5.0)**: Static threshold, not learned from data
- **Player blacklist**: Needs 8+ edge-3+ picks at <40% HR to block. At season start, no player has enough picks → all pass
- **Games vs opponent**: Checks historical gamebooks (box scores), not prediction history → works from first game
- **Signals**: Fire based on current game context features, not historical predictions

So the algorithm would have produced valid picks from day one. The only difference is that negative filters (especially player blacklist) wouldn't have blocked bad players until mid-season.

### Replay Plan

#### Phase 1: Ensure clean data (Dec 20/22/25 fix + re-grade)

See Steps 1-5 above. Must be done FIRST before any backfill.

#### Phase 2: Best bets backfill for full season

```bash
# Backfill signal best bets for each game date from season start
# This re-runs the v314 consolidated algorithm (edge 5+, negative filters)
for date in $(bq query --use_legacy_sql=false --format=csv --max_rows=200 \
  'SELECT DISTINCT game_date FROM `nba-props-platform.nba_predictions.prediction_accuracy` WHERE game_date >= "2025-11-02" AND game_date < "2026-01-09" ORDER BY 1' \
  | tail -n +2); do
  echo "Backfilling $date"
  PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date $date --only signal-best-bets
done
```

**What this does:**
- For each date Nov 2 → Jan 8 (before the system went live), re-runs the SignalBestBetsExporter
- Uses edge 5+ floor, all negative filters (player blacklist, games_vs_opponent, UNDER edge 7+ block, etc.)
- Picks up to 5 picks per day ranked by edge
- Writes to `signal_best_bets_picks` table (idempotent — DELETE + INSERT per date)

**What to watch for:**
- Early November: Only champion V9 model was running → no cross-model consensus
- Shadow models (V12, quantile) deployed late January → only contribute to late-season backfill
- Player blacklist will be empty for early dates (needs accumulation) — could include players that later get blocked

#### Phase 3: Multi-model backfill with shadow predictions

The shadow models (V12 MAE, V9 Q43/Q45, V12 Q43/Q45, V9 low-vegas) started predicting at different dates. For the replay to be complete, we need their predictions to exist in `player_prop_predictions`. Check coverage:

```sql
SELECT
  system_id,
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction,
  COUNT(DISTINCT game_date) as days_active
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2025-11-01'
  AND is_active = TRUE
GROUP BY 1
ORDER BY 1;
```

If shadow models don't have predictions for early dates, the best bets backfill will only use V9 champion picks for those dates (which is correct — can't backfill what didn't exist).

#### Phase 4: Retrain all model families

```bash
# Champion V9 (7-day rolling window)
./bin/retrain.sh --promote --eval-days 14

# All shadow families
./bin/retrain.sh --all --eval-days 14

# Sync registry
./bin/model-registry.sh sync
```

#### Phase 5: Re-export full season record

```bash
# After backfill, re-export the all-time best bets record
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date $(date +%Y-%m-%d) --only best-bets-all,admin-dashboard
```

### Expected Outcome

After full backfill:
- Season record starts Nov 2, 2025 (not Jan 9)
- All picks use current v314 consolidated algorithm (edge 5+, negative filters)
- Clean data (no bettingpros contamination)
- Shadow model contributions where they existed
- More accurate assessment of total season P&L

### Key Assumptions

1. **Can't retroactively create shadow model predictions** — if V12/quantile models didn't run before their deploy date, those picks don't exist
2. **Backfilled picks may differ from what would have been live** — player blacklist wouldn't have fired early season, market conditions may have been different
3. **The backfill is for audit/analysis** — these are "what would we have picked" results, not real P&L

---

## Session Notes

- Chat experienced frequent `[Tool result missing due to internal error]` from too many parallel BQ connections. **Next session: run commands sequentially.**
- `daily_export.py` full export is slow (~5+ min) and can hang. Monitor with `ps aux | grep daily_export`.
- `signal_best_bets_picks.prediction_correct` is NOT populated — season record must be computed via JOIN with `prediction_accuracy`.

---

## Files Changed This Session

| File | Change | Commit |
|------|--------|--------|
| `data_processors/enrichment/.../prediction_line_enrichment_processor.py` | Line <5.0 floor in `enrich_predictions()` | `a9bf195c` |
| `predictions/coordinator/player_loader.py` | Line <5.0 floor in 4 query methods | `a9bf195c` |
