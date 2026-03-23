# New Chat Handoff — 2026-03-23 (Post Session 483)

**Date:** 2026-03-23 (Monday)
**Latest commit:** `0ae9c62e` — MLB market regime awareness

---

## System State: HEALTHY

### NBA Fleet (3 enabled models — above safety floor)
| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0228` | HEALTHY | NEW (just trained) | Jan 3–Feb 28, 61.5% gate |
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 60.0% (N=20) | Primary |
| `lgbm_v12_noveg_train1215_0214` | HEALTHY | 60.0% (N=15) | avg_edge 1.34 — watch |

**Today (Mar 23): 10 games — first real volume slate this week.** Expect 2-4 picks.

### Key Active Constraints
- `weekly-retrain` CF: **KEEP PAUSED** (retrain gate logic is backwards — see session learnings)
- OVER floor: **5.0** (auto-rises to 6.0 when vegas_mae < 4.5 — new Session 483 gate)
- `catboost_v9_low_vegas`: **DO NOT RE-ENABLE**
- OVER floor: do not lower to 4.5

---

## What Was Done This Session (483)

### 1. 9-Agent Review (5 Opus + 4 Sonnet)
Full system analysis after the March 8 disaster (4-12, 25% HR).
Root cause: system had built every market-awareness guard but labeled them all "observation."

### 2. 7 NBA Guardrails Activated
All in `ml/signals/aggregator.py`, `regime_context.py`, `signal_health.py`:

| Change | Effect |
|--------|--------|
| `mae_gap_obs` → active when gap > 0.5 | Blocks OVER when model losing to Vegas |
| `regime_rescue_blocked` → active | Blocks OVER rescue in cautious/TIGHT regimes |
| `over_edge_floor_delta` → applied | Floor actually rises 5.0→6.0 when triggered |
| `regime_context.py`: queries `vegas_mae_7d` | When < 4.5: raises floor +1.0, disables rescue |
| OVER edge 7+ bypasses `sc3_over_block` | 78.8% HR — mirrors UNDER bypass |
| `home_under` → BASE_SIGNALS | 48% 30d HR, removed from scoring + rescue |
| `signal_health.py` HOT gate | Requires picks_7d >= 5 AND hr_30d >= 50% |

### 3. New LGBM Model Trained
`lgbm_v12_noveg_train0103_0228` — Jan 3–Feb 28, all governance gates passed (61.5% HR).
Fleet back at 3 models (above MIN_ENABLED_MODELS=3 floor). Live in production.

### 4. MLB Guardrails Ported (Opus agent audit)
`ml/signals/mlb/best_bets_exporter.py`:
- `_get_regime_context()` wired in — queries `mlb_predictions.league_macro_daily`
- TIGHT gate (vegas_mae_7d < 1.7 K): raises floor +0.5 K, disables rescue
- MAE gap gate (gap > 0.3 K): blocks all OVER picks
- `home_pitcher_over` → BASE_SIGNAL_TAGS (fires on 50% of OVER picks — inflated SC)

### 5. Playoff Shadow Mode
`backfill_jobs/publishing/daily_export.py`: `NBA_PLAYOFF_SHADOW_START` env var.
When set: picks still in BQ but NOT exported to GCS API.
Two Cloud Scheduler reminders created:
- `nba-playoffs-shadow-activate`: Apr 14, 9 AM ET
- `nba-playoffs-shadow-review`: May 1, 9 AM ET

### 6. Other Fixes
- `quick_retrain.py`: eval query auto-detects system_id (was hardcoded catboost_v9)
- MLB grading: Slack alert when HTTP returns non-200
- MLB pitcher-props-validator: schedule fixed `4-10` → `3-10` (Opening Day Mar 27)
- 6 BLOCKED graveyard models hard-deactivated
- Market monitoring added to `signal_decay_monitor.py` (TIGHT + BB HR alerts)

---

## Tomorrow's Priorities

### Morning Checks (START keyword)
```bash
/daily-steering          # Model health, signal health, macro trends
/validate-daily          # Full pipeline validation
./bin/check-deployment-drift.sh --verbose
/best-bets-config        # BB thresholds, models, signals
```

### Mar 23 Specific
- 10-game slate — first real volume test for new fleet + all 7 guardrails
- Watch: **pick count** (expect 2-4), **vegas_mae** (keep above 4.5)
- New model `lgbm_v12_noveg_train0103_0228` in its first live game — watch for anomalies

### lgbm_v12_noveg_train1215_0214 Watch
avg_edge = 1.34 (collapse threshold ~1.1). Decision point: **Mar 25 (12-game slate)**.
Deactivate if HR < 52.4% after Mar 25. Safe to deactivate — 2 other models remain.

---

## MLB Opening Day Checklist (Mar 27 in 4 days)

### Mar 24 (tomorrow) — Critical
```bash
./bin/mlb-season-resume.sh   # Reminder fires 8 AM ET — DO THIS FIRST
```
This unpauses all 24 MLB scheduler jobs and starts the 2026 season data flow.

**Also on Mar 24:** Verify MLB orchestrator payload:
```bash
grep -n "write_to_bigquery\|predict.batch" \
    orchestration/cloud_functions/mlb_phase4_to_phase5/main.py | head -10
```
If calling `/predict-batch` without `"write_to_bigquery": true`, Opening Day predictions
get computed but never saved to BigQuery. Fix if needed.

### Mar 27 Opening Day Verification
```sql
-- Are predictions generating?
SELECT game_date, COUNT(*) as n FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-03-27' GROUP BY 1;
-- Expected: ~15-20 predictions

-- Are best bets publishing?
SELECT game_date, COUNT(*) as picks FROM mlb_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-27' GROUP BY 1;
-- Expected: 3-5 picks
```

Note: MLB `_get_regime_context()` will return default values for first 1-2 days
(no `league_macro_daily` data yet) — picks will be generated normally. Regime awareness
kicks in once grading data populates the table.

---

## BB Performance Context

- **30d HR: 50.0%** (N=70) — March 8 dominated this (4-12)
- **Ex-March-8: 57.4%** (N=54) — the real underlying performance
- **March 8 washes out: ~April 7** — 30d HR jumps automatically
- **Post-fleet-reset (Mar 11+): 66.7%** (N=6) — small but clean

---

## Remaining Pending Items

- [ ] Verify MLB orchestrator `write_to_bigquery: true` (Mar 24)
- [ ] Build `ml/signals/mlb/signal_health.py` — MLB signal health computation (medium, after Opening Day)
- [ ] Fix `deployment/scheduler/mlb/validator-schedules.yaml` multi-doc YAML (pre-commit failing)
- [ ] Single-model dominance alert (>40% picks from one model) — design done, not coded
- [ ] Playoffs: activate shadow mode on Apr 14 (Scheduler reminder fires 9 AM ET)
- [ ] Playoffs: review shadow HR on May 1 (Scheduler reminder fires 9 AM ET)

---

## Key New Gotchas (Session 483)

**Observation filters = silent debt.** Every `# Observation — does NOT block` comment is a
time bomb. Run: `grep -n "Observation.*NOT block\|observation only" ml/signals/aggregator.py`
periodically and promote any with N > 30 BB-level picks.

**`quick_retrain.py` with production lines.** The default eval query (`--use-production-lines`)
auto-detects the best system_id now. Previously was hardcoded to `catboost_v9`.
If catboost_v9 is absent, it still falls back to `--no-production-lines` automatically.

**MLB `_get_regime_context()` returns defaults on Day 1.** Non-fatal — pipeline continues.
After first graded games appear in `mlb_predictions.league_macro_daily`, regime awareness
starts working. Monitor the first week: if picks look like they should be blocked but aren't,
check if league_macro_daily is being populated by the post-grading export.

**Playoff shadow mode activation.** On April 14, the Scheduler sends a Slack reminder.
Command to activate:
```bash
gcloud functions deploy phase6-export \
  --update-env-vars NBA_PLAYOFF_SHADOW_START=2026-04-14 \
  --region=us-west2 --project=nba-props-platform
```
To re-enable after playoffs:
```bash
gcloud functions deploy phase6-export \
  --remove-env-vars NBA_PLAYOFF_SHADOW_START \
  --region=us-west2 --project=nba-props-platform
```

---

## Session 483 Commits (7 total)
```
0ae9c62e feat: MLB market regime awareness — port 3 NBA Session 483 guardrails
26a86d45 feat: NBA playoff shadow mode
eecf07e9 fix: quick_retrain eval auto-detects system_id
6233d57c docs: Session 483 final state
df8698a2 docs+fix: Session 483 follow-through
2d11ac60 fix: activate 7 market-awareness guardrails (9-agent review)
```
