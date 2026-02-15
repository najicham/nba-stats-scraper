# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 259 complete)
**Status:** Code committed, BQ DDLs + backfill + deploy pending

---

## Quick Start

```bash
# 1. Read the handoff
cat docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md

# 2. Run BQ DDLs (Priority 1 — tables must exist before deploy)
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_combo_registry.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_health_daily.sql
# Then run the ALTER TABLE commands from the handoff

# 3. Push to main (auto-deploys Cloud Run)
git push origin main

# 4. Backfill historical data
PYTHONPATH=. python ml/experiments/signal_backfill.py --start 2026-01-09 --end 2026-02-14
PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2026-01-09 --end 2026-02-14

# 5. Deploy post-grading-export Cloud Function
./bin/deploy-service.sh post-grading-export

# 6. Validate
/validate-daily
```

---

## What Session 259 Built

- **Combo Registry** — BQ-driven signal combination scoring (replaces hardcoded bonuses)
- **Signal Count Floor** — MIN_SIGNAL_COUNT=2 (1-signal picks at 43.8% HR eliminated)
- **Scoring Formula Fix** — edge capped at /7.0, signal multiplier capped at 3
- **Signal Health Monitoring** — multi-timeframe HR with HOT/NORMAL/COLD regime (informational)
- **ANTI_PATTERN Blocking** — redundancy trap combos blocked entirely
- **latest.json** — stable frontend URL for signal best bets

---

## Strategic Priority: Model Retrain

The champion CatBoost model is 35+ days stale and decaying (71.2% -> 39.9% edge 3+ HR). The signal framework can't fix a decaying model. **Model retrain is the highest-leverage next step.**

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-02-14
```

---

**Handoff:** `docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md`
**Commit:** `e433b22c`
