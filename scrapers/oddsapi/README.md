```markdown
# Odds‑API Scraper Suite (`scrapers/oddsapi/`)

This folder bundles five scrapers that wrap The‑Odds‑API v4 for NBA lines.
They all inherit the same `ScraperBase` and share season‑wide defaults:

```

sport      : basketball\_nba
regions    : us
markets    : player\_points
bookmakers : draftkings,fanduel,betmgm,pointsbetus,williamhill_us,betrivers
group      : dev                # overridden by --group capture / prod
api_key     : env ODDS\_API\_KEY   # or --api_key flag

````

---

## 1. Which file does what?

* **`odds_api_events.py`**  
  *GET /v4/sports/{sport}/events*  
  Current list of upcoming & in‑progress games (no odds).

* **`odds_api_historical_events.py`**  *(legacy name `oddsa_events_his.py`)*  
  *GET /v4/historical/sports/{sport}/events*  
  Same list, but at a historical **snapshot** time.

* **`odds_api_current_event_odds.py`**  *(legacy `oddsa_player_props.py`)*  
  *GET /v4/sports/{sport}/events/{eventId}/odds*  
  Live player‑prop odds for one game.

* **`odds_api_historical_event_odds.py`**  *(legacy `oddsa_player_props_his.py`)*  
  *GET /v4/historical/sports/{sport}/events/{eventId}/odds*  
  Historical snapshot of those odds.

* **`odds_api_team_players.py`**  *(legacy `oddsa_team_players.py`)*  
  *GET /v4/sports/{sport}/participants/{teamId}/players*  
  Undocumented roster endpoint (returns team players).

---

## 2. Running a scraper (local dev)

```bash
# Current odds for a live / next game
python -m scrapers.oddsapi.odds_api_current_event_odds \
       --event_id 6f0b6f8d8cc9c5bc6375cdee \
       --debug

# Historical odds snapshot for an old game
python -m scrapers.oddsapi.odds_api_historical_event_odds \
       --event_id 242c77a8d5890e18bab91773ad32fcb5 \
       --date    2025-03-09T23:55:38Z \
       --debug
````

Environment prep:

```bash
export ODDS_API_KEY=xxxxxxxxxxxxxxxx    # or store in .env
```

No need to pass `--sport --regions --markets --bookmakers` unless you want to override the defaults.

---

## 3. Capturing fixtures for pytest

We record RAW + prettified JSON with **`tools/fixtures/capture.py`**.

```bash
# Historical events list
python tools/fixtures/capture.py oddsa_events_his \
       --sport basketball_nba \
       --date 2025-03-10T00:00:00Z \
       --debug

# Historical player‑points snapshot
python tools/fixtures/capture.py oddsa_player_props_his \
       --event_id 242c77a8d5890e18bab91773ad32fcb5 \
       --date    2025-03-09T23:55:38Z \
       --debug
```

Capture adds:

* `--group capture` → scraper writes `/tmp/raw_<runId>*` and `/tmp/exp_<runId>.json`
* `--run_id <uuid>`  → filenames & logs stay in sync
* `--debug` (if you passed `--debug`) → verbose output

Files are auto‑copied to `tests/samples/<scraper>/`.
Pytest then runs with:

```bash
pytest -v tests/scrapers/oddsapi
```

---

## 4. Common CLI flags

* `--event_id`   (required for both *event‑odds* scrapers)
* `--date`      (required only for *historical* scrapers)
* `--regions`   default `us`
* `--markets`   default `player_points`
* `--bookmakers` default `draftkings,fanduel`
* `--api_key`    optional – falls back to `ODDS_API_KEY` env var
* `--group`     dev | capture | prod   (default `dev`)
* `--run_id`     optional; `capture.py` auto‑supplies one
* `--debug`     optional; bumps log level to DEBUG

---

## 5. FAQ / Troubleshooting

* **404 on current odds**
  – You’re querying a game that’s already finished. Use the historical scraper.

* **`No module named …`**
  – Check the file name vs. your import:
  `scrapers.oddsapi.odds_api_historical_event_odds` etc.

* **`unrecognized arguments: --run_id`**
  – Add `--run_id` / `--debug` to the scraper’s `argparse` block
  or call `add_common_args(parser)` from `scrapers.utils.cli_utils`.

* **Fixture copied but empty JSON**
  – Snapshot returned 204 or your `bookmakers` list didn’t post that market yet.

