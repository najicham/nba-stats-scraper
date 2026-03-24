# Session 485 Handoff — 2026-03-23

**Latest commit:** `fb38a1c2` — fix: correct stale OVER edge floor log message
**Branch:** main (auto-deployed)

---

## System State: HEALTHY

### NBA Fleet (4 enabled models — upgraded from 3)
| Model | Framework | Train Window | State | Eval HR |
|-------|-----------|-------------|-------|---------|
| `catboost_v12_noveg_train0103_0228` | CatBoost | Jan 3–Feb 28 | NEW | 75.0% (N=48) ✓ |
| `lgbm_v12_noveg_train0103_0227` | LGBM | Jan 3–Feb 27 | HEALTHY 61.5% | — |
| `lgbm_v12_noveg_train0103_0228` | LGBM | Jan 3–Feb 28 | NEW | 61.5% (N=234) |
| `lgbm_v12_noveg_train1215_0214` | LGBM | Dec 15–Feb 14 | WATCH 57.1% | — |

Worker cache refreshed. CatBoost model will generate first live predictions tomorrow (Mar 24).

### Today's Picks (Mar 23 — 10 games)
**0 best bets.** System working correctly. Root cause: avg_abs_diff 1.29-1.47 across all 3 LGBMs → only 25 edge5+ candidates vs ~200/day needed.

---

## What Was Done This Session (485)

### 1. 12-Agent Plan Review
16 agents total (12 review + 4 drill-down) analyzed the proposed session plan. Key reversals:

**Signal graduation proposal KILLED:**
- `projection_consensus_over` headline metric (64.7% HR, N=34) was **prediction-level, not BB-level**
- Actual BB-level HR: **12.5% (1-8)** — catastrophic
- Zero picks are currently blocked by the real_sc gate that have this signal; the binding constraint is over_edge_floor
- Unanimous: wait until true BB-level N≥30 at HR≥60% (6-8 more weeks at current rate)

**CF gate fix deferred:**
- The "backwards gate" is a scheduler pause, not code — no code to invert
- Fix requires ~30-50 lines of new `cap_to_last_loose_market_date()` logic
- Do after Opening Day (Mar 28-29). Manual `retrain.sh --train-end 2026-02-28` remains the workaround.

### 2. Pick Drought Deep-Dive (4 agents)
**Root cause quantified:**
- **Nov 2025:** avg_abs_diff 4.29, edge5+ 27% of predictions (~200/day)
- **Jan 2026:** avg_abs_diff 2.73, edge5+ 15%
- **Mar 2026:** avg_abs_diff 1.26-1.5, edge5+ **2.1%** (~25/day)

The LGBM fleet is structurally lower-edge than the old CatBoost fleet. The 78% collapse in edge5+ candidates is the primary cause of 0-1 picks/day. The market tightening (Mar 7-13, MAE 4.1-4.5) compounded an already-compressed situation but MAE has recovered to 5.23 (NORMAL). The LGBMs haven't recovered edge because the distribution mismatch between their training period and current market is persistent.

**Signal gate compounding (secondary):**
On Mar 23, 3 edge5+ OVER picks existed (Brandon Ingram 6.3, Jaylen Wells 5.6, Naji Marshall 5.4) but all were blocked by `sc3_over_block` / `starter_over_sc_floor` (real_sc=0). The HOT shadow signals (projection_consensus_over, usage_surge_over, sharp_book_lean_over) were all firing on them but contribute zero to real_sc. HSE rescue didn't fire for these players.

### 3. CatBoost Retrain — `catboost_v12_noveg_train0103_0228`
**All governance gates passed:**
- HR edge 3+: **75.0% (N=48)**
- Vegas bias: **+0.47** (within ±1.5)
- Directional balance: OVER 74.1%, UNDER 76.2%

Hypothesis: CatBoost historically produces higher avg_abs_diff than LGBM on same data. If confirmed tomorrow, this directly addresses the pick drought by adding more edge5+ candidates to the pool.

Worker cache refreshed. Model live as of tonight.

### 4. Log message fix
`ml/signals/aggregator.py` line 1405: stale "4.0" replaced with "5.0 base, regime-adaptive". Floor was raised in Session 468 but log was never updated.

---

## Tomorrow's Critical Action (Mar 24)

```bash
./bin/mlb-season-resume.sh --dry-run   # Preview (all 35 jobs already enabled)
./bin/mlb-season-resume.sh              # Execute — verification + clean audit trail
```

All 35 MLB scheduler jobs are already ENABLED (verified tonight). The script is a no-op but provides clean audit trail before Opening Day.

---

## Opening Day Verification (Mar 27)

### Evening after predictions (6-8 PM ET):
```sql
SELECT game_date, COUNT(*) as n FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 predictions

SELECT game_date, COUNT(*) as picks FROM mlb_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 3-5 picks
```

### Morning after (Mar 28):
```sql
SELECT game_date, COUNT(*) as graded FROM mlb_predictions.prediction_accuracy
WHERE game_date = '2026-03-27' GROUP BY 1;
-- Expected: 15-20 graded
```

---

## Key Active Constraints

- `weekly-retrain` CF: **KEEP PAUSED** (scheduler paused, not code — fix Mar 28-29)
- OVER floor: **5.0** (auto-rises to 6.0 when vegas_mae < 4.5)
- CatBoost `train0118_0315` variants: **KEEP DISABLED** — trained through TIGHT market, avg_abs_diff 0.88-1.12 when last active, N=7-8 not statistically meaningful
- `projection_consensus_over`: **DO NOT GRADUATE** — BB-level HR only 12.5% (1-8), needs 6-8 more weeks

---

## Pending Items

- [ ] MLB season resume verification → **Tomorrow Mar 24**
- [ ] Monitor `catboost_v12_noveg_train0103_0228` avg_abs_diff → **Mar 24 (first live day)**
- [ ] `lgbm_v12_noveg_train1215_0214` WATCH → let decay CF handle **Mar 25**
- [ ] Fix `weekly-retrain` CF gate (add `cap_to_last_loose_market_date()`) → **Mar 28-29**
- [ ] MLB Opening Day verification → **Mar 27 evening + Mar 28 morning**
- [ ] MLB `mlb_league_macro.py` manual backfill after first games grade → **Mar 28**
- [ ] Playoffs: activate shadow mode → **Apr 14**
- [ ] `usage_surge_over` graduation watch — currently N=18 at 72.2% HR 30d; check again at N=30

---

## New Gotchas (Session 485)

**Projection-level vs BB-level HR is not the same metric.** `signal_health_daily` counts all predictions where a signal fired, regardless of BB pipeline filtering. A signal can show 64% HR in that table while having 12% actual BB-level HR. Always verify against `signal_best_bets_picks` before graduation decisions.

**LGBM fleet structurally generates lower avg_abs_diff than CatBoost.** Jan 2026 had 2.73 avg_abs_diff (mixed CatBoost/LGBM fleet). Current all-LGBM fleet: 1.3-1.5. The CatBoost retrain tonight tests whether the architecture difference is the missing piece.

**The `weekly-retrain` gate is not code.** It is a manually paused scheduler (`weekly-retrain-trigger`, paused 2026-03-21T02:25:54Z). The fix requires adding `cap_to_last_loose_market_date()` to `orchestration/cloud_functions/weekly_retrain/main.py` before re-enabling. Do not re-enable without this fix — a March 30 retrain would sweep in the TIGHT period (Mar 11-14) and produce edge-collapsed models.

**`retrain.sh --all` requires `python` in PATH.** Script uses bare `python` command. Use `PYTHONPATH=. .venv/bin/python3 ml/experiments/quick_retrain.py` directly as the workaround.

---

## Session 485 Commits (2 total)
```
fb38a1c2 fix: correct stale OVER edge floor log message (4.0 → 5.0 base, regime-adaptive)
(catboost_v12_noveg_train0103_0228 registered directly in BQ — no code commit)
```
