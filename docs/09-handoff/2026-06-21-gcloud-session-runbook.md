# Runbook — STEPS 1, 6, 7 (need a working gcloud/BQ session)

**Date:** 2026-06-21
**Why a separate doc:** `gcloud` and the `bq` CLI HANG in the WSL env this work was done in. These three
steps are turnkey from any environment with working `gcloud`/BQ. Use the Python BQ client
(`project='nba-props-platform'`) — the local gcloud default project is wrong.

Context: STEPS 3/4/5 are DONE on branch `offseason-eval-foundation-2026-06` (commits `69abe001`,
`7e4ab54b`, `e3209a63`, `27c80733`; pushed; nothing deployed). Results:
`2026-06-21-STEP5-staleness-RESULT.md`, `2026-06-21-STEP4-gated-rerun-RESULT.md`.

---

## STEP 1 — verify the 4 prod crash/DvP fixes deployed (`39133b3f` on main)

These auto-deploy on push to main and touch the live best-bets path; confirm they actually shipped.

```bash
# 1a. Build succeeded on the functions trigger after the commit
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=10
#     → look for SUCCESS on cloudbuild-functions covering 39133b3f

# 1b. phase6-export CF updateTime post-dates the commit
gcloud functions describe phase6-export --gen2 --region=us-west2 \
  --project=nba-props-platform --format='value(updateTime)'

# 1c. No publishing/phase6 drift
./bin/check-deployment-drift.sh --verbose
```

Functional proof (already done this session, re-run to confirm post-deploy): the harness that surfaced
the crashes runs clean —
`PYTHONPATH=. python -u scripts/nba/training/discovery/bb_injection_run.py --start 2025-10-28 --end 2026-04-12`
(2025-26 reached 102 dates, timeouts=0, no `None.startswith` / DvP crashes). Don't use pick *output* as
the health signal — the system is auto-halted.

---

## STEP 6 — `model_bb_candidates`: identify the ~15 silently-NULL columns (Task #39)

The writer does `row = dict(c)` (`signal_best_bets_exporter.py:1397`), so a column is NULL whenever the
candidate dict `c` reaching the writer lacks that key. **Static check (done offline): all 45 schema names
DO appear as assignments somewhere in the build path — so the NULLs are a runtime PROPAGATION gap (the
aggregator/merger sets them on a different dict, or only conditionally), not missing code.** The BQ query
is the definitive identifier.

Generate the per-column NULL-rate query (45 cols) from the schema:
```bash
python - <<'PY'
import json
cols=[f['name'] for f in json.load(open('schemas/model_bb_candidates.json'))]
print("SELECT COUNT(*) n_rows,\n" +
      ",\n".join(f"  COUNTIF({c} IS NULL) AS {c}__null" for c in cols) +
      "\nFROM `nba-props-platform.nba_predictions.model_bb_candidates`\n"
      "WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);")
PY
```
Run it (Python BQ client). Columns where `*__null == n_rows` are the silently-NULL set. Then for each:
- **Trace where it SHOULD be set** — start at `_collect_all_model_candidates`
  (`signal_best_bets_exporter.py:~500`), the per-model aggregator pick dict, and `_tag_candidate`
  (`pipeline_merger.py:99`). Likely culprits: provenance fields the aggregator computes for its OWN picks
  but `_collect_all_model_candidates` rebuilds without copying (e.g. `combo_classification`,
  `combo_hit_rate`, `qualifying_subsets`, `observation_flags`, `direction_conflict_count`,
  `spread`/`over_rate_last_10`/`is_back_to_back`/`star_teammates_out` supplement-derived fields).
- **Decide populate vs trim** per column (the open question): populate if cheap and analytically useful;
  otherwise drop from the schema to stop advertising a dead column.
- This is eval/provenance plumbing (not the live pick path) — safe to fix on the branch.

---

## STEP 7 — verify + RESUME the assists/rebounds schedulers (TIME-BOUND: before NBA opening night, late Oct 2026)

The cheap, non-regret data clock. 4 jobs created 2026-04-06 (MEMORY); a broad off-season pause batch makes
them *plausibly* PAUSED. They must fire year-round so a season of REB/AST lines+actuals accrues for a real
multi-season backtest by ~Feb-Mar 2027. **No model build** — data only.

```bash
# 7a. Check state (the 4 jobs)
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format='table(name,state,schedule)' | grep -iE 'assists|rebounds'
#   expected names: nba-assists-props-morning, nba-assists-props-pregame,
#                   nba-rebounds-props-pregame, nba-rebounds-props-morning

# 7b. If state=PAUSED, resume each:
for J in nba-assists-props-morning nba-assists-props-pregame \
         nba-rebounds-props-pregame nba-rebounds-props-morning; do
  gcloud scheduler jobs resume "$J" --location=us-west2 --project=nba-props-platform
done

# 7c. Confirm data is landing (after a fire) — Python BQ client:
#   SELECT market_type, COUNT(*), MAX(game_date)
#   FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
#   WHERE market_type IN ('assists','rebounds') GROUP BY 1
```
Zero code changes needed (`bp_player_props` already supports market IDs 151/assists, 157/rebounds; raw
table has `market_type`). If a scheduler firing surfaces issues, fall back to the deploy script noted in
MEMORY (assists/rebounds market expansion, Session 515).

---

## After this session's branch work — when ready to act on STEP 3 (HSE floor)

The floor ships **default OFF** (`HSE_RESCUE_FLOOR_MODE=off`). Recommended promotion (each step its own
sign-off; merging `ml/signals/aggregator.py` to main auto-deploys the worker):
1. Merge branch → main (deploys aggregator with mode still `off` = no behavior change).
2. Set `HSE_RESCUE_FLOOR_MODE=observe` on prediction-worker/coordinator (use `--update-env-vars`, NEVER
   `--set-env-vars`) to accrue `hse_rescue_floor` rows in `best_bets_filtered_picks`.
3. After N ≥ 30, compute CF HR of `filter_reason='hse_rescue_floor'`; promote to `active` ONLY if CF HR ≤ 45%.
</content>
