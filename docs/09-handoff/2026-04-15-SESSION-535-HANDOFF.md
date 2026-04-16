# Session 535 Handoff — MLB pipeline fixes, PitcherModal redesign, 6-agent review cycle

**Date:** 2026-04-15 (third session of the day, continuation of 533/534)
**Focus:** MLB 0-pick diagnosis, 3 cascading grading bugs, PitcherModal visual overhaul, 6-agent review + fix cycle.
**Commits:**
- `nba-stats-scraper`: `fb447d49` (scheduler IaC), `eec9e484` (3 grading bugs + filter audit), `120f4b30` (rescue signal expansion)
- `props-platform-web`: `5a8c3cf` (modal redesign), `98cc584` (review fixes), `737c510` (perf/a11y/icons/game-log accuracy)
- `infinitecase`: `1e9a5ce` (unused vars), `db778b8` (chip scroll fix), `3054ba9` (keyboard shortcut scroll fix)

---

## TL;DR

Diagnosed MLB 0 picks since Apr 11 — NOT a bug, edge compression (avg -0.03K) + 3 cascading grading bugs that left `vegas_mae_7d` NULL for all April (regime detection dead). Fixed all three bugs, backfilled data, expanded rescue signals for early-season volume. Redesigned PitcherModal with K distribution chart, season stats strip, reference lines, then ran a 6-agent Opus review that found 7 red issues — fixed 5. Second review round added useMemo (5x), SVG a11y, icon dedup, game log accuracy dots.

---

## What was applied

### MLB Backend (3 commits)

**1. Scheduler IaC (`fb447d49`)**
- Created `deployment/scheduler/mlb/bb-schedules.yaml` + `deploy-bb-schedules.sh`
- Documents all 3 Session 534 schedulers (mlb-best-bets-generate, mlb-pitcher-export-morning/pregame)
- Note: ~36 other MLB schedulers still have no IaC (pre-existing debt)

**2. Three cascading grading bugs (`eec9e484`)**

| Bug | File | Root Cause | Fix |
|-----|------|-----------|-----|
| `vegas_mae_7d` always NULL | `mlb_prediction_grading_processor.py` | Backfill query set `actual_value` but never set `is_scored=TRUE`. League macro filters on `is_scored=TRUE` → 0 rows → NULL. | UPDATE now sets `is_scored=TRUE` and `is_push`. Filter changed from `actual_value=0` to `is_scored=FALSE`. |
| Post-grading analytics never ran via Pub/Sub | `main_mlb_grading_service.py` | `/process` endpoint (Pub/Sub) never called `_run_post_grading_analytics()`. Only manual `/grade-date` had it. | Added analytics call to `/process` endpoint. |
| `mae_gap_7d` always NULL | `main_mlb_grading_service.py` | `_compute_mae_gap()` never called before `write_row()`. | Added call between compute and write. |

Defense-in-depth: `mlb_league_macro.py` vegas accuracy query now uses `(is_scored = TRUE OR actual_value > 0)`.

Also moved `_write_filter_audit()` outside the `if ranked_picks` block in `best_bets_exporter.py` so filter audit writes on zero-pick days (was invisible before).

**Data backfilled:** 51 `bp_pitcher_props` rows fixed (Apr 9-14). `league_macro_daily` repopulated — Apr 12 and Apr 9 were TIGHT (vegas_mae < 1.7K), rest NORMAL.

**3. Rescue signal expansion (`120f4b30`)**
- Added `recent_k_above_line` and `projection_agrees_over` to `RESCUE_SIGNAL_TAGS`
- Both are already active signals, available from day 1 (no season-cumulative dependency)
- HOME pitchers below edge floor can now enter pipeline when these signals fire
- Away rescue still blocked (`BLOCK_AWAY_RESCUE=True`), `real_signal_count >= 2` still applies
- Cross-season evidence: home OVER at edge 0.50-0.74 hits 71.9% HR (N=64, 2024-2025)

### PitcherModal Frontend (3 commits)

**Commit `5a8c3cf` — Redesign:**
- `KDistChart`: SVG histogram (0-7+ K buckets), tonight's line as sky-blue threshold, "X% beat [line]" hit rate
- `SeasonStatsStrip`: 5-cell row (GS / IP / K/9 / ERA / WHIP)
- `KTrendChart`: h-40→h-28, ReferenceLine at tonight's line, tighter margins, 9px axis font
- `SplitsCard`: text-xl→text-base for density
- Side-by-side KDist + KTrend on md+ screens, stacked on mobile
- `overscroll-contain` on PitcherModal + PlayerModal (fixes background scroll leak)

**Commit `98cc584` — Review fixes:**
- Grid: `grid-cols-2` → `grid-cols-1 md:grid-cols-2` with symmetric `pr-4`/`pl-4`
- Removed `refLine` fallback to historical (drew duplicate line through amber dot)
- Axis font 7px→9px

**Commit `737c510` — Perf/a11y/cleanup:**
- `useMemo` on 5 computations: deriveLast5, evidenceChips, h2hStarts, KDistChart bucketing, KTrendChart data
- SVG `role="img"` + `aria-label` on KDistChart and ArsenalBubble
- Replaced 3 duplicate icon SVGs with shared `@/components/ui/Icons` import
- Game log accuracy dots: green (correct) / red (wrong) + "BB" badge for best-bet starts

### infinitecase (3 commits)

- `1e9a5ce`: Removed unused vars (`Trash2`, `Tag`, `toggleFileSelect`, `toggleSelectAll`, `handleBulkReextract`) to unblock Vercel build
- `db778b8`: StatusChip `router.push(path, { scroll: false })` + error-state routes to `/files`
- `3054ba9`: Keyboard tab shortcuts (`Cmd+1..5`) also got `{ scroll: false }`

---

## Key findings from 6-agent review

### MLB 0-picks root cause (verified)

- **Only edge floor binds today.** Signal count gate never reached. Max edge today: 1.0K (Hancock, AWAY), which fails AWAY_EDGE_FLOOR=1.25. The 2 picks above 0.75 are both AWAY.
- **pitcher_game_summary 2026 data is fine** — all 30 pitchers have season stats. The f08/f09/f23 warnings are from 4 BLOCKED pitchers with NULL lines.
- **2026 model HR is 42.6% vs historical 74-75% for April.** Edge distribution is comparable to prior years — model is making similar-confidence predictions but getting them wrong. This is a model quality issue, not a pipeline issue.
- **13 of 19 signals can fire from day 1** — signal dormancy is not the primary blocker.
- **UNDER is disabled** and should stay that way (47-49% HR walk-forward, 3-signal gate too strict).

### PitcherModal profile data unused (22 fields available)

Free features (wire-up only, no backend): `tonight.confidence`, `quality_starts`, `game_log.prediction_correct` (now shipped), `game_log.was_best_bet` (now shipped), `game_log.walks_allowed`, `game_log.earned_runs`, `game_log.pitch_count`, `putaway.usage_pct_on_2k`, `expected_csw_pct`.

### NBA modal patterns worth porting

1. **Opponent K-defense section** (CRITICAL) — rank opponent K-rate 1-30 with badge
2. **Rest splits by days** (HIGH) — 4-day/5-day/6+ day with Over%
3. **Analytics tracking** (HIGH) — zero Mixpanel/GA4 on pitcher modal currently
4. **View Full Season drilldown** (MEDIUM) — sub-view pattern from NBA
5. **Dynamic XAxis interval** (LOW) — steal NBA's `Math.floor(length/5) - 1` formula

---

## What to work on next

### 1. Confidence meter in hero card (10 min, free wire-up)

`tonight.confidence` is in the profile JSON but not rendered. Add a small visual (e.g., a thin bar or percentage badge) next to the OVER/UNDER pill in the hero verdict card.

**File:** `props-web/src/components/modal/PitcherModal.tsx`, `OverviewTab` function, inside the hero section after `RecommendationPill`.

### 2. Opponent K-defense section (30 min)

Show opponent team strikeout rate as a ranked badge. Data path:

- **Backend:** `opponent_team_k_rate` is already computed in `predictions/mlb/pitcher_loader.py:174`. Check if it's in the GCS pitcher profile JSON (search `mlb_pitcher_profile_exporter.py` or `mlb_best_bets_exporter.py`).
- **Frontend type:** Not currently in `PitcherProfileResponse`. Need to add `opponent_k_rate?: number` to `PitcherTonight` in `pitchers-types.ts`.
- **Component:** Render as a badge below the MatchupBar: "OPP K RATE: 24.3% (8th highest)". Color green if top-10 (K-prone), red if bottom-10 (tough K matchup).

### 3. Rest splits by days (30 min)

In the SplitsCard (currently Home/Away + L3/L5/L10), add a third row: "4-day rest / 5-day rest / 6+ day rest". Derive from game_log dates:

```tsx
const withDaysRest = deduped.map((g, i, arr) => ({
  ...g,
  daysRest: i < arr.length - 1
    ? Math.round((new Date(g.game_date).getTime() - new Date(arr[i + 1].game_date).getTime()) / 86400000)
    : null,
}));
const rest4 = computeSplit(withDaysRest.filter(g => g.daysRest === 4));
const rest5 = computeSplit(withDaysRest.filter(g => g.daysRest === 5));
const rest6plus = computeSplit(withDaysRest.filter(g => g.daysRest != null && g.daysRest >= 6));
```

### 4. Strike Zone Heartbeat (2-3 hours, biggest feature)

**Backend:**
- Query `mlb_raw.mlb_game_feed_pitches` for K-outcome pitches per pitcher
- Aggregate last 20 K locations (px, pz coordinates)
- Add to pitcher profile exporter JSON as `strikeout_locations: [{px, pz, pitch_type, date}]`
- BQ view: `SELECT px, pz, pitch_type, game_date FROM mlb_game_feed_pitches WHERE event_type IN ('strikeout', 'strikeout_double_play') AND pitcher_lookup = @pitcher ORDER BY game_date DESC LIMIT 20`

**Frontend:**
- SVG strike zone (17" x 24" plate, scaled to ~120px width)
- Plot K locations as colored dots (by pitch type)
- Prototype at `/tmp/mlb-proto-v2-strike-zone.html`
- Add as a section in Overview tab between evidence chips and splits

### 5. Model quality investigation (1 hour, research-only)

The 2026 model hits 42.6% HR vs 74-75% historically. O4 agent confirmed edge distribution is normal — the model is confident but wrong. Investigate:

- Is the retrained model from Session 524 (`catboost_mlb_v2_regressor_40f_20250928.cbm`) still deployed? Verify: `gcloud run services describe mlb-prediction-worker --format="value(spec.template.spec.containers[0].env)" | grep MODEL`
- Compare feature distributions for 2026 April vs 2025 April — are any features drifting?
- Run `scripts/mlb/training/train_regressor_v2.py` with `--training-start 2024-04-01 --training-end 2026-04-14 --eval-start 2026-04-01` to see if a fresh retrain improves April HR.
- **Do NOT deploy a retrained model without governance gates.**

### 6. Remaining review items (low priority)

- Tab button ARIA semantics (role="tab", aria-selected, keyboard arrows)
- CollapsibleSection aria-expanded
- PitcherModal.test.tsx (mirror PlayerModal test patterns)
- Analytics tracking hooks (Mixpanel/GA4)
- View Full Season drilldown sub-view

---

## Monitoring

```bash
# MLB BB picks (should grow as rescue signals help)
bq query --use_legacy_sql=false \
'SELECT game_date, COUNT(*) bb FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
 WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) GROUP BY 1 ORDER BY 1 DESC'

# Filter audit (should now have rows even on 0-pick days)
bq query --use_legacy_sql=false \
'SELECT game_date, filter_name, COUNT(*) cnt
 FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit`
 WHERE game_date >= CURRENT_DATE() - 3 GROUP BY 1,2 ORDER BY 1 DESC, cnt DESC'

# Regime detection (should show TIGHT/NORMAL, not NULL)
bq query --use_legacy_sql=false \
'SELECT game_date, vegas_mae_7d, market_regime
 FROM `nba-props-platform.mlb_predictions.league_macro_daily`
 WHERE game_date >= CURRENT_DATE() - 7 ORDER BY game_date DESC'

# Rescue signal impact (check if rescues appear in tomorrow's run)
bq query --use_legacy_sql=false \
'SELECT game_date, pitcher_name, edge, recommendation, signal_tags
 FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
 WHERE game_date >= CURRENT_DATE() - 1 ORDER BY game_date DESC'
```

---

## Model recommendation for next session

**Opus for items 4 (Strike Zone backend) and 5 (model investigation).** Both require multi-file code dives. **Sonnet for items 1-3** (confidence meter, opponent K section, rest splits) — straightforward frontend wire-ups.

---

## Deployment status

All 3 backend commits auto-deployed via Cloud Build (8 builds, all SUCCESS). `mlb-phase6-grading` and `mlb-prediction-worker` both on latest revisions with traffic routed. Frontend commits auto-deploy via Vercel.
