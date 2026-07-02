# Session Handoff — 2026-05-14 — Modal polish landed, prior handoff was stale, MLB 0-picks today

**Primary work this session:** props-web NBA-pattern alignment on the MLB pitcher modal (one commit, shipped). **Important finding:** the 2026-05-13 handoff doc that prescribed "Projects A/B/C" as next-session work was **stale by a month** — all three projects had already shipped on 2026-04-14 / 2026-04-16. This handoff replaces it as the source of truth.

**Source-of-truth docs:**
- `docs/09-handoff/2026-05-13-mlb-modal-and-followups.md` — **NOW SUPERSEDED on the modal-design portion** but still authoritative on the 5 ops follow-ups and roadmap timing.
- `docs/09-handoff/2026-05-13-mlb-grading-and-publish-bugs.md` — unchanged; the grading fix from 2026-05-13 is verified live.

## TL;DR

1. **Modal polish shipped (`props-web 4bc751e`):** aligned MLB PitcherModal to the NBA tile-grid pattern. Net `-114` lines. Uniform `bg-surface-secondary/50 rounded-xl p-4` + `<h4>` chrome across every tile, flat matchup-bar above the grid, splits 5-cell grid → real `<table>`, charts and arsenal split into half-tiles. TS + unit tests clean. Auto-deployed via Vercel.
2. **Prior handoff was wrong about pending work.** Projects A/B/C from Session 532 had ALL shipped before 2026-04-17. See "Discovery" section below for commits. The 2026-05-13 doc was written without checking git state.
3. **Today's MLB best-bets export = 0 picks.** Generated 10:45 ET (`gs://nba-props-platform-api/v1/mlb/best-bets/2026-05-14.json` is well-formed but `best_bets: []`). Worth a 10-min look before assuming "quiet card." Yesterday was 1-3 (33%) on 3 OVER picks at edges 0.3-0.5.
4. **NBA halt unchanged** — `between_rounds` (playoffs), no picks expected.
5. **5 ops follow-ups + 3 long-standing carry-overs** all roll forward to next session, unchanged from the 2026-05-13 doc.

## Discovery — the prior handoff was stale

The 2026-05-13 doc listed Projects A and B as pending. Git proves otherwise:

| Project | Commit | Date | Status |
|---|---|---|---|
| **A** — Matchup section + Key Angles + H2H | `edfeb3a` | 2026-04-14 | Shipped |
| **B** — Strike Zone Heartbeat | `0855ca1` | 2026-04-16 | Shipped |
| **C** — Line Beaters ledger view | `edfeb3a` | 2026-04-14 | Shipped |

What's currently in `props-web/src/components/modal/PitcherModal.tsx`:
- `MatchupBar` (pre-edit ~line 768) + `OpponentKBadge` — team + opp + season K% with rank ordinal, color-toned. Wired to `profile.tonight.opponent_k_rate`, `opponent_k_rank`, `opponent_k_rank_of`.
- H2H section — filters `game_log` by tonight's opponent, renders `H2HRow` strip.
- `StrikeZoneHeartbeat` — 5×5 SVG zone heatmap (zones 1-9 inner, 11-14 corners), heat-scaled, in-zone% summary.
- Ledger alt view on Line Beaters tab.

**One real gap remaining vs the original Project A spec:** the backend doesn't ship `pick_angles` on the profile JSON. The frontend synthesizes evidence chips client-side from profile fields (`PitcherModal.tsx` top comment: *"pick_angles doesn't ship on the pitcher profile — we synthesize"*). Functionally equivalent UX, different data path. ~1 hr backend lift if we want to make it real.

**Lesson for future handoffs:** before prescribing next-session work, run `git log --oneline <relevant-file>` to confirm what's actually shipped. The 2026-05-13 doc had the right intent (continue modal work) but cited the wrong starting state.

## What happened this session

After confirming the discovery, user redirected from "ship Projects A/B" to "polish the live modal — simple and crisp like the NBA one." Survey of the NBA `GameReportTab.tsx` revealed the pattern to match:

- Outer `space-y-3` with a flat `text-sm` matchup-bar sibling above the grid (NOT a separate bordered strip)
- `grid grid-cols-1 sm:grid-cols-2 gap-3` with every tile in identical `bg-surface-secondary/50 rounded-xl p-4` chrome
- Each tile has an `<h4 className="text-sm font-semibold text-text-primary uppercase tracking-wide mb-3">` header *inside* the card, not above
- Dense data → real `<table>` with right-aligned `tabular-nums`, `even:bg-white/[0.03]` row tint, thin `border-card-border` rules
- The only `col-span-2` in NBA's modal is the `ResultCard` — everything else is half-width

Five moves landed on `PitcherModal.tsx`:

| | Move | Before | After |
|---|---|---|---|
| A | Matchup bar | Floating strip with `border-b`, `text-[10px] tracking-[0.18em]` uppercase | Flat `text-sm` line with `·` separators, sibling above the grid |
| B | K-line tile | Custom flex layout, no `<h4>` | Standard tile + `<h4>Tonight's K Line</h4>` header |
| C | Charts | Single `col-span-2` tile with internal 2-col grid | K Distribution + K Trend as two separate half-tiles |
| C | Arsenal | Single `col-span-2` tile (scatter + bars combined) | Whiff vs Usage + Pitch Mix as two separate half-tiles |
| D | Splits | 5-cell grid layout (home/away grid + L3/L5/L10 grid + rest grid) | Real `<table>` with Window / Avg K / Over % / Starts columns |
| E | Consistency pass | 6 sections had `<SectionLabel>` outside the card chrome | All moved inside as `<h4>` (Why, Strike Zone, Arsenal Quality, Advanced, H2H, Recent Starts) |
| — | Grid gap | `gap-4` | `gap-3` matching NBA |

Final modal layout (in scroll order):

```
MatchupBar (flat text-sm line, NBA-style)
─────────────────────────────────────────
Tonight's K Line    │ Season Stats
K Distribution      │ K Trend
Why                 │ Splits (table)
Strike Zone Heartbeat (full-width — aspect ratio)
Whiff vs Usage      │ Pitch Mix
Arsenal Quality     │ Advanced
vs OPP last N       │ Recent Starts
```

**Verification:** TypeScript clean, 8/8 unit tests pass, ESLint shows 1 pre-existing error (line 171 `useEffect` setState — not introduced this session).

**Commit:** `4bc751e` on `props-web/main` — `refactor(pitcher-modal): align to NBA tile-grid pattern — uniform half-tile chrome`. Pushed at end of session. Vercel auto-deploy.

## Morning state — 2026-05-14

| Surface | Status |
|---|---|
| `nba_orchestration.halt_state` (NBA today) | `halt_active=TRUE, halt_reason=between_rounds` — playoffs, correct |
| `nba_orchestration.halt_state` (MLB today) | `halt_active=FALSE` |
| `mlb_predictions.signal_best_bets_picks` (yesterday) | 3 picks: Cease/Rocker/Schultz, all OVER, edges 0.3-0.5 → 1-2 graded per `mlb/best-bets/2026-05-13.json` summary (`graded:3 correct:1 accuracy:33.3`) |
| `gs://...mlb/best-bets/2026-05-14.json` | Well-formed, `best_bets: []`, generated 14:45 UTC |
| `props-web/main` | `4bc751e` — last night's modal polish |
| `nba-stats-scraper/main` | `cd94394e` — no overnight commits |

### MLB 0-picks today — flag for investigation

Worth ~10 min before assuming "quiet card":
- Are there starters scheduled for today at all? (`mlb_raw.mlb_lineup_pitchers` or `bp_player_props` for today)
- Did predictions run? (`mlb_predictions.pitcher_strikeout_predictions WHERE game_date = CURRENT_DATE()`)
- If predictions exist but no picks: edge floor, MLB_MAX_EDGE=1.25 deployed 2026-05-13 (algorithm `mlb_v9_max_edge_125`), regime gates, halt floor — any of these could be blocking
- The 4:30 PM ET `mlb-best-bets-generate-late` scheduler will run again — re-check then

## Pending — rolled forward from 2026-05-13 doc (unchanged)

### Ops follow-ups (5 items, each < 30 min)

| Item | Effort | Why it matters |
|---|---|---|
| Update `deploy-mlb-phase6-grading` trigger to include `data_processors/publishing/mlb/**` in `includedFiles`. Documented in `fc6f4e86` commit but GCP-side config not updated (v2 trigger API; `gcloud builds triggers update` syntax pending). | 10 min | Prevents repeat of "deployed phase6_export but not mlb-phase6-grading" cascade. |
| Wire `bin/backups/mlb_snapshot_daily.sh` to Cloud Scheduler (daily 11 AM ET). Script is committed but runs manually only. | 15 min | Closes the 30-day BQ recovery window beyond BQ's built-in 7-day time-travel. |
| Backfill historical `signal_best_bets_picks.prediction_correct`/`is_voided` from `prediction_accuracy`. All 79 historical BB rows have NULL grading state because the MERGE was silently failing all season (partition filter, fixed in `a0e128b3`). One-time UPDATE FROM JOIN. | 20 min | LEFT JOIN in `export_all` is currently load-bearing; backfill enables future simplification. |
| Investigate why `mlb_raw.mlb_pitcher_stats` had 0 rows for 2026-05-12. All pitchers/teams. `mlb_game_feed_pitches` populated normally. Per-pitch ingestion ran; aggregated-stats path broken for that day. | 20-30 min | Could be transient or a pattern. Worth knowing before relying on `mlb_pitcher_stats`. |
| `props-web` GH Actions CI lint cleanup — failing on `no-explicit-any`, `react/no-unescaped-entities`, `no-html-link-for-pages`. Pre-existing, doesn't block Vercel. | 1-2 hr | Quality signal restoration. |

### Long-standing carry-overs (not session-blocking)

- **`SLACK_WEBHOOK_URL_SIGNALS` on `mlb-regime-monitor`** — deployed with empty env var; alerts silently no-op. Patch via `--update-env-vars` once user provides URL. Webhook prefix in `shared/utils/slack_channels.py:31`.
- **`OPENWEATHERMAP_API_KEY` blocker** — `mlb_weather` scraper writes mock data (75°F neutral) without it. `WeatherColdUnderSignal`, `ColdWeatherKOverSignal` silently no-op. Free tier covers usage. Procedure in 2026-05-13 doc, Session 2 carry-over #2.
- **`mlb_precompute.lineup_k_analysis` empty** — diagnosed 2026-05-13. Processor wired, never writes rows. A1 lineup features confirmed vapor. Don't touch unless explicitly asked.

## MLB Roadmap Session 6

Entry condition: **2026-05-20 at the earliest**. Two monitoring windows still need to fill:

1. **A2 7-day monitor** — `MLB_MAX_EDGE=1.25` deployed 2026-05-13 (`mlb_v9_max_edge_125`). 7-day Wilson LB threshold check due 2026-05-20. Query in `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/07-A2-MONITOR-QUERY.md`. Revert via `gcloud run services update mlb-prediction-worker --update-env-vars="MLB_MAX_EDGE=1.5"` if TOTAL Wilson LB drops below 43.6%.
2. **B1 regime monitor** — deployed 2026-05-13 evening (`553c9c59` + prior). First state row was DEGRADING (MLB/UNDER, HR 30.4%, N=46). Read `mlb_orchestration.direction_regime_state` to track.

Session 6 plan: UNDER pipeline decision (A/B/C branch tree in `docs/.../06-MULTI-SESSION-ROADMAP.md`) + start E2 (filter CF evaluator NBA-port).

## What this session did NOT do

- Did not touch the backend.
- Did not address any of the 5 ops follow-ups from the 2026-05-13 doc.
- Did not ship `pick_angles` on profile JSON (the one real Project A residual).
- Did not investigate today's 0-pick MLB export — flagged for next session.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-14-modal-polish-and-zero-picks.md.

Two reasonable starting points:
1. The 0-pick MLB export — quick investigation, ~15 min.
2. Knock out one of the 5 ops follow-ups (recommend the trigger-config or
   snapshot-scheduler one — both are < 20 min, both close a real gap).

Use Sonnet unless the work surfaces a non-trivial design call.
```
