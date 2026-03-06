# Session 420 Handoff — HSE Rescue Restore, Signal Tuning

**Date:** 2026-03-06
**Type:** Signal tuning, infrastructure verification
**Key Change:** Restored `high_scoring_environment_over` to rescue tags after v415 removal killed OVER pipeline (0 OVER picks at edge 5+ on Mar 6).

---

## What This Session Did

### 1. Re-enabled HSE Rescue (Primary Fix)

**Problem:** Session 415 removed `high_scoring_environment_over` from rescue tags to "tighten" rescue. Result: Mar 6 morning produced only 1 pick (Jerami Grant UNDER 19.5). Zero OVER picks at edge 5+.

**Data:** HSE rescue was 71.4% HR (5-7) overall, 3-0 on Mar 5 (Tre Johnson, Bilal Coulibaly, Cody Williams — all won).

**Fix:** Added `high_scoring_environment_over` back to `rescue_tags` in `ml/signals/aggregator.py`. 40% rescue cap still enforced.

**Algorithm version:** `v420_hse_rescue_restore`

### 2. Verified line_jumped_under Observation Status

Confirmed the Session 417 demotion is working correctly — `continue` is commented out (line 506). The Mar 1-5 counterfactual data showing it "blocking" was from `_record_filtered` observation logs (`line_jumped_under_obs`), not actual blocks. No action needed.

### 3. Infrastructure Verification

- **Self-heal CF:** Already deployed and ACTIVE with scheduler (12:45 PM ET daily). No action needed.
- **Evening scraper:** `post_game_window_1b` at 23:30 ET in `config/workflows.yaml`. `execute-workflows` scheduler fires at :05 hourly — covers the tolerance window. First test tonight.

### 4. blowout_risk_under Status

N=7, 42.9% HR at signal level. Too small for action. Wait for N=20+.

### 5. Test Fix

Updated `test_aggregator.py` expected filter keys to include `under_after_streak` (added in Session 418 but test wasn't updated). All 63 tests pass.

---

## Key Data Findings (Session 419 Analysis)

| Metric | Value | Implication |
|--------|-------|-------------|
| Mar 6 picks (morning) | 1 (Jerami Grant UNDER) | v415 too aggressive |
| OVER edge 5+ today | 0 of 1,326 predictions | OVER pipeline dead |
| `over_edge_floor` counterfactual | 87.5% HR (7-1, since Mar 1) | Blocking winners |
| HSE rescue (removed v415) | 71.4% HR (5-7), 3-0 Mar 5 | Was performing well |
| `line_jumped_under` obs | 100% HR (5-5) blocked winners | Demotion correct |
| BB HR 7d/14d/30d | 62.1% / 63.4% / 60.0% | All GREEN |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Restored HSE to rescue_tags, bumped version to v420 |
| `tests/unit/signals/test_aggregator.py` | Added `under_after_streak` to expected filter keys |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Updated rescue tags list |

---

## What We Did NOT Do (And Why)

- **Did NOT lower OVER edge floor from 5.0** — over_edge_floor counterfactual is 87.5% HR but N=8. Season-wide edge 3-5 OVER = 52.2%. Need more data.
- **Did NOT re-enable `signal_stack_2plus` for rescue** — 60% HR at N=5, above breakeven but not convincing.
- **Did NOT convert `blowout_risk_under` to negative filter** — N=7 at signal level, need N=20+.
- **Did NOT touch rescue cap (40%)** — review scheduled Mar 12.

---

## Next Session Priorities

1. **Push to main → auto-deploy** — v420 changes need to be deployed for tonight's predictions
2. **Re-run prediction coordinator** for Mar 6 after deploy to regenerate picks (should see more than 1)
3. **Monitor Mar 6 evening results** — first slate with HSE rescue restored + evening scraper
4. **Rescue cap review (Mar 12)** — if overall HR < 55% → tighten, > 60% → loosen
5. **blowout_risk_under check** — wait for N=20+
6. **under_star_away review (Mar 19)** — counterfactual HR since demotion to obs
