# Session 536 Handoff — PitcherModal feature sweep + morning steering

**Date:** 2026-04-16
**Focus:** All 6 next-up items from Session 535 shipped (frontend + backend). Morning steering check run — NBA correctly halted, MLB pipeline healthy.
**Status:** Uncommitted changes in two repos. **Nothing pushed yet.**

---

## TL;DR

Cleared the entire Session 535 "next steps" list in a single pass: confidence meter, opponent K-defense badge, rest-day splits, Strike Zone Heartbeat (backend + SVG viz), model quality investigation (research-only), and tab ARIA + tests. Then ran the morning steering report. MLB model is hitting 57-73% HR daily, edge compression still starving best bets. Work is staged but **not committed** — next session should review, commit, push.

---

## What was built (uncommitted)

### Backend — `nba-stats-scraper` (+188 lines, 1 file)

`data_processors/publishing/mlb/mlb_pitcher_exporter.py`:

1. **`_fetch_opponent_k_defense(game_date)`** — computes opponent season K rate from `batter_game_summary`, ranks all 30 MLB teams by K rate (rank 1 = most K-prone), and joins with tonight's starters from `pitcher_game_summary.opponent_team_k_rate`. Emits `opponent_k_rate`, `opponent_k_rank`, `opponent_k_rank_of` into `profile.tonight`.

2. **`_fetch_strikeout_zones(pitcher_lookups)`** — queries `mlb_raw.mlb_game_feed_pitches` for pitches that ended a strikeout (`at_bat_event='Strikeout' AND is_at_bat_end=TRUE`) over the pitcher's last 5 start dates. Groups by MLB zone code (1-9 in-zone, 11-14 out-of-zone corners), also aggregates top pitch type per zone. Emits `profile.strikeout_zones = {starts_sampled, total_ks, zones[], last_seen_date}`.

3. **`_build_profile` extended** with two new kwargs: `opponent_k_defense` and `strikeout_zones`. Both wired from `_build_bundle`.

Backward-compatible: new fields are optional/None when upstream data is missing (early season, pre-Statcast pitchers, etc.).

### Frontend — `props-web` (+460 lines, 2 files + 1 new test file)

**`src/lib/pitchers-types.ts` (+30 lines):**
- `PitcherTonight` gained `opponent_k_rate`, `opponent_k_rank`, `opponent_k_rank_of`.
- New `PitcherStrikeoutZoneCell` + `PitcherStrikeoutZones` interfaces.
- `PitcherProfileResponse` gained `strikeout_zones: PitcherStrikeoutZones | null`.

**`src/components/modal/PitcherModal.tsx` (+437 lines):**
- `ConfidenceMeter` — bar + % next to the OVER/UNDER pill. Tone matches recommendation. Hidden on PASS.
- `OpponentKBadge` inside `MatchupBar` — e.g. "OPP K 24.3% · 8th/30". Green if top-third K-prone, red if bottom-third.
- `ordinalShort` helper for "1st/2nd/3rd/4th" suffixes.
- **Rest-day splits** in `SplitsCard` — new third row (4-day / 5-day / 6+ day rest) derived from game_log date gaps.
- `StrikeZoneHeartbeat` — 5x5 SVG heatmap. Inner 3x3 is the strike zone (green scale), corners are chase zones (amber). Each cell shows K count + top pitch type. Side panel shows total Ks, % in zone, % chase. Gated: min 5 K-pitches to render.
- **Tab ARIA fixes:** `role="tablist"`/`role="tab"`/`aria-selected`/`aria-controls`, roving tabindex, ←/→/Home/End keyboard navigation. Tab panels wrapped with `role="tabpanel"`.
- `CollapsibleSection` gained `aria-expanded` + `aria-controls`.

**`src/components/modal/PitcherModal.test.tsx` (NEW, 8 tests):**
- usePitcherModal hook: throws outside provider, initial state, open, close.
- PitcherModalProvider: renders children, dialog role, tablist + tab `aria-selected`, Escape-to-close.
- All 8 pass. Existing `PlayerModal.test.tsx` (8 tests) still passes.

### Validation

- **TypeScript:** `npx tsc --noEmit` clean.
- **ESLint:** No new errors/warnings introduced (4 pre-existing errors unrelated to this work on line 569 h2hStarts useMemo and set-state-in-effect at line 554).
- **Python syntax:** `py_compile` clean on modified exporter.

---

## Morning steering summary (2026-04-16)

### NBA — playoffs, correctly dormant
- All 7 active models BLOCKED, 12+ others INSUFFICIENT_DATA. Best: `catboost_v12_noveg_train1227_0221` at 51.7% HR 7d.
- Last 7d: **0 best bets** (edge-based auto-halt from Session 515 is active).
- Last 30d: 7-5 (58.3%, N=12) — final pre-halt picks from late March.
- Round 1 of playoffs running (2-4 games/day through Apr 23).
- **Action:** None. Do NOT retrain — April playoff data would pollute the window. Memory already flags this.

### MLB — active, edge-compressed but model is fine
- **Model HR 57-73% mid-April** (57.1, 66.7, 70.6, 73.3 on Apr 11/12/14/15). Apr 10 was the only weak day (41.2%).
- **BB volume: 3 picks since Apr 9, all WINS** (J.T. Ginn, Keider Montero, Jeffrey Springs — all OVER).
- **Zero BB picks Apr 11-15** despite strong daily HR. Edge compression (avg 0.33-0.78) + 0.75 home / 1.25 away floors screen most candidates out.
- League macro Apr 15: TIGHT (vegas_mae_7d=1.68), model MAE keeping pace (gap +0.10).
- **Today (Apr 16):** 10 games, 17 pitchers have K props (odds snapshot 10:31 AM ET). Predictions had not yet run when steering was done — monitor in ~30 min.

### Deployment
- 15/16 services ✓ up to date. One false-positive on `validation-runner` (checker conflates repo HEAD with service-specific commits; no code actually changed since last deploy).
- Model registry ✓ matches GCS manifest.
- All traffic routed to latest revisions.

### Model quality finding (research-only)
Session 535 flagged 42.6% MLB HR — **that number is stale.** Current 6-day avg is 62%+ on graded predictions. Problem is NOT model quality; it's edge compression below the thresholds. Confirmed with:
- Avg abs edge Apr 10-15: 0.33-0.78
- Only 27/99 preds crossed 0.75, only 7/99 crossed 1.25
- Deployed model is still `catboost_mlb_v2_regressor_40f_20250928.cbm` (Session 524), revision `mlb-prediction-worker-00066-52g`.
- **Recommendation: do NOT retrain.** If more volume is desired, lower home floor to 0.5 is the lever — but that's a threshold decision, not a model decision.

---

## What to do next session

### 1. Commit and push (30 min, FIRST thing to do)

Two repos, changes are additive and independently testable.

**`nba-stats-scraper` commit:**
```
feat(mlb-exporter): opponent K-defense + strikeout zone data for profile JSON

- _fetch_opponent_k_defense: team K rate + league rank joined with tonight's starters
- _fetch_strikeout_zones: K-ending pitch distribution by MLB zone code (1-14) over L5 starts
- Both wired through _build_bundle into profile.tonight and profile.strikeout_zones
```

**`props-web` commit:**
```
feat(pitcher-modal): confidence meter, opponent K badge, rest splits, Strike Zone Heartbeat

- ConfidenceMeter: tonight.confidence next to RecommendationPill, toned to rec
- OpponentKBadge in MatchupBar with season rank (1=most K-prone)
- SplitsCard: 4/5/6+ day rest-day splits derived from game_log
- StrikeZoneHeartbeat: 5x5 SVG (inner 3x3 in-zone green, corners amber chase)
- Tabs: proper role/aria-selected/aria-controls + keyboard nav
- CollapsibleSection: aria-expanded + aria-controls
- PitcherModal.test.tsx: 8 tests (provider, hook, dialog, tablist, escape)
```

Auto-deploy will pick both up. Backend fields are optional so frontend deploying before backend is safe (UI just won't render those sections until the GCS JSON has the fields).

### 2. Validate it actually works end-to-end (15 min)

After both deploys finish, open a pitcher modal in the UI for a pitcher starting tonight:
1. Confidence meter should appear next to OVER/UNDER pill.
2. MatchupBar should show "OPP K X.X% · Nth/30".
3. Strike Zone Heartbeat should render if the pitcher has 5+ recorded strikeouts in the last 5 starts.
4. SplitsCard should show rest-day row if game_log spans enough dates.

If the Strike Zone Heartbeat is empty or sparse for most pitchers, early-April data volume may be the cause — `mlb_game_feed_pitches` requires finals to be processed. Check:
```sql
SELECT COUNT(DISTINCT pitcher_lookup) FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
WHERE at_bat_event='Strikeout' AND is_at_bat_end=TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
```

### 3. Confirm today's MLB predictions landed (5 min)

```bash
bq query --use_legacy_sql=false \
'SELECT COUNT(*) preds, ROUND(AVG(ABS(edge)),2) avg_edge
 FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
 WHERE game_date = CURRENT_DATE()
   AND recommendation IN ("OVER","UNDER","PASS")'
```

Should be 15-20 preds. If zero, the `prediction-worker` or `mlb-best-bets-generate` scheduler hasn't fired yet — check logs.

### 4. Session 535 items NOT done

- **Analytics tracking hooks** (Mixpanel/GA4) on PitcherModal — zero coverage currently. Port the pattern from PlayerModal.
- **View Full Season drilldown** sub-view (NBA pattern). Medium priority, good for engagement metrics once they exist.
- **Dynamic XAxis interval** formula port (`Math.floor(length/5) - 1`). Low priority, purely cosmetic.

### 5. Edge threshold experiment (research, 1 hour)

If the pick-drought drags into next week, run a replay lowering the home edge floor from 0.75 → 0.5 for Apr 1-15 and see what BB HR looks like. If Apr 11-15 would have produced 5-8 additional picks at 60%+ HR, that's strong evidence to lower the floor. Script: `scripts/mlb/training/season_replay.py`.

**Do NOT change the floor without running this backtest first.** Session 535 already recommended this as the primary lever — it just needs data to back the recommendation.

---

## Files changed this session

| Repo | File | Status |
|------|------|--------|
| nba-stats-scraper | `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | Modified (+188/-1) |
| nba-stats-scraper | `docs/09-handoff/2026-04-16-SESSION-536-HANDOFF.md` | New (this file) |
| props-web | `src/components/modal/PitcherModal.tsx` | Modified (+437/-7) |
| props-web | `src/lib/pitchers-types.ts` | Modified (+30/-0) |
| props-web | `src/components/modal/PitcherModal.test.tsx` | New (112 lines) |

No other repos touched. No deploys triggered. No model changes.

---

## Key lessons

1. **"Model HR 42.6%" can age out in days.** The Session 535 handoff was written when the MLB model looked broken; 4 days later it's hitting 57-73%. Always re-query before acting on HR claims in handoffs.

2. **Edge compression ≠ model failure.** When avg abs edge is 0.48 and floors are 0.75/1.25, most predictions are disqualified before signal evaluation even runs. The model can be great and the pipeline can still yield zero picks.

3. **Additive JSON fields deploy safely in either order.** The new `strikeout_zones` + `opponent_k_rate` fields are optional on the TypeScript side, so frontend can ship before backend without breaking.

4. **MLB zone codes (1-14) give you free discrete bins.** No need to query `plate_x/plate_z` coordinates — the `zone` column in `mlb_game_feed_pitches` is already quantized into 9 in-zone + 4 out-zone buckets, which is exactly what a 5x5 heatmap needs.

---

## Deployment status

**Nothing deployed this session.** Changes are local-only in both repos. Push to main on either repo triggers auto-deploy (`mlb_pitcher_exporter` is part of the `phase6-export` CF; frontend is Vercel).

Morning steering check also showed `validation-runner` drift — ignore, it's a false positive from the drift checker.
