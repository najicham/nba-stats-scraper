# Pushback Prompt: Response to B+ Review

Paste everything below the line into the same chat.

---

Good review. I want to push back on a few points and get your response.

## 1. Small Sample Sizes — You're Right, But What's the Alternative?

You flagged that nearly every decision is built on 12-50 pick samples. Fair. But here's the practical reality:

- We get ~5 best bets per game day, ~3-4 game days per week. That's 15-20 picks/week at the edge 3+ threshold.
- To reach your suggested 385 picks for 95% CI ±5%, we'd need **19-25 weeks of data** — nearly 5 months.
- The NBA season is ~6 months. By the time we have statistically valid sample sizes, the season is over and the data distribution has shifted anyway (trade deadline, All-Star break, playoff rotations).

So the question isn't "do we have enough data to be statistically confident?" (we don't, and we won't). The question is: **given that we'll always be working with small samples in a non-stationary environment, are our decisions directionally correct and our fail-safes adequate?**

The V12 confidence 0.87 filter is a good example. Yes, 12 picks is small. But 41.7% HR at -110 odds loses money by definition. Even if the true rate is 55% (upper end of a generous CI), we're barely breaking even on that tier while the 0.90+ tier is at 60.5% on 38 picks. The downside of filtering is losing ~3 picks per game day from a tier that's at best marginal. The downside of NOT filtering is including picks that are likely negative EV. The asymmetry favors filtering.

**Do you disagree with this framing? Or is your concern more about the combo registry classifications (where look-ahead bias is a real issue) than the confidence floor (where the decision has clear directional logic)?**

## 2. Replay Overfitting — Agreed, But V8 Replay Is Already Planned

You suggested running the replay across V8's 4 years of data. We agree — that's literally Priority 3 in our next steps ("Run V8 multi-season replay to calibrate thresholds"). The Session 261 design doc calls for this explicitly.

But I want to challenge your characterization that the Threshold strategy's advantage is "tautological." You said:

> "You block when HR drops below breakeven, which by definition improves ROI. The interesting question is whether the WATCH and DEGRADING states add value."

The WATCH and DEGRADING states ARE the value. The 52.4% BLOCK is the last resort. The system's purpose is:

1. **WATCH (58%):** Alert the operator 4-5 days before the model becomes unprofitable. On the V9 decay, WATCH fired Jan 28 — 5 days before the Feb 2 crash. That's the window to investigate, consider switching, or reduce exposure.
2. **DEGRADING (55%):** Trigger automated model switching. If a challenger is above breakeven, switch to it.
3. **BLOCK (52.4%):** If no model is above breakeven, stop betting entirely.

The ROI improvement isn't just from blocking — it's from the graduated response. If we only had BLOCK at 52.4%, we'd lose 5 more days of bad bets before triggering. WATCH and DEGRADING gave us lead time on the one real test we have.

**Your point about needing V8 multi-season validation is correct though. If WATCH/DEGRADING produce excessive false positives across 4 years of V8 data (where the model was healthy), that would invalidate the thresholds. We'll run this.**

## 3. Feedback Loop Risk — I Think You're Overweighting a Theoretical Concern

You described a feedback loop:
> "Signal hit rate depends on whether the underlying model is accurate → Model accuracy determines which picks get selected → Selected picks determine future signal hit rates"

In theory, yes. In practice, the Feb 2 data shows the opposite happened:
- Model-dependent signals (high_edge, edge_spread) correctly went COLD during model decay
- Behavioral signals (minutes_surge) stayed HOT and went 3/3

This is exactly the behavior we want — the system correctly differentiated between model-dependent and model-independent signals during the one real decay episode we've observed.

Your concern that behavioral signals "could get dragged down by the model's overall poor performance on the same picks" requires a specific mechanism: the model's bad predictions would need to correlate with behavioral signal triggers in a way that makes behavioral signals look bad. But behavioral signals are computed from player behavior patterns (minutes played, shooting trends), not from model predictions. They trigger independently.

That said, your suggestion to "separate behavioral signal health tracking from model-dependent signal health tracking" is operationally easy and costs nothing. We could add an `is_model_dependent` flag to the health computation (we already have this field in signal_health_daily). **This is a good suggestion even if the theoretical risk is low.**

## 4. Kelly Criterion — Interesting But Premature

You suggested variable bet sizing via Kelly criterion. This is a good idea in theory, but it requires something we don't have: **calibrated probability estimates.**

Kelly sizing needs P(win) for each bet. Our model produces point predictions (predicted_points), not probabilities. The "edge" is |predicted - line|, which correlates with win probability but isn't a calibrated probability. A pick with edge 8.5 isn't twice as likely to win as edge 4.25 — the relationship between edge and win rate isn't linear (and may not even be monotonic, as we saw with V9's highest-confidence picks inverting).

To use Kelly properly, we'd need to:
1. Calibrate edge → win probability (requires hundreds of graded picks per edge bucket)
2. Validate that calibration holds across model decay periods
3. Re-calibrate per model (V9's edge-to-HR curve is different from V12's)

This is a Season 2 project, not a pre-Feb-19 fix. **Do you agree, or do you think even a crude fractional Kelly (e.g., bet more when edge > 7, less when edge 3-5) would add value without formal calibration?**

## 5. Simple Baseline Benchmark — This Already Exists

You suggested adding a "dumb baseline" comparison. We actually have this:
- `moving_average` model is essentially "bet the recent average" — it hit 48.0% on Feb 2 (best of all models that day)
- `catboost_v8` has 27K+ graded picks across 4 years at 79.7% lifetime HR — that's the benchmark
- Vegas lines with no model = 50% HR by definition (lines are set to be efficient)

The question we've already answered is: does V9/V12 + signals beat naive approaches? Yes, when the model is fresh (71.2% V9 at launch, 60.5% V12 at 0.90+). The problem is exclusively about model staleness, not about whether ML adds value over baselines.

**But your implicit point is valid: we should track the moving_average and V8 baselines continuously as sanity checks. If our complex system can't beat moving_average on a rolling basis, something is broken. We don't currently surface this comparison in the daily dashboard.**

## Summary of Where I Land

| Your Concern | My Response |
|-------------|-------------|
| Small samples | Agree it's a risk, but the alternative (wait 5 months) is impractical. Directional logic + fail-safes are the pragmatic approach. |
| Replay overfitting | Agree. V8 multi-season replay is already planned and will validate or invalidate thresholds. |
| Feedback loop | Theoretical risk is low based on Feb 2 evidence. But adding `is_model_dependent` separation to health tracking is easy and worth doing. |
| Kelly criterion | Correct direction but premature without calibrated probabilities. Season 2 project. |
| Combo look-ahead bias | **You're right.** This is the most actionable concern. We should freeze current classifications and validate on post-Feb-19 data before adding new combos. |
| Simple benchmarks | Already exist implicitly (V8, moving_average) but should be surfaced in the daily dashboard. Good suggestion. |
| V12 decay planning | **You're right.** We need a minimum sample size gate (INSUFFICIENT_DATA state exists but may not be calibrated for V12's lower pick volume). |

**What's your response? Particularly on points 1 (practical sample size framing) and 4 (Kelly without calibration).**
