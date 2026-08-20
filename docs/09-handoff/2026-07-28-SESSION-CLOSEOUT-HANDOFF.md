# Session Handoff — 2026-07-28 (entry point for next session)

**Branch:** `main`, clean. **System:** OFF-SEASON, halted; opener ~Oct 21 2026.

**This session did no code work.** It read the 2026-07-27 close-out, confirmed the audit is converged, and agreed to stop. This doc is the fresh entry point; the substance is unchanged from `2026-07-27-SESSION-7-CLOSEOUT-HANDOFF.md`, which remains the definitive, self-contained handoff. **Read that next, then the audit index `docs/08-projects/current/gcp-cost-audit-2026-07/README.md`.**

---

## TL;DR

Nothing to do off-season. The GCP cost + robustness audit is at a verified stopping point — everything applied is behavior-verified, everything deferred is turnkey. The only work left is **owner-only (item 3)** or **calendar-gated (the August §4 safety batch)**. Do NOT re-run the audit or reopen closed items.

---

## The one thing with a clock: Item 3 (OWNER-ONLY)

Console → Billing → **Credits** on `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720`. `jett-prod` runs the `minScale=1` + `cpu-throttling:false` config that cost $321/mo on InfiniteCase, on an account with no export/budget — possible **trial-credit cliff**. CLI cannot see trial-credit state, so this is a manual console check only you can do. It's the single item that could bite unexpectedly — glance at it before fully context-switching away.

---

## The real next task: August §4 safety batch (calendar-gated)

All §4 defects are **dormant while halted** (no predictions run), so the right window is August, with tests, near opener — NOT an off-season push (code commits auto-deploy on push; deploying unvalidatable changes months early only adds drift risk).

**Apply reference:** `docs/08-projects/current/gcp-cost-audit-2026-07/08-AUGUST-EXECUTION-PREP.md` — exact before/after diffs. **Read its top banner first: two first-pass diffs regressed and were corrected — do NOT apply the pre-correction versions.**

Order (full detail in the 2026-07-27 handoff §4):
1. 🟢 Trivial batch: §4.3, §4.10, §4.1 (corrected), §4.5 (corrected), §4.4 (corrected). Per-dir tests first (`-p no:cacheprovider`).
2. 🟠 §4.2 — premise stale; real residue is `base_exporter.py` query-error `except` (~`:394-399`) fail-opens; make it set `halt_active=True` for recent dates.
3. 🟡 §4.6 min-instances→0 ($79/mo) — its own coordinated commit; update ALL reversion vectors together.
4. 🟠 §4.7 100× shot-zone normalize (~1.5% blast radius).
5. 🟠 §4.9 pre-season fan-out smoke test — redesigned (dev project gone); publish ONE synthetic msg to `prediction-request-prod`, delete same-session, run AFTER §4.6.

---

## Done + behavior-verified (do NOT reopen)

- §3.1 `prediction-request-prod` push sub + DLQ — fan-out restored; dead-letters retained. **Sub exists — do NOT re-create.**
- §3.2 `infinitecase-db` automated backups — 3 SUCCESSFUL backups confirmed (07-25/26/27).
- §4.5 retry recycle — confirmed stopped.
- Plan reviewed (10 lenses + 2 Fable rounds) — 2 real diff regressions caught & fixed, 6 doc-staleness items fixed.
- §3.4 "$31/mo bigquery-backups" — PHANTOM, struck from forecast.

**Explicit do-NOTs:** don't re-run the audit; don't reopen the Tier B rewrite / §6 closures; don't flip the grading dedup (`prediction_accuracy_processor.py:573`); don't re-create the fan-out sub.

**Cost verdict:** solved itself. ~$0.73 marginal per slate; in-season ~$200–250/mo; floor-dominated. The audit's yield was the safety layer, not cost cuts.

---

## Parked — verify at October restore

- `nbac_play_by_play` + `nbac_injury_report` mint ~12 `failed_permanent`/day since 07-04 (`nba_orchestration.failed_processor_queue`). Trivial cost, likely benign off-season, but both are **core in-season sources** — must verify green at October restore.
- `OddsGameLinesProcessor` daily failures; ~99% `model_bb_candidates` provenance loss (writer fixed, verify at open); orphaned CFs; `expected_by` midnight-UTC anchor; GCS lifecycle. All in `06-PLAN §7`.
- **September quiet-window task:** read `ml/signals/aggregator.py` for defects (only scanned so far; it's where the betting edge lives). `06-PLAN §5`.

---

## Environment notes (host-specific — retest on a fresh host)

- Prior WSL host's "subagents/Fable broken" + "gcloud describe hangs" were **host-specific**; the Session-7 host had neither. Probe once before assuming. Memory: `wsl-gcloud-hang-and-subagents-broken-2026-07-23`.
- Still wrap mutations in `timeout … || echo "EXIT=$?"`; verify with a list call before retrying. Always `--project=nba-props-platform`.
- BigQuery: use repo `.venv/bin/python3` + `google.cloud.bigquery`. `ROWS`/`ROW` reserved. `ml_feature_store_v2` UNPARTITIONED.

---

## Where everything lives

| Doc | What |
|---|---|
| `2026-07-27-SESSION-7-CLOSEOUT-HANDOFF.md` | **Definitive, self-contained audit close-out. Read after this.** |
| `…/gcp-cost-audit-2026-07/README.md` | Audit index: status, read-order, do-not-reopen, gotchas. |
| `…/06-PLAN.md` | Living plan (§4 August, §6 closures, §7 parked, §8 uncertain, §9 sequence). |
| `…/08-AUGUST-EXECUTION-PREP.md` | Turnkey §4 diffs + Fable corrections. The apply reference. |
| Memory | `gcp-cost-audit-item1-applied-2026-07-23`, `wsl-gcloud-hang-and-subagents-broken-2026-07-23`. |

---

## Recommended first moves for the next session

1. If August and owner is ready: execute §4 step 1 (trivial batch) per the 2026-07-27 handoff §4 — apply the **corrected** diffs, per-dir tests, one commit, verify auto-deploy.
2. Otherwise: nothing off-season. Nudge the owner on item 3 (the only external-clock item).
3. Don't re-run the audit — converged. Don't re-create the fan-out sub. Don't flip the grading dedup.

*Handoff 2026-07-28. No code changes this session; audit remains at its verified stopping point.*
