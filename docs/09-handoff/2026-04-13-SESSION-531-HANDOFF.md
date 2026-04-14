# Session 531 Handoff — 2025 backfill + expected arsenal + MLB frontend IA + pitcher modal v1

**Date:** 2026-04-13
**Focus:** Options A/B/C from Session 530 plan; then MLB frontend info-architecture fixes + pitcher modal v1
**Commits:**
- `nba-stats-scraper`: `c65b487a`, `2b9fc878` (2 commits)
- `props-platform-web`: `893371c`, `47b130d`, `577756e`, `89e505b`, `309d73f`, `2b68791`, `46650c4` (7 commits)

---

## TL;DR

Completed Session 530's full A/B/C plan: backfilled 2025 MLB per-pitch season (710K pitches, 0 errors), shipped expected-arsenal views + exporter + UI, and wired a monthly signal correlation reminder. Then fixed user-reported MLB UX issues: sport-default flipped to MLB, NBA offseason copy, tonight/trends/pitchers pages all broken ("Coming Soon" placeholders) replaced with real data, design language unified with NBA (PitcherCard tile + Last5KGrid colored squares mirroring PlayerCard + Last10Grid), and finally built a **pitcher modal v1** to replace the full profile page.

**Handoff-next-session priority: rethink modal content.** The modal shell + interaction is locked in and good. The tab structure (Overview / Arsenal / Game Log) and section ordering was a fast first cut based on 8-agent synthesis, but **the user explicitly wants to reconsider what belongs in it.** The 8-agent brainstorm + 2-agent review are documented in this handoff for the next session to build on.

---

## What Was Done

### Option A — 2025 historical per-pitch backfill (commit `c65b487a`)

**Script:** `bin/backfill/backfill_mlb_game_feed_range.sh` — date-range wrapper around the scraper (`--group test` → `/tmp`) + GCS upload + processor invocation. Idempotent via processor scoped DELETE per `(game_date, game_pk)`. 2s sleep between dates.

**Run:** 2025-03-27 → 2025-10-31, 219 dates processed, 37 off-days skipped, **710,639 pitches, 0 errors**, ~62s/date, ~3.5h total wall time. Full-season coverage by month: Apr 114K, May 120K, Jun 116K, Jul 107K, Aug 124K, Sep 110K.

**Arsenal coverage jump:** `pitcher_pitch_arsenal_latest.source` went from 137 feed-sourced + 760 statcast-fallback → **910 all feed-sourced**. Statcast fallback effectively retired.

### Option B — Expected arsenal metrics (commit `c65b487a`)

**Two new BQ views:**

1. **`mlb_analytics.league_pitch_type_stats`** — per pitch type: league_whiff_rate, league_csw_rate, league_called_strike_rate, league_in_zone_rate, league_avg_velocity, league_avg_spin. Min sample 500 pitches. Baselines look correct (SL 31.4%, ST 29.6%, FS 32.4%, FF 18.4%).

2. **`mlb_analytics.pitcher_expected_arsenal_latest`** — per pitcher, arsenal-weighted:
   - `expected_whiff_pct` / `actual_whiff_pct` / `whiff_vs_expected_pp` (deception premium)
   - `expected_csw_pct`
   - `stuff_velocity_premium` (arsenal-weighted avg velo vs league)
   - `is_reliable` gate: source=`game_feed_pitches` AND arsenal_coverage_pct ≥ 70 AND total_pitches_sampled ≥ 300 (excludes short-sample reliever noise). 216 reliable pitchers as of this session.

**Validated starters:** Wheeler +11.9pp deception, Skubal +4.8pp, Webb −5.1pp (sinker/command profile, negative expected), Skenes +1.3pp with +3.1 velo premium. Numbers match scouting.

**Exporter:** `data_processors/publishing/mlb/mlb_pitcher_exporter.py::_fetch_expected_arsenal` added; `expected_arsenal` block on each profile JSON (null when gate fails). All 299 profiles re-exported.

### Option C — Monthly signal correlation reminder

**Cloud Scheduler job:** `mlb-arsenal-correlation-monthly` at 1st of month 9 AM ET. POSTs to existing `slack-reminder-f7p3g7f6ya-wl.a.run.app` CF. Message: run `scripts/mlb/analysis/arsenal_signal_correlation.py`, review any metric tier with ≥5pp HR deviation and N≥30, promote to shadow signal in `ml/signals/mlb/signals.py`. First fire: 2026-05-01. Test-fired successfully this session.

### Last-5 K history on tonight entries (commit `2b9fc878`)

Each `leaderboard.json` tonight starter now carries `last_5_results` (O/U/NL), `last_5_k` (actual K totals), `last_5_lines` (K lines). Derived from existing `game_logs` fetch in `mlb_pitcher_exporter.py`. Powers the Last5KGrid on PitcherCard tiles without a profile fetch.

### Frontend — sport-aware banner + default MLB (commits `893371c`, `47b130d`)

- `sport-config.ts` with `SPORT_META` (emoji, displayName, offseasonMessage, regularSeasonEndDate per sport)
- `SPORT_META.nba.regularSeasonEndDate = "2026-04-12"` → banner switches to "NBA Regular season has ended. Check back next season!" copy automatically on NBA pages
- `SportContext` default flipped `"nba"` → `"mlb"` (NBA season over, MLB active)
- `ScheduleBreakBanner`: derives offseason from config OR resume_date >30 days (`OFFSEASON_THRESHOLD_DAYS`). Uses `SPORT_META` for emoji/copy (no hardcoded 🏀)
- Type `ScheduleBreak` has TODO for backend migration to `active_breaks: { nba?, mlb? }` map (deferred until ~MLB All-Star 2026-07)

### Frontend — MLB pages fixed + unified design language

User reported: `/` tonight page and `/trends` page both showed `"MLB Tonight — Coming Soon"` placeholders. Root cause: defaulting to MLB surfaced existing placeholders.

- **`PitcherCard` tile** (`components/cards/PitcherCard.tsx`) — twin of NBA `PlayerCard`: 152px rounded-md, full-width name+matchup header, 2-column body (Line/Pred/Edge/Track left, Last5 right). Opens modal on click, prefetches profile JSON on hover.
- **`Last5KGrid`** (`components/ui/Last5KGrid.tsx`) — twin of `Last10Grid`: 5 colored squares (positive/20 OVER, negative/20 UNDER, surface-tertiary NL) with K totals inside. 24px mobile / 36px desktop.
- **Shared panels** (`components/pitchers/MlbScoutingPanels.tsx`): `MlbTonightPanel` (grid), `MlbLeaderboardSection` (ranked rows), `ViewRail` (pill chip nav), mapper functions for the 4 leaderboards.

### Frontend — IA changes after "tonight and pitchers look the same" feedback (commit `309d73f`)

- **`/` home:** unchanged — tonight grid of PitcherCards
- **`/pitchers`:** NO LONGER shows tonight grid. Default tab changed from Tonight → **Hot Hands**. Tonight's slate surfaced as a compact horizontal chip strip at top (`TonightStrip`) for quick modal access without duplicating the home page
- **`/trends`:** when `sport === "mlb"` → `router.replace("/pitchers")`. Leaderboards live on `/pitchers` only
- **Header nav:** sport-aware `NAV_ITEMS_NBA` (Best Bets / Tonight / Trends) vs `NAV_ITEMS_MLB` (Best Bets / Tonight / Pitchers)
- **BottomNav mobile:** swaps third slot Trends → Pitchers when sport=mlb

### Frontend — Pitcher modal v1 (commits `309d73f`, `2b68791`, `46650c4`)

After 8-agent brainstorm + 2-agent review, shipped a first-cut modal that replaced the full profile page.

**Shell (`components/modal/PitcherModal.tsx`):**
- Mirrors NBA `PlayerModal` architecture: backdrop + dialog, escape-to-close, focus trap, body-scroll lock, swipe-to-dismiss on mobile (`useSwipeToDismiss`, threshold 80)
- **Mobile:** full viewport (`h-full rounded-none`)
- **Desktop:** **locked at `sm:h-[85vh]`** after user reported "modal changes vertical size when navigating tabs" — shell stays stable, content scrolls inside
- Prev/next pitcher navigation in header (uses the starters array passed from the card's `relatedStarters` prop OR the leaderboard row's `relatedPitchers`)
- Own Provider (`PitcherModalProvider`) wired in `providers.tsx` between `PlayerModalProvider` and `ChallengeModalProvider`

**Card refactor:** `PitcherCard` changed from `<Link>` → `<button onClick={openModal}>`. Seed starter passed for instant paint; profile JSON fetched in background with prefetch on `onMouseEnter`/`onFocus`.

**Content tabs (Overview / Arsenal / Game Log):**

| Tab | Current sections |
|---|---|
| **Overview** | Hero verdict card (Line/Pred/Edge + OVER/UNDER/PASS pill + Last5KGrid) → "Why" evidence chips (6 derived from existing profile fields, NOT from `pick_angles`) → Track record card with OVER/UNDER split + rank |
| **Arsenal** | Pitch arsenal bars (width=usage, color=whiff intensity) → Arsenal Quality (whiff vs expected, velo vs league) → Advanced metrics (putaway / velo fade / concentration) |
| **Game Log** | Deduped recent starts table + OVER/UNDER record summary |

**Sticky matchup bar** above tabs (`TEAM vs OPP`).

**Tab switching resets to Overview** when prev/next pitcher switcher fires.

### Frontend — overflow fix (commit `46650c4`)

User reported "white sliver on the right side of the browser." Added root-level guard in `globals.css`:
```css
html, body {
  overflow-x: hidden;
  max-width: 100vw;
}
```
Kept `scrollbar-gutter: stable` (prevents vertical scrollbar jitter). Catches any accidental horizontal overflow without hunting the specific element.

### Frontend — deleted the profile page (commit `2b68791`)

User said: *"I don't like having a full profile page like this, I only want modals with tabs like we do for NBA. Modals are nice and don't lose your context on the page."*

- **Deleted** `src/app/pitchers/[slug]/page.tsx` entirely
- `MlbLeaderboardSection` rows: converted `<Link>` → `<button onClick={openModal}>` so clicking a leaderboard entry opens the modal instead of navigating
- Removed "Open full profile →" CTA from the modal
- Every click on any pitcher anywhere on the site now opens the modal; users never lose their list/grid position

---

## System State

### BigQuery

| Object | Change |
|---|---|
| `mlb_raw.mlb_game_feed_pitches` | 710K new rows (2025-03-27 → 2025-10-31) added to existing 64K 2026 rows |
| `mlb_analytics.league_pitch_type_stats` | **new** |
| `mlb_analytics.pitcher_expected_arsenal_latest` | **new**, 910 pitchers (216 reliable) |
| `mlb_analytics.pitcher_pitch_arsenal_latest` | unchanged schema; feed-source coverage jumped 137 → 910 |

### GCS API bucket

- `gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json` — now carries `last_5_results/last_5_k/last_5_lines` on each tonight starter
- `gs://nba-props-platform-api/v1/mlb/pitchers/{pitcher_lookup}.json` — 299 files re-exported with `expected_arsenal` block

### Cloud Scheduler

- **new:** `mlb-arsenal-correlation-monthly` (1st of month, 9 AM ET)
- First fire: 2026-05-01

### Cloud Run

- `nba-phase2-raw-processors` — no deploy (no code change)
- `phase6-export` — no deploy (change was in shared exporter, re-ran locally)

---

## The Open Question For Next Session

**The user's ask:** "*I want a new session to think back through what should be in the modal.*"

The modal shell, interaction, sizing, and entry/exit are all locked in and working. What's open is the **content architecture** — the three tabs and their sections were a fast first cut built from the 8-agent synthesis. Several directions weren't fully explored.

### What was shipped (the v1 baseline to critique)

```
┌─ Matchup bar (sticky): TEAM vs OPP
├─ Tab bar (sticky): [Overview] [Arsenal] [Game Log]
│
├─ Overview tab:
│   ├─ Hero verdict card (Line/Pred/Edge + OVER/UNDER pill + Last5KGrid)
│   ├─ "Why" evidence chips (up to 6, derived client-side)
│   └─ Track record card (hit rate + OVER/UNDER split + rank)
│
├─ Arsenal tab:
│   ├─ Pitch arsenal bars (usage × whiff × velo)
│   ├─ Arsenal Quality (whiff vs expected + velo vs league)
│   └─ Advanced (putaway / velo fade / concentration)
│
└─ Game Log tab:
    ├─ OVER/UNDER record summary
    └─ Deduped recent starts table
```

### Key decisions that got made fast and are worth revisiting

| Decision | Rationale at the time | Worth revisiting |
|---|---|---|
| 3 tabs | Reviewer Agent 1 said "2 tabs max or single-scroll" — I went with 3 for cleaner separation | Is the Arsenal/Log split overkill? Could be 2 tabs, single scroll, or *more* sub-tabs within Arsenal |
| Numeric hero (not prose) | Reviewer preferred numbers, Agent 3 pushed narrative verdict | Narrative could live as a sub-header below Line/Pred/Edge; not either-or |
| No K trajectory chart | Reviewer Agent 1 said YAGNI — Last5KGrid carries the signal | Agent 2 specifically argued this as the defining signature visual. The L5 squares don't show line-vs-actual gap the way a dotted overlay would |
| No percentile rail (Baseball Savant style) | Not in v1 scope | Agent 7 called this out — could be a hero band above the tabs |
| No matchup context (opponent K-rate, park, umpire) | Data gaps flagged; no opponent splits in JSON | Requires backend work but is the #1 UX gap for prop bettors (Agent 7: "Path to the Line" narrative) |
| Evidence chips derived client-side | `pick_angles` not on profile JSON (reviewer confirmed) | Backend could add a proper signals array; currently we fake it |

### The 8-agent brainstorm captured (for the new session to mine)

Frontend lenses:
1. **Pattern-match NBA modal** (Agent 1) — catalog of copy/swap/new/omit. Ended at "2 tabs, Tonight + Arsenal"
2. **Info-dense pitching lab** (Agent 2) — 5 ranked viz ideas: K trajectory chart, arsenal whiff-usage scatter bars, velo fade strip, whiff-vs-expected delta bar, home/away split bars
3. **Narrative / "why does the model like this"** (Agent 3) — prose verdict above numbers, categorized FOR/AGAINST evidence ladder, "known risks" section framed as "model priced this in"
4. **Mobile-first thumb zone** (Agent 4) — sticky 124px chrome, swipe-dismiss restricted to top 60px, long-press game-log rows for secondary stats, no modal on desktop (page instead — we overruled this)

Strategic lenses:
5. **Data inventory** (Agent 5) — top 10 decision-utility fields; 3 available-but-not-shown; 3 wished-for; 3 de-emphasize
6. **User journeys** (Agent 6) — 5 entry paths (tonight grid / best bet / hot hands / model's favorites / shared link); Journey A wins ties; junk journey = fantasy/ROS context
7. **Competitive landscape** (Agent 7) — steal Savant percentile rails, FanGraphs game-log trend arrows, Action Network matchup delta card. Under-served opportunity: **"Path to the Line"** narrative fusing projection + lineup composition + pitch efficiency
8. **UX for bettors** (Agent 8) — anchor to the book's line, recency weighted 3x, communicate variance, track record as trust anchor, PASS as first-class, confidence visually encoded

### The 2-agent review ground-truth findings (must respect)

- **`pick_angles` is NOT on the profile JSON.** Only on best-bets JSON. Either add to backend exporter (~1 week) or derive client-side.
- **Duplicate game log rows** — Wheeler's `2025-05-29 vs ATL` appears twice verbatim. Real backend bug. Current client-side dedup works but upstream fix is better.
- **`strikeouts_line: null` in early-season games** — any K Trajectory chart must handle missing line gracefully.
- **`leaderboard.tonight.starters`** is the sibling nav list. Leaderboard-entered pitchers get no swipe nav (non-tonight pitcher has empty `relatedPitchers`).
- **`recharts@3.6.0` is available** in package.json. Don't hand-roll SVG unless size-critical.

### Data contract snapshots (for the next session's reference)

```bash
# Full pitcher profile shape
gsutil cat gs://nba-props-platform-api/v1/mlb/pitchers/zack_wheeler.json | python3 -m json.tool

# Tonight's leaderboard — tonight entries + 4 leaderboards
gsutil cat gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json | python3 -m json.tool

# Today's best bets (where `pick_angles` DO exist, if we want to surface them)
gsutil cat gs://nba-props-platform-api/v1/mlb/best-bets/2026-04-13.json | python3 -m json.tool
```

Profile JSON top-level keys: `generated_at, pitcher_id, pitcher_name, team, tonight, track_record, game_log, pitch_arsenal, advanced_arsenal, expected_arsenal`.

### Suggested ways in for the next session

A few angles a fresh session could take — not prescriptive, just primers:

1. **"What's the 15-second answer?"** — Agent 8's framing. If a bettor only has 15 seconds, what must the modal prove? Start there, cut everything that doesn't serve it.
2. **Journey-A-first rebuild** — Agent 6 said 60-70% of modal opens are from the tonight grid. Design the modal specifically for that journey; other journeys (best-bet receipt check, hot-hands drilldown, shared link) are secondary variants.
3. **"Path to the Line" narrative** — Agent 7's under-served opportunity. A single readable sentence: *"Needs 6 Ks. Model projects 5.2 IP × 26 TBF × 28% K-rate = 7.3 expected. Cleared line in 7 of last 10."* This would be radically different from the current stat-dashboard approach.
4. **Scrap tabs, go single-scroll with anchors** — Agent 4 suggested anchor chips instead of tabs. If the content per tab isn't dense enough to earn a tab, fold it.
5. **Add backend `pick_angles` first** — if we want proper narrative, fix the data contract. `ml/signals/mlb/` already generates angles for best-bets; extending to all pitchers is straightforward.

---

## What To Work On Next

### Primary: rethink pitcher modal content (user's explicit ask)

- Start fresh; review this handoff + sample the three JSON files above
- Consider which of the 8 agent lenses resonates (they conflict — Agent 2 wants density, Agent 3 wants prose, Agent 4 wants sparse thumb-zone UX)
- Decide: tabs vs single-scroll, numeric vs narrative hero, what visualizations (if any) beyond Last5KGrid
- The shell, sizing, nav, prefetch are locked — don't redesign those

### Secondary (if time): backend support

- Add `pick_angles` to the pitcher profile exporter so narrative can be data-driven
- Fix the game-log dedup at the SQL level (`_fetch_game_logs` in `mlb_pitcher_exporter.py` — dedup by `(pitcher_lookup, game_date)`)
- Add opponent K-rate vs handedness view (agent-flagged #1 data gap for bettors)

### Deferred from Session 530 (still live)

- Historical 2025 backfill — **DONE** this session
- Expected K% by arsenal (Option B original spec) — shipped the whiff-based version; full K-rate projection requires PA-sequencing logic and is a separate research project
- Monthly correlation re-run — scheduled, first fire May 1

---

## Files Changed

### `nba-stats-scraper`

| File | Change |
|---|---|
| `bin/backfill/backfill_mlb_game_feed_range.sh` | **new** — date-range backfill runner |
| `schemas/bigquery/mlb_analytics/league_pitch_type_stats.sql` | **new** — league baselines per pitch type |
| `schemas/bigquery/mlb_analytics/pitcher_expected_arsenal.sql` | **new** — expected vs actual arsenal metrics |
| `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | `_fetch_expected_arsenal()` + `expected_arsenal` on profile; `last_5_results/k/lines` on tonight entries |

### `props-platform-web`

| File | Change |
|---|---|
| `src/components/cards/PitcherCard.tsx` | **new** — NBA PlayerCard twin, opens modal |
| `src/components/ui/Last5KGrid.tsx` | **new** — Last10Grid twin, K totals |
| `src/components/pitchers/MlbScoutingPanels.tsx` | **new** — shared Mlb panels, mappers, ViewRail |
| `src/components/modal/PitcherModal.tsx` | **new** — bottom-sheet modal with tabs |
| `src/lib/sport-config.ts` | **new** — `SPORT_META` + `isPastRegularSeason` |
| `src/lib/pitchers-types.ts` | `PitcherLastNResult`, `PitcherExpectedArsenal`, last_5_* on TonightStarter |
| `src/app/providers.tsx` | Mount `PitcherModalProvider` |
| `src/app/page.tsx` | MLB tonight grid replaces Coming Soon placeholder |
| `src/app/pitchers/page.tsx` | Redesigned — leaderboards hub + TonightStrip; default tab Hot Hands |
| `src/app/pitchers/[slug]/page.tsx` | **deleted** — everything is in the modal |
| `src/app/trends/page.tsx` | MLB path redirects to `/pitchers` |
| `src/app/layout.tsx` | (touched + reverted) Fraunces/JetBrains Mono experiment; final state = Inter only |
| `src/app/globals.css` | `html, body { overflow-x: hidden; max-width: 100vw }` |
| `src/components/layout/Header.tsx` | Sport-aware desktop nav |
| `src/components/layout/BottomNav.tsx` | Sport-aware mobile bottom nav |
| `src/contexts/SportContext.tsx` | Default `"nba"` → `"mlb"` |
| `src/components/ui/BackendStatusIndicator.tsx` | `ScheduleBreakBanner` uses `SPORT_META` + regularSeasonEndDate |

---

## Lessons / Guardrails

- **`pick_angles` is best-bets-only.** Don't assume every pitcher-facing UI can read it. Profile JSON lacks it entirely; fall back to client-side derivation or expand the backend exporter.
- **Client-side game-log dedup required.** `_fetch_game_logs` occasionally emits duplicate `(date, opponent, K)` rows. Fix at SQL level eventually; dedup on render in the meantime.
- **Locked modal height prevents tab jitter.** `sm:h-[85vh] sm:max-h-[85vh]` beats `sm:h-auto`. Content-driven resize is bad UX across tabs of different density.
- **`html, body { overflow-x: hidden }` is a safe universal guard** for viewport-wide slivers. Doesn't conflict with `scrollbar-gutter: stable`.
- **Backend scoped DELETE on re-export doesn't remove stale best-bets rows.** Edge-halt days (2026-03-28+) have `best_bets: []` in the daily JSON — relying on best-bets as a pick_angles source gives nothing during halt regimes.
- **Scrapers running locally via `--group test` bypass Cloud Run timeouts.** The 300s Cloud Run limit risk from reviewer agents never materialized because the backfill loop runs on the dev box, not as a scheduler invocation.
- **219 dates at 62s/date = 3.5h.** Rate-limit sleep of 2s between dates was sufficient; MLB Stats API never throttled.

---

## Memory Updates

Worth storing:
- **710K pitches backfilled 2025 season, zero errors** — arsenal coverage went 137 → 910 feed-sourced pitchers, statcast fallback path now rarely used
- **`pitcher_expected_arsenal_latest` is the new "deception premium" view** — `whiff_vs_expected_pp >= 5` is the "elite stuff" tier, validated on Wheeler (+11.9) and Skubal (+4.8)
- **`mlb-arsenal-correlation-monthly` Cloud Scheduler** fires 1st of month 9 AM ET — re-run arsenal signal correlation as data accumulates
- **MLB frontend info architecture:** `/` = tonight grid, `/pitchers` = leaderboards hub + tonight strip, `/trends` redirects for MLB, no `/pitchers/[slug]` page, all clicks open pitcher modal
- **`SPORT_META.nba.regularSeasonEndDate = "2026-04-12"`** — update yearly when NBA final regular-season game is known (currently hardcoded; could be derived from schedule later)
- **Pitcher modal content is UNSETTLED** — shell is final, sections/tabs are v1 and being rethought next session

---

## Model Recommendation for Next Session

**Opus.** The next session is a design-thinking task (what belongs in the modal) with many agent perspectives to weigh. Shell implementation is done, so heavy Sonnet-speed execution isn't needed. Opus handles conflicting design lenses + user taste calibration better; save Sonnet for when the content is decided and we're building it.

If the user pivots mid-session to shipping a specific variant (e.g. "add a K trajectory chart"), that's Sonnet-appropriate work.
