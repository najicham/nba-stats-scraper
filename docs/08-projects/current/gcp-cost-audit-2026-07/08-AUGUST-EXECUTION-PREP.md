# 08 — August §4 Execution Prep (turnkey diffs)

**Date:** 2026-07-24 (Session 7)
**Purpose:** Turn `06-PLAN.md §4` from "scoped" into "mechanical apply." Every item below was re-verified from source this session (working agent runtime) with exact before/after diffs, caller-impact audits, deploy paths, and — where the plan flagged an unknown — the resolution. **Nothing here is applied.** This is the reference the August executor (or an approved same-session push) works from.

**Global note:** all these defects are **dormant off-season** — no predictions run, no picks publish. None is live-urgent; they bite at season open. That is why they batch here rather than forcing an off-season deploy.

**Readiness legend:** 🟢 turnkey (exact diff, low risk) · 🟡 turnkey but coordinated (multi-file, order matters) · 🟠 needs one more decision/fix before apply.

> **Reviewed by 2 Fable agents (Session 7, 2026-07-24) — this doc reflects their corrections.** They caught **two real regressions** in the first-pass diffs, both verified from source: §4.4 would have introduced a **poison-pill** (retaining schema-invalid rows blocks a table's writes) — now conditional retention; §4.5 would have **halved the retry budget** by double-incrementing a counter the auto-retry CF already owns — now no increment in `queue_for_retry`. Plus: §4.10 version premise stale (current is `v2_54features`); §4.1 has two sibling fail-opens (`quality_gate.py:216`, `training_data_loader.py:47`); §4.2's "port from MLB" premise is stale (source file gone, exporters already call `halt_envelope`); §4.9 needs a cleanup checklist. **Do NOT apply the pre-correction diffs.** Adversarial review before applying is exactly why these are still docs, not commits.

---

## §4.3 — worker logging typo 🟢 (15 min, zero behavioral risk)

`predictions/worker/worker.py:2467`. `type(e, exc_info=True).__name__` raises `TypeError` *inside* the except handler → the original staging-write error is never logged, the metric never emits, and `return False` (which triggers the Pub/Sub retry) never runs → prediction-write failures are silently dropped. Adjacent `:2477` already uses the correct form. The fix strictly improves behavior (nothing currently works could break).

**BEFORE**
```python
        logger.error(
            f"STAGING WRITE EXCEPTION for {player_lookup}: {type(e, exc_info=True).__name__}: {e} "
            f"(batch={batch_id}) - will trigger Pub/Sub retry"
        )
```
**AFTER**
```python
        logger.error(
            f"STAGING WRITE EXCEPTION for {player_lookup}: {type(e).__name__}: {e} "
            f"(batch={batch_id}) - will trigger Pub/Sub retry",
            exc_info=True,
        )
```
**Deploy:** `prediction-worker` (auto-deploy on push).

---

## §4.10 — feature_version non-determinism 🟢 (1 line)

`predictions/worker/data_loaders.py:159-164`. `SELECT DISTINCT feature_version … WHERE game_date=@d LIMIT 1` has **no `ORDER BY`**, while the docstring (`:145-152`) claims "tries v2_39features first (newer), falls back to v2_37features." On a two-version date it picks non-deterministically → train/serve skew. Version strings are `'v2_39features'`/`'v2_37features'` (differ only in `39` vs `37`), so lexical DESC = newer-first, matching the docstring. No inversion risk.

**BEFORE**
```sql
        SELECT DISTINCT feature_version
        FROM `{self.project_id}.{self.predictions_dataset}.ml_feature_store_v2`
        WHERE game_date = @game_date
        LIMIT 1
```
**AFTER**
```sql
        SELECT DISTINCT feature_version
        FROM `{self.project_id}.{self.predictions_dataset}.ml_feature_store_v2`
        WHERE game_date = @game_date
        ORDER BY feature_version DESC
        LIMIT 1
```
**Deploy:** `prediction-worker` (auto-deploy).

> **Caveat (Fable review):** the current write value is actually **`v2_54features`** (`ml_feature_store_processor.py:93 FEATURE_VERSION`), so the docstring's "v2_39features/v2_37features" is itself stale (there is a newer version). Lexical `DESC` still ranks `54 > 39 > 37` correctly **today**, but it is fragile to digit-width: a future `v2_9features` or `v2_100features` would mis-sort lexically. Add a commit-message caveat; if versions ever vary in width, switch to a numeric parse. Not a blocker now.

---

## §4.1 — zero-tolerance fail-open + the NULL trap 🟢 (the plan's "~1 hour"; verified)

Three coordinated edits. The subtlety: naïvely dropping `or 0` turns a silent fail-open into a hard `TypeError`, because `dict.get(key, default)` returns `None` when the key exists with value `None` (the documented gotcha) → `None > 0` crashes inside the actionable check. The fix must make NULL **block cleanly**.

### (a) Coordinator fail-open → fail-closed — `predictions/coordinator/coordinator.py:1505-1508`
**BEFORE**
```python
        except Exception as e:
            # Non-fatal: If quality gate fails, fall back to publishing all requests
            logger.error(f"QUALITY_GATE: Failed to apply quality gate (publishing all): {e}", exc_info=True)
            viable_requests = requests
```
**AFTER**
```python
        except Exception as e:
            # Fail CLOSED (plan §4.1): if the quality gate errors we cannot prove any
            # player is clean, so publish NOTHING rather than fabricating clean picks.
            logger.error(f"QUALITY_GATE: Failed to apply quality gate (blocking all): {e}", exc_info=True)
            viable_requests = []
```
(The `else: viable_requests = requests` at `:1503-1504` — the normal no-gate path — is intentionally left unchanged.)

### (b) Loader preserves NULL — `predictions/worker/data_loaders.py:1042`
**BEFORE**
```python
                features['required_default_count'] = int(getattr(row, 'required_default_count', 0) or 0)
```
**AFTER**
```python
                # Zero tolerance: preserve a NULL required_default_count as None (do NOT
                # coerce to 0). An unknown count must block downstream, not be cleaned to zero.
                _rdc = getattr(row, 'required_default_count', None)
                features['required_default_count'] = int(_rdc) if _rdc is not None else None
```
(Line 1041 `default_feature_count` stays int-coerced — unchanged.)

### (c) Worker backstop branches on None first — `predictions/worker/worker.py:2077-2080`
**BEFORE**
```python
        required_defaults = features.get('required_default_count', features.get('default_feature_count', 0))
        if is_actionable and required_defaults > 0:
            is_actionable = False
            filter_reason = 'has_default_features'
```
**AFTER**
```python
        # required_default_count is authoritative. Fall back to default_feature_count ONLY
        # when the key is entirely absent (legacy rows) — a present-but-None value must NOT
        # fall through to the default (dict.get returns None when the key exists with None).
        if 'required_default_count' in features:
            required_defaults = features['required_default_count']
        else:
            required_defaults = features.get('default_feature_count')
        # A NULL/None count means quality metadata is missing -> fail CLOSED (block).
        # `is None` is checked first so `None > 0` is never evaluated.
        if is_actionable and (required_defaults is None or required_defaults > 0):
            is_actionable = False
            filter_reason = 'has_default_features'
```

**Readers audited (11 sites):** only `worker.py:2077` would have raised on `None`; it is fixed above. `quality_gate.py:369` has the same latent `.get` shape but reads its own BQ-sourced dict (int-coerced at `:216`), so it won't crash. All other readers assign-only or guard with `pd.notna`/`fillna`/truthy checks. Measured exposure: 44 NULL rows / 40,564 (0.1%).

> **Caveats (Fable review) — two related fail-opens the core diff does NOT close, worth folding in:**
> - **`quality_gate.py:216` also fail-opens on NULL:** it coerces `required_default_count` NULL → `default_feature_count or 0`, so the *quality gate itself* passes a NULL-count player. After this fix the **worker backstop (c) is the SOLE NULL blocker** — so (c) is load-bearing, and hardening `quality_gate.py:216` to treat NULL as blocking is a sensible companion edit (defense-in-depth, matching the zero-tolerance stance).
> - **`shared/ml/training_data_loader.py:47` admits NULL-count rows into TRAINING:** `COALESCE(required_default_count, 0) = 0` lets a row with unknown quality into the training set. Outside the runtime-serving fix, but a real training-data-quality gap — record it as a sibling item.
**Deploy:** `prediction-coordinator` + `prediction-worker` (both auto-deploy).

---

## §4.2 — make halts halt 🟠 (premise PARTLY STALE — re-verify; residual is one fail-closed fix)

Flagged by the Fable strategy review as missing from this doc. On inline check (Session 7) the plan's §4.2 framing has **moved**:
- **The cited source file is gone.** `data_processors/publishing/mlb_best_bets_exporter.py` does not exist — the "port the 8-line MLB `halt_envelope()` block" premise can't be executed as written.
- **Both NBA targets already call `halt_envelope`.** `signal_best_bets_exporter.py` (`:119, :164, :474, :797`) and `best_bets_all_exporter.py` (`:214`) already look up the halt envelope — the "advisory-only, never applied" framing is likely outdated. **Verify** whether they also *empty the `best_bets` array / suppress picks* when `halt_active` (e.g. the zero-pick path at signal `:797`), which is the behavior that actually matters.
- **The genuine residual (matches the plan's second half):** `base_exporter.py`'s query-error `except` path (~`:394-399`) sets `halt_reason='unknown_state'` but **does NOT set `halt_active=True`** — so a halt_state **query failure fail-OPENS**, while the adjacent missing-row path (`:407-413`) correctly fail-CLOSES (`halt_active=True` for dates ≤7 days old). Make the except path match: set `halt_active=True` for recent dates on query error.

**Action:** don't port a nonexistent file. Do a focused read of the two exporters' halt-application logic (confirm picks are suppressed on `halt_active`), then apply the one-spot `base_exporter.py` fail-closed fix. Re-scope §4.2 in `06-PLAN` accordingly. 🟠 because the exporter-suppression verification is still open.

---

## §4.5 — terminate the retry recycle 🟢 (~$30/mo measured; single `shared/` edit)

`shared/utils/pipeline_logger.py` `queue_for_retry()`. The dedup lookup (`:579-586`) matches only `status IN ('pending','retrying')`, so a `failed_permanent` row re-mints a fresh `retry_count=0` row on the next transient failure → infinite recycle. The UPDATE branch (`:603-611`) reads `existing_retry_count` (`:599`) but never uses it and hard-sets `status='pending'` without touching `retry_count`.

**Fix (replaces `:579-621`):** broaden the dedup to `IN ('pending','retrying','failed_permanent')` + `ORDER BY updated_at DESC LIMIT 1` so a terminal row is FOUND (not re-minted as a fresh `retry_count=0` row).

> **⚠️ CORRECTION (Fable adversarial review, verified from source).** Do **NOT** increment `retry_count` inside `queue_for_retry`. `auto_retry_processor/main.py:407` **already** does `retry_count=retry_count + 1` when it flips a row to `'retrying'` (comment `:404`: "will be set back to pending by processor if it fails again"), and its cap at `:367-371` is exact. The lifecycle is: processor-fail → `queue_for_retry` (pending) → CF (retrying, +1) → processor-fail → `queue_for_retry` (pending) → CF (retrying, +1)… **The CF owns the counter.** Adding a second increment in `queue_for_retry` (which dedup-matches the CF's `'retrying'` rows) double-counts → the budget pins after **2** executed retries, not 3.
>
> **Corrected fix:** in the UPDATE branch, leave `retry_count` untouched. If the found row is already `'failed_permanent'` OR `existing_retry_count >= max_retries`: keep it `failed_permanent` with `next_retry_at=NULL` (just refresh `error_message`/`updated_at`) — this stops the recycle at the source. Otherwise set `status='pending'` for the CF to pick up. (Reusing a terminal row is the intended tradeoff: a months-later transient failure on the same key won't auto-retry — acceptable.)
>
> **At apply time:** write the exact AFTER against current source (the full UPDATE branch at `:603-611`, param list included) — the ONLY writer of `retry_count` here must remain the auto-retry CF (`main.py:407`). This is the second spot that regressed in review; verify no other caller increments the field, and confirm with a test that N transient failures pin at exactly `max_retries`, not `max_retries/2`.

**Deploy path (clarified):** the bug is in `shared/`, reached by `data_processors/{raw,analytics,precompute}/*_base.py` + `scrapers/scraper_base.py`. A normal push to main redeploys **nba-phase2-raw-processors, nba-phase3-analytics-processors, nba-phase4-precompute-processors, nba-scrapers** (their triggers watch `shared/`). **NOT gated on the manual-deploy `auto_retry_processor` CF** — that CF already caps correctly on its own path. The plan's line-138 warning is moot for this fix.

---

## §4.4 — batch-writer buffer ordering 🟢 (turnkey; add one test)

`shared/utils/bigquery_batch_writer.py` `_flush_internal()` clears the buffer (`:259`) *before* `insert_rows_json()`, so a failed flush loses the records and every caller discards the `False`. **The "clear to release lock faster" comment is false** — all three entry points (`add_record`, `_periodic_flush`, `flush`) hold `self.lock` across the I/O, so clearing early releases nothing.

**Fix:** snapshot `records_to_flush = self.buffer[:batch_size]`, remove them (`del self.buffer[:batch_size]`) **only on confirmed success**; wire the existing `total_flush_failures` counter to `shared.observability.metrics.emit_metric` (fail-open). Index math is race-free because the lock is held for the whole flush.

> **⚠️ CORRECTION (Fable adversarial review, verified from source).** `insert_rows_json` is called with **`skip_invalid_rows=False`** (`bigquery_batch_writer.py:293`), so there are TWO distinct failure paths and they must be treated DIFFERENTLY:
> - **`if errors:` path (`:302`)** = row-level rejection (a schema-invalid record rejects the whole request). This is **permanent** — retaining the batch would poison the buffer and **block ALL future writes to that table** until cap-eviction reaches the bad row (indefinitely on low-traffic tables). **Keep the current behavior here: DROP the records** (log them / consider a DLQ later), do NOT retain.
> - **`except Exception:` path (`:318`)** = transient (network/timeout/quota). **Retain here only** — bounded by `MAX_BUFFER_RECORDS` (drops oldest, counted in `total_records_dropped`).
>
> So the fix is **conditional retention: retain on transient exception, drop on row-level `errors`.** The original "retain unconditionally" diff introduced a poison-pill regression. Secondary caveat: retrying a timed-out-but-actually-committed insert re-sends with fresh insertIds → possible duplicate rows (tolerable for the monitoring/audit tables that use this writer, but the writer is therefore "safer for transient loss," not "strictly safer").
>
> **At apply time:** write the exact AFTER against current source — mind the `records_to_flush` → `filtered_records` intermediate between the snapshot and the `insert_rows_json` call — and cover it with the new failure-path unit test (buffer non-empty after an exception, empty after a later success, buffer NOT retained after row-level `errors`). This is one of the two spots that regressed in review; do not paste a pre-written block blind.

**Caller audit (17 real callers):** none loops on `flush()`; none depends on buffer-cleared-on-failure; the only return-value consumer (`ml/signals/claude_pick_reviewer.py:585-640`) merely logs the bool. **The change is strictly safer for every caller.** **No `_flush_internal` failure-path unit test exists — add one** (buffer non-empty + `total_flush_failures==1` after `insert_rows_json` errors; empty after a later success). Existing tests `@patch` `get_batch_writer`, so they won't break.
**Deploy:** all `shared/`-watching services (phase2/3/4, scrapers, etc.) on push.

---

## §4.6 — min-instances → 0 🟡 ($79/mo measured; coordinated multi-vector)

**Order matters.** Enable Eventarc `--retry` on the 3 orchestrator triggers FIRST (they are `RETRY_POLICY_DO_NOT_RETRY`; min-instances is an expensive workaround), then set min=0.

**Reversion vectors — the complete set (verified live this session):**
| Vector | Where | Which services carry `=1` |
|---|---|---|
| Deploy script | `bin/deploy-service.sh:51-62` (`get_min_instances` returns `"1"`) | prediction-coordinator + 3 orchestrators |
| Build trigger substitutions | per-trigger `_MIN_INSTANCES` (repo default is `0`; the `=1` is in GCP trigger config, NOT a repo file) | `deploy-prediction-coordinator`=1, `deploy-phase3-to-phase4-orchestrator`=1, `deploy-phase4-to-phase5-orchestrator`=1, `deploy-phase5-to-phase6-orchestrator`=1 (fix via `gcloud builds triggers update … --substitutions _MIN_INSTANCES=0`) |
| Drift detector | `bin/validation/detect_config_drift.py` | **Only the 3 orchestrators** (`min_instances:1`, high-severity escalation). **Coordinator is expected `min=0` there** — so the drift detector will NOT flag a coordinator drop to 0. |

**Consequence:** the **coordinator has two reversion vectors** (deploy-service.sh + its build trigger) and the detector won't catch a regression; the **orchestrators have three** (deploy-service.sh + trigger + detector). All must change in one coordinated pass or it silently reverts.

---

## §4.7 — 100× shot-zone scale bug 🟠 (mechanism confirmed; blast radius now MEASURED; fix diff still to write)

**Mechanism (confirmed):** `player_shot_zone_analysis` stores percentages 0-100 (`…/player_shot_zone_analysis_processor.py:133`). The cached path in `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:1852-1854` divides by 100 → correct 0-1. The **fallback** path (`feature_extractor.py:885-888`, fires only on daily-cache miss at `:1944-1948`) already computes ratios 0-1, then hits the same unconditional `/100` → **0-0.01, a 100× under-scale.** Affected features: `FEATURES_SHOT_ZONE = [18,19,20]` (`shared/ml/feature_contract.py:778`) = pct_paint, pct_mid_range, pct_three. Feature 19 (mid_range) is the reliable tell — the shot_zone_lookup overlay (`:1955`) re-supplies only 18 & 20, never 19.

**Blast radius (MEASURED this session — resolves plan uncertainty #5):** no per-row flag records cache-hit vs fallback, so measured via the value-range proxy (features in `(0, 0.01)`). Feature-19 count = **2,223 of 147,340 rows ≈ 1.5%**, present across all seasons (this season's rate is lower, ~0.3-0.4%). **Small blast radius** → the fix is worth doing, but historical backtests are only marginally contaminated (not a revalidation emergency). Exact proxy query (verified, run from repo `.venv` + `google.cloud.bigquery`):

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) AS ym,
  COUNTIF(feature_18_value > 0 AND feature_18_value < 0.01) AS paint18,
  COUNTIF(feature_19_value > 0 AND feature_19_value < 0.01) AS mid19,   -- reliable tell
  COUNTIF(feature_20_value > 0 AND feature_20_value < 0.01) AS three20,
  COUNT(*) AS total_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
GROUP BY ym ORDER BY ym;
```
(paint18/three20 over-count — a spot-up shooter or non-shooter legitimately has ~0 paint/three share; **mid19 is the cleanest tell**. Table is UNPARTITIONED, so this full-scans — cheap but not free.)

**Still to decide before apply:** the fix itself — make the `/100` in `ml_feature_store_processor.py:1852-1854` conditional on the source scale, OR normalize the fallback in `feature_extractor.py:885-888` to 0-100 before it reaches the divide. Prefer normalizing the fallback (one site, keeps the processor's divide uniform). Then decide whether to backfill the ~1.5% of affected historical rows (low value given the small radius).

---

## §4.9 — pre-season fan-out smoke test 🟠 (premise needs REDESIGN — the dev sandbox does not exist)

**The plan says:** "publish one synthetic message via `prediction-request-dev` (NOT prod)." **This is not runnable as written.** Verified live this session:
- The **`nba-props-platform-dev` project does not exist** (`gcloud projects list` → only `nba-props-platform`; describing the dev project errors "Requested project not found").
- The dev environment the test harness references (`bin/predictions/deploy/test_prediction_worker.sh:19-25`, README `:80-175`) — dev project, `prediction-request-dev` topic, `prediction-worker-dev` service, dev subscription — is **entirely gone** (or never survived the off-season purge). There is no `prediction-request-dev` topic in `nba-props-platform` either.

**So the smoke test needs a redesign — options:**
1. **(Recommended) One synthetic message on PROD, cleaned up.** Publish a single crafted message to `prediction-request-prod` for a throwaway player/game, confirm it traverses topic → sub → cold worker → staging write, then delete the staging/prediction row. This exercises the *actual* opener path (the thing worth de-risking). Off-season + halted, so a lone synthetic prediction is low-harm; just ensure it never reaches grading/best-bets (it won't — halted) and delete the row afterward. **Must run AFTER §4.6 sets the worker/coordinator to min=0** to genuinely test cold-start.
2. Stand up a minimal dev topic + subscription pointing at the **prod** worker — same net effect as option 1 (invokes prod worker, writes a prod staging row) with more setup. No real isolation benefit.
3. Recreate the full `nba-props-platform-dev` environment — far too heavy for a smoke test; only worth it if a standing dev sandbox is wanted for other reasons.

**Recommendation:** adopt option 1, and update `06-PLAN §4.9` + `test_prediction_worker.sh` accordingly. The earlier Session-7 note ("recreate the dev topic") is superseded by this — the topic alone is insufficient because it belongs to a non-existent project.

> **⚠️ Safety hardening (Fable strategy review) — a prod synthetic message has a bigger blast surface than "it's halted" implies.** Halt gates Phase 6 *export*, but NOT these, which all still run off-season and would ingest a synthetic `player_prop_predictions` row:
> - **The edge-based auto-halt query** averages `ABS(predicted_points - current_points_line)` over `game_date >= CURRENT_DATE()-7`. On an empty off-season slate, **one synthetic row IS the 7-day average** — it could flip `halt_active` state.
> - **`halt_state_writer`** runs daily **5 AM ET** — if cleanup slips past it, halt_state is computed on fabricated data.
> - **Canaries (every 30 min)** and **`expected_outputs` reconciliation** would also see the row.
>
> **Required cleanup checklist for option 1:** (a) use an obviously-synthetic `player_lookup` (e.g. `smoke-test-synthetic`) and a clearly-fake `game_id`; (b) delete from **both** the staging table **and** `player_prop_predictions` in the **same session**, immediately after confirming the write; (c) run the whole test **outside** the 5 AM ET `halt_state_writer` window and verify the next writer cycle computed clean; (d) confirm no canary/edge-halt alert fired. If this cleanup discipline feels too tight, that itself argues for a heavier but isolated approach (recreate a dev topic + subscription → prod worker, message flagged synthetic) — but option 1 with the checklist is the pragmatic choice.

---

## Suggested apply order (when approved / in August)

1. 🟢 **Trivial, isolated, deploy on push:** §4.3, §4.10 (worker), §4.1 (coordinator+worker, **corrected** None-branch), §4.5 (shared/, **corrected** no-increment), §4.4 (shared/, **corrected** conditional-retention + new test). Each is a clean diff **as corrected above**; batch into one or two commits, let auto-deploy carry them (off-season = safe window). Run the per-dir test suite first (`-p no:cacheprovider`, per the cross-suite-pollution lesson).
2. 🟠 **§4.2** — verify the two exporters suppress picks on `halt_active`, then apply the one-spot `base_exporter.py` query-error fail-closed fix. Can ride with the trivial batch once verified.
3. 🟡 **§4.6** as its own coordinated commit + the four `gcloud builds triggers update` calls + Eventarc `--retry` first. Do not fold into the trivial batch. **(Config-only for the trigger/Eventarc parts — candidate to do NOW for the ~$79/mo it burns off-season; see handoff.)**
4. 🟠 **§4.7** once the fix approach is chosen (normalize fallback) — small backfill optional.
5. 🟠 **§4.9** redesigned to option 1 **+ the cleanup checklist above**, run **after** §4.6, before the Oct 21 opener.

*Prep 2026-07-24 (Session 7). All diffs verified from source; nothing applied. See `07-PLAN-REVIEW-2026-07-24.md` Session-7 addendum and `2026-07-24-SESSION-7-HANDOFF.md`.*
