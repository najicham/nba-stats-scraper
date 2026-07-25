# GCP Cost + Robustness Audit (2026-07) — Index

**Status as of 2026-07-24 (Session 7):** cost question settled; this-week actions closed except one owner-only item; August safety fixes captured as reviewed turnkey diffs. **Nothing further is blocking off-season.**

This folder is 8 numbered docs + handoffs. Read them in this order; don't re-derive.

## Bottom line

- **Cost solved itself.** The $1,019 June invoice was ~$550 one-time + already-fixed bugs. Marginal cost of a 15-game slate is **~$0.73** — cost is floor-dominated, in-season ~$200–250/mo. No further cost-hunting is warranted (refuted repeatedly; see 06 §6/§8).
- **The real yield is the safety layer** — fail-open gates, a silent prediction-write drop, a retry recycle, halt-application gaps. Those are `06-PLAN §4`, now turnkey in `08`.

## Current status

| Item | State |
|---|---|
| §3.1 prediction-request-prod sub (fan-out) | ✅ applied Session 6, verified |
| §3.2 infinitecase-db backups | ✅ applied Session 7, verified (`enabled=True`, online) |
| §3.3 Credits pages (2 billing accts) | ⏳ **OWNER-ONLY** — CLI can't see trial-credit state |
| §3.4 nba-bigquery-backups "$31/mo" | ❌ PHANTOM — no such line item |
| §4 August safety fixes | 📋 turnkey diffs in `08`, **reviewed** (2 regressions caught + fixed); nothing applied |
| §5 September monitors / §4.6 min-instances | 🗓️ scheduled (August is ~1 week out; §4.6 not worth pulling forward for ~$18) |

## Read order

| Doc | What |
|---|---|
| **`06-PLAN.md`** | The living plan. **Start here.** Baseline, this-week, August §4, explicit non-goals, sequence. |
| `07-PLAN-REVIEW-2026-07-24.md` | 10-lens solidity review + Session-7 addendum (real 10-agent re-run). |
| **`08-AUGUST-EXECUTION-PREP.md`** | Turnkey §4 diffs (exact before/after), caller audits, deploy paths, **Fable review corrections**. The apply reference. |
| `00-FULL-ANALYSIS.md` | Billing deep-dive (source data). |
| `01-WAVE-2-PIPELINE-EFFICIENCY.md` | Pipeline efficiency wave. |
| `02-DECISION-RECORD.md` | Tradeoffs (superseded by 06 where they conflict). |
| `04-ROBUSTNESS-ASSESSMENT.md` | Original safety wave. **Contains 2 KNOWN-WRONG findings** (grading-dedup flip, zero-tolerance severity) — see 06 §4.8/§5. |
| Handoffs | `docs/09-handoff/2026-07-{21,24}-SESSION-{5,6,7}-HANDOFF.md` (Session 7 is current). |

## Do-not-reopen (06 §6) — permanent

Tier B pipeline rewrite; most batch-read work; hash-skip on feature rebuilds; collapsing player_daily_cache/shot_zone; cutting the 4 daily rebuilds; cutting the fleet for cost; **flipping the grading dedup** (`prediction_accuracy_processor.py:573 ORDER BY created_at DESC` is correct).

## Gotchas surfaced by the audit (verify before acting)

- **`nba-props-platform-dev` project does not exist** — the §4.9 smoke test can't use `prediction-request-dev`; needs redesign (prod synthetic message + cleanup). `test_prediction_worker.sh`'s dev path is dead.
- **Docs-only pushes do NOT trigger Cloud Build** (verified: last build 07-05). Code commits do.
- **Turnkey ≠ correct:** the `08` diffs looked clean but a Fable adversarial pass found a poison-pill (§4.4) and a double-increment (§4.5). **Adversarially review before applying.**
- Env/CLI quirks are host-specific — see memory `wsl-gcloud-hang-and-subagents-broken-2026-07-23` (RETEST on a fresh host; don't inherit "subagents broken").

*Index created Session 7 (2026-07-24). Update the status table as items land.*
