# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 260 complete)
**Status:** Sessions 259+260 code committed. BQ DDLs + backfill + deploy pending.

---

## Quick Start

```bash
# 1. Read the handoffs (259 has DDLs, 260 has model selection)
cat docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md
cat docs/09-handoff/2026-02-15-SESSION-260-HANDOFF.md

# 2. Run BQ DDLs (Priority 1 — tables must exist before deploy)
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_combo_registry.sql
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_health_daily.sql
# Then run the ALTER TABLE commands from the Session 259 handoff

# 3. Push to main (auto-deploys Cloud Run)
git push origin main

# 4. Backfill historical data
PYTHONPATH=. python ml/experiments/signal_backfill.py --start 2026-01-09 --end 2026-02-14
PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2026-01-09 --end 2026-02-14

# 5. Deploy post-grading-export Cloud Function
./bin/deploy-service.sh post-grading-export

# 6. Evaluate challenger models and switch if one beats breakeven (52.4%)
# See Session 260 handoff for query + gcloud command

# 7. Validate
/validate-daily
```

---

## What Session 260 Built

- **Configurable Model Selection** — `BEST_BETS_MODEL_ID` env var switches which model drives best bets (no code deploy needed)
- **Signal Health Weighting (LIVE)** — HOT signals 1.2x, COLD signals 0.5x in aggregator scoring
- **Fail-safe defaults** — missing health data = Session 259 behavior, missing env var = champion model

## What Session 259 Built

- **Combo Registry** — BQ-driven signal combination scoring (replaces hardcoded bonuses)
- **Signal Count Floor** — MIN_SIGNAL_COUNT=2 (1-signal picks at 43.8% HR eliminated)
- **Scoring Formula Fix** — edge capped at /7.0, signal multiplier capped at 3
- **Signal Health Monitoring** — multi-timeframe HR with HOT/NORMAL/COLD regime
- **ANTI_PATTERN Blocking** — redundancy trap combos blocked entirely
- **latest.json** — stable frontend URL for signal best bets

---

## Strategic Priority: Unblock Best Bets

Champion model is decayed (36.7% HR). Best bets produces **zero picks**. Two paths to unblock:

1. **Switch to strongest challenger** (fastest — just set env var):
   ```bash
   gcloud run services update <phase6-service> --region=us-west2 \
     --update-env-vars="BEST_BETS_MODEL_ID=catboost_v9_q45_train1102_0131"
   ```

2. **Retrain champion** (better long-term):
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_FEB_RETRAIN" \
       --train-start 2025-11-02 \
       --train-end 2026-02-14
   ```

---

**Handoffs:**
- Session 260: `docs/09-handoff/2026-02-15-SESSION-260-HANDOFF.md`
- Session 259: `docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md`
**Project docs:** `docs/08-projects/current/signal-discovery-framework/SESSION-260-ADAPTIVE-PREDICTION-SYSTEM.md`
