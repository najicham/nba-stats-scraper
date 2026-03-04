# Shadow Monitoring Disabled Models

## The Idea

When we disable a model, we currently stop it from generating predictions entirely. This means we lose all future data about how it would have performed. If the model would have recovered or excelled in a different market regime, we'd never know.

**Proposal:** Disabled models should continue generating predictions in shadow mode. Their picks should flow through the full best bets pipeline (filters, signals, ranking) but never be published. We track their "would-be" best bets and ultra bets performance alongside live models.

## Why This Matters

1. **We've made mistakes before.** Session 391 found that the 113-player blacklist was entirely caused by disabled model predictions — the disabled models were still contaminating evaluations. If we'd been shadow-tracking instead, we'd have caught this pattern earlier.

2. **Market regimes shift.** A model that performed terribly in Feb (seasonal rotation stabilization) might perform well in March (playoffs approaching, rotations tightening). Without shadow data, we can never validate this.

3. **Best bets is the metric that matters.** A model's raw HR can be 50% but its best bets HR can be 80% if the filter stack removes its losing patterns. We need to track best bets performance specifically, not just raw predictions.

4. **Ultra bets insight.** If a disabled model would have produced ultra-tier picks that won, that's a signal we need to investigate — something about its architecture captures patterns others miss.

## Implementation Approach

### Option A: Full Shadow Pipeline (Recommended)

- Worker continues generating predictions for disabled models (already gated by env vars — just set to `true` in shadow mode)
- `supplemental_data.py` includes shadow models in a SEPARATE selection pass (not competing with live models)
- `aggregator.py` runs filter stack on shadow predictions and writes results to a shadow table
- New BQ table: `nba_predictions.shadow_best_bets_picks` — same schema as `signal_best_bets_picks` plus `shadow_model_id`
- Grading picks up shadow picks too (they have actual outcomes from games)

**Pros:** Full fidelity, measures exactly what would have happened
**Cons:** Doubles prediction compute cost, adds BQ query complexity

### Option B: Post-Hoc Simulation (Lighter)

- Don't generate new predictions from disabled models
- Instead, keep their existing `prediction_accuracy` data flowing (grading continues for as-yet-ungraded predictions)
- Add a `bin/shadow_eval.py` script that:
  1. Queries disabled model predictions from `player_prop_predictions`
  2. Runs them through the filter stack in Python (using `aggregator.py` directly)
  3. Writes results to `shadow_best_bets_picks`
- Run daily as part of post-grading export

**Pros:** Zero additional prediction compute, uses existing data
**Cons:** Only works for models that still have active predictions; no new predictions after disable

### Option C: Retroactive Analysis Only

- When considering re-enabling a model, manually run `what_if_retrain.py` or `post_filter_eval.py` on its historical predictions
- No automated shadow tracking

**Pros:** Simplest, no infrastructure changes
**Cons:** Requires manual effort, easy to forget, no continuous monitoring

## What to Track

For each shadow model, per game_date:

| Metric | Description |
|--------|-------------|
| shadow_bb_picks | Number of picks that would have made best bets |
| shadow_bb_correct | Number that were correct |
| shadow_bb_hr | Hit rate |
| shadow_ultra_picks | Number that would have been ultra bets |
| shadow_ultra_correct | Number correct |
| shadow_avg_edge | Average edge of shadow picks |
| shadow_avg_signal_count | Average signal count |
| shadow_filter_pass_rate | % of edge 3+ predictions passing filters |

## Alert Criteria

Surface a "shadow model outperforming" alert when:
- Shadow model BB HR > 65% over 14 days on N >= 10 picks
- Shadow model has ultra picks at > 75% HR
- Shadow model's filter pass rate is significantly different from live models (could indicate filter misconfiguration)

## Open Questions for Next Session

1. Which option (A/B/C) balances cost vs insight best?
2. Should shadow models compete in the same per-player selection, or get their own selection pass?
3. How long do we shadow-monitor before considering re-enablement?
4. Should we shadow-monitor ALL disabled models or only recent disables?
