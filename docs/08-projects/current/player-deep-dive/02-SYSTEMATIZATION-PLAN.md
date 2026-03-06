# Player Deep Dive -- Systematization Plan

*Session 417, March 5 2026*

## The Critical Question

**Should we build player-specific profiles into our prediction/betting system?**

### Cross-Season Stability Analysis

Before building anything, we tested whether player-specific patterns persist across seasons (2023-24 vs 2024-25, N=193 players with 20+ games each):

| Trait | Cross-Season Correlation | Verdict |
|-------|-------------------------|---------|
| **Over/under rate** | **0.143** | NOT STABLE -- almost no persistence |
| **Avg margin vs line** | **0.171** | NOT STABLE |
| **Scoring variance (std)** | **0.642** | MODERATELY STABLE |

### Regression to the Mean

| S1 Player Type | S1 Over Rate | S2 Over Rate | Drift |
|----------------|-------------|-------------|-------|
| High OVER (55%+ S1) | 58.8% | 52.9% | -5.9pp |
| High UNDER (<45% S1) | 40.6% | 49.9% | +9.3pp |
| Neutral (45-55% S1) | 49.7% | 49.1% | -0.6pp |

**Finding: Player over/under tendencies REGRESS TO THE MEAN.** A player who was 59% OVER in 2023-24 was only 53% OVER in 2024-25. The market adjusts. This means player-specific directional signals are NOT a viable persistent edge.

---

## What Works vs What Doesn't

### Does NOT work for systematic signals:
- Player-specific over/under rates -- regress to mean (r=0.14)
- Player-specific margin vs line -- regress to mean (r=0.17)
- Per-player day-of-week patterns -- N too small per player/day combo
- Per-player matchup history -- N too small (4-9 games per opponent)

### DOES work:
- **Player scoring variance** -- stable across seasons (r=0.64). High-variance players stay high-variance.
- **Within-season rolling patterns** -- already captured by our model features (f0-f4: rolling averages, f34: pts_slope, f44: scoring_trend, f55: over_rate_last_10)
- **Line range effects** -- market systematically overprices certain players at high lines (Curry 22.2% over at 29+). This is partially captured by our edge calculation but not as a player-specific signal.
- **Bounce-back effect** -- mean reversion after extreme games. We already have `mean_reversion_under` signal, but no over-direction equivalent.

---

## Recommendation

### Tier 1: Do Now (high value, low effort)

#### A. Player Variance Classification
Store per-player scoring variance in a lookup table. Use it for:
- **Confidence calibration** -- high-variance players should get lower confidence scores
- **Ultra bets filtering** -- exclude high-variance players from ultra bets (their "sure things" are less sure)
- **Position sizing** -- informational for human bettors

Implementation: Add `player_scoring_std` to feature store or a new `player_profiles` table. Updated monthly.

#### B. Batch Deep Dive Reports
Run `player_deep_dive.py` for our top ~50 most-predicted players. Store reports in `results/player_profiles/`. Review monthly.
- Useful for human insight and debugging model performance on specific players
- NOT for automated signals (patterns don't persist)

```bash
# Run for top predicted players
for player in tyresemaxey stephencurry jalenbrunson ...; do
    python bin/analysis/player_deep_dive.py $player --output results/player_profiles/${player}.md
done
```

### Tier 2: Consider (moderate value, moderate effort)

#### C. Bounce-Back OVER Signal
Curry's data confirms strong mean reversion after bad games (+5.0 pts bounce-back). We already have `mean_reversion_under` (trend_slope>=2.0 AND avg_3g>=line+2 = 77.8% HR).

A symmetric `mean_reversion_over` signal could work:
- Trigger: Player scored <60% of their line in last game AND last 3 games trending down
- Validation: Need to test across all players, not just Curry
- Risk: Our model features (f34: pts_slope, f55: over_rate_last_10) may already capture this

#### D. Line Range Sensitivity Analysis
Some players are systematically overpriced at certain line ranges. While player-specific effects don't persist well, the LINE RANGE effect might persist better (it's a market inefficiency, not a player trait).

Test: For each line range (15-20, 20-23, 23-26, 26-29, 29+), do high-line players consistently go UNDER? If this is a market-wide pattern (not player-specific), it could be a new signal.

### Tier 3: Defer (low value or high risk)

#### E. Full Player Profile Database
Building a BigQuery `player_profiles` table with 30+ features per player:
- **Not recommended** -- cross-season r=0.14-0.17 means profiles go stale within a season
- Our model's 56-day training window already adapts to player changes
- The model IS the player profile (it learns player-specific patterns via features)

#### F. Player-Specific Model Tuning
Training separate models or hyperparameters per player:
- **Not recommended** -- N too small per player (50-200 games)
- Would overfit catastrophically
- Our model already learns player-specific patterns through features

---

## Integration with Best Bets and Ultra Bets

### Best Bets: No direct integration recommended

The deep dive analysis confirms that our existing signal/filter stack already captures the actionable patterns:
- Rolling averages (f0-f4) capture recent form
- Scoring trend slope (f34, f44) captures momentum
- Rest/fatigue features (f5, f39) capture rest effects
- Matchup features (f13, f14, f29, f30) capture opponent effects
- Mean reversion signal already exists for UNDER

Player-level quirks (Curry's Saturday scoring, away advantage) are too noisy and player-specific to systematize.

### Ultra Bets: Player variance as a filter

One concrete integration point:

**Ultra bets should prefer low-variance players.** High-variance players (like Curry, std=9.9) are inherently less predictable. A player with std=5 at the same edge/signal level is a more reliable ultra bet.

Implementation: Add a `player_variance_tier` (low/medium/high) based on rolling 30-game scoring std. Use as an ultra bet qualifier:
- Low variance (std < 6): +0.05 ultra score bonus
- High variance (std > 9): -0.05 ultra score penalty or exclude from ultra

### Deep Dive as a Debugging Tool

The strongest use case is **diagnostic, not predictive:**
- Model is 28.6% HR on Curry with catboost_v12 -- WHY? The deep dive shows Curry's extreme variance and market overpricing explain it.
- A player has been going UNDER 7 straight -- is it a real pattern or noise? Run the deep dive to check.
- Pre-season setup: run deep dives on key players to understand their profiles before the season starts.

---

## Revised Summary (Post-Agent Research)

Initial analysis suggested player data was mostly diagnostic. Further research revealed **structural scoring distribution traits interact with our model predictions in highly exploitable ways.** See `03-SIGNAL-FINDINGS.md` for full details.

| Signal | HR | N | Effort | Decision |
|--------|-----|------|--------|----------|
| `bounce_back_over` (AWAY only) | 56-62% | 379-700 | LOW | **IMPLEMENT** |
| `under_after_streak` (neg filter) | 44.7% anti | 515 | LOW | **IMPLEMENT** |
| `over_streak_reversion_under` | ~56% | 366 | LOW | **IMPLEMENT** |
| `bad_shooting_bounce_over` | 54.5% | 220 | MEDIUM | **IMPLEMENT** |
| Tier-based direction pref | 59-61% | 1K-4K | MEDIUM | **IMPLEMENT** |
| Scoring shape modifier | varies | 20K+ | MEDIUM | VALIDATE FIRST |
| Volatile + high edge boost | 61.9% | 3K | LOW | VALIDATE FIRST |
| Player variance tier | 56.6% top | 290 | LOW | **IMPLEMENT** |
| Batch deep dives (all 262 players) | diagnostic | — | LOW | **DO NOW** |

**Bottom line:** Player-specific over/under rates regress to the mean (r=0.14), but structural scoring traits (variance, skewness, bounce-back coefficients, streak behavior) interact with our model in exploitable ways. The most actionable finding: our model has a blind spot on streak players — it over-predicts UNDER after down-streaks (44.7% HR on N=515), and the bounce-back is primarily an AWAY phenomenon (56.2% over, N=379).
