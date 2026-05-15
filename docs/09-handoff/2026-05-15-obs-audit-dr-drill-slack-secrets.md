# Session Handoff — 2026-05-15 — Obs-filter audit + DR drill + Slack→Secret Manager

**Primary work this session:** four orthogonal bites of follow-up to the 2026-05-14 Path A/B/C foundations work. Built directly on yesterday's predecessor (`2026-05-14-path-a-and-b-foundations.md`) — start there for context if anything below is unclear.

## TL;DR

1. **C — Obs filter audit (NBA off-season).** Five-week 2026-03-04 → 2026-04-07 BQ data window reviewed in `ml/signals/aggregator.py`. Promoted 3, removed 1, refreshed the audit comment block. Live picks unaffected (NBA halted until June 3). Commit `0fa94ed8`.
2. **E — DR runbook drill.** Snapshot-restore path validated end-to-end against `ml_feature_store_v2` (1 GB / 147,340 rows): **CLONE completed in 3 s**, schema and row counts matched live exactly. Added `bin/operations/dr_restore_snapshot.sh` helper; bumped `disaster-recovery-runbook.md` to v1.1 with snapshot-first path. Commit `314829a7`.
3. **B finish — `data_quality_alerts` deploy.sh applied live + payload bug fix.** Yesterday's check-in but never-run deploy script applied via `bash deploy.sh prod`. First post-migration scheduler trigger surfaced a pre-existing payload bug (`{"type":"section","fields":[]}` → Slack 400 `invalid_attachments`) that was masked for 7+ days by the empty env vars. Fix verified end-to-end: scheduler at 20:52:34 UTC returned HTTP 200, zero ERROR logs post-fix. Commit `b5305393`.
4. **A — Slack→Secret Manager Tier 1 migration.** 10 of 14 target CFs migrated live via `gcloud run services update --update-secrets / --remove-env-vars`. 5 deploy scripts updated to use `--set-secrets` so manual re-deploys preserve the migration. **4 CFs deferred** (Tier 2/3 — need user input). Commit `e05c1957`.

## What landed (commits + files)

### Commit `0fa94ed8` — obs-filter audit (C)

| File | Change |
|---|---|
| `ml/signals/aggregator.py` | Promoted to active blocks: `under_star_away` (CF HR 38.8%, N=49), `line_jumped_under_obs` (41.4%, N=58), `tanking_risk_obs` (40.0%, N=30). Removed `high_spread_over_would_block` (80.6%, N=31 — strictly worse than Session 514's 63.6%). Audit block at L243-296 fully rewritten with today's actions + deferred-filter list (low-N or borderline). |
| `tests/unit/signals/test_aggregator.py` | Refreshed `expected_keys` in `test_empty_predictions_filter_summary` (test was already out of sync). Renamed `test_under_star_away_no_longer_blocks` → `test_under_star_away_blocks`. Updated `test_line_jumped_under_tracked` to new BQ name (`_obs` suffix preserved for CF HR history continuity). Net pytest delta: **−1 failure** vs baseline. |

Auto-deploy fired 10 builds (phase6-export, prediction-coordinator/worker, live-export, post-grading-export, mlb-prediction-worker, mlb-phase6-grading + 2 sub-builds); all **SUCCESS**. Algorithm version unchanged (no `v*` bump) because NBA is halted — filters take effect on the next NBA pick run (June 3).

### Commit `314829a7` — DR drill (E)

| File | Change |
|---|---|
| `bin/operations/dr_restore_snapshot.sh` | **New.** Helper that auto-discovers latest snapshot, prompts before executing, clones to `*_dr_test_<date>` (24h auto-expiry), prints validation query. Supports `DATASET` / `LIVE_DATASET` env for MLB. |
| `docs/02-operations/disaster-recovery-runbook.md` | v1.0 → v1.1. Scenario 1 Step 4A rewritten: snapshot restore now the **primary path**; GCS-export path demoted to legacy with status note. Drill result + helper usage + time-travel fallback documented. Version table updated. |

Drill data: snapshot `ml_feature_store_v2_20260515_150003` → `ml_feature_store_v2_dr_test_20260515`. CLONE took 3 s (metadata-only). Row count = 147,340 (matched). Distinct players = 1,115 (matched). Date range 2021-11-02 → 2026-04-26 (matched). Schema diff empty. Test table cleaned up.

### Commit `b5305393` — Slack payload fix (B finish)

| File | Change |
|---|---|
| `orchestration/cloud_functions/data_quality_alerts/main.py` | Conditionally append the third `section` block only when `fields` is non-empty. Slack rejects `{"type":"section","fields":[]}` as `invalid_attachments` / HTTP 400. Bug was masked for 7+ days because the env vars storing the webhook URLs were empty strings — `send_slack_alert` short-circuited at "No Slack webhook configured" before the payload ever reached Slack. The first post-migration scheduler trigger surfaced it. |

Live deploy of `data_quality_alerts` ran in this session via `bash orchestration/cloud_functions/data_quality_alerts/deploy.sh prod` (yesterday's check-in but never-executed script). Webhook secrets `slack-webhook-monitoring-error` / `slack-webhook-monitoring-warning` are now bound via `secretEnvironmentVariables`. Scheduler `data-quality-alerts-job` (daily 7 PM ET) intact.

### Commit `e05c1957` — Path A Tier 1 (A)

**10 NBA/MLB CFs migrated live via `gcloud run services update`:**

| CF | env var | secret |
|---|---|---|
| analytics-quality-check | SLACK_WEBHOOK_URL_WARNING | slack-webhook-monitoring-warning |
| filter-counterfactual-evaluator | SLACK_WEBHOOK_URL_ALERTS | slack-webhook-monitoring-warning |
| morning-deployment-check | SLACK_WEBHOOK_URL_WARNING | slack-webhook-monitoring-warning |
| nba-monitoring-alerts | SLACK_WEBHOOK_URL | slack-webhook-url |
| phase4-timeout-check | SLACK_WEBHOOK_URL | slack-webhook-url |
| pipeline-health-monitor | SLACK_WEBHOOK_URL | slack-webhook-monitoring-error |
| pipeline-reconciliation | SLACK_WEBHOOK_URL | slack-webhook-url |
| slack-reminder | SLACK_WEBHOOK_URL | slack-webhook-url-reminders |
| stale-running-cleanup | SLACK_WEBHOOK_URL | slack-webhook-url |
| validation-runner | SLACK_WEBHOOK_URL | slack-webhook-url |

**5 deploy scripts updated** to use `--set-secrets` so manual re-deploys preserve the migration:
- `bin/deploy/deploy_stale_cleanup.sh`
- `bin/deploy/deploy_validation_runner.sh` (SLACK_WEBHOOK_URL only)
- `bin/orchestrators/deploy_phase4_timeout_check.sh`
- `orchestration/cloud_functions/weekly_retrain/deploy.sh`
- `orchestration/cloud_functions/mlb_regime_monitor/deploy.sh` (was untracked — now in git with TODO for signals secret)

**Key technique:** `gcloud run services update` (not `gcloud functions deploy`) for env-var/secret swaps on Gen2 CFs. Avoids the source-rebuild path entirely — each migration took ~9 s instead of ~3 min. Pattern:

```bash
gcloud run services update <FUNC> \
  --region=us-west2 --project=nba-props-platform \
  --update-secrets="<KEY>=<secret>:latest" \
  --remove-env-vars=<KEY>
```

`cloudbuild-functions.yaml` doesn't touch Slack env vars, so the migration is durable across auto-deploys for these CFs.

## Verifications to run at session start

1. **Builds clean** (today's 4 commits + ongoing):
   ```
   gcloud builds list --region=us-west2 --project=nba-props-platform --limit=15 \
     --format="table(id,status,createTime)"
   ```
   Expect SUCCESS or WORKING on everything since `e05c1957`.

2. **Path A migrations still in place** (no regression from any auto-deploy):
   ```
   for cf in analytics-quality-check filter-counterfactual-evaluator morning-deployment-check \
            nba-monitoring-alerts phase4-timeout-check pipeline-health-monitor \
            pipeline-reconciliation slack-reminder stale-running-cleanup validation-runner; do
     state=$(gcloud functions describe $cf --gen2 --region=us-west2 \
       --project=nba-props-platform \
       --format="value(serviceConfig.secretEnvironmentVariables)" 2>/dev/null \
       | grep -c slack-webhook)
     echo "$cf: $state secret bindings"
   done
   ```
   Each should report at least 1 binding.

3. **`data_quality_alerts` Slack alerts still healthy** (no ERROR logs since the b5305393 redeploy):
   ```
   gcloud logging read 'resource.labels.service_name="data-quality-alerts" \
     AND severity>=ERROR AND timestamp>="2026-05-15T18:39:00Z"' \
     --project=nba-props-platform --limit=5
   ```
   Empty result = healthy. The 7 PM ET scheduler tick is the next real run.

4. **Obs-filter changes harmless during halt** (NBA still halted, no NBA picks):
   ```
   bq query --use_legacy_sql=false \
     "SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` \
      WHERE game_date = CURRENT_DATE()"
   ```
   Should be 0. MLB picks unaffected (filters are NBA-only). MLB pipeline still publishing daily.

## Open work — operational housekeeping (small)

These finish what today started. None are urgent (NBA halted, MLB stable).

### A. Path A Tier 2/3 — finish the Slack migration (4 CFs)

The remaining 4 CFs / env vars couldn't be migrated today because the destination secret either doesn't exist or the URL didn't match anything in Secret Manager:

| CF | env var | issue | recommendation |
|---|---|---|---|
| `shadow-performance-report` | `SLACK_WEBHOOK_URL` | URL doesn't match any existing secret. Distinct URL: `B09HLQFABL2/iok...` | Decide: create `slack-webhook-shadow-reports`? Or reuse an existing channel? |
| `validation-runner` | `SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH` | URL doesn't match: `B0AD1SZPQ6A/j4x...` | Create `slack-webhook-orchestration-health`. |
| `mlb-regime-monitor` | `SLACK_WEBHOOK_URL_SIGNALS` | env var is **empty** (already broken — Slack alerts silently no-op) | Create `slack-webhook-signals` for `#nba-betting-signals`. The `deploy.sh` already has a TODO comment pointing here. |
| `weekly-retrain` | `SLACK_WEBHOOK_URL` | env var is **empty** (already broken) | Already fixed in `weekly_retrain/deploy.sh` — next manual deploy will migrate it. Or: `gcloud run services update weekly-retrain --update-secrets="SLACK_WEBHOOK_URL=slack-webhook-url:latest" --remove-env-vars=SLACK_WEBHOOK_URL` (single command, ~9 s). |

`weekly-retrain` is the only one that can move without user input — just run that one-liner.

### B. Apply the Path B Slack payload fix to any other CFs that use the same pattern

The empty-`fields` Slack 400 bug isn't unique to `data_quality_alerts`. Other CFs that build Slack `attachments` → `blocks` payloads with conditional `fields` could have the same hidden bug — and now that they're on real webhooks (via Path A migration), they could start firing 400s.

Quick audit:
```
grep -l '"type": "section"' orchestration/cloud_functions/**/main.py
grep -rA20 '"type": "section"' orchestration/cloud_functions/ | grep -B5 '"fields"'
```

If you find any, the fix is the same: `if fields: blocks.append({"type":"section","fields":fields[:10]})`.

### C. Side discovery — PUSHOVER credentials in `stale-running-cleanup`

While migrating `stale-running-cleanup`, observed:
```
PUSHOVER_APP_TOKEN=32ey3yg3r9
PUSHOVER_USER_KEY=u31p6rtwpvkpqq4nmtzsj5r9sb21oo
```

Both plaintext in env vars. Secret-manager candidates for the same migration pattern. Low priority but trivial to do alongside the Path A finish.

### D. Path D — MLB auto-retrain CF (1-2 days)

Yesterday's predecessor flagged this. Clone the `weekly_retrain` CF pattern for MLB:
- Source: `scripts/mlb/training/train_regressor_v2.py` with `--training-start 2024-04-01` baked in (per Session 524 — old May-Sep 2025 model had +1.15 K OVER bias).
- Governance gates: MLB-specific (HR > 53% at edge 0.75/1.25, OVER bias < ±0.5, N >= 15 graded).
- Trigger: weekly Monday morning ET.
- MLB grading was fixed Session 520; data is healthy.

## Open work — predictive-system improvements (bigger, higher leverage)

The user explicitly flagged that the next session should also continue improving the prediction system, not just close out housekeeping. The off-season window (until June 3) is the right time. Ranked by leverage:

### 1. Investigate the 2025-26 NBA anomaly (highest leverage)

Per MEMORY (Session 514): "**2025-26 was uniquely broken from day one** — Early season 55.9% vs historical 68-70%. Model quality issue, not seasonal dynamics."

We never figured out why. The four prior seasons (2021-22 through 2024-25) all hit 62-64% HR through April; only 2025-26 underperformed. **If we don't understand it, we can't prevent it next year.**

Hypotheses worth testing (all replayable on the BQ snapshot we now have):
- Feature drift early-season: are vegas lines or shooting variance distributions different from prior Octobers?
- Model fleet composition: was the Oct-Dec fleet over-indexed on a particular family (LGBM clones — Session 487)?
- Training-window contamination: did the rolling 56-day window absorb late 2024-25 noise into Nov 2025 models?
- Specific feature collapse: `feature_55 over_rate_last_10` or `feature_56 margin_vs_line_avg_last_5` (V16 additions) may have been mis-calibrated for the season.

Tools available: `scripts/nba/training/discovery/{feature_scanner,combo_tester,archetype_analyzer,expanded_scanner}.py` operate on 5-season data and can do this kind of decomposition. `ml/experiments/experiment_harness.py` for ad-hoc training experiments. `model_performance_daily` and `signal_health_daily` have backfilled daily metrics back to early 2025-26.

### 2. MLB system gaps — real value when the season heats up

MEMORY flags two persistent MLB gaps that are **operational blockers**, not nice-to-haves:

- **`mlb_precompute.lineup_k_analysis` empty.** Processor exists, wired into precompute service, Phase 4→5 lists it as a dependency, but 0 rows ever written. A1 lineup features confirmed vapor; investigation hooks in 2026-05-14 handoff Session 1→2. Of `pitcher_ml_features`'s 6 lineup-derived features (f25/f26/f27/f33/f34/f44), only f25 has any nonzero values (119/946). **This is silently neutering MLB predictions.**
- **MLB weather pipeline blocked.** `mlb_weather` scraper requires `OPENWEATHERMAP_API_KEY`. Not in Secret Manager, not set on `mlb-phase1-scrapers`. Without it, the scraper raises (per Path A change yesterday) so weather rows never write. Weather signals (`WeatherColdUnderSignal`, `ColdWeatherKOverSignal`) never fire. `predictions/mlb/supplemental_loader.py:230` already wired for weather; just needs source rows. **Cold weather is a strong UNDER tell for K props.**

Get OPENWEATHERMAP_API_KEY → `gcloud secrets create OPENWEATHERMAP_API_KEY` → `--update-secrets` on phase1 → add `mlb-weather-pregame` scheduler. ~1 hour of work for a real signal.

### 3. Filter audit follow-up

Today promoted 3 / removed 1 of ~19 obs filters. The deferred list:

- `signal_stack_2plus_obs` (N=117, CF HR 48.7%) — coin flip, big N but not actionable yet
- `opponent_under_block` (N=19, CF HR 57.9%) — N just below 20 floor; one more week of data would settle it
- `opponent_depleted_under` (N=18, CF HR 55.6%) — same
- `high_skew_over_block_obs` (N=15, CF HR 73.3%) — high HR but low N
- `bench_under_obs` (N=12, CF HR 66.7%) — high HR but low N
- `mid_line_over_obs` (N=11, CF HR 54.5%) — right at threshold
- ~13 others (N < 10 each)

These can't move until the NBA data window grows. **Pre-season (mid-Oct) is the natural re-audit point** — by then 2026-27 will have started and the late-2025-26 data will be aged out anyway.

### 4. Per-model pipeline tuning

Algorithm version is currently `v496_home_over_revert_batch_subset` (Path B added `v497_health_aware_weights_line_rose_block` plus the today's filter changes — bump pending). Signal weights, rescue priorities, regime thresholds could all be reviewed against 5-season data. Lower leverage than items 1-2 but a natural place to spend a session.

### 5. Per-archetype profitability (from player_deep_dive)

Session 417 found `low_line + low_variance UNDER = 62.0% HR (N=819)` — best archetype. Bounce-back OVER is `AWAY only` (Session 417). These archetype rules are not currently encoded as signals. **Translating profitable archetypes into signals could push BB pipeline HR up another 2-3 pp.**

## System state at handoff

- **NBA halted between_rounds** since 2026-04-07. Next NBA games **June 3** (~19 days). Edge-based auto-halt is **active** (avg edge 1.45 < 5.0 threshold). Zero NBA picks expected until June.
- **MLB in season, low-edge.** May 14 had 0 BB picks from 15 predictions (all OVER edges 0.6-1.0, below the 1.25 away threshold). No model in crisis. May 13 added a 4:30 PM ET late-export scheduler to catch late scratches.
- **Snapshot CFs running daily** at 11 AM ET for both NBA (`nba_predictions_backups`) and MLB (`mlb_predictions_backups`). 30-day retention. Restore drill validated.
- **All Path A/B/C foundations from 2026-05-14 still live.** New gates (`min_hr_edge5=55`) haven't fired (no retrains during halt). Tonight content guard is armed.
- **Algorithm version:** `v497_health_aware_weights_line_rose_block` in code; live picks would be `v496_*` (deployed pre-Path-B-Week-3). Re-evaluate version bump when picks resume.

## Memory updates suggested

These belong in topic files (MEMORY.md is over 200 lines and getting truncated):

- **`gcloud run services update` pattern for Gen2 CF env/secret swaps** — way faster than `gcloud functions deploy` (9 s vs 3 min). No source rebuild. Use for Path A finish and similar work.
- **Slack `{"type":"section","fields":[]}` returns 400** — `invalid_attachments`. Conditional-append pattern documented in `data_quality_alerts/main.py`. Probably hidden in other CFs.
- **Snapshot restore is ~3 s for 1 GB tables** — CLONE is metadata-only. DR runbook helper is at `bin/operations/dr_restore_snapshot.sh`.
- **Path A migration map for unmigrated CFs** — `shadow-performance-report`, `validation-runner.OH`, `mlb-regime-monitor`, `weekly-retrain` (see "Open work" section above).

## Carry-over from 2026-05-14 handoff (still open)

Per yesterday's predecessor:
- 33-CF Slack→Secret Manager migration — **partial: 10 of 14 NBA-side CFs done, 4 deferred (see Tier 2/3 above).** Original estimate was 33 CFs but the actual target set was 14 NBA/MLB CFs.
- Apply data_quality_alerts deploy.sh live — **done this session.**
- Audit obs filters in aggregator.py — **done this session.**
- Path B Week 4 — MLB auto-retrain CF — **still open, see "Open work D" above.**
- DR runbook drill — **done this session.**
