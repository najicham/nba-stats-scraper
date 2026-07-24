# Session Handoff — 2026-07-24 (Session 7, off-season)

**Branch:** `main`, clean except audit docs + handoffs. **System state:** OFF-SEASON, halted; opener ~Oct 21 2026.
**This session APPLIED ONE INFRA CHANGE** (item 2 — `infinitecase-db` backups) and **re-ran the 10-agent plan review on a working runtime.** No code committed; no repo HEAD change beyond docs.

Predecessor: `docs/09-handoff/2026-07-24-SESSION-6-HANDOFF.md` (Session 6 applied item 1, reviewed the plan in the main loop because its subagents were dead). This session executed the two Session-6 "do next" tasks: re-run the review with real agents, and apply item 2.

---

## 0. TL;DR

1. **Item 2 (`infinitecase-db` backups) is APPLIED and verified.** `enabled=True`, `startTime=09:00`, `retainedBackups=7`, instance stayed `RUNNABLE` (online, no restart). §3 of `06-PLAN.md` is now closed except item 3 (owner-only).
2. **The 10-agent review runs fine on this host.** The Session-6 stalls were WSL-local. 9/10 agents succeeded; lens 6 stalled once and was finished in the main loop. **The plan re-confirmed solid** — no lens overturned anything.
3. 🔴 **NEW finding: the `prediction-request-dev` topic is gone.** Verified live. It is a **prerequisite for §4.9** (the pre-season fan-out smoke test) — recreate it before the smoke test. Folded into `06-PLAN.md §4.9`.
4. **Two §4.6/§4.9 refinements folded in** (drift detector doesn't pin the coordinator; §4.9 must run after §4.6 sets min=0).
5. **Item 3 (Credits pages) remains owner-only** — unchanged, the only item with an external clock.

---

## 1. What was applied (item 2) — the only infra change this session

**Enabled automated daily backups on `infinitecase-db`** (project `infinite-case`, Postgres 15) — it had **zero** backups.

```
gcloud sql instances patch infinitecase-db --project=infinite-case \
  --backup-start-time=09:00 --retained-backups-count=7
```
Applied config (from the server echo): `backupConfiguration.enabled=true`, `startTime=09:00`, `retainedBackups=7 (COUNT)`, `transactionLogRetentionDays=7`, `backupTier=STANDARD`.
**Verified** with `describe`: `enabled=True  startTime=09:00  retainedBackups=7  state=RUNNABLE`.

- **Online, no restart** — instance stayed `RUNNABLE`. PITR (`--enable-point-in-time-recovery`) was correctly NOT set (it is the only backup-adjacent flag that forces a restart). `--enable-bin-log` correctly omitted (MySQL-only). `patch` is PATCH-merge, so no other settings were touched.
- **WSL note:** the `patch` command hung on the response (moved to background at the 120s harness limit) but **succeeded server-side** — the mutation-hang behavior the Session-6 handoff §5 warned about. Confirmed with `describe` (which returned fine here, unlike Session 6's host). Rollback if ever needed: patch back with `--no-backup`.
- ~$0.20/mo.

---

## 2. The review re-run (the Session-6 "do first" task)

Real 10-agent fan-out against `06-PLAN.md` + `07-PLAN-REVIEW-2026-07-24.md`. Agent briefs forbade `gcloud`/`bq` and passed live values inline. **9/10 agents succeeded**; lens 6 stalled ("no progress for 600s") and was completed in the main loop by direct file reading. Every lens returned SOLID / SAFE-TO-DEFER / SOUND / COVERED.

| Lens | Verdict |
|---|---|
| 1 Item-1 contract | ✅ SOLID (publish is `predictions/coordinator/coordinator.py`, not `worker/`) |
| 2 Item-1 safety | ✅ SOLID — poison msgs ACK 204; transient→500→5 retries→DLQ; MERGE dedup idempotent |
| 3 Opener cold-start | ✅ COVERED by §4.9 — `time.sleep(0.02)`=50/sec confirmed |
| 4+5 Item-2/Item-4 logic | ✅ SOUND — patch is online + PATCH-merge; item-4 phantom re-confirmed |
| 6 August code findings | ✅ CONFIRMED (main loop) — all five real; dedup must not flip |
| 7 Min-instances vectors | ✅ + refinement (below) |
| 8 Aggregator safety | ✅ SAFE-TO-DEFER — no broad excepts; blocklist deliberate; `or 0` correct |
| 9 Parked items | ✅ correct — `feature_version DESC` picks newer; leak is backfill-only baseline |
| 10 Measurement/sequencing | ✅ SOLID — no §6 closure is cost-fragile; flagged the dev-topic risk (it materialized) |

---

## 3. New / sharpened findings folded into the plan

1. 🔴 **`prediction-request-dev` topic missing (verified live).** `gcloud pubsub topics list` → only `prediction-request-prod` and `prediction-request-dlq`. **Prerequisite for §4.9.** Recreate before the smoke test: `gcloud pubsub topics create prediction-request-dev` (one command, mutation → needs go). `bin/predictions/deploy/test_prediction_worker.sh:25` still references it. Folded into `06-PLAN §4.9`.
2. **§4.6:** the Cloud Build reversion vector is trigger config, not a repo file (review was right). Additionally `detect_config_drift.py` pins only the **3 orchestrators** to `min=1`; `prediction-coordinator` is expected `min=0` there, so a coordinator drop to 0 is reverted **only** by `deploy-service.sh:51-62`, and the drift detector won't flag it. Folded into `06-PLAN §4.6`.
3. **§4.9 ordering:** run it **after** §4.6 sets `min=0`, else it exercises a warm worker. Folded into `06-PLAN §4.9`.

---

## 4. Do next — in order

1. **Item 3 (OWNER ONLY):** Console → Billing → Credits on `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720`. `jett-prod` runs the `minScale=1` + `cpu-throttling:false` config that cost $321/mo on InfiniteCase, on an account with no export/budget. Possible trial cliff. CLI cannot see trial-credit state.
2. **August safety work** (`06-PLAN §4`, ~2-3 days): 4.1 zero-tolerance fail-open (`data_loaders.py:1042` is the real one), 4.2 make-halts-halt (+ `base_exporter.py` fail-closed), 4.3 the `type(e,...)` typo, 4.4 batch-writer ordering, 4.5 retry recycle, 4.6 min-instances→0 (with the §4.6 refinements above), 4.7 shot-zone 100× bug, **4.9 smoke test** (recreate the dev topic first; run after 4.6), **4.10 feature_version ORDER BY**.
3. **September** (`06-PLAN §5`): monitors with inputs today.
4. **October restore** (`06-PLAN §9`): per manifest with corrections.

---

## 5. Environment notes (this host)

- **Subagent runtime WORKS here** (unlike Session 6's WSL host). Fan out freely; forbid `gcloud`/`bq` in briefs and pass live values inline. One agent stalled once — if that recurs, finish that lens in the main loop.
- **`gcloud` mutations hang on response** (patch moved to background but succeeded server-side). Wrap in `timeout`, give 180-240s, and **verify with `describe`/`list` before retrying**. `describe` and `list` both returned fine on this host (Session 6's host hung on `describe`/`get-iam-policy`).
- Always pass `--project=nba-props-platform` (or the target project). Local default project is unreliable.
- **UNIVERSAL (unchanged):** billing export `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`, US, partitioned on `_PARTITIONTIME`; credits are a negative nested array (UNNEST + ADD); never join US export to us-west2 `nba_*`. Never trigger Phase 6 `signal-best-bets` for historical dates. Do **not** flip the grading dedup at `prediction_accuracy_processor.py:573`.

---

## 6. Documents

| File | What |
|---|---|
| `docs/08-projects/current/gcp-cost-audit-2026-07/06-PLAN.md` | Living plan. §3 item 2 → DONE; §4.6/§4.9 refined; dev-topic prerequisite added. **Start here.** |
| `.../07-PLAN-REVIEW-2026-07-24.md` | Now has a **Session 7 addendum** documenting the real 10-agent re-run. |
| `docs/09-handoff/2026-07-24-SESSION-6-HANDOFF.md` | Predecessor (item 1). |

---

*Handoff 2026-07-24 (Session 7). Item 2 applied & verified. 10-agent review re-run (plan solid). Dev-topic gap surfaced for §4.9. Item 3 owner-only; August work scoped.*
