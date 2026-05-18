# Session Handoff — 2026-05-18 — edge-window pytest + grading divergence discovery

**Predecessor:** [`2026-05-17-2-halt-state-mlb-extension-and-fleet-transition-fix.md`](2026-05-17-2-halt-state-mlb-extension-and-fleet-transition-fix.md). That session shipped the MLB halt-envelope wiring + fleet-transition grace. This session shipped open-work item #1 (edge-sweep + regime pytest) and surfaced a high-priority grading divergence vs sportsbook rules while reviewing yesterday's picks.

## TL;DR

1. **Edge-window × regime pytest landed.** `tests/mlb/test_exporter_with_regressor.py` +373 lines, 21 new tests, all passing. Codifies the 5/14-5/16 floor/cap collision class as CI guarantee. Three layers: parametrized behavioral cross-product (15 cases), rescue path coverage (2 cases), static module-constant invariants (4 cases). Commit `740761ff`.

2. **Grading divergence discovered.** `MIN_IP_FOR_VALID_PROP = 4.0` in `data_processors/grading/mlb/mlb_prediction_grading_processor.py:41` is far more conservative than US sportsbooks (FanDuel = 1 pitch, DraftKings/BetMGM = 1 out). Two 5/17 BB picks (Fedde, Brandon Young) were voided as `short_start` that would have been graded as LOSSES at FanDuel/DraftKings/BetMGM rules. This inflates our reported HR vs. what an actual bettor would see at the book.

3. **Verification of 5/18 auto-clear pending wall-clock time.** At session end (~05:35 UTC = 01:35 ET Monday), the 5 AM ET writer had not yet fired and 12:55 PM ET MLB pick-gen was ~11h away. Prerequisites all confirmed in place; see "Verification still pending" section.

## What landed (commits)

### `740761ff` — test(mlb): edge-window × regime cross-product pytest

Single file change: `tests/mlb/test_exporter_with_regressor.py` (+373 lines, no removed lines).

Three new test classes:

| Class | Tests | Purpose |
|---|---|---|
| `TestEdgeWindowCrossProduct` | 15 parametrized | Cross-product of (regime ∈ NORMAL/TIGHT/BLOCK_ALL_OVER) × (side ∈ HOME/AWAY) × (edge band ∈ below-floor/in-window/above-cap). Each cell asserts pick survival OR records the expected blocker in `filter_audit`. Catches pipeline-order drift, regime-delta drift, and floor/cap drift in one suite. |
| `TestRescueOverridesEdgeFloor` | 2 | Rescue path coverage kept orthogonal to the edge-window matrix. NORMAL HOME below floor → rescued; TIGHT HOME below floor → rescue disabled, blocks by `edge_floor`. |
| `TestEdgeWindowStaticInvariants` | 4 | Module-constant invariants: NORMAL home window ≥ MIN_EDGE_WINDOW_K (critical — guarantees the system isn't permanently droughted); AWAY explicitly closed or open (no implicit collisions); TIGHT home closure documented as known state; TIGHT_VEGAS_MAE_THRESHOLD ≤ 1.5 (the 5/14-5/16 threshold was 1.7). |

Helper additions:
- `_make_regime(regime, vegas_mae_7d, mae_gap_7d)` — builds dict matching `_get_regime_context()` shape
- `_no_halt_envelope(_)` — bypasses halt for tests
- `_make_features_no_rescue(**overrides)` — features that fire 2+ real signals but NO rescue signals (so cross-product measures the edge window itself, not rescue behavior)

Pre-existing failures NOT addressed (separate scope — would be a one-line PR each):
- `TestUltraTier::test_algorithm_version_updated` — expects `mlb_v8_s456_v3final_away_5picks`, current is `mlb_v9_max_edge_125`
- `TestUltraTier::test_bq_row_includes_ultra_fields` — fails downstream from above
- `TestV3FinalAwayFilters::test_away_pitcher_blocked_below_away_edge_floor` — expects `away_edge_floor` filter, current emits `away_over_blocked_policy` (because BLOCK_ALL_AWAY_OVER=true now)
- `TestV3FinalAwayFilters::test_away_pitcher_passes_above_away_edge_floor` — expects pass at edge 1.3, current blocks (BLOCK_ALL_AWAY_OVER)
- `tests/mlb/test_worker_integration.py` — 9 failures, looks like the `get_prediction_systems()` API changed

## Grading divergence vs sportsbooks (HIGH-PRIORITY DISCOVERY)

### What

`data_processors/grading/mlb/mlb_prediction_grading_processor.py:41` defines `MIN_IP_FOR_VALID_PROP = 4.0`. Any pitcher who starts but is pulled before 4 IP is graded with `void_reason='short_start'` — the prop is treated as voided (no win/loss).

### Why this is wrong

US sportsbook rules for pitcher K props are MUCH more permissive:

| Book | Rule |
|---|---|
| **FanDuel** | Valid if pitcher throws ≥ 1 pitch |
| **DraftKings** | Valid if pitcher records ≥ 1 out (~⅓ IP) |
| **BetMGM** | Valid if pitcher records ≥ 1 out |
| **Caesars** | Valid if pitcher records ≥ 1 out (some markets: starts the game) |
| **Pinnacle** | Most strict in US: typically 1 IP minimum |

The 4 IP threshold matches NO major US book. It looks like it was chosen as a quality gate ("pitcher needs enough time for the prediction to be meaningful") rather than to match book settlement.

### Evidence — 5/17 picks

```
pitcher           line   actual  rec   current_grade   FanDuel/DK_grade
erick_fedde       3.5    2       OVER  voided          LOSS
brandon_young     3.5    3       OVER  voided          LOSS
```

Both pitchers started, both got pulled early, both struck out FAR fewer than the line. Our system reports HR = N/A (voided). FanDuel/DK bettors would have lost both.

### Impact

This silently inflates our reported HR vs reality. Historical impact unknown — needs a backfill audit:

```sql
-- How many "void" picks would have been losses at FanDuel/DK rules?
SELECT
  void_reason,
  COUNT(*) AS picks,
  COUNTIF(actual_strikeouts < line_value AND recommendation = 'OVER') AS would_be_loss_over,
  COUNTIF(actual_strikeouts > line_value AND recommendation = 'UNDER') AS would_be_loss_under,
  COUNTIF(actual_strikeouts > line_value AND recommendation = 'OVER') AS would_be_win_over,
  COUNTIF(actual_strikeouts < line_value AND recommendation = 'UNDER') AS would_be_win_under
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE void_reason = 'short_start'
  AND game_date >= '2024-04-01'
GROUP BY void_reason
```

### Fix options (need user input before implementing)

1. **Lower MIN_IP_FOR_VALID_PROP to 0.33 (1 out — DraftKings rule).** Simplest. Matches modal US book behavior.
2. **Lower to 0.0 (FanDuel — just needs to throw a pitch).** Most permissive; matches FanDuel.
3. **Per-book grading** — track which book the line came from and apply that book's rule. Most accurate but high effort.
4. **Add `grading_void_threshold` env var** — start conservative, can adjust without code change.

**Recommendation:** Option 1 (1 out / 0.33 IP). Reasoning: (a) matches most volume across US books; (b) preserves "rain shortened, 0 outs" as genuine void; (c) reversible via env var if option 4 adopted later; (d) immediately stops inflating HR vs reality.

**Before changing:** run the backfill audit query above to quantify how the historical record shifts. If HR drops materially (e.g., from 63.4% to 58%), that's a real signal about model quality, not a bug.

## Verification still pending (predecessor handoff items #1-4)

Wall-clock time hadn't arrived at session end. Run these as the FIRST step in the next session:

### 1. ~10:05 UTC — halt cleared for 5/18

```bash
bq query --use_legacy_sql=false 'SELECT effective_date, halt_active, halt_reason, halt_since, TO_JSON_STRING(halt_metrics) AS m FROM `nba-props-platform.nba_orchestration.halt_state` WHERE sport="mlb" ORDER BY effective_date DESC LIMIT 3'
```

Expected: 5/18 row `halt_active=FALSE`. Predecessor session diagnostics if it fails.

### 2. ~17:00 UTC — MLB picks shipped

```bash
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) AS picks, COUNTIF(recommendation="OVER") AS overs, COUNTIF(recommendation="UNDER") AS unders, ROUND(AVG(ABS(edge)),2) AS avg_edge FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC'
```

Expected: 5/18 row with 3-6 picks.

### 3. ~14:30 UTC — halt envelope in Phase 6 JSON

```bash
gsutil cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json | python3 -c "import json,sys; d=json.load(sys.stdin); print({k: d.get(k) for k in ['halt_active','halt_reason','halt_since','total_picks','graded']})"
```

Expected: `halt_active=False` for normal day.

### 4. By 5/22 — fleet_in_transition grace releases

New MLB regressor was registered 2026-05-17. Grace ends 2026-05-22.

```bash
bq query --use_legacy_sql=false 'SELECT game_date, model_id, decay_state, hr_7d, n_7d FROM `nba-props-platform.mlb_predictions.model_performance_daily` WHERE game_date >= CURRENT_DATE()-7 AND model_id LIKE "catboost_mlb_v2_regressor%20260517" ORDER BY game_date DESC'
```

Expected: at least one row by 5/19 morning.

## Open work — ordered by priority

### 🔥 Highest leverage (next 1-2 sessions)

1. **Grading divergence backfill audit + fix** (~3-6h). Highest-value because it's a HR truthfulness issue, not a model issue. Run the audit query above to quantify. Discuss option 1 vs option 4 with user. Implement, write a one-time backfill of historical `prediction_accuracy.prediction_correct` to use new threshold, add a comment in `mlb_prediction_grading_processor.py:41` documenting the chosen rule.

2. **MLB filter counterfactual evaluator + auto-demote** (~2 days). Predecessor handoff #2. Direct port of `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py` to MLB. MLB has enough graded picks now (654+) for top 3-4 filters. Would have auto-rejected the "tighten MAX_EDGE on N=8 evidence" Session 2 decision.

3. **Three missing pre-commit hooks** (~2h total — predecessor handoff #3, never built):
   - `--set-secrets` validator: detect when a service has >N secrets and a `--set-secrets` would silently unmount them
   - `download()` override detector: scraper must override `start_download()` or `download_data()`, never `download()` (mlb_weather was dead code 6+ months)
   - Threshold-literal-drift grep: detect duplicated literal numeric thresholds across N files (TIGHT_VEGAS_MAE_THRESHOLD drifted between two files this week)

### 🟡 Medium leverage

4. **Fix the 13 stale tests** (~1h total). The 4 in `test_exporter_with_regressor.py` (algorithm_version, AWAY tests) are 5-min each. The 9 in `test_worker_integration.py` need a look — `get_prediction_systems` API changed. Could clean up while context is fresh from item #1.

5. **MLB weekly_retrain CF** (~3-5 days). Predecessor handoff #4. Today's manual `--window 365` retrain validated `train_regressor_v2.py` passes governance — perfect time to port `weekly_retrain/main.py`. Bundle with: registry model-swap event signaling to halt_state_writer.

6. **Audit empty mlb_precompute tables** (4-8h, predecessor handoff #5). Gap analysis agent found 4 tables consumed by `pitcher_features_processor` but never populated:
   - `lineup_k_analysis` (already in memory: vapor confirmed)
   - `pitcher_innings_projection`
   - `pitcher_arsenal_summary`
   - `batter_k_profile`

   Features `f25-f44` in `pitcher_ml_features` likely return NULL/zero for all pitchers — model trains on holes. Either fix or drop.

7. **2 more dead-`download()` scrapers** (predecessor handoff #6). `scrapers/mlb/external/mlb_ballpark_factors.py:447` and `scrapers/mlb/statcast/mlb_statcast_pitcher.py:123`. `mlb_raw.statcast_pitcher_stats` empty since Jan 7 — likely the same bug.

### 🟢 Architectural / longer term

8. **`halt_overrides` table** — predecessor handoff #7. Writer doesn't respect manual MERGE overrides; gets overwritten at next 5 AM run.

9. **MPD recovery lag** — predecessor handoff #9. Today's race fix mitigates fresh-model case; the more general "grading writes MPD at 10 AM ET, halt re-evaluates at 5 AM ET next day" creates a 24h+ recovery floor. Consider re-invoking halt_state_writer post-grading.

10. **`/mlb-best-bets-config` skill** (~4h, predecessor #8). Single pane of glass for MLB threshold state.

11. **Isotonic calibration on regressor** (~1 day, predecessor #10). Addresses model overconfidence at edge 1.0-1.5 OVER. Lower priority now that auto-halt + transition grace handle the operational symptoms.

### ❌ Explicitly deferring

- **NBA work** — user signaled NBA is done; defer indefinitely.
- **MLB edge-collapse halt check** — 5/14-5/16 was median edge, not collapsed. Theater. Revisit only if drought episodes accumulate N≥30 with non-pick_drought signatures.

## What we learned (process notes)

1. **Test rot accumulates silently when CI ignores it.** 30 tests in `tests/mlb/` were already failing on `main` before this session. The CI either doesn't run them or doesn't gate on them. Worth checking: does the GitHub Action / Cloud Build trigger run `pytest tests/mlb/`? If yes, why are 30 reds tolerated? If no, why have the tests at all?

2. **Production behavior should drive test design, not the other way around.** First draft of `TestEdgeWindowCrossProduct` failed on `NORMAL HOME edge=0.60 → block` because rescue ACTUALLY does kick in. The test was wrong; production was right. Made the test honest by suppressing rescue features and adding a separate `TestRescueOverridesEdgeFloor` class to cover rescue orthogonally.

3. **Static invariant + behavioral cross-product is a strong combination.** The static `TestEdgeWindowStaticInvariants` is the fast layer (4 tests in 0.1s, run on every commit). The behavioral `TestEdgeWindowCrossProduct` is the slow layer (15 tests in ~1s) that catches regressions in the pipeline ORDER, not just constants. Both layers needed.

4. **User noticed grading divergence by looking at a single pick.** This wasn't in any handoff, alert, or dashboard. The Fedde DNF observation prompted a search that surfaced a structural HR-inflation issue. Worth: a "look at picks vs. what the book actually paid" comparison should be part of daily steering.

## Key references

- **Predecessor handoffs**: [`2026-05-17-2-halt-state...`](2026-05-17-2-halt-state-mlb-extension-and-fleet-transition-fix.md), [`2026-05-17-mlb-drought-fix...`](2026-05-17-mlb-drought-fix-retrain-and-antifragility.md)
- **New tests:** `tests/mlb/test_exporter_with_regressor.py:797+` (search for `_make_regime`)
- **Grading void logic:** `data_processors/grading/mlb/mlb_prediction_grading_processor.py:41` (`MIN_IP_FOR_VALID_PROP`) and `:288-296` (short_start branch)
- **Exporter config:** `ml/signals/mlb/best_bets_exporter.py:50-140` (env vars + edge-window invariant); `ml/signals/mlb/config.py` (regime thresholds)

## First message for the next session

> Read `docs/09-handoff/2026-05-18-edge-window-pytest-and-grading-divergence.md`.
>
> Start by running the four pending verification queries (halt cleared, picks shipped, halt envelope in JSON, MPD freshness). If anything failed overnight, the predecessor handoffs have the diagnostic steps.
>
> Then the highest-leverage open work is item #1: the grading divergence. Run the audit query in the handoff first to quantify the HR shift, then we'll decide between options 1 (DK rule = 1 out) and 4 (env var).
>
> Item #4 (fixing the 13 stale tests) is a strong "quick win" alternative — ~1h, immediately reduces noise in `pytest tests/mlb/`.
>
> Note: today (5/18) MLB picks should ship normally. If they don't, the first place to look is `_fleet_in_transition` and `halt_metrics` in the halt_state row — same diagnostic as predecessor.
