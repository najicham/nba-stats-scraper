# Session Handoff — 2026-05-11 (Evening) — Pipeline State Drain + MLB Improvement Plan

**Status at end of session:** Yesterday's Fix #2 (Phase 2-6 backfill dispatch) shipped, smoke-tested, and is in production. Three small cleanups landed. Two frontend redesigns shipped on playerprops.io after fixing a 3-day-stale Vercel deploy chain. A 3-agent investigation of MLB improvements produced a tiered plan, summarized below. Demo readiness unchanged.

**Predecessors:**
- `docs/09-handoff/2026-05-11-PIPELINE-STATE-AGENT-REVIEW-FOLLOWUP.md` (afternoon — planner path + resolver hardening)
- `docs/09-handoff/2026-05-11-PIPELINE-STATE-FOLLOWUP-HANDOFF.md` (morning — ParameterResolver gap + Fix #1)

---

## What shipped this session

### Backend (`nba-stats-scraper`)

| Commit | Subject |
|--------|---------|
| `127a00df` | yesterday's agent-review follow-ups (planner path + resolver hardening, packaged) |
| `b4dfd016` | **Fix #2** — Phase 2-6 dispatch in pubsub_subscriber |
| `54d08d56` | Cleanup — payload regex validation + resolver unit test + legacy `BigQueryClient` removed |

Subscriber CF deployed twice: rev `-00007-koh` (Fix #2), then `-00008-puj` (regex validation).

### Fix #2 smoke-test outcomes (revision `-00007-koh`)

| Phase | Date | Output | Result | Time |
|-------|------|--------|--------|------|
| 3 | 2026-04-19 | `team_defense_game_summary` | ✅ EXPECTED + `pubsub_backfiller_success` | ~3.5 min |
| 4 | 2026-05-03 | `ml_feature_store_v2` | ✅ EXPECTED + `pubsub_backfiller_success` | ~4 min |
| 5 | 2026-04-19 | `player_prop_predictions` | ⚠️ DEGRADED — coordinator 503 (`analytics_coverage_pct=70%`) — **correct behavior**, gap_detector will retry once Phase 3 backfills | <30s |
| 6 | 2026-04-19 | `results_json` | ✅ EXPECTED + `pubsub_backfiller_success` (Pub/Sub publish OK) | <30s |

Phase 6 refuses destructive output_types (`signal_best_bets_json`, `picks_json`) at the helper layer — these would overwrite live JSON with empty picks for historical dates (Session 481 incident). Ops handles those manually.

### Frontend (`/home/naji/code/props-web`)

| Commit | Subject |
|--------|---------|
| `937e1e8` | NBA off-season state + `–` for empty record windows |
| `a04d40c` | null-guard `gameTime` in PlayerCard — **unblocked Vercel chain** (3 days of failed builds) |
| `4485667` | NBA off-season banner + Ultra OVER flex (replace dead empty state) |

**Important:** Before `a04d40c`, every commit pushed to `props-web` main since 2026-05-09 was failing the Vercel build silently. Site had been serving a stale build for 3 days. Verify any future props-web change actually deployed via:
```
gh api repos/najicham/props-platform-web/commits/<sha>/status | jq '.statuses[].state'
```

---

## Live state at session end

### NBA Phase 1 queue (drain progress vs morning snapshot)

```
                 EXPECTED  COMPLETE  EMPTY_OK  FAILED  DEGRADED
yesterday morn      677       —        —        450       —
yesterday eve       470      373      289        49        4
tonight             347      477      289        49       23
```

Phase 1 NBA drained 123 rows in the last 24h via the resolver fix. 49 FAILED rows remain — all dated 2025-10-21 → 2025-11-02 (early-season failures from pre-redeploy attempts, attempts=3 already). A simple UPDATE could re-eligibilize them; left for next session.

### Subscriber CF logging glitch (rev `-00007-koh` and `-00008-puj`)

`logger.info()` calls do not surface in Cloud Logging on the new revisions despite BQ writes proving the code is executing. 131 log entries since the deploy, zero substantive messages — all are container-lifecycle noise (TCP probe, autoscaling, no-available-instance). Old revision `-00006-hac` did emit substantive log lines yesterday. Root cause unknown. **Not a functional issue** (BQ row updates are the actual telemetry), but it makes operational debugging harder. Worth a fresh look.

### `PROCESSOR_TIMEOUT=600s` vs CF timeout (540s)

Phase 3 + Phase 4 dispatches block on the processor's synchronous response. Phase 3 took 3.5min in the smoke test, Phase 4 took 4min — both well under the CF timeout. But a slow run (date with many games + heavy precompute) could exceed 9 min and the CF would die mid-flight, leaving BQ unwritten. Worth a follow-up: drop `PROCESSOR_TIMEOUT` to 480s.

### Triage carry-forwards

- **36 Phase 1 NBA `nbac_*` FAILED rows** (2025-10-21 → 2025-11-02, `attempts=3`, `source=gap_detector`, updated 16:15-17:15 UTC pre-resolver fix). Reset to EXPECTED would unstick them; the resolver works now.
- **~99 Phase 6 NBA `signal_best_bets_json` / `picks_json` rows** in Oct-Nov 2025 — destructive types refused by `_dispatch_phase6`. Should be marked `EMPTY_OK` (analogous to yesterday's preseason triage). These will keep escalating until triaged.

---

## MLB improvement plan (3-agent investigation, 2026-05-11)

Three agents ran in parallel against the live MLB system. Their findings converge tightly. The biggest insight is structural:

> **The MLB system is structurally similar to NBA but lacks the maturity of NBA's signal / feature / retrain infrastructure. Recent fixes (grading Session 520, retrain Session 524) have masked deeper systemic issues.**

### The leaks (Agent 1 — performance diagnosis, N=60 graded BB picks last 30d, 60% HR)

1. **The model over-predicts high-K pitchers (HIGH severity).** Predicted Ks ≥ 6.5 = **28.6% HR (N=7)**, signed_error +1.01 (under-shot actuals by ~1 K). Predicted Ks < 5.5 = 72-75% HR. The model wins on mid/low-K starters and loses on aces.
2. **Edge 1.0-1.5 is the worst tier, not the best.** Edge 0.5-1.0 = 70.8% HR (N=24). Edge 1.0-1.5 = **35.7% HR (N=14)**. Higher "edge" correlates with model over-shoot, the opposite of NBA.
3. **Specific pitcher losers:** Sandy Alcantara 0-5 (pred 6.12 vs actual 3.4), Kevin Gausman 0-2 (pred 6.65 vs actual 2.5), Cam Schlittler 0-2, Jack Leiter 0-2. Pattern: ace-tier names where the model trusts K-rate priors.
4. **Dead/backward signals:** `chase_rate_over` 36.4% HR (N=22), `high_csw_over` 38.1% HR (N=21). Actively losing.
5. **Pre-retrain bias real, post-retrain unconfirmed.** Apr 9 – May 8: 50.8% HR (N=63), +0.69 K over-prediction. May 9-11 post-retrain: 80% HR (N=5), -0.52 K. N=5 is too thin to declare victory.

### The feature/signal gaps (Agent 2 — landscape inventory)

1. **11 of 35 features (31%) are 100% inert in the feature store** — feature contract reads them but processor wires them to zero. The "36-feature" model is effectively a ~24-feature model. Dead features include:
   - `f18_game_total_line`, `f19_team_implied_runs` (game-context — read by supplemental_loader, never plumbed into precompute)
   - `f28_umpire_k_factor` (umpire data fresh but join broken)
   - `f30_velocity_trend`, `f31_whiff_rate`, `f32_put_away_rate` (Statcast arsenal — fresh in `statcast_pitcher_daily`, join points to `pitcher_arsenal_summary` which is 100% zero)
   - `f11/13/14` (split features dead — `bdl_pitcher_splits` last modified 2026-01-15)
   - `f26/27/33/34` (lineup features all zero)
2. **NBA's strongest signal class has no MLB analog.** `book_disagree_over` (NBA 93% HR) — `bp_pitcher_props` (12+ books) and `oddsa_pitcher_props` both exist, never differenced.
3. **32 shadow signals + 5 active signals never fire** (zero rows in `signal_health_daily`). The pick stack draws from ~14 signals.
4. **6 negative filters in MLB vs 25 active + 11 obs in NBA.** Missing cold-shooting analogs, line-rose blockers, low-line blockers, team-cap, calendar/day-of-week filters.
5. **Unused fresh data:**
   - `mlb_game_feed_pitches` (884K rows, pitch-by-pitch Statcast)
   - `bp_batter_props` + `oddsa_batter_props` (775K + 635K rows) — could power true bottom-up lineup-K estimate
   - `catcher_framing` populated but only shadow signals consume it

### The training cadence (Agent 3 — model + training process)

1. **No auto-retrain.** "biweekly-retrain" scheduler is a Slack reminder, no automation. Last retrain was manual Apr 11 (Session 524). NBA's `weekly-retrain` CF has no MLB analog.
2. **Training window relies on a human remembering a flag.** Default 120 days excludes April. Operator-prescribed `--training-start 2024-04-01` is the fix — but if forgotten, the +1.15 K bias regresses.
3. **Single-model fleet.** Worker code supports v1, v1.6_rolling, v2_regressor, ensemble_v1, LightGBM v1, XGBoost v1. Only `catboost_v2_regressor` is enabled (`MLB_ACTIVE_SYSTEMS`). No cross-model signals possible (no combos, no book_disagreement-style cross-checks), no drift early-warning. The Apr 1-9 grading bug + April bias both happened in a single-model fleet with nothing to flag drift.
4. **Walk-forward harness exists but unused.** `scripts/mlb/training/walk_forward_simulation.py` was never used to validate the 120-day default vs alternatives.

### Tiered improvement plan (synthesis)

**Tier 1 — High leverage, low effort (do first, ~1-2 days each):**

1. **Wire the 11 dead features.** Fix the supplemental→precompute join in `data_processors/precompute/mlb/pitcher_features_processor.py`. Plausibly the largest single model improvement available — the over-prediction bias on high-K pitchers may partially stem from the model defaulting to K-rate priors when context features are zero. ~1 day. **Highest ROI single change.**
2. **Block / demote `chase_rate_over` + `high_csw_over`.** Both actively losing (36% / 38% HR). Add to negative filter list or move to shadow. ~30 min.
3. **Anchor the training window.** In `scripts/mlb/training/train_regressor_v2.py::resolve_dates()`, default to `min(today − 120d, last_april_1)`. Makes April-bias regression impossible. ~1 hour.

**Tier 2 — Mid leverage, mid effort (after Tier 1 lands):**

4. **Add `book_disagree_over_pitcher` signal.** Port NBA pattern using `bp_pitcher_props` std vs Odds API consensus. ~1 day. NBA's strongest non-combo signal at 93% HR has no MLB twin.
5. **Promote one challenger model to shadow.** Train LightGBM v1 on the same 18-month window, gate identically, enable via `MLB_ACTIVE_SYSTEMS`. Buys cross-model signals + drift early-warning. ~1-2 days.
6. **MLB weekly-retrain CF.** Fork or extend `orchestration/cloud_functions/weekly_retrain`. Run Mondays 5 AM ET during Mar-Oct. Wire same model_registry + GCS upload path the script already prints. ~1 day.

**Tier 3 — Longer-horizon:**

7. Real `line_movement_over` signal (multi-snapshot history loader fix).
8. True bottom-up K from `bp_batter_props` (replace static `batter_k_profile`).
9. Day-of-week / calendar filter set (MLB has none).
10. Confirm the high-K-pitcher over-prediction bias is actually fixed by the new model (need N≥30 post-May-9 picks).

### Key files for next session

- Training: `scripts/mlb/training/train_regressor_v2.py`, `scripts/mlb/training/walk_forward_simulation.py`
- Features: `data_processors/precompute/mlb/pitcher_features_processor.py`, `predictions/mlb/supplemental_loader.py`, `predictions/mlb/pitcher_loader.py`
- Signals: `ml/signals/mlb/signals.py` (1975 lines, 56 classes), `ml/signals/mlb/registry.py` (code-based, no YAML)
- Worker: `predictions/mlb/prediction_systems/` (6 predictor classes; only catboost_v2 enabled)
- Tables: `mlb_predictions.prediction_accuracy`, `mlb_predictions.signal_best_bets_picks`, `mlb_predictions.signal_health_daily`, `mlb_predictions.model_registry`, `mlb_precompute.pitcher_ml_features`

### Open questions worth answering early in the next session

1. Does the new model (post-Session 524, May 9) actually correct the high-K over-prediction, or just shift bias uniformly? Pull MLB picks since May 9, split by predicted-Ks bucket.
2. Why is `chase_rate_over` losing — feature wiring bug, or early-season NULL artifact like `high_csw_over`?
3. Is the 11-dead-feature fix mechanical (a join change) or does it require new processor logic? Read `pitcher_features_processor.py` first.
4. What's the right MLB governance gate for HR? Script uses 55% at edge 0.75; NBA uses 53% at edge 3+. Was 55% walk-forward validated or copy-pasted?

---

## Things NOT changed this session (intentionally)

- The 49 Phase 1 NBA FAILED preseason rows — they look fixable but I wanted explicit sign-off before doing more BQ DML.
- The Phase 6 destructive output_types — `_dispatch_phase6` refuses them by design; manual triage required.
- The subscriber logging glitch — diagnosed enough to confirm not functional; full root cause TBD.
- The `PROCESSOR_TIMEOUT` mismatch — flagged, change is a one-liner but I didn't want to deploy a 4th time today.

---

## Recommended next-session opening sequence

```bash
# 1. Verify queue drain continued overnight
bq query --use_legacy_sql=false --format=pretty --project_id=nba-props-platform '
SELECT phase, status, COUNT(*) AS n
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE sport="nba" GROUP BY phase, status ORDER BY phase, status'

# 2. Check Fix #2 is processing the queue cleanly (look for HTTP 500s post-deploy)
gcloud logging read 'resource.type="cloud_run_revision" \
  resource.labels.service_name="backfill-pubsub-subscriber" \
  textPayload:"HTTP 500" timestamp>="2026-05-11T22:00:00Z"' \
  --project=nba-props-platform --limit=10

# 3. Start MLB Tier 1 work — read pitcher_features_processor first
$EDITOR data_processors/precompute/mlb/pitcher_features_processor.py
```

---

## Files touched this session

Backend:
- `orchestration/__init__.py`, `orchestration/parameter_resolver.py`, `orchestration/cloud_functions/expected_outputs_planner/main.py`, `shared/utils/bigquery_client.py` (deleted), `shared/utils/__init__.py`, `shared/utils/bigquery_utils.py`
- `orchestration/cloud_functions/scraper_gap_backfiller/main.py`, `orchestration/cloud_functions/scraper_gap_backfiller/requirements.txt`, `orchestration/cloud_functions/scraper_gap_backfiller/deploy-pubsub-subscriber.sh`
- `scripts/verify_database_completeness.py`
- `tests/unit/orchestration/test_parameter_resolver.py` (+ pytest installed in `.venv`)

Frontend (separate repo `/home/naji/code/props-web`):
- `src/lib/best-bets-types.ts`, `src/components/best-bets/RecordHero.tsx`, `src/components/cards/PlayerCard.tsx`, `src/app/[sport]/best-bets/page.tsx`
