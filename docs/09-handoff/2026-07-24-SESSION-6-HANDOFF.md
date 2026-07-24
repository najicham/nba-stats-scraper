# Session Handoff — 2026-07-24 (Session 6, off-season)

**Branch:** `main`, clean (working tree has the audit docs + this handoff). **System state:** OFF-SEASON, halted; opener ~Oct 21 2026.
**This session APPLIED ONE INFRA CHANGE** (item 1) — the first thing applied from the entire GCP cost audit. Everything else was read-only or doc edits. **No code committed; no repo HEAD change beyond docs.**

Predecessor: `docs/09-handoff/2026-07-21-SESSION-5-HANDOFF.md` (Session 5, read-only). This session executed §3 of `06-PLAN.md`.

---

## 0. TL;DR

1. **Item 1 (Pub/Sub fan-out) is APPLIED and verified.** Phase 5 fan-out restored. Do not re-create it.
2. **Item 4 (`nba-bigquery-backups` $31/mo) is a PHANTOM** — no such line item exists; premise refuted.
3. **Item 2 (`infinitecase-db` backups) is confirmed off and ready** — one online command, awaiting owner go.
4. **Item 3 (Credits pages) is owner-only** and unchanged — the only item with an external clock.
5. **The plan is solid** — see `07-PLAN-REVIEW-2026-07-24.md`. Two new low-cost August items added (§4.9, §4.10).
6. ⚠️ **The subagent runtime is DOWN in this environment** — 10 launches, 10 stalls. Do the first task below (re-run the review with real agents) to check whether a fresh runtime recovered; if agents stall again, work in the main loop.

---

## 1. What was applied (item 1) — the only infra change

**Recreated the missing `prediction-request-prod` push subscription with a DLQ.** The topic had zero subscriptions → messages published for Phase 5 fan-out went nowhere → would have silently broken opening night.

Applied (canonical config from `bin/predictions/deploy/deploy_prediction_worker.sh:225-231` + DLQ enhancement):
```
subscription  prediction-request-prod  (topic prediction-request-prod)
push endpoint https://prediction-worker-f7p3g7f6ya-wl.a.run.app/predict
OIDC SA       prediction-worker@nba-props-platform.iam.gserviceaccount.com
ack-deadline  300s
DLQ           prediction-request-dlq, maxDeliveryAttempts=5
+ IAM         pubsub agent service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com
              granted roles/pubsub.subscriber on the subscription (publisher on DLQ topic pre-existed)
```
**Verified:** worker `/predict` decodes the push envelope (`worker.py:752-765`); coordinator publish shape matches (`coordinator.py:3582-3602`); poison messages ACK at 204 (DLQ only catches transient failures); re-deliveries tolerated (MERGE + grading dedup).

**Corrections to the plan's stated premise:** topic AND DLQ topic already existed (only the sub was missing); real ack-deadline is 300s (plan implied 60); the pubsub-agent subscriber grant was an omitted prerequisite. Rollback if ever needed: `gcloud pubsub subscriptions delete prediction-request-prod --project=nba-props-platform`.

---

## 2. What was diagnosed / rechecked

| Item | Result |
|---|---|
| **4** `nba-bigquery-backups` | **PHANTOM.** No project/service/SKU by that name in the billing export. nba April BigQuery = $49.57 query analysis + ~$0.20/mo storage; no backup SKU. "$31/mo" extrapolated from one day's $1.04. Drop the `−$31?` forecast line. |
| **2** `infinitecase-db` | Premise CONFIRMED: `backupConfiguration.enabled=False` (Postgres 15, RUNNABLE). Enabling is online (no restart). **Not applied** (different project — needs go). |

---

## 3. Do next — in order

1. **RE-RUN THE 10-AGENT PLAN REVIEW (fresh runtime).** This session's subagents were 100% dead; a new session may have a working runtime. Task 10 agents against `06-PLAN.md` + `07-PLAN-REVIEW-2026-07-24.md` to confirm the lenses. **If agents stall again ("no progress for 600s"), stop relaunching and work in the main loop** — that is how everything this session got done. Forbid `gcloud`/`bq` in agent briefs (they hang) and pass live values inline.
2. **Item 2 patch (owner approval):** `gcloud sql instances patch infinitecase-db --project=infinite-case --backup-start-time=09:00 --retained-backups-count=7`. One command, online, ~$0.20/mo.
3. **Item 3 (OWNER ONLY):** Console → Billing → Credits on `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720`. `jett-prod` runs the `minScale=1` + `cpu-throttling:false` config that cost $321/mo on InfiniteCase, on an account with no export/budget. Possible trial cliff.
4. **August safety work** (`06-PLAN.md §4`, ~2-3 days): 4.1 zero-tolerance fail-open, 4.2 make-halts-halt (+ `base_exporter.py:392` fail-closed), 4.3 the `type(e,...)` typo, 4.4 batch-writer ordering, 4.5 retry recycle, 4.6 min-instances→0 (note §4.6 vector correction: the Cloud Build `_MIN_INSTANCES` reversion vector is GCP trigger config, not a repo commit), 4.7 shot-zone 100× bug, **4.9 pre-season smoke test (NEW)**, **4.10 feature_version ORDER BY (NEW, 1 line)**.

---

## 4. Documents

| File | What |
|---|---|
| `docs/08-projects/current/gcp-cost-audit-2026-07/06-PLAN.md` | The living plan. §3 statuses updated; §4.9/4.10 added. **Start here.** |
| `.../07-PLAN-REVIEW-2026-07-24.md` | This session's 10-lens solidity review. |
| `.../00-FULL-ANALYSIS.md`, `01`, `02`, `04` | Original audit waves. `04` contains the two KNOWN-WRONG findings (grading dedup, zero-tolerance severity) — see 06-PLAN §4.8 / §5. |
| `docs/09-handoff/2026-07-21-SESSION-5-HANDOFF.md` | Predecessor (has a Session-6 update banner). |

---

## 5. Environment gotchas — WHICH ARE LOCAL vs UNIVERSAL (read before acting)

**LOCAL to this WSL machine — a Claude Web / cloud session will NOT have these, and may behave differently:**
- `gcloud`/`bq`/`gsutil` CLIs hang on the response for **mutations, `run/sql describe`, `get-iam-policy`** (EXIT=124). `pubsub/run list`-style calls are reliable. Always wrap in `timeout … || echo "EXIT=$?"`; give mutations 180-240s; after a timeout on a mutation, VERIFY with a list call before retrying (create may have succeeded server-side). **A cloud/web session on different infra may not hang at all — retest before assuming.**
- BigQuery queries: use `.venv/bin/python3` + `google.cloud.bigquery`. System `python3` lacks the module; `bq` CLI hangs. **A web session won't have this local `.venv`** — it must install/auth its own client.
- Local `gcloud` default project is WRONG — always pass `--project=nba-props-platform` (or the target project). A fresh session must authenticate gcloud/ADC first.
- **Subagent runtime dead this session (10/10 stalls), model-independent.** May be session/host-specific — a fresh session should retest (task 1) rather than assume.

**UNIVERSAL (true regardless of where the session runs):**
- Billing export: table `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`, location **US**. Partitioned on **`_PARTITIONTIME`** (NOT `usage_start_time`) — filter both, pad `_PARTITIONTIME` ~4 days wider. Credits are a **negative nested array**: `cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c),0)` — ADD, never subtract. Export is US; `nba_*` datasets are us-west2 — never join across; billing export lags ~1 day (use D-2).
- Never trigger Phase 6 `signal-best-bets` for historical dates (deletes picks).
- Do NOT flip the grading dedup at `prediction_accuracy_processor.py:573` — `ORDER BY created_at DESC` is deliberate and correct.

---

## 6. Should we write anything for CLAUDE WEB?

**Short answer: no separate CLAUDE-WEB doc is needed — but §5's LOCAL-vs-UNIVERSAL split above is the thing a web session most needs.** A claude.ai/code (web/cloud) session runs on different infrastructure than this WSL host, so:
- It will **not** have this machine's `gcloud` auth, the local `.venv`, or (probably) the CLI-hang behavior. It must authenticate its own gcloud/ADC and install its own BigQuery client first.
- The subagent runtime failure may be **local to this host** — a web session should retest agents (handoff task 1) rather than inherit the "agents are dead" conclusion.
- Everything under §5 UNIVERSAL and the whole plan/review applies unchanged.

If a web session is specifically expected to pick this up, point it at this handoff + `06-PLAN.md` + `07-PLAN-REVIEW-2026-07-24.md`; those three are self-contained. No web-specific artifact beyond that.

---

*Handoff 2026-07-24. Item 1 applied & verified. Plan reviewed (main-loop; re-run with agents on a fresh runtime). Items 2/3 awaiting owner.*
