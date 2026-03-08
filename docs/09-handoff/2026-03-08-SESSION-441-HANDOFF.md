# Session 441 Handoff — Cross-Day Autopsy + Team Cap + Hot Shooting Reversion

**Date:** 2026-03-08
**Session:** 440-441 (NBA focus, continuation of 439)
**Status:** v441 DEPLOYED. 99 tests pass. 5 commits pushed.

---

## What Was Done

### 1. Committed & Deployed v439 (from Session 439)
- Star criteria fix: removed `usage >= 25%`, added `games >= 10` + `pts >= 12` guard
- Normalizer: 3 processors use shared `normalize_name_for_lookup()`
- `depleted_stars_over_obs` observation filter

### 2. P10 Prediction Sanity PROMOTED to Active (v440)
- Model-level HR = 40.9% (N=88) for `pred > 2x season_avg` on bench players (line < 18)
- Mar 7: would have blocked Konchar (2.77x avg, LOSS), partially caught 4/5 OVER losses
- 4 tests including boundary at line=18

### 3. Mar 7 Player Deep Dive (4 parallel agents, 8 players)

**BB Picks:**
| Player | Pick | Result | Root Cause |
|--------|------|--------|------------|
| Keyonte George | OVER 22.5 | 22 (-0.5) | Good pick, 4/17 FG bad variance. 68% season OVER HR. |
| SGA | UNDER 30.5 | 27 (-3.5) | Clean signal win. 62% UNDER HR at 30+ lines. Structural edge. |
| Bailey/Konchar/Horford/Traore | OVER | All LOSS | Bench/role players on depleted teams |

**Overperformers:**
- Ziaire Williams: FT outlier (8/8). Not repeatable.
- Gui Santos: Curry OUT → +19.9 min. Partially exploitable but model already partially captures.
- Jalen Johnson: Pure efficiency spike (63.2% FG). Not repeatable.
- Quentin Grimes: Embiid+George OUT → +11.5 min. Volume boost is real.

**Underperformers:**
- DiVincenzo: Usage crash (10.6% vs 15%). 58.4% season UNDER HR. Potential signal.
- Claxton: Usage crash (10.8% vs 18%). Blowout WIN paradox.

### 4. Cross-Day Autopsy Mar 1-7 (3 parallel agents)

**Daily BB Performance:**
| Date | Picks | HR | Notes |
|------|-------|----|-------|
| Mar 1 | 2 | 100% | Perfect |
| Mar 4 | 7 | 42.9% | All OVER, no UNDER balance |
| Mar 5 | 11 | 72.7% | Best day — good mix |
| Mar 7 | 6 | 16.7% | 3 UTA picks in same blowout |

**OVER: 47.4% (9/19). UNDER: 71.4% (5/7).**

**Key Discoveries:**
1. **Volume boost NOT exploitable** — profitable players blocked by zero-tolerance. Eligible players go UNDER 70% at stars_out=3.
2. **Bounce-back OVER is a MYTH** — 43.1% over rate after 0-pt games. No reversion.
3. **Hot shooting reversion is REAL at 70%+** — 59.2% UNDER HR (N=250). Below 70% = no signal.
4. **Same-team concentration is systemic risk** — 3 UTA picks on Mar 7 = correlated bet.
5. **Jabari Smith Jr is model blind spot** — predicts 10.6, actual 15.8. 39.6% UNDER HR on 106 picks.
6. **We are NOT missing predictable opportunities** — every outlier was unpickable or unpredictable.

### 5. Per-Team Cap DEPLOYED (v441)
- `MAX_PICKS_PER_TEAM = 2` — drops 3rd+ pick per team, keeps highest edge
- Prevents Mar 7-style correlated blowout exposure
- Active filter with counterfactual tracking

### 6. Hot Shooting Reversion Observation (v441)
- `hot_shooting_reversion_obs` — tracks OVER picks after 70%+ FG games
- UNDER HR = 59.2% (N=250) at model level
- Uses `prev_game_fg_pct >= 0.70 AND prev_game_minutes >= 20`
- Observation mode — accumulating BB-level data

### 7. Stale Test Fix
- `test_algorithm_version_updated` was hardcoded to 'v365'. Fixed to check prefix 'v4'.

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v441_team_cap_hot_reversion` |
| Tests | **99 pass** (93 + 6 new) |
| Active filters | 24 (was 22) |
| Observation filters | 8 (was 6) |
| Commits this session | 5 (v439, v440, test fix, v441, cleanup) |
| Builds | All SUCCESS |
| BB HR (season) | 64.1% (91-51), +31.81 units |
| Last game date (graded) | Mar 7 (1-5, -4.09 units) |

---

## What to Do Next

### Priority 1: Monitor v441 Impact (Mar 9+)
- Check `algorithm_version = v441_team_cap_hot_reversion` in exports
- Watch for team_cap filtering in logs (should be rare — most days have <3 picks/team)
- Monitor `hot_shooting_reversion_obs` firing count

### Priority 2: Continue Cross-Day Autopsy
- Extend to Jan-Feb data for more pattern discovery
- Focus on: what separates winning days from losing days?
- Investigate whether UNDER should have higher representation in picks

### Priority 3: Jabari Smith Jr Blacklist Investigation
- Model consistently underestimates by 50% (predicts 10.6, actual 15.8)
- 39.6% UNDER HR on 106 picks — actively losing money
- Check if already on blacklist. If not, investigate adding.

### Priority 4: Promote Hot Shooting Reversion
- After 2-3 weeks BB-level data, evaluate promotion from observation to active
- Need: BB-level N >= 20, HR >= 55% to promote

### Priority 5: P9 Edge Z-Score Promotion
- Still in observation, needs ~2 weeks data

### NOT Doing Yet
- Usage crash UNDER signal — promising finding from deep dive but needs more research
- Backfill/clean 397 bad nbac_player_boxscores rows
- Fix 7 scraper normalizers (lower priority)

---

## Key Learnings

1. **Per-team concentration is a real risk.** 3 UTA picks on Mar 7 = correlated bet. Max 2/team prevents this.
2. **Hot shooting mean-reverts at 70%+ ONLY.** 60-69% FG shows ZERO signal. The threshold matters.
3. **Bounce-back OVER is a myth.** 0-point games predict WORSE next-game performance (43.1% over), not better.
4. **Volume boost is real but unexploitable.** The players who benefit most are exactly the ones we can't predict (no features, no lines).
5. **UNDER selection (71.4%) dramatically outperforms OVER (47.4%)** in Mar 1-7. System should lean UNDER.
6. **Every "missed opportunity" was either unpickable or unpredictable.** The system isn't leaving money on the table.

---

## Files Changed

```
# v439 (Session 439)
ml/signals/aggregator.py — depleted_stars_over_obs, algo v439
data_processors/analytics/upcoming_player_game_context/team_context.py — star criteria fix
data_processors/raw/nbacom/nbac_player_boxscore_processor.py — shared normalizer
data_processors/raw/nbacom/nbac_play_by_play_processor.py — shared normalizer
data_processors/raw/espn/espn_boxscore_processor.py — shared normalizer
docs/09-handoff/2026-03-08-SESSION-439-HANDOFF.md

# v440 (Session 440)
ml/signals/aggregator.py — prediction_sanity active, algo v440
tests/unit/signals/test_aggregator.py — 4 P10 tests

# v441 (Session 441)
ml/signals/aggregator.py — team_cap + hot_shooting_reversion_obs, algo v441
tests/unit/signals/test_aggregator.py — 6 new tests (team cap + hot reversion)
docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md

# Test fix
tests/unit/signals/test_player_blacklist.py — algorithm version assertion
```

## Commits
```
bb9ca542 feat: Session 439 — star criteria fix + normalizer fixes + depleted roster obs
534d6298 feat: Session 440 — promote prediction_sanity filter from observation to active
16f22f80 fix: update stale algorithm version assertion (v365 → v4*)
97421b9c feat: Session 441 — per-team cap (2/team) + hot shooting reversion obs
8be2a6dd chore: remove unused team_capped list in team cap logic
```
