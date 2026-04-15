# Session 532 Handoff — MLB frontend discipline, leaderboard grids, modal charts, design brainstorm

**Date:** 2026-04-14
**Focus:** Strip prediction content from MLB non-best-bets pages, add modal charts, leaderboard card grid, editorial PitcherCard v2. Plus: 8-agent MLB design brainstorm with 10 HTML prototypes saved for reference.
**Commits:**
- `nba-stats-scraper`: none (this repo — handoff-only)
- `props-platform-web`: `bb6dccf`, `2fa486a`, `a88dd19` (3 commits)

---

## TL;DR

Two things shipped this session + a big design brainstorm left on the runway for next session.

**Shipped (frontend only):**
1. **Modal charts** — K Trajectory (recharts bar + line), Arsenal Bubble (SVG scatter), log summary pills, and Splits card (home/away + L3/L5/L10). Fills the "give me visuals like NBA" gap.
2. **No-model-content discipline on MLB non-best-bets surfaces** — PitcherCard, TonightStrip, and leaderboards now show only observed stats. Edge / projection / recommendation all stripped from the tonight grid and pitchers-page chips. Renamed "Model's Favorites" → "Best Record" with clean copy.
3. **Leaderboard row list → card grid** — 2-col mobile, 3-col desktop. New `LeaderCard` with rank badge, big stat, statTone coloring.
4. **PitcherCard v2** — editorial card-story layout. 40px tabular K line as focal point, L5 avg beside it with colored delta, Last-5 grid, italic narrative hook derived from observed data ("Three straight OVERS — running hot."), tiny receipts row. Hot-streak 3px amber left border when L3 are all OVER. Still zero model fields.

**Not shipped — design research for next session:**
- 8 agents (2 research, 4 frontend-design, 2 Opus synthesis/creative) produced 10 HTML prototypes in `/tmp/` + a prioritized roadmap + a creative director brief with 8 design angles.
- Three follow-up projects are fully scoped below: Outing Script section (matchup context), Strike Zone Heartbeat (signature visual), and Ledger alt-view on Line Beaters.

---

## What Was Done

### Phase 1 — Modal charts (commit `bb6dccf`)

Added real visualizations to `PitcherModal.tsx` so the modal stops being all text:

- **`KTrendChart`** — recharts `ComposedChart`. Bar per start (last 10, oldest→newest) colored emerald/rose by OVER/UNDER; amber dashed line connects per-game K-line dots. K totals labeled above each bar. Live legend top-right. Lives on the Overview tab.
- **`ArsenalBubble`** — pure SVG scatter. X=usage%, Y=whiff%, bubble radius = usage, each pitch type gets a unique color (cyan/violet/amber/emerald/red/indigo/orange). Glow ring on elite (≥30% whiff) pitches. Weighted-avg whiff reference line in amber dashed. Legend row below plot. Lives on the Arsenal tab, above the existing bar list.
- **Log summary pills** — Avg K, Range, OVER%, Record. OVER% color-toned (≥55% green, ≤45% red).
- **`SplitsCard`** — new Overview section. Home/Away split (avg K, N, O%) + L3/L5/L10 recent-form windows. All derived from `game_log`.

Recharts imports added to `PitcherModal.tsx`. Null-safe throughout — pitches missing `usage_pct` or `whiff_rate` filtered out before SVG math.

### Phase 2 — No-model-content discipline (commit `2fa486a`)

User caught that MLB pages were showing prediction fields on non-best-bets cards/pages, which contradicts NBA's rule ("no model references on tonight/trends pages, only best bets"). Cleaned up:

**`PitcherCard.tsx` (v1 pass):**
- Removed `PRED / EDGE / RECOMMENDATION` from the 2×2 stat grid
- Replaced with `LINE | L5 AVG K` mirroring NBA's `LINE | AVG` pattern
- L5 avg colored green when above line, red when below
- Renamed "Track" label → "Hit Rate"

**`TonightStrip` on `/pitchers`:**
- Removed edge values + OVER/UNDER chip coloring
- Replaced with: K line (book stat) + green dot indicator for Best Bets

**`MlbScoutingPanels.tsx`:**
- `MlbLeaderboardSection` rows → 2/3-col card grid
- New `LeaderCard` component: rank badge, name, team, big stat, sub detail, `statTone` coloring (positive/negative/neutral)
- `mapModelTrusts` sub description: `"12-3 · avg edge 1.45"` → `"12-3 record"` (edge removed)
- Tab order changed: Hot Hands → Strikeout Kings → Line Beaters → Best Record
- "Model's Favorites" tab renamed to **"Best Record"** with clean copy

**Pitchers page (`/pitchers`):**
- `max-w-3xl` → `max-w-4xl` to give the card grid breathing room

### Phase 3 — PitcherCard v2 editorial layout (commit `a88dd19`)

Replaced the stat-grid layout with the Card Story hierarchy from the Opus brainstorm. Still observation-only (no model content):

- 40px tabular K LINE number as the focal point (up from 16px)
- L5 avg beside it with `+0.5` delta chip colored by position vs line
- Last-5 result grid on the right (unchanged behavior)
- **Italic narrative hook** derived client-side from `last_5_results + last_5_k + strikeouts_line + is_home`. Examples: "Three straight OVERS — running hot.", "L5 average 1.2 K above tonight's line on the road.", "Line matches his recent form."
- Compact receipts row at bottom: `L5 4-1 · Hit 83% · 23p`
- Hot-streak 3px amber left-border accent when L3 are all OVER
- Best-bet 3px green left-border accent (unchanged behavior)
- Card lifts 2px + gains a subtle shadow on hover

Font stack unchanged — stayed on Inter per the Session 531 revert of a Fraunces experiment.

### Phase 4 — Design brainstorm (not shipped)

8 parallel agents. Artifacts remain on disk:

**Research outputs (in-context, not saved to files):**
- **NBA Modal Catalog** — every interesting section in `GameReportTab.tsx` + trends page + player card patterns
- **MLB Data Inventory** — full JSON shape, client-side computable stats, best-bets `angles` schema, wish-list (opponent K rate, umpire, park factors, velocity trend)

**Opus outputs:**
- **Synthesis / prioritized roadmap** — Tier 1 items: (1) Key Angles narrative, (2) Opponent K Rate section, (3) Park + Umpire chips, (4) H2H history, (5) Velocity trend sparkline. Don't-builds list is explicit.
- **Creative brainstorm** — 8 angles including Strike Zone Heartbeat as visual signature, three-beat "Path to the Line" narrative, leaderboard-as-rooms metaphor, novel derived stats nobody shows (PEI, 85-Pitch Ceiling, Walk Tax, Gas Tank Rating, Third-Time Penalty), Outing Script for pitchers.

**10 HTML prototypes in `/tmp/`:**

| File | Concept | Status |
|---|---|---|
| `mlb-prototype-tonight.html` | Tonight grid grouped by game matchup | Reference only |
| `mlb-prototype-modal-overview.html` | "Scouting Intel Brief" Overview tab with Path-to-the-Line narrative | Narrative worth stealing |
| `mlb-prototype-modal-arsenal.html` | "Baseball Savant Evolved" Arsenal tab | Scatter hero close to shipped version |
| `mlb-prototype-leaderboard.html` | Sports-almanac leaderboard page | Close to shipped version |
| `mlb-proto-v2-strike-zone.html` | **Strike Zone Heartbeat** — 60 Ks plotted, pulsing animation, pitch-colored | **Needs backend; scoped below** |
| `mlb-proto-v2-workshop.html` | "Pitcher's Workshop" — arsenal as hand-drawn physical objects | Deferred (unique but not load-bearing) |
| `mlb-proto-v2-outing-script.html` | **Outing Script** — 6 matchup chips + 4 novel stats | **Needs backend; scoped below** |
| `mlb-proto-v2-card-story.html` | Editorial card hierarchy | **SHIPPED this session (adapted, observation-only)** |
| `mlb-proto-v2-fireplace.html` | Hot Hands atmospheric room (ember particles) | Deferred (nice-to-have) |
| `mlb-proto-v2-ledger.html` | Line Beaters spreadsheet-energy alt view | **Scoped below (frontend-only)** |

---

## System State

### Frontend (`props-platform-web`)

| File | Change |
|---|---|
| `src/components/modal/PitcherModal.tsx` | +KTrendChart, +ArsenalBubble, +SplitsCard, +LogStatPill, recharts imports |
| `src/components/cards/PitcherCard.tsx` | v2 editorial layout + `deriveHook()`, observation-only |
| `src/components/pitchers/MlbScoutingPanels.tsx` | Row list → card grid, LeaderCard component, statTone coloring |
| `src/app/pitchers/page.tsx` | Tab order, "Best Record" rename, `max-w-4xl`, TonightStrip edge-stripping |

### Backend (`nba-stats-scraper`)

No changes. All this session's frontend work operated on existing GCS JSON shape.

### GCS API bucket

Unchanged.

### Cloud Scheduler / Cloud Run

Unchanged.

---

## The Three Next-Session Projects (Scoped)

### Project A — Matchup section ("Outing Script") on the modal Overview tab

**Why:** The biggest polish gap vs NBA. K props are 50% pitcher, 50% opponent. Currently every piece of data in the modal is about the pitcher in isolation. This closes the gap.

**What to build:**
A new section on the modal Overview tab (between Splits and Track Record) titled "Matchup" or "Outing Script". Renders 4-6 chips:

1. **Opponent K%** (season + vs same handedness) — e.g., "NYM · 23.8% K% · Rank 11 of 30 vs RHP"
2. **Park K factor** — e.g., "Citi Field · 102" with a slightly-K-friendly badge
3. **Pitcher's Key Angles** — 3 narrative bullets pulled from best-bets JSON `angles` array (only available when pitcher is a best bet; graceful fallback when not)
4. **H2H history** — last 3-5 starts vs tonight's opponent, filtered from existing `game_log` (zero backend, free win)
5. **Umpire K/9 tendency** — optional, only when data is available
6. **Weather / bullpen leash** — stretch

**Data needs:**
- **Available now (zero backend):**
  - `angles` from `best-bets/{date}.json` (already written there; not on profile JSON)
  - H2H: filter `profile.game_log` by `opponent === tonight.opponent`
- **Needs backend:**
  - Team K% season table (exists in raw MLB data, needs exporter → GCS or BigQuery view)
  - Park K factors (static reference table — one-time ingest job)
  - Umpire tendency (daily scrape from MLB rosters — ~1 day of work)

**Reference prototype:** `/tmp/mlb-proto-v2-outing-script.html` — cockpit aesthetic with 6-chip instrument panel + 4 novel stats. Don't literally port that aesthetic (it's too different from the rest of the app) but the *information architecture* is right.

**Effort:**
- Key Angles + H2H: **S** (~half-day, frontend only)
- Opponent K% + Park: **M** (backend: 1-2 days for exporter; frontend: 2-3 hours)
- Umpire: **M** (backend scrape + join)

**Recommended order:** Ship the frontend-only pieces (Key Angles + H2H) first this session, queue the backend work separately.

---

### Project B — Strike Zone Heartbeat (signature visual)

**Why:** The one truly distinctive visual element — something nobody else has for K props. Makes the product recognizable in screenshots. Opus creative director's #1 pick.

**What to build:**
A stylized strike zone plotted with each K from the last 20 starts as a small glowing dot, colored by the pitch type that got the K. Subtle breathing/pulse animation. Sits at the top of the Overview tab or as its own hero section.

**Data needs:**
- **Requires backend.** Need pitch-level location (plate_x, plate_z) matched to K outcomes. Source: `mlb_raw.mlb_game_feed_pitches` table (already has 710K+ 2025 rows after Session 531's backfill).
- New BigQuery view: for each pitcher, last 20 K's with pitch_type + location, aggregated into profile JSON
- Add `strikeout_locations` array to `pitcher_exporter.py` → profile JSON

**Reference prototype:** `/tmp/mlb-proto-v2-strike-zone.html` — fully designed, 60 K dots, pitch-colored with CRT glow, breathing zone animation, hover legend filter. React port should mirror the aesthetic closely.

**Effort:**
- Backend: **M** (1 day — view + exporter change + deploy)
- Frontend: **M** (1-2 days — SVG component + React port of the animations)

---

### Project C — Ledger alt view on Line Beaters (frontend-only)

**Why:** Power-user view for the Line Beaters tab. Dense spreadsheet-energy alternative to the card grid. Uses only data we already have. Provides a "sharp's view" without a backend lift.

**What to build:**
A second view mode on the Line Beaters leaderboard tab — toggle between "Cards" (current) and "Ledger" (new). The Ledger is a real `<table>` with:
- 2-digit padded rank, pitcher name (serif), team badge
- GS, Avg K, Avg Line, Margin (big + colored with sign)
- Last-10 sparkline column: inline SVG bars showing per-start margin above/below line (green up, red down, scaled to fit)
- Row hover: yellow highlighter tint + cursor-following popover showing per-start details
- Tabular-nums, Bloomberg-terminal energy

**Data needs:**
None new. Ledger consumes the same `line_beaters` leaderboard data that feeds the card grid today. The per-start sparkline needs `recent_margins` array; check if it's already in `leaderboard.json`. If not, compute client-side from profile fetches (fetch-on-hover pattern).

**Reference prototype:** `/tmp/mlb-proto-v2-ledger.html` — fully designed, real HTML table, inline SVG sparklines, spreadsheet discipline.

**Effort:**
- **S-M** (half-day to 1 day — new component + view toggle + sparkline SVG)

---

## Also Deferred

These came out of the brainstorm but weren't scoped this session:

- **Pitcher's Workshop** (`/tmp/mlb-proto-v2-workshop.html`) — arsenal as hand-drawn physical objects. Beautiful but non-load-bearing. Would replace the Arsenal bubble if we want a more distinctive aesthetic there.
- **Fireplace room** (`/tmp/mlb-proto-v2-fireplace.html`) — Hot Hands leaderboard with ember particles. Atmospheric but expensive to build and not aligned with the rest of the app's restraint.
- **Conviction pips / Edge Bar** from the card-story prototype — deliberately *not* ported because they're model-content (confidence + projection). Revisit if the "no model on non-best-bets pages" rule ever relaxes.

---

## Lessons / Guardrails

- **The no-model-content rule is load-bearing.** User caught 3 separate places (PitcherCard stat cells, TonightStrip chips, leaderboard sub-descriptions) where prediction fields were leaking onto non-best-bets surfaces. When adapting designs from prototypes, always audit for: `edge`, `predicted_*`, `recommendation`, `confidence`, and "avg edge X.XX" copy. Bettors must reach the Best Bets tab to see model output.
- **Don't add new fonts without explicit user buy-in.** Session 531 had a Fraunces/JetBrains Mono experiment that got reverted. The card-story prototype called for Fraunces — I kept Inter for the React port because of that history.
- **Client-side dedup is still required on `game_log`.** Backend occasionally emits duplicate `(date, opponent, K)` rows. The `dedupeGameLog()` helper in `PitcherModal.tsx` handles it; any new Matchup/H2H code should call the same helper.
- **Recharts `ComposedChart` with `Bar` + `Line` works cleanly.** Color cells via className with Tailwind fill classes (`fill-emerald-500/60 dark:fill-emerald-400/50`) rather than inline style — dark mode works transparently.
- **`Math.max(...array)` trips TypeScript nullability.** When reducing over arrays of `number | null`, filter with a type predicate first (`: p is X & { field: number }`) before passing to Math functions.
- **HTML prototypes are a cheap way to compare aesthetic directions.** The 10 prototypes in `/tmp/` cost about 6 agent-hours total. Worth the investment when committing to a new visual language — prevents churn of "ship → hate it → rewrite" cycles.
- **Opus is better than Sonnet for creative brainstorms and prioritization.** The synthesis agent ("what to actually build") cut through the 8 ideas from the creative brief and produced a ruthless 5-item Tier 1 with clear reasoning. Sonnet would have hedged more.

---

## Memory Updates

Worth storing:
- **MLB no-model-content rule:** PitcherCard, TonightStrip, MlbLeaderboardSection, and anywhere the tonight grid lives must show only observed stats (line, L5 avg, L5 grid, hit rate, track record count). Best Bets tab is the only surface that should show edge, projection, recommendation, conviction, or "model" copy.
- **PitcherCard v2 layout:** Big 40px K line + L5 avg + delta, Last-5 grid, italic narrative hook derived from observed data, tiny receipts row. Hot-streak 3px amber border when L3 are all OVER.
- **10 MLB design prototypes exist in `/tmp/` on naji's WSL box** (not committed to repo). Re-generate via agents if the files are lost — the prompts are in this session's transcript.
- **Strike Zone Heartbeat requires `strikeout_locations` on profile JSON** — pull from `mlb_game_feed_pitches`, filter to K-outcome pitches, aggregate last 20 starts.
- **`best-bets/{date}.json` has `angles` array; profile JSON does not.** Extending profile exporter to include `angles` when pitcher is a best bet is a ~1-hour backend task.

---

## Model Recommendation for Next Session

**Sonnet.** Project A (Matchup section) is execution work — fetch best-bets JSON, filter game_log for H2H, render chips. Standard React + TypeScript, small surface area. Sonnet moves faster here and the creative heavy lifting is already done.

If the user jumps to Project B (Strike Zone Heartbeat), consider Opus for the BigQuery view design (non-trivial aggregation across 710K pitches) but Sonnet for the React SVG port.
