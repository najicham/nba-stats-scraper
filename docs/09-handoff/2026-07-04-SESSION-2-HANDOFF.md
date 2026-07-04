# Session Handoff — 2026-07-04 (Session 2, off-season execution)

**Branch:** `main` (all work committed + pushed). **System state:** OFF-SEASON, halted;
opening night provisional ~Oct 21, 2026. Nothing here changes live pick behavior — exports are
halted, so every writer/registry/view change takes effect at season resume.

## What this session was

Executed the entire **ranked worklist** from the 2026-07-04 (Session 1) handoff — all 4 items.
Continues `docs/09-handoff/2026-07-04-session-handoff.md`.

## Commits shipped (4, all on `main`, pushed → auto-deploy triggered)

| Commit | Item | What |
|--------|------|------|
| `f51742b7` | #1 | Repair pipeline-canary image (bin/monitoring stripped by .gcloudignore) |
| `19ecbc16` | #2 (C1) | Unconditional shadow-tag persistence + `v_bb_candidate_signal_stream` view |
| `aba36777` | #3 | Green ~111 stale unit tests (pool-cache isolation + fixture drift) |
| `74d014b5` | #4 (C3) | Pre-registered two-tier promotion gates (measurement-infra) |

### #1 — Canary image fix + `.gcloudignore` audit (`f51742b7`)
- **Root cause confirmed:** `nba-pipeline-canary` job died every run with `can't open file
  '/app/bin/monitoring/pipeline_canary_queries.py'` — repo-root `.gcloudignore:2` (`bin/`) strips
  bin/ from `gcloud builds submit` contexts.
- **Key finding (carry forward):** a `!bin/monitoring/` negation does **NOT** work here — gcloud's
  git-mode `list-files-for-upload` silently drops `!` re-includes under an excluded dir (verified;
  the same negation works in a plain filesystem-walk fixture). So the durable fix is to build these
  monitoring images with a **local `docker build`** (reads the real FS, ignores .gcloudignore).
- Rebuilt + pushed `pipeline-canary:latest` via local docker; job now RUNS its checks (off-season it
  EXIT 1s on empty-data — 0 picks/0 predictions/missing models — which is correct, not an image
  defect). Added `bin/monitoring/rebuild_canary_image.sh` documenting the path.
- **Audit result:** only the canary was broken. Sibling images that also `COPY bin/monitoring/`
  (`nba-deployment-drift-alerter`, `nba-auto-batch-cleanup`) are HEALTHY — built via local docker.
  Both canary triggers left **PAUSED** (verified).
- Note: `processing-gap-monitor` (last exec FAILED 2025-10, stale) and `nba-q43-performance-monitor`
  (FAILED today, doesn't COPY bin/monitoring) are separate/off-season-expected — NOT this class.

### #2 — C1 shadow-tag persistence + signal-stream view (`19ecbc16`)
- `ml/signals/aggregator.py` (metadata-only, ~10 lines): `_record_filtered` now falls back to the
  full qualifying-signal tag list (from `signal_results`) when a caller passes no `sig_tags` — the
  ~40 pre-signal-stage call sites, which dropped tags on ~68% of filtered rows. **Byte-identical
  serve path:** the aggregator suite is 98 pass / 32 pre-existing-fail with AND without the edit.
- New view `nba_predictions.v_bb_candidate_signal_stream` (created live; read-only over halted
  tables). Replay on 2026-03-25: grain-unique, 85.7%/90.9% graded, dedup priority verified.
- **Gotcha:** the view needs a **static `game_date` predicate** (`signal_best_bets_picks` has
  require_partition_filter) — the C4 tracker's date-range queries satisfy this; a subquery-derived
  date does not. The `merge_rejected` leg is sparse until C2's fixed writer runs live at season open.
- Tests: `tests/unit/signals/test_c1_shadow_tag_persistence.py` (7 pass).

### #3 — Scoped test-greening (`aba36777`)
- **Root-cause fix (biggest lever):** `shared.clients.bigquery_pool._client_cache` is a
  process-global client cache. The first exporter test cached its mock; every later test reused the
  stale client → empty results → failure. Added an **autouse fixture in `tests/unit/conftest.py`**
  that clears the BQ-pool + champion caches before each test. **This alone fixed 94 publishing
  failures** (safe: real code re-creates the client on next call).
- Genuinely-stale updates: `test_best_bets_exporter.py` (26 green — TIER_CONFIG is edge-based now;
  `_safe_float`→module `safe_float`), `test_player_blacklist.py` (green — stale OVER/edge-5 fixtures
  → UNDER/star-line; deleted 2 tests for the removed `familiar_matchup` S494), `test_health_aware_weights.py`
  (green), 2 brittle `ALGORITHM_VERSION` pins → durable `^v\d+`.
- **Net: publishing 147→47 failed, signals 42→31 failed (~111 resolved).** Remaining = bespoke
  per-exporter fixture drift + `test_aggregator.py` stale-filter tail (genuinely multi-session; NOT a
  gate per the plan). **Next session: continue this tail if desired — each failing exporter needs its
  mock fixtures re-fit to the current query/transform contract.**

### #4 — C3 pre-registered two-tier promotion gates (`74d014b5`)
- `docs/08-projects/current/measurement-infrastructure/PREREG-promotion-gates-2026-27.md` — the
  authoritative pre-registration (git commit = timestamp): two-tier design, Class-A/Class-B
  block-class stratification (**default B**), power-honesty note (gates resolve only ≥+6pp effects),
  and the six gates verbatim.
- Structured `promotion:` blocks on 4 signals + 2 filters in `shared/registry/{signals,filters}.yaml`
  (machine-readable for the C4 tracker; loader ignores the extra key — verified). Added top-level
  `stream_block_class` (22 Class-A tags; everything else B) that C4 reads to build Tier-1.
- Tests: `test_promotion_gates_prereg.py` (7 pass) — locks structure + prevents the two gated
  filters from leaking into Class-A (which would bias the measurement).

## Next worklist (for the taking-over session)

1. **Finish the test-greening tail** (multi-session): remaining ~47 publishing + ~31 signals
   (`test_aggregator.py`) failures are bespoke fixture drift — re-fit each exporter's mock fixtures to
   the current contract; update `test_aggregator.py` stale-filter assertions (renamed/removed/demoted
   filters). The high-leverage pool-cache fix is already in; what's left is per-file.
2. **C4 — promotion tracker** + **C5 — paper-stakes** (measurement-infra Components 4 & 5, Sept
   slack per the plan; not July-critical). C4 reads `v_bb_candidate_signal_stream` + the registry
   `promotion:` blocks + `stream_block_class`. C5 stamps paper stakes on picks.
3. **October dress-rehearsal checks:** confirm `model_bb_candidates` populates non-NULL context cols
   once C2's fixed writer runs live; confirm the canary greens once the pipeline produces picks (then
   un-pause its triggers per the restore manifest).

## Do NOT (unchanged from Session 1)
Restore/enable weekly-retrain or decay-detection before season open; resume any paused trigger;
attempt a full-suite green as a gate; build a CI test gate; front-load C4/C5; pause master-controller;
backfill lost model_bb_candidates provenance.

## Verification commands
```bash
# canary image now runs (off-season EXIT 1 on empty data is expected/correct):
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait

# C1 view (needs a literal game_date predicate):
bq query --use_legacy_sql=false 'SELECT disposition, COUNT(*) n FROM
  `nba-props-platform.nba_predictions.v_bb_candidate_signal_stream`
  WHERE game_date = "2026-03-25" GROUP BY 1'

# C1 + C3 tests:
.venv/bin/pytest tests/unit/signals/test_c1_shadow_tag_persistence.py tests/unit/signals/test_promotion_gates_prereg.py -q

# registry gates parse + loader unaffected:
.venv/bin/python -c "from shared.registry.loader import load_signal_registry; print(len(load_signal_registry()))"
```

## Key references
- Session 1 handoff: `docs/09-handoff/2026-07-04-session-handoff.md`
- Plan: `docs/09-handoff/2026-07-03-5-adjudicated-plan.md`
- Measurement-infra spec: `docs/08-projects/current/measurement-infrastructure/00-SPEC.md`
- Pre-registration: `docs/08-projects/current/measurement-infrastructure/PREREG-promotion-gates-2026-27.md`
- Canary rebuild: `bin/monitoring/rebuild_canary_image.sh`
