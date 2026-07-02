# Handoff — NBA discovery session: star-OUT signal + 10-angle structural-mispricing sweep

**Date:** 2026-05-24 · **Type:** session close-out / next-session brief
**Prior handoff:** `2026-05-22-2-nba-vegas-line-leak-resolved.md` (leak fix landed; follow-ups deferred)
**Auto-memory created:** `kalshi-player-props-structure.md` · `star-out-vacated-touches-signal.md` · `nba-angles-tested-2026-05-23.md`

---

## 0. Orientation — read this first

This session set out to figure out whether we could expand NBA betting beyond points props (assists, rebounds, threes). The honest answer turned out to be **no for those specific markets** — Kalshi was the only source of historical line data and its spread structure makes everything unprofitable, plus its pricing died 2026-03-13. **But the methodology that emerged from killing that idea** — testing structural-event mispricing with a replicable recipe — found a major signal in the points market we already serve.

**Headline finding:** When a team's lead scorer (≥18 ppg trailing 30d) is OUT and the model recommends OVER at edge ≥ 3, targets at rotation rank 2-7 hit **79.4% over 4 seasons (N=509)**, and **98.3% of qualifying picks are not currently captured by the production pipeline** (they're blocked by the OVER edge floor of 6.0). This is a genuine capacity expansion of the existing system, not a marginal tweak.

**Engineering plan is written, governance-aware, and ready to execute.** The natural next session is to build it.

---

## 1. What landed this session

### Wins (3 signals discovered)

| Signal | Cohort | HR | Sample | Status |
|--------|--------|-----|--------|--------|
| **Star-OUT (ranks 2-4)** | Lead scorer OUT, target rank 2/3/4, model OVER, edge ≥3 | 79.4% | N=509, 4 seasons | Discovery doc + production plan ready |
| **Star-OUT extension (ranks 5-7)** | Same as above but ranks 5/6/7 | 72-84% per rank | N=441 across ranks | Folded into above doc |
| **Trade-aftermath UNDER** | Target player on new team, games 1-2 after `team_abbr` change | OVER 47.6% (losing), UNDER 61.8% | N=139 | Logged in memory; no formal doc yet |

### Negatives (7 angles tested, didn't survive)

| Angle | Why it died |
|-------|-------------|
| Threes-Kalshi Poisson | Kalshi 30-39c spreads eat edge in every direction; pricing dead 2026-03-13 |
| Star-RETURN | Effect captured by existing model; not unique structural mispricing |
| Opposing-team star-OUT | Books price opposing-team injuries correctly (residuals identical) |
| Minutes-trending-up | Opposite of hypothesis: mean reversion makes these picks worse, not better |
| Day-after-blowout | HR identical across won_by_20 / lost_by_20 / close — fully priced |
| Opposing rim-protector OUT | Marginal UNDER e5+ drop (-7pp), but not clean enough |
| Long-gap return (suspension proxy) | Small-N noise; both OVER and UNDER lose ~47% on 7-9 gap |

All 10 tests + reasons documented in `~/.claude/projects/.../memory/nba-angles-tested-2026-05-23.md` so future-me doesn't re-run them.

### Side discovery

`player_game_summary.three_pt_makes` population gap from 2026-03-03 onward (0-25% vs 85-95% prior). Raw `nbac_gamebook_player_stats.three_pointers_made` is fine (96% populated). Pure Phase 3 ETL regression. Task #7 still open. Doesn't block anything urgent.

### Docs created

- `docs/08-projects/current/star-out-vacated-touches-discovery/`
  - `README.md` — TL;DR, cohort, headline numbers, risk flags
  - `FINDINGS.md` — 14-section evidence package (raw spike, Vegas pricing, cross-season, edge interaction, injury timing, B2B robustness, incremental value, star-RETURN control, statistical significance, rank 5-7 extension, trade-aftermath sibling finding)
  - `PRODUCTION-PLAN.md` — Feature spec, signal pseudocode, shadow→active gates, volume cap, rollback, files-that-change list

### Docs deferred (you raised, scoped out for separate session)

- 199 stale projects in `docs/08-projects/current/` that should graduate to `completed/` or `archive/`
- Missing `DOCUMENTATION-INDEX.md` (README.md references it but it doesn't exist)
- Legacy top-level dirs outside numbered taxonomy (`docs/analysis/`, `docs/guides/`, `docs/investigations/`, etc.)
- No explicit graduation workflow in `CLAUDE-CODE-PROJECT-WORKFLOW.md`

Agent 3 from this session has the full audit. ~2 hours of work to triage.

---

## 2. The headline finding in 60 seconds

**Cohort:** For each (game_date, team):
1. Lead scorer = highest-ppg player on team trailing 30d, ≥5 games on team, ≥18 ppg
2. Lead scorer status = `out` in `nbac_injury_report` latest snapshot for that date
3. Target = same team, rank 2-7 by trailing-30 ppg
4. Model recommendation = OVER, model edge ≥ 3

**Result (4 seasons, 2022-23 through 2026-04):**

| Edge | Early-announce (≤4pm) | Late-announce (≥5pm) |
|------|------------------------|------------------------|
| 3-5 | 73.3% (N=146) | 65.4% (N=78) |
| 5+ | 86.3% (N=182) | 86.4% (N=103) |

Combined edge 3+: **79.4% HR (N=509)** — robust to B2B (slightly stronger), validated cross-season.

**Why this isn't already captured:** Current OVER edge floor is 6.0 (regime-adaptive). 357/363 qualifying picks in 2024-25 + 2026 partial fall below the floor → blocked. The signal works as a **rescue rule** that lowers the floor to 3.0 for this specific cohort.

**Sample size estimate live:** ~175 incremental picks/year at expected 70-72% HR. ROI ~+35% per bet. Modest absolute volume, real value.

---

## 3. Recommended next session: build the star-OUT rescue signal

**Why this and not something else:**
- Production plan is written and concrete (no design work needed)
- The signal is well-validated (4 seasons, 98% incremental, robust to B2B)
- Building it doesn't touch existing model artifacts (no retrain required, no schema migration)
- Per governance (CLAUDE.md), signal additions need user sign-off at each step — opening with this gives you a clean approval gate

**Steps (full detail in `docs/08-projects/current/star-out-vacated-touches-discovery/PRODUCTION-PLAN.md`):**

1. **Verify approach is still right.** Read PRODUCTION-PLAN.md §10 (files that will change). Walk through `ml/signals/aggregator.py` and confirm the rescue-list insertion point is where the plan expects.

2. **Wire the context computation.** Add `compute_star_out_context()` to `ml/signals/supplemental_data.py`. Takes the day's predictions + bq_client; returns dict keyed by `(game_date, player_lookup)` with `is_star_teammate_out` (bool) + `target_team_scorer_rank` (int).

3. **Add the signal evaluator.** Add `evaluate_star_out_rescue()` to `aggregator.py` with the pseudocode from PRODUCTION-PLAN.md §2. Register in rescue list between `combo_*` (priority 1) and `hse_rescue` (priority 3).

4. **Add backtest hook.** Modify `bin/simulate_best_bets.py` (or thin wrapper) to apply the rule as a hypothetical. Run on 2024-25 + 2025-26 partial. Expected output: ~175 incremental picks/season, HR ~70%+, no team-cap violations, no >5 days. Write results to `docs/08-projects/current/star-out-vacated-touches-discovery/BACKTEST-VALIDATION.md`.

5. **User sign-off before shipping.** Per CLAUDE.md governance — explicit approval required before shadow deploy.

6. **Ship to shadow.** Auto-deploy via push to main (per CLAUDE.md auto-deploy). Watch `signal_health_daily` and `model_performance_daily` for first 14 days of live data once season resumes.

7. **Promote to active** when N≥30, HR≥65%, no filter conflicts. Update `SIGNAL-INVENTORY.md` and bump algorithm version (e.g., `v523_star_out_rescue`).

**Estimated effort:** 1-2 days of focused work. Most complexity is in #2 (computing the context efficiently — single BQ scan vs N scans per prediction) and #4 (backtest validation).

**Known risk to flag at sign-off:** 2025-26 was the weakest season for the standalone cells (47%/52% vs 55-63% prior years). Likely reflects the broader 2025-26 model regime issues per `2025-26-anomaly-rootcause.md` rather than this signal specifically, but worth monitoring closely once live. If first 2 weeks of next-season shadow shows <50% HR, auto-disable per existing decay-detection pattern.

---

## 4. Other open items

### Existing pending task

- **#7 Investigate Phase 3 three_pt_makes gap (Mar 3+ 2026).** Side discovery. Phase 3 analytics processor for `three_pt_makes`/`three_pt_attempts` regressed starting 2026-03-03. Raw `nbac_gamebook_player_stats` has the data; the Phase 3 population step broke. Probably a small fix — check the `nbac_gamebook` processor's column-write logic. Not blocking anything because raw is fine; only affects users querying `player_game_summary.three_pt_makes` directly.

### Plausible follow-up discoveries (NOT yet scoped)

- **Trade-aftermath as its own discovery doc.** Small signal but distinct. ~30 min to write up; productionization is similar pattern to star-OUT but UNDER-side.
- **Untested angles still on the table:**
  - Coach change → usage redistribution (need coach data — not in BQ)
  - DPOY-tier specific defender OUT (needs defender quality metric)
  - Player archetypes that systematically over/under perform (player-level, not event-level)
  - Cross-validation of star-OUT with existing `combo_3way`/`book_disagreement` (additive or redundant?)
  - Pre-game line movement patterns on player props

### Bigger projects deferred

- **Docs cleanup** (Agent 3 findings — 199 stale projects, missing index, legacy dirs). ~2 hours minimum.
- **Leak handoff follow-ups** from 2026-05-22:
  - `check-date-comparisons` hook silently dead (`types:` AND-bug; needs dry-run before activating)
  - V18 features 60/61 array backfill (low priority)
  - First "real" clean retrain (waiting for season data to resume grading)

---

## 5. Things I learned the hard way

- **`bq query` with `PARTITION BY` on FLOAT64 fails.** Cast to STRING (`CAST(line_value AS STRING)`) when partitioning window functions by float columns.
- **`minutes` in `nbac_gamebook_player_stats` is a STRING in "MM:SS" format**, not a numeric. Use `SAFE_CAST(SPLIT(minutes, ":")[SAFE_OFFSET(0)] AS INT64)` for minutes-played filters.
- **`ROWS` is a BigQuery reserved keyword** — can't use as a column alias unquoted. Use `row_count` or similar.
- **`LAG()` can't appear in correlated subqueries' WHERE clauses.** Compute LAG in a CTE, then filter in the outer query.
- **Inactive players don't appear in `player_game_summary`.** Means "top scorer per team-game" via that table is always-present by construction. To find OUT players, use `nbac_injury_report` directly.
- **`prediction_accuracy` has multiple rows per (game_date, player_lookup)** because of multi-model predictions. `QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY line_value) = 1` to dedupe to one row per player-game.
- **The discovery recipe works but hit rate is ~30%.** Don't get attached to any single hypothesis. Test fast, bank the negatives in memory, move on.

---

## 6. Operational state at session end

- **Repo:** main, no uncommitted code changes (only docs/memory).
- **Best-bets:** still halted (playoff dormancy + edge-based auto-halt active per pre-session state). No change.
- **Fleet:** unchanged. No retrain attempted this session.
- **MLB betting:** still concluded as no-edge from 2026-05-22 session. Pipeline running as info product only.
- **Pre-commit hooks:** all passing (no code changes to trigger).
- **Docs added (3 new files):** `docs/08-projects/current/star-out-vacated-touches-discovery/{README,FINDINGS,PRODUCTION-PLAN}.md`
- **Memory files added (3 new):** `kalshi-player-props-structure.md`, `star-out-vacated-touches-signal.md`, `nba-angles-tested-2026-05-23.md`

---

## 7. If you want to verify any of this in 60 seconds

```bash
# Confirm discovery docs are in place
ls -la docs/08-projects/current/star-out-vacated-touches-discovery/

# Re-run the headline finding (production-pattern query in star-out-vacated-touches-signal.md)
# This should show ~79% HR on edge 3+ across the combined cohort:
bq query --use_legacy_sql=false --project_id=nba-props-platform '
WITH player_team_games AS (
  SELECT game_date, player_lookup, team_abbr, points, minutes_played
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN "2022-09-01" AND "2026-06-30"
    AND team_abbr IS NOT NULL AND points IS NOT NULL
),
-- [full SQL in star-out-vacated-touches-signal.md §"Cohort definition (SQL pattern — proven)"]
-- ...
SELECT 1'

# See task list (note many completed)
# TaskList in next session
```

---

## 8. Out of scope (kept out, still out)

- MLB pitcher-strikeout BETTING (concluded 2026-05-22, no edge, permanent halt). Pipeline stays as info product.
- Non-points NBA markets (assists, rebounds, threes singles) — no historical line data on real sportsbooks. Forward-collect for 2026-27 backtest.
- Re-opening Kalshi for any betting strategy — spreads + dead pricing make it not viable.
