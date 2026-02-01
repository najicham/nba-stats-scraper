# Session 68 Sonnet Prompt

Copy everything below the line into a new Sonnet session:

---

## Context

You're continuing from Session 67. V9 model is deployed and performing well (79.4% high-edge hit rate). Your tasks are to fix the experiment code, run February retrain, and optionally clean historical data.

**Start by reading the handoff:**
```
docs/09-handoff/2026-02-01-SESSION-68-TAKEOVER-PROMPT.md
```

## Tasks (in order)

### Task 1: Fix Experiment Line Source

The `/model-experiment` skill and `ml/experiments/quick_retrain.py` use BettingPros lines, but production uses Odds API DraftKings. This causes experiments to underestimate performance.

**Fix:**
1. Read `ml/experiments/quick_retrain.py` and find where it loads eval lines
2. Add `--line-source` argument with choices `['draftkings', 'bettingpros', 'fanduel']`, default `'draftkings'`
3. Update the SQL query to use the selected line source:
   - `draftkings` → `nba_raw.odds_api_player_points_props WHERE bookmaker = 'draftkings'`
   - `bettingpros` → `nba_raw.bettingpros_player_points_props WHERE bookmaker = 'BettingPros Consensus'`
   - `fanduel` → `nba_raw.odds_api_player_points_props WHERE bookmaker = 'fanduel'`
4. Update `.claude/skills/model-experiment.md` to document the new option

**Verify fix:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_VERIFY_LINES" \
    --train-start 2025-11-02 --train-end 2026-01-08 \
    --eval-start 2026-01-09 --eval-end 2026-01-31 \
    --line-source draftkings
```
Expected: ~79% high-edge, ~65% premium (matching backfill results).

### Task 2: February Retrain

Retrain V9 with expanded training window (includes January data):

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31 \
    --eval-start 2026-01-25 \
    --eval-end 2026-01-31 \
    --line-source draftkings
```

If results are better than current V9, deploy:
```bash
gsutil cp models/catboost_retrain_V9_FEB_RETRAIN_*.cbm \
    gs://nba-props-platform-models/catboost/v9/
./bin/deploy-service.sh prediction-worker
```

### Task 3: Historical Feature Cleanup (Optional)

If time permits, fix team_win_pct for 2024-25 season (currently 100% stuck at 0.5):

1. Run audit: `PYTHONPATH=. python bin/audit_feature_store.py --season 2024-25 --check-leakage`
2. See `docs/08-projects/current/ml-challenger-experiments/HISTORICAL-FEATURE-CLEANUP-PLAN.md` for full plan

## Key Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Experiment script (NEEDS LINE SOURCE FIX) |
| `.claude/skills/model-experiment.md` | Skill definition (UPDATE WITH NEW OPTION) |
| `predictions/worker/prediction_systems/catboost_v9.py` | V9 implementation |
| `bin/audit_feature_store.py` | Feature quality scanner |

## V9 Current Status

- System ID: `catboost_v9`
- Deployed: ✅ Yes (default)
- High-Edge Hit Rate: 79.4%
- Premium Hit Rate: 65.6%

## When Done

1. Commit all changes with descriptive messages
2. Push to origin/main
3. Write a brief handoff note if there's remaining work
