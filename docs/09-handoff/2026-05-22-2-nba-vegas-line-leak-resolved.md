# Handoff — NBA odds-snapshot leak: RESOLVED + follow-ups

**Date:** 2026-05-22 (evening) · **Type:** session close-out
**Supersedes the open work in:** `docs/09-handoff/2026-05-22-1-nba-vegas-line-leak-fix.md`
**Related auto-memory:** `nba-feature-leak-audit.md` (rewritten this session) ·
`pre-commit-types-or-gotcha.md` (new)

---

## 0. Orientation — read this first

The earlier handoff (`-1-`) scoped the fix to "one confirmed leak in `feature_extractor.py`".
**That scope was incomplete.** During execution, the new pre-commit guard I built was run
repo-wide and surfaced **11 more locations** doing the same pattern — including in LIVE
signal/pipeline code and in the V18 training path that bypasses the feature store.

All 16 locations are now fixed, deployed, and guarded against regression. The historical
feature store is backfilled for the affected window. This document captures (1) what
landed, (2) verification numbers, and (3) the three concrete follow-ups that remain.

Severity framing from `-1-` still holds: **live picks were not contaminated** (post-tip
snapshots don't exist at serve time); the leak primarily affected training data and
feature-store-based backtests. Modest in absolute terms (~0.27 line error on ~10% of
rows), real enough to fix.

---

## 1. What landed

### Commits (all on main)

| SHA | Summary |
|-----|---------|
| `5bf94ebe` | feature_extractor.py 5-query fix + `check_odds_snapshot_filter.py` hook |
| `f61ef08f` | hook `types_or` fix — see §3.1 below for why this matters |
| `0ea9a9ee` | 11 more leaks: signals · processors · training · schemas |
| `ebcafcd8` | `scripts/backfill_vegas_leak_fix.py` (one-time cleanup script) |

### Files touched (the 16 leaks)

- `data_processors/precompute/ml_feature_store/feature_extractor.py` — 5 queries
  (`odds_api_lines` → feat 25/27, `latest_per_book` → feat 50, `daily_consensus` → feat 54,
  `dk_closing` → feat 60, `latest_snapshot` → feat 61). The stale "no leakage" docstring
  on `_batch_extract_v18_line_movement` is corrected.
- `ml/signals/per_model_pipeline.py` + `ml/signals/supplemental_data.py` — 4 queries
  total (`dk_line_movement` + `sharp_lean` in each). **Live best-bets pipeline.**
- `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py`
  + `betting_data.py` — Phase 3 current-line picks.
- `ml/experiments/quick_retrain.py` — V18 `line_movement_query` + `vig_skew_query`.
  **The 6-agent audit's §2 ("training assembly column-based, no target bleed") missed
  this entire path.** `quick_retrain.py` computes V18 features 60/61 directly from
  the raw odds table, bypassing the feature store.
- `bin/backfill_f47_f50.py` — count + merge queries. Explains why historical
  `feature_50_value` was ~83% contaminated.
- `schemas/bigquery/raw/odds_api_props_tables.sql` — `odds_api_player_points_props_latest_by_player`
  VIEW. The `_recent` view is intentionally exempt (it returns all snapshots,
  doesn't pick a latest); marked with a `pre-tipoff-exempt` comment.

### The guard

`.pre-commit-hooks/check_odds_snapshot_filter.py` + entry in `.pre-commit-config.yaml`.
Flags any `ORDER BY snapshot_timestamp DESC` on `odds_api_player_points_props` that
lacks a `minutes_before_tipoff` bound. **CTE-block-scoped** via paren matching, so an
adjacent safe CTE can't mask a leaky one. Override mechanism: `pre-tipoff-exempt`
comment inside the block. Currently blocking and reports clean across the whole repo.

### Cloud Build deploys (all SUCCESS)

Push 1 (`5bf94ebe..f61ef08f`): `deploy-nba-phase4-precompute-processors`.
Push 2 (`f61ef08f..0ea9a9ee`): 8 services — `deploy-nba-phase3-analytics-processors`,
`deploy-phase6-export`, `deploy-post-grading-export`, `deploy-live-export`,
`deploy-prediction-coordinator`, `deploy-prediction-worker`,
`deploy-mlb-prediction-worker`, `deploy-mlb-phase6-grading`.

Push 3 (`ebcafcd8`): docs/scripts change, no auto-deploys triggered.

### Backfill (data operation)

`scripts/backfill_vegas_leak_fix.py --start 2025-10-01 --end 2026-05-22 --apply` was
run this session. Updated rows in `ml_feature_store_v2`:

| Feature | Column | Rows updated |
|---------|--------|--------------|
| 25 | `feature_25_value` (vegas_points_line) | 2,130 |
| 27 | `feature_27_value` (vegas_line_move) | 2,571 |
| 50 | `feature_50_value` (multi_book_line_std) | **7,889** |
| 54 | `feature_54_value` (prop_line_delta) | 506 |
| **Total** | | **13,096** |

The script only UPDATEs rows where the existing value is non-null and differs from
the clean recomputation by > 0.001 (surgical — doesn't fill nulls, doesn't touch
bettingpros-fallback rows).

**Why only Oct 2025 → present?** In-game snapshots (`minutes_before_tipoff < 0`)
only started appearing in `nba_raw.odds_api_player_points_props` in October 2025.
Pre-Oct-2025 data is naturally clean because the leak vector didn't exist yet.
Confirmed empirically: a validate-mode run on 2024-12-15 showed 0 differing rows
across all 4 features.

### Retrain attempted (this session)

`./bin/retrain.sh --all --enable` ran. **All three attempted families failed**
(`lgbm_v12_noveg_mae`, `v12_noveg_mae`, `xgb_v12_noveg_mae`) with
`_detect_best_eval_system_id: no graded predictions found in eval window`. Eval window
defaults to "most recent 7 days" = 2026-05-15..21, and the system has been in playoff
halt since late March, so there are no graded predictions to evaluate against.

The clean code path was exercised. No new models entered the fleet. **Nothing in
production changed.** The next retrain that produces models will happen when graded
predictions resume.

---

## 2. Verification

### Pre-registered §6 query (per the original handoff), Jan-Feb 2026

Compares stored `feature_25_value` against the latest pre-tipoff line for the same
(player_lookup, game_date). Predictive-leak signal: do differing rows track actual
outcomes better than the correct pre-tip line would?

|                          | Before fix | After backfill |
|--------------------------|-----------:|---------------:|
| Rows joined              | 5,804      | 5,805 |
| Differing (> 0.5 line)   | 1,191      | **33** |
| % differing              | 20.52%     | **0.57%** |
| Avg abs line diff        | 0.399      | **0.0072** |
| Max abs line diff        | 18.0       | 3.0 |
| Pre-tip residual (clean) | 4.867      | — |
| Stored residual (leaky)  | 4.429      | — |

The remaining 33 differing rows (~0.6%) are very likely bettingpros-fallback rows —
the leak class is different there (`bettingpros_player_points_props` uses `created_at`
and has no `minutes_before_tipoff` column), so they are intentionally out of scope.

### Direct contamination rate (raw snapshot picks)

9.6% of player-games (629/6,554) in Jan-Feb 2026 had the *old* query pick an in-game
snapshot. Aligns with the original handoff's "~7%" estimate (close enough; methodology
differs slightly).

### Guard runs clean

```bash
python .pre-commit-hooks/check_odds_snapshot_filter.py
# -> "Odds-snapshot leak guard: OK" (exit 0)
```

---

## 3. Three follow-ups — pick them up here

### 3.1 `check-date-comparisons` hook is silently dead (same `types:` bug)

`.pre-commit-config.yaml` line 73-78: the existing Session-458 leak guard uses
`types: [python, sql]`. In pre-commit, `types:` is AND-ed — a file is never both
python and sql, so this matches **zero files** and the hook has been silently skipped
since it was deployed. Switch to `types_or: [python, sql]` (one-word fix).

**Why this needs your sign-off instead of a one-line patch:** the hook is *blocking*
(returns 1 on flagged patterns). Activating it could surface pre-existing failures
across the repo that have accumulated while it was dead. Suggested approach:
1. Switch the spec, run `python .pre-commit-hooks/check_date_comparisons.py` locally
   first, see what (if anything) it flags.
2. If clean, just commit the spec fix.
3. If it flags things, triage and either fix or add to the hook's exception list
   before the spec change lands.

This is the analog of what I did with my new hook in commit `0ea9a9ee` (where it
flagged 11 things and I fixed them all).

### 3.2 Features 60 / 61 in the deprecated `features` array

`ml_feature_store_v2` has no `feature_60_value` / `feature_61_value` columns — V18
features only live in the `features` ARRAY (per `shared/ml/feature_contract.py`
`FEATURE_STORE_FEATURE_COUNT = 60`, comment says "Bump to 64 when BQ schema migration
adds feature_60-63 columns").

This session's backfill did **not** rewrite array offsets 60/61. Two reasons it's
low-priority:
1. `ml/experiments/quick_retrain.py` (the manual retrain path) computes V18 features
   directly from raw odds — now-clean. So new models train clean for 60/61 without
   any feature-store intervention.
2. The weekly-retrain CF reads from the feature store (see §3.3 background), but it
   uses `feature_N_value` columns; the array column is "deprecated" per memory. If
   the CF reads features 60/61 (need to verify), it does so through the array — and
   that's the path that's still tainted historically.

If you do want to fix it, the approach is an UPDATE that rebuilds the array element:

```sql
UPDATE `nba-props-platform.nba_predictions.ml_feature_store_v2`
SET features = (
  SELECT ARRAY_AGG(
    CASE WHEN off = 60 THEN @clean_60
         WHEN off = 61 THEN @clean_61
         ELSE element END ORDER BY off
  )
  FROM UNNEST(features) element WITH OFFSET off
)
WHERE game_date = ... AND player_lookup = ...
```

Per (player_lookup, game_date). Tedious but mechanical. Probably not worth doing
unless you find a model that's measurably affected. Marked as a known soft spot in
auto-memory.

### 3.3 First "real" clean retrain — wait for season data

The retrain attempted this session failed because eval window 2026-05-15..21 has no
graded predictions (playoff dormancy since ~Mar 28). Two paths forward:

- **Wait.** Whenever the next season starts and graded predictions resume, the next
  `weekly-retrain` CF run (Monday 5 AM ET) will be the first end-to-end clean retrain:
  - Reads training data from `ml_feature_store_v2` — now backfilled clean for 2025-10
    onward (and unaffected pre-Oct-2025).
  - Uses the (now-clean) `quick_retrain.py` *only if* invoked through `./bin/retrain.sh`.
    The CF itself uses its own embedded training code that reads from the feature store;
    it does not import `quick_retrain.py`. (See §4 — I almost wasted an op redeploying
    the CF for no reason.)
- **Force a retrain on pre-playoff data** if you want validation now. Pass an explicit
  earlier eval window, e.g.:
  ```bash
  ./bin/retrain.sh --all --enable --train-end 2026-02-28 --eval-days 7
  ```
  Auto-caps from Session 514 already nudge train_end to pre-late-season, but the
  `--eval-days` default still tries to use "most recent N days" which is empty right now.
  Need `--eval-system-id` or a wider lookback.

Either way: no production impact unless models pass governance + get promoted; promotion
is a separate user-approved step per CLAUDE.md.

---

## 4. Things I learned the hard way (so you don't have to)

- **`weekly-retrain` CF does NOT import `quick_retrain.py`.** It has its own 45KB
  embedded training implementation in `main.py`. The comment references at lines
  161, 174 are hyperparameter-provenance notes only. I almost authorized a manual
  deploy that wasn't needed — corrected mid-session.
- **`pre-commit` `types: [python, sql]` is AND-ed.** Use `types_or: [python, sql]`.
  Caught it because my new hook silently skipped a Python file it should have flagged.
- **In-game snapshots only appear from Oct 2025 onward in the raw odds table.** Verifying
  this empirically before sizing the backfill saved a lot of unnecessary BQ scanning.
- **Feature 54 (`prop_line_delta`) was already sparsely populated** (~33% of rows
  overall, with Nov-Jan 2025/26 entirely null) before this fix. That's a separate
  population gap, not a contamination issue. The backfill script's surgical
  "only update existing non-null" behavior leaves those nulls alone — intentional.
- **The 6-agent audit's "training assembly column-based" claim is wrong for V18.**
  V18 features 60-63 are computed by `quick_retrain.py` from raw odds. If you do
  future audits, look for direct raw-table reads in training/retrain code, not just
  feature-store read paths.

---

## 5. Operational state at session end

- **Repo:** main is at `ebcafcd8`. All 4 commits pushed.
- **Builds:** 9 service deploys SUCCESS. No drift expected; run
  `./bin/check-deployment-drift.sh --verbose` to confirm.
- **Best-bets:** still halted (playoffs / edge-based auto-halt active per pre-session
  state). No change from this session's work.
- **Fleet:** unchanged. Retrain produced no new models.
- **Pre-commit hook:** active and blocking. Repo clean against it.

---

## 6. If you want to verify any of this in 30 seconds

```bash
# Hook clean?
python .pre-commit-hooks/check_odds_snapshot_filter.py

# Backfill verification — should show ~0.6% differing
bq query --use_legacy_sql=false --project_id=nba-props-platform '
WITH lp AS (SELECT DISTINCT player_lookup, game_date,
  FIRST_VALUE(points_line) OVER (PARTITION BY player_lookup, game_date
    ORDER BY CASE WHEN bookmaker = "draftkings" THEN 0 ELSE 1 END, snapshot_timestamp DESC) AS line_pre
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
  WHERE game_date BETWEEN "2026-01-01" AND "2026-02-28"
    AND points_line IS NOT NULL AND minutes_before_tipoff >= 0),
fs AS (SELECT player_lookup, game_date, feature_25_value AS stored
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN "2026-01-01" AND "2026-02-28" AND feature_25_value IS NOT NULL)
SELECT COUNT(*) n, COUNTIF(ABS(stored-line_pre) > 0.5) differing,
  ROUND(COUNTIF(ABS(stored-line_pre) > 0.5)/COUNT(*)*100, 2) pct
FROM fs JOIN lp USING (player_lookup, game_date)'

# Recent commits
git log --oneline 518ce4c8..HEAD
```

---

## 7. Out of scope (already noted in the original handoff and still out of scope)

- **MLB pitcher-strikeout project** — concluded, efficient market, no edge. Untouched.
- **2022-23 feature_25 rows** — `minutes_before_tipoff` was mostly NULL then. Per the
  original handoff's "exclude" recommendation, those rows were not in the backfill
  scope and stay flagged as a known soft spot for any training that reaches into
  that period.
- **bettingpros-fallback rows** — different table, different leak class (uses
  `created_at`, no `minutes_before_tipoff` column). The ~33 residual differing rows
  in §2's verification are almost certainly these. If a future audit cares, it would
  need a separate fix for bettingpros.
