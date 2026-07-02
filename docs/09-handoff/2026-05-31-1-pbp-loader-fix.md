# Handoff — PBP Phase 2 loader fix (Task #30-V2, scope-1)

**Date:** 2026-05-31 · **Type:** session close-out / next-session brief
**Prior handoff:** `2026-05-30-1-tasks-shipped-and-pbp-discovery.md` (discovered loader broken since 2025-11-02; deferred to this session)
**Commits this session:** `86c7dc15`
**Tasks shipped:** Task #30-V2 *partial* — loader code fix + prod verification. Bulk backfill of 184 days deferred to next session.
**Tasks remaining from prior audit:** #25, #26, #30 (backfill phase), #33, #34 (3 hooks), #35–#40

---

## 0. Orientation — read this first

The prior session discovered `nba_raw.nbac_play_by_play` had been silently dropping every load since 2025-11-02 (whole 2025-26 season, 184 days, 1,299 games), with GCS holding every file. This session diagnosed the root cause, shipped a one-line fix, verified it in prod, and stopped before the bulk backfill — which is its own session.

**What the fix does NOT do:** it does not retroactively load the 184 days of missing PBP data. Going forward, any new PBP write succeeds. Old data still needs a re-trigger from GCS to BQ.

---

## 1. What landed

| Commit | Subject |
|---|---|
| `86c7dc15` | `fix(nba): pbp processor reads file_path from opts (loader broken since 2025-11-02)` |

Auto-deployed via Cloud Build `7ed1e5e0-cbca-4f67-a554-3b2981e6c3d8` → revision `nba-phase2-raw-processors-00305-zhs`, 100% traffic.

### Code change

`data_processors/raw/nbacom/nbac_play_by_play_processor.py:281` — was:

```python
file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
```

Now reads `self.opts['file_path']` (set by `FileProcessor` at `handlers/file_processor.py:101`) first, falls back to the old `metadata.source_file` lookup for safety.

### Verification

| Test | Game | Result |
|---|---|---|
| Local invocation | `2026-04-15/game-0052500101/...json` | `rows_processed: 562` (was 0) |
| Prod Pub/Sub trigger | `2026-04-17/game-0052500201/...json` | `rows_processed: 634` |

Both games now in `nba_raw.nbac_play_by_play` partitioned correctly.

---

## 2. The root-cause story

**Trigger:** commit `fc80e130` (2025-11-19, "pub sub entity documentation") ran `bin/maintenance/fix_processor_signatures.py` to mass-refactor 17 processors' `transform_data(self, raw_data, file_path)` → `transform_data(self)`. For each, the script inserted `file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')` as the new file-path source.

**Why only PBP broke severely** (other 16 share the same buggy pattern):
1. `nbac_play_by_play` scraper never wrote `metadata.source_file` into its JSON (confirmed: keys are `game_id, season, fetchedUtc, eventCount` only).
2. The PBP processor's `game_date` extraction is the ONLY source — derived from the `YYYY-MM-DD` segment of the path.
3. `nba_raw.nbac_play_by_play` has `requirePartitionFilter=TRUE` on partition column `game_date`.

With `file_path='unknown'`: regex fails → `game_date_str=None` → every row gets `game_date=None` → the parameterized `DELETE ... WHERE game_id = @id AND game_date = @date` runs with `game_date=NULL`, which BigQuery does not accept as enabling partition elimination → 400 "Cannot query over table without a filter ... that can be used for partition elimination."

**Silent failure path:** the error was caught at line 661 of the processor, raised at line 680, re-caught at line 711, logged, rate-limited as a notification, set `stats['rows_inserted'] = 0`, returned cleanly. `processor.run()` reported success.

**Other 16 affected processors are NOT confirmed broken** because most extract `game_date` from JSON content, not the file path. Spot check from `nba_raw.__TABLES__`:

| Table | Last modified | State |
|---|---|---|
| `nbac_play_by_play` | 2026-05-31 (fix today) | was broken, now fixed |
| `nbac_gamebook_player_stats` | 2026-05-31 | healthy |
| `nbac_injury_report` | 2026-05-31 | healthy |
| `nbac_team_boxscore` | 2026-04-27 | stale, but off-season |
| Others | varies | off-season stale; unverified |

A full audit of the other 16 is a follow-up task — none look severely broken but it should be ruled out before next season.

---

## 3. Bystander observation (not part of fix scope)

Prod log from the verification trigger also showed:

```
ERROR:data_processors.raw.handlers.file_processor:Failed to extract opts from path: nba-com/play-by-play/2026-04-17/game-0052500201/20260418_080544.json
ValueError: No extractor found for path: nba-com/play-by-play/2026-04-17/game-0052500201/20260418_080544.json
```

The PBP path has no registration in `data_processors/raw/path_extractors/registry.py`. `FileProcessor` catches this and falls back to empty opts; my fix still works because `opts['file_path']` is set unconditionally at line 101 after the extract attempt. So PBP has a *separate* missing-registration bug that doesn't bite. Worth a separate cleanup pass on `path_extractors/registry.py` — confirm what callers depend on extracted opts vs. just `file_path`.

---

## 4. Bulk backfill — design hooks for next session

The 184-day catch-up was deliberately NOT executed this session.

**Scope (per prior handoff):**
- 184 days × ~7 games/day ≈ 1,299 games × ~600 events = ~780K BQ rows
- Each game is one GCS file; processor takes ~10–18s per game
- Total wall-clock at 1 worker: ~4 hours; with concurrency easily ~30 min
- Phase 3 re-run for ~13K player-games downstream is hours of Cloud Run compute

**Recommended approach:**
1. **List target files:** `gsutil ls -r "gs://nba-scraped-data/nba-com/play-by-play/2025-11-*" "gs://nba-scraped-data/nba-com/play-by-play/2026-*"` → flatten to one file per game (each `game-*` dir has exactly one `YYYYMMDD_HHMMSS.json`).
2. **Trigger mechanism:** re-publish Unified V2 messages to `nba-phase1-scrapers-complete` (the same approach used for the prod verification). Sample message that worked:
   ```json
   {"processor_name":"nbac_play_by_play","phase":"phase_1_scrapers","status":"success",
    "metadata":{"gcs_path":"gs://nba-scraped-data/nba-com/play-by-play/<DATE>/game-<ID>/<file>.json","record_count":0}}
   ```
3. **Batch carefully:** publishing all 1,299 at once will spin up many Phase 2 instances. Throttle to e.g. 20 messages/sec.
4. **Idempotency:** the processor uses `MERGE_UPDATE` (DELETE-then-INSERT keyed on `game_id + game_date`). Safe to re-publish; will just overwrite.
5. **Phase 3 re-run:** Phase 2 → Phase 3 trigger is auto via `nba-phase2-raw-complete` topic. Phase 3 will re-run for each game. PBP-dependent Phase 3 processors (shot zones, paint/mid_range/assisted_fg/and1 in player_game_summary) will populate.
6. **Don't trigger during off-season halt windows** — system is currently halted, so this is a safe time to backfill; no risk of polluting today's predictions.

**Cost ceiling:** GCS reads ~$5; BQ inserts <$10; Cloud Run compute ~$15-30. Total ≪ $50.

**Watch for:** the bystander path-extractor error (Section 3) will fire 1,299 times in logs. Cosmetic, but consider filing a follow-up to register PBP in `path_extractors/registry.py` before the bulk run.

---

## 5. Current operational state

### Halt state (unchanged)

| Sport | `halt_active` | `halt_reason` |
|---|---|---|
| NBA | true | `predictions_inactive` (off-season) |
| MLB | true | `pick_drought` (concluded as no-edge 2026-05-22) |

### nba_raw.nbac_play_by_play

| Metric | Value |
|---|---|
| Total rows | 1,043 (pre-fix) + 1,196 (this session's two test games) = 2,239 |
| Earliest 2025-26 game in table | 2026-04-15 (the local-test game) |
| 2025-11-02 → 2026-04-26 coverage | still ~0% (1,297 games still need backfill) |

---

## 6. The 15-task scoreboard (unchanged except #30-V2 partial)

### DONE this session

| # | Task | Commit | Effort actual |
|---|---|---|---|
| **30-V2 (loader fix)** | Diagnose + fix PBP processor `file_path` extraction | `86c7dc15` | S (diagnosis was M, fix was XS) |

### Carry-forward

| # | Task | Effort | Notes |
|---|---|---|---|
| **25** | BDB stuck-date investigation | — | DEFERRED |
| **26** | Fix 17 stale-API schedulers (v1 → v2) | M | |
| **30 (bulk)** | Backfill 184 days of PBP GCS → BQ → Phase 3 | **M (was L)** | Loader fix done. Bulk run is mechanical now. See Section 4. |
| **33** | Vegas line feature quality regression (f25/26/27/50) | M | |
| **34 (3 hooks)** | wire partition_filters, code_quality, all_schemas | S→M | |
| **35** | Delete 7 dead CFs + 12 orphan source dirs | S | |
| **36** | Fix MLB schedulers running year-round | M | |
| **37** | Remove `roles/editor` from `756957797294-compute` SA | M | |
| **38** | Audit + cleanup dead signals/filters | M | |
| **39** | `model_bb_candidates` writer — emit all 45 cols | S | |
| **40** | Regenerate `prediction_accuracy` + `model_bb_candidates` schema files | S | |

### New tasks discovered this session

| # | Task | Effort | Notes |
|---|---|---|---|
| **41** | Audit the other 16 processors touched by `fc80e130` for the same `metadata.source_file` bug | S | None confirmed broken, but rule it out before next NBA season |
| **42** | Register `nba-com/play-by-play` in `data_processors/raw/path_extractors/registry.py` | XS | Bystander finding (Section 3); will fire 1,299 times during backfill |

### Suggested next-session priorities

1. **Task #30 (bulk backfill)** — the loader works; this is mechanical. Best done during off-season (i.e. now).
2. **Task #42** — quick cleanup before bulk backfill to keep logs tidy.
3. **Task #41** — audit the other 16. Low likelihood of breakage but cheap to verify.

---

## 7. Verification commands (60-second smoke tests)

```bash
# Latest commit pushed + deployed
git log --oneline -3
# Expected: 86c7dc15 fix(nba) ... — then 0924f6c0, 25d74cce (prior handoff)

gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 --project=nba-props-platform \
  --format='value(status.latestReadyRevisionName,status.traffic[0].revisionName)'
# Expected: both fields = nba-phase2-raw-processors-00305-zhs (or higher)

# Verify the two test games landed
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT game_id, game_date, COUNT(*) AS events
   FROM `nba-props-platform.nba_raw.nbac_play_by_play`
   WHERE game_date IN (DATE "2026-04-15", DATE "2026-04-17")
   GROUP BY 1, 2 ORDER BY 2, 1'
# Expected:
#   20260415_ORL_PHI  2026-04-15  562
#   20260417_CHA_ORL  2026-04-17  634

# Confirm the rest of the season is still empty (bulk backfill not done)
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT COUNT(DISTINCT game_date) AS days_with_data
   FROM `nba-props-platform.nba_raw.nbac_play_by_play`
   WHERE game_date >= "2025-11-02" AND game_date <= "2026-04-26"'
# Expected: 2 (just the two test games from this session)

# Confirm code change is deployed
PYTHONPATH=. .venv/bin/python3 -c "
import inspect
from data_processors.raw.nbacom.nbac_play_by_play_processor import NbacPlayByPlayProcessor
src = inspect.getsource(NbacPlayByPlayProcessor.transform_data)
assert 'self.opts.get(\"file_path\")' in src or \"self.opts.get('file_path')\" in src
print('OK: fix present in local source')"
```

---

## 8. Memory file updates needed (next session may want to apply)

Suggested but NOT done this session (to keep blast radius small):

- **New memory file:** `pbp-loader-broken-since-nov.md` capturing the full diagnosis (fc80e130 mass-refactor, the 16 sibling processors, partition-filter interaction, silent-success failure mode). Worth ~50 lines.
- **MEMORY.md update:** the "Active Operational State" bullet currently warns "PBP loader broken season-wide ... 1,299 games. Fix BEFORE Oct 2026 season start." Update to: "Loader fixed 2026-05-31 commit `86c7dc15`. Bulk backfill of 1,297 historical games still pending — see [[pbp-loader-broken-since-nov]]."
- **CLAUDE.md Common Issues table:** add a row for the silent-success failure pattern from partition-filter rejection — generalizes beyond PBP.

---

## 9. Out of scope (kept out, still out)

- **Bulk backfill of 184 days** — separate session.
- **Audit of other 16 processors** sharing the buggy pattern (Task #41).
- **Path extractor registration** for `nba-com/play-by-play` (Task #42).
- **Working tree mess** (1,276+ dirty files) — none touched.
- **Re-Phase-3 for affected player-games** — automatic once backfill triggers Phase 2 completion events; nothing to do manually.

---

**End of handoff.** Next session: pick up Task #30 (bulk backfill) using the design in Section 4. The loader works; the rest is mechanical.
