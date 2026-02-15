# Session 259 Handoff — Combo Registry, Signal Health, Scoring Fix

**Date:** 2026-02-15
**Status:** Code complete, committed. BQ DDLs and backfill NOT yet run.

---

## What Was Done

### Implementation (all committed, not yet deployed)

1. **Combo Registry** (`ml/signals/combo_registry.py`)
   - BQ table `signal_combo_registry` with 7 validated combos from Session 257
   - Python loader with hardcoded fallback (works offline/in tests)
   - `match_combo()` finds best matching combo by highest cardinality
   - Replaces all hardcoded combo bonuses in the aggregator

2. **Signal Count Floor** (`ml/signals/aggregator.py`)
   - `MIN_SIGNAL_COUNT = 2` — 1-signal picks (43.8% HR) excluded from best bets
   - Eliminates ~16 picks (13.6%), of which only 7 were winners
   - Expected HR improvement: ~67.8% → ~72%

3. **Scoring Formula Fix** (`ml/signals/aggregator.py`)
   - Edge contribution: `min(1.0, edge / 7.0)` (was `/10.0`)
   - Signal multiplier: `1.0 + 0.3 * min(signal_count, 3) - 1)` (was unbounded)
   - ANTI_PATTERN combos blocked entirely (no negative scores, just skip)
   - SYNERGISTIC combos get registry-defined `score_weight` bonus

4. **Signal Health Monitoring** (`ml/signals/signal_health.py`)
   - Multi-timeframe HR (7d/14d/30d/season) per signal
   - Regime classification: HOT (div > +10), NORMAL, COLD (div < -10)
   - Status: DEGRADING (COLD + model-dependent), WATCH (div < -5), HEALTHY
   - Informational only — NOT a blocking gate
   - Computed after grading in `post_grading_export`

5. **Combo Fields on All Pick Tables**
   - `matched_combo_id`, `combo_classification`, `combo_hit_rate` on:
     - `pick_signal_tags` (annotations)
     - `signal_best_bets_picks` (curated picks)
     - JSON export

6. **latest.json** — stable URL for frontend at `signal-best-bets/latest.json`

7. **min_signal_count** in JSON metadata so frontend knows the floor

---

## What Needs to Be Done (Next Session)

### Priority 1: BQ DDLs (must do before anything else)

```bash
# 1. Create new tables
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_combo_registry.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_health_daily.sql

# 2. ALTER existing tables (add combo columns)
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.pick_signal_tags ADD COLUMN IF NOT EXISTS matched_combo_id STRING"
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.pick_signal_tags ADD COLUMN IF NOT EXISTS combo_classification STRING"
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.pick_signal_tags ADD COLUMN IF NOT EXISTS combo_hit_rate FLOAT64"

bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.signal_best_bets_picks ADD COLUMN IF NOT EXISTS matched_combo_id STRING"
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.signal_best_bets_picks ADD COLUMN IF NOT EXISTS combo_classification STRING"
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.signal_best_bets_picks ADD COLUMN IF NOT EXISTS combo_hit_rate FLOAT64"
bq query --use_legacy_sql=false "ALTER TABLE nba-props-platform.nba_predictions.signal_best_bets_picks ADD COLUMN IF NOT EXISTS warning_tags ARRAY<STRING>"

# 3. Create view
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/v_signal_combo_performance.sql
```

### Priority 2: Push to main (auto-deploys Cloud Run services)

```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

### Priority 3: Backfill historical data

```bash
# Signal tags + best bets with combo fields (overwrites existing — use --force if needed)
PYTHONPATH=. python ml/experiments/signal_backfill.py --start 2026-01-09 --end 2026-02-14

# Signal health
PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2026-01-09 --end 2026-02-14
```

### Priority 4: Deploy post-grading-export Cloud Function

```bash
./bin/deploy-service.sh post-grading-export
```

### Priority 5: Verify

```bash
# Combo registry populated
bq query --use_legacy_sql=false "SELECT combo_id, classification, status, hit_rate FROM nba_predictions.signal_combo_registry ORDER BY hit_rate DESC"

# Signal health populated
bq query --use_legacy_sql=false "SELECT signal_tag, regime, status FROM nba_predictions.signal_health_daily WHERE game_date = '2026-02-02'"

# Combo performance view
bq query --use_legacy_sql=false "SELECT * FROM nba_predictions.v_signal_combo_performance"

# latest.json exists
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/latest.json | python -m json.tool | head -20
```

---

## Key Decisions Made

1. **Signal count floor = 2, not 3.** 2-signal picks hit 72%, 3-signal hit 74%. The marginal gain from requiring 3 doesn't justify the coverage loss.

2. **ANTI_PATTERN combos are blocked, not penalized.** Negative composite scores created confusing ranking artifacts. Cleaner to just skip them.

3. **Signal health is informational, not blocking.** Session 257 proved threshold-based blocking has negative EV (blocks more winners than losers). Health is for monitoring, frontend transparency, and early model decay detection.

4. **Hardcoded fallback registry.** If BQ is unavailable, the aggregator still works with the 7 validated combos baked into `combo_registry.py`. This prevents production outages from a missing table.

5. **Model retrain is higher priority than more signals.** Champion is 35+ days stale. The other research chat should focus on cross-model signals (21-23) and vegas line movement (9), not the full 23-signal mega plan.

---

## Files Changed

### New
- `ml/signals/combo_registry.py`
- `ml/signals/signal_health.py`
- `ml/signals/combo_3way.py` (from Session 258)
- `ml/signals/combo_he_ms.py` (from Session 258)
- `schemas/bigquery/nba_predictions/signal_combo_registry.sql`
- `schemas/bigquery/nba_predictions/signal_health_daily.sql`
- `schemas/bigquery/nba_predictions/v_signal_combo_performance.sql`

### Modified
- `ml/signals/aggregator.py` — registry-based scoring, floor, new formula
- `ml/signals/registry.py` — combo signals + ESO registered
- `ml/signals/blowout_recovery.py` — center + B2B exclusion
- `ml/signals/cold_snap.py` — home-only filter
- `ml/signals/supplemental_data.py` — position + is_home in supplemental
- `data_processors/publishing/signal_annotator.py` — combo fields
- `data_processors/publishing/signal_best_bets_exporter.py` — combo fields, health, latest.json
- `ml/experiments/signal_backfill.py` — combo registry integration
- `orchestration/cloud_functions/post_grading_export/main.py` — signal health computation

### Commit
`e433b22c` — `feat: combo registry, signal health monitoring, scoring fix, signal count floor`
