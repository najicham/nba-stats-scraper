# Session Handoff — 2026-07-01 (Session 2, Signal Research)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commits:** `b8cbff13`, `1dfcaaca`, `9aedb1b5`, `0650c56c`, `90444709`
**Picking up from:** `docs/09-handoff/2026-07-01-1-session-handoff.md`

---

## What was accomplished

### Phase 1 — Season-open checklist + infrastructure fixes

**Bug fixes shipped:**
- `supplemental_data.py`: JOIN `nba_static.travel_distances` → `nba_enriched.travel_distances` (table was never in nba_static; 1,710 rows confirmed in nba_enriched including Abu Dhabi global game rows)
- `signal_health.py`: 13 shadow signals added to `ACTIVE_SIGNALS` (firing canary was blind to all of them)
- Travel context query: `INNER JOIN` → `LEFT JOIN` with `from_team=away_team` fallback for season openers with no prior game in 14-day window
- `signals.yaml`: odds_api scraper cadence comment corrected (2h not 10min)

**Runbook updated:** `docs/02-operations/runbooks/season-resume-2026-27.md` — added first-week verification section with all BQ diagnostics for new shadow signals, travel spot-check queries, Bluesky handle script (all 10 confirmed valid 2026-07-01).

**Bluesky handles:** All 10 beat writers confirmed valid (curl check). Re-run at season open if >2 months pass.

---

### Phase 2 — 11 new shadow signals implemented

All zero pick impact. All registered in aggregator.py SHADOW_SIGNALS, registry.py, signals.yaml, signal_health.py ACTIVE_SIGNALS.

| Signal | Mechanism | Pred dict fields |
|--------|-----------|-----------------|
| `high_minutes_under` | Season avg ≥34.5 mpg | `supplemental['minutes_stats']['minutes_avg_season']` |
| `high_3pt_season_under` | Season 3PT% ≥40.2% | `pred['three_pct_season']` |
| `high_3pt_recent_under` | Last-3 3PT% ≥45.5% | `pred['three_pct_last_3']` |
| `steep_downtrend_under` | Slope ≤-0.82 | `pred['trend_slope']` (feature_44) |
| `elite_line_under` | Line ≥28 | `pred['line_value']` |
| `low_var_mid_line_under` | std<4.5, line 15-25 | `pred['points_std_last_10']`, `pred['line_value']` |
| `star_out_rescue` | Lead scorer OUT, rank 2-7 OVER | `pred['is_star_teammate_out']`, `pred['target_team_scorer_rank']` |
| `drive_volume_under` | Season drives/g ≥7 | `pred['drives_avg_season']` |
| `season_breakout_over` | +3 PPG vs last season | `pred['season_scoring_delta']`, `pred['cross_season_games']` |
| `season_breakout_under` | -7 PPG vs last season | same |
| `career_matchup_under` | Career avg vs opp (3yr) < line -2 | `supplemental['career_matchup_3yr']` |

**4 new supplemental BQ queries added to `supplemental_data.py`** (after book_convergence_map block):
1. `drives_avg_query` → `drives_avg_map` → `pred['drives_avg_season']`
2. `cross_season_query` → `cross_season_map` → `pred['season_scoring_delta']` etc.
3. `star_out_query` → `star_out_map` → `pred['is_star_teammate_out']`, `pred['target_team_scorer_rank']`
4. `matchup_3yr_query` → `matchup_3yr_map` → `supp['career_matchup_3yr']`

---

### Phase 3 — 5-season BQ backtests on all 11 signals

Results via 4 parallel general-purpose agents running BQ queries against `prediction_accuracy`.

| Signal | N | HR% | vs Baseline | Seasons | Decision |
|--------|---|-----|-------------|---------|----------|
| `elite_line_under` | 1,679 | 63.2% | +3.8pp | **4/5** | **PROMOTED (weight 1.5)** |
| `star_out_rescue` | 1,797 | 74.3% | +6.6pp OVER | **4/5** | Shadow; incremental=66%/54% 2025-26 |
| `season_breakout_under` | 1,509 | 65.7% | +~3pp | 3/4 | Shadow; threshold → -7.0 (73% HR) |
| `high_3pt_season_under` | 9,651 | 60.4% | +1.0pp | 5/5 | Shadow (thin, N too large) |
| `high_3pt_recent_under` | 8,891 | 60.2% | +0.8pp | 4/5 | Shadow (thin) |
| `high_minutes_under` | 10,133 | 63.0% | +1.6pp | 3/5 | Shadow (2025-26 inverts) |
| `steep_downtrend_under` | 6,197 | 59.6% | +0.2pp | 4/5 | **REMOVED** — dead end |
| `low_var_mid_line_under` | 3,733 | 61.3% | -0.1pp | 3/5 | **REMOVED** — hypothesis refuted |
| `season_breakout_over` | 5,089 | 61.6% | -0.2pp | 2/4 | **REMOVED** — OVER scoring-env artifact |
| `career_matchup_under` | 36,538 | 60.8% | +0.2pp | 1/5 | **REMOVED** — inverse outperforms |
| `drive_volume_under` | — | — | — | — | Shadow; BROKEN (data all 0.0) |

---

### Phase 4 — 5-agent adversarial review of star_out_rescue

**Verdict: DO NOT ACTIVATE.** 3/3 review agents agreed.

**The decisive finding (adversarial agent):** The incremental zone (edge 3-5.9, what rescue actually adds) hits **66.1% pooled but only 54.4% in 2025-26 — BELOW the 2025-26 OVER baseline (-2.9pp premium)**. The premium collapsed from +5.9pp (2024-25) to -2.9pp (2025-26). This is NOT explained by the broad OVER decline — star-out picks underperformed the already-collapsed 2025-26 OVER baseline.

**Statistical review (second agent):** Methodology sound — bootstrap CI [71.4%, 76.1%], no look-ahead bias (8.63% post-game-only cases have LOWER HR), dedup choice irrelevant (±0.1pp). 2025-26 HR = 59.9% (CI lower 52.7%, barely above breakeven). Signal survives statistical checks but 2025-26 remains a serious yellow flag.

**Mechanics review (third agent):** No structural risks from caps or filters. SC≥3 gate limits live volume naturally. HSE overlap minimal. Safe to stay shadow.

**Activation gate for 2026-27:**
- N≥30 live BB-level picks where signal fires
- HR of those live picks ≥65%
- Incremental zone (edge 3.0-5.9) HR also ≥65%
- Explicit user sign-off
- Then: remove from SHADOW_SIGNALS, add to rescue_tags + OVER_SIGNAL_WEIGHTS (weight 2.5)

---

### Phase 5 — Discovery agents + threshold optimization

**`fta_high_cv_under` (NEW, wired as shadow):**
- FTA avg ≥5/game AND FTA CV ≥0.4, UNDER
- 61.4% → 62.3% → 63.2% → 63.9% HR across 4 pre-anomaly seasons (monotonically improving)
- Same 2025-26 collapse as b2b_fatigue_under (50.9% in anomaly year)
- Fields already in pred dict from Session 451 `fta_variance` CTE — zero new supplemental query needed
- Promote: N≥30 live 2026-27 at HR≥58% (do not use 2025-26 data in gate)

**`season_breakout_under` threshold tightened to -7.0:**
- Scanner found -3.0 (63.7%), -5.0 (65.7%), -7.0 (73.0% N=407, 4/4 seasons), -10.0 (92% N=51 too thin)
- Real signal lives at -7.0; updated in signal file

---

## Critical validation rules (PERMANENT — never violate)

### Rule 1: November UNDER baseline is inflated
The UNDER baseline is +4-8pp HIGHER in November every normal season:
- 2021-22: Nov 71.0% vs Dec-Apr 63.1% (+7.9pp)
- 2022-23: Nov 68.7% vs Dec-Apr 62.8% (+5.9pp)
- 2023-24: Nov 68.0% vs Dec-Apr 62.0% (+6.0pp)
- 2024-25: Nov 65.6% vs Dec-Apr 61.6% (+4.0pp)

**Any signal showing an "early-season spike" in Oct-Nov is measuring baseline inflation, not signal edge.** Always compute vs monthly UNDER baseline, not annual average. This explained 100% of the "early-season spikes" seen across multiple shadow signals.

### Rule 2: Rescue signals need the incremental-zone test
For any signal that bypasses an edge floor, headline HR is irrelevant — what matters is HR in the INCREMENTAL zone (picks with edge below the floor that would be newly admitted). For star_out_rescue: headline 74% looks great but incremental zone (edge 3-5.9) = 66% pooled / 54% in 2025-26.

### Rule 3: nba_tracking_stats columns are empty
`drives`, `touches`, `paint_touches`, `catch_shoot_fga`, `pull_up_fga` are ALL 0.0 across all 307K rows. Only `usage_pct` is populated. The `drive_volume_under` signal will never fire until the scraper is fixed. Do not investigate "why drive_volume_under isn't firing" — the data doesn't exist yet.

---

## Current shadow signal fleet (as of 2026-07-01)

### Validated by 5-season backtest
| Signal | HR | N | Seasons | Promote when |
|--------|-----|---|---------|-------------|
| `b2b_fatigue_under` | 63.2% (5-season) | large | **5/5** | N≥30 HR≥58% live 2026-27 |
| `elite_line_under` | 63.2% | 1,679 | 4/5 | **ALREADY ACTIVE (weight 1.5)** |
| `season_breakout_under` | 73.0% (at -7.0) | 407 | 4/4 | N≥30 HR≥68% live 2026-27 |
| `fta_high_cv_under` | 61-64% (4 seasons) | ~7.8K | 4/4 pre-anomaly | N≥30 HR≥58% live 2026-27 |
| `star_out_rescue` | 74.3% overall | 1,797 | 4/5 | Incremental zone N≥30 HR≥65% + sign-off |

### Pre-registered (no backtest, accumulating from 2026-27)
| Signal | Mechanism | Promote when |
|--------|-----------|-------------|
| `national_tv_under` | Primetime + line≥22 | N≥30 HR≥55% |
| `whole_line_precision` | Whole-number line | UNDER: N≥30 HR≥62%; OVER: N≥50 HR≥70% |
| `line_converging_under` | CLV gate — line drifted against pick | N≥30 HR≥60% |
| `high_line_under` | Line ≥25 | N≥30 HR≥58% |
| `ref_crew_under_tendency` | Crew O/U tendency (data-gated) | N≥30 HR≥58% + 2 Covers seasons |
| `dense_schedule_grind_under` | 4+ games in 7 days | N≥30 HR≥58% |
| `long_road_trip_under` | 3+ consecutive away | N≥30 HR≥58% |
| `rotowire_bench_under` | Pre-game bench designation | N≥30 HR≥65% |
| `tight_consensus_under` | 6+ books posting today | N≥30 HR≥58% |
| `westward_road_trip_under` | Away team traveling west | N≥30 HR≥58% |
| `b2b_long_haul_under` | B2B + 1000+ miles | N≥30 HR≥62% |
| `multi_book_convergence_under` | 3+ books lowered line intraday | N≥30 HR≥58% |
| `high_minutes_under` | Season avg ≥34.5 mpg | N≥30 HR≥58%; only 3/5 seasons |
| `high_3pt_season_under` | Season 3PT% ≥40.2% | N≥30 HR≥60%; compare monthly baseline |
| `high_3pt_recent_under` | Last-3 3PT% ≥45.5% | N≥30 HR≥60%; quantify hot_3pt_under overlap |
| `drive_volume_under` | Drives/g ≥7 | Fix scraper first; then N≥30 HR≥58% |
| `season_breakout_over` | REMOVED — do not restore |
| `career_matchup_under` | REMOVED — do not restore |
| `steep_downtrend_under` | REMOVED — do not restore |
| `low_var_mid_line_under` | REMOVED — hypothesis refuted |

### 5 demoted OVER signals (shadow, use over_decay_watch.py from Dec 2026)
- `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over`
- Each must clear N≥30 HR≥58% on live 2026-27 data via `PYTHONPATH=. python bin/monitoring/over_decay_watch.py`

---

## Remaining open research directions

### High priority (validated, ready to test if more data becomes available)
1. **star_out_rescue live accumulation** — it's in shadow and will fire from Oct 2026. Check `signal_health_daily` weekly. If incremental zone HR ≥65% after N=30, bring for sign-off.
2. **fta_high_cv_under live accumulation** — same pattern as b2b_fatigue_under. Watch for the 2025-26 anomaly to not repeat.

### Medium priority (data/infrastructure gaps)
3. **Fix nba_tracking_stats scraper** — drives/touches columns are all 0.0. Find where the scraper should populate them and fix. Once fixed, `drive_volume_under` can start accumulating.
4. **CLV intraday convergence** — `line_converging_under` is wired but needs multiple odds_api snapshots per day. Verify fire rate at season open (diagnostic in runbook).

### Research angles NOT worth pursuing (false discoveries confirmed)
- Monday UNDER: +1.1pp vs UNDER baseline = noise
- Team win% UNDER: BACKWARDS (winning teams hit UNDER more)
- 3PT season + elite line combo: below baseline (58.9%)
- Career matchup history: model already knows this via predicted_points
- Steep scoring slope (≤-0.82): downtrend_under band already captures it
- Mid-line low-variance archetype: hypothesis refuted at BQ scale

### Future research (genuinely unexplored, worthwhile at season open)
- **`season_breakout_under` real-time check**: at game 20+ of 2026-27, this signal starts firing. The threshold of -7.0 means players who are 7+ PPG below last season's same-game-count pace. Will be interesting to watch early in the season when role changes are visible.
- **Shadow signal overlap analysis**: once several hundred live picks accumulate in 2026-27, analyze which shadow signals co-fire. If `fta_high_cv_under` and `b2b_fatigue_under` fire together, the combo HR might be promotable even before individual thresholds are met.
- **RotoWire parser health at season open**: spot-check that `rotowire_bench_under` and `minutes_surge_over` start firing (if HTML structure changed between seasons, parser will silently fail). Check canary for NEVER_FIRED status.

---

## What NOT to re-litigate

- **star_out_rescue headline HR** — the 74-79% figure is from edge-6+ picks that already qualify. The incremental question is answered: 66% pooled, 54% in 2025-26.
- **Nov vs season signal comparisons** — Nov baseline is inherently inflated (+4-8pp). Any historical "signal spike in November" is baseline noise.
- **Career matchup history as a signal** — the model's predicted_points already encodes 1-year matchup history (features 29/30). A 3-year extension still failed (+0.2pp, 1/5 seasons). Signal is not recoverable.
- **Low-variance mid-line archetype** — refuted at N=3,733. The low-var edge is real at low lines (<15) but does not extend to mid-line (15-25).
- **Steep downtrend (slope ≤-0.82)** — partially overlaps with downtrend_under (which uses -1.5 to -0.5 band). The extended range adds nothing (+0.2pp pooled).

---

## Season open (October 2026) additions from this session

The `season-resume-2026-27.md` runbook now includes:
- BQ diagnostic queries for all new shadow signals' first-week verification
- Travel direction spot-check (GSW@BOS example, nba_enriched confirmed)
- Book-count and convergence signal fire-rate diagnostics
- Kelly haircut bet_size_units BQ verification query
- Stokastic scraper check (run `--debug` after 1 PM ET on first game day)
- Bluesky handle curl script (all 10 confirmed valid 2026-07-01)
