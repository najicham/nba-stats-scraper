# Working from a second machine (macOS)

Written 2026-09-13 for a week away from the primary WSL box. Everything here was checked
against the repo as it stands at that date; where something is an expectation rather than a
measurement it says so.

The short version: the repo is portable, GCP is reachable from anywhere, and the only real
friction is that **this codebase's shell scripts assume GNU coreutils**, which macOS does not
ship. §2 fixes that in one `brew install`.

---

## 1. Get the repo running

```bash
git clone git@github.com:najicham/nba-stats-scraper.git
cd nba-stats-scraper

python3 --version          # want 3.11 or 3.12 (CI runs 3.12; the WSL box runs 3.12.3)
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-test.txt        # pytest, pytest-timeout, pytest-benchmark, hypothesis…
```

On Apple Silicon, `xgboost` needs OpenMP at import time. If `import xgboost` raises
`Library not loaded: libomp.dylib`:

```bash
brew install libomp
```

`.venv/` is not in git and does not transfer — build it on the laptop.

### Verify the install

```bash
PYTHONPATH=. .venv/bin/python -c "import xgboost, catboost, pandas, google.cloud.bigquery; print('ok')"
```

---

## 2. Install GNU tools — do this before running anything in `bin/`

The scripts in `bin/` use `timeout`, `grep -P`, `sed -i` (GNU form), `date -d` and
`readlink -f`. macOS ships BSD versions of these, which either do not exist or take different
arguments. **`bin/check-deployment-drift.sh` — one of the four Quick Start commands — uses
`date -d` and will misbehave without this.**

```bash
brew install coreutils gnu-sed grep findutils
```

Then put the GNU versions first on PATH, in `~/.zshrc`:

```bash
export PATH="$(brew --prefix coreutils)/libexec/gnubin:$PATH"
export PATH="$(brew --prefix gnu-sed)/libexec/gnubin:$PATH"
export PATH="$(brew --prefix grep)/libexec/gnubin:$PATH"
export PATH="$(brew --prefix findutils)/libexec/gnubin:$PATH"
```

Check it took:

```bash
timeout 1 true && echo "timeout ok"
date -d "1 day ago" +%F && echo "date -d ok"
echo foo | grep -P 'f.o' && echo "grep -P ok"
```

If you would rather not touch PATH, the GNU binaries are also available prefixed with `g`
(`gtimeout`, `gsed`, `gdate`) — but then the repo's scripts still will not work, so prefer the
PATH route.

---

## 3. Authenticate to GCP

```bash
brew install --cask google-cloud-sdk      # or the official installer

gcloud auth login                          # for gcloud/bq CLI
gcloud auth application-default login      # for Python client libraries (ADC)
gcloud config set project nba-props-platform
gcloud config set run/region us-west2
```

### ⚠️ Always pass the project explicitly anyway

The default project on the primary machine has silently been wrong more than once (`jett-prod`,
`dmhr-platform`, `urcwest`). A wrong default is also what produced the long-standing myth that
`bq` "hangs" on this project — it was `bq`'s interactive setup prompt, fired because the default
project was wrong. Both tools are fast (~2s) when pointed at the right project.

```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false 'SELECT 1'
gcloud run services list --region=us-west2 --project=nba-props-platform --limit=3
```

Make it a habit: **`--project=` for gcloud, `--project_id=` for bq, every time.**

### What does NOT apply on macOS

The WSL-specific hang notes in memory (`run describe`, `iam`, `pubsub` mutations blocking on
response) are host-specific to that box. Do not pre-emptively wrap everything in `timeout`
because of them — but do keep a timeout on anything that could sit on bad hotel wifi.

---

## 4. Run the tests the way CI runs them

CI collects `tests/unit/` only, on Python 3.12, with no credentials. Reproduce that exactly —
it needs no network and takes about 2.5 minutes:

```bash
env CLOUDSDK_CONFIG=/nonexistent/gcloud GOOGLE_APPLICATION_CREDENTIALS=/nonexistent/adc.json \
  PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -q --tb=line \
  --ignore=tests/unit/scrapers/ --ignore=tests/unit/services/ --timeout=60
```

Expected as of 2026-09-13: **2,930 passed, 24 skipped, 0 failed.**

Pointing those two env vars at nonexistent paths is not a trick to make things fail — it is
the faithful CI emulation, and it also guarantees the suite is not quietly doing real work
against your account. (Until 2026-09-08 it was: see
`docs/09-handoff/2026-09-08-MEASUREMENT-CI-GATES-TOPOLOGY.md` §2.1.)

Pre-commit hooks (34 of them) run on commit; to run them by hand:

```bash
.venv/bin/pre-commit run --files <paths>
```

---

## 5. What is safe to do from a laptop, and what is not

### Safe — read-only, no blast radius

```bash
PYTHONPATH=. python bin/validation/validate_pubsub_topology.py   # dead publish targets
./bin/check-deployment-drift.sh --verbose                        # needs §2 GNU tools
/daily-steering  /validate-daily  /best-bets-config              # Claude Code skills
bq query --project_id=nba-props-platform --use_legacy_sql=false '…'
```

### Think first

- **`git push origin main` auto-deploys every changed service from HEAD.** There is no staging
  gate. A push that touches `shared/utils/**` fans out to roughly 25 Cloud Build triggers at
  once, and this project is at its regional Cloud Run quota ceiling — which is the exact
  condition under which builds go green while the revision never becomes ready. If you push,
  verify by reading the **serving** revision's `BUILD_COMMIT` (§7 of the 09-08 handoff), not by
  looking at `gcloud builds list`.
- **Never `--set-env-vars`.** It wipes every other variable. Always `--update-env-vars`.
- **Never trigger a Phase 6 `signal-best-bets` export for a historical date** — it deletes
  picks.
- **`ml/signals/` is under code freeze** until 100 graded 2026-27 picks exist. Bug fixes and
  observability are fine; anything that changes selection is not.

### Do not do these on hotel wifi at all

Retraining, backfills, and anything that starts a long BigQuery job you would need to babysit.
They are not dangerous, they are just bad to abandon halfway.

---

## 6. What is running while you are away

It is the off-season. NBA opener is **2026-10-20**; the first publishable pick is around
**2026-11-17**. The system is halted by design and publishes nothing.

**92 Cloud Scheduler jobs are ENABLED** (78 are paused). On a no-game day most of them do
real work over an empty slate and cost approximately nothing — one Phase-4 chain was measured
at 5.6 GB ≈ $0.035, and a no-game day at 0 bytes scanned. In-season the whole platform runs
≈$200–250/month, so a quiet week is well under that.

Things that will genuinely fire: `master-controller-hourly`, `execute-workflows` (hourly),
`gap-detector-30min`, `halt-state-writer-daily` (5 AM ET), `expected-outputs-planner-nightly`,
the `ml-feature-store-*` jobs, `bigquery-daily-backup`, and the monitoring/alerting set.

### What a real problem looks like

Almost nothing here is urgent before October. The two things worth a glance if Slack gets
noisy:

| signal | meaning |
|---|---|
| `#deployment-alerts` going red repeatedly | a build is genuinely failing — but note `deploy-monthly-retrain` is *permanently* red (it points at a directory deleted in the Task #35 cleanup). Red from that one is noise. |
| `halt-state-writer` stale | the halt-state alert is absence-based, so it fires when the 5 AM write stops happening. Check `nba_orchestration.halt_state` for today. |

```sql
-- is the system still writing its daily halt row?
SELECT effective_date, sport, halt_active, halt_reason
FROM `nba-props-platform.nba_orchestration.halt_state`
WHERE effective_date >= CURRENT_DATE() - 3
ORDER BY effective_date DESC;
```

An active halt row in the off-season is **correct** — `off_season` is the expected reason.

### Emergency levers, in case you need them

```bash
# publish through a halt (emergency only; logs ERROR, emits halt_gate_overridden)
gcloud run services update phase6-export --region=us-west2 \
  --update-env-vars=HALT_GATE_ENABLED=false        # NEVER --set-env-vars

# roll a service back
gcloud run services update-traffic <service> --region=us-west2 \
  --to-revisions=<known-good-revision>=100
```

---

## 7. Where to start reading

1. `docs/09-handoff/2026-09-08-MEASUREMENT-CI-GATES-TOPOLOGY.md` — the most recent session.
2. `docs/09-handoff/2026-09-07-NEXT-SESSION-MENU.md` — the candidate-work menu. Items C, A, D
   and E are done; B, F, G, H, I are open.
3. `CLAUDE.md` — the troubleshooting matrix is the highest-value part.
4. `docs/02-operations/runbooks/season-resume-2026-27.md` — what has to be true by Oct 20.

Two standing rules that have repeatedly proven right here, worth carrying to any machine:

- **A success report on this system is weak evidence.** Require a positive artifact — run the
  thing and read the data.
- **Absence of an error is not evidence of success.** `/process-date` returns 200 `{"stats":{}}`
  while writing nothing; `logger.info` is discarded in every Gen2 CF; a `_Default` sink
  exclusion drops `severity=INFO` for ~30 services; `emit_metric` fails open. Use
  `region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT` — it is immune to all four.
