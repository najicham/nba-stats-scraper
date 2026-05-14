# Session Handoff — 2026-05-13 — Modal design continuation + tonight's follow-ups

**Primary focus next session: MLB pitcher modal design** — picking up the Projects A and B that were scoped but not shipped in Session 532 (2026-04-14). Secondary: a small set of ops follow-ups left from tonight's incident response, plus the still-active MLB roadmap entry condition (Session 6).

**Source-of-truth docs:**
- `docs/09-handoff/2026-04-14-SESSION-532-HANDOFF.md` — original modal-design brainstorm + the three scoped projects (A/B/C). Read this first for project context.
- `docs/09-handoff/2026-05-13-mlb-grading-and-publish-bugs.md` — tonight's incident diagnosis (referenced for the backend changes that landed).
- `docs/09-handoff/2026-05-13-mlb-roadmap-session-6.md` — pending MLB roadmap entry (UNDER decision + first NBA-port; entry 2026-05-20).

## TL;DR

Three streams of pending work, in priority order:

1. **Modal design — Projects A & B from Session 532** (the user's explicit ask for next session). Project A is mostly frontend-only and shippable in a single session; Project B needs a new BQ aggregation + JSON field.
2. **Ops follow-ups from tonight** — five small items (trigger config, snapshot scheduler, historical BB backfill, scraper investigation, lint cleanup). Each is < 30 min.
3. **MLB roadmap Session 6** — entry condition is **2026-05-20** (A2 monitor + B1 7-day state need to accumulate). Not yet startable.

## Primary — modal design continuation

### Project A — Matchup section ("Outing Script") on the Overview tab

The "free wins" from Session 532's scoping are still free:

- **Key Angles row** — read `pick_angles` from the best-bets JSON (`mlb/best-bets/all.json` or per-date) for the modal's pitcher on the modal's game_date. Render as a chip group at the top of the Overview tab, above existing content. The angle strings are already pre-formatted by `ml/signals/mlb/pick_angle_builder.py` (e.g., "Cold weather (45°F)", "Sharp money OVER", "vs RHB bottom-5 K%").
- **H2H against the listed opponent** — filter the existing `game_log` JSON for prior outings against the opponent team_abbr; show as a Last N Starts strip with K count, IP, result. No backend change needed.

Backend-dependent pieces (defer or estimate cost first):
- Opponent K% vs LHP/RHP — needs a new BQ view aggregating opponent K rates by hand. ~1 hr.
- Park K factor — needs `mlb_reference.venue_factors` (doesn't exist yet) or a Statcast aggregation. ~2 hr.
- Umpire K tendency — `mlb_raw.covers_referee_stats` exists for NBA but MLB equivalent uses `mlb_raw.mlb_umpire_stats`. Should be 1-1 mappable. ~30 min.

**Suggested session shape:** ship the two frontend-only pieces (Key Angles + H2H strip) first; defer the backend-dependent ones until the design lands and you can measure whether the UI actually improves with them.

### Project B — Strike Zone Heartbeat (signature visual)

Requires backend before frontend can be designed:

- Aggregate `mlb_raw.mlb_game_feed_pitches` to per-pitcher zone × outcome counts. Probably as a new view `mlb_analytics.pitcher_strikeout_locations` (or as part of the pitcher_features pipeline).
- Schema: `pitcher_lookup, season_year, zone (1-9 or 14 if including out-of-zone), strikeouts, total_pitches, whiff_pct`.
- Front the view via a new field on the per-pitcher profile JSON.
- Frontend: React + SVG 3×3 (or 3×4 with chase zones) heatmap. Reuse Tailwind theme tokens. Add it as a tab on the modal.

**Cost estimate:** 1 hr backend (view + JSON wiring), 1-2 hr frontend (SVG component, theme tokens, modal tab integration).

**Why prioritize this:** it's the "signature visual" the user asked for in Session 532 ("graphs and cool things"). A pitcher's release-point or zone profile is the most identifiable visual on a modal — competing sites use it as their main differentiator.

### Project C — Ledger alt view on Line Beaters tab

Frontend-only. Lower priority for next session unless A and B land quickly. Session 532's handoff has the scoping; nothing has changed.

### Modal-adjacent improvements landed tonight (free wins)

Tonight's frontend work shipped four UX-impact pieces that affect the modal indirectly:

- **Void taxonomy** — DNS/DNF/PPD/SUS badges (commit `dd99851` props-web) with `<Tooltip>` describing the reason (`4471fba`). If the modal renders historical picks, voids now show with proper labels.
- **Row hover** — `WeeklyHistory` and `TodayPicksTable` rows tint as a unit on hover (`aab41de`) with a darker tint that doesn't blend with the row stripe (`953c9d1`).
- **`actual_starter_lookup` field** on BestBetsPick — modal could surface "Started behind <opener>" on the picker's stat strip if you want that. The data is already in the JSON; just needs a slot in the modal layout.

## Secondary — tonight's ops follow-ups

| Item | Effort | Why it matters |
|---|---|---|
| **Update `deploy-mlb-phase6-grading` trigger config** to include `data_processors/publishing/mlb/**` in its `includedFiles`. Tonight I documented this in commit `fc6f4e86` but the actual GCP-side config wasn't updated (v2 trigger API; `gcloud builds triggers update` syntax pending). Without this, future changes to `mlb_best_bets_exporter.py` won't redeploy the grading service that bundles it. | 10 min | Prevents a repeat of tonight's "deployed phase6_export but not mlb-phase6-grading" cascade. |
| **Wire `bin/backups/mlb_snapshot_daily.sh` to Cloud Scheduler** (daily 11 AM ET cron). The script is committed but currently has to be run manually. | 15 min | Closes the 30-day BQ recovery window beyond BQ's built-in 7-day time-travel. |
| **Backfill historical `signal_best_bets_picks.prediction_correct`/`is_voided` from `prediction_accuracy`**. All 79 historical BB rows have NULL grading state because the MERGE was silently failing all season (partition filter, fixed tonight in `a0e128b3`). One-time UPDATE FROM JOIN on the BB table backfills them — and lets us safely remove the LEFT JOIN in `export_all` later if we want to. | 20 min | The LEFT JOIN is currently load-bearing; backfill enables future simplification. |
| **Investigate why `mlb_raw.mlb_pitcher_stats` had 0 rows for 2026-05-12.** All pitchers, all teams. `mlb_game_feed_pitches` was populated normally, so per-pitch ingestion ran; the aggregated-stats path is broken for that one day. Likely scraper logs from 2026-05-13 morning will show why. | 20-30 min | Could be a one-off (rate limit, transient API issue) or a pattern. Worth knowing before relying on `mlb_pitcher_stats` for anything. |
| **`props-web` GH Actions CI lint cleanup**. The CI workflow is failing on `no-explicit-any`, `react/no-unescaped-entities`, `no-html-link-for-pages`, etc. across multiple files (NOT tonight's changes — pre-existing). Doesn't block Vercel deploy, but every push shows red. | 1-2 hr | Quality signal restoration; nice-to-have. |

## Tertiary — MLB roadmap (Session 6)

Entry condition: **2026-05-20** at the earliest. Two monitoring windows need to fill:

1. **A2 7-day monitor** — `MLB_MAX_EDGE=1.25` deployed 2026-05-13 (algorithm version `mlb_v9_max_edge_125`). 7-day Wilson LB threshold check is **DUE 2026-05-20**. Query in `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/07-A2-MONITOR-QUERY.md`. If TOTAL Wilson LB drops below 43.6%, revert via `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_MAX_EDGE=1.5"`.
2. **B1 regime monitor** — deployed 2026-05-13 evening (commit `553c9c59` and prior). First state row is DEGRADING (MLB/UNDER, HR 30.4%, N=46). Read `mlb_orchestration.direction_regime_state` to see if state stays DEGRADING across the week or flips back. Not actionable until 7+ days of state accumulate.

Session 6's plan: UNDER pipeline decision (A/B/C branch tree in `docs/.../06-MULTI-SESSION-ROADMAP.md`) + start E2 (filter CF evaluator NBA-port).

## Other carry-overs (long-standing, not session-blocking)

- **`SLACK_WEBHOOK_URL_SIGNALS` on `mlb-regime-monitor`** — deployed with empty env var; alerts silently no-op. Patch via `--update-env-vars` once the user provides the URL. Webhook prefix documented in `shared/utils/slack_channels.py:31`.
- **`OPENWEATHERMAP_API_KEY` blocker** — `mlb_weather` scraper writes mock data (75°F neutral) without it. Weather signals (`WeatherColdUnderSignal`, `ColdWeatherKOverSignal`) silently no-op. Free tier covers usage. Procedure in Session 2 carry-over #2.
- **`mlb_precompute.lineup_k_analysis` empty** — diagnosed 2026-05-13. Processor wired, never writes rows. A1 lineup features confirmed vapor. Don't touch unless explicitly asked.

## What this session will NOT do

- Backend grading changes — the `did_not_start` work and the supporting infrastructure shipped tonight (commits `553c9c59` → `9392c21d`). Verified live.
- The UNDER pipeline decision — needs 2026-05-20 monitoring data.
- Anything in the NBA system — still in playoffs, auto-halt active since ~Mar 28.

## Useful pointers

- **Modal source file:** `props-web/src/components/modals/PitcherModal.tsx` (and adjacent `PitcherCard.tsx`, `OverviewTab.tsx`, `LineBeatersTab.tsx`). Session 532 shipped Phase 1 (charts), Phase 2 (no-model-content), Phase 3 (PitcherCard v2). Projects A/B/C extend Phase 4.
- **Run modal locally:** `cd /home/naji/code/props-web && npm run dev`, navigate to a pitcher on the leaderboard, click row.
- **Backend data flow for modal:** profile JSON at `gs://nba-props-platform-api/v1/mlb/pitchers/profile/<lookup>.json`. Generated by `data_processors/publishing/mlb/mlb_pitcher_exporter.py` on the `mlb-pitcher-export-pregame` / `-morning` schedules.
- **Verify tonight's frontend changes are live:** hard-refresh `playerprops.io/mlb`, scroll to Tuesday May 12 in history — should show Waldron as `[DNS]` with hover tooltip "Rodriguez started instead".

## Calendar context

Today is 2026-05-13 (~9:30 PM ET at handoff time). MLB regular season mid-stride. NBA playoffs (halt active). Vercel auto-deploys the props-web changes on push to main.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-modal-and-followups.md.
Start with Project A's frontend-only pieces — Key Angles row and H2H strip
on the modal Overview tab. Reference docs/09-handoff/2026-04-14-SESSION-532-HANDOFF.md
for the original scoping. Use Sonnet unless the work surfaces a non-trivial
backend design call.
```
