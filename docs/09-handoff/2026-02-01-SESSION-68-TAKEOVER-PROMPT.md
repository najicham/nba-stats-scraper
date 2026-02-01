# Session 68 Takeover Prompt

**Date:** 2026-02-01
**Previous Session:** 67
**Priority:** Fix experiment code line source, February retrain

---

## Quick Context

Session 67 deployed CatBoost V9 with **79.4% high-edge hit rate** on backfilled predictions. However, there's a discrepancy between experiment evaluation (72.2%) and production backfill (79.4%) due to different line sources.

---

## Start Here

```bash
# 1. Read the full handoff
cat docs/09-handoff/2026-02-01-SESSION-67-HANDOFF.md

# 2. Use agents to study the codebase
```

**Use these agent prompts to understand the system:**

```
Task(subagent_type="Explore", prompt="Read docs/08-projects/current/ml-challenger-experiments/README.md and ML-EXPERIMENTATION-ROADMAP.md to understand V9 and experiment plans")

Task(subagent_type="Explore", prompt="Read ml/experiments/quick_retrain.py and identify where BettingPros Consensus lines are used - these should be changed to Odds API DraftKings")

Task(subagent_type="Explore", prompt="Read predictions/worker/prediction_systems/catboost_v9.py to understand V9 implementation")
```

---

## Priority 1: Fix Experiment Line Source

### The Problem

Experiment code uses **BettingPros Consensus** lines, but production uses **Odds API DraftKings** lines. This causes evaluation to underestimate performance.

### The Fix

In `ml/experiments/quick_retrain.py`, change `load_eval_data()`:

```python
# FROM (current):
FROM nba_raw.bettingpros_player_points_props
WHERE bookmaker = 'BettingPros Consensus'

# TO (correct):
FROM nba_raw.odds_api_player_points_props
WHERE bookmaker = 'draftkings'
```

### Verify

After fixing, re-run the experiment:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_VERIFY_LINES" \
    --train-start 2025-11-02 --train-end 2026-01-08 \
    --eval-start 2026-01-09 --eval-end 2026-01-31
```

Expected: Hit rates should match backfill (~79% high-edge, ~65% premium).

---

## Priority 2: February Retrain

Retrain V9 with expanded training window:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31 \
    --eval-start 2026-01-25 \
    --eval-end 2026-01-31 \
    --hypothesis "February retrain with expanded training window"
```

If better than current V9, deploy:
```bash
gsutil cp models/catboost_retrain_V9_FEB_RETRAIN_*.cbm \
    gs://nba-props-platform-models/catboost/v9/
./bin/deploy-service.sh prediction-worker
```

---

## Priority 3: Historical Feature Cleanup

Fix team_win_pct for 2024-25 season (100% stuck at 0.5):

1. Run audit: `PYTHONPATH=. python bin/audit_feature_store.py --season 2024-25 --check-leakage`
2. Create correction table from game results
3. Backfill feature store
4. Enable cross-season training experiments

See: `docs/08-projects/current/ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md`

---

## V9 Current Status

| Metric | Value |
|--------|-------|
| System ID | `catboost_v9` |
| Deployed | ✅ Yes (default) |
| Training | Nov 2, 2025 → Jan 8, 2026 |
| High-Edge Hit Rate | 79.4% |
| Premium Hit Rate | 65.6% |
| Predictions Backfilled | 6,465 (Jan 9-31) |

---

## Key Files

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v9.py` | V9 prediction system |
| `ml/experiments/quick_retrain.py` | Monthly retraining (NEEDS LINE SOURCE FIX) |
| `ml/backfill_v8_predictions.py` | Backfill with V9 support |
| `bin/audit_feature_store.py` | Feature quality scanner |
| `docs/08-projects/current/ml-challenger-experiments/` | All documentation |

---

## Verification

```bash
# Check V9 is running
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"catboost_v9"' --limit=5

# Check V9 predictions
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions, MAX(game_date) as latest
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
GROUP BY 1"
```

---

*Created: Session 67, 2026-02-01*
