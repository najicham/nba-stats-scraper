# Session Handoff — 2026-07-02

**Branch:** main (clean, all pushed)
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Today's sessions:** Session 2 (signal research) + Session 3 (cleanup & fixes)
**Prior handoff chain:** `2026-07-01-1` → `2026-07-01-2` → `2026-07-01-3` → this doc

---

## What was done across today's sessions

### Session 2 — Signal research (commits `b8cbff13` through `0b267af1`)

Full signal research sprint: 11 new shadow signals implemented, 5-season BQ backtests on all of them, 5-agent adversarial review on `star_out_rescue`, discovery of 2 critical validation rules.

**PROMOTED to active:**
- `elite_line_under` (line ≥ 28 UNDER): weight=1.5, 63.2% HR (N=1,679, 4/5 seasons, +3.8pp)

**REMOVED (dead ends — unregistered and signals.yaml status=removed):**
- `steep_downtrend_under`: +0.2pp noise
- `low_var_mid_line_under`: -0.1pp, mid-line archetype hypothesis refuted
- `season_breakout_over`: -0.2pp, 2/4 seasons, OVER scoring-env artifact
- `career_matchup_under`: +0.2pp, 1/5 seasons; inverse outperforms

**Shadow (accumulating from 2026-27):**
- `star_out_rescue`: 74.3% overall but incremental zone (edge 3-5.9) = 54.4% in 2025-26 — DO NOT activate
- `season_breakout_under`: threshold tightened to -7.0 (73.0% HR N=407, 4/4 seasons)
- `fta_high_cv_under`: NEW — 61-64% HR 4/4 pre-anomaly seasons (same pattern as b2b_fatigue_under)
- `high_minutes_under`, `high_3pt_season_under`, `high_3pt_recent_under`: thin margins, shadow
- `drive_volume_under`: BROKEN at session time (scraper bug — drives all 0.0); fixed in Session 3

**Critical validation rules (permanent):**
1. **November UNDER baseline is +4-8pp higher** every normal season — any "early-season spike" is baseline inflation, not signal edge. Always compare vs monthly UNDER baseline.
2. **Rescue signals need the incremental-zone test** — for rescue (bypass edge floor), what matters is HR in edge 3.0-5.9, not headline HR. star_out_rescue headline = 74%, incremental = 54% in 2025-26.

### Session 3 — Cleanup & fixes (commits `7d1a3f9b` through `391dea2f`)

**Bug 1 — nba_tracking_stats `PlayerOrTeam=Player` (commit `7d1a3f9b`):**

Root cause of drives/touches all 0.0 across 307K rows:
- `nba_api` v1.11.4 `LeagueDashPtStats` has `PlayerOrTeam.default = team` (confirmed from package source)
- Scraper called it without `player_or_team='Player'` → team rows have TEAM_ID not PLAYER_ID → `_parse_result()` skipped all rows
- Only `MeasureType=Usage` (which IS player-level) populated `usage_pct`
- Fix: `player_or_team='Player'` in nba_api kwargs + `PlayerOrTeam=Player` in HTTP fallback params
- `drive_volume_under` signal will now get real `drives_avg_season` data from 2026-27 open

**Bug 2 — 4 removed signals still registered (commit `f6c18526`):**

The 4 removed signals above were still in `ml/signals/registry.py`. A registered signal NOT in `SHADOW_SIGNALS` or `BASE_SIGNALS` counts toward `real_sc` (the pick qualification gate). If any fired, picks could qualify on the strength of a known-bad signal. Fix: removed all 4 `registry.register()` calls. Also removed dead `matchup_3yr_query` from `supplemental_data.py` (saves 1 BQ query/day, nothing consumed its output).

**Docstring fix — `season_breakout_under` (commit `e2eeb527`):**
Threshold in docstring said -3.0; actual code is -7.0.

**Runbook update — season-resume fire rate monitor (commit `e492b737`):**
Fire rate monitor was tracking 13 shadow signals; added 7 more from the Session 2 batch (high_minutes_under, high_3pt_season_under, high_3pt_recent_under, star_out_rescue, drive_volume_under, season_breakout_under, fta_high_cv_under). Now 20 total.

---

## Key signal removal principle (PERMANENT — for future sessions)

**The `real_sc` gate relies on `SHADOW_SIGNALS` being complete.**

Any signal NOT in `BASE_SIGNALS`, NOT in `SHADOW_SIGNALS`, and NOT in `UNDER/OVER_SIGNAL_WEIGHTS` (or registered but at weight 0) will:
1. Count toward `real_sc` (could gate picks in based on a dead signal)
2. Get default weight 1.0 in UNDER quality scoring (could affect ranking)

**Correct removal pattern:**
- Signal still being monitored but shouldn't affect picks → add to `SHADOW_SIGNALS`
- Signal confirmed dead end → remove from `registry.py` (and update signals.yaml to `status: removed`)

---

## Current shadow signal fleet

### Validated by 5-season backtest (shadow → active gate exists)
| Signal | HR | N | Seasons | Promote when |
|--------|-----|---|---------|-------------|
| `b2b_fatigue_under` | 63.2% (5-season) | large | **5/5** | N≥30 live 2026-27 HR≥58% |
| `elite_line_under` | 63.2% | 1,679 | 4/5 | **ALREADY ACTIVE (weight 1.5)** |
| `season_breakout_under` | 73.0% (at -7.0) | 407 | 4/4 | N≥30 live HR≥68% |
| `fta_high_cv_under` | 61-64% (4 seasons) | ~7.8K | 4/4 pre-anomaly | N≥30 live HR≥58% |
| `star_out_rescue` | 74.3% overall | 1,797 | 4/5 | Incremental zone N≥30 HR≥65% + sign-off |
| `high_line_under` | 59.9% | large | 5/5 | N≥30 HR≥58% |

### Pre-registered (no backtest, accumulating from 2026-27)
| Signal | Mechanism | Promote when |
|--------|-----------|-------------|
| `national_tv_under` | Primetime + line≥22 | N≥30 HR≥55% |
| `whole_line_precision` | Whole-number line | UNDER: N≥30 HR≥62%; OVER: N≥50 HR≥70% |
| `line_converging_under` | CLV gate — line rose ≥0.5 by tip | N≥30 HR≥60% |
| `ref_crew_under_tendency` | Crew O/U tendency | N≥30 HR≥58% + 2 Covers seasons |
| `dense_schedule_grind_under` | 4+ games in 7 days | N≥30 HR≥58% |
| `long_road_trip_under` | 3+ consecutive away | N≥30 HR≥58% |
| `rotowire_bench_under` | Pre-game bench designation | N≥30 HR≥65% |
| `tight_consensus_under` | 6+ books posting today | N≥30 HR≥58% |
| `westward_road_trip_under` | Away team traveling west | N≥30 HR≥58% |
| `b2b_long_haul_under` | B2B + 1000+ miles | N≥30 HR≥62% |
| `multi_book_convergence_under` | 3+ books lowered line intraday | N≥30 HR≥58% |
| `high_minutes_under` | Season avg ≥34.5 mpg | N≥30 HR≥58%; only 3/5 seasons |
| `high_3pt_season_under` | Season 3PT% ≥40.2% | N≥30 HR≥60%; compare monthly baseline |
| `high_3pt_recent_under` | Last-3 3PT% ≥45.5% | N≥30 HR≥60%; check hot_3pt_under overlap |
| `drive_volume_under` | Drives/g ≥7 | Scraper fixed; N≥30 HR≥58% |
| `season_breakout_under` | -7+ PPG vs last season | N≥30 HR≥68% |
| `star_out_rescue` | Lead scorer OUT, rank 2-7 OVER | Incremental zone N≥30 HR≥65% |
| `fta_high_cv_under` | FTA avg ≥5, FTA CV ≥0.4 | N≥30 HR≥58% (excl. 2025-26) |
| `sharp_consensus_under` | Book std across 12+ books | N≥30 HR≥60%; book-count-regime aware |
| `quantile_floor_over` | p25 > line (MultiQuantile models) | N≥30 HR≥60% |
| `b2b_fatigue_under` | rest_days==1 UNDER | N≥30 HR≥58% |

### 5 demoted OVER signals (shadow, re-grade via over_decay_watch.py from Dec 2026)
- `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over`
- Each must clear N≥30 HR≥58% on live 2026-27 before weight restoration

---

## star_out_rescue activation gate (explicit sign-off required)

**DO NOT activate without:**
1. N≥30 live BB-level picks where signal fires
2. HR of those picks ≥65%
3. INCREMENTAL zone (edge 3.0-5.9 specifically) HR also ≥65%
4. **Explicit user sign-off**

Activation code: remove from `SHADOW_SIGNALS`, add to `rescue_tags` + `OVER_SIGNAL_WEIGHTS` (weight 2.5) in `aggregator.py`, update `signals.yaml` status=active.

---

## Remaining open items (prioritized)

### Season-open (Oct 2026) — cannot do now
1. **star_out_rescue** — check `signal_health_daily` weekly once season starts. Bring for sign-off when incremental HR gates pass.
2. **fta_high_cv_under** — accumulate. Promote when N≥30 HR≥58% on live data.
3. **drive_volume_under** — verify first-game-day `drives_avg_season` is non-zero in BQ.
4. **Shadow signal fire rate** — run the 20-signal monitor query from `season-resume-2026-27.md` on opening night.
5. **Add 2026 to `FALLBACK_SEASON_START_DATES`** in `shared/config/nba_season_dates.py` once NBA announces 2026-27 schedule.

### Off-season — potentially doable now
6. **VSiN scraper diagnostic** — data stopped 2026-03-28. Run `python scrapers/external/vsin_betting_splits.py --date TODAY --debug` to verify HTML class `txt-color-vsinred` is still valid. If class changed, update the scraper.

### Research converged — do NOT re-investigate
- career_matchup_under: model already encodes matchup; removed
- steep_downtrend_under: +0.2pp noise; removed
- Any more feature additions to the model: R²≈0 when predicting residuals from player/context features — adding features cannot help
- OVER edge-based signals at edge 3-5: net-negative in 4/5 seasons (43-50% HR); static edge-6 floor is correct
- low-variance mid-line archetype: hypothesis refuted at N=3,733
- CLV "static line" signals: 51.7% sub-breakeven

---

## Files changed this session (for context)

| File | Change |
|------|--------|
| `scrapers/external/nba_tracking_stats.py` | v1.2: add PlayerOrTeam=Player to both API and HTTP paths |
| `ml/signals/registry.py` | Remove 4 dead signal registrations |
| `ml/signals/supplemental_data.py` | Remove dead matchup_3yr_query |
| `ml/signals/signal_health.py` | Update drive_volume_under comment; add 13 shadow signals to ACTIVE_SIGNALS (done in session 2) |
| `ml/signals/aggregator.py` | Update comments; elite_line_under at weight 1.5 |
| `ml/signals/season_breakout_under.py` | Fix stale -3.0 threshold in docstring → -7.0 |
| `docs/02-operations/runbooks/season-resume-2026-27.md` | Fire rate monitor 13→20 signals |
| New shadow signal files (session 2) | high_minutes_under, high_3pt_season_under, high_3pt_recent_under, season_breakout_under, fta_high_cv_under, star_out_rescue, drive_volume_under, career_matchup_under (removed), low_var_mid_line_under (removed), steep_downtrend_under (removed), season_breakout_over (removed), elite_line_under (ACTIVE) |

---

## System health (off-season baseline)
- **Halt active**: no picks being generated
- **Weekly retrains**: `weekly-retrain` CF fires every Monday 5 AM ET (still running during off-season)
- **Signal/filter registry**: clean — all 4 removed signals fully unregistered
- **nba_tracking_stats scraper**: PlayerOrTeam bug fixed, will work correctly at 2026-27 open
- **Model fleet**: 10+ shadow models enabled, weekly retrains continuing
- **Infrastructure**: all auto-deploy triggers live, no drift expected

---

## Quick reference for new session

```bash
# Check recent commit history
git log --oneline -10

# Season-resume runbook (all season-open tasks and diagnostics)
docs/02-operations/runbooks/season-resume-2026-27.md

# Signal fleet current state
ml/signals/aggregator.py  # SHADOW_SIGNALS, UNDER_SIGNAL_WEIGHTS, OVER_SIGNAL_WEIGHTS
shared/registry/signals.yaml  # authoritative status/weight for all signals

# Test VSiN scraper (run if pursuing Fix #6 above)
PYTHONPATH=. .venv/bin/python3 scrapers/external/vsin_betting_splits.py --date 2026-07-02 --debug
```

---

## Prior session handoffs (full chain)
- `docs/09-handoff/2026-07-01-1-session-handoff.md` — Kelly haircut, low_var block, 4 new shadow signals
- `docs/09-handoff/2026-07-01-2-signal-research-session-handoff.md` — full signal backtest session
- `docs/09-handoff/2026-07-01-3-cleanup-fixes-handoff.md` — scraper fix + signal unregistration
- This document: `docs/09-handoff/2026-07-02-SESSION-HANDOFF.md` — comprehensive state for new chat
