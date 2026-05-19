---
name: mlb-best-bets-config
description: Read-only diagnostic — single-pane-of-glass view of MLB best bets thresholds, active fleet, regime, halt status, filters, and recent CF HR
---

# Skill: MLB Best Bets Config Dashboard

Read-only diagnostic for the MLB pitcher strikeouts best bets pipeline.
Mirrors the NBA `/best-bets-config` skill but reflects MLB-specific
config: OVER-only by default, edge thresholds tuned for K props,
regime gating on `vegas_mae` (not points_mae), and the auto-halt
envelope.

## Trigger
- User types `/mlb-best-bets-config`
- User asks about MLB best bets thresholds, fleet, halt status, or filter health

## Workflow

Run all sections below and present results as a formatted dashboard.

---

### Section 1: Exporter Config

Read constants and env-var overrides from `ml/signals/mlb/best_bets_exporter.py`:

```bash
grep -nE '^(DEFAULT_EDGE_FLOOR|AWAY_EDGE_FLOOR|BLOCK_AWAY_RESCUE|BLOCK_ALL_AWAY_OVER|UNDER_ENABLED|MAX_EDGE|MAX_PROB_OVER|MAX_PICKS_PER_DAY|MIN_SIGNAL_COUNT)' ml/signals/mlb/best_bets_exporter.py
grep -nE '^(TIGHT_VEGAS_MAE_THRESHOLD|TIGHT_OVER_FLOOR_DELTA)' ml/signals/mlb/config.py
grep -n "algo_version\s*=\s*'" ml/signals/mlb/best_bets_exporter.py
```

Also read the live env-var values on the deployed worker:

```bash
gcloud run services describe mlb-prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" 2>/dev/null \
  | tr ',' '\n' | grep -E '^MLB_'
```

Display as:

```
## 1. Exporter Config
| Setting                    | Default | Env var override         | Notes                                       |
|----------------------------|---------|--------------------------|---------------------------------------------|
| algorithm_version          | mlb_v9_max_edge_125 | (hardcoded)  | Bump in code; mirrors NBA pattern          |
| DEFAULT_EDGE_FLOOR         | 0.75    | MLB_EDGE_FLOOR           | Home OVER floor                             |
| AWAY_EDGE_FLOOR            | 1.25    | MLB_AWAY_EDGE_FLOOR      | Away OVER floor (cross-season 54.1% HR)    |
| BLOCK_ALL_AWAY_OVER        | true    | MLB_BLOCK_ALL_AWAY_OVER  | Codifies AWAY_EDGE_FLOOR==MAX_EDGE collision|
| BLOCK_AWAY_RESCUE          | true    | MLB_BLOCK_AWAY_RESCUE    | No rescue for away OVER                    |
| UNDER_ENABLED              | false   | MLB_UNDER_ENABLED        | Walk-forward: 47-49% HR without signals    |
| MAX_EDGE                   | 1.25    | MLB_MAX_EDGE             | Overconfidence cap; tightened from 1.5 S2 |
| MAX_PROB_OVER              | 0.70    | MLB_MAX_PROB_OVER        | Probability cap                             |
| MAX_PICKS_PER_DAY          | 5       | MLB_MAX_PICKS_PER_DAY    | Top-N hard limit                           |
| MIN_SIGNAL_COUNT           | 2       | (hardcoded)              | Real-signal floor                           |
| TIGHT_VEGAS_MAE_THRESHOLD  | 1.5     | (hardcoded, mlb/config)  | Below this, regime is TIGHT                |
| TIGHT_OVER_FLOOR_DELTA     | 0.5     | (hardcoded, mlb/config)  | Adds to DEFAULT_EDGE_FLOOR in TIGHT regime |
```

---

### Section 2: Active Fleet

Query `mlb_predictions.model_registry`:

```sql
SELECT
  model_id, model_family, status, enabled,
  training_start_date, training_end_date,
  DATE_DIFF(CURRENT_DATE(), training_end_date, DAY) AS days_stale
FROM `nba-props-platform.mlb_predictions.model_registry`
WHERE enabled = TRUE
ORDER BY days_stale ASC
```

Active prediction-generating models in the last 3 days. (Note:
`pitcher_strikeout_predictions` uses `model_version` not `system_id`, so we
look at `prediction_accuracy` for the canonical system_id list.)

```sql
SELECT DISTINCT system_id, COUNT(*) AS preds_last_3d
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY system_id
ORDER BY system_id
```

Cross-check vs `MLB_ACTIVE_SYSTEMS` on the worker:

```bash
gcloud run services describe mlb-prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" 2>/dev/null \
  | tr ',' '\n' | grep MLB_ACTIVE_SYSTEMS
```

Flag:
- Enabled in registry but no recent predictions → **NO PREDICTIONS**
- Active on worker but disabled in registry → **DRIFT**
- `days_stale > 14` → **STALE** (MLB retrain cadence is biweekly)

---

### Section 3: Halt State + Regime Context

```sql
SELECT
  effective_date, halt_active, halt_reason, halt_since,
  TO_JSON_STRING(halt_metrics) AS metrics
FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE sport = 'mlb'
ORDER BY effective_date DESC
LIMIT 5
```

Regime context (reads `mlb_predictions.league_macro_daily`):

```sql
SELECT
  game_date,
  ROUND(vegas_mae_7d, 2) AS vegas_mae_7d,
  ROUND(mae_gap_7d, 2) AS mae_gap_7d,
  market_regime,
  ROUND(avg_predicted_edge_7d, 2) AS avg_edge_7d
FROM `nba-props-platform.mlb_predictions.league_macro_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC
```

Display as:

```
## 3. Halt + Regime
| Date       | Halt | Reason         | vegas_mae_7d | mae_gap_7d | Regime |
|------------|------|----------------|--------------|------------|--------|
| 2026-05-18 | NO   | (cleared)      | 1.42         | -0.11      | TIGHT  |
| 2026-05-17 | YES  | pick_drought   | 1.45         | -0.10      | TIGHT  |
```

If `market_regime = TIGHT`, the exporter auto-raises `DEFAULT_EDGE_FLOOR` by `TIGHT_OVER_FLOOR_DELTA` and disables rescue. Mention this in the display when active.

---

### Section 4: Negative Filter Inventory

MLB has two layers:

**Layer A — Hardcoded blocks in `best_bets_exporter.py` (run first):**

| # | Filter                      | Condition                                            | Notes                            |
|---|-----------------------------|------------------------------------------------------|----------------------------------|
| 1 | halt_state                  | halt_active for canonical reason                     | Section 3                        |
| 2 | direction_filter            | UNDER + UNDER_ENABLED=false                          | All UNDERs blocked by default    |
| 3 | overconfidence_cap          | OVER + edge > MAX_EDGE (1.25)                        | Session 2 — tightened from 1.5  |
| 4 | probability_cap             | OVER + p_over > MAX_PROB_OVER (0.70)                 | Walk-forward: prob>0.7 = 58.7%   |
| 5 | away_over_blocked_policy    | OVER + away + BLOCK_ALL_AWAY_OVER=true              | Codifies AWAY collision          |
| 6 | away_edge_floor             | OVER + away + edge < AWAY_EDGE_FLOOR (1.25)         | (if BLOCK_ALL_AWAY_OVER=false)  |
| 7 | edge_floor                  | edge < effective_edge_floor (regime-adjusted)        | Final gate                       |

**Layer B — Registry filters (`ml/signals/mlb/registry.py:negative_filters()`):**

```bash
grep -nE "class.*Filter\(BaseMLBSignal" ml/signals/mlb/signals.py
```

| # | Filter (tag)            | Condition                                            |
|---|-------------------------|------------------------------------------------------|
| 1 | bullpen_game_skip       | Probable starter is bullpen day                       |
| 2 | il_return_skip          | Pitcher returning from IL                             |
| 3 | pitch_count_cap_skip    | Pitcher under explicit pitch-count cap                |
| 4 | insufficient_data_skip  | Not enough recent appearances                          |
| 5 | pitcher_blacklist       | Pitcher on manual blacklist                           |
| 6 | whole_line_over         | OVER + whole-number line (.0 not .5) — S443 +9.6pp   |

---

### Section 5: Active Filter Overrides (CF auto-demote)

Phase 1 of the MLB CF evaluator collects CF HR per filter daily. Any filter
auto-demoted (or manually demoted) appears here as `active = TRUE` and is
treated as OBSERVATION by the exporter (still evaluated, doesn't block).

```sql
SELECT
  filter_name, override_type, cf_hr_7d, n_7d,
  triggered_at, triggered_by, demote_start_date, re_eval_date
FROM `nba-props-platform.mlb_predictions.filter_overrides`
WHERE active = TRUE
ORDER BY triggered_at DESC
```

Phase 1 ELIGIBLE_FOR_AUTO_DEMOTE is `{}` (empty) — see
`orchestration/cloud_functions/mlb_filter_counterfactual_evaluator/main.py`.
This section will be empty in normal operation until eligibility is enabled.

---

### Section 6: Filter CF HR (recent 7d)

```sql
SELECT
  filter_name,
  SUM(blocked_count) AS blocked_7d,
  SUM(wins) AS wins_7d,
  SUM(losses) AS losses_7d,
  ROUND(100.0 * SUM(wins) / NULLIF(SUM(wins + losses), 0), 1) AS cf_hr_7d
FROM `nba-props-platform.mlb_predictions.filter_counterfactual_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY filter_name
ORDER BY blocked_7d DESC
```

**Reading guide (matches NBA):**
- CF HR < 50% → filter is correctly blocking losers (working as intended)
- CF HR 50–55% → ambiguous, watch
- CF HR ≥ 55% AND N ≥ 20 over 7 consecutive days → filter is blocking winners → candidate for demotion. Add to `ELIGIBLE_FOR_AUTO_DEMOTE`.

Flag filters trending bad in the output.

---

### Section 7: Signal Inventory

```bash
grep -n "registry\.register" ml/signals/mlb/registry.py | wc -l
```

```bash
# Active vs shadow split
python3 -c "
from ml.signals.mlb.registry import build_mlb_registry
r = build_mlb_registry()
print(f'Active: {len(r.active_signals())}')
print(f'Shadow: {len(r.shadow_signals())}')
print(f'Filters: {len(r.negative_filters())}')
print(f'Total: {len(r.all())}')
"
```

If `mlb_predictions.signal_health_daily` has data, also show recent health:

```sql
SELECT
  signal_tag, regime, ROUND(hit_rate_7d * 100, 1) AS hr_7d, sample_size_7d
FROM `nba-props-platform.mlb_predictions.signal_health_daily`
WHERE game_date = (SELECT MAX(game_date) FROM `nba-props-platform.mlb_predictions.signal_health_daily`)
ORDER BY sample_size_7d DESC
LIMIT 30
```

(Most MLB signals have zero health rows because they haven't appeared in picks — that's normal early-season, see MEMORY: "Dead signals early season".)

---

### Section 8: Recent Picks Summary

```sql
SELECT
  game_date,
  COUNT(*) AS picks,
  COUNTIF(recommendation = 'OVER') AS overs,
  COUNTIF(recommendation = 'UNDER') AS unders,
  ROUND(AVG(ABS(edge)), 2) AS avg_edge,
  ROUND(AVG(confidence_score), 1) AS avg_conf
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

Pair with grading rollup:

```sql
WITH bb_picks AS (
  SELECT DISTINCT pitcher_lookup, game_date, recommendation, line_value
  FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
)
SELECT
  pa.game_date,
  COUNT(*) AS graded,
  COUNTIF(pa.prediction_correct) AS wins,
  ROUND(100.0 * SAFE_DIVIDE(COUNTIF(pa.prediction_correct), COUNT(*)), 1) AS hr
FROM `nba-props-platform.mlb_predictions.prediction_accuracy` pa
INNER JOIN bb_picks USING (pitcher_lookup, game_date, recommendation, line_value)
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
```

---

### Section 9: Sync / Process Health

| Check | How | Alert If |
|-------|-----|----------|
| Halt envelope read on every export | `grep _read_halt_envelope ml/signals/mlb/best_bets_exporter.py` | not called |
| filter_overrides read on every export | `grep _load_filter_overrides ml/signals/mlb/best_bets_exporter.py` | not called |
| filter_counterfactual_daily fresh | `SELECT MAX(game_date) FROM mlb_predictions.filter_counterfactual_daily` | > 2 days stale |
| MLB CF evaluator scheduled | `gcloud scheduler jobs describe mlb-filter-counterfactual-evaluator-daily --location=us-west2` | not present |
| signal_health_daily fresh (if pick volume sufficient) | `SELECT MAX(game_date)` | > 3 days stale |
| Grading writes prediction_accuracy daily | `SELECT MAX(game_date)` | > 1 day stale |
| Cloud Run traffic on `mlb-prediction-worker` routed to latest | `gcloud run services describe ... --format='value(status.traffic[0].latestRevision)'` | `False` |

Display sync status with pass/fail indicators.

---

### Checklists (always show at bottom)

```
## Promote a filter to ELIGIBLE_FOR_AUTO_DEMOTE
- [ ] Filter has 7+ consecutive days of data in filter_counterfactual_daily
- [ ] 7d total_graded >= 20 (or higher floor via PER_FILTER_MIN_PICKS_7D)
- [ ] 7d CF HR within [40%, 60%] — sustained without auto-demote
- [ ] Adding it doesn't break a known structural gate (NEVER_DEMOTE set)
- [ ] Deploy ELIGIBLE_FOR_AUTO_DEMOTE update + smoke-test the CF
- [ ] Document in MEMORY/mlb-system.md

## Promote a shadow signal to active
- [ ] Cross-season replay: >= 60% HR at N >= 30
- [ ] Hit rate consistent across 2+ seasons (not single-season fluke)
- [ ] Move from shadow registration block to active in registry.py
- [ ] Add to MEMORY/mlb-system.md signal inventory
- [ ] Verify it fires within 7d post-deploy

## Bump MAX_EDGE
- [ ] N >= 30 for the current cap (avoid Session 2 N=8 trap)
- [ ] Wilson lower bound HR < 43.6% in the over-cap bucket
- [ ] Document override env var: MLB_MAX_EDGE=X.X on mlb-prediction-worker
- [ ] Revert plan: env-var rollback to previous value
```

---

### Notes

- MLB is OVER-only by default (`UNDER_ENABLED=false`). All UNDER picks are blocked by `direction_filter` and counted in `best_bets_filter_audit`.
- `BLOCK_ALL_AWAY_OVER=true` means the AWAY_EDGE_FLOOR codepath is dormant — all away OVER picks are blocked by the explicit policy filter. Setting it false re-enables AWAY_EDGE_FLOOR as the gate.
- The auto-halt envelope (`nba_orchestration.halt_state`) reads via `_read_halt_envelope()` at export time. Halts: `off_season`, `between_rounds`, `fleet_blocked`, `predictions_inactive`, `pick_drought`, `tight_market`, `manual`. `unknown_state` fails-OPEN at pick gen.
- Phase 1 of the MLB filter CF evaluator (deployed 2026-05-18) writes daily CF HR but does NOT auto-demote — `ELIGIBLE_FOR_AUTO_DEMOTE = {}`. Phase 2 will populate the set once 7+ days of data exists for candidate filters.
