# Session 314 Handoff — GCS Export Pipeline Investigation

**Date:** 2026-02-20
**Focus:** Investigating why GCS exports (best bets, subsets, live grading, performance) are stale/empty despite BQ having correct data
**Status:** Investigation complete, fixes NOT yet applied
**Prior sessions:** 312B (frontend issues), 312C (ANTI_PATTERN diagnosis), 313 (quality scorer fix)

---

## Summary

The BQ pipeline is healthy — predictions, grading, and subset performance all work internally. The problem is that the **GCS JSON exports** (which the frontend reads) are stale or empty across multiple endpoints. Feb 19 was one of the best prediction days of the season (V9 edge 3+ went 12-0, Best Bets subset went 16-4 at 80% HR), but users saw none of it.

---

## Key Discovery: Two Separate "Best Bets" Systems

This session uncovered that there are **two independent "best bets" systems** that are easily confused. The frontend sees both and reported both as "0 picks," but they are architecturally different.

### System 1: Subset-Based Best Bets (working)

| Property | Value |
|----------|-------|
| **Materializer** | `SubsetMaterializer` (during Phase 6 signal annotation) |
| **BQ table** | `current_subset_picks` (subset_id=`best_bets`) |
| **GCS path** | `v1/picks/{date}.json` (embedded in Phoenix model group) |
| **Selection logic** | Top 5 V9 picks by composite score |
| **Filters** | No edge floor, no signal filters, no ANTI_PATTERN check |
| **Feb 19 result** | **20 picks, went 16-4 (80% HR)** |
| **Code path** | `SignalAnnotator._bridge_signal_picks()` → `BestBetsAggregator` → `current_subset_picks` |

This is the system that generated the 16-4 record on Feb 19. It works because the `_bridge_signal_picks()` path in the signal annotator populates the dynamic subset via the materializer, which has different filtering behavior than the signal exporter.

### System 2: Signal-Based Best Bets (broken / 0 picks)

| Property | Value |
|----------|-------|
| **Exporter** | `SignalBestBetsExporter` + `BestBetsAggregator` |
| **BQ table** | `signal_best_bets_picks` |
| **GCS path** | `v1/signal-best-bets/{date}.json` |
| **Selection logic** | Edge 5+ floor, 8 negative filters, ANTI_PATTERN combo check, signal annotation |
| **Filters** | Edge floor (5.0), blacklist, familiar matchup, UNDER blocks, quality floor, ANTI_PATTERN |
| **Last produced picks** | Feb 11 (2 picks). Maximum ever was ~5 picks/day. |
| **Code path** | `SignalBestBetsExporter.generate_json()` → `BestBetsAggregator` → `signal_best_bets_picks` + GCS |

This is the system that the frontend reports as "0 picks." It applies many more constraints, including the ANTI_PATTERN combo registry check that 312C identified.

### Why This Distinction Matters

Future sessions must not conflate these two systems. The "best bets" the frontend team saw going 16-4 in BQ (System 1) are **not** the same "best bets" showing 0 picks in GCS (System 2). Fixing the signal-based system won't retroactively fix the picks grading display (which depends on live grading export, Issue 3 below).

---

## ANTI_PATTERN: Correcting Session 312C's Framing

Session 312C diagnosed the signal best bets 0-pick issue as: "ANTI_PATTERN entries block **every** edge 5+ pick." This is partially correct but overstates the problem.

### What 312C Got Right
- Two ANTI_PATTERN entries exist in `signal_combo_registry` (`high_edge` and `edge_spread_optimal+high_edge`)
- Both fire on all edge 5+ picks (by definition)
- A local test on Feb 20 confirmed: 60 candidates → 58 rejected by edge floor → 2 remaining rejected by ANTI_PATTERN → 0 output

### What 312C Missed
- **ANTI_PATTERN doesn't block "everything"** — it only blocks picks where the best combo match is ANTI_PATTERN. Picks with `minutes_surge` match the 3-way SYNERGISTIC combo (`edge_spread_optimal+high_edge+minutes_surge`, cardinality 3), which overrides the cardinality-2 ANTI_PATTERN match.
- **All picks from Feb 5-11 survived** precisely because they had `minutes_surge`, giving them a SYNERGISTIC combo match that beats the ANTI_PATTERN.
- **The ANTI_PATTERN is one factor among several.** On Feb 20, 58/60 candidates were rejected by the edge floor alone — only 2 even reached the ANTI_PATTERN check. The real bottleneck is low edge-5+ coverage (4.8% of predictions).
- **The `best_bets` dynamic subset (System 1) had 20 picks on Feb 19** using the same `BestBetsAggregator`. If ANTI_PATTERN truly blocked "everything," this subset should also be 0. The discrepancy suggests deployment drift or different code paths between the signal annotator and the signal best bets exporter.

### BQ Combo Registry State (confirmed)

| combo_id | classification | hit_rate | N | status |
|----------|---------------|----------|---|--------|
| `high_edge` | ANTI_PATTERN | 43.8% | 16 | BLOCKED |
| `edge_spread_optimal+high_edge` | ANTI_PATTERN | 31.3% | 16 | BLOCKED |
| 11 others | SYNERGISTIC | 56.9-95.5% | 14-156 | Various |

Same entries exist in fallback registry: `ml/signals/combo_registry.py` lines 87-102.

### Recommendation
Remove the ANTI_PATTERN entries **after** understanding the deployment discrepancy (P0/P2 below). The `high_edge` standalone stat (43.8%, N=16) was from picks where it was the ONLY signal — prevented by MIN_SIGNAL_COUNT=2. The entries are redundant AND harmful, but the root cause of 0 picks is multi-factorial.

---

## GCS Export Pipeline Issues

### Issue 1: `systems/subsets.json` Stale Since Feb 13

**Symptom:** GCS file `v1/systems/subsets.json` last updated Feb 13 (`generated_at: 2026-02-13T10:00:20`). Only shows 3 model groups (Phoenix, Aurora, Summit). Missing q43/q45 quantile models.

**BQ state (healthy):** `dynamic_subset_definitions` has 7 system_ids with 34 active subsets, including:
- `catboost_v9` (10 subsets)
- `catboost_v12` (9 subsets)
- `catboost_v9_q43_train1102_0131` (4 subsets)
- `catboost_v9_q45_train1102_0131` (3 subsets)
- `catboost_v12_noveg_q43_train1102_0125` (2 subsets)
- `catboost_v12_noveg_q45_train1102_0125` (2 subsets)
- `catboost_v9_low_vegas_train0106_0205` (4 subsets)

**`performance.json` IS being updated** (latest: Feb 20 at 10:00 UTC), so the `phase6-daily-results` scheduler is running. The subset definitions export specifically stopped.

**Code review:** `SubsetDefinitionsExporter.generate_json()` has no early-return or break-detection logic. It simply queries `dynamic_subset_definitions WHERE is_active = TRUE`. No obvious code bug.

**Likely cause:** Feb 13 was the start of All-Star break. Either:
1. The phase6 daily export stopped calling the subset definitions exporter during the break
2. The exporter ran but the upload failed silently
3. The scheduler job that triggers this specific export is broken/misconfigured

**Key file:** `data_processors/publishing/subset_definitions_exporter.py`

### Issue 2: Live Grading Export Broken

**Symptom:** `v1/live-grading/2026-02-19.json` has:
- `generated_at: null`
- 81 predictions, all `game_status: "scheduled"`
- 0 actuals populated

**BQ state (healthy):** `prediction_accuracy` has 1,011 graded records for Feb 19 at 68.4% HR (V9). Games are fully final.

**Investigation clues:**
- Post-game marker exists: `v1/live/post-game-2026-02-19.done` (created 05:00 UTC Feb 20)
- The file was written at 06:57 UTC Feb 20 but still has no actuals
- The `generated_at: null` is suspicious — suggests the score-fetching code path was skipped entirely
- The live grading exporter queries `player_game_summary` for `game_status = 3` scores

**Possible causes:**
1. `player_game_summary` didn't have `game_status = 3` when the export ran
2. Join key mismatch between exporter query and the actual data
3. The export Cloud Function ran but errored silently during score fetching

**Key file:** `data_processors/publishing/live_grading_exporter.py`

### Issue 3: `performance.json` and Picks Grading Stale

**Symptom:** `subsets/performance.json` last generated Feb 13. Picks files (`picks/{date}.json`) have `actual: null` / `result: null` on all records despite BQ having grading data.

**Likely downstream of Issues 1 & 2.** If live grading isn't populating actuals in GCS, performance aggregation can't compute windowed stats.

### Issue 4: Session 312 Changes Not Deployed

Session 312 committed but did NOT push:
- Aggregator now returns `Tuple[List[Dict], Dict]` with `filter_summary`
- `signal_best_bets_exporter.py` adds `filter_summary` + `edge_distribution` to JSON output
- `status_exporter.py` adds `best_bets` service to `status.json`
- All callers updated for tuple return
- 27 new tests, all passing
- **NOT yet pushed/deployed** — needs commit + push to trigger auto-deploy

---

## Frontend Gap Summary

**The core problem:** BQ has correct data (grading, predictions, subset performance) but the GCS exports that the frontend reads are stale or incomplete.

The frontend team documented this in `props-web/docs/backend-requests/2026-02-19-picks-pipeline-status-review.md`:

| GCS Endpoint | Frontend Sees | BQ Reality |
|-------------|---------------|------------|
| `picks/{date}.json` | 185 picks, 0 graded (no actuals) | 1,011 graded, 68.4% HR |
| `live-grading/{date}.json` | 81 predictions, all pending | All games final, fully graded |
| `best-bets/{date}.json` | 0 picks | System 1 had 20 picks, 16-4 (80% HR) |
| `signal-best-bets/{date}.json` | 0 picks | Last produced Feb 11 (2 picks) |
| `performance.json` | Stale since Feb 13 | Fresh data in BQ |
| `subsets.json` | Stale since Feb 13, missing q43/q45 models | 7 system_ids, 34 active subsets |

---

## Session 313 Quality Scorer Fix (Already Deployed)

- `quality_scorer.py` fix: optional features with `source='default'` or `source='fallback'` no longer penalize `quality_score`
- Previously, V12 optional features (f37-f53) defaulting would drag the quality score to ~69.6, just below the 70 threshold, blocking 132 players with zero required-feature defaults
- Deployed as commit `471ca805` to `nba-phase4-precompute-processors`
- Expected impact: ~132 more players quality-ready per game day (coverage recovery from ~42% toward ~73%)
- Feb 19 V9 grading: 68.4% HR (excellent first post-ASB day)

---

## Additional Note: BEST_BETS_MODEL_ID env var

The `phase6-export` Cloud Function has `BEST_BETS_MODEL_ID=catboost_v12` set. Effects:
- Signal annotator queries V12 predictions instead of V9
- Aggregator min_confidence = 0.90 (V12 config) — but there's a **scale mismatch bug**: confidence scores are 87-95 on 0-100 scale and floor is 0.90 on 0-1 scale, so this never actually blocks anything
- This env var was noted but not investigated further

---

## Today's Pipeline State (Feb 20)

| Metric | Value |
|--------|-------|
| Active predictions | 770 (61 per model x ~10 models) |
| Edge 3+ predictions | 120 (15.6%) |
| Edge 5+ predictions | 37 (4.8%) |
| Quality ready | 64/151 = 42.4% (pre-quality-scorer-fix) |
| Signal best bets produced | 0 |
| Dynamic `best_bets` subset | Not yet checked for Feb 20 |

---

## Updated Architecture Discovery (Late Session 314)

Further investigation revealed the system is **even more complex** than initially documented. There are actually **three** best bets code paths, **three** subset materialization streams, and a slow query.

### Three Best Bets Code Paths

| # | System | Exporter | Output | Aggregator | Blacklist? | Status |
|---|--------|----------|--------|------------|------------|--------|
| 1 | Legacy tiered | `BestBetsExporter` | `best-bets/{date}.json` | None (hardcoded tiers) | No | Pre-297, may still run |
| 2 | Signal-based | `SignalBestBetsExporter` | `signal-best-bets/{date}.json` + `signal_best_bets_picks` BQ | `BestBetsAggregator` | **YES** | 0 picks since Feb 11 |
| 3 | Annotator bridge | `SignalAnnotator._bridge_signal_picks()` | `current_subset_picks` (subset_id=`best_bets`) | `BestBetsAggregator` | **NO** | Working (16-4 on Feb 19) |

**Critical finding:** System 2 instantiates the aggregator with `player_blacklist=player_blacklist` while System 3 does NOT pass a blacklist. This difference may contribute to System 2 producing 0 picks while System 3 produces 20.

### Three Subset Materialization Streams (all write to `current_subset_picks`)

| Stream | Class | Trigger | Subsets | Notes |
|--------|-------|---------|---------|-------|
| **Core** | `SubsetMaterializer` | Phase 5 prediction completion | Dynamic from `dynamic_subset_definitions` | Quality gate: MIN_FEATURE_QUALITY_SCORE=85 |
| **Signal** | `SignalSubsetMaterializer` | `SignalBestBetsExporter` | 4 curated: `signal_combo_he_ms` (94.9%), `signal_combo_3way` (95.5%), `signal_bench_under` (76.9%), `signal_high_count` (85.7%) | Deletes + re-writes |
| **Cross-model** | `CrossModelSubsetMaterializer` | `AllSubsetsPicksExporter` | 5 consensus: `xm_consensus_3plus`, `xm_consensus_4plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement` | Observation-only |

All three streams write to the same `current_subset_picks` BQ table. Subsets are distinguished by `subset_id` and `trigger_source`.

### Slow Query Found

`SignalBestBetsExporter._query_games_vs_opponent()` (line ~535) scans the full season of `player_game_summary` every run (~675K rows) with no caching. All other publishing queries have proper partition filters.

---

## Action Items for Next Session (Prioritized)

### P0: Decide which best bets system to keep
**The core question:** We have 3 overlapping best bets systems. Which is the "right" one?

- **System 3 (annotator bridge)** produced the 16-4 picks on Feb 19 — great results but picks only live in BQ subsets, not in a dedicated GCS endpoint
- **System 2 (signal exporter)** was designed to be the canonical signal-based picks but hasn't produced picks since Feb 11
- **System 1 (legacy)** may be dead code

Options to evaluate:
1. **Consolidate to one system** — pick the best architecture and route all outputs through it
2. **Fix System 2** — remove ANTI_PATTERN, fix blacklist discrepancy, and ensure it produces the same quality picks as System 3
3. **Promote System 3** — give the annotator bridge its own GCS endpoint since it's already producing good picks

### P1: Push Session 312 changes
Session 312 changes (filter_summary, edge_distribution, status.json best_bets) are ready to deploy. This improves observability regardless of the root cause.

### P2: Investigate deployment state + ANTI_PATTERN discrepancy
```bash
# What code is actually deployed on phase6-export?
gcloud functions describe phase6-export --region=us-west2 --project=nba-props-platform --format="yaml(buildConfig.source)"
# Check Cloud Function logs for signal best bets
gcloud functions logs read phase6-export --region=us-west2 --limit=50 --start-time=2026-02-20T04:00:00Z
```
Also check: does the blacklist difference between System 2 and System 3 explain the discrepancy? Run System 2 locally without blacklist and compare output.

### P3: Fix live grading export
This is blocking the frontend from showing ANY results, including the great 16-4 picks. Check `player_game_summary` game_status and Cloud Function logs for the live-export function.

### P4: Fix subsets.json staleness
Manually trigger the subset definitions export. If it works, the issue is just the break-period scheduler not resuming.

### P5: Evaluate ANTI_PATTERN removal
The two ANTI_PATTERN entries (`high_edge`, `edge_spread_optimal+high_edge`) should likely be removed:
- The `high_edge` standalone stat (43.8% HR, N=16) was from picks where it was the ONLY signal — prevented by MIN_SIGNAL_COUNT=2
- The `edge_spread_optimal+high_edge` combo (31.3% HR, N=16) is small sample and these signals fire together on ALL edge 5+ picks by definition
- But do this AFTER understanding the deployment discrepancy (P0/P2)

### P6: Cache `_query_games_vs_opponent()`
This full-season scan runs every signal best bets export. Consider pre-computing weekly or caching the result.

### P7: Verify quality scorer fix impact
```bash
# Check Feb 21 quality coverage (should be 70%+ if fix is active)
bq query --project_id=nba-props-platform --nouse_legacy_sql \
'SELECT game_date,
  COUNTIF(is_quality_ready) as qr, COUNT(*) as total,
  ROUND(100.0*COUNTIF(is_quality_ready)/COUNT(*),1) as ready_pct
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = "2026-02-21" GROUP BY 1'
```

---

## Next Session Investigation Prompt

Copy this into a new session to continue the investigation:

> **Context:** Session 314 discovered we have 3 overlapping best bets systems and 3 subset materialization streams all writing to the same `current_subset_picks` table. See `docs/09-handoff/2026-02-20-SESSION-314-HANDOFF.md` for full details.
>
> **Questions to answer:**
> 1. **Which best bets system should be canonical?** System 3 (annotator bridge, no blacklist) went 16-4 on Feb 19. System 2 (signal exporter, with blacklist) has produced 0 picks since Feb 11. System 1 (legacy tiered) may be dead code. Read all three code paths, compare their selection logic, and recommend consolidation.
> 2. **Why does the blacklist difference matter?** System 2 passes `player_blacklist` to the aggregator, System 3 doesn't. Run System 2 locally without the blacklist and with the blacklist to see if that's the difference.
> 3. **Is the legacy `BestBetsExporter` still active?** Check if anything calls it or if `best-bets/{date}.json` is still being written.
> 4. **Fix the live grading export** — this is the highest-impact fix. The 16-4 picks exist in BQ but the frontend can't show them because `live-grading/2026-02-19.json` has 0 actuals. Check CF logs and `player_game_summary` game_status.
> 5. **Cache the slow query** — `SignalBestBetsExporter._query_games_vs_opponent()` scans the full season every run.
>
> **Key files:** `data_processors/publishing/signal_annotator.py` (bridge at line 242), `data_processors/publishing/signal_best_bets_exporter.py` (exporter at line 236), `data_processors/publishing/best_bets_exporter.py` (legacy), `ml/signals/aggregator.py` (shared aggregator).

---

## Key Files Reference

| File | Role |
|------|------|
| `ml/signals/aggregator.py` | BestBetsAggregator — edge-first selection with ANTI_PATTERN check (line 211) |
| `ml/signals/combo_registry.py` | Combo registry loader + fallback entries (ANTI_PATTERN at lines 87-102) |
| `data_processors/publishing/signal_best_bets_exporter.py` | Signal best bets (System 2) → GCS + `signal_best_bets_picks` BQ |
| `data_processors/publishing/signal_annotator.py` | Annotates predictions + bridges to `best_bets` dynamic subset (System 3, line 242) |
| `data_processors/publishing/best_bets_exporter.py` | Legacy best bets (System 1) → `best-bets/{date}.json` |
| `data_processors/publishing/subset_materializer.py` | Core dynamic subsets → `current_subset_picks` |
| `data_processors/publishing/signal_subset_materializer.py` | 4 curated signal subsets → `current_subset_picks` |
| `data_processors/publishing/cross_model_subset_materializer.py` | 5 consensus subsets → `current_subset_picks` |
| `data_processors/publishing/subset_definitions_exporter.py` | `systems/subsets.json` export |
| `data_processors/publishing/live_grading_exporter.py` | `live-grading/{date}.json` export |
| `data_processors/publishing/status_exporter.py` | `status.json` — Session 312 added best_bets service (not deployed) |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Session 313 fix (deployed) |
