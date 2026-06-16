# System Deep-Dive — 2026-06-16

**Trigger:** owner request — full system health check + "is MLB pitcher strikeouts profitable again?" + "which sport/data to tackle next?"
**Method:** 20-agent parallel recon (infra / NBA / MLB / opportunity) → adversarial verification → synthesis. 23 agents, ~700 `bq`/`gcloud` calls.

## TL;DR
Posture is **correct**: NBA off-season (idle, auto-halted by design) + MLB in-season (info-only, betting permanently halted). One genuine production bug was active and is now **fixed + deployed**. Everything else is expected idleness or off-season cleanup debt.

---

## ✅ Fixed + shipped this session

### P0 — MLB BP props 404 redelivery storm (exhausting `pipeline_event_log` quota)
- **Symptom:** ~1,900 BigQuery `403 quotaExceeded` (partition modifications) per 2h across `nba-phase2-raw-processors`, `nba-phase4-precompute-processors`, `nba-scrapers`, `mlb-phase2-raw-processors`. Plus 2,694 `notFound` errors in 2h.
- **Root cause:** `MlbBpHistoricalPropsProcessor.__init__` set `self.dataset_id = get_raw_dataset()`, which returns `nba_raw` when the host service has `SPORT` unset. Daily `bettingpros-mlb/pitcher-strikeouts/<date>/props.json` files are delivered to `nba-phase2-raw-sub` → processed by `nba-phase2-raw-processors` (SPORT=nba) → `get_table(nba_raw.bp_pitcher_props)` → **404 on every file** → Pub/Sub NACK → redelivery storm. Each retry spewed pipeline events → `pipeline_event_log` (an append-only audit table written via *load jobs*, 1 partition-mod each) blew its 5,000/day partition-modification quota → collateral 403s everywhere.
- **Severity correction:** the workflow's first pass claimed "legitimate writes being dropped." Verified false — the errored destination tables are only `pipeline_event_log` (quota) and the MLB processor's 404 lookup. `pipeline_logger` **catches** its own write failures (non-fatal). So this was wasteful/noisy and burned observability quota, **not production data loss**.
- **Fix (`mlb_bp_historical_props_processor.py`):** force `self.dataset_id = SportConfig.for_sport('mlb').raw_dataset` regardless of host service. This is an MLB-only processor (its `table_name` is already hardcoded to `bp_pitcher_props`/`bp_batter_props`); it must never resolve to `nba_raw`. Idempotent (dedup by `source_file_path`). Deploys to both `nba-phase2-raw-processors` and `mlb-phase2-raw-processors` via auto-deploy.
- Once files process successfully → ACK → redelivery loop ends → `expected_outputs` for `bp_pitcher_props` flips to COMPLETE → `gap_detector` stops re-escalating.

---

## ⚾ MLB pitcher strikeouts — profitable again? **No. Keep halted.**

Fresh window **May22–Jun15, OVER edge≥0.75: 29-18, 61.7% HR, +8.36u, 17.8% ROI (N=47)**, real month trend (Apr 43.8% → May 60.3% → June 66.7%), well-distributed (34 pitchers / 23 days). Looks tempting — but **refuted** by adversarial verification on the bar required to risk money:
1. **Not significant** — one-sided binomial of 29/47 vs −110 breakeven (52.38%): **p=0.128, 95% CI lower bound 0.487 (below breakeven)**. Season slice 95/172 (55.2%) worse (p=0.251). A 2-3 week hot streak at N=47 produces this by variance.
2. **No CLV** — `closing_line`/`clv_raw` 100% NULL. The decisive efficiency check (closing-line capture) is still non-functional, per the 2026-05-22 finding.
3. **Train/serve skew** — live worker serves the leak-trained model on de-leaked features (active `halt_overrides` note); the model overshoots K (positive signed_error, worsening into June) → mechanically flatters directional OVER. Live OVER HR ~50% and declining.

**Resume bar (pre-registered):** OVER edge≥0.75 sustaining **≥58% HR with positive CLV at N≥100**. Until then: keep halted, shadow only, **fix closing-line capture first**.

---

## 🎯 Next sport + data to tackle

**Primary: MLB batter props (total_bases + hits) — efficiency-backtest FIRST, this season.** Only candidate playable now. Actuals live (`mlb_analytics.batter_game_summary`); 635K rows of 2024-25 historical lines (`mlb_raw.oddsa_batter_props`). Batter total_bases/hits structurally softer than the efficient K market. **Guardrail:** the 2026-05-21 C2 scan already killed *naive* OVER/UNDER on all 8 batter markets — so only a *conditional/signal-driven* edge is open; prove it on a backtest before building. Caveats: batter-line scraper dormant since 2025-09-28 (reactivate), 1-2 books only, no batter Statcast.

**Runner-up: NBA rebounds + assists — build off-season, deploy ~October.** Highest infra reuse; NBA is the proven-profitable sport (2025-26 BB 63.8%). But data clock only started 2026-04-06 (~1-2 wks, playoff-biased — too thin), each market needs a dedicated model, and there's no non-points prediction/grading/export plumbing (`player_prop_predictions` has no `market_type`). Collect a full season first.

**Defer:** NFL (greenfield, Sept), WNBA (greenfield, thin). **Untapped lever:** add Pinnacle (sharp book) via Odds API `regions=eu/us2` — all 12 current MLB books are retail US, so we have zero sharp-vs-retail divergence signal. Also `kalshi_player_props` (~498K rows, idle).

---

## Open issues (ranked — NOT yet fixed)

| P | Issue | Fix |
|---|---|---|
| P2 | MLB `expected_outputs` permanently false-FAILED: planner emits `mlbstatsapi/` but scraper writes `mlb-stats-api/` (schedule + boxscores). Data is actually present. Halted MLB publish rows are FAILED instead of EMPTY_OK. | Correct planner prefix to `mlb-stats-api/`; reconciler credit `halt_active=true` as EMPTY_OK; populate `last_error`. |
| P3 | NBA PBP gaps: **Oct 2025 (~80 opener games) absent** from `nbac_play_by_play`; Feb 2026 block already known (upstream scrape outage). Labels (gamebook) intact. | While idle, confirm whether Oct 2025 source JSON exists in GCS; backfill loader if yes, re-scrape if no; re-run Phase 3 cascade. Use date+distinct-game-count checks, NOT `game_id` joins (incompatible ID formats). |
| P4 | Off-season cost: `prediction-worker` + `prediction-coordinator` min=1 with 0 traffic 30d (~$26-40/mo). ~15 NBA monitors firing at a halted pipeline. | `--min-instances=0` (NOT the 3 orchestrators — Feb 23 cold-start incident). Pause NBA off-season monitors. Reversible; restore before ~Oct preseason. |
| P5 | Config drift: `signals.yaml` weights stale vs code (`book_disagree_over` 1.5→3.0, `combo_3way` 2.0→2.5, `extended_rest_under`/`rest_advantage_2d` status); model-registry `is_production` → orphan disabled `catboost_v9_33f`; `bin/model-registry.sh` defaults to wrong project `jett-prod`. | Pre-season cleanup batch. Fix the registry CLI project default before next-season ops. |

**Local-env gotcha:** the machine's default gcloud/bq project is **`jett-prod`** — always pass `--project[_id]=nba-props-platform`.

**Explicitly NOT issues (expected off-season idleness):** NBA Phase2/5/6 FAILED `expected_outputs` (predictions halted off-season), NBA fleet INSUFFICIENT_DATA, frozen NBA raw tables/signal-health, MLB betting halt, empty `pitcher_strikeout_predictions`/`shadow_mode_predictions` (predictions write to `pitcher_strikeouts`).
