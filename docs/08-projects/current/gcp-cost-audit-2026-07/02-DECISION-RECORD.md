# 02 — Decision Record: GCP Cost Audit 2026-07

**Date:** 2026-07-21
**Status:** DRAFT — awaiting owner decisions. `[PENDING: …]` slots await the red-team and correctness-risk streams.
**Companions:** `00-FULL-ANALYSIS.md` (Wave 1 — where the money goes), `01-WAVE-2-PIPELINE-EFFICIENCY.md` (Wave 2 — can the pipeline do the same work for less), `03-VALIDATION-PLAYBOOK.md` (how we prove each change worked).
**Purpose:** Not a summary. This is the record of the *choices* the audits force, with tradeoffs stated explicitly enough that (a) the owner can decide with open eyes, and (b) anyone reading in six months can reconstruct why each choice was made — including the choices to do nothing.

**Nothing in this document has been applied.**

---

## 0. How to Read This

Every decision follows the same shape: options → case for → case against → what is traded → reversibility → what would change the answer → recommendation with confidence.

Confidence: **High** = multiple independent measurements agree. **Medium** = single measurement, or designed-not-measured. **Low** = inference.

Two facts frame everything:

1. **The money is modest.** Forward in-season run rate is **$424/mo** (~$3,620/yr blended). Off-season $130/mo. Not existential for a working product.
2. **The robustness picture is not modest.** For one representative game-date (2026-03-10): **5,656 processor runs at 12.9% success produced 7 published picks** — control-plane rows outnumber the product 1,400:1 — and a 2-month provenance loss (`model_bb_candidates`) went unnoticed because failure is the ledger's normal state.

**The dollar findings and the reliability findings are mostly the same findings viewed from two angles.**

Core tension: *the cash case for the big rewrite is weak on its own; the robustness case is strong but carries the only risk in this document that could damage the revenue product.*

**Excluded from decision-making because it is not optional:** the `prediction-request-prod` push subscription does not exist. Predictions cannot run without it. Recreating it (with DLQ, `maxDeliveryAttempts=5`) is a blocking defect fix, this week, regardless of everything else. It also blocks the Tier B test harness.

---

## 1. Decision 1 — Do the rewrite at all?

### Options

| | Option | In-season $/mo | Effort | Serve-path risk |
|---|---|---|---|---|
| **D1-a** | Do nothing | $424 | 0 | none new |
| **D1-b** | Tier A only (config) | $322 | ~3 days | near-zero |
| **D1-c** | Tier A + Tier C | ~$250–290 | ~2–3 weeks | low |
| **D1-c′** | D1-c + in-place hot-path fixes (Wave 2 §8) — **no consolidation** | est. $150–250 | +1–2 weeks | low-medium |
| **D1-d** | Full Tier B consolidation | $34–87 | 12–20 days claimed | **highest in this record** |

**D1-c′ is not in either audit's tier structure but falls out of Wave 2 §8.** Most named call-site fixes (`team_context` batching, coordinator fan-out, `quality_gate` hoist, async `.result()` collection) are implementable inside the *existing* services. It is the legitimate middle path and deserves explicit consideration rather than being collapsed into "Tier B or not."

### The steelman for doing nothing

- **The system works.** ~3.4 picks/day at 60%+ BB hit rate vs a 53% raw model. That pipeline is the entire value of the project and emerged from ~500 sessions of accumulated fixes. A rewrite puts the one thing that makes money at risk to save money that doesn't matter.
- **$3,600–5,100/yr is not existential.** The cost problem, to the extent it existed, was June's $1,019 — and **~$550 of that was bugs and one-offs already fixed.** The run rate already fell 76% on July 4 with zero capability loss.
- **The catastrophic incidents were caught and closed.** Wave 1's 12-month do-nothing growth projection is **+$15–25/mo** — "genuinely modest," in the audit's own words.
- **Every dollar figure for Tier B is DESIGNED, not measured** (Wave 2 §12 says so). The $34/mo target assumes a 25× CPU reduction nobody has demonstrated on this codebase.
- The estimate is bid by and for a single-operator project, during the only window where mistakes cannot be absorbed by "fix it tomorrow, no game tonight."

**This case is real. If the system were also reliable, it would win.**

### The case against doing nothing

- **12.9% run success is not a cost number — it is why a 2-month provenance loss went unnoticed.** A ledger where 87% of entries are failures cannot alarm on anything. The next silent loss might be one that matters.
- **Both expensive loops are dormant, not fixed.** Loop B's gap-detector chain is enabled today; the retry recycle's stop on July 4 could not be explained. It re-armed once already (March 9) and billed three weeks of the season.
- **The 115× write amplification is corrupting-adjacent.** Duplicates are byte-identical today, but 10 processors do blind `WRITE_APPEND` under `maxDeliveryAttempts=5`. Any future non-idempotent change turns duplication into corruption.
- **"Do nothing" still costs October work** — the restore manifest, reversion traps, broken monitors, and the season-guard problem. The purge pattern has already destroyed one critical capability (weekly retraining).

### What each option trades

- **D1-a** accepts the control-plane inversion, two armed loops, and an unalarmed ledger for another season. The risk accepted is not spend — it is *another silent failure of the `model_bb_candidates` class*.
- **D1-b** trades 3 days for $102/mo, fixes nothing structural. Zero regret in any future.
- **D1-c** trades ~2–3 weeks for ~$150/mo more *and* closes the loops, amplification, and partition drift.
- **D1-c′** additionally attacks the query storm in place. Captures an unknown-but-large fraction of Tier B's efficiency without consolidation risk — but leaves 93 services and the idle-floor re-incursion risk.
- **D1-d** trades the highest engineering risk here for the last ~$150–250/mo, structural immunity to the min-instances bug class (Jobs *cannot* have min-instances), a 26:1 → ~1:1 control-plane ratio, and a system one person can hold in their head.

> **The marginal cash of D1-d over D1-c is only ~$1,100–1,800/yr. If Tier B is justified, it is justified by robustness, not money. Anyone approving it should approve it on those grounds.**

### Reversibility

D1-b/c/c′ are reversible to semi-reversible throughout. D1-d is **semi-reversible only while the old services stay deployed-but-idle** through a defined rollback window, and irreversible after they are deleted.

### What would change the answer

- Toward D1-a/b: red-team finds a capability loss the plan missed; the validation design concludes the oracle cannot cover the ~35 unaudited exporters; owner availability drops below ~15 focused days.
- Toward D1-d: correctness analysis concludes the *current* architecture's risk exceeds cutover risk; or Tier C fixes prove harder in place than in the consolidated design.
- `[PENDING: red-team verdict on "no capability loss"]` `[PENDING: correctness-risk ranking of current-vs-rewrite risk]`

### Recommendation

**Do D1-c (Tier A + Tier C) unconditionally — High confidence.** Every item is either pure config or a correctness fix worth doing at $0 savings. None is wasted if Tier B proceeds.

**Tier B: conditional GO — Medium confidence**, under the Decision 2 abort gates, contingent on the red-team finding no disqualifying capability loss. The recommendation is *not* driven by the $34/mo target; it is driven by the control-plane inversion and by making the min-instances and scheduler-purge bug classes structurally impossible. **If the owner weighs product risk more heavily than the audits do, D1-c′ is a defensible stopping point and should not be treated as a failure.**

---

## 2. Decision 2 — Timing

### The window, honestly measured

The stated window is ~10 weeks. It is really shorter:

- Restore Wave A begins **T-14 ≈ Oct 7**. From then the pipeline is live-ish and cutover risk rises.
- A credible shadow needs game-like load; preseason (mid-Oct) is the first real traffic.
- Net: **~8 weeks of build time, with the highest-signal validation compressed into the 2 weeks with least slack.** The 12–20 day estimate fits *only if* nothing else claims those weeks — October rehearsal prep, restore manifest work, and the review streams all will.

### Cost of missing the window

Run 2026-27 on the current architecture at ~$250–322/mo post-A+C. Dollar cost of a one-year deferral: **~$1,500–2,500**, provided Tier C landed. **Missing the window is cheap. This matters for every tradeoff below.**

### Cost of rushing

Cutting over an under-validated pipeline near opening night risks the product during the weeks that seed model retraining, signal health baselines, and live promotion gates (several staged signals need live N≥30 accruing from opening night). A bad first month contaminates the measurement infrastructure the whole season leans on.

> **The asymmetry is stark: rushing risks the product to save ~$2k; deferring costs ~$2k to protect the product.**

### Is a partial rewrite worse than none?

- **Worse than none:** two half-alive pipelines, state crossing an unplanned seam, both needing maintenance on game days. **Forbid this explicitly: cutover is all-of-Phases-2–4-or-none.** (Phase 5/6 can be a separately gated second step — Wave 2 identifies 2→3 and 5→6 as independent amplification concentrations.)
- **Better than none:** the Job is built and shadow-runs all season without ever taking the write path. Costs almost nothing (Jobs bill only when run), produces a season of parity data, and converts the 2027 cutover from a leap into a formality. **This is the designated fallback, not a consolation prize.**

### Pre-committed abort gates

Superseded in detail by `03-VALIDATION-PLAYBOOK.md` §4 (G0–G4). Summary:

1. **G2 replay campaign** — ~10 historical dates green, L4/L5 exact. Not met → fallback.
2. **G3 preseason live shadow** — 7 consecutive clean live days. Not met → open on the old pipeline, keep shadowing.
3. **G4 cutover** — legacy reverse-shadows the first 3 real game days.
4. **At no point** is the old pipeline deleted before the rollback window closes (proposed: All-Star break).

### Recommendation

**Start Tier A this week, Tier C in August, Tier B build after Tier C's seams land — Medium-High confidence** — with abort gates binding.

> **The fallback (shadow all season, cut over in 2027) preserves ~90% of Tier B's eventual value at ~5% of its risk.** Any pressure to skip a gate should be answered with the fallback, not with compressed validation.

---

## 3. Decision 3 — Where cost and robustness ALIGN vs CONFLICT

This is the heart of the question. Every action classified by whether the two goals point the same way.

### 3.1 Aligned — cost down AND robustness up

| Action | Cost effect | Robustness effect |
|---|---|---|
| **C1 — terminate the retry recycle** | $52–96/mo | Restores *meaning* to the run ledger. 4,472 runs/day for dead dates is the noise floor the provenance loss hid under. Highest-alignment item in the record. |
| **C2 — partition the drifted tables** | $15–20/mo | Removes full-scan MERGEs and DML-lock exposure; restores the tables to their own checked-in DDL. Zero code change — the MERGE already carries the predicate. |
| **C3 — populate `source_file_path`** | $25–40/mo | Kills 115× republish amplification at source *and* closes the door on future blind-append corruption. Chosen precisely because it avoids touching write semantics. |
| **Eventarc `--retry` + orchestrators min=0** | $44/mo, permanent | Fixes the actual defect (`RETRY_POLICY_DO_NOT_RETRY` means a dropped message is *lost*; min-instances was an expensive bandage). Converts an apparent conflict into strict alignment. |
| **Coordinator fan-out fix** | large share of worker waste | Also fixes the `is_active` defect that silently broke the quality gate for 9 of 10 systems. 86% of predictions are discarded recomputes. |
| **Kill `bluesky-nba-listener`** | $20/mo | Writes to a table that does not exist. No robustness to lose. |
| **Fix `cleanup-artifact-registry.sh`** | ~$8/mo | Weekly job reports success while skipping the largest repo — the "monitoring that monitors nothing" pattern. |
| **Cost anomaly detector + budget restructure** | +$0.08/yr | Catches both historical incidents on day one. |
| **Season guard in code, not scheduler surgery** | removes purge/restore cycle | The purge already killed weekly retraining once. A guard in versioned code cannot delete a scheduler. |
| **Batch reads generally** | bulk of the query storm | §8.6's per-entity check-then-write has a *real race* making the 3-strike circuit breaker unreliable — batching fixes the race. |
| **C4 — drop `tonight-players` from `TONIGHT_EXPORT_TYPES`** | ~$46/mo | Removes 9 redundant daily runs of a per-player loop with two live query bugs. (One product question: confirm 2 refreshes/day meets UI freshness.) |

### 3.2 Conflicted — cost bought with robustness

| Action | Cost gained | Robustness paid | Verdict |
|---|---|---|---|
| **`prediction-coordinator` → min=0** alone | $36.80/mo | Cold start on the stalled-batch path. Callers are schedulers (retry-friendly); nothing has a sub-minute SLA; cold-start latency is **unmeasured**. | Accept off-season. Before October either measure it or restore min=1 (already on the manifest). Low stakes. |
| **Scheduler consolidation 116 → ~10** | $12/mo | Fewer independent failure domains; a single dispatcher becomes a single point of failure; and consolidation is exactly the change that silently drops one job of 116 — the weekly-retrain failure mode again. | **$12 does not justify it standalone. Do it only inside Tier B**, where the targets are consolidated anyway. Mandatory mitigation: diff the dispatch table against the 204-job backup. |
| **93 services → ~5 (Tier B core)** | $150–250/mo + structural immunity | Loses per-message retry granularity, independent deploys, blast-radius isolation. One bad deploy stops the whole pipeline rather than one phase. | Two honest counterpoints: (a) today's isolation demonstrably failed to isolate — 87% failure *was* the isolated architecture; (b) checkpoint-restart is **designed, not proven**. `[PENDING: red-team on checkpoint-restart adequacy]` |
| **Retiring ~40 monitor CFs in Tier B** | $13–16/mo | The fleet is broken-not-expensive, but not uniformly worthless: **decay auto-disable has 8 real interventions**. Wholesale retirement risks throwing out the working 20% with the broken 80%. | Retire nothing until Decision 5's keep-list is named and running. |
| **Pausing cleanup/stall schedulers** | $4/mo | These are the self-healing layer. Fine while halted; load-bearing in-season. | Accept off-season; already on the restore manifest. |
| **memberradar / infinitecase-db deletion** | $22/mo | Deletion is forever, and `infinitecase-db` **already has zero backups** — the robustness problem predates the cost decision. | Export-then-delete for memberradar. For infinitecase-db the urgent action is a backup regardless of the eventual choice. |

### 3.3 The pattern worth recording

Almost everything in §3.1 shares one shape: **the money was being spent on failure** — failed runs, redundant recomputes, retries of the unretryable, warm containers guarding against a bug with a two-line real fix. Where cost-cutting means *deleting failure*, cost and robustness are the same project.

The genuine conflicts are confined to **consolidation** (trading isolation for simplicity) and **idle-capacity removal** where the idle capacity was doing implicit reliability work.

> **Triage every future cost proposal with one question: does this delete failure, or does it delete margin?**

---

## 4. Decision 4 — What we will deliberately NOT do

Recorded so they are not re-litigated. Each was investigated and refuted; citations in Wave 1 §9/§10 and Wave 2 §10.

| # | We will NOT… | Because | Reopen only if |
|---|---|---|---|
| N1 | Cut the model fleet for cost | $0.50–1.00/model/mo; whole-fleet inference is 0.13s. 10→3 saves $5–10/mo. | Fleet cost exceeds ~$20/mo measured, or a *modeling* reason emerges — never a billing reason. |
| N2 | Cut the 4 daily feature-store rebuilds | 12.7% of the morning edge-3 pool churns by afternoon; freezing changes **~70–130 picks/season** to save ~$3/mo. The real problem was 19.6 rebuilds/date from retry churn — fixed by C1. | Measured churn between rebuilds falls near zero across a full in-season month. |
| N3 | Treat GCS versioning as a cost problem | 1,695× amplification totals ~$0.01/mo. Apply the lifecycle rule as hygiene; expect no savings. | Never — the arithmetic cannot move enough. |
| N4 | Chase BigQuery storage or delete backup datasets | Storage is $0.09/mo; snapshots share bytes; deleting backups saves ~$0.00 and destroys the only rollback path. `__TABLES__.size_bytes` overstates billed storage. | Storage exceeds ~$5/mo (≈50× growth). |
| N5 | Throttle the owner's ad-hoc research | $3–5/mo, 7% of March BQ, refuted three times as a driver. Research produced every edge the product has. | Ad-hoc alone exceeds ~$50/mo sustained — and the response would be a quota conversation, not process friction. |
| N6 | Install budget-triggered billing disable | Destroys resources unrecoverably on a false positive, and it *will* false-positive on forecast noise. June was painful, not existential; this control's failure mode is existential. | A runaway an order of magnitude beyond June that the quota caps cannot bound. |
| N7 | Add materialized views | 82% of jobs already cache-hit; dominant patterns are latest-row-per-key which MVs cannot express; floor-padding is not MV-reducible. Rollup tables are the tool. | BQ pricing/feature changes. |
| N8 | Restructure the 180-column feature store | Worker reads 60 value columns; gate reads 7 materialized scalars. Narrow multiplies rows ×60; STRUCT recreates the array-vs-column bug just escaped. Fix schema evolution by generating DDL from `feature_contract.py`. | Never for cost. Only if a modeling need changes the access pattern. |
| N9 | Label BigQuery query jobs for attribution | 5,210 `QueryJobConfig` sites, no central wrapper — a large refactor to attribute $29/mo. `INFORMATION_SCHEMA.JOBS` already answers it. | A central BQ client wrapper exists anyway (Tier B would create one). |
| N10 | Stop (rather than delete or keep) Cloud SQL | Measured: stopping saves $0.43/mo — the idle IP reservation replaces 96% of the cost. Strictly worse than both alternatives. | GCP changes idle-IP billing. |
| N11 | Build an "off-season mode" of scheduler purges | The purge pattern silently killed weekly retraining. After Tier B a season guard is 3 lines of versioned code. | Never in the purge form. |
| N12 | Restore the 5 crash-looping dead scrapers | fantasypros/dailyfantasyfuel/dimers et al.: hundreds of runs/day, zero successes, zero readers. **Three are slated for Wave A restore — strike them from the manifest.** | A consumer for their data actually ships. |

---

## 5. Decision 5 — Minimum viable guardrail set

### The finding this responds to

Nothing was watching: a 335× overnight step ran 104 days ($1,120); a redelivery storm burned $225 with zero alerts; eight budgets exist and all are structurally incapable of early warning. Meanwhile the pipeline monitoring fleet is broken-not-expensive, and its one proven component — decay auto-disable, 8 real interventions — had its scheduler deleted.

### Options

- **G-0:** budgets only. Free, invoice-lagged.
- **G-1 (minimum viable):** restructured budgets + backtested cost anomaly detector + hard caps + proven-value monitor restorations. **~$1/mo.**
- **G-2:** G-1 + rebuild the full monitoring fleet pre-season. Weeks of work on components with unproven value.

### The G-1 set

| Guardrail | Cost | Note |
|---|---|---|
| Account ceiling ($700, actual + forecast → Slack) + `--last-period-amount` auto-seasonal companion + per-project budgets incl. the two unbudgeted projects | $0 | Wave 1 §10 has exact commands. **Kill the $40 always-firing budget** — alert fatigue by construction. |
| `cost_anomaly_detector.py` CF, 9 AM ET, D-2 lag | **~$0.08/yr** | Backtested: catches 2026-03-22 on day one and the June ramp 25 days early; quiet on steady state and on drops. |
| Freshness check on the detector itself, in `daily-health-check` | $0 | So it cannot die the weekly-retrain death. **A watchdog that can die silently is not a watchdog.** |
| BigQuery quota: 2 TiB/day project, 1 TiB/day per-user | $0 | Current headroom ~$1,250/day, per-user literally unlimited. Tradeoff stated plainly: a genuine runaway hard-fails queries until midnight PT — that is the point. |
| `max-instances` caps on the 11 uncapped services/CFs | $0 | A retry storm currently fans to 100 instances by default. |
| **Restore `decay-detection` scheduling** + verify `weekly-retrain-trigger` in Wave C | ~$0.10/mo | The one monitor with 8 proven interventions must not open the season dark. |
| Fix-or-delete triage of broken monitors (`nba-monitoring-alerts` queries, the no-source alert CFs, relocate `nba-grading-alerts` out of urcwest) | ~0 | **Deleting a monitor that cannot work is a robustness gain.** Download deployed source archives before deleting the no-source CFs — they are the only copies. |
| Review ritual: detector → `#nba-alerts` on anomaly only; weekly `/cost-check`; one line in monthly handoff | $0 | Silence = healthy. No new daily habit. |

### Not covered (accepted)

Slow ramps below daily thresholds (weekly `/cost-check` is the imperfect net); the two exportless billing accounts; anything on the invoice-only lag path.

### Recommendation

**G-1, this week, before any Tier B work begins — High confidence.** ~$1/mo against demonstrated multi-hundred-dollar failure modes. It must be in place *before* the rewrite: a consolidation project is exactly when new anomalies appear, and the detector is the rewrite's cheapest tripwire. G-2 rejected — most of the fleet's value is unproven and Tier B plans to absorb monitoring anyway.

---

## 6. Decision 6 — Risk acceptance

| # | Residual risk | Bound / mitigation | Accept? |
|---|---|---|---|
| R1 | **2026-27 does not resemble 2025-26.** Every forecast and Tier B's replay validation assume last season's shape. | ±20% priced into the rate; auto-seasonal budget absorbs drift. | **Yes.** Error of this kind costs tens/month. |
| R2 | **Single-operator system.** One person builds, validates, cuts over, operates. No second reviewer for the cutover diff. | The parallel review agents are a partial substitute; abort gates are the calendar's forcing function. | **Yes, conditionally** — the strongest standing argument for the shadow-all-season fallback. |
| R3 | **Unaudited surface.** Phase 4 internals, ~35 exporters, worker feature-array assembly were NOT audited. "No capability loss" cannot be stronger than audit coverage. | The 5-layer diff (L4 picks + L5 JSON exact) covers the exporter output even where the code was unread. | **Yes, with the L4/L5 layers mandatory.** Without them, no. |
| R4 | **Product-economics uncertainty dwarfs the infrastructure question.** The honest live curve is flat ~50–51%; the 60%+ figure rests on 175–203 graded picks, below the N≥300 sizing threshold. | Not an infra question. Resolves only with live volume (earliest honest read: mid-season 2026-27). | **Yes — explicitly.** This record optimizes infrastructure *conditional on* the product hypothesis; it does not adjudicate it. |
| R5 | **Undiagnosed phase4 latency regression** (3× cost since ~May 31) multiplies into the in-season bill and into Tier B's baseline. | Diagnose before restore Wave B. | **No — do not accept.** Time-box a diagnosis in August. |
| R6 | **Loop B's self-resolution is unexplained.** If it stopped because a backfill path was silently disabled, October restore re-arms a loop *and* may be missing a capability. | Confirm the mechanism before restoring gap-detector cadence; add the flat-cost signature alert. | **No — confirm first.** |
| R7 | **Two unexamined billing accounts.** `jett-prod` runs the exact config that cost InfiniteCase $321/mo; one account may be inside a free-trial window with a cliff coming. | 15 minutes in the Console Credits pages. | **No — 15-minute task**, do it this week. |
| R8 | **Cutover regression the oracle misses** — identical on replay, divergent on a live edge case. | Preseason live shadow; rollback window with old services intact; **the zero-tolerance gate fails closed** — a data-access regression surfaces as blocked players, not bad picks. | **Yes, within the rollback window.** The fail-closed property is the single best safety fact in this plan. |

---

## 7. What would change course

| Decision | Committed course | Change it if… |
|---|---|---|
| D1 scope | Tier A+C now; Tier B conditional | Red-team finds a capability loss without a design answer; or Tier C in-place fixes cut the rate below ~$200/mo, leaving robustness as the *sole* justification — at which point re-price Tier B against D1-c′ explicitly. |
| D2 timing | Build Aug–Sep, gated cutover, shadow fallback | Any gate slips ≥1 week → take the fallback immediately, no renegotiation. Conversely, if replay parity lands clean by Sep 1, consider cutting Phases 2–4 first and holding 5/6 for November. |
| D3 conflicts | Accept §3.2 trades as scoped | A preseason cold-start incident → restore min=1 for the season; checkpoint-restart flaky in shadow → per-message retry returns as a per-stage queue, or Tier B halts. |
| D4 not-do list | Closed as recorded | Only the per-item reopen conditions. Re-litigation requires new data, not new opinions. |
| D5 guardrails | G-1 | Detector false-positives >~1/week → raise thresholds before muting anything; a missed incident → add the missing dimension (it currently sees project×service×day only). |
| D6 risk | Accept R1–R4, R8; refuse R5–R7 | **R4 is the one that could invert everything:** if mid-season graded volume shows the BB edge is not real, infrastructure work pauses in favor of the product question. Spending engineering on cheaper delivery of a product that doesn't work is the one clearly wrong branch. |

---

## 8. Reversibility Matrix

**Reversible** = one command/commit undoes it. **Semi-reversible** = undoable with prepared artifacts. **Irreversible** = the listed backup step is *mandatory before execution*.

| Action | Class | Backup step / trap |
|---|---|---|
| min-instances=0 (coordinator, 3 orchestrators, 4 urcwest CFs) | Reversible | **Trap runs the other way:** `bin/deploy-service.sh:51-62`, Cloud Build `_MIN_INSTANCES: 1`, and `detect_config_drift.py` will silently re-revert to min=1. Fix all three in the same commit or it doesn't stick. |
| Eventarc `--retry` + ack-deadline raise | Reversible | Verify no poison-message loop (DLQ catches it). |
| Scheduler **pause** | Reversible | Paused jobs still bill $0.10/mo. |
| Scheduler **delete** / consolidation | Semi-reversible | 204-job backup JSON exists. Real risk is *silent omission* — diff restored set against backup. |
| Artifact Registry prune | **Irreversible** | Dry-run one week; verify keep-rules against the 4 digest-pinned services; ~40 backfill jobs pin `gcr.io` untagged → prune, never blanket-delete. |
| Delete dead AR repos | **Irreversible** | Confirm zero references in job/service specs first. |
| GCS lifecycle on noncurrent versions | **Irreversible** | No consumer reads noncurrent versions. |
| C1 retry-recycle fix | Reversible | Pure code. **`auto-retry-processor` is manual-deploy** — verify with `check-deployment-drift.sh`. |
| C2 partitioning (copy → verify → swap) | Semi-reversible | Keep the original ≥30 days. **Do NOT copy `partition_expiration_days=365`** (purges 5 seasons of training data). **Do NOT enable `require_partition_filter`** — training reads legitimately scan multi-season ranges. |
| C3 `source_file_path` fix | Reversible | Historical rows can stay `'unknown'`. |
| C4 drop `tonight-players` | Reversible | One line. |
| C6 collapse cache/shot-zone/JSON cols | Semi-reversible | Snapshot first; re-verify zero readers at execution time, not audit time. |
| Drop fully-dead tables | Semi-reversible | Snapshot before drop. |
| Delete zombie/no-source CFs | **Irreversible** | **Download deployed source archives first** — the only copies in existence. |
| Secret dedup | Semi-reversible | Grep deployments for both names; disable versions before destroying. |
| Kill `bluesky-nba-listener` | Reversible | Pause the scheduler; it has never persisted a row. |
| memberradar export + delete | **Irreversible** | `gcloud sql export` to GCS before delete. |
| `infinitecase-db` (any path) | **Irreversible today** | **Zero backups exist now.** Take one this week regardless of the eventual decision. |
| MLB retirement | Semi-reversible | Pause-don't-delete if the info-product data clock stays open. |
| **Tier B cutover** | Semi-reversible → **Irreversible at service deletion** | Old services + images + configs retained deployed-but-idle through the rollback window. **Deletion is the last step of the project, months after cutover — never part of it.** |
| BQ quota override | Reversible | Raisable in ~1 minute. |
| Budget restructure / detector | Reversible | Config + one CF. |

---

## 9. Assumptions Register

| # | Assumption | Depended on by | Early signal it is false |
|---|---|---|---|
| A1 | 2026-27 resembles 2025-26 | All forecasts; replay validation | Opening-month game-day cost outside $8.70–13.05 |
| A2 | $10.88/game-day holds ±20% | The $424 anchor; the $34–87 band | **The undiagnosed phase4 regression (R5) is already inside this assumption and pushes it high.** First 10 game-days' median vs anchor |
| A3 | The off-season window is ~10 weeks | Tier B GO; D2 gates | Restore Wave A at T-14 (≈Oct 7) → real build window ~8 weeks. Gate 1 is the tripwire by construction |
| A4 | "No capability loss" is achievable | Tier B | Wave 2's own caveat: all "after" figures are **designed, not measured**; ~35 exporters + Phase 4 internals unaudited |
| A5 | 12–20 days is honest | D2 | Single operator; the estimate covers build, not validation-and-cutover |
| A6 | The two loops stay dormant until fixed | Interim run rate; October restore | **Loop B is structurally armed today**; the retry recycle's stop is unexplained and re-armed once already |
| A7 | 60%+ BB hit rate is real | The "protect the product" weighting in D1/D2 | N=175–203 graded picks < N≥300; raw live curve flat ~50–51% |
| A8 | The billing picture is complete | The "not existential" framing | Two accounts have no export; possible free-trial cliff on `jett-prod` |
| A9 | Cloud Run Jobs stay ~36% cheaper and min-instance-free | Tier B's floor-immunity argument | GCP pricing changes |
| A10 | The 5-layer diff is a sufficient correctness oracle | D2 gates; R8 | It requires L4/L5 exactness; the single-layer feature-store version was already refuted |

---

## 10. Summary of Recommendations

| Decision | Recommendation | Confidence |
|---|---|---|
| Blocking defect | Recreate `prediction-request-prod` subscription with DLQ — this week | — |
| D1 scope | Tier A + Tier C unconditionally; **Tier B conditional GO on robustness grounds, not cash**; D1-c′ is a respectable stopping point | A+C: High · B: Medium |
| D2 timing | Build Aug–Sep behind binding gates; **shadow-all-season is the designated fallback**, ~90% of the value at ~5% of the risk | Medium-High |
| D3 conflicts | Take every §3.1 aligned item; accept §3.2 trades only as scoped | High |
| D4 not-do list | Closed as recorded; reopen only on listed conditions | High |
| D5 guardrails | G-1 (~$1/mo) **before** Tier B begins; restore decay-detection; fix-or-delete broken monitors | High |
| D6 risk | Accept R1–R4, R8; **refuse** R5 (diagnose phase4), R6 (explain Loop B), R7 (check the two billing accounts) | High |

---

### The one-paragraph version, for the future reader

*We fixed the config waste and the correctness bugs immediately because cost and robustness pointed the same way — the money was being spent on failure. We treated the big rewrite as a robustness project wearing a cost justification, priced its marginal cash honestly (~$1,500/yr over the cheaper tiers), gated it behind pre-committed abort criteria, and kept a fallback — shadow all season, cut over next summer — that we considered a success, not a defeat. We wrote down what we refused to do so nobody spends another week re-deriving that the model fleet costs $1/model and the feature-store rebuilds are worth 70–130 picks. And we accepted, in writing, that the biggest open question was never the infrastructure — it is whether the edge is real, and only the season can answer that.*

---

*Drafted 2026-07-21. No changes applied.*
