# Session Handoff — 2026-05-12 — MLB Pitcher Modal Polish vs NBA Player Modal

User flagged that NBA modal looks "way better" than MLB. Three independent agents (charts, layout, polish) reviewed both files and converged on the same root cause and roughly the same fix priorities. This handoff captures their synthesis so next session can implement cleanly without re-running the review.

**Predecessors (same day):**
- `docs/08-projects/current/system-improvement-roadmap-2026-05-12/PLAN.md` (30-finding roadmap)
- Frontend: props-web commits `43b30cc`, `65b60ce`, `4ec97a7`, `053ac2e` (calendar fix, CI gate, watchdog, copy de-modeling)
- Backend: nba-stats-scraper `cc05044d`, `df10b62f`, `ac1f245f`, `badff7bd` (history backfill, freshness checks, empty-publish guard, chronological sort)

## Files in scope

- `/home/naji/code/props-web/src/components/modal/PlayerModal.tsx` (NBA, lazy-loads tabs)
- `/home/naji/code/props-web/src/components/modal/GameReportTab.tsx` (NBA tab content — the polish reference)
- `/home/naji/code/props-web/src/components/modal/PitcherModal.tsx` (MLB, 2173-line monolith)
- `/home/naji/code/props-web/src/components/ui/Last5KGrid.tsx`

## Three-agent synthesis

All three agents independently flagged that the **gap is structural + stylistic, not data** — MLB has unique Statcast assets (arsenal, putaway, velo fade, strike-zone heartbeat) that NBA *lacks*. The MLB modal just doesn't present them with NBA's editorial discipline.

### Agent 1 — Charts/graphs (under-polished MLB visualizations)

| # | Finding | File:line | Fix |
|---|---------|-----------|-----|
| 1 | **KTrendChart is 4× too short** — `h-28` (112px) vs NBA ScoringTrend `h-44` (176px) — bars stack on labels | `PitcherModal.tsx:1346` vs `GameReportTab.tsx:979` | Raise to `h-40`-`h-44`, bump `renderKLabel` `fontSize` from 8 → 10–11, fix `margin.left:-24` → `4` |
| 2 | **KTrendChart has competing dashed lines** — per-game historical `<Line strokeDasharray="3 2">` overlays the tonight `<ReferenceLine>`, plus a 4-item legend. Visual noise. | `PitcherModal.tsx:1373-1385` (line), `1387-1393` (ref), `1324-1343` (legend) | Delete the historical `<Line>`, move values to tooltip. Add right-edge `label` prop to ReferenceLine (`{ value: tonightLine, position: 'right' }`). Drop legend. |
| 3 | **NBA has Scoring Averages comparison table; MLB has no analog.** NBA shows Last 7/14/30/60-day PPG with colored `vs Szn` delta column at ±1.5 threshold — the single most informative chart in NBA. MLB's `SeasonStatsStrip` is a one-row season summary, no rolling windows, no deltas. | `GameReportTab.tsx:476-576` vs `PitcherModal.tsx:1234-1269` | Clone the NBA table into PitcherModal: rows for Last 3/5/10 starts with K/start, K/9, ERA, `vs Season` delta column using same `text-positive`/`text-negative` thresholds |
| 4 | **KDistChart cramped** — viewBox ~130×~115, fonts 7-8px, rows 13px tall. Dashed threshold line gets no label. | `PitcherModal.tsx:1114-1228` | `ROW_H` → 18, `BAR_MAX_W` → 130, add `<text>` next to threshold line with `Tonight: {tonightLine}` |
| 5 | **ArsenalBubble fonts too small** — 3.8-5px in 100×72 viewBox, blurry even after CSS scale. Y-axis only 3 ticks. | `PitcherModal.tsx:1416-1609` | viewBox → 200×144, fonts → 9-10, add 4th X tick |
| 6 | **Last5KGrid only 5 squares** vs NBA's 10-game equivalent. | `ui/Last5KGrid.tsx` | Add `Last10KGrid` variant |
| 7 | **Color encoding too saturated** — KTrendChart uses saturated emerald/rose; NBA uses muted gray gradients (`fill-gray-400/70` vs `fill-gray-300/90`). | `PitcherModal.tsx:1365-1367` | Match NBA's muted palette, or drop opacity `/60` → `/40` |

**Agent 1 "start here":** Refactor `KTrendChart` (lines 1275-1399). ~30 lines of edits in one component. "Closes 60% of the perceived-quality gap with NBA in a single PR." The chart users stare at longest.

### Agent 2 — Layout / information architecture

| # | Finding | Detail |
|---|---------|--------|
| 1 | **MLB lacks tabs.** NBA splits Game Report / Full Season Log via lazy-loaded tabs. MLB stuffs 14+ sections into one 2× viewport-height scroll. Statcast (zone, arsenal bubble, advanced) belongs on a second tab. | `PitcherModal.tsx:556-762` (current single-scroll) vs `PlayerModal.tsx:12-13` (lazy tabs) |
| 2 | **No "above the fold" anchor.** MLB stacks three context blocks (MatchupBar @ line 559, Tonight's K line panel @ 564-590, SeasonStatsStrip @ 593) before any content. NBA opens with ONE inline matchup bar then 2-col grid. | Fix: merge MatchupBar + K-line into one row: `team @ OPP · K Line: 6.5 · OPP K 24.3% (5th/30) · L5: ▣▣▣▢▢` |
| 3 | **No 2-col grid.** NBA uses `grid-cols-1 sm:grid-cols-2 gap-3` so KeyAngles pairs with ScoringTrend, GameLog with SeasonStats. MLB has it in TWO places (1599, 1662) but Evidence/Splits/Zone/Arsenal/Pitch Mix/H2H/Recent Starts are all full-width siblings. | Pair-up: `Evidence \| Splits`, `Zone \| Pitch Mix`, `H2H \| Recent Starts pills` |
| 4 | **No RecentTrends prose row.** NBA renders 3-4 plain-English sentences ("Scoring is up, averaging 28.4 PPG over last 5, +2.1 above his season average"). MLB only has terse evidence chips. Higher-impact than chips because it reads like a scouting report. | `GameReportTab.tsx:655-751` is the template. Build an MLB-flavored equivalent: "K rate up, 7.2 K/start over last 5, +1.4 above season" |
| 5 | **Specced-but-not-built collapsibility.** The PitcherModal header comment (line 14-15) says "Advanced metrics… collapsible · Game log… collapsible" but `PitcherModalContent` renders both expanded always. | Add collapse/expand state on AdvancedBlock + GameLogTable |
| 6 | **Weaker empty states.** Rookie with 1 start gets a nearly-blank modal ("No data yet for this pitcher"). NBA falls back to nearby game-log table. | `PitcherModal.tsx:553` — fall back to season stats + L5 grid even without arsenal/zone |

**Agent 2 "start here":** Add the 2-tab split at `PitcherModal.tsx:556`. Tab 1 = bettor-essential narrative (matchup, K line, trend, splits, H2H, recent starts). Tab 2 = Statcast depth (zone, arsenal, advanced). One change converts a 2173-line wall into a scannable two-screen modal and unlocks the matchup-bar merge + 2-col grid as natural follow-ups.

### Agent 3 — Visual polish

| # | Finding | NBA pattern | MLB pattern | Fix |
|---|---------|-------------|-------------|-----|
| 1 | **Card chrome — hardest visual gap.** NBA uses translucent fill + soft radius + no border; MLB uses opaque + hard radius + explicit border. 10 sites in MLB. | `bg-surface-secondary/50 rounded-xl p-4` | `bg-surface-secondary rounded-lg border border-card-border p-3` | Global swap of the class string. 10 sites: `PitcherModal.tsx:565, 597, 666, 692, 706, 1243, 1449, 1663, 1813, 1890` |
| 2 | **Section labels too quiet.** NBA uses headline-weight h4; MLB uses tertiary-weight micro-caps. Section starts dissolve into body. | `text-sm font-semibold text-text-primary uppercase tracking-wide mb-3` | `text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2` | Edit `SectionLabel` at `PitcherModal.tsx:903` |
| 3 | **54 inline `style={{ color: "var(--...)" }}`** in MLB vs 0 in NBA's GameReportTab. Bypasses dark variants; sources of one-off shades. | Tailwind tokens (`text-text-tertiary`) | Inline CSS vars | Replace inline `style` with className equivalents |
| 4 | Spacing rhythm: NBA `space-y-3` + `p-4` cards. MLB `space-y-5` + `p-3` cards (far apart AND cramped). | — | — | `space-y-4` outer, `p-4` inner |
| 5 | Pills: NBA solid `bg-positive text-white` hero chips. MLB uses bordered stat-block grid. | `ResultCard` GameReportTab.tsx:1175 | `LogStatPill` PitcherModal.tsx:1813 | Use solid color, not bordered grid |
| 6 | Typography density: NBA defaults to `text-sm`. MLB uses `text-xs` and `text-[10px]` constantly. | `text-sm` | `text-xs`/`text-[10px]` | Bump everything up one size |
| 7 | Dividers: NBA `border-b border-card-border/50` (whispers). MLB `divide-y divide-card-border` (shouts). | — | — | Match NBA |
| 8 | Loading skeletons: NBA `rounded-xl`, MLB `rounded-lg` (same radius mismatch as cards). | — | — | Match cards |
| 9 | Empty states: NBA has tailored copy. MLB has one generic `<EmptyState message="No data yet for this pitcher" />`. | — | — | Per-section tailored copy |

**Agent 3 "start here":** Project-wide replace `"bg-surface-secondary rounded-lg border border-card-border"` → `"bg-surface-secondary/50 rounded-xl"` (10 call sites). One mechanical edit removes the hard border and brings every MLB card into NBA's editorial card system. Biggest visual jump for the least risk; makes every subsequent polish step feel coherent.

## Where the agents agree

- **NBA's editorial card chrome** is the single most visible-effect / lowest-risk change. All three agents reference it differently but converge on it.
- **Tabs/IA split** is the structural fix that unlocks the rest — without it the modal is too long to fix incrementally.
- **KTrendChart** is the user's primary visualization-quality complaint.

## Recommended PR sequence (next session)

| PR | Scope | Effort | What user sees |
|----|-------|--------|----------------|
| 1 | Global card-chrome class swap (Agent 3 #1, 10 sites) + `SectionLabel` rewrite (Agent 3 #2) + `space-y-4`/`p-4` rhythm (Agent 3 #4) | 1-2 hr | Whole modal instantly looks more "editorial," softer, more confident. Zero structural changes. |
| 2 | `KTrendChart` refactor (Agent 1 #1, #2) — raise height, fix margin, delete competing dashed line, drop legend, add ReferenceLine label | 1-2 hr | The headline chart breathes. Hero visualization fixed. |
| 3 | Add 2-tab split (Agent 2 #1) — Tab 1 = bettor essentials, Tab 2 = Statcast depth | 4-6 hr | Modal scannability transforms; lazy-load opportunity for Statcast charts (recharts subset moves off initial load) |
| 4 | Build NBA-style "K Production Trends" comparison table (Agent 1 #3) — Last 3/5/10 starts × K/start, K/9, ERA, vs Season delta with positive/negative threshold encoding | 2-3 hr | The single most-informative chart pattern from NBA, now in MLB |
| 5 | RecentTrends prose row (Agent 2 #4) + tailored empty-state copy (Agent 2 #6, Agent 3 #9) | 2 hr | Modal reads like a scouting report |
| 6 | Cleanup pass: 54 inline `style` → Tailwind tokens (Agent 3 #3), typography size bump (Agent 3 #6), divider softening (Agent 3 #7), 2-col grid pair-ups (Agent 2 #3) | 3-4 hr | Polish at parity with NBA |

**Total: ~13-19 hr of focused work, shippable as 6 sequential PRs.** Each PR independently improves the modal; first 2 PRs alone close >50% of the perceived gap per agents 1+3.

## Open questions for next session

1. **Tabs vs single-scroll** — Agent 2 strongly recommends tabs; the original PitcherModal header comment line 17 *explicitly* declared "Intentionally NOT included: Tabs (single-scroll is fine)." That was a deliberate past design call. User should confirm the reversal before PR 3 lands.
2. **PitcherModal lazy-load** (deferred from prior session) — agent 8 of the earlier 16-agent review estimated 290 KB recharts cut from `/nba/*` bundle by lazy-loading. PR 3 (tabs) is a natural moment to also lazy-load Tab 2 since it contains all the heavy recharts components. Bundle this in.
3. **Last 5 → Last 10 grid** — would MLB users prefer 10 games of context? More data, more visual real estate.
4. **Color palette for MLB** — agents 1 and 3 both flagged saturated emerald/rose in MLB charts. NBA uses muted grays. Confirm if MLB should match NBA's restraint or keep its current accent.

## Other context worth carrying forward

- **Wrong-opponent upstream bug is STILL ACTIVE today** (uncovered late this session). 2026-03-28 → today predictions have wrong opponent attribution in `mlb_predictions.pitcher_strikeouts`. Chronological sort works around it via pitcher-name JOIN, but cards still show wrong opponents to users. Promotion candidate from roadmap P0 #4.
- **Sentry → Slack rule** still not wired (user-side action in console).
- **MLB feature store rolling K features 100% NULL** for 2026 (roadmap P0 #1) — separate session needed.

## Suggested next-session opening

```
/clear
Read docs/09-handoff/2026-05-12-mlb-modal-polish-vs-nba.md.
Brief me on the state in ~150 words and the open questions, then we'll
pick which PR to start with.
```
