# Session Handoff — 2026-05-17 (Session 2) — halt_state MLB extension + fleet-transition fix

**Predecessor:** [`2026-05-17-mlb-drought-fix-retrain-and-antifragility.md`](2026-05-17-mlb-drought-fix-retrain-and-antifragility.md). Predecessor shipped the 4-day MLB drought RCA + retrain + 8 commits. This session picked up the top-leverage open item — extending the NBA `halt_state_writer` to MLB — then ran a 6-agent post-deploy review that surfaced a critical race condition (fleet_blocked false-positive on fresh model deploys), fixed it, and shipped defensive cleanups.

## TL;DR

1. **`halt_state_writer` now writes meaningful MLB halt rows.** Previously MLB rows existed in `nba_orchestration.halt_state` but were always `halt_active=FALSE` because `_predictions_inactive`, `_fleet_blocked`, and `_edge_collapse` all bailed on non-NBA sports. The 5/14-5/16 drought had zero halt visibility despite zero picks. (`9a7c2cf4`)
2. **MLB pick-gen and Phase 6 publisher now read the halt envelope.** `MLBBestBetsExporter.export()` short-circuits with `[]` when `halt_active=TRUE` and reason is in the canonical set. `MlbBestBetsExporter.generate_json()` + `export_all()` include `halt_active`/`halt_reason`/`halt_since` in JSON output. (`9a7c2cf4`, `fdd6f4ac`)
3. **6-agent post-deploy review found a critical race condition.** With MLB's single-model fleet, `_fleet_blocked` reads the latest `model_performance_daily` decay_state — which lags 24h behind today's grading. When the new model was deployed 5/17 and the old model's last MPD row showed `BLOCKED`, the writer would correctly halt MLB tomorrow morning despite the new model being fresh and validated. Three agents (devil's advocate, threshold review, forward priority) independently flagged this. Fix shipped same session. (`80ad1c60`)
4. **Fleet-in-transition grace clause.** New `_fleet_in_transition` helper: when EVERY production-enabled model in the registry is within 5 days of registration AND has no MPD rows in last 14 days, suspend `fleet_blocked`. Records `fleet_in_transition=true` in `halt_metrics` for audit. Only fires when the entire fleet is in transition — NBA's multi-model fleets unaffected by single weekly retrains. (`80ad1c60`)
5. **Pick-drought must be ONGOING.** Previous logic counted drought days anywhere in the 3-day lookback; would re-fire after picks resumed. Now requires the most recent game day in the lookback to itself be a drought day. Halt clears the morning after picks resume. (`80ad1c60`)
6. **Verified tomorrow's auto-clear.** Dry-run for 5/18: `halt_active=FALSE` (5/17 broke drought + fleet still in transition). MLB picks should ship normally at 12:55 PM ET Monday.

## What landed (commits)

### `9a7c2cf4` — feat(mlb): extend halt_state_writer to MLB + wire halt envelope in exporters

| File | Change |
|---|---|
| `orchestration/cloud_functions/halt_state_writer/main.py` | Parameterized `_predictions_inactive` and `_fleet_blocked` via `PREDICTIONS_LOOKUP` / `MODEL_PERF_LOOKUP` config dicts. MLB schema drift handled (`decay_state`/`hr_7d`/`n_7d` vs NBA's `state`/`rolling_hr_7d`/`rolling_n_7d`). New MLB-only `_mlb_pick_drought` mirrors the canary I shipped in predecessor session: 2+ consecutive days where preds≥5 AND picks==0. Edge-collapse stays NBA-only (MLB thresholds need N≥30 calibration data not yet available). |
| `ml/signals/mlb/best_bets_exporter.py` | Added `_read_halt_envelope()` + halt gate at top of `export()`. Returns `[]` with audit row when `halt_active=TRUE` and reason in canonical set `{off_season, between_rounds, fleet_blocked, predictions_inactive, pick_drought, tight_market, manual}`. `unknown_state` intentionally excluded (fail-OPEN at pick-gen, fail-CLOSED at publish). |
| `data_processors/publishing/mlb/mlb_best_bets_exporter.py` | `generate_json()` (per-date) emits `halt_active`/`halt_reason`/`halt_since` in JSON output. Same stable schema as NBA. |

NBA behavior verified bit-for-bit identical (all NBA halt_state rows 5/10-5/17 still `between_rounds`).

### `80ad1c60` — fix(halt-state): suspend fleet_blocked during model swaps + drought must be ongoing

| File | Change |
|---|---|
| `halt_state_writer/main.py` | Added `MODEL_REGISTRY_LOOKUP` config dict + `FLEET_TRANSITION_GRACE_DAYS=5`. New `_fleet_in_transition(bq, sport, today)` helper consults model_registry to detect "entire production fleet just deployed, no MPD rows yet" state. `evaluate_halt_state` invokes it before `_fleet_blocked` and suspends the check when true. Records `fleet_in_transition=true, fleet_in_transition_models=[...], fleet_in_transition_ages=[...]` in halt_metrics. |
| `halt_state_writer/main.py` | `_mlb_pick_drought` now requires `most_recent_is_drought=True` — the most recent game day in the lookback window must itself be a drought day, not just any 2 days within the window. Prevents halt persisting after picks resume. |

Verified end-to-end on 5/14-5/19 window. After re-invoking writer for 5/17: row updated from `fleet_blocked` (false-positive) to `pick_drought` (correctly tied to past 3 days of zero picks); `fleet_in_transition=true` recorded in metrics for audit.

### `fdd6f4ac` — chore(mlb): defensive cleanups around halt envelope wiring

| File | Change |
|---|---|
| `data_processors/publishing/mlb/mlb_best_bets_exporter.py` | `export_all()` (all.json) was missing halt envelope — per-date `export()` got it in `9a7c2cf4` but cumulative all.json was missed. Frontend now has halt fields on both views. |
| `ml/signals/mlb/best_bets_exporter.py` | Added `halt_source_date` to `_read_halt_envelope()` output (NBA parity). Documented `canonical_halts` policy in comment block — explains why MLB blocks on `pick_drought`/`tight_market`/`manual` while NBA's allow-zero list at `signal_best_bets_exporter.py:521` is narrower (different purposes: block-at-gen vs allow-zero-at-publish). |

Operational coupling agent's "fail-OPEN on BQ error needs fixing" concern reviewed and dropped — NBA's `BaseExporter.halt_envelope` docstring explicitly specifies fail-OPEN for transient query errors (`base_exporter.py:352-354`). MLB matches NBA. Deliberate — telemetry failure shouldn't block picks.

### Live infra changes (not in git)

- **`halt-state-writer` CF deployed twice** (revisions `00005-dow` then `00006-xxx`). Scheduler at `halt-state-writer-daily` (5 AM ET) fires daily for both NBA + MLB.
- **MLB 5/17 halt row written:** `halt_active=TRUE, halt_reason=pick_drought, halt_since=2026-05-17, fleet_in_transition=true`. The 3 picks shipped at 20:30 UTC pre-deploy (Lambert/Pallante/Fedde via signal rescue) are intentionally left in BQ — they grade tomorrow and provide the new regressor's first validation data.
- **mlb-prediction-worker auto-deployed** with new halt gate (revision past `00084-khw`).
- **Phase 6 MLB publishers auto-deployed** with halt envelope fields in JSON output.

## Verification — first 24 hours

### 1. Tomorrow 5/18 ~10:05 UTC — confirm writer cleared the halt

```bash
bq query --use_legacy_sql=false 'SELECT effective_date, halt_active, halt_reason, halt_since, TO_JSON_STRING(halt_metrics) AS m FROM `nba-props-platform.nba_orchestration.halt_state` WHERE sport="mlb" ORDER BY effective_date DESC LIMIT 3'
```

Expected: 5/18 row `halt_active=FALSE`. If still TRUE, check `m.fleet_in_transition` (should be true) and `m.drought_days` (should not include 5/17 since it had picks).

### 2. Monday 5/18 ~17:00 UTC — confirm MLB picks shipped

```bash
bq query --use_legacy_sql=false 'SELECT game_date, COUNT(*) AS picks, COUNTIF(recommendation="OVER") AS overs, COUNTIF(recommendation="UNDER") AS unders, ROUND(AVG(ABS(edge)),2) AS avg_edge FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1 DESC'
```

Expected: 5/18 row with 3-6 picks. If 0 picks AND halt_active=FALSE, check the export logs for filter blocks. If 0 picks AND halt_active=TRUE, the fleet_in_transition grace didn't fire — check `halt_metrics.fleet_in_transition` and the registry query in `_fleet_in_transition`.

### 3. 5/18 ~14:30 UTC — verify halt envelope in Phase 6 JSONs

```bash
gsutil cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json | python3 -c "import json,sys; d=json.load(sys.stdin); print({k: d.get(k) for k in ['halt_active','halt_reason','halt_since','total_picks','graded']})"
```

Expected: `halt_active=False` for normal day. If the field is missing entirely, Phase 6 publisher hasn't redeployed yet — check `gcloud builds list --filter='trigger:deploy-mlb-phase6-grading'`.

### 4. Confirm fleet_in_transition releases on schedule (5 days post-registration)

The new MLB regressor was registered 2026-05-17. Grace ends 2026-05-22. If MPD rows still don't exist on 5/22 (e.g., grading stuck), `_fleet_in_transition` returns None → `_fleet_blocked` re-engages → halt fires. Monitor:

```bash
bq query --use_legacy_sql=false 'SELECT game_date, model_id, decay_state, hr_7d, n_7d FROM `nba-props-platform.mlb_predictions.model_performance_daily` WHERE game_date >= CURRENT_DATE()-7 AND model_id LIKE "catboost_mlb_v2_regressor%20260517" ORDER BY game_date DESC'
```

Expected: at least one row by 5/19 morning (after Monday's grading). If empty on 5/22, investigate `data_processors/grading/mlb/main_mlb_grading_service.py` MPD writer path.

### 5. Carry-over from predecessor (still pending wall-clock time)

- New regressor HR over 5-7 days (predecessor verification item #4). First grades land 5/18 morning.
- MLB drought canary firing correctly (predecessor verification item #3) — should report 0 drought days starting 5/18.

## Open work — ordered by priority (per Forward Priority agent)

User explicitly deprioritized NBA work this session — focus is MLB.

### 🔥 Highest leverage (next 1-2 sessions)

1. **Edge-sweep + regime interaction pytest** (~4h). Codifies the 5/14-5/16 floor/cap collision class as CI guarantee. Highest incident-prevention-per-hour per Forward Priority agent. Build before more retrains so future model swaps have CI guardrails. File: `tests/mlb/test_exporter_with_regressor.py`. Parameterize `(edge, regime, home/away)` cross-product, assert non-empty edge window for each.

2. **MLB filter counterfactual evaluator + auto-demote** (~2 days). Direct port of `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py` to MLB. Creates `mlb_predictions.filter_counterfactual_daily` + `mlb_orchestration.mlb_filter_overrides` tables; aggregator reads at export. Would auto-reject the next "tighten MAX_EDGE based on N=8" decision. MLB has 654 graded picks (sufficient sample for top 3-4 filters).

3. **Three missing pre-commit hooks from predecessor "lessons learned"** (~2h total — never built):
   - **`--set-secrets` validator**: extend `validate_deploy_safety.py` to flag when service has >N mounted secrets and `--set-secrets` is used (prevents silent secret unmount). Predecessor session almost lost `OPENWEATHERMAP_API_KEY` this way.
   - **`download()` override detector**: scraper must override `start_download()` or `download_data()`, never `download()`. `mlb_weather` was dead code for 6+ months because of this; gap analysis agent found 2 more candidates (`mlb_ballpark_factors`, `mlb_statcast_pitcher`).
   - **Threshold-literal-drift grep**: detect duplicated literal numeric thresholds across N files. TIGHT_VEGAS_MAE_THRESHOLD drifted 1.7/1.5 between two files within one session before centralization.

### 🟡 Medium leverage

4. **MLB weekly_retrain CF** (~3-5 days). Today's manual `--window 365` retrain validated `train_regressor_v2.py` passes governance gates — perfect time to port `weekly_retrain/main.py`. Bundle with: registry model-swap event signaling to halt_state_writer (so `_fleet_in_transition` knows about the swap via a richer mechanism than "created_at < N days ago").

5. **Audit empty `mlb_precompute` tables** (4-8h). Gap analysis agent found 4 tables consumed by `pitcher_features_processor` but never populated:
   - `lineup_k_analysis` (predecessor handoff item #5 — already known)
   - `pitcher_innings_projection`
   - `pitcher_arsenal_summary`
   - `batter_k_profile`

   Features `f25-f44` in `pitcher_ml_features` are likely returning NULL/zero for all pitchers — model trains on holes. Either fix the processors or drop the features from the model.

6. **Investigate 2 more dead-`download()` scrapers**: `scrapers/mlb/external/mlb_ballpark_factors.py:447` and `scrapers/mlb/statcast/mlb_statcast_pitcher.py:123`. Same architectural bug as `mlb_weather`. `mlb_raw.statcast_pitcher_stats` is empty (last modified Jan 7). Fix or document as deprecated.

### 🟢 Architectural / longer term

7. **`halt_overrides` table** — schema references it; runbook documents it; writer doesn't actually respect it. Operational coupling agent flagged: manual MERGE into halt_state gets overwritten at next 5 AM run. No `?force_unhalt=true` query param on the writer. Build this when first real operator-override scenario arises.

8. **`/mlb-best-bets-config` skill** (~4h, predecessor item #4). Single pane of glass for MLB threshold state.

9. **MPD recovery lag** (~architectural). Today's race fix mitigates the most common case (fresh model), but the more general "grading writes MPD at 10 AM ET, halt re-evaluates at 5 AM ET next day" still creates a 24h+ recovery floor for any halt that should clear based on graded performance. Consider re-invoking halt_state_writer after grading completes.

10. **Isotonic calibration on regressor** (~1 day, predecessor item #8). Addresses model overconfidence at edge 1.0-1.5 OVER — the root cause `MAX_EDGE=1.25` cap is working around. Lower priority now that auto-halt + transition grace handle the operational symptoms.

### ❌ Explicitly deferring

- **NBA Round 2 prep** — user signaled NBA is done; defer indefinitely.
- **MLB edge-collapse halt check** — 5/14-5/16 was median edge (0.4-0.7), not collapsed. Adding an edge-collapse rule would be theater. Revisit only if drought episodes accumulate N≥30 with non-pick_drought signatures.
- **Removing the 3 stale 5/17 picks** — they grade tomorrow and provide the new regressor's first validation data. Today's halt_state row honestly reflects "would have halted based on past evidence" while picks reflect "operator-approved late-generate."

## Operational state at handoff

- **MLB halt envelope is live end-to-end.** Writer → halt_state BQ table → MLB pick-gen + Phase 6 JSON.
- **Tomorrow's 5/18 halt should auto-clear** based on (a) `_fleet_in_transition` suspending `fleet_blocked` for ~5 more days, (b) `most_recent_is_drought=False` clearing pick_drought because 5/17 shipped 3 picks.
- **New MLB regressor in production:** `catboost_mlb_v2_regressor_36f_20260517`, registered 2026-05-17 19:35 UTC, `is_production=TRUE, enabled=TRUE`. Worker revision past `00084-khw`. First graded data lands 5/18 morning.
- **NBA halted between rounds** since 2026-05-10 (`between_rounds`). No NBA work planned this session or next.
- **All other infrastructure from predecessor session** (admin dashboard, bias decay CF, OWM secret, `mlb-weather-pregame` scheduler) still operational.
- **MEMORY note updated** in `~/.claude/projects/-home-naji-code-nba-stats-scraper/memory/mlb-drought-fixes-2026-05-17.md` — predecessor's topic file; this session's fixes append to it implicitly via commits.

## What we learned (process notes)

1. **6-agent post-deploy reviews caught a critical race that pre-deploy testing missed.** My initial deploy of `9a7c2cf4` was 30 minutes from being self-defeating: `fleet_blocked` would have fired tomorrow morning for purely procedural reasons (MPD row lag) on a freshly-validated model. Three independent agents (devil's advocate, threshold review, forward priority) converged on the same finding within 10 minutes. **Lesson: every "we shipped a halt rule" deserves a same-session devil's-advocate run** — the rule's behavior on the day AFTER deploy can differ qualitatively from the day OF deploy.

2. **N=1 fleet semantics are degenerate.** "All models in BLOCKED state" is identity-equivalent to "the one model is BLOCKED" when fleet size is 1. We've now encoded that as a system-wide halt, which double-counts the signal because BLOCKED already self-throttles via low confidence / edge compression. Should be noted in code comments next to `_fleet_blocked` — done in `80ad1c60`.

3. **Operational coupling reviews surface invisible coverage gaps.** All.json missing halt envelope, no `halt_overrides` table, MPD recovery lag — all real gaps that the implementation worked-as-intended view doesn't surface. Worth doing this style of review for any new system-wide control surface.

4. **"Fail-open" vs "fail-closed" is per-layer, not per-system.** Pick-gen exporter fails open (telemetry shouldn't block picks). Publishing layer fails closed (envelope visible). Both correct; the asymmetry is intentional. Documented in `_read_halt_envelope` docstring (`fdd6f4ac`).

5. **The first agent run challenged the obvious framing.** Code review found the implementation correct; devil's advocate argued the WHOLE PRIORITY was wrong. Both perspectives were valuable. Devil's advocate ultimately didn't convince — we still shipped halt_state — but it surfaced the race condition that would have invalidated the work without the in-transition grace clause.

## Key references

- **Predecessor handoff** (read first): [`2026-05-17-mlb-drought-fix-retrain-and-antifragility.md`](2026-05-17-mlb-drought-fix-retrain-and-antifragility.md)
- **halt_state_writer main code:** `orchestration/cloud_functions/halt_state_writer/main.py` (now 770 lines; `_fleet_in_transition` at line ~290, `_fleet_blocked` at ~395, `_mlb_pick_drought` at ~480)
- **MLB pick-gen halt gate:** `ml/signals/mlb/best_bets_exporter.py:430-485` (canonical_halts set + gate logic)
- **MLB Phase 6 JSON halt fields:** `data_processors/publishing/mlb/mlb_best_bets_exporter.py:90-110` (generate_json) and `:541-562` (export_all)
- **Halt state runbook:** `docs/02-operations/runbooks/halt-mode-operations.md` (NOTE: needs update for new `pick_drought` reason + `fleet_in_transition` metric)
- **Deploy script:** `orchestration/cloud_functions/halt_state_writer/deploy.sh --cf-only`. CF is NOT auto-deployed via cloudbuild.

## First message for the next session

> Read `docs/09-handoff/2026-05-17-2-halt-state-mlb-extension-and-fleet-transition-fix.md`.
>
> Start with verification item #1 (confirm tomorrow morning's writer cleared the halt) and item #2 (confirm MLB picks shipped Monday). If either fails, the diagnostics are in the Verification section.
>
> Then pick the highest-priority open work item. Top 3 by Forward Priority agent leverage:
>
> 1. **Edge-sweep + regime pytest** (~4h) — codifies the 5/14-5/16 floor/cap collision in CI before more model swaps land. Highest incident-prevention-per-hour.
> 2. **MLB filter CF + auto-demote** (~2 days) — prevents the next "tighten threshold on N=8 evidence" regression class.
> 3. **Three missing pre-commit hooks** (~2h total) — `--set-secrets` validator, `download()` override detector, threshold-literal-drift grep. Absent from the open-work doc until this handoff.
>
> The 4 empty `mlb_precompute` tables (item #5) is a strong "quick win" too if you want a smaller-scope task.
>
> Note: tomorrow (5/18) MLB picks should ship normally. If they don't, the first place to look is `_fleet_in_transition` and `halt_metrics` in the halt_state row.
