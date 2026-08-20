# Runbook: The Morning Canary Set

**Purpose:** eight checks that answer two questions and only two — *is the machine alive?* and
*is it telling the truth?*

**What this deliberately is not:** a performance dashboard. Hit rate, pick counts, and edge
averages are **excluded on purpose**. Numbers that move with variance invite reacting to
variance, and reacting to variance is the documented cause of the 2025-26 collapse. Performance
questions belong to `/daily-steering` and the drawdown protocol; this list is about integrity.

**Design rule:** every check below guards a failure that has **already happened at least once**
in this system. Nothing is here speculatively. If a check has never caught anything and never
could, delete it — a canary set nobody trusts is a canary set nobody reads.

**Where it lives:** fold this into the top of `/daily-steering` as a single eight-row GREEN/RED
block. A separate dashboard will not get opened.

---

## The eight

### 1. Scheduler manifest matches reality

**Check:** every job with a RESTORE verdict in the scheduler manifest exists, is in the expected
state for today's date, and its schedule and timezone match the manifest. Any job with a SKIP
verdict does *not* exist.

**Why it earns its place:** `weekly-retrain-trigger` was deleted in a 94-job purge and the Cloud
Function is HTTP-only with no other invoker, so weekly retraining **fired never** — the root
cause of the 2025-26 collapse. Critically, the existing scheduler health check iterates over jobs
that *exist*, so a deleted job is structurally invisible to it. This is the single highest-value
check on the list: it detects the exact failure that already destroyed one season.

**Note:** `gcloud scheduler jobs list` has hung in some environments; use the Python client
(`scheduler_v1.CloudSchedulerClient.list_jobs`).

---

### 2. Every monitor has a recent heartbeat

**Check:** no monitor's heartbeat is older than 26 hours.

**Why:** the watchers go dark too. Canary schedulers have sat paused behind an unresolved image
fix; the drift alerter was paused; `decay-detection-daily` was deleted outright. A four-day total
outage in Aug 2026 was discovered **by accident**, not by alerting. A dashboard that is green
because nothing is checking is strictly worse than no dashboard.

**Implementation note:** this must be an *absence* alert — each monitor emits a heartbeat metric
at the end of every run, success or failure, and the alert fires when the metric stops arriving.
Absence alerting is the only kind that survives the death of its own emitter.

---

### 3. Expected outputs: zero overdue

**Check:** no `EXPECTED` row in `nba_orchestration.expected_outputs` is past its due time.

**Why:** this is the system's one canonical "did the data actually arrive" contract, and reusing
it beats re-deriving per-phase freshness checks. A play-by-play loader was broken **for months**
undetected before this existed.

---

### 4. Fleet is fresh and diverse

**Check:** newest enabled model ≤ 10 days old (in season), ≥ 3 models enabled, ≥ 1 non-LGBM.

**Why:** stale models do not fail visibly — they become *confidently wrong*: high edge, low hit
rate, which reads as good news. The age check catches retraining death regardless of cause
(missing scheduler, stale Cloud Function, governance deadlock) with one query. The diversity
floor catches the clone-collapse mode where the whole fleet becomes r ≥ 0.95 variants of one
model.

---

### 5. Effect assertions hold

**Check:** each entry in the effect-assertions list still passes.

**Why this is the most important structural check:** the system's signature failure is code that
runs, computes, and affects nothing. **Three separate instances were found in a single night** in
Aug 2026 — `book_count` was never set so a book-count scaling fix was dead for six weeks; the
health multipliers never applied because the row they read is written the day after it is needed;
the counterfactual evaluator counted rows instead of distinct picks. Each merged, passed tests,
deployed successfully, and did nothing.

The general mechanism: **every behavioral fix ships with a query proving it took effect**, checked
daily. Seed the list with:

| Assertion | Passes when |
|---|---|
| `book_count_coverage` | ≥ 80% of today's candidates have non-null `book_count` |
| `health_rows_present` | a `signal_health_daily` row exists for the date the exporter will query |
| `tracking_drives_nonzero` | `AVG(drives) > 0` for the latest `nba_tracking_stats` date |
| `cf_distinct_picks` | counterfactual N equals a `COUNT(DISTINCT ...)` recomputation |
| `bb_candidates_provenance` | previously-null provenance columns are > 90% populated |

"We think it deployed" is not done. "The data says it took effect" is done.

---

### 6. Halt coherence — silence is explained

**Check:** either picks were published, **or** all of: a halt-state row exists for today, the
regime context computed without exception, upstream predictions exist for today's slate, and
per-model candidates exist.

**Why:** October and November produce zero picks *by design*. That makes real breakage
unfalsifiable — if the coordinator dies, the feature store empties, or the halt check throws (a
missing-import bug in the halt path has happened), the symptom is identical to correct behavior.
This check is what makes designed silence trustworthy.

**Zero picks + full upstream + halt flag set** is green.
**Zero picks + empty upstream** is a page.

---

### 7. Grading closed the loop

**Check:** yesterday's graded count is ≥ 90% of gradable, and `filter_counterfactual_daily` plus
`model_performance_daily` are fresh.

**Why:** everything downstream starves silently without grading — retraining N, decay states,
counterfactual demotions, signal health. `signal_health_daily` has gone stale in production
before. If grading is behind, every number you might react to is a measurement artifact.

---

### 8. Regime and OVER exposure

**Check:** `|pred_bias|` 7d within band, published OVER share ≤ 40%, and edge-6+ OVER rolling hit
rate printed alongside the 38.9% prior-4-season baseline.

**Why:** the 2025-26 scoring-environment shift is the most likely repeat failure, and it *was*
detectable roughly four weeks after opening night via model bias (pred−actual 14d ≤ −2.0 against
a clean 5-season envelope of ±0.81). Printing the OVER band next to its historical baseline keeps
the known landmine visible in the place you look every morning, rather than in a script scheduled
for December.

**The correct response to an anomaly signal is alarm plus forced retrain — not an OVER-floor
change.** The floor stays static; see the drawdown protocol.

---

## Reading it

**All eight green** means the machine is alive and honest. It does **not** mean you are winning,
and it is not supposed to.

**Any red** is diagnosed before any selection-logic change. Per the drawdown protocol §3, the
first 72 hours of a losing stretch are integrity work only — and this list *is* that work.

---

*Created 2026-08-19 from the pre-season audit. Companion: `drawdown-protocol.md`. Each check
traces to a failure that already occurred; the evidence is in the Aug 2026 session findings and
`docs/09-handoff/`.*
