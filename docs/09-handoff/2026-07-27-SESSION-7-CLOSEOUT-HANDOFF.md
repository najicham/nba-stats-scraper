# Session Handoff — 2026-07-27 (GCP audit close-out; entry point for next session)

**Branch:** `main`, clean. **System:** OFF-SEASON, halted; opener ~Oct 21 2026.
**This is the definitive, self-contained handoff** for the GCP cost + robustness audit. It supersedes `2026-07-24-SESSION-7-HANDOFF.md` (kept for detail). If you read one doc, read this, then the audit index `docs/08-projects/current/gcp-cost-audit-2026-07/README.md`.

---

## 0. TL;DR

The audit is at a **verified stopping point.** Everything applied is confirmed working at the *behavior* level (not just config). Everything deferred is captured as reviewed, turnkey, internally-consistent docs. The only open work is **owner-only** (item 3) or **calendar-gated** (the August §4 safety batch, now days away). **There is nothing worth doing off-season.** The next real task is executing the August §4 batch when the owner is ready.

---

## 1. State in one paragraph

The cost problem largely solved itself (~$0.73 marginal slate; in-season ~$200–250/mo; floor-dominated). The audit's real yield was the **safety layer**, captured as `06-PLAN §4` and made turnkey in `08-AUGUST-EXECUTION-PREP.md`. This-week actions (§3) are closed except the owner-only Credits check. A 10-agent plan review + two rounds of Fable adversarial review confirmed the plan solid, caught **two real regressions** in the first-pass diffs (now corrected), and fixed six doc-staleness items. Three behavior-level verifications closed out items 1 & 2. **Do NOT** reopen the Tier B rewrite / §6 closures, flip the grading dedup (`prediction_accuracy_processor.py:573`), or re-create the fan-out sub (it exists).

---

## 2. Done + behavior-verified

| Item | Status |
|---|---|
| §3.1 `prediction-request-prod` push sub + DLQ (Phase 5 fan-out) | ✅ applied S6. **Behavior-verified:** DLQ topic has `prediction-request-dlq-sub` → dead-letters retained, not discarded. |
| §3.2 `infinitecase-db` automated backups | ✅ applied S7 (owner-approved). **Behavior-verified:** 3 `SUCCESSFUL AUTOMATED` backups (07-25/26/27, 09:00), online, no restart. |
| §3.4 `nba-bigquery-backups` "$31/mo" | ❌ PHANTOM — no such line item. Refuted; struck from the forecast. |
| Plan review (10 lenses) + 2 Fable rounds | ✅ plan solid; 2 diff regressions caught + fixed; 6 doc-staleness items fixed. |
| §4.5 retry recycle | ✅ confirmed STOPPED (0 fresh `retry_count=0` re-mints since 07-04). |

**Verification commands (read-only, reusable):** `gcloud sql backups list --instance=infinitecase-db --project=infinite-case`; `gcloud pubsub topics list-subscriptions prediction-request-dlq --project=nba-props-platform`.

---

## 3. Open

- **Item 3 — OWNER-ONLY.** Console → Billing → Credits on `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720`. `jett-prod` runs the `minScale=1` + `cpu-throttling:false` config that cost $321/mo on InfiniteCase, on an account with no export/budget — possible trial cliff. CLI can't see trial-credit state.
- **August §4 safety batch** — the main next task. Details in §4 below.

---

## 4. The August §4 batch — how to execute

**Reference: `08-AUGUST-EXECUTION-PREP.md`** — exact before/after diffs, caller audits, deploy paths. **Read its top banner first: two first-pass diffs regressed and were corrected — do NOT apply the pre-correction versions.**

**Apply order:**
1. 🟢 **Trivial batch (one or two commits, auto-deploys on push):** §4.3 (`type(e)` typo), §4.10 (feature_version `ORDER BY DESC`), §4.1 (fail-open — 3 sites, **corrected** None-branch), §4.5 (retry recycle — **corrected**, no double-increment; `shared/` push reaches phase2/3/4 + scrapers, NOT gated on the manual-deploy CF), §4.4 (batch-writer — **corrected** conditional retention + new failure-path unit test). Run per-dir tests first (`-p no:cacheprovider`).
2. 🟠 **§4.2** — premise stale (`mlb_best_bets_exporter.py` gone; both NBA exporters already call `halt_envelope`). Real residue: make `base_exporter.py`'s query-error `except` path (~`:394-399`) set `halt_active=True` for recent dates (it currently fail-opens). Verify exporters suppress picks on `halt_active` first.
3. 🟡 **§4.6 min-instances→0** ($79/mo) as its own coordinated commit: Eventarc `--retry` on the 3 orchestrator triggers FIRST, then update **all reversion vectors together** — `deploy-service.sh:51-62` + the **4** build-trigger `_MIN_INSTANCES` substitutions (`deploy-prediction-coordinator` + 3 orchestrators, via `gcloud builds triggers update`) + `detect_config_drift.py` (pins only the 3 orchestrators; coordinator is uncovered). Don't fold into the trivial batch.
4. 🟠 **§4.7** 100× shot-zone: normalize the fallback to 0-100 before the `/100`. Blast radius measured ~1.5% (small); historical backfill optional.
5. 🟠 **§4.9** pre-season fan-out smoke test — **redesigned** (the `nba-props-platform-dev` project does not exist, so "publish to `prediction-request-dev`" is dead). Publish ONE synthetic message to `prediction-request-prod` for a throwaway player/game, confirm it reaches a staging write, **delete the row same-session**, run **after** §4.6, and follow the cleanup checklist in `08 §4.9` (a synthetic row can skew the 7d edge-halt query / `halt_state_writer` — clean up before the 5 AM ET writer cycle).

**Why none of this is urgent:** all §4 defects are dormant while halted (no predictions run). The right window is August with tests, not an off-season push. **Verified:** docs-only pushes do NOT trigger Cloud Build (last build 07-05); code commits do.

---

## 5. Parked — verify at October restore (§7 of the plan)

- **`nbac_play_by_play` + `nbac_injury_report` mint ~12 `failed_permanent`/day since 07-04** (`nba_orchestration.failed_processor_queue`, 141 rows each/24 dates). Trivial cost, terminal (not the recycle), likely benign off-season (no games) — but both are **core in-season sources**, so **must verify green at October restore.** `succeeded` rows in that ledger stopped exactly 07-04 (partial explanation for the plan's §8 #2 "unexplained July 4 stop").
- `OddsGameLinesProcessor` failing daily; ~99% `model_bb_candidates` provenance loss (writer fixed, verify at open); the `:478` look-ahead leak (de-risked — league-avg baseline only, per Lens 9); orphaned CFs; `expected_by` midnight-UTC anchor; GCS object-version lifecycle. All in `06-PLAN §7`, none urgent.
- **September (quiet-window) task:** read `ml/signals/aggregator.py` for defects (only *scanned* so far; it's where the betting edge lives). Now an explicit `06-PLAN §5` line.

---

## 6. Environment notes (HOST-SPECIFIC — retest on a fresh host)

- **This host:** subagents work (including `model: fable` — used them this session), and `gcloud sql/builds/projects` list+describe did NOT hang. The prior WSL host's "subagents/Fable 100% broken" + "describe hangs" were **host-specific** — probe once before assuming either. See memory `wsl-gcloud-hang-and-subagents-broken-2026-07-23`.
- Still wrap mutations in `timeout … || echo "EXIT=$?"` (cheap insurance); verify with a list call before retrying. Always `--project=nba-props-platform` (or the target project).
- **BigQuery:** use repo `.venv/bin/python3` + `google.cloud.bigquery` (system python3 lacks it; `bq` CLI unreliable). `ROWS`/`ROW` are reserved — alias around them. `ml_feature_store_v2` is UNPARTITIONED (full-scans).
- Billing export (UNIVERSAL): `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`, US, partitioned on `_PARTITIONTIME`; credits are a negative nested array (UNNEST + ADD); never join US export to us-west2 `nba_*`.

---

## 7. Where everything lives

| Doc | What |
|---|---|
| **`…/gcp-cost-audit-2026-07/README.md`** | Index: status, read-order, do-not-reopen, gotchas. **Start here after this handoff.** |
| `…/06-PLAN.md` | The living plan (baseline, §4 August, §6 closures, §7 parked, §8 uncertain, §9 sequence). |
| `…/08-AUGUST-EXECUTION-PREP.md` | Turnkey §4 diffs + Fable corrections. **The apply reference.** |
| `…/07-PLAN-REVIEW-2026-07-24.md` | Solidity review + Session-7 addendum. |
| `docs/02-operations/session-learnings.md` | Two reusable anti-patterns added (retain-on-failure poison pill; two-owners-one-counter). |
| Memory | `gcp-cost-audit-item1-applied-2026-07-23`, `wsl-gcloud-hang-and-subagents-broken-2026-07-23`. |

---

## 8. Recommended first moves for the next session

1. If it's August and the owner is ready: execute §4 step 1 (trivial batch) per §4 above — apply the **corrected** diffs, run per-dir tests, one commit, verify auto-deploy.
2. Otherwise: nothing off-season. Ping the owner on item 3 (the only external-clock item).
3. Don't re-run the audit — it's converged. Don't re-create the fan-out sub. Don't flip the grading dedup.

*Handoff 2026-07-27. Audit close-out. Items 1 & 2 applied + behavior-verified; plan + diffs reviewed (2 regressions fixed); docs consolidated. END HERE is the verified recommendation.*
