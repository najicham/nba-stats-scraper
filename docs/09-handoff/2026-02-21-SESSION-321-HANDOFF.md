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
