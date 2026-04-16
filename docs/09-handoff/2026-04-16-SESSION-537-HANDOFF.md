# Session 537 Handoff — MLB pipeline recovery + frontend URL routing + editorial banner

**Date:** 2026-04-16
**Focus:** Real root-cause diagnosis on the MLB drought (not edge compression — scheduler + bug in my own S536 code), URL-based sport routing refactor, offseason banner redesign.
**Status:** Everything shipped. 6 commits across two repos, all auto-deployed. MLB leaderboard populated for today (13 tonight starters).

---

## TL;DR

Session 536's "edge compression" thesis for the MLB BB drought was a **partial diagnosis**. Investigation this session found three compounding issues:

1. `mlb-predictions-generate` scheduler was firing without OIDC auth → instant 500s from Cloud Run before the worker even saw the request. Zero MLB predictions landed for April 16.
2. My own Session 536 code (`_fetch_opponent_k_defense` in `mlb_pitcher_exporter.py`) queried `pitcher_game_summary` with `is_starting_pitcher = TRUE` — that column doesn't exist. The exporter crashed, `leaderboard.json` wrote empty. Only noticed after the deploy-phase6-export CF re-ran today.
3. Edge compression is real but secondary — even with working infra, Apr 11–15 had at most 2 picks clearing the 0.75/1.25 home/away floors. Lever is there; not urgent.

All three fixed this session. MLB leaderboard now has 13 pitchers for tonight. Scheduler has OIDC, should fire clean tomorrow.

Frontend: full URL-based sport routing refactor (`/nba/*`, `/mlb/*`) via Next.js `[sport]` dynamic segment + middleware redirect from cookie. Share links work. Banner redesigned per user feedback + design-agent review: DM Serif Display (not italic), no emoji, no arrow on CTA, cursor-pointer fix, left-anchored CTA.

---

## What was built (all committed + pushed)

### `nba-stats-scraper`

- `d08a26ed` feat(mlb-exporter): opponent K-defense + strikeout zone data for profile JSON
  (original Session 536 backend work, committed this session — adds `profile.tonight.opponent_k_rate/rank/rank_of` and `profile.strikeout_zones` to the pitcher profile JSON)
- `ab3ce398` fix(mlb-exporter): drop non-existent `is_starting_pitcher` filter
  (hotfix for the bug above)

### `props-web`

- `0855ca1` feat: pitcher modal — confidence meter, opp K badge, rest splits, strike-zone heartbeat
  (Session 536 frontend work)
- `12dc7c3` feat: offseason banner — editorial bulletin treatment (first pass)
- `e7b6923` refactor: URL-based sport routing — `/nba/*` and `/mlb/*` via `[sport]` segment
- `9774f7c` refactor: offseason banner — DM Serif Display, drop italic, trim composition
  (response to "too fancy" feedback + design-agent review)

---

## MLB pipeline recovery (the real story)

### What actually broke

**Symptom:** User reported "MLB side is not default to today and not showing any data."

**Trail of breadcrumbs:**
1. `leaderboard.json` for today had `tonight starters: 0, leaderboard: 0`. Generated at 17:08 UTC (scheduled run time).
2. `mlb_predictions.pitcher_strikeouts` BQ table: zero rows for `2026-04-16`.
3. `mlb-predictions-generate` scheduler last fire: `status.code: 13`, error message: `URL_UNREACHABLE-UNREACHABLE_5xx. Original HTTP response code number = 500`.
4. Worker logs during that scheduler fire: **empty**. Request never reached the service.
5. Worker time-to-fail: 10ms (AttemptStarted 17:00:04.417 → AttemptFinished 17:00:04.427). That's TLS-handshake territory, not application.
6. Comparison: `mlb-best-bets-generate` scheduler has `oidcToken` config pointing at `756957797294-compute@developer.gserviceaccount.com`. `mlb-predictions-generate` had **no OIDC block at all**.
7. Manual `curl -X POST https://mlb-prediction-worker-.../predict-batch` → HTTP 200, 17 predictions written to BQ in 19 seconds.

**Conclusion:** The worker runs fine. The scheduler was unauthenticated, Cloud Run's HTTP layer rejected it as 5xx before the app saw it.

### What I did

**Live fix:**
```bash
gcloud scheduler jobs update http mlb-predictions-generate \
  --location=us-west2 --project=nba-props-platform \
  --oidc-service-account-email=756957797294-compute@developer.gserviceaccount.com \
  --oidc-token-audience=https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app
```

Now matches the known-working `mlb-best-bets-generate` config. Next fire: tomorrow 17:00 UTC / 1 PM ET.

**Manual recovery for today (Apr 16):**
- `curl -X POST /predict-batch` → 17 predictions landed in `mlb_predictions.pitcher_strikeouts`
- Fixed `is_starting_pitcher` bug, pushed → triggered `deploy-phase6-export` Cloud Build
- Once the CF redeployed (~5 min), re-triggered: `gcloud pubsub topics publish nba-phase6-export-trigger --message='{"sport":"mlb","export_types":["pitchers"],"target_date":"today"}'`
- Verified: `leaderboard.json` regenerated at 18:12 UTC with 13 tonight starters

**Today's data, as of 18:12 UTC:**

| Pitcher | Team/Opp | Line | Pred | Edge | Rec |
|---|---|---|---|---|---|
| Luis Castillo | SEA/HOU | 4.5 | 5.7 | +1.20 | OVER |
| Chase Burns | CIN/LAA | 6.5 | 5.7 | −0.80 | UNDER |
| Jack Leiter | TEX/LAD | 5.5 | 6.1 | +0.60 | OVER |
| Patrick Corbin | TOR/MIN | 4.5 | 3.9 | −0.60 | UNDER |
| ... | ... | ... | ... | ... | ... |
| Shane Baz | BAL/SF | 4.5 | 4.4 | −0.10 | UNDER |

13 total. 1 pitcher (Castillo) crosses the 0.75 home edge floor but he's AWAY; 0 pitchers cross the 1.25 away floor. Consistent with the broader edge-compression pattern — no BB picks expected tonight without relaxing floors.

### Why `leaderboard.count: 0` is fine

The `leaderboard` array is season-long aggregate rankings (hot hands, strikeout kings, etc.). Mid-April there's too little data to rank meaningfully. It'll populate naturally. `tonight.starters` is what the home page actually uses.

---

## Frontend: URL-based sport routing (`/nba/*`, `/mlb/*`)

### Why this refactor

Before: sport was React state + localStorage. Reported bug: "I selected NBA, refreshed, it went to MLB." Root cause likely stale bundle from before my `"mlb"→"nba"` default flip. But the underlying fragility was real — localStorage is client-only, so SSR can't know your preference, and share links lose sport context.

After: **URL is the source of truth**. `/nba/best-bets`, `/mlb/pitchers`, etc. Share links work. SEO gets sport-specific indexable paths. No hydration flash.

### What moved

Seven page files moved under `src/app/[sport]/`:
- `/` → `/[sport]/` (Tonight)
- `/best-bets` → `/[sport]/best-bets`
- `/results` → `/[sport]/results`
- `/picks` → `/[sport]/picks`
- `/trends` → `/[sport]/trends` (NBA-only — MLB visits redirect to `/mlb/pitchers`)
- `/pitchers` → `/[sport]/pitchers` (MLB-only — NBA visits redirect to `/nba/trends`)
- `/players` → `/[sport]/players`

Sport-agnostic pages stayed at root: `/about`, `/privacy`, `/settings`, `/status`, `/terms`, `/premium`, `/challenges`, `/c/[code]`, `/admin`, `/analytics-demo`, `/api/*`.

### Key architectural pieces

- **`src/middleware.ts`**: two jobs, in order.
  1. Sport redirect — unprefixed requests (`/`, `/best-bets`, etc.) → `/${cookie.sport ?? 'nba'}/...`. Runs before auth so URL is canonical before any render.
  2. Session verification (unchanged from before).
- **`src/app/[sport]/layout.tsx`**: validates `sport` param against `{nba, mlb}`; `notFound()` on invalid. `generateStaticParams` → both sports prerendered as SSG.
- **`src/contexts/SportContext.tsx`**: rewrite. Sport derives from `useParams().sport`; cookie fallback on sport-agnostic pages. `setSport` does `router.push` + sets `sport` cookie (1-year max-age). Public API `{ sport, setSport }` unchanged — zero consumer changes needed. `SportProvider` kept as passthrough so `providers.tsx` is untouched.
- **Nav components** (Header, BottomNav, Footer): all hrefs sport-prefixed. `Header.buildNavItems(sport)` factory; Footer reads sport from context; BottomNav too.
- **Cross-sport redirects** live in the pages, not middleware: `/mlb/trends` → `/mlb/pitchers`, `/nba/pitchers` → `/nba/trends`. Handled via `useRouter().replace()` inside the page component.

### Verification

- `tsc --noEmit` clean
- `next build`: 38 routes generated (NBA × 7 + MLB × 7 + sport-agnostic + API)
- Full test suite: **549/549** logic tests pass. No regressions.
- Manual verify: `curl /` → 307 → `/nba`; `curl /mlb/best-bets` → 200.

---

## Offseason banner — two iterations, final version

### Iteration 1 (commit `12dc7c3`)

"The Bulletin" — editorial treatment. Instrument Serif italic headline, monospace dateline, masthead rule, accent hairline, underlined CTA with sliding arrow.

### User feedback

> "The font is kinda too fancy or italics. Let's pick a better font. Remove the arrow next to the 'To the MLB season'. There should be a finger pointer when clicking it."

### Design-agent review (Explore agent, 400 words)

> The italic Instrument Serif reads like *New Yorker* masthead energy — too precious, clashes with the site's warm, approachable editorial tone. Replace with **DM Serif Display** (upright, single weight, contemporary, no ornament). Delete the subhead — it's placeholder copy doing placeholder work; the CTA already carries the "MLB is live" message. Right-anchored CTA creates desktop dead space — left-anchor instead. Keep the orange hairline, monospace dateline, stagger-fade — those work.

### Iteration 2 (commit `9774f7c`) — shipped

- **Font**: `DM_Serif_Display` via next/font, replaces Instrument Serif. Variable `--font-dm-serif-display`. Upright only, no italic style loaded.
- **Italic removed** from headline.
- **Subhead deleted** — just headline + CTA now.
- **Arrow removed** from CTA (`To the MLB season` with no trailing `→`).
- **`cursor-pointer` explicit** on the button (Tailwind preflight resets the default button cursor).
- **CTA left-anchored** (`justify-start` not `sm:justify-end`).
- Stagger retightened: 0ms dateline → 80ms rule → 160ms headline → 240ms CTA (was 320ms before subhead removal).

Everything else preserved: the orange hairline at top, the monospace dateline, the masthead rule separator, the underlined CTA with accent-color decoration that darkens on hover, the motion-reduce bypass.

---

## Next session pickups

### Priority 1 — verify tomorrow's auto-recovery

1. **Confirm `mlb-predictions-generate` fires cleanly at 17:00 UTC tomorrow (Apr 17)** with the new OIDC config. Check `status.code` should be 0, not 13. If still failing, we've got a deeper issue than just auth (IAM, network, etc.).
2. **Confirm `deploy-phase6-export` CF handles a normal run** (no more `is_starting_pitcher` errors in logs around 17:00 UTC).
3. **Check `leaderboard.json` generated_at** is after 17:00 UTC Apr 17 with starters populated.

### Priority 2 — audit other MLB schedulers for missing OIDC

I found 21 MLB schedulers without OIDC tokens. Most are Slack reminders hitting `slack-reminder-f7p3g7f6ya-wl.a.run.app` which appears to allow unauthenticated (hasn't been breaking). But these hit real services and are worth auditing:

- `mlb-grading-daily` → `mlb-phase6-grading/grade-date`
- `mlb-predictions-generate` → `mlb-prediction-worker/predict-batch` ← **fixed this session**
- `mlb-umpire-assignments`, `mlb-props-morning`, `mlb-props-pregame`, `mlb-live-boxscores`, `mlb-overnight-results`, `mlb-game-feed-daily` → `mlb-phase1-scrapers/scrape`

Some of these may work because `mlb-phase1-scrapers` allows `allUsers` IAM binding. But the same was true of `mlb-prediction-worker` (I checked) and it still failed. Cloud Run's behavior with missing auth + allUsers is inconsistent. Recommend adding OIDC to all of them defensively.

Audit script:
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform --format="value(name.basename())" | grep "^mlb-" | while read job; do
  has_oidc=$(gcloud scheduler jobs describe "$job" --location=us-west2 --project=nba-props-platform --format="value(httpTarget.oidcToken.serviceAccountEmail)")
  uri=$(gcloud scheduler jobs describe "$job" --location=us-west2 --project=nba-props-platform --format="value(httpTarget.uri)")
  if [[ "$uri" == *"run.app"* ]] && [[ -z "$has_oidc" ]]; then
    echo "MISSING OIDC: $job → $uri"
  fi
done
```

Also worth persisting to YAML source-of-truth: `deployment/scheduler/mlb/` already has some YAML files; add OIDC config there so future re-creates don't drop it again (this is how Session 515 apparently broke it — URL updates without re-adding auth).

### Priority 3 — leverage MLB UNDER (still open from this morning)

From the S537 MLB investigation conversation:

**12-day graded performance by edge bucket:**

| Edge | OVER N | OVER HR | UNDER N | UNDER HR |
|---|---|---|---|---|
| ≥1.0 | 12 | 50.0% | 5 | **100.0%** (5–0) |
| 0.75–1.0 | 5 | **80.0%** | 5 | **80.0%** |
| 0.5–0.75 | 8 | 50.0% | 11 | 54.5% |
| <0.5 | 27 | ~49% | 19 | ~58% |

UNDER is dominant at every edge bucket. MLB has `UNDER_ENABLED=false` in `ml/signals/mlb/best_bets_exporter.py`. Enabling it would add ~10–12 picks over the last 12 days at 80–90% HR.

**Before flipping the env var**: run `scripts/mlb/training/season_replay.py` with UNDER enabled over the 2024-2025 season. Confirm the 65% UNDER HR isn't a 12-day artifact. If it holds, flip `MLB_UNDER_ENABLED=true` on the prediction worker.

**Do not enable UNDER without the replay.** NBA's hard-won lesson (Session 488) is that short-window CF HR can be misleading.

### Priority 4 — Session 536 frontend TODOs (still not done)

- Analytics tracking hooks (Mixpanel/GA4) on PitcherModal. Zero coverage. Port the pattern from `PlayerModal`.
- View Full Season drilldown on PitcherModal (NBA pattern).
- Dynamic XAxis interval formula port (`Math.floor(length/5) - 1`). Cosmetic.

### Priority 5 — small frontend polish

- **Flash on MLB-cookie users**: first render is NBA default (server doesn't know the cookie), then middleware redirects to `/mlb/...`. There's a ~50ms flash before the redirect resolves. For a premium feel, add an inline `<script>` in `layout.tsx` `<head>` that reads the `sport` cookie and adds a `data-sport` attribute to `<html>` before hydration — same pattern the theme toggle uses. Pretty minor; do if frontend polish matters.
- **Hard-refresh reminder**: tell any visitors on the prod domain to `Ctrl+Shift+R` once to bust the old bundle. Otherwise they may see the old banner for a session.

---

## Files changed this session

### `nba-stats-scraper`

| File | Change |
|---|---|
| `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | New `_fetch_opponent_k_defense` + `_fetch_strikeout_zones` methods (S536 work); `is_starting_pitcher` hotfix (S537) |
| `docs/09-handoff/2026-04-16-SESSION-536-HANDOFF.md` | S536 handoff committed |
| `docs/09-handoff/2026-04-16-SESSION-537-HANDOFF.md` | **This file** |

### `props-web`

| File | Change |
|---|---|
| `src/app/layout.tsx` | DM Serif Display via next/font (was Instrument Serif) |
| `src/app/globals.css` | `--font-editorial` mapping, editorial-rise keyframes, `.editorial-stagger` class (reduced-motion safe) |
| `src/app/[sport]/layout.tsx` | NEW — sport param validation + `generateStaticParams` |
| `src/app/[sport]/page.tsx` | Moved from `src/app/page.tsx`; offseason date seeding, sport-aware hooks |
| `src/app/[sport]/best-bets/page.tsx` | Moved from `src/app/best-bets/page.tsx` |
| `src/app/[sport]/results/page.tsx` | Moved + offseason date seeding |
| `src/app/[sport]/results/PerformanceModal.tsx` | Moved |
| `src/app/[sport]/picks/page.tsx` | Moved |
| `src/app/[sport]/trends/page.tsx` | Moved + cross-sport redirect to `/mlb/pitchers` |
| `src/app/[sport]/pitchers/page.tsx` | Moved + cross-sport redirect to `/nba/trends` |
| `src/app/[sport]/players/page.tsx` | Moved |
| `src/components/ui/BackendStatusIndicator.tsx` | Offseason banner rewrite (two iterations) |
| `src/components/modal/PitcherModal.tsx` | S536 confidence meter + opponent K + rest splits + strike-zone heartbeat |
| `src/components/modal/PitcherModal.test.tsx` | NEW — 8 tests for provider + hook + dialog + tablist + escape |
| `src/components/layout/Header.tsx` | Sport-prefixed NAV_ITEMS factory; regex matcher for switcher visibility |
| `src/components/layout/BottomNav.tsx` | Sport-prefixed hrefs |
| `src/components/layout/Footer.tsx` | Sport-prefixed hrefs via `useSport()` |
| `src/components/admin/AdminGuard.tsx` | Sport-aware redirect |
| `src/components/layout/BottomNav.test.tsx` | Updated to assert `/nba/...` paths; added missing `useSport` mock |
| `src/contexts/SportContext.tsx` | Rewrite: URL-derived via `useParams`, cookie fallback, `setSport` navigates + sets cookie |
| `src/hooks/useEffectiveDate.ts` | Accept sport, skip snap during offseason |
| `src/lib/pitchers-types.ts` | Add `opponent_k_rate/rank/rank_of`, `PitcherStrikeoutZones` types (S536) |
| `src/lib/sport-config.ts` | `getInitialPageDate(sport)` helper; editorial offseason copy |
| `src/middleware.ts` | Sport redirect layer added before auth verification |

**Renames tracked cleanly via `git mv`** — `git log --stat` shows 95–100% rename similarity on all 7 page moves.

---

## Key lessons

1. **"Edge compression" was a partial story.** The Session 536 handoff blamed the MLB drought on edge compression. The real root cause was infrastructure (scheduler auth, exporter bug) — edge compression was a secondary factor. **Always check infra before blaming the model.** Scheduler `status.code: 13` + 10ms time-to-fail is auth, not app.

2. **BQ column names: `bq show --schema` first.** The `is_starting_pitcher` bug could have been caught in seconds by running `bq show --schema --format=prettyjson mlb_analytics.pitcher_game_summary` before writing the SQL. Added to my mental checklist.

3. **`pitcher_game_summary` is one row per starting-pitcher start**, not per pitcher-appearance. No role filter is needed — every row is already a start. The `is_starting_pitcher` filter was both wrong AND redundant.

4. **Cloud Run + missing OIDC with allUsers IAM is inconsistent.** Even though `mlb-prediction-worker` has `allUsers` binding, requests without OIDC were getting rejected with 5xx at the HTTP layer before reaching the app. Worker logs showed NOTHING. Don't trust IAM alone — add OIDC to every scheduler hitting a `*.run.app` URL defensively.

5. **URL routing > localStorage for sport identity.** Share links, SEO, back/forward navigation, SSR correctness — URL wins on every axis. localStorage is correct for theme toggle (personal, invisible, non-shareable). Sport is part of page identity.

6. **Design-agent review caught what user feedback didn't articulate.** User said "font is kinda fancy." Agent's "precious *New Yorker* masthead energy" gave the actual diagnosis. Useful to invoke fresh eyes on UI work even after user feedback.

7. **`git mv` + later content edits show as RM in status.** If you want clean rename-only commits, split the rename commit from the content edit commit. I bundled them in the URL routing commit — still readable, but split would be cleaner in retrospect.

---

## Deployment status at session end

**Auto-deploys from pushes** (verify `gcloud builds list --region=us-west2 --limit=5`):

- `d08a26ed` → `deploy-phase6-export` + `deploy-post-grading-export` + `deploy-live-export` all SUCCESS as of 17:57 UTC
- `ab3ce398` → same three triggers, all SUCCESS as of 18:12 UTC
- props-web → Vercel auto-deploy from `main` (status unknown from my side; visit `playerprops.io` and hard-refresh to verify)

**Manual infra change** (not code):

- `mlb-predictions-generate` scheduler: OIDC added via gcloud. Not in a YAML source-of-truth file — consider adding for next deploy cycle. Diff preserved in session context.

**Nothing left uncommitted.** Clean working tree on both repos.
