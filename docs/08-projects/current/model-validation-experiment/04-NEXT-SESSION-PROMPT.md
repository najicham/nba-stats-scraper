# Next Session Prompt

Copy everything below this line and paste into a new chat:

---

Read these files first to understand context:
1. `docs/09-handoff/2026-02-14-SESSION-253-HANDOFF.md` — what was done, what's next
2. `docs/08-projects/current/model-validation-experiment/03-SUBSET-REDESIGN-PLAN.md` — subset redesign + Best Bets meta-subset + 3PT bounce signal design

## Task: Build Signal Discovery Framework + Best Bets Meta-Subset

### Background

We ran 52 model experiments across 2 seasons and found two winning configs (E: V9 MAE 33f, C: V12 MAE RSM50 no-vegas). We need a "Best Bets" meta-subset that curates 3-5 picks per day from multiple signal sources. Each pick gets a `source_tag` so we can track which signals are working. The website will display Best Bets as its single primary record instead of 25 confusing subsets.

### What to build

**1. Signal detection framework** — a reusable way to define, backtest, and tag signals that can qualify a pick for Best Bets. Each signal should:
- Have a detection function: `detect_signal(player_lookup, game_date, features, prediction) -> {qualifies: bool, confidence: float, metadata: dict}`
- Be independently backtestable on historical windows W1-W4 (Dec 8-21, Jan 5-18, Jan 19-Feb 1, Feb 1-13)
- Return a `source_tag` string and any signal-specific metadata

**2. Implement these initial signals:**

| Signal | Tag | Logic | Hypothesis |
|--------|-----|-------|------------|
| **High Edge** | `high_edge` | Primary model edge >= 5 | Core profitable signal (82% HR when model is fresh) |
| **Dual Agree** | `dual_agree` | Both Config E and C recommend same direction at edge 3+ | Cross-model validation = highest conviction |
| **3PT Bounce** | `3pt_bounce` | Player 3PT% last 3 games > 1 std below season avg, 4+ 3PA/game, model says OVER | Shooting regression to mean |
| **Minutes Surge** | `minutes_surge` | Player minutes_avg_last_3 > minutes_avg_season by 3+, model says OVER | More minutes = more points opportunity |
| **Pace Mismatch** | `pace_up` | Opponent pace top 5 in league, player's team pace bottom 15, model says OVER | Pace-up game inflates scoring |

**3. Backtest each signal** independently on W1-W4 (use `quick_retrain.py` eval data or query `prediction_accuracy` directly). For each signal report:
- Hit rate, sample size, ROI per window
- Overlap with other signals (% of picks that qualify for multiple signals)
- Whether the signal is additive (improves HR when combined with edge filter) or redundant

**4. Build the Best Bets aggregator:**
- Takes all qualifying picks from all signals for a game date
- Ranks by combined confidence (edge magnitude + number of signals firing)
- Caps at 5 picks per day
- Stores in a `best_bets_picks` table with `source_tag`, `source_models`, `confidence_rank`
- Each pick tracks which signal(s) qualified it (a pick can have multiple tags)

**5. Decide: is each signal a Phase 5 overlay or Phase 6 filter?**
- `high_edge` and `dual_agree` are Phase 5 (need model predictions)
- `3pt_bounce`, `minutes_surge`, `pace_up` could be Phase 6 (post-prediction filters using feature store data)
- Recommend the right architecture for each

### Key constraints

- The ASB retrain happens Feb 18 (train Nov 2 → Feb 13, both E and C configs). Run that first if it hasn't been done yet.
- Use `ml/experiments/quick_retrain.py` for retrains. Config E = default flags, Config C = `--feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise`
- 3PT data is in V13 features (`fg3_pct_last_3` at index 45, `fg3_pct_std_last_5` at index 49, `three_pa_avg_last_3` at index 50). Season baseline may need a separate query.
- The existing `dynamic_subset_definitions` table and `v1/best-bets/` GCS API endpoint already exist — build on them.
- Don't create new models. Signals are overlays on existing model predictions.

### Success criteria

- At least 3 signals backtested across 4 eval windows with HR and N reported
- Best Bets aggregator logic implemented and backtested (simulated picks for W2 and W4)
- Clear recommendation on which signals to ship vs which need more data
- Schema and integration plan for production deployment
