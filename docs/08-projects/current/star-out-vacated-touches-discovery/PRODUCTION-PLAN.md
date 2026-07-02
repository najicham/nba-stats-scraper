# Star-OUT Signal — Production Plan

**Status:** Not yet built. Needs explicit user approval per CLAUDE.md governance before any code lands.
**Estimated effort:** 1-2 days for feature + aggregator + shadow deployment.
**Risk:** Low. Adds new rescue path; doesn't change existing signal behavior.

---

## 1. Feature additions

Two new fields on prediction-time data (added to feature pipeline, NOT stored in `ml_feature_store_v2` since they depend on injury report read at prediction time):

### `is_star_teammate_out` (BOOL)
- TRUE if the target player's team's "lead scorer" (computed below) is in `nbac_injury_report` latest snapshot with `injury_status = "out"` for the prediction's `game_date`
- Lead scorer = player with highest trailing-30-day ppg on the team, ≥5 games on team in last 30 days, ≥18 ppg

### `target_team_scorer_rank` (INTEGER 1-15)
- Target player's rank by trailing-30-day ppg on his team (same denominator)
- Computed at prediction time from `player_game_summary`
- **Cohort eligibility: ranks 2-7** (rank 5-7 extension validated 2026-05-23; see FINDINGS.md §13)

### Computation location
- Best fit: `ml/signals/supplemental_data.py` — new function `compute_star_out_context(predictions, bq_client)` that returns a dict keyed by `(game_date, player_lookup)`
- Called once per pipeline run after `query_predictions_with_supplements`, batched (one BQ scan total)
- Cache for the day (TTL until end of game_date)

## 2. Signal definition

Add to `ml/signals/aggregator.py`:

```python
def evaluate_star_out_rescue(pred, ctx):
    """
    Rescue signal: bypass OVER edge floor when target player's star teammate is OUT
    and the model recommends OVER with edge >= 3.

    Validated discovery: 79.4% HR on N=509 across 4 seasons, 98% incremental
    to existing pipeline. See docs/08-projects/current/star-out-vacated-touches-discovery/
    """
    if pred['recommendation'] != 'OVER':
        return None
    if pred['model_edge'] < 3.0:
        return None
    if not ctx.get('is_star_teammate_out'):
        return None
    if ctx.get('target_team_scorer_rank') not in (2, 3, 4, 5, 6, 7):
        return None
    return {
        'tag': 'star_out_rescue',
        'rescue_priority': 2,  # between combo(1) and HSE(3)
        'weight': 2.0,         # contributes to real_sc
    }
```

### Integration with existing aggregator
- Add `star_out_rescue` to the rescue list in `aggregator.py`, between `combo_*` (priority 1) and `hse_rescue` (priority 3)
- Tag bypasses the OVER edge floor (6.0 → 3.0 for this cohort only)
- Counts as 1 toward `real_sc` (helps satisfy `real_sc >= 3` gate when combined with other signals)
- Does NOT bypass: negative filters (hot_3pt_under, cold_fg_under, etc.), team cap (2/team), volume cap (15/day), edge-based auto-halt

## 3. SIGNAL-INVENTORY.md entry (when promoting to active)

```markdown
| star_out_rescue | OVER | TBD% | SHADOW | Lead scorer (>=18 ppg) is OUT; target is rank 2/3/4 on team. Bypasses OVER edge floor 6.0→3.0. Discovery: docs/08-projects/current/star-out-vacated-touches-discovery/ |
```

## 4. Shadow → Active gates

Per CLAUDE.md governance + Session 466-468 promotion threshold patterns:

| Gate | Threshold | Why |
|------|-----------|-----|
| N graded | ≥ 30 | Standard NBA promotion minimum |
| HR (shadow live) | ≥ 65% | Backtest was 71.7% incremental; allow 5pp degradation buffer |
| Cross-validation w/ filter audit | No conflict with active filters | Verify no negative filter dominance |
| Algorithm version bump | New version (e.g., `v523_star_out_rescue`) | Trackability |
| User sign-off | Explicit per CLAUDE.md | Signal addition affects pick generation |

## 5. Volume cap

Limit `star_out_rescue` rescues to **5 picks/day max** initially. Discovery shows ~1 game/day fits the cohort during normal season (175/year ÷ 200 game-days ≈ 0.9/day, with some days having multiple eligible teams). Cap exists to prevent runaway behavior if injury report has many OUTs (e.g., late-season load management days).

## 6. Backtest hook before live deploy

Before shipping to shadow, modify `bin/simulate_best_bets.py` (or write a thin wrapper) to:
1. Apply the proposed `star_out_rescue` rule as a hypothetical
2. Run on 2024-25 + 2025-26 partial
3. Verify: incremental picks ≈ 175/season, HR ≈ 70%+, no team-cap violations
4. Cross-check N picks/day distribution (no >5 days)

Output goes in this dir as `BACKTEST-VALIDATION.md` before shadow ship.

## 7. Monitoring

After shadow deploy:
- Add to `model_performance_daily` (or analog) the daily count of `star_out_rescue` activations + HR
- Watch for `signal_health_daily` regime change (HOT → COLD)
- If HR drops below 55% over a 14-day rolling window, auto-demote to OBSERVATION (per existing filter-counterfactual-evaluator pattern)

## 8. Rollback plan

- Disable: remove `star_out_rescue` from rescue list in `aggregator.py`, deploy. No persistent state to clean up.
- Picks generated under the rescue retain provenance via `pick_angles` field — auditable post-hoc.

## 9. Open implementation questions

- **How to handle traded players?** Target player who joined team <10 days ago doesn't have 5 games on team → won't be ranked. Acceptable — they're excluded from cohort by definition.
- **Multi-star-OUT scenario?** Memory says `stars_out >= 2` already a thing (OVER 68%). Does this signal stack additively or is it subsumed? Test in backtest.
- **Late-breaking handling at prediction time?** Final prediction run is ~3 hours before tipoff. Injuries announced after that won't trigger. Acceptable for v1; consider live-update path later.

## 10. Files that will change

- `ml/signals/supplemental_data.py` — new `compute_star_out_context()` function
- `ml/signals/aggregator.py` — new `evaluate_star_out_rescue()`, register in rescue list
- `bin/simulate_best_bets.py` — wire up the new context fetch
- `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` — add row when promoting
- `CLAUDE.md` — add to "Signal System" section when promoting

No schema migration. No retrain required. No model artifact changes.
