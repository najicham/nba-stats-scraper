# Session 540 Handoff — MLB pitcher pages frontend overhaul

**Date:** 2026-04-16 (evening, after S539)
**Focus:** Frontend only. Make the MLB pitcher pages visually consistent with the NBA equivalents and strip all model output from them. No backend, no deploys, no scheduler/data work.

> **Read first:** [S539](./2026-04-16-SESSION-539-HANDOFF.md) — it has the open MLB-scheduler cold-start hypothesis that still needs verification (see "Carried forward" below). Nothing from S539's backend/pipeline state was touched this session.

---

## TL;DR

Four commits to `props-web`, none to `nba-stats-scraper`. All on `main`, all pushed, Vercel auto-redeployed. Net −570 lines on the frontend (mostly from `PitcherModal.tsx`).

Three focuses, in order:

1. **`PitcherCard` grid consistency** — grid rows were visually out of sync because some cards had a narrative hook and others didn't, and the `Hit%` footer rendered inconsistently. Fixed vertical rhythm across the 3-column grid.
2. **`PitcherCard` + `PitcherModal` aligned with NBA patterns** — matchup moved from top-left to top-right (NBA style), "Last 5" label added above the K-result grid, modal got an NBA-style scrollable pitcher switcher with auto-scroll + swipe + "N of M" counter, tabs removed in favor of single-scroll with a 2-col grid on desktop.
3. **All model output removed from MLB pitcher pages** — the rule going forward: model-derived stuff (predictions, edge, recommendation, confidence, Best Bet, our hit rate) lives ONLY on the best-bets pages. Pitcher pages are purely observational.

---

## Commits (props-web main)

All on `github.com:najicham/props-platform-web.git`, branch `main`.

| Hash | Scope | Summary |
|---|---|---|
| `10fd933` | PitcherCard | Reserve `min-h-[32px]` for narrative hook slot; always render L5 receipt with em-dash fallback. Cards line up vertically in the grid. |
| `79aa8d3` | PitcherCard | Header unified with NBA PlayerCard: name left, matchup right, `border-b` divider. "Last 5" label added above `Last5KGrid`. |
| `e416fcd` | PitcherModal | Full NBA-parity refactor. Scrollable pill switcher (desktop) + prev/next + swipe + "N of M" (mobile), Overview/Arsenal/Log tabs merged into single scroll, 2-col grid on `sm+` for Splits+TrackRecord and ArsenalQuality+Advanced. Deleted `CollapsibleSection` (dead), fixed 6 lint errors I introduced (setState-in-effect, ref-in-render, aria-selected on button → aria-current, useMemo dep narrowing), updated test that was asserting `tablist` role. |
| `d821650` | Model-strip on pitcher pages | Removed everything model-derived: Best Bet badge + positive left-border on PitcherCard, full hero verdict card + Track Record section + Key Angles + model-conviction chip in PitcherModal, "Best Record" leaderboard tab + green best-bet dot on `/mlb/pitchers`. Deleted 5 orphan helpers (`HeroStat`, `RecommendationPill`, `ConfidenceMeter`, `TrackRecordCard`, `TrackSide`), `mapModelTrusts` mapper, `fetchBestBetsAll` import. |

---

## State at session end

- **`props-web` main:** `d821650`. Pushed. Vercel should be deployed by now.
- **`nba-stats-scraper` main:** `1225f7a4` (S539 handoff). Untouched this session.
- **Typecheck:** clean on all edited files.
- **Lint:** clean on everything I wrote. Two pre-existing errors remain in code I didn't touch (`PitcherModal.tsx:171` setState-in-effect — pre-existed before any of my work; `pitchers/page.tsx:187` raw `<a>` that should be `<Link>`). I intentionally left those — out of scope and I didn't want to sneak unrelated fixes into a pure-refactor commit.
- **Tests:** 64/64 pass across `src/components/modal/` and `src/components/cards/`. Full `vitest run` was 549/549 passing, with one flaky vitest worker-exit error (infrastructure, not a real failure).
- **Production build:** `next build` succeeds.
- **Dev server smoke test:** `/mlb/pitchers` returns HTTP 200.

---

## What "observed only" means on pitcher pages (for future sessions)

The rule the user set: model output only shows on the best-bets pages. Everything else on the pitcher experience is what's actually observed. Concretely:

**Kept on pitcher pages** (all observed/Statcast-derived):
- Sportsbook K line, L5 results grid, L5 avg vs line
- Season stats strip (GS, IP, K/9, ERA, WHIP)
- K Distribution chart, K Trend chart
- Strike Zone Heartbeat
- Arsenal: Pitch Mix bars, Whiff-vs-Usage scatter, Arsenal Quality (whiff vs expected, velo premium), Advanced (putaway, velo fade, concentration)
- Splits (home/away, L3/L5/L10, rest days)
- H2H history vs tonight's opponent
- Game log table with summary pills (Avg K, Range, OVER%, Record)
- Hot streak amber accent on PitcherCard (last 3 all OVER — purely observed)

**Removed** (model-derived, live on best-bets now):
- Predicted Ks, edge, OVER/UNDER recommendation, confidence meter, Best Bet badge
- Our season track record ("Hit 100% · 2p")
- Best-bet angles (pick reasoning)
- "Best Record" leaderboard (ranking pitchers by our accuracy)
- Green dot on Pitching-Tonight strip for `is_best_bet`

**Type definitions untouched** — `TonightStarter.is_best_bet`, `track_record_picks`, `track_record_hr_pct` still exist in `pitchers-types.ts` and still come from the backend JSON. Just not rendered on pitcher surfaces anymore. Best-bets pages continue to consume them.

---

## Carried forward from S539 (NOT addressed this session)

All of these are still open. This session was frontend-only.

### Priority 1 — verify MLB scheduler fires (S539's big open question)

Did today's 16:55 UTC (`mlb-best-bets-generate`) and 17:00 UTC (`mlb-predictions-generate`) scheduler fires succeed? The cold-start hypothesis from S539 predicted one of three outcomes:

- Both succeed → S537 OIDC fix alone solved it, close the line.
- Only predictions succeeds → cold-start is real, apply `min-instances=1`.
- Both fail → deeper issue, investigate worker revision.

Run this to check (from S539):
```bash
gcloud scheduler jobs describe mlb-best-bets-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status)"
gcloud scheduler jobs describe mlb-predictions-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status)"

bq query --use_legacy_sql=false --format=pretty '
SELECT "preds" AS s, COUNT(*) n FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "bb", COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "filter_audit", COUNT(*) FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit` WHERE game_date = CURRENT_DATE()
'
```

### Priority 2 — apply `min-instances=1` if scheduler cold-start confirmed

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --min-instances=1
```

### Priority 3 — fix `mlb_umpire_assignments` scraper

`scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py:101` — `self.download_data.get("dates", [])` fails because `download_data` is a function, not a dict. Small fix.

### Priority 4 — longer-term items

- OIDC audit on remaining ~21 MLB schedulers (defensive)
- MLB UNDER enablement evaluation (needs 2024-2025 replay first)
- Session 536 frontend TODOs (analytics, drilldown, XAxis)

---

## New follow-up items (from this session)

None that are blocking. A couple of nice-to-haves the next session could consider if the user asks:

- The `LeaderboardSkeleton` on `/mlb/pitchers` still shows 8 skeleton rows sized for when "Best Record" existed. Since that tab is gone, there are now only 3 leaderboard views — the skeleton sizing is fine but worth a glance if feels off.
- `PitcherModal.tsx:171` — pre-existing `react-hooks/set-state-in-effect` lint error. Not urgent; Next.js build is still passing. Fix pattern: return early first, then reset via a second small `useEffect` on `isOpen` only.
- `ModelTrustsHimEntry` type in `pitchers-types.ts` and the `model_trusts_him` field on `PitcherLeaderboardResponse` are no longer consumed by the frontend, but the backend still emits them in the GCS JSON. Leaving the types intact so we don't churn the contract; if you confirm no other consumer reads it, they can be deleted.

---

## Useful one-liners

Full pipeline health (carried from S539):
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT "preds" AS s, COUNT(*) n FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "bb", COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "filter_audit", COUNT(*) FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "graded_yday", COUNT(*) FROM `nba-props-platform.mlb_predictions.prediction_accuracy` WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
'
```

Manual MLB pipeline kick (if 16:55 scheduler failed again):
```bash
curl -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets \
  -H "Content-Type: application/json" -d '{"game_date": "TODAY"}'

gcloud pubsub topics publish nba-phase6-export-trigger --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}'
```

---

## Key lessons for future sessions

**"Model stuff only on best-bets pages" is now a design rule, not a preference.** If a future session adds a new surface showing pitcher data and it includes anything the model produced (predictions, edge, confidence, our track record, best-bet flags, angles), it should be stripped before merge — or proactively be on the best-bets side of the split. Check `grep` for `is_best_bet`, `track_record_`, `recommendation`, `predicted_`, `edge`, `confidence` in any new pitcher-facing component.

**The NBA `PlayerModal` is the reference for "crisp."** When building a new MLB surface, mirror its patterns: single-scroll over tabs, scrollable pill switcher at top, 2-column grid on desktop for mid-density sections. That gives cross-sport consistency with almost no cost.

**The React Compiler lint is strict about ref-in-render and setState-in-effect.** When you write `if (someRef.current !== someProp) { someRef.current = someProp; ... }` at the top of a component body, it complains. Move to a `useEffect` keyed on the prop. For `setState` inside effect bodies, put the reset in the cleanup function instead.
