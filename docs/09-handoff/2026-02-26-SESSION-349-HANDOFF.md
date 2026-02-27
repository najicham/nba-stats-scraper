# Session 349 Handoff — Trends Page Fix, blowout_recovery Disabled, Scheduler Gap

**Date:** 2026-02-26
**Status:** DEPLOYED. Three changes shipped.

---

## What Changed

### 1. Trends Page Stale Data Fix (Scheduler Gap)

**Root Cause:** The `trends-tonight` export type (which generates `v1/trends/tonight.json` for the Trends page on playerprops.io) was only triggered by the Phase 5→6 orchestrator — NOT by any Cloud Scheduler job. The `phase6-hourly-trends` scheduler sent `["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays"]` but omitted `"trends-tonight"`.

When Phase 5→6 didn't fire (pipeline timing issue), the Trends page went stale — last update was Feb 25 at 03:20 UTC.

**Fixes:**
1. **Immediate:** Manually published Pub/Sub message to trigger `trends-tonight` export for Feb 26. Trends page updated at 23:37 UTC with 10 games, 30 trends, 10 matchups.
2. **Permanent:** Updated `phase6-hourly-trends` Cloud Scheduler to include `"trends-tonight"` in export_types. Now runs hourly 6 AM - 11 PM ET.

**No code change required** — this was a Cloud Scheduler configuration fix via `gcloud scheduler jobs update`.

### 2. blowout_recovery Signal Disabled

**Commit:** `ae6d8cdf` — `feat: disable blowout_recovery signal — 50% HR, harmful in Feb`

**Performance (best bets picks):**
- Overall: 7-7 (50% HR) — at breakeven, no value
- January: 6-10 (60%) — marginal
- February: 1-4 (25%) — actively harmful
- All picks were OVER direction
- Notable disasters: McDaniels OVER 13.5 → 2 pts, Oubre OVER 8.9 → 0 pts

**Files changed:**
| File | Change |
|------|--------|
| `ml/signals/signal_health.py` | Removed from `ACTIVE_SIGNALS` (13→12 active) |
| `ml/signals/registry.py` | Commented out `BlowoutRecoverySignal()` registration |
| `ml/signals/combo_registry.py` | Status → DISABLED, score_weight → 0.0 |
| `ml/signals/pick_angle_builder.py` | Commented out blowout_recovery angle |
| `CLAUDE.md` | Updated signal table + count |

**Effect:** Signal no longer fires. Historical `blowout_recovery` tags in `pick_signal_tags` are treated as ghost signals (filtered by `ACTIVE_SIGNALS` set at query time).

### 3. Pre-existing Test Fixes (Session 348 Signal-Density Filter)

**File:** `tests/unit/signals/test_player_blacklist.py`

Three test classes used base-only signals (model_health + high_edge) in their fixtures. Session 348's signal-density filter correctly blocks base-only picks, causing these tests to fail. Fixed by adding `rest_advantage_2d` as a third signal to each fixture. Also updated algorithm version assertion from `v330` to `v348`.

---

## Findings (Not Requiring Code Changes)

### Feb 26 Best Bets — Ungraded

5 picks exported BEFORE signal-density filter deployed (natural experiment):
- Kawhi Leonard UNDER 29.5 (edge -7.7) — ULTRA
- Joel Embiid UNDER 27.5 (edge -6.7) — ULTRA
- Luka Doncic UNDER 30.5 (edge -5.9) — ULTRA
- Anthony Edwards UNDER 28.5 (edge -5.5) — ULTRA
- Jalen Green UNDER 20.5 (edge -5.1)

All base-only signals, all Stars/Starters UNDER — exactly the profile the new filter blocks. Games hadn't started at session time. **Grade these in Session 350.**

### Shadow Model Coverage Gap

| Model | Feb 26 Predictions | Expected Feb 27 |
|-------|--------------------|-----------------|
| `train0105_0215` (new, Session 348) | **0** (registered too late) | ~117 |
| `train1225_0209` shadows (4 models) | 6 each (late batch) | ~117 |
| Active/production models | 117 each | ~117 |

The new `train0105_0215` model IS properly registered (enabled=true, GCS exists, validated). It simply missed the Feb 26 prediction cycle. Full coverage expected Feb 27.

### tonight/all-players.json Shows 0 Predictions Pre-Game

The `live-export-evening` scheduler runs every 3 minutes from 4-11 PM ET. It queries for live game data and overwrites `tonight/all-players.json`. Pre-game (all games status=1), it writes 0 predictions with the game list. This is expected — the live exporter takes over from the pre-game snapshot. Predictions populate once games start.

### Phase 6 Foreign Team Code Noise

Phase 6 export logs show "Unknown team codes" for non-NBA teams (GUA, SEM, HAP, MEL, STR, STP, WLD, VIN, AUS). These are international/exhibition games leaking into the schedule. Not causing failures but cluttering logs. Low priority cleanup.

---

## Deployment Status

Auto-deploy triggered for 3 services:
- `deploy-phase6-export`: signal changes
- `deploy-live-export`: signal changes
- `deploy-post-grading-export`: signal changes

Cloud Scheduler updated:
- `phase6-hourly-trends`: Added `trends-tonight` to export_types

---

## Current Signal System (12 Active)

| Signal | Direction | HR | Status |
|--------|-----------|-----|--------|
| `model_health` | BOTH | 52.6% | PRODUCTION |
| `high_edge` | BOTH | 66.7% | PRODUCTION |
| `edge_spread_optimal` | BOTH | 67.2% | PRODUCTION |
| `combo_he_ms` | OVER | 94.9% | PRODUCTION |
| `combo_3way` | OVER | 95.5% | PRODUCTION |
| `bench_under` | UNDER | 76.9% | PRODUCTION |
| `3pt_bounce` | OVER | 74.9% | CONDITIONAL |
| `b2b_fatigue_under` | UNDER | 85.7% | CONDITIONAL |
| `rest_advantage_2d` | BOTH | 64.8% | CONDITIONAL |
| `prop_line_drop_over` | OVER | 71.6% | PRODUCTION |
| `book_disagreement` | BOTH | 93.0% | WATCH |
| `ft_rate_bench_over` | OVER | 72.5% | WATCH |

**Removed this session:** `blowout_recovery` (50% HR, harmful)

---

## Known Issues

### Model Registry Duplicate Families
Validator reports 2 duplicate enabled families:
- `v12_noveg_q55_tw`: both `train1225_0209` (older) and `train0105_0215` (newer)
- `v9_low_vegas`: both `train0106_0205` (active) and `train1225_0209` (shadow)

These are intentional — running older alongside newer for comparison. Disable older once newer has 3+ days of graded data.

### Feb 25 Production Model Performance
- V12: 45.2% HR (19/42) — poor
- V9: 68.4% HR (13/19) — solid

V12 continues to underperform at 26+ days stale. The fresh `train0105_0215` shadow is the path to recovery.

---

## Next Session Priorities

### Priority 0: Grade Feb 26 Best Bets
- 5 picks from before signal-density filter — natural experiment
- If all 5 lose, confirms the filter is blocking the right picks
- Query: `SELECT * FROM signal_best_bets_picks WHERE game_date = '2026-02-26'`

### Priority 1: Verify Feb 27 Shadow Model Coverage
- Expect ~117 predictions per shadow model (including new `train0105_0215`)
- If still missing, investigate prediction worker model loading

### Priority 2: Check Signal-Density Filter Impact (Feb 27)
- First day with filter active. How many picks survive?
- If zero picks on some days, consider lowering edge floor to 4.5 for signal-rich (4+) picks

### Priority 3: Grade Shadow Models (Mar 1-3)
- Need 3+ days of graded predictions for meaningful evaluation
- Focus on `train0105_0215` (68% HR in backtest, best directional balance)
- Compare to older `train1225_0209` shadows

### Priority 4: Disable Older q55_tw Shadow
- Once `train0105_0215` has 3 days of data, disable `train1225_0209`
- Also consider disabling `v9_low_vegas_train1225_0209` if active `train0106_0205` performs similarly

### Priority 5: Investigate Foreign Team Codes in Phase 6 Logs
- Low priority but noisy: GUA, SEM, HAP, MEL, etc.
- Likely schedule scraper pulling international games
- Could filter at scraper or processing level

---

## Key Files

| File | Change |
|------|--------|
| `ml/signals/signal_health.py` | Removed blowout_recovery from ACTIVE_SIGNALS |
| `ml/signals/registry.py` | Disabled BlowoutRecoverySignal registration |
| `ml/signals/combo_registry.py` | Status DISABLED, weight 0.0 |
| `ml/signals/pick_angle_builder.py` | Removed blowout_recovery angle |
| `CLAUDE.md` | Updated signal count + blowout_recovery status |
| `tests/unit/signals/test_player_blacklist.py` | Fixed signal-density filter test failures |
