# Session 518 Handoff — MLB Pipeline Root Cause Found & Partially Fixed

**Date:** 2026-04-09 (long evening session)
**Focus:** Daily check → uncovered MLB pipeline still 100% blocked despite S517 → discovered actual root cause (3 months of silent data loss) → fixed it → uncovered chain of secondary bugs in unshipped exporter code path
**Commits:** `fe1fd520`, `e744894f`, `7b06658a` (all on `main`)

---

## TL;DR

- **Sessions 515 and 517 chased the wrong root cause for 3 months.** BettingPros API has been working the whole time. The Phase 2 file router was missing a single registry entry for `bettingpros-mlb/pitcher-` paths → silent data drop since at least 2026-01.
- **Phase 2 router fix shipped.** `bp_pitcher_props` BQ table now has data for 2026-04-09 (9 rows) for the first time since 2025-09.
- **MLB predictions now use BP features.** Edges jumped from 0.23-0.45 K range (oddsa fallback) to 0.27-1.20 K range (proper distribution). 1 valid best bet identified: **jeffrey_springs OVER 0.82**.
- **Persistence still broken.** `signal_best_bets_picks` BQ insert fails on `game_pk cannot be empty`. The exporter's row builder doesn't pass game_pk through.
- **NEW high-severity findings late session** (Agent 3 risk assessor): prediction duplication (1500 rows for Apr 9 from manual retriggers), `is_home` 100% NULL on `pitcher_strikeouts`, 32 unbackfilled `scraper_failures` waiting for the broken gap-backfiller.

---

## START HERE — Session 519 First Hour

### 1. Manual SQL backfill jeffrey_springs (5 min) — DO FIRST

This pick was identified by the exporter at 01:22 UTC on 2026-04-10 but never persisted due to the `game_pk` schema bug. Don't lose a real OVER pick:

```sql
-- Step 1: Look up game_pk
SELECT CAST(game_id AS INT64) AS game_pk, team_abbr, opponent_team_abbr
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE player_lookup = 'jeffrey_springs' AND game_date = '2026-04-09';

-- Step 2: Verify the row doesn't already exist (Session 519 may have already fixed game_pk and inserted)
SELECT * FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date = '2026-04-09' AND pitcher_lookup = 'jeffrey_springs';

-- Step 3: Manual INSERT (only if Step 2 returns nothing)
-- Pick details: jeffrey_springs OVER 4.5, edge 0.82, predicted 5.32 K
-- Model: catboost_v2_regressor, system rank 1, no signal count, no rescue
INSERT INTO `nba-props-platform.mlb_predictions.signal_best_bets_picks` (
  pitcher_lookup, game_pk, game_date, system_id, pitcher_name,
  team_abbr, opponent_team_abbr, predicted_strikeouts, line_value,
  recommendation, edge, confidence_score, signal_tags, signal_count,
  real_signal_count, rank, pick_angles, algorithm_version,
  signal_rescued, ultra_tier, ultra_criteria, staking_multiplier, created_at
) VALUES (
  'jeffrey_springs',
  <FILL_FROM_STEP_1>,
  '2026-04-09',
  'catboost_v2_regressor',
  'Jeffrey Springs',
  'ATH', 'MIA',  -- verify against pgs
  5.32, 4.5, 'OVER', 0.82,
  9.999,  -- clamped per Session 518 fix (raw was 20.12)
  '', 0, 0, 1,
  [], 'mlb_v2',
  FALSE, FALSE, [], 1,
  CURRENT_TIMESTAMP()
);
```

### 2. Apply game_pk surgical fix (5 min code, 10 min deploy+verify)

**Agent 1 verified the data flow**: `data_processors/analytics/mlb/pitcher_game_summary_processor.py:148` does `CAST(game_pk AS STRING) as game_id`. The pick dict's `game_id` IS the `game_pk`, just stringified. Cast back to int.

**File:** `ml/signals/mlb/best_bets_exporter.py:1029`

```python
# Before
'game_pk': pick.get('game_pk'),

# After
'game_pk': int(pick['game_id']) if pick.get('game_id') else None,
```

Commit, push (auto-deploys mlb-prediction-worker via `deploy-mlb-prediction-worker` trigger), verify build, **then route traffic explicitly** (see DON'Ts below):

```bash
# After build SUCCESS:
gcloud run services update-traffic mlb-prediction-worker \
  --to-revisions=mlb-prediction-worker-XXXXX-yyy=100 \
  --region=us-west2 --project=nba-props-platform
```

Then trigger best-bets ONE TIME ONLY (not predict-batch — see DON'Ts):

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST \
  https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"2026-04-10"}'
```

Verify with:
```sql
SELECT pitcher_lookup, recommendation, edge, confidence_score
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
WHERE game_date = '2026-04-10' ORDER BY edge DESC;
```

### 3. Then SYSTEMATIC schema audit (60 min) — BEFORE fixing anything else

**Agent 2's strongest insight**: 5 distinct bugs in one code path means it's **unshipped code**, not buggy code. `MlbBpHistoricalPropsProcessor` was created Jan 2026 for backfill, annotated as live-capable, never tested end-to-end. The exporter has multiple schema mismatches we haven't found yet.

**Don't iteratively patch.** Read end-to-end and build a schema-drift table BEFORE touching code:

```sql
-- Get the live schema
SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale
FROM `nba-props-platform.mlb_predictions.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'signal_best_bets_picks'
ORDER BY ordinal_position;
```

Then map every key the exporter writes (`ml/signals/mlb/best_bets_exporter.py:1018-1044`) against the schema. Build this table in S519 doc:

| Pick dict key | BQ column | Type match? | Nullable match? | Status |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

Fix all mismatches in ONE commit. Don't ship piecemeal.

---

## Critical DO NOTs (Carry Into Session 519)

| Don't | Why |
|---|---|
| **DO NOT manually trigger `/predict-batch`** | Every call adds 300 duplicate rows to `pitcher_strikeouts`. We already have 1500 rows for 2026-04-09 from 5 retriggers (vs 300 for normal days). Each call compounds the duplication. Use `/best-bets` only — it reads existing predictions. |
| **DO NOT redeploy `mlb-prediction-worker` with `--to-latest`** | A staging-tagged revision (`mlb-prediction-worker-00005-gon`) silently pins traffic. `--to-latest` returns success but doesn't move traffic. ALWAYS use `--to-revisions=NEW_NAME=100` explicitly. |
| **DO NOT redeploy `scraper-gap-backfiller` without investigating** | Revisions 00003 (Jan 30) and 00004 (Feb 5) both failed `HealthCheckContainerError` on container startup. Likely missing transitive deps in `requirements.txt` (pyyaml/pytz, or `config/scraper_parameters.yaml` not in zip). Fix the root cause before pushing a 00005. |
| **DO NOT touch `confidence_score` schema** without considering downstream | Today's clamping (`7b06658a`) is a write-time hack. The `pitcher_strikeouts` table accepts the raw value. Any dashboards comparing the two will show drift. |

---

## What Was Done This Session

### Discovery chain
1. Daily check found NBA `nbac_player_boxscore` failing every 4h (12:00, 16:00, 20:00 UTC). Caller passes `date` instead of `gamedate`.
2. Found MLB `pitcher_strikeout_predictions` empty YTD — concluded MLB pipeline still 100% blocked, contradicting S517 handoff.
3. Launched **3 parallel agents**: MLB feature investigation, NBA scraper investigation, strategic priority review.
4. **Agent 1 (MLB)** found `pitcher_loader.py` selects 300 pitchers from past 365 days (not today's starters), and the worker writes to `pitcher_strikeouts` (live table, has 4178 rows!) not `pitcher_strikeout_predictions` (deprecated). Predictions ARE happening; my table check was wrong.
5. **Agent 2 (NBA)** found `parameter_resolver.py:447` returns `{'date': ...}` instead of `{'gamedate': ...}` on empty games list. Triggered by `scraper-gap-backfiller` CF still pinned to Jan 24 revision because Jan 30/Feb 5 revisions failed startup. Cloud Run silently kept old revision while reporting `latestRevision: true`. **2 months of silent traffic pinning.**
6. **Agent 3 (Strategic)** flagged: even after fixes, model may have been trained on BP data and now we feed oddsa data — distribution shift risk.
7. Investigated D (BP API outage) and found: scraper IS getting data (10 props/day with full feature set). File written to `gs://nba-scraped-data/bettingpros-mlb/pitcher-strikeouts/2026-04-09/props.json`. Phase 2 receives the trigger but logs `WARNING: No processor found for file: bettingpros-mlb/pitcher-strikeouts/2026-04-09/props.json`. **The Phase 2 file router was missing a single registry entry.** The processor existed (`MlbBpHistoricalPropsProcessor`), supported live data per docstring, but was never registered.
8. Fix shipped (commit `fe1fd520`). Cloud Build deployed `nba-phase2-raw-processors` automatically. **`mlb-phase2-raw-processors` is NOT auto-deployed** (shared image, no separate trigger) — required manual `gcloud run services update --image=...`.
9. Re-triggered BP MLB scraper. Phase 2 processed the file successfully. `bp_pitcher_props` got 9 rows for 2026-04-09.
10. Re-triggered MLB worker. Same `BLOCKED` warning — `bp_features` LEFT JOIN at `pitcher_loader.py:502` uses direct equality but bp uses `anthonykay` format and pgs uses `anthony_kay` format. Format mismatch (oddsa already had `REPLACE` pattern; bp didn't).
11. Fix shipped (commit `e744894f`). Re-triggered worker. **8 valid predictions from today's starters** with edges 0.27-1.20 K (was 0.23-0.45 K via oddsa). max_meyer 1.2, jeffrey_springs 0.82.
12. Triggered `/best-bets` endpoint. Exporter identified jeffrey_springs as the first 2026 MLB best bet candidate. **BQ insert failed with `confidence_score` NUMERIC(4,3) overflow** (regressor outputs 5-20+, schema max ±9.999).
13. Fix shipped (commit `7b06658a`) clamping confidence_score. Re-triggered. Next BQ error: `game_pk cannot be empty`.
14. Stopped before fixing game_pk. Launched **4 strategic review agents** to plan next steps.
15. User decided to stop and write handoff (this doc).

### Commits pushed
| SHA | What |
|---|---|
| `fe1fd520` | Register `MlbBpHistoricalPropsProcessor` in Phase 2 router |
| `e744894f` | `pitcher_loader.py:502` bp JOIN player_lookup format fix |
| `7b06658a` | Clamp `confidence_score` to NUMERIC(4,3) bounds in MLB best bets exporter |

### BQ operations
- `UPDATE nba_orchestration.scraper_failures SET backfilled = TRUE` for `nbac_player_boxscore` 2026-04-08 (1 row affected) — cleared the orphan that was driving the every-4h failure storm.

### Infrastructure changes
| Change | Details |
|---|---|
| Manual deploy | `mlb-phase2-raw-processors` revision `00006-pwz` (image `nba-phase2-raw-processors:latest`) |
| Traffic routing | `mlb-prediction-worker` → `00038-8jz` then `00039-8kr` (required `--to-revisions` due to staging-tagged old revision) |
| Manual scheduler trigger | `mlb-bp-props-pregame` to test the fixed Phase 2 path |
| Manual API call | `/predict-batch` triggered 5 times (CAUSED PREDICTION DUPLICATION — see warnings) |
| Manual API call | `/best-bets` triggered 2 times |

---

## Current System State (2026-04-10 ~01:25 UTC)

### MLB Pipeline — FIRST WORKING DAY since 2025

| Table | Status | Notes |
|---|---|---|
| `mlb_raw.bp_pitcher_props` | 9 rows for 2026-04-09 | Was 0 YTD. Fix verified. |
| `mlb_raw.oddsa_pitcher_props` | 1417 rows for 2026-04-09 | Was already working since S517 |
| `mlb_predictions.pitcher_strikeouts` | **1500 rows for 2026-04-09** | DUPLICATION — should be ~300. 5 manual retriggers. |
| `mlb_predictions.signal_best_bets_picks` | **EMPTY for 2026-04-09** | game_pk insert error |
| `mlb_predictions.best_bets_filter_audit` | Has filter reasons | Confirms 8 picks reached filter stage |

### Today's actual picks (from `pitcher_strikeouts`)

| Pitcher | Recommendation | Edge | Predicted | Line | Filter outcome |
|---|---|---|---|---|---|
| max_meyer | OVER | **1.20** | 6.7 | 5.5 | Blocked by `away_edge_floor` (is_home NULL → defaulted away, needs 1.25+) |
| jeffrey_springs | OVER | **0.82** | 5.32 | 4.5 | **PASSED — would persist as best bet but game_pk error** |
| eduardo_rodriguez | OVER | 0.56 | 5.06 | 4.5 | Blocked by `edge_floor` (< 0.75) |
| nolan_mclean | OVER | 0.27 | 5.77 | 5.5 | Blocked by `edge_floor` |
| jack_flaherty | SKIP | — | 6.13 | 5.5 | Red flag (bullpen/IL/etc.) |
| mick_abel | SKIP | — | 5.32 | 4.5 | Red flag |
| ryan_weathers | SKIP | — | 5.88 | 5.5 | Red flag |
| seth_lugo | SKIP | — | 5.03 | 4.5 | Red flag |

### NBA Pipeline
- Same as Session 517 — auto-halt active, all 4 enabled models BLOCKED
- 7d: 2-0 (100%, only 2 picks!), 14d: 2-2 (50%), 30d: 9-5 (64.3%)
- Vegas MAE 5.18-5.59, MAE gap 0.83-0.92 (model behind Vegas)
- Reg season ends ~Apr 13 (4 days)
- Schedule: Apr 10 (15), Apr 12 (15), Apr 14 (2), Apr 15 (2). Apr 11/13 = no games.
- Monday Apr 7 retrain BLOCKED by governance (UNDER HR 50.91% < 52.4%)

### Session 516 fixes — ALL HOLDING ✓
- Traffic routing across 21 services: all routing to latest
- Phase 3 amplification loop: zero republishes
- nba-phase2-raw-processors cleanup: zero republishes
- prediction-coordinator timedelta errors: zero

---

## Outstanding Punch List (8 items, prioritized)

| # | Item | File:line | Severity | Est | Notes |
|---|---|---|---|---|---|
| 1 | `game_pk` required, pick dict has `game_id` | `ml/signals/mlb/best_bets_exporter.py:1029` | **BLOCKER** | 5 min code + 15 min deploy | Agent 1 verified fix recipe (see START HERE #2) |
| 2 | `is_home` is **100% NULL** on `pitcher_strikeouts` (2101/2101 rows since 2026-04-07) | `predictions/mlb/pitcher_loader.py` (request dict around line 122) | **High** | 30 min | Affects `away_edge_floor` gating. max_meyer 1.2 wrongly blocked. Investigate why `pgs.is_home` is NULL for upcoming games — may need probable pitcher join. |
| 3 | `supplemental_loader.py` `total_line` SQL error (column is `total_runs`) | `predictions/mlb/supplemental_loader.py` | Warning only | 10 min | Trivial; clears log noise |
| 4 | 292 spurious BLOCKED rows per worker run (loader scope) | `predictions/mlb/pitcher_loader.py:508` | Cosmetic | 15 min | Agent 1's P0.1: add `AND (oddsa.player_lookup IS NOT NULL OR bp.player_lookup IS NOT NULL)` to outer WHERE. Doesn't affect picks. |
| 5 | Staging-tagged revision pinning `mlb-prediction-worker` traffic | Cloud Run config | Operational | 30 min | Find why a `staging` tag exists on `00005-gon`. Remove or reroute. Every deploy currently needs explicit `--to-revisions`. |
| 6 | `scraper-gap-backfiller` pinned to broken Feb 5 revision | `orchestration/cloud_functions/scraper_gap_backfiller/requirements.txt` likely missing pyyaml/pytz | **P1 — silent for 2 months** | 60 min | Investigate startup failure FIRST. Don't push 00005 blindly. Check if `config/scraper_parameters.yaml` is in source zip. |
| 7 | `validation-runner` deployment drift (`12b9f65` vs `main`) | Cloud Build trigger config | P1 | 15 min | From Session 516. Check `gcloud builds triggers describe deploy-validation-runner`. |
| 8 | `parameter_resolver.py:447` returns `{'date': ...}` instead of `{'gamedate': ...}` | `orchestration/parameter_resolver.py:447` | P1 | 5 min code + redeploy gap-backfiller (which depends on #6) | Agent 2's diagnosis. Proper fix for orphan-failure pattern that today's BQ UPDATE just bandaided. |

---

## NEW HIGH-SEVERITY FINDINGS (Late Session, From Risk Agent)

### Finding 1: Prediction duplication (HIGH)

**Evidence:**
```sql
SELECT game_date, COUNT(*) FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-04-06' GROUP BY 1;
-- 2026-04-06: ~300
-- 2026-04-07: ~300
-- 2026-04-08: ~300
-- 2026-04-09: 1500   ← 5x duplication
```

**Cause:** Every manual `/predict-batch` call writes 300 new rows (one per pitcher in the loader scope, including 292 spurious BLOCKED). No `(game_date, pitcher_lookup, system_id)` unique constraint. We triggered `/predict-batch` 5 times today during debugging.

**What breaks:** Grading double-counts, accuracy views inflate, downstream `model_performance_daily` exposure. Tonight's 17:00 UTC cron will add another 300.

**Mitigation for Session 519:**
```sql
-- Delete duplicates, keep most recent per (game_date, pitcher_lookup, system_id)
DELETE FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = '2026-04-09'
  AND prediction_id NOT IN (
    SELECT prediction_id FROM (
      SELECT prediction_id, ROW_NUMBER() OVER (
        PARTITION BY game_date, pitcher_lookup, system_id
        ORDER BY created_at DESC
      ) AS rn
      FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
      WHERE game_date = '2026-04-09'
    ) WHERE rn = 1
  );
```

### Finding 2: `is_home` is structurally NULL (HIGH)

**Evidence:**
```sql
SELECT COUNTIF(is_home IS NULL), COUNT(*)
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-04-07';
-- 2101, 2101  → 100% NULL
```

**Cause:** Not yet root-caused. Either `pgs.is_home` is NULL for upcoming games, or it's lost in the request dict construction at `pitcher_loader.py:116-136`, or the predictor doesn't pass it through. Needs investigation in S519.

**Impact:** Exporter at `best_bets_exporter.py:412-415` does `is_away = (is_home is not None and not bool(is_home))`. When NULL, `is_away = False` → away picks evaluated as HOME → 0.75 K floor instead of 1.25 K. In OPPOSITE direction, this means home picks (which might benefit from the more lenient floor) get the away gating somehow.

The exporter has a `features.get('is_home')` fallback that partially works — filter audit shows 1 `away_edge_floor BLOCKED`, so the fallback does fire for some picks. But coverage is incomplete.

### Finding 3: 32 unbackfilled `scraper_failures` waiting (MEDIUM-HIGH)

**Evidence:**
```sql
SELECT scraper_name, COUNT(*) AS failures, MAX(retry_count) AS max_retries
FROM nba_orchestration.scraper_failures
WHERE backfilled = FALSE
GROUP BY scraper_name ORDER BY failures DESC;
-- bdb_pbp_scraper: 25 failures, max retry 181
-- nbac_play_by_play: 4 failures
-- ... 32 total
```

**`bdb_pbp_scraper` is NOT in `parameter_resolver.complex_resolvers`** (only `bigdataball_pbp` is registered at line 94 of parameter_resolver.py). Gap-backfiller will fall through to `_get_default_parameters` → `date=context['execution_date']=TODAY`, call scraper with wrong date. Either marks gap as falsely backfilled OR fails and re-triggers the orphan pattern.

**Mitigation:** Don't redeploy `scraper-gap-backfiller` until #8 (`parameter_resolver.py:447`) is fixed AND `bdb_pbp_scraper` is added to complex_resolvers OR has its failures cleared via SQL.

---

## Session 519 Recommended Sequence

### Phase A — Verification (15 min)
1. `/daily-steering` for any overnight regressions
2. Check `pitcher_strikeouts` count for 2026-04-09 (did 17:00 UTC cron add another 300?)
3. Check `signal_best_bets_picks` for 2026-04-09 AND 2026-04-10
4. Check `scraper_failures` for new rows since 2026-04-09

### Phase B — Manual recovery (10 min)
5. Manual SQL backfill jeffrey_springs (recipe in START HERE #1)
6. Cleanup query to dedupe pitcher_strikeouts for 2026-04-09 (recipe in Finding 1)

### Phase C — Surgical game_pk fix (20 min)
7. Apply Agent 1's one-line fix to `best_bets_exporter.py:1029`
8. Commit, push, wait for build, route traffic with `--to-revisions`
9. Trigger `/best-bets` ONCE for 2026-04-10. **DO NOT trigger /predict-batch.**
10. Verify signal_best_bets_picks has rows for 2026-04-10

### Phase D — Systematic schema audit (60 min) — DO NOT SKIP
11. Read `ml/signals/mlb/best_bets_exporter.py` end-to-end (1059 lines)
12. Read `predictions/mlb/pitcher_loader.py` end-to-end
13. Query INFORMATION_SCHEMA for `signal_best_bets_picks`
14. Build a schema-drift table (pick dict key → BQ column → status)
15. Identify ALL mismatches, then fix in ONE commit

### Phase E — `is_home` investigation (30 min)
16. Trace `pgs.is_home` source — is it NULL upstream or lost in pitcher_loader?
17. Decide: fix in pgs ETL, or in feature loader, or default heuristically
18. Verify with max_meyer (today's edge 1.2 likely-home pick) — once is_home is set, he should become a 2nd best bet for 2026-04-09

### Phase F — Punch list (rest of session)
19. #3 supplemental_loader (10 min trivial)
20. #4 loader scope cleanup (15 min, removes 292 spurious BLOCKED)
21. #5 staging-tagged revision investigation (30 min)
22. #6 scraper-gap-backfiller proper fix — investigate startup failure FIRST
23. #7 validation-runner drift fix
24. #8 parameter_resolver.py:447 fix (after #6 unblocks)

---

## Memory Updates Recommended

Add these patterns to `MEMORY.md`:

### Pattern: silent data loss via Phase 2 router gaps
When `bp_*`/`oddsa_*` BQ tables stop updating, FIRST check Phase 2 file router registry (`data_processors/raw/main_processor_service.py` PROCESSOR_REGISTRY) before blaming upstream API. Sessions 515 and 517 chased BettingPros API outage for 3 months when the actual bug was a missing dict entry. The processor existed, the docstring said it supported live data, but the registry entry was never added.

### Pattern: player_lookup format mismatch
- `bp_pitcher_props.player_lookup`: `anthonykay` (no separator)
- `oddsa_pitcher_props.player_lookup`: `anthonykay` (no separator)
- `pitcher_game_summary.player_lookup`: `anthony_kay` (underscore)
- Always `REPLACE(pgs.player_lookup, '_', '') = bp.player_lookup` (or oddsa) in JOINs
- Training script uses NORMALIZE+REGEXP for accents; production loader uses simpler REPLACE — may miss accented names

### Pattern: deploy assumption failures
Session 516 found 21 services not routing to latest. Session 518 found:
- `mlb-phase2-raw-processors` shares NBA image but has no auto-deploy trigger → manual `--image=...` after every NBA Phase 2 build
- `mlb-prediction-worker` has a `staging` tag pinning revision `00005-gon`, causing `--to-latest` to silently fail. ALWAYS use `--to-revisions=NEW_REV=100`
- `scraper-gap-backfiller` Cloud Function pinned to Jan 24 revision; revisions 00003 (Jan 30) and 00004 (Feb 5) failed `HealthCheckContainerError` on container startup. Cloud Run silently kept old revision while reporting `latestRevision: true, percent: 100` (lying)

**Always verify revision routing after deploy, not just build status.**

### Pattern: MlbBpHistoricalPropsProcessor + best_bets_exporter is unshipped code
Created Jan 2026 for backfill (manual `load_to_bigquery.py` runs). Annotated as live-capable but never tested end-to-end. Session 518 found 4 distinct schema/data flow bugs in this path:
1. Phase 2 router missing entry
2. bp JOIN format mismatch
3. confidence_score NUMERIC overflow
4. game_pk required field missing
There are likely MORE. Approach S519 with systematic schema audit, not iterative patching.

### MLB dynamics (catboost_v2_regressor)
- Worker writes to `mlb_predictions.pitcher_strikeouts` (NOT the deprecated `pitcher_strikeout_predictions` table)
- system_id = 'catboost_v2_regressor'
- Confidence values are 5-20+ (regressor raw output, not probability)
- Edges of 0.27-1.20 K are normal for opening week. Best bets threshold: home 0.75 K, away 1.25 K.
- Default red flags skip 4-5 pitchers/day for bullpen/IL/insufficient data
- Today's 4 OVER picks and 4 SKIPs = 8 of ~10 starters covered (others lack rolling stats >= 3)

---

## Files Changed

| Purpose | File |
|---|---|
| Phase 2 router registry | `data_processors/raw/main_processor_service.py` |
| Phase 2 router export | `data_processors/raw/mlb/__init__.py` |
| BP JOIN format | `predictions/mlb/pitcher_loader.py` |
| confidence_score clamp | `ml/signals/mlb/best_bets_exporter.py` |

## Infrastructure Operations

| Op | Detail |
|---|---|
| BQ UPDATE | `nba_orchestration.scraper_failures` cleared orphan `nbac_player_boxscore` 2026-04-08 (1 row) |
| Manual deploy | `mlb-phase2-raw-processors` → revision `00006-pwz` |
| Traffic routing | `mlb-prediction-worker` → `00038-8jz` then `00039-8kr` (via `--to-revisions`) |
| Manual scheduler trigger | `mlb-bp-props-pregame` |
| Auto-deploys triggered by 4 commits | `deploy-nba-phase2-raw-processors`, `deploy-mlb-prediction-worker` (2x), `deploy-prediction-worker`, `deploy-prediction-coordinator`, `deploy-post-grading-export`, `deploy-live-export`, `deploy-phase6-export` |

---

## 4-Agent Strategic Review Synthesis (For Context)

When deciding whether to push through tonight or stop, 4 agents reviewed the situation in parallel. Findings:

1. **Tactical (push-through):** Found surgical 1-line `game_pk` fix path. Argued for 30-min push to close end-to-end.
2. **Strategic (stop now):** Argued the 5-bug pattern indicates unshipped code path. Iterative patching at hour 5+ has high regression risk. Manual SQL backfill tomorrow is trivial. Stop digging.
3. **Risk (production safety):** Found 3 NEW high-severity issues (prediction duplication, is_home NULL, 32 unbackfilled scraper_failures). Recommended stop + monitoring.
4. **Tomorrow planner:** Built the systematic Session 519 plan (Phase A-F above).

User's call: stop and write handoff. This document.

The session achieved its biggest possible win — finding the actual MLB pipeline root cause that 2 prior sessions missed. The persistence-layer bugs are well-understood, well-documented, and ready for systematic fix tomorrow.
