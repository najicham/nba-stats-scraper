# Fixture‑Capture Harness

This folder contains **`capture.py`**, a thin wrapper that:

1. Runs any scraper in **`group=capture`** mode  
2. Grabs the `/tmp/raw_<runId>*` and `/tmp/exp_<runId>.json` artefacts it wrote  
3. (Optionally gzips large files)  
4. Copies them into **`tests/samples/<scraper>/…`**  
   so they can be used as **“golden fixtures”** for pytest.

> **Why?**  
> Unit tests stay fast and deterministic, while integration tests can still
> pin a known‑good API response to disk.

---

## Quick‑Start

```bash
# Make sure env vars / .env are loaded
export ODDS_API_KEY=xxxxxxxxxxxxxxxx

# Single scraper capture
python tools/fixtures/capture.py oddsapi.odds_api_historical_event_odds \
       --eventId 242c77a8d5890e18bab91773ad32fcb5 \
       --date    2025-03-09T23:55:38Z \
       --debug

# Batch capture (BalldontLie matrix example)
python tools/fixtures/capture.py --all
````

### What just happened?

* `capture.py` generates a short **run‑id** (e.g. `799182f0`).
* It invokes the scraper via `python -m <module> --group capture --runId <id>`.

  * The scraper writes
    `/tmp/raw_<id>.<ext>` – **RAW**   (HTML, binary, or JSON)
    `/tmp/exp_<id>.json`  – **EXP**   (pretty‑printed decoded JSON)
* Any artefact larger than **200 kB** is gzipped.
* Files are copied to `tests/samples/<scraper>/`.
  Example path: `tests/samples/odds_api_historical_event_odds/exp_799182f0.json.gz`

Now **pytest** can read those fixtures without re‑hitting the live API:

```bash
pytest -v tests/scrapers/oddsapi
```

---

## Common CLI Flags

| Flag              | Added by capture.py                         | Passed through to scraper | Purpose                                              |
| ----------------- | ------------------------------------------- | ------------------------- | ---------------------------------------------------- |
| `--group capture` | ✅                                           | ✅                         | Activates scraper’s *capture* exporters (RAW & EXP). |
| `--runId <uuid>`  | ✅                                           | ✅                         | Correlates artefacts and logs for this run.          |
| `--debug`         | ✅ (only if you passed `--debug` to capture) | ✅                         | Makes `scraper_base` emit verbose logs.              |

Most scrapers also accept:

| Flag           | Default                     | Notes                                                  |
| -------------- | --------------------------- | ------------------------------------------------------ |
| `--sport`      | `basketball_nba`            | Season‑wide default we set in `set_additional_opts()`. |
| `--regions`    | `us`                        | Same.                                                  |
| `--markets`    | `player_points`             | Same.                                                  |
| `--bookmakers` | `draftkings,fanduel`        | Filter lines to the two biggest books.                 |
| `--api_key`     | not required – env fallback | Reads `ODDS_API_KEY` automatically.                    |

---

## Updating Scrapers to Work with *capture.py*

* **Expose** the `--runId` and `--debug` flags in the scraper’s CLI block
  (or simply call `add_common_args(parser)` if you use the shared helper).
* Ensure the scraper’s **exporter list** contains at least one entry with
  `"groups": ["capture"]` and file names that follow the
  `raw_%(run_id)s.*` / `exp_%(run_id)s.json` convention.

---

## Regenerating Fixtures

When API contracts change or you modify the scraper logic:

```bash
# Remove old fixtures (optional)
rm tests/samples/odds_api_historical_event_odds/*

# Re‑capture with fresh responses
python tools/fixtures/capture.py oddsapi.odds_api_historical_event_odds \
       --eventId ...  --date ... --debug
```

Commit the updated files so CI uses the new baseline.

---

## Troubleshooting

| Symptom                                        | Likely cause / fix                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **`No module named …`**                        | Wrong module path. Use `scrapers.oddsapi.<file_stem>` or rename the file.                                     |
| **`error: unrecognized arguments: --runId`**   | Scraper’s CLI parser doesn’t define `--runId`. Add it (or use `add_common_args`).                             |
| **`Invalid HTTP status code (no retry): 404`** | You hit the *current* odds endpoint with an event that’s in the past. Use the *historical* scraper instead.   |
| **No fixtures copied**                         | The scraper didn’t write `/tmp/raw_<id>*`. Double‑check that exporters under `group=capture` point to `/tmp`. |

