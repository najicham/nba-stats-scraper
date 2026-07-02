# Session Handoff — 2026-05-13 — MLB roadmap Session 2 startup

**Prior session (2026-05-13, this morning):** Session 1 of the multi-session MLB roadmap. Executed Task 1 (X2 verification), Task 2 (X1 lineup pipeline diagnosis), and a partial Task 3 (A3: shipped Component C only — Components A+B hit a stop condition). This handoff sets up Session 2.

**Source-of-truth docs:**
- `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md` — canonical plan
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-1.md` — what Session 1 was supposed to do

## TL;DR

- **X2 result: A1 vapor CONFIRMED.** f25=119/946 nonzero, f26/f27/f33/f34 all 0. The plan branch "if Agent D was right" applies. A1 stays dead; X1 deeper investigation deferred indefinitely per roadmap.
- **X1 diagnosis: lineup_k_analysis is empty.** Processor exists and is wired in the precompute service, but the table has 0 rows ever. Pub/Sub trigger from `batter_game_summary` is the suspected break point. Did NOT fix — scope only.
- **A3 partial ship:** Component C (`mlb-best-bets-generate-late` at 4:30 PM ET, March-October) is **DEPLOYED, ENABLED, and verified end-to-end** via manual fire — 2 picks written today. Components A (weather scheduler) and B (weather wiring) were **DEFERRED** because the scraper needs `OPENWEATHERMAP_API_KEY` which is not set on `mlb-phase1-scrapers` and not in Secret Manager. Without it, the scraper silently writes mock data (75°F neutral), so scheduling it would only burn cycles.

No model changes. No governance gates. NBA dormant per existing memory. MLB OVER cash cow undisturbed.

## What shipped (Session 1)

### Component C — `mlb-best-bets-generate-late` scheduler ✓

| Field | Value |
|---|---|
| Job name | `mlb-best-bets-generate-late` |
| Schedule | `30 16 * 3-10 *` (4:30 PM ET, March-October) |
| Time zone | `America/New_York` |
| URI | `https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets` |
| Body | `{"game_date": "TODAY"}` |
| State | ENABLED |
| First test-fire | 2026-05-13T14:17:06Z — succeeded, 2 picks written |
| Next natural fire | 2026-05-13T20:30:00Z (today, 4:30 PM EDT) |
| Source-of-truth file | `bin/schedulers/setup_mlb_schedulers.sh` (updated) |

Verified: `bq query 'SELECT * FROM mlb_predictions.signal_best_bets_picks WHERE game_date = CURRENT_DATE()'` returned 2 OVER picks (Dylan Cease 6.5, Noah Schultz 4.5) with `algorithm_version='mlb_v8_s456_v3final_away_5picks'`. Endpoint returned 200, no errors in worker logs.

**Known scoped-DELETE limitation (from MEMORY.md):** The /best-bets endpoint deletes prior picks via `WHERE game_date = X AND pitcher_lookup IN (refreshed)`. A pitcher scratched between 12:55 and 16:30 ET drops out of `pitcher_lookups` → their stale BQ row is NOT deleted. **BUT** the public site reads GCS JSON, which is regenerated fresh per export — so the scratched pitcher disappears from playerprops.io. Net effect: public-site bug fixed; BQ retains shadow rows (audit/history only).

## What did not ship (Session 1)

### Component A — weather scheduler — DEFERRED

`scrapers/mlb/external/mlb_weather.py` requires `OPENWEATHERMAP_API_KEY` env var. Findings:

- Not set on `mlb-phase1-scrapers` Cloud Run service (verified via `gcloud run services describe`)
- No matching secret in Secret Manager (`gcloud secrets list | grep -i weather` → empty)
- Without it, scraper writes mock data: all open-air stadiums at 75°F, `k_weather_factor=1.0`, identical for every team every day
- `WeatherColdUnderSignal` (ml/signals/mlb/signals.py:301) thresholds on `temperature_f`; `ColdWeatherKOverSignal` (line 772) similarly
- Mock data would never trigger either signal — same as today's empty-table state, but with 30 rows/day of fake garbage instead of zero rows

User chose "Skip A+B, ship C only" when surfaced.

### Component B — weather → predictions wiring — DEFERRED

`predictions/mlb/supplemental_loader.py:230` `_load_weather()` is already coded. It just returns `{}` because the source table is empty. Once Component A ships real data, Component B is automatic (no code change needed).

## X2 verification (Task 1)

Query and result, for the record:

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(f25_bottom_up_k_expected != 0) AS f25_nonzero,
  COUNTIF(f26_lineup_k_vs_hand != 0) AS f26_nonzero,
  COUNTIF(f27_platoon_advantage != 0) AS f27_nonzero,
  COUNTIF(f33_lineup_weak_spots != 0) AS f33_nonzero,
  COUNTIF(f34_matchup_edge != 0) AS f34_nonzero
FROM `nba-props-platform.mlb_precompute.pitcher_ml_features`
WHERE game_date >= '2026-04-01';

-- Result:
-- total_rows=946, f25_nonzero=119, f26=0, f27=0, f33=0, f34=0
```

Agent D's claim confirmed (was 5/6 vapor, but f25 has partial population — likely from one of the upstream dependencies). f26/f27/f33/f34 — the four "lineup-derived" features — are 0.0 constants in every prediction row. Wiring them into the V2 feature contract today would ship placeholders into production. **A1 stays dead.** The roadmap branch "If A1 is confirmed vapor (5 features = 0.0): X1 stays in C5, defer indefinitely" applies.

## X1 diagnosis (Task 2)

Scope only, no fix. Findings:

| Check | Result |
|---|---|
| `mlb_precompute.lineup_k_analysis` row count | **0** (never populated) |
| `data_processors/precompute/mlb/lineup_k_analysis_processor.py` exists | Yes |
| Wired into `main_mlb_precompute_service.py:61` | Yes (`MLB_PRECOMPUTE_PROCESSORS['lineup_k_analysis']`) |
| Listed as Phase 4→5 orchestrator dependency | Yes (`orchestration/cloud_functions/mlb_phase4_to_phase5/main.py:49`) |
| Direct Cloud Scheduler entry | **No** (no `lineup_k_analysis` job in `gcloud scheduler jobs list`) |
| Trigger map (`main_mlb_precompute_service.py:67`) | `'batter_game_summary': [MlbLineupKAnalysisProcessor]` — Pub/Sub-driven from analytics completion |
| Sibling processor `pitcher_features` health | Healthy — 11-30 rows/day in `pitcher_ml_features` for last 14 days |
| `mlb_raw.mlb_lineup_batters` (input) coverage | Spotty: 8/14 days, mostly 2-6 teams per day, max 22 teams on 2026-05-10. Two scrapers feed it (`mlb-lineups-morning` 11 AM ET, `mlb-lineups-pregame` 1 PM ET) — both ENABLED, both succeeded yesterday |

**Two likely root causes** (don't fix in Session 2 unless explicitly told):
1. The `batter_game_summary` → Pub/Sub topic → `lineup_k_analysis` trigger is not firing. Sibling `pitcher_features` works because it's triggered by `pitcher_game_summary` (different Pub/Sub message).
2. The processor IS firing but failing silently against sparse `mlb_raw.mlb_lineup_batters` input data — no rows ever land because the dependency check (`mlb_analytics.batter_game_summary`, lookback 5 games, `critical=False`) yields zero usable input.

**Investigation hooks for whoever picks this up:**
- `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="mlb-phase4-precompute-processors" AND textPayload:"lineup_k_analysis"' --limit=20`
- Manually fire: `curl -X POST $PRECOMPUTE_URL/process -d '{"processor":"lineup_k_analysis","analysis_date":"2026-05-13"}'` (verify endpoint + auth first)
- Check the Pub/Sub subscription on `mlb-phase4-precompute-processors` for whatever topic `batter_game_summary` analytics completion publishes to

Per roadmap, this stays in cluster C5 and is deferred indefinitely (A1 is dead → no immediate need for lineup features).

## Session 2 plan (per roadmap)

**Goal:** Ship the only OVER ranking change with strong evidence (A2 narrowed), and start the CLV foundation that Phase C will need.

| Step | Effort | Notes |
|---|---|---|
| A2 narrowed — Tighten `MAX_EDGE` 1.5 → 1.25 | 2h | Skip the bucket re-rank for now (Agent D's CI overlap concern). One constant change + `algorithm_version` bump. |
| 7-day monitor query for A2 | 30 min | Save as a BQ saved query: 7d OVER HR by edge bucket. Manual check next week. |
| A5 design — CLV table + scheduler schema | 1h | Design only, don't build. Write the schema SQL + scheduler config draft. Save to docs. |
| B1 backtest design | 30 min | Write the 2024/2025 false-positive query. Don't build B1 yet. |

**Deploy at session end:** A2 narrowed (MAX_EDGE tighten). A5 + B1 designed but not built.

**Verification 7 days later:** OVER HR Wilson LB must not regress > 2pp. If it does, revert.

## Stop conditions for Session 2

ABORT and surface to user if:
- A2 tighten changes existing OVER pick volume by > 50% on a smoke test (suggests miscalibration vs the 5-season replay rationale)
- The MAX_EDGE constant lives in more than one place and they're not in sync (rationale for `algorithm_version` bump is provenance — make sure the bump propagates)
- 5-season backtest of MAX_EDGE=1.25 doesn't reproduce the +X pp Wilson LB improvement Agent D quoted in `01-AGENT-FINDINGS.md` Lane 5

## Carry-over items from Session 1

1. **Verify the 4:30 PM ET natural fire (today, 2026-05-13).** The manual test-fire at 10:17 AM ET worked, but the natural cron schedule is the real validation. After 21:00 UTC today, check:
   ```bash
   gcloud scheduler jobs describe mlb-best-bets-generate-late --project=nba-props-platform --location=us-west2 --format="yaml(lastAttemptTime,status)"
   bq query --use_legacy_sql=false --project_id=nba-props-platform "SELECT COUNT(*), MAX(created_at) FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` WHERE game_date = CURRENT_DATE()"
   ```
   Expected: `status: {}`, `lastAttemptTime` close to `2026-05-13T20:30:00Z`, `MAX(created_at)` past 20:30 UTC.

2. **OPENWEATHERMAP_API_KEY** is a Session-2 (or later) blocker for resurrecting Components A+B. Free tier is 1000 calls/day; we have 30 stadiums + 1 daily call = 30 calls/day, well under limit. If the user provides a key:
   - `printf 'KEYHERE' | gcloud secrets create OPENWEATHERMAP_API_KEY --data-file=- --project=nba-props-platform`
   - `gcloud run services update mlb-phase1-scrapers --update-secrets="OPENWEATHERMAP_API_KEY=OPENWEATHERMAP_API_KEY:latest" --region=us-west2 --project=nba-props-platform`
   - Test scrape one stadium manually: `curl -X POST $SCRAPERS_URL/scrape -d '{"scraper": "mlb_weather", "team_abbr": "NYY"}'`
   - Verify real temp lands in BQ: `bq query "SELECT temperature_f, k_weather_factor FROM mlb_raw.mlb_weather WHERE scrape_date = CURRENT_DATE() AND team_abbr='NYY'"`
   - Then add `mlb-weather-pregame` scheduler at ~11:30 AM ET (between morning props at 10:30 ET and lineups-pregame at 1 PM ET) — pattern matches `mlb-umpire-assignments` (`30 16 * * *` in ET tz).

3. **X1 deeper investigation** — only if the user wants it. Roadmap defers indefinitely; X1 stays in C5.

## What this session will NOT do

(Same as Session 1 plus the carry-overs above stay non-Session-2.)

- Anything UNDER-related (Phase C decision is Session 6)
- A4 Poisson WF (Session 3)
- A5 build (Session 3)
- B1 build (Session 4)
- Any model retrain or deploy (first touchpoint is Session 5)
- Fixing the lineup pipeline (deferred indefinitely)
- Adding weather scheduler without an API key

## Useful pointers

- Auto-deploy is live on push to main. Scheduler-script changes (like the one this session made to `bin/schedulers/setup_mlb_schedulers.sh`) do NOT auto-deploy — they're source-of-truth for future re-runs only.
- A2 MAX_EDGE constant lives in `ml/signals/mlb/best_bets_exporter.py` (search for `MAX_EDGE`); confirm before editing.
- The handoff for Session 1 (this morning's start prompt) is `docs/09-handoff/2026-05-13-mlb-roadmap-session-1.md`.

## Calendar context

Today is 2026-05-13. MLB regular season mid-stride. NBA in playoffs (dormant — playoffs-started halt active since ~Mar 28). The natural 4:30 PM ET fire of the new scheduler is at 20:30 UTC today (~6 hours from end of Session 1).

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-2.md.
Execute Session 2 as described. Start with the A2 MAX_EDGE tighten.
```
