# 08 — August §4 Execution Prep (turnkey diffs)

**Date:** 2026-07-24 (Session 7)
**Purpose:** Turn `06-PLAN.md §4` from "scoped" into "mechanical apply." Every item below was re-verified from source this session (working agent runtime) with exact before/after diffs, caller-impact audits, deploy paths, and — where the plan flagged an unknown — the resolution. **Nothing here is applied.** This is the reference the August executor (or an approved same-session push) works from.

**Global note:** all these defects are **dormant off-season** — no predictions run, no picks publish. None is live-urgent; they bite at season open. That is why they batch here rather than forcing an off-season deploy.

**Readiness legend:** 🟢 turnkey (exact diff, low risk) · 🟡 turnkey but coordinated (multi-file, order matters) · 🟠 needs one more decision/fix before apply.

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

**Readers audited (11 sites):** only `worker.py:2077` would have raised on `None`; it is fixed above. `quality_gate.py:369` has the same latent `.get` shape but reads its own BQ-sourced dict (int-coerced at `:216`), so it's insulated. All other readers assign-only or guard with `pd.notna`/`fillna`/truthy checks. **No additional edits required.** Measured exposure: 44 NULL rows / 40,564 (0.1%).
**Deploy:** `prediction-coordinator` + `prediction-worker` (both auto-deploy).

---

## §4.5 — terminate the retry recycle 🟢 (~$30/mo measured; single `shared/` edit)

`shared/utils/pipeline_logger.py` `queue_for_retry()`. The dedup lookup (`:579-586`) matches only `status IN ('pending','retrying')`, so a `failed_permanent` row re-mints a fresh `retry_count=0` row on the next transient failure → infinite recycle. The UPDATE branch (`:603-611`) reads `existing_retry_count` (`:599`) but never uses it and hard-sets `status='pending'` without touching `retry_count`.

**Fix (replaces `:579-621`):** broaden dedup to `IN ('pending','retrying','failed_permanent')` + `ORDER BY updated_at DESC`; increment `retry_count = existing+1`; once `>= max_retries` (the existing `max_retries=3` param at `:539`, no new constant) pin the row to `failed_permanent` with `next_retry_at=NULL` so `auto_retry_processor` (which only picks up `status='pending'`) never re-queues it. Full diff in the agent transcript / reproduce from the description above.

**Deploy path (clarified):** the bug is in `shared/`, reached by `data_processors/{raw,analytics,precompute}/*_base.py` + `scrapers/scraper_base.py`. A normal push to main redeploys **nba-phase2-raw-processors, nba-phase3-analytics-processors, nba-phase4-precompute-processors, nba-scrapers** (their triggers watch `shared/`). **NOT gated on the manual-deploy `auto_retry_processor` CF** — that CF already caps correctly on its own path. The plan's line-138 warning is moot for this fix.

---

## §4.4 — batch-writer buffer ordering 🟢 (turnkey; add one test)

`shared/utils/bigquery_batch_writer.py` `_flush_internal()` clears the buffer (`:259`) *before* `insert_rows_json()`, so a failed flush loses the records and every caller discards the `False`. **The "clear to release lock faster" comment is false** — all three entry points (`add_record`, `_periodic_flush`, `flush`) hold `self.lock` across the I/O, so clearing early releases nothing.

**Fix:** snapshot `records_to_flush = self.buffer[:batch_size]`, remove them (`del self.buffer[:batch_size]`) **only on confirmed success**; on failure retain them for the next flush, bounded by a new `MAX_BUFFER_RECORDS` cap (drops oldest, counted in `total_records_dropped`); wire the existing `total_flush_failures` counter to `shared.observability.metrics.emit_metric` (fail-open). Index math is race-free because the lock is held for the whole flush. Full diff in the agent transcript.

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

**Blast radius (MEASURED this session — resolves plan uncertainty #5):** no per-row flag records cache-hit vs fallback, so measured via the value-range proxy (features in `(0, 0.01)`). Feature-19 count = **2,223 of 147,340 rows ≈ 1.5%**, present across all seasons (this season's rate is lower, ~0.3-0.4%). **Small blast radius** → the fix is worth doing, but historical backtests are only marginally contaminated (not a revalidation emergency). Query: `docs/08-projects/current/gcp-cost-audit-2026-07/` proxy in the Session-7 transcript (`ml_feature_store_v2`, `COUNTIF(feature_19_value > 0 AND feature_19_value < 0.01)` grouped by month).

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

---

## Suggested apply order (when approved / in August)

1. 🟢 **Trivial, isolated, deploy on push:** §4.3, §4.10 (worker), §4.1 (coordinator+worker), §4.5 (shared/), §4.4 (shared/ + new test). Each is a clean diff verified above; batch into one or two commits, let auto-deploy carry them (off-season = safe window). Run the per-dir test suite first (`-p no:cacheprovider`, per the cross-suite-pollution lesson).
2. 🟡 **§4.6** as its own coordinated commit + the four `gcloud builds triggers update` calls + Eventarc `--retry` first. Do not fold into the trivial batch.
3. 🟠 **§4.7** once the fix approach is chosen (normalize fallback) — small backfill optional.
4. 🟠 **§4.9** redesigned to option 1, run **after** §4.6, before the Oct 21 opener.

*Prep 2026-07-24 (Session 7). All diffs verified from source; nothing applied. See `07-PLAN-REVIEW-2026-07-24.md` Session-7 addendum and `2026-07-24-SESSION-7-HANDOFF.md`.*
