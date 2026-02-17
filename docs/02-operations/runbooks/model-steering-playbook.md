# Model Steering Playbook

**When to switch models, retrain, or pause — a decision guide.**

Updated: 2026-02-15 (Session 271)

---

## How the System Works Now

Signal best bets are **always produced** regardless of model health (health gate removed, Session 270). The 2-signal minimum provides baseline quality filtering. The website's blocked banner (`model-health.json`) still shows when the champion is below breakeven, but picks are still generated.

**Your job:** Run `/daily-steering` each morning. Act on the recommendation. Most days it says ALL CLEAR and you're done in 2 minutes. See `daily-checklist.md` for the step-by-step routine.

---

## How Alerts Reach You

| Alert | Channel | Frequency | Trigger |
|-------|---------|-----------|---------|
| Decay state transition | `#nba-alerts` Slack | When state changes | `decay-detection` CF (11 AM ET daily) |
| Challenger outperformance | `#nba-alerts` Slack | When 5+ pp margin, N >= 30 | Same CF |
| Cross-model crash | `#nba-alerts` Slack | When 2+ models < 40% | Same CF |
| Model blocked banner | `model-health.json` (website) | Daily | `model-health` export |
| Directional concentration | `/validate-daily` Phase 0.57 | Manual check | On-demand |

---

## Decision Matrix

### Scenario 1: Champion Enters WATCH State

**Alert:** "MODEL DECAY — WATCH" Slack message
**Meaning:** Champion 7d HR dropped below 58% for 2+ days. Still above breakeven (52.4%).

**Action:**
- [ ] Monitor for 2-3 more days — WATCH often self-corrects
- [ ] Run `/replay` to see if switching would have helped historically
- [ ] Check if the dip coincides with unusual NBA events (injuries, schedule quirks)
- [ ] **Do NOT switch models yet** — false positive rate is low but WATCH is informational

---

### Scenario 2: Champion Enters DEGRADING State

**Alert:** "MODEL DECAY — DEGRADING" Slack message
**Meaning:** Champion 7d HR dropped below 55% for 3+ days.

**Action:**
- [ ] Check challengers: Is any challenger above 56% with N >= 30?
  ```bash
  PYTHONPATH=. python ml/analysis/model_performance.py --date $(date -d '-1 day' +%Y-%m-%d)
  ```
- [ ] If yes: **Prepare to switch** — set `BEST_BETS_MODEL_ID` to challenger
  ```bash
  gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="BEST_BETS_MODEL_ID=catboost_v12"
  ```
- [ ] If no viable challenger: **Start retrain planning** (see Scenario 5)
- [ ] Run `/replay --compare` to validate the switch would have improved results

---

### Scenario 3: Champion Enters BLOCKED State

**Alert:** "MODEL DECAY — BLOCKED" Slack message
**Meaning:** Champion 7d HR dropped below 52.4% (breakeven). Losing money.

**Important:** Signal best bets are still produced (health gate removed, Session 270). The 2-signal minimum provides quality filtering, but the model driving edge calculations is below breakeven. Website shows "sitting out" via `model-health.json` → `show_blocked_banner: true`.

**Action (urgent):**
- [ ] Check challengers for a viable replacement:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT model_id, state, rolling_hr_7d, rolling_n_7d
  FROM nba_predictions.model_performance_daily
  WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  ORDER BY rolling_hr_7d DESC"
  ```
- [ ] If a challenger is HEALTHY with 56%+ HR and N >= 30: **Switch immediately**
  ```bash
  gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="BEST_BETS_MODEL_ID=<challenger_model_id>"
  ```
- [ ] If NO viable challenger: Begin retrain planning (Scenario 5)
- [ ] If BLOCKED persists 3+ days with no switch option: Consider pausing picks manually or warning users via site copy

---

### Scenario 4: Cross-Model Crash (Market Disruption)

**Alert:** "MARKET DISRUPTION" dark-red Slack message
**Meaning:** 2+ models crashed below 40% on the same day. This is the market, not the model.

**Action:**
- [ ] **Do NOT switch models** — all models affected equally
- [ ] **Pause betting for 1 day** — wait for market to normalize
- [ ] Check NBA context: trades, mass injuries, schedule quirks
- [ ] Resume normal operations next game day — crash should be transient
- [ ] If crash persists 2+ consecutive days: investigate root cause (data pipeline issue?)

---

### Scenario 5: When to Retrain

**Triggers:**
- Champion BLOCKED for 5+ consecutive days with no viable challenger
- Champion > 30 days since training (staleness)
- Monthly calendar date (retrain every 4-6 weeks recommended)

**Process:**
```bash
# 1. Train new model
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end 2026-02-15

# 2. Script outputs ALL GATES PASSED or FAILED
#    Gates: duplicate check, vegas bias, high-edge HR >= 60%, sample size, tier bias, MAE

# 3. If ALL GATES PASSED:
#    Upload to GCS, register, shadow for 2+ days

# 4. After 2+ shadow days with good results:
#    Promote (update CATBOOST_V9_MODEL_PATH env var)
```

**NEVER skip gates.** A retrain with better MAE once crashed hit rate to 51.2% due to UNDER bias.

---

### Scenario 6: Challenger Outperforms Champion

**Alert:** "Challenger outperforming by X pp" Slack message
**Meaning:** A shadow model has 7d HR > champion + 5pp with N >= 30.

**Action:**
- [ ] Verify the outperformance is sustained (not just 1-2 good days):
  ```bash
  PYTHONPATH=. python bin/compare-model-performance.py <challenger_id> --days 14
  ```
- [ ] Check if champion is decaying vs challenger genuinely better
- [ ] If challenger has been outperforming for 7+ days with N >= 50:
  ```bash
  # Switch best bets model
  gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="BEST_BETS_MODEL_ID=<challenger_id>"
  ```
- [ ] Monitor for 3 days after switch to confirm improvement

---

### Scenario 7: Recovering After a Switch

**Signal:** Champion recovers to HEALTHY (58%+ HR for 2+ consecutive days)

**Action:**
- [ ] If currently on a challenger, evaluate whether to switch back
- [ ] Run `/replay` comparing champion vs challenger over recent period
- [ ] If champion consistently outperforms challenger by 3+ pp over 7 days: switch back
  ```bash
  gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="BEST_BETS_MODEL_ID=catboost_v9"
  ```
- [ ] If performance is similar: stay on current model (avoid thrashing)

---

## Quick Reference: Key Commands

```bash
# Check current best bets model
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep BEST_BETS

# Switch best bets model
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="BEST_BETS_MODEL_ID=catboost_v12"

# Check all model states
bq query --use_legacy_sql=false "
SELECT model_id, state, rolling_hr_7d, rolling_n_7d, days_since_training
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
ORDER BY rolling_hr_7d DESC"

# Replay compare strategies
PYTHONPATH=. python ml/analysis/replay_cli.py \
  --start $(date -d '-30 days' +%Y-%m-%d) \
  --end $(date -d '-1 day' +%Y-%m-%d) \
  --models catboost_v9,catboost_v12 --compare

# Train new model
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "RETRAIN_NAME" --train-start 2025-11-02 --train-end $(date +%Y-%m-%d)

# Model registry
./bin/model-registry.sh list
./bin/model-registry.sh production
```

---

## Thresholds Reference

| Threshold | Value | Meaning |
|-----------|-------|---------|
| WATCH | 58.0% 7d HR | Elevated monitoring |
| DEGRADING | 55.0% 7d HR | Consider switching |
| BLOCKED | 52.4% 7d HR | Below breakeven, banner shown (picks still produced) |
| Challenger min | 56.0% 7d HR, N >= 30 | Minimum to consider switching to |
| Outperformance alert | 5+ pp margin, N >= 30 | Slack alert fires |
| Retrain staleness | 30+ days since training | Consider monthly retrain |

Validated across V8's 4-season history: 0.13% false positive rate (Session 265).
