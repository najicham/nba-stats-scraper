# Session 419 Handoff — Evening Scraper, Manual Grading, Pick Analysis

**Date:** 2026-03-05 (evening) → 2026-03-06 (morning)
**Type:** Operations, infrastructure, pick analysis
**Key Insight:** Added 11:30 PM ET post-game scraper window to close the same-night scoring gap after BDL was disabled. Mar 5 graded 9-4 (69.2%). First full v415 slate (Mar 6) produced only 1 pick — may be too aggressive.

---

## What This Session Did

### 1. Mar 5 Manual Grading: 9-4 (69.2%)

Graded live via ESPN box scores since pipeline didn't have results yet (no evening scraper at the time).

| Player | Dir | Line | Actual | Result | Rescued? | Edge |
|--------|-----|------|--------|--------|----------|------|
| Devin Booker | OVER | 24.5 | 27 | **WIN** | No | 5.0 |
| Tre Johnson | OVER | 13.5 | 15 | **WIN** | Yes (HSE) | 4.8 |
| Grayson Allen | OVER | 17.5 | 21 | **WIN** | Yes (stack_2plus) | 4.4 |
| Bilal Coulibaly | OVER | 12.5 | 17 | **WIN** | Yes (HSE) | 4.1 |
| Austin Reaves | UNDER | 19.5 | 16 | **WIN** | No | 4.0 |
| Gui Santos | OVER | 12.5 | 14 | **WIN** | Yes (combo_he_ms) | 3.8 |
| Kevin Durant | UNDER | 25.5 | 23 | **WIN** | No | 3.7 |
| Cody Williams | OVER | 8.5 | 13 | **WIN** | Yes (HSE) | 3.3 |
| Jalen Duren | UNDER | 18.5 | 7 | **WIN** | No | 3.0 |
| Tyler Herro | UNDER | 21.5 | 25 | LOSS | No | 4.2 |
| Scottie Barnes | OVER | 17.5 | 16 | LOSS | Yes (stack_2plus) | 3.9 |
| Cade Cunningham | UNDER | 25.5 | 26 | LOSS | No | 3.7 |
| Nolan Traore | OVER | 11.5 | 9 | LOSS | Yes (combo_he_ms) | 3.3 |

**Rescued: 5-2 (71.4%) | Non-rescued: 4-2 (66.7%)**

### 2. Loss Analysis

| Loss | Root Cause | Actionable? |
|------|-----------|-------------|
| Tyler Herro UNDER 21.5 (scored 25) | MIA blowout WIN 126-110 — star feasted before bench. `blowout_risk_under` 2-2 (50%) at BB | Watch: signal has no proven edge |
| Scottie Barnes OVER 17.5 (scored 16) | Rescued via `signal_stack_2plus` (demoted in v415). All contextual signals, no conviction | Already fixed by v415 |
| Cade Cunningham UNDER 25.5 (scored 26) | Lost by 0.5 pts. Volatile scorer keeps shooting regardless of game state | Noise — no fix |
| Nolan Traore OVER 11.5 (scored 9) | BKN blowout LOSS vs MIA — bench player on losing team gets pulled early | Pattern: bench OVER on heavy underdog |

### 3. Evening Scraper Window (SHIPPED)

**Problem:** BDL fully disabled since Feb 11 (all scheduler jobs PAUSED). No live box scores. Games finishing ~10 PM ET weren't scored until 1-4 AM ET.

**Fix:** Added `post_game_window_1b` at 11:30 PM ET to `config/workflows.yaml`:
- Runs `nbac_schedule_api` (game status → Final) + `nbac_player_boxscore` (leaguegamelog API)
- Phase 2→3 auto-triggers via Pub/Sub
- No gamebook PDF (not available right after games)

**Post-game timeline now:**

| Window | Time (ET) | What |
|--------|-----------|------|
| post_game_window_1 | 10:00 PM | First attempt (games may be live) |
| **post_game_window_1b** | **11:30 PM** | **NEW — East Coast/Central finals** |
| post_game_window_2 | 1:00 AM | Most games complete |
| post_game_window_2b | 2:00 AM | West Coast complete |
| post_game_window_3 | 4:00 AM | Final + gamebook PDFs |

### 4. Pick Locking & Algorithm Version Drift

Mar 5 picks were generated across 3 algorithm versions due to true pick locking:
- 3 picks at `v406` (8 AM early predictions, locked)
- 9 picks at `v414` (12-2 PM afternoon, pre-v415 deploy)
- 1 pick at `v415` (5:20 PM post-deploy)

This meant `signal_stack_2plus` and `high_scoring_environment_over` were still rescuing picks despite being demoted/removed in v415. **Not a bug** — pick locking preserves picks mid-day by design.

**First full v415 slate: Mar 6** — produced only 1 pick (Jerami Grant UNDER 19.5) by morning. Picks grow through the day as prop lines arrive.

### 5. How Picks Grow Through the Day

Prop lines arrive every 2 hours from Odds API. Players without lines can't be predicted:

| Time (ET) | Players with lines | Mar 5 BB picks |
|-----------|-------------------|----------------|
| 2 AM | ~45 | — |
| 11 AM | ~68 | 3 picks |
| 2 PM | ~75 | 4 picks |
| 5 PM | ~88 | 12 picks |
| 7 PM | **134** | 13 picks |

Each line refresh triggers: Scraper → Phase 2 → Phase 4 → Phase 5 → Best Bets export. New picks appear when: (1) player gets a line, (2) line moves creating edge, (3) signal data updates.

### 6. BDL Status — Cancel Subscription

BDL is dead:
- All scheduler jobs PAUSED since Feb 11
- Last data: Feb 6
- Zero records in all BDL tables for recent dates
- Replaced by `nbac_player_boxscore` (NBA.com leaguegamelog API)

### 7. KD Team Investigation — No Bug

KD correctly listed as HOU (traded PHX→HOU July 2025). `nbac_player_movement` and `nba_players_registry` both have correct data. Initial confusion was from not querying `team_abbr` in first query.

### 8. Daily Steering Report (Mar 6 Morning)

| Metric | Value | Status |
|--------|-------|--------|
| 7d BB HR | 18-11 (62.1%) | GREEN |
| 14d BB HR | 26-15 (63.4%) | GREEN |
| 30d BB HR | 39-26 (60.0%) | GREEN |
| Market compression | 1.000 | GREEN |
| OVER 14d | 61.5% (N=26) | GREEN |
| UNDER 14d | 66.7% (N=15) | GREEN |
| Residual bias | -0.2 pts | GREEN |
| Fleet | 19/26 BLOCKED | Expected |

**Signals:** combo_3way and combo_he_ms went COLD. `blowout_risk_under` at 16.7% signal HR (N=12) — candidate for negative filter.

---

## Commits

```
bb28cb01 feat: add 11:30 PM ET post-game window for same-night box scores
```

## Files Changed

| File | Changes |
|------|---------|
| `config/workflows.yaml` | Added `post_game_window_1b` at 11:30 PM ET |

---

## Manual Action Still Required

**Self-heal needs manual redeploy** (carried from Session 416):
```bash
./bin/deploy/deploy_self_heal_function.sh
```

**Cancel BDL subscription** — zero value, all jobs paused.

---

## Priority Actions for Next Session

### P1: Monitor v415 Slate Size (Tonight, Mar 6)

First full slate under `v415_rescue_tighten`. Only 1 pick by morning — should grow to 5-10 by game time. If slate stays at 1-3 picks for multiple days:
- v415 may be too aggressive
- Consider re-enabling `high_scoring_environment_over` for rescue (went 3-0 in rescued picks Mar 5)

### P2: blowout_risk_under Evaluation

Currently 2-2 (50%) at BB level, 16.7% signal HR (N=12). At N=20+:
- HR < 50% → convert to negative filter
- HR > 50% → keep as signal

### P3: Signal Rescue Evaluation (Mar 10+)

Cumulative rescue HR with Mar 5: 8-5 (61.5%). Need N=15+ graded for decision.
- HR < 55% → tighten further
- HR > 60% → current tightening is working

### P4: Rescue Cap Review (Mar 12)

Per Session 415 plan. Evaluate if 40% cap is right.

---

## Key Context

- **Algorithm version:** `v415_rescue_tighten` now fully active
- **Market regime:** All GREEN, fully recovered from post-ASB compression
- **Autocorrelation:** After 69.2% night, next-day avg is 72.2% (r=0.43)
- **7 games tonight** (Mar 6), full schedule through next week
- **Evening scraper deployed** — first test tonight at 11:30 PM ET
